# arduino-stc51

面向 STC 8051 / 251 单片机的 Arduino core，提供芯片级开发板定义、GPIO / 定时 / 串口等 API、常用外设库，以及生成 Intel HEX 的 SDCC 构建流程。默认使用 plain C；需要 C++ 类和 Arduino 类库接口时，可显式启用实验 C++ 配置。

当前源码版本为 **0.0.2 开发版**，包含 22 个具体型号、25 种执行配置。源码支持范围与发布包版本不同；目前仓库的 Boards Manager 索引仍为 0.0.1。当前功能尚未完成实板验证，编译成功和模拟器运行不能替代硬件验证。版本信息见 [RELEASE_NOTES.md](RELEASE_NOTES.md)。

三个项目分别负责开发流程中的不同部分：

| 项目 | 用途 |
| --- | --- |
| `arduino-stc51` | Arduino core、开发板定义、引脚和库接口，编译 sketch 并导出 HEX |
| `stcxx` | 独立 STC C / C++ 工具链；为实验 C++ 路径提供编译器和运行时 |
| `stc-cli` | 独立 UART ISP 命令行工具，检查和烧录导出的 HEX |

三个仓库可以并排放置，例如 `D:\Git\stc51\arduino-stc51`、`D:\Git\stc51\stcxx`、`D:\Git\stc51\stc-cli`。Arduino 平台目前没有自动上传配方，烧录使用独立工具。

## 芯片范围

型号来自 [devices.json](tools/variants/devices.json)，由生成器维护 `boards.txt` 和 `variants/`。不要仅凭相近型号替代选择；封装实际引脚还应核对对应芯片手册。

| 执行体系 | 型号 | 数量 |
| --- | --- | ---: |
| MCS51 / STC8 | STC8A8K64S4A12、STC8C2K64S4、STC8G1K08、STC8G1K08A、STC8G2K64S4、STC8H1K08、STC8H1K28、STC8H3K64S4、STC8H8K64U | 9 |
| MCS51 / Ai8H | Ai8H2K12U、Ai8H2K32U | 2 |
| MCS251 / STC32 | STC32CL8K48、STC32CL8K64、STC32F12K54、STC32G12K64、STC32G12K128、STC32G144K246、STC32G8K48、STC32G8K64 | 8 |
| MCS51 / MCS251 双模式 | AI8051U-34K16、AI8051U-34K32、AI8051U-34K64 | 3 |

AI8051U 默认 MCS51，可选择 `execution=mcs251`。三款双模式芯片带来 14 个 MCS51、11 个 MCS251 配置；切换编译配置不会改变芯片的硬件执行模式。MCS251 的地址布局与链接边界见 [variants-mcs251.md](docs/variants-mcs251.md)。

## 安装和首次构建

使用已发布版本时，将以下地址添加到 Arduino IDE 的“附加开发板管理器网址”，再安装 `arduino-stc51`：

```text
https://raw.githubusercontent.com/coloz/arduino-stc51/main/package_arduino-stc51_index.json
```

对应的 Arduino CLI 命令如下。安装结果是索引中的已发布版本，不包含当前源码的全部新增功能。

```powershell
arduino-cli config add board_manager.additional_urls https://raw.githubusercontent.com/coloz/arduino-stc51/main/package_arduino-stc51_index.json
arduino-cli core update-index
arduino-cli core install arduino-stc51:mcs51
```

**构建当前源码**：Windows 上准备 Arduino CLI、PowerShell、`tar` 和 `curl.exe`，然后在本仓库根目录运行：

```powershell
$build = .\scripts\build-example.ps1 -WorkDirectory D:\stc51-work
$build.firmware
```

脚本将当前源码打包并安装到独立工作目录，按 [工具清单](tools/toolchain-manifest.json) 下载或复用经过大小和 SHA-256 校验的 Windows 工具包，然后编译一个 STC8G1K08A、12 MHz 的 [Blink](examples/Blink/Blink.ino) 示例。首次使用需要下载依赖；工具缓存位于 `sdk/downloads/toolchain`。它保留生成的 HEX、构建目录和 Arduino CLI 配置，便于继续开发。

Blink 使用 P3.2，需按自己的电路连接 LED 和限流电阻或修改引脚。平台不假定存在板载 LED，通用 `LED_BUILTIN` 为 `NOT_A_PIN`。时钟菜单必须与 ISP 中设置的实际时钟一致；core 不自动校准或切换系统时钟。

编译自己的 sketch 目录，或指定其他型号：

```powershell
$build = .\scripts\build-example.ps1 `
    -Fqbn 'arduino-stc51:mcs51:stc32g144k246:clock=12m' `
    -SketchPath D:\sketches\MySketch -WorkDirectory D:\stc51-work

arduino-cli compile --config-file $build.config `
    --fqbn 'arduino-stc51:mcs51:stc32g144k246:clock=12m' `
    --build-path D:\stc51-work\my-build D:\sketches\MySketch
```

`SketchPath` 是包含同名 `.ino` 的目录。Arduino CLI 不在 PATH 时，可传 `-ArduinoCli 'C:\Program Files\Arduino CLI\arduino-cli.exe'`。当前 SDCC 要求 sketch 和构建路径不含空格。源码安装脚本目前面向 Windows；其他宿主的工具链资料见 [toolchain-and-sdk.md](docs/toolchain-and-sdk.md)。

## Plain C 和实验 C++

默认路径使用 SDCC 编译 plain C。支持 `setup()` / `loop()`，以及 `pinMode`、`digitalWrite`、`millis`、`micros`、`delay`、外部中断、按型号提供的 ADC 和 UART1。`Serial.begin()`、`Wire.begin()` 等点语法在 plain C 中由函数指针表实现，不提供 C++ 重载、继承或类模板。

