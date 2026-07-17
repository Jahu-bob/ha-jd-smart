"""Constants for the JD Smart integration."""

from datetime import timedelta
import logging

DOMAIN = "jd_smart"
LOGGER = logging.getLogger(__package__)

DEFAULT_SCAN_INTERVAL = timedelta(seconds=60)
FAST_POLL_INTERVAL = timedelta(seconds=2)
FAST_POLL_DURATION = timedelta(seconds=10)

CONF_APP_VERSION = "app_version"
CONF_CHANNEL = "channel"
CONF_COOKIE = "cookie"
CONF_DEVICE_ID = "device_id"
CONF_DEVICE_MODEL = "device_model"
CONF_DEVICE_NAME = "device_name"
CONF_DEVICES = "devices"
CONF_FEED_ID = "feed_id"
CONF_PLATFORM = "platform"
CONF_PLATFORM_VERSION = "platform_version"
CONF_PIN = "pin"
CONF_SGM_CONTEXT = "sgm_context"
CONF_TGT = "tgt"
CONF_USER_AGENT = "user_agent"

DEFAULT_APP_VERSION = "2.2.0"
DEFAULT_CHANNEL = "76161171"
DEFAULT_DEVICE_ID = "1780721316039153856527"
DEFAULT_DEVICE_MODEL = "Pixel 8"
DEFAULT_PLATFORM = "Android"
DEFAULT_PLATFORM_VERSION = "14"
DEFAULT_USER_AGENT = "android"

JD_SMART_BASE_URL = "https://api.smart.jd.com"
SNAPSHOT_PATH = "/c/service/integration/v1/getDeviceSnapshot_v1"
CONTROL_PATH = "/c/service/integration/v1/controlDevice_v1"
DEVICE_LIST_PATH = "/c/service/devmanager/v2/getDevicesAndCategory"

# gw.smart.jd.com gateway: device model (getDeviceDetails). Same HmacSHA1 signing
# as api.smart.jd.com (identical seg1/key), only the base/path/body differ. Used to
# discover each device's full stream model (controllable streams, options, ranges).
GW_API_BASE = "https://gw.smart.jd.com"
GW_DETAILS_PATH = "/c/service/devmanager/v1/getDeviceDetails"

APP_KEY = "a188caaf009839ba200bb55bb8fa38407a595c2a"
HMAC_KEY = "e685c8d1daa7e4dec8821a3df41c0b34a56db779"

ATTR_MANUFACTURER = "JD Smart"
UPDATE_AUTH_FAILURE_THRESHOLD = 3

# Services exposed for diagnostics / manual control of any device type.
SERVICE_GET_SNAPSHOT = "get_device_snapshot"
SERVICE_CONTROL_DEVICE = "control_device"
SERVICE_GET_DEVICE_MODEL = "get_device_model"
ATTR_FEED_ID = "feed_id"
ATTR_STREAM_ID = "stream_id"
ATTR_VALUE = "value"
ATTR_COMMAND = "command"

# Per-device fields stored inside the CONF_DEVICES list items. category / house_id /
# card_meta are captured best-effort during discovery; older entries that lack them
# fall back to stream-based detection / card_meta-less model / manual control.
CONF_CATEGORY = "category"
CONF_HOUSE_ID = "house_id"
CONF_CARD_META = "card_meta"
CONF_STREAMS = "streams"

# stream_ids that strongly indicate an air conditioner (orangeboyChen's AC uses
# lowercase streams: settemp = target temp, mode = hvac mode, mark = fan speed).
# A gas water heater or purifier is unlikely to expose all three.
AC_STREAM_HINTS = frozenset({"settemp", "mode", "mark"})


def is_air_conditioner(category: str | None, streams: dict[str, str]) -> bool:
    """Return True if a device should be exposed via the climate platform.

    Category name is authoritative when present; otherwise fall back to detecting
    the AC-specific stream combo (handles older config entries without category).
    """
    if category:
        lowered = category.lower()
        if "空调" in category or ("air" in lowered and "cond" in lowered):
            return True
    return AC_STREAM_HINTS <= set(streams)
