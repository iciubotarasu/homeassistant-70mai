"""Firebase (FCM) push for the 70mai integration.

The 70mai app learns about alarms from Firebase push notifications, not by
polling (com.banyac.push.firebase.FirebaseMessageService in the Android
app 4.5.0: the payload carries a "70maiData" JSON string). This module
registers Home Assistant as one more Firebase client of the 70mai app's
Firebase project, hands its token to 70mai (userLoginPwd's deviceToken and
updateDeviceToken), and on every push refreshes the coordinator at once,
so a new alarm reaches Home Assistant within seconds instead of at the
next poll. The poll keeps running, slower, as a safety net.

70mai keeps one push token per account (as it keeps one session): while
Home Assistant holds the token, the phone app stops getting alarm pushes
until it logs in again. That is the point here (Home Assistant notifies
instead), but it is why push can be switched off (CONF_PUSH).

Same approach and library as Home Assistant's own Ring integration.
"""
from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any, Dict, Optional

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.storage import Store

from .const import DOMAIN

if TYPE_CHECKING:
    from .coordinator import Mai70Coordinator

_LOGGER = logging.getLogger(__name__)

# The 70mai Android app's Firebase client config (res/values/strings.xml of
# com.banyac.midrive.app 4.5.0: project_id, google_app_id,
# gcm_defaultSenderId, google_api_key). These ship inside the public app.
FCM_PROJECT_ID = "maina-286912"
FCM_APP_ID = "1:252046607293:android:fcf9c8d2435b8e920208d4"
FCM_SENDER_ID = "252046607293"
FCM_API_KEY = "AIzaSyBSpm3p6XWd9n-ZBYKTHFdHYn6EtwDMlH8"

EVENT_PUSH = f"{DOMAIN}_push"
_STORE_VERSION = 1


class Mai70Push:
    """Owns the FCM client of one config entry."""

    def __init__(self, hass: HomeAssistant, coordinator: "Mai70Coordinator", entry_id: str) -> None:
        self.hass = hass
        self.coordinator = coordinator
        self._store: Store = Store(hass, _STORE_VERSION, f"{DOMAIN}.{entry_id}.fcm")
        self._client: Any = None
        self.token: Optional[str] = None
        self.last_message: Optional[Dict[str, Any]] = None

    async def async_start(self) -> bool:
        """Register with Firebase and start listening. False (and polling
        only) if anything fails: push is an optimisation, never required."""
        try:
            from firebase_messaging import FcmPushClient, FcmRegisterConfig
        except ImportError:  # pragma: no cover - dependency missing
            _LOGGER.warning("firebase-messaging is not installed; 70mai push disabled")
            return False

        stored = await self._store.async_load() or {}
        config = FcmRegisterConfig(
            project_id=FCM_PROJECT_ID,
            app_id=FCM_APP_ID,
            api_key=FCM_API_KEY,
            messaging_sender_id=FCM_SENDER_ID,
        )
        self._client = FcmPushClient(
            self._on_message,
            config,
            stored.get("credentials"),
            self._on_credentials_updated,
            received_persistent_ids=stored.get("persistent_ids") or [],
            http_client_session=async_get_clientsession(self.hass),
        )
        try:
            self.token = await self._client.checkin_or_register()
        except Exception as exc:  # noqa: BLE001 - library raises many types
            _LOGGER.warning("70mai push: Firebase registration failed (%s); polling only", exc)
            self._client = None
            return False

        if not await self.coordinator.async_set_push_token(self.token):
            _LOGGER.warning("70mai push: 70mai did not accept the push token; polling only")
            self._client = None
            return False

        await self._client.start()
        self.coordinator.set_push_active(True)
        _LOGGER.info("70mai push: listening for alarm notifications")
        return True

    async def async_stop(self) -> None:
        self.coordinator.set_push_active(False)
        if self._client is not None:
            await self._client.stop()
            self._client = None

    @callback
    def _on_credentials_updated(self, credentials: Dict[str, Any]) -> None:
        self._store.async_delay_save(lambda: {"credentials": credentials}, 1)

    def _on_message(self, notification: Dict[str, Any], persistent_id: str, _obj: Any = None) -> None:
        # Called from the FCM client's task, in the event loop.
        data = notification.get("data") if isinstance(notification.get("data"), dict) else notification
        payload: Any = data.get("70maiData") if isinstance(data, dict) else None
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except ValueError:
                pass
        self.last_message = {"notification": notification, "payload": payload}
        _LOGGER.debug("70mai push %s: %s", persistent_id, notification)
        self.hass.bus.async_fire(EVENT_PUSH, {"payload": payload, "raw": notification})
        credentials = self._client.credentials if self._client else None
        ids = (self._client.persistent_ids if self._client else [])[-50:]
        self._store.async_delay_save(
            lambda: {"credentials": credentials, "persistent_ids": ids}, 5
        )
        self.hass.async_create_task(self.coordinator.async_refresh_from_push())
