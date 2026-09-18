# USB CDC / HID 验证记录

验证日期：2026-09-17。软件测试通过不代表所有芯片都已经完成实板验证。

## 自动化协议测试

在 WSL GCC 下运行真实 C 驱动，使用模拟 USB 寄存器/FIFO，并启用
AddressSanitizer、UndefinedBehaviorSanitizer、`-Wall -Wextra -Werror`：

```text
wsl -e python3 /mnt/d/Git/stc51/arduino-stc51/scripts/check-usb-cdc.py
```

通过范围：G12、G144、AI8051U 的 CDC、HID、CDC + HID；16 KB 型号的
CDC-only / HID-only 配置；无 USB 型号的编译保护；C++ Stream/Print API 与 Serial 别名。
覆盖描述符与接口路由、EP0 多包和中断事务、无效请求 STALL、line coding、DTR/RTS、
BREAK、128 字节缓冲区边界和 RX 背压、短写和发送超时、整包 ZLP、flush、挂起/恢复、
总线复位、1200 bps 重启及取消/禁用、HID 报告和 LED 输出、UART1 引脚冲突保护。

`stc-cli` 的 `cargo test --locked`：74 个库测试、8 个命令行单元测试、
2 个集成测试通过。覆盖新 CDC 的 1200 bps 上传路由以及原有 ISP 协议回归。
`scripts/check-upload.py` 的 10 种板型上传配方测试通过，包含路径空格、无 COM 的 HID
下载入口及错误 HEX 在访问设备前拒绝；这些检查不会向硬件写入固件。

## 真实工具链编译

`node scripts/check-usb-build.mjs` 使用 Arduino CLI、原生 stcxx 驱动与 SDCC，
直接编译当前工作区。2026-09-17 的 13 组结果全部通过：

| 芯片 / 配置 | 示例 | 程序字节 |
| --- | --- | ---: |
| G144 / CDC | CDCSerial | 24885 |
| G144 / CDC、48 MHz、高地址 XRAM | CDCSerial | 24885 |
| G144 / 显式 USBSerial | CDCSerialEcho | 18615 |
| G144 / CDC + HID | CDCKeyboardMouse | 33336 |
| G12K128 / CDC | CDCSerial | 22261 |
| G12K64 / CDC | CDCSerial | 22273 |
| AI8051U-34K64 / CDC | CDCSerial | 22556 |
| AI8051U-34K32 / CDC | CDCSerial | 22556 |
| AI8051U-34K16 / CDC-only | CDCMinimal | 16062 |
| G12K128 / HID | ButtonMouse | 20288 |
| AI8051U-34K16 / HID-only | RawHID | 15218 |
| G12K128 / CDC + HID | RawHID | 21472 |
| G8K64 / 无 USB | Blink | 6249 |

AI8051U-34K16 的最小 CDC 回显已占用约 98% Flash，不适合较大应用。
这些字节数受工具链、优化选项及示例修改影响；不应作为固定 ABI 或容量承诺。
本机 Arduino 已安装更新后的核心、示例和上传器，旧文件另行备份；使用已安装平台
再次编译 G144、48 MHz、CDCSerial 通过（24885 字节）。重启 IDE 后可刷新 CDC 菜单。

## Windows 实板测试

目标：用户连接的 STC32G144K246，已通过出厂 HID 确认 F8D1、BSL 7.5.1U、48 MHz。
P3.2 配合断电重插进入 ISP 后完成烧录。独立 CDC 枚举为 COM6（1209:0002），
CDC + Keyboard + Mouse + RawHID 枚举为 COM7（1209:0003）；Windows 设备状态均为正常。

**默认 XRAM 布局未通过本板实测。** 首次二进制测试在 64 字节包的第 6 字节发现
`DB → CB` 的位错误，GPIO 切换计数也异常。保持同一源程序、CPU 时钟、工具链及 USB
实现，仅将 XRAM 从默认低地址区域改到 `020000..02FFFF`（64 KiB）后，下面的完整测试通过。
这一结果与工作区 `stc-cli/docs/HARDWARE_STC32G144_USB.md` 的既有内存访问记录一致，
但尚未确定底层原因，不能推广为所有 G144 的问题，也不能据此认定物理损坏。

已增加仅针对 G144 的 **XRAM layout → High bank 64 KiB (0x020000)** 菜单供本板使用，
保留默认 128 KiB 布局。测试不修改 ISP 时钟、校准值或硬件选项。

