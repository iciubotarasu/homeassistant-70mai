"""Constants for the 70mai dashcam integration."""
from __future__ import annotations

from datetime import timedelta

DOMAIN = "mai70"

CONF_UUID = "uuid"
# Config-entry key holding the resolved 70mai API base URL. Entries created
# before region support don't have it and keep using SERVER_EU.
CONF_BASE_URL = "base_url"
# Config-flow-only field: one of SERVER_CHOICES' keys, SERVER_AUTO, or a
# server address typed by hand (the selector accepts custom values).
CONF_SERVER = "server"

# 70mai account data lives on one regional server, and a login against the
# wrong one fails like a bad password. Known hosts (2026-11):
# - eu: the one every request in client70mai's captures went to.
# - int: the 70mai app's built-in default (assets/config/app_config.json
#   in the 4.0.0 APK); confirmed working by an Australian user (issue #2).
# - us: answers like a 70mai API to an anonymous probe, but no user has
#   confirmed logging in there yet.
# The app itself learns its real server at runtime from a downloaded
# config, so this list may be incomplete; that's why the config flow also
# accepts a server address typed by hand.
SERVER_EU = "https://eu-api.70mai.com"
SERVER_INT = "https://int-api.70mai.com"
SERVER_US = "https://us-api.70mai.com"
SERVER_AUTO = "auto"
# Also the order SERVER_AUTO tries them in.
SERVER_CHOICES = {
    "eu": SERVER_EU,
    "int": SERVER_INT,
    "us": SERVER_US,
}

DEFAULT_SCAN_INTERVAL = timedelta(minutes=5)

# The main coordinator runs every ALARM_SCAN_INTERVAL so a new alarm shows
# up within a minute, but only the alarm endpoints are called on every run.
# Everything else is cached and re-fetched only once it is older than its
# group's interval: fast-changing data (battery, dashcam status, signal)
# after DETAIL_REFRESH_INTERVAL, data that practically never changes
# (device list, account country, firmware, SIM plugin, upload switch, SIM
# external power) after STATIC_REFRESH_INTERVAL. That is fewer requests per
# hour than the old "everything every 5 minutes" poll. While Firebase push
# is connected (push.py), alarms arrive by push and the alarm poll slows to
# ALARM_SCAN_INTERVAL_PUSH as a safety net.
ALARM_SCAN_INTERVAL = timedelta(minutes=1)
ALARM_SCAN_INTERVAL_PUSH = timedelta(minutes=5)
DETAIL_REFRESH_INTERVAL = timedelta(minutes=5)
STATIC_REFRESH_INTERVAL = timedelta(hours=1)

# A collision alarm (101) is first reported as "suspected" (eventStatus 1)
# and resolved later by 70mai to "normal boarding" (2, the owner got in) or
# "collision confirmed" (3, with a clip). Unresolved ones are re-checked
# with getDeviceAlarm on every poll for this long.
COLLISION_TRACK_TIMEOUT = timedelta(minutes=30)

# Alarm names and descriptions, as the 70mai Android app (4.5.0,
# com.banyac.dashcam.model.DeviceAlarm.getAlarmTitle/getAlarmDetail and its
# English strings) shows them. 101 depends on eventStatus.
ALARM_COLLISION = 101
COLLISION_SUSPECTED = 1
COLLISION_BOARDING = 2
COLLISION_CONFIRMED = 3
COLLISION_NAMES = {
    COLLISION_SUSPECTED: (
        "Vehicle suspected of collision",
        "Collision occurs. Please view your vehicle status.",
    ),
    COLLISION_BOARDING: (
        "Normal boarding behavior",
        "Your vehicle starts normally. Cancelling collision warning.",
    ),
    COLLISION_CONFIRMED: (
        "Vehicle collision detected",
        "Collision has been detected. Please check your vehicle status.",
    ),
}
ALARM_NAMES = {
    102: ("Vehicle driving out of the geo-fence", "The vehicle left a geo-fence."),
    103: ("Remote surveillance video", "Remotely filmed video uploaded."),
    104: (
        "Overheat protection",
        "Ambient temperature high, Dash Cam is shutting down for protection.",
    ),
    105: (
        "Battery protection",
        "The vehicle battery voltage has dropped to the protection value you "
        "set, and the Dash Cam automatically powers off.",
    ),
    106: ("Remote surveillance photo", "Your remotely taken image has been uploaded."),
    107: (
        "Suspicious persons detected",
        "There are suspicious persons around your vehicle. Please promptly "
        "check the vehicle status.",
    ),
    108: (
        "Parking surveillance global timer",
        "Dash Cam has turned off as scheduled by the parking surveillance "
        "global duration, to save car battery power.",
    ),
    109: ("Vehicle entered the geo-fence", "The vehicle entered a geo-fence."),
}


def alarm_name(alarm_type, event_status=None):
    """(name, description) for an alarm, or (None, None) for an unknown code."""
    try:
        alarm_type = int(alarm_type)
    except (TypeError, ValueError):
        return None, None
    if alarm_type == ALARM_COLLISION:
        return COLLISION_NAMES.get(event_status, COLLISION_NAMES[COLLISION_SUSPECTED])
    return ALARM_NAMES.get(alarm_type, (None, None))

# getPosition has its own faster, adaptive poll
# (coordinator.Mai70PositionCoordinator) instead of riding along with the
# DEFAULT_SCAN_INTERVAL poll of every other endpoint. A dashcam that is
# driving keeps pushing its position to 70mai's cloud every few seconds
# (lastUpdateTime was ~11s old in a capture taken while driving), a parked
# one stops (~10 min old in a parked capture), so the age of the newest
# lastUpdateTime picks the interval: ACTIVE while any device's position is
# at most POSITION_ACTIVE_MAX_AGE old, IDLE otherwise.
# getPosition's own "status" field (2 while driving, 3 while parked in
# those same two captures) looks like it says the same thing, but its
# meaning isn't documented, so the confirmed timestamp is used instead.
POSITION_SCAN_INTERVAL_ACTIVE = timedelta(seconds=60)
POSITION_SCAN_INTERVAL_IDLE = timedelta(minutes=2)
POSITION_ACTIVE_MAX_AGE = timedelta(minutes=3)

# get_device_status_history_daily() keyIndex/smartType for battery voltage
# telemetry (see client70mai.client.MaiClient docstring for details).
BATTERY_KEY_INDEX = "1.4"
BATTERY_SMART_TYPE = 51

# check_new_rom_from_app() requires a client-reported base_version/
# base_subversion to run the update check at all, but the version it
# actually needs to report back the dashcam's current firmware
# (resultBodyObject.version) doesn't depend on what's passed here, so a
# fixed placeholder is used instead of tracking a real "last known"
# version across polls.
FIRMWARE_CHECK_BASE_VERSION = "0.0.0"
FIRMWARE_CHECK_BASE_SUBVERSION = "0"

# 70mai's API only allows one active session per account: logging into
# the mobile app invalidates this integration's token. After detecting
# that, wait this long before logging back in, so the integration
# doesn't immediately kick the app's own session back out again.
TOKEN_INVALID_RELOGIN_DELAY = timedelta(minutes=5)

MANUFACTURER = "70mai"
