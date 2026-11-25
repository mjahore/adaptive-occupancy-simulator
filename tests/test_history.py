"""No vacation/unknown gaps may be bridged by historical learning."""

from dataclasses import replace

import pytest

from custom_components.adaptive_occupancy_simulator.archive import Archive
from custom_components.adaptive_occupancy_simulator.const import occupancy_reason, validate
from custom_components.adaptive_occupancy_simulator.history import resample
from custom_components.adaptive_occupancy_simulator.model import Frame


def home_history(config):
    values = {entity: [(0, "off")] for entity in config["lights"] + config["legacy_automations"]}
    values.update(
        {
            "person.resident_one": [(0, "home")],
            "person.resident_two": [(0, "not_home")],
            config["alarm"]: [(0, "armed_home")],
        }
    )
    return values


def feature(ts):
    return (ts // 60) % 1440, 0, -10


@pytest.mark.parametrize(
    "entity,state,reason",
    [
        ("automation.legacy", "on", "legacy_enabled"),
        ("automation.legacy", "unavailable", "legacy_unknown"),
        ("person.resident_two", "unknown", "presence_unknown"),
        ("alarm_control_panel.test_alarm", "armed_away", "alarm_interlock"),
        ("light.kitchen", "unavailable", "light_unknown"),
    ],
)
def test_short_contamination_excludes_whole_frame(config, entity, state, reason):
    history = home_history(config)
    original = history[entity][0][1]
    history[entity] += [(100, state), (110, original)]
    rows = resample(history, 0, 900, config, feature)
    assert rows[0].reason == reason
    assert not rows[0].eligible
    assert rows[1].eligible


def test_missing_start_state_never_assumed_off(config):
    history = home_history(config)
    history["automation.legacy"] = [(400, "off")]
    rows = resample(history, 0, 900, config, feature)
    assert [r.eligible for r in rows] == [False, False, True]


def test_aos_dry_run_history_excluded(config):
    history = home_history(config)
    history["switch.aos"] = [(0, "on"), (300, "off")]
    rows = resample(history, 0, 900, config, feature, "switch.aos")
    assert rows[0].reason == "simulation_enabled"
    assert rows[1].eligible


def test_named_zone_away_and_unknown_fail_closed(config):
    states = {
        "person.resident_one": "work",
        "person.resident_two": "not_home",
        config["alarm"]: "armed_away",
        "automation.legacy": "off",
    }
    assert occupancy_reason(states, config) == ""
    states["person.resident_one"] = "unavailable"
    assert occupancy_reason(states, config) == "presence_unknown"


def test_invalid_alarm_mapping(config):
    for states in (["armed_home"], ["unknown"], ["triggered"], []):
        with pytest.raises(ValueError):
            validate({**config, "away_states": states})


def test_archive_exclusion_retention_and_identity(tmp_path):
    archive = Archive(tmp_path / "aos.sqlite", {"lights": ["light.a", "light.b"]})
    archive.initialize()
    frames = [Frame(i * 300, 1, i * 5, 0, 0) for i in range(4)]
    archive.write(frames)
    archive.write([replace(frames[0], mask=2)])
    assert archive.read()[0].mask == 1  # import cannot overwrite live provenance
    exclusion = archive.exclude(300, 900, "vacation")
    assert [r.ts for r in archive.read()] == [0, 900]
    archive.close_exclusion(exclusion, 600)
    assert [r.ts for r in archive.read()] == [0, 600, 900]
    archive.prune(600)
    assert archive.summary()["frames"] == 2
    changed = Archive(archive.path, {"lights": ["light.b", "light.a"]})
    changed.initialize()
    assert changed.read() == []


def test_crash_does_not_leave_permanent_open_session(tmp_path):
    archive = Archive(tmp_path / "aos.sqlite", ["light.a"])
    archive.initialize()
    lost = archive.exclude(0, 32503680000, "AOS enabled session")
    active = archive.exclude(300, 32503680000, "AOS enabled session")
    archive.close_abandoned_sessions(active, 600)
    exclusions = {e["id"]: e for e in archive.summary()["exclusions"]}
    assert exclusions[lost]["end"] == 600
    assert exclusions[active]["end"] == 32503680000


async def test_recorder_adapter_chunks_and_keeps_boundary_continuity(hass, config, tmp_path, monkeypatch):
    from datetime import UTC, datetime, timedelta
    from types import SimpleNamespace

    from homeassistant.components.recorder import history as ha_history
    from homeassistant.helpers import recorder as ha_recorder

    from custom_components.adaptive_occupancy_simulator.history import import_recorder

    archive = Archive(tmp_path / "import.sqlite", config["lights"])
    await hass.async_add_executor_job(archive.initialize)
    seed = datetime.now(UTC) - timedelta(days=3)
    states = {e: "off" for e in config["lights"] + config["legacy_automations"]}
    states.update(
        {"person.resident_one": "home", "person.resident_two": "home", config["alarm"]: "armed_home"}
    )
    calls = []

    def history(*args, **kwargs):
        calls.append((args, kwargs))
        return {e: [SimpleNamespace(last_updated=seed, state=s)] for e, s in states.items()}

    monkeypatch.setattr(ha_history, "get_significant_states", history)
    monkeypatch.setattr(
        ha_recorder,
        "get_instance",
        lambda _: SimpleNamespace(async_add_executor_job=hass.async_add_executor_job),
    )
    imported = await import_recorder(hass, {**config, "import_days": 2}, archive, feature, lambda: True)
    rows = await hass.async_add_executor_job(archive.read)
    assert imported == len(rows) and imported >= 574
    assert all(r.eligible for r in rows)
    assert all(b.ts - a.ts == 300 for a, b in zip(rows, rows[1:]))
    for args, kwargs in calls:
        assert args[2] - args[1] <= timedelta(days=1)
        assert kwargs["include_start_time_state"]
        assert not kwargs["significant_changes_only"]
        assert kwargs["no_attributes"]
