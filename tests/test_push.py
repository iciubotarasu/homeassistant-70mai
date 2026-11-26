"""Firebase push: registration, token hand-off to 70mai, and a push
triggering an immediate alarm poll."""
from __future__ import annotations

from typing import Any, Dict, List
from unittest.mock import patch

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from custom_components.mai70.const import ALARM_SCAN_INTERVAL_PUSH, DOMAIN

from .conftest import DEVICE_ID, FakeMaiClient, ok, setup_integration


class FakeFcm:
    instances: List["FakeFcm"] = []

    def __init__(self, callback, config, credentials=None, credentials_updated_callback=None, **kwargs):
        self.callback = callback
        self.config = config
        self.credentials = credentials or {}
        self.persistent_ids: list = []
        self.started = False
        FakeFcm.instances.append(self)

    async def checkin_or_register(self) -> str:
        return "fcm-token"

    async def start(self) -> None:
        self.started = True

    async def stop(self) -> None:
        self.started = False


class PushClient(FakeMaiClient):
    def __init__(self) -> None:
        super().__init__()
        self.alarms: List[Dict[str, Any]] = []
        self.registered_tokens: List[str] = []

    def update_device_token(self, token: str) -> Dict[str, Any]:
        self.calls.append(("update_device_token", (token,)))
        self.registered_tokens.append(token)
        return ok(True)

    def get_device_alarm_list(self, *args: Any) -> Dict[str, Any]:
        self.calls.append(("get_device_alarm_list", args))
        self._require_token()
        return ok(self.alarms)


async def test_push_registers_and_refreshes(hass: HomeAssistant) -> None:
    FakeFcm.instances.clear()
    client = PushClient()
    with patch("firebase_messaging.FcmPushClient", FakeFcm):
        entry = await setup_integration(hass, client, options={"push": True})
        await hass.async_block_till_done(wait_background_tasks=True)

    fcm = FakeFcm.instances[-1]
    assert fcm.started
    assert fcm.config.project_id == "maina-286912"
    assert client.device_token == "fcm-token"
    assert "fcm-token" in client.registered_tokens
    # Logged in again as the Android app, with the token.
    assert client.login_device_types[-1] == 2
    coordinator = hass.data[DOMAIN][entry.entry_id]
    assert coordinator.push_active
    assert coordinator.update_interval == ALARM_SCAN_INTERVAL_PUSH
    sensor = er.async_get(hass).async_get_entity_id("binary_sensor", DOMAIN, f"{DEVICE_ID}_push_connected")
    assert hass.states.get(sensor).state == "on"

    # A push arrives for a new alarm: the alarm list is read right away.
    client.alarms = [
        {"id": "p1", "alramType": 107, "createTimestamp": 1_795_680_539_000, "coverUrl": None}
    ]
    events: list = []
    hass.bus.async_listen(f"{DOMAIN}_push", lambda e: events.append(e.data))
    fcm.callback({"data": {"70maiData": '{"alarmId": "p1"}'}}, "pid-1", None)
    await hass.async_block_till_done(wait_background_tasks=True)
    # Debounced refresh: give it its cooldown.
    from pytest_homeassistant_custom_component.common import async_fire_time_changed
    from homeassistant.util import dt as dt_util
    from datetime import timedelta

    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=11))
    await hass.async_block_till_done(wait_background_tasks=True)

    event_id = er.async_get(hass).async_get_entity_id("event", DOMAIN, f"{DEVICE_ID}_alarm")
    assert hass.states.get(event_id).attributes.get("alarm_id") == "p1"
    assert events and events[0]["payload"] == {"alarmId": "p1"}

    await hass.config_entries.async_unload(entry.entry_id)
    assert not fcm.started


async def test_android_login_refused_falls_back(hass: HomeAssistant) -> None:
    from client70mai.exceptions import MaiResponseFormatError

    class Refusing(PushClient):
        def login(self, email, plain_password, device_type=3):
            if device_type == 2:
                raise MaiResponseFormatError("no")
            return super().login(email, plain_password, device_type)

    FakeFcm.instances.clear()
    client = Refusing()
    with patch("firebase_messaging.FcmPushClient", FakeFcm):
        entry = await setup_integration(hass, client, options={"push": True})
        await hass.async_block_till_done(wait_background_tasks=True)
    assert client.login_device_types[-1] == 3
    assert "fcm-token" in client.registered_tokens
    assert hass.data[DOMAIN][entry.entry_id].push_active
    await hass.config_entries.async_unload(entry.entry_id)
