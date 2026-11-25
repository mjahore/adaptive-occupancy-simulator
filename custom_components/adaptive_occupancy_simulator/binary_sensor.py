"""Safety and model readiness indicators."""

from homeassistant.components.binary_sensor import BinarySensorEntity

from .entity import AOSEntity


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities(
        [
            AOSBinary(entry.runtime_data, "safe_to_simulate", "Safe to simulate"),
            AOSBinary(entry.runtime_data, "model_ready", "Model ready"),
        ]
    )


class AOSBinary(AOSEntity, BinarySensorEntity):
    @property
    def is_on(self):
        if self.key == "model_ready":
            return bool(self.runtime.model and self.runtime.model.ready)
        return not bool(self.runtime.reason())
