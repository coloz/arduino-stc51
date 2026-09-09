# STC SDK 与编译器基线

> **0.0.2 发布更新（2026-09-06）**：四种宿主各 23 项 plain-C 配置已通过编译与离线镜像校验；Linux/macOS `r1` 工具链已按最终补丁重建。Windows 保留上游 plain-C 编译器。实验 C++ 的 Arduino 入口仅支持另行准备工具链的 Windows + WSL。当前证据见[发布记录](releases/0.0.2.md)，下方旧 C++ 矩阵记录不构成本次的新运行时资格。

> Lifecycle update (2026-09-06): the active platform now has **20 models / 23 execution profiles**
> (13 MCS51 + 10 MCS251). STC8A8K64S4A12 and STC32F12K54 were removed.
> The 22-model / 25-profile / 31-workload set and removed-device details below are
> historical toolchain/qualification records, not the current support list or new PASS evidence.
> See the [lifecycle review](variant-lifecycle.md).

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
- Linux x86_64 资产：旧 `r1` 已删除；构建脚本现在只会在 fresh source 上严格应用并验证最终组合补丁，但新的宿主归档尚未构建，仍为 **NOT QUALIFIED**，不得先填 size/hash
- macOS Apple Silicon：现有本地 `...-r1.tar.bz2` 生成于最终组合补丁之前，且生成它的 macOS 脚本没有应用该补丁；**NOT QUALIFIED**，不得发布或写入当前工具索引
- macOS Intel：现有本地 `...-r1.tar.bz2` 与 Apple Silicon 包具有相同的旧构建路径；**NOT QUALIFIED**，不得宣称含有最终 ISR/R9、PointerGet displacement 和重叠寄存器修复
- 编译目标：`-mmcs51` 与 `-mmcs251`

实验性 MCS51/MCS251 C++ profile 的全部编译器源码单独放在
`D:\Git\stc51\stcxx`（WSL：`/mnt/d/Git/stc51/stcxx`），不再依赖旧的
用户缓存编译器目录。固定入口为
`/mnt/d/Git/stc51/stcxx/out/bin/sdcc`。该项目包含 Clang 20.1.8 IR-only
前端、LLVM 20、固定提交的 LLVM-CBE，以及带 MCS251 ISR、间接访问、指针偏移、
重叠寄存器和扩展 SPX/SSEG 栈修复的 Linux SDCC。最终身份为：

- standalone 分支：`arduino-cpp-core`；本轮源码已提交为 `f16b00a71e3da804b52b796b332ff5696db4280a`，输入同时由下列补丁和锁的哈希绑定。`7f7127e65368eb4fb67c9f93cfb0ecd558ff456b` 是以前的快照，历史资格不转移至新提交；
- Clang source patch：`f8fda423712d808dd087d4e789b1e824911cde62d738078bf9325a898d8476c0`；
- LLVM-CBE source patch：`0a332f0000aa9d335eb4c0b67bbd40b3020d9acf586c4279b5e8a0ecd2c3025f`；
- launcher/wrapper：`e4674cb08f4db442ef7485318c49c47a90e1a319e5ca2cb3ac38123d99a7a234`；
- SDCC frontend ELF：`64c9a96111e94795841f0e05e4664d6c2c0d9eaa117a2ce996e1bc32cca3dda2`；
- `sdldmcs251`：`dc3ceeee91443710efb32edec129ec6a0202b59454af58fbb50517c689c5bb0e`；
- 完整源补丁：`fcb1342a77a412dbb8b0c8c6e8e4df5e1b59744790e63e40c32dd812c9472e12`。

standalone `check-out-wsl.sh` 的固定输出清单也被锁定：`out/MANIFEST.sha256`
SHA-256 为 `35b33920150a280dcb10bc1252bf490a350ce51b01b639855df1ad000761f735`，
`out/toolchain-lock.json` SHA-256 为
`127cbed44a13052360a403bde6495de9de08f0b6bb1614e1613681660105f595`。

