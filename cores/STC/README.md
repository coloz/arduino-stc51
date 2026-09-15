# STC MCS251 core

当前核心只支持 STC32 和 AI8051U 的 MCS251 执行配置。能力来自生成的 board flags，不根据不存在的旧系列猜测寄存器布局。引脚、时钟、ADC/PWM/总线及中断语义见 [实际开发说明](../../docs/arduino-practical-api.md)。
