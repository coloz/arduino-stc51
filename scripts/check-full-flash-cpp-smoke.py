#!/usr/bin/env python3
"""Run the audited C++ bridge and full-Flash linker on two MCS251 QEMU models.

Run under Linux/WSL with a rebuilt SDCC selected explicitly. This development
regression records its exact candidate tools and never changes published locks.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "scripts/full-flash-cpp-smoke"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_hex(path: Path) -> dict[int, int]:
    image = {}
    base = 0
    eof = False
    for line in path.read_text().splitlines():
        record = bytes.fromhex(line[1:])
        if eof or not line.startswith(":") or len(record) != record[0] + 5 or sum(record) & 255:
            raise RuntimeError(f"invalid Intel HEX record in {path}")
        count, kind = record[0], record[3]
        address = int.from_bytes(record[1:3], "big")
        if kind == 0:
            for index, value in enumerate(record[4:4 + count]):
                absolute = base + address + index
                if absolute in image:
                    raise RuntimeError(f"overlapping Intel HEX payload at {absolute:x}")
                image[absolute] = value
        elif kind == 4 and count == 2 and address == 0:
            base = int.from_bytes(record[4:6], "big") << 16
        elif kind == 1 and count == 0 and address == 0:
            eof = True
        else:
            raise RuntimeError(f"unsupported Intel HEX record kind {kind}")
    if not eof:
        raise RuntimeError("Intel HEX lacks EOF")
    return image


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sdcc", type=Path)
    parser.add_argument("--compiler-elf", type=Path)
    parser.add_argument("--assembler", type=Path)
    parser.add_argument("--runtime-root", type=Path, default=ROOT.parent / "stcxx/out/share/sdcc")
    parser.add_argument("--include-root", type=Path)
    parser.add_argument("--clang", type=Path, default=Path.home() / ".cache/arduino-stc51/clang-build-20.1.8/bin/clang")
    parser.add_argument("--llvm-cbe", type=Path, default=Path("/var/tmp/arduino-stc51-cpp-bridge/llvm-cbe-local/build/tools/llvm-cbe/llvm-cbe"))
    parser.add_argument("--opt", type=Path, default=Path("/usr/bin/opt-20"))
    parser.add_argument("--llvm-dis", type=Path, default=Path("/usr/bin/llvm-dis-20"))
    parser.add_argument("--qemu", type=Path, default=Path("/var/tmp/arduino-stc51-qemu-build-all-variants-v2/qemu-system-mcs251"))
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--machine", choices=("stc32g12k128", "stc32g144k246"), action="append")
    parser.add_argument("--frontend-only", action="store_true")
    args = parser.parse_args()
    # Preserve compiler symlink entry points, but make paths independent of
    # the per-target subprocess working directory.
    for attribute in ("sdcc", "compiler_elf", "assembler", "runtime_root", "include_root", "clang", "llvm_cbe", "opt", "llvm_dis", "qemu"):
        value = getattr(args, attribute)
        if value is not None:
            setattr(args, attribute, value.absolute())
    work = args.work_dir.resolve()
    work.mkdir(parents=True, exist_ok=True)
    lock = json.loads((ROOT / "tools/cpp-cli/toolchain-lock.json").read_text())
    profile = lock["targets"]["mcs251"]
    adapter = ROOT / "tools/cpp-cli/adapt.py"
    aligner = ROOT / "tools/cpp-cli/align-member-functions.py"
    tools = {"clang": args.clang, "llvm_cbe": args.llvm_cbe, "opt": args.opt, "llvm_dis": args.llvm_dis}
    for name, path in tools.items():
        if digest(path) != lock["tools"][name]["sha256"]:
            raise RuntimeError(f"locked frontend identity differs: {name}: {path}")
    tools.update({"adapter": adapter, "aligner": aligner, "runner": Path(__file__).resolve(),
                  "shared_adapter": ROOT / "tools/cpp-core-pipeline/audit_and_adapt.py"})
    commands = []

    def run(command, directory=work):
        command = [str(value) for value in command]
        record = {"command": command, "cwd": str(directory)}
        commands.append(record)
        result = subprocess.run(command, cwd=directory, capture_output=True, text=True)
        record.update({"returncode": result.returncode, "stdout": result.stdout, "stderr": result.stderr})
        (work / "commands.json").write_text(json.dumps(commands, indent=2) + "\n")
        if result.returncode:
            raise RuntimeError(f"command failed: {command!r}\n{result.stdout}\n{result.stderr}")
        return result.stdout

    preserve = sorted(["setup", "loop", "__stcxx_run_global_ctors", profile["abi_identity_symbol"], "stcxx_runtime_panic"])
    preserve_path = work / "preserve.txt"
    preserve_path.write_text("\n".join(preserve) + "\n")
    bc, optimized, ir = (work / name for name in ("probe.bc", "optimized.bc", "optimized.ll"))
    run([args.clang, f"--target={profile['target_triple']}", "-x", "c++", "-std=gnu++11", "-O0",
         "-ffreestanding", "-fno-builtin", "-funsigned-char", "-fno-exceptions", "-fno-rtti",
         "-fno-threadsafe-statics", "-fno-use-cxa-atexit", "-fno-c++-static-destructors",
         "-fno-unwind-tables", "-fno-asynchronous-unwind-tables", "-Xclang", "-mno-constructor-aliases",
         "-Xclang", "-disable-O0-optnone", "-nostdinc", "-Werror", "-emit-llvm", "-c",
         FIXTURES / "probe.cpp", "-o", bc])
    run([args.opt, "-passes=internalize,globaldce", "-internalize-public-api-list=" + ",".join(preserve), bc, "-o", optimized])
    run([args.llvm_dis, optimized, "-o", ir])
    run([args.llvm_cbe, optimized, "-o", work / "raw.c"])
    run([sys.executable, adapter, "--ir", ir, "--raw-c", work / "raw.c", "--c-abi-preserve", preserve_path,
         "--output-c", work / "adapted.c", "--audit-json", work / "adapter-audit.json",
         "--expected-triple", profile["target_triple"], "--expected-layout", profile["data_layout"],
         "--abi-identity-symbol", profile["abi_identity_symbol"], "--target-profile", "mcs251"])
    adapter_audit = json.loads((work / "adapter-audit.json").read_text())
    if not adapter_audit["ir"]["constructors"]:
        raise RuntimeError("C++ smoke lost its global constructor")
    if not adapter_audit["ir"]["pointer_integer_conversions"]["member_function_symbols"]:
        raise RuntimeError("C++ smoke lost its nonvirtual member-function pointer")
    evidence = {"tools": {name: {"path": str(path), "sha256": digest(path)} for name, path in tools.items()},
                "fixtures": {path.name: digest(path) for path in FIXTURES.iterdir() if path.is_file()},
                "scope": "candidate-toolchain C++ constructor/virtual/member-pointer/full-Flash QEMU regression",
                "frontend_outcome": "PASS", "constructor_count": len(adapter_audit["ir"]["constructors"]),
                "member_function_symbols": adapter_audit["ir"]["pointer_integer_conversions"]["member_function_symbols"],
                "targets": []}
    if args.frontend_only:
        (work / "result.json").write_text(json.dumps(evidence, indent=2) + "\n")
        print("FULL_FLASH_CPP_FRONTEND=PASS")
        return
    if not args.sdcc or not args.assembler:
        parser.error("--sdcc and --assembler are required unless --frontend-only")
    evidence["tools"].update({name: {"path": str(path), "sha256": digest(path)}
                              for name, path in {"sdcc": args.sdcc, "assembler": args.assembler, "qemu": args.qemu}.items()})
    compiler_elf = args.compiler_elf
    if compiler_elf is None:
        compiler_elf = next((path for path in (args.sdcc.parent.parent / "src/sdcc", args.sdcc.parent.parent / "libexec/sdcc", args.sdcc)
                             if path.is_file() and path.read_bytes()[:4] == b"\x7fELF"), None)
    if compiler_elf is None or compiler_elf.read_bytes()[:4] != b"\x7fELF":
        raise RuntimeError("cannot identify the executed SDCC ELF; supply --compiler-elf")
    candidate_linker = args.sdcc.parent / "sdldmcs251"
    if not candidate_linker.is_file():
        raise RuntimeError("candidate compiler bin directory lacks sdldmcs251")
    evidence["tools"].update({name: {"path": str(path), "sha256": digest(path)}
                              for name, path in {"sdcc_elf": compiler_elf, "sdldmcs251": candidate_linker}.items()})
    include_root = args.include_root or args.runtime_root / "include"
    evidence["runtime_inputs"] = {
        "include_root": str(include_root),
        "headers": {name: digest(include_root / name) for name in ("stddef.h", "stdint.h")},
        "libraries": {str(path): digest(path) for path in sorted((args.runtime_root / "lib/mcs251-large-stack-auto").glob("*.lib"))},
    }
    base = [args.sdcc, "-mmcs251", "--model-large", "--stack-auto", "--std-sdcc11", "--opt-code-size",
            "--function-sections", "--data-sections", "-I" + str(include_root),
            "-I" + str(include_root / "mcs51")]
    for machine, floor, blob_count, blob_size, iram in (
        ("stc32g12k128", 0xfe0000, 2, 50000, 4096),
        ("stc32g144k246", 0xfc2800, 4, 56000, 16384),
    ):
        if args.machine and machine not in args.machine:
            continue
        target_work = work / machine
        target_work.mkdir(exist_ok=True)
        raw_asm, asm, rel, hex_path = (target_work / name for name in ("bridge.raw.asm", "bridge.asm", "bridge.rel", "firmware.hex"))
        alignment_audit = target_work / "alignment.json"
        run([*base, "--nogcse", "--less-pedantic", "-S", work / "adapted.c", "-o", raw_asm], target_work)
        run([sys.executable, aligner, "align", "--input-assembly", raw_asm, "--output-assembly", asm,
             "--adapter-audit", work / "adapter-audit.json", "--target-profile", "mcs251", "--local-parity", "even",
             "--audit-json", alignment_audit], target_work)
        run([args.assembler, "-plosgffw", rel, asm], target_work)
        run([*base, f"-DFULL_FLASH_CPP_BLOB_COUNT={blob_count}", f"-DFULL_FLASH_CPP_BLOB_BYTES={blob_size}UL",
             "-c", FIXTURES / "runtime.c", "-o", target_work / "runtime.rel"], target_work)
        # Pin the direct member-pointer target high. Every other bridge function
        # remains automatically placed, exercising ECALL/function relocations.
        member_symbols = adapter_audit["ir"]["pointer_integer_conversions"]["member_function_symbols"]
        direct_symbol = next(symbol for symbol in member_symbols if "direct" in symbol)
        current_area = None
        direct_area = None
        for line in asm.read_text().splitlines():
            match = re.fullmatch(r"\s*\.area\s+(\S+)\s+\(CODE\)\s*", line)
            if match:
                current_area = match.group(1)
            if line.strip() == "_" + direct_symbol + ":":
                direct_area = current_area
        if not direct_area or not direct_area.startswith("CSEG_F_"):
            raise RuntimeError("could not bind the C++ direct member function to its named section")
        run([*base, "--code-loc", "0xff0000", "--code-size", str(0x1000000 - floor),
             "--xram-size", "8192" if blob_count == 2 else "131072", "--iram-size", str(iram),
             "--stack-loc", "0x100", "--stack-size", str(iram - 256),
             f"-Wl-b GSINIT0=0x{floor:x}", f"-Wl-b {direct_area}=0xff0800",
             f"-Wl--code-window=0x{floor:x}:0x1000000", "-L" + str(args.runtime_root / "lib/mcs251-large-stack-auto"),
             target_work / "runtime.rel", rel, "--out-fmt-ihx", "-o", hex_path], target_work)
        run([sys.executable, aligner, "verify", "--audit-json", alignment_audit,
             "--relocated-listing", target_work / "bridge.rst", "--target-profile", "mcs251"], target_work)
        mapped = (target_work / "firmware.map").read_text()
        areas = [(name, int(start, 16), int(size, 16)) for name, start, size in re.findall(
            r"^Code Window Area: (\S+) 0x([0-9A-Fa-f]+) 0x([0-9A-Fa-f]+)$", mapped, re.MULTILINE)]
        previous_end = floor
        for name, start, size in sorted(areas, key=lambda item: item[1]):
            if start < previous_end or start + size > 0x1000000:
                raise RuntimeError(f"overlapping or out-of-Flash CODE allocation: {name}")
            previous_end = start + size
        direct_allocations = [(start, size) for name, start, size in areas if name == direct_area]
        if len(direct_allocations) != 1 or direct_allocations[0][0] != 0xff0800:
            raise RuntimeError("the direct member function did not retain its high-Flash binding")
        if not areas or sum(size for _, _, size in areas) <= 0xff0000 - floor:
            raise RuntimeError("C++ pressure image does not exceed the former pre-HOME limit")
        if not any(name.startswith("CONST_D_") and start > 0xff0000 for name, start, _ in areas):
            raise RuntimeError("C++ pressure image did not place a constant above HOME")
        image = read_hex(hex_path)
        if min(image) < floor or max(image) >= 0x1000000:
            raise RuntimeError("Intel HEX payload escapes physical Flash")
        for index in range(blob_count):
            blobs = [(start, size) for name, start, size in areas if name.startswith(f"CONST_D__cpp_flash_blob{index}_")]
            if len(blobs) != 1 or blobs[0][1] != blob_size:
                raise RuntimeError(f"blob {index} lacks its complete independent allocation")
            start, size = blobs[0]
            if image.get(start) != 0x10 + index or image.get(start + size - 1) != 0xa0 + index:
                raise RuntimeError(f"blob {index} first/last bytes differ from the initializer")
        qemu_command = [str(args.qemu), "-M", machine, "-nographic", "-monitor", "none", "-serial", "stdio", "-bios", str(hex_path)]
        try:
            qemu_result = subprocess.run(qemu_command, capture_output=True, timeout=8)
            output, errors = qemu_result.stdout, qemu_result.stderr
        except subprocess.TimeoutExpired as error:
            output = error.stdout or b""
            errors = error.stderr or b""
        (target_work / "qemu.log").write_bytes(output)
        (target_work / "qemu.stderr.log").write_bytes(errors)
        if b"CPP_FULL_FLASH_PASS\n" not in output or b"FAIL" in output or b"PANIC" in output:
            raise RuntimeError(f"{machine}: QEMU did not report C++ full-Flash PASS: {output!r}; stderr: {errors!r}")
        evidence["targets"].append({"machine": machine, "outcome": "PASS", "code_bytes": sum(size for _, _, size in areas),
            "direct_member_section": direct_area, "direct_member_address": "0xff0800", "qemu_command": qemu_command,
            "artifacts": {path.name: digest(path) for path in (hex_path, target_work / "firmware.map", alignment_audit, target_work / "qemu.log", target_work / "qemu.stderr.log")}})
        (work / "result.json").write_text(json.dumps(evidence, indent=2) + "\n")
        print(f"FULL_FLASH_CPP_QEMU=PASS machine={machine}", flush=True)


if __name__ == "__main__":
    main()
