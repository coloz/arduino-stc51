# 宿主与工具要求

arduino-stc51 与配套 stcxx 的当前交付范围为 Windows 和 macOS，源码版本尚未正式发布。

| 宿主 | 编译路径与要求 |
| --- | --- |
| Windows x86_64 | 普通 C 使用原生 SDCC；C++ 由 Windows Arduino CLI 经 BusyBox、WSL 调用锁定的前端和 SDCC。安装时需要配套的原生和 WSL 工具包。 |
| macOS Apple Silicon | 使用原生 SDCC 和前端，依赖 Bash 4.4+、GNU coreutils 和 Python 3。当前前端部署基线为 macOS 15，实际使用验证系统为 macOS 15.7.1。 |
| macOS Intel | 需要单独的 x86_64 工具包与验收，不能直接使用 ARM64 候选。 |

Linux 独立宿主不属于当前交付范围。WSL 中的编译器、前端及其对应源码仍是 Windows C++ 的必要依赖；QEMU 和 CI 可以使用 Linux 执行器。

安装方式见[工具链与 SDK](toolchain-and-sdk.md)。编译或模拟执行通过不代替真实串口/HID、外设和产品板验收，具体见[硬件验证](hardware-validation.md)。
