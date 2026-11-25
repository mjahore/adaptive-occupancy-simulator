"""Diagnostics intentionally omit household IDs, times, masks and location."""


async def async_get_config_entry_diagnostics(hass, entry):
    r = entry.runtime_data
    return {
        "status": r.status,
        "dry_run": r.dry_run,
        "enabled": r.enabled,
        "light_count": len(r.config["lights"]),
        "person_count": len(r.config["persons"]),
        "legacy_count": len(r.config["legacy_automations"]),
        "model": r.model.diagnostics() if r.model else None,
        "archive_frames": r.summary.get("frames", 0),
        "has_error": bool(r.error),
        "schedule_actions": len(r.plan),
        "pending_actions": len(r.plan) - r.cursor,
    }
