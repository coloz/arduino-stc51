# STC Arduino C++ class layer

> Lifecycle update (2026-09-06): the active platform now has **20 models / 23 execution profiles**
> (13 MCS51 + 10 MCS251). STC8A8K64S4A12 and STC32F12K54 were removed.
> The 22-model / 25-profile / 31-workload set and removed-device details below are
> historical toolchain/qualification records, not the current support list or new PASS evidence.
> See the [lifecycle review](../../../docs/variant-lifecycle.md).

This directory contains the class and runtime layer of the experimental C++
core. It contains real C++ classes for `String`, `Printable`, `Print`,
`Stream`, `HardwareSerial`, `SPISettings`, `SPIClass`, `TwoWire`, `IPAddress`,
and the `Client`/`Server`/`UDP` transport interfaces. The platform now selects
this layer only through the explicit `cppcore=enabled` menu option; plain C
remains the default.

The Arduino CLI exposes this layer at 12 MHz for all 20 physical variants and
23 MCS51/MCS251 execution profiles (13 MCS51 and 10 MCS251). Both target
frontends and bridge ABIs are
implemented independently: MCS51 uses 16-bit code pointers, 2-byte data-member
pointers, and 4-byte member-function pointers; MCS251 uses 24-bit, 3-byte, and
6-byte layouts respectively. The final clean compile/link/capacity and exact
QEMU qualification contract has 25 profiles and 31 workloads: six compact
profiles each use separate `runtime` and `io` images, while nineteen full
profiles use one `full` image. An enabled profile is not a runtime PASS until
all of its retained source sets, build manifests, firmware hashes, and runtime
audits agree. Current outcomes live only in `tests/cpp/variant-matrix/*.json`;
this packaged contract deliberately does not duplicate them.

AI8051U-34K16 supplies two of the compact profiles and caps each program image
at 14,336 bytes. STC32F12K54 is a constrained full profile: its 4 KiB XDATA
budget is split into a 3,584-byte heap and a 512-byte static-XDATA reserve.

## Production source list

Compile these files as C++11 or newer with exceptions and RTTI disabled:

```text
WString.cpp
Print.cpp
Stream.cpp
IPAddress.cpp
HardwareSerial.cpp
stcxx_allocator.cpp       # omit only when STCXX_CUSTOM_ALLOCATOR is defined
stcxx_runtime.cpp
stcxx_new.cpp
```

The existing C HAL remains in the build, including `HardwareSerial.c`,
`HardwareSerial_isr.c`, `HardwareSerial_print*.c`, and their UART state.
`HardwareSerial_object.c` must be excluded because the C++ layer defines the
real global `HardwareSerial Serial` object.  Keeping both would be a duplicate
symbol and, more importantly, would give `Serial` two incompatible types.

The bundled SPI and Wire libraries own `SPIClass.cpp`/`WireClass.cpp` as well
as `SPI.c`/`Wire.c`; the class objects are therefore linked only when Arduino
actually selects the corresponding library.  This prevents an ordinary sketch
from gaining unresolved Wire HAL references merely because the core was built.
When those files are compiled with `STCXX_CPP_CORE=1`, their legacy C function
table objects are suppressed while all named `SPI_*` and `Wire_*` functions
remain available; that profile also enables the HAL-only `Wire_end()` release
operation without changing the legacy C function-table layout.  In C++
translation units, the bundled `<SPI.h>` and
`<Wire.h>` route to `SPIClass.h` and `WireClass.h`; the default C route and its
function-table syntax are unchanged.

Required driver policy:

```text
-std=c++11 (or newer)
-fno-exceptions
-fno-rtti
-fno-use-cxa-atexit
STCXX_CPP_CORE=1
```

