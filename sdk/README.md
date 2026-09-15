# STC 上游 SDK 清单

本目录只保存可审计的上游资产元数据，不复制 STC 的 SDK、`.LIB` 或 AiCube-ISP 二进制文件。

- [`manifest.json`](manifest.json) 固定了截至 2026-08-31 已核验的官方 URL、版本／包内更新时间、字节数和 SHA-256。
- [`downloads/`](downloads/) 是可选的本地下载缓存，目录内容默认被其局部 `.gitignore` 忽略。
- 下载脚本位于 [`../scripts/fetch-stc-sdk.ps1`](../scripts/fetch-stc-sdk.ps1)，下载目录必须由调用者显式指定。

编译工具配置见 [C++ 驱动说明](../tools/cpp-cli/README.md)，第三方许可见 [LICENSES](../LICENSES)。官方 SDK 仅作为寄存器及算法参考；Keil C251 对象和运行库不能直接当作 SDCC ABI 的 Arduino 库链接。
