"""Lighting relays share the same learning and execution safeguards as lights."""

from types import SimpleNamespace

import pytest
import voluptuous as vol
from homeassistant.core import Context
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er

from custom_components.adaptive_occupancy_simulator.config_flow import schema
from custom_components.adaptive_occupancy_simulator.const import DOMAIN, validate
from custom_components.adaptive_occupancy_simulator.entity import own_entities
from custom_components.adaptive_occupancy_simulator.history import resample
from custom_components.adaptive_occupancy_simulator.model import Action
from custom_components.adaptive_occupancy_simulator.runtime import Runtime


@pytest.fixture
def config(config):
    return {**config, "lights": ["light.kitchen", "switch.table_lamp"]}


def ready(runtime):
    runtime.enabled = True
    runtime.model = SimpleNamespace(ready=True, days=7)
    runtime.plan_day = runtime.now().astimezone(runtime.tz).date().isoformat()


@pytest.mark.parametrize("dry_run", [True, False])
@pytest.mark.parametrize("on", [True, False])
async def test_switch_dispatch_uses_correct_service(runtime, hass, dry_run, on):
    hass.states.async_set("switch.table_lamp", "off" if on else "on")
    await hass.async_block_till_done()
    ready(runtime)
    runtime.dry_run = dry_run
    calls = []
    for domain in ("light", "switch"):
        for service in ("turn_on", "turn_off"):
            hass.services.async_register(domain, service, lambda call: calls.append(call))
    await runtime.dispatch(Action(0, "switch.table_lamp", on, "bootstrap"), runtime.generation)
    if dry_run:
        assert calls == []
        assert runtime.log[0]["result"] == "would_call"
    else:
        assert len(calls) == 1
        assert (calls[0].domain, calls[0].service) == ("switch", "turn_on" if on else "turn_off")
        assert calls[0].data == {"entity_id": "switch.table_lamp"}


async def test_return_cancels_mixed_schedule_without_changing_targets(runtime, hass):
    hass.states.async_set("switch.table_lamp", "on")
    await hass.async_block_till_done()
    ready(runtime)
    runtime.dry_run = False
    calls = []
    for domain in ("light", "switch"):
        for service in ("turn_on", "turn_off"):
            hass.services.async_register(domain, service, lambda call: calls.append(call))
    later = int(runtime.now().timestamp()) + 3600
    runtime.plan = [
        Action(later, "light.kitchen", True, "bootstrap"),
        Action(later, "switch.table_lamp", False, "bootstrap"),
    ]
    runtime._arm_next()
    hass.states.async_set("person.resident_one", "home")
    await hass.async_block_till_done()
    await runtime.dispatch(runtime.plan[-1], runtime.generation)
    assert not runtime.enabled and runtime.action_timer is None
    assert calls == []
    assert hass.states.get("switch.table_lamp").state == "on"
    assert hass.states.get("light.kitchen").state == "off"


async def test_manual_switch_change_blocks_simulator(runtime, hass):
    ready(runtime)
    runtime.dry_run = False
    own = Context()
    runtime.own_contexts.append(own.id)
    hass.states.async_set("switch.table_lamp", "on", context=own)
    await hass.async_block_till_done()
    assert "switch.table_lamp" not in runtime.overrides
    hass.states.async_set("switch.table_lamp", "off")
    await hass.async_block_till_done()
    calls = []
    hass.services.async_register("switch", "turn_on", lambda call: calls.append(call))
    await runtime.dispatch(Action(0, "switch.table_lamp", True, "bootstrap"), runtime.generation)
    assert not calls
    assert runtime.log[0]["result"] == "skipped_override"


async def test_light_and_switch_share_cap(runtime, hass):
    hass.states.async_set("light.kitchen", "on")
    await hass.async_block_till_done()
    ready(runtime)
    runtime.dry_run = False
    runtime.config["maximum_lights_on"] = 1
    calls = []
    hass.services.async_register("switch", "turn_on", lambda call: calls.append(call))
    await runtime.dispatch(Action(0, "switch.table_lamp", True, "bootstrap"), runtime.generation)
    assert not calls
    assert runtime.log[0]["result"] == "skipped_limit"


async def test_switch_maximum_on_timer(runtime, hass):
    ready(runtime)
    runtime.dry_run = False
    own = Context()
    runtime.own_contexts.append(own.id)
    hass.states.async_set("switch.table_lamp", "on", context=own)
    await hass.async_block_till_done()
    runtime.live_on_since["switch.table_lamp"] = runtime.now().timestamp() - 200 * 60
    calls = []
    hass.services.async_register("switch", "turn_off", lambda call: calls.append(call))
    await runtime._execute_due(runtime.generation)
    assert len(calls) == 1
    assert calls[0].domain == "switch" and calls[0].service == "turn_off"
    assert "switch.table_lamp" not in runtime.live_on_since


def test_mixed_history_preserves_joint_states_and_unknown_exclusions(config):
    history = {
        "person.resident_one": [(0, "home")],
        "person.resident_two": [(0, "not_home")],
        config["alarm"]: [(0, "armed_home")],
        "automation.legacy": [(0, "off")],
        "light.kitchen": [(0, "off"), (600, "on")],
        "switch.table_lamp": [(0, "off"), (300, "on"), (700, "unavailable"), (710, "on"), (900, "off")],
    }
    rows = resample(history, 0, 1200, config, lambda _: (0, 0, -10))
    assert [row.mask for row in rows] == [0, 2, 3, 1]
    assert [row.eligible for row in rows] == [True, True, False, True]


@pytest.mark.parametrize("target", ["scene.evening", "script.lamp", "fan.bedroom", "lock.front", "switch."])
def test_unsupported_targets_are_rejected(config, target):
    with pytest.raises(ValueError):
        validate({**config, "lights": [target]})


async def test_renamed_aos_controls_cannot_be_targets(hass, config, runtime):
    registry = er.async_get(hass)
    own = registry.async_get_or_create("switch", DOMAIN, "self_test", suggested_object_id="innocent_name")
    assert own.entity_id == "switch.innocent_name"
    excluded = own_entities(hass)
    assert own.entity_id in excluded
    with pytest.raises(ValueError):
        Runtime(hass, SimpleNamespace(data={**config, "lights": [own.entity_id]}, options={}, entry_id="bad"))
    selection = next(
        v
        for k, v in schema(config, "user", excluded_entities=excluded).schema.items()
        if k.schema == "lights"
    )
    with pytest.raises(vol.Invalid):
        selection([own.entity_id])
    # The final dispatch gate also protects against stale or malformed plans.
    ready(runtime)
    runtime.config["lights"].append(own.entity_id)
    with pytest.raises(HomeAssistantError):
        await runtime.dispatch(Action(0, own.entity_id, False, "bootstrap"), runtime.generation)
