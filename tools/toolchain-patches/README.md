# MCS251 编译器源码补丁

`sdcc-mcs251-arduino-cpp.patch` 是当前 Linux/WSL 和 macOS 工具链构建脚本使用的完整补丁。它应用于 `gevico/sdcc-c251` 的 `b09075b6a93e6afe10645181e3aeff041ea37f87` 提交，SHA-256 为 `310d5d53f3cf246ea34b18bad44a868cb7dcd8f55faab317f5505da30747ef2d`。

补丁包含 MCS251 后端、ISR 上下文、完整 Flash 布局、函数和数据分区，以及 Arduino C++ 运行时需要的修正。源码由相邻的 `stcxx` 项目维护，本目录保留用于工具链重建的副本。

维护入口：

- `scripts/build-linux-toolchain.sh`：构建内部源码维护使用的 Linux SDCC 工具包，不进入 Windows 或 macOS 的安装依赖。
- `scripts/build-macos-toolchain.sh`：构建原生 macOS SDCC 工具包。
- `scripts/check-toolchain-build-inputs.py`：检查构建脚本、补丁与分发锁中的源码身份一致。

Clang 和 LLVM-CBE 的来源补丁分别保留在 `tools/clang-stc-target` 和 `tools/llvm-cbe-stc`，其 SHA-256 记录于 `tools/cpp-cli/toolchain-lock*.json`。完整前端重建入口由 `stcxx` 维护。

上述源码补丁不进入开发板管理器安装包。当前型号和使用说明见 [平台 README](../../README.md)。
