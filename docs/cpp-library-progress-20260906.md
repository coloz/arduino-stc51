# Library compatibility recovery, 2026-09-06

> Lifecycle update (2026-09-06): the active platform now has **20 models / 23 execution profiles**
> (13 MCS51 + 10 MCS251). STC8A8K64S4A12 and STC32F12K54 were removed.
> The 22-model / 25-profile / 31-workload set and removed-device details below are
> historical toolchain/qualification records, not the current support list or new PASS evidence.
> See the [lifecycle review](variant-lifecycle.md).

This is a development checkpoint, not a release qualification. Paths below are
relative to the SDK checkout now at `D:\Git\stc51\arduino-stc51`; its sibling
compiler checkout is `D:\Git\stc51\stcxx`.

## Latest checkpoint

- The rebuilt compiler fixes constant integer variadic arguments and MCS251
  high-address pointer truthiness. Compiler regression and publication checks
  pass; the standalone source/control worktree remains uncommitted.
- Fresh stdio, delay-liveness, and exact Print special-value sketches compile,
  link, and pass QEMU on MCS51 and STC32G144K246.
- SD's C/C++ SPI symbol mismatch is fixed. Both representative CPUs now pass
  the disconnected-card error oracle, but MCS51 needs a separate extended
  runtime (510.568 seconds); its original 180-second TIMEOUT remains recorded.
- The six bundled C backends pass 150/150 native compile cases across all 25
  profiles (22 physical variants). This is not all-variant C++ runtime coverage.
- The current aggregate host suite passes 10/10 groups, including the new Print
  oracle. Its source inventory and all ten log hashes have been rechecked.
- U8g2's graphics-buffer oracle passes isolated diagnostics on both CPUs, but
  automatic constant storage binding and finer function selection are pending.
  See [the integration plan](cpp-native-const-storage-plan.md).

No overall compatibility percentage is claimed: compile coverage, host logic,
target runtime, capacity, and physical peripherals have different acceptance
criteria. The latest full 20-library target and all-variant runtime matrices
are not complete.

## Implemented in this recovery

- MCS51 memory intrinsics accept wider constant lengths only when they fit native
  `size_t`; overflowing and dynamic wider lengths still fail closed. This fixes
  real Clang-generated four-byte IPAddress initialization, without truncating
  unproven runtime values.
- The CBE adapter distinguishes explicit native `<string.h>` intrinsic output
  from ordinary IR-derived string function declarations. Conflicting prototypes
  in native-header mode and unbound direct calls remain rejected.
- Active source-checkout scripts discover the sibling compiler after relocation.
  A separate source-discovery manifest verifies the original 22 archive hashes;
  historical snapshots and evidence keep their original paths.
- Diagnostic builds can freeze external libraries with repeatable `--library`
  arguments. U8g2 2.36.19 has an additional full/page graphics-buffer test beyond
  its existing text-transport probe. No third-party source was modified.

## Fresh evidence before v6 target runtime tests

| Evidence | Result | What it does not prove |
| --- | --- | --- |
| `tmp/common20/frontend-relocated-v1/results.json` | 40/40 PASS, valid evidence | SDCC link or target execution |
| `tmp/common20/host-relocated-v1/results.json` | 9/9 PASS, valid evidence | Real CPU/peripheral timing |
| `tmp/common20-stdio-abi-relocated-v1/results.json` | 12/12 PASS | Native varargs execution |
| `tmp/u8g2-graphics-host-v1/result.json` | Original sketch passes 2,176 byte checks | Fonts, physical display, I2C timing |

`tmp/common20-platform-v6/platform-snapshot.json` freezes the next target test
inputs. QEMU outcomes must be read from each completed run's own `results.json`;
a build still running, failed build, or missing report is not a PASS.

The interrupted v5 twenty-library batch is not a complete matrix. Older all-chip
QEMU results describe their original source state, not v6. Current all-variant
release qualification also requires the standalone compiler source-provenance
gate to pass; do not bypass it or implicitly commit the user's working tree.

## Completed v6 diagnostics (not all-chip qualification)

