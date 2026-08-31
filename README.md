# arduino-stc51

[![CI](https://github.com/coloz/arduino-stc51/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/coloz/arduino-stc51/actions/workflows/ci.yml)
[![Version](https://img.shields.io/badge/version-0.0.1-blue.svg)](package_arduino-stc51_index.json)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

面向 STC 8051/251 系列 MCU 的 Arduino core，提供精确到芯片型号的开发板定义、Wiring-C / Arduino-C API、常用外设库和基于 SDCC 的可复现工具链。

> 需要帮助或发现问题？请先查看[项目文档](#文档)，搜索已有
> [Issues](https://github.com/coloz/arduino-stc51/issues)，确认没有重复后再提交问题。

## 目录

- [开发状态](#开发状态)
- [文档](#文档)
- [支持的 MCU](#支持的-mcu)
- [安装](#安装)
- [快速开始](#快速开始)
- [Arduino API 与兼容性](#arduino-api-与兼容性)
- [已知限制](#已知限制)
- [问题反馈](#问题反馈)
- [参与开发](#参与开发)
- [许可证](#许可证)

## 开发状态

当前版本为 **0.0.1**，属于早期开发版本。

| 项目 | 当前状态 |
|---|---|
| 精确型号变体 | 25 个默认配置已纳入编译/链接矩阵 |
| MCS51 后端 | 已用于 STC89、STC12、STC15、STC8 和 Ai8H；AI8051U 默认使用该后端 |
| MCS251 后端 | 用于 STC32，并可供 AI8051U 选择；**experimental** |
| 主机工具链 | Windows x64、macOS Apple Silicon、macOS Intel；暂不支持 Linux |
| 自动化验证 | 覆盖全部默认变体、补充编译配置和随包库示例 |
| 实板验证 | 仍待逐型号完成；生成 HEX 不等于真机通过 |

自动化编译结论与实板验证证据分开记录。发布或接线前请查看
[硬件验证状态](docs/hardware-validation.md)，不要把“编译通过”理解为
对应封装、电压、时钟和外设已经在实板验证。

## 文档

- [Core API、资源冲突与迁移边界](docs/core-api-compatibility.md)
- [随包库和 Arduino 库兼容性](docs/library-compatibility.md)
- [工具链、STC SDK 来源与许可边界](docs/toolchain-and-sdk.md)
- [逐型号编译与实板验证状态](docs/hardware-validation.md)
- [统一 core 的实现说明](cores/STC/README.md)

## 支持的 MCU

| 系列 | 精确型号 | 编译后端 | 编译状态 | 实板状态 |
|---|---|---|---|---|
| STC89 | STC89C51RC、STC89C52RC、STC89C58RD+ | MCS51 | 已覆盖 | 待验证 |
| STC12 | STC12C2052AD、STC12C5A60S2 | MCS51 | 已覆盖 | 待验证 |
| STC15 | STC15F104W、STC15F2K60S2、STC15W408AS、STC15W4K32S4 | MCS51 | 已覆盖 | 待验证 |
| STC8A/C | STC8A8K64S4A12、STC8C2K64S4 | MCS51 | 已覆盖 | 待验证 |
| STC8G | STC8G1K08、STC8G1K08A、STC8G2K64S4 | MCS51 | 已覆盖 | 待验证 |
| STC8H | STC8H1K08、STC8H1K28、STC8H3K64S4、STC8H8K64U | MCS51 | 已覆盖 | 待验证 |
| STC32 | STC32CL8K64、STC32G8K64、STC32G12K64、STC32G12K128 | MCS251（实验） | 已覆盖 | 待验证 |
| AI8051U | AI8051U-34K64 | MCS51；可选 MCS251（实验） | 已覆盖 | 待验证 |
| Ai8H | Ai8H2K12U、Ai8H2K32U | MCS51 | 已覆盖 | 待验证 |

每款 MCU 都有独立的 `variants/<型号>/`、内存边界、有效引脚掩码和
`variant.json`。型号数据集中维护在
[`tools/variants/devices.json`](tools/variants/devices.json)，并由生成器同步
生成 `boards.txt` 和变体文件。

## 安装

当前 Boards Manager 包支持 Windows x64、macOS Apple Silicon（arm64）和
macOS Intel（x86_64），暂不提供 Linux 工具链。在 Arduino IDE 2.x 的
“附加开发板管理器网址”中添加：

```text
https://raw.githubusercontent.com/coloz/arduino-stc51/main/package_arduino-stc51_index.json
```

然后打开开发板管理器，搜索并安装 **arduino-stc51 0.0.1**。

也可以通过 Arduino CLI 添加索引并安装：

```powershell
arduino-cli config add board_manager.additional_urls https://raw.githubusercontent.com/coloz/arduino-stc51/main/package_arduino-stc51_index.json
arduino-cli core update-index
arduino-cli core install arduino-stc51:mcs51@0.0.1
```

## 快速开始

1. 在开发板菜单中选择准确的 MCU 型号。
2. 选择与 STC ISP 配置一致的 CPU 时钟；STC89 还要同步选择 12T 或 6T
   machine cycle。
3. 编译草图或导出已编译的二进制文件。
4. 在 Windows 上使用官方 AiCube-ISP 打开生成的 Intel HEX 并烧录。

core 不会切换或校准芯片振荡器。项目也不捆绑 AiCube-ISP，已核验的版本、
下载地址、大小和 SHA-256 记录在
[`sdk/manifest.json`](sdk/manifest.json)。

## Arduino API 与兼容性

本项目提供经 SDCC 验证的 **Wiring-C / Arduino-C** 接口。`.ino` 草图按 C
编译，不提供 Arduino C++ ABI。

当前 core 包含：

- GPIO、四种 STC 端口模式和有效引脚检查；
- `millis`、`micros`、延时、外部中断、移位、脉宽和常用数学辅助；
- UART1 的 `Serial` 对象式与函数式接口；
- 逐型号 ADC 映射和 1--15 位返回结果宽度设置；
- `Wire`、`SPI`、`SoftwareSerial`、`LiquidCrystal`、`Stepper` 和
  `SD` 随包库。

`Serial.begin()`、`Wire.begin()` 等点号语法由只读函数指针表提供，不代表
存在 C++ 类、继承或重载。`String`、`Print`、`Stream` 以及依赖这些接口
的常规 Arduino C++ 库不能直接使用。完整接口矩阵见
[Core API 兼容性文档](docs/core-api-compatibility.md)。

## 已知限制

- STC32 和 AI8051U 的 MCS251 路径仍为实验状态。
- 25 个型号尚未完成系统性的实板验证。
- 当前不提供自动上传配方；编译后需使用 AiCube-ISP 烧录 HEX。
- Timer0 固定用作系统时基；启用 UART1 时 Timer1 被串口占用。
- PWM、EEPROM/IAP、USB、CAN、DAC、硬件 I2C/SPI、多串口、`tone` 和
  `Servo` 尚未作为通用能力提供。
- 受上游 SDCC 参数解析限制，草图目录和自定义 `--build-path` 应避免空格。
- 裸 MCU 没有统一板载 LED，`LED_BUILTIN` 为 `NOT_A_PIN`；接线前必须核对
  所用封装的官方引脚图。

## 问题反馈

提交 Issue 前请先搜索是否已有相同问题，并至少附上：

- MCU 完整型号和 FQBN；
- CPU 时钟，以及 STC89 的 12T/6T 配置；
- Arduino IDE/CLI 版本和操作系统；
- 可复现的最小草图与完整编译日志；
- 若为运行问题，附供电、封装、烧录工具版本和接线信息。

## 参与开发

重新生成或检查全部变体：

```powershell
node ./tools/variants/generate.mjs
node ./tools/variants/generate.mjs --check
```

运行仓库一致性检查和 Windows 全变体编译矩阵：

```powershell
./scripts/check-repository.ps1
./scripts/test-all-variants.ps1
```

创建可复现的 Boards Manager 平台归档：

```powershell
./scripts/package-platform.ps1
```

欢迎提交 Issue 和 Pull Request。新增型号时，请同时更新型号数据库、生成文件、
编译证据和对应文档。

## 许可证

本仓库代码采用 [MIT License](LICENSE)。上游工具、历史来源代码和 STC 厂商
资料各自保留其许可证与署名；详情见 [LICENSES](LICENSES/) 和
[工具链与 SDK 文档](docs/toolchain-and-sdk.md)。
