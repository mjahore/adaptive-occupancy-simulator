"""Use real HA state/event/service dispatch to test safety race boundaries."""

import asyncio
from types import SimpleNamespace

import pytest
from homeassistant.core import Context
from homeassistant.exceptions import HomeAssistantError

from custom_components.adaptive_occupancy_simulator.model import Action


def ready(runtime):
    runtime.enabled = True
    runtime.model = SimpleNamespace(ready=True, days=7)
    runtime.plan_day = runtime.now().astimezone(runtime.tz).date().isoformat()


@pytest.mark.parametrize("dry", [True, False])
async def test_dry_run_and_live_dispatch(runtime, hass, dry):
    ready(runtime)
    runtime.dry_run = dry
    calls = []
    hass.services.async_register("light", "turn_on", lambda call: calls.append(call))
    action = Action(int(runtime.now().timestamp()), "light.kitchen", True, "bootstrap")
    await runtime.dispatch(action, runtime.generation)
    assert len(calls) == (0 if dry else 1)
    assert runtime.log[0]["result"] == ("would_call" if dry else "called")


@pytest.mark.parametrize("person", ["person.resident_one", "person.resident_two"])
async def test_return_cancels_without_light_changes(runtime, hass, person):
    ready(runtime)
    runtime.dry_run = False
    calls = []
    hass.services.async_register("light", "turn_on", lambda call: calls.append(call))
    hass.services.async_register("light", "turn_off", lambda call: calls.append(call))
    runtime.plan = [Action(int(runtime.now().timestamp()) + 3600, "light.kitchen", True, "bootstrap")]
    runtime._arm_next()
    cancel = runtime.action_timer
    assert cancel is not None
    hass.states.async_set(person, "home")
    await hass.async_block_till_done()
    assert not runtime.enabled
    assert runtime.action_timer is None
    assert not calls
    assert hass.states.get("light.kitchen").state == "off"


async def test_return_during_persistence_blocks_dispatch(runtime, hass):
    ready(runtime)
    runtime.dry_run = False
    calls = []
    hass.services.async_register("light", "turn_on", lambda call: calls.append(call))
    runtime.plan = [Action(int(runtime.now().timestamp()), "light.kitchen", True, "bootstrap")]
    entered, resume = asyncio.Event(), asyncio.Event()

    async def save(_data):
        entered.set()
        await resume.wait()

    runtime.store.async_save = save
    token = runtime.generation
    task = asyncio.create_task(runtime._execute_due(token))
    await entered.wait()
    hass.states.async_set("person.resident_one", "home")
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    resume.set()
    await task
    assert calls == []


@pytest.mark.parametrize(
    "entity,state",
    [
        ("person.resident_one", "unknown"),
        ("person.resident_two", "unavailable"),
        ("alarm_control_panel.test_alarm", "triggered"),
        ("automation.legacy", "on"),
    ],
)
async def test_interlocks_and_stale_generation(runtime, hass, entity, state):
    ready(runtime)
    runtime.dry_run = False
    calls = []
    hass.services.async_register("light", "turn_on", lambda call: calls.append(call))
    token = runtime.generation
    hass.states.async_set(entity, state)
    await runtime.dispatch(Action(0, "light.kitchen", True, "bootstrap"), token)
    assert not calls


async def test_manual_override_and_own_context(runtime, hass):
    ready(runtime)
    context = Context()
    runtime.own_contexts.append(context.id)
    hass.states.async_set("light.kitchen", "on", context=context)
    await hass.async_block_till_done()
    assert "light.kitchen" not in runtime.overrides
    hass.states.async_set("light.kitchen", "off")
    await hass.async_block_till_done()
    assert runtime.overrides["light.kitchen"] > runtime.now().timestamp()
    calls = []
    runtime.dry_run = False
    hass.services.async_register("light", "turn_on", lambda call: calls.append(call))
    await runtime.dispatch(Action(0, "light.kitchen", True, "bootstrap"), runtime.generation)
    assert not calls
    assert runtime.log[0]["result"] == "skipped_override"


async def test_no_mode_change_while_enabled(runtime):
    runtime.enabled = True
    with pytest.raises(HomeAssistantError):
        await runtime.set_dry_run(False)


