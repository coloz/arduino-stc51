# Maintained regression tests

Run from the repository root on Linux/WSL with Python 3, GCC/G++, Clang and sanitizers:

```sh
python3 scripts/check-host-regressions.py --output .build/host-regressions
```

If Clang is installed outside PATH, set `STCXX_TEST_CLANG` to its executable.
The C function-closure tests execute both the original and trimmed source to
check shared file state, static locals and callbacks retained by initializers.

This CI entry point saves source hashes, logs and exit codes, and rejects
source changes during a run. Individual suites can also be run directly:

```sh
python3 scripts/check-core-runtime.py
python3 scripts/check-library-runtime.py
python3 scripts/check-stepper-runtime.py
python3 scripts/check-serial-runtime.py
python3 scripts/check-serial-arithmetic.py
python3 -m unittest discover -s tests -p 'test_*.py' -v
```

Before packaging, verify that both host builders and all three SDK compiler
locks select the same source patch. In a workspace with a prepared sibling
stcxx checkout, also check its reproduction scripts, source lock, published
development driver and core/SDK bindings:

```sh
python3 scripts/check-toolchain-build-inputs.py
python3 scripts/check-toolchain-build-inputs.py --compiler-root ../stcxx
```

The second command checks the development publication; it does not substitute
for `../stcxx/arduino/scripts/check-sources-wsl.sh`, the full executable inventory,
fresh installation, target execution or physical board qualification.

The serial host model compiles the actual C APIs and ISR against shared byte
registers under ASan/UBSan. It covers receive buffers of 2, 16 and 255 bytes,
polling lookahead, overflow, wraparound, restart and the UART-disabled branch.
It does not model electrical UART timing. The explicitly selected `SerialReceive`
target probe separately checks 43 native C/C++ receive operations against a
test-only seeded ring; physical UART reception still requires hardware tests.

The arithmetic suite extracts the three actual buffered Serial baud functions
and uses explicit `uint32_t` host values for the target's `unsigned long`.
Independent exact integer oracles check 617 rounding/tolerance/configuration
cases and 2,000,000 deterministic random pairs under UBSan. Use `--source`
to check an isolated `HardwareSerial.c` candidate and `--output` with a new
directory to retain the generated source, oracle cases, logs and input hashes.
The unified entry saves these in its `serial-arithmetic` subdirectory. Target
integer widths, ABI behavior and physical baud timing require separate checks.

The host library suite compiles the actual `SD.c`, `SDClass.cpp`, String,
Print and Stream implementations. Only GPIO/time and block storage are modeled.
It covers FAT16/FAT32 multi-cluster writes, remount/readback, append, overwrite,
remove, stale handles across 65536 opens, copy/move lifetime and injected write
failures. Host integer widths do not certify the MCS251 ABI or hardware timing.

The Stepper suite compiles the actual C implementation and C++ facade with
ASan/UBSan. Its GPIO/time model checks every pin position and pair for invalid
pins, duplicates and physical aliases; rejected configurations must leave state
and outputs unchanged. It verifies the open-drain/LOW/output setup order,
release/detach, all 2/4/5-wire phases in both directions, speed rejection and
recovery, one-microsecond clamping, delay chunking, unsigned-long rollover,
indirect C table calls, copied objects, and another motor called from `yield()`.
Only operations with no yield/callback boundary cache the current context;
stepping and waiting continue to resolve the context across yield boundaries.

Build the target String/Stream and SD facade smoke through the normal installer:

```powershell
$env:STCXX_WSL_DISTRO = 'Ubuntu'
$build = .\scripts\build-example.ps1 `
  -Fqbn 'arduino-stc51:mcs251:stc32g12k128:cppcore=enabled,clock=12m' `
  -SketchPath .\tests\target\ProductionSmoke
```

Build the long-running File lifecycle probe with unchanged production class
sources and a deterministic C backend (no SD card accessed):

