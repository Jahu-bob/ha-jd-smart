"""Coordinator for the JD Smart integration."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.components import persistent_notification
from homeassistant.helpers.event import async_track_point_in_utc_time
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
import homeassistant.util.dt as dt_util

from .api import (
    JdSmartAuthError,
    JdSmartCannotConnectError,
    JdSmartClient,
    JdSmartError,
    JdSmartSnapshot,
    JdSmartTokenRefreshError,
)
from .const import (
    CONF_COOKIE,
    CONF_TGT,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    FAST_POLL_DURATION,
    FAST_POLL_INTERVAL,
    LOGGER,
    UPDATE_AUTH_FAILURE_THRESHOLD,
    is_air_conditioner,
)
from .model import control_kind, model_from_card_meta, parse_stream_model

type JdSmartConfigEntry = ConfigEntry[JdSmartRuntimeData]


@dataclass
class JdSmartRuntimeData:
    """Runtime data for JD Smart."""

    client: JdSmartClient
    coordinators: dict[str, JdSmartCoordinator]


class JdSmartCoordinator(DataUpdateCoordinator[JdSmartSnapshot]):
    """Data coordinator for JD Smart."""

    config_entry: JdSmartConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: JdSmartConfigEntry,
        client: JdSmartClient,
        feed_id: str,
        device_name: str | None,
        device_category: str | None = None,
        house_id: str | None = None,
        card_meta: dict | None = None,
    ) -> None:
        """Initialize coordinator."""
        super().__init__(
            hass,
            LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=DEFAULT_SCAN_INTERVAL,
        )
        self.client = client
        self.feed_id = feed_id
        self.device_name = device_name
        self.device_category = device_category
        self.house_id = house_id
        self.card_meta = card_meta
        # Stream model for this device (getDeviceDetails or card_meta fallback).
        # Empty until async_fetch_model() runs; entities guard on it.
        self.stream_model: dict[str, dict] = {}
        self._fast_poll_cancel: Callable[[], None] | None = None
        self._token_refresh_lock = asyncio.Lock()
        self._consecutive_update_failures = 0

    async def _async_update_data(self) -> JdSmartSnapshot:
        """Fetch latest snapshot."""
        digest = self.data.digest if self.data else ""
        try:
            snapshot = await self.client.async_get_snapshot(self.feed_id, digest)
            self._consecutive_update_failures = 0
            return snapshot
        except JdSmartAuthError:
            LOGGER.info("JD Smart snapshot authentication failed; refreshing token")
            try:
                await self._async_refresh_token()
                snapshot = await self.client.async_get_snapshot(self.feed_id, digest)
                self._consecutive_update_failures = 0
                return snapshot
            except JdSmartAuthError as refresh_err:
                self._async_create_reauth_notification()
                raise ConfigEntryAuthFailed from refresh_err
            except JdSmartCannotConnectError as refresh_err:
                if self.data is None:
                    raise ConfigEntryNotReady from refresh_err
                await self._async_handle_update_failure(refresh_err)
            except JdSmartError as refresh_err:
                await self._async_handle_update_failure(refresh_err)
        except JdSmartCannotConnectError as err:
            if self.data is None:
                raise ConfigEntryNotReady from err
            await self._async_handle_update_failure(err)
        except JdSmartError as err:
            await self._async_handle_update_failure(err)
        raise UpdateFailed("Unable to update JD Smart")

    async def async_fetch_model(self) -> None:
        """Fetch this device's stream model once at setup (getDeviceDetails).

        The model is static metadata (which streams are controllable, options,
        ranges), so it is fetched once and reused. getDeviceDetails is called via
        api.smart.jd.com + Wangyin (works even with an empty houseId for this
        account); on failure or empty result, fall back to the card_meta captured
        at discovery (yields switch/select only, no numeric ranges). Never raises
        -- a missing model just means only read-only sensors plus the control
        service are exposed for this device.

        Air conditioners skip this entirely: they are driven by the climate platform
        and do not need the generic stream model.
        """
        streams = self.data.streams if self.data else {}
        if is_air_conditioner(self.device_category, streams):
            LOGGER.debug(
                "JD Smart device %s (feed_id=%s) is an air conditioner; skipping "
                "stream-model fetch (uses climate platform).",
                self.device_name or self.feed_id,
                self.feed_id,
            )
            return
        model: dict[str, dict] = {}
        source = "card_meta"
        # getDeviceDetails via api.smart.jd.com + Wangyin works even with an empty
        # houseId for this account, so always attempt it (do not gate on house_id).
        try:
            raw = await self.client.async_get_device_details(
                self.feed_id, self.house_id
            )
            model = parse_stream_model(raw)
            if model:
                source = "getDeviceDetails"
            else:
                LOGGER.warning(
                    "JD Smart getDeviceDetails returned no model for %s "
                    "(feed_id=%s, house_id=%s); falling back to card_meta. "
                    "Use the jd_smart.get_device_model service to inspect the "
                    "raw response.",
                    self.device_name or self.feed_id,
                    self.feed_id,
                    self.house_id,
                )
        except Exception as err:  # noqa: BLE001 -- best-effort, never break setup
            LOGGER.warning(
                "JD Smart getDeviceDetails failed for %s (feed_id=%s): %s; "
                "falling back to card_meta.",
                self.device_name or self.feed_id,
                self.feed_id,
                err,
            )
        if not model and self.card_meta:
            model = model_from_card_meta(self.card_meta)
        self.stream_model = model
        if model:
            kinds = [control_kind(m) for m in model.values()]
            LOGGER.info(
                "JD Smart device %s (feed_id=%s) model source=%s: switch=%d/"
                "select=%d/number=%d (streams=%d)",
                self.device_name or self.feed_id,
                self.feed_id,
                source,
                kinds.count("switch"),
                kinds.count("select"),
                kinds.count("number"),
                len(model),
            )
        else:
            LOGGER.warning(
                "JD Smart [0.2.1] device %s (feed_id=%s) has no model (getDeviceDetails and "
                "card_meta both empty); only read-only sensors + control service "
                "will be available.",
                self.device_name or self.feed_id,
                self.feed_id,
            )

    async def async_control_streams(self, commands: dict[str, object]) -> None:
        """Control streams and refresh state."""
        try:
            snapshot = await self.client.async_control_streams(self.feed_id, commands)
        except JdSmartAuthError as err:
            LOGGER.warning(
                "JD Smart control authentication failed: "
                "feed_id=%s, commands=%s, error=%s",
                self.feed_id,
                commands,
                err,
            )
            try:
                await self._async_refresh_token()
                snapshot = await self.client.async_control_streams(
                    self.feed_id,
                    commands,
                )
            except JdSmartAuthError as refresh_err:
                self._async_create_reauth_notification()
                raise ConfigEntryAuthFailed from refresh_err
            except JdSmartError as refresh_err:
                LOGGER.warning(
                    "JD Smart control failed after token refresh: "
                    "feed_id=%s, commands=%s, error=%s",
                    self.feed_id,
                    commands,
                    refresh_err,
                )
                raise UpdateFailed("Unable to control JD Smart") from refresh_err
        except JdSmartError as err:
            LOGGER.warning(
                "JD Smart control failed: feed_id=%s, commands=%s, error=%s",
                self.feed_id,
                commands,
                err,
            )
            raise UpdateFailed("Unable to control JD Smart") from err
        if snapshot is not None:
            self.async_set_updated_data(snapshot)
        self.trigger_fast_polling()
        await self.async_request_refresh()

    async def _async_refresh_token(self) -> None:
        """Refresh token and persist the refreshed values."""
        async with self._token_refresh_lock:
            try:
                new_tgt, new_cookie = await self.client.async_refresh_token()
            except JdSmartTokenRefreshError as err:
                LOGGER.exception("JD Smart token refresh failed")
                self._async_create_token_refresh_failed_notification(err)
                raise
            self.hass.config_entries.async_update_entry(
                self.config_entry,
                data={
                    **self.config_entry.data,
                    CONF_TGT: new_tgt,
                    CONF_COOKIE: new_cookie,
                },
            )

    async def _async_handle_update_failure(self, err: JdSmartError) -> None:
        """Handle repeated update failures."""
        self._consecutive_update_failures += 1
        if self._consecutive_update_failures >= UPDATE_AUTH_FAILURE_THRESHOLD:
            LOGGER.warning(
                "JD Smart update failed repeatedly; requesting reauthentication: "
                "feed_id=%s, failures=%s",
                self.feed_id,
                self._consecutive_update_failures,
            )
            self._async_create_reauth_notification()
            raise ConfigEntryAuthFailed from err
        raise UpdateFailed("Unable to update JD Smart") from err

    @callback
    def _async_create_reauth_notification(self) -> None:
        """Create a persistent reauth notification."""
        persistent_notification.async_create(
            self.hass,
            (
                "JD Smart could not update the device data several times. "
                "Open Settings > Devices & services and reauthenticate JD Smart."
            ),
            title="JD Smart authentication required",
            notification_id=f"{DOMAIN}_{self.feed_id}_reauth",
        )

    @callback
    def _async_create_token_refresh_failed_notification(self, err: Exception) -> None:
        """Create a persistent notification for token refresh failures."""
        reason = str(err) or err.__class__.__name__
        persistent_notification.async_create(
            self.hass,
            (
                "JD Smart failed to refresh authentication. "
                f"Device: {self.device_name or self.feed_id}. "
                f"Reason: {reason}. "
                "Open Settings > Devices & services and update JD Smart authentication."
            ),
            title="JD Smart authentication refresh failed",
            notification_id=f"{DOMAIN}_{self.feed_id}_token_refresh_failed",
        )

    def async_shutdown(self) -> None:
        """Cancel pending coordinator callbacks."""
        if self._fast_poll_cancel:
            self._fast_poll_cancel()
            self._fast_poll_cancel = None

    @callback
    def trigger_fast_polling(self) -> None:
        """Temporarily poll faster after a control command."""
        self.update_interval = FAST_POLL_INTERVAL
        if self._fast_poll_cancel:
            self._fast_poll_cancel()
        end = dt_util.utcnow() + FAST_POLL_DURATION
        self._fast_poll_cancel = async_track_point_in_utc_time(
            self.hass, self._reset_polling, end
        )

    @callback
    def _reset_polling(self, _now: datetime) -> None:
        """Reset polling interval."""
        self.update_interval = DEFAULT_SCAN_INTERVAL
        self._fast_poll_cancel = None
