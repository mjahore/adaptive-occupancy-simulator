"""Real HA Core objects, temporary configuration and no physical devices."""

from types import SimpleNamespace

import pytest
from homeassistant import loader
from homeassistant.bootstrap import async_load_base_functionality
from homeassistant.config_entries import ConfigEntries
from homeassistant.core import HomeAssistant

from custom_components.adaptive_occupancy_simulator.const import settings
from custom_components.adaptive_occupancy_simulator.runtime import Runtime


@pytest.fixture
def config():
    return settings(
        {
            "persons": ["person.resident_one", "person.resident_two"],
            "alarm": "alarm_control_panel.test_alarm",
            "lights": ["light.kitchen", "light.living_room"],
            "legacy_automations": ["automation.legacy"],
            "minimum_days": 2,
        }
    )


@pytest.fixture
async def hass(tmp_path):
    instance = HomeAssistant(str(tmp_path))
    instance.config.time_zone = "America/New_York"
    instance.config.latitude = 40.7
    instance.config.longitude = -74.0
    instance.config_entries = ConfigEntries(instance, {})
    loader.async_setup(instance)
    assert await async_load_base_functionality(instance)
    yield instance
    await instance.async_stop(force=True)


@pytest.fixture
async def runtime(hass, config):
    entry = SimpleNamespace(data=config, options={}, entry_id="test_entry")
    for entity in config["persons"]:
        hass.states.async_set(entity, "not_home")
    hass.states.async_set(config["alarm"], "armed_away")
    for entity in config["legacy_automations"]:
        hass.states.async_set(entity, "off")
    for entity in config["lights"]:
        hass.states.async_set(entity, "off")
    runtime = Runtime(hass, entry)
    await runtime.initialize()
    yield runtime
    await runtime.shutdown()
