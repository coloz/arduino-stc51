# Arduino Core API 兼容性说明

本文说明 `arduino-stc51` 当前统一核心所承诺的兼容范围。这里的“兼容”是
Wiring 风格的 **plain C API**，不是 Arduino AVR/SAMD/ESP 等 C++ Core 的
二进制或完整源码兼容。

## 编译模型与对象式语法

SDCC 的 8051 后端不提供本项目所需的完整 Arduino C++ ABI，因此构建系统将
`.ino` 作为 C 编译。草图仍使用 `setup(void)` 和 `loop(void)`，但应遵守 C
语法：不能使用类、继承、构造函数、重载、模板、引用、命名空间或 lambda。

`Serial`、`Wire`、`SPI`、`SoftwareSerial`、`LiquidCrystal`、`Stepper` 和 `SD` 是
只读函数指针表，因而可以保留熟悉的点号写法：

```c
#include <Arduino.h>
#include <Wire.h>
#include <SPI.h>

void setup(void)
{
    Serial.begin(9600UL);
    Wire.begin();
    SPI.begin();
    SPI.beginTransaction(100000UL, MSBFIRST, SPI_MODE0);
}

void loop(void)
{
}
```

这只是 C 结构体成员调用，不是 `HardwareSerial`、`TwoWire` 或 `SPIClass` C++
对象。没有 Arduino C++ 的默认参数和重载，例如数值输出应使用
`Serial.printNumber(value, DEC)`，两参数随机数应使用
`random_minmax(lower, upper)`。依赖 `String`、`Print`、`Stream`、
`Printable` 或 C++ 回调对象的第三方 Arduino 库必须先移植，不能仅靠改
头文件名直接编译。

每个对象也有等价的函数前缀接口，例如 `Serial_begin()`、`Wire_write()`、
`SPI_transfer()`、`SoftwareSerial_poll()`；在需要明确控制链接内容或调试调用
路径时可直接使用。

## API 矩阵

| 类别 | 当前支持 | 兼容性边界 |
| --- | --- | --- |
| 草图生命周期 | `setup`、`loop`、`yield`、`initVariant` | plain C；`yield()` 默认为空 |
| 数字 GPIO | `pinMode`、`digitalWrite`、`digitalRead`、`digitalPinIsValid` | 无效/未引出的稀疏编号会被拒绝；模式详见下文 |
| 时间 | `millis`、`micros`、`delay`、`delayMicroseconds` | 依赖 Timer0 和正确的 `F_CPU` |
| 全局中断 | `interrupts`、`noInterrupts` | 直接控制 EA；长时间关中断会丢失时基 tick |
| 外部中断 | `attachInterrupt`、`detachInterrupt`、`digitalPinToInterrupt` | 仅 INT0/P3.2、INT1/P3.3；仅 `LOW`、`FALLING` |
| 串口 | `Serial.begin/end/available/availableForWrite/peek/read/readBytes/write/flush/overflow` | 仅 UART1；TX 同步，通常为中断 RX；占用 Timer1 |
| 串口文本 | `print`、`println`、`printNumber`、`printlnNumber` | C 字符串和显式整数进制；没有 C++ `Print` 重载族 |
| 位/字节辅助 | `bit*`、`lowByte`、`highByte`、`makeWord` | 宏可能重复求值；参数不要带自增等副作用 |
| 数学辅助 | `min`、`max`、`abs`、`constrain`、`round`、角度换算、`sq`、`map` | 多数为宏；`map` 的零宽输入区间返回 `to_low` |
| 随机数 | `randomSeed`、`random`、`random_minmax` | 伪随机；无熵源自动播种 |
| 移位/脉宽 | `shiftIn`、`shiftOut`、`pulseIn`、`pulseInLong` | 阻塞式软件实现，精度受函数开销和中断影响 |
| I2C | Wire 软件主机，7 位地址，读写、重复起始、时钟拉伸超时 | 16 字节 TX + 16 字节 RX；无 10 位地址和从机模式 |
| SPI | SPI 软件主机，模式 0--3、MSB/LSB、字节/缓冲区传输 | 阻塞式；无硬件 DMA/中断；片选由草图控制 |
| 软件 UART | `SoftwareSerial` 同步 TX、显式 `poll()` RX、反相逻辑、16 字节缓冲 | 单全局双引脚端口、8N1；仅低速且有帧间空闲；无后台接收/PCINT/多实例；波特率须实测 |
| 字符 LCD | `LiquidCrystal`，HD44780 4/8 位、显示/光标/自定义字符/文本 | 单控制器、固定延时、单实例；无 busy flag 和双 Enable 40x4 |
| 步进电机 | `Stepper`，2/4/5 线、速度、正反向阻塞步进、释放 | 单实例；无加减速/细分/闭环；必须使用外部功率驱动 |
| SD 存储 | `SD`，SD1/SD2/SDHC 初始化、原始扇区读写、FAT16/FAT32 根目录文件读取 | 软件 SPI；单卡/单文件/单 512 字节 XDATA 缓存；仅短 8.3 和只读文件层；无 C++ `File`/`Stream`、LFN、子目录或 exFAT |
| 模拟输入 | `analogRead`、`analogReference`、`analogReadResolution`、20 个型号的逐型号 `A0...`/映射 | 默认 10 位、原生 8/10/12 位；仅 `DEFAULT`；无 ADC、无效引脚或超时返回 `-1`；实板待验证 |
| 模拟输出 | `analogWrite()` 数字阈值回退 | `<128` 为 LOW，其他为 HIGH；不是 PWM |

