# Arduino 实际开发中的能力与边界

本页对应当前 MCS251 平台：10 个型号、10 个执行配置，以 `boards.txt` 和 `tools/variants/devices.json` 为准。功能可用性、程序容量和物理波形应分别判断。

## PWM

`analogWrite(pin, value)` 在支持的引脚输出硬件 PWM，值为 0～255。
0/255 切换为恒低/恒高；中间值使用 256 个计数，频率约 1 kHz，取决于系统时钟
和整数分频。当前提供 STC32G、STC32CL 和 AI8051U 的 PWMA/PWMB 正向输出。
STC32CL8K48／64 的物理引脚别名 P1.4/P0.2、P1.5/P0.3 共用焊盘；切换别名会停止原引脚的 PWM。

先用 `digitalPinHasPWM(pin)` 查询当前型号。需要明确成功或失败时，使用
`analogWriteChecked(pin, value)`，返回 `STC_PWM_OK`、`STC_PWM_INVALID`、
`STC_PWM_UNSUPPORTED` 或 `STC_PWM_BUSY`。普通 `analogWrite` 会把越界值钳制到
0～255，并在没有 PWM 的有效引脚上使用 `<128` LOW、其余 HIGH 的 Arduino
数字回退；`analogWriteConfigurationError()` 保留这次不支持状态。

同一通道的不同复用引脚不能同时使用；第二个请求返回 BUSY。一个引脚对应多个
通道时采用固定的首个映射。`digitalWrite` 和 `pinMode` 会停止该引脚的 PWM，
释放通道；其他通道继续工作。两个库不得同时直接配置同一 PWM 定时器组。
所有通道共享各自组的频率，不提供任意频率、互补输出、死区、捕获或刹车接口。
本实现不占用系统 Timer0 和串口 Timer1。

AI8051U 的 P5.2 可输出 PWMB 通道 7；常见低电平点亮 LED 的亮度方向与占空比
相反。跨型号代码不要假定 P5.2 都是 PWM 引脚。有效引脚还受所选变体和实物封装限制。

## 外部中断

INT0=P3.2、INT1=P3.3。STC32/AI 的 IT0/IT1 为 0 时是
双边沿触发，因此支持 CHANGE、FALLING，LOW 请求会明确拒绝。
RISING 通过双边沿中断内读取引脚并过滤下降沿实现：高脉冲必须保持到 ISR 采样，
不能用它替代高速硬件捕获。

`interruptModeSupported(irq, mode)` 可预先查询；`attachInterruptChecked` 返回
`STC_INTERRUPT_OK`、`STC_INTERRUPT_INVALID`、`STC_INTERRUPT_UNSUPPORTED_MODE`。
无效请求保留原配置和回调。传统 `attachInterrupt` 委托同一检查逻辑，结果可由
`interruptConfigurationError()` 读取。回调应短小；共享多字节变量仍需原子访问。

## Wire、SPI 和串口

Wire 按型号和引脚使用硬件控制器或软件主机。硬件接线以 variant 和总线说明为准；软件回退默认 SDA=P3.2、SCL=P3.3。使用 7 位地址，每个收发缓冲默认
32 字节；不提供从机或 10 位地址。I²C 与外部中断或其他库共用引脚时，由应用协调。
外部上拉、电压、总线电容与器件要求仍需满足。

STC32CL8K48／64 现已启用硬件总线，默认 Wire 接线改为 **SDA=P3.3、SCL=P3.2**。
默认 SPI 为 MOSI=P1.3、MISO=P1.4、SCK=P1.5、SS=P1.2；CL 的 P1.0 和 P5.2 不存在。
12 MHz 下 SPI 请求至少 750 kHz 才能使用硬件分频档；默认 100 kHz 仍采用软件。
STC32G 的独立 SPI 第三组为 P4.0/P4.1/P4.3；P7.5/P7.6/P7.7 属于 USART2 的 SPI 路由，当前 SPI 库在该组引脚使用软件。
各型号的外设开关、引脚组和容量以[型号配置](variants-mcs251.md)及其源数据为准。

