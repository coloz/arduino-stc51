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

    if any(area.name.startswith("CONST_D_") and area.size for area in areas):
        fail(
            f"{path}: per-object CONST_D_ sections require a section-aware readonly "
            "slicer; refusing to merge or discard unaudited areas"
        )
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


def parse_sectioned_arrays(path: Path, arrays: dict[str, int]):
    """Validate pure const arrays with SDCC --data-sections, without merging.

    ASxxxx area indices are 16-bit, even when a module contains >255 arrays.
    No symbol/area relocation fixups are accepted; retained T/R pairs and area
    indices can consequently stay byte-for-byte identical.
    """
    raw = path.read_bytes()
    try:
        lines = raw.decode('ascii').splitlines()
    except UnicodeDecodeError:
        fail(f'{path}: non-ASCII sectioned REL')
    if len(lines) < 4 or lines[0] != 'XH3' or not HEADER_RE.fullmatch(lines[1]):
        fail(f'{path}: unsupported sectioned REL header')
    areas, definitions, symbols = [], {}, set()
    current = -1
    first = next((i for i, line in enumerate(lines) if line.startswith('T ')), len(lines))
    absolute = 0
    for line in lines[2:first]:
        area = AREA_RE.fullmatch(line)
        if area:
            current += 1
            areas.append(dict(name=area['name'], size=int(area['size'], 16),
                              flags=int(area['flags'], 16), addr=int(area['addr'], 16)))
            continue
        symbol = SYMBOL_RE.fullmatch(line)
        if not symbol:
            if not line.startswith(('M ', 'O ')):
                fail(f'{path}: unknown sectioned header record')
            continue
        if symbol['kind'] != 'Def' or symbol['name'] in symbols:
            fail(f'{path}: references or duplicate definitions are not sliceable')
        symbols.add(symbol['name'])
        if symbol['name'] == '.__.ABS.' and current == -1 and int(symbol['value'],16) == 0:
            absolute += 1
            continue
        if current < 0 or current in definitions or int(symbol['value'],16) != 0:
            fail(f'{path}: section aliases or nonzero definition offset')
        definitions[current] = symbol['name']
    header = HEADER_RE.fullmatch(lines[1])
    if absolute != 1 or int(header['areas'],16) != len(areas) or int(header['symbols'],16) != len(symbols):
        fail(f'{path}: sectioned header counts mismatch')
    data, coverage = {}, {}
    for index, area in enumerate(areas):
        if area['name'].startswith('CONST_D_'):
            if area['flags'] != 0x20 or area['addr'] != 0:
                fail(f'{path}: unsupported CONST_D flags/address')
            name = definitions.get(index)
            if area['size']:
                if name is None or arrays.get(name.removeprefix('_')) != area['size']:
                    fail(f'{path}: CONST_D section does not match one source-sized array')
            elif name is not None:
                fail(f'{path}: exported zero-sized section')
            data[index] = bytearray(area['size']); coverage[index] = bytearray(area['size'])
        elif index in definitions or (area['size'] and area != dict(name='REG_BANK_0',size=8,flags=4,addr=0)):
            fail(f'{path}: non-array data/code in sectioned candidate')
    pairs = []
    if (len(lines)-first) % 2:
        fail(f'{path}: incomplete T/R pair')
    for i in range(first, len(lines), 2):
        if not lines[i].startswith('T ') or not lines[i+1].startswith('R '):
            fail(f'{path}: expected sectioned T/R pair')
        try:
            t = bytes.fromhex(lines[i][2:]); r = bytes.fromhex(lines[i+1][2:])
        except ValueError:
            fail(f'{path}: invalid sectioned T/R hex')
        if len(t) < 3 or len(r) != 4 or r[:2] != b'\0\0':
            fail(f'{path}: real relocation or unsupported T/R width')
        index = int.from_bytes(r[2:], 'big'); offset = int.from_bytes(t[:3], 'big'); payload = t[3:]
        if index >= len(areas) or offset + len(payload) > areas[index]['size']:
            fail(f'{path}: sectioned T/R range error')
        if payload:
            if index not in data or any(coverage[index][offset:offset+len(payload)]):
                fail(f'{path}: non-CONST_D or overlapping payload')
            data[index][offset:offset+len(payload)] = payload
            coverage[index][offset:offset+len(payload)] = b'\1' * len(payload)
        elif offset:
            if i+3 >= len(lines) or not lines[i+2].startswith('T ') or not lines[i+3].startswith('R '):
                fail(f'{path}: unsupported section location marker')
            nt = bytes.fromhex(lines[i+2][2:]); nr = bytes.fromhex(lines[i+3][2:])
            if len(nt) <= 3 or nt[:3] != t or nr != r:
                fail(f'{path}: section location marker lacks matching payload')
        pairs.append((index, lines[i:i+2]))
    if any(not all(value) for value in coverage.values()):
        fail(f'{path}: sectioned CONST_D byte coverage has gaps')
    return raw, lines, first, areas, definitions, data, pairs


