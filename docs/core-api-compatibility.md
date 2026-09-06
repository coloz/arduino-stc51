# Arduino Core API 兼容性说明

本文说明 `arduino-stc51` 当前统一核心所承诺的兼容范围。默认兼容层是 Wiring
风格的 **plain C API**，不是 Arduino AVR/SAMD/ESP 等 C++ Core 的二进制或完整
源码兼容。仓库另有覆盖 MCS51/MCS251、22 个物理型号和 25 个执行配置的
12 MHz opt-in C++11 profile；它们是
**EXPERIMENTAL / NOT_SUPPORTED**，本页不会把它的结果扩大为默认平台、其他
芯片、实板或广泛第三方库承诺。

2026-09-06 的库扩展改动与分层验证见
[`cpp-library-expansion-plan.md`](cpp-library-expansion-plan.md) 和
[`library-compatibility.md`](library-compatibility.md)。旧矩阵 PASS 仅属于其绑定的源码快照，
不能作为修改后的 SDK 已完成全量验证的证明。

## 编译模型与对象式语法

SDCC 的 8051 前端不提供本项目所需的 Arduino C++ 语言支持，因此默认构建将
`.ino` 作为 C 编译。草图仍使用 `setup(void)` 和 `loop(void)`，但应遵守 C
语法：不能使用类、继承、构造函数、重载、模板、引用、命名空间或 lambda。

实验 profile 使用 Clang C++11→LLVM Bitcode 整程序链接→受控 LLVM-CBE→补丁
SDCC，并通过 `platform.txt`/Arduino CLI 的显式选项启用：

```text
arduino-stc51:mcs51:stc32g144k246:cppcore=enabled,clock=12m
```

双目标 frontend、逐 TU bitcode、core archive/sidecar 选择、最终整程序 bridge 和
HEX 生成路径均已接通；MCS51 与 MCS251 分别锁定 16/24 位代码指针、2/3 字节
数据成员指针和 4/6 字节成员函数指针。资格矩阵固定为 22 个物理型号、25 个
执行 profile（14 MCS51 + 11 MCS251）和 31 个 workload：6 个 compact profile
各用独立 `runtime`/`io` 固件，19 个 full profile 各用一个 `full` 固件。每个结果
都必须绑定 workload source set、当次 build manifest、工具审计和固件 SHA-256，
不能复用旧 digest；当前归一化 outcome 只在 `tests/cpp/variant-matrix/*.json`，原始
保留证据位于 `tests/qemu/results/`，平台包文档不复制结论。
这仍不是异常、RTTI、完整 STL、全部地址空间、全部 ABI 边缘、广泛第三方库或
实板的合格证据。QEMU 源提交 `faeac38c0076795d7b4e59f0ddcb5fc7e7bd7015`
虽然为 25 个执行配置提供精确 machine，但 model
存在本身不等于 runtime PASS；禁止用 machine alias 或历史 K246 canary 补齐结果。
最终 clean run 正在重新生成，结果只能由相互哈希绑定的权威 JSON 声明。

AI8051U-34K16 的 MCS51/MCS251 两个 profile 均使用 compact 合同，程序上限为
14,336 字节。STC32F12K54 的 MCS251 profile 使用 3,584 字节 heap，并为其他
静态 XDATA 保留 512 字节预算；它仍属于 19 个 full profile，但不得超过总计
4 KiB XDATA 的链接边界。

在以下 plain-C 示例中，`Serial`、`Wire`、`SPI`、`SoftwareSerial`、
`LiquidCrystal`、`Stepper` 和 `SD` 是
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

在默认 profile 中，这只是 C 结构体成员调用，不是 `HardwareSerial`、`TwoWire` 或 `SPIClass` C++
对象。没有 Arduino C++ 的默认参数和重载，例如数值输出应使用
`Serial.printNumber(value, DEC)`，两参数随机数应使用
`random_minmax(lower, upper)`。依赖 `String`、`Print`、`Stream`、
`Printable` 或 C++ 回调对象的第三方 Arduino 库必须先移植，不能仅靠改
头文件名直接编译。

每个对象也有等价的函数前缀接口，例如 `Serial_begin()`、`Wire_write()`、
`SPI_transfer()`、`SoftwareSerial_poll()`；在需要明确控制链接内容或调试调用
路径时可直接使用。