```powershell
$build = .\scripts\build-file-lifecycle.ps1
```

The latter copies the exact production class into an isolated sketch and
checks its source hashes before and after compilation. Its test backend
models open/close/write failure only; the host FAT suite covers the real FAT
backend. These probes are not user application examples.

Run either HEX with a QEMU binary built from the documented MCS251 patches:

```sh
python3 scripts/check-qemu-smoke.py \
  --qemu /path/to/qemu-system-mcs251 \
  --firmware /path/to/ProductionSmoke.ino.hex \
  --board stc32g12k128 \
  --expected tests/target/ProductionSmoke/expected-uart.txt \
  --output .build/qemu-production-smoke
```

For the lifecycle probe, use its HEX and `tests/target/FileLifecycle/expected-uart.txt`.
For C++ return-value address identity, build `tests/target/ReturnIdentity`
through `build-example.ps1` and use its `expected-uart.txt`. This checks direct,
cross-translation-unit and indirect returns, copy/move construction and 1000
repeated returns on the actual target. The companion compiler regression is
`../stcxx/arduino/scripts/check-cbe-return-identity.py`; its host execution
isolates the CBE lowering and does not replace the target check.
Use WSL paths when running under WSL. The runner verifies the complete UART
transcript, imposes a deadline and saves hashes of the firmware, emulator,
oracle and output. It does not program a physical board. Use a new output
directory to retain each prior run's evidence.

Tests belong in version control and CI. The board-package allow-list excludes
them; build outputs remain under `.build/` and are ignored by Git.

For a locally staged Windows toolchain candidate, pass its manifest explicitly.
Put each candidate archive beside that manifest; size and SHA-256 are checked.
Use `-BuildProperty` to select the candidate's own archive helper and retain the
returned installation record with the qualification report:

```powershell
$build = .\scripts\build-example.ps1 `
  -ToolManifestPath C:\work\candidate\toolchain-manifest.json `
  -BuildProperty 'compiler.ar.path={runtime.tools.sdcc-mcs251.path}/bin'
python scripts/qualify-release.py --platform $build.platform --config $build.config `
  --stc C:\tools\stc-cli.exe --output .build\candidate-qualification `
  --host windows-x86_64-native --all-clocks `
  --build-property 'compiler.ar.path={runtime.tools.sdcc-mcs251.path}/bin'
```

This covers plain-C Blink for every declared board and clock. The report binds
the actual installed compiler, archive helper, libraries and CLI binaries, and
rejects a changed toolchain, local platform override, selected clock, or
inconsistent programmer validation. It does not certify C++ or hardware.
Candidate staging and deterministic ZIP tools are maintained in
`../stcxx/arduino/scripts/publish-windows-sdcc.py` and
`../stcxx/arduino/scripts/archive-sdcc-candidate.py`.

Run the maintained C++ ABI baseline against an independently staged platform
and its matching locked native SDCC/frontend candidate:

```sh
python3 scripts/check-cpp-targets.py \
  --platform /path/to/staged/platform --config /path/to/arduino-cli.json \
  --cli /path/to/arduino-cli --frontend /path/to/stcxx-frontend \
  --qemu /path/to/qemu-system-mcs251 --stc /path/to/stc-cli \
  --output .build/cpp-targets
