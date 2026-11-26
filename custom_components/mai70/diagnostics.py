"""Diagnostics for the 70mai integration: the alarm/push bookkeeping (no
credentials; URLs and the push token are redacted)."""
from __future__ import annotations

from typing import Any, Dict

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import HomeAssistant

from .const import DOMAIN

_REDACT = {CONF_EMAIL, CONF_PASSWORD, "token", "url", "video_url", "cover_url", "picture_url", "credentials"}


async def async_get_config_entry_diagnostics(hass: HomeAssistant, entry: ConfigEntry) -> Dict[str, Any]:
    coordinator = hass.data[DOMAIN][entry.entry_id]
    state = coordinator._state_for_store()
    return async_redact_data(
        {
            "options": dict(entry.options),
            "push_active": coordinator.push_active,
            "login_device_type": coordinator._login_device_type,
            "update_interval": str(coordinator.update_interval),
            "initial_sync": coordinator._initial_sync,
            "seen_counts": {dev: len(ids) for dev, ids in state["seen"].items()},
            "last_poll_ms": state["last_poll_ms"],
            "last_alarm": state["last_alarm"],
            "pending_videos": {dev: list(items) for dev, items in state["pending_videos"].items()},
            "collisions": {dev: list(items) for dev, items in state["collisions"].items()},
            "last_alarm_list_size": getattr(coordinator, "_last_alarm_list_size", None),
            "last_push": coordinator.push.last_message if coordinator.push else None,
        },
        _REDACT,
    )
