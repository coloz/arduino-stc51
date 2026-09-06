# Native constant storage: implementation plan

Status: root cause verified; general production integration pending.

## Reproducer and evidence

Native MCS51 SDCC places the U8g2 rotation callback tables in `CONST` (CODE).
Clang emits their `extern const` aggregate declarations as `external global`,
so the current CBE declaration loses native storage information. The generated
generic pointer gets RAM tag `0x00`, and the native constructor reads an invalid
callback instead of using Flash tag `0x80`. Ordinary stock Clang behaves the
same way; `tests/cpp/abi/native-const-address-probe.cpp` is the small reproducer.
This is a cross-language storage contract, not a U8g2-name special case.

- Original inputs: `tmp/common20-platform-v6/u8g2-graphics-buffer-extra-v1`.
- Diagnostic: `tmp/u8g2-mcs51-const-code-tag-v1/result.json`, SHA256
  `dcd25d35bd92285a25af52b01612a7de80650cad1d1d13b751cfec712711a8ef`.
- Three generated pointer-tag corrections make the unchanged 2,176-check
  full/page/rotation oracle pass QEMU; ROM is 62,763/65,536, XRAM 5,783/8,192.
  The diagnostic reuses native objects and does not qualify the SDK.

## Implementation order

1. Add a native object-storage collector adjacent to
   `tools/cpp-cli/collect-c-abi-roots.py`. Consume the actual link's direct RELs
   and archive members, excluding C++ placeholder objects. Reuse the strict
   ASxxxx parsing rules in the existing REL slicer/archive tools; distinguish
   a symbol definition from its area and address rather than inferring storage
   from spelling. Bind every participating REL, archive, member and tool hash.
   Reject duplicate/ambiguous definitions, invalid indices, unknown target
   areas, and inputs changed during collection.
2. In `stcxx-cli.sh`, collect storage alongside the native C ABI roots before
   final CBE adaptation. Pass an explicit audited storage map to `adapt.py`.
   For proven MCS51 native CODE *object* declarations, emit `__code` storage so
   SDCC creates the correct generic pointer and read instruction. Do not treat
   function declarations as objects, or assume LLVM `global` means RAM.
   Preserve known RAM objects and MCS251's flat-address ABI. Reject writes to
   proven CODE objects and unsupported declaration forms. A C++ dynamically
   initialized const object or a native explicit XDATA const must remain RAM.
3. Validate the final link's actual member selection and symbol areas against
   that storage map. If archive selection cannot be determined beforehand,
   use an explicit bounded two-stage link and require stable selection/storage;
   never accept an unaudited provisional executable. Add collector, adapter,
   tests and hashes to both toolchain locks and the standalone mirror.
4. Independently integrate finer function selection for eligible ordinary C
   translation units. The U8g2 experiment showed 84,604 -> 62,757 bytes before
   pointer corrections. Preserve the existing static-data, macro-definition,
   relocation, alias, and final-map audits; do not raise Flash limits or silently
   remove graphics checks. The safe bodyless-declaration splitter fix already
   has real-Clang positive/negative tests.

## Acceptance gates

- Minimal mixed native-C/C++ tests for byte arrays and callback aggregates in
  CODE, ordinary writable RAM, explicit XDATA const, and dynamically initialized
  C++ const; inspect tags and execute reads/callbacks on both CPUs.
- Negative tests for duplicate symbols, forged/stale storage maps, member
  substitution, unknown areas, indirect CODE writes, and selection changes.
- Fresh unmodified U8g2 library builds and the existing full/page/rotation QEMU
  oracle on MCS51 and MCS251, including warning, heap, capacity and link audits.
- Repeat the pinned 20-library matrix and evaluate every physical device/profile
  at its actual memory limit. A too-small variant is a reported capacity limit,
  not a waived or inflated pass. Physical display/I2C timing, fonts and all
  display drivers require separate probes; this graphics oracle does not cover
  them.

All-variant release evidence also requires the unchanged standalone-source
provenance gate. These steps do not authorize implicit Git commits.
