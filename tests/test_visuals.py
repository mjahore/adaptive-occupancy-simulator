"""Visualizations preserve missing data, time boundaries and runtime isolation."""

from copy import deepcopy
from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from homeassistant.exceptions import Unauthorized

from custom_components.adaptive_occupancy_simulator.frontend import websocket_dashboard
from custom_components.adaptive_occupancy_simulator.model import Action, Frame, HybridModel
from custom_components.adaptive_occupancy_simulator.visuals import (
    dashboard_data,
    day_chart,
    preview_chart,
    summarize,
    transition_matrix,
)


def test_heatmap_per_entity_denominators_and_censored_durations():
    frames = [
        Frame(0, 0, 0, 0, -10),
        Frame(300, 1, 5, 0, -10),
        Frame(600, 1, 10, 0, -10, False, "light_unknown", 1, True),
        Frame(900, 0, 15, 0, -10),
        Frame(1200, 3, 20, 0, -10, False, "legacy_enabled"),
    ]
    data = summarize(frames, ["light.a", "switch.b"], ZoneInfo("UTC"))
    assert data["frames"] == 4 and data["partial_frames"] == 1
    assert data["rows"][0]["on"]["all"][0] == 2
    assert data["rows"][0]["totals"]["all"][0] == 4
    assert data["rows"][1]["totals"]["all"][0] == 3
    assert data["rows"][0]["median_on_minutes"] == 10
    assert data["rows"][1]["totals"]["all"][1] == 0
    # A missing frame censors the on duration.
    assert (
        summarize(frames[:2] + frames[3:], ["light.a", "switch.b"], ZoneInfo("UTC"))["rows"][0][
            "median_on_minutes"
        ]
        is None
    )


def test_solar_day_bootstrap_and_minimum_support():
    frames = []
    for day in range(7):
        for i in range(6):
            frames.append(Frame(day * 86400 + i * 300, int(i < 3), i * 5, 0, -10 if i < 3 else 10))
    data = summarize(frames, ["light.a"], ZoneInfo("UTC"))["solar"][0]
    assert data["difference"] == 1 and data["interval"] == [1, 1] and data["days"] == 7
    assert summarize(frames[:-6], ["light.a"], ZoneInfo("UTC"))["solar"][0]["interval"] is None


@pytest.mark.parametrize("day,slots", [("2026-03-08", 276), ("2026-11-01", 300)])
async def test_charts_use_real_dst_day_lengths(runtime, day, slots):
    date = datetime.fromisoformat(day).date()
    p = preview_chart(runtime, None, date, 1)
    assert p["total_slots"] == slots and p["end"] - p["start"] == slots * 300
    frame = Frame(p["start"], 0, 0, 0, 0)
    assert summarize([frame], runtime.config["lights"], runtime.tz)["days"][0]["expected"] == slots


async def test_timeline_uses_entire_plan_and_clamps_runtime_timeout(runtime):
    day = runtime.now().astimezone(runtime.tz).date()
    base = day_chart(runtime, day, [], kind="saved")
    actions = [Action(base["start"] + i * 300, "light.kitchen", bool(i % 2), "bootstrap") for i in range(100)]
    actions.append(Action(base["end"] - 20, "light.living_room", True, "bootstrap"))
    chart = day_chart(runtime, day, actions, kind="saved")
    assert chart["events"] == 101 and len(chart["actions"]) == 101
    assert chart["rows"][1]["intervals"][0]["end"] == base["end"]
    open_on = day_chart(
        runtime, day, [Action(base["start"], "light.kitchen", True, "bootstrap")], kind="saved"
    )
    assert (
        open_on["rows"][0]["intervals"][0]["end"] == base["start"] + runtime.config["maximum_on_minutes"] * 60
    )


async def test_preview_never_changes_live_plan_or_services(runtime, hass):
    now = int(runtime.now().timestamp()) // 300 * 300
    frames = [
        Frame(now - day * 86400 + i * 300, int(i % 12 >= 6), i * 5, 0, -10)
        for day in range(1, 8)
        for i in range(288)
    ]
    runtime.model = HybridModel(frames, runtime.config, runtime.tz)
    runtime.enabled = True
    runtime.dry_run = False
    runtime.plan = [Action(now + 3600, "light.kitchen", True, "bootstrap")]
    before = deepcopy(runtime.snapshot())
    plan = deepcopy(runtime.plan)
    generation = runtime.generation
    calls = []
    hass.services.async_register("light", "turn_on", lambda c: calls.append(c))
    a = await dashboard_data(runtime, resample=True, solar_shift=60)
    b = await dashboard_data(runtime, resample=True, day_offset=1)
    assert a["seed"] != b["seed"]
    assert runtime.snapshot() == before and runtime.plan == plan and runtime.generation == generation
    assert not calls


async def test_visual_api_requires_admin(hass):
    conn = SimpleNamespace(user=SimpleNamespace(is_admin=False))
    with pytest.raises(Unauthorized):
        websocket_dashboard(hass, conn, {"id": 1, "type": "adaptive_occupancy_simulator/dashboard"})


def test_transition_matrix_uses_actual_counts_and_preserves_other_mass():
    model = SimpleNamespace(pooled={0: [(1, 2), (1, 4), (2, 6)], 1: [(0, 3)], 2: [(3, 2)]})
    m = transition_matrix(model, ["light.a", "switch.b"], limit=2)
    assert m["total"] == 5 and m["omitted_states"] == 2
    assert [s["mask"] for s in m["states"]] == [0, 1, None]
    assert m["rows"][0]["counts"] == [0, 2, 1]
    assert m["rows"][0]["probabilities"] == [0, 2 / 3, 1 / 3]
    assert m["rows"][0]["median_dwell_minutes"] == 20
    assert m["rows"][2]["counts"] == [0, 0, 1]
    assert all(sum(row["probabilities"]) == 1 for row in m["rows"])
    full = transition_matrix(model, ["light.a", "switch.b"])
    final = next(i for i, s in enumerate(full["states"]) if s["mask"] == 3)
    assert full["rows"][final]["probabilities"] == [None] * 4
    assert transition_matrix(None, ["light.a"])["rows"] == []


def test_partial_observations_do_not_invent_matrix_states(config):
    frames = [Frame(i * 300, i % 2, i * 5, 0, -10, False, "light_unknown", 1, True) for i in range(12)]
    model = HybridModel(frames, config, ZoneInfo("UTC"))
    assert transition_matrix(model, config["lights"])["total"] == 0


async def test_matrix_updates_before_readiness_without_retraining(runtime, hass):
    from datetime import timedelta

    start = int(runtime.now().timestamp()) // 300 * 300 - 3600
    frames = [Frame(start + i * 300, mask, i * 5, 0, -10) for i, mask in enumerate([0, 1, 1, 0])]
    runtime.model = HybridModel([], runtime.config, runtime.tz)
    assert not runtime.model.ready
    await hass.async_add_executor_job(runtime.archive.write, frames)
    first = await dashboard_data(runtime)
    assert first["transitions"]["total"] == 1
    await hass.async_add_executor_job(runtime.archive.write, [Frame(start + 1200, 2, 20, 0, -10)])
    now = runtime.now()
    runtime.now = lambda: now + timedelta(minutes=5)
    second = await dashboard_data(runtime)
    assert second["transitions"]["total"] == 2
    assert not runtime.model.ready and not runtime.model.pooled
