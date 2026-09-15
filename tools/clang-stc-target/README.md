# Clang 20.1.8 STC 前端补丁

`clang-20.1.8-stcsdcc-ir-only.patch` 保留已锁定 Clang 二进制的源码来源，SHA-256 为 `f8fda423712d808dd087d4e789b1e824911cde62d738078bf9325a898d8476c0`。完整编译器源码准备与重建由相邻的 `stcxx` 项目维护。

Arduino 当前仅使用 MCS251 的 `msp430-stc-none-eabi` triple，Clang 生成 LLVM IR，最终机器代码由 LLVM-CBE、Arduino 适配器和 SDCC 生成。补丁中的历史双目标实现属于现有二进制的来源，不增加 Arduino 的支持型号。

本目录不进入开发板管理器安装包。编译工具及 ABI 配置以 `tools/cpp-cli/toolchain-lock*.json` 为准，使用方法见 [C++ 驱动说明](../cpp-cli/README.md)。
