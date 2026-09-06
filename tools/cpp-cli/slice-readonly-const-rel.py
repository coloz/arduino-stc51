#!/usr/bin/env python3
"""Fail-closed slicer for oversized, relocation-free ASxxxx CONST modules."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path


AREA_RE = re.compile(
    r"^A (?P<name>\S+) size (?P<size>[0-9A-F]+) "
    r"flags (?P<flags>[0-9A-F]+) addr (?P<addr>[0-9A-F]+)$"
)
HEADER_RE = re.compile(
    r"^H (?P<areas>[0-9A-F]+) areas "
    r"(?P<symbols>[0-9A-F]+) global symbols$"
)
SYMBOL_RE = re.compile(
    r"^S (?P<name>\S+) (?P<kind>Def|Ref)(?P<value>[0-9A-F]+)$"
)
ARRAY_RE = re.compile(
    r"^\s*const\s+uint8_t\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)"
    r"\s*\[\s*(?P<size>[0-9]+)\s*\]\s+[^;=]*=\s*$",
    re.MULTILINE,
)


def digest_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def digest_path(path: Path) -> str:
    return digest_bytes(path.read_bytes())


def fail(message: str) -> None:
    raise SystemExit(f"readonly CONST REL audit failed: {message}")


@dataclass(frozen=True)
class Area:
    index: int
    name: str
    size: int
    flags: int
    addr: int
    line_index: int


@dataclass(frozen=True)
class Definition:
    name: str
    offset: int
    area_index: int


@dataclass
class RelFile:
    path: Path
    raw: bytes
    lines: list[str]
    first_text_index: int
    areas: list[Area]
    definitions: list[Definition]
    references: set[str]
    const_area: Area
    const_data: bytes
    empty_area_markers: list[int]
    redundant_const_markers: list[int]


def parse_rel(path: Path, *, require_slice_shape: bool) -> RelFile:
    raw = path.read_bytes()
    try:
        text = raw.decode("ascii")
    except UnicodeDecodeError as error:
        fail(f"{path}: non-ASCII REL: {error}")
    lines = text.splitlines()
    if not lines or lines[0] != "XH3":
        fail(f"{path}: expected XH3 ASxxxx object")
    if len(lines) < 4 or not HEADER_RE.fullmatch(lines[1]):
        fail(f"{path}: malformed H record")

    areas: list[Area] = []
    definitions: list[Definition] = []
    references: set[str] = set()
    current_area = -1
    first_text_index = len(lines)
    for index, line in enumerate(lines[2:], start=2):
        if line.startswith("T "):
            first_text_index = index
            break
        area_match = AREA_RE.fullmatch(line)
        if area_match:
            current_area += 1
            areas.append(Area(
                current_area,
                area_match.group("name"),
                int(area_match.group("size"), 16),
                int(area_match.group("flags"), 16),
                int(area_match.group("addr"), 16),
                index,
            ))
            continue
        symbol_match = SYMBOL_RE.fullmatch(line)
        if symbol_match:
            name = symbol_match.group("name")
            if symbol_match.group("kind") == "Ref":
                references.add(name)
            else:
                definitions.append(Definition(
                    name, int(symbol_match.group("value"), 16), current_area
                ))

    header = HEADER_RE.fullmatch(lines[1])
    assert header is not None
    if int(header.group("areas"), 16) != len(areas):
        fail(f"{path}: H area count does not match A records")
    symbol_count = len(definitions) + len(references)
    if int(header.group("symbols"), 16) != symbol_count:
        fail(f"{path}: H symbol count does not match S records")

    const_areas = [area for area in areas if area.name == "CONST"]
    if len(const_areas) != 1:
        fail(f"{path}: expected exactly one CONST area")
    const_area = const_areas[0]
    data = bytearray(const_area.size)
    covered = bytearray(const_area.size)
    empty_area_markers: list[int] = []
    redundant_const_markers: list[int] = []

    index = first_text_index
    while index < len(lines):
        text_line = lines[index]
        if not text_line.startswith("T ") or index + 1 >= len(lines):
            fail(f"{path}:{index + 1}: expected T/R pair")
        relocation_line = lines[index + 1]
        if not relocation_line.startswith("R "):
            fail(f"{path}:{index + 2}: expected R after T")
        try:
            text_bytes = bytes.fromhex(text_line[2:])
            relocation_bytes = bytes.fromhex(relocation_line[2:])
        except ValueError as error:
            fail(f"{path}:{index + 1}: invalid hex record: {error}")
        if len(text_bytes) < 3 or len(relocation_bytes) != 4:
            fail(f"{path}:{index + 1}: unsupported T/R record width")
        if relocation_bytes[:3] != b"\x00\x00\x00":
            fail(f"{path}:{index + 2}: real relocation is not sliceable")
        area_index = relocation_bytes[3]
        if area_index >= len(areas):
            fail(f"{path}:{index + 2}: area index is out of range")
        address = int.from_bytes(text_bytes[:3], "big")
        payload = text_bytes[3:]
        if not payload:
            if address != 0:
                # SDCC can emit a zero-length CONST location record directly
                # before the real payload record at that same address.  It is
                # redundant only when the following complete T/R pair proves
                # the same CONST area/address and contains actual bytes.
                if area_index != const_area.index or index + 3 >= len(lines):
                    fail(f"{path}:{index + 1}: unsupported nonzero empty marker")
                try:
                    next_text = bytes.fromhex(lines[index + 2][2:])
                    next_relocation = bytes.fromhex(lines[index + 3][2:])
                except (ValueError, IndexError) as error:
                    fail(f"{path}:{index + 1}: malformed marker successor: {error}")
                if (not lines[index + 2].startswith("T ") or
                        not lines[index + 3].startswith("R ") or
                        len(next_text) <= 3 or len(next_relocation) != 4 or
                        next_relocation[:3] != b"\x00\x00\x00" or
                        next_relocation[3] != const_area.index or
                        int.from_bytes(next_text[:3], "big") != address):
                    fail(f"{path}:{index + 1}: nonzero empty marker is not a redundant CONST location record")
                redundant_const_markers.append(address)
                index += 2
                continue
            if area_index not in empty_area_markers:
                empty_area_markers.append(area_index)
        else:
            if area_index != const_area.index:
                fail(f"{path}:{index + 1}: payload outside CONST")
            end = address + len(payload)
            if end > const_area.size:
                fail(f"{path}:{index + 1}: payload exceeds CONST")
            if any(covered[address:end]):
                fail(f"{path}:{index + 1}: overlapping CONST payload")
            data[address:end] = payload
            covered[address:end] = b"\x01" * len(payload)
        index += 2

    if require_slice_shape:
        if references:
            fail(f"{path}: candidate has undefined/internal references")
        absolute_definitions = [
            item for item in definitions if item.name == ".__.ABS."
        ]
        if (len(absolute_definitions) != 1 or
                absolute_definitions[0].offset != 0 or
                absolute_definitions[0].area_index != -1):
            fail(f"{path}: expected one pre-area .__.ABS. definition at zero")
        if const_area.flags != 0x20 or const_area.addr != 0:
            fail(f"{path}: CONST flags/address are not the audited relocatable shape")
        unexpected_definitions = [
            item for item in definitions
            if item.name != ".__.ABS." and item.area_index != const_area.index
        ]
        if unexpected_definitions:
            fail(f"{path}: exported definition outside CONST")
        if const_area.size and not all(covered):
            fail(f"{path}: CONST byte coverage has gaps")

    return RelFile(
        path, raw, lines, first_text_index, areas, definitions, references,
        const_area, bytes(data), empty_area_markers, redundant_const_markers
    )


def source_from_depfile(candidate: Path) -> Path:
    depfile = candidate.with_suffix(".d")
    if not depfile.is_file():
        fail(f"missing dependency file {depfile}")
    logical = depfile.read_text(encoding="utf-8", errors="strict").replace("\\\n", " ")
    tokens = logical.split()
    if not tokens or not tokens[0].endswith(":"):
        fail(f"{depfile}: unsupported dependency syntax")
    sources = [Path(token) for token in tokens[1:] if token.endswith(".c")]
    if len(sources) != 1 or not sources[0].is_file():
        fail(f"{depfile}: expected exactly one existing C source dependency")
    return sources[0]


def references_from_rel(path: Path) -> set[str]:
    try:
        lines = path.read_bytes().decode("ascii").splitlines()
    except UnicodeDecodeError as error:
        fail(f"{path}: non-ASCII root REL: {error}")
    if not lines or lines[0] != "XH3":
        fail(f"{path}: root is not an XH3 ASxxxx object")
    references: set[str] = set()
    for line in lines[2:]:
        if line.startswith("T "):
            break
        match = SYMBOL_RE.fullmatch(line)
        if match and match.group("kind") == "Ref":
            references.add(match.group("name"))
    return references


def source_arrays(path: Path) -> dict[str, int]:
    # Generated/font sources can carry legacy comment bytes.  Declarations
    # being audited are ASCII; latin-1 gives a lossless one-byte decoding.
    text = path.read_bytes().decode("latin-1")
    arrays: dict[str, int] = {}
    for match in ARRAY_RE.finditer(text):
        name = match.group("name")
        if name in arrays:
            fail(f"{path}: duplicate audited array {name}")
        arrays[name] = int(match.group("size"))
    return arrays


def emit_sliced_rel(
    candidate: RelFile,
    selected: list[tuple[Definition, int]],
) -> tuple[bytes, list[dict[str, object]]]:
    packed = bytearray()
    selected_audit: list[dict[str, object]] = []
    rebased: dict[str, int] = {}
    for definition, size in selected:
        start = definition.offset
        span = candidate.const_data[start:start + size]
        rebased[definition.name] = len(packed)
        packed.extend(span)
        selected_audit.append({
            "symbol": definition.name,
            "original_offset": start,
            "rebased_offset": rebased[definition.name],
            "size": size,
            "sha256": digest_bytes(span),
        })

    header_lines: list[str] = []
    inserted_symbols = False
    for index, line in enumerate(candidate.lines[:candidate.first_text_index]):
        if index == 1:
            header_lines.append(
                f"H {len(candidate.areas):X} areas {1 + len(selected):X} global symbols"
            )
            continue
        symbol_match = SYMBOL_RE.fullmatch(line)
        if symbol_match:
            if symbol_match.group("name") == ".__.ABS.":
                header_lines.append(line)
            continue
        area_match = AREA_RE.fullmatch(line)
        if area_match and area_match.group("name") == "CONST":
            header_lines.append(
                f"A CONST size {len(packed):X} flags "
                f"{candidate.const_area.flags:X} addr {candidate.const_area.addr:X}"
            )
            for definition, _ in selected:
                header_lines.append(
                    f"S {definition.name} Def{rebased[definition.name]:06X}"
                )
            inserted_symbols = True
            continue
        header_lines.append(line)
    if not inserted_symbols:
        fail(f"{candidate.path}: failed to rebuild CONST header")

    body_lines: list[str] = []
    for area_index in candidate.empty_area_markers:
        body_lines.append("T 00 00 00")
        body_lines.append(f"R 00 00 00 {area_index:02X}")
    redundant_markers = set(candidate.redundant_const_markers)
    for definition, size in selected:
        rebased_address = rebased[definition.name]
        if definition.offset in redundant_markers:
            body_lines.append(
                "T " + " ".join(
                    f"{byte:02X}" for byte in rebased_address.to_bytes(3, "big")
                )
            )
            body_lines.append(f"R 00 00 00 {candidate.const_area.index:02X}")
        span = candidate.const_data[definition.offset:definition.offset + size]
        for offset in range(0, len(span), 13):
            address = rebased_address + offset
            record = address.to_bytes(3, "big") + span[offset:offset + 13]
            body_lines.append("T " + " ".join(f"{byte:02X}" for byte in record))
            body_lines.append(f"R 00 00 00 {candidate.const_area.index:02X}")
    return ("\n".join(header_lines + body_lines) + "\n").encode("ascii"), selected_audit


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--source", type=Path)
    parser.add_argument("--root-rel", action="append", default=[], type=Path)
    parser.add_argument("--root-list", action="append", default=[], type=Path)
    parser.add_argument("--expect-input-sha256")
    parser.add_argument("--expect-source-sha256")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--audit", required=True, type=Path)
    args = parser.parse_args()

    candidate = parse_rel(args.input.resolve(), require_slice_shape=True)
    source = args.source.resolve() if args.source else source_from_depfile(candidate.path)
    if (args.expect_input_sha256 and
            digest_bytes(candidate.raw) != args.expect_input_sha256.lower()):
        fail(f"{candidate.path}: input hash does not match pinned value")
    if (args.expect_source_sha256 and
            digest_path(source) != args.expect_source_sha256.lower()):
        fail(f"{source}: source hash does not match pinned value")
    arrays = source_arrays(source)
    definitions = sorted(
        (item for item in candidate.definitions if item.name != ".__.ABS."),
        key=lambda item: item.offset,
    )
    if not definitions or definitions[0].offset != 0:
        fail(f"{candidate.path}: CONST definitions do not start at zero")
    if len({item.name for item in definitions}) != len(definitions):
        fail(f"{candidate.path}: duplicate definition name")
    if len({item.offset for item in definitions}) != len(definitions):
        fail(f"{candidate.path}: aliases/shared offsets are not sliceable")

    spans: dict[str, int] = {}
    for index, definition in enumerate(definitions):
        end = (definitions[index + 1].offset
               if index + 1 < len(definitions) else candidate.const_area.size)
        if end <= definition.offset:
            fail(f"{candidate.path}: definition offsets are not increasing")
        source_name = definition.name.removeprefix("_")
        expected_size = arrays.get(source_name)
        if expected_size is None:
            fail(f"{source}: {definition.name} is not an audited const uint8_t array")
        span_size = end - definition.offset
        if expected_size != span_size:
            fail(
                f"{candidate.path}: {definition.name} adjacent-offset span "
                f"{span_size} != source array size {expected_size}"
            )
        spans[definition.name] = span_size
    definition_source_names = {item.name.removeprefix("_") for item in definitions}
    if not definition_source_names.issubset(arrays):
        rel_only = sorted(definition_source_names - set(arrays))
        fail(
            f"{source}: REL definitions are not all audited const arrays; "
            f"rel_only={rel_only[:5]} counts={len(arrays)}/{len(definitions)}"
        )

    root_paths = list(args.root_rel)
    for root_list in args.root_list:
        for line in root_list.read_text(encoding="utf-8").splitlines():
            if not line.strip().endswith(".rel"):
                continue
            listed_path = Path(line)
            if not listed_path.is_absolute():
                fail(f"{root_list}: root-list REL path must be absolute: {line}")
            root_paths.append(listed_path)
    root_refs: set[str] = set()
    root_hashes: list[dict[str, str]] = []
    for root_path in root_paths:
        resolved = root_path.resolve()
        if resolved == candidate.path:
            continue
        root_refs.update(references_from_rel(resolved))
        root_hashes.append({"path": str(resolved), "sha256": digest_path(resolved)})
    selected_defs = [item for item in definitions if item.name in root_refs]
    selected = [(item, spans[item.name]) for item in selected_defs]
    output, selected_audit = emit_sliced_rel(candidate, selected)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(output)
    reparsed = parse_rel(args.output, require_slice_shape=True)
    expected_data = b"".join(
        candidate.const_data[item.offset:item.offset + size]
        for item, size in selected
    )
    if reparsed.const_data != expected_data:
        fail(f"{args.output}: generated CONST payload verification failed")

    selected_names = {item.name for item in selected_defs}
    audit = {
        "schema_version": 1,
        "policy": "fail-closed-asxxxx-relocation-free-readonly-const-array-slicing",
        "input": {
            "path": str(candidate.path),
            "sha256": digest_bytes(candidate.raw),
            "const_size": candidate.const_area.size,
            "definition_count": len(definitions),
            "redundant_const_location_marker_count": len(candidate.redundant_const_markers),
            "redundant_const_location_markers": candidate.redundant_const_markers,
        },
        "source": {"path": str(source), "sha256": digest_path(source)},
        "roots": root_hashes,
        "root_policy": "conservative union of all external Refs in the actual direct-REL link closure",
        "selected": selected_audit,
        "discarded": [
            {"symbol": item.name, "offset": item.offset, "size": spans[item.name]}
            for item in definitions if item.name not in selected_names
        ],
        "output": {
            "path": str(args.output.resolve()),
            "sha256": digest_bytes(output),
            "const_size": len(expected_data),
            "payload_sha256": digest_bytes(expected_data),
        },
        "gates": {
            "format": "XH3",
            "single_const_area": True,
            "const_flags": f"0x{candidate.const_area.flags:X}",
            "payload_only_in_const": True,
            "real_relocations": 0,
            "aliases": 0,
            "undefined_symbols_in_candidate": 0,
            "source_arrays_match_adjacent_definition_spans": True,
        },
    }
    args.audit.parent.mkdir(parents=True, exist_ok=True)
    args.audit.write_text(json.dumps(audit, indent=2) + "\n", encoding="utf-8")
    print(
        f"READONLY_CONST_REL_SLICE=PASS input={candidate.const_area.size} "
        f"output={len(expected_data)} selected={len(selected)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
