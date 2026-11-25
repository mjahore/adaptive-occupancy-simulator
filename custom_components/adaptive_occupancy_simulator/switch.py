"""Explicit enable intent and persistent, default-on dry-run controls."""

from homeassistant.components.switch import SwitchEntity
from homeassistant.const import EntityCategory

from .entity import AOSEntity


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities(
        [AOSSwitch(entry.runtime_data, "enabled", None), AOSSwitch(entry.runtime_data, "dry_run", "Dry run")]
    )


class AOSSwitch(AOSEntity, SwitchEntity):
    _attr_icon = "mdi:home-lightbulb"

    def __init__(self, runtime, key, name):
        super().__init__(runtime, key, name)
        if key == "dry_run":
            self._attr_entity_category = EntityCategory.CONFIG

    @property
    def is_on(self):
        return self.runtime.enabled if self.key == "enabled" else self.runtime.dry_run

    async def async_turn_on(self, **kwargs):
        await self._set(True)

    async def async_turn_off(self, **kwargs):
        await self._set(False)

    async def _set(self, value):
        if self.key == "enabled":
            await self.runtime.set_enabled(value)
        else:
            await self.runtime.set_dry_run(value)
