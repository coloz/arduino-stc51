# Arduino MCS251 C++ driver

Windows 使用 `stcxx-cli.py`，macOS 使用 `stcxx-cli.sh`。两端均在本机执行 Clang → LLVM-CBE → SDCC，锁定 MCS251 ABI，并核验 C ABI 根、sidecar、堆、存储及最终链接图。共享审计逻辑由相同的 Python 辅助脚本执行。

Windows x64 使用 `toolchain-lock.windows-x86_64.json`，前端包包含五个原生 `.exe` 工具及嵌入式 Python。PowerShell 在启动 Python 前核验引导文件和驱动的摘要。不需要 WSL、Ubuntu、Git Bash 或系统 Python。C 和 C++ 共用原生 `sdcc-mcs251`。

Apple Silicon Mac 使用 `toolchain-lock.macos-arm64.json` 和 ARM64 工具包。C++ 构建需要 Bash 4.4+、GNU coreutils 和 Python 3，可运行 `brew install bash coreutils python` 安装。驱动自动发现 `/opt/homebrew/opt/bash/bin/bash`、`/opt/homebrew/opt/coreutils/libexec/gnubin` 和 `/opt/homebrew/bin`，也支持 `STCXX_BASH`、`STCXX_COREUTILS_BIN` 覆盖路径。最低系统版本为 macOS 15，本次验证使用 macOS 15.7.1 ARM64。

开发板管理器只安装 `sdcc-mcs251` 和 `stcxx-frontend` 两项工具，按 `packages/<packager>/tools/<name>/<version>` 定位。源码调试可用 `STCXX_CPP_TOOLS_ROOT` 指定已解压的前端根目录，用 `STCXX_SDCC` 指定匹配的本机 SDCC；覆盖路径仍须通过锁文件中的摘要和 ABI 检查。

前端 `bin` 目录包含 `clang`、`llvm-link`、`opt`、`llvm-dis`、`llvm-cbe`，Windows 文件带 `.exe` 后缀。归档、工具和运行库均有摘要绑定。`verify-macos-frontend.py` 保留原文件名，同时支持两个原生宿主；动态库环境覆盖 `DYLD_*`/`LD_*` 会被拒绝。

Windows 原生前端构建和打包入口位于 `stcxx` 仓库的 `arduino/scripts/build-windows-frontend.py` 与 `package-windows-frontend.py`。用户安装说明见 [README.md](../../README.md)。Linux 工具只用于内部源码维护，不属于 Windows 安装或构建路径。Intel Mac 和 Linux 独立宿主不在当前发布范围。
