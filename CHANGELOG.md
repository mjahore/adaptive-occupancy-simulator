# Changelog

## 0.2.0 — 2026-11-25

- Bundle a seven-view visual dashboard: full lighting timelines, hourly heatmaps, solar association bars, observed transition probability matrix with counts and dwell times, coverage and a read-only synthetic-day explorer.
- Preserve known-device observations when another light or lighting switch is unknown/unavailable. Build a provisional partial joint-block baseline per device, then prioritize complete joint bootstrap/semi-Markov evidence as it grows. Unknown states never become off.
- Keep occupancy, Canary, legacy vacation, AOS-session and explicit exclusion guards for all baseline data and commands. Return-home cancellation and dry-run defaults are unchanged.
- Add per-entity Recorder import diagnostics and usable-date counts; distinguish partial learning from complete joint eligibility. Upgrade old archive rows conservatively and re-scan retained light-unknown history.
- Resolve dashboard controls through the entity registry, including renamed regenerate controls; fix the classic dashboard regenerate ID.
- Serve a versioned local card resource and administrator-only WebSocket data; verify registration, authentication, native lifecycle and actual SQLite Recorder on Core 2026.7.2 / Python 3.14.6.
- Existing pasted dashboards must be replaced with the new YAML after update/restart. No additional script migration is needed for users already on 0.1.x.

## 0.1.2 — 2026-11-25

- Allow `switch.*` entities alongside `light.*` in native setup and options for lighting plugs, relays and switches.
- Dispatch each target through its own domain's on/off actions. Both types share Recorder learning, the joint model, limits, overrides, dry run and immediate return-home cancellation without cleanup commands.
- Exclude AOS's own controls from target selection and reject them before execution, including renamed controls.
- Preserve existing configuration keys and light-only setups. Changing the selected targets resets AOS to disabled/dry run and rebuilds incompatible training frames from retained Recorder history.
- Add mixed-target execution, cancellation, historical eligibility and actual SQLite Recorder tests; verify options reload on HA Core 2026.7.2 / Python 3.14.6.
- Keep the device's reported software version aligned with the integration manifest.

## 0.1.1 — 2026-11-25

- Replace the initial house icon with a Markov-chain-inspired emblem: four state nodes, directed cycle, self-loop, and a warm active-state accent.
- Ship 256 px and 512 px brand icons for light and dark themes.
- Display the artwork in the repository README and document the HACS 2.0.5 repository-list limitation.
- No changes to configuration, learning, scheduling, or light control.

## 0.1.0 — 2026-11-25

- Initial release of Adaptive Occupancy Simulator.