GPIO 模式在带 `PxM0/PxM1` 的 STC12/STC15/STC8/STC32/AI8051U 上包括
`INPUT`（高阻输入）、`INPUT_PULLUP`（准双向弱上拉）、`OUTPUT`（推挽）、
`OUTPUT_OPEN_DRAIN` 和 `OUTPUT_QUASI`。STC89 没有这些模式寄存器，只能按
经典端口行为近似：P0 为开漏释放且需要外部上拉，P1/P2/P3/P4 为准双向；
因此其 `INPUT` 与 `INPUT_PULLUP` 不能完全复现现代四模式端口的区别。

`attachInterrupt()` 对不支持的中断号、空回调以及 `CHANGE`/`RISING` 请求
直接拒绝。`digitalPinToInterrupt(P3_2)` 为 0，
`digitalPinToInterrupt(P3_3)` 为 1，其他引脚为 `NOT_AN_INTERRUPT`。

## 稀疏引脚编码

引脚值是端口和位号的直接编码：

```text
pin = (port << 4) | bit
P0_0 = 0x00
P3_2 = 0x32
P7_7 = 0x77
```

因此 `NUM_DIGITAL_PINS == 0x78`（120）表示编码空间的排他上界，不表示
芯片有 120 个 GPIO，也不表示 `0` 到 `119` 均有效。每个十六进制低半字节
的 `8`--`F` 都是空洞，未出现在具体封装上的端口位也是无效引脚。

推荐始终使用 `P3_2`、`PIN_SERIAL_RX`、`SDA`、`MOSI` 等符号，并在通用
代码中调用 `digitalPinIsValid(pin)`。`STC_NUM_LOGICAL_DIGITAL_PINS` 和
`PIN_VALID_MASK_P0` 至 `PIN_VALID_MASK_P7` 描述有效逻辑端口名；
`STC_NUM_BONDED_DIGITAL_PINS` 在已知别名去重后描述最大独立物理 GPIO，
但具体封装仍可能引出更少。`STC_VARIANT_PIN_ALIAS_GROUP_COUNT`、
`digitalPinsSharePhysicalPad()` 和 `digitalPinToPhysicalAlias()` 可查询变体
保留的别名。不要用
`for (pin = 0; pin < NUM_DIGITAL_PINS; ++pin)` 的结果推断封装能力。

