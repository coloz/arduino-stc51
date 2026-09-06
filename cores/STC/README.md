# Unified STC core

这里是 22 个已纳入目标集合的 STC 8051/251 型号共用 clean-room Arduino-C 核心。STC8、
Ai8H 以及 AI8051U 兼容模式使用 SDCC `mcs51` 后端；STC32
以及显式选择该模式的 AI8051U 使用实验性的 `mcs251` 后端。

默认构建不是 AVR Arduino Core 的 C++ 移植；plain-C profile 把 `.ino` 草图作为 C 编译，
提供 Wiring 风格函数以及由函数指针表组成的 `Serial`、`Wire`、`SPI`、
`SoftwareSerial`、`LiquidCrystal`、`Stepper` 对象，例如
`Serial.begin(9600UL)`、`Wire.begin()` 和 `SPI.transfer(value)`。Arduino
C++ 的类继承、重载、模板以及依赖这些接口的库在该默认 profile 中不具备源码
兼容性；需要改用本核心公开的 plain-C 接口。

`cpp/` 中另有 opt-in 的实验性 C++11 类层和运行时，包括 `String`、`Print`、
`Stream`、`HardwareSerial`、`SPIClass`、`TwoWire`、`IPAddress`、`Client`、
`Server`、`UDP`、构造器、静态 guard 和 `new/delete`；`libraries/SD` 另提供
继承 `Stream` 的只读 `File` 与 `SDClass`。它为 22 个物理型号、25 个 MCS51/MCS251
执行配置的 12 MHz profile 接入 Arduino CLI，必须显式选择 `cppcore=enabled`；
默认仍为 plain-C。双目标 frontend/ABI/bridge 已接通，最终 clean compile/link/
capacity 与逐配置精确 QEMU 使用 25-profile/31-workload 的机器可读资格合同：
6 个 compact profile 各跑 `runtime`/`io`，其余 19 个各跑 `full`。其中
AI8051U-34K16 的两个 compact profile 上限为 14,336 字节；STC32F12K54 的
4 KiB XDATA 固定为 3,584 字节 heap 加 512 字节静态 reserve。当前 outcome
不嵌入本平台文档，只以 `tests/cpp/variant-matrix/results.json` 为准。状态仍是
**EXPERIMENTAL / NOT_SUPPORTED**，不得扩大为其他芯片 runtime、实板或第三方库总体结论。

锁定 QEMU 提交 `faeac38c0076795d7b4e59f0ddcb5fc7e7bd7015` 已提供 14 个
MCS51 与 11 个 MCS251 精确 machine。最终 25-profile/31-workload clean run 正在
重新生成；machine 存在、编译成功或历史 17/18 结果都不能单独声明 runtime PASS。

C++ profile 还提供供常见模板源码使用的最小 freestanding 头集合，以及
`F()`/`PSTR()`/`PROGMEM`/`pgm_read_*` 源码兼容名。当前实验 profile 把这类常量
当普通数据访问；`String`/`Print` 也能接收外部库产生的
`const __FlashStringHelper *`，但仍把它当普通 data pointer 读取。以上能力不能据此
声称常量位于独立 code 空间或节省 RAM；异常、RTTI、线程安全静态初始化、完整
STL/libstdc++ 和全局析构均不支持。`WCharacter.h`、`binary.h` 与 `WProgram.h`
分别提供字符辅助、旧式 `Bxxxxxxxx` 常量和 pre-1.0 include 入口的源码兼容层。

## 当前实现

- GPIO：`pinMode`、`digitalWrite`、`digitalRead`、`digitalPinIsValid`，并提供
  `INPUT`、`INPUT_PULLUP`、`OUTPUT`、`OUTPUT_OPEN_DRAIN`、
  `OUTPUT_QUASI`。当前所有变体使用带 `PxM0/PxM1` 的四模式 GPIO。
- 时间：`millis`、`micros`、`delay`、`delayMicroseconds`、`yield`、
  `interrupts`、`noInterrupts`。Timer0 是核心永久占用的 1 ms 时基。
- 外部中断：`attachInterrupt`、`detachInterrupt` 只对应 INT0/P3.2 和
  INT1/P3.3，只接受 `LOW` 与 `FALLING`；`CHANGE`、`RISING` 不会被静默
  映射为错误的触发方式。
- 通用辅助：`shiftIn`、`shiftOut`、`pulseIn`、`pulseInLong`、随机数、
  `map`、位操作和常用数学宏；C++ 的两个脉宽函数默认 timeout 均为 1 秒，
  plain C 调用必须显式传入 timeout。
