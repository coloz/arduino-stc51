# 20 库适配范围与验证口径

这些库代表常见功能场景，不是下载量排行榜。版本与 SHA-256 固定在
`tests/cpp/library-compat/common20-lock.json`，下载自 Arduino 官方索引指定的原始归档。
Adafruit BusIO 1.17.4、Adafruit Unified Sensor 1.1.15 为额外依赖，不计入 20。
不修改上游源码，不冒用 `__AVR__`、ESP32 或 ARM 架构宏来绕过检测。

测试层次必须分开：

- 前端：真实 STC Clang 为库和依赖的 C++ 翻译单元产生目标 LLVM IR；不包含 SDCC 链接。
- 构建：Arduino CLI 发现依赖，经过 LLVM-CBE 和 SDCC，保留 HEX、map、内存和 ABI 审计。
- 主机行为：生产库代码执行，GPIO/时钟/块设备或网络传输边界由确定性模型提供。
- QEMU：精确型号运行本次 HEX；每个用例只证明其明确的串口 oracle。
- 实板：本轮未连接真实传感器、无线电、网卡、显示器或 SD 卡，不能据此宣称时序/电气合格。

## 所选库与风险

| 库 / 固定版本 | 实际依赖与本轮验证范围 | 不能扩大的结论 |
| --- | --- | --- |
| ArduinoJson 7.4.3 | C++11 模板、动态内存、String；解析/修改/精确序列化主机 oracle，目标序列化用例 | 64 KiB MCS51 不能容纳所有完整语料；需分别测 Flash 和 heap |
| Bounce2 2.71.0 | millis、GPIO、类继承；真实时间线消抖 oracle | 不能把模拟输入当作物理开关电气验证 |
| AccelStepper 1.64.0 | micros、浮点数学、回调、STEP/DIR；脉宽/正反方向/位置 oracle | 实际最高步频、电机驱动与加速负载尚未实测 |
| DHT20 0.3.3 | Wire、超时、CRC；目标无传感器错误路径 | 不证明温湿度读取和传感器时序 |
| RF24 1.6.2 | SPI 事务、CE/CS、PROGMEM、64 位地址；目标初始化无设备路径 | 不证明无线收发、中断/ACK 和物理 SPI 时钟 |
| Adafruit GFX 1.12.6 | Print、虚函数、malloc、BusIO；canvas1/8/16 像素 oracle | 字体表及完整显示驱动的 RAM/Flash 需求另计 |
| Adafruit SSD1306 2.5.17 | GFX/BusIO/Wire、动态 framebuffer；128×64 缓冲分配/像素用例 | 1024 字节 framebuffer 不代表所有小容量芯片可用；未验证屏幕响应 |
| Adafruit BME280 2.3.0 | BusIO/Sensor、Wire/SPI、NAN；目标无设备初始化错误路径 | 不证明校准寄存器读取与温压湿测量 |
| DHT sensor library 1.4.7 | GPIO、忙等待、关中断；目标温度转换 | DHT11/22 脉冲解码须真实时序 oracle/实板，不由转换函数证明 |
| RTClib 2.1.4 | BusIO、pgmspace、stdio、DateTime；闰日/非法日期/运算/格式 oracle | 不证明各种 RTC 芯片的寄存器、闹钟、中断功能 |
| OneWire 2.3.8 | generic GPIO fallback、关中断、微秒等待；CRC8/CRC16 oracle | 上游明确警告此架构 fallback 时序不保证；CRC 不证明 1-Wire 总线 |
| DallasTemperature 4.0.6 | OneWire；scratchpad、温度/分辨率、异步转换命令模型 | 模型验证库协议，不等同于真实 DS18B20 或寄生供电时序 |
| PubSubClient 2.8.0 | Client、IPAddress、malloc；CONNECT/SUBSCRIBE/PUBLISH 字节、分片 QoS1/PUBACK oracle | Core 抽象本身不提供 TCP/IP、TLS 或网卡 |
| Ethernet 2.0.2 | SPI、Client/Server/UDP、IPAddress；静态 IP/无控制器路径 | DHCP、DNS、socket 收发及 W5x00 硬件未验证 |
| U8g2 2.36.19 | C/C++ 混合、GPIO/Wire/SPI、字体表；目标选择 U8x8 文本模式 | U8x8 子集不代表完整 U8g2 framebuffer/所有字体能装入芯片 |
| LiquidCrystal I2C 1.1.2 | Wire、Print、delay；初始化/字符写入调用 | 上游 write 返回计数不能证明 I2C ACK 或 LCD 显示 |
| Keypad 3.1.1 | GPIO、millis、扫描状态机；真实 2×2 模型与按下/保持/释放/空闲 oracle | 不包含物理按键矩阵串扰、电气上拉验证 |
| PID 1.2.0 | 浮点、millis；采样窗口、正/反方向、比例计算 oracle | PID 算法可用不等于 analogWrite 已有真正 PWM |
| TinyGPSPlus 1.0.3 | Stream 输入、NMEA 校验与数字解析；RMC 字段/校验/几何 oracle | 不证明 GNSS 硬件接收链路或完整所有 NMEA 报文 |
| TaskScheduler 4.0.8 | millis、函数指针、协作调度；一次/周期触发时间线 oracle | 不提供 RTOS，也不代表需要完整 STL 的可选配置都可用 |

## 可重跑入口

1. Windows 运行 `tests/cpp/library-compat/fetch-common20.ps1`，校验归档和提取文件的完整清单。
2. WSL 运行 `run-common20-frontends.py --output <新的证据目录>`，保留目标 IR 与逐单元日志。
3. `prepare-common20-platform.ps1 -WorkDirectory <新的隔离目录>` 冻结 SDK 与工具输入。
4. WSL 运行 `run-common20-builds.py --platform-work <该目录的WSL路径> --batch <新名字>`。
5. WSL 运行 `run-expansion-host-suite.py --output <新的证据目录>`。

每个失败都必须保留，不得用语法 PASS 替换链接失败，也不得把无设备路径改写成外设功能 PASS。
完整版本结果由上述 JSON 与源文件哈希决定；这份范围说明本身不授予全库或全 variants 合格状态。

## 本轮发现的编译器与 libc 边界缺口

- LLVM-CBE 曾把 MCS251 的内存 intrinsic 长度按 24 位指针宽度传入，
  而原生 `size_t` 为 32 位；真实 ArduinoJson 路径因此覆盖返回地址。
  修复须由真实大桥、负向审计和 QEMU 重放闭环，不以语法通过代替。
- MCS51 原生 malloc/calloc/realloc 返回 16 位 XDATA 指针，而 C++ 需要
  含地址空间标记的 24 位 generic 指针；新增 native C 包装负责转换，
  同时处理 MCS51 strchr/strrchr 的 char 参数边界。
- 数学函数需要核对实际 SDCC `*f` 符号；目标 float/double 均为 32 位，
  不能因声明存在就宣称 `sqrt` 等已可链接。
- 新的 stdio 边界提供有界 `snprintf` 与 UART1 格式输出；先调用
  `Serial.begin`，`getchar` 会等待输入。格式符能力限于安装的 SDCC formatter。
  FILE 文件流、scanf 和跨 Clang/SDCC 的 `va_list` 未实现，使用即明确报错。
  主机有界输出测试不证明 SDCC 原生 varargs ABI，后者另由目标用例验证。

随附 LiquidCrystal 新增 public `init(...)` 和按实例的 `setRowOffsets(...)`；
构造器仅记录引脚，需在 Core 启动后调用 `begin`/`init`，以免全局构造阶段依赖未启动的计时器。
