# arduino-stc51

面向 STC **MCS251** 芯片的 Arduino core。当前版本 **0.0.1**，仅维护 10 个型号；所有型号固定使用 `-mmcs251`，Arduino 架构标识为 `mcs251`。

MCS51 芯片、板项和 C++ 适配路径已移除。旧的 `arduino-stc51:mcs51:…` FQBN 不再适用，需要重新安装当前源码并选择新板项。工程名仍为 `arduino-stc51`。

当前版本供开发和有限场景验证使用，尚未完成实板验收。产品板需验证实际时钟、接线和外设功能；编译成功不代表实板验收通过。

当前维护范围为 **Windows x64 和 Apple Silicon Mac（macOS 15+）**。两端的 C 和 C++ 均使用原生工具，无需 WSL。Windows 前端包自带 Python；macOS C++ 需要 `brew install bash coreutils python`。Linux 独立宿主和 Intel Mac 不在当前支持范围内。详见 [C++ 驱动说明](tools/cpp-cli/README.md)。

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

安装资源见 [v0.0.1 Release](https://github.com/coloz/arduino-stc51/releases/tag/v0.0.1)。本次保持版本号 0.0.1 并替换发布包；已安装旧 0.0.1 的用户也需卸载、更新索引后重新安装，并清理构建缓存。此前的 0.0.2、0.0.3 保持撤下。

开发板管理器在两端都安装 `sdcc-mcs251`、`stcxx-frontend` 和 `stc-cli` 三项工具。Windows 使用系统 PowerShell 5.1、原生 `.exe` 工具及包内 Python；macOS 使用原生 ARM64 工具。C++ 前端负责 Clang → LLVM-CBE 转换，C 和 C++ 共用本机 SDCC，`stc-cli` 负责串口上传。安装依赖已移除占位包 `stc51-native-macos-host`。

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

## 上传

Arduino 上传时，AI8051U 等 ISP 不提供型号 ID 的板项默认使用 IDE 中选择的型号，不再要求手动打开额外确认开关。`工具 → Upload model check` 可切换到 `Require detected model ID`；该严格模式会拒绝无法提供 ID 的协议。具有可识别 ID 的型号继续核对实物与所选型号是否匹配。

正常上传在输出窗口显示等待上电提示和 `Writing... 0%` 至 `100%` 的进度，按芯片确认接收的数据量更新。普通信息和进度使用正常文字颜色，真正的错误保留红色及失败状态。IDE 的“详细上传输出”不会开启原始 ISP 报文；需要排查协议时可单独运行 `stc-cli flash ... --debug`。

STC32G144K246 的 `工具 → Upload method` 默认为 `Automatic (USB CDC or UART)`。所选端口为 STC 原生 USB CDC（`34BF:FF02`）时，通过 `@STCISP#` 切换到工厂 HID 下载；USB 转串口或普通串口使用 UART ISP。`UART ISP` 可显式指定串口下载。芯片已经处于工厂 HID 模式、应用 COM 口不再存在时，选择 `Native USB`，并且只连接一个待下载的 STC HID 设备。USB 路径具有可验证的型号 ID，保留对应的检查。

自动进入 USB 下载要求当前运行的固件支持 `@STCISP#`。普通 Blink 草图没有 USB CDC，烧录后原 COM 口会消失；再次下载时需按开发板方式进入 USB 下载模式并选择 `Native USB`。USB 上传也显示百分比，不修改芯片已有的时钟及硬件选项。

本地替换平台文件后，如果新菜单没有出现，在 IDE 中执行 `工具 → Reload Board Data（重新加载开发板数据）`。IDE 会持久化板型菜单，普通重启未必更新已有缓存；重新加载后检查所选时钟等板型参数。

## 从源码构建

准备 Arduino CLI、PowerShell、tar，以及所需编译工具。以下命令在源码仓库根目录执行；开发板管理器安装包不包含 `scripts` 维护工具：

```powershell
$build = .\scripts\build-example.ps1 `
    -Fqbn 'arduino-stc51:mcs251:stc32g12k128:clock=12m' `
    -WorkDirectory D:\stc51-work `
    -ToolCacheDirectory D:\stc51-tools
$build.firmware
```

脚本将当前源码打包到独立目录，校验工具包的 SHA-256，然后编译示例。`-SketchPath` 可指定含同名 `.ino` 的 sketch 目录；SDCC 构建路径应避免空格。默认 Blink 使用 P3.2，按电路修改引脚，不假设存在板载 LED。

省略 `cppcore=enabled` 时使用 plain C。安装脚本不传 FQBN 时默认编译 STC32G8K64、12 MHz 的 plain C Blink。C++ 配置追加 `,cppcore=enabled`，使用已锁定的本机前端包和 SDCC。G12K128、G144K246 等完整 Flash 布局依赖发布包中重建的 SDCC 分区功能；旧原版工具包不满足时构建会明确拒绝。详见 [C++ 驱动说明](tools/cpp-cli/README.md)。

源码安装脚本用于维护者调试。脚本会下载并校验锁定的 SDCC 归档，也可通过 `-ToolCacheDirectory` 复用本地归档，或通过 `-ToolManifestPath` 指定已验证的工具清单。打包不会自动发布。版本变化见 [RELEASE_NOTES.md](RELEASE_NOTES.md)。

## C++ 与 Arduino API

C++ 使用 Clang → LLVM-CBE → SDCC，提供 `String`、`Print`、`Stream`、`HardwareSerial`、`SPIClass`、`TwoWire` 等接口。所有板项都有 12 MHz C++ 配置；AI8051U-34K64 另有 40 MHz、STC32G144K246 另有 48 MHz。编译时钟必须与芯片实际时钟一致，菜单不会替代 ISP 时钟配置。

支持 GPIO、计时、UART1、按型号提供的 ADC/PWM/外部中断，以及 Wire、SPI、SoftwareSerial、LiquidCrystal、Stepper 和受限的 SD。接口以 [Arduino.h](cores/STC/Arduino.h) 和各库头文件为准，使用示例位于 `libraries/<库名>/examples`。总线和 GPIO 共用引脚，使用前核对型号和封装。

ABI 使用 16 位 `int`、32 位 `long`/`size_t`/`ptrdiff_t`、24 位指针，大端布局，`double` 与 `float` 均为 32 位。异常、RTTI、线程和完整 STL 不在支持范围内。不要直接发送结构体内存作为外部协议；可使用 `STCByteOrder.h`。运行时配置见 [runtime-manifest.json](cores/STC/cpp/runtime-manifest.json)。

## 烧录

Arduino IDE 中选择实际芯片型号和串口，点击“上传”即可调用开发板管理器安装的原生 `stc-cli`。出现等待连接提示后，将芯片断电再上电以进入 ISP；默认等待 60 秒。请关闭占用该串口的串口监视器或其他程序。

AI8051U、STC32CL8K48/64、STC32G12K64 和 STC32G144K246 的 ISP 当前无法提供可核验的型号 ID。核对芯片丝印和 IDE 所选型号后，在“工具 → Upload model check”选择“I checked the chip marking (ISP has no model ID)”。默认保留型号校验，不会自动绕过。STC32G12K128、STC32G8K48/64 使用自动型号校验。

若仍提示 `Property 'upload.tool.serial' is undefined`，说明安装的是旧平台包。由于版本仍为 0.0.1，请卸载旧开发板包、刷新索引并重新安装，然后重启 IDE。

也可从 [v0.0.1 Release](https://github.com/coloz/arduino-stc51/releases/tag/v0.0.1) 下载独立 `stc-cli`，先检查 HEX 再手动烧录，例如：

```powershell
$stc = '..\stc-cli\target\release\stc-cli.exe'
& $stc validate --expect STC32G12K128 --execution-mode mcs251 --file $build.firmware
& $stc flash --port COM5 --expect STC32G12K128 --execution-mode mcs251 `
    --file $build.firmware --reset manual --allow-experimental
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
