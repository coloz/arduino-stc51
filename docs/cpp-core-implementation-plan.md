# C++ Arduino Core 实施计划

> Lifecycle update (2026-09-06): the active platform now has **20 models / 23 execution profiles**
> (13 MCS51 + 10 MCS251). STC8A8K64S4A12 and STC32F12K54 were removed.
> The 22-model / 25-profile / 31-workload set and removed-device details below are
> historical toolchain/qualification records, not the current support list or new PASS evidence.
> See the [lifecycle review](variant-lifecycle.md).

状态：MCS51/MCS251 双目标 C++ Arduino CLI frontend/bridge 已实现；资格合同固定为 22 个物理型号、25 个执行配置和 31 个 workload，最终 clean run 正在重新生成，当前 outcome 只在机器可读 JSON 中声明；生产发布与广泛库兼容尚未完成  
范围：当前 22 个 STC8、STC32、AI8051U 和 Ai8H 精确型号  
最终目标：广泛兼容只依赖 Arduino 公共 API 的可移植 C++ 库

当前资格明确为 **EXPERIMENTAL / NOT_SUPPORTED**。plain-C 是全部板项的默认
profile；C++ 必须在已接入的 12 MHz 配置显式选择 `cppcore=enabled`。MCS51 与
MCS251 使用独立 target triple/data layout、普通函数指针和成员指针 ABI。QEMU、
主机 mock 和 frontend IR 证据不能替代最终逐配置 JSON、实板、完整库语料或容量门。

## 1. 技术结论

