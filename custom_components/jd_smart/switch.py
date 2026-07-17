"""Switch platform for JD Smart.

Air conditioners use the static description-based switches (backlight, display,
powerful). Any other device type (water heater, purifier, ...) uses generic
on/off switches derived from its stream model.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .control import (
    OFF_VALUES,
    control_map,
    control_name,
    is_air_conditioner_device,
    model_entry,
)
from .coordinator import JdSmartConfigEntry
from .entity import JdSmartEntity


@dataclass(frozen=True, kw_only=True)
class JdSmartSwitchDescription(SwitchEntityDescription):
    """JD Smart switch description."""

    stream_id: str


SWITCHES: tuple[JdSmartSwitchDescription, ...] = (
    JdSmartSwitchDescription(
        key="bglight", stream_id="bglight", translation_key="backlight"
    ),
    JdSmartSwitchDescription(
        key="scrdispaly", stream_id="scrdispaly", translation_key="display"
    ),
    JdSmartSwitchDescription(
        key="ecomode", stream_id="ecomode", translation_key="powerful"
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: JdSmartConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up JD Smart switches."""
    coordinators = entry.runtime_data.coordinators

    # AC devices: static description-based switches.
    ac_entities: list[SwitchEntity] = []
    for coordinator in coordinators.values():
        if is_air_conditioner_device(coordinator):
            ac_entities.extend(
                JdSmartSwitch(coordinator, description) for description in SWITCHES
            )
    if ac_entities:
        async_add_entities(ac_entities)

    # Non-AC devices: generic on/off switches from the stream model. Re-evaluated
    # on each coordinator update so streams are picked up as the model/snapshot fill in.
    known: set[tuple[str, str]] = set()

    def _add() -> None:
        new: list[SwitchEntity] = []
        for coordinator in coordinators.values():
            if is_air_conditioner_device(coordinator):
                continue
            for stream_id, kind in control_map(coordinator).items():
                if kind != "switch":
                    continue
                key = (coordinator.feed_id, stream_id)
                if key in known:
                    continue
                known.add(key)
                new.append(JdControlSwitch(coordinator, stream_id))
        if new:
            async_add_entities(new)

    _add()
    for coordinator in coordinators.values():
        entry.async_on_unload(coordinator.async_add_listener(_add))


class JdSmartSwitch(JdSmartEntity, SwitchEntity):
    """JD Smart stream switch (AC, description-based)."""

    entity_description: JdSmartSwitchDescription

    def __init__(
        self,
        coordinator,
        description: JdSmartSwitchDescription,
    ) -> None:
        """Initialize switch."""
        super().__init__(coordinator, description.key)
        self.entity_description = description
        self._attr_translation_key = description.translation_key

    @property
    def is_on(self) -> bool | None:
        """Return switch state."""
        value = self.streams.get(self.entity_description.stream_id)
        if value == "":
            return None
        return value == "1"

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn switch on."""
        await self._control(1)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn switch off."""
        await self._control(0)

    async def _control(self, value: int) -> None:
        """Control helper."""
        try:
            await self.coordinator.async_control_streams(
                {self.entity_description.stream_id: value}
            )
        except Exception as err:
            raise HomeAssistantError("Unable to control JD Smart") from err


class JdControlSwitch(JdSmartEntity, SwitchEntity):
    """JD Smart generic on/off switch (non-AC, stream-model-driven)."""

    def __init__(self, coordinator, stream_id: str) -> None:
        """Initialize switch."""
        super().__init__(coordinator, stream_id)
        self._stream = stream_id
        self._attr_name = control_name(coordinator, stream_id, model_entry(coordinator, stream_id))

    @property
    def is_on(self) -> bool | None:
        """Return switch state."""
        value = self.streams.get(self._stream)
        if value is None:
            return None
        return str(value).strip() not in OFF_VALUES

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn switch on."""
        await self._control(1)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn switch off."""
        await self._control(0)

    async def _control(self, value: int) -> None:
        """Control helper."""
        try:
            await self.coordinator.async_control_streams({self._stream: value})
        except Exception as err:
            raise HomeAssistantError("Unable to control JD Smart") from err

    @property
    def available(self) -> bool:
        """Return True when the stream is present in the latest snapshot."""
        return super().available and self._stream in self.streams
