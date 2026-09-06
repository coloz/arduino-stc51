# 逐型号编译与实板验证指南

本文用于跟踪 `arduino-stc51` 支持型号的验证状态。这里严格区分两类结论：

- **编译/链接验证**只说明当前 core、变体定义和测试草图能由对应后端完成编译、链接，并生成 HEX；它不能证明程序能够启动，也不能证明引脚、电气特性、中断、时基、UART 或 ADC 在芯片上工作正确。
- **实板验证**必须在型号和封装一致的芯片上下载程序，并保留接线、供电、时钟、串口输出及测量记录后，才能标为通过。

型号数据库描述的是芯片可用逻辑引脚的上限。标有封装相关的型号，实际引出引脚可能更少；接线前必须以所用芯片丝印、封装图和最新官方数据手册为准。

## 编译/链接矩阵

在仓库根目录运行：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\test-all-variants.ps1
```

如 Arduino CLI 不在默认位置，可显式指定：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\test-all-variants.ps1 `
  -ArduinoCli 'C:\Program Files\Arduino CLI\arduino-cli.exe'
```

调试单个或少量型号时可按数据库 `id` 过滤；多个值用 PowerShell 数组传入：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\test-all-variants.ps1 `
  -DeviceId stc8h8k64u

& .\scripts\test-all-variants.ps1 `
  -DeviceId @('stc8h8k64u', 'stc32cl8k64')
```

未知 `id` 会立即报错。选择任一 AI8051U 型号时会同时编译默认 `mcs51` 和实验
`mcs251` 配置。

需要保留临时构建产物时，可使用 `-KeepWorkDirectory`；也可用
`-WorkDirectory D:\Temp\stc51-variant-test` 指向一个专用测试目录。不要把工作目录指向
仓库根目录或保存其他资料的目录。

脚本会打包当前工作树、按清单校验工具链归档的文件大小和 SHA-256、对数据库中的
每个型号执行干净编译，并确认生成了 HEX。它还会编译 Wire、SPI、SoftwareSerial、
LiquidCrystal、Stepper 和 SD 的代表示例，并用 MCS251 再编译一次 SoftwareSerial
和 SD。
STC32G/STC32CL/STC32F12K54 使用实验性的 `mcs251` 后端；AI8051U 默认测试 `mcs51`，
并额外测试实验性的 `mcs251` 配置。
只有脚本以零退出码结束且打印最终 `PASS`，对应配置才能记为
“编译/链接通过”。网络下载失败、
工具链校验失败、超出 Flash 或未生成 HEX 都应记为失败，而不是硬件失败。

plain-C 本地矩阵包含 22 个默认板项、3 个 AI8051U 的附加 `mcs251`
配置和 8 个库探针，共 33 个配置；当前 outcome 只读取对应机器可读结果，不复制到
平台包文档。K246 默认构建还会解析 Intel HEX，检查 `0xFF0000` 复位跳板、
INT0/Timer0/INT1/UART1 的 24 位跳转、未占用 Timer1 的 `RETI` 以及目标地址范围。
全部 22 个物理型号、25 个 MCS51/MCS251 执行配置的 12 MHz 实验 C++ profile 已接入
Arduino CLI 的显式 `cppcore=enabled` 选项；默认仍为 plain-C。最终补丁工具链来源是独立项目
`D:\Git\stc51\stcxx`，其 frontend ELF 和 `sdldmcs251` SHA-256 分别为
`1ccd9c28fa7d7fb7428cd43f423a80f1a456f98d32fc0f7823e5163d48d78cb5` 与
`749a198184383d56902979f45e554b4a24dfe97b8d70b2d891a5e437559263fa`。

