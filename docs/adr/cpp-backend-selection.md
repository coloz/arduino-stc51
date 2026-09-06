# ADR: STC Arduino C++ 后端选择

> Lifecycle update (2026-09-06): the active platform now has **20 models / 23 execution profiles**
> (13 MCS51 + 10 MCS251). STC8A8K64S4A12 and STC32F12K54 were removed.
> The 22-model / 25-profile / 31-workload set and removed-device details below are
> historical toolchain/qualification records, not the current support list or new PASS evidence.
> See the [lifecycle review](../variant-lifecycle.md).

状态：**EXPERIMENTAL CANDIDATE-A CANARY / PRODUCTION NOT_SELECTED / NOT_SUPPORTED**  
关联 ABI：[cpp-target-abi.md](cpp-target-abi.md)  
当前证据：[cfront lowering shape spike](../../tools/cpp-spike/README.md)、
[LLVM-CBE GNU++11 bridge spike](../../tools/cpp-bridge-spike/README.md)

## 结论

Candidate A 已被实现为范围受限的 MCS51/MCS251 双目标实验 profile，但尚未被选为生产后端；candidate B
仍为 `NOT_READY`。当前链路把真实 GNU++11 翻译单元经专用 Clang IR-only TargetInfo、
LLVM 20、fail-closed LLVM-CBE adapter 和补丁 SDCC 落到对应目标，并有 Arduino CLI
与逐配置精确 QEMU 门禁。普通函数指针及 2/4-byte MCS51、3/6-byte MCS251 成员指针
布局已进入完整 build identity；它仍借用只用于 triple 分发的 MSP430 arch 名称，
C/C++ ABIInfo 也没有成为完整 STC production ABI，因此不能把中间 canary 外推到其他
型号、时钟或任意库。

plain-C recipe 仍是默认路径。全部 22 个物理型号、25 个 MCS51/MCS251 执行配置有显式
`cppcore=enabled` 12 MHz opt-in；资格合同要求 14 MCS51 + 11 MCS251 profile，并将
6 个 compact profile 各拆为 `runtime`/`io`、其余 19 个使用 `full`，合计 31 个
workload。当前 outcome 只由 `tests/cpp/variant-matrix/*.json` 声明。
其状态明确为
`EXPERIMENTAL` / `NOT_SUPPORTED`。生产 G2 完成前，
任何文档、core class 或测试都不得把它写成 `SUPPORTED` 或“广泛兼容”。

## Candidate A：LLVM-to-SDCC-C backend

候选链路是：

```text
Clang C++ -> whole-program LLVM bitcode -> dedicated LLVM-to-SDCC-C backend
-> pinned sdcc -mmcs51/-mmcs251 -> ASxxxx REL/IHX
```

它可以复用成熟 MCS51 codegen 和当前 MCS251 assembler/linker，但 bridge 本身必须是一个
目标专用编译器后端，而不是普通 pretty-printer。

