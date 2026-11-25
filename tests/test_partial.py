"""Unknown devices lose only their own observations; interlocks still fail closed."""

import sqlite3
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from custom_components.adaptive_occupancy_simulator.archive import Archive
from custom_components.adaptive_occupancy_simulator.history import resample
from custom_components.adaptive_occupancy_simulator.model import Frame, HybridModel, PartialMask, constrain


def partial_history(config):
    return {
        **{e: [(0, "off")] for e in config["legacy_automations"]},
        **{e: [(0, "home")] for e in config["persons"]},
        config["alarm"]: [(0, "armed_home")],
        config["lights"][0]: [(0, "off"), (300, "on"), (900, "off")],
        config["lights"][1]: [(0, "unavailable")],
    }


def test_known_neighbors_retained_and_off_is_valid(config):
    rows = resample(partial_history(config), 0, 1200, config, lambda _: (0, 0, -10))
    assert all(not r.eligible and r.baseline_eligible and r.known_mask == 1 for r in rows)
    assert [r.mask for r in rows] == [0, 1, 1, 0]


@pytest.mark.parametrize(
    "entity,state",
    [
        ("automation.legacy", "unknown"),
        ("automation.legacy", "on"),
        ("person.resident_one", "unknown"),
        ("alarm_control_panel.test_alarm", "armed_away"),
    ],
)
def test_partial_history_never_bypasses_interlocks(config, entity, state):
    history = partial_history(config)
    # An unknown light is already present; a later guard change must not be hidden by it.
    history[entity] += [(100, state), (110, history[entity][0][1])]
    rows = resample(history, 0, 600, config, lambda _: (0, 0, -10))
    assert not rows[0].baseline_eligible
    assert rows[1].baseline_eligible


def test_short_light_outage_removes_only_affected_bit(config):
    history = partial_history(config)
    history[config["lights"][1]] = [(0, "on"), (100, "unavailable"), (110, "on")]
    rows = resample(history, 0, 600, config, lambda _: (0, 0, -10))
    assert rows[0].known_mask == 1 and rows[0].baseline_eligible
    assert rows[1].eligible and rows[1].known_mask == 3


def baseline_frames(days):
    return [
        Frame(day * 86400 + i * 300, int(i % 12 >= 6), i * 5, 0, -10, False, "light_unknown", 1, True)
        for day in range(days)
        for i in range(288)
    ]


def test_baseline_requires_per_target_days_and_never_commands_unknown(config):
    config = {**config, "minimum_days": 7}
    model = HybridModel(baseline_frames(7), config, ZoneInfo("UTC"))
    assert model.ready and not model.complete_ready
    targets = [Frame(10 * 86400 + i * 300, 0, i * 5, 0, -10) for i in range(288)]
    actions = constrain(model.generate(targets, 7), config["lights"], config, 7)
    assert actions and {a.entity_id for a in actions} == {config["lights"][0]}
    assert {a.source for a in actions} == {"baseline_partial"}
    younger = HybridModel(baseline_frames(2), config, ZoneInfo("UTC"))
    assert not younger.ready and younger.generate(targets, 1) == []
    assert any(mask is not None for _, mask, _ in younger.generate(targets, 1, preview=True))


def test_complete_evidence_takes_priority(config):
    frames = [replace(f, eligible=True, reason="", known_mask=3) for f in baseline_frames(7)]
    model = HybridModel(
        frames + [replace(f, ts=f.ts - 86400 * 30) for f in baseline_frames(7)], config, ZoneInfo("UTC")
    )
    target = [Frame(86400 * 10 + i * 300, 0, i * 5, 0, -10) for i in range(288)]
    assert model.complete_ready
    assert all(not isinstance(mask, PartialMask) for _, mask, _ in model.generate(target, 10))


