"""Alarm event platform for the 70mai integration.

One event entity per dashcam, with three event types:

- "alarm": a new alarm was reported. alarm_name/alarm_description are the
  texts the 70mai app shows for it (see const.ALARM_NAMES).
- "alarm_update": 70mai resolved a collision alarm (101) reported earlier as
  "suspected": event_status 2 means normal boarding (the owner got in, the
  warning is cancelled), 3 means the collision is confirmed (a clip follows).
- "video": an alarm's uploaded clips got pre-signed download URLs, usually a
  few minutes after its "alarm".
"""
from __future__ import annotations

from typing import Any, Dict

from homeassistant.components.event import EventEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import Mai70Coordinator
from .entity import Mai70Entity, async_setup_dynamic_entities

_ALARM_FIELDS = (
    "alarm_id",
    "alarm_type",
    "alarm_name",
    "alarm_description",
    "event_status",
    "alarm_time",
    "happen_time",
    "latitude",
    "longitude",
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: Mai70Coordinator = hass.data[DOMAIN][entry.entry_id]
    async_setup_dynamic_entities(
        coordinator,
        async_add_entities,
        entity_factory=lambda device_id: Mai70AlarmEvent(coordinator, device_id),
    )


class Mai70AlarmEvent(Mai70Entity, EventEntity):
    """Fires once for each new alarm, collision resolution and clip set."""

    _attr_translation_key = "alarm"
    _attr_name = None
    _attr_event_types = ["alarm", "alarm_update", "video"]
    _attr_icon = "mdi:bell-alert-outline"

    def __init__(self, coordinator: Mai70Coordinator, device_id: str) -> None:
        super().__init__(coordinator, device_id)
        self._attr_unique_id = f"{device_id}_alarm"

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        # The poll that ran during setup (e.g. right after a restart) came
        # before this entity existed: report what it found now.
        self._fire_events()

    @callback
    def _handle_coordinator_update(self) -> None:
        self._fire_events()
        super()._handle_coordinator_update()

    @callback
    def _fire(self, event_type: str, data: Dict[str, Any]) -> None:
        self._trigger_event(event_type, data)
        # One state write per event: EventEntity only keeps the last
        # _trigger_event() until the state is written, so several events
        # in one poll would otherwise reach automations as just one.
        self.async_write_ha_state()

    @callback
    def _fire_events(self) -> None:
        data = self._device_data
        for alarm in data.get("new_alarms", []):
            self._fire(
                "alarm",
                {
                    **{k: alarm.get(k) for k in _ALARM_FIELDS},
                    "picture_url": alarm.get("picture_url"),
                    "video_url": alarm.get("video_url"),
                    "cover_url": alarm.get("cover_url"),
                    "raw": alarm["raw"],
                },
            )
        for alarm in data.get("alarm_updates", []):
            self._fire(
                "alarm_update",
                {
                    **{k: alarm.get(k) for k in _ALARM_FIELDS},
                    "cover_url": alarm.get("cover_url"),
                    "raw": alarm["raw"],
                },
            )
        for alarm in data.get("new_videos", []):
            videos = alarm.get("videos") or {}
            main = videos.get("front_video") or next(iter(videos.values()), {})
            self._fire(
                "video",
                {
                    **{k: alarm.get(k) for k in _ALARM_FIELDS},
                    "video_url": main.get("url"),
                    "cover_url": main.get("cover_url") or alarm.get("cover_url"),
                    "videos": videos,
                    "complete": alarm.get("complete"),
                },
            )
        # Consume them: a later write (another platform's refresh, a
        # restart of the entity) must not report them a second time.
        for key in ("new_alarms", "alarm_updates", "new_videos"):
            if data.get(key):
                data[key] = []