| Run | MCS51 | MCS251 |
| --- | --- | --- |
| `tmp/stdio-runtime-v6/results.json` | Link PASS, QEMU TIMEOUT/repeated BEGIN | Link PASS, QEMU FAIL |
| `tmp/libc-abi-runtime-v6/results.json` | Rejected pointer-to-integer tag-test cast; no QEMU | Link and QEMU PASS |
| `tmp/sd-no-card-runtime-v6/results.json` | Link PASS, QEMU TIMEOUT/repeated BEGIN | Link PASS, QEMU TIMEOUT/repeated BEGIN |
| `tmp/common20-platform-v6/u8g2-graphics-buffer-extra-v1/results.json` | 84,604-byte ROM exceeds 65,536; no QEMU | HEX produced, ambiguous archive-member map audit rejected; no QEMU |

The stdio stage probe independently confirms the MCS251 failure at the signed/
long formatting check: its valid buffer is at address 0x010000, but native SDCC
pointer truthiness incorrectly checks only the low sixteen bits. A separate
compiler candidate is required. This is not a formatter output mismatch.

The MCS51 stdio trace shows a different native ABI mismatch: ISO `memset` takes
an `int`, whereas the installed native MCS51 string library takes one byte.
The mismatched call shifts `size_t`, overwrites unrelated state, and breaks
subsequent virtual dispatch. The SDK now routes explicit C++ `memset` calls
through `__stcxx_libc_memset`; compiler-generated memory intrinsics continue to
use the audited native-header path. The new wrapper's target symbol and native
one-byte-value/two-byte-length stack contract pass static regressions. Its fresh
runtime test is under `tmp/stdio-runtime-v7-memset`, not retroactively v6.

U8g2's MCS251 failure is a 32-character archive-member-name truncation collision,
not a QEMU failure. A deterministic short-member alias needs to preserve the
original object hash and symbol identity. MCS51 additionally needs finer C
function reachability before this graphics case can fit its actual Flash limit;
the limit must not be inflated or the graphics oracle silently reduced.

## Subsequent isolated verification

- `tmp/libc-abi-runtime-v6-tag-helper-v1/results.json`: both representative
  targets compile/link and pass QEMU. The tag helper now uses a native C
  character view of the pointer representation instead of an unsupported
  C++ pointer-to-integer cast. This test contains no `memset` call.
- `tmp/common20/frontend-v7-memset/results.json`: 40/40 frontend cases pass with
  valid evidence after the memset facade change.
- `tmp/common20/host-v7-memset/results.json`: 9/9 host suites pass with unchanged
  implementation inputs during the run.
- `tmp/stdio-runtime-v7-memset/results.json`: MCS51 no longer restarts and the
  explicit int-to-byte memset check passes. The only remaining failure in this
  run is long-integer formatting. LLVM retained `i32 42` but CBE emitted plain
  `42` as a variadic argument, which SDCC passes as a 16-bit int.
- `tmp/stdio-cbe-varargs-replay-v2/results.json`: candidate CBE explicitly casts
  STC variadic integers to their LLVM-width C types. Using the v7 frozen IR and
  native objects, all stdio stage checks and the final MCS51 QEMU oracle pass.
  This replay does not replace fresh CLI compilation, warning/heap gates, or
  the all-variant suite. Existing CBE aggregate and memory-intrinsic regressions
  also pass with the candidate.

## Compiler and U8g2 candidate regressions

- `tmp/cbe-varargs-regression-v3/results.json`: both native CPUs reproduce the
  old direct-constant variadic ABI failure and pass with the candidate. Dynamic
  arguments and indirect calls also pass. The candidate rejects unpromoted
  eight-bit integer varargs; swapping baseline and candidate correctly makes
  the differential runner fail. All 72 recorded digests were independently
  checked. This is an integer-varargs ABI test, not support for Clang `va_list`
  or every floating-point variadic combination. The MCS251 indirect-call case
  retains existing SDCC warning 244, so this diagnostic does not waive the CLI
  warning gate.
- `tmp/sdcc-mcs251-nullcmp-regression-v2/results.json`: the native compiler's
  pointer truthiness regression fails with the baseline and passes with the
  candidate. MCS251 has a three-byte address, not a two-byte address plus a
  generic-pointer tag; addresses such as `0x010000` must compare non-null.