当前 [sdcc-c251](https://github.com/gevico/sdcc-c251) 仍是 C 编译器。MCS251
与 MCS51 共用 SDCC 的 C 前端；C17、GNU C11/GNU C17、GNU builtins 和
`sdcpp` 都不等于 C++，也不提供模板、重载、C++ ABI、全局构造或运行时。

直接在 SDCC 中加入 C++ 前端不是本项目首选。要达到 Arduino 库所需的 C++11
兼容度，必须同时实现解析、名称查找、模板实例化、重载、类布局、异常相关语义、
C++ ABI 和运行时；工作量远大于改造 Core。

本计划固定使用 Clang 作为 C++ 前端。当前双目标实验链路已经选择并实现候选 A；
候选 B 保留为长期替代路线，不是当前 Arduino CLI profile 的组成部分：

```text
固定前端：
.ino/.cpp -> Clang 目标模型与 C++ ABI lowering -> LLVM Bitcode

候选 A：
C++ Bitcode 整程序链接与受控优化
-> 专用 LLVM-to-SDCC-C backend
-> sdcc -mmcs51/-mmcs251
-> ASxxxx REL/LIB/HEX

候选 B：
C++ Bitcode
-> 原生 LLVM MCS51/MCS251 backend
-> ASxxxx 兼容汇编
-> sdas8051/sdas251 + sdld
```

候选 A 能复用 SDCC MCS51/MCS251 代码生成、汇编器和链接器，但 bridge 本质上是受控
整程序后端，不是普通源码转换器。当前实现保留每个 Arduino C++ TU 的 LLVM
Bitcode sidecar，在最终链接时校验、排序、整程序链接、fail-closed 审计，再经
LLVM-CBE 与补丁 SDCC 生成一个 bridge 对象。候选 B 避免双重 ABI lowering，却
需要重新实现指令选择、寄存器、调用、栈帧和多地址空间，尚未实现。

当前已完成双目标 profile 的 `String`/`Printable`/`Print`/`Stream`、
`HardwareSerial`、SPI/Wire 类层、`IPAddress`/`Client`/`Server`/`UDP`、受限的
FAT16/FAT32 根目录 8.3 文件读写 `File`/`SDClass`、最小 freestanding 头和运行时。
它们是后续 G4/G5 的实验输入，
不表示相应跨板或广泛库退出门已经完成。

GCC 不进入首期：没有可直接使用的现代 MCS51/MCS251 GCC 后端，重新移植 GCC
不会减少目标 ABI、Harvard 地址空间和机器后端工作。

## 2. “广泛兼容”的可验证定义

只有发布门全部通过后才使用“广泛兼容”，不能把它作为工具链启动时的既成结论：

- 默认整次构建使用 GNU C++11；GNU C++17 是全局实验选项，不允许单个库私自切换；
- 支持类、继承、虚函数、模板、lambda、重载、全局构造、动态对象和跨 TU 实例化；
- 固定版本的 Tier A 运行语料在代表板上无源码补丁通过；
- 25--40 个 Tier B 库完成固定版本的 compile/link breadth 测试；
- 使用固定版本 ArduinoCore-API，并兼容传统 Arduino `Print`、`Stream`、
  `HardwareSerial`、`Wire`、`SPI`、`File` 和网络抽象接口；
- 每项分别报告 `compile`、`link`、`run`、`capacity`，不得用编译通过
  代替实板通过；
- `architectures=*` 仅用于候选筛选；仍需检查依赖闭包、架构条件分支、预编译
  对象、私有 SDK、寄存器访问和内联汇编。

首期明确不承诺：

- C++ 异常、RTTI、完整 libstdc++、线程安全局部静态初始化；
- 直接依赖 AVR、ESP 或其他架构寄存器、内联汇编、私有 SDK 的库；
- 无 STC 后端的 FastLED、Servo、IRremote、NeoPixel 等精确定时库；
- 每个小容量型号都能容纳所有源码兼容的库组合。

首期参数基线：

```text
-std=gnu++11 -ffreestanding -fno-exceptions
-fno-rtti -fno-threadsafe-statics -fno-use-cxa-atexit
```

这些选项只裁掉裸机不需要或代价过高的运行时，不能以此裁掉模板、虚函数、全局构造
或语言诊断。若提供 GNU C++17，必须另有语言 gate 和至少一个固定 C++17 语料。

## 3. 当前 22 个型号与推进顺序

移除 STC89、STC12、STC15，并加入 STC32G144K246、STC32G8K48、
STC32CL8K48、STC32F12K54、AI8051U-34K32 和 AI8051U-34K16 后，当前集合为
11 个纯 MCS51、8 个纯 MCS251 和 3 个双模式型号。全部有 UART1，21 个有 ADC，
Flash 最小 8 KiB。

当前 C++ 矩阵覆盖 22 个唯一型号、25 个执行配置（14 MCS51 + 11 MCS251）。两个
target frontend、ABI、LLVM-CBE/SDCC bridge 和 profile 选择均已接通。6 个显式
compact profile 各跑 `runtime` 与 `io`，其余 19 个各跑 `full`，共 31 个
workload。`tests/cpp/variant-matrix/results.json` 必须由同一次保留的 build schema v2/
runtime audit schema v4 evidence 生成，旧快照不能记为当前 PASS；本计划不复制 outcome。
AI8051U-34K16 的两个 compact profile 各以 14,336 字节为程序上限；
STC32F12K54 的 4 KiB XDATA 配置使用 3,584 字节 heap，并为静态 XDATA 保留
512 字节预算。

| 层级 | 型号/模式 | 主要资源 | 用途 |
|---|---|---|---|
| A | AI8051U-34K64/MCS51 | 64 KiB Flash、32 KiB XDATA、2 KiB EDATA | 首个语言、运行时和大库 bring-up |
| B | STC8H8K64U/MCS51 | 64 KiB Flash、8 KiB XDATA | 现实 8 位内存门与首块稳定 MCS51 实板 |
| C | AI8051U-34K64/MCS251 | 同一芯片切换实验 MCS251 | 排除外设差异的双 ABI 对照 |
| D | STC32G144K246/MCS251 | 246 KiB（251,904 B）程序 Flash，使用保留 HOME 的分区链接；128 KiB XDATA、16 KiB EDATA | MCS251 高地址链接/启动与大代码目标；同名锁定 QEMU 已用于其建模范围内的确定性 smoke/differential，旧结果不自动覆盖新布局 |
| E | STC32G12K128、STC32F12K54/MCS251 | 8 KiB 或 4 KiB XDATA；F12K54 为 3,584 B heap + 512 B 静态 reserve | 受限内存的纯 MCS251 约束门，防止 K246 大内存掩盖问题 |
| F | 其余 64 KiB 型号 | 2--8 KiB XDATA | 外设、引脚和容量回归 |
| G | 8/12 KiB 型号与 AI8051U-34K16 | 1 KiB XDATA 或 16 KiB Flash 上限 | compact profile 和逐用例容量结果 |

MCS51 已实现为独立工具链路线，没有复用 MCS251 frontend 的大端、32 位 `size_t`
或 24 位函数指针 ABI。它锁定小端、16 位 `size_t`、16 位函数指针和 24 位 tagged
generic pointer；AI8051U 双模式用于持续比较大小端、指针、成员指针、`size_t`、
调用约定和启动过程。

AI8051U 通过不能替代 STC8H8K64U。32 KiB XDATA 会掩盖对象布局、堆和缓冲浪费，
所以 8 KiB XDATA 的 STC8H8K64U 是进入库兼容阶段前的强制门。

STC32G144K246 用于单独验证用户 Flash 高地址映射、复位入口、构造器表以及
code/函数指针；QEMU 是已实现的可重复执行路径，但不替代实板发布门。本 Arduino
core 仓库不把上游编译器已有的 QEMU 测试继承为自身结论；任何 PASS 都只能来自
本项目保存的固定工具版本、命令、产物、日志和 oracle，范围仍
限定为模型覆盖项；具体 outcome 以机器可读结果为准。
STC32G12K128 继续作为 8 KiB XDATA/4 KiB EDATA
的纯 MCS251 约束配置。

同名 QEMU 机型不是 cycle-exact 芯片替身。G0 必须冻结实际模型版本和外设清单；
当前只把 CPU、代码/数据存储器、UART1、Timer0/1 与 P0--P7 纳入仿真 oracle。
P8--PB、ADC、USB、PLL、模拟/电气行为和断电启动必须由静态映像检查或实板覆盖，
不能因 QEMU 启动成功而推导为 PASS。

K246 的物理用户 Flash 是半开区间 `[0xFC2800, 0x1000000)`，大小为
`0x1000000 - 0xFC2800 = 0x3D800 = 251,904 B`。SDCC/ASlink 启动布局把
`GSINIT0` 放在 `0xFC2800`，并把必须执行的复位 `HOME` 区固定在 `0xFF0000`。
K128 对应区间是 `[0xFE0000, 0x1000000)`，`GSINIT0` 位于 `0xFE0000`，
`HOME` 同样位于 `0xFF0000`。旧发布布局只向普通代码开放 HOME 前的
182/64 KiB；相关历史编译、QEMU 和实板记录保留其原始范围。

当前板定义使用 `segmented_home`：`maximum_code_bytes` 分别为 251,904 和
131,072，包含实际启动和向量字节。`build.flash_flags` 将
`--function-sections --data-sections` 传给 MCS251 编译和链接流程；
`-Wl--code-window=0xfc2800:0x1000000`（K128 起点为 `0xfe0000`）
限定允许的物理地址半开区间。链接器保留实际 HOME 区间以及启动段连续性，
在剩余低、高地址空闲区放置完整函数和只读数据对象。单个函数或对象不能跨越
HOME，碎片化或单个对象过大仍可能在累计字节数达到总容量前导致链接失败。
生成器必须验证 GSINIT0 是物理 Flash 起点、HOME 位于窗口内且声明容量准确，
不能把该规则套到 STC16 Beta 的非连续可编程分区或 EEPROM 区。

此布局要求重建带相应编译器和 ASlink 修改的工具链，并同步 C++ 工具锁及
发布清单；旧的 `gevico/sdcc-c251` 发布二进制没有这些新增选项。size 报告按
CODE 区的实际字节总和计数，map/HEX 验证检查物理边界、各区不重叠以及 HOME
复位跳板。完整 Flash 的验证使用同时占用 HOME 两侧的压力程序，覆盖 24 位
直接/间接调用、函数指针、常量、初始化和中断；QEMU 结果限于模型覆盖项，
断电重启及实板发布资格仍需对应固件的硬件记录。

## 4. 编译器与 ABI 工作包

### 4.1 Clang 目标模型

建立两个独立目标：

- `mcs51-unknown-none-sdcc`：小端、16 位 `int`、MCS51 指针和地址空间；
- `mcs251-unknown-none-sdcc`：大端、以 MCS251 ABI v2 的寄存器/指针规则为
  参考、32 位 `size_t` 和对应指针模型；下面定义的 Arduino C++ ABI 差异必须
  使用独立 ABI revision，禁止冒充或链接原生 v2 产物。

首个生产 ABI 固定为 `stc-arduino-cxx-v1`：

- 全部 C++、C HAL、core、库和运行时统一采用 `stack-auto` 可重入调用模型；
  默认 overlay 参数区对象不得混入同一映像；
- `float`、`double`、`long double` 都采用 32 位 IEEE single，匹配当前 Arduino
  STC/AVR 容量与源码语义；这是相对原生 MCS251 ABI v2（64 位 `double`）的显式
  ABI 差异；
- 不再依靠 `-Ddouble=float` 改写 C/C++ token。Clang `TargetInfo`、bridge、C HAL
  和专用 runtime 必须从类型系统层面一致实现 32 位 `double`，并禁止链接 stock
  MCS251 v2 浮点库；
- ABI identity 至少编码 target、memory model、`stack-auto`、软件栈放置、浮点
  宽度、地址空间模型、异常/RTTI 配置和 ABI revision；任何一项不符都必须在链接
  前失败。

`stack-auto` 是广泛 C++ profile 的硬要求，因为 virtual、成员函数指针、多参数
回调、递归和跨 TU 间接调用不能依赖 overlay 参数区。G0 仍需在该 ABI 内冻结
MCS51 是否使用 xstack、MCS251 的 SP/SPX 与软件栈区域、增长方向、对齐、guard、
ISR 切换/嵌套和溢出处理。若小容量型号无法满足，只能降为机器可读的 `minimal` /
`capacity-unsupported` profile，不能在同一 ABI 中静默退回 overlay。

不能只增加 `TargetInfo`。完整 spike 至少包括：

- LLVM Triple、Clang driver/toolchain 和预定义宏；
- `TargetInfo`、DataLayout、char signedness、对齐、枚举和位域规则；
- `__data/__idata/__pdata/__xdata/__code` 到 LLVM address space 的映射；
- 普通、generic、code 和函数指针的宽度及合法转换；
- `TargetCXXABI/CGCXXABI`；
- `TargetCodeGenInfo/ABIInfo` 的参数、返回、`sret/byval` 和 varargs 规则；
- class/vtable、成员函数指针、聚合和跨 TU 布局；
- direct/indirect call、递归、ISR 嵌套和 C 边界 thunk 的统一 stack-auto 规则；
- `float/double/long double` 参数、返回、varargs、mangling 和 math helper；
- ABI 版本符号，禁止不同目标、内存模型、stack/浮点模式或 ABI 产物混用。

未知架构的默认 Clang ABI 不能视为与 SDCC 匹配。现有 C HAL、core 和匹配的
SDCC runtime 必须用 `stack-auto` 与同一浮点 ABI 重编；不能重编的 vendor/汇编
对象只允许经审计的叶子 thunk 接入。每一条规则都需要 Clang 侧
`sizeof/alignof/offsetof` 探针、SDCC 侧探针和 QEMU/实机可观察结果。

### 4.2 候选 A：LLVM-to-SDCC-C backend

输入是链接后的 C++ Bitcode，输出一个或少量 SDCC C 翻译单元。必须处理：

- SSA/PHI、任意整数宽度、控制流、全局初始化、alias、linkage 和 COMDAT；
- `poison/undef/freeze`、`nsw/nuw`、移位和溢出，避免生成额外 C UB；
- 各地址空间的 GEP、24 位 generic pointer、`addrspacecast` 和函数指针；
- 聚合参数/返回、varargs、成员函数指针、虚表和全局构造器；
- 固定 alloca、内存 intrinsic、64 位运算 helper、大 `switch`；
- 未引用代码/构造器删除、源码位置和确定性输出；
- 所有未知 IR、动态 alloca、atomic、vector、inline asm 和非法地址空间转换
  必须显式失败，禁止静默误编译。

首期 Clang C++ 与 SDCC C 边界只允许固定宽度标量、明确地址空间的指针和显式
thunk。禁止结构体按值和未定义的 varargs 直接跨边界。`extern "C"` 只控制语言
链接和符号名，不证明两端二进制 ABI 相同。

bridge 只做 C++ Bitcode 的受控整程序优化；现有 SDCC C 对象不参与 LLVM LTO。
通用 `llvm-cbe` 不能作为生产实现，因为标准 C 无法正确表达 8051 多地址空间和
generic pointer 语义。

bridge 输出的所有翻译单元必须用与 `stc-arduino-cxx-v1` 匹配的 `stack-auto`
选项和专用 runtime 编译。Clang 的 32 位 `double` 语义在 IR/C 边界只能降低为明确的
32 位浮点类型/helper；不得重新解释为原生 MCS251 v2 的 64 位 `double`。

### 4.3 候选 B：原生 LLVM 后端

最小 spike 要生成 ASxxxx 兼容汇编并复用现有 assembler/linker，至少覆盖：

- MCS51 与 MCS251 基础指令、寄存器和地址模式；
- call/frame lowering、极小硬件栈、软件栈与 ISR；
- code/data/xdata/edata 地址空间和合法化；
- 间接调用、函数指针、聚合和必要 runtime helper；
- `-Os` 下的代码大小和可诊断性。

候选 B 不能把每个 TU 独立变成 ASxxxx `.rel` 后再期待 `sdld` 实现 ELF
`COMDAT/weak/linkonce` 语义。生产 spike 固定加入最终链接前的 Bitcode prelink：

1. Arduino 编译阶段把 C++ TU 和可参与 ODR 的 core/library archive member 保存为
   Bitcode 及成员索引；
2. 最终链接按 Arduino archive extraction 规则选择成员，再由 `llvm-link`/内部化
   阶段解析 `linkonce_odr`、COMDAT、weak、模板实例和全局构造器；
3. 完成 whole-program DCE 后输出单个或确定性分区的 ASxxxx 汇编，每个外部符号
   唯一，再与 ABI 匹配的 C HAL `.rel` 链接；
4. C 与 C++ 之间的 weak hook 若不能在 Bitcode 层共同解析，必须改为显式注册或
   强符号 thunk，禁止依赖 `sdld` 未承诺的 weak 选择顺序。

若该 prelink 方案不能保持 Arduino 的 archive member 提取、用户强定义覆盖 core
默认 hook 和增量构建语义，候选 B 必须改为扩展 object/linker 的 COMDAT/weak
支持或在 G2 淘汰，不能把 ODR 问题推迟到 G3。

### 4.4 G2 架构决策量表

两条路线使用相同的真实 `-Os` 输入，不只用手写 IR：

- specific/generic/code pointer 往返与间接访问；
- 聚合参数/返回、varargs、函数和成员函数指针；
- virtual、全局构造、跨 TU 模板/COMDAT；
- 大 `switch`、64 位算术和内存 intrinsic；
- ArduinoJson 和自包含跨 TU C++ 语料；Adafruit BusIO 仅在 G0 已冻结的生产
  Arduino API 头足以编译真实上游 TU 时加入，否则延至 G4b，禁止测试专用 shim。

ADR 必须记录：

- QEMU 已建模范围内与实机的语义差异数必须为 0；未建模外设另走实板门；
- 未知或未实现 IR 必须为 0；
- ODR/COMDAT/weak、用户 hook 覆盖和 archive extraction 差异必须为 0；
- 相对同功能 SDCC C 基线的 Flash、静态 RAM 和 stack 增量；
- 最大 stack、构建时间、生成中间文件大小和诊断质量；
- 实现复杂度、维护面和三平台可重复构建。

门槛数值在 G0 的 benchmark manifest 中冻结，不能看完结果后调整。任一方案未达到
门槛时，只能发布“实验性 C++ 子集”，不得继续宣称广泛兼容。

## 5. C++ 运行时与启动

最小运行时包括：

- 构造器表和 `__stcxx_run_global_ctors()`；
- `new/delete`、数组版本、sized delete、placement new 和 nothrow；
- `__cxa_pure_virtual`、`__cxa_deleted_virtual`；
- 非线程局部静态 guard；
- `memcpy/memmove/memset` 及必要整数 helper；
- 明确的 OOM 行为、堆边界、最大连续分配和 stack high-water；
- 裸机不运行全局析构，也不允许隐式依赖 `atexit`。

为保持标准 C++ 与主流 Arduino Core 的全局对象语义，启动顺序固定为：

```text
复位入口、.data/.bss 初始化
-> __stcxx_run_global_ctors()
-> main()
-> init()
-> initVariant()
-> setup()
-> loop()
```

构造器必须在进入 `main()` 前且只运行一次；因此全局对象构造器不得假设 GPIO、
Timer 或 UART 已由 `init()` 配置。G0 把顺序和析构策略写入 ABI/启动 ADR，并以跨 TU
全局对象、静态局部对象及复位测试锁定；若最终必须偏离该顺序，要有跨 Core 兼容
证据和负向测试。

当前 runtime slice 只完成 `main()` core prologue 调用，能保证其早于 Arduino 生命周期，
但尚未满足上面的严格 pre-main 门。完成 GSFINAL/startup-section 接入并在目标机复位测试
通过前，该项保持 `NOT_SUPPORTED`。

MCS51 的 256 字节 IDATA 不能被 XDATA 总量掩盖。间接调用、深栈、ISR 嵌套、
局部对象和 guard 分别测量。MCS251 的 EDATA、XDATA、heap 和 stack 分开报告；
USB 保留 RAM 不得算作通用 heap，除非 allocator 明确使用并通过 USB 共存测试。

## 6. Arduino C++ Core 分层

固定一个 ArduinoCore-API tag/commit 和 `ARDUINO_API_VERSION`，同时固定用于传统
库兼容的 ArduinoCore-avr/Wire/SPI/SD 接口基线。复用 ArduinoCore-API host tests，
并增加目标机 conformance tests。

实现顺序按真实依赖拆分：

1. 基础类型、`pgmspace`、`F/PSTR/pgm_read_*`；
2. `WString/String`、`Printable`、`Print` 作为同一原子阶段；
3. `Stream`；
4. `HardwareSerial` 和真实 `Serial` 对象；
5. `SPISettings/SPIClass/SPI`、`TwoWire/Wire`；
6. `File/SDClass/SD`；
7. `IPAddress/Client/Server/UDP` 和 Ethernet 抽象；
8. `SoftwareSerial`、`LiquidCrystal`、`Stepper` 等库级组件。

要求：

- 现有 C HAL 保留，公共 C 头提供 `extern "C"` 保护；
- `PROGMEM/F/PSTR/pgm_read_*` 映射到真实 code 地址空间，不能是 no-op；
- 单例式 C 状态逐步改为 context，使软件串口、Wire、SPI 可多实例；
- 提供 freestanding 的 `<new>`、`<type_traits>`、`<utility>`、`<limits>`
  等最小头集合，但不声称完整 libstdc++；
- Timer、ISR、UART、软件总线、Servo/PWM 的资源冲突机器可读；
- 未实现 API 用 feature macro 和清晰编译错误表示，禁止空实现或测试专用 stub。

当前 K246 profile 为提高源码可编译性提供 `F/PSTR/PROGMEM/pgm_read_*` 的普通
数据访问 fallback，`STCXX_PROGMEM_IS_DATA` 明确暴露该事实。它尚未达到上面
“真实 code 地址空间”的发布门，也不承诺节省 RAM。

Core conformance 独立覆盖：

- `String` copy/move/concat/OOM；
- `Printable` 与 `Print` 全部 overload；
- `Stream` timeout/parse；
- Wire callback、多实例和 SPI transaction；
- Flash string/code pointer；
- 全局对象、虚调用、回调、new/delete 和 OOM。

## 7. 固定库语料

`tests/cpp/library-corpus.json` 是发布输入，不是库名列表。每项必须记录：

- 精确 tag/commit、下载 URL、SHA-256、许可证；
- 完整依赖闭包及其版本和哈希；
- Arduino API 基线、构建标准、宏和 board profile；
- minimal sketch、feature sketch、所需外设和接线；
- 运行 oracle、串口协议、超时和最大资源预算；
- 每个目标的预期 `compile/link/run/capacity` 状态。

禁止本地 fork、源码补丁、测试专用 shim 和 no-op。允许库公开文档定义的配置宏。

语料分三层：

- Tier A：约 10--15 个固定版本 runtime canary，所有发布门实板运行；
- Tier B：25--40 个固定版本 compile/link breadth 库，覆盖数据处理、传感器、
  显示、存储、网络和控制；
- Rolling：定期测试最新版本，只预警生态漂移，不阻断固定基线发布。

Tier A 初始候选：

1. ArduinoJson；
2. Bounce2 或同类 GPIO/millis 库；
3. AccelStepper；
4. LiquidCrystal、Stepper；
5. Adafruit Unified Sensor + BME280/BMP280；
6. Adafruit BusIO -> GFX -> SSD1306；
7. U8g2；
8. SD；
9. Ethernet；
10. PubSubClient。

网络运行门固定 W5x00 型号、本地服务器和 MQTT broker。PubSubClient 另用确定性
mock `Client` 测协议，避免网络波动被误判为 Core 错误。每个列入 release-gating
tier 的用例都由 manifest 生成 gate，不能只抽查其中三项。

失败归类至少包括：frontend、backend/bridge、ABI、runtime、stdlib/header、
Core API、HAL、Arduino build/preprocessor/library resolution、架构专用代码、
容量和测试基础设施。

## 8. 容量与 profile

容量结论以“板型 × 语料用例 × 编译配置”为单位，不能把整块 MCU 永久标成
`capacity-unsupported`。每次构建记录：

- Program bytes 和预留 Flash；
- 静态 IDATA、XDATA、EDATA；
- heap peak、最大连续分配；
- 普通路径与最坏 ISR 嵌套的 stack high-water；
- 各地址空间 guard/headroom。

`tests/cpp/profiles.json` 为每块板冻结数值门槛。至少满足：

- Flash 余量不低于 `max(10%, 1024 B)`；
- MCS51 IDATA 在最坏调用链和 ISR 后仍保留不少于 32 B guard；
- allocator 所在空间在峰值后仍保留 `max(10%, 256 B)`；
- 最大连续空闲块大于语料最大单次分配；
- 不合并互不可替代的 IDATA/XDATA/EDATA 数字。

profile 语义：

- `full`：完整 Core 抽象和全部 Tier A 门通过；
- `standard`：完整基础 Core，通过 manifest 指定的中等容量 Tier A 子集；
- `minimal`：显式 feature set，只承诺基础 API 和小容量语料；
- `capacity-unsupported`：只标记具体用例/组合，不标记整块板。

任何 profile 裁剪都要有 feature macro 和确定性编译诊断，禁止运行时静默降级。

## 9. 里程碑与退出门

### G0：目标、API、ABI 和基线冻结

交付物：

- 当前 22 个 variants、板项和 C 构建矩阵一致；
- ArduinoCore-API、传统接口基线、benchmark 和 corpus manifest；
- `stc-arduino-cxx-v1` ABI manifest：两个目标的数据/地址空间模型、32 位浮点
  家族、`stack-auto` 调用约定、MCS51 xstack 与 MCS251 SP/SPX 选择、C/C++
  thunk、构造顺序和产物 identity；
- C Core 的 Flash、各 RAM、heap、stack 基线和数值预算。

退出条件：22 个默认配置、3 个 AI8051U/MCS251 附加配置和当前 8 个库探针组成的
33 项本地矩阵可重复生成 HEX；代表配置的 runner、oracle 和
状态记录格式已冻结。K246 的 QEMU 结果只有在保存固定版本、完整命令、产物与日志
并满足 oracle 后才可记为 PASS，否则保持 `NOT_RUN`/FAIL。
另外必须先用 SDCC C proof build 验证匹配的 stack-auto runtime、direct/indirect/
递归、ISR 嵌套、stack guard 和固定宽度浮点边界，并冻结 virtual/成员函数探针的
预期结果；这些 C++ 探针在 G1/G3 执行。任何 `-Ddouble=float` 与原生 64 位
MCS251 `double` 混用都必须被构建门拒绝。

### G1：Clang 目标与 C++ ABI lowering

交付物：两个 triple、driver、地址空间、TargetInfo、CXXABI、ABIInfo、匹配选项
重编的 C HAL 边界夹具和探针，
包括全部浮点参数/返回/varargs/mangling/math helper，以及 stack-auto 下的直接、
间接、成员函数和 ISR 调用。

退出条件：Clang/SDCC 的类型、聚合、指针、浮点、调用、stack 和边界 thunk 逐项
一致；宿主 triple、`-Ddouble=float` token hack、overlay 默认或未标识 ABI 仍影响
结果即不得进入 G2。

### G2：后端 bake-off 与 ADR

交付物：候选 A bridge spike、候选 B 原生 backend + Bitcode prelink spike、同一
真实语料报告，以及 ODR/weak/archive extraction 报告。

退出条件：选定生产后端；语义差异、未知 IR、重复/丢失 ODR 符号和 hook 覆盖差异
均为 0，并满足 G0 冻结的 Flash、stack、构建时间和诊断门。G2 只能选择满足既定
ABI 的后端，不能在看完结果后改 ABI；若必须修改，提升 ABI revision 并回到 G1。
未通过则缩小为实验子集。

### G3：C++ 运行时

交付物：构造、模板、继承、virtual、lambda、静态初始化和 new/delete。

退出条件：在 G2 已验证的 prelink/linker 语义上，跨 TU 模板/COMDAT、vtable、
复制/移动、回调、递归、OOM 和负向能力测试在 AI8051U/MCS51 与 STC8H8K64U
通过，并记录 heap/stack 峰值与 guard 余量。

### G4a：基础 Arduino 类

交付物：pgmspace、String/Printable/Print、Stream、HardwareSerial。

退出条件：host conformance 与两块 MCS51 代表板的 API/行为测试通过。

### G4b：总线

交付物：SPI、Wire、多实例 context 和资源冲突元数据。

退出条件：SPI transaction、Wire callback/超时和固定传感器夹具通过。

### G4c：存储与网络抽象

交付物：File/SD、IPAddress、Client/Server/UDP、Ethernet 所需公共接口。

退出条件：SD 字节序/错误路径和确定性 mock 网络测试通过。

### G5：固定库兼容语料

交付物：Tier A/B manifest、自动 gate、容量报告和 rolling 非阻断车道。

退出条件：每个 Tier A 条目按 manifest 在 AI8051U/MCS51、STC8H8K64U/MCS51
达到预期；Tier B 固定基线 compile/link 达标；所有失败有唯一分类。

### G6：MCS251 差分与库门

交付物：AI8051U 同硅片 MCS51/MCS251 差分、STC32G144K246 高地址链接/启动与
QEMU/实机结果，以及 STC32G12K128 受限内存纯 MCS251 结果。

退出条件：各自匹配 ABI manifest且可观察语义一致；除 ABI/启动测试外，至少重跑
ArduinoJson、BusIO/GFX/SSD1306、SD、Ethernet/PubSubClient 子集，验证大小端、
`size_t`、指针、32 位 `double`/varargs ABI 和深栈路径。

K246 必须单列高地址链接、复位入口、构造器表和 code/函数指针结果；QEMU smoke
是实板门的补充，不得以 QEMU 代替实板。P8--PB XFR、ADC2 和 PLL 暴露状态也要
作为独立能力记录，不能由普通 CoreAPI 编译结果推导。

### G7：13 个其余型号与发布

交付物：除 AI8051U-34K64、STC8H8K64U、STC32G144K246、STC32G12K128 这
4 个代表型号外，其余 13 个唯一型号的逐用例容量/profile、三平台工具包和
Boards Manager。

退出条件：Windows、Linux、macOS 工具包可重复构建；Arduino CLI/IDE 安装、缓存
`core.a`、升级和卸载通过；每个目标和语料用例都有明确状态。

## 10. 仓库落点

```text
docs/adr/
  cpp-target-abi.md
  cpp-backend-selection.md
tools/wrapper/
  stcxx-compile.sh
  stcxx-archive.sh
  stcxx-link.sh
cores/STC/cpp/
  pgmspace.h
  WString.h/.cpp
  Printable.h
  Print.h/.cpp
  Stream.h/.cpp
  HardwareSerial.cpp
  Wire.cpp
  SPI.cpp
  stcxx_runtime.c
  stcxx_startup.c
tests/cpp/
  abi/
  backend/
  runtime/
  core/
  libraries/
  negative/
tests/cpp/library-corpus.json
tests/cpp/profiles.json
.github/workflows/cpp-toolchain.yml
```

Clang fork和后端源码使用独立仓库和独立版本。本仓库只固定工具版本、URL、大小、
SHA-256 和许可证，避免把大型编译器源码放入 Boards Manager 平台包。

## 11. 剩余执行顺序

下面的工期表是最初规划量级，不是发布日期承诺。K246 候选 A 垂直链路提前形成
了可运行实验实现，但没有自动完成各阶段的跨板、库、容量、实板和发布退出门。

| 阶段 | 估算 | 立即结果 |
|---|---:|---|
| G0 | 1--2 周 | 冻结基线、API/ABI/语料 manifest |
| G1 | 4--8 周 | Clang 正确生成两个目标的 C++ Bitcode |
| G2 | 6--12 周 | 两个 spike 和后端 ADR |
| G3 | 4--8 周 | 最小 C++ ABI/runtime |
| G4a--G4c | 8--16 周 | 标准 Arduino C++ Core 层 |
| G5 | 6--12 周 | 固定库兼容与容量报告 |
| G6 | 4--8 周 | MCS251 ABI、K246 高地址/字节序和库门 |
| G7 | 4--8 周 | 其余型号和三平台发布 |

当前按顺序执行：

1. 持续保持 22 个默认板项和 33 个 plain-C 配置回归，不让 opt-in C++ 改变默认
   ABI、缓存或库发现行为；
2. 固化 25 配置 Arduino CLI clean/incremental/cache/stale-sidecar、C/C++ 混合 TU、
   archive/weak/ODR 和精确 QEMU 证据，并记录每个产物 identity；
3. 持续回归独立 MCS51/MCS251 frontend/bridge ABI，覆盖普通函数指针、数据成员指针、
   非虚/虚成员函数指针、varargs、地址空间和最坏 ISR/stack；
4. 完成真实 code-space Flash 字符串和严格 pre-`main()` 构造门，或明确修订 ABI
   合同与兼容边界；
5. 对冻结 Tier A/B 语料逐项完成 source lock、Arduino CLI compile/link、目标运行
   和容量；不得用 host 或 frontend IR PASS 代替后续阶段；
6. 在代表实板验证启动、GPIO、时基、UART、总线、存储和容量，再扩到其余型号；
7. 重建并资格验证 Windows/Linux/macOS 工具包与平台归档。现有 macOS `r1` 和
   旧 release/index 资产不含最终组合补丁，不得发布为当前实现。

## 12. 参考基线

- [sdcc-c251 README](https://github.com/gevico/sdcc-c251)
- [sdcc-c251 MCS251 ABI](https://github.com/gevico/sdcc-c251/blob/912a589d4080c9cd5c5c1faf871c62dd5023580d/doc/mcs251/abi.md)
- [SDCC 官方手册](https://sdcc.sourceforge.net/doc/sdccman.pdf)
- [LLVM IR Data Layout](https://llvm.org/docs/LangRef.html#data-layout)
- [Writing an LLVM Backend](https://llvm.org/docs/WritingAnLLVMBackend.html)
- [ArduinoCore-API](https://github.com/arduino/ArduinoCore-API)
- [Arduino Library specification](https://docs.arduino.cc/arduino-cli/library-specification/)

## 13. 实现检查点（2026-09-06）

MCS51/MCS251 的 12 MHz GNU++11 链路现已从独立 pipeline 接入 Arduino CLI：每个
C++ TU 由锁定 Clang 生成 Bitcode sidecar，最终链接时进行内容校验、排序、
LLVM 整程序链接、fail-closed 审计、LLVM-CBE 转换和对应目标的补丁 SDCC 链接。
编译器源码与生成工具固定放在独立项目 `D:\Git\stc51\stcxx`（WSL：
`/mnt/d/Git/stc51/stcxx`）；本 core 不把编译器源码混入平台目录。
plain-C 仍是默认。全部 22 个物理型号、25 个执行配置都有显式 C++ profile；最终
资格由 6×2 compact 与 19×1 full 的 31 个 workload 组成；当前
`CppMinimalSmoke`/runtime canary 的 clean compile/link/capacity 与精确 QEMU outcome
只记录在 `tests/cpp/variant-matrix/*.json`。以下是 K246 的显式 FQBN 示例：

```text
arduino-stc51:mcs51:stc32g144k246:cppcore=enabled,clock=12m
```

扩展 canary 的每次 QEMU 结果必须绑定当次 build manifest 与固件 SHA-256；旧
固件 digest 或手写 PASS 不能作为新构建证据。覆盖包括跨 TU 构造、
模板/lambda/virtual、动态分配和 guard、
聚合/位域/指针差、最小标准头、`String`/`Print`/`Stream`、IPv4/IPv6、软件
SPI/Wire、Timer0 与 UART1。锁定 QEMU 提交
`faeac38c0076795d7b4e59f0ddcb5fc7e7bd7015` 为 22 个物理型号、25 个执行配置提供
精确 machine，但只验证各自建模的 CPU/内存/UART/Timer/数字外设，不覆盖 ADC、
USB、CAN、DMA、PLL、电气或 cycle-exact 时序。machine 存在不等于 PASS，不能借用
旧 K246 结果或设置 alias；最终每个配置都必须绑定本次构建和逐配置 runtime audit。
最终 clean 25-profile/31-workload run 正在重新生成，默认宿主时序另补充 9 个
profile、11 个 workload；两者 outcome 都只能由权威 JSON 声明。

Core 类层已包含 `String`、`Printable`、`Print`、`Stream`、`HardwareSerial`、
`SPIClass`、`TwoWire`、`IPAddress`、`Client`、`Server`、`UDP` 和受限的
FAT16/FAT32 根目录 8.3 文件读写 `File`/`SDClass`。LiquidCrystal 1.0.7、
Stepper 1.1.3、Ethernet 2.0.2、上游
SD 1.3.0 与 ArduinoJson 7.4.3 的分阶段结果只在
`tests/cpp/library-compat/results.json` 声明；frontend 接受、target link、runtime、
capacity 和 source provenance 不得互相替代。

因此本检查点只说明 G1--G4/G6 的双目标实现与资格方法已接通，production status
仍为 `NOT_SUPPORTED`。异常、RTTI、完整 STL/libstdc++、真正 code-space Flash
字符串、完整 Tier A/B run/capacity、发行工具包和实板仍是独立资格门。
