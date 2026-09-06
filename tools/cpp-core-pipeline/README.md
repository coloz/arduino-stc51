# 共享 LLVM / C 适配器与来源元数据

本目录保留 Arduino 实验性 C++ 构建使用的共享适配器，以及早期 K246 流水线的来源元数据。当前 Arduino 构建入口位于 [cpp-cli](../cpp-cli/README.md)，完整编译器的源码准备和构建由 **stcxx** 项目维护，入口见[平台 README](../../README.md)。

## 当前文件

| 文件 | 作用 |
| --- | --- |
| [audit_and_adapt.py](audit_and_adapt.py) | 共享 LLVM / LLVM-CBE 审计、C 输出规范化和构造函数桥接逻辑 |
| [toolchain-lock.json](toolchain-lock.json) | 记录工具来源、ABI、补丁和参考产物身份 |
| [source-manifest.json](source-manifest.json) | 保存原始 K246 配置、源码身份和历史验证约定 |
| 本 README | 说明组件用途与验证边界 |

`cpp-cli/adapt.py` 在运行时动态加载 `audit_and_adapt.py`，复用其中的解析、检查和规范化函数。该文件只导入 Python 标准库，是平台的实际构建依赖；它不依赖已移除的测试 runner、独立审计脚本或复现输入。

共享适配器检查已支持的 LLVM 指令与 intrinsic，规范化 LLVM-CBE 的函数指针 typedef 顺序及已识别的 C 形态，并生成构造函数调用桥接。Arduino 的双目标处理由 `cpp-cli/adapt.py` 在此基础上完成；不符合已实现约束的输入会导致构建失败。

## 历史元数据的用途

直接 K246 runner、独立回归检查、复现源码和留存的仿真结果已移除。本目录不再提供可独立重复运行的完整 K246 验证流水线。

两个 JSON 中保留的旧测试路径、测试哈希、警告计数、仿真身份及资格字段用于追溯当时的配置，不表示对应文件仍存在，也不能证明当前工具通过了同一组检查。当前 Arduino 配方实际读取的工具及适配器约束以 [cpp-cli/toolchain-lock.json](../cpp-cli/toolchain-lock.json) 为准。

原始 `stc-arduino-cxx-v1-mcs251-k246-canary` 只描述特定的 12 MHz 配置。编译与链接完成不能推导出全部 22 个型号、25 个执行配置的运行时通过，更不能替代真实芯片上的启动、外设、时钟和烧录验证。本次整理不提高任何资格或支持等级。
