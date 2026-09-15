# arduino-stc51

面向 STC **MCS251** 芯片的 Arduino core。当前版本 **0.0.1**，仅维护 10 个型号；所有型号固定使用 `-mmcs251`，Arduino 架构标识为 `mcs251`。

MCS51 芯片、板项和 C++ 适配路径已移除。旧的 `arduino-stc51:mcs51:…` FQBN 不再适用，需要重新安装当前源码并选择新板项。工程名仍为 `arduino-stc51`。

当前版本供开发和有限场景验证使用，尚未完成实板验收。产品板需验证实际时钟、接线和外设功能；编译成功不代表实板验收通过。

当前维护范围为 **Windows x64 和 Apple Silicon Mac（macOS 15+）**。Windows C++ 需要 WSL Ubuntu；macOS C++ 需要 `brew install bash coreutils python`。Linux 独立宿主和 Intel Mac 不在当前支持范围内。详见 [C++ 驱动说明](tools/cpp-cli/README.md)。

## 安装

在 Arduino IDE 的“附加开发板管理器网址”中加入：

```text
https://raw.githubusercontent.com/coloz/arduino-stc51/main/package_arduino-stc51_index.json
```

在开发板管理器中安装 **arduino-stc51 0.0.1**，然后选择对应型号。Arduino CLI 可使用：

```powershell
arduino-cli core update-index --additional-urls https://raw.githubusercontent.com/coloz/arduino-stc51/main/package_arduino-stc51_index.json
arduino-cli core install arduino-stc51:mcs251@0.0.1 --additional-urls https://raw.githubusercontent.com/coloz/arduino-stc51/main/package_arduino-stc51_index.json
```

