"""Shared helpers for the generic (non-AC) entity platforms.

The per-device coordinator holds a ``stream_model`` (from getDeviceDetails, or a
card_meta fallback). These helpers classify each controllable stream into
switch/select/number and resolve display names, so water heaters, purifiers and
any other non-AC device get the right HA entities automatically.
"""

from __future__ import annotations

from .const import is_air_conditioner
from .model import control_kind

# Values that mean "off" for an on/off stream.
OFF_VALUES = {"0", "", "false", "False", "off", "OFF", "no", "None"}


def device_model(coordinator) -> dict:
    """This device's stream model (getDeviceDetails or card_meta fallback)."""
    return getattr(coordinator, "stream_model", None) or {}


def model_entry(coordinator, stream_id: str) -> dict:
    """Return the model entry for one stream (empty dict if absent)."""
    return device_model(coordinator).get(stream_id) or {}


def control_map(coordinator) -> dict:
    """Return {stream_id: 'switch'|'select'|'number'} for controllable streams."""
    out: dict[str, str] = {}
    for sid, m in device_model(coordinator).items():
        kind = control_kind(m)
        if kind:
            out[sid] = kind
    return out


def control_name(coordinator, stream_id: str, model: dict | None = None) -> str:
    """Display name for a stream: model stream_name > stream_id."""
    m = model if model is not None else model_entry(coordinator, stream_id)
    name = m.get("name")
    if name and name != stream_id:
        return name
    return stream_id


def is_air_conditioner_device(coordinator) -> bool:
    """Return True if this coordinator's device should use the climate platform."""
    streams = coordinator.data.streams if coordinator.data else {}
    return is_air_conditioner(coordinator.device_category, streams)


def is_binary_stream(stream_id: str, model: dict | None) -> bool:
    """Return True for an on/off (binary) read-only stream.

    A two-way {0,1} enum that is NOT controllable (stream_type==1 or unknown and not
    in the control map) is exposed as a binary_sensor rather than a plain sensor.
    """
    opts = (model or {}).get("options")
    return bool(opts) and len(opts) == 2 and set(opts) <= {"0", "1"}


def to_number(value):
    """Coerce a stream value to int/float when possible, else return it unchanged."""
    if value is None or value == "":
        return None
    try:
        f = float(value)
        return int(f) if f.is_integer() else f
    except (TypeError, ValueError):
        return value
