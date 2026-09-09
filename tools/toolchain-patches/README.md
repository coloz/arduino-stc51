# MCS51/MCS251 C++ toolchain patches

> Lifecycle update (2026-09-06): the active platform now has **20 models / 23 execution profiles**
> (13 MCS51 + 10 MCS251). STC8A8K64S4A12 and STC32F12K54 were removed.
> The 22-model / 25-profile / 31-workload set and removed-device details below are
> historical toolchain/qualification records, not the current support list or new PASS evidence.
> See the [lifecycle review](../../docs/variant-lifecycle.md).

> Source candidate update (2026-09-09): the mirrored complete patch now adds
> bounded MCS251 full-Flash placement and optional function/data sections.
> The compiler audit additionally fixes wide objects, DPX reloads, heap
> exhaustion/extent, pointer formatting and assembler/linker boundary handling.
> Linux/macOS packaging scripts target revision 3. This source update does
> not publish replacement packages or inherit the older runtime qualification
> recorded below; that release evidence applies only to its original hashes.

This directory and its sibling `tools/clang-stc-target`/
`tools/llvm-cbe-stc` directories contain packaging mirrors of source-level
fixes for the pinned dual-target toolchain.
The source project used by the Arduino C++ path is kept separately from this
core at `D:\Git\stc51\stcxx` (WSL:
`/mnt/d/Git/stc51/stcxx`). Generated compiler binaries live below that
project's `out/` directory; they are not compiler source and are not vendored
into this core repository.

The prior qualified standalone snapshot was branch `arduino-cpp-core`, commit
`7f7127e65368eb4fb67c9f93cfb0ecd558ff456b`. The current source candidate is
committed as `f16b00a71e3da804b52b796b332ff5696db4280a` and requires byte-identical
Core/standalone patches:

| component | Core mirror | SHA-256 |
|---|---|---|
| Clang 20.1.8 STC frontend | `tools/clang-stc-target/clang-20.1.8-stcsdcc-ir-only.patch` | `f8fda423712d808dd087d4e789b1e824911cde62d738078bf9325a898d8476c0` |
| LLVM-CBE STC lowering | `tools/llvm-cbe-stc/llvm-cbe-83f1bea-stc-sdcc.patch` | `0a332f0000aa9d335eb4c0b67bbd40b3020d9acf586c4279b5e8a0ecd2c3025f` |
| patched SDCC/ASlink source candidate | `tools/toolchain-patches/sdcc-mcs251-arduino-cpp.patch` | `fcb1342a77a412dbb8b0c8c6e8e4df5e1b59744790e63e40c32dd812c9472e12` |

The checked standalone fixed-output bundle passed `check-out-wsl.sh`; its
`out/MANIFEST.sha256` and `out/toolchain-lock.json` SHA-256 values are
`35b33920150a280dcb10bc1252bf490a350ce51b01b639855df1ad000761f735` and
`127cbed44a13052360a403bde6495de9de08f0b6bb1614e1613681660105f595`.

## Current Arduino C++ compiler source patch

`sdcc-mcs251-arduino-cpp.patch` is the complete patch consumed by the current
Arduino C++ build. Its SHA-256 is
`fcb1342a77a412dbb8b0c8c6e8e4df5e1b59744790e63e40c32dd812c9472e12`.
It applies to exactly:

- repository: `https://github.com/gevico/sdcc-c251.git`
- tag: `v4.6.0-mcs251-20260804`
- base commit: `b09075b6a93e6afe10645181e3aeff041ea37f87`

Besides the ISR, indirect-load, pointer-offset and overlapping-register fixes
described below, the final patch adds the MCS251 extended SPX/SSEG linker path,
unbounded peephole-variable storage, and lossless handling for long generated
DPTR operands. The authoritative file is maintained by the standalone compiler
project as `arduino/patches/sdcc-mcs251-arduino-cpp.patch`. This Core copy is a
packaging mirror; repository checks require both files and hashes to be exactly
equal before an installed platform can claim the locked compiler provenance.