锁及其余工具身份记录在 `tools/cpp-cli/toolchain-lock.json` 与
`tools/cpp-core-pipeline/toolchain-lock.json`；补丁、独立 regression 和验证边界见
`tools/toolchain-patches/README.md`。旧的
`sdcc-mcs251-isr-context.patch` 只是最终补丁的后端修复组件，不是当前完整
Arduino C++ 编译器补丁。

Arduino CLI 已为 20 个物理型号、23 个 MCS51/MCS251 执行配置提供明确的
12 MHz opt-in 入口；例如 K246：

```text
arduino-stc51:mcs51:stc32g144k246:cppcore=enabled,clock=12m
```

plain-C 仍是默认项；MCS51 与 MCS251 均有匹配各自 endian、`size_t`、普通函数指针
和成员指针布局的 frontend/bridge。资格合同固定为 25 个配置（14 MCS51 + 11
MCS251）与 31 个 workload（6 compact×2 + 19 full×1）；当前 clean
compile/link/capacity 与精确 QEMU outcome 只读取 `tests/cpp/variant-matrix/*.json`。
这 6 个 compact profile 包含原有四个 8/12 KiB 配置和 AI8051U-34K16 的两个
执行模式；后者程序上限固定为 14,336 字节。STC32F12K54 使用受约束的
3,584 字节 heap + 512 字节静态 XDATA reserve，二者之和严格受 4 KiB XDATA 限制。
默认 24 MHz 不在当前 C++ 资格范围。Windows recipe 还要求预先准备的 WSL/Ubuntu
工具环境，平台归档没有携带这些大型 Linux 实验工具；因此普通 Boards Manager 安装
并不等于具备可移植的 C++ 工具链。该入口及其运行结果仍统一标记为
`EXPERIMENTAL` / `NOT_SUPPORTED`，不能据此宣称广泛兼容 Arduino C++ 库。

锁定 adapted-C bridge 的 SDCC 编号 warning 契约为：84 x17、196 x14、244 x22、
357 x1；独立 R9 regression 另要求 244 x1，普通保留 C 源不允许编号 warning。
任何缺失、额外或计数变化都会使门禁失败。

锁定 QEMU 源提交 `faeac38c0076795d7b4e59f0ddcb5fc7e7bd7015` 为 22 个物理型号、
25 个执行配置提供精确 machine；`qemu-system-mcs51` 和 `qemu-system-mcs251`
SHA-256 分别为 `08b41280f0a326ab5fe4ca2f18ed6d41860a7b4bb488b2b0a58fc5f088ea8157`
与 `81c1246c4d85911b03562307ae23df50cba636098be9af1fdcfa38fd192cf3e7`。
它们只验证各 machine 已建模的行为，不覆盖真实晶振/ISP 配置、电气与模拟特性、
引脚负载、复位/掉电行为或模型外设。model 存在不等于 runtime PASS；任何 25-profile/
31-workload C++ 结论必须绑定同一次 source set、clean build manifest、固件 SHA-256
和逐 workload runtime audit，不得使用 machine alias 或历史固件替代。
最终 25-profile/31-workload clean run 正在重新生成；在权威 JSON 完整且相互哈希绑定
以前，不把已建模的 25 个 machine 写成 runtime PASS。默认宿主时序补充集合为
9 个 profile、11 个 workload，也不能替代锁定时序全矩阵。
当前没有代表性 K246 实板资格认证；在完成烧录、复位、中断、栈边界、时序和外设实测前，
QEMU PASS 不能升级为硬件发布或量产支持结论。

0.0.2 的跨宿主 plain-C 发布矩阵覆盖 Windows x64、Linux x86_64、macOS arm64 和 x86_64（11+）。Linux/macOS 归档均从锁定提交加完整补丁重建，并在各自宿主通过 23 项配置检查；Intel 工具通过 Rosetta 执行。全部归档的准确大小、SHA-256 和构建信息见 `tools/toolchain-manifest.json`。本次验证不扩展 C++、外设或实板支持范围。

