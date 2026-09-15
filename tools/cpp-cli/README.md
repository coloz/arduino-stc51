# Arduino MCS251 C++ driver

`stcxx-cli.sh` 提供预处理、C/C++ 编译和最终链接入口，仅接受 MCS251。Clang/LLVM-CBE/SDCC 和运行时适配器由 toolchain-lock.json 校验。保留原生 C ABI 根、归档 sidecar 选择、只读数据存储、函数指针对齐、警告结构和堆/栈布局检查；已移除另一 CPU 架构的专用适配。Windows 路径与 POSIX 路径均可传入。源码构建入口见 [README.md](../../README.md)。

Linux 编译和链接使用 Arduino 选中的 SDCC；显式 `STCXX_SDCC` 或
`STCXX_TOOLCHAIN_ROOT` 可选择开发候选。目录解析先跟随符号链接，再识别
`bin/include/lib` 分发包、`out/share/sdcc` 输出及原始构建目录。
Windows 的 C++ 入口仍使用 WSL 内受锁定的 Linux 工具。

源码目录的 `toolchain-lock.json` 保留开发工具版本。维护者使用
`scripts/package-platform.ps1 -LinuxToolchain portable` 打包时，将维护的
`toolchain-lock.linux-x86_64.json` 复制为包内标准 `toolchain-lock.json`；因此
编译入口和目标验证读取同一份分发锁。默认 `development` 打包不替换开发锁。
Linux 候选索引生成器会拒绝仍选择开发锁的 SDK。可分发 Linux 前端与 Mac
一样校验完整文件清单，包含资源头文件和私有库，并拒绝加载器环境覆盖。
共用校验器暂保留历史文件名 `verify-macos-frontend.py`。

`STCXX_CPP_TOOLS_ROOT` 可指定前端目录，其 `bin` 下应包含 `clang`、`llvm-link`、
`opt`、`llvm-dis` 和 `llvm-cbe`；各工具原有的 `STCXX_*` 环境变量可分别覆盖。
工具锁含 `arduino_frontend` 时，未显式指定根目录会从 Arduino 的
`packages/<packager>/tools/<name>/<version>` 中选择锁定的准确版本；缺少该版本
会报错。未含该绑定的开发锁保留原有开发路径。目录覆盖不会跳过摘要校验，缺失文件不会
回退到其他主机工具。Clang 的 `libclang-cpp` 及五个工具各自实际解析到的
`libLLVM.so.20.1` 也必须匹配锁文件；`scripts/inspect-cpp-toolchain.sh` 使用相同的
路径解析并输出这些实现的摘要。

ARM64 Mac 使用 `toolchain-lock.macos-arm64.json` 和原生工具，不再进入 WSL。
按候选索引安装时自动选择该锁声明的前端依赖。开发目录可设置
`STCXX_CPP_TOOLS_ROOT` 为对应的完整 Mac 前端包；五个工具必须来自
同一包。编译前校验全部文件，包含 Clang、LLVM、zstd 动态库及资源头文件。
不能用其他宿主包、包外单个工具或 `DYLD_*`/`LD_*` 环境覆盖替代受锁定的包。

Mac C++ 入口需要 Bash 4.4+、GNU coreutils 和 Python 3。默认从
`/opt/homebrew/opt/bash/bin/bash`、`/opt/homebrew/opt/coreutils/libexec/gnubin`
及 `/opt/homebrew/bin` 查找；可通过 `STCXX_BASH`、`STCXX_COREUTILS_BIN` 指定
前两者。缺少依赖会直接报告原因。当前前端最低部署版本为 macOS 15，实际测试
系统为 macOS 15.7.1 ARM64。Intel Mac 及其他系统版本需要各自的工具包和验证。
