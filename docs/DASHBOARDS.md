# Install or update the seven-view dashboard

`dashboards/aos.yaml` is the visual dashboard. Its single custom card is bundled with AOS 0.2.0; no additional HACS frontend repository or chart library is required. Household data is fetched locally through an administrator-only Home Assistant WebSocket command. Sign in as a Home Assistant administrator to use these views.

1. Update AOS in HACS and restart Home Assistant.
2. Refresh the browser (or reload the Companion app frontend).
3. For an existing AOS dashboard, open **Edit dashboard → Raw configuration editor** and replace its contents with [the complete dashboard YAML](../dashboards/aos.yaml). For a new dashboard, create an empty dashboard under **Settings → Dashboards**, then paste the same YAML.
4. Save. The card discovers AOS controls through the entity registry, including renamed controls. It does not require hard-coded AOS entity IDs.
5. Open **Learning → Import history** and review the per-entity report. Preview exploration works while you are home and AOS is disabled.

HACS updates integration files; it does not replace previously pasted dashboard configurations. Back up your existing raw configuration if you customized it.

## Frontend resource

In normal storage mode AOS automatically adds or updates this module resource:

`/aos-dashboard/aos-card.js?v=0.2.0`

If the page says **Custom element doesn't exist: aos-dashboard-card**, check **Settings → Dashboards → Resources** (advanced mode may be needed), add the URL above with type **JavaScript module** if missing, then refresh. Avoid duplicate entries for the same path.

For YAML-managed resources, merge this into the existing `lovelace:` configuration:

```yaml
lovelace:
  resources:
    - url: /aos-dashboard/aos-card.js?v=0.2.0
      type: module
```

A file-managed dashboard may also use:

```yaml
lovelace:
  dashboards:
    aos-dashboard:
      mode: yaml
      title: AOS
      icon: mdi:home-lightbulb
      show_in_sidebar: true
      filename: dashboards/aos.yaml
```

Copy the dashboard file into `/config/dashboards/aos.yaml`. Merge these examples under one `lovelace:` key, preserving other resources and dashboards.

## Views

| View | Contents |
|---|---|
| Overview | Native controls, readiness, today's gold timeline, hourly heatmap, solar bars |
| Live Activity | Recent decisions, skip reasons, manual overrides and Stop |
| Schedule | Full saved daily plan, blue current-time line, sunrise/sunset markers, tomorrow's provisional preview and synthetic-day explorer |
| Learning | All/weekday/weekend heatmaps, per-device usable dates, import diagnostics, coverage, complete observed on durations |
| History & Exclusions | Per-entity missing history, archived reason counts and explicit exclusions |
| Model Diagnostics | Observed transition probability matrix, counts, dwell durations, solar association and model evidence |
| Settings & Safety | Configured residents, alarm, sentinels, devices, limits and native settings link |

Charts use Home Assistant's configured timezone. They handle 23/25-hour DST days. Narrow screens scroll charts horizontally inside each card. Values and tooltips come from actual retained observations; empty evidence remains empty.

## What the charts mean

**Saved plan:** gold bars are desired on periods, capped at the maximum-on limit. Faded bars are elapsed planned time, not confirmed execution. Interlocks, unavailable devices and manual overrides can skip commands. The display includes the full day, beyond the native sensor's 40-action preview. Choose Show full day for morning activity.

**Tomorrow and synthetic days:** these are read-only model samples. Resampling and shifting solar conditioning never replace the saved plan, change authorization or call lights. Preview uses at least two observed dates per target; actual plans still use the configured minimum (default seven). The solar slider shifts conditioning and displayed preview markers by up to two hours; it does not change the real sunset or training data. Selecting a different day clears the sample until you resample. Tomorrow's eventual saved plan can differ. Dinner, bedtime and movement between rooms are not inferred.

**Replace saved plan:** this separate, confirmed control calls the real regenerate button. It changes the plan used by AOS. Use the explorer for experimentation.

**Hourly heatmaps:** each cell is the observed on fraction for that device and hour. Known devices in qualified partial frames count independently; unknown is never treated as off. Hatching means no evidence. A tooltip gives the numerator and denominator. Weekday/weekend filters change the sample pool. Repeated autumn DST hours share a civil-hour bin.

**Transition matrix:** rows are the current joint lighting combination, columns the next observed combination. It displays the semi-Markov model's pooled transition counts from complete, uncensored eligible runs. Rows with evidence sum to one before rounding; rows without outgoing evidence show dashes. The eight most frequent combinations are named, with remaining combinations grouped as Other so probability mass is retained. The legend identifies lights on together and median observed dwell time. Time staying in a combination is represented by duration rather than five-minute self-transitions; Other-to-Other can be nonzero because it groups different combinations. This is lighting-state evidence, not person movement or the final hybrid scheduler's probabilities. Partial frames do not invent complete joint states for this matrix.

**Solar bars:** the difference in nighttime and daytime on fractions, in percentage points, averaged over dates with at least 15 eligible minutes in each group. Night is below −6° solar elevation and day above 6°; twilight is omitted. Approximate 95% intervals use 400 whole-day bootstrap draws after at least seven paired dates. This descriptive association includes daily routines and is not a causal sunlight sensitivity estimate or calibrated confidence score. Serial dependence across dates and small samples limit the intervals.

**Import report:** the configured lookback is distinct from archive retention. Unknown five-minute intervals and chunks without records are listed for each selected entity. Counts can overlap and describe the latest scan, while archived reason counts describe stored frames. Complete joint days and per-device baseline dates are deliberately separate. Reports reset on reload until the next import.

## Classic dashboard and the missing regenerate button

[dashboards/aos-classic.yaml](../dashboards/aos-classic.yaml) preserves the original built-in-card dashboard. Its expected regenerate ID is corrected to `button.adaptive_occupancy_simulator_regenerate_preview`. If Home Assistant renamed or suffixed an entity, update the classic dashboard's references. The new visual dashboard resolves control IDs automatically.

Native sensors and controls remain available without opening the visual card. Unlike classic history graphs, visual historical charts use AOS's archive and do not depend on retaining AOS sensor attributes in Recorder.

The transition matrix refreshes from the latest archived complete observations on a five-minute cache cycle, even before model readiness. It uses the same uncensored-run rule as model fitting; it can include newer evidence than the currently fitted execution model, which updates on daily or explicit retraining. Missing or partial joint states are never invented to fill the matrix.