端口别名还会使逻辑名数量大于独立物理 GPIO 数量。STC32CL8K64 有 19 个
逻辑端口名、17 个物理 GPIO，P1.4/P0.2 与 P1.5/P0.3 分别共用焊盘；
AI8051U-34K64 有 46 个逻辑端口名、45 个物理 GPIO，P4.4/P4.5 在封装内
硬短接且没有选择寄存器，`PIN_VALID_MASK_P5 == 0xCF`。P4.4/P4.5 中一个
作为输出时，另一个必须保持高阻，禁止驱动相反电平。Ai8H2K12U/
Ai8H2K32U 的 P1.2/P5.4 共用焊盘，变体选择 P5.4；core 启动时由
`init()` 临时置位 `P_SW2.7` 访问扩展 SFR，清零 `P_SWX1.0`，再
恢复原 `P_SW2`。这些别名不能作为独立物理引脚同时驱动。

同理，Arduino 模拟别名是枚举序号，不等于硬件 ADC 通道号或独立焊盘数。
STC32CL8K64 的 `A0 == P5_4` 对应 ADC2；`A2/A8` 分别是
P1.4/P0.2，`A3/A9` 分别是 P1.5/P0.3，因此 10 个逻辑 ADC 路由只落在
8 个独立物理焊盘上。

## 定时器、中断与 RAM 占用

| 使用者 | 固定资源 | 注意事项 |
| --- | --- | --- |
| 核心时间基准 | Timer0、中断向量 1 | 初始化后持续运行；不可再交给草图或 PWM 库 |
| `Serial` | UART1、Timer1；常规配置另用向量 4 和 RX 缓冲 | `Serial.end()` 后才能安全重用 Timer1 |
| 外部中断 API | INT0/P3.2 向量 0、INT1/P3.3 向量 2 | P3.2/P3.3 同时可能被 Wire/SPI 默认引脚占用 |
| ADC | ADC 模块和所选模拟引脚 | 不占 Timer0/Timer1；旧 P1ASF 型号改回数字用途时调用 `pinMode()` |
| Wire | SDA/SCL GPIO、16 字节 TX 和 16 字节 RX 缓冲 | 无专用定时器，但其软件延时依赖 Timer0 |
| SPI | MOSI/MISO/SCK/SS GPIO 和少量状态 | 无专用定时器，但其软件延时依赖 Timer0 |
| SoftwareSerial | 两个 GPIO、16 字节 RX 缓冲、Timer0 时间读取 | 阻塞式 TX/显式采样；`TR0`/`ET0`/`EA` 不可用时拒绝收发并置时序错误；无后台 RX |
| LiquidCrystal | 6--11 个 GPIO、17 字节状态 | 固定延时、单控制器；R/W 不作为 GPIO 使用时须接地 |
| Stepper | 2/4/5 个 GPIO、少量状态 | 阻塞并依赖 Timer0；GPIO 只接逻辑驱动级，不能直接带绕组 |
| SD | SPI 的 4 个 GPIO、单个 512 字节 XDATA 扇区缓存及 FAT/文件状态 | 至少 1 KiB XDATA；阻塞式低速访问；默认 P3.2/P3.3 与 INT0/INT1、Wire 冲突 |

Timer0 溢出标志只能表示“至少溢出一次”，不能累计多次未服务的中断。若全局
中断关闭超过约 1 ms，`millis()`/`micros()` 可能永久少计时间；调用外部中断
回调时也应保持短小。`delayMicroseconds()`、软件 Wire/SPI、SoftwareSerial、
LiquidCrystal、Stepper、SD 和 `pulseIn()`
还会受到中断延迟与 C 函数开销影响，适合普通控制通信，不应当作精密测量或
严格高速总线。