- `tmp/stdio-runtime-v6-mcs251-combined-replay-v2/combined-results.json`: frozen
  v6 C++ IR regenerated by the variadic candidate, with native stdio rebuilt
  using the pointer-comparison candidate, passes QEMU. This still reuses other
  native objects and is explicitly not a fresh full SDK qualification.
- `tmp/u8g2-function-split-alias-v1/result.json`: archive members now have
  deterministic short names with checked source-object provenance. Relinking
  frozen MCS251 inputs passes the map audit and produces byte-identical HEX;
  the full/page/rotation graphics-buffer oracle then passes QEMU. No upstream
  U8g2 files, Flash limits, or graphics checks were changed. This is an isolated
  relink, not a fresh full-library build or all-variant test.

## Rebuilt toolchain and subsequent SDK fixes

The standalone publication build completed at
`/var/tmp/stc-cpp-nullptr-varargs-release-v2`. Both native compiler gates exit
zero: MCS251 reports 67 PASS lines; MCS51 reports 17 and matches its upstream
baseline digest. These are compiler regressions, not 84 Arduino variants.
The published compiler ELF is
`5b212e57752a65cbb7f61ea50dd23290375f9dbee9c594db8cd2a1efd941d808`;
the complete native runtime libraries were rebuilt with it. Publication
manifest and extended-stack self-tests pass. The official CBE rebuild is
byte-identical to the validated variadic candidate (`3a1a188f...`).

The active compiler remains in the sibling project's `out` directory; the old
complete publication is recoverable in `out-pre-nullptr-varargs-20260906`.
The old CBE is retained at `tmp/llvm-cbe-pre-varargs-20260906`. The SDK lock,
source manifests, and patch mirrors now refer to the rebuilt tools. Synchronizing
hashes does not create a source commit or satisfy the separate clean-source gate.

The SD restart has a separate confirmed symbol/type mismatch. Native `SD.c`
used the C `SPI` function-pointer table, but the mixed build suppresses that
table and defines a C++ `SPIClass SPI` object under the same linker symbol.
The backend now calls `SPI_*` C entry points directly. The FAT host mock no
longer supplies a fake C table: the additional mixed-link regression links
the real `SPIClass.cpp`, exercises the no-card `SD.begin()` path, and verifies
that SPI remains usable. Both FAT16/32 image and mixed-link host tests pass.
Fresh target execution must still be reported separately.

Fresh v8 results (`tmp/common20-platform-v8-varargs-nullptr-sd`) are now:

| Test | Result | Scope |
| --- | --- | --- |
| `tmp/stdio-runtime-v8-varargs-nullptr/results.json` | Both targets compile/link and QEMU PASS, valid evidence | Eight explicit memset/stdio stage checks; not FILE/scanf/Clang va_list |
| `tmp/delay-microseconds-runtime-v8/results.json` | Both targets compile/link and QEMU PASS, valid evidence | Delay/serial liveness only; not wall-clock accuracy or printed float values |
| `tmp/sd-no-card-runtime-v8-native-spi/results.json` | Both compile/link; MCS251 QEMU PASS in 144.022 s, MCS51 TIMEOUT at 180 s | No-card path only; MCS51 now emits one BEGIN instead of restarting |
| `tmp/common20-bundled-native-all25-v2-sd-spi/results.json` | 150/150 PASS, valid evidence | Six C backends x 25 profiles / 22 physical variants; compile only |
| `tmp/common20/host-v8-sd-spi/results.json` | 9/9 PASS, valid evidence | Includes actual mixed SD/SPI linkage and FAT images; not target I/O |

The v8 delay-stage output exposed a floating-point formatting bug: NaN was
printed as `ovf`, although infinity used `inf`. The liveness marker does not
assert those values. The separate v9 fix and exact-value regression below
qualify Print formatting without retroactively changing this v8 evidence.

### Completed SD runtime extension

