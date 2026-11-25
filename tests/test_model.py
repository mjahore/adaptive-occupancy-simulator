"""Statistical invariants and physical schedule limits."""

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest

from custom_components.adaptive_occupancy_simulator.model import Frame, HybridModel, constrain


def training_frames(days=7):
    start = int(datetime(2026, 10, 5, tzinfo=UTC).timestamp())
    return [
        Frame(start + day * 86400 + i * 300, 3 if (i // 6) % 2 else 0, i * 5, int(day % 7 >= 5), -10)
        for day in range(days)
        for i in range(288)
    ]


def test_bootstrap_preserves_joint_correlations_and_is_reproducible(config):
    config = {**config, "bootstrap_probability": 1, "maximum_lights_on": 2}
    model = HybridModel(training_frames(), config, ZoneInfo("UTC"))
    targets = [Frame(1800000000 + i * 300, 0, 18 * 60 + i * 5, 0, -10) for i in range(36)]
    plan = model.generate(targets, 42)
    assert plan == model.generate(targets, 42)
    assert {mask for _, mask, _ in plan} <= {0, 3}
    assert {source for _, _, source in plan} == {"bootstrap"}


def test_cold_start_never_invents_schedule(config):
    model = HybridModel(training_frames(1), config, ZoneInfo("UTC"))
    assert not model.ready
    assert model.generate(training_frames(1), 1) == []


def test_sparse_semi_markov_and_censored_gaps(config):
    model = HybridModel(training_frames(7), {**config, "bootstrap_probability": 0}, ZoneInfo("UTC"))
    targets = [Frame(1800000000 + i * 300, 0, 1000 + i * 5, 0, -10) for i in range(60)]
    plan = model.generate(targets, 8)
    assert any(source.startswith("semi_markov") for _, _, source in plan)
    assert {mask for _, mask, _ in plan} <= {0, 3}
    assert len(model.transitions) <= 6
    # An excluded hole must not create a transition from before to after it.
    fragmented = [Frame(0, 0, 0, 0, 0), Frame(300, 0, 5, 0, 0), Frame(900, 3, 15, 0, 0)]
    gap_model = HybridModel(fragmented, config, ZoneInfo("UTC"))
    assert not gap_model.transitions


def test_cap_and_maximum_on(config):
    config = {
        **config,
        "maximum_lights_on": 1,
        "maximum_on_minutes": 15,
        "minimum_dwell_minutes": 5,
        "jitter_seconds": 0,
    }
    trajectory = [(i * 300, 3, "bootstrap") for i in range(20)]
    actions = constrain(trajectory, config["lights"], config, 7)
    state, since = set(), {}
    for action in actions:
        if action.on:
            state.add(action.entity_id)
            since[action.entity_id] = action.ts
        else:
            if action.entity_id in since:
                assert action.ts - since.pop(action.entity_id) <= 900
            state.discard(action.entity_id)
        assert len(state) <= 1


@pytest.mark.parametrize("day,count", [("2026-03-08", 276), ("2026-11-01", 300)])
async def test_dst_generates_unique_utc_slots(runtime, day, count):
    observed = []

    class Capture:
        def generate(self, targets, seed):
            observed.extend(targets)
            return []

    runtime.model = Capture()
    runtime._make_plan(datetime.fromisoformat(day).date(), 1)
    assert len(observed) == count
    assert len({f.ts for f in observed}) == count
    assert all(b.ts - a.ts == 300 for a, b in zip(observed, observed[1:]))
