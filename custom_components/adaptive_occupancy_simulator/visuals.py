"""Read-only visual summaries and exploratory plans; no device services or writes."""

import asyncio
import random
from collections import Counter, defaultdict
from datetime import UTC, datetime, time, timedelta
from statistics import median

from astral.sun import elevation, sunrise, sunset
from homeassistant.helpers import entity_registry as er

from .const import DOMAIN, STEP_SECONDS, VERSION
from .model import Frame, constrain, observed_transitions


def transition_matrix(model, lights, limit=8, *, frames=None):
    """Bounded projection of the actual pooled semi-Markov transition counts."""
    if frames is not None:
        pooled = defaultdict(list)
        for first, target, dwell in observed_transitions(frames):
            pooled[first.mask].append((target, dwell))
    else:
        pooled = model.pooled if model else {}
    frequency = Counter()
    for source, outcomes in pooled.items():
        frequency[source] += len(outcomes)
        frequency.update(target for target, _ in outcomes)
    selected = sorted(frequency, key=lambda mask: (-frequency[mask], mask))[:limit]
    omitted = len(frequency) - len(selected)
    masks = selected + ([None] if omitted else [])
    indices = {mask: i for i, mask in enumerate(masks)}
    counts = [[0] * len(masks) for _ in masks]
    dwells = [[] for _ in masks]
    for source, outcomes in pooled.items():
        row = indices.get(source, len(selected))
        for target, dwell in outcomes:
            counts[row][indices.get(target, len(selected))] += 1
            dwells[row].append(dwell * STEP_SECONDS / 60)
    states = [
        {
            "mask": mask,
            "entities": [e for bit, e in enumerate(lights) if mask & (1 << bit)] if mask is not None else [],
        }
        for mask in masks
    ]
    rows = [
        {
            "counts": row,
            "total": sum(row),
            "probabilities": [n / sum(row) for n in row] if sum(row) else [None] * len(row),
            "median_dwell_minutes": median(dwells[i]) if dwells[i] else None,
        }
        for i, row in enumerate(counts)
    ]
    return {
        "states": states,
        "rows": rows,
        "total": sum(sum(row) for row in counts),
        "omitted_states": omitted,
    }


def summarize(frames, lights, tz):
    """Use per-target denominators: a neighbor's unknown state never means OFF."""
    frames = sorted((f for f in frames if f.eligible or f.baseline_eligible), key=lambda f: f.ts)
    full = (1 << len(lights)) - 1
    kinds = ("all", "weekday", "weekend")
    totals = {k: [[0] * 24 for _ in lights] for k in kinds}
    on = {k: [[0] * 24 for _ in lights] for k in kinds}
    coverage = defaultdict(int)
    solar_days = {}
    durations = [[] for _ in lights]
    starts = {}
    previous = None
    previous_known = 0
    for f in frames:
        known = full if f.eligible else (f.known_mask or 0)
        day = datetime.fromtimestamp(f.ts, tz).date().isoformat()
        coverage[day] += 1
        hour, kind = f.minute // 60, "weekend" if f.weekend else "weekday"
        solar = solar_days.setdefault(day, {"n": [[0, 0] for _ in lights], "on": [[0, 0] for _ in lights]})
        bucket = 0 if f.elevation < -6 else 1 if f.elevation > 6 else None
        contiguous = previous is not None and previous.ts + STEP_SECONDS == f.ts
        if not contiguous:
            starts.clear()
        for bit in range(len(lights)):
            if not known & (1 << bit):
                starts.pop(bit, None)
                continue
            lit = bool(f.mask & (1 << bit))
            for group in ("all", kind):
                totals[group][bit][hour] += 1
                on[group][bit][hour] += lit
            if bucket is not None:
                solar["n"][bit][bucket] += 1
                solar["on"][bit][bucket] += lit
            if lit:
                if contiguous and previous_known & (1 << bit) and not previous.mask & (1 << bit):
                    starts[bit] = f.ts
            elif bit in starts:
                durations[bit].append((f.ts - starts.pop(bit)) / 60)
        previous, previous_known = f, known
    solar_rows = []
    for bit, entity in enumerate(lights):
        paired = [d for d in solar_days.values() if min(d["n"][bit]) >= 3]
        rates = [(d["on"][bit][0] / d["n"][bit][0], d["on"][bit][1] / d["n"][bit][1]) for d in paired]
        contrast = [n - d for n, d in rates]
        interval = None
        if len(rates) >= 7:
            rng = random.Random(417 + bit)
            draws = sorted(sum(rng.choices(contrast, k=len(contrast))) / len(contrast) for _ in range(400))
            interval = [round(draws[9], 4), round(draws[389], 4)]
        solar_rows.append(
            {
                "entity": entity,
                "days": len(rates),
                "night": sum(n for n, _ in rates) / len(rates) if rates else None,
                "day": sum(d for _, d in rates) / len(rates) if rates else None,
                "difference": sum(contrast) / len(contrast) if contrast else None,
                "interval": interval,
            }
        )
    days = []
    for day, count in sorted(coverage.items()):
        date = datetime.fromisoformat(day).date()
        start = datetime.combine(date, time.min, tz).timestamp()
        end = datetime.combine(date + timedelta(days=1), time.min, tz).timestamp()
        days.append({"date": day, "samples": count, "expected": int((end - start) / STEP_SECONDS)})
    return {
        "frames": len(frames),
        "complete_frames": sum(f.eligible for f in frames),
        "partial_frames": sum(not f.eligible for f in frames),
        "days": days,
        "rows": [
            {
                "entity": entity,
                "on": {k: on[k][i] for k in kinds},
                "totals": {k: totals[k][i] for k in kinds},
                "median_on_minutes": median(durations[i]) if durations[i] else None,
                "complete_runs": len(durations[i]),
            }
            for i, entity in enumerate(lights)
        ],
        "solar": solar_rows,
    }