```

The default is ReturnIdentity and NativeCallbacks at O0/Oz on every declared
C++ board and clock: currently 48 builds. Each build checks the actual Arduino
properties, module optimization, firmware/manifest binding, device Flash
window and capacity, complete QEMU UART output, and offline programmer result.
The allocated Flash reported by Arduino may include alignment padding absent
from HEX; both quantities must fit the actual device budget. Build failures
remain failures. Complete source, helper, configuration and tool inventories
are checked again after the matrix, including the explicit frontend directory.

Use repeatable `--board`, `--clock`, `--probe` and `--optimization` options for
diagnosis. A passing subset has `full_baseline_coverage: false` and cannot stand
in for the complete baseline. A rerun retains earlier per-run directories and
replaces the top-level report with the new RUNNING/PASS/FAIL result. The runner
rejects ambient `STCXX_*` overrides; select its frontend explicitly.

On WSL, a Windows `stc-cli.exe` can be selected with `--stc-windows-paths`.
Only offline `validate` and `--version` commands are issued. The runner keeps
the `wslpath` multicall name and records its executable identity; no serial
port is opened. A corrupted HEX must be rejected before builds start.

The separate six-library configuration/lifecycle matrix is maintained in
`scripts/check-library-targets.py`. Neither matrix grants physical peripheral,
timing, SD-media or overall production qualification. Unit tests of these
runners use simulated tools and are included in the host CI regression suite;
their success is not target-execution evidence.

The library runner accepts `--qemu-timeout SECONDS` (default 180). The value
must be finite and greater than zero, at most 3600 seconds; it is recorded in
the report and applied to each QEMU case. This bounds host execution time and
does not relax the complete UART oracle or qualify physical peripheral timing.
The standalone `check-qemu-smoke.py` default remains 60 seconds.

Select `--probe HeapTelemetry --board stc32g12k128 --clock 12000000` with the
same C++ runner for the additional allocator regression at O0/Oz. It checks
allocation before `setup()` in a global constructor, realloc data retention,
free/coalescing, full-arena exhaustion, and telemetry low-water marks. Its
native C companion injects seven malformed free-list states and verifies
rejection without exposing a successful snapshot; invalid telemetry remains
invalid after repairing only the free list, until full reinitialization.
The expected UART contains 57 checks. This explicitly selected test does not
change the default 48-case ABI baseline or imply coverage of other boards.
The corruption companion belongs only in test firmware.

The native heap always initializes before global constructors and takes its
initial integrity snapshot. Sampling/query routines live in the separate
`stcxx_heap_telemetry.c` archive member, which should be absent from programs
that never use allocator sampling or telemetry, and selected exactly once
when these routines are used. Target link maps and the existing heap-provider
audit must confirm both the selection and the unchanged arena/state sizes.

Select `--probe StepperPhases --board stc32g12k128 --clock 12000000` with the
C++ target runner to execute 73 additional checks at O0/Oz. This sketch uses
the real Stepper library, GPIO reads/writes and timing core: it checks all
2/4/5-wire winding patterns forward/reverse, disabled motion, speed recovery,
release, and copied-object phase independence. Its five pins are P1.3, P1.4,
P1.5, P1.6 and P3.5; UART1 is left for the test oracle. QEMU execution validates
the emulated output levels, not a motor's electrical/mechanical behavior.
This explicit probe does not replace the 48-case ABI or six-library matrices.

Select `--probe SmallControl --optimization z` with the C++ runner for the
basic application matrix on all declared C++ board/clock profiles. Add
`--board ai8051u_34k16` for the 16 KB device alone. The sketch checks the real
Arduino C++ UART facade, GPIO P1.3, millisecond scheduling, microsecond delay,
and eight output transitions (14 checks total). It does not require an SD
filesystem, motor objects or a combination of libraries. The existing gate
still checks actual Flash capacity, HEX addresses, the complete UART oracle,
offline programmer validation and source/tool identities.

Apply the [application scope](../docs/application-scope.md) when assessing
release readiness: a complex probe that exceeds a small chip's capacity is
retained as a failed workload, while the intended application has its own
required tests. A passing small application does not convert other failures
into passes or qualify physical timing, electrical behavior or every library.

`python3 scripts/check-toolchain-build-inputs.py` checks that the Linux and
macOS SDCC build entries agree with the SDK's upstream source identity and
actual locked patch, including the patched generator identity shared by the
two builders. Its regression tests run in the host suite and reject the old
macOS pins, patch tampering and later shell overrides. This check does not
build Mach-O binaries or qualify execution on macOS; each host's actual build
and packaged-tool validation remain separate.
