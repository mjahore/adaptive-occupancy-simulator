# Architecture and statistical model

AOS separates historical eligibility, statistical planning and physical execution. A plan can exist while simulation is disabled. Only the execution layer can call lights, and it rechecks the current household state immediately before dispatch.

Lighting targets are `light.*` and `switch.*` entities with on/off states. They share the existing ordered `lights` configuration key and joint bit mask, so existing light-only configurations need no data migration. The executor checks the allowed domain and rejects AOS's own registry entries before calling that domain's `turn_on` or `turn_off` action. The same learning, availability, override and limit checks apply to both types.

## Historical eligibility

The Recorder adapter calls `get_significant_states` for selected entities with start-state inclusion, all state changes, uncompressed output and no attributes. Calls execute in Recorder's own database executor, in one-day chunks. The adapter never opens Recorder's SQLite file or depends on its SQL tables.

For each five-minute UTC interval, a chronological sweep maintains the selected entities' states. A frame is usable only when at least one person is home, every person is known, the alarm permits learning, every legacy sentinel is off, all lights have known on/off state, and any known AOS enable switch is off. Any disqualifying transition inside an interval rejects the whole interval. Missing start states reject history until a known state appears.

Each stored frame contains UTC timestamp, joint-light bit mask, local minute, weekday/weekend, solar elevation, eligibility and rejection reason. AOS sessions and manual exclusions form a second interval filter. Local sampling taints intervals on interlock changes and writes a startup-gap rejection; it never bridges a restart with fabricated occupancy. Live observations take precedence over later imports.

AOS's separate SQLite archive uses parameterized transactions on HA's general executor. At 365 days, five-minute sampling produces at most about 105,120 rows, independent of light count. Up to 48 lights fit in one integer mask. The archive is pruned during daily training. No neural libraries or dense state matrix are used.

## Joint block bootstrap

Planning runs over a local calendar day expressed as increasing UTC instants. This yields 276 five-minute slots on the spring DST transition and 300 on the autumn transition, with no duplicated UTC times.

For each target block, donor starts must match weekday/weekend and solar phase (night below −6°, twilight −6° to 6°, day above 6°), be within 90 civil minutes and 15° solar elevation, and have a complete contiguous eligible block. An excluded or missing frame breaks continuity.

Eligible donors receive weights proportional to:

`exp(−civil_minute_distance / 60 − solar_elevation_difference / 10 − age_seconds / (180 × 86400))`

The whole sequence of joint room masks is copied. Rooms are not sampled independently, preserving empirical within-block overlap and transitions. One seeded random generator controls sampling and another deterministic seeded pass applies constraints. Solar elevation is calculated with Astral from HA's latitude, longitude and elevation; it does not require historical `sun.sun` records.

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
