"""Sensor platform for JD Smart.

Air conditioners use the static description-based sensors (current temperature,
humidity, TVOC, runtime counters, diagnostics). Any other device type (water
heater, purifier, ...) gets a read-only sensor for each remaining stream, named
and unitised from its stream model.
"""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE, UnitOfTemperature, UnitOfTime
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .control import (
    control_map,
    control_name,
    is_air_conditioner_device,
    is_binary_stream,
    model_entry,
    to_number,
)
from .coordinator import JdSmartConfigEntry
from .entity import JdSmartEntity


@dataclass(frozen=True, kw_only=True)
class JdSmartSensorDescription(SensorEntityDescription):
    """JD Smart sensor description."""

    stream_id: str


SENSORS: tuple[JdSmartSensorDescription, ...] = (
    JdSmartSensorDescription(
        key="curtemp",
        stream_id="curtemp",
        translation_key="current_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    JdSmartSensorDescription(
        key="curhum",
        stream_id="curhum",
        translation_key="current_humidity",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    JdSmartSensorDescription(
        key="tvoc",
        stream_id="tvoc",
        translation_key="tvoc",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    JdSmartSensorDescription(
        key="time_sum",
        stream_id="time_sum",
        translation_key="runtime_total",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    JdSmartSensorDescription(
        key="time_clr",
        stream_id="time_clr",
        translation_key="clean_runtime",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    JdSmartSensorDescription(
        key="speaker",
        stream_id="speaker",
        translation_key="speaker_raw",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    JdSmartSensorDescription(
        key="mdpmode",
        stream_id="mdpmode",
        translation_key="mdp_mode",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    JdSmartSensorDescription(
        key="ptcheat",
        stream_id="ptcheat",
        translation_key="protection_state",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: JdSmartConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up JD Smart sensors."""
    coordinators = entry.runtime_data.coordinators

    # AC devices: static description-based sensors.
    ac_entities: list[SensorEntity] = []
    for coordinator in coordinators.values():
        if is_air_conditioner_device(coordinator):
            ac_entities.extend(
                JdSmartSensor(coordinator, description) for description in SENSORS
            )
    if ac_entities:
        async_add_entities(ac_entities)

    # Non-AC devices: one sensor per read-only, non-binary stream.
    known: set[tuple[str, str]] = set()

    @callback
    def _add() -> None:
        new: list[SensorEntity] = []
        for coordinator in coordinators.values():
            if is_air_conditioner_device(coordinator):
                continue
            streams = coordinator.data.streams if coordinator.data else {}
            cmap = control_map(coordinator)
            for stream_id in streams:
                if stream_id in cmap:
                    continue  # already a control entity (switch/select/number)
                if is_binary_stream(stream_id, model_entry(coordinator, stream_id)):
                    continue  # on/off read-only -> binary_sensor
                key = (coordinator.feed_id, stream_id)
                if key in known:
                    continue
                known.add(key)
                new.append(JdStreamSensor(coordinator, stream_id))
        if new:
            async_add_entities(new)

    _add()
    for coordinator in coordinators.values():
        entry.async_on_unload(coordinator.async_add_listener(_add))


class JdSmartSensor(JdSmartEntity, SensorEntity):
    """JD Smart stream sensor (AC, description-based)."""

    entity_description: JdSmartSensorDescription

    def __init__(
        self,
        coordinator,
        description: JdSmartSensorDescription,
    ) -> None:
        """Initialize sensor."""
        super().__init__(coordinator, description.key)
        self.entity_description = description
        self._attr_translation_key = description.translation_key

    @property
    def native_value(self) -> str | float | None:
        """Return sensor value."""
        value = self.streams.get(self.entity_description.stream_id)
        if value == "":
            return None
        if self.entity_description.state_class is not None:
            try:
                return float(value)
            except (TypeError, ValueError):
                return None
        return value


class JdStreamSensor(JdSmartEntity, SensorEntity):
    """JD Smart generic read-only stream sensor (non-AC, stream-model-driven)."""

    def __init__(self, coordinator, stream_id: str) -> None:
        """Initialize sensor."""
        super().__init__(coordinator, stream_id)
        self._stream = stream_id
        model = model_entry(coordinator, stream_id)
        self._options = model.get("options") or None  # {code: label} for enum streams
        self._attr_name = control_name(coordinator, stream_id, model)
        # Only set a unit when the model provides one; no device_class/state_class to
        # avoid HA validation constraints on unknown telemetry streams.
        if not self._options and model.get("unit"):
            self._attr_native_unit_of_measurement = model["unit"]

    @property
    def native_value(self) -> str | float | None:
        """Return sensor value (enum label for option streams, else number/raw)."""
        value = self.streams.get(self._stream)
        if value is None or value == "":
            return None
        if self._options:
            return self._options.get(str(value), value)
        return to_number(value)

    @property
    def available(self) -> bool:
        """Return True when the stream is present in the latest snapshot."""
        return super().available and self._stream in self.streams
