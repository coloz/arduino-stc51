# Arduino core API 兼容范围

当前平台仅维护 10 个 MCS251 型号，型号和封装引脚以 `tools/variants/devices.json` 为准。

| API | 当前行为与边界 |
| --- | --- |
| setup / loop | plain C 默认；启用 cppcore 后为真实 C++11 |
| pinMode / digitalRead / digitalWrite | 按型号的有效 GPIO；支持输入、上拉、推挽、准双向和开漏，具体上拉寄存器按型号选择 |
| millis / micros / delay | Timer0 时基；时钟必须与 ISP 配置一致；禁止在不允许中断推进的上下文中阻塞等待 |
| Serial | UART1、Timer1；同步发送、中断接收缓冲，需及时读取并检查 overflow |
| analogRead / analogReadResolution | 默认 10 位，按型号的 10/12 位 ADC；无 ADC、无效通道、超时返回 -1 |
| analogWrite | 已映射的 STC32G/STC32CL/AI8051U 引脚输出硬件 PWM，其余有效引脚数字阈值回退 |
| attachInterrupt | INT0=P3.2、INT1=P3.3；STC32/AI 支持 CHANGE/FALLING，RISING 用软件过滤 |
| String / Print / Stream / IPAddress | C++ 类接口，有限堆及 32 位浮点精度 |
| STCByteOrder.h | 显式 LE/BE 16/32/64 位编码，允许非对齐缓冲，调用方检查长度 |

带 `Checked` 的 GPIO/PWM/中断/总线扩展提供可检查的错误状态，详见[实际开发说明](arduino-practical-api.md)。EEPROM/IAP、通用 USB、CAN、DAC、多路 UART、tone 和 Servo 尚无通用 Arduino 实现。

第三方库能通过 C++ 语法分析，不等于其 AVR 寄存器、PROGMEM、原子操作或时序假设适用于本平台。完整运行时边界见 [C++ 合同](cpp-runtime-contract.md)，外设库见[库兼容说明](library-compatibility.md)。