- UART1：同步发送、带 16 字节接收中断缓冲的 `Serial`，同时保留
  `Serial_*` 函数接口；启用 UART1 时占用 Timer1。
- ADC：22 个型号中的 21 个具有逐型号模拟引脚/通道表和原生 10/12 位
  读取实现。`analogRead()` 默认返回 Arduino 常用的 10 位结果，
  `analogReadResolution()` 可选择 1--15 位结果宽度；参考模式仅支持
  `DEFAULT`。
- `Wire`：独立库中的软件 I2C 7 位地址主机，支持时钟拉伸超时、重复起始
  和 16 字节收发缓冲；不是硬件 I2C，也不提供从机回调。
- `SPI`：独立库中的软件 SPI 主机，支持模式 0--3、MSB/LSB 顺序、单字节
  与缓冲区全双工传输；C++ `setClockDivider(SPI_CLOCK_DIVn)` 把常量当作
  `F_CPU / n` 的比值请求而非 AVR 寄存器编码，attach/detach interrupt 仅为
  no-op 兼容入口；片选由草图控制。
- `SoftwareSerial`：独立库中的实验性单端口软件 UART，面向低速、有帧间空闲的
  同步发送与显式轮询接收；C++ profile 有引脚构造器并继承 `Stream`，但所有对象
  仍共享一个活动后端。最后一次成功 `begin()`/`listen()` 的对象拥有该后端；非活动
  对象不会读写、查询或关闭当前拥有者，失败的切换也保留原拥有者。不具备 AVR
  PCINT 后台接收或同时多实例语义。
- `LiquidCrystal`：单控制器 HD44780 兼容字符屏的 4/8 位并口驱动；
  `Stepper`：单电机 2/4/5 线阻塞式 GPIO 驱动，C++ `version()` 返回兼容值 `5`。
- `SD`：软件 SPI 上的 SD1/SD2/SDHC，支持原始 512 字节扇区读写，以及
  FAT16/FAT32 根目录短 8.3 文件读取、创建、追加、覆盖、flush 和 remove；不支持
  子目录或目录遍历，需至少 1 KiB XDATA，建议 8 KiB。

以上列表首先描述默认 plain-C 层。实验 C++ profile 复用相同 HAL；`SPIClass`、
`TwoWire` 和受限 `File`/`SDClass` 不会把软件总线、电气行为、存储介质行为或
掉电一致性提升为新的硬件承诺。

引脚采用稳定但稀疏的 `(port << 4) | bit` 编码，例如 `P3_2 == 0x32`。
`NUM_DIGITAL_PINS` 是编码空间上界 184，不是封装引脚数，也不能据此假定
中间编号连续有效。应使用 `P0_0`...`PB_7` 名称和
`digitalPinIsValid()`；具体变体另提供
`STC_NUM_LOGICAL_DIGITAL_PINS`、`STC_NUM_BONDED_DIGITAL_PINS` 与各端口
`PIN_VALID_MASK_Px`。前者和端口掩码描述有效逻辑端口名，后者在已知别名
去重后统计最大独立物理 GPIO；具体封装仍可能引出更少。变体还提供
`STC_VARIANT_PIN_ALIAS_GROUP_COUNT`、`digitalPinsSharePhysicalPad()` 和
`digitalPinToPhysicalAlias()` 以查询保留的别名。

STC32CL8K64 有 19 个逻辑端口名、17 个物理 GPIO，其中 P1.4/P0.2、
P1.5/P0.3 分别共用焊盘。AI8051U-34K64 有 46 个逻辑端口名、45 个物理
GPIO，P4.4/P4.5 在封装内硬短接且没有选择寄存器，P5 有效掩码为
`0xCF`；若其中一个别名作为输出，另一个必须保持高阻，禁止驱动相反电平。
Ai8H2K12U 与 Ai8H2K32U 的 P1.2/P5.4 共用焊盘；变体只暴露 P5.4，
`init()` 在 core 启动阶段临时置位 `P_SW2.7` 访问扩展 SFR，清零
`P_SWX1.0` 选择 P5.4，再恢复原 `P_SW2`。任何别名对都不能当作两个独立
推挽输出使用。

STC32G144K246 暴露 P0--P9、PA、PB 共 92 个逻辑端口名和 91 个独立物理
GPIO；P1.2/P5.4 只保留规范名 P5.4，P1.3/P1.7 是同一物理焊盘的两个逻辑名。
P8--PB 通过 XFR 访问，并在 core 初始化时使能 EAXFR；这条路径必须与
`0xFC2800`--`0xFFFFFF` 用户 Flash 高地址布局、复位入口和中断栈一起单独
验证，不能由普通低端口编译探针代替。