The core root (`cores/STC`) is the public Arduino-library include directory.
It contains canonical forwarding headers for `<WString.h>`, `<Print.h>`,
`<Stream.h>`, `<Printable.h>`, `<pgmspace.h>`, `<IPAddress.h>`,
`<Client.h>`, `<Server.h>`, and `<Udp.h>`.  Those class-only headers
fail closed unless both C++ and `STCXX_CPP_CORE=1` are active.  The existing
core-root `<HardwareSerial.h>` preserves its complete plain-C
`HardwareSerialClass` facade, but conditionally routes to the real
`cpp/HardwareSerial.h` class under the same opt-in C++ condition.  Third-party
libraries therefore need only the normal core-root include path; they must not
depend on adding `cores/STC/cpp` as a second public include directory.

The top-level `Arduino.h` separately selects `cpp/ArduinoCpp.h` when the C++
profile is active, and the retained Wiring C declarations have C linkage.
Implementation sources in this directory continue to use their local headers.
These header routes alone do not enable C++; the explicit board menu profile
also selects the compiler bridge, target defines and link integration. The
default platform build remains plain C.

The class-to-HAL ABI is declared in `stc_c_hal.h` under `extern "C"`.  `String`
uses the replaceable C allocator ABI from `stcxx_allocator.h`; a target heap
may define `STCXX_CUSTOM_ALLOCATOR` and provide those three functions.

The default target allocator also exposes exact SDCC free-list telemetry through
the single `stcxx_allocator_read_telemetry(stcxx_allocator_telemetry_t *)`
snapshot API. Its packed result contains six `uint16_t` fields: arena size,
initial/current total free, current largest free block, and minimum total/
largest values. It establishes its baseline immediately
after `__sdcc_heap_init()` and samples the low-water marks after each successful
`stcxx_malloc()` or `stcxx_realloc()`.  Traversal fails closed on malformed,
cyclic, reverse, out-of-range, or overflowing free-list state.  The measurements
cover allocations routed through the `stcxx_*` ABI (including `new` and
`String`); a third-party library that calls libc `malloc()` directly is outside
this telemetry scope. The persistent state occupies a separate 8-byte XDATA core
archive member so the explicit heap object's XSEG remains exactly the selected
board arena and MCS51 IDATA stack headroom is unaffected.

The telemetry state variables are defined by the separate
`cores/STC/stcxx_heap_state.c` archive member: exactly 8 bytes of XDATA, no
IDATA and no second heap-provider symbol.  Keeping that state outside
`stcxx_heap.c` lets the link audit require the provider member's XSEG to equal
the configured arena exactly, while final XDATA accounting still includes the
additional 8-byte state member once.

## Deliberate feature gates

True Flash-string overloads are enabled only when the target
defines `STCXX_FLASH_STRINGS=1`, a real `STCXX_PGM_P` code-pointer type,
`STCXX_FLASH_READ_BYTE(pointer)`, and `STCXX_PROGMEM`.  Host tests enable a
same-address-space implementation with `STCXX_HOST_TEST`.  When this feature
is disabled, `F()`, `PSTR()`, `PROGMEM`, common `pgm_read_*` names, and the
canonical `String`/`Print` overloads for `const __FlashStringHelper *` remain
available as an explicitly labelled generic-data-pointer fallback.  This also
accepts flash-helper values returned by libraries such as ArduinoJson.  The
fallback keeps `F()`'s canonical static type as
`const __FlashStringHelper *`, so normal Arduino overload resolution is
preserved, but treats the underlying literal and all helper values as ordinary
data pointers; it does not qualify a Harvard code address space or save RAM.