QEMU outcome 不计入 24 MHz、实板或未建模外设的结果。锁定源码提交
`faeac38c0076795d7b4e59f0ddcb5fc7e7bd7015` 已为 22 个物理型号、25 个执行配置提供
精确 machine；MCS51/MCS251 二进制 SHA-256 分别为
`08b41280f0a326ab5fe4ca2f18ed6d41860a7b4bb488b2b0a58fc5f088ea8157` 和
`81c1246c4d85911b03562307ae23df50cba636098be9af1fdcfa38fd192cf3e7`。model 存在
不等于 runtime PASS，审计也拒绝任何 machine alias。C++ 合同要求 25 个 profile
（14 MCS51 + 11 MCS251）：6 个 compact profile 各保留 `runtime`/`io` 两个 workload，
其余 19 个各保留 `full`，共 31 个。固件 SHA-256、逐次 stdout、适用的 heap telemetry/compact
lifecycle 和 build-manifest 必须逐 workload 绑定；不能沿用旧固件哈希替代当前矩阵证据。
最终 clean run 正在重新生成；只有权威 JSON 可以声明 outcome。默认宿主时序的补充
集合为 9 个 profile、11 个 workload，不能替代全矩阵。
下表只把 core/型号这一事实记入“编译/链接状态”；库探针
也只代表编译/链接，实板列仍保持未验证。
ADC 位数为芯片原生分辨率；Arduino `analogRead()` 的默认返回分辨率为 10 位。

