# arduino-stc51 0.0.2

2026-09-06 发布。Boards Manager 支持 Windows x64、Linux x86_64、macOS Apple Silicon 和 Intel（macOS 11+）。

## 本次更新

- 提供 20 个 STC8、STC32、AI8051U 和 Ai8H 型号，三款 AI8051U 可选 MCS51 / MCS251，共 23 种执行配置。
- 默认 plain C，包含 Arduino 风格核心 API，以及 Wire、SPI、SoftwareSerial、LiquidCrystal、Stepper 和受限 SD 接口。
- 移除 STC8A8K64S4A12 与 STC32F12K54，依据见[型号生命周期记录](docs/variant-lifecycle.md)。
- Linux x86_64、macOS arm64 / x86_64 工具链从固定 SDCC 提交和完整 Arduino 补丁重新构建；Windows plain-C 编译器继续使用校验锁定的上游包。
- 补齐 Linux 的 Boards Manager 工具依赖；新增跨宿主发布校验脚本。
- 附带 stc-cli 0.1.0 的 Windows x64、Linux x86_64、macOS arm64 / x86_64 归档，以及 stc-cli 源码和已应用补丁的 SDCC 对应源码。

## 安装

将以下地址加入 Arduino IDE 的“附加开发板管理器网址”，安装 `arduino-stc51`：

```text
https://raw.githubusercontent.com/coloz/arduino-stc51/main/package_arduino-stc51_index.json
```

平台和重建工具链均使用本 release 的固定下载地址，并锁定大小与 SHA-256。旧 0.0.1 索引条目及其原始归档保持不变。独立 stc-cli 解压后位于 `bin/`，Linux 版要求 GLIBC 2.34+，macOS 版要求 11+；Arduino 的 Linux SDCC 工具链要求 GLIBC 2.29+ / GLIBCXX 3.4.21+。

## 发布验证

- Windows x64、Linux x86_64、macOS arm64 / x86_64：每个宿主的 23 种执行配置均通过 Blink plain-C 编译、链接、HEX 校验/容量检查、stc-cli 离线验证、缓存重编译及错误输入拒绝检查，共 92 项配置编译。Intel macOS 工具在 Apple Silicon 上通过 Rosetta 执行。
- Windows 的 10 种 MCS251 配置通过 HOME / GSINIT0 / Flash 地址布局检查；STC32G144K246 通过四类中断的扩展上下文检查。
- Windows + 已准备的 WSL 工具链：STC8G1K08A 和 STC32G144K246 的 12 MHz 实验 C++ Blink 编译通过。这两项是冒烟验证，不代表完整 C++ 库或运行时矩阵通过。
- stc-cli 源码提交 `94d0f2d3133fee2340c768ffdf5dd11d33391312` 的原生跨平台 CI、Rust 1.85 最低版本、格式及 lint 均通过。Windows/macOS 二进制在本次重新构建；Linux 二进制取自该提交的成功 CI，并在 Ubuntu 上运行完整离线验证。

验证明细见 [发布记录](docs/releases/0.0.2.md) 和 release 附件 `release-qualification.json`；全部附件的大小和 SHA-256 见 `release-manifest.json` 与 `SHA256SUMS`。

## 使用边界

MCS251 和 C++ 保持实验状态，尚未完成实板烧录、复位、时序及外设验证。平台仍不提供自动上传配方，导出的 HEX 由独立 stc-cli 烧录。

C++ 菜单依赖 Windows + WSL 和另行准备的锁定 Clang / LLVM-CBE / stcxx 工具链；本次 Linux/macOS SDCC 归档用于 plain C，并未提供这些宿主的原生 Arduino C++ 构建入口。不提供异常、RTTI、线程或完整 STL / libstdc++。

STC32G144K246 普通代码窗口为 182 KiB，STC32G12K128 为 64 KiB。AI8051U 的编译执行模式必须与芯片已有配置一致；实验烧录参数及身份校验限制见 README 和 stc-cli 包内文档。
