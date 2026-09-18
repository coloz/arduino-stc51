# Native driver validation

Windows x64, 2026-09-17. These are compiler/linker checks, not hardware tests.

## Completed checks

- `cargo test --locked`: 7 passed. The ignored subprocess fixture is explicitly
  launched by the subprocess test; it verifies Unicode, whitespace, quotes,
  literal shell metacharacters, stdout/stderr and exit status 7.
- `cargo clippy --locked --all-targets -- -D warnings`: passed.
- Cache hash tampering and missing members are rejected. Archive traversal is
  rejected. Failed link setup removes an existing HEX output.
- PE imports for the native driver contain only Windows system DLLs; there is
  no Python, MSVC C++ runtime or dynamic C runtime dependency.
- Unpacked native platform and toolchain compiled Blink through the packaged
  Arduino recipes. This caught and corrected the required SDCC `libexec/cc1`
  packaging dependency; the final payload includes and hashes it.
- The active Arduino installation compiled the examples below without compiler
  overrides. A second Blink compile reused both its object and the standard
  cached `core.a`; ButtonMouse and KeyboardMouse reused that same core.
- Native installation payloads contain no Python, PowerShell or shell scripts.
  Verbose compilation logs contain native driver/compiler commands and no
  legacy interpreter invocation. Rust and Node are only development tools.

| Sketch | Board | Program bytes | Result |
| --- | --- | ---: | --- |
| Blink, cold and cached | STC32G12K128 | 6269 | Pass, active installation |
| ButtonMouse | STC32G12K128 | 16140 | Pass, active installation |
| KeyboardMouse | STC32G12K128 | 20672 | Pass, active installation |
| RawHID | AI8051U-34K16 | 12477 | Pass, active installation |
| NativeCpp | STC32G12K128 | 37310 | Pass, development driver |
| ArduinoJson JsonParserExample | STC32G144K246 | 95399 | Pass, development driver |
| NativeDisplay (U8g2/U8x8) | STC32G144K246 | 53869 | Pass, development driver |
| NativeTrim | AI8051U-34K16 | 3277 | Pass, development driver |

NativeCpp exercises virtual methods/destructors, member-function pointers,
global/local initialization, allocation, String, Serial and floating point.
NativeTrim checks removal of an unused font and function while retaining shared
private state and a callback initializer in a single C translation unit.
NativeDisplay exercises real library C closure selection and font pruning.
Hardware-specific SDCC branches that Clang cannot safely analyze are retained.

Full logs and link audit manifests are in the checkout's `.tmp/native-driver/`
directory; `scripts/check-installed-native.mjs` reproduces the installation checks.
`scripts/check-native-package.mjs` checks an unpacked candidate in a separate
sketchbook, while `scripts/check-native-driver.mjs` selects a development sketch.

## Boundaries

The native driver is 0.2.0. Release 0.0.6 packages it for Windows x64 with
stcxx-toolchain 0.2.0 and stc-cli 0.1.0-stc.2, alongside a separately built
Apple Silicon driver and tools. The earlier local validation used
an override of platform 0.0.5 and tool directory 0.1.0; its previous installation
is retained outside Arduino15 in `Arduino15-native-backups`. Release qualification
uses an isolated Arduino installation and is attached separately to the release.

No firmware was flashed in these driver checks. Apple Silicon release qualification
is performed on macOS and recorded in the release attachments. This sample set does not establish compatibility
with every third-party library or every C++ construct. Unsupported IR, bridge
warnings or storage/alignment checks fail explicitly; no interpreter fallback is
used. Legacy migration scripts and compiler rebuild materials have been removed
from this SDK. The SDK consumes prebuilt compilers verified by its native host
locks; rebuilding those compilers belongs to the separate compiler project.