实验 C++ profile 则提供真实类接口：`String`、`Printable`、`Print`、`Stream`、
`HardwareSerial`、`SPISettings`/`SPIClass`、`TwoWire`、`IPAddress`、`Client`、
`Server`、`UDP`，以及随库提供的 `SoftwareSerial : Stream`、`LiquidCrystal`、
`Stepper` 和受限读写 `File`/`SDClass`。网络四个类只是 Arduino 公共抽象，不包含
Ethernet/WiFi 协议或硬件驱动；SD C++ 层仍受根目录短 8.3、单活动文件限制。
`WCharacter.h` 提供基于 `ctype` 的 Arduino 字符分类/大小写辅助，`binary.h`
提供 `B0` 到 `B11111111` 的旧式二进制常量，`WProgram.h` 是包含 `Arduino.h`
的 pre-1.0 源码兼容入口；这些头文件不改变 ABI 或增加对应硬件能力。

`F()`/`PSTR()`/`PROGMEM` 当前是普通数据访问兼容层，不提供 AVR 式独立 Flash
地址空间或 RAM 节省承诺。`STCXX_FLASH_STRINGS=0` 时，`String`/`Print` 仍接受
第三方库返回的 `const __FlashStringHelper *`（例如 ArduinoJson 的 `f_str()`），
但按普通 data pointer 读取；这是源码兼容回退，不是 Flash/RAM 优化证明。

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
| C++ `<math.h>` / `<cmath>` | 21 个 SDCC `*f` 函数及 Core 实现的 `fmodf`、`roundf`、`truncf`；同时提供对应无后缀名称 | 仅 opt-in C++ profile；该 ABI 的 `double` 与 `float` 均为 binary32，无后缀声明直接绑定同一 `*f` 符号，不提供 64 位 double 精度 |
| 随机数 | `randomSeed`、`random`、`random_minmax` | 伪随机；无熵源自动播种 |
| 移位/脉宽 | `shiftIn`、`shiftOut`、`pulseIn`、`pulseInLong`；C++ 两个脉宽函数的默认 timeout 均为 1,000,000 us | 阻塞式软件实现，精度受函数开销和中断影响；plain C 必须显式传 timeout |
| I2C | Wire 软件主机，7 位地址、重复起始、内部地址读取、timeout flag/reset | 默认 32 字节 TX + RX（各），可显式缩小；无 10 位地址和从机模式 |
| SPI | 软件主机、模式 0--3、MSB/LSB、缓冲传输、`SPISettings`；事务中断保护 | `using/notUsingInterrupt` 注册保存/屏蔽/恢复规则；不是递归锁。分频值请求 `F_CPU / n`，非 AVR 寄存器值；无硬件 DMA/传输完成中断，attach/detach 仍为兼容 no-op；片选由草图控制 |
| 软件 UART | `SoftwareSerial : Stream`，同步 TX、`available/peek/read` 自动轮询 RX、反相逻辑 | 一个活动监听者；默认 64 字节 RX，低内存 16 字节；无后台接收/PCINT，必须频繁服务。非活动对象不能关闭当前拥有者；失败切换保留原拥有者；仅低速有帧间空闲，波特率须实测 |
| 字符 LCD | `LiquidCrystal`，HD44780 4/8 位、显示/光标/自定义字符/文本及 public `init(...)`/`setRowOffsets(...)` | C++ 每实例独立状态和行偏移；构造器仅记录引脚，需在 Core 启动后 `begin`/`init`；固定延时，无 busy flag 和双 Enable 40x4 |
| 步进电机 | `Stepper`，2/4/5 线、速度、正反向阻塞步进、释放；C++ `version()` 为 `5` | C++ 每实例独立引脚/相位/速度；无加减速/细分/闭环，须外部功率驱动 |
| SD 存储 | SD1/SD2/SDHC、FAT16/32 根目录 8.3 文件 read/create/append/overwrite/flush/remove | 软件 SPI；单卡/单活动文件/单 512 字节缓存；无 LFN、子目录/遍历、exFAT 和掉电原子性；`begin(clock, cs)` 当前忽略 clock |
| 模拟输入 | `analogRead`、`analogReference`、`analogReadResolution`、21 个型号的逐型号 `A0...`/映射 | 默认 10 位、原生 10/12 位；仅 `DEFAULT`；无 ADC、无效引脚或超时返回 `-1`；实板待验证 |
| 模拟输出 | `analogWrite()` 数字阈值回退 | `<128` 为 LOW，其他为 HIGH；不是 PWM |

