# Arduino MCS251 C++ driver

Windows 使用 `stcxx-cli.py`，macOS 使用 `stcxx-cli.sh`。两端均在本机执行 Clang → LLVM-CBE → SDCC，锁定 MCS251 ABI，并核验 C ABI 根、sidecar、堆、存储及最终链接图。共享审计逻辑由相同的 Python 辅助脚本执行。

Windows x64 使用 `toolchain-lock.windows-x86_64.json`，统一工具包的 `frontend/` 包含五个原生 `.exe` 工具及嵌入式 Python。PowerShell 在启动 Python 前核验引导文件和驱动的摘要。不需要 WSL、Ubuntu、Git Bash 或系统 Python。C 和 C++ 共用 `sdcc/` 中的原生 SDCC。

Apple Silicon Mac 使用 `toolchain-lock.macos-arm64.json` 和 ARM64 工具包。C++ 构建需要 Bash 4.4+、GNU coreutils 和 Python 3，可运行 `brew install bash coreutils python` 安装。驱动自动发现 `/opt/homebrew/opt/bash/bin/bash`、`/opt/homebrew/opt/coreutils/libexec/gnubin` 和 `/opt/homebrew/bin`，也支持 `STCXX_BASH`、`STCXX_COREUTILS_BIN` 覆盖路径。最低系统版本为 macOS 15；原组件验证环境为 macOS 15.7.1 ARM64，统一包的宿主执行需单独验证。

编译使用开发板管理器安装的 `stcxx-toolchain`，通过锁文件的 `arduino_toolchain` 精确定位到 `packages/stc/tools/stcxx-toolchain/<version>`。前端位于 `frontend/`，SDCC 位于 `sdcc/`；另有原生 `stc-cli` 用于 IDE 上传。源码调试可用 `STCXX_TOOLS_ROOT` 指定已解压的统一包根目录；原有 `STCXX_CPP_TOOLS_ROOT`（组件前端目录）和 `STCXX_SDCC`（SDCC 可执行文件）覆盖仍保留。覆盖路径仍须通过锁文件中的摘要和 ABI 检查。

前端 `frontend/bin` 目录包含 `clang`、`llvm-link`、`opt`、`llvm-dis`、`llvm-cbe`，Windows 文件带 `.exe` 后缀。归档、工具和运行库均有摘要绑定。`verify-macos-frontend.py` 保留原文件名，同时支持两个原生宿主；动态库环境覆盖 `DYLD_*`/`LD_*` 会被拒绝。

Windows 原生前端构建和打包入口位于 `stcxx` 仓库的 `arduino/scripts/build-windows-frontend.py` 与 `package-windows-frontend.py`。用户安装说明见 [README.md](../../README.md)。Linux 工具只用于内部源码维护，不属于 Windows 安装或构建路径。Intel Mac 和 Linux 独立宿主不在当前发布范围。