def test_constraints_hold_unknown_state_without_inventing_off(config):
    trajectory = [(0, PartialMask(1, 1), "baseline_partial"), (900, PartialMask(2, 2), "baseline_partial")]
    actions = constrain(
        trajectory, config["lights"], {**config, "maximum_lights_on": 1, "jitter_seconds": 0}, 1
    )
    assert [(a.entity_id, a.on) for a in actions] == [
        (config["lights"][0], True),
        (config["lights"][1], False),
    ]
    assert not any(a.entity_id == config["lights"][0] and not a.on for a in actions)


def test_old_archive_upgrade_preserves_good_and_excluded_data(tmp_path):
    path = tmp_path / "old.sqlite"
    with sqlite3.connect(path) as db:
        db.execute(
            "CREATE TABLE frames(ts INTEGER PRIMARY KEY, mask INTEGER, minute INTEGER, weekend INTEGER, elevation REAL, eligible INTEGER, reason TEXT)"
        )
        db.executemany(
            "INSERT INTO frames VALUES(?,?,?,?,?,?,?)",
            [
                (0, 1, 0, 0, -10, 1, ""),
                (300, 1, 5, 0, -10, 0, "light_unknown"),
                (600, 1, 10, 0, -10, 0, "legacy_enabled"),
            ],
        )
    archive = Archive(path, {"lights": ["light.a", "light.b"]})
    archive.initialize()
    incoming = [Frame(t, 0, t // 60, 0, -10, False, "light_unknown", 2, True) for t in (0, 300, 600)]
    archive.write(incoming)
    rows = archive.read()
    assert rows[0].eligible and rows[0].mask == 1
    assert rows[1].known_mask == 2 and rows[1].baseline_eligible
    assert rows[2].reason == "legacy_enabled" and not rows[2].baseline_eligible
    archive.write([Frame(300, 0, 5, 0, -10, False, "sampling_gap", 0, False)], replace=True)
    archive.write(incoming)
    assert archive.read()[1].reason == "sampling_gap"
    archive.exclude(300, 900, "vacation")
    assert [r.ts for r in archive.read()] == [0]


async def test_live_partial_sampling_keeps_unknown_mask_and_rejects_guard_change(runtime, hass):
    for entity in runtime.config["persons"]:
        hass.states.async_set(entity, "home")
    hass.states.async_set(runtime.config["alarm"], "armed_home")
    hass.states.async_set(runtime.config["lights"][1], "unavailable")
    await hass.async_block_till_done()
    assert runtime.learning_status == "learning_partial"
    runtime.sample_timer()
    runtime._begin_sample()
    runtime.tainted = "light_unknown"
    stamp = runtime.sample.ts
    # Finish the sample explicitly; no model training or wall-clock scheduling needed.
    runtime.last_train_day = runtime.now().astimezone(runtime.tz).date().isoformat()
    await runtime._sample_tick(datetime.fromtimestamp(stamp, UTC) + timedelta(minutes=5))
    rows = await hass.async_add_executor_job(runtime.archive.read)
    assert rows[-1].baseline_eligible and rows[-1].known_mask == 1
    runtime.sample_timer()
    runtime._begin_sample()
    runtime.tainted = "light_unknown"
    hass.states.async_set("automation.legacy", "on")
    await hass.async_block_till_done()
    await runtime._sample_tick(datetime.fromtimestamp(runtime.sample.ts, UTC) + timedelta(minutes=5))
    rows = await hass.async_add_executor_job(runtime.archive.read)
    assert not rows[-1].baseline_eligible


async def test_learning_status_does_not_claim_partial_when_all_unknown(runtime, hass):
    for e in runtime.config["persons"]:
        hass.states.async_set(e, "home")
    hass.states.async_set(runtime.config["alarm"], "armed_home")
    for e in runtime.config["lights"]:
        hass.states.async_set(e, "unknown")
    assert runtime.learning_status == "light_unknown"
    hass.states.async_set(runtime.config["lights"][0], "off")
    assert runtime.learning_status == "learning_partial"
    hass.states.async_set("automation.legacy", "unknown")
    assert runtime.learning_status == "legacy_unknown"
