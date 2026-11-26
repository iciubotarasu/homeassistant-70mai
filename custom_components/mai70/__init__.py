"""The 70mai Dashcam integration."""
from __future__ import annotations

import uuid as uuid_module

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD, Platform
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
)
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType

from client70mai import MaiClient

from .const import CONF_BASE_URL, CONF_PUSH, CONF_UUID, DOMAIN, SERVER_EU
from .coordinator import Mai70Coordinator
from .push import Mai70Push

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

SERVICE_FETCH_ALARM_VIDEOS = "fetch_alarm_videos"
ATTR_HOURS = "hours"
FETCH_ALARM_VIDEOS_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_HOURS, default=24): vol.All(
            vol.Coerce(float), vol.Range(min=0.1, max=168)
        )
    }
)

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.DEVICE_TRACKER,
    Platform.EVENT,
    Platform.IMAGE,
    Platform.SENSOR,
    Platform.SWITCH,
]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the integration-wide services."""

    async def _fetch_alarm_videos(call: ServiceCall) -> ServiceResponse:
        queued = 0
        for coordinator in hass.data.get(DOMAIN, {}).values():
            queued += await coordinator.async_requeue_alarm_videos(call.data[ATTR_HOURS])
        return {"queued_alarms": queued}

    hass.services.async_register(
        DOMAIN,
        SERVICE_FETCH_ALARM_VIDEOS,
        _fetch_alarm_videos,
        schema=FETCH_ALARM_VIDEOS_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up 70mai from a config entry."""
    device_uuid = entry.data.get(CONF_UUID) or str(uuid_module.uuid4()).upper()
    # Entries from before region support have no base URL: they were all
    # created against the EU server.
    client = MaiClient(
        uuid=device_uuid, base_url=entry.data.get(CONF_BASE_URL, SERVER_EU)
    )

    coordinator = Mai70Coordinator(
        hass,
        client,
        entry.data[CONF_EMAIL],
        entry.data[CONF_PASSWORD],
        entry_id=entry.entry_id,
    )
    await coordinator.async_load_state()
    await coordinator.async_config_entry_first_refresh()
    # Needs the device list from the main coordinator's first refresh.
    await coordinator.position_coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    entry.async_on_unload(entry.add_update_listener(_async_options_updated))
    if entry.options.get(CONF_PUSH, True):
        push = Mai70Push(hass, coordinator, entry.entry_id)
        coordinator.push = push
        coordinator._on_shutdown.append(push.async_stop)
        # In the background: Firebase registration takes a few seconds and
        # must not hold up setup; polling works meanwhile.
        entry.async_create_background_task(hass, push.async_start(), f"{DOMAIN}_push_start")
    return True


async def _async_options_updated(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        coordinator = hass.data[DOMAIN].pop(entry.entry_id)
        await coordinator.async_shutdown_extras()
    return unloaded
