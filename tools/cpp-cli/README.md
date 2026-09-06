# Arduino C++ 构建桥接层

本目录是 Arduino 构建配方使用的运行时工具，连接 Clang、LLVM-CBE 和 SDCC。当前实验性 C++ 配置覆盖 22 个物理型号、25 个执行配置（14 个 MCS51、11 个 MCS251），时钟限定为 12 MHz。编译和链接支持不代表全部配置已完成运行时或实板验证。

普通 C 配方仍是默认入口。启用 C++ 时使用相应板卡的 `cppcore=enabled,clock=12m`，例如：

```text
arduino-stc51:mcs51:stc32g144k246:cppcore=enabled,clock=12m
```

板卡选择、Arduino CLI 用法及 stcxx 工具链项目入口见[平台 README](../../README.md)。

## 构建过程

```text
每个 C++ 翻译单元 → Clang bitcode + SDCC 占位目标文件
                 → Arduino 库发现与归档
                 → 按实际链接输入选择 bitcode
                 → LLVM 链接与审计 → LLVM-CBE → C 适配 → SDCC → HEX
```

每个 C++ 文件独立编译。最终链接时，驱动按实际目标文件和归档成员选择 bitcode，校验关联文件的内容哈希，再完成机器代码生成。C 翻译单元也使用对应的补丁版 SDCC 和 `--stack-auto`。

Core 缓存无法单独保存 LLVM 关联文件，因此本配置禁用 Arduino 的 Core 专用缓存。增量构建目录仍可使用，但旧的或内容不匹配的关联文件会导致构建失败。

## 保留的运行时组件

| 文件 | 用途 |
| --- | --- |
| [stcxx-cli.sh](stcxx-cli.sh) | Arduino 编译、链接入口，检查工具身份并生成构建清单 |
| [adapt.py](adapt.py) | 审计目标 IR，生成构造函数桥接代码，适配 LLVM-CBE 输出 |
| [collect-c-abi-roots.py](collect-c-abi-roots.py)、[select-cpp-archive-sidecars.py](select-cpp-archive-sidecars.py) | 按 C ABI 引用及构造函数依赖选择归档中的 C++ 模块 |
| [align-member-functions.py](align-member-functions.py) | 保留成员函数指针要求的函数对齐，并核对最终地址 |
| [slice-readonly-const-rel.py](slice-readonly-const-rel.py) | 在已证明对象结构和引用范围时裁剪大型只读常量区 |
| [split-c-function-tu.py](split-c-function-tu.py)、[build-function-split-archive.py](build-function-split-archive.py) | 按函数拆分 C 翻译单元并构建归档 |
| [audit-function-split-link-map.py](audit-function-split-link-map.py)、[aslink_map_symbols.py](aslink_map_symbols.py) | 检查最终链接映射、符号和内存布局 |
| [toolchain-lock.json](toolchain-lock.json) | 锁定当前配方要求的工具、运行库、ABI 和适配器身份 |

`adapt.py` 还会动态加载 [cpp-core-pipeline/audit_and_adapt.py](../cpp-core-pipeline/audit_and_adapt.py)。这个共享适配器和上表的链接审计程序均属于实际构建依赖，应随平台保留。

适配器只接受已实现的 IR/C 形态。内部 C 标识符超过 ASxxxx 的安全长度时，按预处理 token 生成带 SHA-256 的短名称；公开 ABI 名称保持原样，不能安全转换的输入会被拒绝。构建清单记录所选模块、适配过程、链接产物及其哈希。

## 准备工具环境

当前 Windows Arduino 配方通过 WSL 调用 Linux 工具。完整 Clang、LLVM-CBE 和 SDCC 的源码准备、构建与安装由 **stcxx** 项目维护；按[平台 README](../../README.md)中的项目入口阅读其构建说明。本目录不提供独立工具链安装器，普通 Boards Manager 安装也不会自动准备这些大型实验工具。

在 WSL 环境中，可用以下变量选择已准备好的工具：

| 变量 | 含义 |
| --- | --- |
| `STCXX_CLANG` | 补丁版 Clang |
| `STCXX_LLVM_LINK`、`STCXX_OPT`、`STCXX_LLVM_DIS` | LLVM 20 工具 |
| `STCXX_LLVM_CBE` | 与锁文件匹配的 LLVM-CBE |
| `STCXX_TOOLCHAIN_ROOT` | stcxx 项目目录；默认从其 `out/bin/sdcc` 取 SDCC |
| `STCXX_SDCC` | 显式覆盖 SDCC 路径 |

Windows 环境变量 `STCXX_WSL_DISTRO` 选择 WSL 发行版，默认 `Ubuntu`。目录可以调整，但指定路径不会跳过工具和运行库的哈希检查；重新构建的二进制不保证自动匹配现有锁文件。

建议构建和工具目录不含空格。当前 Windows SDCC/sdcpp 包自身的 include 路径处理存在空格限制。

## 清理与验证边界

独立测试、原型目录、测试固件和留存的验证产物已移除；上面的运行时组件仍随平台提供。锁文件中的测试路径、测试哈希及旧测量身份作为历史元数据保存，不能当作当前可运行的测试入口或当前工具的通过证据。

生成 HEX、输出 `STCXX_ARDUINO_CLI_LINK=PASS` 或生成哈希清单，只表示本次构建通过了驱动实现的编译与链接检查。完整 ABI、第三方库兼容性、外设运行和实板行为仍需分别验证；本次文件清理不改变任何发布资格结论。
