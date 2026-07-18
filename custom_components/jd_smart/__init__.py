"""The JD Smart integration."""

from __future__ import annotations

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import JdSmartClient, JdSmartCredentials, JdSmartDeviceProfile, JdSmartError
from .const import (
    ATTR_COMMAND,
    ATTR_FEED_ID,
    ATTR_STREAM_ID,
    ATTR_VALUE,
    CONF_APP_VERSION,
    CONF_CARD_META,
    CONF_CATEGORY,
    CONF_CHANNEL,
    CONF_COOKIE,
    CONF_DEVICE_NAME,
    CONF_DEVICES,
    CONF_DEVICE_ID,
    CONF_DEVICE_MODEL,
    CONF_FEED_ID,
    CONF_HOUSE_ID,
    CONF_PLATFORM,
    CONF_PLATFORM_VERSION,
    CONF_PIN,
    CONF_SGM_CONTEXT,
    CONF_TGT,
    CONF_USER_AGENT,
    DEFAULT_APP_VERSION,
    DEFAULT_CHANNEL,
    DEFAULT_DEVICE_ID,
    DEFAULT_DEVICE_MODEL,
    DEFAULT_PLATFORM,
    DEFAULT_PLATFORM_VERSION,
    DEFAULT_USER_AGENT,
    DOMAIN,
    SERVICE_CONTROL_DEVICE,
    SERVICE_GET_DEVICE_MODEL,
    SERVICE_GET_SNAPSHOT,
)
from .coordinator import JdSmartConfigEntry, JdSmartCoordinator, JdSmartRuntimeData
from .model import control_kind, parse_stream_model

PLATFORMS: list[Platform] = [
    Platform.CLIMATE,
    Platform.SWITCH,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.NUMBER,
    Platform.BINARY_SENSOR,
]


async def async_setup_entry(hass: HomeAssistant, entry: JdSmartConfigEntry) -> bool:
    """Set up JD Smart from a config entry."""
    client = JdSmartClient(
        async_get_clientsession(hass),
        JdSmartCredentials(
            cookie=entry.data[CONF_COOKIE],
            tgt=entry.data[CONF_TGT],
            pin=entry.data.get(CONF_PIN),
            sgm_context=entry.data.get(CONF_SGM_CONTEXT),
        ),
        JdSmartDeviceProfile(
            device_id=entry.data.get(CONF_DEVICE_ID, DEFAULT_DEVICE_ID),
            app_version=entry.data.get(CONF_APP_VERSION, DEFAULT_APP_VERSION),
            platform=entry.data.get(CONF_PLATFORM, DEFAULT_PLATFORM),
            device_model=entry.data.get(CONF_DEVICE_MODEL, DEFAULT_DEVICE_MODEL),
            platform_version=entry.data.get(
                CONF_PLATFORM_VERSION, DEFAULT_PLATFORM_VERSION
            ),
            channel=entry.data.get(CONF_CHANNEL, DEFAULT_CHANNEL),
            user_agent=entry.data.get(CONF_USER_AGENT, DEFAULT_USER_AGENT),
        ),
    )
    coordinators: dict[str, JdSmartCoordinator] = {}
    for device in _entry_devices(entry.data):
        feed_id = device[CONF_FEED_ID]
        coordinator = JdSmartCoordinator(
            hass,
            entry,
            client,
            feed_id,
            device.get(CONF_DEVICE_NAME),
            device_category=device.get(CONF_CATEGORY),
            house_id=device.get(CONF_HOUSE_ID),
            card_meta=device.get(CONF_CARD_META),
        )
        await coordinator.async_config_entry_first_refresh()
        # Best-effort: fetch each device's stream model so non-AC devices get the
        # right switch/select/number entities. Failures never block setup.
        await coordinator.async_fetch_model()
        coordinators[feed_id] = coordinator

    entry.runtime_data = JdSmartRuntimeData(
        client=client,
        coordinators=coordinators,
    )
    _async_register_services(hass)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: JdSmartConfigEntry) -> bool:
    """Unload a config entry."""
    if runtime_data := getattr(entry, "runtime_data", None):
        for coordinator in runtime_data.coordinators.values():
            coordinator.async_shutdown()
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_reload_entry(hass: HomeAssistant, entry: JdSmartConfigEntry) -> bool:
    """Reload a config entry."""
    if not await async_unload_entry(hass, entry):
        return False
    return await async_setup_entry(hass, entry)


def _entry_devices(data: dict) -> list[dict[str, str]]:
    """Return configured devices, supporting old single-device entries."""
    if devices := data.get(CONF_DEVICES):
        return devices
    return [
        {
            CONF_FEED_ID: data[CONF_FEED_ID],
            CONF_DEVICE_NAME: data.get(CONF_DEVICE_NAME, ""),
        }
    ]


def _find_coordinator_by_feed(
    hass: HomeAssistant, feed_id: str
) -> JdSmartCoordinator | None:
    """Find the coordinator owning a feed_id across all JD Smart entries."""
    target = str(feed_id)
    for entry in hass.config_entries.async_entries(DOMAIN):
        runtime = getattr(entry, "runtime_data", None)
        if not runtime:
            continue
        for fid, coordinator in runtime.coordinators.items():
            if str(fid) == target:
                return coordinator
    return None


