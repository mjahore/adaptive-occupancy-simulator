"""Shared integration constants; no Home Assistant imports."""

DOMAIN = "adaptive_occupancy_simulator"
NAME = "Adaptive Occupancy Simulator"
VERSION = "0.1.0"
STEP_SECONDS = 300
MAX_LIGHTS = 48
LEGACY_AUTOMATIONS = []
DEFAULTS = {
    "persons": [],
    "alarm": "",
    "lights": [],
    "legacy_automations": LEGACY_AUTOMATIONS,
    "away_states": ["armed_away"],
    "home_states": ["disarmed", "armed_home", "armed_night"],
    "retention_days": 365,
    "import_days": 10,
    "minimum_days": 7,
    "block_minutes": 60,
    "bootstrap_probability": 0.8,
    "minimum_dwell_minutes": 10,
    "maximum_on_minutes": 180,
    "maximum_lights_on": 8,
    "manual_override_minutes": 60,
    "jitter_seconds": 45,
}
UNKNOWN = {"unknown", "unavailable", "", None}


def settings(data, options=None):
    """Merge immutable defaults, initial configuration and current options."""
    return {**DEFAULTS, **data, **(options or {})}


def validate(config):
    """Reject ambiguous interlocks and unsafe model dimensions."""
    for key, domain in (("persons", "person"), ("lights", "light"), ("legacy_automations", "automation")):
        items = config[key]
        if not isinstance(items, list) or len(items) != len(set(items)):
            raise ValueError(f"Invalid {key}")
        if any(not isinstance(e, str) or not e.startswith(domain + ".") for e in items):
            raise ValueError(f"Invalid {key}")
    if not config["persons"] or not 1 <= len(config["lights"]) <= MAX_LIGHTS:
        raise ValueError("Select residents and 1–48 individual lights")
    if not config["alarm"].startswith("alarm_control_panel."):
        raise ValueError("Select an alarm control panel")
    if (
        not config["away_states"]
        or not config["home_states"]
        or set(config["away_states"]) & set(config["home_states"])
        or (set(config["away_states"]) | set(config["home_states"]))
        & (UNKNOWN | {"arming", "disarming", "pending", "triggered"})
    ):
        raise ValueError("Unsafe alarm state mapping")
    bounds = {
        "retention_days": (7, 730),
        "import_days": (1, 365),
        "minimum_days": (2, 90),
        "block_minutes": (15, 180),
        "bootstrap_probability": (0, 1),
        "minimum_dwell_minutes": (5, 60),
        "maximum_on_minutes": (15, 720),
        "maximum_lights_on": (1, MAX_LIGHTS),
        "manual_override_minutes": (5, 1440),
        "jitter_seconds": (0, 120),
    }
    for key, (low, high) in bounds.items():
        if not low <= config[key] <= high:
            raise ValueError(f"Invalid {key}")
    if config["minimum_dwell_minutes"] > config["maximum_on_minutes"]:
        raise ValueError("Minimum dwell exceeds maximum on duration")
    if config["minimum_days"] > config["retention_days"]:
        raise ValueError("Minimum learning days exceeds retention")


def occupancy_reason(states, config, *, learning=False, enabled=False):
    """Fail closed; named zones count as away, missing states never do."""
    persons = [states.get(e) for e in config["persons"]]
    if any(s in UNKNOWN for s in persons):
        return "presence_unknown"
    if learning:
        if enabled:
            return "simulation_enabled"
        if "home" not in persons:
            return "unoccupied"
        allowed = config["home_states"]
    else:
        if "home" in persons:
            return "resident_home"
        allowed = config["away_states"]
    if states.get(config["alarm"]) not in allowed:
        return "alarm_interlock"
    for entity in config["legacy_automations"]:
        value = states.get(entity)
        if value == "on":
            return "legacy_enabled"
        if value != "off":
            return "legacy_unknown"
    return ""
