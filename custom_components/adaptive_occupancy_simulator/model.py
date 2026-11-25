"""Bounded, dependency-free joint bootstrap / sparse semi-Markov model.

All temporal arithmetic uses UTC seconds. Local civil time and solar elevation
are conditioning features only, so DST never creates duplicate action instants.
"""

import math
import random
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime

from .const import STEP_SECONDS


@dataclass(frozen=True, slots=True)
class Frame:
    ts: int
    mask: int
    minute: int
    weekend: int
    elevation: float
    eligible: bool = True
    reason: str = ""


@dataclass(frozen=True, slots=True)
class Action:
    ts: int
    entity_id: str
    on: bool
    source: str

    def as_dict(self):
        return asdict(self)


def phase(elevation):
    return 0 if elevation < -6 else 1 if elevation < 6 else 2


def clock_distance(a, b):
    d = abs(a - b)
    return min(d, 1440 - d)


class HybridModel:
    """Sparse observed joint states; never allocates a 2**N transition matrix."""

    def __init__(self, frames, config, timezone):
        self.config = config
        self.frames = sorted((f for f in frames if f.eligible), key=lambda f: f.ts)
        self.by_time = {f.ts: f for f in self.frames}
        self.days = len({datetime.fromtimestamp(f.ts, timezone).date() for f in self.frames})
        self.transitions = defaultdict(list)
        self.pooled = defaultdict(list)
        self.candidates = defaultdict(list)
        for frame in self.frames:
            self.candidates[(frame.weekend, phase(frame.elevation))].append(frame)
        # Only complete runs with an observed predecessor AND successor count.
        # Runs on either side of any excluded interval are censored.
        runs = []
        run = []
        for frame in self.frames:
            if run and (frame.ts != run[-1].ts + STEP_SECONDS or frame.mask != run[-1].mask):
                runs.append(run)
                run = []
            run.append(frame)
        if run:
            runs.append(run)
        for previous, current, following in zip(runs, runs[1:], runs[2:]):
            first, last = current[0], current[-1]
            if previous[-1].ts + STEP_SECONDS != first.ts or last.ts + STEP_SECONDS != following[0].ts:
                continue
            value = (following[0].mask, len(current))
            self.transitions[(first.weekend, phase(first.elevation), first.mask)].append(value)
            self.pooled[first.mask].append(value)

    @property
    def ready(self):
        return self.days >= self.config["minimum_days"]

    def diagnostics(self):
        return {
            "eligible_frames": len(self.frames),
            "eligible_days": self.days,
            "joint_states": len({f.mask for f in self.frames}),
            "transition_contexts": len(self.transitions),
            "observed_transitions": sum(map(len, self.transitions.values())),
            "ready": self.ready,
        }

    def generate(self, targets, seed):
        """Return a daily joint trajectory with empirical dwell distributions."""
        if not self.ready:
            return []
        rng = random.Random(seed)
        trajectory = []
        block = max(1, int(self.config["block_minutes"] / 5))
        index, state = 0, 0
        while index < len(targets):
            target = targets[index]
            length = min(block, len(targets) - index)
            candidates = []
            for frame in self.candidates[(target.weekend, phase(target.elevation))]:
                if clock_distance(frame.minute, target.minute) > 90:
                    continue
                if abs(frame.elevation - target.elevation) > 15:
                    continue
                # Entire multivariate block must be eligible and uninterrupted.
                if all(frame.ts + j * STEP_SECONDS in self.by_time for j in range(length)):
                    candidates.append(frame)
            if candidates and (
                rng.random() < self.config["bootstrap_probability"] or not self.pooled.get(state)
            ):
                weights = [
                    math.exp(
                        -clock_distance(f.minute, target.minute) / 60
                        - abs(f.elevation - target.elevation) / 10
                        - max(0, target.ts - f.ts) / (180 * 86400)
                    )
                    for f in candidates
                ]
                selected = rng.choices(candidates, weights=weights, k=1)[0]
                for j in range(length):
                    state = self.by_time[selected.ts + j * STEP_SECONDS].mask
                    trajectory.append((targets[index + j].ts, state, "bootstrap"))
                index += length
                continue
            outcomes = self.transitions.get((target.weekend, phase(target.elevation), state))
            source = "semi_markov"
            if not outcomes:
                outcomes = self.pooled.get(state)
                source = "semi_markov_pooled"
            if outcomes:
                next_state, dwell = rng.choice(outcomes)
                dwell = min(dwell, length)
                trajectory.extend((targets[index + j].ts, state, source) for j in range(dwell))
                state = next_state
                index += dwell
            else:
                # No invented independent coin flips when evidence is absent.
                trajectory.append((target.ts, None, "no_evidence"))
                index += 1
        return trajectory


def constrain(trajectory, lights, config, seed):
    """Convert joint states to actions with deterministic safety constraints.

    Unknown initial state emits an explicit desired state at the first supported
    frame. Runtime skips redundant commands. No end-of-session cleanup exists.
    """
    rng = random.Random(seed)
    previous = None
    last_change = {}
    on_since = {}
    actions = []
    min_dwell = config["minimum_dwell_minutes"] * 60
    max_on = config["maximum_on_minutes"] * 60
    cap = min(len(lights), config["maximum_lights_on"])
    for ts, mask, source in trajectory:
        if mask is None:
            continue
        desired = mask & ((1 << len(lights)) - 1)
        if previous is not None:
            for bit in range(len(lights)):
                flag = 1 << bit
                if ts - last_change.get(bit, -(10**12)) < min_dwell:
                    desired = (desired & ~flag) | (previous & flag)
                if bit in on_since and ts - on_since[bit] >= max_on:
                    desired &= ~flag
        # Keep existing lit rooms first, randomize ties reproducibly.
        active = [b for b in range(len(lights)) if desired & (1 << b)]
        rng.shuffle(active)
        active.sort(key=lambda b: not ((previous or 0) & (1 << b)))
        desired = sum(1 << b for b in active[:cap])
        jitter = rng.randint(0, int(config["jitter_seconds"]))
        # OFF precedes ON at each joint transition to enforce the concurrent cap.
        changed = [b for b in range(len(lights)) if previous is None or (previous ^ desired) & (1 << b)]
        changed.sort(key=lambda b: bool(desired & (1 << b)))
        for bit in changed:
            on = bool(desired & (1 << bit))
            actions.append(Action(ts + jitter, lights[bit], on, source))
            last_change[bit] = ts
            if on:
                on_since[bit] = ts
            else:
                on_since.pop(bit, None)
        previous = desired
    return actions
