#!/usr/bin/env python3
"""Plan fail-closed, source-proven function-level splits for a C translation unit."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


REL_AREA_RE = re.compile(r"^A (?P<name>\S+) size (?P<size>[0-9A-F]+) flags (?P<flags>[0-9A-F]+) addr (?P<addr>[0-9A-F]+)$")
REL_SYMBOL_RE = re.compile(r"^S (?P<name>\S+) (?P<kind>Def|Ref)(?P<value>[0-9A-F]+)$")


def fail(message: str) -> None:
    raise SystemExit(f"C function split audit failed: {message}")


def digest_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def digest_path(path: Path) -> str:
    return digest_bytes(path.read_bytes())


def source_offset(location: dict[str, Any], source: Path, size: int) -> int | None:
    if "spellingLoc" in location or "expansionLoc" in location:
        expansion = location.get("expansionLoc")
        if not isinstance(expansion, dict):
            return None
        if "includedFrom" in expansion:
            return None
        expansion_file = expansion.get("file")
        if expansion_file is not None and Path(expansion_file).resolve() != source:
            return None
        fail("macro-expanded top-level source ranges are not supported")
    if "includedFrom" in location:
        return None
    file_name = location.get("file")
    if file_name is not None and Path(file_name).resolve() != source:
        return None
    offset = location.get("offset")
    if not isinstance(offset, int) or offset < 0 or offset >= size:
        return None
    return offset


def range_offsets(node: dict[str, Any], source: Path, size: int) -> tuple[int, int] | None:
    source_range = node.get("range")
    if not isinstance(source_range, dict):
        return None
    begin_loc = source_range.get("begin")
    end_loc = source_range.get("end")
    if not isinstance(begin_loc, dict) or not isinstance(end_loc, dict):
        return None
    begin = source_offset(begin_loc, source, size)
    end_start = source_offset(end_loc, source, size)
    token_length = end_loc.get("tokLen")
    if begin is None or end_start is None or not isinstance(token_length, int):
        return None
    end = end_start + token_length
    if token_length <= 0 or end <= begin or end > size:
        return None
    return begin, end


def walk(node: dict[str, Any]) -> Iterable[dict[str, Any]]:
    yield node
    for child in node.get("inner", []):
        if isinstance(child, dict):
            yield from walk(child)


@dataclass(frozen=True)
class Function:
    name: str
    storage: str
    declaration_begin: int
    declaration_end: int
    body_begin: int
    body_end: int
    calls: tuple[str, ...]

    @property
    def is_static(self) -> bool:
        return self.storage == "static"


def parse_translation_unit(ast: dict[str, Any], source: Path, source_bytes: bytes) -> list[Function]:
    if ast.get("kind") != "TranslationUnitDecl":
        fail("Clang AST root is not TranslationUnitDecl")
    size = len(source_bytes)
    functions: list[Function] = []
    seen_names: set[str] = set()

    for declaration in ast.get("inner", []):
        if not isinstance(declaration, dict) or declaration.get("isImplicit"):
            continue
        kind = declaration.get("kind")
        if kind == "FunctionDecl" and not any(
            isinstance(child, dict) and child.get("kind") == "CompoundStmt"
            for child in declaration.get("inner", [])
        ):
            # A declaration cannot contribute code to any split member.  In
            # particular, attributes on a prototype are commonly spelled by a
            # macro, so resolving its top-level source range would reject an
            # otherwise source-owned translation unit for no useful reason.
            continue
        declaration_range = range_offsets(declaration, source, size)
        if declaration_range is None:
            continue

        if kind in {"FileScopeAsmDecl", "GCCAsmStmt", "MSAsmStmt"}:
            fail(f"file-scope assembly is not splittable: {kind}")
        if kind == "VarDecl":
            if declaration.get("storageClass") != "extern":
                fail(f"file-scope data definition is not splittable: {declaration.get('name', '<unnamed>')}")
            if "init" in declaration or any(
                isinstance(child, dict) for child in declaration.get("inner", [])
            ):
                fail(f"initialized extern VarDecl is not splittable: {declaration.get('name', '<unnamed>')}")
            continue
        if kind != "FunctionDecl":
            continue

        name = declaration.get("name")
        if not isinstance(name, str) or not name:
            fail("top-level function definition has no stable name")
        bodies = [
            child for child in declaration.get("inner", [])
            if isinstance(child, dict) and child.get("kind") == "CompoundStmt"
        ]
        if not bodies:
            continue
        if len(bodies) != 1:
            fail(f"function {name} does not have exactly one body")
        if name in seen_names:
            fail(f"multiple definitions of function {name}")
        seen_names.add(name)
        body_range = range_offsets(bodies[0], source, size)
        if body_range is None:
            fail(f"function {name} has an unknown or non-source body range")
        declaration_begin, declaration_end = declaration_range
        body_begin, body_end = body_range
        if not (declaration_begin <= body_begin < body_end <= declaration_end):
            fail(f"function {name} body is outside its declaration range")
        if source_bytes[body_begin:body_begin + 1] != b"{" or source_bytes[body_end - 1:body_end] != b"}":
            fail(f"function {name} body range is not brace-delimited")

        calls: set[str] = set()
        for node in walk(bodies[0]):
            if node.get("kind") != "DeclRefExpr":
                continue
            referenced = node.get("referencedDecl")
            if isinstance(referenced, dict) and referenced.get("kind") == "FunctionDecl":
                called = referenced.get("name")
                if isinstance(called, str) and called:
                    calls.add(called)
        storage = declaration.get("storageClass", "external")
        if storage not in {"static", "external"}:
            fail(f"function {name} has unsupported storage class {storage}")
        functions.append(Function(
            name=name,
            storage=storage,
            declaration_begin=declaration_begin,
            declaration_end=declaration_end,
            body_begin=body_begin,
            body_end=body_end,
            calls=tuple(sorted(calls)),
        ))

    if not functions:
        fail("translation unit has no source-owned function definitions")
    ordered = sorted(functions, key=lambda item: item.body_begin)
    previous_end = -1
    for function in ordered:
        if function.body_begin < previous_end:
            fail(f"overlapping function body ranges at {function.name}")
        previous_end = function.body_end
    return ordered


def sanitize_name(name: str) -> str:
    safe = "".join(character if character.isalnum() or character == "_" else "_" for character in name)
    if not safe or safe != name:
        fail(f"function name cannot be represented safely: {name!r}")
    return safe


def load_roots(arguments: argparse.Namespace) -> list[str]:
    roots = list(arguments.root)
    if arguments.root_list:
        root_list = Path(arguments.root_list).resolve()
        for line in root_list.read_text(encoding="utf-8").splitlines():
            item = line.strip()
            if not item or item.startswith("#"):
                continue
            roots.append(item[1:] if item.startswith("_") else item)
    unique = sorted(set(roots))
    if not unique:
        fail("at least one external root is required")
    return unique


def select_members(functions: list[Function], requested_roots: list[str]) -> list[tuple[str, set[str]]]:
    by_name = {function.name: function for function in functions}
    for root in requested_roots:
        function = by_name.get(root)
        if function is None:
            fail(f"requested root is not defined by the source: {root}")
        if function.is_static:
            fail(f"requested root is static: {root}")

    selected_roots = set(requested_roots)
    pending = list(requested_roots)
    while pending:
        current = by_name[pending.pop()]
        for called in current.calls:
            target = by_name.get(called)
            if target is not None and not target.is_static and called not in selected_roots:
                selected_roots.add(called)
                pending.append(called)

    selected: list[tuple[str, set[str]]] = []
    for root in sorted(selected_roots):
        keep = {root}
        helper_pending = list(by_name[root].calls)
        while helper_pending:
            called = helper_pending.pop()
            target = by_name.get(called)
            if target is None or not target.is_static or called in keep:
                continue
            keep.add(called)
            helper_pending.extend(target.calls)
        selected.append((root, keep))
    return selected


def render_member(source_bytes: bytes, functions: list[Function], keep: set[str]) -> bytes:
    chunks: list[bytes] = []
    cursor = 0
    for function in functions:
        chunks.append(source_bytes[cursor:function.body_begin])
        if function.name in keep:
            chunks.append(source_bytes[function.body_begin:function.body_end])
        else:
            chunks.append(b";")
        cursor = function.body_end
    chunks.append(source_bytes[cursor:])
    return b"".join(chunks)


def verify_rel(path: Path, root: str, external_names: set[str]) -> dict[str, Any]:
    raw = path.read_bytes()
    try:
        lines = raw.decode("ascii").splitlines()
    except UnicodeDecodeError as error:
        fail(f"{path}: split output REL is not ASCII: {error}")
    if len(lines) < 2 or lines[0] != "XH3" or not lines[1].startswith("H "):
        fail(f"{path}: split output is not an XH3 ASxxxx REL")
    definitions: list[str] = []
    references: list[str] = []
    areas: list[dict[str, Any]] = []
    for line in lines[2:]:
        area_match = REL_AREA_RE.fullmatch(line)
        if area_match:
            areas.append({
                "name": area_match.group("name"),
                "size": int(area_match.group("size"), 16),
                "flags": int(area_match.group("flags"), 16),
                "address": int(area_match.group("addr"), 16),
            })
            continue
        symbol_match = REL_SYMBOL_RE.fullmatch(line)
        if symbol_match:
            target = definitions if symbol_match.group("kind") == "Def" else references
            target.append(symbol_match.group("name"))
    if len(definitions) != len(set(definitions)) or len(references) != len(set(references)):
        fail(f"{path}: split output has duplicate public symbol records")
    expected = "_" + root
    if definitions.count(expected) != 1:
        fail(f"{path}: expected exactly one definition of {expected}")
    leaked = sorted(
        name for name in definitions
        if name.startswith("_") and name[1:] in external_names and name != expected
    )
    if leaked:
        fail(f"{path}: split output leaks other source entry definitions: {', '.join(leaked)}")
    if not areas:
        fail(f"{path}: split output has no ASxxxx areas")
    return {
        "rel": str(path.resolve()),
        "rel_sha256": digest_bytes(raw),
        "rel_size": len(raw),
        "definitions": sorted(definitions),
        "references": sorted(references),
        "areas": areas,
        "expected_external_definition": expected,
        "symbol_gate": "PASS",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--clang", required=True)
    parser.add_argument("--source", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--audit", required=True)
    parser.add_argument("--root", action="append", default=[])
    parser.add_argument("--root-list")
    parser.add_argument("--clang-arg", action="append", default=[])
    parser.add_argument("--expected-source-sha256")
    parser.add_argument("--verify-rel", action="append", default=[], metavar="ROOT=PATH")
    arguments = parser.parse_args()

    source = Path(arguments.source).resolve()
    clang = Path(arguments.clang).resolve()
    output_dir = Path(arguments.output_dir).resolve()
    audit_path = Path(arguments.audit).resolve()
    if not source.is_file() or not clang.is_file():
        fail("source and locked Clang must both be regular files")
    source_bytes = source.read_bytes()
    source_hash = digest_bytes(source_bytes)
    if arguments.expected_source_sha256 and source_hash != arguments.expected_source_sha256.lower():
        fail("source hash does not match the pinned value")
    if b"\x00" in source_bytes:
        fail("source contains a NUL byte")

    command = [
        str(clang), "-x", "c", "-fsyntax-only", "-fno-color-diagnostics",
        "-Xclang", "-ast-dump=json", *arguments.clang_arg, str(source),
    ]
    completed = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    if completed.returncode != 0:
        fail(f"Clang AST extraction failed ({completed.returncode}): {completed.stderr.decode('utf-8', 'replace')}")
    try:
        ast = json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        fail(f"Clang emitted malformed AST JSON: {error}")
    functions = parse_translation_unit(ast, source, source_bytes)
    requested_roots = load_roots(arguments)
    selected = select_members(functions, requested_roots)

    output_dir.mkdir(parents=True, exist_ok=True)
    members: list[dict[str, Any]] = []
    for index, (root, keep) in enumerate(selected):
        generated = render_member(source_bytes, functions, keep)
        if generated == source_bytes:
            fail(f"split member {root} unexpectedly equals the original source")
        member_path = output_dir / f"{index:04d}-{sanitize_name(root)}.c"
        member_path.write_bytes(generated)
        members.append({
            "root": root,
            "static_helper_closure": sorted(keep - {root}),
            "source": str(member_path),
            "source_sha256": digest_bytes(generated),
            "source_size": len(generated),
        })

    if arguments.verify_rel:
        rel_by_root: dict[str, Path] = {}
        for specification in arguments.verify_rel:
            root, separator, rel_name = specification.partition("=")
            if not separator or not root or not rel_name or root in rel_by_root:
                fail(f"malformed or duplicate --verify-rel value: {specification}")
            rel_by_root[root] = Path(rel_name).resolve()
        expected_roots = {member["root"] for member in members}
        if set(rel_by_root) != expected_roots:
            fail("verified REL roots do not exactly match the selected members")
        external_names = {item.name for item in functions if not item.is_static}
        for member in members:
            root = member["root"]
            member["compiled_rel"] = verify_rel(rel_by_root[root], root, external_names)

    audit = {
        "schema_version": 1,
        "outcome": "PASS",
        "policy": "fail-closed-clang-ast-source-range-c-function-splitting",
        "source": str(source),
        "source_sha256": source_hash,
        "source_size": len(source_bytes),
        "clang": str(clang),
        "clang_sha256": digest_path(clang),
        "clang_arguments": arguments.clang_arg,
        "clang_ast_sha256": digest_bytes(completed.stdout),
        "clang_stderr_sha256": digest_bytes(completed.stderr),
        "function_count": len(functions),
        "external_function_count": sum(not item.is_static for item in functions),
        "static_function_count": sum(item.is_static for item in functions),
        "requested_roots": requested_roots,
        "selected_root_count": len(members),
        "discarded_external_count": sum(not item.is_static for item in functions) - len(members),
        "members": members,
        "functions": [
            {
                "name": item.name,
                "storage": item.storage,
                "declaration_range": [item.declaration_begin, item.declaration_end],
                "body_range": [item.body_begin, item.body_end],
                "calls": list(item.calls),
            }
            for item in functions
        ],
        "gates": {
            "clang_ast_json": "PASS",
            "source_hash": "PASS",
            "no_file_scope_data_definitions": "PASS",
            "no_file_scope_assembly": "PASS",
            "all_function_bodies_have_exact_source_ranges": "PASS",
            "all_requested_roots_are_external_definitions": "PASS",
            "compiled_rel_symbols": "PASS" if arguments.verify_rel else "NOT_RUN",
        },
    }
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    audit_path.write_text(json.dumps(audit, indent=2) + "\n", encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
