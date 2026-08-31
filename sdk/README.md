# STC 上游 SDK 清单

本目录只保存可审计的上游资产元数据，不复制 STC 的 SDK、`.LIB` 或 AiCube-ISP 二进制文件。

- [`manifest.json`](manifest.json) 固定了截至 2026-08-31 已核验的官方 URL、版本／包内更新时间、字节数和 SHA-256。
- [`downloads/`](downloads/) 是可选的本地下载缓存，目录内容默认被其局部 `.gitignore` 忽略。
- 下载脚本位于 [`../scripts/fetch-stc-sdk.ps1`](../scripts/fetch-stc-sdk.ps1)，下载目录必须由调用者显式指定。

完整的工具链选择、兼容性和许可说明见 [`../docs/toolchain-and-sdk.md`](../docs/toolchain-and-sdk.md)。