For MCS251, `--function-sections --data-sections` creates independently
placeable function and constant-object areas. The linker option
`-Wl--code-window=0xFE0000:0x1000000` bounds STC32G12K128 placement to its
128 KiB Flash window; STC32G144K246 uses
`-Wl--code-window=0xFC2800:0x1000000` for 246 KiB. The end is exclusive.
Explicit HOME/reset and absolute CODE allocations are reserved first.
GSINIT0 through GSFINAL remain contiguous, as does each XINIT image and
individual constant object. The map includes a `Code Window` allocation
ledger with physical addresses; out-of-window or overlapping fixed areas
and unplaceable sections fail the link. Layouts without this option retain
the legacy behavior.

The candidate also fixes an existing backend error exposed by placing code
and constants in different 64 KiB regions. A flat 24-bit `__code` pointer
previously loaded DPXL but read through the region-relative `MOVC @A+DPTR`
instruction, which ignored that region byte. Flat code and data reads now
use native `MOV @DPX`. Small and large switch-table paths likewise add the
selector through all 24 address bits and use flat reads/extended jumps, so
table access does not fall back to the caller's 64 KiB region.

Apply it only to the pinned revision:

```sh
git checkout b09075b6a93e6afe10645181e3aeff041ea37f87
git apply --check /path/to/sdcc-mcs251-arduino-cpp.patch
git apply /path/to/sdcc-mcs251-arduino-cpp.patch
```

## Backend-fix component patch

`sdcc-mcs251-isr-context.patch` contains four backend fixes and their compiler
regression coverage. It is retained as a reviewable component/history file,
not as the final Arduino compiler patch. Its SHA-256 is
`46156f7ae915487cd31dd94a99934d05706db591bcf2942253e8248b2bf60b25`.

The relevant base and patched Git blobs are:

| File | Base blob | Patched blob |
| --- | --- | --- |
| `src/mcs251/gen.c` | `7f19079887ee0dee4a9d7c1dab03a2773913bee8` | `61aeb1ca96b0a7b81b6c5aa2bd77fd413745cae0` |
| `src/mcs251/gen_lower.c.inc` | `6ba73fbb00a74346950d099a4701f0f67adecbea` | `b7218de09d698fc9cdff2af6cd9e1c8743de9915` |
| `src/mcs251/main.c` | `2cd5ac357726984cc070b215bab8102fffe8563d` | `ed61ad51a6a77d21851ad628c86c940e9705ebbf` |

The blob table describes this component patch only. Final compiler
reproduction must use the complete patch above, not this component by itself.

### ISR fixed-scratch preservation

The backend can use `DPXL`, `DR24`, and `DR28` as fixed scratch state without
representing every use in an ISR's allocation mask. The original prologue
saved `DPL` and `DPH`, but an interrupt could truncate a live 24-bit pointer or
overwrite a double-register address temporary. The patch saves all three in
every non-naked ISR and restores them in reverse order.

Native `PUSH DR24`, `PUSH DR28`, and their matching pops transfer four bytes.
The new width-aware helpers therefore charge four bytes to
`_G.stack.pushed`; adding the instructions with one-byte accounting would
miscompute stack-parameter and frame offsets.

The compiler now defines
`__SDCC_MCS251_EXTENDED_ISR_CONTEXT__=1`. The core's source fallback is gated
on this compiler-owned capability: a stock compiler emits the manual sequence,
while this patched compiler emits the backend sequence. The exact-sequence
checker confirmed one and only one contiguous save/restore triple for Timer0,
UART1, INT0, and INT1 in both paths.

Do not list `dpxl`, `dr24`, or `dr28` in SDCC's ISR register-exclusion option.
As with the existing accumulator/DPTR exclusions, doing so explicitly disables
the corresponding save.

### R8-R15 indirect-load lowering

