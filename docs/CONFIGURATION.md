# Configuration and actions

All settings are available through the integration's Configure/options dialog. There is one AOS instance per Home Assistant installation. AOS deliberately does not replace your existing Away Mode trigger.

## Household selection

| Setting | Default | Meaning |
|---|---|---|
| Residents | Must select | Every selected person is an independent safety interlock |
| Alarm | Must select | Read-only Canary entity; customize for your installation |
| Lights and lighting switches | Must select | 1–48 individual `light.*` or `switch.*` entities connected to lighting; on/off only |
| Legacy automations | Must select any existing vacation lighting automations | Every selected sentinel must be known and off for learning or simulation |
| Allowed away states | `armed_away` | Simulation requires one of these states |
| Allowed home states | `disarmed`, `armed_home`, `armed_night` | Learning requires one of these states |

Home and away alarm sets must be disjoint. Unknown, unavailable, arming, disarming, pending and triggered cannot authorize learning or simulation. A named person zone such as `work` counts as away; missing and unavailable entities do not. One resident home plus another unknown stops simulation but does not permit learning.

Select only switches or smart plugs that power lights, not appliances. AOS's own control switches are excluded even if renamed. Scenes, scripts, fans and other entity domains are not supported as lighting targets.

Do not select light groups that overlap selected individual lights, or both a switch and a light wrapper controlling the same physical circuit. AOS cannot reliably infer physical group membership or duplicate circuits across integrations. Keep exterior security lighting under its existing controller unless you explicitly intend to migrate it.

Removing a legacy sentinel explicitly removes that guard from subsequent imports. Keep your legacy entities present and disabled through migration; missing historical states are excluded, not assumed off. Enabled-state history is a conservative vacation marker, not a record of when each automation actually issued a light command. If an automation was enabled all year, its entire retained history is excluded.

## Adding lighting switches

Update to AOS 0.1.2 or newer in HACS and restart Home Assistant. Open **Settings → Devices & services → Adaptive Occupancy Simulator → Configure**, then add the desired `switch.*` entities under **Lights and lighting switches to simulate**. Complete the remaining settings and save. Existing light-only selections remain supported, and the away/return scripts require no changes for this update.

Changing the ordered selection clears incompatible joint-state training frames and the daily plan, resets AOS to disabled with dry run on, and imports retained Recorder history for the new selection. Previously purged history cannot be recovered. Review Learning and the preview before explicitly enabling again; newly selected switches with missing history may delay readiness. Ensure Recorder records these switches. Existing historical legacy exclusions continue to apply.

Both domains use the same on/off history, model and safeguards. AOS calls `light.turn_on/off` for lights and `switch.turn_on/off` for switches. All limits count selected entities, not bulbs: a lighting relay powering several lamps counts as one target. Returning home cancels pending commands for both types without changing their current states.

## Learning and model limits

| Setting | Default | Allowed range |
|---|---:|---:|
| AOS retention days | 365 | 7–730 |
| Recorder import lookback days | 10 | 1–365 |
| Minimum eligible days | 7 | 2–90 |
| Bootstrap block minutes | 60 | 15–180 |
| Bootstrap probability | 0.80 | 0–1 |
| Minimum command dwell minutes | 10 | 5–60 |
| Maximum continuous simulated on minutes | 180 | 15–720 |
| Maximum simultaneous lighting targets | 8 | 1–48 |
| Manual override pause minutes | 60 | 5–1440 |
| Joint timing jitter seconds | 45 | 0–120 |

The sample interval is five minutes. Block length is rounded down to a whole number of samples. Minimum eligible days counts local dates with eligible observations, not guaranteed full days of coverage. Always review the resulting plan: a readiness flag alone does not establish that every time of day has representative history.

The maximum-on runtime timer applies to lights AOS actually turned on and still owns. It remains subject to occupancy, alarm and manual override interlocks; it never forces a light off after someone returns or while the alarm/presence is uncertain. A temporarily unavailable light may remain on beyond the limit. On recovery, AOS can attempt its overdue off command if every interlock permits it.

Outside light state or attribute changes pause that light and release AOS's maximum-on ownership. HA action context and parent context distinguish AOS commands from other changes; devices that lose context may create conservative false overrides. Concurrent limits count observed on states plus AOS commands awaiting state acknowledgement. AOS does not turn off unrelated manually lit rooms to enforce a cap.

## Entities

Expected IDs use the prefix `adaptive_occupancy_simulator`; HA may append a suffix on collision or preserve a user rename.

| Entity | Purpose |
|---|---|
| `switch.adaptive_occupancy_simulator` | Explicit Away Mode intent |
| `switch.adaptive_occupancy_simulator_dry_run` | Persistent dry-run control, on initially |
| `binary_sensor.adaptive_occupancy_simulator_safe_to_simulate` | All runtime gates including enable/model readiness pass |
| `binary_sensor.adaptive_occupancy_simulator_model_ready` | Minimum training evidence reached |
| Status, Next action, Schedule sensors | Execution and bounded upcoming plan |
| Learning, History, Model sensors | Data provenance and model evidence |
| Activity sensor | Last 25 decisions and override expirations |
| Stop, Import history, Retrain, Regenerate preview, Clear overrides buttons | Native maintenance actions |

The schedule preview shows at most 40 future commands. The full current daily plan is in AOS's private storage file. Activity keeps 100 recent decisions internally, with 25 exposed to the dashboard; it is not an unlimited audit log.

## Actions

The actions `adaptive_occupancy_simulator.stop`, `import_history`, `retrain`, `regenerate`, and `clear_overrides` take no parameters. They are also available as buttons. Import history is limited to the configured lookback and cannot recover purged Recorder records. Retrain rebuilds the model without rerolling an already-generated daily plan; use Regenerate to replace the plan explicitly.

To exclude an additional known vacation or contaminated interval:

```yaml
action: adaptive_occupancy_simulator.exclude_period
data:
  start: "2026-10-01T00:00:00-04:00"
  end: "2026-10-07T00:00:00-04:00"
  reason: "Legacy vacation lighting before migration"
```

Start is inclusive, end exclusive, and timezone offsets are required. Every overlapping five-minute frame is excluded. This action stops AOS, clears the schedule, and retrains. Re-enable explicitly afterward. Exclusions intentionally have no UI delete action; removing a mistaken exclusion currently requires a backed-up, offline archive correction or rebuilding the archive.

## Data and removal

AOS stores its model's source observations and interval exclusions in `/config/.storage/adaptive_occupancy_simulator_<entry_id>.sqlite`. Mode, plan, cursor and recent decisions use HA Store at `/config/.storage/adaptive_occupancy_simulator.<entry_id>`. The immutable daily schedule uses a separate `adaptive_occupancy_simulator.plan.<entry_id>` HA Store file so consuming an action does not rewrite the entire plan. Include all three files in backups. The sparse fitted tables are reconstructed from retained observations at startup; no information necessary to rebuild the model is lost.

Changing ordered lights, people, alarm mapping, legacy sentinels or location invalidates incompatible training frames. Changing any configuration invalidates the daily plan and resets disabled/dry run. Retention deletions reuse SQLite pages but do not necessarily shrink the file immediately.

To remove: stop AOS, restore the scripts as described in Migration, remove its integration entry, remove the custom component through HACS or the filesystem, and restart. Archive files are retained for recovery; remove the three AOS-specific storage files only after stopping HA and keeping a backup. Never remove `home-assistant_v2.db`.