STC89 板项按官方兼容基线默认 12T 机器周期；若 ISP 把具体芯片设为 6T，
必须在开发板菜单中同步选择 `STC89 machine cycle: 6T`，否则时间和串口
波特率都会偏差。该菜单同时设置 Timer0 与 Timer1 的周期除数。

UART1 默认使用 P3.0/P3.1。`Serial.begin(baud)` 会为所选 `F_CPU` 配置
Timer1 波特率发生器；请求值超出 Timer1 可表示范围时不会改变现有配置。
发送为阻塞式。常规配置使用 16 字节中断 RX 缓冲；2 KiB 的
STC12C2052AD 以 `STC_VARIANT_SERIAL_BUFFERED_RX == 0` 选择单字节轮询缓存，
并仅接受 4800/9600/19200/38400/57600/115200 中误差不超过 3% 的速率。
`readBytes()` 只取
调用时已经到达的数据，不会像 Arduino `Stream` 那样等待超时。
STC15F104W 的官方型号定义没有 UART1，变体以
`STC_VARIANT_HAS_UART1 == 0` 明确标记；该型号的 `Serial` 调用会安全失败，
不会访问不存在的 UART/Timer1 寄存器，也不因此虚构出 UART 功能。

Wire 默认 SDA/SCL 为 P3.2/P3.3；SPI 通常默认 P3.2/P3.3/P3.4/P3.5，缺少
P3.4/P3.5 的 STC8G1K08A 回退到 P5.4/P5.5。默认引脚只是可移植起点，仍应
核对具体封装、板级连线和复用功能，必要时先调用 `Wire.setPins()` 或
`SPI.setPins()`。Wire 总线必须具备合适的外部上拉；带四模式端口的型号会
使用真正的开漏模式。STC89 的 P3 是准双向端口，不是真正开漏，要求严格
I2C 电气兼容时应把 Wire 改到 P0 的可引出脚并外接上拉，或使用外部开漏
缓冲器。

所有独立库都只在容量允许时使用，不是 2 KiB/4 KiB 型号的体积承诺。
链接器只拉入草图实际引用的库，但软件通信、显示/运动控制、时间基准和串口组合后仍可能
超过小型号 Flash；构建系统会按所选型号上限拒绝超限镜像。
SD 还会在 `STC_XDATA_BYTES < 1024` 时明确拒绝编译，因为 FAT 扇区缓存本身就需要
512 字节；支持门槛不表示 1 KiB 型号与其他缓冲、深调用栈组合后一定有足够余量。

## ADC 输入

25 个变体中有 20 个建立了经过逐型号核对的 ADC 引脚/通道表。每个支持
ADC 的变体生成 `A0...`、`NUM_ANALOG_INPUTS`、
`analogInputToDigitalPin(index)`、`digitalPinToAnalogInput(pin)` 和通道反查
宏；`A0` 表示该型号表中的第一个模拟别名，不保证其硬件通道号总是 0，例如
STC32CL8K64 的 `A0` 是 P5.4/ADC2。

`analogRead()` 默认返回 10 位结果。`analogReadResolution(bits)` 接受的
结果宽度会被限制在 1--15 位：请求位数低于原生 8/10/12 位时舍弃低位，
高于原生位数时在低位补零，因此不会凭空增加有效精度。参考源只承诺
`analogReference(DEFAULT)`；其他模式不会改动硬件。无 ADC 的
STC89C52RC、STC89C51RC、STC89C58RD+、STC15F104W、STC8C2K64S4，
以及任何非法或不具备 ADC 通道的引脚，`analogRead()` 都返回 `-1`；转换
超时同样返回 `-1`。

公共实现使用四种明确的寄存器布局，而不是假定所有“现代 STC”都相同：