The target include directory also supplies small freestanding C and C++
standard-header shims needed by common Arduino libraries.  They use the host
standard library outside the STC target, and provide only no-exception,
no-RTTI declarations/templates on the target; this is not a full hosted STL.
The C surface includes `<inttypes.h>` format macros derived from Clang's
TargetInfo and a deliberately limited `<stdio.h>` facade. `snprintf` uses a
bounded native-SDCC output callback, including size-zero counting and NUL
termination; `printf`/`puts`/`putchar` use UART1 after `Serial.begin` and
`getchar` waits for UART1 input. Formatting syntax is the installed SDCC
formatter's subset, not an assertion of full AVR-libc format support.
`FILE` is opaque only: file streams, scanf, and Clang-to-SDCC `va_list`
entry points produce explicit unsupported diagnostics. Use Arduino `File`
and `Stream` for those SDK abstractions. On the real STC
frontend/SDCC route, `Arduino.h` exposes the usual Arduino convenience
`stdlib.h`, `string.h`, and `math.h` declarations before defining Arduino
macros; native host conformance avoids glibc's incompatible POSIX
`random(void)` declaration.

`IPAddress` follows the ArduinoCore-API 1.5.2 IPv4/IPv6 and `Printable`
surface.  `Client`, `Server`, and `UDP` are abstract compatibility contracts;
the core does not claim to provide a TCP/IP stack.  The bundled SD library
adds a C++ `File`/`SDClass` adapter while retaining its existing root-only,
single-open-file backend constraints. FAT16/32 root 8.3 files now support
create/append/overwrite/flush/remove; directories, long names and power-fail
atomicity are not provided. `new.h` and global network class declarations
(with `arduino` namespace aliases) support AVR-style consumer source.

The bundled `SoftwareSerial` class retains one global polling HAL.  The last
object whose `begin()` or `listen()` succeeds owns that backend.  Inactive
objects return neutral read/status results, reject writes, and cannot close or
flush the active object; a rejected activation leaves the existing owner and
its configuration unchanged.  This ownership routing permits explicit object
switching but does not provide simultaneous receive or a background ISR.
`available/peek/read` now service polling RX automatically. LiquidCrystal and
Stepper, unlike SoftwareSerial, now retain independent state per C++ object.

UART framing is currently limited to `SERIAL_8N1`.  The two-argument `begin`
rejects every other configuration and exposes the state through
`configurationError()`; it does not silently ignore the requested framing.

SPI provides Arduino-shaped settings, begin/end, transactions, byte/word and
in-place buffer transfers.  The software HAL applies clock, bit order, and all
four modes. `usingInterrupt()` and `notUsingInterrupt()` register the interrupt
enables to save/mask/restore around a transaction; this is not a recursive mutex.
The legacy `SPI_CLOCK_DIV2` through `SPI_CLOCK_DIV128` constants and
`setClockDivider()` are provided, but the constants mean literal divisor
ratios: the requested software-bus clock becomes `F_CPU / divisor`.  They are
not AVR SPI-register encodings, and GPIO/software overhead means the physical
clock is not guaranteed to equal that request.  `attachInterrupt()` and
`detachInterrupt()` exist only as compatibility no-ops because this software
master has no hardware transfer-completion interrupt. New code should prefer
`SPISettings(clock, bitOrder, mode)`.

Wire is a controller-only, 7-bit-address implementation.  It provides
begin/end, clock and stretch-timeout configuration, buffered writes, repeated
starts, internal-register-address reads and Stream reads over configurable
C HAL buffers (default 32 bytes each). Timeout-status flags and optional
software-state reset/line release are implemented; `WIRE_HAS_TIMEOUT=1`.
Slave mode/callbacks and 10-bit addresses are not implemented (`WIRE_HAS_SLAVE=0`).

The portable runtime and its generated-constructor bridge contract are
specified in `docs/cpp-runtime-contract.md` and `runtime-manifest.json`.  Its
qualification set is 22 physical variants, 25 execution profiles, and 31
workloads using exact machines from locked QEMU commit
`faeac38c0076795d7b4e59f0ddcb5fc7e7bd7015`. Machine
availability and compile/link success are not runtime claims: each PASS must
bind the same source set, build manifest, firmware hash, tool audits, and
per-workload runtime result. Physical hardware remains `NOT_RUN` for every
variant unless separate board evidence explicitly says otherwise.
The final clean qualification run is being regenerated, so only the
authoritative, mutually hash-bound JSON may state its current outcome.
