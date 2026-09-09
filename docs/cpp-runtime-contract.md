# STC Arduino C++ runtime contract

> Lifecycle update (2026-09-06): the active platform now has **20 models / 23 execution profiles**
> (13 MCS51 + 10 MCS251). STC8A8K64S4A12 and STC32F12K54 were removed.
> The 22-model / 25-profile / 31-workload set and removed-device details below are
> historical toolchain/qualification records, not the current support list or new PASS evidence.
> See the [lifecycle review](variant-lifecycle.md).

Status: **EXPERIMENTAL / NOT_SUPPORTED**. Independent MCS51 and MCS251 C++
paths are integrated into explicit 12 MHz Arduino CLI profiles selected with
`cppcore=enabled` for 20 physical variants and 23 execution configurations.
The historical qualification set uses 31 workload results: six compact profiles require separate
`runtime` and `io` images, and nineteen full profiles require one `full` image.
The execution split is 14 MCS51 plus 11 MCS251 profiles; the three AI8051U
capacities each contribute both modes.
Current outcomes are intentionally external to this packaged contract and live
only in `tests/cpp/variant-matrix/*.json`; machine availability and historical
canaries are never a current PASS by themselves. Plain C remains the default.
Nothing in this document qualifies 24 MHz,
another MCU's runtime, physical hardware, exceptions/RTTI, a complete standard
library, or general Arduino-library compatibility.

## Startup boundary

With `STCXX_CPP_CORE=1`, `cores/STC/main.c` calls
`__stcxx_run_global_ctors()` before `init()`, `initVariant()`, `setup()`, and
`loop()`.  The current observable order is therefore:

```text
SDCC GSINIT/GSFINAL initializes .data and .bss
-> __sdcc_program_startup
-> main() core prologue
-> generated global constructors
-> init()
-> initVariant()
-> setup()
-> loop()/yield()
```

This is Arduino-compatible for code observed through the Arduino lifecycle,
but it is not a claim that constructors execute before the machine enters
`main()`.  The target ABI ADR requires strict pre-main construction, so a
future startup-section integration must move the same runtime entry to
GSFINAL; that target integration remains unverified.

When `STCXX_CPP_CORE` is absent or zero, `main.c` has no runtime include,
reference, or call, and every C++ runtime implementation file preprocesses to
an empty C translation unit.  The existing plain-C route is unchanged.

## Generated constructor bridge

No generic C pointer type can honestly represent every 8051 code/data address
space, so the runtime does not consume a linker-provided function-pointer
array. The C++ lowering step generates one bridge translation
unit with these C-linkage functions:

```cpp
extern "C" void __stcxx_bridge_require_abi()
{
    STCXX_ABI_IDENTITY_SYMBOL();
}

extern "C" uint16_t __stcxx_bridge_ctor_count()
{
    return 2;
}

extern "C" void __stcxx_bridge_invoke_ctor(uint16_t index)
{
    switch (index) {
    case 0: constructor_from_a_0(); return;
    case 1: constructor_from_b_0(); return;
    default: stcxx_runtime_panic(STCXX_PANIC_CTOR_BRIDGE_RANGE);
    }
}
```

The bridge contains direct calls, so the backend chooses the correct function
call and code address without a lossy pointer-table cast.  The runtime invokes
indices `0..count-1` and records completion; subsequent calls are no-ops and a
recursive call is fatal.  The runtime preserves the exact increasing index
order emitted by the bridge.  Within one translation unit the bridge must
preserve definition order.  The deterministic cross-translation-unit
tie-break rule is not frozen yet and is a production gate; C++ programs must
not depend on the otherwise unspecified relative order.
Every bridge, including one with zero constructors, is mandatory.  Its ABI
probe calls the target-specific `STCXX_ABI_IDENTITY_SYMBOL`; a mismatched
bridge and runtime therefore fail at link time with a descriptive undefined
symbol rather than booting with a silently incompatible ABI.

## Runtime sub-ABI identities

`runtime-manifest.json` is the machine-readable source of truth for this
runtime slice.  Its names encode the facts consumed by the runtime itself:

| profile | byte order | `size_t` | `ptrdiff_t` | generic/data pointer | function pointer |
| --- | --- | ---: | ---: | ---: | ---: |
| MCS51 | little-endian | 2 bytes, align 1 | 4 bytes, align 1 | 3 bytes | 2 bytes |
| MCS251 | big-endian | 4 bytes, align 1 | 4 bytes, align 1 | 3 bytes | 3 bytes |

