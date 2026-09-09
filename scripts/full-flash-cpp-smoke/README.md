This Linux/WSL regression uses the existing locked Clang/LLVM-CBE frontend,
Arduino bridge adapter, and member-function alignment audit with an explicitly
selected rebuilt SDCC. It does not install or modify a published toolchain.

```sh
python3 scripts/check-full-flash-cpp-smoke.py \
  --sdcc /path/to/rebuilt/bin/sdcc \
  --assembler /path/to/rebuilt/bin/sdas251 \
  --runtime-root ../stcxx/out/share/sdcc \
  --work-dir /var/tmp/stc51-full-flash-cpp-smoke
```

The C++ fixture retains a dynamic global constructor, virtual call, direct
member-function pointer, and virtual member-function pointer. The runner binds
the direct member to `0xFF0800` and verifies final method addresses through the
existing alignment helper. Native `__code` arrays push the total image above
the previous 64/182 KiB limits and require data placement above HOME on K128
and K246. QEMU must print `CPP_FULL_FLASH_PASS` for both machines.

`commands.json`, the adapter and alignment audits, map/HEX files, UART logs, and
`result.json` remain in the requested work directory. `--frontend-only` checks
and records the LLVM/CBE/adapter portion before a candidate SDCC is available.
The outcome covers the supplied QEMU models; it does not qualify real hardware.
