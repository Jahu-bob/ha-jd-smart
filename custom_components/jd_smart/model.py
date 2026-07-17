"""JD Smart device stream-model parsing -- pure functions.

These classify each controllable stream of *any* JD Smart device (water heater,
water purifier, fan, ...) into a HA entity type (switch / select / number) so the
integration does not hardcode AC-specific stream_ids. Ported from L1yp/jd-smart
(proven). ``getDeviceDetails`` (gw gateway) is the authoritative model source;
``card_meta`` from the device-list response is the degraded fallback.

This module only depends on the stdlib ``json``, so it can be self-tested offline
(``python model.py``) without Home Assistant or aiohttp installed.
"""

from __future__ import annotations

import json
from typing import Any

try:
    from .const import is_air_conditioner
except ImportError:  # running `python model.py` standalone for self-test
    from const import is_air_conditioner


def _num(value: Any) -> Any:
    """Coerce to int/float when possible, else return the original value."""
    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return value
    try:
        f = float(str(value).strip())
        return int(f) if f.is_integer() else f
    except (TypeError, ValueError):
        return value


def coerce_value(value: Any) -> Any:
    """Normalise a control value: bool/numeric -> number; numeric string -> number.

    JD's App sends bare numbers in controlDevice bodies. orangeboyChen's
    ``_control_body`` stringifies values (proven for ACs); this helper is available
    for non-AC devices that may require bare numbers.
    """
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return value
    s = str(value).strip()
    try:
        f = float(s)
        return int(f) if f.is_integer() else f
    except ValueError:
        return s


def _flatten_options(options: Any) -> dict[str, str] | None:
    """Flatten card_desc/card_control options ([{"0":"off"},{"1":"on"}]) to {"0":"off","1":"on"}."""
    if not isinstance(options, list):
        return None
    flat: dict[str, str] = {}
    for item in options:
        if isinstance(item, dict):
            flat.update({str(k): v for k, v in item.items()})
    return flat or None


def build_card_meta(smart_info: dict) -> dict[str, dict]:
    """Combine card_desc + card_control into {stream_id: {name, unit, options, controllable}}.

    card_desc gives the display name (stream_text) / unit / options; card_control
    marks a stream controllable and may carry on/off options. This is the degraded
    model source used when getDeviceDetails is unavailable (only yields
    switch/select, no numeric ranges).
    """
    meta: dict[str, dict] = {}

    def _slot(sid: Any) -> dict:
        return meta.setdefault(
            str(sid), {"name": None, "unit": None, "options": None, "controllable": False}
        )

    for item in smart_info.get("card_desc") or []:
        if not isinstance(item, dict):
            continue
        sid = item.get("stream_id")
        if sid is None:
            continue
        slot = _slot(sid)
        if item.get("stream_text"):
            slot["name"] = item["stream_text"]
        if item.get("unit"):
            slot["unit"] = item["unit"]
        opts = _flatten_options(item.get("options"))
        if opts:
            slot["options"] = opts
    for item in smart_info.get("card_control") or []:
        if not isinstance(item, dict):
            continue
        sid = item.get("stream_id")
        if sid is None:
            continue
        slot = _slot(sid)
        slot["controllable"] = True
        opts = _flatten_options(item.get("options"))
        if opts and not slot["options"]:
            slot["options"] = opts
    return meta


def _details_streams(raw: Any) -> list:
    """Extract the streams list from a getDeviceDetails response.

    Handles result-as-string, result.smartDetailInfo.streams, result.streams and a
    few legacy shapes; returns [] when no streams are found (caller falls back).
    """
    if isinstance(raw, list):
        return raw
    if not isinstance(raw, dict):
        return []
    res = raw.get("result", raw)
    if isinstance(res, str):
        try:
            res = json.loads(res)
        except ValueError:
            return []
    if isinstance(res, dict):
        sdi = res.get("smartDetailInfo")
        if isinstance(sdi, dict) and isinstance(sdi.get("streams"), list):
            return sdi["streams"]
        streams = res.get("streams") or res.get("streamList") or res.get("data")
        return streams if isinstance(streams, list) else []
    if isinstance(res, list):
        return res
    return []


