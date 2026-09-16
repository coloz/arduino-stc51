# 0.0.1（2026-09-16）

- 以 0.0.1 重新发布 Windows x64 和 Apple Silicon Mac（macOS 15+）安装包及独立 `stc-cli` 烧录工具。
- 修复 Arduino IDE 上传时报 `Property 'upload.tool.serial' is undefined`：开发板管理器自动安装原生 `stc-cli`，所有型号均配置串口上传配方；无法读取型号 ID 的芯片提供显式确认菜单。
- Windows 的 C 和 C++ 均使用原生 `.exe` 工具，前端包自带 Python，通过系统 PowerShell 5.1 启动，无需 WSL、Ubuntu 或 Git Bash。
- 移除 `sdcc-mcs251-wsl` 依赖和 `stc51-native-macos-host` 占位包；Windows 与 macOS 的 C/C++ 共用各自原生 SDCC，前端工具依赖版本更新为 `20.1.8-stc.3`。
- macOS C++ 使用原生 ARM64 工具，需要 Bash 4.4+、GNU coreutils 和 Python 3。
- 支持 10 个 STC32/AI8051U 型号，统一使用 MCS251；原生 SDCC 支持各型号的完整 Flash 布局。
- 提供 C++ `String`、`Print`、`Stream`、串口及 Wire、SPI、SoftwareSerial、LiquidCrystal、Stepper、受限 SD 库。
- STC32CL8K48／64 支持硬件 I²C、SPI、PWM、独立上拉和存储器访问加速。
- 安装包只包含运行所需的 core、variants、库、示例、编译驱动及许可证；维护脚本、源码补丁和生成器保留在源码仓库。
- 版本号保持 0.0.1，替换已有发布包并更新索引。包括已安装旧 0.0.1 的用户，均需卸载、更新索引后重新安装，并清理旧构建缓存；板型使用 `arduino-stc51:mcs251:…`。此前的 0.0.2、0.0.3 保持撤下。
- 编译、链接及离线 HEX 校验不等于实板验收。使用方式、宿主要求和已知限制见 [README.md](README.md)。
