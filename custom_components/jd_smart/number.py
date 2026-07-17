"""Number platform for JD Smart (non-AC devices only).

Numeric controllable streams (e.g. a water heater's target temperature, a timer)
are exposed as HA number entities. min/max/step/unit come from the device's stream
model (getDeviceDetails). Air conditioners use the climate platform instead.
"""

from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .control import (
    control_map,
    control_name,
    is_air_conditioner_device,
    model_entry,
    to_number,
)
from .coordinator import JdSmartConfigEntry
from .entity import JdSmartEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: JdSmartConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up JD Smart numbers."""
    coordinators = entry.runtime_data.coordinators
    known: set[tuple[str, str]] = set()

    def _add() -> None:
        new: list[NumberEntity] = []
        for coordinator in coordinators.values():
            if is_air_conditioner_device(coordinator):
                continue
            for stream_id, kind in control_map(coordinator).items():
                if kind != "number":
                    continue
                key = (coordinator.feed_id, stream_id)
                if key in known:
                    continue
                known.add(key)
                new.append(JdControlNumber(coordinator, stream_id))
        if new:
            async_add_entities(new)

    _add()
    for coordinator in coordinators.values():
        entry.async_on_unload(coordinator.async_add_listener(_add))


class JdControlNumber(JdSmartEntity, NumberEntity):
    """JD Smart generic numeric control (stream-model-driven)."""

    _attr_mode = NumberMode.BOX

    def __init__(self, coordinator, stream_id: str) -> None:
        """Initialize number."""
        super().__init__(coordinator, stream_id)
        self._stream = stream_id
        model = model_entry(coordinator, stream_id)
        # int streams send integers; default to int when ptype is unknown.
        self._is_int = model.get("ptype") in ("int", None)
        self._attr_name = control_name(coordinator, stream_id, model)
        # HA clamps native_value to [min, max] and defaults missing bounds to [0, 100].
        # When the model lacks a range (rare: controllable stream_type==0 with no
        # options/min/max), use a wide default so values >100 are not rejected.
        if model.get("min") is not None:
            self._attr_native_min_value = model["min"]
        else:
            self._attr_native_min_value = 0
        if model.get("max") is not None:
            self._attr_native_max_value = model["max"]
        else:
            self._attr_native_max_value = 100000
        self._attr_native_step = model.get("step") or 1
        if model.get("unit"):
            self._attr_native_unit_of_measurement = model["unit"]

    @property
    def native_value(self) -> float | None:
        """Return current value."""
        value = to_number(self.streams.get(self._stream))
        return value if isinstance(value, (int, float)) else None

    async def async_set_native_value(self, value: float) -> None:
        """Set the value (int streams send integers)."""
        out = int(value) if self._is_int and float(value).is_integer() else value
        try:
            await self.coordinator.async_control_streams({self._stream: out})
        except Exception as err:
            raise HomeAssistantError("Unable to control JD Smart") from err

    @property
    def available(self) -> bool:
        """Return True when the stream is present in the latest snapshot."""
        return super().available and self._stream in self.streams
