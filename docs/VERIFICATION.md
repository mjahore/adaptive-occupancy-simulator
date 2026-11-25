# Verification and known limitations

The integration targets **Home Assistant Core 2026.7.2 / Python 3.14.6**. Development validation used those exact installed versions on macOS ARM64. It does not establish that the physical Raspberry Pi, Canary integration, household lights or hosted Home Assistant frontend have passed acceptance testing.

## Automated verification

The test suite exercises actual Home Assistant Core objects, native config and options flows, entity platforms, storage, event dispatch, service calls, template rendering and SQLite Recorder. Light and switch services are simulated; no real household device is contacted.

Covered behavior includes:

- Default disabled/dry run state; live-mode changes rejected while enabled; failed persistence cannot authorize live mode.
- Every configured resident independently cancels pending work on return, without cleanup commands; stale callbacks and a return during storage persistence cannot dispatch a new light action.
- Unknown/unavailable residents, unsafe alarm states and legacy-enabled states prevent simulation.
- Manual overrides, own-action context recognition, concurrent caps including unacknowledged commands, and a runtime maximum-on timer after the daily plan ends.
- Service failures suspend subsequent execution; unload cleanup is idempotent.
- Native installation, duplicate-entry prevention, options reload and platform unload against HA 2026.7.2.
- Mixed light/switch selection and domain-correct dispatch, dry-run switch commands, mixed-target return cancellation, switch overrides and maximum-on timers, and shared concurrent limits. AOS's own controls are rejected even when renamed.
- A committed real SQLite Recorder event read through the selected history API; chunked adapter calls use the verified flags and preserve five-minute boundary continuity.
- Historical unknown-start states, short contaminated intervals, old AOS sessions, explicit exclusions, retention and changed light-order invalidation.
- Deterministic joint-block sampling, sparse semi-Markov transitions, censored gaps, cold-start refusal and output limits.
- Both DST day lengths with unique UTC slots.
- Seven classic dashboard views and real installed entity references, including the corrected regenerate button; script schema validation and migration examples.
- Per-device partial masks, brief outages, guard contamination within partial intervals, per-target evidence thresholds, unknown-command suppression and archive upgrade provenance.
- Actual HTTP serving, Lovelace resource registration across reload, registry-based renamed controls and authenticated administrator/non-administrator WebSocket requests; invalid exploration inputs rejected.
- Per-device heatmap denominators, censored durations, paired-day solar intervals, full saved-plan timelines, DST and read-only previews with no schedule/service side effects.
- Transition matrix count normalization, bounded Other aggregation, blank unsupported rows, and automatic archive updates before model readiness without refitting the execution model.