安装资源见 [v0.0.1 Release](https://github.com/coloz/arduino-stc51/releases/tag/v0.0.1)。此前的 0.0.2、0.0.3 已撤下；装过旧版的用户请先卸载，再选择 0.0.1 安装，并清理原有构建缓存。

Windows 的编译辅助操作使用系统自带的 Windows PowerShell 5.1，无需额外的 shell 工具包。普通 C 使用原生 SDCC；C++ 通过 WSL Ubuntu 调用已锁定的 Clang/LLVM-CBE/SDCC 工具链。macOS 使用原生工具与系统 `/bin/sh`。

## 支持型号

| 型号 | 物理程序 Flash | 当前构建上限 |
| --- | --- | --- |
| STC32G12K128 | 128 KiB | 128 KiB |
| STC32G144K246 | 246 KiB | 246 KiB |
| STC32G8K64 | 64 KiB | 64 KiB |
| STC32CL8K64 | 64 KiB | 64 KiB |
| AI8051U-34K64 | 64 KiB | 64 KiB |
| STC32G12K64 | 64 KiB | 64 KiB |
| STC32G8K48 | 48 KiB | 48 KiB |
| STC32CL8K48 | 48 KiB | 48 KiB |
| AI8051U-34K32 | 32 KiB | 32 KiB |
| AI8051U-34K16 | 16 KiB | 16 KiB |

型号、存储布局和引脚掩码以 [devices.json](tools/variants/devices.json) 为准。物理 Flash 与当前已验证的可执行窗口不一定相同。具体封装也可能引出更少的 GPIO。

STC32CL8K48／64 提供硬件 Wire、SPI、PWM 和访问加速，默认 Wire 接线为 SDA=P3.3、SCL=P3.2。各型号外设能力和引脚配置见对应的 `variants/<型号>/pins_arduino.h`。

## 从源码构建

准备 Arduino CLI、PowerShell、tar，以及所需编译工具。以下命令在源码仓库根目录执行；开发板管理器安装包不包含 `scripts` 维护工具：

```powershell
$env:STCXX_WSL_DISTRO = 'Ubuntu'
$build = .\scripts\build-example.ps1 `
    -Fqbn 'arduino-stc51:mcs251:stc32g12k128:clock=12m' `
    -WorkDirectory D:\stc51-work `
    -ToolCacheDirectory D:\stc51-tools
$build.firmware
```

脚本将当前源码打包到独立目录，校验工具包的 SHA-256，然后编译示例。`-SketchPath` 可指定含同名 `.ino` 的 sketch 目录；SDCC 构建路径应避免空格。默认 Blink 使用 P3.2，按电路修改引脚，不假设存在板载 LED。

省略 `cppcore=enabled` 时使用 plain C。安装脚本不传 FQBN 时默认编译 STC32G8K64、12 MHz 的 plain C Blink，可使用固定的原生工具包。G12K128、G144K246 等完整 Flash 布局需要重建后的 SDCC 分区功能；旧原版工具包不满足时构建会明确拒绝。C++ 路径使用相邻 `stcxx` 项目的已锁定工具链，Windows 下通过 WSL 调用，默认 SDCC 为 `D:\Git\stc51\stcxx\out\bin\sdcc`。详见 [C++ 驱动说明](tools/cpp-cli/README.md)。

源码安装脚本用于维护者调试。脚本会下载并校验锁定的 SDCC 归档，也可通过 `-ToolCacheDirectory` 复用本地归档，或通过 `-ToolManifestPath` 指定已验证的工具清单。打包不会自动发布。版本变化见 [RELEASE_NOTES.md](RELEASE_NOTES.md)。

## C++ 与 Arduino API

C++ 使用 Clang → LLVM-CBE → SDCC，提供 `String`、`Print`、`Stream`、`HardwareSerial`、`SPIClass`、`TwoWire` 等接口。所有板项都有 12 MHz C++ 配置；AI8051U-34K64 另有 40 MHz、STC32G144K246 另有 48 MHz。编译时钟必须与芯片实际时钟一致，菜单不会替代 ISP 时钟配置。

支持 GPIO、计时、UART1、按型号提供的 ADC/PWM/外部中断，以及 Wire、SPI、SoftwareSerial、LiquidCrystal、Stepper 和受限的 SD。接口以 [Arduino.h](cores/STC/Arduino.h) 和各库头文件为准，使用示例位于 `libraries/<库名>/examples`。总线和 GPIO 共用引脚，使用前核对型号和封装。

ABI 使用 16 位 `int`、32 位 `long`/`size_t`/`ptrdiff_t`、24 位指针，大端布局，`double` 与 `float` 均为 32 位。异常、RTTI、线程和完整 STL 不在支持范围内。不要直接发送结构体内存作为外部协议；可使用 `STCByteOrder.h`。运行时配置见 [runtime-manifest.json](cores/STC/cpp/runtime-manifest.json)。

## 烧录

从 [v0.0.1 Release](https://github.com/coloz/arduino-stc51/releases/tag/v0.0.1) 下载对应系统的 `stc-cli` 烧录工具，或使用相邻 `stc-cli` 项目的源码构建。先用 `validate` 检查生成的 HEX，再按实物型号和端口烧录，例如：

```powershell
$stc = '..\stc-cli\target\release\stc-cli.exe'
& $stc validate --expect STC32G12K128 --execution-mode mcs251 --file $build.firmware
& $stc flash --port COM5 --expect STC32G12K128 --execution-mode mcs251 `
    --file $build.firmware --reset manual
```

不同目标所需的实验协议参数以当前 `stc-cli` 的说明为准。支持选择执行模式的芯片应先由官方 ISP 配置为 MCS251；`stc-cli --execution-mode` 用于镜像处理，不会切换芯片硬件模式。

## 维护

```powershell
node .\tools\variants\generate.mjs --check
node .\tools\variants\generate.mjs
.\scripts\package-platform.ps1
```

生成器仅接受 MCS251 型号，并拒绝遗留的孤立 variant 目录。平台和库架构声明统一为 `mcs251`。修改 [devices.json](tools/variants/devices.json) 后重新生成配置。CI 保留工具链源码锁定检查、型号元数据检查和示例编译。

`scripts` 只保留源码构建、工具链打包、索引生成和发布校验入口。用户安装包保留 core、variants、库、示例、编译驱动、锁文件及许可说明；维护脚本、工具链源码补丁和生成器只放在源码仓库。

第三方 SDK、SDCC 的公共 `include/mcs51` 目录和固定上游归档名属于 MCS251 仍需的依赖或来源记录，不代表继续提供 MCS51 Arduino 支持。项目采用 [MIT 许可证](LICENSE)，第三方许可保留于 [LICENSES](LICENSES)。
