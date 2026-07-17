"""Select platform for JD Smart.

Air conditioners use the static description-based select (horizontal direction).
Any other device type (water heater mode, purifier flush mode, ...) uses generic
selects derived from its stream model's enum options.
"""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .control import (
    control_map,
    control_name,
    is_air_conditioner_device,
    model_entry,
)
from .coordinator import JdSmartConfigEntry
from .entity import JdSmartEntity


@dataclass(frozen=True, kw_only=True)
class JdSmartSelectDescription(SelectEntityDescription):
    """JD Smart select description."""

    stream_id: str
    option_to_value: dict[str, str]


SELECTS: tuple[JdSmartSelectDescription, ...] = (
    JdSmartSelectDescription(
        key="hordir",
        stream_id="hordir",
        translation_key="horizontal_direction",
        options=["swing", "direct"],
        option_to_value={"swing": "0", "direct": "1"},
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: JdSmartConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up JD Smart selects."""
    coordinators = entry.runtime_data.coordinators

    ac_entities: list[SelectEntity] = []
    for coordinator in coordinators.values():
        if is_air_conditioner_device(coordinator):
            ac_entities.extend(
                JdSmartSelect(coordinator, description) for description in SELECTS
            )
    if ac_entities:
        async_add_entities(ac_entities)

    known: set[tuple[str, str]] = set()

    def _add() -> None:
        new: list[SelectEntity] = []
        for coordinator in coordinators.values():
            if is_air_conditioner_device(coordinator):
                continue
            for stream_id, kind in control_map(coordinator).items():
                if kind != "select":
                    continue
                key = (coordinator.feed_id, stream_id)
                if key in known:
                    continue
                known.add(key)
                new.append(JdControlSelect(coordinator, stream_id))
        if new:
            async_add_entities(new)

    _add()
    for coordinator in coordinators.values():
        entry.async_on_unload(coordinator.async_add_listener(_add))


class JdSmartSelect(JdSmartEntity, SelectEntity):
    """JD Smart stream select (AC, description-based)."""

    entity_description: JdSmartSelectDescription

    def __init__(
        self,
        coordinator,
        description: JdSmartSelectDescription,
    ) -> None:
        """Initialize select."""
        super().__init__(coordinator, description.key)
        self.entity_description = description
        self._attr_translation_key = description.translation_key
        self._value_to_option = {
            value: option for option, value in description.option_to_value.items()
        }

    @property
    def current_option(self) -> str | None:
        """Return selected option."""
        return self._value_to_option.get(
            self.streams.get(self.entity_description.stream_id, "")
        )

    async def async_select_option(self, option: str) -> None:
        """Select option."""
        try:
            await self.coordinator.async_control_streams(
                {
                    self.entity_description.stream_id: int(
                        self.entity_description.option_to_value[option]
                    )
                }
            )
        except Exception as err:
            raise HomeAssistantError("Unable to control JD Smart") from err


class JdControlSelect(JdSmartEntity, SelectEntity):
    """JD Smart generic multi-way select (non-AC, stream-model-driven)."""

    def __init__(self, coordinator, stream_id: str) -> None:
        """Initialize select."""
        super().__init__(coordinator, stream_id)
        self._stream = stream_id
        model = model_entry(coordinator, stream_id)
        # options: {code: label}; codes may be non-contiguous (e.g. Mode 0/4).
        self._code_to_label: dict[str, str] = model.get("options") or {}
        self._label_to_code = {v: k for k, v in self._code_to_label.items()}
        self._attr_options = list(self._code_to_label.values())
        self._attr_name = control_name(coordinator, stream_id, model)

    @property
    def current_option(self) -> str | None:
        """Return selected option (label)."""
        value = self.streams.get(self._stream)
        if value is None:
            return None
        return self._code_to_label.get(str(value))

    async def async_select_option(self, option: str) -> None:
        """Select option by label; writes the underlying code."""
        code = self._label_to_code.get(option)
        if code is None:
            raise HomeAssistantError(f"Unknown option: {option}")
        try:
            await self.coordinator.async_control_streams({self._stream: code})
        except Exception as err:
            raise HomeAssistantError("Unable to control JD Smart") from err

    @property
    def available(self) -> bool:
        """Return True when the stream is present in the latest snapshot."""
        return super().available and self._stream in self.streams
