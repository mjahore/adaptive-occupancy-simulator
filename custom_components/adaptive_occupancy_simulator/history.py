"""Recorder adapter and conservative interval resampling."""

from datetime import UTC, datetime, timedelta
from functools import partial

from .const import STEP_SECONDS, occupancy_reason
from .model import Frame


def resample(history, start, end, config, feature, aos_entity=None):
    """Require known, eligible occupancy for EVERY instant in each interval.

    `history` is entity -> [(epoch_seconds, state)]. A missing start state is
    unknown, never presumed home/off. Any vacation/unknown interval taints the
    whole five-minute frame, including sub-five-minute vacations.
    """
    events = sorted((stamp, entity, state) for entity, values in history.items() for stamp, state in values)
    states = {}
    cursor = 0
    frames = []
    first = ((int(start) + STEP_SECONDS - 1) // STEP_SECONDS) * STEP_SECONDS

    def reason():
        why = occupancy_reason(
            states, config, learning=True, enabled=bool(aos_entity and states.get(aos_entity) == "on")
        )
        if not why and any(states.get(e) not in {"on", "off"} for e in config["lights"]):
            why = "light_unknown"
        return why

    for ts in range(first, int(end) - STEP_SECONDS + 1, STEP_SECONDS):
        while cursor < len(events) and events[cursor][0] <= ts:
            _, entity, state = events[cursor]
            states[entity] = state
            cursor += 1
        why = reason()
        mask = sum(1 << i for i, e in enumerate(config["lights"]) if states.get(e) == "on")
        while cursor < len(events) and events[cursor][0] < ts + STEP_SECONDS:
            _, entity, state = events[cursor]
            states[entity] = state
            why = why or reason()
            cursor += 1
        minute, weekend, elevation = feature(ts)
        frames.append(Frame(ts, mask, minute, weekend, elevation, not bool(why), why))
    return frames


async def import_recorder(hass, config, archive, feature, alive, aos_entity=None):
    """Read selected entity history one day per job on Recorder's executor."""
    from homeassistant.components.recorder.history import get_significant_states
    from homeassistant.helpers.recorder import get_instance

    end = datetime.now(UTC)
    start = end - timedelta(days=config["import_days"])
    entities = list(
        dict.fromkeys(
            config["lights"]
            + config["persons"]
            + [config["alarm"]]
            + config["legacy_automations"]
            + ([aos_entity] if aos_entity else [])
        )
    )
    imported = 0
    while start < end and alive():
        until = min(start + timedelta(days=1), end)
        # Align chunk boundaries so no five-minute interval falls into a gap.
        if until < end:
            until = datetime.fromtimestamp(int(until.timestamp()) // STEP_SECONDS * STEP_SECONDS, UTC)
        raw = await get_instance(hass).async_add_executor_job(
            partial(
                get_significant_states,
                hass,
                start,
                until,
                entities,
                include_start_time_state=True,
                significant_changes_only=False,
                minimal_response=False,
                no_attributes=True,
            )
        )
        if not alive():
            break
        history = {
            entity: [(s.last_updated.timestamp(), s.state) for s in states] for entity, states in raw.items()
        }
        frames = await hass.async_add_executor_job(
            resample, history, start.timestamp(), until.timestamp(), config, feature, aos_entity
        )
        if not alive():
            break
        await hass.async_add_executor_job(archive.write, frames)
        imported += len(frames)
        start = until
    return imported
