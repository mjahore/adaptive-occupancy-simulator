# Migrate existing vacation lighting

AOS replaces occupancy-simulation lighting, while your existing scripts continue to manage the alarm, HVAC, locks, notifications and other household behavior. Keep a backup of those scripts and automations before migration.

## Configure and learn

1. Install AOS and select your real person entities, alarm panel and individual interior lights in the native configuration form. The public repository contains no household-specific defaults.
2. Select **every legacy vacation lighting automation** as a historical sentinel. The selection starts empty because entity IDs differ between installations. Do not skip this step when migrating an existing system.
3. Keep AOS disabled and dry run on while occupied. Review Learning and History after the Recorder import. Historical sentinel on-periods and unknown states are rejected. Add explicit exclusion periods for other known artificial lighting history.
4. Retain the old automation entities so their history remains available. AOS's compact archive grows from retained Recorder history and future local observations; it cannot recover already-purged data.

## Retire legacy lighting controllers

Inspect every scheduler that enables or randomizes the old lighting automations, including their called scripts. Disable lighting-only schedulers and remove only the lighting branches from mixed-purpose automations. Preserve their unrelated household actions.

Disable each legacy vacation automation using `automation.turn_off` with `stop_actions: true`. Independently launched scripts may continue after their caller is stopped; cancel any detached lighting-only scripts separately. Leave the old automations disabled rather than deleting them during validation.

## Integrate with existing scripts

Add the enable action from `examples/turn_on_away_mode.yaml` to your existing Away Mode script where the legacy vacation lighting was enabled. Add the stop action from `examples/turn_off_away_mode.yaml` at the beginning of your existing return/disable script. The example files are minimal UI script bodies, not complete replacements for your household orchestration.

Preserve the existing trigger conditions, timing, security actions, HVAC actions, automation toggles and notifications. Confirm the actual AOS switch entity ID; HA may append a suffix after a name collision. If an unavailable AOS action must not block remaining household actions, set `continue_on_error: true` on that action.

AOS independently cancels future light commands when any configured person becomes home. It does not wait for the return script, and it never changes lights as part of cancellation. AOS only reads the alarm; your existing lifecycle must put the alarm in the configured away state for simulation to run.

## Validate and authorize live output

With a ready model and residents actually away, enable AOS while dry run remains on. Review intended calls, room patterns and timing. Confirm that a real resident arrival cancels AOS without changing lights. Check unknown-state interlocks and manual override handling using an isolated test setup or supervised household testing.

Stop AOS before switching dry run off. Re-enable only when ready for supervised live use. Any configuration change returns the integration to disabled/dry run. See `VERIFICATION.md` for the full acceptance checklist and limits.

## Roll back

Stop AOS first; current light states remain unchanged. Restore your backed-up script bodies and legacy scheduler behavior. Let the original away lifecycle re-enable the old lighting at the next intended activation. Keep AOS disabled or remove it. Do not run the old vacation controller and AOS live at the same time.
