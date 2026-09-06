# Clang 20.1.8 STC IR 前端补丁

本目录保留实验性 MCS51 / MCS251 Clang 前端的补丁、CMake 兼容辅助文件和来源锁。补丁使 Clang 输出 STC 配置的 LLVM IR / bitcode；最终机器代码由 LLVM-CBE、Arduino 适配器和 SDCC 生成。

完整工具链的源码准备与构建由 **stcxx** 项目维护，入口见[平台 README](../../README.md)。Arduino 集成方式见 [cpp-cli README](../cpp-cli/README.md)。

## 保留文件

| 文件 | 用途 |
| --- | --- |
| [clang-20.1.8-stcsdcc-ir-only.patch](clang-20.1.8-stcsdcc-ir-only.patch) | 针对锁定 Clang 20.1.8 源码的目标布局和 IR 输出补丁 |
| [toolchain-lock.json](toolchain-lock.json) | 源码压缩包、补丁、修改后源码和目标布局的身份 |
| [cmake/BootstrapZstd.cmake](cmake/BootstrapZstd.cmake) | 为缺少 zstd 导入目标的宿主 LLVM CMake 配置提供显式兼容设置 |
| 本 README | 描述补丁作用和使用边界 |

CMake 辅助文件只处理已经安装的 zstd 库，不负责下载或安装依赖。完整 LLVM 开发环境不需要这项兼容设置。

## 补丁作用

补丁只识别下面两个完整 triple：

```text
msp430-stc51-none-eabi
msp430-stc-none-eabi
```

它借用 LLVM 的 MSP430 架构标识，通过精确的 vendor、OS 和 EABI 组合选择 STC 布局。补丁提供以下处理：

- 为两个目标设置不同的标量与指针布局，定义 `__STC_MCS51__` 或 `__STC_MCS251__`，以及 `__STC_CLANG_IR_ONLY__`。
- 默认使用无符号 `char`；显式覆盖此选项会改变 ABI，不能与现有配方混用。
- 在输出 LLVM IR / bitcode 时跳过 MSP430 `TargetMachine`，保留 STC 数据布局。
- 拒绝直接生成汇编或原生目标文件，避免进入 MSP430 机器代码后端。

可用已构建的补丁版 Clang 输出 IR 或 bitcode：

```sh
clang --target=msp430-stc51-none-eabi -emit-llvm -S input.cpp -o input-mcs51.ll
clang --target=msp430-stc-none-eabi -emit-llvm -c input.cpp -o input-mcs251.bc
```

这些命令只说明前端输出方式。实际 Arduino C++ 编译需要由平台配方提供完整的语言选项、运行时头文件和 ABI 约束。普通 `-S` / `-c` 不受此目标支持；也不能将生成的 IR 直接交给 MSP430 `llc` 后端。

## 实验性数据模型

| 属性 | MCS51 | MCS251 |
| --- | ---: | ---: |
| 字节序 | 小端 | 大端 |
| `char` | 无符号 8 位 | 无符号 8 位 |
| `short` / `int` | 16 位 | 16 位 |
| `long` / `size_t` / `ptrdiff_t` | 32 / 16 / 32 位 | 32 / 32 / 32 位 |
| 通用数据指针 | 24 位带标签 | 24 位平面地址 |
| 普通函数指针 | 16 位程序地址 | 24 位程序地址 |
| 数据成员 / 成员函数指针 | 2 / 4 字节 | 3 / 6 字节 |
| `float` / `double` / `long double` | IEEE binary32 | IEEE binary32 |
| 自然及聚合 ABI 对齐 | 1 字节 | 1 字节 |

精确 LLVM DataLayout 字符串见锁文件的 `target_profiles`。下游必须同时检查 triple 与 DataLayout；这些值描述 Clang 的 IR 模型，不能单独证明 SDCC 对象布局、参数传递、栈和运行库完全兼容。

## 清理与资格边界

本目录的 bootstrap/checker、probe 源码和旧结果文件已移除，当前只保留上表列出的组件。锁文件中的测试名称、probe 哈希和历史结果身份用于来源追溯，不是当前可重复运行的测试证据。构建应使用 stcxx 的正式入口。

该前端仍是实验实现：目标身份借用 MSP430，部分调用 ABI 分类沿用其代码路径。成员指针宽度及对应转换已有专门实现，但完整类布局、虚表、聚合参数、地址空间、可变参数及与 SDCC 的 ABI 兼容性仍需逐项验证。Arduino 配方限制异常、RTTI、TLS、内联汇编和全局析构等功能。

前端输出成功或元数据中保留的旧 PASS，不构成当前全部配置、第三方库或实板运行的资格。本次清理不改变这些限制。
