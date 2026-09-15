# 0.0.3（2026-09-15）

- 发布 Windows x64 和 Apple Silicon Mac（macOS 15+）开发板管理器安装包及独立 `stc-cli` 烧录工具。
- Windows 原生 SDCC 更新至 r8，Mac 原生 SDCC 更新至 r9，支持完整 Flash 布局；C++ 前端、WSL 编译器及运行时资源按 SHA-256 锁定。
- Windows C++ 使用 WSL Ubuntu；Mac C++ 使用原生 ARM64 工具，需 Bash 4.4+、GNU coreutils、Python 3。Linux 独立宿主和 Intel Mac 不在本版支持范围内。
- 改善 C++ 原生 C 回调、只读数据及函数归档裁剪，并修复堆运行时、串口算术与接收、SD 文件生命周期及 Stepper 相关问题。

- 补齐 STC32CL8K48／64 的硬件 I²C、SPI、PWM、独立上拉和存储器访问加速；默认 SDA=P3.3、SCL=P3.2，SPI SS=P1.2。
- 修正 STC32 独立 SPI 第三组引脚为 P4.0/P4.1/P4.3，以及独立上拉访问的 XFR 开关保护。
- Arduino 架构改为 `mcs251`；仅维护 10 个 STC32/AI8051U 型号，统一使用 MCS251。
- 移除 10 个 MCS51-only variants，以及独立 MCS51 C++ ABI、程序指针转换、栈审计、旧外设寄存器分支和维护配置。
- FQBN、库 architectures、安装/CI 路径和工具包本地名称同步更新。旧 FQBN 需迁移并清理旧安装及构建缓存。
- 旧 MCS51 发布平台退出当前索引。请重新选择 `arduino-stc51:mcs251:…` 板型；底层仍被 MCS251 使用的公共依赖及上游来源标识保留。
- 验证报告随 Release 提供。编译、链接和离线 HEX 验证不等于实板验收；使用前仍需核对实际时钟、引脚、外设与 ISP 执行模式。
- 使用方式及宿主要求见 [README.md](README.md)。