`stcxx_config.h` rejects a target build when these sizes differ.  The MCS251
profile does **not** use a four-byte pointer assumption.  Scalar assertions
also freeze 8-bit `bool`, 16-bit `int`, 32-bit `long`, and FP32 `float` and
`double` for this Arduino ABI.  The target frontend must additionally provide
`STCXX_TARGET_ENDIAN_LITTLE` for MCS51 or `STCXX_TARGET_ENDIAN_BIG` for
MCS251; selecting the opposite or both is a preprocessing error, and the
choice is embedded in the versioned identity symbol.  These symbols are not a
complete object ABI identity.  Before linking, the production driver must
also prove the target, memory model, stack-auto and xstack policy, floating
model, address-space model, exception/RTTI policy, and ABI revision specified
by `tests/cpp/abi/abi-manifest.json`.

## Local-static guard ABI

The locked frontend uses `-fno-threadsafe-statics`. Clang therefore emits one
byte-aligned `i8` guard object and reads/writes that byte directly:

| offset | field | meaning |
| ---: | --- | --- |
| 0 | `initialized` | zero before first use, one after construction completes |

The generated target IR must contain no calls to `__cxa_guard_acquire`,
`__cxa_guard_release`, or `__cxa_guard_abort`; those hooks are deliberately
absent from the runtime. This is a non-thread-safe, no-recursion-detection
profile. Target evidence audits the exact `i8` guard definition plus its
direct load/store code generation for both MCS51 and MCS251.

## Allocation and fatal hooks

`stcxx_allocator.h` remains the single heap boundary used by both `String` and
the new/delete implementation:

- the default implementation delegates to `malloc`, `realloc`, and `free`;
- a target heap defines `STCXX_CUSTOM_ALLOCATOR` and supplies
  `stcxx_malloc`, `stcxx_realloc`, and `stcxx_free` with compatible generic
  pointer/address-space semantics;
- `stcxx_set_oom_hook()` installs a failure-notification hook without replacing
  the heap or the fatal throwing-allocation policy;
- `stcxx_set_panic_hook()` permits logging or a watchdog reset before the
  runtime halts.

Throwing-form `new`/`new[]` normalize zero to one byte and, because exceptions
are disabled, never return null. On failure they notify the custom OOM hook
when one is installed; if that hook returns, the runtime always enters
`STCXX_PANIC_OUT_OF_MEMORY`. A hook may instead perform a reset or another
non-returning transfer. `std::nothrow` forms return null without invoking the
OOM or panic hook. Scalar, array, and nothrow deletes all use `stcxx_free`;
C++14-or-newer builds also expose sized delete.  The frozen GNU++11 profile
does not require sized deallocation.  Placement new/delete are header-only
and never touch the heap.

Heap capacity is a per-device contract, not a target-wide constant.
STC32F12K54 is the constrained MCS251 case: its 4 KiB XDATA configuration
allocates a 3,584-byte heap and reserves the remaining 512-byte budget for all
static XDATA, including allocator telemetry and other selected archive members.
The final link audit rejects a heap-plus-static-reserve value above 4,096
bytes and independently checks actual XDATA use. AI8051U-34K16 keeps its
16,384-byte heap but is capacity-tiered by Flash: each execution mode is a
compact profile with a 14,336-byte maximum program image.

The default target allocator also samples the pinned SDCC free list after
heap initialization and after every successful `stcxx_malloc()` or
`stcxx_realloc()`.  The layout contract is the standalone compiler source
`device/lib/malloc.c`, raw SHA-256
`344c80c4bf8f4bb5fbe03e9e3bbbd63be76328340033c943947a15105bb86fba`
(Git blob `fd17c388683fe100ecd5cedd8a4194194d1c1f32`).  The two toolchain
locks, runtime/Core manifests, build evidence and repository gate bind that
same identity. The single
MCS251 heap extent provider is now `__sdcc_heap_size32` (four bytes), while
MCS51 retains `__sdcc_heap_size` (two bytes). Custom heap objects must be
rebuilt with the matching runtime. This does not enlarge the board profiles'
qualified 32 KiB maximum arena or change their 16-bit telemetry fields.
The single
`stcxx_allocator_read_telemetry(stcxx_allocator_telemetry_t *)` snapshot returns
six packed `uint16_t` fields: arena size, initial/current total free, current
largest free block, and minimum total/largest values. It fails closed if the list is
cyclic, reversed, outside the heap or arithmetically invalid.  Its scope is
strictly allocations routed through `stcxx_malloc`/`stcxx_realloc` (including
the Core `String` and `new` paths).  A third-party library that directly calls
libc `malloc`, `realloc` or `free` is not observed and cannot use these values
as its own allocator-capacity proof.

Telemetry counters intentionally live in the separate
`cores/STC/stcxx_heap_state.c` translation unit.  Its archive member contributes
exactly 8 bytes of XDATA, no IDATA and no heap-provider symbol.  This keeps the
`stcxx_heap.c` provider member's XSEG exactly equal to the configured allocator
arena.  The final link audit requires one provider member and one selected
state member, then includes both the arena and those 8 state bytes in total
XDATA capacity accounting.

