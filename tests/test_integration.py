"""Full config-flow/platform lifecycle and actual SQLite Recorder adapter."""

import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from homeassistant import loader
from homeassistant.bootstrap import async_load_base_functionality
from homeassistant.helpers.recorder import async_initialize_recorder
from homeassistant.setup import async_setup_component

from custom_components.adaptive_occupancy_simulator.config_flow import schema
from custom_components.adaptive_occupancy_simulator.const import DOMAIN


@pytest.fixture
async def installed(hass, config):
    target = Path(hass.config.path("custom_components", DOMAIN))
    await hass.async_add_executor_job(shutil.copytree, Path("custom_components") / DOMAIN, target)
    loader.async_setup(hass)
    assert await async_load_base_functionality(hass)
    async_initialize_recorder(hass)
    for e in config["persons"]:
        hass.states.async_set(e, "home")
    hass.states.async_set(config["alarm"], "armed_home")
    hass.states.async_set("automation.legacy", "off")
    for e in config["lights"]:
        hass.states.async_set(e, "off")
    assert await async_setup_component(
        hass, "recorder", {"recorder": {"db_url": "sqlite:///" + hass.config.path("recorder.sqlite")}}
    )
    assert await async_setup_component(hass, DOMAIN, {})
    await hass.async_start()
    yield hass


async def create_entry(hass, config):
    flow = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    assert flow["type"] == "form" and flow["step_id"] == "user"
    for step in ("user", "learning", "model"):
        keys = [key.schema for key in schema(config, step).schema]
        flow = await hass.config_entries.flow.async_configure(
            flow["flow_id"], {key: config[key] for key in keys}
        )
    assert flow["type"] == "create_entry"
    await hass.async_block_till_done()
    return flow["result"]


async def test_full_setup_options_reload_and_unload(installed, config):
    hass = installed
    entry = await create_entry(hass, config)
    runtime = entry.runtime_data
    assert runtime.dry_run and not runtime.enabled
    assert hass.states.get("switch.adaptive_occupancy_simulator")
    assert hass.states.get("switch.adaptive_occupancy_simulator_dry_run").state == "on"
    assert hass.states.get("sensor.adaptive_occupancy_simulator_status").state == "disabled"
    assert hass.states.get("button.adaptive_occupancy_simulator_stop")
    second = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    assert second["type"] == "abort"
    options = await hass.config_entries.options.async_init(entry.entry_id)
    lighting_selector = next(
        value for key, value in options["data_schema"].schema.items() if key.schema == "lights"
    )
    assert set(lighting_selector.config["filter"][0]["domain"]) == {"light", "switch"}
    assert "switch.adaptive_occupancy_simulator" in lighting_selector.config["exclude_entities"]
    updated_lights = ["light.kitchen", "switch.table_lamp"]
    hass.states.async_set("switch.table_lamp", "off")
    for step in ("user", "learning", "model"):
        keys = [key.schema for key in schema(config, step).schema]
        data = {key: config[key] for key in keys}
        if step == "user":
            data["lights"] = updated_lights
        if step == "model":
            data["maximum_lights_on"] = 1
        options = await hass.config_entries.options.async_configure(options["flow_id"], data)
    assert options["type"] == "create_entry"
    await hass.async_block_till_done()
    assert entry.runtime_data is not runtime
    assert entry.runtime_data.config["maximum_lights_on"] == 1
    assert entry.runtime_data.config["lights"] == updated_lights
    assert entry.runtime_data.dry_run
    reloaded = entry.runtime_data
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert reloaded.closed


async def test_native_setup_with_only_lighting_switches(installed, config):
    hass = installed
    config = {**config, "lights": ["switch.table_lamp"]}
    hass.states.async_set("switch.table_lamp", "off")
    entry = await create_entry(hass, config)
    assert entry.runtime_data.config["lights"] == ["switch.table_lamp"]
    assert entry.runtime_data.dry_run and not entry.runtime_data.enabled
    assert await hass.config_entries.async_unload(entry.entry_id)


@pytest.mark.parametrize("entity_id", ["light.kitchen", "switch.table_lamp"])
async def test_real_recorder_query(installed, config, entity_id):
    from functools import partial

    from homeassistant.components.recorder.history import get_significant_states
    from homeassistant.helpers.recorder import get_instance

    hass = installed
    recorder = get_instance(hass)
    await recorder.async_block_till_done()
    await hass.async_add_executor_job(recorder.block_till_done)
    start = datetime.now(UTC) - timedelta(seconds=1)
    hass.states.async_set(entity_id, "on")
    await hass.async_block_till_done()
    from homeassistant.components.recorder.tasks import CommitTask

    recorder.queue_task(CommitTask())
    await recorder.async_block_till_done()
    raw = await recorder.async_add_executor_job(
        partial(
            get_significant_states,
            hass,
            start,
            datetime.now(UTC) + timedelta(seconds=1),
            [entity_id],
            include_start_time_state=True,
            significant_changes_only=False,
            minimal_response=False,
            no_attributes=True,
        )
    )
    assert raw.get(entity_id), raw
    assert raw[entity_id][-1].state == "on"
    assert raw[entity_id][-1].last_updated.tzinfo