def slice_sectioned_arrays(args):
    path = args.input.resolve()
    source = args.source.resolve() if args.source else source_from_depfile(path)
    arrays = source_arrays(source)
    raw, lines, first, areas, definitions, data, pairs = parse_sectioned_arrays(path, arrays)
    if args.expect_input_sha256 and digest_bytes(raw) != args.expect_input_sha256.lower():
        fail(f'{path}: input hash does not match pinned value')
    if args.expect_source_sha256 and digest_path(source) != args.expect_source_sha256.lower():
        fail(f'{source}: source hash does not match pinned value')
    roots = list(args.root_rel)
    for root_list in args.root_list:
        for value in root_list.read_text().splitlines():
            if not value.strip().endswith('.rel'): continue
            if not Path(value).is_absolute(): fail('root-list REL path must be absolute')
            roots.append(Path(value))
    refs, root_hashes = set(), []
    for root in roots:
        root = root.resolve()
        if root == path: continue
        refs.update(references_from_rel(root))
        root_hashes.append(dict(path=str(root),sha256=digest_path(root)))
    keep = {index for index, name in definitions.items() if name in refs}
    selected = [dict(symbol=definitions[i],area=areas[i]['name'],original_offset=0,
                     rebased_offset=0,size=len(data[i]),sha256=digest_bytes(data[i])) for i in sorted(keep)]
    output = []; current = -1
    for i, line in enumerate(lines[:first]):
        if i == 1:
            output.append(f'H {len(areas):X} areas {len(keep)+1:X} global symbols'); continue
        area = AREA_RE.fullmatch(line)
        if area:
            current += 1
            if current in data and current not in keep:
                line = f'A {area["name"]} size 0 flags {area["flags"]} addr {area["addr"]}'
        symbol = SYMBOL_RE.fullmatch(line)
        if symbol and symbol['name'] != '.__.ABS.' and current not in keep: continue
        output.append(line)
    for index, pair in pairs:
        if index in keep or index not in data: output.extend(pair)
    emitted = ('\n'.join(output)+'\n').encode('ascii')
    args.output.parent.mkdir(parents=True,exist_ok=True); args.output.write_bytes(emitted)
    _, _, _, after_areas, after_defs, after_data, _ = parse_sectioned_arrays(args.output, arrays)
    if after_defs != {i:definitions[i] for i in keep} or len(after_areas) != len(areas):
        fail('sectioned output symbol/area identity mismatch')
    if any(after_data[i] != data[i] for i in keep) or any(after_data[i] for i in data if i not in keep):
        fail('sectioned output payload mismatch')
    packed = b''.join(data[i] for i in sorted(keep))
    audit = dict(schema_version=1,policy='fail-closed-asxxxx-relocation-free-readonly-const-array-slicing',
                 input=dict(path=str(path),sha256=digest_bytes(raw),const_size=sum(map(len,data.values())),definition_count=len(definitions)),
                 source=dict(path=str(source),sha256=digest_path(source)),roots=root_hashes,
                 root_policy='conservative union of all external Refs in the actual direct-REL link closure',
                 selected=selected,
                 discarded=[dict(symbol=name,area=areas[i]['name'],offset=0,size=len(data[i])) for i,name in definitions.items() if i not in keep],
                 output=dict(path=str(args.output.resolve()),sha256=digest_bytes(emitted),const_size=len(packed),payload_sha256=digest_bytes(packed)),
                 gates=dict(format='XH3',single_const_area=False,section_indices_preserved=True,
                            const_flags='0x20',payload_only_in_const=True,real_relocations=0,aliases=0,
                            undefined_symbols_in_candidate=0,source_arrays_match_section_sizes=True))
    args.audit.parent.mkdir(parents=True,exist_ok=True)
    args.audit.write_text(json.dumps(audit,indent=2)+'\n')
    print(f'READONLY_CONST_REL_SLICE=PASS input={audit["input"]["const_size"]} output={len(packed)} selected={len(keep)} sections=preserved')
    return 0


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

    if re.search(rb'^A CONST_D_\S+ size [1-9A-F][0-9A-F]* ', args.input.read_bytes(), re.M):
        return slice_sectioned_arrays(args)
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
