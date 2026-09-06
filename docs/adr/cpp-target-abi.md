# ADR: STC Arduino C++ 目标 ABI 基线

> Lifecycle update (2026-09-06): the active platform now has **20 models / 23 execution profiles**
> (13 MCS51 + 10 MCS251). STC8A8K64S4A12 and STC32F12K54 were removed.
> The 22-model / 25-profile / 31-workload set and removed-device details below are
> historical toolchain/qualification records, not the current support list or new PASS evidence.
> See the [lifecycle review](../variant-lifecycle.md).

状态：**PARTIALLY FROZEN / EXPERIMENTAL DUAL-TARGET IMPLEMENTATION / NOT_SUPPORTED**  
ABI 标识：`stc-arduino-cxx-v1`  
机器清单：[abi-manifest.json](../../tests/cpp/abi/abi-manifest.json)

## 决策

为 Clang C++ 前端定义并实现两个独立目标：

- `mcs51-unknown-none-sdcc`；
- `mcs251-unknown-none-sdcc`。

两者共享 freestanding GNU C++11 语言 profile，但不是同一个二进制 ABI。所有 C++、
运行时和参与 C++ 调用边界的 C 对象必须使用 `--stack-auto`；默认 SDCC overlay 参数区对象
不得混入。异常、RTTI、线程安全局部静态和 `__cxa_atexit` 均关闭。

本 ADR 冻结的是目标数据模型、调用栈原则和启动可观察顺序。仓库现在为全部
22 个物理型号、25 个 MCS51/MCS251 执行配置提供真实 C++ frontend/bridge 和 12 MHz
opt-in profile；plain-C 仍是默认路径，必须显式选择 `cppcore=enabled`。普通函数指针、
数据成员指针和成员函数指针布局已经纳入 target/build identity。最终全矩阵 clean
compile/link/capacity 与精确 QEMU 使用 25-profile/31-workload 合同，当前 outcome
只由 `tests/cpp/variant-matrix/*.json` 声明；这仍不是受支持的生产编译器。
aggregate/varargs、地址空间和完整启动/栈边界仍是生产阻断项；状态必须
保持 `EXPERIMENTAL` / `NOT_SUPPORTED`。

## 证据与解释边界