该芯片有 251,904 字节物理用户 Flash。当前 SDCC/ASlink 把普通代码从
`0xFC2800` 连续向上放置，并把复位 HOME/IVT 固定在 `0xFF0000`，所以板定义只
公开 HOME 前的 186,368 字节连续代码区，暂留其上 64 KiB。构建矩阵会解析 HEX，
检查复位跳板、INT0、Timer0、INT1、UART1 和未占用 Timer1 的入口；恢复完整物理
容量仍需要可验证的分区链接与跨段重定位。历史 K246 QEMU canary 已验证其当时固件的
CPU、内存、UART1、Timer0/1 和 P0--P7 路径，但该历史结果不属于正在重新生成的
25-profile/31-workload outcome；模型也不覆盖 P8--PB、ADC、PLL、电气行为
或 cycle-exact 时序，也不能替代实板运行。

## 资源和边界

- Timer0 及其中断向量 1 由系统时基占用；重配 Timer0 会破坏所有时间 API，
  软件 Wire/SPI、SoftwareSerial、LiquidCrystal 和 Stepper 的延时也会随之
  失效。关闭全局中断超过一个 Timer0 周期会
  丢失累计 tick，因此不要把 `noInterrupts()` 区间维持到毫秒量级。
- `Serial.begin()` 运行期间 UART1 占用 Timer1；常规缓冲配置另占 UART1
  中断向量 4。草图或其他库不能同时把 Timer1 用于 PWM、计时或其他波特率
  发生器。
- Wire 在四模式端口上使用开漏 GPIO，并为 TX/RX 各保留 16 字节数据 RAM；
  SPI 与 Wire 均为阻塞式软件实现，`setClock`/
  `beginTransaction` 的频率是目标值；SPI `setClockDivider()` 也只是把 divisor
  换算为目标值，不是经硬件分频保证的精确总线频率。
- 各独立库不承诺能装入所有小容量型号；软件总线、显示、运动控制与其他 API 组合后的
  最终体积由所选芯片的链接上限检查。
- 核心不选择或校准系统时钟。烧录配置、熔丝/选项字和板上振荡源必须与
  `F_CPU` 一致，所有时间与波特率结果才有意义。
ADC 使用 STC8/STC32/AI/Ai8 的现代 `ADCCFG` 布局。变体生成 `A0...`、
`NUM_ANALOG_INPUTS`、
`analogInputToDigitalPin()` 与通道反查宏，避免把一组连续通道假设套到所有
封装。无 ADC 的 STC8C2K64S4 以及非法/非 ADC 引脚调用 `analogRead()` 都返回
`-1`；转换超时也返回 `-1`。`analogReference()` 仅承诺 `DEFAULT`，其他
模式不会改动硬件。

STC32G144K246 当前 Arduino 映射只暴露 ADC1 的外部通道 0--10；ADC2 和内部
参考通道未纳入 `analogRead()`。core 也不会配置该型号的 PLL，板菜单的
  `F_CPU` 必须与实际时钟一致；无论机器可读 QEMU outcome 为何，其范围都不覆盖
  ADC2、PLL 或模拟行为。

`analogWrite()` 仍仅按 128 阈值回退为数字 LOW/HIGH，不代表 PWM，
`digitalPinHasPWM()` 始终为假。读取分辨率扩展只会补零，缩减则丢弃低位，
不会增加 ADC 的实际精度。

EEPROM/IAP、USB、CAN、DAC、硬件 I2C/SPI、多串口、`tone` 和 `Servo` 也
未声明为核心能力。尤其 EEPROM 仿真必须先为 IAP 划定不会被链接器代码占用
的 Flash 区域并定义擦写/掉电策略；USB 还需要逐型号时钟、引脚、端点和描述
符配置。当前没有满足这些安全前提，因此不提供占位 API。

完整接口矩阵和迁移注意事项见
[`../../docs/core-api-compatibility.md`](../../docs/core-api-compatibility.md)。
库级 Arduino AVR 对照、API 与限制见
[`../../docs/library-compatibility.md`](../../docs/library-compatibility.md)。
编译/链接覆盖与逐型号实板状态分别记录在
[`../../docs/hardware-validation.md`](../../docs/hardware-validation.md)；生成
HEX 不等于对应封装、电压、时钟和外设已经在实板通过。
下载的 STC 官方 SDK 只作为行为核对依据，未复制进本核心；若应用直接集成
SDK 外设代码，应独立检查许可证、目标型号、SFR 定义及与 Timer0/Timer1 的
资源冲突。
