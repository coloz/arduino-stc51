#!/usr/bin/env python3
"""Collect the exact LLVM definitions still referenced by native SDCC inputs.

LLVM cannot see references originating in separately compiled ``.rel`` files
or SDAR members.  This helper scans their textual symbol tables, subtracts
symbols also supplied natively, maps SDCC's one-character C name prefix back
to the source/LLVM spelling, and emits the public API list for LLVM's
``internalize`` pass.  C++ placeholder archive members are excluded by an
explicit, already hash-verified selection file.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path
import importlib.util

_archive_spec = importlib.util.spec_from_file_location('archive_members', Path(__file__).with_name('archive_members.py'))
_archive_module = importlib.util.module_from_spec(_archive_spec)
_archive_spec.loader.exec_module(_archive_module)
read_member = _archive_module.read_member


SYMBOL_PATTERN = re.compile(
    r"^S\s+(?P<name>\S+)\s+(?P<kind>Def|Ref)[0-9A-Fa-f]+$",
    re.MULTILINE,
)


def digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def decode_rel(payload: bytes, label: str) -> str:
    try:
        return payload.decode("ascii")
    except UnicodeDecodeError as error:
        raise SystemExit(f"non-ASCII SDCC relocatable input: {label}: {error}")


def parse_rel_symbols(payload: bytes, label: str) -> tuple[set[str], set[str]]:
    text = decode_rel(payload, label)
    definitions: set[str] = set()
    references: set[str] = set()
    for match in SYMBOL_PATTERN.finditer(text):
        destination = definitions if match.group("kind") == "Def" else references
        destination.add(match.group("name"))
    if not definitions and not references:
        raise SystemExit(f"no SDCC symbol table entries in native input: {label}")
    return definitions, references


def source_symbol(sdcc_symbol: str) -> str:
    """Undo exactly the single leading underscore added by SDCC's C ABI."""

    if not sdcc_symbol.startswith("_"):
        return sdcc_symbol
    return sdcc_symbol[1:]


def parse_llvm_definitions(ir: str) -> set[str]:
    symbols: set[str] = set()
    for line in ir.splitlines():
        if line.startswith("define "):
            if re.search(r"\b(?:internal|private)\b", line):
                continue
            match = re.search(r'@(?:"([^"]+)"|([-A-Za-z$._0-9]+))\(', line)
        elif line.startswith("@") and "=" in line:
            if re.search(r"=\s*(?:internal|private)\b", line):
                continue
            match = re.match(r'@(?:"([^"]+)"|([-A-Za-z$._0-9]+))\s*=', line)
        else:
            continue
        if match:
            name = match.group(1) or match.group(2)
            if not name.startswith("llvm."):
                symbols.add(name)
    return symbols


def read_cpp_members(path: Path) -> dict[Path, set[str]]:
    result: dict[Path, set[str]] = {}
    if not path.is_file():
        raise SystemExit(f"missing C++ archive-member selection: {path}")
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line:
            continue
        fields = line.split("\t")
        if len(fields) != 2:
            raise SystemExit(
                f"invalid C++ archive-member selection at {path}:{line_number}"
            )
        archive = Path(fields[0]).resolve()
        member = fields[1]
        members = result.setdefault(archive, set())
        if member in members:
            raise SystemExit(f"duplicate C++ archive member: {archive}: {member}")
        members.add(member)
    return result


def run() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ir", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--audit-json", required=True, type=Path)
    parser.add_argument("--sdar", required=True, type=Path)
    parser.add_argument("--cpp-members", required=True, type=Path)
    parser.add_argument("--direct-rel", action="append", default=[], type=Path)
    parser.add_argument("--archive", action="append", default=[], type=Path)
    parser.add_argument("--required-root", action="append", default=[])
    args = parser.parse_args()

    llvm_definitions = parse_llvm_definitions(args.ir.read_text(encoding="utf-8"))
    selected_cpp_members = read_cpp_members(args.cpp_members)
    native_definitions: set[str] = set()
    native_references: set[str] = set()
    inputs: list[dict[str, object]] = []

    def consume(payload: bytes, label: str, kind: str) -> None:
        definitions, references = parse_rel_symbols(payload, label)
        native_definitions.update(definitions)
        native_references.update(references)
        inputs.append({
            "kind": kind,
            "label": label,
            "sha256": digest(payload),
            "definition_count": len(definitions),
            "reference_count": len(references),
        })

    for path in args.direct_rel:
        resolved = path.resolve()
        if not resolved.is_file():
            raise SystemExit(f"missing native direct relocatable: {resolved}")
        consume(resolved.read_bytes(), str(resolved), "direct-rel")

    for archive_value in args.archive:
        archive = archive_value.resolve()
        if not archive.is_file():
            raise SystemExit(f"missing native archive: {archive}")
        listing = subprocess.run(
            [str(args.sdar), "-t", str(archive)],
            check=True,
            stdout=subprocess.PIPE,
        ).stdout.decode("utf-8").splitlines()
        if len(listing) != len(set(listing)):
            raise SystemExit(f"duplicate member names in SDAR archive: {archive}")
        excluded = selected_cpp_members.get(archive, set())
        unknown = sorted(excluded - set(listing))
        if unknown:
            raise SystemExit(
                f"selected C++ member missing from {archive}: {', '.join(unknown)}"
            )
        for member in listing:
            if member in excluded:
                continue
            payload = read_member(args.sdar, archive, member)
            consume(payload, f"{archive}({member})", "native-archive-member")

    unresolved_native = native_references - native_definitions
    referenced_llvm = {
        source_symbol(symbol)
        for symbol in unresolved_native
        if source_symbol(symbol) in llvm_definitions
    }
    required = set(args.required_root)
    missing = sorted(required - llvm_definitions)
    if missing:
        raise SystemExit("missing required LLVM bridge root(s): " + ", ".join(missing))
    roots = sorted(required | referenced_llvm)
    if not roots:
        raise SystemExit("empty LLVM preservation root set")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("\n".join(roots) + "\n", encoding="utf-8", newline="\n")
    audit = {
        "schema_version": 1,
        "outcome": "pass",
        "policy": "required-bridge-roots-plus-unresolved-native-sdcc-refs",
        "archive_reference_model": "all-non-cpp-members-conservative-overapproximation",
        "archive_reference_model_limitation": (
            "References from every native archive member are considered before "
            "the SDCC linker's member-pull fixed point. This may preserve an extra "
            "LLVM C ABI root, but can never omit a root required by a native member."
        ),
        "llvm_public_definition_count": len(llvm_definitions),
        "native_definition_count": len(native_definitions),
        "native_reference_count": len(native_references),
        "native_unresolved_count": len(unresolved_native),
        "referenced_llvm_roots": sorted(referenced_llvm),
        "required_roots": sorted(required),
        "preserved_roots": roots,
        "inputs": inputs,
    }
    args.audit_json.write_text(
        json.dumps(audit, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    print(",".join(roots))
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