Linux x86_64 构建需要 GCC/G++、Make、Bison、Flex、Boost 与 zlib 头文件、
`file`、`readelf` 和 bzip2。发布资产使用 digest 锁定的 Debian 11 镜像：

```sh
docker build -f scripts/linux-toolchain.Dockerfile -t arduino-stc51-toolchain:debian11 .
docker run --rm --user "$(id -u):$(id -g)" -v "$PWD:/work" -w /work \
  arduino-stc51-toolchain:debian11 \
  sh ./scripts/build-linux-toolchain.sh x86_64 ./dist
```

脚本只接受原生 Linux x86_64 主机，锁定上游标签、提交和组合补丁 SHA，在 fresh clone
上执行 strict apply/reverse-check 和 patched `gen.c` blob 校验，再构建、安装并检查编译器
可运行性、ELF 架构和动态依赖后打包。独立回归检查已移除。它原子创建固定的架构专用
临时目录；若目录已存在则拒绝覆盖，只清理本次自己创建的目录。输出为
`sdcc-mcs251-linux-x86_64-<commit>-r<revision>.tar.bz2`；包修订号用于区分同一份锁定源码的宿主打包改进，避免覆盖已发布工具缓存。

macOS 构建的最小依赖是 Xcode Command Line Tools、Homebrew Boost 头文件和 GNU tar。
产物的最低部署目标为 macOS 11.0；Intel 版本已重建，并通过 Rosetta 执行 plain-C 发布矩阵。
可复现脚本不会安装依赖；它校验固定补丁和源码 blob，并检查编译器可运行性、Mach-O
架构、部署目标和动态依赖。脚本原子创建固定的架构专用临时目录，拒绝复用已存在目录，也只清理本次自己创建
的目录：

```sh
brew install boost gnu-tar
sh ./scripts/build-macos-toolchain.sh arm64 ./dist
sh ./scripts/build-macos-toolchain.sh x86_64 ./dist
```

Arduino 的 Linux 和 macOS 配方使用系统 `/bin/sh`、`/bin/cat` 和主工具链自带的原生 `sdar`。Windows 发行包中的 `sdar.exe` 缺少运行时 DLL，因此只有 Windows 配方继续调用锁定的 CH55xDuino archive helper。helper 依赖仍为每个 Boards Manager 宿主提供可解析的 flavour；Linux 和 macOS 编译配方不会执行它们。

## 不可变发布资产

Boards Manager 索引本身使用固定的 `main` 分支 URL，便于客户端发现新版本；
平台归档和本项目构建的工具链归档则发布到对应 `v<版本>` GitHub Release，索引
使用 `releases/download/v<版本>/<文件名>` URL。发布后不得覆盖或重建同名资产。
任何字节变化都必须使用新的平台版本，并同步更新索引、字节数和 SHA-256；旧版本
条目及其 Release 资产继续保留，以保证已有安装和缓存仍可复验。

这是社区 fork，不是 STC 官方编译器。`mcs51` 后端用于传统 8051 路径；新增的 `mcs251` 后端仍被上游明确标为 **experimental**。STC32G、STC32CL 或 AI8051U 的 32 位模式必须按实验功能看待：完成最小编译测试不等同于启动代码、中断栈、存储器模型和外设在真实硬件上均已验证。

对量产、功能安全或依赖厂商 `.LIB` 的工程，STC 官方资料所采用的 Keil C51/C251 仍是生产参考路径。Arduino + SDCC 路径应在目标芯片和实际封装上完成烧录、复位、中断、定时器、串口与边界内存测试后再采用。

## 支持边界

- STC8G/STC8H 包覆盖现代 8 位系列的官方参考代码，但具体型号可能裁剪端口或外设。
- STC32G 包是 STC32G 的官方参考；STC32CL 与它共享的内容必须逐项对照型号手册，不能仅凭系列名假定兼容。
- AI8051U 可涉及 C51 与 C251 两种执行路径，预编译库不能跨编译器或存储器模型混用。
- STC89、STC12、STC15 只作为历史资料来源保留，不再属于当前 variants、板项或发布测试矩阵。
