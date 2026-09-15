# C++ library target probes

`LibraryProbes.ino` compiles one actual installed library at a time. Select
`STCXX_LIBRARY_CASE=1..6` with the C++ build flags. No backend is replaced.
All selected logical pins exist, are distinct physical pads in the declared
model pin maps, and avoid UART1 P3.0/P3.1. Actual package wiring still needs
separate qualification; these probes are intended for QEMU.

| Case | Library | Checks | Runtime scope |
| --- | --- | --- | --- |
| 1 | Wire | 11 | Invalid/recovered pin configuration, empty receive state, transmit buffer overflow, null buffer, timeout flag and end/reset |
| 2 | SPI | 11 | Invalid/recovered pins/settings, transaction nesting rejection, reconfiguration while busy, clock divider and end/reset |
| 3 | SoftwareSerial | 12 | Begin/listen/stop/end, invalid configuration preserving the current port, copy/assignment ownership and inactive writes |
| 4 | LiquidCrystal | 9 | Valid/invalid objects, character writes, independent copied context and rejected display geometry |
| 5 | Stepper | 10 | Configuration, speed rejection/recovery, independent object/copy state, forward/reverse step and release |
| 6 | SD | 12 | Invalid pins, unmounted open/exists/remove, invalid File copies/moves/writes/seek/iteration and unsupported directories |

UART reporting uses the native C boundary to avoid including unrelated C++
formatting functions solely for the test report. Each fixed oracle includes
the library name, check count and final status. Failed checks print their
index. A build error or insufficient Flash remains a failed case.

From Linux/WSL, test all six libraries on every declared C++ board/clock
profile at `Oz` using a staged candidate:

```sh
python3 scripts/check-library-targets.py \
  --platform /path/to/installed/hardware/mcs251/0.0.3 \
  --config /path/to/arduino-cli.json --cli /path/to/arduino-cli \
  --qemu /path/to/qemu-system-mcs251 --output .build/library-targets
```

For a smaller diagnostic run, add `--board stc32g12k128 --clock 12000000
--library SPI --optimization 0`. Selection options are repeatable; unsupported
or duplicate profiles are rejected. Use a new output directory for each run.

Successful QEMU checks do not certify I2C slave traffic, SPI transfer data,
UART bit timing, an attached LCD/motor, SD card media, FAT data operations or
physical pin multiplexing. The actual FAT backend has a separate host suite;
hardware bus and product reliability testing remain separate release gates.
