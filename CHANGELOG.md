# Changelog

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
