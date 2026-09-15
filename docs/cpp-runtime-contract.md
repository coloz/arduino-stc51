# MCS251 C++ 运行时合同

平台只接受 `-mmcs251` 和 `STCXX_TARGET_MCS251=1`，并拒绝已退休的 CPU 配置。当前激活方式是 `cppcore=enabled`；默认仍为 plain C。

| ABI 项 | 约定 |
| --- | --- |
| Clang triple | msp430-stc-none-eabi（定制 STC TargetInfo） |
| 字节序 | 大端 |
| char / bool | 8 位，plain char 无符号 |
| int / short | 16 位 |
| long / size_t / ptrdiff_t | 32 位 |
| long long | 64 位 |
| float / double / long double | 32 位 |
| 数据/函数指针 | 24 位，字节对齐 |
| 数据成员/成员函数指针 | 3 / 6 字节 |
| local static guard | 单字节直接访问，无线程安全保证 |

在原生 C 与 C++ 之间调用时，双方必须同时使用 large/stack-auto 合同。IR、CBE、归档 sidecar、ABI 标识、原生外部符号存储类别和最终链接均有一致性检查。虚函数与成员函数指针还需要函数入口对齐审计。

原生 C 边界不支持按值传递或返回结构体、联合体等聚合对象。此限制也适用于函数指针回调，包括注册表、原生工厂返回的回调以及普通回调再次接收或返回的函数指针。两个适配入口都会追踪这些来源，拒绝不能证明调用目标和聚合 ABI 均在当前 C++ 模块内的用法。检查采用保守的别名和字段合并，复杂但实际合法的间接访问也可能被拒绝。

原生接口应使用标量或显式输入/结果指针。例如共享 C/C++ 头文件中的 `typedef void (*PairCallback)(Pair *out, unsigned short n);`；实现通过 `out` 写入成员。结果对象的布局、生命周期和存储类别仍须符合双方合同。内部 C++ 按值返回及已证明来源的间接调用继续支持。相关正向固件为 `tests/target/NativeCallbacks`、`tests/target/ReturnIdentity`，负向固件为 `tests/negative/NativeAggregateCallbacks`；Linux/WSL 使用 `scripts/check-native-callbacks.py --help` 查看候选安装、Arduino CLI 与 QEMU 的验证入口。

全局构造函数在 setup 之前执行，按生成桥中的顺序调用。编译关闭异常、RTTI、线程安全静态初始化和全局析构注册。局部 RAII 析构可用；不提供完整 libstdc++、线程、异常展开或退出时的全局析构服务。

每个板项明确配置 XDATA 堆、IRAM 上限和扩展栈区；栈从 0x100 开始，大小由 variant 决定。`__sdcc_heap_size32` 为 32 位，堆对象必须作为唯一提供者出现在运行库之前。分配失败时普通 new 进入 panic，nothrow new 返回空；telemetry 提供总空闲量、最大连续块和低水位。递归、深层虚调用与中断嵌套仍需预算，扩展栈不是无限内存。

MCS251 的堆结构定义在 stcxx 的私有头文件 `device/lib/mcs251/heap.h`，初始化及共享状态由 `device/lib/_heap_init.c` 提供，分配算法仍在 `device/lib/malloc.c`。三份源码均由运行时合同和工具链锁绑定。初始化可单独选入 `_heap_init.rel`，不使用动态分配的程序因此不必选入 `malloc.rel`；使用分配的程序仍共享同一条空闲链表。SDK 在全局构造之前显式初始化所配置的堆，不允许包内默认堆成为第二个提供者。

F()/PROGMEM 当前不提供 AVR Harvard Flash 节省 RAM 的完整语义。原生 C CODE 常量按最终符号存储类别核对，MCS251 采用统一 24 位指针，不再有程序地址空间转换分支。外部协议请显式编码字节序。

机器可读合同见 `cores/STC/cpp/core-manifest.json`、`runtime-manifest.json` 和 `tools/cpp-cli/toolchain-lock.json`。当前型号以[型号配置](variants-mcs251.md)为准。

原生 C 与 C++ 混合链接时，常量声明依据实际 REL/归档中的 CODE/XDATA 区域生成，并核对最终链接符号。未知区域或不一致的存储映射会使构建失败；普通 C++ `const` 不会自动全部放入 Flash。这不提供完整 AVR PROGMEM 兼容性，第三方库仍需按实际存储方式适配。
