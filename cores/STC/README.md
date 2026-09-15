# STC MCS251 core

当前核心只支持 STC32 和 AI8051U 的 MCS251 执行配置。能力来自生成的 board flags，不根据不存在的旧系列猜测寄存器布局。公共接口见 [Arduino.h](Arduino.h)，具体引脚与外设能力以各型号的 `pins_arduino.h` 为准。
