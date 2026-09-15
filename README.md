# arduino-stc51

面向 STC **MCS251** 芯片的 Arduino core。当前源码版本 **0.0.3，尚未发布**，仅维护 10 个型号；所有型号固定使用 `-mmcs251`，Arduino 架构标识为 `mcs251`。

MCS51 芯片、板项和 C++ 适配路径已移除。旧的 `arduino-stc51:mcs51:…` FQBN 不再适用，需要重新安装当前源码并选择新板项。工程名仍为 `arduino-stc51`。

当前版本供开发和有限场景验证使用，尚未完成统一正式发布及实板验收。使用说明见[文档目录](docs/README.md)，产品板应按[硬件验证说明](docs/hardware-validation.md)验证实际功能。

本次生产发布仅面向 **Windows 和 macOS**。Windows 的 C++ 流程仍需 WSL；Linux 独立宿主不纳入发布适配和验收。各宿主的实际验证范围见[发布宿主范围](docs/release-host-scope.md)。

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

STC32CL8K48／64 提供硬件 Wire、SPI、PWM 和访问加速，默认 Wire 接线为 SDA=P3.3、SCL=P3.2。各型号外设和引脚配置见[实际开发说明](docs/arduino-practical-api.md)。

## 从源码构建

准备 Arduino CLI、PowerShell、tar，以及所需编译工具。以下命令在仓库根目录执行：

```powershell
$env:STCXX_WSL_DISTRO = 'Ubuntu'
$build = .\scripts\build-example.ps1 `
    -Fqbn 'arduino-stc51:mcs251:stc32g12k128:cppcore=enabled,clock=12m' `
    -WorkDirectory D:\stc51-work
$build.firmware
```

脚本将当前源码打包到独立目录，校验工具包的 SHA-256，然后编译示例。`-SketchPath` 可指定含同名 `.ino` 的 sketch 目录；SDCC 构建路径应避免空格。默认 Blink 使用 P3.2，按电路修改引脚，不假设存在板载 LED。

省略 `cppcore=enabled` 时使用 plain C。安装脚本不传 FQBN 时默认编译 STC32G8K64、12 MHz 的 plain C Blink，可使用固定的原生工具包。G12K128、G144K246 等完整 Flash 布局需要重建后的 SDCC 分区功能；旧原版工具包不满足时构建会明确拒绝。C++ 路径使用相邻 `stcxx` 项目的已锁定工具链，Windows 下通过 WSL 调用，默认 SDCC 为 `D:\Git\stc51\stcxx\out\bin\sdcc`。详见[工具链说明](docs/toolchain-and-sdk.md)。

新架构尚未生成已发布资产，当前包索引不再列出旧 MCS51 平台，也不提供虚假的 0.0.3 下载地址。现阶段请使用源码安装脚本；打包不会自动发布。版本变化见 [RELEASE_NOTES.md](RELEASE_NOTES.md)。

## C++ 与 Arduino API

C++ 使用 Clang → LLVM-CBE → SDCC，提供 `String`、`Print`、`Stream`、`HardwareSerial`、`SPIClass`、`TwoWire` 等接口。所有板项都有 12 MHz C++ 配置；AI8051U-34K64 另有 40 MHz、STC32G144K246 另有 48 MHz。编译时钟必须与芯片实际时钟一致，菜单不会替代 ISP 时钟配置。

支持 GPIO、计时、UART1、按型号提供的 ADC/PWM/外部中断，以及 Wire、SPI、SoftwareSerial、LiquidCrystal、Stepper 和受限的 SD。具体硬件总线布局、错误返回值、引脚冲突和内存限制见[实际开发说明](docs/arduino-practical-api.md)、[API 兼容范围](docs/core-api-compatibility.md)和[库说明](docs/library-compatibility.md)。

ABI 使用 16 位 `int`、32 位 `long`/`size_t`/`ptrdiff_t`、24 位指针，大端布局，`double` 与 `float` 均为 32 位。异常、RTTI、线程和完整 STL 不在支持范围内。不要直接发送结构体内存作为外部协议；可使用 `STCByteOrder.h`。运行时约定见 [cpp-runtime-contract.md](docs/cpp-runtime-contract.md)。

## 烧录

使用相邻 `stc-cli` 项目的当前源码构建。先用 `validate` 检查生成的 HEX，再按实物型号和端口烧录，例如：

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

生成器仅接受 MCS251 型号，并拒绝遗留的孤立 variant 目录。平台和库架构声明统一为 `mcs251`。型号配置见[变体说明](docs/variants-mcs251.md)，维护回归入口见[测试说明](tests/README.md)。

第三方 SDK、SDCC 的公共 `include/mcs51` 目录和固定上游归档名属于 MCS251 仍需的依赖或来源记录，不代表继续提供 MCS51 Arduino 支持。项目采用 [MIT 许可证](LICENSE)，第三方许可保留于 [LICENSES](LICENSES)。