def parse_value_des(value_des: Any) -> dict[str, str] | None:
    """Flatten getDeviceDetails value_des ('[{"0":"off"},{"1":"on"}]') to {"0":"off","1":"on"}."""
    if not value_des:
        return None
    arr = value_des
    if isinstance(arr, str):
        try:
            arr = json.loads(arr)
        except ValueError:
            return None
    if not isinstance(arr, list):
        return None
    flat: dict[str, str] = {}
    for item in arr:
        if isinstance(item, dict):
            flat.update({str(k): v for k, v in item.items()})
    return flat or None


def parse_stream_model(raw: Any) -> dict[str, dict]:
    """Parse getDeviceDetails into {stream_id: {name, ptype, is_enum, options, min, max, step, unit, current, stream_type}}.

    ``stream_type`` is the authoritative controllability flag: 0 = controllable,
    1 = read-only sensor (even with min/max, e.g. Voltage). None = unknown source.
    """
    model: dict[str, dict] = {}
    for s in _details_streams(raw):
        if not isinstance(s, dict):
            continue
        sid = s.get("stream_id")
        if not sid:
            continue
        model[str(sid)] = {
            "name": s.get("stream_name") or str(sid),
            "ptype": s.get("ptype"),
            "is_enum": s.get("is_enum"),
            "options": parse_value_des(s.get("value_des")),
            "min": _num(s.get("min_value")),
            "max": _num(s.get("max_value")),
            "step": _num(s.get("step")),
            "unit": s.get("units") or None,
            "current": s.get("current_value"),
            "stream_type": s.get("stream_type"),
        }
    return model


def control_kind(m: dict) -> str | None:
    """Classify a stream model entry as 'switch' | 'select' | 'number' | None.

    Controllability is decided by ``stream_type`` (0 = controllable, 1 = read-only):
    - stream_type==1 -> None (read-only sensor, never a control entity).
    - stream_type==0 -> controllable; sub-classified by shape, 'number' as fallback.
    - stream_type None (card_meta fallback) -> decided by shape (options/min-max).

    {0,1} two-way enum -> switch; other multi-way enum -> select (codes may be
    non-contiguous, e.g. Mode 0/4); non-enum numeric with min/max -> number.
    """
    st = m.get("stream_type")
    if st == 1:
        return None
    opts = m.get("options")
    if opts:
        if len(opts) == 2 and set(opts) <= {"0", "1"}:
            return "switch"
        return "select"
    if m.get("min") is not None and m.get("max") is not None:
        if m.get("is_enum") == -1 or m.get("ptype") in ("int", "float", "double", "number"):
            return "number"
    if st == 0:
        return "number"
    return None


def model_from_card_meta(card_meta: dict | None) -> dict[str, dict]:
    """Degraded model from discovery card_meta (controllable streams only).

    card_meta lacks min/max/step, so it can only derive switch/select (numeric
    streams have no range -> not exposed as number). Used when getDeviceDetails fails.
    """
    model: dict[str, dict] = {}
    for sid, cm in (card_meta or {}).items():
        if not cm.get("controllable"):
            continue
        model[str(sid)] = {
            "name": cm.get("name") or str(sid),
            "ptype": None,
            "is_enum": None,
            "options": cm.get("options") or None,
            "min": None,
            "max": None,
            "step": None,
            "unit": cm.get("unit") or None,
            "current": None,
            "stream_type": 0,
        }
    return model