Under `--stack-auto`, register pressure can place a byte loaded through `@r0`
or `@r1` in R8-R15. The old lowering used the R0-R7 direct aliases and could
emit `mov ar9,@r1`; the assembler then treated `ar9` as an undefined symbol.
Changing only the destination spelling to `r9` is also invalid because an
MCS251 `MOV` from `@Rn` permits only A or R11 as the destination.

The general backend fix lowers a fixed-register indirect load through A and
reports the accumulator clobber:

```asm
mov a,@r1
mov r9,a
```

The patch adds `fixed-register-indirect-load.c` to the MCS251 register
allocation checks. The independent C++-pipeline reproducer
`tools/cpp-core-pipeline/repros/sdcc-mcs251-ar9.c` also compiles and assembles;
its final `.rel` SHA-256 is
`1709452aa1d9e86a292dbd9242100ceb9e4233c5344f4bd02a76a6c431ec61e5`.

### Big-endian narrowed generic loads

`GET_VALUE_AT_ADDRESS` carries a literal byte displacement in `IC_RIGHT`.
The optimizer uses it to keep the low bytes when narrowing a scalar in the
native big-endian ABI: `uint16_t -> uint8_t` reads at `+1`, and
`uint32_t -> 24-bit` reads at `+1`. The old pointer lowerings discarded that
displacement. This affected generic loads and far/local-array loads such as
the IPv6 parser, and could similarly affect direct, near, paged, and code
loads.

The fix consumes the displacement consistently in all pointer-get paths. For
far, code, and generic accesses it adjusts the complete 24-bit DPX address.
If a separate pointer post-increment was fused into the same operation, it
removes only the access displacement before writing the updated base pointer
back. Independent regressions cover generic u32-to-u24, generic u16-to-u8,
and far/local-array u16-to-u8 loads, including these sequences:

```asm
mov dr28,dpx
inc dpx
ecall __gptrget

mov dr28,dpx
inc dpx
mov a,@dpx
```

Run it with:

```sh
python3 tools/cpp-core-pipeline/check_sdcc_big_endian_narrowing.py \
  --sdcc /path/to/patched/sdcc \
  --source tools/cpp-core-pipeline/repros/sdcc-mcs251-u32-low24.c \
  --far-source \
    tools/cpp-core-pipeline/repros/sdcc-mcs251-be-memory-low-byte.c \
  --overlap-source \
    tools/cpp-core-pipeline/repros/sdcc-mcs251-overlap-generic-store.c
```

The regression fails on the pre-fix compiler and passes all three narrowing
cases on the compiler recorded below. It is also a mandatory gate in
`tools/cpp-core-pipeline/run-sdcc-stage.sh`.

### Overlapping multi-byte arithmetic

The byte-at-a-time add fallback propagates carry from low to high. A register
allocation used source `[r7,r6,r5]` and result `[r5,r4,r3]` for `object + 5`;
writing result byte zero to `r5` destroyed the source high byte before the
third add. The resulting invalid address made the later generic byte store
silently miss the String buffer.

The backend now detects when any destination byte aliases a later source
byte. In that case it pushes each computed result, consumes every source byte,
then pops the results into the destination tuple. The independent reproducer
retains the real object-field load and `__gptrput`, and the checker asserts
that the high source `r5` is read before destination `r5` is written.

## Historical Linux qualification before the full-Flash candidate

A clean out-of-tree x86-64 Linux build was published into the standalone
project-local `out/` bundle. The fixed driver is:

```text
/mnt/d/Git/stc51/stcxx/out/bin/sdcc
```

- version: `SDCC : mcs51/mcs251 TD- 4.6.0 #0 (Linux)`
- launcher/wrapper SHA-256:
  `e4674cb08f4db442ef7485318c49c47a90e1a319e5ca2cb3ac38123d99a7a234`
- compiler frontend ELF (`out/libexec/sdcc`) SHA-256:
  `9c53d67813ce37e2ea883922bac2d0764d387742952ac10592de7719eb1b4e2b`
