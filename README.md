# JD Smart for Home Assistant

Unofficial Home Assistant custom integration for devices controlled through the JD Smart / JD Xiaojia app — air conditioners, gas water heaters, water purifiers, and other JD Smart devices.

This repository packages the JD Smart control API as a Home Assistant custom integration. It is not affiliated with JD.com, JD Smart, JD Xiaojia, or Home Assistant.

[简体中文 README](README_zh-Hans.md)

## Purpose

This repository is for users who have devices controlled through the JD Smart / JD Xiaojia app and can extract session values from a local app traffic capture. Air conditioners are exposed via a dedicated climate entity; any other device type (gas water heater, water purifier, fan, outlet, ...) is supported automatically through a generic stream-model-driven entity layer — no per-device hardcoding.

## Features

- Climate entity for air conditioners (power, HVAC mode, target temperature, fan speed, vertical swing, sleep preset).
- Generic entity layer for any other JD Smart device: switches, selects, numbers, sensors and binary sensors are generated automatically from each device's stream model - so water heaters, water purifiers and the like work without per-device code.
- Switch entities for AC backlight, display, and powerful mode.
- Select entity for AC horizontal swing direction.
- Sensor entities for current temperature, humidity, and diagnostic values.
- Services for diagnostics and manual control of any device (`get_device_snapshot`, `control_device`, `get_device_model`).
- Config flow UI.
- `tgt` token refresh support.

## Installation

### HACS

Add this repository as a HACS custom repository:

```text
https://github.com/orangeboyChen/ha-jd-smart
```

Repository type:

```text
Integration
```

Install it from HACS, restart Home Assistant, then add the integration from:

```text
Settings -> Devices & services -> Add integration -> JD Smart
```

When JD Smart is already configured, adding the integration again first asks
whether to manually enter authentication data, refresh authentication, or add
more devices.

### Manual

Copy the integration into your Home Assistant configuration directory:

```text
config/custom_components/jd_smart/
```

Restart Home Assistant, then add the integration from:

```text
Settings -> Devices & services -> Add integration -> JD Smart
```

## Configuration

You need values from a working JD Smart / JD Xiaojia mobile app session. You can capture HTTPS traffic with a tool such as Stream, Proxyman, Charles, HTTP Toolkit, or mitmproxy.

Open a device page (for example the air conditioner) in the JD Smart / JD Xiaojia app and capture a successful request to:

```text
https://api.smart.jd.com/c/service/integration/v1/getDeviceSnapshot_v1
```

Use values from the same request whenever possible. You do not need to enter
`feed_id` manually. After authentication, the integration fetches the available
devices and lets you select one or more devices. Devices that are
already configured are hidden from the selection list.

`cookie`

The full `Cookie` request header from the captured app request.

`tgt`

The `tgt` request header from the captured app request.

`pin`

Optional JD account PIN, used for token refresh.

`sgm_context`

The `Sgm-Context` request header. It is optional in the UI, but copy it if your working capture contains it.

`device_id`

The `device_id` query parameter from the request URL. If left empty, the integration generates one, but using the captured value is recommended.

`platform`

The exact `plat` query parameter from your capture. Do not guess this value. The confirmed iOS capture used `iPhone`; other platforms should use the captured value.

`app_version`

The `app_version` query parameter and `appversion` request header.

`device_model`

The `hard_platform` query parameter and `appplatform` request header.

`platform_version`

The `plat_version` query parameter and `appplatformversion` request header.

`channel`

The `channel` query parameter in the captured request URL, for example
`channel=76161171`. Use the value from your working capture.

`user_agent`

The request `User-Agent` header.

## Entities

Air conditioners are exposed as a climate entity (power, HVAC mode, target temperature, current temperature, current humidity, fan speed, vertical swing, sleep preset; target temperature 18-32 C with 1 C steps), plus AC-specific switches (backlight, display, powerful), a select (horizontal swing) and sensors (current temperature, humidity, TVOC, runtime counters, diagnostics).

Any other device type gets a set of generic entities derived from its stream model: an on/off stream becomes a switch, a multi-way enum becomes a select, a numeric range becomes a number, and read-only streams become sensors or binary sensors. Use the `jd_smart.get_device_model` service to inspect which streams a device exposes and how they are classified.

## Services

- `jd_smart.get_device_snapshot` - return a device's current snapshot (streams + status).
- `jd_smart.control_device` - send a control command to any device, by `stream_id` + `value` or a `command` array. Useful for non-AC devices and debugging.
- `jd_smart.get_device_model` - (diagnostic) return a device's stream model and controllable-stream classification. Use this to see which entities a device will get, and to troubleshoot a device that only shows a Power switch (usually meaning the stream model could not be fetched - check `house_id` / `tgt`).

## Disclaimer

This is an unofficial integration and is not affiliated with JD.com, JD Smart, or
Home Assistant. Use of this integration may violate the JD Smart / JD Xiaojia
Terms of Service. Use it at your own risk. See [DISCLAIMER.md](DISCLAIMER.md)
for the full disclaimer.
