# arduino-stc51 0.0.2（开发中，尚未发布）

本文件描述当前源码，不是发布公告。仓库中的 Boards Manager 索引仍为 0.0.1；当前源码打出的 0.0.2 平台包尚未成为经过完整发布验证的新版本。文档整理、构建入口调整和测试产物清理不改变功能的实验状态，也不产生新的硬件或发布资格。

## 当前功能

- 22 个 STC8、STC32、AI8051U 和 Ai8H 具体型号。三款 AI8051U 可选择 MCS51 / MCS251，共有 25 种执行配置。
- 默认 plain C，提供 Arduino 风格核心 API，以及 Wire、SPI、SoftwareSerial、LiquidCrystal、Stepper 和受限 SD 随包库。
- 所有 22 款均有 `cppcore=enabled,clock=12m` 实验 C++ 配置；Windows 通过 WSL 使用独立 `stcxx` 工具链与锁定的 Clang / LLVM-CBE 工具。
- 新增 `scripts/build-example.ps1` 和普通 Blink 示例，支持隔离安装当前源码、校验工具包并编译一个指定 sketch。该构建入口不依赖测试矩阵或历史结果文件。
- 可将导出的 Intel HEX 交给独立 `stc-cli` 烧录。Arduino 平台仍不提供自动上传配方；型号、实验参数和执行模式要求见 [README](README.md)。

## 使用限制

C++ 仍为实验功能，不承诺普通 Arduino C++ 库的完整兼容性，不提供异常、RTTI、线程或完整 STL / libstdc++。实际可用 API 和运行时约定分别见 [核心兼容说明](docs/core-api-compatibility.md)、[库兼容说明](docs/library-compatibility.md) 和 [C++ 运行时约定](docs/cpp-runtime-contract.md)。

STC32G144K246 物理 Flash 为 246 KiB，当前普通代码窗口为 182 KiB；STC32G12K128 物理 Flash 为 128 KiB，当前普通代码窗口为 64 KiB。其他 MCS251 地址要求见 [variants-mcs251.md](docs/variants-mcs251.md)。AI8051U 编译执行模式必须与芯片已有硬件配置一致。

当前未完成实板验证。模拟器也不覆盖完整外设、模拟和电气行为、断电启动或周期精确时序；见 [硬件验证状态](docs/hardware-validation.md)。历史测试产物不作为本文件的当前验证结论，也不作为普通源码构建的前置条件。

## 发布状态

发布平台包不包含 `tests/`、本机构建输出和大型工具链源码；`scripts/` 中的开发命令应在完整源码 checkout 运行。工具包按工具清单中的大小与 SHA-256 校验。发布新版本前仍需为对应宿主重新核对当前编译器、补丁、运行时、平台包及功能验证结果，再更新 Boards Manager 索引。

旧 release/index 资产和现有 macOS `r1` 工具包不代表当前源码已具备发布资格。此文档未宣称完成新的编译矩阵、模拟器或实板验证。
