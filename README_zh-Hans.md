# 京东小家 for Home Assistant

这是一个非官方 Home Assistant 自定义集成，用于接入京东小家 App 中的设备——空调、燃气热水器、净水器以及其他京东小家设备。

本仓库的目标是把京东小家控制 API 封装成 Home Assistant custom integration。它不隶属于京东、京东小家或 Home Assistant。

[English README](README.md)

## 用途

这个仓库适合拥有通过京东小家操控的设备、并且可以从 App 本地抓包中提取会话信息的用户。空调通过专门的 climate 实体接入；其他任何类型的设备（燃气热水器、净水器、电风扇、插座等）则通过通用的物模型驱动实体层自动支持，无需为每种设备单独写代码。

## 功能

- 空调实体：开关、模式、目标温度、风速、上下风、睡眠模式。
- 通用实体层：为任何其他京东小家设备自动生成开关、选择、数值、传感器和二值传感器实体--依据每台设备的物模型，热水器、净水器等无需单独适配。
- 开关实体：空调背光灯、屏显、强力。
- 选择实体：空调左右风。
- 传感器：当前温度、当前湿度和若干诊断值。
- 诊断/控制服务：`get_device_snapshot`、`control_device`、`get_device_model`。
- 支持 UI 配置流程。
- 支持 `tgt` token 刷新。

## 安装

### HACS

在 HACS 中添加自定义仓库：

```text
https://github.com/orangeboyChen/ha-jd-smart
```

类型选择：

```text
Integration
```

安装后重启 Home Assistant，然后进入：

```text
设置 -> 设备与服务 -> 添加集成 -> 京东小家
```

如果已经配置过京东小家，再次添加集成时会先让你选择：手动填写鉴权信息、刷新鉴权信息，或添加更多设备。

### 手动安装

把本仓库中的集成复制到 Home Assistant 配置目录：

```text
config/custom_components/jd_smart/
```

重启 Home Assistant，然后进入：

```text
设置 -> 设备与服务 -> 添加集成 -> 京东小家
```

## 配置

需要从一个可正常使用的京东小家 App 会话中获取请求参数。可以使用 Stream、Proxyman、Charles、HTTP Toolkit 或 mitmproxy 等工具抓取 HTTPS 请求。

请打开某个设备页面（例如空调）并抓取成功调用：

```text
https://api.smart.jd.com/c/service/integration/v1/getDeviceSnapshot_v1
```

尽量从同一次请求中复制所有字段。不需要手动填写 `feed_id`。认证通过后，集成会自动拉取设备列表，并允许一次选择一个或多个设备；已经配置过的设备不会再出现在选择列表中。

`cookie`

抓包中的完整 `Cookie` 请求头。

`tgt`

抓包中的 `tgt` 请求头。

`pin`

可选京东账号 PIN，用于 token 刷新。

`sgm_context`

抓包中的 `Sgm-Context` 请求头。UI 中是可选项，如果抓包里有，建议填写。

`device_id`

请求 URL 中的 `device_id` 参数。留空时集成会自动生成，建议使用抓包值。

`platform`

请求 URL 中的 `plat` 参数原值。不要猜这个字段，应直接复制抓包中的值。当前已确认的 iOS 抓包值是 `iPhone`；其他平台以实际抓包为准。

`app_version`

请求 URL 中的 `app_version` 参数，同时也对应 `appversion` 请求头。

`device_model`

请求 URL 中的 `hard_platform` 参数，同时也对应 `appplatform` 请求头。

`platform_version`

请求 URL 中的 `plat_version` 参数，同时也对应 `appplatformversion` 请求头。

`channel`

抓包请求 URL 中的 `channel` 参数，例如 `channel=76161171`。请使用可用抓包中的原值。

`user_agent`

请求中的 `User-Agent`。

## 实体

空调通过 climate 实体接入（电源、模式、目标温度、当前温度、当前湿度、风速、上下风、睡眠模式；目标温度 18-32 摄氏度，步进 1 摄氏度），外加空调专用的开关（背光灯、屏显、强力）、选择（左右风）和传感器（当前温度、当前湿度，以及 TVOC、运行时间、蜂鸣器原始值、MDP 模式、保护状态等诊断值）。

其他任何类型的设备会根据其物模型自动生成一组通用实体：开关量（on/off）变成开关，多档枚举变成选择，数值范围变成数值，只读流变成传感器或二值传感器。用 `jd_smart.get_device_model` 服务可以查看某台设备暴露了哪些流以及它们如何归类。

## 服务

- `jd_smart.get_device_snapshot`：返回某设备的当前快照（streams + 状态）。
- `jd_smart.control_device`：向任意设备下发控制命令，可用 `stream_id` + `value` 单条，或 `command` 数组多条。用于非空调设备和调试。
- `jd_smart.get_device_model`：（诊断）返回某设备的物模型和可控流归类。用来查看一台设备会生成哪些实体，以及排查"为什么只有电源开关"（通常意味着物模型没拉到，检查 `house_id` / `tgt`）。

## 免责声明

本项目是非官方集成，与京东、京东小家、Home Assistant 均无任何关联。使用本集成
可能违反京东小家的服务条款，请自行评估风险并自行承担。完整免责声明见
[DISCLAIMER.md](DISCLAIMER.md)。