`Wire.setPinsChecked(sda, scl)` 拒绝不存在、重复及同一物理焊盘别名；
`Wire.configurationError()` 返回配置状态。`endTransmission()` 的返回值沿用
0 成功、1 缓冲过长、2 地址 NACK、3 数据 NACK、4 其他错误、5 超时。
`requestFrom()` 返回实际读取长度，失败原因用 `Wire.lastError()` 查询。
无效地址不会再截断成另一个有效地址。

默认每次等待 SCL 释放的上限为 25 ms，可用 `setWireTimeout(us, reset)` 调整；
显式传 0 表示无限等待。超时上限是每次等待的上限，不是整笔多字节事务的总时限。
Wire 依赖 Timer0 时基，须在前台、EA/ET0/TR0 开启时使用；关闭时拒绝启动事务。
总线恢复测试覆盖外部释放后的再次访问，没有自动发送九个恢复时钟。
软件时钟设置是请求值，实际速率受 GPIO 调用与中断开销影响。

SPI 按型号和引脚使用硬件或软件主机，支持模式 0～3、MSB/LSB，片选由应用控制。
`SPI.setPinsChecked`、`SPI.beginTransactionChecked(SPISettings(...))` 返回
`STC_SPI_OK`、`STC_SPI_INVALID` 或 `STC_SPI_BUSY`；无效频率/模式/位序被拒绝，
嵌套事务和事务中改引脚返回 BUSY。`SPI.configurationError()` 可用于传统 void
接口之后检查结果。事务按 `usingInterrupt` 注册保存、屏蔽、恢复中断，不能递归使用。
没有跨库的全局引脚占用管理；Wire、SPI、PWM、Serial 仍可能由应用配置成冲突引脚。

UART1 的 Serial 使用 Timer1，发送同步、接收通常由中断缓冲。长期不取数据仍会
溢出，应检查 `Serial.overflow()` 并设计接收协议、服务频率与缓冲预算。
SoftwareSerial 依然是轮询接收，不能保证在刷屏、阻塞延时等工作期间接住连续数据。
需要可靠接收时优先 UART1；这轮没有把它扩展成后台软件 UART 或多路硬件串口。

## 内存、数据格式与库

目标 ABI 保持 `int` 16 位、`long` 32 位、`double` 与 `float` 均为 32 位，
普通 `char` 无符号。MCS251 为大端、24 位指针，不能直接把内存结构
当成串口、文件或传感器协议。使用固定宽度整数与
`STCByteOrder.h` 的 `stcRead/WriteLE/BE16/32/64`；这些函数允许非对齐字节缓冲，
调用者负责长度检查。示例见 `examples/Practical/PortablePacket`。

`String`、`malloc`、`new` 仍受有限的固定堆约束。长寿命对象交错分配可能产生
碎片，即使总空闲量足够，大块申请也会失败。预先 `String.reserve()`，检查其结果，
循环内尽量复用缓冲；检查 `malloc`、`new (std::nothrow)` 和库的 `begin()` 返回值。
普通 `new` 失败走运行时 panic；不要假定它会抛出异常或返回可忽略的空指针。
`cpp/stcxx_allocator.h` 的 telemetry 同时给出总空闲量、最大连续块及低水位；
它是此核心的扩展，不是跨平台 Arduino API。分配器不应在 ISR 中使用。

MCS251 使用按型号配置的扩展调用栈。递归、长调用链和中断嵌套仍可能耗尽栈；增加 XDATA 堆不会扩大已配置的调用栈。

原生 C 常量与 C++ 混合链接现在依据实际 REL/归档中的 CODE/XDATA 区域生成声明，
并核对最终链接符号；不会把所有 C++ `const` 都搬到 Flash。未知区域和不一致的
存储映射会拒绝构建，详见[C++ 运行时约定](cpp-runtime-contract.md)。
这不等于完整 AVR PROGMEM 兼容，也不保证任意库都能装入小容量芯片。
第三方库需要按具体版本、配置、Flash/RAM 预算做构建和运行验证。

第三方库使用情况应以具体型号、版本和运行验证为准。
