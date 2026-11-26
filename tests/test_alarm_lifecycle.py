"""Alarm names, collision resolution, persisted state across restarts,
the last-alarm image, the cloud-upload switch and the cached poll."""
from __future__ import annotations

from typing import Any, Dict, List
from unittest.mock import patch

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er

from custom_components.mai70.const import DOMAIN

from .conftest import DEVICE_ID, FakeMaiClient, ok, setup_integration

COVER = "https://eu4gmedia.70mai.com/cover.JPG?sign=z"


def _alarm(alarm_id: str, alarm_type: int, status: Any = None, created: int = 1_795_680_539_000) -> Dict[str, Any]:
    return {
        "id": alarm_id,
        "alramType": alarm_type,
        "eventStatus": status,
        "happenTime": created - 6 * 3600 * 1000,
        "createTimestamp": created,
        "coordinatesLat": 44.39,
        "coordinatesLng": 26.10,
        "coverUrl": COVER,
        "attachment": None,
    }


class Client(FakeMaiClient):
    def __init__(self) -> None:
        super().__init__()
        self.alarms: List[Dict[str, Any]] = []
        self.alarm_detail: Dict[str, Dict[str, Any]] = {}
        self.switch = {"monitorVedioUpload": True, "details": [{"eventType": 3, "resourceKeys": ["front_video"]}]}

    def get_device_alarm_list(self, *args: Any) -> Dict[str, Any]:
        self.calls.append(("get_device_alarm_list", args))
        self._require_token()
        return ok(self.alarms)

    def get_device_alarm(self, device_id: str, alarm_id: str) -> Dict[str, Any]:
        self.calls.append(("get_device_alarm", (device_id, alarm_id)))
        self._require_token()
        return ok(self.alarm_detail.get(alarm_id))

    def get_device_switch(self, device_id: str) -> Dict[str, Any]:
        self.calls.append(("get_device_switch", (device_id,)))
        self._require_token()
        return ok(self.switch)

    def set_device_switch(self, device_id: str, value: bool, details: list) -> Dict[str, Any]:
        self.calls.append(("set_device_switch", (device_id, value, details)))
        self._require_token()
        self.switch = {**self.switch, "monitorVedioUpload": value}
        return ok(True)


def _event_id(hass: HomeAssistant) -> str:
    return er.async_get(hass).async_get_entity_id("event", DOMAIN, f"{DEVICE_ID}_alarm")


def _record(hass: HomeAssistant, entity_id: str) -> list:
    seen: list = []

    @callback
    def _listener(event) -> None:
        if event.data["entity_id"] == entity_id and event.data["new_state"] is not None:
            seen.append(dict(event.data["new_state"].attributes))

    hass.bus.async_listen("state_changed", _listener)
    return seen


async def _refresh(hass: HomeAssistant, entry) -> None:
    await hass.data[DOMAIN][entry.entry_id].async_refresh()
    await hass.async_block_till_done()


async def test_names_and_collision_resolution(hass: HomeAssistant) -> None:
    client = Client()
    entry = await setup_integration(hass, client)
    events = _record(hass, _event_id(hass))

    client.alarms = [_alarm("a1", 101, 1), _alarm("a2", 107, created=1_795_680_600_000)]
    await _refresh(hass, entry)
    assert [(e["event_type"], e["alarm_name"]) for e in events] == [
        ("alarm", "Vehicle suspected of collision"),
        ("alarm", "Suspicious persons detected"),
    ]
    assert events[0]["alarm_time"].startswith("2026-11-26T")

    # Still unresolved: no update yet.
    client.alarm_detail["a1"] = _alarm("a1", 101, 1)
    await _refresh(hass, entry)
    assert len(events) == 2

    # 70mai resolves it as the owner getting in.
    client.alarm_detail["a1"] = _alarm("a1", 101, 2)
    await _refresh(hass, entry)
    assert events[-1]["event_type"] == "alarm_update"
    assert events[-1]["event_status"] == 2
    assert events[-1]["alarm_name"] == "Normal boarding behavior"

    # Resolved alarms aren't checked again.
    calls = client.call_count("get_device_alarm")
    await _refresh(hass, entry)
    assert client.call_count("get_device_alarm") == calls


async def test_first_install_reports_no_old_alarms(hass: HomeAssistant) -> None:
    client = Client()
    client.alarms = [_alarm("old", 107)]
    await setup_integration(hass, client)
    assert hass.states.get(_event_id(hass)).attributes.get("event_type") is None


async def test_restart_reports_missed_alarms_once(hass: HomeAssistant) -> None:
    client = Client()
    client.alarms = [_alarm("old", 107)]
    entry = await setup_integration(hass, client)

    # Restart: an alarm came in while HA was down.
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    client.alarms.append(_alarm("missed", 107, created=1_795_680_700_000))
    with patch("custom_components.mai70.MaiClient", return_value=client):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    state = hass.states.get(_event_id(hass))
    assert state.attributes["event_type"] == "alarm"
    assert state.attributes["alarm_id"] == "missed"

    # And nothing is reported again on the next poll.
    events = _record(hass, _event_id(hass))
    await _refresh(hass, entry)
    assert events == []


async def test_last_alarm_image(hass: HomeAssistant) -> None:
    client = Client()
    entry = await setup_integration(hass, client)
    client.alarms = [_alarm("a2", 107)]
    await _refresh(hass, entry)
    entity_id = er.async_get(hass).async_get_entity_id("image", DOMAIN, f"{DEVICE_ID}_last_alarm")
    assert entity_id is not None
    attrs = hass.states.get(entity_id).attributes
    assert attrs["alarm_name"] == "Suspicious persons detected"
    assert attrs["alarm_id"] == "a2"


async def test_cloud_upload_switch(hass: HomeAssistant) -> None:
    client = Client()
    await setup_integration(hass, client)
    entity_id = er.async_get(hass).async_get_entity_id(
        "switch", DOMAIN, f"{DEVICE_ID}_cloud_upload_switch"
    )
    assert hass.states.get(entity_id).state == "on"
    await hass.services.async_call("switch", "turn_off", {"entity_id": entity_id}, blocking=True)
    await hass.async_block_till_done()
    assert ("set_device_switch", (DEVICE_ID, False, client.switch["details"])) in client.calls
    assert hass.states.get(entity_id).state == "off"


async def test_static_data_is_cached_between_alarm_polls(hass: HomeAssistant) -> None:
    client = Client()
    entry = await setup_integration(hass, client)
    before = {name: client.call_count(name) for name in ("get_device_switch", "check_new_rom_from_app", "get_device_alarm_list")}
    await _refresh(hass, entry)
    assert client.call_count("get_device_switch") == before["get_device_switch"]
    assert client.call_count("check_new_rom_from_app") == before["check_new_rom_from_app"]
    assert client.call_count("get_device_alarm_list") == before["get_device_alarm_list"] + 1
