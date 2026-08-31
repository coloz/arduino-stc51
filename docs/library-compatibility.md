# Arduino 库对照与兼容性

本文以最接近 STC 8 位目标的官方
[`ArduinoCore-avr` 1.8.8](https://github.com/arduino/ArduinoCore-avr/tree/1.8.8/libraries)
平台随包库为严格基线，并把 Arduino 官方独立常用库另行列出。对照快照日期为
2026-08-31。

本平台把草图和库作为 **plain C** 编译。这里的“支持”表示提供相近用途和显式
函数 API，不表示 Arduino C++ 类、构造器、重载、`String`、`Print` 或 `Stream`
源码兼容。所有新增实现均为针对本 core API 的 clean-room MIT 实现，没有复制
Arduino 官方库源码。

## Arduino AVR Core 随包库

ArduinoCore-avr 1.8.8 的 `libraries/` 包含 5 个库：`EEPROM`、`HID`、`SPI`、
`SoftwareSerial` 和 `Wire`。本平台的对应状态如下。

| 官方随包库 | 当前状态 | 本平台边界 |
| --- | --- | --- |
| `SPI` | 已提供 | 软件主机，模式 0--3、MSB/LSB、单字节/缓冲传输；无 `SPISettings` C++ 对象、硬件 SPI、从机或 DMA |
| `Wire` | 已提供 | 软件 I2C 7 位地址主机、重复起始、时钟拉伸超时、16 字节 TX/RX；无从机回调、10 位地址或硬件 I2C |
| `SoftwareSerial` | 已补充，实验性受限支持 | 单个全局双引脚端口；同步 TX，显式轮询 RX；只面向低速、有帧间空闲的流量；无后台 PCINT 接收、多个 C++ 实例或 `Stream` |
| `EEPROM` | 未提供 | STC 各型号的 IAP/独立 EEPROM 布局、扇区、时序与容量不同；尚缺链接区预留、磨损和掉电一致性策略 |
| `HID` | 未提供 | 只有部分 U 型号具备 USB；尚无统一 USB Device、端点、描述符、时钟与启动层 |

`EEPROM` 和 `HID` 不提供返回固定值或静默 no-op 的占位库。这样的占位实现会让
草图“能编译”却在写 Flash 或枚举 USB 时产生不可恢复的数据风险和错误能力判断。

## 已补充的常用独立库

`LiquidCrystal`、`Stepper` 与 `SD` 不属于现代 ArduinoCore-avr 上述 5 个随包库，
但都是 Arduino 生态中的常用独立库，因此一并提供针对本 core 的 plain-C 版本。

| 库 | 主要 API | 实现范围 |
| --- | --- | --- |
| `LiquidCrystal` | `setPins*`、`begin`、`clear`、`home`、`setCursor`、显示/光标/闪烁/滚动/方向控制、`createChar`、`command`、`write/print/println` | 单个 HD44780 兼容控制器，4/8 位并口，可选 R/W；固定延时，不读 busy flag；不支持双 Enable 的 40x4 模块 |
| `Stepper` | `setPins2/4/5`、`setSpeed`、`step`、`release` 和状态查询 | 单个 2/4/5 线电机，阻塞式整步/五相序列；不做加减速、细分、电流控制或位置闭环 |
| `SD` | `setPins`、`begin/beginDefault/end`、卡/FAT/错误状态、`readBlock/writeBlock`、`exists/open/read/readBytes/peek/available/seek/position/size/close` | SPI 模式 SD1/SD2/SDHC；MBR 第一分区或 super-floppy；FAT16/FAT32 根目录短 8.3 文件只读；单卡、单文件、单 512 字节缓存；无长文件名、子目录、文件系统写入、FAT12、exFAT/SDXC 或 C++ `File`/`Stream` |

两者都检查数字引脚是否存在，并拒绝把同一引脚或同一物理焊盘别名分配给多个
信号。`Stepper` 只输出逻辑控制波形；电机绕组必须通过匹配的晶体管、H 桥或专用
驱动器连接，不能直接接 MCU GPIO。

## SD 使用边界

`SD.begin(cs_pin)` 只有在卡初始化和 FAT 卷参数挂载成功后才返回真；根目录扇区在
后续 `exists/open` 时按需读取。
默认软件 SPI 使用 P3.2/P3.3/P3.4/P3.5（MOSI/MISO/SCK/CS），也可在开始前用
`SD.setPins()` 一次性改写；库会拒绝无效引脚、重复引脚以及同一物理焊盘的别名。
初始化阶段使用约 100 kHz，成功后仍受软件 SPI 限制，目标频率最高约 500 kHz，
因此适合配置、日志回读等低吞吐场景，而不是音视频连续流。

- 支持 SD v1、SD v2 和 SDHC 的 SPI 模式；支持带 MBR 第一分区或直接位于 LBA0 的
  FAT16/FAT32 卷。FAT12、MMC、exFAT/SDXC 和多分区选择不在当前范围内。
- 文件层只认根目录短 8.3 名称，并且一次只打开一个普通文件，只读访问。
  `read()`/`peek()` 在 EOF 返回 `-1`，`seek()` 只接受 `0..size()`；没有官方 C++
  `File`、`Print`、`Stream`、目录遍历、长文件名、创建、追加、删除或目录操作语义。
- `readBlock()`/`writeBlock()` 是面向 512 字节 LBA 的原始接口，不是文件写入。
  对已挂载 FAT 卷调用 `writeBlock()` 可能立即破坏引导扇区、FAT 或目录；除非调用者
  自己管理完整的块布局和掉电一致性，否则不要使用。
- FAT 解析固定占用一个 512 字节 `__xdata` 扇区缓存，编译门槛为至少 1 KiB XDATA；
  1 KiB 型号仍需为栈、Serial 和其他库留出余量，正式编译探针使用 8 KiB XDATA 的
  STC8H8K64U 与 STC32G12K128。MCS251 后端仍属于实验路径。
- SD 卡本体通常是 3.3 V 器件。裸卡座不得直接承受不兼容的 5 V 信号；应使用电压
  匹配的 MCU 或具备合适稳压与电平转换的模块，并保证稳定供电和公共地。

对照 [Arduino 官方 SD API](https://github.com/arduino-libraries/SD/blob/master/docs/api.md)
与其 [1.3.0 源码接口](https://github.com/arduino-libraries/SD/blob/master/src/SD.h)，
当前 plain-C 子集如下。名称相近不表示 C++ 源码兼容。

| 官方接口组 | 本平台状态 | 差异 |
| --- | --- | --- |
| `SD.begin/end` | 已提供 | 显式 `begin(cs)` 或 `beginDefault()`；固定软件 SPI，初始化与全部等待有界 |
| `SD.exists/open(..., FILE_READ)` | 部分提供 | 仅根目录 ASCII 短 8.3 普通文件；一个全局文件状态，不返回 C++ `File` 对象 |
| `File.read/peek/available/seek/position/size/close` | 已提供等价前缀/点号接口 | `SD.read()` 等操作当前全局文件；`available()` 返回剩余字节数，不继承 `Stream` |
| `File.write/availableForWrite/flush/print/println` | 未提供文件语义 | FAT 层保持只读；原始 `writeBlock()` 不等价于文件写入 |
| `SD.mkdir/remove/rmdir` | 未提供 | 不修改目录、FAT 或文件元数据 |
| `File.name/isDirectory/openNextFile/rewindDirectory` | 未提供 | 当前不打开目录、不遍历目录项 |

## SoftwareSerial 使用边界

本平台没有覆盖所有 GPIO 的统一 pin-change interrupt，因此接收端采用显式轮询。
使用前必须先配置两个不同的有效物理引脚：

```c
#include <SoftwareSerial.h>

if (SoftwareSerial.setPins(P3_2, P3_3) && /* RX, TX */
    SoftwareSerial.begin(9600UL)) {
    SoftwareSerial.println("ready");
}
```

- 默认只接受约 1200--9600 baud 的配置请求；“接受”不是时序精度或跨型号可用性
  承诺。具体
  `F_CPU`、1T/6T/12T 模式、编译优化、其他中断和线路负载都会影响波特率。
- 只有 `poll()` 会在看到起始位时同步采样完整 8N1 帧；`available()`、`peek()`、
  `read()` 和 `readBytes()` 只访问已经缓冲的数据，不会暗中等待。草图必须高频调用
  `poll()`，否则会漏掉起始位。缓冲区默认 16 字节，环形缓冲可用容量为 15 字节。
- 发送同样是阻塞式 8N1。收发期间必须让 Timer0 保持运行，并保持 `TR0`、`ET0` 和
  全局中断 `EA` 有效；不应从 ISR 或 `noInterrupts()` 区间调用。库会拒绝明显不可用
  的时基，并用有界等待避免 Timer0 停止时永久卡死；`timingError()` 返回并清除对应
  的粘滞错误。
- `setInverseLogic(true)` 支持反相逻辑；`overflow()` 与 `framingError()` 返回并清除
  对应的粘滞状态。帧错误后会先等待线路恢复空闲，避免把持续低电平反复当作新帧。
- 这是两个独立 GPIO 的单端口函数表，并非单线半双工。发送期间不会接收，连续或同时
  双向流量会丢字节；示例因此只演示带帧间空闲的轮询回显，而不是可靠串口桥。
- 默认 P3.2/P3.3 还常被 INT0/INT1、Wire 和 SPI 使用，组合前必须重新规划引脚。
  两端须共地并使用与 MCU 电压兼容的 TTL/CMOS 电平，不能直连正负电压的 RS-232；
  STC89 的 P0 高电平需要外部上拉，反相 RX 的空闲低电平也需要对端主动驱动或下拉。
- 这是单端口函数表，不支持 AVR 库的构造器和多个对象。需要可靠持续接收、高波特率
  或多端口时，应优先使用芯片硬件 UART，并在后续逐型号多 UART 层完成后迁移。

## 尚未补充的常用能力

| 能力/库 | 当前阻塞条件 |
| --- | --- |
| `Servo` | Timer0 已用于时基，Timer1 常被 UART1 占用；缺逐型号 16 位定时器、通道和引脚复用矩阵 |
| `tone()` / `noTone()` | 这是 AVR core API 而非随包库；同样缺可安全分配的定时器与冲突管理 |
| `Ethernet` / `WiFi` | 依赖 SPI、网络协议、客户端/服务端流接口和更大缓冲；应先建立 plain-C 网络抽象 |
| `Keyboard` / `Mouse` | 都建立在 USB HID 之上，前置条件与 `HID` 相同 |
| 其他显示/网络库 | 多数依赖 Arduino C++ 基础设施或特定扩展板，应按设备和内存需求单独移植 |

Arduino IDE 1.x 曾把更多库随 IDE 一起发布，但现代平台将“core 随包库”和 Library
Manager 独立库分开管理。特定 Arduino Robot、Yún、Esplora 或扩展板库不作为裸
STC MCU 的默认兼容目标。

## 验证含义

仓库检查会验证 6 个已提供库的 metadata、头文件、C 实现、示例和许可证；构建矩阵
会在 8 KiB MCS51 代表型号上编译 `SoftwareSerial` 的最小轮询示例，并额外用
MCS251 后端编译同一示例，并在 MCS51/MCS251 两个后端编译 `SD` 示例；其余库也
各有编译探针。这些结果只证明
Arduino CLI/SDCC 能完成预处理、编译、归档和链接。软件串口时序、LCD 初始化波形、
步进相序/电流、Wire/SPI/SD 电气与存储介质行为仍需按
[`hardware-validation.md`](hardware-validation.md) 在具体型号、封装、时钟和驱动电路上验证。