| 布局 | 对应型号/系列 | 关键差异 |
| --- | --- | --- |
| STC12C2052AD 8 位专用布局 | STC12C2052AD | `ADC_CONTR=0xC5`、`ADC_DATA=0xC6`，8 位结果 |
| 旧式 `AUXR1` 对齐布局 | STC12C5A60S2 | `ADC_RES/ADC_RESL`，`AUXR1` 选择 10 位对齐 |
| 旧式 `CLK_DIV` 对齐布局 | STC15F2K60S2、STC15W408AS、STC15W4K32S4 | 旧式 START/FLAG 位，`CLK_DIV` 选择 10 位对齐 |
| 现代 `ADCCFG` 布局 | 其余已启用 ADC 的 STC8、STC32、AI8051U、Ai8H 型号 | 现代 START/FLAG 位，`ADCCFG` 配置右对齐和 ADC 时钟 |

旧式 P1 ADC 型号在读取时设置模拟功能选择位；随后对同一引脚调用
`pinMode()` 会清除该选择位并恢复数字 GPIO。ADC 引脚、参考电压、采样源
阻抗和封装焊盘仍必须在目标板上测量；编译/链接通过不代表 ADC 已经实板
验证。

## 明确未宣称的能力

- **PWM / 真正的模拟输出**：尚无逐型号 PWM/CCP/PCA 通道和端口重映射元
  数据，而且 Timer0 已被时基占用、Timer1 可能被 UART1 占用。
  `digitalPinHasPWM()` 始终为假；`analogWrite()` 只有数字阈值回退。
- **EEPROM / IAP**：STC 的 IAP 擦写 Flash 需要按具体型号确定扇区、等待时
  序和命令，并必须在链接布局中预留不会被程序覆盖的数据区，还要处理擦写
  寿命和掉电一致性。在这些约束进入链接脚本和变体元数据前，不提供假装安全
  的 EEPROM API。
- **USB**：只有部分 U 型号具备 USB，且需要逐型号验证时钟、引脚、端点、
  描述符、启动流程以及所用 SDK 代码的许可证。当前没有通用 `USB`、CDC、
  HID 或 Host API。
- **其他外设**：硬件 I2C/SPI、多 UART、CAN、DAC、比较器、RTC、DMA 等尚
  未形成跨型号 Arduino API；现有 Wire/SPI 是软件主机实现。
- **Arduino C++ 基础设施**：没有 `String`、`Print`、`Stream`、动态 C++
  对象、异常、RTTI 和标准 C++ Arduino 库生态；`tone`/`noTone`、Servo、
  EEPROM、USB 等标准库也尚未提供。

Arduino AVR 随包库以及 `LiquidCrystal`、`Stepper`、`SD` 等常用独立库的逐项对照、
现有 plain-C API 和未实现原因见
[`library-compatibility.md`](library-compatibility.md)。

这些边界用于防止“能编译”被误认为“已按目标芯片正确连接并验证”。后续新增
硬件能力时，应先把官方型号/封装映射、SFR 和资源冲突写入变体元数据，再补充
真实硬件测试；不应以静默 no-op 作为支持证明。当前 ADC 也仍需按
[`hardware-validation.md`](hardware-validation.md) 完成实板验证，不能把生成
HEX 当作电气和采样正确性的证据。

## 使用前检查

1. 选择精确型号板项，另行核对芯片丝印和实际封装，并确认 `F_CPU` 与实际
   ISP/时钟选项一致。
2. 用 `digitalPinIsValid()` 和具体变体的引脚掩码核对 GPIO，不要把稀疏编码
   当作连续 Arduino 板号。
3. 规划 Timer0、Timer1、INT0/INT1 与各软件库 GPIO 的冲突。
4. 为 Wire 配置外部上拉；对软件总线、软件串口和时间 API 在目标板上实测容差。
5. ADC 只连接到变体声明的 `A0...` 引脚，仅使用 `DEFAULT` 参考模式，并在
   实板核对输入范围、原生分辨率和通道映射。
6. 仅把本表中明确支持的 API 当作承诺；对 PWM/IAP/USB 等尚未支持的能力
   使用 STC 官方资料逐型号实现和验证。