def _selftest() -> bool:
    """Offline self-test for the model parsing/classification pure functions."""
    ok = True

    def check(name: str, cond: bool) -> None:
        nonlocal ok
        ok = ok and bool(cond)
        print(f"  [{'ok' if cond else 'FAIL'}] {name}")

    streams = [
        {"stream_id": "Horizontal", "stream_name": "左右摆头", "is_enum": 1,
         "value_des": '[{"0":"关"},{"1":"开"}]', "ptype": "int", "min_value": 0, "max_value": 1},
        {"stream_id": "Mode", "stream_name": "模式", "is_enum": 1,
         "value_des": '[{"0":"标准模式"},{"4":"婴儿风"}]', "ptype": "int"},
        {"stream_id": "Wind", "stream_name": "风速", "is_enum": 1,
         "value_des": '[{"0":"1档"},{"1":"2档"},{"2":"3档"}]', "ptype": "int"},
        {"stream_id": "TimingSetHour", "stream_name": "定时设置时", "is_enum": -1,
         "value_des": "", "ptype": "int", "min_value": 0, "max_value": 24, "step": "1"},
    ]
    model = parse_stream_model({"code": "0", "result": {"smartDetailInfo": {"streams": streams}}})
    check("smartDetailInfo.streams parsed", set(model) >= {"Horizontal", "Mode", "Wind", "TimingSetHour"})
    check("value_des parsed to options", model["Horizontal"]["options"] == {"0": "关", "1": "开"})
    check("Horizontal(0/1) -> switch", control_kind(model["Horizontal"]) == "switch")
    check("Mode(0/4 non-contiguous) -> select", control_kind(model["Mode"]) == "select")
    check("Wind(multi-way) -> select", control_kind(model["Wind"]) == "select")
    check("TimingSetHour(numeric+range) -> number", control_kind(model["TimingSetHour"]) == "number")
    check("number range/step parsed", model["TimingSetHour"]["max"] == 24 and model["TimingSetHour"]["step"] == 1)
    check("name from stream_name", model["Mode"]["name"] == "模式")

    socket_streams = [
        {"stream_id": "Power", "is_enum": 1, "value_des": '[{"0":"关"},{"1":"开"}]',
         "min_value": 0, "max_value": 1, "ptype": "int", "stream_type": 0},
        {"stream_id": "Voltage", "is_enum": -1, "value_des": "", "min_value": 0,
         "max_value": 240, "ptype": "float", "units": "伏", "stream_type": 1},
        {"stream_id": "CurrentPowerSum", "is_enum": -1, "value_des": "", "min_value": 0,
         "max_value": 65535, "ptype": "int", "stream_type": 1},
    ]
    sm = parse_stream_model({"result": {"smartDetailInfo": {"streams": socket_streams}}})
    check("stream_type parsed", sm["Power"]["stream_type"] == 0 and sm["Voltage"]["stream_type"] == 1)
    check("Power(type0 enum) -> switch", control_kind(sm["Power"]) == "switch")
    check("Voltage(type1, has min/max) -> None (read-only)", control_kind(sm["Voltage"]) is None)
    check("CurrentPowerSum(type1) -> None", control_kind(sm["CurrentPowerSum"]) is None)
    check("type0 no enum/range -> number fallback",
          control_kind({"stream_type": 0, "options": None, "min": None, "max": None}) == "number")

    card_meta = build_card_meta({
        "card_desc": [{"stream_id": "Mode", "stream_text": "当前模式", "options": [{"0": "普通"}, {"1": "智能"}, {"2": "节能"}]}],
        "card_control": [{"stream_id": "Power", "options": [{"0": "关"}, {"1": "开"}]},
                         {"stream_id": "Mode"}],
    })
    cm_model = model_from_card_meta(card_meta)
    check("card_meta only keeps controllable", set(cm_model) == {"Power", "Mode"})
    check("card_meta Power -> switch", control_kind(cm_model["Power"]) == "switch")
    check("card_meta Mode -> select (multi-way)", control_kind(cm_model["Mode"]) == "select")

    check("is_air_conditioner by streams", is_air_conditioner(None, {"settemp": "25", "mode": "0", "mark": "2"}))
    check("not AC without mark", not is_air_conditioner(None, {"settemp": "25", "mode": "0"}))
    check("is_air_conditioner by category", is_air_conditioner("空调", {}))
    check("coerce_value numeric string", coerce_value("4") == 4 and coerce_value("1.5") == 1.5)

    print("\nmodel self-test", "PASS" if ok else "FAIL")
    return ok


if __name__ == "__main__":
    import sys

    sys.exit(0 if _selftest() else 1)
