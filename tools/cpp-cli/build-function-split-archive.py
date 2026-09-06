#!/usr/bin/env python3
"""Build an archive closure with fail-closed splits for oversized C function TUs."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


AREA_RE = re.compile(r"^A (\S+) size ([0-9A-F]+) flags ([0-9A-F]+) addr ([0-9A-F]+)$")
SYMBOL_RE = re.compile(r"^S (\S+) (Def|Ref)[0-9A-F]+$")


def fail(message: str) -> None:
    raise SystemExit(f"C function archive audit failed: {message}")


def digest_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def digest_path(path: Path) -> str:
    return digest_bytes(path.read_bytes())


def archive_member_alias(source: Path) -> str:
    """Return a deterministic member name that SDLD can display in full."""
    source_sha256 = digest_path(source)
    identity = source.name.encode("utf-8") + b"\0" + bytes.fromhex(source_sha256)
    # Locked SDLD prints at most 32 archive-member characters.  Keep every
    # generated name below that boundary so two long source basenames can
    # never become indistinguishable in the final link map.
    return "fs-" + digest_bytes(identity)[:24] + ".rel"


def run(command: list[str], *, cwd: Path | None = None) -> bytes:
    completed = subprocess.run(
        command, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False
    )
    if completed.returncode:
        fail(
            f"command failed ({completed.returncode}): {command!r}: "
            + completed.stderr.decode("utf-8", "replace")
        )
    return completed.stdout


def parse_rel_bytes(payload: bytes, label: str) -> dict[str, Any]:
    try:
        lines = payload.decode("ascii").splitlines()
    except UnicodeDecodeError as error:
        fail(f"{label}: non-ASCII REL: {error}")
    if len(lines) < 2 or lines[0] != "XH3" or not lines[1].startswith("H "):
        fail(f"{label}: expected XH3 ASxxxx REL")
    definitions: set[str] = set()
    references: set[str] = set()
    areas: dict[str, int] = {}
    for line in lines[2:]:
        area = AREA_RE.fullmatch(line)
        if area:
            name = area.group(1)
            if name in areas:
                fail(f"{label}: duplicate area {name}")
            areas[name] = int(area.group(2), 16)
            continue
        symbol = SYMBOL_RE.fullmatch(line)
        if symbol:
            target = definitions if symbol.group(2) == "Def" else references
            if symbol.group(1) in target:
                fail(f"{label}: duplicate {symbol.group(2)} symbol {symbol.group(1)}")
            target.add(symbol.group(1))
    if not definitions and not references:
        fail(f"{label}: REL has no public symbols")
    return {"definitions": definitions, "references": references, "areas": areas}


def parse_rel(path: Path) -> dict[str, Any]:
    return parse_rel_bytes(path.read_bytes(), str(path))


@dataclass
class Member:
    meta_path: Path
    actual_rel: Path
    metadata: dict[str, Any]
    original: dict[str, Any]
    actual: dict[str, Any]
    candidate: bool
    selected: bool = False
    requested_roots: set[str] = field(default_factory=set)
    compiled: list[Path] = field(default_factory=list)
    split_audit: Path | None = None


def verify_metadata(meta_path: Path, actual_rel: Path, code_limit: int, xram_limit: int) -> Member:
    metadata = json.loads(meta_path.read_text(encoding="utf-8"))
    if metadata.get("schema_version") != 1:
        fail(f"{meta_path}: unsupported metadata schema")
    original_rel = Path(metadata["original_rel"]).resolve()
    source = Path(metadata["source"]).resolve()
    clang = Path(metadata["clang"]).resolve()
    sdcc = Path(metadata["sdcc"]).resolve()
    for path in (original_rel, source, clang, sdcc, actual_rel):
        if not path.is_file():
            fail(f"missing function archive input: {path}")
    for path, key in (
        (original_rel, "original_rel_sha256"),
        (source, "source_sha256"),
        (clang, "clang_sha256"),
        (sdcc, "sdcc_sha256"),
    ):
        if digest_path(path) != metadata[key]:
            fail(f"{meta_path}: pinned hash mismatch for {path}")
    original = parse_rel(original_rel)
    actual = parse_rel(actual_rel)
    candidate = (
        original["areas"].get("CSEG", 0) > code_limit
        or original["areas"].get("XSEG", 0) + original["areas"].get("XISEG", 0) > xram_limit
    )
    return Member(meta_path, actual_rel, metadata, original, actual, candidate)


def archive_symbols(sdar: Path, archive: Path) -> tuple[set[str], set[str]]:
    listing = run([str(sdar), "-t", str(archive)]).decode("utf-8").splitlines()
    if len(listing) != len(set(listing)):
        fail(f"{archive}: duplicate archive member names")
    definitions: set[str] = set()
    references: set[str] = set()
    for name in listing:
        parsed = parse_rel_bytes(run([str(sdar), "-p", str(archive), name]), f"{archive}({name})")
        definitions.update(parsed["definitions"])
        references.update(parsed["references"])
    return definitions, references


def compile_candidate(member: Member, roots: set[str], work: Path, splitter: Path) -> None:
    metadata = member.metadata
    source = Path(metadata["source"]).resolve()
    clang = Path(metadata["clang"]).resolve()
    sdcc = Path(metadata["sdcc"]).resolve()
    stem = digest_path(member.meta_path)[:16]
    candidate_work = work / f"candidate-{stem}"
    source_dir = candidate_work / "sources"
    rel_dir = candidate_work / "rels"
    audit = candidate_work / "audit.json"
    source_dir.mkdir(parents=True, exist_ok=True)
    rel_dir.mkdir(parents=True, exist_ok=True)
    command = [
        sys.executable, str(splitter), "--clang", str(clang), "--source", str(source),
        "--output-dir", str(source_dir), "--audit", str(audit),
        "--expected-source-sha256", metadata["source_sha256"],
    ]
    for root in sorted(roots):
        command.extend(["--root", root[1:] if root.startswith("_") else root])
    for argument in metadata["clang_arguments"]:
        command.append("--clang-arg=" + argument)
    run(command)
    plan = json.loads(audit.read_text(encoding="utf-8"))
    compiled: list[tuple[str, Path]] = []
    for item in plan["members"]:
        root = item["root"]
        generated = Path(item["source"])
        rel = rel_dir / f"{root}.rel"
        compile_command = [
            str(sdcc), *metadata["sdcc_arguments"],
            "-I" + metadata["relocated_source_parent_include"],
            str(generated), "-o", str(rel),
        ]
        # SDCC emits -MMD basename files in its cwd and ignores GCC -MF.
        # Keep every generated dependency beside this candidate's evidence.
        run(compile_command, cwd=candidate_work)
        compiled.append((root, rel))
    verify_command = list(command)
    for root, rel in compiled:
        verify_command.append(f"--verify-rel={root}={rel}")
    run(verify_command)
    member.requested_roots = set(roots)
    member.compiled = [rel for _, rel in compiled]
    member.split_audit = audit


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--member", action="append", nargs=2, required=True, metavar=("META", "ACTUAL_REL"))
    parser.add_argument("--root-rel", action="append", default=[])
    parser.add_argument("--root-archive", action="append", default=[])
    parser.add_argument("--code-limit", type=int, required=True)
    parser.add_argument("--xram-limit", type=int, required=True)
    parser.add_argument("--splitter", type=Path, required=True)
    parser.add_argument("--sdar", type=Path, required=True)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--output-archive", type=Path, required=True)
    parser.add_argument("--audit", type=Path, required=True)
    arguments = parser.parse_args()
    if arguments.code_limit <= 0 or arguments.xram_limit <= 0:
        fail("code and XRAM limits must be positive")
    splitter = arguments.splitter.resolve()
    sdar = arguments.sdar.resolve()
    work = arguments.work_dir.resolve()
    output_archive = arguments.output_archive.resolve()
    for tool in (splitter, sdar):
        if not tool.is_file():
            fail(f"missing function archive tool: {tool}")
    work.mkdir(parents=True, exist_ok=True)

    members = [
        verify_metadata(Path(meta).resolve(), Path(actual).resolve(), arguments.code_limit, arguments.xram_limit)
        for meta, actual in arguments.member
    ]
    if not any(member.candidate for member in members):
        fail("function archive group has no oversized CSEG/XSEG candidate")
    original_rel_paths = [Path(member.metadata["original_rel"]).resolve() for member in members]
    if len(original_rel_paths) != len(set(original_rel_paths)):
        fail("duplicate original REL in function archive group")

    base_definitions: set[str] = set()
    base_references: set[str] = set()
    root_inputs: list[dict[str, Any]] = []
    for value in arguments.root_rel:
        path = Path(value).resolve()
        parsed = parse_rel(path)
        base_definitions.update(parsed["definitions"])
        base_references.update(parsed["references"])
        root_inputs.append({"kind": "direct-rel", "path": str(path), "sha256": digest_path(path)})
    for value in arguments.root_archive:
        path = Path(value).resolve()
        definitions, references = archive_symbols(sdar, path)
        base_definitions.update(definitions)
        base_references.update(references)
        root_inputs.append({"kind": "conservative-all-archive-members", "path": str(path), "sha256": digest_path(path)})

    selected_definitions = set(base_definitions)
    selected_references = set(base_references)
    iterations: list[dict[str, Any]] = []
    maximum_iterations = len(members) * 3 + 3
    for iteration in range(maximum_iterations):
        unresolved = selected_references - selected_definitions
        changes: list[dict[str, Any]] = []
        for member in members:
            hits = member.original["definitions"] & unresolved
            if not hits:
                continue
            if member.candidate:
                requested = member.requested_roots | hits
                if requested != member.requested_roots:
                    compile_candidate(member, requested, work, splitter)
                    compiled_defs: set[str] = set()
                    compiled_refs: set[str] = set()
                    for rel in member.compiled:
                        parsed = parse_rel(rel)
                        compiled_defs.update(parsed["definitions"])
                        compiled_refs.update(parsed["references"])
                    selected_definitions.update(compiled_defs)
                    selected_references.update(compiled_refs)
                    member.selected = True
                    changes.append({"kind": "split-candidate", "metadata": str(member.meta_path), "roots": sorted(requested)})
            elif not member.selected:
                member.selected = True
                selected_definitions.update(member.actual["definitions"])
                selected_references.update(member.actual["references"])
                changes.append({"kind": "ordinary-member", "rel": str(member.actual_rel), "roots": sorted(hits)})
        iterations.append({"iteration": iteration, "changes": changes})
        if not changes:
            break
    else:
        fail("archive closure did not converge")

    unresolved = selected_references - selected_definitions
    stranded = sorted(
        symbol for member in members for symbol in member.original["definitions"]
        if symbol in unresolved
    )
    if stranded:
        fail("archive closure left group definitions unresolved: " + ", ".join(stranded))

    archive_members: list[Path] = []
    for member in members:
        if not member.selected:
            continue
        archive_members.extend(member.compiled if member.candidate else [member.actual_rel])
    if not archive_members:
        fail("archive closure selected no members")
    source_names = [path.name for path in archive_members]
    if len(source_names) != len(set(source_names)):
        fail("selected archive member basenames are not unique")
    alias_dir = work / "archive-members"
    alias_dir.mkdir(parents=True, exist_ok=True)
    archive_member_sources = []
    aliased_members = []
    for source in archive_members:
        source = source.resolve()
        source_sha256 = digest_path(source)
        name = archive_member_alias(source)
        alias = alias_dir / name
        alias.write_bytes(source.read_bytes())
        if digest_path(alias) != source_sha256:
            fail(f"archive alias differs from source REL: {source}")
        archive_member_sources.append({
            "name": name,
            "source_rel": str(source),
            "source_rel_sha256": source_sha256,
        })
        aliased_members.append(alias)
    names = [path.name for path in aliased_members]
    if len(names) != len(set(names)):
        fail("deterministic archive member aliases are not unique")
    if any(len(name) > 32 for name in names):
        fail("deterministic archive member alias exceeds the SDLD display limit")
    if output_archive.exists():
        output_archive.unlink()
    run([str(sdar), "-rc", str(output_archive), *map(str, aliased_members)])
    listing = run([str(sdar), "-t", str(output_archive)]).decode("utf-8").splitlines()
    if listing != names:
        fail("SDAR output member order/identity differs from the selected closure")
    for binding in archive_member_sources:
        archived = run([str(sdar), "-p", str(output_archive), binding["name"]])
        if digest_bytes(archived) != binding["source_rel_sha256"]:
            fail(f"SDAR member differs from its source REL: {binding['name']}")

    member_evidence = []
    for member in members:
        item: dict[str, Any] = {
            "metadata": str(member.meta_path),
            "metadata_sha256": digest_path(member.meta_path),
            "source": member.metadata["source"],
            "source_sha256": member.metadata["source_sha256"],
            "original_rel": member.metadata["original_rel"],
            "original_rel_sha256": member.metadata["original_rel_sha256"],
            "actual_rel": str(member.actual_rel),
            "actual_rel_sha256": digest_path(member.actual_rel),
            "candidate": member.candidate,
            "selected": member.selected,
            "original_areas": member.original["areas"],
            "requested_roots": sorted(member.requested_roots),
        }
        if member.split_audit:
            item["split_audit"] = str(member.split_audit)
            item["split_audit_sha256"] = digest_path(member.split_audit)
            item["split"] = json.loads(member.split_audit.read_text(encoding="utf-8"))
        member_evidence.append(item)
    audit = {
        "schema_version": 1,
        "outcome": "PASS",
        "policy": "fail-closed-archive-closure-with-clang-ast-function-splits",
        "limits": {"code_bytes": arguments.code_limit, "xram_bytes": arguments.xram_limit},
        "tools": {
            "orchestrator": {"path": str(Path(__file__).resolve()), "sha256": digest_path(Path(__file__).resolve())},
            "splitter": {"path": str(splitter), "sha256": digest_path(splitter)},
            "sdar": {"path": str(sdar), "sha256": digest_path(sdar)},
        },
        "root_collection": "direct REL closure plus conservative union of every supplied archive member",
        "root_inputs": root_inputs,
        "iterations": iterations,
        "members": member_evidence,
        "selected_member_count": len(archive_members),
        "discarded_input_member_count": sum(not member.selected for member in members),
        "selected_split_candidate_count": sum(member.candidate and member.selected for member in members),
        "discarded_split_candidate_count": sum(member.candidate and not member.selected for member in members),
        "output_archive": str(output_archive),
        "output_archive_sha256": digest_path(output_archive),
        "output_archive_size": output_archive.stat().st_size,
        "output_archive_member_naming": "deterministic-source-and-content-sha256-v1",
        "output_archive_members": names,
        "output_archive_member_sources": archive_member_sources,
        "original_oversized_rel_excluded": all(
            Path(member.metadata["original_rel"]).name not in names
            for member in members if member.candidate
        ),
    }
    arguments.audit.resolve().write_text(json.dumps(audit, indent=2) + "\n", encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