def _async_register_services(hass: HomeAssistant) -> None:
    """Register diagnostics / manual-control services (idempotent)."""
    if hass.services.has_service(DOMAIN, SERVICE_GET_SNAPSHOT):
        return

    async def _handle_get_snapshot(call: ServiceCall) -> dict:
        """Return a device's raw snapshot (streams + status)."""
        coordinator = _find_coordinator_by_feed(hass, call.data[ATTR_FEED_ID])
        if coordinator is None:
            raise HomeAssistantError(
                f"No JD Smart device with feed_id={call.data[ATTR_FEED_ID]}"
            )
        digest = coordinator.data.digest if coordinator.data else ""
        try:
            snapshot = await coordinator.client.async_get_snapshot(
                coordinator.feed_id, digest
            )
        except JdSmartError as err:
            raise HomeAssistantError(f"Snapshot failed: {err}") from err
        return {
            "feed_id": coordinator.feed_id,
            "name": coordinator.device_name,
            "status": snapshot.status,
            "from_device_success": snapshot.from_device_success,
            "streams": snapshot.streams,
        }

    async def _handle_control_device(call: ServiceCall) -> dict:
        """Control a device by stream_id+value or a command array."""
        coordinator = _find_coordinator_by_feed(hass, call.data[ATTR_FEED_ID])
        if coordinator is None:
            raise HomeAssistantError(
                f"No JD Smart device with feed_id={call.data[ATTR_FEED_ID]}"
            )
        raw_cmd = call.data.get(ATTR_COMMAND)
        if raw_cmd:
            commands: dict[str, object] = {}
            for item in raw_cmd:
                if not isinstance(item, dict):
                    raise HomeAssistantError("Each command must be a dict")
                sid = item.get(ATTR_STREAM_ID)
                # Accept current_value (matches services.yaml docs) or value.
                if "current_value" in item:
                    value = item["current_value"]
                elif ATTR_VALUE in item:
                    value = item[ATTR_VALUE]
                else:
                    raise HomeAssistantError(
                        "Each command needs stream_id and current_value"
                    )
                if sid is None:
                    raise HomeAssistantError("Each command needs stream_id")
                commands[str(sid)] = value
        else:
            sid = call.data.get(ATTR_STREAM_ID)
            if sid is None or ATTR_VALUE not in call.data:
                raise HomeAssistantError(
                    "Provide stream_id + value, or a command array"
                )
            commands = {str(sid): call.data[ATTR_VALUE]}
        try:
            await coordinator.async_control_streams(commands)
        except ConfigEntryAuthFailed:
            raise  # let HA trigger reauth on expired tgt
        except Exception as err:  # noqa: BLE001 -- surface as a service error
            raise HomeAssistantError(f"Control failed: {err}") from err
        return {"feed_id": coordinator.feed_id, "commands": commands, "ok": True}

    async def _handle_get_device_model(call: ServiceCall) -> dict:
        """Return a device's stream model (getDeviceDetails) + control classification."""
        coordinator = _find_coordinator_by_feed(hass, call.data[ATTR_FEED_ID])
        if coordinator is None:
            raise HomeAssistantError(
                f"No JD Smart device with feed_id={call.data[ATTR_FEED_ID]}"
            )
        raw = None
        model: dict[str, dict] = {}
        error: str | None = None
        try:
            raw = await coordinator.client.async_get_device_details(
                coordinator.feed_id, coordinator.house_id
            )
            model = parse_stream_model(raw)
        except Exception as err:  # noqa: BLE001 -- diagnostic: return error, don't 500
            error = f"{type(err).__name__}: {err}"
        control_map = {
            sid: kind for sid, m in model.items() if (kind := control_kind(m))
        }
        return {
            "feed_id": coordinator.feed_id,
            "name": coordinator.device_name,
            "category": coordinator.device_category,
            "house_id": coordinator.house_id,
            "streams_parsed": len(model),
            "control_map": control_map,
            "model": model,
            "raw": raw,
            "error": error,
        }

    hass.services.async_register(
        DOMAIN,
        SERVICE_GET_SNAPSHOT,
        _handle_get_snapshot,
        schema=vol.Schema({vol.Required(ATTR_FEED_ID): cv.string}),
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_CONTROL_DEVICE,
        _handle_control_device,
        schema=vol.Schema(
            {
                vol.Required(ATTR_FEED_ID): cv.string,
                vol.Optional(ATTR_STREAM_ID): cv.string,
                vol.Optional(ATTR_VALUE): vol.Any(int, float, str),
                vol.Optional(ATTR_COMMAND): [dict],
            }
        ),
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_GET_DEVICE_MODEL,
        _handle_get_device_model,
        schema=vol.Schema({vol.Required(ATTR_FEED_ID): cv.string}),
        supports_response=SupportsResponse.ONLY,
    )