基线工具是 `gevico/sdcc-c251` commit
[`b09075b6a93e6afe10645181e3aeff041ea37f87`](https://github.com/gevico/sdcc-c251/tree/b09075b6a93e6afe10645181e3aeff041ea37f87)，
本地版本输出为 `SDCC : mcs51/mcs251 TD- 4.6.0 #0 (MINGW64)`。源级证据为该 commit 的：

- [`device/include/stddef.h`](https://github.com/gevico/sdcc-c251/blob/b09075b6a93e6afe10645181e3aeff041ea37f87/device/include/stddef.h)；
- [`src/mcs51/main.c`](https://github.com/gevico/sdcc-c251/blob/b09075b6a93e6afe10645181e3aeff041ea37f87/src/mcs51/main.c)；
- [`src/mcs251/main.c`](https://github.com/gevico/sdcc-c251/blob/b09075b6a93e6afe10645181e3aeff041ea37f87/src/mcs251/main.c)；
- [`doc/mcs251/abi.md`](https://github.com/gevico/sdcc-c251/blob/b09075b6a93e6afe10645181e3aeff041ea37f87/doc/mcs251/abi.md)。

当前编译器源码位于 `D:\Git\stc51\stcxx`，实际工具身份以
[C++ CLI 锁文件](../../tools/cpp-cli/toolchain-lock.json) 为准。
以下身份属于保留的早期 K246 canary/ABI 测量，不是当前工具链版本；原始证据
中的路径和 hash 保持不变，不可用新 hash 替换后继续声称旧结果有效：

- launcher/wrapper：`8db337e32dd8809280dd5f2e3c2539c67976a741118ae027f2f5916c18dec96c`；
- compiler frontend ELF：`1ccd9c28fa7d7fb7428cd43f423a80f1a456f98d32fc0f7823e5163d48d78cb5`；
- `sdldmcs251`：`749a198184383d56902979f45e554b4a24dfe97b8d70b2d891a5e437559263fa`；
- 完整源补丁：`684114dd748396fa9967f18b177944a50800cd5621386a8387e2af24c7aa08f5`。

补丁修复 ISR 上下文、R9 间接访问、PointerGet literal displacement、重叠寄存器
指针加法以及 MCS251 扩展 SPX/SSEG 栈；
独立汇编 regression 覆盖 big-endian u32-to-u24、u16-to-u8、far/local byte load 与
object-plus-offset store。锁定 adapted-C bridge 的编号 warning 契约为 84 x17、196 x14、
244 x22、357 x1，独立 R9 fixture 另有 244 x1。精确身份和门禁在
[`../../tools/cpp-core-pipeline/toolchain-lock.json`](../../tools/cpp-core-pipeline/toolchain-lock.json)
与 [`../../tools/cpp-core-pipeline/README.md`](../../tools/cpp-core-pipeline/README.md) 中维护。

仓库中的 [native-layout-probe.c](../../tests/cpp/abi/native-layout-probe.c) 使用负长度数组断言，
避免 SDCC 把 `_Static_assert` 失败仅作为 warning 处理。复现命令为：

```powershell
$StcAbiSdcc = Resolve-Path `
  'sdk/downloads/variant-work/extract/sdcc-mcs251/sdcc-mcs251/bin/sdcc.exe'
$StcAbiInclude = Resolve-Path `
  'sdk/downloads/variant-work/extract/sdcc-mcs251/sdcc-mcs251/include'
New-Item -ItemType Directory -Force `
  tools/cpp-spike/.build/abi/mcs51,tools/cpp-spike/.build/abi/mcs251 | Out-Null
& $StcAbiSdcc -mmcs51 --std-sdcc11 -I$StcAbiInclude -c `
  tests/cpp/abi/native-layout-probe.c -o tools/cpp-spike/.build/abi/mcs51/probe.rel
& $StcAbiSdcc -mmcs251 --std-sdcc11 -I$StcAbiInclude -c `
  tests/cpp/abi/native-layout-probe.c -o tools/cpp-spike/.build/abi/mcs251/probe.rel
& $StcAbiSdcc -mmcs51 -E -dM tests/cpp/abi/native-layout-probe.c |
  Select-String 'BYTE_ORDER|CHAR_UNSIGNED|SIZEOF|PTRDIFF|SIZE_TYPE'
& $StcAbiSdcc -mmcs251 -E -dM tests/cpp/abi/native-layout-probe.c |
  Select-String 'BYTE_ORDER|CHAR_UNSIGNED|SIZEOF|PTRDIFF|SIZE_TYPE'
```

两个 compile 命令均须返回 0。使用 `double`/`long double` 时，当前 SDCC 会产生 warning 93；
原因见下一节，这条 warning 是已记录的基线现象，不应通过 token 宏隐藏。

## 标量模型

下表是 `stc-arduino-cxx-v1` 的冻结契约。数字为 `size / natural alignment`，单位是 byte；
两个目标的所有已列自然对齐均为 1。显式 over-alignment 尚未纳入首版契约。

| 类型 | MCS51 | MCS251 | 说明 |
|---|---:|---:|---|
| `bool`、`char`、`signed/unsigned char` | 1 / 1 | 1 / 1 | plain `char` 为 unsigned |
| `short`、`int` | 2 / 1 | 2 / 1 | 16-bit `int` |
| `long` | 4 / 1 | 4 / 1 | 32-bit |
| `long long` | 8 / 1 | 8 / 1 | 64-bit |
| `float` | 4 / 1 | 4 / 1 | C++ 契约要求 IEEE binary32 |
| `double`、`long double` | 4 / 1 | 4 / 1 | C++ 契约要求有真实类型语义的 binary32 |
| `size_t` | 2 / 1，`unsigned int` | 4 / 1，`unsigned long` | 不允许假设它与指针等宽 |
| `ptrdiff_t` | 4 / 1，`long int` | 4 / 1，`long int` | MCS51 也不是 16-bit |

MCS51 对象是 little-endian；MCS251 ABI revision 2 对象是 big-endian，且没有可选的
little-endian 模式。

### `double` 的已知源文档冲突

pinned `doc/mcs251/abi.md` 的表格写 `double = 8`，但实际 pinned compiler 在两目标均定义
`__SIZEOF_DOUBLE__=4`、`__SIZEOF_LONG_DOUBLE__=4`，并报告：

```text
warning 93: types 'double', 'long double' not supported. Assuming 'float'
```

实测 `sizeof(double)==4` 和 `sizeof(long double)==4`，因此不能把源文档中的 8 当作已实现
ABI。首版 C++ 契约选择 32-bit `float`、`double`、`long double`，但生产 frontend、bridge、
C 边界 thunk 和 runtime 必须从类型系统层面共同实现它；“SDCC 假定 float”本身也不是
完整 C++ `double` 实现。

严禁用 `-Ddouble=float` 构造或混入此 ABI。该宏会改写 token，破坏类型系统、重载、模板、
名字修饰、varargs 和诊断，且不能证明两个翻译单元的调用约定一致。当前 C-only profile 中
由该宏生成的对象属于另一个 legacy build profile；除经过审核且不含浮点/聚合边界的叶子 C
thunk 外，不得与 `stc-arduino-cxx-v1` 对象链接。

## 指针和地址空间

所有表中指针的 natural alignment 都是 1。

| 指针 | MCS51 size / 内存顺序 | MCS251 size / 内存顺序 |
|---|---|---|
| `__data *` | 1，page-zero byte address | 1，page-zero byte address |
| `__idata *` | 1，internal indirect byte address | 1，page-zero indirect byte address |
| `__pdata *` | 1，live `P2` MOVX page offset | 1，live `MXAX:P2` MOVX page offset |
| `__xdata *` / `__far *` | 2，low/high | 3，bits 23:16 / 15:8 / 7:0 |
| `__code *` | 2，low/high | 3，bits 23:16 / 15:8 / 7:0 |
| generic `T *` | 3，low/high/tag | 3，flat 24-bit high/mid/low，无 tag |
| 普通 function pointer | 2，low/high | 3，high/mid/low |
| 数据成员指针 | 2，16-bit offset/null 表示 | 3，24-bit offset/null 表示 |
| 成员函数指针 | 4，两个 16-bit ABI word | 6，两个 24-bit ABI word |

MCS51 generic pointer 的 tag 固定为 far `0x00`、near `0x40`、xstack `0x60`、code
`0x80`。MCS251 的 generic、far、code 和 function pointer 都是 24-bit 内存对象；
generic pointer 没有地址空间 tag，24-bit 指针运算必须跨 64 KiB 边界传播进位。

MCS251 内存对象虽为 big-endian，SDCC 主参数/返回槽仍按逻辑 low-to-high 使用
`DPL/DPH/B`；三字节指针也可写成 high-to-low 的 `B:DPH:DPL`。这不是 little-endian
内存布局。间接调用把 24-bit 目标装入 DR28 后执行 `ECALL @DR28`。MCS51 普通函数指针
是 2 byte，并使用 SDCC 的 `LCALL`/`RET` 间接 trampoline。两项均由
[C++ lowering spike](../../tools/cpp-spike/README.md) 的汇编与表项断言覆盖。

## stack-auto、SP、SPX 与 xstack

`--stack-auto` 是本 ABI 的强制项。所有普通函数按 reentrant 规则放置 automatic objects、
spill 和非寄存器参数；每个目标和 memory model 必须链接对应的 `*-stack-auto` runtime。
任何默认 overlay 对象混入都应在 pre-link 阶段失败，`extern "C"` 不能豁免该规则。

MCS51 保留 8-bit `SP` hardware stack，位于 IDATA、向高地址增长，push 预增，普通 call
return frame 为 2 byte。`--stack-auto` 不会把这个 call stack 变成 16-bit。

SDCC 的 MCS51 `--xstack` 是另一条机制：它在 `pdata` 中建立最多 256 byte 的 software
pseudo-stack，把 reentrant 参数和 automatic objects 放入其中，同时占用 `P2` page
register；call/return 仍使用 8-bit `SP`。是否在 `stc-arduino-cxx-v1` 的 MCS51 profile
强制启用 xstack、其 page/location 和 ISR 切换规则仍为 **UNFROZEN**。在该选择冻结并有
stack high-water/overflow 测试前，MCS51 C++ 不能过生产门。

MCS251 使用 DR60/SPX architectural view，ABI 有效 stack pointer 是 region `00:` 中完整
16-bit `SPH:SP`，不是旧 MCS51 的 8-bit SP。stack 向高地址增长，startup 写入
`__start__stack - 1`；slot 使用 signed `@SPX+dis16`，取 stack object 地址时物化为 region
`00:` 的三字节 flat pointer。普通 C call 一律 `ECALL`/`ERET`，return frame 3 byte；
interrupt frame 4 byte。默认省略 legacy frame pointer，并用 native `inc/dec spx` 管理 frame。

MCS251 profile 禁止使用 legacy MCS51 `--xstack` pseudo-stack。所有当前 MCS251 profile 的
链接起点均固定为 `0x0100`：STC32G12K64/K128 使用 `0x0f00` byte；
STC32G8K64/G8K48、STC32CL8K64/CL8K48 与三个 AI8051U 容量的 MCS251 模式使用
`0x0700` byte；STC32F12K54 使用 `0x1f00` byte；STC32G144K246 使用
`0x3f00` byte。链接器检查 SSEG 边界并在 `.mem` 中记录 SPX
范围；K246 的 region `00:` EDATA 仍只有 `0x0000..0x3fff`（16 KiB），不能因其
128 KiB XDATA 而扩大 SPX 可用容量。运行时 high-water、guard、递归深度和 ISR
nesting 的实板资格仍未冻结。

堆容量同样按器件冻结。STC32F12K54 的 4 KiB XDATA 只允许 3,584 字节 heap，
另为 allocator telemetry 和其他静态 XDATA 保留 512 字节预算；最终链接必须同时
检查声明预算与实际 XDATA 用量。AI8051U-34K16 的两个目标各使用 14,336 字节
compact 程序上限，这属于容量合同，不改变本 ADR 的目标 ABI。

## 构造、局部静态与结束策略

启动可观察顺序固定为：

```text
reset entry -> .data copy / .bss zero -> __stcxx_run_global_ctors()
-> main() -> init() -> initVariant() -> setup() -> loop()
```

全局构造器必须在 `main()` 前且只执行一次，所以不得假设 `init()` 已配置 GPIO、Timer 或
UART。同一 translation unit 内按 definition order；跨 translation unit 的相对顺序不由
C++ 程序依赖，最终表即使采用确定性 tie-break 也不得宣传为语言保证。函数局部静态在首次
执行路径初始化且只执行一次，首版不提供线程安全 guard。裸机不运行全局析构，也不依赖
`atexit`。

这是生产 ABI 的目标顺序，不是当前实现状态。当前 runtime slice 在 `main()` 的 core
prologue 调用 `__stcxx_run_global_ctors()`，已经保证构造器早于 `init()`、`setup()` 和
`loop()`，但机器已经进入 `main()`；严格 pre-main 的 GSFINAL/startup-section 接入仍是
生产阻断项。两种顺序分别记录在 `abi-manifest.json`，在该阻断项完成前不得把目标端构造
语义标记为 `SUPPORTED`。

## 已冻结与未冻结

已冻结：

- 两目标的端序、基础宽度、plain-char signedness、natural alignment；
- `size_t`、`ptrdiff_t` 和各地址空间/函数指针表示；
- C++ profile 的 32-bit 三种浮点类型目标、`--stack-auto` 和禁止 overlay 混入；
- MCS251 SPX 语义；
- 构造器相对 `main()`/Arduino init 的位置、exactly-once 和不运行全局析构。

仍未冻结且阻断生产：

- candidate A/B 的生产选择以及专用 Clang target identity、`CXXABI/ABIInfo`；当前仅有
  synthetic-triple IR-only TargetInfo 与范围受限 adapter；
- 完整 class/vtable/mangling 边缘、aggregate `sret/byval`、varargs、enum/bit-field；
- MCS51 xstack 策略；MCS251 已固定链接范围之外的 runtime
  high-water/guard/overflow 与 ISR nesting；
- allocator/heap 地址空间；跨 TU ctor table 的实现 tie-break；
- 严格 machine-level pre-main 的 startup-section 集成；
- 不依赖 token 宏的 C++ `double` frontend、lowering、helper 和边界验证。

因此现在要求全部 22 个 active variants、25 个执行配置（14 MCS51 + 11 MCS251）
通过各自 12 MHz Arduino CLI C++ compile/link/capacity 和精确 QEMU 门。6 个 compact
profile 各要求 `runtime`/`io` 两项，19 个 full profile 各要求一项，共 31 项；
双目标普通函数指针、数据成员指针、
非虚/虚成员函数指针与 null 检查也属于该门。保留 JSON 的当前 outcome 不写入 ADR；
无论结果如何都不允许据此把清单状态改为 `SUPPORTED`，也不允许发布宣称“广泛兼容
Arduino C++ 库”的工具链。锁定 QEMU 提交
`faeac38c0076795d7b4e59f0ddcb5fc7e7bd7015` 已经提供 25 个精确 machine，但
model 存在不等于 PASS，并且禁止 machine alias。最终 clean run 正在重新生成，
只有相互哈希绑定的权威 JSON 可以声明 outcome。当前没有代表性实板资格认证，真实晶振/ISP、电气与模拟、复位、
栈边界和模型外设仍必须在对应实板完成后才能形成硬件发布结论。
