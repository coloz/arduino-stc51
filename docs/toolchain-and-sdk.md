# 工具链与 SDK

当前 Arduino 架构为 `mcs251`，唯一编译目标为 `-mmcs251`。维护型号见 `tools/variants/devices.json`。

当前生产发布只考虑 Windows 和 macOS，Linux 独立宿主已退出本次适配与验收范围。WSL 继续用于 Windows C++ 的内部工具依赖和目标模拟测试，详见[发布宿主范围](release-host-scope.md)。

## 编译路径

Plain C 由 SDCC C251 编译；C++11 经定制 Clang、LLVM、LLVM-CBE 转为经审计的 C，再由 SDCC 编译链接。Windows 的 C++ 配方通过 WSL 调用 Linux 工具；Linux 和 ARM64 Mac 直接启动各自受锁定的原生工具。入口均验证启动标记并保留参数边界。Linux 开发入口是相邻 `stcxx/out/bin/sdcc`，可通过 `STCXX_TOOLCHAIN_ROOT`、`STCXX_SDCC` 等覆盖，但实际二进制必须符合相应宿主的工具锁。

`tools/cpp-cli/toolchain-lock.json` 绑定 Linux/WSL 驱动、适配器、编译器和 MCS251 运行库的哈希。源码目录保留开发工具锁；`package-platform.ps1 -LinuxToolchain portable` 明确选择 `toolchain-lock.linux-x86_64.json` 为归档中的标准运行锁。ARM64 Mac 使用独立的 `toolchain-lock.macos-arm64.json`。Mac 与可分发 Linux 前端在运行前检查完整文件清单，包含私有动态库和资源头文件。修改 helper 后需更新路径对应的哈希并重新验证；不应改写历史实验记录的哈希。异常、RTTI 和完整 STL 不在该 freestanding ABI 中。

G12K128/G144K246 的完整 Flash 布局需要 `--function-sections`、`--data-sections` 和链接窗口支持。固定的旧上游 Windows 包不包含全部源码改进；旧工具会被能力检查拒绝，不能通过删选项绕过。当前源代码的 C++ 路径使用已锁定的重建编译器。宿主构建方法见 `scripts/build-linux-toolchain.sh`、`scripts/build-macos-toolchain.sh` 和 `tools/toolchain-patches/README.md`。

Mac C++ 入口需要 Bash 4.4+、GNU coreutils 和 Python 3，具体路径配置见[C++ 驱动说明](../tools/cpp-cli/README.md)。当前前端面向 macOS 15 / Apple Silicon；Intel Mac 及其他系统版本需要各自的工具包和验证。

## 生成 ARM64 Mac 安装候选

源码仓库中的 `scripts/create-macos-candidate-index.py` 供发布维护者使用，从 SDK 归档读取版本和所选宿主的运行锁，拒绝不匹配的 SDCC/前端归档。默认宿主为 ARM64 Mac。先将三个归档放在同一资产服务目录，再从 arduino-stc51 源码根目录生成索引。例如：

```sh
python3 scripts/create-macos-candidate-index.py \
  --platform "$STC_ASSETS/arduino-stc51-0.0.3.tar.bz2" \
  --sdcc "$STC_ASSETS/sdcc-mcs251-macos-arm64-b09075b6a93e6afe10645181e3aeff041ea37f87-r9.tar.bz2" \
  --frontend "$STC_ASSETS/stcxx-frontend.tar.bz2" \
  --sdcc-version 4.6.0-mcs251-20260804-r9 \
  --base-url http://127.0.0.1:8000 \
  --output "$STC_ASSETS/package_arduino-stc51_candidate_index.json"
```

`STC_ASSETS` 是归档所在目录。生成器只写新索引，拒绝覆盖已有文件；服务 URL 允许 HTTPS 或用于本地测试的回环 HTTP。配置 Arduino CLI 的 `board_manager.additional_urls` 指向该索引，再执行 `core update-index` 和 `core install arduino-stc51:mcs251@0.0.3`。生成索引本身不上传资产，也不授予生产发布资格；每个候选索引只包含所选宿主。

Windows 候选使用 `--host x86_64-mingw32`，除 SDK、原生 Windows SDCC ZIP 和 WSL 前端外，还需通过 `--wsl-sdcc`、`--host-tools` 提供锁定的 WSL SDCC 和 BusyBox 归档。SDK 打包使用现有的 `-LinuxToolchain portable` 参数选择 WSL 所需工具锁；此参数名保留兼容性，不表示增加 Linux 发布宿主。生成器绑定四个工具的准确版本与摘要；新编译器完成验证并更新锁之前，不应将私有测试目录当作正式候选。

## 来源和依赖

下载资产、版本、许可证、URL 和 SHA-256 位于 `tools/toolchain-manifest.json` 和 `sdk/manifest.json`。独立维护的 STC8 SDK 和 AI8051U 8 位库资产已退出平台参考清单。保留 STC32、AI8051U C251 SDK 和相关 USB/ISP 资料。

本地通用宿主工具名为 `STCHostTools`，归档工具名为 `SDCCArchiveTools`；它们用于运行脚本和生成 core.a。上游不可变下载文件的原名、SDCC 版本字符串和共享 `include/mcs51` 目录仍保留。这些公共依赖也是 MCS251 后端所需，不能仅按名字删除。

Keil C251 的对象、运行库或内存模型不等同于本 SDCC ABI。官方 SDK 是寄存器及算法参考，不自动成为可链接的 Arduino 库。实际产品板按[硬件验证说明](hardware-validation.md)验收。
