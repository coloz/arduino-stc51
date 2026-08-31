# Unified STC core

这里是 25 个已支持 STC 8051/251 型号共用的 clean-room Arduino-C 核心。STC89、
STC12、STC15、STC8 以及 AI8051U 兼容模式使用 SDCC `mcs51` 后端；STC32
以及显式选择该模式的 AI8051U 使用实验性的 `mcs251` 后端。

这不是 AVR Arduino Core 的 C++ 移植。构建系统把 `.ino` 草图作为 C 编译，
提供 Wiring 风格函数以及由函数指针表组成的 `Serial`、`Wire`、`SPI`、
`SoftwareSerial`、`LiquidCrystal`、`Stepper` 对象，例如
`Serial.begin(9600UL)`、`Wire.begin()` 和 `SPI.transfer(value)`。Arduino
C++ 的类继承、重载、模板、`String`、`Print`、`Stream` 以及依赖它们的库不
具备源码兼容性；需要改用本核心公开的 plain-C 接口。

## 当前实现

- GPIO：`pinMode`、`digitalWrite`、`digitalRead`、`digitalPinIsValid`，并提供
  `INPUT`、`INPUT_PULLUP`、`OUTPUT`、`OUTPUT_OPEN_DRAIN`、
  `OUTPUT_QUASI`。带 `PxM0/PxM1` 的系列使用四模式 GPIO；STC89 按经典准
  双向端口处理。
- 时间：`millis`、`micros`、`delay`、`delayMicroseconds`、`yield`、
  `interrupts`、`noInterrupts`。Timer0 是核心永久占用的 1 ms 时基。
- 外部中断：`attachInterrupt`、`detachInterrupt` 只对应 INT0/P3.2 和
  INT1/P3.3，只接受 `LOW` 与 `FALLING`；`CHANGE`、`RISING` 不会被静默
  映射为错误的触发方式。
- 通用辅助：`shiftIn`、`shiftOut`、`pulseIn`、`pulseInLong`、随机数、
  `map`、位操作和常用数学宏。
- UART1：同步发送、常规配置带 16 字节接收中断缓冲的 `Serial`，同时保留
  `Serial_*` 函数接口。2 KiB STC12C2052AD 使用单字节轮询接收以控制体积；
  启用 UART1 时占用 Timer1。STC15F104W 本身没有 UART1，其 `Serial` 为
  不访问硬件的安全失败接口。
- ADC：25 个型号中的 20 个具有逐型号模拟引脚/通道表和原生 8/10/12 位
  读取实现。`analogRead()` 默认返回 Arduino 常用的 10 位结果，
  `analogReadResolution()` 可选择 1--15 位结果宽度；参考模式仅支持
  `DEFAULT`。
- `Wire`：独立库中的软件 I2C 7 位地址主机，支持时钟拉伸超时、重复起始
  和 16 字节收发缓冲；不是硬件 I2C，也不提供从机回调。
- `SPI`：独立库中的软件 SPI 主机，支持模式 0--3、MSB/LSB 顺序、单字节
  与缓冲区全双工传输；片选由草图控制。
- `SoftwareSerial`：独立库中的实验性单端口软件 UART，面向低速、有帧间空闲的
  同步发送与显式轮询接收；不具备 AVR PCINT 后台接收或多个 C++ 实例语义。
- `LiquidCrystal`：单控制器 HD44780 兼容字符屏的 4/8 位并口驱动；
  `Stepper`：单电机 2/4/5 线阻塞式 GPIO 驱动。
- `SD`：软件 SPI 上的 SD1/SD2/SDHC，支持原始 512 字节扇区读写，以及
  FAT16/FAT32 根目录短 8.3 文件只读；需至少 1 KiB XDATA，建议 8 KiB。

引脚采用稳定但稀疏的 `(port << 4) | bit` 编码，例如 `P3_2 == 0x32`。
`NUM_DIGITAL_PINS` 是编码空间上界 120，不是封装引脚数，也不能据此假定
中间编号连续有效。应使用 `P0_0`...`P7_7` 名称和
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

## 资源和边界

- Timer0 及其中断向量 1 由系统时基占用；重配 Timer0 会破坏所有时间 API，
  软件 Wire/SPI、SoftwareSerial、LiquidCrystal 和 Stepper 的延时也会随之
  失效。关闭全局中断超过一个 Timer0 周期会
  丢失累计 tick，因此不要把 `noInterrupts()` 区间维持到毫秒量级。
- `Serial.begin()` 运行期间 UART1 占用 Timer1；常规缓冲配置另占 UART1
  中断向量 4。草图或其他库不能同时把 Timer1 用于 PWM、计时或其他波特率
  发生器。
- Wire 在四模式端口上使用开漏 GPIO，并为 TX/RX 各保留 16 字节数据 RAM；
  STC89 的准双向端口不是真正开漏，严格 I2C 应改用带外部上拉的 P0 引脚或
  外部开漏缓冲。SPI 与 Wire 均为阻塞式软件实现，`setClock`/
  `beginTransaction` 的频率是目标值，不是经硬件分频保证的精确总线频率。
- 各独立库不承诺能装入 2 KiB/4 KiB 型号；软件总线、显示、运动控制与其他 API 组合后的
  最终体积由所选芯片的链接上限检查。
- 核心不选择或校准系统时钟。烧录配置、熔丝/选项字和板上振荡源必须与
  `F_CPU` 一致，所有时间与波特率结果才有意义。
- STC89 默认按 12T 机器周期计算；ISP 选择 6T 时还必须在开发板菜单中同步
  选择 `STC89 machine cycle: 6T`。
- STC89 P0 是开漏口，没有可由核心启用的内部上拉；其他经典准双向端口也
  不能像四模式 GPIO 那样真正关闭弱上拉。

ADC 按硬件差异分成四种寄存器布局：STC12C2052AD 的 `0xC5/0xC6` 8 位
布局；STC12C5A60S2 的旧式 `ADC_RES/ADC_RESL` 加 `AUXR1` 对齐；旧 STC15
的同组结果寄存器加 `CLK_DIV` 对齐；以及 STC8/STC32/AI/Ai8 使用
`ADCCFG` 的现代布局。变体生成 `A0...`、`NUM_ANALOG_INPUTS`、
`analogInputToDigitalPin()` 与通道反查宏，避免把一组连续通道假设套到所有
封装。无 ADC 的 5 个型号（STC89C52RC、STC89C51RC、STC89C58RD+、
STC15F104W、STC8C2K64S4）以及非法/非 ADC 引脚调用 `analogRead()` 都返回
`-1`；转换超时也返回 `-1`。`analogReference()` 仅承诺 `DEFAULT`，其他
模式不会改动硬件。旧式 P1 ADC 引脚在随后调用 `pinMode()` 时会清除模拟
选择位并恢复数字用途。

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
