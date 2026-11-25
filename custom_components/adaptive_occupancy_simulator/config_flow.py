"""Native configuration and options flows."""

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import DEFAULTS, DOMAIN, LIGHTING_DOMAINS, NAME, settings, validate
from .entity import own_entities


def schema(values, step, *, excluded_entities=()):
    fields = {}
    groups = {
        "user": ("persons", "alarm", "lights"),
        "learning": (
            "legacy_automations",
            "away_states",
            "home_states",
            "retention_days",
            "import_days",
            "minimum_days",
        ),
        "model": (
            "block_minutes",
            "bootstrap_probability",
            "minimum_dwell_minutes",
            "maximum_on_minutes",
            "maximum_lights_on",
            "manual_override_minutes",
            "jitter_seconds",
        ),
    }
    domains = {
        "persons": "person",
        "alarm": "alarm_control_panel",
        "lights": list(LIGHTING_DOMAINS),
        "legacy_automations": "automation",
    }
    bounds = {
        "retention_days": (7, 730),
        "import_days": (1, 365),
        "minimum_days": (2, 90),
        "block_minutes": (15, 180),
        "bootstrap_probability": (0, 1),
        "minimum_dwell_minutes": (5, 60),
        "maximum_on_minutes": (15, 720),
        "maximum_lights_on": (1, 48),
        "manual_override_minutes": (5, 1440),
        "jitter_seconds": (0, 120),
    }
    for key in groups[step]:
        value = values.get(key, DEFAULTS.get(key))
        marker = vol.Required(key, default=value)
        if key in domains:
            fields[marker] = selector.EntitySelector(
                selector.EntitySelectorConfig(
                    filter={"domain": domains[key]},
                    multiple=key != "alarm",
                    exclude_entities=list(excluded_entities) if key == "lights" else [],
                )
            )
        elif key.endswith("states"):
            fields[marker] = selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=["armed_away", "armed_home", "armed_night", "disarmed", "armed_vacation"],
                    multiple=True,
                    custom_value=True,
                )
            )
        else:
            low, high = bounds[key]
            fields[marker] = selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=low,
                    max=high,
                    step=0.05 if key == "bootstrap_probability" else 1,
                    mode=selector.NumberSelectorMode.BOX,
                )
            )
    return vol.Schema(fields)


def normalize(data):
    return {
        k: int(v) if isinstance(v, float) and k != "bootstrap_probability" else v for k, v in data.items()
    }


class FlowSteps:
    """Shared three-step collection; all options remain native HA controls."""

    async def _step(self, step, user_input, next_step=None):
        errors = {}
        excluded = own_entities(self.hass)
        if user_input is not None:
            self.collected.update(normalize(user_input))
            try:
                validate(self.collected, forbidden_entities=excluded)
            except ValueError, TypeError, KeyError:
                errors["base"] = "invalid_configuration"
            else:
                if next_step:
                    return await getattr(self, "async_step_" + next_step)()
                return self.async_create_entry(title=self.entry_title, data=self.collected)
        return self.async_show_form(
            step_id=step,
            data_schema=schema(self.collected, step, excluded_entities=excluded),
            errors=errors,
        )

    async def async_step_learning(self, user_input=None):
        return await self._step("learning", user_input, "model")

    async def async_step_model(self, user_input=None):
        return await self._step("model", user_input)


class AOSConfigFlow(FlowSteps, config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1
    entry_title = NAME

    async def async_step_user(self, user_input=None):
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()
        if not hasattr(self, "collected"):
            self.collected = settings({})
        return await self._step("user", user_input, "learning")

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return AOSOptionsFlow()


class AOSOptionsFlow(FlowSteps, config_entries.OptionsFlow):
    entry_title = ""

    async def async_step_init(self, user_input=None):
        self.collected = settings(self.config_entry.data, self.config_entry.options)
        return await self.async_step_user(user_input)

    async def async_step_user(self, user_input=None):
        return await self._step("user", user_input, "learning")