`TEST_RESULTS.txt` records the final test/lint run. Dependency deprecation warnings are reported without treating them as integration failures. The local 0.2.0 suite passes 83 tests. Hosted tests, HACS validation and hassfest are also configured; consult [GitHub Actions](https://github.com/mjahore/adaptive-occupancy-simulator/actions) for each subsequent commit's result.

## Visual verification

The actual bundled card was rendered in a local browser using synthetic observations produced by the real analytics/model backend. The fixture is labelled example data and connects to no household device. Overview, schedule sampling, filters, matrix, learning/report, activity, history and settings were inspected; narrow-screen chart scrolling was checked. This is component rendering validation, not full end-to-end acceptance in the user's HAOS dashboard. Actual Core HTTP/resource/WebSocket integration is separately exercised by automated tests.

## API verification sources

Pinned source and the installed package take precedence over current documentation for this target:

| API or fact | Verified source |
|---|---|
| Core version and Python minimum | [Core 2026.7.2 constants](https://github.com/home-assistant/core/blob/2026.7.2/homeassistant/const.py) and [project metadata](https://github.com/home-assistant/core/blob/2026.7.2/pyproject.toml) |
| Recorder history entry point and arguments | [Pinned history implementation](https://github.com/home-assistant/core/blob/2026.7.2/homeassistant/components/recorder/history/__init__.py) |
| Recorder instance access | [Pinned Recorder helper](https://github.com/home-assistant/core/blob/2026.7.2/homeassistant/helpers/recorder.py) |
| Recorder executor | [Pinned Recorder core](https://github.com/home-assistant/core/blob/2026.7.2/homeassistant/components/recorder/core.py) |
| State subscriptions and cancellable UTC timers | [Pinned event helpers](https://github.com/home-assistant/core/blob/2026.7.2/homeassistant/helpers/event.py) |
| Native config/options flow and runtime data | [Pinned config entries](https://github.com/home-assistant/core/blob/2026.7.2/homeassistant/config_entries.py), exercised by lifecycle tests |
| Mixed-domain entity picker and own-control exclusion | [Pinned selector](https://github.com/home-assistant/core/blob/2026.7.2/homeassistant/helpers/selector.py) and [entity registry](https://github.com/home-assistant/core/blob/2026.7.2/homeassistant/helpers/entity_registry.py), inspected locally and exercised by options tests |
| Switch on/off states and actions | [Official switch documentation](https://www.home-assistant.io/integrations/switch/), domain dispatch exercised on the target Core |
| Static card resource | [Async static path API](https://developers.home-assistant.io/blog/2024/06/18/async_register_static_paths/) and installed Core 2026.7.2 HTTP source, exercised over HTTP |
| Lovelace resource collection | Installed Core 2026.7.2 `components/lovelace/resources.py`, including load/create/update, exercised in integration lifecycle tests |
| Card contract | [Official custom card documentation](https://developers.home-assistant.io/docs/frontend/custom-ui/custom-card/); component rendering and JavaScript syntax checked locally |
| Authenticated dashboard command | Installed Core 2026.7.2 WebSocket API decorators/schema, tested with actual admin/non-admin authentication |
| Store and entity APIs | [Pinned storage helper](https://github.com/home-assistant/core/blob/2026.7.2/homeassistant/helpers/storage.py), exercised by persistence/platform tests |
| Astral dependency and HA coordinates | [Pinned project dependencies](https://github.com/home-assistant/core/blob/2026.7.2/pyproject.toml), [pinned sun helpers](https://github.com/home-assistant/core/blob/2026.7.2/homeassistant/helpers/sun.py) |
| Recorder defaults and SQLite behavior | [Official Recorder documentation](https://www.home-assistant.io/integrations/recorder/) |
| Python target release | [Python 3.14.6 release](https://www.python.org/downloads/release/python-3146/) |
| Repository layout and brand metadata | [HACS integration requirements](https://www.hacs.xyz/docs/publish/integration/), [publishing requirements](https://www.hacs.xyz/docs/publish/start/) |

The historical `recorder/history/modern.py` path is absent in 2026.7.2; AOS uses `recorder.history` instead. Current developer pages can describe APIs introduced after this target, so their latest examples are not assumed compatible. Recorder history and Lovelace resource collections are internal HA APIs and may require adaptation for future Core releases.

## Resource benchmark

`BENCHMARK.json` and `tools/benchmark.py` report a synthetic year of 105,120 frames for 32 lights. On the available ARM64 Mac with Python 3.14.6 and allocation tracing enabled: fitting took about **2.72 seconds**, one-day planning **2.46 seconds**, and peak traced Python allocations **36.9 MiB**. This excludes the HA process, Recorder workload, filesystem effects and device service latency. It is not a Pi 4 performance measurement. Use the script to compare on representative development hardware; do not install development tools into HAOS merely to reproduce it.

The schedule file is written once per plan generation; consumed cursors and mode changes use a separate small Store record. Archive transactions and model computation run in executors. High-frequency entity attribute history can still make Recorder imports expensive despite selected-entity daily chunks.

## Household acceptance checklist

1. With AOS installed and disabled, confirm native entity IDs and Canary's observed state mapping. Leave dry run on.
2. Confirm historical legacy on-periods and unknown periods are excluded. Review any gaps and retain at least the configured eligible-day count. Default ten-day Recorder retention may offer too little clean evidence initially.
3. Audit every legacy lighting scheduler and any detached scripts before enabling live use.
4. Check all seven views in the actual HA frontend, including mobile layout and actual entity-name collisions. Local component rendering and actual Core resource/API integration are tested separately; confirm the installed dashboard in your HA frontend.
5. While genuinely away, enable dry-run AOS through the revised lifecycle and confirm plausible upcoming times/rooms, all interlocks, and no real AOS light calls.
6. Verify that either resident's real arrival stops AOS without changing lights. The independent interlock must work even if the alarm/HVAC return sequence fails.
7. Review an outside light change/automation conflict and its override pause. Some devices discard action context; confirm false overrides are acceptable.
8. During controlled away testing, verify reload persistence, no replay of missed actions, and normal behavior when entities reconnect. Check CPU, memory, storage and responsiveness on the Pi.
9. Stop AOS, explicitly turn dry run off, and enable it again only when ready for supervised live testing.

## Deliberate limitations

- This is lighting-pattern simulation, not a proven burglary deterrent or a security-system replacement. No effectiveness percentage is claimed.
- On/off only for `light.*` and lighting `switch.*` entities; no brightness, color temperature, color, transitions, curtains, media players, scenes, scripts or physical occupancy sensors. Five-minute sampling misses shorter light activity.
- Sparse or seasonally unrepresentative data can yield empty or repetitive schedules. Day counting does not guarantee full-day coverage. Unknown/absent device history is excluded per device in the baseline; complete joint training still requires every target known. Guard uncertainty excludes the entire interval. History is never fabricated.
- Solar conditioning uses elevation plus local time and day type. There is no separate learned sunset-offset regression, holiday calendar or weather dependence. Semi-Markov fallback may pool across solar/day contexts and truncates empirical dwell at planning-block boundaries.
- Model constraints and manual overrides alter the sampled distribution. No held-out statistical calibration or household realism study has been performed.
- Physical commands already dispatched cannot be recalled. Stop, return, unsafe inputs and unloading never restore or turn off lights. This takes priority over maximum-on cleanup.
- An unavailable device or competing automation can prevent a desired state. AOS does not verify physical lamp illumination. Context-losing devices can cause false manual overrides.
- Retention cannot recover purged Recorder data. Legacy automations with missing history reduce usable evidence; always-enabled legacy automations exclude their entire enabled period.
- Daily model fitting does not reroll an existing plan automatically. Use Regenerate explicitly; new local days generate new plans. Startup imports retained history, while daily collection primarily uses AOS's own sampler.
- Single household instance, up to 48 individual lights and lighting switches in total, English strings, and bounded native-sensor/activity previews. The visual timeline reads the full saved plan; the matrix displays eight frequent states plus Other. Explicit exclusions have no deletion UI in this release.
- Pi 4/HAOS operation, actual Canary and lighting-device behavior, and the installed household dashboard still require target-household acceptance.

The transition matrix is an empirical lighting-state diagnostic that can update before model readiness. It is not a room-movement estimator or a calibrated forecast. Solar bootstrap intervals are approximate and do not establish causality. Preview sampling may show an empty day despite meeting the minimum date count when no matching blocks exist.
