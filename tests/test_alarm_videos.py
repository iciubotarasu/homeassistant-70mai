"""Tests for resolving an alarm's uploaded clips (attachment ->
getFileDetails -> pre-signed mainUrl) and the "video" event."""
from __future__ import annotations

import json
from typing import Any, Dict, List

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from custom_components.mai70.const import DOMAIN
from custom_components.mai70.coordinator import _parse_attachments

from .conftest import DEVICE_ID, FakeMaiClient, ok, setup_integration

FRONT_ID = "20f4cdc04b09414582c217db2d7c35d6"
REAR_ID = "bbbb0000bbbb0000bbbb0000bbbb0000"
FRONT_URL = "https://eu4gmedia.70mai.com/front.MP4?sign=x"
REAR_URL = "https://eu4gmedia.70mai.com/rear.MP4?sign=y"


def _alarm(attachment: Any) -> Dict[str, Any]:
    return {
        "id": "118546995",
        "alramType": 107,
        "happenTime": 1795668897000,
        "coordinatesLat": 44.39,
        "coordinatesLng": 26.10,
        "pictureUrl": None,
        "videoUrl": None,
        "coverUrl": "https://eu4gmedia.70mai.com/cover.JPG?sign=z",
        "attachment": attachment,
    }


def _file(file_id: str, url: str) -> Dict[str, Any]:
    return {
        "fileId": file_id,
        "fileOrigName": f"{file_id}.MP4",
        "fileStatus": 3,
        "mainUrl": url,
        "mainSize": 1000,
        "videoCoverUrl": url + "&cover",
    }


class AlarmClient(FakeMaiClient):
    def __init__(self) -> None:
        super().__init__()
        self.alarms: List[Dict[str, Any]] = []
        self.files: Dict[str, Dict[str, Any]] = {}

    def get_device_alarm_list(self, *args: Any) -> Dict[str, Any]:
        self.calls.append(("get_device_alarm_list", args))
        self._require_token()
        return ok(self.alarms)

    def get_file_details(self, file_ids: List[str]) -> Dict[str, Any]:
        self.calls.append(("get_file_details", (file_ids,)))
        self._require_token()
        return ok([self.files[f] for f in file_ids if f in self.files])


def test_parse_attachments() -> None:
    raw = json.dumps(
        [
            {"key": "front_video", "userspaceFileId": FRONT_ID},
            {"key": "backend_video", "userspaceFileId": REAR_ID},
            {"key": "broken"},
        ]
    )
    assert _parse_attachments({"attachment": raw}) == {
        "front_video": FRONT_ID,
        "backend_video": REAR_ID,
    }
    assert _parse_attachments({"attachment": None}) == {}
    assert _parse_attachments({"attachment": "not json"}) == {}


async def test_video_event_after_upload(hass: HomeAssistant) -> None:
    client = AlarmClient()
    entry = await setup_integration(hass, client)
    coordinator = hass.data[DOMAIN][entry.entry_id]
    entity_id = er.async_get(hass).async_get_entity_id("event", DOMAIN, f"{DEVICE_ID}_alarm")

    client.alarms = [
        _alarm(
            json.dumps(
                [
                    {"key": "front_video", "userspaceFileId": FRONT_ID},
                    {"key": "backend_video", "userspaceFileId": REAR_ID},
                ]
            )
        )
    ]
    await coordinator.async_refresh()
    await hass.async_block_till_done()

    # First poll: the alarm is seen, no clip is uploaded yet.
    state = hass.states.get(entity_id)
    assert state.attributes["event_type"] == "alarm"
    assert state.attributes["video_url"] is None

    # Only the front clip is up: still waiting for the rear one.
    client.files[FRONT_ID] = _file(FRONT_ID, FRONT_URL)
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get(entity_id).attributes["event_type"] == "alarm"

    # Both clips are up: one "video" event with both URLs.
    client.files[REAR_ID] = _file(REAR_ID, REAR_URL)
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    state = hass.states.get(entity_id)
    assert state.attributes["event_type"] == "video"
    assert state.attributes["alarm_id"] == "118546995"
    assert state.attributes["video_url"] == FRONT_URL
    assert state.attributes["videos"]["backend_video"]["url"] == REAR_URL
    assert state.attributes["complete"] is True

    # Reported once only: later polls don't look the clips up again.
    calls = client.call_count("get_file_details")
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert client.call_count("get_file_details") == calls


async def test_fetch_alarm_videos_service(hass: HomeAssistant) -> None:
    """An alarm already seen (e.g. on the setup poll, before the event
    entity existed) gets its "video" event through the service."""
    client = AlarmClient()
    client.alarms = [_alarm(json.dumps([{"key": "front_video", "userspaceFileId": FRONT_ID}]))]
    client.files[FRONT_ID] = _file(FRONT_ID, FRONT_URL)
    await setup_integration(hass, client)
    entity_id = er.async_get(hass).async_get_entity_id("event", DOMAIN, f"{DEVICE_ID}_alarm")
    # The setup poll saw the alarm before the entity existed: no event.
    assert hass.states.get(entity_id).attributes.get("event_type") is None

    response = await hass.services.async_call(
        DOMAIN, "fetch_alarm_videos", {"hours": 24}, blocking=True, return_response=True
    )
    await hass.async_block_till_done()
    assert response == {"queued_alarms": 1}
    state = hass.states.get(entity_id)
    assert state.attributes["event_type"] == "video"
    assert state.attributes["video_url"] == FRONT_URL
