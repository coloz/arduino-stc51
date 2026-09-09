#!/usr/bin/env python3
"""Compile both heap ABIs and exercise the CLI's actual Python audit gates.

Object fixtures start with freshly compiled production sources. Final-link
tests use synthetic maps, not simulated firmware or hardware qualification.
All compiler output and gate fixtures stay in the requested work directory.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]
STATE_SYMBOLS = (
    "___stcxx_heap_telemetry_ready_state",
    "___stcxx_heap_telemetry_valid_state",
    "___stcxx_heap_initial_total_free_state",
    "___stcxx_heap_minimum_total_free_state",
    "___stcxx_heap_minimum_largest_free_state",
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sdcc", required=True, help="SDCC executable (both targets required)")
    parser.add_argument("--tool-bin", type=Path, help="prepend assembler/preprocessor directory to PATH")
    parser.add_argument("--sdcc-include", type=Path, help="SDCC headers, for an uninstalled compiler")
    parser.add_argument("--workdir", type=Path, help="artifact directory (defaults to a new temporary directory)")
    args = parser.parse_args()
    compiler = shutil.which(args.sdcc)
    if compiler is None:
        parser.error(f"cannot find SDCC: {args.sdcc}")
    work = (args.workdir or Path(tempfile.mkdtemp(prefix="stc-heap-abi-"))).resolve()
    work.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    tool_bin = args.tool_bin or Path(compiler).parent
    env["PATH"] = str(tool_bin.resolve()) + os.pathsep + env.get("PATH", "")
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    blocks = re.findall(r"<<'PY'\n(.*?)\nPY", (ROOT / "tools/cpp-cli/stcxx-cli.sh").read_text(), re.S)

    def gate(marker: str, name: str) -> Path:
        matches = [block for block in blocks if marker in block]
        if len(matches) != 1:
            raise SystemExit(f"expected one actual CLI gate for {name}, observed {len(matches)}")
        path = work / name
        path.write_text(matches[0] + "\n", encoding="utf-8")
        return path

    prelink = gate("heap_rel = Path(sys.argv[1])", "prelink-gate.py")
    final = gate("heap-link audit argument vector differs", "final-gate.py")
    results = []

    def run(argv: list[str]) -> subprocess.CompletedProcess:
        return subprocess.run(argv, text=True, stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT, env=env)

    def check(name: str, argv: list[str], diagnostic: str | None = None) -> None:
        result = run([sys.executable, *argv])
        passed = result.returncode == 0 if diagnostic is None else (
            result.returncode != 0 and diagnostic in result.stdout
        )
        record = {"case": name, "outcome": "pass" if passed else "fail",
                  "accepted": result.returncode == 0, "diagnostic": result.stdout}
        results.append(record)
        (work / "report.json").write_text(json.dumps(results, indent=2) + "\n")
        print(f"{record['outcome'].upper()}: {name}")
        if not passed:
            raise SystemExit(f"unexpected gate result for {name}:\n{result.stdout}")

    for target, size in (("mcs251", 4096), ("mcs51", 512)):
        directory = work / target
        directory.mkdir(exist_ok=True)

        def write(name: str, text: str) -> Path:
            path = directory / name
            path.write_text(text, encoding="ascii")
            return path

        for module in ("stcxx_heap", "stcxx_heap_state"):
            command = [compiler, "-m" + target, "--model-large", "--stack-auto",
                       "--std-sdcc11", "-DSTCXX_CPP_CORE=1", f"-DSTCXX_HEAP_SIZE={size}UL",
                       "-I" + str(ROOT / "cores/STC")]
            if args.sdcc_include:
                command += ["-I" + str(args.sdcc_include.resolve())]
            command += ["-c", str(ROOT / f"cores/STC/{module}.c"),
                        "-o", str(directory / f"{module}.rel")]
            result = run(command)
            if result.returncode:
                raise SystemExit(f"cannot compile {target}/{module}:\n{result.stdout}")
        heap = directory / "stcxx_heap.rel"
        state = directory / "stcxx_heap_state.rel"
        expected = "___sdcc_heap_size32" if target == "mcs251" else "___sdcc_heap_size"
        opposite = "___sdcc_heap_size" if target == "mcs251" else "___sdcc_heap_size32"
        assembly = (directory / "stcxx_heap.asm").read_text()
        value = re.search(rf"^{re.escape(expected)}:\n\s*\.byte ([^;\n]+)", assembly, re.M)
        wanted = [0, 0, 0x10, 0] if target == "mcs251" else [0, 2]
        if value is None or [int(byte.strip().removeprefix("#"), 0)
                             for byte in value[1].split(",")] != wanted:
            raise SystemExit(f"wrong {target} heap-size constant width/value")
        print(f"PASS: {target}-size-constant-{len(wanted)}-bytes")

        def precheck(name: str, h: Path, s: Path = state, diagnostic: str | None = None) -> None:
            check(target + "-prelink-" + name,
                  [str(prelink), str(h), str(s), target, "0"], diagnostic)

        payload = heap.read_text()
        precheck("valid", heap)
        wrong = write("wrong-size-symbol.rel", payload.replace(expected, opposite))
        precheck("wrong-name", wrong, diagnostic="must not provide opposite-ABI")
        dual = write("dual-size-symbol.rel", payload + f"S {opposite} Def000000\n")
        precheck("dual-name", dual, diagnostic="must not provide opposite-ABI")
        missing = write("missing-size-symbol.rel", re.sub(
            rf"^S {re.escape(expected)} Def[0-9A-Fa-f]+\n", "", payload, flags=re.M))
        precheck("missing-name", missing, diagnostic=f"must define {expected} exactly once")
        polluted_states = []
        for symbol in (expected, opposite):
            polluted = write(symbol + "-state.rel", state.read_text() + f"S {symbol} Def000000\n")
            polluted_states.append(polluted)
            precheck("state-" + symbol, heap, polluted, "heap-state object must not provide")

        core = write("core.a", "synthetic archive fixture; gate checks its digest only\n")
        members = write("members.txt", "stcxx_heap_state.c.rel\n")
        log = write("link.log", "")
        stack = ["0x10000", "0x1000", "0x1000"] if target == "mcs251" else ["", "", ""]
        arguments = [str(heap), str(core.with_suffix(".lib"))]
        if target == "mcs251":
            for flag, value in zip(("--iram-size", "--stack-loc", "--stack-size"), stack):
                arguments += [flag, value]
        link_args = write("link-arguments.txt", "\n".join(arguments) + "\n")
        map_text = str(heap) + "\n[ stcxx_heap_state.c.rel ]\n"
        for symbol in ("___sdcc_heap", expected, "___stcxx_heap_init"):
            map_text += f"C: 000100 {symbol} stcxx_heap\n"
        for symbol in STATE_SYMBOLS:
            map_text += f"D: 000100 {symbol[:32]} stcxx_heap_state\n"
        map_text += f"C: {size + 8:06X} l_XSEG\n"
        link_map = write("firmware.map", map_text)

        def finalcheck(name: str, s: Path = state, diagnostic: str | None = None) -> None:
            check(target + "-final-" + name, [str(final), str(directory / "final-audit.json"),
                  str(log), str(link_args), str(link_map), str(heap), str(s), str(core),
                  str(members), str(ROOT / "tools/cpp-cli/aslink_map_symbols.py"), target, *stack], diagnostic)

        finalcheck("valid")
        for module in ("stcxx_heap", "unrelated_legacy_object"):
            link_map.write_text(map_text + f"C: 000200 {opposite} {module}\n")
            finalcheck("dual-name-" + module, diagnostic="opposite-ABI heap-size provider")
        link_map.write_text(map_text.replace(expected + " stcxx_heap", opposite + " stcxx_heap"))
        finalcheck("wrong-name", diagnostic="opposite-ABI heap-size provider")
        link_map.write_text(map_text)
        for polluted in polluted_states:
            finalcheck("state-" + polluted.stem, polluted, "telemetry-state object provides a heap symbol")
    print(f"PASS: {len(results)} actual-gate cases plus both compiled ABI widths; artifacts: {work}")


if __name__ == "__main__":
    main()