| 实测项目 | 结果 |
| --- | --- |
| 独立 CDC / 复合设备枚举、UTF-8 中文 | 通过 |
| 1、7、63、64、65、127、128、129、255、256、512、1024、4096、8192 字节回显 | 逐字节一致 |
| `@STCISP#`、NUL、FF 作为普通数据 | 通过，不触发重启 |
| 256 KiB 连续二进制回显 | 两种配置各一轮通过，零错字节 |
| 实测回显吞吐 | 独立 CDC 约 7.6 KB/s，复合约 6.0 KB/s；含此测试程序和主机开销 |
| 暂停应用接收 250 ms 后继续收取 4096 字节 | 无丢失，背压通过 |
| 9600 8N1、230400 7E2、115200 8N1 主机设置 | 设备查询值正确 |
| DTR 关闭/打开、BREAK 开始/结束 | 通过 |
| RTS | 有限制：单独更改不立即更新，下一次 DTR 切换后设备收到正确值 |
| millis / GPIO 软件调度 | 主机 3 秒对应 2988 ms、29 次 P5.2 切换；不代表电气测量 |
| 串口关闭/重开 5 次、Serial.end/begin | 通过 |
| USBDevice.detach/attach 重新枚举 | 通过 |
| 禁用重启钩子后用 1200 bps、再恢复钩子 | 通过 |
| 1200 bps 自动进入 ISP 并下载运行 | 独立 CDC → CDC、CDC → 复合设备、复合设备 → CDC 均通过 |
| RawHID + CDC | 64 组 8 字节 RawHID 回显，交替传输 64×129 字节 CDC，全部一致 |
| 键盘 / 鼠标 | Windows 枚举正常，发送释放/静止报告；未执行实际按键或光标移动 |

RTS-only 的即时控制未通过，不将这一项计为完全通过；测试 JSON 保留即时观察值及
DTR 切换后的观察值。协议模拟中独立 SET_CONTROL_LINE_STATE 请求处理通过，
实板表现与本机主机驱动延后发送相符，但没有 USB 总线抓包用于最终归因。

原始证据位于工作区 `.tmp/usb-cdc/`：

- `cdc-default-result.json`：默认布局失败记录。
- `cdc-high-final-result.json`：独立 CDC 的 13 项检查。
- `composite-high-result.json`：复合设备的 14 项检查及 HID 接口信息。
- `flash-cdc-default/`、`flash-cdc-high/`、`flash-composite-high/`：烧录 JSON、固件 SHA256、HID 原始报告与独立审计结果。
- `flash-chinese-arduino/`：最终通过本机已安装平台的 Arduino CLI 自动上传记录；由 COM7 自动进入 ISP，下载后返回 COM6。
- `chinese-final-result.json`：最终用户程序的 6 条连续中文输出及主机时间戳。

前三轮烧录各有 1460 个 128 字节块，独立检查确认线上的数据与 HEX（空洞补 FF）完全一致，
所有编程块收到 `02 54` 确认，帧校验和正确，没有发送 `04` 硬件选项写入命令。
三次烧录前 STATUS 的已知时钟、校准和选项字节一致；最后两个未分类字节不据此解释。
这是下载协议确认和运行验证，不是独立 Flash 回读。

最终板上保留用户的 P5.2 闪灯程序：HIGH 2 秒、LOW 2 秒、`Serial.println("你好啊")`。
使用本机已安装平台、`cdc=enabled,clock=48m,xram=high` 编译通过，代码 24710 字节；
已安装平台和工作区生成的 HEX 哈希相同。通过 Arduino 的默认 Automatic 上传配方完成下载，
上传器自动从复合 COM7 切入出厂 HID，再运行到独立 CDC COM6，全程无需再按按键。
在 COM6 / 115200 下连续捕获 6 条完全正确的 UTF-8 输出，间隔 4.015～4.016 秒。
最终 HEX SHA256：`579ad79cbf19841c2b44a4159585bdc92b9cb68368ecb733230c16f9ab24b8e9`。
测试结束已关闭串口句柄，未占用串口监视器；P5.2 的物理灯光仍需人工观察。

可复现测试固件：`scripts/tests/usb/HardwareValidation/HardwareValidation.ino`。
测试只发送静止鼠标报告和全部释放的键盘报告，不输入文字或移动光标。

```text
arduino-cli compile --config-file .tmp/usb-cdc/arduino-cli.yaml --fqbn stc:mcs251:stc32g144k246:cdc=enabled,clock=48m,xram=high --build-path .tmp/usb-cdc/hardware-cdc scripts/tests/usb/HardwareValidation
python -m pip install pyserial hidapi
python scripts/check-usb-hardware.py --port COMxx --output .tmp/usb-cdc/hardware-cdc-result.json
```

CPU 时钟必须匹配实际 ISP 配置；上面的 48 MHz 已在这块板上读出，其他板仍需读取确认。
复合设备编译追加 `--build-property build.extra_flags=-DUSB_TEST_COMPOSITE=1`，
测试追加 `--composite`。测试脚本不会烧录或主动进入 ISP，但会测试软件 detach/attach；
需要先通过 STC ISP 烧录对应固件。脚本校验显式选择的端口及 VID/PID，并保存 JSON 结果。

该测试不覆盖 GPIO 的外部电气测量、ADC 精度、UART 外接回环、I²C/SPI/CAN 外设，
也不覆盖其他型号实板或 Linux/macOS 的 USB 驱动。P5.2 切换计数只是软件证据，
不能代替目视、示波器或逻辑分析仪测量。
