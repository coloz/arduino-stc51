# MCS251 型号目录

核对日期：2026-09-06。本目录按 STC 官方选型表及[生命周期核查](variant-lifecycle.md)登记，速度、温度等级、
封装后缀不另建 variant。每个 variant 描述该型号最大的逻辑 GPIO 集合，具体封装仍应
按原厂管脚表接线。ARM Cortex-M0 的 STC32F03x 不在 MCS251 范围内。

## 已登记型号

KiB = 1024 字节。表中的范围仅为 MCS251 Source 模式下可供用户存放程序的 Flash，
不将 EEPROM、厂商数学库 ROM 或 USB 缓冲区计入代码容量。

| 型号 | 用户 Flash | MCS251 程序地址 | EDATA / XDATA | variant |
|---|---:|---|---|---|
| STC32G12K128 | 128 KiB | FE0000–FFFFFF | 4 / 8 KiB | `STC32G12K128` |
| STC32G12K64 | 64 KiB | FF0000–FFFFFF | 4 / 8 KiB | `STC32G12K64` |
| STC32G8K64 | 64 KiB | FF0000–FFFFFF | 2 / 6 KiB | `STC32G8K64` |
| STC32G8K48 | 48 KiB | FF0000–FFBFFF | 2 / 6 KiB | `STC32G8K48` |
| STC32CL8K64 | 64 KiB | FF0000–FFFFFF | 2 / 6 KiB | `STC32CL8K64` |
| STC32CL8K48 | 48 KiB | FF0000–FFBFFF | 2 / 6 KiB | `STC32CL8K48` |
| STC32G144K246 | 246 KiB | FC2800–FFFFFF | 16 / 128 KiB | `STC32G144K246` |
| AI8051U-34K64 | 64 KiB | FF0000–FFFFFF | 2 / 32 KiB | `AI8051U_34K64` |
| AI8051U-34K32 | 32 KiB | FF0000–FF7FFF | 2 / 32 KiB | `AI8051U_34K32` |
| AI8051U-34K16 | 16 KiB | FF0000–FF3FFF | 2 / 32 KiB | `AI8051U_34K16` |

所有上述型号的 MCS251 复位入口都在 `0xFF0000`。降容量型号保持该入口，
不能用 `0x1000000 - flash_bytes` 推算其程序起点。数据库在这些型号的
`linker.flash_loc` 或 `mcs251_linker.flash_loc` 中显式记录起点；构建检查同时
限制 HEX 数据和 MAP 中的 CODE 段不越过实际程序区末端。

STC32G12K128 与 STC32G144K246 沿用现有链接策略，连续可用代码上限分别为
64 KiB 和 182 KiB，以避开 `0xFF0000` 的 HOME 向量区；物理 Flash 容量不代表
当前链接器已可利用全部空间。AI8051U 默认使用 MCS51 模式，其程序起点为 `0x0000`；
在 Arduino 的 Execution mode 菜单选择 MCS251 后才使用上表地址，烧录模式必须一致。

STC32F12K54 已于 2026-09-06 移除，原厂明确其不是量产产品，详见生命周期记录。

STC32G8K64 与 STC32G8K48 的 ADC 通道 2 均映射到 P5.4，P1.2 保留为数字 GPIO，
依据 STC32G 手册 §22.1.1；本次同步修正已有 STC32G8K64 的模拟引脚映射。

## 新增型号的资格范围

以下 2026-09-05 的 22 型号 / 25 配置 / 31 workload 说明保留为历史资格记录。
移除两款后当前支持 20 个型号、23 种执行配置，旧记录不代表当前配置已经验证。

2026-09-05 新增 STC32G8K48、STC32CL8K48、STC32F12K54、AI8051U-34K32 和
AI8051U-34K16。它们提供实验性 plain-C 配置及保守的 12/24 MHz 时钟选项，
现在也提供显式 `cppcore=enabled` 的 12 MHz C++ profile，并已加入逐配置精确 QEMU
合同。完整集合为 22 个物理型号、25 个执行配置（14 MCS51 + 11 MCS251）和
31 个 workload（6 compact×2 + 19 full×1）。AI8051U-34K16 的两个执行模式属于
compact，程序上限都是 14,336 字节；STC32F12K54 属于受约束的 full profile，
其 4 KiB XDATA 分配 3,584 字节 heap，并为其他静态 XDATA 保留 512 字节预算。

新增型号不继承相邻芯片或历史 17/18 集合的运行结果。锁定 QEMU 提交
`faeac38c0076795d7b4e59f0ddcb5fc7e7bd7015` 已提供对应 exact machine，但最终
25-profile/31-workload clean run 正在重新生成；只有同次 source set、build manifest、
固件哈希和 runtime audit 相互绑定后的权威 JSON 才能声明 PASS。数据库或构建脚本
变化也会使旧证据的源码哈希绑定过期。

运行全部 plain-C 型号验证：

```powershell
& ./scripts/test-all-variants.ps1 -KeepWorkDirectory
```

只验证本次新增型号（AI8051U 的两种执行模式会分别编译）：

```powershell
& ./scripts/test-all-variants.ps1 -DeviceId @(
    'stc32g8k48', 'stc32cl8k48',
    'ai8051u_34k32', 'ai8051u_34k16'
) -SkipLibraryProbes -KeepWorkDirectory
```

编译、链接、地址边界检查和 exact-machine 可用性都不代表实板验证；当前这些新增
型号的实板状态仍为待验证，精确 QEMU outcome 只读取机器可读证据。

## 原厂资料

- [STC32G12K128/12K64 选型表](https://www.stcmicro.com/stc/stc32g12k128.html)
- [STC32G8K64/8K48 选型表](https://www.stcmicro.com/stc/stc32g8k64.html)
- [STC32CL8K64/8K48 选型表](https://www.stcmicro.com/stc/stc32cl8k64.html)
- [STC32G 完整手册](https://www.stcmicro.com/datasheet/stc32g-cn.pdf)：
  §21.3.2 的 16 KiB EEPROM 地址为 FFC000–FFFFFF，对应 48 KiB 程序区；§22.1.1 ADC 映射。
- [STC32G144K246 产品页](https://www.stcmicro.com/stc/stc32g144k246.html)
- [STC32F 系列技术手册，2024-02-02](https://www.stcmicro.com/datasheet/stc32f-cn.pdf)：
  §1.4、§2.1 型号和管脚，§10.1 程序映射，§10.2 RAM，§21.1 ADC。
- [AI8051U 选型简介](https://www.stcmicro.com/datasheet/Ai8051U_Features.pdf)及
  [完整手册](https://www.stcmicro.com/datasheet/AI8051U-cn.pdf)：§12.1 程序区、
  §22.4 EEPROM 从 Flash 尾部向前分配。

旧版手册示意图和示例注释残留的 STC32F12K60、STC32F12K16 没有出现在当前
STC32F 选型表中，本目录不据此推导额外可售型号。
