#!/usr/bin/env python3
"""Select LLVM sidecars with archive semantics while preserving selected ctors.

LLVM treats ``llvm.global_ctors`` as an unconditional root, so passing every
Arduino core sidecar to ``llvm-link --only-needed`` pulls every translation
unit that owns a constructor.  This helper removes ctor lists only in a
selection probe, identifies the archive members actually needed by direct
translation units or native C ABI roots, and then relinks the original
bitcode for the selected members.  Consequently, constructors are retained
exactly for archive members that would have been pulled.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path


GLOBAL_CTORS = re.compile(
    r"^@llvm\.global_ctors\s*=\s*appending\s+global\s+.*(?:\n|$)",
    re.MULTILINE,
)

ODR_COALESCIBLE_LINKAGES = {"linkonce_odr", "weak_odr"}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sidecar_ir_path(bitcode: Path) -> Path:
    path = Path(str(bitcode).removesuffix(".bc") + ".ll")
    if not path.is_file():
        path = Path(str(bitcode).replace(".stcxx.bc", ".stcxx.ll"))
    if not path.is_file():
        raise SystemExit(f"missing C++ sidecar IR: {path}")
    return path


def public_definitions(ir: str) -> set[str]:
    symbols: set[str] = set()
    for line in ir.splitlines():
        match = None
        if line.startswith("define "):
            if re.search(r"\b(?:available_externally|internal|private)\b", line):
                continue
            match = re.search(r'@(?:"([^"]+)"|([-A-Za-z$._0-9]+))\(', line)
        elif line.startswith("@") and "=" in line:
            if re.search(r"=\s*(?:available_externally|external|internal|private)\b", line):
                continue
            match = re.match(r'@(?:"([^"]+)"|([-A-Za-z$._0-9]+))\s*=', line)
        if match:
            name = match.group(1) or match.group(2)
            if not name.startswith("llvm."):
                symbols.add(name)
    return symbols


def compile_identity(ir: str) -> dict[str, str]:
    """Extract the target and compiler identity shared by archive sidecars."""
    identity: dict[str, str] = {}
    for key, pattern in (
        ("target_datalayout", r'^target datalayout = "([^"]+)"$'),
        ("target_triple", r'^target triple = "([^"]+)"$'),
    ):
        matches = re.findall(pattern, ir, re.MULTILINE)
        if len(matches) != 1:
            raise SystemExit(f"LLVM module has no unique {key}")
        identity[key] = matches[0]
    ident_nodes = re.findall(r"^!llvm\.ident\s*=\s*!\{(.*)\}$", ir, re.MULTILINE)
    if len(ident_nodes) != 1:
        raise SystemExit("LLVM module has no unique llvm.ident named metadata")
    ident_body = ident_nodes[0].strip()
    if not ident_body or not re.fullmatch(r"!\d+(?:\s*,\s*!\d+)*", ident_body):
        raise SystemExit("LLVM module has malformed llvm.ident reference list")
    ident_refs = re.findall(r"!(\d+)", ident_body)
    ident_payloads: list[str] = []
    for ident_ref in ident_refs:
        payload_matches = re.findall(
            rf'^!{re.escape(ident_ref)}\s*=\s*!\{{!"((?:[^"\\]|\\.)+)"\}}$',
            ir,
            re.MULTILINE,
        )
        if len(payload_matches) != 1:
            raise SystemExit(
                f"LLVM module llvm.ident reference !{ident_ref} has no unique "
                "single-string payload"
            )
        ident_payloads.append(payload_matches[0])
    if len(set(ident_payloads)) != 1:
        raise SystemExit("LLVM module has mixed llvm.ident payloads")
    identity["llvm_ident"] = ident_payloads[0]
    return identity


def odr_definition_identities(ir: str) -> dict[str, dict[str, str]]:
    """Return narrowly auditable ODR-coalescible definitions.

    Clang emits inline C++ methods and ABI objects such as class vtables in
    every translation unit that needs them as ``linkonce_odr ... comdat``
    definitions.  Those repeated definitions are not ambiguous archive
    providers: LLVM is required to coalesce them.  Keep this deliberately
    limited to functions/globals with an explicit COMDAT identity; ordinary
    weak definitions and incomplete shapes remain fail-closed.
    """
    comdats: dict[str, str] = {}
    for match in re.finditer(
        r'^\$("[^"]+"|[-A-Za-z$._0-9]+) = comdat ([A-Za-z]+)$',
        ir,
        re.MULTILINE,
    ):
        raw_key = match.group(1)
        key = raw_key[1:-1] if raw_key.startswith('"') else raw_key
        comdats[key] = match.group(2)
    identities: dict[str, dict[str, str]] = {}
    for line in ir.splitlines():
        definition_kind: str
        if line.startswith("define "):
            definition_kind = "function"
            symbol_match = re.search(
                r'@(?:"([^"]+)"|([-A-Za-z$._0-9]+))\(', line
            )
            linkage_match = re.match(
                r"define\s+(?:dso_local\s+)?(linkonce_odr|weak_odr)\b", line
            )
        elif line.startswith("@") and "=" in line:
            definition_kind = "global"
            symbol_match = re.match(
                r'@(?:"([^"]+)"|([-A-Za-z$._0-9]+))\s*=\s*', line
            )
            linkage_match = re.match(
                r'@(?:"[^"]+"|[-A-Za-z$._0-9]+)\s*=\s*'
                r"(?:dso_local\s+)?(linkonce_odr|weak_odr)\b",
                line,
            )
        else:
            continue
        if not symbol_match or not linkage_match:
            continue
        symbol = symbol_match.group(1) or symbol_match.group(2)
        comdat_match = re.search(
            r"\bcomdat(?:\(\$(\"[^\"]+\"|[-A-Za-z$._0-9]+)\))?(?=[,\s]|$)",
            line,
        )
        if not comdat_match:
            continue
        raw_comdat_key = comdat_match.group(1)
        comdat_key = (
            raw_comdat_key[1:-1]
            if raw_comdat_key and raw_comdat_key.startswith('"')
            else raw_comdat_key or symbol
        )
        selection_kind = comdats.get(comdat_key)
        if selection_kind is None:
            continue
        # Attribute group numbers and numeric SSA argument names are
        # module-local identifiers, not part of the function type.
        signature = re.sub(r"#\d+", "#<attrs>", line)
        signature = re.sub(r"%\d+(?=\s*[,)]\s*)", "%<arg>", signature)
        identities[symbol] = {
            "definition_kind": definition_kind,
            "linkage": linkage_match.group(1),
            "comdat_key": comdat_key,
            "comdat_selection_kind": selection_kind,
            "signature": signature,
        }
    return identities


def definition_count(ir: str, symbol: str) -> int:
    quoted = re.escape(symbol)
    function_count = len(re.findall(
        rf'^define\b[^\n]*@(?:"{quoted}"|{quoted})\(', ir, re.MULTILINE
    ))
    global_count = len(re.findall(
        rf'^@(?:"{quoted}"|{quoted})\s*=\s*', ir, re.MULTILINE
    ))
    return function_count + global_count


def validate_final_odr(
    final_ir: str, records: dict[str, dict[str, object]]
) -> None:
    """Require each admitted ODR duplicate to become one identical definition."""
    final_odr_identities = odr_definition_identities(final_ir)
    for symbol, record in records.items():
        count = definition_count(final_ir, symbol)
        final_identity = final_odr_identities.get(symbol)
        if count != 1 or final_identity != record["identity"]:
            raise SystemExit(
                "linked ODR definition did not coalesce exactly once with its "
                f"audited identity: {symbol} (count={count})"
            )
        record["final_definition_count"] = count
        record["final_identity"] = final_identity


def audit_selected_odr_duplicates(
    direct_modules: list[dict[str, object]],
    candidates: list[dict[str, object]],
    selected: set[int],
    selection_reasons: dict[int, dict[str, object]],
    final_ir: str,
) -> dict[str, dict[str, object]]:
    """Audit duplicate definitions across every input that reaches final link."""
    all_owners: dict[str, list[str]] = {}
    selected_owners: dict[str, list[dict[str, object]]] = {}

    for module in direct_modules:
        label = f"direct:{module['index']}:{module['bitcode']}"
        for symbol in module["definitions"]:
            all_owners.setdefault(symbol, []).append(label)
            selected_owners.setdefault(symbol, []).append({
                "kind": "direct",
                "index": module["index"],
                "path": str(module["bitcode"]),
                "identity": module["odr_definitions"].get(symbol),
                "anchor": {"kind": "unconditional-direct-input"},
            })
    for candidate in candidates:
        index = int(candidate["index"])
        label = f"candidate:{index}:{candidate['archive']}({candidate['member']})"
        for symbol in candidate["definitions"]:
            all_owners.setdefault(symbol, []).append(label)
    for candidate in candidates:
        index = int(candidate["index"])
        if index not in selected:
            continue
        reason = selection_reasons.get(index)
        reason_symbols = list(reason.get("symbols", [])) if reason else []
        unique_anchor_symbols = sorted(
            symbol for symbol in reason_symbols
            if len(all_owners.get(symbol, [])) == 1
        )
        anchor = None
        if unique_anchor_symbols:
            anchor = {
                "kind": "unique-selected-definition",
                "symbols": unique_anchor_symbols,
                "selection_reason": reason,
            }
        for symbol in candidate["definitions"]:
            selected_owners.setdefault(symbol, []).append({
                "kind": "archive-candidate",
                "index": index,
                "archive": str(candidate["archive"]),
                "member": candidate["member"],
                "identity": candidate["odr_definitions"].get(symbol),
                "anchor": anchor,
            })

    records: dict[str, dict[str, object]] = {}
    for symbol, owners in sorted(selected_owners.items()):
        if len(owners) < 2:
            continue
        archive_owners = [
            owner for owner in owners if owner["kind"] == "archive-candidate"
        ]
        # Direct inputs are unconditionally linked and therefore do not pose
        # an archive-member provenance ambiguity by themselves.  If an
        # archive candidate also owns the symbol, however, it must have been
        # selected by a genuinely unique definition of its own.
        if not archive_owners:
            continue
        identities = [owner["identity"] for owner in owners]
        all_odr = all(identity is not None for identity in identities)
        same_identity = all_odr and all(
            identity == identities[0] for identity in identities[1:]
        )
        anchors = [owner["anchor"] for owner in owners if owner["anchor"]]
        archive_anchors = [
            owner["anchor"] for owner in archive_owners if owner["anchor"]
        ]
        if not same_identity or not archive_anchors:
            raise SystemExit(
                "selected inputs contain unauditable duplicate definitions: " + symbol
            )
        records[symbol] = {
            "owners": owners,
            "owner_count": len(owners),
            "identity": identities[0],
            "anchor_evidence": anchors,
            "archive_anchor_evidence": archive_anchors,
            "full_definition_owner_count": len(all_owners[symbol]),
        }

    validate_final_odr(final_ir, records)
    return records


def run_command(arguments: list[str]) -> None:
    subprocess.run(arguments, check=True)


def link(llvm_link: Path, inputs: list[Path], output: Path,
         only_needed: bool = False) -> None:
    command = [str(llvm_link)]
    if only_needed:
        command.append("--only-needed")
    command.extend(str(path) for path in inputs)
    command.extend(["-o", str(output)])
    run_command(command)


def disassemble(llvm_dis: Path, bitcode: Path, output: Path) -> None:
    run_command([str(llvm_dis), str(bitcode), "-o", str(output)])


def run() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--llvm-link", required=True, type=Path)
    parser.add_argument("--llvm-dis", required=True, type=Path)
    parser.add_argument("--roots", required=True, type=Path)
    parser.add_argument("--work-dir", required=True, type=Path)
    parser.add_argument("--output-bc", required=True, type=Path)
    parser.add_argument("--audit-json", required=True, type=Path)
    parser.add_argument("--direct", action="append", default=[], type=Path)
    parser.add_argument(
        "--candidate", action="append", default=[], nargs=3,
        metavar=("ARCHIVE", "MEMBER", "BITCODE"),
    )
    args = parser.parse_args()

    if not args.direct:
        raise SystemExit("at least one direct C++ sidecar is required")
    if not args.candidate:
        raise SystemExit("at least one C++ archive sidecar candidate is required")
    roots = {
        line for line in args.roots.read_text(encoding="utf-8").splitlines()
        if line
    }
    if not roots:
        raise SystemExit("empty C/C++ ABI root set")

    work = args.work_dir.resolve()
    work.mkdir(parents=True, exist_ok=True)
    direct = [path.resolve() for path in args.direct]
    for path in direct:
        if not path.is_file():
            raise SystemExit(f"missing direct C++ bitcode: {path}")

    candidates: list[dict[str, object]] = []
    seen_member_keys: set[tuple[Path, str]] = set()
    seen_bitcode: set[Path] = set(direct)
    for index, (archive_value, member, bitcode_value) in enumerate(args.candidate):
        archive = Path(archive_value).resolve()
        bitcode = Path(bitcode_value).resolve()
        key = (archive, member)
        if key in seen_member_keys:
            raise SystemExit(f"duplicate archive member candidate: {archive}({member})")
        if bitcode in seen_bitcode:
            raise SystemExit(f"duplicate C++ bitcode selection input: {bitcode}")
        if not archive.is_file() or not bitcode.is_file():
            raise SystemExit(f"missing C++ archive candidate input: {archive}({member})")
        ir_path = sidecar_ir_path(bitcode)
        ir = ir_path.read_text(encoding="utf-8")
        definitions = public_definitions(ir)
        module_compile_identity = compile_identity(ir)
        odr_definitions = odr_definition_identities(ir)
        if not definitions:
            raise SystemExit(f"archive candidate has no public LLVM definitions: {ir_path}")
        stripped_ir = GLOBAL_CTORS.sub("", ir)
        ctor_lists = len(GLOBAL_CTORS.findall(ir))
        if "@llvm.global_ctors" in stripped_ir:
            raise SystemExit(f"unsupported multiline llvm.global_ctors: {ir_path}")
        stripped_path = work / f"candidate-{index:03d}-no-ctors.ll"
        stripped_path.write_text(stripped_ir, encoding="utf-8", newline="\n")
        candidates.append({
            "index": index,
            "archive": archive,
            "member": member,
            "bitcode": bitcode,
            "ir": ir_path,
            "definitions": definitions,
            "compile_identity": module_compile_identity,
            "odr_definitions": odr_definitions,
            "stripped_ir": stripped_path,
            "ctor_list_count": ctor_lists,
        })
        seen_member_keys.add(key)
        seen_bitcode.add(bitcode)

    direct_modules: list[dict[str, object]] = []
    for index, bitcode in enumerate(direct):
        ir_path = sidecar_ir_path(bitcode)
        ir = ir_path.read_text(encoding="utf-8")
        direct_modules.append({
            "index": index,
            "bitcode": bitcode,
            "ir": ir_path,
            "definitions": public_definitions(ir),
            "odr_definitions": odr_definition_identities(ir),
            "compile_identity": compile_identity(ir),
        })

    direct_ir = work / "direct.ll"
    direct_bc = work / "direct.bc"
    link(args.llvm_link, direct, direct_bc)
    disassemble(args.llvm_dis, direct_bc, direct_ir)
    direct_ir_text = direct_ir.read_text(encoding="utf-8")
    direct_definitions = public_definitions(direct_ir_text)
    direct_compile_identity = compile_identity(direct_ir_text)
    mismatched_direct_identity = [
        int(module["index"])
        for module in direct_modules
        if module["compile_identity"] != direct_compile_identity
    ]
    if mismatched_direct_identity:
        raise SystemExit(
            "direct input target/compiler identity mismatch: "
            + ", ".join(str(index) for index in mismatched_direct_identity)
        )
    mismatched_compile_identity = [
        int(candidate["index"])
        for candidate in candidates
        if candidate["compile_identity"] != direct_compile_identity
    ]
    if mismatched_compile_identity:
        raise SystemExit(
            "archive candidate target/compiler identity mismatch: "
            + ", ".join(str(index) for index in mismatched_compile_identity)
        )

    selected: set[int] = set()
    selection_reasons: dict[int, dict[str, object]] = {}
    for candidate in candidates:
        hits = sorted(roots & candidate["definitions"])
        if hits:
            index = int(candidate["index"])
            selected.add(index)
            selection_reasons[index] = {"kind": "native-or-required-root", "symbols": hits}

    iterations: list[dict[str, object]] = []
    coalesced_odr_records: dict[str, dict[str, object]] = {}
    maximum_iterations = len(candidates) + 1
    final_bc = work / "selected-final.bc"
    final_ir = work / "selected-final.ll"
    for iteration in range(maximum_iterations):
        selected_inputs = direct + [
            candidate["bitcode"] for candidate in candidates
            if int(candidate["index"]) in selected
        ]
        base_bc = work / f"iteration-{iteration:03d}-base.bc"
        base_ir = work / f"iteration-{iteration:03d}-base.ll"
        link(args.llvm_link, selected_inputs, base_bc)
        disassemble(args.llvm_dis, base_bc, base_ir)
        base_definitions = public_definitions(base_ir.read_text(encoding="utf-8"))
        remaining = [
            candidate for candidate in candidates
            if int(candidate["index"]) not in selected
        ]
        if not remaining:
            final_bc, final_ir = base_bc, base_ir
            iterations.append({
                "iteration": iteration,
                "selected_before": sorted(selected),
                "newly_selected": [],
                "remaining": 0,
            })
            break

        probe_bc = work / f"iteration-{iteration:03d}-probe.bc"
        probe_ir = work / f"iteration-{iteration:03d}-probe.ll"
        link(
            args.llvm_link,
            [base_bc] + [candidate["stripped_ir"] for candidate in remaining],
            probe_bc,
            only_needed=True,
        )
        disassemble(args.llvm_dis, probe_bc, probe_ir)
        probe_definitions = public_definitions(probe_ir.read_text(encoding="utf-8"))
        added = probe_definitions - base_definitions

        definition_owners: dict[str, list[int]] = {}
        for candidate in remaining:
            for symbol in candidate["definitions"]:
                definition_owners.setdefault(symbol, []).append(int(candidate["index"]))
        new: set[int] = set()
        symbol_hits: dict[int, list[str]] = {}
        repeated: list[tuple[str, list[int]]] = []
        for symbol in sorted(added):
            owners = definition_owners.get(symbol, [])
            if len(owners) == 1:
                new.add(owners[0])
                symbol_hits.setdefault(owners[0], []).append(symbol)
            elif len(owners) > 1:
                repeated.append((symbol, owners))
        coalesced_odr: dict[str, dict[str, object]] = {}
        ambiguous: list[str] = []
        for symbol, owners in repeated:
            owner_identities = [
                candidates[owner]["odr_definitions"].get(symbol)
                for owner in owners
            ]
            all_odr = all(identity is not None for identity in owner_identities)
            same_odr_identity = all_odr and all(
                identity == owner_identities[0] for identity in owner_identities[1:]
            )
            # A shared ODR symbol can explain an added probe definition only
            # after at least one of its owners is independently identified by
            # a non-shared definition.  Otherwise archive-member provenance
            # remains unknowable and must still fail closed.
            selected_anchors = sorted(owner for owner in owners if owner in new)
            if same_odr_identity and selected_anchors:
                coalesced_odr[symbol] = {
                    "owners": owners,
                    "selected_owner_anchors": selected_anchors,
                    "identity": owner_identities[0],
                }
                previous = coalesced_odr_records.get(symbol)
                if previous is not None and previous != coalesced_odr[symbol]:
                    raise SystemExit(
                        f"ODR coalescing identity changed between iterations: {symbol}"
                    )
                coalesced_odr_records[symbol] = coalesced_odr[symbol]
            else:
                ambiguous.append(symbol)
        if ambiguous:
            raise SystemExit(
                "only-needed probe selected ambiguous archive definitions: "
                + ", ".join(ambiguous)
            )
        if not new:
            if added:
                raise SystemExit(
                    "only-needed probe added definitions not owned by a candidate: "
                    + ", ".join(sorted(added))
                )
            final_bc, final_ir = base_bc, base_ir
            iterations.append({
                "iteration": iteration,
                "selected_before": sorted(selected),
                "newly_selected": [],
                "remaining": len(remaining),
            })
            break
        for index in new:
            selection_reasons[index] = {
                "kind": "llvm-only-needed-reference",
                "symbols": sorted(symbol_hits[index]),
                "iteration": iteration,
            }
        iterations.append({
            "iteration": iteration,
            "selected_before": sorted(selected),
            "newly_selected": sorted(new),
            "remaining": len(remaining),
            "coalesced_odr_definitions": coalesced_odr,
        })
        selected.update(new)
    else:
        raise SystemExit("C++ archive selection failed to reach a fixed point")

    final_ir_text = final_ir.read_text(encoding="utf-8")
    missing_roots = sorted(roots - public_definitions(final_ir_text))
    if missing_roots:
        raise SystemExit("selected C++ sidecars do not define roots: " + ", ".join(missing_roots))
    selected_odr_records = audit_selected_odr_duplicates(
        direct_modules,
        candidates,
        selected,
        selection_reasons,
        final_ir_text,
    )
    args.output_bc.parent.mkdir(parents=True, exist_ok=True)
    args.output_bc.write_bytes(final_bc.read_bytes())

    audit_candidates = []
    for candidate in candidates:
        index = int(candidate["index"])
        audit_candidates.append({
            "archive": str(candidate["archive"]),
            "archive_sha256": digest(candidate["archive"]),
            "member": candidate["member"],
            "bitcode": str(candidate["bitcode"]),
            "bitcode_sha256": digest(candidate["bitcode"]),
            "llvm_ir_sha256": digest(candidate["ir"]),
            "ctor_list_count": candidate["ctor_list_count"],
            "stripped_probe_ir_sha256": digest(candidate["stripped_ir"]),
            "public_definition_count": len(candidate["definitions"]),
            "compile_identity": candidate["compile_identity"],
            "odr_coalescible_definition_count": len(candidate["odr_definitions"]),
            "selected": index in selected,
            "selection_reason": selection_reasons.get(index),
        })
    audit = {
        "schema_version": 1,
        "outcome": "pass",
        "policy": "ctor-aware-llvm-only-needed-archive-fixed-point",
        "selection_probe_removes_ctor_lists_only": True,
        "final_link_uses_original_selected_bitcode": True,
        "roots": sorted(roots),
        "direct_inputs": [
            {
                "path": str(module["bitcode"]),
                "sha256": digest(module["bitcode"]),
                "llvm_ir": str(module["ir"]),
                "llvm_ir_sha256": digest(module["ir"]),
                "public_definition_count": len(module["definitions"]),
                "odr_coalescible_definition_count": len(module["odr_definitions"]),
                "compile_identity": module["compile_identity"],
                "anchor": "unconditional-direct-input",
            }
            for module in direct_modules
        ],
        "candidate_count": len(candidates),
        "selected_candidate_count": len(selected),
        "selected_members": [
            f"{candidate['archive']}({candidate['member']})"
            for candidate in candidates if int(candidate["index"]) in selected
        ],
        "iterations": iterations,
        "probe_coalesced_odr_definitions": coalesced_odr_records,
        "coalesced_odr_definitions": selected_odr_records,
        "candidates": audit_candidates,
        "output_bc_sha256": digest(args.output_bc),
    }
    args.audit_json.write_text(
        json.dumps(audit, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    print(",".join(str(index) for index in sorted(selected)))
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
