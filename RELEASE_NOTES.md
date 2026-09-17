# 0.0.4（2026-09-17）

- 新增原生 USB HID、自定义报告收发及 Arduino 官方 Keyboard/Mouse 移植，支持键盘指示灯和键鼠组合；通过 `yield()` / 主循环服务 USB。
- 新增双路原生 CAN，适配经典 CAN 和 G144 CAN-FD 控制器的经典帧收发；提供官方 `HardwareCAN` / `CanMsg` 风格 API 和独立 `CANPacketClass`。
- 补充 15 个 CAN/USB 示例，覆盖独立收发、过滤、扩展帧、远程帧、双路 CAN、键盘文字/组合键/指示灯、串口转键盘、按钮/摇杆鼠标、滚轮、媒体键和 HID 游戏手柄；各库 README 提供示例索引与接线说明。
- 按型号生成 USB/CAN 能力标志，补充芯片支持说明和上游许可证。
- 仅更新 core 平台包；SDCC、C++ 前端、上传器及编译器源码继续复用 v0.0.2 已发布资源，工具版本、下载地址和校验值保持不变。
- 已安装 0.0.3 的用户刷新开发板索引后升级至 `stc:mcs251@0.0.4`；FQBN 和工具依赖保持不变。

# 0.0.3（2026-09-17）

- 包标识改为 `stc`，FQBN 统一为 `stc:mcs251:<variants>`；板卡 ID 和菜单参数保持不变。
- 同步工具依赖、Windows/macOS 前端锁文件、源码安装路径及构建和验证脚本；平台包和索引同步更新。
- 旧包用户刷新索引后安装 `stc:mcs251@0.0.3`，重新选择板卡，并将项目中的 FQBN 前缀改为 `stc:mcs251:`。包标识已变化，不会通过旧包的版本升级自动迁移。
- 沿用 0.0.2 的编译器、前端和上传器归档，继续支持 Windows x64、Apple Silicon macOS 15+ 和 10 个 MCS251 型号。

# 0.0.2（2026-09-16）

- 清理未使用的上游 SDK 清单、Linux 容器配置及 Linux 分发锁文件，安装包不再包含 SDK 资料。
- 保留仍使用的打包、代码生成、源码锁定与发布校验工具；源码构建的工具缓存改至 `dist/toolchain-cache`。
- 移除 GitHub Actions 工作流及历史库兼容性报告；保留可手动运行的本地验证脚本。
- 打包和索引脚本默认读取平台版本，原生安装验证从候选索引读取版本，支持 0.0.2 及后续版本。
- 沿用 0.0.1 的编译器、上传器、C++ core 与库实现，继续支持 Windows x64、Apple Silicon macOS 15+ 和 10 个 MCS251 型号。
- 刷新开发板管理器索引后可由 0.0.1 升级至 0.0.2。编译、链接和离线 HEX 校验不代表实板验收。

# 0.0.1（2026-09-16，历史记录）

平台现仅提供 C++11 模式，已移除语言菜单和纯 C 兼容接口。旧 FQBN 中的 `cppcore=enabled` / `cppcore=plain` 参数需删除。所有板项默认 12 MHz，AI8051U-34K64 可选 40 MHz、STC32G144K246 可选 48 MHz；实际芯片时钟须与所选配置一致。

- 修复 U8g2 在 Windows 长路径下的函数归档命令超长，以及并行依赖扫描时的临时文件冲突；无需缩短构建路径或强制单线程。
- 修复 DHT 的清理分支返回值分析和 RTClib 常量字节读取链，保留 SDCC 告警审计。
- 补齐 `fminf/fmaxf`、`itoa/utoa/ltoa/ultoa`；将合法 C++ 的匿名 typedef 兼容性提示、整数字面量到浮点的舍入提示保留为警告，TFT_eSPI 可使用通用 SPI 路径。
- 随附 Adafruit NeoPixel `1.15.5-stc.1` 实验移植：目前仅 STC32G144K246、12/48 MHz、P0～P7 有效引脚、800 kHz。编译与指令模型验证不代替实板时序验收，详见 [移植说明](libraries/Adafruit_NeoPixel/README-STC.md)。
- 以 0.0.1 重新发布 Windows x64 和 Apple Silicon Mac（macOS 15+）安装包及独立 `stc-cli` 烧录工具。
- 修复编译过程反复出现的 `__has_builtin`、`__STDC_HOSTED__` 重复定义警告；Windows、macOS 工具包同时包含修复，保留真正的源码警告和错误。
- 修复 Arduino IDE 上传时报 `Property 'upload.tool.serial' is undefined`：开发板管理器自动安装原生 `stc-cli`，所有型号均配置上传配方。无法返回型号 ID 的 UART 协议默认允许上传；可核验的型号 ID 仍执行匹配检查。
- 上传显示按芯片确认接收量更新的百分比。普通提示和进度使用正常文字颜色，错误继续以红色显示；详细上传模式不再默认输出原始 ISP 报文。
- STC32G144K246 支持自动识别所选 USB CDC／UART 端口，以及 `工具 → Upload method → Native USB` 手动选项。工厂 HID 模式没有 COM 口时也可上传。
- 更新后若未出现 `Upload method`，执行 `工具 → Reload Board Data（重新加载开发板数据）` 并检查板型参数。
- SDCC 工具依赖更新为 `4.6.0-stc.0.0.1-r1`，上传器更新为 `0.1.0-stc.1`，避免复用旧版工具缓存；平台版本仍为 0.0.1。
- Windows 的 C 和 C++ 均使用原生 `.exe` 工具，前端包自带 Python，通过系统 PowerShell 5.1 启动，无需 WSL、Ubuntu 或 Git Bash。
- 移除 `sdcc-mcs251-wsl` 依赖和 `stc51-native-macos-host` 占位包；Windows 与 macOS 的 C/C++ 共用各自原生 SDCC，前端工具依赖版本更新为 `20.1.8-stc.3`。
- macOS C++ 使用原生 ARM64 工具，需要 Bash 4.4+、GNU coreutils 和 Python 3。
- 支持 10 个 STC32/AI8051U 型号，统一使用 MCS251；原生 SDCC 支持各型号的完整 Flash 布局。
- 提供 C++ `String`、`Print`、`Stream`、串口及 Wire、SPI、SoftwareSerial、LiquidCrystal、Stepper、受限 SD 库。
- STC32CL8K48／64 支持硬件 I²C、SPI、PWM、独立上拉和存储器访问加速。
- 安装包只包含运行所需的 core、variants、库、示例、编译驱动及许可证；维护脚本、源码补丁和生成器保留在源码仓库。
- 版本号保持 0.0.1，替换已有发布包并更新索引。包括已安装旧 0.0.1 的用户，均需卸载、更新索引后重新安装，并清理旧构建缓存；板型使用 `arduino-stc51:mcs251:…`。此前的 0.0.2、0.0.3 保持撤下。
- 编译、链接及离线 HEX 校验不等于实板验收。使用方式、宿主要求和已知限制见 [README.md](README.md)。