def day_chart(runtime, day, actions, *, kind, solar_shift=0):
    """Reconstruct desired ON intervals, bounded by the executor's maximum-on limit."""
    start = int(datetime.combine(day, time.min, runtime.tz).timestamp())
    end = int(datetime.combine(day + timedelta(days=1), time.min, runtime.tz).timestamp())
    ordered = sorted((a for a in actions if start <= a.ts < end), key=lambda a: a.ts)
    rows = []
    for entity in runtime.config["lights"]:
        intervals = []
        since = None
        source = None
        for action in (a for a in ordered if a.entity_id == entity):
            if action.on and since is None:
                since, source = action.ts, action.source
            elif not action.on and since is not None:
                intervals.append(
                    {
                        "start": since,
                        "end": min(action.ts, since + runtime.config["maximum_on_minutes"] * 60),
                        "source": source,
                    }
                )
                since = None
        if since is not None:
            intervals.append(
                {
                    "start": since,
                    "end": min(end, since + runtime.config["maximum_on_minutes"] * 60),
                    "source": source,
                }
            )
        rows.append({"entity": entity, "intervals": intervals})
    solar = {}
    for name, fn in (("sunrise", sunrise), ("sunset", sunset)):
        try:
            solar[name] = (
                int(fn(runtime.observer, date=day, tzinfo=runtime.tz).timestamp()) + solar_shift * 60
            )
        except ValueError:
            solar[name] = None
    return {
        "day": day.isoformat(),
        "start": start,
        "end": end,
        "kind": kind,
        **solar,
        "rows": rows,
        "events": len(ordered),
        "lit_targets": sum(bool(r["intervals"]) for r in rows),
        "actions": [a.as_dict() for a in ordered],
    }


def preview_chart(runtime, model, day, seed, solar_shift=0):
    """Use the real model with a private seed; never replace runtime.plan or its cursor."""
    start = int(datetime.combine(day, time.min, runtime.tz).timestamp())
    end = int(datetime.combine(day + timedelta(days=1), time.min, runtime.tz).timestamp())
    targets = []
    for stamp in range(start, end, STEP_SECONDS):
        minute, weekend, solar = runtime.feature(stamp)
        if solar_shift:
            instant = datetime.fromtimestamp(stamp, UTC) - timedelta(minutes=solar_shift)
            solar = round(elevation(runtime.observer, instant), 2)
        targets.append(Frame(stamp, 0, minute, weekend, solar))
    trajectory = model.generate(targets, seed, preview=True) if model else []
    actions = constrain(trajectory, runtime.config["lights"], runtime.config, seed)
    result = day_chart(runtime, day, actions, kind="exploration", solar_shift=solar_shift)
    result["seed"] = seed
    result["solar_shift"] = solar_shift
    result["supported_slots"] = sum(mask is not None for _, mask, _ in trajectory)
    result["total_slots"] = len(targets)
    return result


