# Architecture and statistical model

AOS separates historical eligibility, statistical planning and physical execution. A plan can exist while simulation is disabled. Only the execution layer can call lights, and it rechecks the current household state immediately before dispatch.

Lighting targets are `light.*` and `switch.*` entities with on/off states. They share the existing ordered `lights` configuration key and joint bit mask, so existing light-only configurations need no data migration. The executor checks the allowed domain and rejects AOS's own registry entries before calling that domain's `turn_on` or `turn_off` action. The same learning, availability, override and limit checks apply to both types.

## Historical eligibility

The Recorder adapter calls `get_significant_states` for selected entities with start-state inclusion, all state changes, uncompressed output and no attributes. Calls execute in Recorder's own database executor, in one-day chunks. The adapter never opens Recorder's SQLite file or depends on its SQL tables.

For each five-minute UTC interval, a chronological sweep maintains the selected entities' states. A complete joint frame is usable only when at least one person is home, every person is known, the alarm permits learning, every legacy sentinel is off, all lights have known on/off state, and any known AOS enable switch is off. Any occupancy, alarm, legacy or AOS-session contamination rejects the whole interval. A light becoming unknown removes that light from the partial-observation mask for the entire interval, while known neighbors remain usable. Missing light start states withhold that device until its state is known; missing guard states still reject the whole interval.

Each stored frame contains UTC timestamp, joint-light bit mask, local minute, weekday/weekend, solar elevation, eligibility, rejection reason, a per-device known mask and partial-baseline eligibility. The archive also tracks live/import/legacy provenance. AOS sessions and manual exclusions form a second interval filter. Local sampling taints intervals on interlock changes and writes a startup-gap rejection; it never bridges a restart with fabricated occupancy. Live observations take precedence over later imports.

AOS's separate SQLite archive uses parameterized transactions on HA's general executor. At 365 days, five-minute sampling produces at most about 105,120 rows, independent of light count. Up to 48 lights fit in one integer mask. The archive is pruned during daily training. No neural libraries or dense state matrix are used.

## Joint block bootstrap

Planning runs over a local calendar day expressed as increasing UTC instants. This yields 276 five-minute slots on the spring DST transition and 300 on the autumn transition, with no duplicated UTC times.

For each target block, donor starts must match weekday/weekend and solar phase (night below −6°, twilight −6° to 6°, day above 6°), be within 90 civil minutes and 15° solar elevation, and have a complete contiguous eligible block. An excluded or missing frame breaks continuity.

Eligible donors receive weights proportional to:

`exp(−civil_minute_distance / 60 − solar_elevation_difference / 10 − age_seconds / (180 × 86400))`

The whole sequence of joint room masks is copied. Rooms are not sampled independently, preserving empirical within-block overlap and transitions. One seeded random generator controls sampling and another deterministic seeded pass applies constraints. Solar elevation is calculated with Astral from HA's latitude, longitude and elevation; it does not require historical `sun.sun` records.

## Partial-history provisional baseline

Qualified partial observations share the same occupancy, alarm, legacy and AOS-session gates as complete observations. For each target the model counts local dates with known on/off evidence. A provisional plan can command only targets reaching the configured minimum (default seven dates); the read-only explorer lowers this to two dates without authorizing execution. Counts do not imply full-day coverage.

The baseline copies contiguous partial joint blocks using the same time/day-type/solar matching and age weights. Each sampled slot carries a values mask and a known mask. Unknown bits produce no commands; they never become off. Previously planned on states are conservatively retained when checking concurrent caps through unknown slots. The executor's maximum-on timer remains independent and subject to all interlocks.

Once enough complete joint dates exist, the full bootstrap/semi-Markov model takes priority; partial blocks fill only otherwise unsupported slots. Daily retraining refines the evidence without automatically rerolling an existing plan. The original `eligible_frames` and `eligible_days` diagnostics count complete joint frames; `partial_frames`, `baseline_ready_targets` and per-entity dates explain additional evidence. `learning_partial` means current known devices can learn.

