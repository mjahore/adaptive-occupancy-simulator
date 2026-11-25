"""Validate dashboard templates and migration behavior against HA schemas."""

import json
from pathlib import Path

import yaml
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.template import Template

from custom_components.adaptive_occupancy_simulator.const import VERSION


def test_repository_metadata():
    manifest = json.loads(Path("custom_components/adaptive_occupancy_simulator/manifest.json").read_text())
    assert manifest["config_flow"] and manifest["single_config_entry"]
    assert manifest["requirements"] == []
    assert manifest["version"] == VERSION
    assert len(list(Path("custom_components").glob("*/manifest.json"))) == 1
    assert json.loads(Path("hacs.json").read_text())["homeassistant"] == "2026.7.2"
    for path in Path("examples").glob("*.yaml"):
        data = yaml.safe_load(path.read_text())
        if "sequence" in data:
            cv.SCRIPT_SCHEMA(data["sequence"])


async def test_seven_dashboards_render_with_missing_and_populated_data(hass):
    from homeassistant.helpers import template

    template.async_setup(hass)
    dashboard = yaml.safe_load(Path("dashboards/aos-classic.yaml").read_text())
    assert len(dashboard["views"]) == 7
    assert len({v["path"] for v in dashboard["views"]}) == 7
    for populated in (False, True):
        if populated:
            prefix = "sensor.adaptive_occupancy_simulator_"
            hass.states.async_set(
                prefix + "status",
                "dry_run",
                {"persons": ["person.resident_one"], "lights": ["light.kitchen"]},
            )
            hass.states.async_set(
                prefix + "activity",
                "would_call",
                {
                    "recent": [
                        {
                            "time": "2026-11-25T15:00:00Z",
                            "result": "would_call",
                            "entity": "light.kitchen",
                            "action": "on",
                            "detail": "",
                        }
                    ],
                    "overrides": {"light.kitchen": 1800000000},
                },
            )
            hass.states.async_set(
                prefix + "schedule",
                "1",
                {
                    "preview": [
                        {"ts": 1800000000, "entity_id": "light.kitchen", "on": True, "source": "bootstrap"}
                    ]
                },
            )
            hass.states.async_set(
                prefix + "history",
                "10",
                {
                    "counts": {"": 5, "legacy_enabled": 5},
                    "exclusions": [
                        {"start": 1800000000, "end": 32503680000, "reason": "AOS enabled session"}
                    ],
                },
            )
            hass.states.async_set(prefix + "model", "7", {"ready": True, "joint_states": 4})
        for view in dashboard["views"]:
            for card in view["cards"]:
                assert not card["type"].startswith("custom:")
                if card["type"] == "markdown":
                    result = Template(card["content"], hass).async_render()
                    assert isinstance(result, str)


def test_example_scripts_only_toggle_simulation():
    on = yaml.safe_load(Path("examples/turn_on_away_mode.yaml").read_text())
    off = yaml.safe_load(Path("examples/turn_off_away_mode.yaml").read_text())
    assert len(on["sequence"]) == len(off["sequence"]) == 1
    assert on["sequence"][0]["action"] == "switch.turn_on"
    assert off["sequence"][0]["action"] == "switch.turn_off"
    assert on["sequence"][0]["target"]["entity_id"] == "switch.adaptive_occupancy_simulator"
    assert off["sequence"][0]["target"]["entity_id"] == "switch.adaptive_occupancy_simulator"
