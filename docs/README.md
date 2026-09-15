# 使用文档

当前源码版本为 0.0.3，尚未正式发布。平台仅维护 MCS251 型号；使用与实物型号、时钟和接线对应的配置。

- [实际开发说明](arduino-practical-api.md)：GPIO、串口、总线、时钟与内存使用。
- [API 兼容范围](core-api-compatibility.md)：已提供的 Arduino API 及边界。
- [库兼容说明](library-compatibility.md)：外设库、文件系统和第三方库移植。
- [C++ 运行时约定](cpp-runtime-contract.md)：数据布局、调用约定和资源限制。
- [工具链与 SDK](toolchain-and-sdk.md)：工具锁、源码构建与安装包生成。
- [宿主范围](release-host-scope.md)：Windows、WSL 和 macOS 的要求。
- [型号配置](variants-mcs251.md)：板项、存储布局和引脚元数据。
- [应用范围](application-scope.md)：根据功能与容量选择配置。
- [硬件验证](hardware-validation.md)：将生成的固件用于产品板前的验证步骤。

版本变化见根目录的 [RELEASE_NOTES.md](../RELEASE_NOTES.md)；维护和 CI 回归命令见 [tests/README.md](../tests/README.md)。
