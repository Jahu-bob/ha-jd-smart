"""Binary sensor platform for JD Smart (non-AC devices only).

Read-only on/off streams (e.g. a water heater's burning/running status) are
exposed as binary sensors. Controllable on/off streams become switches instead.
"""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .control import (
    OFF_VALUES,
    control_map,
    control_name,
    is_air_conditioner_device,
    is_binary_stream,
    model_entry,
)
from .coordinator import JdSmartConfigEntry
from .entity import JdSmartEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: JdSmartConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up JD Smart binary sensors."""
    coordinators = entry.runtime_data.coordinators
    known: set[tuple[str, str]] = set()

    @callback
    def _add() -> None:
        new: list[BinarySensorEntity] = []
        for coordinator in coordinators.values():
            if is_air_conditioner_device(coordinator):
                continue
            streams = coordinator.data.streams if coordinator.data else {}
            cmap = control_map(coordinator)
            for stream_id in streams:
                if stream_id in cmap:
                    continue  # controllable on/off already a switch
                if not is_binary_stream(stream_id, model_entry(coordinator, stream_id)):
                    continue
                key = (coordinator.feed_id, stream_id)
                if key in known:
                    continue
                known.add(key)
                new.append(JdStreamBinarySensor(coordinator, stream_id))
        if new:
            async_add_entities(new)

    _add()
    for coordinator in coordinators.values():
        entry.async_on_unload(coordinator.async_add_listener(_add))


class JdStreamBinarySensor(JdSmartEntity, BinarySensorEntity):
    """JD Smart read-only on/off stream (stream-model-driven)."""

    _attr_device_class = BinarySensorDeviceClass.POWER

    def __init__(self, coordinator, stream_id: str) -> None:
        """Initialize binary sensor."""
        super().__init__(coordinator, stream_id)
        self._stream = stream_id
        self._attr_name = control_name(coordinator, stream_id, model_entry(coordinator, stream_id))

    @property
    def is_on(self) -> bool | None:
        """Return True when the stream is on."""
        value = self.streams.get(self._stream)
        if value is None:
            return None
        return str(value).strip() not in OFF_VALUES

    @property
    def available(self) -> bool:
        """Return True when the stream is present in the latest snapshot."""
        return super().available and self._stream in self.streams
