"""Adaptive Occupancy Simulator custom integration."""

from datetime import datetime

import voluptuous as vol
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED, EVENT_HOMEASSISTANT_STOP, Platform
from homeassistant.core import callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_registry as er

from .const import DOMAIN
from .frontend import async_setup_frontend
from .runtime import Runtime

PLATFORMS = [Platform.SWITCH, Platform.SENSOR, Platform.BINARY_SENSOR, Platform.BUTTON]
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass, config):
    """Register actions once; no YAML configuration is required."""

    async def handle(call):
        entries = [
            entry
            for entry in hass.config_entries.async_entries(DOMAIN)
            if hasattr(entry, "runtime_data") and isinstance(entry.runtime_data, Runtime)
        ]
        if len(entries) != 1:
            raise HomeAssistantError("Configure and load AOS first")
        runtime = entries[0].runtime_data
        if call.service == "stop":
            await runtime.set_enabled(False)
        elif call.service == "retrain":
            await runtime.train()
        elif call.service == "import_history":
            await runtime.train(import_history=True)
        elif call.service == "regenerate":
            await runtime.regenerate()
        elif call.service == "clear_overrides":
            runtime.overrides.clear()
            runtime.save_later()
            runtime.publish()
        elif call.service == "exclude_period":
            try:
                start, end = (datetime.fromisoformat(call.data[k]) for k in ("start", "end"))
            except ValueError as err:
                raise ServiceValidationError("Use ISO timestamps with timezone offsets") from err
            if not start.tzinfo or not end.tzinfo or end <= start:
                raise ServiceValidationError("Use ISO timestamps with a timezone; end must follow start")
            await runtime.exclude(start, end, call.data["reason"])

    for name in ("stop", "retrain", "import_history", "regenerate", "clear_overrides", "exclude_period"):
        schema = (
            vol.Schema(
                {
                    vol.Required("start"): cv.string,
                    vol.Required("end"): cv.string,
                    vol.Optional("reason", default="Manual exclusion"): cv.string,
                }
            )
            if name == "exclude_period"
            else vol.Schema({})
        )
        hass.services.async_register(DOMAIN, name, handle, schema=schema)
    await async_setup_frontend(hass)
    return True


async def async_setup_entry(hass, entry):
    runtime = Runtime(hass, entry)
    entry.runtime_data = runtime
    try:
        await runtime.initialize()
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    except Exception:
        await runtime.shutdown()
        raise
    runtime.aos_entity = er.async_get(hass).async_get_entity_id("switch", DOMAIN, f"{entry.entry_id}_enabled")
    entry.async_on_unload(entry.add_update_listener(_options_updated))

    @callback
    def start(_event=None):
        runtime.spawn(runtime.train(import_history=True), "startup import")

    if hass.is_running:
        start()
    else:
        entry.async_on_unload(hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STARTED, start))

    async def stop(_event):
        await runtime.shutdown()

    entry.async_on_unload(hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, stop))
    return True


async def _options_updated(hass, entry):
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass, entry):
    runtime = entry.runtime_data
    # Stop scheduling before platform teardown. Unload failure also stays inert.
    await runtime.shutdown()
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