`tmp/sd-no-card-runtime-v8-native-spi-mcs51-600s/results.json` runs the exact
same frozen v8 MCS51 HEX with a 600-second budget. It passes in 510.568 seconds,
with one BEGIN, one PASS, and no FAIL markers; all recorded inputs are unchanged.
The report SHA256 is
`5daf27c22f4e2612bf81debd3118e06918ae8606a46f8210816880b0e99d6482`.
The original v8 report remains unchanged and still records its 180-second
MCS51 TIMEOUT. This is a runtime-only extension, not another fresh build.

Bounded monitor samples show the native SPI half-period at XDATA `0x0291`
is consistently `0x0005`, as expected for 100 kHz initialization. Timer0 and
`millis` progress, and no repeated BEGIN is emitted. Together with the terminal
PASS, these observations rule out the previous reset and the suspected wrong
SPI delay argument for this run. Execution is slow under the locked instruction
counting configuration; neither target result qualifies SD hardware, FAT media
I/O, or real-time accuracy.

### Print special-value fix and fresh v9 target verification

`cores/STC/cpp/Print.cpp` now uses `isnan(value)` instead of `value != value`,
matching the local official AVR 1.8.8 implementation. The new host fixture and
`diagnostics/PrintFloatSpecialValues` check exact returned length, sink length,
NUL termination, and output bytes for nine cases: NaN, both infinities, positive
and negative finite values, both finite formatting limits, and both adjacent
overflow values.

The fresh `tmp/common20-platform-v9-print-special` snapshot gives compile/link
and QEMU PASS on MCS51 and MCS251, in 0.226 and 0.262 runtime seconds respectively.
`tmp/print-float-special-values-v9/results.json` has `valid_evidence=true`, SHA256
`1f07494e137a2603440d859645ceb9e644107d12a8c19b64b643369d1df1494d`.
The associated `verification.json` checks identical exact UART transcripts and
binds the source and report hashes. This verifies these Print formatting paths,
not general floating-point comparison semantics or every numerical operation.

The Print host fixture is now part of `run-expansion-host-suite.py`, including
its implementation inputs in the source-hash inventory. The first aggregate
attempt (`tmp/common20/host-v9-print-special`) correctly remains FAIL: its new
expected success marker was mistyped, although the fixture exited zero with
the actual PASS marker. After correcting the aggregator, a fresh complete run
at `tmp/common20/host-v10-print-special/results.json` passes 10/10 groups, with
`valid_evidence=true`, zero changed inputs, and independently verified source
and log hashes. Its SHA256 is
`da480a8af92368abef7bec6d6d0d6ead1d6db9af66db087a25684cbf9fb7ebd3`.
No earlier failed report was rewritten or promoted.

`tmp/final-toolchain-varargs-nullptr-v1/report.json` records the complete tool
review: 95/95 cross-lock checks, 248/248 publication entries, full CBE tests and
the dual-target variadic differential all pass. The unchanged repository gate
still stops at the dirty standalone compiler source/control worktree. Historical
ABI/ADR hashes have been explicitly labelled as historical, not rewritten to
appear to describe the new tools.

## U8g2 remaining integration work

`tmp/u8g2-mcs51-const-code-tag-v1/result.json` proves the second MCS51 problem:
native constant callback tables live in CODE, whereas their C++ external
aggregate declarations reach LLVM as `external global`. CBE consequently
materializes RAM generic-pointer tags. Stock Clang behaves the same way;
`tests/cpp/abi/native-const-address-probe.cpp` reproduces the distinction between
external const aggregates and const byte arrays. Do not fix this by globally
assuming every C++ const object lives in Flash.

Function selection reduces ROM from 84,604 to 62,757 bytes. Changing only three
generated callback-address tags from `0x00` to `0x80` gives 62,763 bytes and
passes the unchanged 2,176-check QEMU oracle in 0.077 seconds. The report SHA is
`dcd25d35bd92285a25af52b01612a7de80650cad1d1d13b751cfec712711a8ef`.
This manual assembly diagnostic is NOT the production fix. Automatic function
selection and native external-object storage binding still need integration.

The safe source-splitter improvement is implemented: ignore bodyless function
declarations before checking source ranges, but continue rejecting macro-expanded
function definitions. Its real-Clang positive/negative and archive tests pass
19/19. No third-party U8g2 source or physical chip capacity was changed.
