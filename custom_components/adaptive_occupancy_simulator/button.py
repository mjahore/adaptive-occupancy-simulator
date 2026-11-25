"""Native actions for maintenance and emergency stop."""

from homeassistant.components.button import ButtonEntity

from .entity import AOSEntity

BUTTONS = {
    "stop": "Stop",
    "import_history": "Import history",
    "retrain": "Retrain",
    "regenerate": "Regenerate preview",
    "clear_overrides": "Clear overrides",
}


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([AOSButton(entry.runtime_data, key, name) for key, name in BUTTONS.items()])


class AOSButton(AOSEntity, ButtonEntity):
    async def async_press(self):
        r = self.runtime
        if self.key == "stop":
            await r.set_enabled(False)
        elif self.key == "import_history":
            await r.train(import_history=True)
        elif self.key == "retrain":
            await r.train()
        elif self.key == "regenerate":
            await r.regenerate()
        else:
            r.overrides.clear()
            r.save_later()
            r.publish()
