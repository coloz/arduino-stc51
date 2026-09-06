# 变体生命周期核查

核查日期：2026-09-06。范围为原 `tools/variants/devices.json` 的 22 个具体型号，
不含 `_common`，也不把速度、温度、封装或芯片修订版当作独立基础型号。

本次移除 2 款，保留 20 款，对应 23 种执行配置（13 MCS51 + 10 MCS251）。
保留表示本次未查到足以确认整款停产或停售的证据，**不等于原厂承诺长期供货**。
旧产品页面、手册下载、经销商库存及替代建议都不能单独证明仍在生产或已经停产。

## 移除依据

| 型号 | 结论与证据 | 处理 |
| --- | --- | --- |
| STC8A8K64S4A12 | [西安电子科技大学出版社的教材换版说明](https://www.xduph.com/pages/BookDetail.aspx?doi=71edf789-cd44-4bd6-95b5-e8424b2ccc6d&type=1)明确说明因该型号停产，第二版改用 STC8A8K64D4；[原厂论坛](https://www.stcaimcu.com/forum.php?mod=viewthread&tid=17544)的 2025-05-06 第 7 楼也记录了使用企业的替换经历，第 8 楼超级版主提供替换资料。 | 移除基础型号。出版社说明是直接的教材变更记录，并非原厂 PCN。 |
| STC32F12K54 | [原厂论坛第 3 页](https://www.stcaimcu.com/forum.php?mod=viewthread&tid=3993&page=3)第 24 楼，超级版主 AI-32位8051 于 2026-01-30 明确指出其不是量产产品、不要使用，并建议 Ai8051U/STC32G 系列；第 26 楼记录下架，第 28 楼称已停产。 | 按不再作为可选供货型号移除。官方人员可确认的准确表述是“不是量产产品”，停产、下架的描述来自同帖用户，不将其冒充正式 EOL 公告。 |

STC8A8K64D4 不在当前支持集合内，本次没有把旧配置直接改名成替代型号。
替换芯片仍须分别核对引脚、寄存器、外设和程序，不能继承旧型号的验证结论。

## 保留型号及核查资料

以下各行均未发现足以确认整款停产/停售的证据，继续保留。选型资料作为型号与
封装的交叉核对，不能单凭页面存在推断供货状态。

| 型号 | 核查资料 |
| --- | --- |
| STC8C2K64S4 | [原厂产品页](https://www.stcmicro.com/cn/stc/stc8c2k64s4.html) |
| STC8G1K08 | [原厂产品页](https://www.stcmicro.com/cn/stc/stc8g1k08.html) |
| STC8G1K08A | [原厂产品页](https://www.stcmicro.com/cn/stc/stc8g1k08a.html) |
| STC8G2K64S4 | [原厂产品页](https://www.stcmicro.com/cn/stc/stc8g2k64s4.html) |
| STC8H1K08 | [原厂产品页](https://www.stcmicro.com/cn/stc/stc8h1k08.html) |
| STC8H1K28 | [原厂产品页](https://www.stcmicro.com/cn/stc/stc8h1k28.html) |
| STC8H3K64S4 | [原厂产品页](https://www.stcmicro.com/cn/stc/stc8h3k64s4.html) |
| STC8H8K64U | [原厂产品页](https://www.stcmicro.com/cn/stc/stc8h8k64u.html) |
| Ai8H2K12U | [原厂产品页](https://www.stcmicro.com/cn/ai/ai8h2k12u.html) |
| Ai8H2K32U | [原厂产品页](https://www.stcmicro.com/cn/ai/ai8h2k32u.html) |
| STC32CL8K48、STC32CL8K64 | [原厂选型表](https://www.stcmicro.com/stc/stc32cl8k64.html) |
| STC32G8K48、STC32G8K64 | [原厂选型表](https://www.stcmicro.com/stc/stc32g8k64.html) |
| STC32G12K64、STC32G12K128 | [原厂选型表](https://www.stcmicro.com/stc/stc32g12k128.html) |
| STC32G144K246 | [原厂产品页](https://www.stcmicro.com/stc/stc32g144k246.html)；[原厂论坛](https://www.stcaimcu.com/forum.php?mod=viewthread&tid=21279)第 7 楼于 2025-11-28 明确回复 LQFP100/LQFP64 已在商城销售。 |
| AI8051U-34K16、AI8051U-34K32、AI8051U-34K64 | [原厂选型简介](https://www.stcmicro.com/datasheet/Ai8051U_Features.pdf)；[原厂论坛](https://www.stcaimcu.com/forum.php?mod=viewthread&tid=3993&page=3)仍将 Ai8051U 系列列为推荐选型。 |

旧手册中 STC8F2K64S4 的 A/B 版停产说明不适用于 STC8A8K64S4A12，也不涉及当前
保留的 STC8G/STC8H 型号。具体 Beta 版、某一封装停供的记录不用于删除整个型号。

## 仓库一致性

删除源数据库中的对应设备后重新生成 `boards.txt`，同时删除两个 `variants/`
目录，避免重新生成或打包时复活已移除型号。其余型号的寄存器、引脚和编译配置不变。

`package_arduino-stc51_index.json` 描述已发布的 0.0.1 归档，因此保留其历史板卡清单，
不把当前源码的移除伪装成旧归档已发生变化。技术文档中保留的 22 型号 / 25 配置 /
31 workload 及 STC32F12K54 内存约束属于移除前的工具链和验证记录。
本次没有重写历史结果或宣称完成新的全量编译、QEMU、实板验证。
