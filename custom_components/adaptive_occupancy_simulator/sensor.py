"""Bounded observability; full schedules stay in AOS storage."""

from homeassistant.components.sensor import SensorEntity

from .entity import AOSEntity

SENSORS = {
    "status": "Status",
    "next_action": "Next action",
    "schedule": "Schedule",
    "learning": "Learning",
    "history": "History",
    "model": "Model",
    "activity": "Activity",
}


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([AOSSensor(entry.runtime_data, key, name) for key, name in SENSORS.items()])


class AOSSensor(AOSEntity, SensorEntity):
    @property
    def native_value(self):
        r = self.runtime
        if self.key == "status":
            return r.status
        if self.key == "next_action":
            return r.plan[r.cursor].ts if r.cursor < len(r.plan) else "none"
        if self.key == "schedule":
            return max(0, len(r.plan) - r.cursor)
        if self.key == "learning":
            return "training" if r.busy else (r._learning_reason() or "learning")
        if self.key == "history":
            return r.summary.get("frames", 0)
        if self.key == "model":
            return r.model.days if r.model else 0
        return r.log[0]["result"] if r.log else "idle"

    @property
    def extra_state_attributes(self):
        r = self.runtime
        if self.key == "status":
            return {
                "reason": r.reason(),
                "error": r.error,
                "dry_run": r.dry_run,
                "persons": r.config["persons"],
                "alarm": r.config["alarm"],
                "legacy_automations": r.config["legacy_automations"],
                "lights": r.config["lights"],
                "away_states": r.config["away_states"],
                "home_states": r.config["home_states"],
            }
        if self.key == "next_action":
            return r.plan[r.cursor].as_dict() if r.cursor < len(r.plan) else {}
        if self.key == "schedule":
            return {
                "day": r.plan_day,
                "seed": r.seed,
                "total": len(r.plan),
                "preview": [a.as_dict() for a in r.plan[r.cursor : r.cursor + 40]],
                "preview_limit": 40,
            }
        if self.key == "learning":
            return {
                "retention_days": r.config["retention_days"],
                "minimum_days": r.config["minimum_days"],
                "last_train_day": r.last_train_day,
                "eligible_now": not bool(r._learning_reason()),
            }
        if self.key == "history":
            return r.summary
        if self.key == "model":
            return r.model.diagnostics() if r.model else {"ready": False}
        return {"recent": list(r.log)[:25], "overrides": r.overrides}