The freestanding headers live under `cores/STC/cpp/` and include the minimal
`new`, `type_traits`, `utility`, `limits`, `algorithm`, `cstdint`, `cstring`,
and related declaration set needed by the qualified probes. The target driver
puts that directory before compiler headers. This is not libstdc++ and does
not promise containers, iostreams, locales, threads, or the rest of the STL.
Host GCC/Clang tests define
`STCXX_USE_SYSTEM_NEW=1`, causing the shim to use the host's next `<new>` and
checking the replacement functions against the hosted declarations.

`__cxa_pure_virtual` and `__cxa_deleted_virtual` report distinct panic reasons
and halt.  Exceptions, RTTI, thread synchronization, `atexit`, and execution
of global destructors are intentionally absent. The Arduino CLI Clang driver
uses `-fno-exceptions`, `-fno-rtti`, `-fno-use-cxa-atexit`, and
`-fno-c++-static-destructors`; an accidental dependency on destructor
registration is a failed lowering/link gate rather than silently pretending
destructors will run on a non-returning Arduino program. The opt-in driver also
hashes the selected frontend/backend tools and per-TU bitcode sidecars before
final lowering.

## Evidence and remaining gates

`tests/cpp/runtime` validates bridge order/once-only behavior, the direct
one-byte non-thread-safe guard contract, pure/deleted virtual traps, allocation
forms and failure policy, the versioned identity symbol, and the startup-source
ordering.  It also compiles the runtime `.cpp` files as C with
`STCXX_CPP_CORE=0` to protect the current wrapper behavior.

Host tests validate portable runtime logic, and the retained K246 direct
pipeline remains a supplemental historical regression. Current qualification
uses the independent MCS51/MCS251 frontend identities and exact machines for
all 25 execution profiles and all 31 required workloads. Each retained run must
bind its exact source set, clean build manifest, firmware SHA-256, target
triple/data layout, pointer ABI, tool/root/sidecar audits, applicable allocator
telemetry or compact lifecycle proof, and runtime stdout. The normalized
machine-readable result under `tests/cpp/variant-matrix/` is authoritative and
binds raw schema-v2 build plus schema-v4 audit evidence under
`tests/qemu/results/`; an old firmware digest, model alias, or model definition
alone cannot produce a PASS.

Still required before the C++ core can be called target-complete are a passing
retained 25-profile/31-workload build/runtime result, the strict pre-`main()` startup move if
the ABI ADR continues to require it, broader varargs/address-space/archive/
weak/COMDAT testing, heap and worst-case stack capacity evidence,
the frozen Tier A/B library gates, release-qualified host tool bundles, and
physical hardware validation. Exceptions, RTTI, thread synchronization,
complete STL/libstdc++, and global destructors remain intentionally unsupported.

The locked QEMU source commit for this scope is
`faeac38c0076795d7b4e59f0ddcb5fc7e7bd7015`, with 14 exact MCS51 and 11 exact
MCS251 machines. The final clean 25-profile/31-workload run is being regenerated;
only the mutually hash-bound authoritative JSON may state its outcome. The
supplemental default-host-timing rerun covers 9 profiles and 11 workloads and
does not replace the locked-timing qualification set.

## Appendix: native libc ABI boundary

The public C++ declarations remain the standard `malloc`, `calloc`, `realloc`,
`strchr`, and `strrchr` APIs.  Their target-only declarations carry assembler
labels that route bridge calls to `cores/STC/stcxx_libc_abi.c`; source code is
not required to use a private replacement API.  The wrapper is compiled by
SDCC, includes SDCC's native headers, and performs these two ABI conversions:

- On MCS51, SDCC's allocator functions return a two-byte `__xdata` pointer,
  while Clang C++ uses a three-byte generic pointer.  The wrapper converts the
  result and therefore supplies the generic XDATA tag in register B.  MCS251
  uses the same three-byte representation for both pointer classes, but still
  goes through the named boundary so one source contract covers both targets.
- SDCC's MCS51 `strchr` and `strrchr` declarations take a one-byte `char`
  search value.  The wrapper accepts the standard `int`, converts it to
  `unsigned char`, and calls that native ABI.  MCS251's native `int` parameter
  receives the same normalized byte value.

This conclusion is grounded in the installed compiler declarations
`out/share/sdcc/include/stdlib.h` and `out/share/sdcc/include/string.h`, the
allocator implementations under `device/lib/malloc.c` and
`device/lib/realloc.c`, and the MCS51/MCS251 pointer-size tables in
`src/mcs51/main.c` and `src/mcs251/main.c` of the standalone compiler tree.
`tests/cpp/abi/test-libc-abi-boundary.sh` compiles the production wrapper for
both targets and fails unless the MCS51 allocator returns carry a zero XDATA
tag in B, the native string argument widths are respected, and both target
LLVM modules reference only the wrapper symbols.  The full QEMU runtime probe
then exercises allocation, zero-initialization, growth with retained bytes,
generic-pointer dereference, and high-byte string-search arguments.
