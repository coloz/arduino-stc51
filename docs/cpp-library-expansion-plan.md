# STC C++ library expansion

Scope: improve the six bundled libraries first, then qualify the twenty application
libraries frozen in `tests/cpp/library-compat/common20-lock.json`. Adafruit BusIO
and Unified Sensor are dependencies, not additional successes towards twenty.

1. Fix actual bundled-library behavior: SPI interrupt transactions, Wire timeout
   reporting and register reads, SoftwareSerial receive servicing, independent LCD
   and Stepper instances, and SD file operations against FAT image fixtures.
2. Repair Core compatibility regressions exposed by AVR comparison and library
   builds. Preserve ABI safety; no mock success for missing hardware capabilities.
3. Download and SHA-256 verify original upstream archives. Analyze each library's
   API, C++ requirements, architecture assumptions and hardware dependencies.
4. Compile and link representative real sketches for both MCS51 and MCS251.
   Run deterministic behavior probes where an oracle exists. A header-only syntax
   probe, a link success, a HAL fixture, QEMU and hardware runs are distinct results.
5. Resolve compiler/Core failures, retain diagnostics and resource usage for every
   case, and rerun the all-variant Core matrix after implementation stabilizes.
6. Refresh hashes and qualification evidence only from the final source state.
   Previous retained evidence describes its original snapshot, not modified code.

The requested scope includes implementation and verification, not publishing a
release or flashing an unspecified physical board. Hardware-only timing and
unmodeled peripheral behavior remain explicitly unqualified.
