# Install the seven-view dashboard

`dashboards/aos.yaml` is one complete native Lovelace dashboard with seven views. It requires no custom cards or frontend JavaScript.

1. In **Settings → Dashboards**, add a new dashboard, start empty and open it.
2. Choose **Edit dashboard → Raw configuration editor**. Replace the empty dashboard configuration with the contents of `dashboards/aos.yaml` and save.
3. Confirm the AOS entity IDs against **Settings → Devices & services → AOS → Entities**. If HA appended a suffix or you renamed an entity, update all references, including those inside Markdown templates.

For a file-managed YAML dashboard, copy the file to `/config/dashboards/aos.yaml` and merge this into the existing `lovelace:` configuration:

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

Do not create a second `lovelace:` key if one already exists. The dashboard URL key contains a hyphen, as HA requires.

| View | Contents |
|---|---|
| Overview | Enable, dry run, status, readiness and immediate Stop |
| Live Activity | Recent intended/called/skipped actions and overrides |
| Schedule | Upcoming 40 actions, model source and regenerate control |
| Learning | Eligibility, retention, import and retrain controls |
| History & Exclusions | Reason counts, explicit intervals and exclusion instructions |
| Model Diagnostics | Joint states, transition support and model explanation |
| Settings & Safety | Native settings link, configured household and control boundaries |

History graphs depend on Recorder retaining AOS sensor states. The optional Recorder exclusion example reduces AOS attribute storage but also removes these status graphs; current tables and controls still work. Dashboard Markdown templates are validated with the HA template engine. Actual browser appearance and mobile layout still require checking in your HA frontend.
