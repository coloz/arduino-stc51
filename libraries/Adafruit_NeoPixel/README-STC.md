# Adafruit NeoPixel 的 STC 移植

本目录基于 Adafruit NeoPixel **1.15.5**，移植版本为 **1.15.5-stc.1**。
保留上游 C++ API、颜色转换、亮度、RGB/RGBW 数据排列与 LGPL 许可；原文件摘要见
[upstream.json](upstream.json)，许可证见 [COPYING](COPYING)。
`architectures=mcs251` 使 Arduino 优先选择本平台随附版本。库管理器中的原始库无需修改。

当前输出后端是**实验性实现**，支持：

- STC32G144K246，MCS251 模式，12 MHz 或 48 MHz，实际时钟必须与 IDE 一致。
- P0～P7 中当前封装有效的 GPIO；P8、P9、PA、PB 暂不支持。
- `NEO_KHZ800`，RGB 和 RGBW 字节流。400 kHz 暂不支持。
- `begin()` 对不支持的引脚或速率返回 `false`；其他芯片在编译时给出明确错误。

```cpp
#include <Adafruit_NeoPixel.h>
Adafruit_NeoPixel pixels(8, P1_0, NEO_GRB + NEO_KHZ800);
void setup() {
  if (!pixels.begin()) { while (true) {} }
  pixels.setPixelColor(0, pixels.Color(32, 0, 0));
  pixels.show();
}
void loop() {}
```

发送过程使用独立 SDCC 汇编，直接操作端口位，保存并恢复进入前的中断使能状态。
时序段不调用 `digitalWrite()`、`delayMicroseconds()`，也不经过 C++ 转 C 优化。
发送期间中断暂停，计时与串口接收可能受影响，长灯带尤其如此。
按指令表计算的目标为：T0H 333 ns、T1H 667 ns、周期 1.25 µs；复位间隔沿用上游 300 µs。
像素分配额外保留一个预取字节，字节数溢出会拒绝分配。

来源：[STC32G144K246 手册](https://www.stcmicro.com/datasheet/STC32G144K246-cn.pdf)
附录 A 的 Source 模式指令周期，以及
[Worldsemi WS2812B-2020 数据手册](https://cdn-shop.adafruit.com/product-files/4684/4684_WS2812B-2020_V1.3_EN.pdf)。
芯片手册对无条件跳转周期的表格和注释存在差异；当前指令模型按指令详情的 3 个时钟计算。
**编译、链接和指令模型检查已进行，尚未用实板、示波器验证缓存、跳转及 GPIO 边沿对波形的影响，不能视为灯带时序验收。**

维护时运行 `scripts/generate-neopixel-stc.py` 生成 `src/neopixel_stc.c`。
本轮已用指令模型检查真实 SDCC 汇编输出中的 64 个引脚、全部字节值、
256/257 字节计数边界及预取边界；临时检查脚本已清理。该检查不模拟实际硬件。
