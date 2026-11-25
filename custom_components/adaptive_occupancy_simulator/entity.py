"""Push-updated entities sharing one AOS device."""

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity

from .const import DOMAIN, NAME, VERSION


class AOSEntity(Entity):
    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, runtime, key, name):
        self.runtime = runtime
        self.key = key
        self._attr_unique_id = f"{runtime.entry.entry_id}_{key}"
        self._attr_name = name
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, runtime.entry.entry_id)},
            name=NAME,
            manufacturer="AOS",
            model="Local occupancy simulator",
            sw_version=VERSION,
        )

    async def async_added_to_hass(self):
        self.runtime.listeners.add(self.async_write_ha_state)
        self.async_on_remove(lambda: self.runtime.listeners.discard(self.async_write_ha_state))