async def dashboard_data(runtime, *, resample=False, day_offset=0, solar_shift=0):
    """One bounded executor job at a time per household; cached historical aggregates."""
    if not hasattr(runtime, "visual_lock"):
        runtime.visual_lock = asyncio.Lock()
        runtime.visual_cache = None
    async with runtime.visual_lock:
        model = runtime.model
        now = runtime.now()
        today = now.astimezone(runtime.tz).date()
        if resample:
            # Only the result of this request changes, even when live simulation is enabled.
            return await runtime.hass.async_add_executor_job(
                preview_chart,
                runtime,
                model,
                today + timedelta(days=day_offset),
                random.SystemRandom().randrange(2**53),
                solar_shift,
            )
        cache_key = (id(model), runtime.seed, today.isoformat(), int(now.timestamp()) // 300)
        if runtime.visual_cache is None or runtime.visual_cache[0] != cache_key:

            def calculate():
                frames = runtime.archive.read()
                return (
                    summarize(frames, runtime.config["lights"], runtime.tz),
                    preview_chart(runtime, model, today + timedelta(days=1), runtime.seed + 1),
                    transition_matrix(model, runtime.config["lights"], frames=frames),
                )

            history, tomorrow, matrix = await runtime.hass.async_add_executor_job(calculate)
            runtime.visual_cache = (cache_key, history, tomorrow, matrix)
        _, history, tomorrow, matrix = runtime.visual_cache
        registry = er.async_get(runtime.hass)
        controls = {}
        for key, domain in (
            ("enabled", "switch"),
            ("dry_run", "switch"),
            ("stop", "button"),
            ("import_history", "button"),
            ("retrain", "button"),
            ("regenerate", "button"),
            ("clear_overrides", "button"),
        ):
            controls[key] = registry.async_get_entity_id(domain, DOMAIN, f"{runtime.entry.entry_id}_{key}")

        def target(entity):
            state = runtime.hass.states.get(entity)
            return {
                "id": entity,
                "name": state.name if state else entity,
                "state": state.state if state else "missing",
            }

        plan = runtime.plan if runtime.plan_day == today.isoformat() else []
        return {
            "version": VERSION,
            "timezone": str(runtime.tz),
            "now": int(now.timestamp()),
            "status": runtime.status,
            "enabled": runtime.enabled,
            "dry_run": runtime.dry_run,
            "error": runtime.error,
            "busy": runtime.busy,
            "ready": bool(model and model.ready),
            "model": model.diagnostics() if model else {},
            "baseline_days": {e: len(days) for e, days in zip(runtime.config["lights"], model.target_days)}
            if model
            else {},
            "minimum_days": runtime.config["minimum_days"],
            "learning_reason": runtime._learning_reason(),
            "learning_status": runtime.learning_status,
            "entities": [target(e) for e in runtime.config["lights"]],
            "persons": [target(e) for e in runtime.config["persons"]],
            "alarm": target(runtime.config["alarm"]),
            "legacy": [target(e) for e in runtime.config["legacy_automations"]],
            "unknown_targets": [
                e for e in runtime.config["lights"] if runtime.states().get(e) not in {"on", "off"}
            ],
            "controls": controls,
            "settings": runtime.config,
            "import_report": runtime.import_report,
            "schedule": day_chart(runtime, today, plan, kind="saved"),
            "tomorrow": tomorrow,
            "history": history,
            "transitions": matrix,
            "exclusions": runtime.summary.get("exclusions", []),
            "reasons": runtime.summary.get("counts", {}),
            "activity": list(runtime.log),
            "overrides": runtime.overrides.copy(),
        }