数学兼容测试分层记录：host 行为测试以 301,092 个固定边界和伪随机用例核对
Core 自身的 `fmodf`、`roundf`、`truncf`，包括 NaN、无穷、正负零、子正规数以及
`x / y` 会溢出的余数用例；双目标 frontend/backend 测试只证明无后缀名称被翻译为
现有 `*f` 符号，并且生成 C 可由 MCS51/MCS251 SDCC 编译。SDCC 随附的其余 21 个
`*f` 实现本轮只核对了头文件、归档符号和链接边界，尚未逐函数做数值精度或实板验证；
host 的系统 libm 结果也不能替代目标库运行证据。

当前 STC8、STC32、AI8051U 和 Ai8H 变体均带 `PxM0/PxM1`，GPIO 模式包括
`INPUT`（高阻输入）、`INPUT_PULLUP`、`OUTPUT`（推挽）、
`OUTPUT_OPEN_DRAIN` 和 `OUTPUT_QUASI`。多数型号的 `INPUT_PULLUP` 使用准双向
弱上拉；STC32G144K246 使用独立 `PxPU` XFR 保持高阻输入并使能上拉。

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
PB_7 = 0xB7
```

因此 `NUM_DIGITAL_PINS == 0xB8`（184）表示编码空间的排他上界，不表示
芯片有 184 个 GPIO，也不表示 `0` 到 `183` 均有效。每个十六进制低半字节
的 `8`--`F` 都是空洞，未出现在具体封装上的端口位也是无效引脚。

推荐始终使用 `P3_2`、`PIN_SERIAL_RX`、`SDA`、`MOSI` 等符号，并在通用
代码中调用 `digitalPinIsValid(pin)`。`STC_NUM_LOGICAL_DIGITAL_PINS` 和
`PIN_VALID_MASK_P0` 至 `PIN_VALID_MASK_PB` 描述有效逻辑端口名；
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

STC32G144K246 使用 P0--P9、PA、PB，暴露 92 个逻辑端口名和 91 个独立物理
GPIO。P1.2/P5.4 只保留规范名 P5.4；P1.3/P1.7 共用焊盘，不能同时作为独立
推挽输出。P8--PB 通过 XFR 访问，必须专门验证 EAXFR 使能、输入/输出、模式、
上拉和 SETB/CLRB 路径。

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
| ADC | ADC 模块和所选模拟引脚 | 不占 Timer0/Timer1；改回数字用途时调用 `pinMode()` |
| Wire | SDA/SCL GPIO、默认 32 字节 TX 和 RX 缓冲（可配置） | 无专用定时器，但其软件延时依赖 Timer0 |
| SPI | MOSI/MISO/SCK/SS GPIO 和少量状态 | 无专用定时器，但其软件延时依赖 Timer0 |
| SoftwareSerial | 两个 GPIO、默认 64 字节 RX（低内存 16）、Timer0 | 阻塞式 TX/自动服务轮询采样；`TR0`/`ET0`/`EA` 不可用时拒绝收发并置时序错误；无后台 RX |
| LiquidCrystal | 6--11 个 GPIO、17 字节状态 | 固定延时、单控制器；R/W 不作为 GPIO 使用时须接地 |
| Stepper | 2/4/5 个 GPIO、少量状态 | 阻塞并依赖 Timer0；GPIO 只接逻辑驱动级，不能直接带绕组 |
| SD | SPI 的 4 个 GPIO、单个 512 字节 XDATA 扇区缓存及 FAT/文件状态 | 至少 1 KiB XDATA；阻塞式低速访问；默认 P3.2/P3.3 与 INT0/INT1、Wire 冲突 |

Timer0 溢出标志只能表示“至少溢出一次”，不能累计多次未服务的中断。若全局
中断关闭超过约 1 ms，`millis()`/`micros()` 可能永久少计时间；调用外部中断
回调时也应保持短小。`delayMicroseconds()`、软件 Wire/SPI、SoftwareSerial、
LiquidCrystal、Stepper、SD 和 `pulseIn()`
还会受到中断延迟与 C 函数开销影响，适合普通控制通信，不应当作精密测量或
严格高速总线。

UART1 默认使用 P3.0/P3.1。`Serial.begin(baud)` 会为所选 `F_CPU` 配置
Timer1 波特率发生器；请求值超出 Timer1 可表示范围时不会改变现有配置。
发送为阻塞式，接收使用 16 字节中断 RX 缓冲。plain-C 函数表的
`Serial.readBytes()`/`Serial_readBytes()` 只取调用时已经到达的数据，不等待；
实验 C++ profile 的 `HardwareSerial : Stream` 则使用
`Stream::readBytes()`，按默认 1000 ms 或 `setTimeout()` 设置的值等待，直到读满
请求长度或超时。两者共享同一个 16 字节 HAL 缓冲，但阻塞语义不同。

Wire 默认 SDA/SCL 为 P3.2/P3.3；SPI 通常默认 P3.2/P3.3/P3.4/P3.5，缺少
P3.4/P3.5 的 STC8G1K08A 回退到 P5.4/P5.5。默认引脚只是可移植起点，仍应
核对具体封装、板级连线和复用功能，必要时先调用 `Wire.setPins()` 或
`SPI.setPins()`。Wire 总线必须具备合适的外部上拉；带四模式端口的型号会
使用真正的开漏模式。

所有独立库都只在容量允许时使用，不承诺能装入全部小容量型号。
链接器只拉入草图实际引用的库，但软件通信、显示/运动控制、时间基准和串口组合后仍可能
超过小型号 Flash；构建系统会按所选型号上限拒绝超限镜像。
SD 还会在 `STC_XDATA_BYTES < 1024` 时明确拒绝编译，因为 FAT 扇区缓存本身就需要
512 字节；支持门槛不表示 1 KiB 型号与其他缓冲、深调用栈组合后一定有足够余量。

## ADC 输入

22 个变体中有 21 个建立了经过逐型号核对的 ADC 引脚/通道表。每个支持
ADC 的变体生成 `A0...`、`NUM_ANALOG_INPUTS`、
`analogInputToDigitalPin(index)`、`digitalPinToAnalogInput(pin)` 和通道反查
宏；`A0` 表示该型号表中的第一个模拟别名，不保证其硬件通道号总是 0，例如
STC32CL8K64 的 `A0` 是 P5.4/ADC2。

`analogRead()` 默认返回 10 位结果。`analogReadResolution(bits)` 接受的
结果宽度会被限制在 1--15 位：请求位数低于原生 10/12 位时舍弃低位，
高于原生位数时在低位补零，因此不会凭空增加有效精度。参考源只承诺
`analogReference(DEFAULT)`；其他模式不会改动硬件。无 ADC 的
STC8C2K64S4 以及任何非法或不具备 ADC 通道的引脚，`analogRead()` 都返回 `-1`；转换
超时同样返回 `-1`。

当前变体使用现代 `ADCCFG` 寄存器布局：

| 布局 | 对应型号/系列 | 关键差异 |
| --- | --- | --- |
| 现代 `ADCCFG` 布局 | 已启用 ADC 的 STC8、STC32、AI8051U、Ai8H 型号 | 现代 START/FLAG 位，`ADCCFG` 配置右对齐和 ADC 时钟 |

STC32G144K246 当前只把 ADC1 外部通道 0--10 映射为 `A0...A10`；ADC2 和
内部参考通道没有 Arduino 映射。该型号的 PLL 也未由 core 配置或公开控制 API。
P8--PB XFR、高地址链接/复位入口、ADC1 映射和时基必须分别留存门禁证据；
CoreAPI 编译成功不等于 QEMU 或实板运行通过。

ADC 引脚、参考电压、采样源
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
- **Arduino C++ 基础设施**：MCS51/MCS251 的 25 个 12 MHz 显式 Arduino CLI profile 已实现
  `String`、`Print`、`Stream`、`HardwareSerial`、`SPIClass`、`TwoWire`、网络
  抽象、受限读写 SD 类层和最小动态对象/构造器运行时。全配置资格采用统一嵌套
  `workloads[]`：6 compact×2 加 19 full×1，共 31 个；当前 compile/link/capacity
  与精确 QEMU outcome 只读取机器可读矩阵。它不是默认 profile；异常、RTTI、
  完整 STL、真正 Flash 字符串地址空间和标准 C++ Arduino 库生态仍未获得总体支持。
  `tone`/`noTone`、Servo、EEPROM、USB 等也尚未提供。实施顺序见
  [`cpp-core-implementation-plan.md`](cpp-core-implementation-plan.md)。

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