async def test_home_enable_rejected_and_stop_has_no_light_calls(runtime, hass):
    hass.states.async_set("person.resident_one", "home")
    with pytest.raises(HomeAssistantError):
        await runtime.set_enabled(True)
    assert not runtime.enabled
    await runtime.set_enabled(False)


async def test_consumed_and_missed_actions_not_replayed(runtime):
    ready(runtime)
    now = int(runtime.now().timestamp())
    runtime.plan = [
        Action(now - 500, "light.kitchen", True, "bootstrap"),
        Action(now + 300, "light.kitchen", False, "bootstrap"),
    ]
    runtime._advance_cursor()
    assert runtime.cursor == 1
    await runtime.store.async_save(runtime.snapshot())
    saved = await runtime.store.async_load()
    assert saved["cursor"] == 1
    assert "plan" not in saved  # cursor persistence does not rewrite the full plan


async def test_unload_cancels_and_removes_listeners(runtime):
    ready(runtime)
    runtime.plan = [Action(int(runtime.now().timestamp()) + 3600, "light.kitchen", True, "bootstrap")]
    runtime._arm_next()
    assert runtime.action_timer
    await runtime.shutdown()
    assert runtime.closed and runtime.action_timer is None
    assert not runtime.tasks


async def test_maximum_on_timer_without_remaining_plan(runtime, hass):
    ready(runtime)
    runtime.dry_run = False
    own = Context()
    runtime.own_contexts.append(own.id)
    hass.states.async_set("light.kitchen", "on", context=own)
    runtime.live_on_since["light.kitchen"] = runtime.now().timestamp() - 200 * 60
    calls = []
    hass.services.async_register("light", "turn_off", lambda call: calls.append(call))
    await runtime._execute_due(runtime.generation)
    assert len(calls) == 1
    assert calls[0].data["entity_id"] == "light.kitchen"
    assert "light.kitchen" not in runtime.live_on_since


async def test_cap_includes_commands_not_yet_acknowledged(runtime, hass):
    ready(runtime)
    runtime.dry_run = False
    runtime.config["maximum_lights_on"] = 1
    calls = []
    hass.services.async_register("light", "turn_on", lambda call: calls.append(call))
    for entity in runtime.config["lights"]:
        await runtime.dispatch(Action(0, entity, True, "bootstrap"), runtime.generation)
    assert len(calls) == 1
    assert runtime.log[0]["result"] == "skipped_limit"


async def test_service_error_suspends_future_execution(runtime, hass):
    ready(runtime)
    runtime.dry_run = False

    async def fail(call):
        raise HomeAssistantError("test device failure")

    hass.services.async_register("light", "turn_on", fail)
    runtime.plan = [Action(int(runtime.now().timestamp()), "light.kitchen", True, "bootstrap")]
    await runtime._execute_due(runtime.generation)
    assert runtime.status == "error"
    assert runtime.action_timer is None


async def test_persistent_restore_rechecks_presence(runtime, hass):
    from custom_components.adaptive_occupancy_simulator.runtime import Runtime

    ready(runtime)
    runtime.dry_run = False
    await runtime.shutdown()
    hass.states.async_set("person.resident_one", "home")
    restored = Runtime(hass, runtime.entry)
    await restored.initialize()
    assert not restored.enabled
    assert restored.action_timer is None
    await restored.shutdown()


async def test_failed_live_authorization_stays_dry(runtime, monkeypatch):
    async def fail_save(data):
        raise OSError("disk full")

    monkeypatch.setattr(runtime.store, "async_save", fail_save)
    with pytest.raises(OSError):
        await runtime.set_dry_run(False)
    assert runtime.dry_run
    monkeypatch.undo()


async def test_daily_plan_persists_separately_and_restores_cursor(runtime, hass):
    from custom_components.adaptive_occupancy_simulator.runtime import Runtime

    ready(runtime)
    runtime.plan_day = ""
    future = int(runtime.now().timestamp()) + 300
    runtime._make_plan = lambda day, seed: [Action(future, "light.kitchen", True, "bootstrap")]
    await runtime.generate_plan()
    plan = list(runtime.plan)
    await runtime.shutdown()
    restored = Runtime(hass, runtime.entry)
    await restored.initialize()
    assert restored.plan == plan
    assert restored.cursor == 0
    assert restored.enabled and restored.dry_run
    await restored.shutdown()
