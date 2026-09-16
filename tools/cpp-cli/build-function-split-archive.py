#!/usr/bin/env python3
"""Audit C function closures, preserving direct objects or archive extraction."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
import importlib.util

_archive_spec = importlib.util.spec_from_file_location('archive_members', Path(__file__).with_name('archive_members.py'))
_archive_module = importlib.util.module_from_spec(_archive_spec)
_archive_spec.loader.exec_module(_archive_module)
read_member = _archive_module.read_member
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


def default_function_code_bytes(areas: dict[str, int]) -> int:
    # --function-sections leaves CSEG empty and places each default function
    # in CSEG_F_*. Keep the original whole-TU budget trigger in either form;
    # source/symbol audits still decide whether splitting is permitted.
    return sum(size for name, size in areas.items()
               if name == "CSEG" or name.startswith("CSEG_F_"))


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
    trim_classification: str | None = None
    external_functions: set[str] = field(default_factory=set)


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
        default_function_code_bytes(original["areas"]) > code_limit
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
        parsed = parse_rel_bytes(read_member(sdar, archive, name), f"{archive}({name})")
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
        "--expected-source-sha256", metadata["source_sha256"], "--merge-roots",
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


def can_trim_member(member: Member, splitter: Path) -> bool:
    """Optional pure-function TU trimming inside an already oversized library.

    Keep ordinary objects when their source shape cannot be proven. Metadata
    hashes have already been verified; generated function closures are compiled
    and symbol-audited again before use. Single-TU emission preserves private
    callback identity and static local state shared by multiple public entries.
    """
    if default_function_code_bytes(member.original['areas']) == 0:
        member.trim_classification = 'no-function-code'; return False
    if any(size for name,size in member.original['areas'].items()
           if name in ('HOME','GSINIT','GSFINAL') or name.startswith('GSINIT')):
        member.trim_classification = 'startup-code-kept'; return False
    spec=importlib.util.spec_from_file_location('stc_function_splitter',splitter)
    module=importlib.util.module_from_spec(spec); sys.modules[spec.name]=module; spec.loader.exec_module(module)
    meta=member.metadata; source=Path(meta['source'])
    result=subprocess.run([meta['clang'],'-x','c','-fsyntax-only','-fno-color-diagnostics',
                           '-Xclang','-ast-dump=json',*meta['clang_arguments'],str(source)],capture_output=True)
    if result.returncode:
        member.trim_classification = 'AST-unavailable-original-kept'; return False
    try:
        ast = json.loads(result.stdout)
        # Attributes can retain entries independently of ordinary call edges
        # (interrupt vectors, constructors, used/section declarations, aliases).
        # Their semantics are outside this optional optimization's proof.
        functions=module.parse_translation_unit(ast,source,source.read_bytes(),
                                                 shared_file_state=True)
        names = {function.name for function in functions}
        if any(node.get('kind', '').endswith('Attr')
               for declaration in ast.get('inner', [])
               if declaration.get('kind') == 'FunctionDecl' and declaration.get('name') in names
               for node in module.walk(declaration)):
            member.trim_classification = 'attributes-original-kept'; return False
    except (SystemExit, ValueError) as error:
        member.trim_classification = 'original-kept: '+str(error); return False
    member.external_functions = {'_' + f.name for f in functions if not f.is_static}
    member.trim_classification = 'functions-shared-single-TU'
    return len(member.external_functions) > 1


def trim_direct_members(members: list[Member], arguments, work: Path,
                        splitter: Path, sdar: Path) -> None:
    """Replace functions inside direct objects; never discard a whole object.

    Use the original references of every input, including every archive member.
    This intentionally overestimates roots so independent trims cannot remove
    an entry still needed by another object. Keep unsupported/unreferenced TUs
    whole, and link every resulting REL directly so startup/data is retained.
    """
    references: set[str] = set()
    inputs: dict[Path, str] = {}
    root_inputs = []
    for member in members:
        references.update(member.actual['references'])
        for path in (member.meta_path, member.actual_rel,
                     Path(member.metadata['source']), Path(member.metadata['original_rel'])):
            inputs[path] = digest_path(path)
    for value in arguments.root_rel:
        path = Path(value).resolve()
        references.update(parse_rel(path)['references'])
        inputs[path] = digest_path(path)
        root_inputs.append({'kind': 'direct-rel', 'path': str(path), 'sha256': inputs[path]})
    for value in arguments.root_archive:
        path = Path(value).resolve()
        references.update(archive_symbols(sdar, path)[1])
        inputs[path] = digest_path(path)
        root_inputs.append({'kind': 'conservative-all-archive-members', 'path': str(path), 'sha256': inputs[path]})
    bindings = []
    trimmed_count = 0
    for member in members:
        original = member.actual_rel
        output = original
        evidence = {'input_rel': str(original), 'input_rel_sha256': inputs[original],
                    'metadata': str(member.meta_path), 'metadata_sha256': inputs[member.meta_path],
                    'original_areas': member.actual['areas']}
        if digest_path(original) != member.metadata['original_rel_sha256']:
            member.trim_classification = 'previously-transformed-original-kept'
        elif can_trim_member(member, splitter):
            roots = references & member.external_functions
            if roots:
                compile_candidate(member, roots, work, splitter)
                if len(member.compiled) != 1:
                    fail('direct object trimming must preserve a single translation unit')
                generated = member.compiled[0]
                parsed = parse_rel(generated)
                required = member.original['definitions'] & references
                non_functions = member.original['definitions'] - member.external_functions
                if not (required | non_functions) <= parsed['definitions']:
                    fail('direct object trimming removed required functions or non-function definitions')
                if parsed['definitions'] - member.original['definitions']:
                    fail('direct object trimming introduced unexpected public definitions')
                removed = member.original['definitions'] - parsed['definitions']
                # Native-only header branches can call helpers absent from the
                # Clang AST. Removing such a helper turns a local definition
                # into an external reference. Keep the original object unless
                # the native compiler confirms no new reference was created.
                new_references = parsed['references'] - member.original['references']
                if new_references:
                    member.trim_classification = 'new-native-references-original-kept'
                if (not new_references and removed and
                        default_function_code_bytes(parsed['areas']) < default_function_code_bytes(member.original['areas'])):
                    output = generated
                    trimmed_count += 1
                evidence.update(requested_roots=sorted(roots), removed_definitions=sorted(removed),
                                new_native_references=sorted(new_references),
                                split_audit=str(member.split_audit), split_audit_sha256=digest_path(member.split_audit),
                                split=json.loads(member.split_audit.read_text()), generated_areas=parsed['areas'])
            else:
                member.trim_classification = 'no-referenced-function-original-kept'
        evidence.update(classification=member.trim_classification, output_rel=str(output),
                        output_rel_sha256=digest_path(output), transformed=output != original)
        bindings.append(evidence)
    for path, expected in inputs.items():
        if digest_path(path) != expected:
            fail(f'direct function trim input changed: {path}')
    replacements = arguments.output_rel_list.resolve()
    replacements.write_text(''.join(item['input_rel'] + '\n' + item['output_rel'] + '\n' for item in bindings),
                            encoding='utf-8', newline='\n')
    audit = {'schema_version': 1, 'outcome': 'PASS', 'linkage': 'direct-rels',
             'policy': 'conservative-original-reference-closure-retaining-every-direct-object',
             'tools': {'orchestrator': {'path': str(Path(__file__).resolve()), 'sha256': digest_path(Path(__file__))},
                       'splitter': {'path': str(splitter), 'sha256': digest_path(splitter)},
                       'sdar': {'path': str(sdar), 'sha256': digest_path(sdar)}},
             'root_inputs': root_inputs, 'bindings': bindings,
             'selected_member_count': 0, 'selected_direct_object_count': len(bindings),
             'discarded_input_member_count': 0, 'selected_split_candidate_count': trimmed_count,
             'discarded_split_candidate_count': 0, 'replacement_list': str(replacements),
             'replacement_list_sha256': digest_path(replacements)}
    arguments.audit.resolve().write_text(json.dumps(audit, indent=2) + '\n', encoding='utf-8', newline='\n')


def expand_arguments(argv: list[str]) -> list[str]:
    """Lossless argument transport, without Windows' CreateProcess limit.

    This is a JSON array of argv strings, not shell syntax or a nested response
    file. The ordinary parser still validates every flag and every input.
    """
    if not argv or argv[0] != '--arguments-json':
        return argv
    if len(argv) != 2:
        fail('--arguments-json must be the only option')
    values = json.loads(Path(argv[1]).read_text(encoding='utf-8'))
    if not isinstance(values, list) or not all(isinstance(v, str) and '\0' not in v for v in values):
        fail('argument file must contain an array of NUL-free strings')
    if '--arguments-json' in values:
        fail('nested argument files are not supported')
    return values


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
    parser.add_argument("--output-archive", type=Path)
    parser.add_argument("--output-rel-list", type=Path,
                        help="Trim direct objects and write input/output REL pairs, preserving every input")
    parser.add_argument("--audit", type=Path, required=True)
    arguments = parser.parse_args(expand_arguments(sys.argv[1:]))
    if arguments.code_limit <= 0 or arguments.xram_limit <= 0:
        fail("code and XRAM limits must be positive")
    splitter = arguments.splitter.resolve()
    sdar = arguments.sdar.resolve()
    work = arguments.work_dir.resolve()
    if bool(arguments.output_archive) == bool(arguments.output_rel_list):
        fail('provide exactly one output archive or direct REL list')
    for tool in (splitter, sdar):
        if not tool.is_file():
            fail(f"missing function archive tool: {tool}")
    work.mkdir(parents=True, exist_ok=True)

    members = [
        verify_metadata(Path(meta).resolve(), Path(actual).resolve(), arguments.code_limit, arguments.xram_limit)
        for meta, actual in arguments.member
    ]
    original_rel_paths = [Path(member.metadata["original_rel"]).resolve() for member in members]
    if len(original_rel_paths) != len(set(original_rel_paths)):
        fail("duplicate original REL in function archive group")
    if arguments.output_rel_list:
        trim_direct_members(members, arguments, work, splitter, sdar)
        return
    output_archive = arguments.output_archive.resolve()
    if not any(member.candidate for member in members):
        fail("function archive group has no oversized CSEG/XSEG candidate")

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
            if not member.candidate and member.trim_classification is None and not member.selected:
                member.candidate = can_trim_member(member, splitter)
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
    # All aliases are local, short names. Do not put hundreds of absolute
    # paths on a Windows command line a second time when invoking SDAR.
    run([str(sdar), "-rc", str(output_archive), *names], cwd=alias_dir)
    listing = run([str(sdar), "-t", str(output_archive)]).decode("utf-8").splitlines()
    if listing != names:
        fail("SDAR output member order/identity differs from the selected closure")
    for binding in archive_member_sources:
        archived = read_member(sdar, output_archive, binding["name"])
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
            "trim_classification": member.trim_classification,
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