On upgrade, SQLite adds the known mask, baseline eligibility and provenance columns without discarding existing complete observations or exclusions. A fresh Recorder scan can enrich old `light_unknown` rows and update prior imported rows; it cannot replace live rows or legacy rows marked complete/unsafe. No data is recovered after Recorder has purged it.

## Sparse semi-Markov fallback

Training identifies contiguous runs of each observed joint state. Only runs with both observed predecessor and successor are used: runs at archive boundaries and gaps are censored. The model stores observed `(next_joint_state, dwell_samples)` pairs by `(weekday/weekend, solar_phase, current_joint_state)`, with a pooled table per current state.

When the mixture selects the semi-Markov component, it samples an empirical successor and duration. Exact-context evidence is preferred; pooled evidence is used if needed. Durations are bounded by the current planning block. If bootstrap evidence exists but the semi-Markov state is unsupported, bootstrap is used. With neither source available, the model emits no-evidence slots and no invented actions.

This is a sparse empirical semi-Markov model, not a hidden-state occupancy estimator. It has no learned room graph, holiday classifier or calibrated security effectiveness score. The configured mixture probability is a preference where evidence supports it, not a guarantee of the final proportion of actions.

## Constraints and execution

The planner enforces minimum dwell, maximum on time and a simultaneous-light cap, then applies a shared nonnegative jitter to each joint transition. OFF events precede ON events at a common timestamp. The executor independently checks real light state, pending AOS ownership, per-light command dwell, overrides and availability. A runtime timer covers maximum-on deadlines even if the plan ends or has no further evidence.

One pending timer schedules the next action or owned-light timeout. A generation token invalidates callbacks during cancellation, reload and regeneration. The daily plan is saved separately from the small runtime record to limit storage writes. The consumed plan cursor is saved before command dispatch; safety gates are checked again after this storage await. A crash can therefore miss a command rather than replay one. Startup never catches up past plan events.

A presence callback immediately disables AOS when any person is home and cancels pending work before scheduling persistence. Other unsafe inputs suspend scheduling without clearing the explicit Away Mode request. Unknown-to-away recovery can resume only future events under all gates. No stop path calls `light.turn_off` or `switch.turn_off`, restores a scene or resets brightness.

The HA event loop cannot retract a service call already handed to a light integration. Physical-device acknowledgement, Zigbee/Z-Wave/network delays and external automations are outside AOS's transaction boundary. Return cancellation promises no subsequent AOS commands after the event is processed, not recall of a previously transmitted command.

## Storage and workload

Startup imports retained Recorder history and fits the model; daily training uses the compact local archive. Additional imports are explicit. Source observations, current schedule and seed survive reloads; fitted tables are rebuilt. All SQLite and model fitting/planning work runs off the event loop. Interlock checks and cancellation remain event-driven.

The Pi 4 resource envelope is bounded structurally, but local benchmark measurements are not Pi benchmarks. Heavy Recorder days may still be expensive even with daily chunks. Keep selection limited to the actual simulation lights and required sentinels. Do not increase Recorder-wide retention to 365 days merely to give AOS a seasonal archive.

## Read-only visual API

A bundled JavaScript custom card fetches an authenticated, administrator-only WebSocket snapshot. A static route serves only the card code, never household data. Expensive history summaries, matrix aggregation and exploratory sampling run in an executor, one visual request at a time, with five-minute aggregate caching. The seven views share this API. Resource registration uses Core 2026.7.2's Lovelace storage collection; YAML-managed resource configuration stays explicit.

The displayed transition matrix aggregates the actual pooled semi-Markov counts into eight frequent joint states plus Other. It does not allocate a 2**N matrix, impute missing states or infer a room-to-room movement graph. Heatmap denominators are per entity. Solar intervals resample whole dates, not individual five-minute points. See [dashboard semantics](DASHBOARDS.md) for statistical limits.

The transition matrix refreshes from the latest archived complete observations on a five-minute cache cycle, even before model readiness. It uses the same uncensored-run rule as model fitting; it can include newer evidence than the currently fitted execution model, which updates on daily or explicit retraining. Missing or partial joint states are never invented to fill the matrix.