随平台提供 Wire、SPI、SoftwareSerial、LiquidCrystal、Stepper 和受限 SD 接口；兼容范围、软件实现和引脚限制见 [核心 API](docs/core-api-compatibility.md) 与 [库兼容说明](docs/library-compatibility.md)。一般 Arduino C++ 库不能直接按 plain C 编译。

实验 C++ 配置使用定制 Clang → LLVM-CBE → SDCC 流程，提供 `String`、`Print`、`Stream`、`HardwareSerial`、`SPIClass`、`TwoWire` 等类接口及受限运行时。22 个型号均有显式配置，**当前只允许 12 MHz**。先按 `stcxx` 仓库说明准备工具链，再按 [工具链说明](docs/toolchain-and-sdk.md) 配置对应的 Clang / LLVM 工具。Windows 配方通过 WSL 调用这些 Linux 工具，Boards Manager 平台包不包含它们。

```powershell
$env:STCXX_WSL_DISTRO = 'Ubuntu'
$build = .\scripts\build-example.ps1 `
    -Fqbn 'arduino-stc51:mcs51:stc32g144k246:cppcore=enabled,clock=12m' `
    -SketchPath D:\sketches\MyCppSketch -WorkDirectory D:\stc51-work
```

当前独立工具链默认路径为 `D:\Git\stc51\stcxx`，WSL 对应 `/mnt/d/Git/stc51/stcxx`，SDCC 入口为 `out/bin/sdcc`。路径可在 WSL 中通过 `STCXX_TOOLCHAIN_ROOT` / `STCXX_SDCC` 覆盖，其他二进制也有相应 `STCXX_*` 变量；实际文件必须匹配工具锁的校验值。仅准备普通 SDCC 或仅启用菜单不足以启用 C++。

AI8051U 的 C++ MCS251 配置示例为 `arduino-stc51:mcs51:ai8051u_34k32:execution=mcs251,cppcore=enabled,clock=12m`。不支持异常、RTTI、线程或完整 STL / libstdc++；详细边界见 [C++ 运行时约定](docs/cpp-runtime-contract.md)。

## 用 stc-cli 烧录

在相邻 `stc-cli` 仓库构建 `cargo build --release --locked`，或使用其已构建的可执行文件。Arduino IDE 可用“导出已编译的二进制文件”得到 HEX；上面的源码脚本通过 `$build.firmware` 返回 HEX 路径。

先编译 STC8G1K08A，再检查和烧录同一个 HEX；将 COM5 替换为实际串口，并按 ISP 要求重新上电：

```powershell
$build = .\scripts\build-example.ps1 -WorkDirectory D:\stc51-work
$stc = '..\stc-cli\target\release\stc-cli.exe'
& $stc validate --expect STC8G1K08A --file $build.firmware
& $stc flash --port COM5 --expect STC8G1K08A --file $build.firmware --reset manual
```

`--expect` 必须与刚编译的 FQBN 型号一致。其他芯片按其支持等级添加参数，例如以下命令分别使用为对应目标生成的 `MySketch.hex`：

```powershell
& $stc flash --port COM5 --expect STC32G144K246 --file MySketch.hex --allow-experimental --force-unverified-target
& $stc flash --port COM5 --expect AI8051U_34K32 --file MySketch.hex --execution-mode mcs251 --allow-experimental --force-unverified-target
```

当前 `stc-cli` 为这 22 款型号都实现了烧录路径，其中 7 款标记 stable、15 款 experimental；该等级不等于本 Arduino core 已获实板验证。9 款官方协议目标因尚无可核实的 UART 身份映射，要求同时传入 `--allow-experimental` 与 `--force-unverified-target`：STC32CL8K48/64、STC32G12K64、STC32G144K246、三款 AI8051U，以及 Ai8H2K12U/32U。

AI8051U 烧录前需用官方 ISP 将芯片设置为与 HEX 一致的 MCS51 / MCS251 模式；`stc-cli --execution-mode` 只选择镜像处理模式，不修改芯片硬件选项。型号、容量、实验协议和完整参数应以 `stc-cli` 的 README 与 `docs/PROTOCOL_SUPPORT.md` 为准。

## 使用边界与开发资料

- STC32G144K246 物理 Flash 为 246 KiB，当前普通程序链接窗口为 182 KiB；STC32G12K128 物理 Flash 为 128 KiB，当前普通程序窗口为 64 KiB。不要按物理容量直接扩大链接范围。
- Timer0 用于系统计时，UART1 占用 Timer1。ADC 能力和 GPIO 可用掩码按型号定义，具体封装可能引出更少的引脚。
- PWM、EEPROM / IAP、USB、CAN、DAC、硬件 I²C / SPI、多路 UART、tone 和 Servo 尚未作为通用 API 提供。
- 模拟器覆盖 CPU、内存和部分 UART / 定时器行为，不能验证模拟外设、电气条件或周期精度。硬件验证要求见 [hardware-validation.md](docs/hardware-validation.md)。

开发板数据库和打包操作应在完整源码 checkout 根目录运行：

```powershell
node .\tools\variants\generate.mjs --check
node .\tools\variants\generate.mjs
.\scripts\package-platform.ps1
```

`scripts/` 中的源码构建脚本不代表安装包包含完整开发环境；发布平台不包含 `tests/`、本机构建输出或大型工具链源码。`package-platform.ps1` 输出平台归档到 `dist/`，不会发布新版本或更新远端索引。

项目代码使用 [MIT 许可证](LICENSE)，第三方代码的许可证和来源保留在 [LICENSES](LICENSES)。
