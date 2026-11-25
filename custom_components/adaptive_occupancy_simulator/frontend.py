"""Bundled visual card, versioned Lovelace resource and authenticated read-only API."""

import logging
from pathlib import Path

import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.components.http import StaticPathConfig
from homeassistant.components.lovelace.const import LOVELACE_DATA
from homeassistant.components.lovelace.resources import ResourceStorageCollection

from .const import DOMAIN, VERSION
from .visuals import dashboard_data

_LOGGER = logging.getLogger(__name__)
CARD_PATH = "/aos-dashboard/aos-card.js"
CARD_URL = f"{CARD_PATH}?v={VERSION}"


async def async_setup_frontend(hass):
    await hass.http.async_register_static_paths(
        [StaticPathConfig(CARD_PATH, str(Path(__file__).parent / "www" / "aos-card.js"), False)]
    )
    websocket_api.async_register_command(hass, websocket_dashboard)
    resources = hass.data[LOVELACE_DATA].resources
    if isinstance(resources, ResourceStorageCollection):
        await resources.async_get_info()
        existing = next((r for r in resources.async_items() if r["url"].split("?")[0] == CARD_PATH), None)
        if existing:
            if existing["url"] != CARD_URL or existing["type"] != "module":
                await resources.async_update_item(existing["id"], {"url": CARD_URL, "res_type": "module"})
        else:
            await resources.async_create_item({"url": CARD_URL, "res_type": "module"})
    else:
        _LOGGER.info("AOS dashboard: add %s as a module in your YAML Lovelace resources", CARD_URL)


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/dashboard",
        vol.Optional("resample", default=False): bool,
        vol.Optional("day_offset", default=0): vol.All(int, vol.Range(min=0, max=1)),
        vol.Optional("solar_shift", default=0): vol.All(int, vol.Range(min=-120, max=120)),
    }
)
@websocket_api.require_admin
@websocket_api.async_response
async def websocket_dashboard(hass, connection, msg):
    entries = [
        e
        for e in hass.config_entries.async_entries(DOMAIN)
        if hasattr(e, "runtime_data") and not e.runtime_data.closed
    ]
    if len(entries) != 1:
        connection.send_error(msg["id"], "not_loaded", "AOS is not loaded. Check Devices & services.")
        return
    runtime = entries[0].runtime_data
    if hasattr(runtime, "visual_lock") and runtime.visual_lock.locked():
        connection.send_error(msg["id"], "busy", "AOS is preparing a chart. Try again shortly.")
        return
    result = await dashboard_data(
        runtime, resample=msg["resample"], day_offset=msg["day_offset"], solar_shift=msg["solar_shift"]
    )
    if runtime.closed:
        connection.send_error(msg["id"], "reloaded", "AOS configuration changed. Refresh the dashboard.")
        return
    connection.send_result(msg["id"], result)
