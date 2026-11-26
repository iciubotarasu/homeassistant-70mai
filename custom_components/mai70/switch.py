"""Cloud-upload switch for the 70mai integration: the "upload monitor
videos" toggle of the 70mai app (getDeviceSwitch/setDeviceSwitch's
monitorVedioUpload, request shape as the 70mai Android app 4.5.0 sends it:
deviceId, monitorVedioUpload and, when present, the per-event-type details
list, passed back unchanged)."""
from __future__ import annotations

from typing import Any, Dict

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from client70mai.exceptions import MaiError

from .const import DOMAIN
from .coordinator import Mai70Coordinator
from .entity import Mai70Entity, async_setup_dynamic_entities


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: Mai70Coordinator = hass.data[DOMAIN][entry.entry_id]
    async_setup_dynamic_entities(
        coordinator,
        async_add_entities,
        entity_factory=lambda device_id: Mai70CloudUploadSwitch(coordinator, device_id),
        should_add=lambda data: (data.get("device_switch") or {}).get("monitor_video_upload")
        is not None,
    )


class Mai70CloudUploadSwitch(Mai70Entity, SwitchEntity):
    _attr_translation_key = "cloud_upload"
    _attr_icon = "mdi:cloud-upload"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: Mai70Coordinator, device_id: str) -> None:
        super().__init__(coordinator, device_id)
        self._attr_unique_id = f"{device_id}_cloud_upload_switch"

    @property
    def _switch(self) -> Dict[str, Any]:
        return self._device_data.get("device_switch") or {}

    @property
    def is_on(self) -> bool | None:
        return self._switch.get("monitor_video_upload")

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._async_set(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._async_set(False)

    async def _async_set(self, value: bool) -> None:
        coordinator: Mai70Coordinator = self.coordinator
        try:
            await coordinator._async_ensure_logged_in()
            resp = await coordinator._async_call(
                coordinator.client.set_device_switch,
                self._device_id,
                value,
                self._switch.get("details") or [],
            )
        except MaiError as exc:
            raise HomeAssistantError(f"70mai rejected the change: {exc}") from exc
        if resp.get("error") or resp.get("resultBodyObject") is False:
            raise HomeAssistantError(
                f"70mai rejected the change: {resp.get('errorMessage') or resp}"
            )
        coordinator.invalidate_cache(self._device_id, "switch")
        await coordinator.async_request_refresh()
