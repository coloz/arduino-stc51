# Arduino 库对照与兼容性

本文以最接近 STC 8 位目标的官方
[`ArduinoCore-avr` 1.8.8](https://github.com/arduino/ArduinoCore-avr/tree/1.8.8/libraries)
平台随包库为严格基线，并把 Arduino 官方独立常用库另行列出。对照快照日期为
2026-09-06。二十个第三方库的扩展工作见
[`cpp-library-expansion-plan.md`](cpp-library-expansion-plan.md)。此次源码修改后的结果
必须重新构建；此前四库/25-profile 证据只证明其绑定的旧源码快照。

默认 profile 把草图和库作为 **plain C** 编译。这里的“支持”表示提供相近用途和
显式函数 API，不表示任意 Arduino C++ 库源码兼容。所有新增实现均为针对本 core
API 的 clean-room MIT 实现，没有复制 Arduino 官方库源码。

全部 22 个物理型号、25 个 MCS51/MCS251 执行配置都有显式
`cppcore=enabled` 的实验 C++11 profile。它包含
`String`、`Printable`、`Print`、`Stream`、`HardwareSerial`、`SPIClass`、
`TwoWire`、`IPAddress`、`Client`、`Server`、`UDP`，以及随库提供的
`SoftwareSerial : Stream`、`LiquidCrystal`、`Stepper` 和受限读写
`File`/`SDClass` 类层。
MCS51/MCS251 都使用真实 C++ translation units、目标专用 ABI 和最终 SDCC 链接；
Core 资格合同包含 25 个配置（14 MCS51 + 11 MCS251）与 31 个 workload
（6 compact×2 + 19 full×1），库语料另按 frontend、link、runtime
和 capacity 分阶段记录。当前 outcome 只读取 `tests/cpp/variant-matrix/results.json`
与 `tests/cpp/library-compat/results.json`；历史单型号 canary 或中间库编译不能升级为
全矩阵 PASS。
AI8051U-34K16 的两种执行模式使用 14,336 字节 compact 程序上限；
STC32F12K54 的 4 KiB XDATA 配置使用 3,584 字节 heap 并保留 512 字节静态预算。
最终 clean Core/QEMU run 正在重新生成；exact machine 已存在不能替代权威 JSON。
异常、RTTI、完整 STL、真实独立 Flash 地址空间、完整库语料和实板仍未合格，
因此这仍不是“广泛兼容”结论。

## Arduino AVR Core 随包库

ArduinoCore-avr 1.8.8 的 `libraries/` 包含 5 个库：`EEPROM`、`HID`、`SPI`、
`SoftwareSerial` 和 `Wire`。本平台的对应状态如下。

| 官方随包库 | 当前状态 | 本平台边界 |
| --- | --- | --- |
| `SPI` | C/C++ 主机；新增 `usingInterrupt/notUsingInterrupt` 事务保护 | 软件模式 0--3、MSB/LSB、缓冲传输；事务保存/屏蔽/恢复注册中断。`SPI_CLOCK_DIVn` 请求 `F_CPU / n`，不是 AVR 寄存器编码；无硬件 SPI、从机、DMA 或传输完成中断 |
| `Wire` | C/C++ 主机；新增 timeout flag/reset 与内部寄存器地址读取 | 7 位地址、重复起始、默认 32 字节 TX/RX（可显式缩小）、时钟拉伸；不支持从机回调、10 位地址或硬件 I2C，`WIRE_HAS_SLAVE=0` |
| `SoftwareSerial` | 常规构造器与 `Stream`；`available/peek/read` 自动服务轮询接收 | 一个活动监听者，同步 TX；默认 64 字节 RX，低内存型号 16 字节。仍须频繁调用接收接口，只面向低速、有帧间空闲的流量；不是后台 PCINT 接收 |
| `EEPROM` | 未提供 | STC 各型号的 IAP/独立 EEPROM 布局、扇区、时序与容量不同；尚缺链接区预留、磨损和掉电一致性策略 |
| `HID` | 未提供 | 只有部分 U 型号具备 USB；尚无统一 USB Device、端点、描述符、时钟与启动层 |

`EEPROM` 和 `HID` 不提供返回固定值或静默 no-op 的占位库。这样的占位实现会让
草图“能编译”却在写 Flash 或枚举 USB 时产生不可恢复的数据风险和错误能力判断。

## 已补充的常用独立库

`LiquidCrystal`、`Stepper` 与 `SD` 不属于现代 ArduinoCore-avr 上述 5 个随包库，
但都是 Arduino 生态中的常用独立库，因此一并提供针对本 core 的 plain-C 接口和
实验 C++ facade。

| 库 | 主要 API | 实现范围 |
| --- | --- | --- |
| `LiquidCrystal` | 并口 HD44780 的显示/光标/自定义字符/Print 和 public `init(...)`/`setRowOffsets(...)` | C++ 每实例独立引脚、控制状态和行偏移；C 接口保留默认实例。构造器不访问硬件，须在 Core 启动后 `begin`/`init`；4/8 位，可选 R/W；固定延时，不读 busy flag；不支持双 Enable 40x4 |
| `Stepper` | 2/4/5 线、速度、阻塞步进、release、version | C++ 每实例独立引脚、相位与速度；C 接口保留默认实例。不做加减速、细分、电流控制或闭环 |
| `SD` | `SDClass`、`File : Stream`、FAT16/32 根目录 8.3 文件读写 | 新增 create/append/seek-overwrite/flush/remove；单卡、单活动文件、单 512 字节缓存；不支持子目录/遍历、长文件名、FAT12、exFAT；不是掉电原子文件系统 |

这些 GPIO 驱动库会检查数字引脚是否存在，并拒绝把同一引脚或同一物理焊盘别名分配给多个
信号。`Stepper` 只输出逻辑控制波形；电机绕组必须通过匹配的晶体管、H 桥或专用
驱动器连接，不能直接接 MCU GPIO。

## SD 使用边界

`SD.begin(cs_pin)` 只有在卡初始化和 FAT 卷参数挂载成功后才返回真；根目录扇区在
后续 `exists/open` 时按需读取。
默认软件 SPI 使用 P3.2/P3.3/P3.4/P3.5（MOSI/MISO/SCK/CS），也可在开始前用
`SD.setPins()` 一次性改写；库会拒绝无效引脚、重复引脚以及同一物理焊盘的别名。
C++ 层仅在改写成功时使全部现有 `File` 句柄失效；请求被拒绝时保持原挂载和句柄。
初始化阶段使用约 100 kHz，成功后仍受软件 SPI 限制，目标频率最高约 500 kHz，
因此适合配置、日志回读等低吞吐场景，而不是音视频连续流。

- 支持 SD v1、SD v2 和 SDHC 的 SPI 模式；支持带 MBR 第一分区或直接位于 LBA0 的
  FAT16/FAT32 卷。FAT12、MMC、exFAT/SDXC 和多分区选择不在当前范围内。
- 文件层只认根目录短 8.3 名称，并且一次只打开一个普通文件。
  `read()`/`peek()` 在 EOF 返回 `-1`，`seek()` 只接受 `0..size()`。双目标实验
  profile 提供 `File : Stream` 与 `SDClass`；`FILE_WRITE` 创建或追加，也可 seek 后覆盖，
  支持 flush/close 回写和 remove。没有目录遍历、长文件名或子目录操作语义。
  FAT/目录更新不是事务；I/O 故障会报告失败，但突然掉电仍可能损坏文件系统。
- `readBlock()`/`writeBlock()` 是面向 512 字节 LBA 的原始接口，不是文件写入。
  对已挂载 FAT 卷调用 `writeBlock()` 可能立即破坏引导扇区、FAT 或目录；除非调用者
  自己管理完整的块布局和掉电一致性，否则不要使用。
- FAT 解析固定占用一个 512 字节 `__xdata` 扇区缓存，编译门槛为至少 1 KiB XDATA；
  1 KiB 型号仍需为栈、Serial 和其他库留出余量，正式编译探针使用 8 KiB XDATA 的
  STC8H8K64U 与 STC32G12K128。MCS51/MCS251 C++ 后端仍属于实验路径。
- STC32G144K246 作为大容量 MCS251 型号进入独立 CoreAPI 编译探针，不增加本地
  8 个库探针。P8--PB XFR、高地址链接/复位入口的静态门禁完成，且 ADC2/PLL 的
  未暴露边界记录清楚前，不把该探针记为 SD 或其他随平台库的运行验证，也不声称
  QEMU 或实板已经通过。
- `SoftwareSerial` 的 K246 构建已覆盖 P8--PB 的 XFR 输入与原子 SETB/CLRB 代码路径；
  这些扩展端口上的实际波特率、上拉和接收采样仍需实板验证。
- SD 卡本体通常是 3.3 V 器件。裸卡座不得直接承受不兼容的 5 V 信号；应使用电压
  匹配的 MCU 或具备合适稳压与电平转换的模块，并保证稳定供电和公共地。

对照 [Arduino 官方 SD API](https://github.com/arduino-libraries/SD/blob/master/docs/api.md)
与其 [1.3.0 源码接口](https://github.com/arduino-libraries/SD/blob/master/src/SD.h)，
默认 plain-C 子集与双目标实验 C++ 层如下。名称相近不表示完整官方实现。

| 官方接口组 | 本平台状态 | 差异 |
| --- | --- | --- |
| `SD.begin/end` | 已提供 | `begin()`/`begin(cs)` 使用固定软件 SPI；C++ `begin(clock, cs)` 为源码兼容而接受但当前忽略 `clock`；初始化与全部等待有界 |
| `SD.exists/open(..., FILE_READ)` | plain-C 与双目标实验 C++ 层均提供；C++ 另有 `String` overload | 仅根目录 ASCII 短 8.3 普通文件；后端仍只有一个全局活动文件状态 |
| `File.read/peek/available/seek/position/size/close` | C/C++ 已实现；C++ 保留句柄复制/失效规则 | `seek()` 不创建稀疏文件；单活动文件，尚无真实 SD 卡 target/实板 oracle |
| `File.write/flush/print/println` | `FILE_WRITE` 模式真实写入，跨扇区/簇追加与覆盖；只读句柄拒绝写入 | 主机 FAT 镜像测试执行生产 FAT 层，只替代块传输边界；不等于 QEMU SD 控制器或实卡验证 |
| `SD.remove` | 删除根目录普通文件并回收 FAT 链 | 单卡/短 8.3；I/O 失败可返回部分操作失败，不承诺掉电原子性 |
| `SD.mkdir/rmdir` | 接口存在，但明确返回失败 | 不提供子目录功能 |
| `File.name/isDirectory/openNextFile/rewindDirectory` | C++ 有兼容表面 | 普通文件 `name()` 可用；`isDirectory()` 恒为 false、`openNextFile()` 返回无效句柄、`rewindDirectory()` 无操作，不能据此宣称目录支持 |

## SoftwareSerial 使用边界

本平台没有覆盖所有 GPIO 的统一 pin-change interrupt，因此接收端仍采用轮询。
`available()`、`peek()`、`read()` 现在自动调用接收服务，但不调用这些接口时不能后台接收。
默认 plain-C profile 使用前必须先配置两个不同的有效物理引脚：

```c
#include <SoftwareSerial.h>

if (SoftwareSerial.setPins(P3_2, P3_3) && /* RX, TX */
    SoftwareSerial.begin(9600UL)) {
    SoftwareSerial.println("ready");
}
```

显式 C++ profile 另提供 Arduino 形状的构造器和 `Stream` 基类，例如：

```cpp
#include <SoftwareSerial.h>

SoftwareSerial debugPort(P3_2, P3_3); // RX, TX

void setup()
{
    debugPort.begin(9600UL);
}
```

可以构造多个对象以便切换配置，但底层只有一个全局活动端口；某对象的
`begin()`/`listen()` 会选择其引脚和配置，不能让两个实例同时接收。

- 默认只接受约 1200--9600 baud 的配置请求；“接受”不是时序精度或跨型号可用性
  承诺。具体
  `F_CPU`、1T/6T/12T 模式、编译优化、其他中断和线路负载都会影响波特率。
- `poll()` 显式服务一次接收；plain-C/C++ 的 `available()`、`peek()`、`read()` 和
  `readBytes()` 在执行期间也会通过读路径轮询。C++ `Stream::readBytes()` 会按
  `setTimeout()` 反复读到满足长度或超时，但两次调用之间仍没有后台采样，因此草图
  必须频繁调用这些接收接口，否则会漏掉起始位。XDATA 不少于 2 KiB 时 RX 缓冲默认
  64 字节、环形可用 63 字节；更小配置默认 16 字节、环形可用 15 字节。
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
  反相 RX 的空闲低电平需要对端主动驱动或下拉。
- plain-C 表面是单端口函数表；C++ 表面虽有构造器、`Stream` 和多个对象的源码
  形状，仍只复用一个活动后端。需要可靠持续接收、高波特率或真正同时多端口时，
  应优先使用芯片硬件 UART，并在后续逐型号多 UART 层完成后迁移。

## 尚未补充的常用能力

| 能力/库 | 当前阻塞条件 |
| --- | --- |
| `Servo` | Timer0 已用于时基，Timer1 常被 UART1 占用；缺逐型号 16 位定时器、通道和引脚复用矩阵 |
| `tone()` / `noTone()` | 这是 AVR core API 而非随包库；同样缺可安全分配的定时器与冲突管理 |
| `Ethernet` / `WiFi` | 实验 C++ profile 已有 `Client`/`Server`/`UDP`/`IPAddress` 抽象，但不含协议栈或芯片驱动；冻结语料的逐阶段 outcome 只在机器可读库矩阵中声明 |
| `Keyboard` / `Mouse` | 都建立在 USB HID 之上，前置条件与 `HID` 相同 |
| 其他显示/网络库 | 多数依赖 Arduino C++ 基础设施或特定扩展板，应按设备和内存需求单独移植 |

Arduino IDE 1.x 曾把更多库随 IDE 一起发布，但现代平台将“core 随包库”和 Library
Manager 独立库分开管理。特定 Arduino Robot、Yún、Esplora 或扩展板库不作为裸
STC MCU 的默认兼容目标。

## C++ 库语料证据

机器可读结果见 `tests/cpp/library-compat/results.json`，本平台包不会复制其中的
瞬时 PASS/FAIL。该文件按固定输入/source lock、frontend、最终 target link、QEMU/host
runtime 与 capacity 分开记账；前一阶段通过不能替代后一阶段。最终常用库矩阵使用
`tests/cpp/library-corpus.json` 中的官方归档 URL、版本、提交和 SHA-256，不接受仅凭
`library.properties` 版本号识别的本地源码树：

| 语料 | 冻结版本 | 官方归档 SHA-256 |
| --- | --- | --- |
| ArduinoJson | 7.4.3 | `cd8d2f7e4f06eb7e215beecb0de5326a82d047a994e84246572ad73ddc52746f` |
| DHT20 | 0.3.2 | `d071c5620b497c4bc97551e8bbab28066c0158b423721ecdac31f76f3b58b59b` |
| RF24 | 1.5.0 | `21e48ef1ac428acaebdb6878b0fc3fed919a4d32122b9f572262ffbae0d41ce3` |
| U8g2 | 2.36.19 | `c9de6e5a5aa2e2884d3296c6a86be4bc2770e27b11d4302ab5134273ccb6a670` |

STC32G144K246/MCS251 使用完整 ArduinoJson 语料；STC8H8K64U/MCS51 使用独立的
compact 语料验证最小 `JsonDocument` 写入、读取与序列化，并对 DHT20、RF24、U8g2
运行相同的官方源码编译/链接门。完整 ArduinoJson 语料仍作为 MCS51 容量负例：真实
clean 构建必须非零退出且不生成 HEX，`.mem` 与 ASlink 日志必须精确报告
`Insufficient ROM/EPROM/FLASH memory`，bridge 输入 REL 与最终 map 中的 CSEG 也都必须
超过 65,536 字节。runner 会预先保存同输入的 provenance-only compilation database，
再用失败构建实际留下的对象与 depfile 证明编译阶段完成。ASxxxx 地址截断 warning 仅
作为诊断保留，不以其文本、数量或 opcode 组合作为资格判据。诊断包上的中间结果不进入最终矩阵；每项只有在同一冻结平台归档、
源码锁、clean Arduino CLI 构建和容量审计全部一致时才能记录 target PASS。

ArduinoJson 的 `f_str()` 可由普通 data-pointer fallback 接入 `String`/`Print`，但不
因此获得 Harvard Flash 或省 RAM 语义。生成 HEX 也不是运行证据：只有精确芯片
machine 上、绑定固件与 QEMU 二进制哈希且 UART oracle 通过的执行才能记录 QEMU
runtime PASS；未执行或未保存该证据时必须保持 `NOT_RUN`。上游 SD 源码仍有未知
STC 架构拒绝、把指针放入 16 位 `int` 以及复制动态 C++ 对象等移植风险；本仓库的
clean-room、受限根目录读写层不把这些差异隐藏成上游库兼容结论。

早期只读主机 mock 的结果只适用于其绑定的旧源码快照，不能证明当前写入实现。
当前主机 FAT16/FAT32 镜像 fixture 会执行生产文件层的 create/append/overwrite/
flush/remove 和故障边界，但仍只替代块传输；frontend IR 也只证明前端接受源码。
软件串口时序、LCD 初始化波形、步进相序/电流、Wire/SPI/SD 电气与存储介质行为
仍需按 [`hardware-validation.md`](hardware-validation.md) 在具体型号、封装、时钟和
驱动电路上验证。