实验 C++ Arduino CLI 回归使用：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\test-cpp-arduino-cli.ps1
```

该脚本要求已准备好的 WSL/Ubuntu 锁定 Clang、LLVM-CBE 和补丁 SDCC 环境，并使用
无空格的工作目录。它的成功不能替代下面的实板步骤；24 MHz 和未显式选择
`cppcore=enabled` 的构建也不属于当前 C++ 资格范围。

逐配置 C++ build 矩阵使用 `scripts/test-cpp-all-variants.ps1`，compile/link/capacity
与 QEMU 结果必须从同一次保留的 build schema v2/runtime audit schema v4 JSON
同步生成 `tests/cpp/variant-matrix/results.json` 和 `tests/cpp/profiles.json`。
下表只描述资格方法，不在平台包内镜像瞬时 outcome：

| C++ 配置组 | compile/link/capacity | 精确 QEMU runtime | 当前结论 |
| --- | --- | --- | --- |
| 当前 C++ 范围：22 个物理型号、25 个执行配置、31 个 workload | 读取权威 JSON | 读取权威 JSON | 任一 required workload 失败或缺失，该 profile 就不能归一为 PASS；QEMU 不等于实板 |

| MCU | 执行模式 | ADC 支持 | 编译/链接状态 | 实板状态 | 建议实板检查点 |
| --- | --- | --- | --- | --- | --- |
| STC8H8K64U | `mcs51` | 是，原生 12 位 | 见机器可读矩阵 | 未验证 | P1.0/ADC0 三点采样；P5.4/ADC2；UART、GPIO、时基 |
| STC32G12K128 | `mcs251`（实验） | 是，原生 12 位 | 见机器可读矩阵 | 未验证 | 先确认启动和中断栈；P1.0/ADC0；UART、GPIO、时基 |
| STC32G144K246 | `mcs251`（实验） | 是，ADC1 原生 12 位 | 见机器可读矩阵 | 未验证 | QEMU 不覆盖 P8--PB、ADC/USB/CAN/DMA/PLL、电气与 cycle-exact 时序；仍需实板 |
| STC8H1K08 | `mcs51` | 是，原生 10 位 | 见机器可读矩阵 | 未验证 | P1.0/ADC0 与 P3.0/ADC8；小封装实际引脚；UART、时基 |
| STC8G1K08A | `mcs51` | 是，原生 10 位 | 见机器可读矩阵 | 未验证 | QEMU 不是实板证据；P3.0/ADC0 与 P5.4/ADC4；全部 6 路映射；UART、时基 |
| STC8G1K08 | `mcs51` | 是，原生 10 位 | 见机器可读矩阵 | 未验证 | P1.0/ADC0 与 P3.0/ADC8；稀疏封装引脚；UART、时基 |
| STC8G2K64S4 | `mcs51` | 是，原生 10 位 | 见机器可读矩阵 | 未验证 | P1.0/ADC0 与 P0.0/ADC8；跨端口通道；UART、时基 |
| STC32G8K64 | `mcs251`（实验） | 是，原生 12 位 | 见机器可读矩阵 | 未验证 | 先确认启动和中断栈；P1.0/ADC0；UART、GPIO、时基 |
| STC32CL8K64 | `mcs251`（实验） | 是，原生 12 位 | 见机器可读矩阵 | 未验证 | P5.4/ADC2；10 个逻辑 ADC 路由仅 8 个独立焊盘；启动与时基 |
| AI8051U-34K64 | `mcs51`；`mcs251`（实验） | 是，原生 12 位 | 见机器可读矩阵 | 未验证 | 两种模式分别启动；P1.0/ADC0；核对 P4.4/P4.5 共用焊盘和 P5 掩码 `0xCF` |
| STC8A8K64S4A12 | `mcs51` | 是，原生 12 位 | 见机器可读矩阵 | 未验证 | P1.0/ADC0 与 P0.0/ADC8；跨端口通道；UART、时基 |
| STC8C2K64S4 | `mcs51` | 否 | 见机器可读矩阵 | 未验证 | GPIO、UART、Timer0 时基；`analogRead()` 无效引脚应安全失败 |
| STC8H1K28 | `mcs51` | 是，原生 10 位 | 见机器可读矩阵 | 未验证 | P1.0/ADC0 与 P0.0/ADC8；实际封装引脚；UART、时基 |
| STC8H3K64S4 | `mcs51` | 是，原生 12 位 | 见机器可读矩阵 | 未验证 | P1.0/ADC0、P1.6/ADC6、P0.0/ADC8；稀疏通道；UART、时基 |
| STC32G12K64 | `mcs251`（实验） | 是，原生 12 位 | 见机器可读矩阵 | 未验证 | 先确认启动和中断栈；P1.0/ADC0；UART、GPIO、时基 |
| Ai8H2K12U | `mcs51` | 是，原生 12 位 | 见机器可读矩阵 | 未验证 | P1.0/ADC0、P5.4/ADC2；核对 P1.2/P5.4 共用焊盘；USB 型号供电 |
| Ai8H2K32U | `mcs51` | 是，原生 12 位 | 见机器可读矩阵 | 未验证 | P1.0/ADC0、P5.4/ADC2；核对 P1.2/P5.4 共用焊盘；UART、时基 |
| STC32G8K48 | `mcs251`（实验） | 是，原生 12 位 | 见机器可读矩阵 | 未验证 | 程序不得进入 FFC000 起的 EEPROM；P5.4/ADC2；核对 exact-QEMU oracle 与实板 |
| STC32CL8K48 | `mcs251`（实验） | 是，原生 12 位 | 见机器可读矩阵 | 未验证 | 48 KiB 程序上限；17 个物理 GPIO；核对 exact-QEMU oracle 与实板 |
| STC32F12K54 | `mcs251`（实验） | 是，原生 12 位 | 见机器可读矩阵 | 未验证 | 54 KiB 程序、8 KiB EDATA/4 KiB XDATA、3,584 B heap + 512 B 静态 reserve、44 GPIO |
| AI8051U-34K32 | `mcs51`；`mcs251`（实验） | 是，原生 12 位 | 见机器可读矩阵 | 未验证 | 两模式均限 32 KiB 程序；分别核对 exact-QEMU oracle 与实板 |
| AI8051U-34K16 | `mcs51`；`mcs251`（实验） | 是，原生 12 位 | 见机器可读矩阵 | 未验证 | 两模式均限 16 KiB Flash，compact 程序上限 14,336 B；分别核对 exact-QEMU oracle 与实板 |

## 实板测试顺序

每块板建议先使用相同的四阶段 core 用例，再按需要执行第五阶段库用例，并一次只增加
一个外设，便于定位启动、引脚映射、定时器占用或电气问题。

### 1. GPIO 与启动

1. 选择封装中真实引出的普通 GPIO。输出脚串联 330 Ω～1 kΩ 电阻接 LED，或接逻辑
   分析仪；输入脚用约 10 kΩ 上拉并用按键接地。
2. 上电后先输出固定启动标记，再以固定周期翻转；验证 `pinMode()`、
   `digitalWrite()`、`digitalRead()` 和无效引脚的安全返回。
3. 任何型号都不得让两个推挽输出直接对接，也不得超过芯片单脚和端口总电流限制。
4. STC32G144K246 的自动化门禁先检查 HEX 位于用户 Flash 高地址范围、复位入口、
   初始化段和中断向量；实板仍必须验证这些入口确实执行，再逐端口验证 P8、P9、
   PA、PB 的 XFR 输入/输出、模式、独立上拉以及 SETB/CLRB。
   普通 P0--P7 翻转或 CoreAPI 编译不能替代这项门禁。固定 runner、oracle、
   产物和日志最多证明 QEMU 已建模的 CPU/内存/UART1/Timer0/1/P0--P7 范围；当前
   outcome 见机器可读证据，且无论其值如何都不能
   推导 P8--PB、ADC、USB、CAN、DMA、PLL 或任何实板 PASS。

### 2. Timer0 时基

用 `delay(1000)` 每秒翻转一个引脚，同时记录 `millis()`；用示波器或逻辑分析仪测量
至少 60 个周期，并记录平均周期、最大偏差和是否发生跳变。下载工具配置的系统时钟
必须与板菜单中的 `F_CPU` 一致；内部 IRC 的误差也会反映在 UART 和时基结果中。
Timer0 是 core 时基资源，长时间关闭中断会造成 `millis()`/`micros()` 停顿；这类停顿
应单独记录，不能误判为晶振偏差。

### 3. UART1 / `Serial`

UART1 默认使用 P3.0（RX）和 P3.1（TX），并在启用时占用 Timer1。将 MCU TX 接到
USB-TTL 串口的 RX，并连接公共 GND；做接收测试时再将适配器 TX 接到 MCU RX。先用
较低波特率输出递增计数和校验字符串，再做回环、连续接收及缓冲溢出测试。

串口适配器必须是与芯片 I/O 电压兼容的 TTL 电平，不能直接连接 RS-232 电平。
下载器、自动复位电路或板载 USB 芯片可能同时占用 UART 引脚，测试前应断开冲突驱动。
### 4. ADC

22 个型号中有 21 个支持 ADC，使用现代 `ADCCFG` 寄存器布局实现。仅在表中
标记支持 ADC 的型号上测试。推荐使用 10 kΩ 线性电位器：两端接 VCC 和
GND，滑动端经 1 kΩ 保护电阻接被测 ADC 引脚，并确保测试仪器与 MCU 共地。先测量
实际 VCC，再依次输入接近 0%、50% 和 100% 参考电压，检查结果是否单调且位于合理
误差范围。输入电压绝不能低于 GND 或高于芯片允许的模拟输入上限。

`analogReference(DEFAULT)` 是当前支持的参考模式，不要把 Arduino AVR 板的 AREF
接法照搬到 STC。默认 `analogRead()` 返回 10 位结果；还应调用
`analogReadResolution()` 在 1--15 位范围内分别检查原生位数和较低位数。
无 ADC 型号、非法/非 ADC 引脚或转换超时返回 `-1`，不能把它当作采样值。
12 位型号请求 10 位时会舍弃低位。若高源阻抗导致读数
偏低或不稳定，应先降低信号源阻抗或使用缓冲器，再判断软件问题。

STC32CL8K64 暴露 19 个逻辑端口名，但 P1.4/P0.2、P1.5/P0.3 两对别名使其
只有 17 个物理 GPIO；其 `A2/A8` 与 `A3/A9` 也分别落在这两对焊盘上，
所以 10 个逻辑 ADC 路由只有 8 个独立物理输入。AI8051U-34K64 暴露 46 个
逻辑端口名、45 个物理 GPIO，P4.4/P4.5 在封装内硬短接且没有选择寄存器，
P5 有效掩码为 `0xCF`；
一个别名作为输出时，另一个必须保持高阻，禁止驱动相反电平。
Ai8H2K12U/Ai8H2K32U 的 P1.2/P5.4 共用焊盘，core 启动时临时置位
`P_SW2.7` 访问扩展 SFR，清零 `P_SWX1.0` 选择变体暴露的 P5.4，再恢复原
`P_SW2`。这些名称不能当作彼此独立的物理引脚使用；测试通道前必须按具体
封装图确认别名。

STC32G144K246 暴露 92 个逻辑端口名和 91 个独立物理 GPIO；P1.2/P5.4 只保留
P5.4，P1.3/P1.7 共用焊盘。当前 Arduino 映射只覆盖 ADC1 外部通道 0--10，
ADC2 与内部参考通道不在 `analogRead()` 范围内。core 不配置 PLL；48 MHz 以上
路径在公开前必须另行验证 PLL 启动、`F_CPU`、Timer0 时基和 UART 波特率。

### 5. 随平台库

- Wire：使用外部上拉和已知地址的 I2C 器件，分别验证写、读、重复起始、NACK 和
  时钟拉伸超时；逻辑分析仪同时确认 START/STOP、地址位和开漏电平。
- SPI：通过逻辑分析仪和可回读的从设备逐一验证模式 0--3、MSB/LSB、目标时钟及
  片选边界；片选由草图负责，不能把软件回环编译探针当作外设已通过。
- SoftwareSerial：先用 1200、2400、4800、9600 baud 和明显帧间空闲做单向测试，
  再做轮询回显；记录起始位、数据位和停止位宽度、误码及中断抖动。发送期间到达的
  RX 字节预期会丢失，不能用连续双向流量验收。另需注入错误停止位和缓冲溢出，检查
  `framingError()`/`overflow()`；停止 Timer0 或关闭 `ET0`/`EA` 时调用应失败并由
  `timingError()` 报告，不能永久阻塞。两端必须共地且使用兼容的 TTL/CMOS 电平，
  绝不能把正负电压的 RS-232 直接接到 GPIO。
- LiquidCrystal：分别检查 4 位与 8 位接法、R/W 接地和显式 R/W 引脚、1/2/4 行地址、
  清屏/归位、光标/闪烁、滚动及 8 个自定义字符。当前只支持单控制器且最多 80 个
  DDRAM 字符，不把双 Enable 40x4 模块记为通过；`begin` 设置几何默认行偏移，
  public `setRowOffsets(...)` 可按实例覆盖，`init(...)` 重新接线并初始化为 16x1。
  构造器只记录引脚，必须在 Core 启动后调用 `begin`/`init`。`println()` 发送 CR/LF 数据字节，
  不代表 LCD 自动换行。
- Stepper：MCU 只能连接匹配的晶体管、H 桥或专用驱动器逻辑输入，禁止把绕组直接接
  GPIO。先断开机械负载，用示波器确认 2/4/5 线相序、步进间隔和正反向，再接电机核对
  一圈步数、失步、驱动电流和温升；当前实现没有加减速、细分或堵转保护。
- SD：首轮使用单独供电稳定、已备份并用 FAT16/FAT32 格式化的小容量 SD/SDHC 卡，
  先验证初始化和已知根目录 8.3 文件的长度、顺序读取、EOF、跨扇区/跨簇读取与 seek，
  再分别验证 MBR 分区卡和 super-floppy。逻辑分析仪确认上电后至少 74 个空闲时钟、
  mode 0、MSB-first、初始化低速、命令/数据期间 CS 边界及所有失败出口 CS 回到高电平。
  STC8H8K64U 与 STC32G12K128 必须分别实测；MCS251 还需覆盖 FAT 小端字段解析。
  原始 `writeBlock()` 只能用可丢弃测试卡和专用 LBA，绝不能在含重要文件或已挂载 FAT
  元数据范围内试写。裸卡按 3.3 V 电气要求连接，不能把不兼容的 5 V GPIO 直接接卡。

## 记录与通过准则

每次实板验证至少记录以下信息：

- MCU 完整丝印、封装、批次和板卡版本；
- 仓库提交、未提交补丁、FQBN、执行模式、内存模型和 `F_CPU`；
- 供电电压、时钟源、下载工具及配置、串口适配器电平；
- 测试草图或其哈希、生成的 HEX、编译器版本；
- GPIO 波形、60 秒时基统计、UART 收发日志、ADC 输入电压与原始读数；
- 若验证随平台库，记录所用库/示例、引脚、外设或驱动器型号、总线/相序波形和边界
  测试结果；
- 通过、失败或受限结论，以及失败可复现步骤。

只有启动、GPIO、时基和该型号声明支持的 UART/ADC 检查均完成，且证据能够对应到
准确的芯片和构建配置时，才可把表中的“实板状态”改为“通过”。`mcs251` 配置还必须
覆盖中断进入/退出和较深调用栈；只看到一次 GPIO 翻转不足以解除其实验状态。
