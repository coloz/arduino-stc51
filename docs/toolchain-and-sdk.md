# STC SDK 与编译器基线

本文记录 arduino-stc51 core 在 **2026-08-31** 采用的上游资料基线，并把“厂商 SDK”“编译器”和“烧录工具”分开说明。所有可下载资产的精确机器可读元数据均在 [`../sdk/manifest.json`](../sdk/manifest.json)。

## 已核验的厂商资产

| 资产 | 版本／包内最新记录 | 官方文件 | 大小（字节） | SHA-256 |
|---|---:|---|---:|---|
| AiCube-ISP | 6.97，2026-08-10 | [AiCube-ISP-v6.97.zip](https://www.stcaimcu.com/data/download/Tools/AiCube-ISP-v6.97.zip) | 9,323,009 | `008a899a4ef50e5033181d2f14fd042c7561e74fcaad3e17533b0ec701c0e88d` |
| STC8G/STC8H LIB + DEMO | UPDATE-NOTE 2025-02-05 | [STC8G-STC8H-LIB-DEMO-CODE.zip](https://www.stcaimcu.com/data/download/DemoCode/STC8G-STC8H-LIB-DEMO-CODE.zip) | 8,144,262 | `eeb621c651ba6c65e306a84fcb919ace4af0599d20e87304918dbcc393eec3fc` |
| STC32G SOFTWARE LIB | UPDATE-NOTE 2025-06-23 | [STC32G-SOFTWARE-LIB.zip](https://www.stcaimcu.com/data/download/DemoCode/STC32G-SOFTWARE-LIB.zip) | 11,230,381 | `21de48c004ecfc19f702d0ee7ad7d1528b0e9dd42004b96c99a9fcb0c8f7e4bf` |
| AI8051U 传统风格 SOFTWARE LIB | UPDATE-NOTE 2025-04-10 | [AI8051U-SOFTWARE-LIB.zip](https://www.stcaimcu.com/data/download/DemoCode/AI8051U-SOFTWARE-LIB.zip) | 14,206,137 | `4dafd661b87264ee5ed5e9b8c32af9b285427987d1d3c01f8b873cdd4a228d22` |
| AI8051U 创新风格 32 位 LIB + DEMO | 更新记录 2025-05-28 | [AI8051U专用库函数.zip](https://www.stcaimcu.com/data/download/DemoCode/AI8051U%E4%B8%93%E7%94%A8%E5%BA%93%E5%87%BD%E6%95%B0.zip) | 7,149,144 | `f7e6a82e09ee404e25c598d59d9e311c3215ef97f3cbe8c2c8080f2b0d7c3b77` |
| AI8051U 创新风格 8 位 LIB + DEMO | 更新记录 2025-05-12 | [AI8051U-8bit专用库函数.zip](https://www.stcaimcu.com/data/download/DemoCode/AI8051U-8bit%E4%B8%93%E7%94%A8%E5%BA%93%E5%87%BD%E6%95%B0.zip) | 671,560 | `40ba43f9a52075b0f353c1fa6e6e116e752666db7f68a082f82ccae566e2a93b` |
| STC USB CDC/HID LIB + DEMO | 官方页面／包内 2026-07-29 | [STC_USB_LIBRARY.zip](https://www.stcaimcu.com/data/download/Library/STC_USB_LIBRARY.zip) | 2,382,964 | `3cbc0deb39b03724529790af11f679c1d83b68afa7a1f4610002555d7adcfc47` |

“包内最新记录”是 ZIP 中 `UPDATE-NOTE`、`库函数更新记录.txt` 或最新归档条目的日期，并不表示每个文件都在当天修改。AI8051U 官方将传统风格、创新风格 8 位和创新风格 32 位分开发布，本清单三者分别锁定。USB 包是 STC 当前单列的 2026-07-29 版本，覆盖本支持集中的 STC8H、STC32G 和 AI8051U；这些包都只作为参考资产，不直接链接到 core。器件寄存器与封装引脚仍应以当前[官方手册](https://www.stcai.com/sy)为准。

AiCube-ISP 是 Windows 下的配置生成、ISP 烧录、远程升级和调试工具，不是 C 编译器，也不参与 Arduino core 的编译或链接。

## 为什么不把厂商 SDK 直接提交到仓库

这些 SDK 面向 Keil C51/C251，除源文件和示例外还包含预编译的专有 `.LIB`。在没有足够明确的再分发授权前，本项目不复制 SDK、`.LIB` 或 AiCube-ISP；清单只保存事实性元数据和官方链接。下载是显式选择，并且必须同时通过精确字节数与 SHA-256 校验。

因此，“更新 SDK”在本项目中表示：

1. 固定当前官方包的 URL、内容日期、大小和摘要；
2. 提供可复验的按需下载方式；
3. Arduino core 使用独立、可审计的寄存器和兼容层实现，不把 Keil `.LIB` 当作 SDCC 库链接。

## 按需下载与校验

需要 PowerShell 5.1 或 PowerShell 7。脚本不会使用隐式下载目录；下载时必须显式提供 `-Destination`：

```powershell
# 仅列出清单，不联网
./scripts/fetch-stc-sdk.ps1 -List

# 下载一个包；sdk/downloads 的内容已由局部 .gitignore 忽略
./scripts/fetch-stc-sdk.ps1 -Asset stc8g-stc8h-lib -Destination ./sdk/downloads

# 下载并校验全部厂商资产
./scripts/fetch-stc-sdk.ps1 -All -Destination ./sdk/downloads
```

如果目标文件已经存在，脚本默认只校验并复用；校验失败会立即停止。只有明确传入 `-Force` 才会在新下载通过两项校验后替换同名文件。

## Arduino 的开放编译器路径

本 core 的开放工具链基于社区项目 [gevico/sdcc-c251](https://github.com/gevico/sdcc-c251) 的 `v4.6.0-mcs251-20260804` 标签（提交 `b09075b6a93e6afe10645181e3aeff041ea37f87`），其基础版本为 SDCC 4.6.0：

- Windows x64 资产：[sdcc-mcs251-windows-x64-b09075b6a93e6afe10645181e3aeff041ea37f87.zip](https://github.com/gevico/sdcc-c251/releases/download/v4.6.0-mcs251-20260804/sdcc-mcs251-windows-x64-b09075b6a93e6afe10645181e3aeff041ea37f87.zip)
- macOS Apple Silicon 资产：`dist/sdcc-mcs251-macos-arm64-b09075b6a93e6afe10645181e3aeff041ea37f87.tar.bz2`
- macOS Intel 资产：`dist/sdcc-mcs251-macos-x86_64-b09075b6a93e6afe10645181e3aeff041ea37f87.tar.bz2`
- 编译目标：`-mmcs51` 与 `-mmcs251`

三种宿主资产的精确大小、SHA-256、构建宿主和依赖用途统一记录在 [`../tools/toolchain-manifest.json`](../tools/toolchain-manifest.json)。两份 macOS 资产均从上述固定提交构建：Apple Silicon 版为原生 arm64，Intel 版由 Apple clang 交叉生成并在 Rosetta 下实际执行验证；所有 Mach-O 工具均检查过，不依赖 `/opt/homebrew` 或 `/usr/local` 动态库。

macOS 构建的最小依赖是 Xcode Command Line Tools 与 Homebrew Boost 头文件。可复现脚本不会安装依赖，也只会清理自己通过 `mktemp` 创建的目录：

```sh
brew install boost
sh ./scripts/build-macos-toolchain.sh arm64 ./dist
sh ./scripts/build-macos-toolchain.sh x86_64 ./dist
```

Arduino 的 macOS 配方使用 `/bin/sh`、`/bin/cat` 和主工具链自带的原生 `sdar`。Windows 发行包中的 `sdar.exe` 缺少运行时 DLL，因此只有 Windows 配方继续调用锁定的 CH55xDuino archive helper。两个 helper 依赖同时保留官方 macOS x86_64 flavour，以满足 Arduino 的全局 `toolsDependencies` 解析；macOS 编译配方不会执行它们。

这是社区 fork，不是 STC 官方编译器。`mcs51` 后端用于传统 8051 路径；新增的 `mcs251` 后端仍被上游明确标为 **experimental**。STC32G、STC32CL 或 AI8051U 的 32 位模式必须按实验功能看待：完成最小编译测试不等同于启动代码、中断栈、存储器模型和外设在真实硬件上均已验证。

对量产、功能安全或依赖厂商 `.LIB` 的工程，STC 官方资料所采用的 Keil C51/C251 仍是生产参考路径。Arduino + SDCC 路径应在目标芯片和实际封装上完成烧录、复位、中断、定时器、串口与边界内存测试后再采用。

## 支持边界

- STC8G/STC8H 包覆盖现代 8 位系列的官方参考代码，但具体型号可能裁剪端口或外设。
- STC32G 包是 STC32G 的官方参考；STC32CL 与它共享的内容必须逐项对照型号手册，不能仅凭系列名假定兼容。
- AI8051U 可涉及 C51 与 C251 两种执行路径，预编译库不能跨编译器或存储器模型混用。
- 本清单没有把 STC89、STC12、STC15 的历史示例包误标为“最新 SDK”。这些器件的变体支持以当前数据手册、SFR 和独立 core 实现为准。