审计与构建的 stock [`JuliaHubOSS/llvm-cbe`](https://github.com/JuliaHubOSS/llvm-cbe/tree/83f1bea66c7415c701925470a2f7596b37153197)
commit 为 `83f1bea66c7415c701925470a2f7596b37153197`（切换 LLVM 22 之前的
LLVM 20 兼容提交）。下列是 stock CBE 本身的阻断项；实验 canary 仅在固定输入集合上
由审计器、adapter 与显式 runtime bridge 封闭这些缺口，并未在上游 CBE 中通用解决：

- LLVM `PointerType` 统一输出为普通 C `void *`/pointer，没有保留 LLVM address space，无法
  表达 `__data/__idata/__pdata/__xdata/__code` 和 MCS51 generic tag；
- `llvm.global_ctors` 被映射为 GCC `__attribute__((constructor))`，而 STC reset/startup
  需要显式 constructor table 和 `__stcxx_run_global_ctors()`；
- stock CBE 没有冻结的 MCS51/MCS251 DataLayout、24-bit pointer、typed C boundary thunk、
  stack-auto identity 或 C++ ABI version；
- 还没有证明 SSA/PHI、`poison/undef/freeze`、整数溢出、aggregate、varargs、COMDAT/weak、
  64-bit helper 和未知 IR 能在不引入 C undefined behavior 的前提下正确降低。

因此“llvm-cbe 能输出 C”不等于 candidate A 已实现。要进入选择评测，必须先有专用 fork，
让未知 IR 显式失败、保留地址空间和 ctor/ODR 语义，并用同一 `stc-arduino-cxx-v1` runtime
完成 compile/link/run。

### 2026-09-01 stock LLVM-CBE spike 结论

固定 LLVM/Clang 20.1.8 与 LLVM-CBE commit
`83f1bea66c7415c701925470a2f7596b37153197` 的实跑使用五个原始 GNU++11 TU，覆盖继承、
构造、跨 TU virtual dispatch、captured lambda、template 和两个 global constructor。
经 `llvm-link`/`opt` 后，原始 CBE C 分为两种可审计 profile：

- mechanical-only 只替换编译器 preamble/attribute 并生成显式 ctor runner；MCS51 与 MCS251
  都能 compile/link，MCS251 在 K246 QEMU 得到 `BEGIN/PASS`；
- typed profile 还对该 fixture 精确修复被擦除的 vtable/vptr/address-space；两目标均
  compile/link，MCS251 同样在 K246 QEMU 得到 `BEGIN/PASS`。

负向门拒绝未知 opcode、address space、`freeze`、target/ctor/CBE shape 漂移，以及
`llvm.global_dtors`、`__cxa_atexit`/`atexit` 和 CBE destructor attribute。Clang 同时使用
`-fno-c++-static-destructors`。生成物保存命令、工具版本/提交/hash、HEX、UART、Flash 尺寸和
机器可读 JSON。

这项历史 spike 把“链路能否执行”的答案推进为 fixture mechanism PASS，但当时 target ABI
gate 仍为 FAIL：MSP430 原生 layout 不是 STC layout；stock CBE 擦除了 pointer/address
space；MCS51 mechanical vtable 实际为 3-byte generic slot，而函数指针为 2 byte；typed
profile 又是 fixture 专用语义改写。后续 canary 没有把这些限制改写为 production PASS，
而是以专用 IR-only TargetInfo、固定 adapter 与拒绝门把接受范围收窄。

### 2026-09-01 K246 Arduino core canary

当前实验实现固定为：

```text
GNU++11 TU -> Clang 20.1.8 STC IR-only profile -> linked/audited LLVM 20 IR
-> locked LLVM-CBE + fail-closed adapter -> patched SDCC MCS251 -> K246 HEX
```

synthetic triple 为 `msp430-stc-none-eabi`，但只用于让 Clang 选择受补丁保护的 IR-only
TargetInfo；生成原生 MSP430 汇编/对象会被拒绝。精确大端 24-bit pointer DataLayout、
目标宏、接受的 IR/C shape、constructor bridge、工具 hash 和 SDCC warning multiset 都由
门禁锁定。当前编译器源码位于 `D:\Git\stc51\stcxx`，实际身份以
[C++ CLI 锁文件](../../tools/cpp-cli/toolchain-lock.json) 为准。
下表及其 warning 数量属于保留的早期 canary 测量，不代表当前工具链，
也不能因更新工具而原地改写这些历史测量：

| artifact | SHA-256 |
|---|---|
| launcher/wrapper | `8db337e32dd8809280dd5f2e3c2539c67976a741118ae027f2f5916c18dec96c` |
| compiler frontend ELF | `1ccd9c28fa7d7fb7428cd43f423a80f1a456f98d32fc0f7823e5163d48d78cb5` |
| `sdldmcs251` | `749a198184383d56902979f45e554b4a24dfe97b8d70b2d891a5e437559263fa` |
| complete source patch | `684114dd748396fa9967f18b177944a50800cd5621386a8387e2af24c7aa08f5` |

锁定 bridge 的编号 warning 契约为 84 x17、196 x14、244 x22、357 x1；独立 R9 fixture
另有 244 x1。门禁还直接覆盖 MCS251 big-endian pointer narrowing、far/local byte load 和
overlapping-register pointer arithmetic，任何 warning、汇编 shape 或 hash 漂移都会失败。

Arduino CLI canary 覆盖 core/sketch/library C++ TU、C/C++ 混合链接、constructor、模板、
lambda、virtual dispatch、allocation/OOM、local-static guard、`String`/`Print`/`Stream`、
`HardwareSerial`、SPI/Wire/SD bridge、普通/成员函数指针与 stale-sidecar rejection。
全部 22 个 active variants、25 个执行配置都进入 build/QEMU 矩阵；其中
AI8051U-34K16 的两个 compact profile 使用 14,336 字节程序上限，STC32F12K54
使用 3,584 字节 heap 与 512 字节静态 XDATA reserve。最终结果必须绑定
同一次 retained build manifest、固件 hash、工具审计和逐配置 runtime audit。锁定源码提交
`faeac38c0076795d7b4e59f0ddcb5fc7e7bd7015` 提供 25 个精确 machine，但 model
存在本身不是 PASS，且禁止 alias。最终 clean run 正在重新生成，只有权威 JSON
可以声明 outcome。QEMU 不替代真实晶振、
ISP、电气、模拟、复位、栈边界和外设实板验证。当前没有代表性实板资格认证。

## Candidate B：原生 LLVM MCS51/MCS251 backend

候选链路是：

```text
Clang C++ -> whole-program LLVM bitcode -> native MCS51/MCS251 codegen
-> ASxxxx-compatible assembly -> sdas8051/sdas251 + sdld
```

找到的 [`Jiangshan00001/llvm-mcs51-backend`](https://github.com/Jiangshan00001/llvm-mcs51-backend)
基于 LLVM 13，README 明确写明 “this could not work yet”。它没有可用的 MCS251 target，也
没有本项目冻结的地址空间、调用/stack、ASxxxx output、ABI revision、运行库和回归证据，
不能作为 candidate B 实现或可复用生产 backend。

Candidate B 还必须处理：

- MCS51/MCS251 指令选择、寄存器重叠、legalization、frame/call/ISR lowering；
- Harvard/flat address space、MCS51 tagged generic pointer 和 MCS251 24-bit relocation；
- ASxxxx assembler/linker 可表达的符号与 relocation；
- 最终 codegen 前的 bitcode prelink，以解析 template/COMDAT/weak/linkonce、constructor、
  archive extraction 和用户强定义覆盖。不能把这些 ELF/ODR 语义留给未承诺它们的 `sdld`。

目前上述项目均未完成，所以 candidate B 同样是 `NOT_READY`。

## cfront spike 的证据边界

mechanism spike 使用历史 `seyko2/cfront-1` commit
`c8b746a220959cf346c01a0619fa11584d9f5210` 观察 1985 年 C++ lowering shape。该仓库没有
`LICENSE`/`COPYING`，本项目不分发其源码或二进制；它也不支持 Arduino 所需的 C++11。

原始 cfront 输出含无原型 `int (*)()` vtable、K&R definition、host `sizeof` 和不兼容
function-pointer cast。仓库保存的 C fixture 已人工改成 typed vtable、ANSI prototype、typed
thunk 和由 SDCC 决定的目标布局。固定 SDCC 下的构建结果为：

| target | Flash | XRAM | 已检查的 indirect call |
|---|---:|---:|---|
| MCS51 | 601 B | 6 B | 2-byte function pointer、`LCALL`/`RET` trampoline |
| MCS251 | 743 B | 8 B | 3-byte function pointer、`ECALL @DR28` |

这只证明“受控 C lowering 可落到两个 SDCC backend”。人工修正过程本身就是尚缺 production
frontend/backend 的证据，不能用来选择 A，也不能把 cfront 作为第三候选。

## 选择门

两候选必须使用相同的真实 GNU C++11 输入、相同 ABI manifest 和相同 `-Os` 预算。至少全部
满足下列门后才允许提交新的 selection ADR：

| gate | Candidate A | Candidate B | 当前要求 |
|---|---|---|---|
| 两目标自动 compile/link | DUAL_TARGET_IMPLEMENTED; CURRENT_RESULT_IN_AUTHORITATIVE_JSON | NOT_RUN | 不能包含手工改写中间 C/asm |
| 所有地址空间与 pointer round-trip | DEFAULT_FLAT_PARTIAL | NOT_RUN | specific/generic/code/function 均运行验证 |
| class/vtable/member pointer/aggregate/varargs | CANARY_PARTIAL | NOT_RUN | 跨 TU 且与 ABI manifest 一致 |
| template/COMDAT/weak/archive/override | CANARY_PARTIAL | NOT_RUN | 语义差异必须为 0 |
| global/local constructors | HISTORICAL_K246_CANARY; CURRENT_RESULT_IN_AUTHORITATIVE_JSON | NOT_RUN | 启动顺序、exactly-once、reset 均通过 |
| stack-auto/recursive/indirect/ISR | DUAL_TARGET_PARTIAL; CURRENT_RESULT_IN_AUTHORITATIVE_JSON | NOT_RUN | stack high-water 与 overflow 可观察 |
| 32-bit C++ `double` without token macro | TARGET_SHAPE_ONLY | NOT_RUN | frontend、runtime、varargs、mangling 一致 |
| unknown IR or silent miscompile | CANARY_FAIL_CLOSED | NOT_RUN | 数量必须为 0；unsupported 必须诊断失败 |
| MCS51 + MCS251 QEMU oracle | 25_EXACT_MACHINES_AVAILABLE; CURRENT_RESULT_IN_AUTHORITATIVE_JSON | NOT_RUN | 仅计与同次 source set/build manifest/固件绑定的 31 个精确 QEMU workload，且只覆盖已建模范围 |
| representative hardware | NOT_RUN | NOT_RUN | QEMU 不能替代实板发布门 |
| Windows/Linux/macOS reproducible build | WSL_QUALIFICATION_ONLY | NOT_RUN | pinned source、hash、command、artifact |

选择时还要报告相对同功能 SDCC C baseline 的 Flash、static RAM、maximum stack、build time、
中间文件大小、诊断质量和维护面。任一候选未过门时，只能继续使用
`EXPERIMENTAL C++ SUBSET` 描述；不能因另一个候选更差而自动胜出。

## 重新决策条件

满足以下任一条件后重新打开本 ADR 的生产选择：

1. Candidate A 专用 fork 自动生成两个目标的 class/virtual/ctor/addrspace fixture，并在 QEMU
   对已建模范围得到 oracle PASS；
2. Candidate B 生成可由 ASxxxx 接受的两目标汇编，并通过同一 fixture 和 ODR/prelink gate；
3. 出现另一个有明确许可、现代 C++11 frontend、两目标 ABI 和可复现运行证据的方案。

在此之前，生产选择值保持 `NOT_SELECTED`；candidate A 的 K246 12 MHz Arduino CLI 入口只保留
`EXPERIMENTAL` / `NOT_SUPPORTED` canary 身份，plain-C 继续作为默认值。