- MCS251 extended linker (`out/bin/sdldmcs251`) SHA-256:
  `d7a2f51d6b931170014317ea999aca0163a5b91ec1547e83871f9ad32d7de588`
- complete source patch SHA-256:
  `b28f5ae2c520fa1c9dffc6c51aeb5025415d80212d33e893e1a3a8837b3b8f9e`
- `make -C build/sdas/as251 check`: pass (269 legal forms, 65 families,
  two opcode maps)
- `make -C build/src/mcs251 check`: pass, including the new indirect-load
  regression; only the optional pyelftools check was skipped because that
  module was absent

The standalone `check-out-wsl.sh` gate additionally qualifies MCS251 EDATA
ends `0x0800`, `0x1000` and `0x4000` with a stack starting at `0x0100`, checks
the exact `SSEG`/SPX map and rejects overflow. The MCS51 linker remains `sdld`
with its legacy 256-byte IRAM limit; it does not inherit this extension.

The Arduino repository exposes C++ build profiles for all 22 physical variants
and 25 MCS51/MCS251 execution configurations. Locked QEMU commit
`faeac38c0076795d7b4e59f0ddcb5fc7e7bd7015` supplies an exact machine for each;
the MCS51/MCS251 executable SHA-256 values are respectively
`08b41280f0a326ab5fe4ca2f18ed6d41860a7b4bb488b2b0a58fc5f088ea8157`
and `81c1246c4d85911b03562307ae23df50cba636098be9af1fdcfa38fd192cf3e7`.
Machine availability is not runtime qualification. The final matrix must bind
the same retained build manifest, firmware hashes, tool audits, and per-profile
runtime records; no model alias or historical firmware is accepted as evidence.

The qualification contract is 14 MCS51 plus 11 MCS251 profiles. Six compact
profiles use two workloads each and nineteen full profiles use one, for 31
locked workloads. AI8051U-34K16 contributes two compact profiles with a
14,336-byte program cap; STC32F12K54 uses a 3,584-byte heap plus a 512-byte
static-XDATA reserve. The final clean runtime run is being regenerated, and
only the authoritative hash-bound JSON may state its outcome.

## Remaining release gates and compiler audit

This result qualifies the complete patch and the project-local Linux bundle.
It does not qualify Windows/macOS packages, physical hardware, or broad
Arduino-library compatibility. Both MCS51 and MCS251 frontends remain
experimental. This provenance note intentionally records no current outcome
for the 25-profile/31-workload compile/link/capacity and exact-QEMU matrix.
Read the authoritative retained
[`tests/cpp/variant-matrix/results.json`](https://github.com/coloz/arduino-stc51/blob/main/tests/cpp/variant-matrix/results.json)
from a complete source checkout; its evidence object must bind the retained
build and exact-QEMU audit JSON by path and SHA-256. Missing, partial, stale,
schema-invalid, or unbound JSON never counts as PASS.

The stale Linux `dist/...-r1.tar.bz2` was removed after inspection. Its
embedded `sdcc` SHA-256 was
`e0aab3ff5e68c0745227fcbf291d232d55205264435baa442f42a25b4e5249e8`,
which was not the final patched compiler. It must not be restored, used as
release evidence, or republished as the ISR+ar9 build.

The 2026-09-09 source audit fixes the formerly documented address-space loss
in `*(&generic_array[i])`, for both loads and stores. Array-subscript lvalues
now preserve the originating pointer's output class and named address space;
the compiler no longer depends on a syntax-pattern rewrite for this case.
The adapter's existing normalization remains compatible with older compilers.
The audit also corrects the pointer-difference intermediate type to match
`ptrdiff_t`, rather than truncating wide differences to a 16-bit `int`.
Detailed scope, regressions and limitations are recorded in the standalone
compiler's `doc/mcs251/compiler-audit-20260909.md`.
