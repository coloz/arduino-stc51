#!/usr/bin/env python3
"""Bind temporary function-split archives to the final ASlink map."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path


def fail(message: str) -> None:
    raise SystemExit(f"C function split link audit failed: {message}")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def archive_member_alias(source_name: str, source_sha256: str) -> str:
    try:
        payload_hash = bytes.fromhex(source_sha256)
    except ValueError:
        fail("archive member source has an invalid SHA-256")
    if len(payload_hash) != 32 or source_sha256 != source_sha256.lower():
        fail("archive member source has an invalid SHA-256")
    identity = source_name.encode("utf-8") + b"\0" + payload_hash
    return "fs-" + hashlib.sha256(identity).hexdigest()[:24] + ".rel"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--audit-list", type=Path, required=True)
    parser.add_argument("--map", dest="map_path", type=Path, required=True)
    parser.add_argument("--link-arguments", type=Path, required=True)
    arguments = parser.parse_args()

    audit_list = arguments.audit_list.resolve()
    map_path = arguments.map_path.resolve()
    link_arguments = arguments.link_arguments.resolve()
    for path in (audit_list, map_path, link_arguments):
        if not path.is_file():
            fail(f"missing input: {path}")

    audit_paths = [
        Path(line).resolve()
        for line in audit_list.read_text(encoding="utf-8").splitlines()
        if line
    ]
    if len(audit_paths) != len(set(audit_paths)):
        fail("duplicate audit path")
    map_payload = map_path.read_text(encoding="utf-8", errors="replace")
    if "ASxxxx Linker V05.50.4-SDLD" not in map_payload:
        fail("final map is not the locked SDLD V05.50.4 format")
    map_lines = map_payload.splitlines()
    link_args = link_arguments.read_text(encoding="utf-8").splitlines()

    for audit_path in audit_paths:
        audit = json.loads(audit_path.read_text(encoding="utf-8"))
        if audit.get("schema_version") != 1 or audit.get("outcome") != "PASS":
            fail(f"unsupported or failed archive audit: {audit_path}")
        archive = Path(audit["output_archive"]).resolve()
        if not archive.is_file() or digest(archive) != audit["output_archive_sha256"]:
            fail(f"temporary archive hash mismatch: {archive}")
        if link_args.count(str(archive)) != 1:
            fail(f"temporary archive is not linked exactly once: {archive}")

        output_members = audit.get("output_archive_members")
        if not isinstance(output_members, list) or not output_members:
            fail(f"archive audit has no output members: {audit_path}")
        if len(output_members) != len(set(output_members)):
            fail(f"archive audit has duplicate output members: {audit_path}")
        if audit.get("output_archive_member_naming") != (
            "deterministic-source-and-content-sha256-v1"
        ):
            fail(f"archive audit has unsupported member naming: {audit_path}")
        source_bindings = audit.get("output_archive_member_sources")
        if not isinstance(source_bindings, list) or len(source_bindings) != len(output_members):
            fail(f"archive audit has invalid member source bindings: {audit_path}")
        bindings_by_name = {}
        for binding in source_bindings:
            if not isinstance(binding, dict) or set(binding) != {
                "name", "source_rel", "source_rel_sha256"
            }:
                fail(f"archive audit has malformed member source binding: {audit_path}")
            name = binding["name"]
            source_value = binding["source_rel"]
            source_sha256 = binding["source_rel_sha256"]
            if not all(isinstance(value, str) and value for value in (
                name, source_value, source_sha256
            )):
                fail(f"archive audit has malformed member source binding: {audit_path}")
            source = Path(source_value).resolve()
            if not source.is_file() or digest(source) != source_sha256:
                fail(f"archive member source hash mismatch: {source}")
            if name != archive_member_alias(source.name, source_sha256) or len(name) > 32:
                fail(f"archive member alias is not deterministic and display-safe: {name}")
            if name in bindings_by_name:
                fail(f"archive audit has duplicate member source binding: {name}")
            bindings_by_name[name] = binding
        if [binding["name"] for binding in source_bindings] != output_members:
            fail(f"archive member source bindings differ from output order: {audit_path}")
        archive_displays = []
        for index, line in enumerate(map_lines[:-1]):
            if line.strip() != str(archive):
                continue
            match = re.fullmatch(r"\s*\[\s*(\S+)\s*\]\s*", map_lines[index + 1])
            if not match:
                fail(f"archive path is not followed by an ASlink object record: {archive}")
            archive_displays.append(match.group(1))

        # Locked SDLD V05.50.4's Libraries Linked table prints at most 32
        # member characters.  The builder therefore gives every temporary
        # member a hash-bound name shorter than that limit; require the exact
        # display here instead of accepting an ambiguous source-name prefix.
        def display_matches(display: str, name: str) -> bool:
            return display == name or (len(display) == 32 and name.startswith(display))

        loaded = []
        for display in archive_displays:
            if display not in bindings_by_name:
                fail(f"ASlink member display is absent or ambiguous: {display}")
            binding = bindings_by_name[display]
            loaded.append({
                "name": display,
                "map_display": display,
                "source_rel": binding["source_rel"],
                "source_rel_sha256": binding["source_rel_sha256"],
            })
        loaded_names = [item["name"] for item in loaded]
        if sorted(loaded_names) != sorted(output_members):
            missing = sorted(set(output_members) - set(loaded_names))
            duplicated = sorted(name for name in set(loaded_names) if loaded_names.count(name) != 1)
            fail(f"selected archive members do not match final map: missing={missing} duplicated={duplicated}")

        excluded = []
        for member in audit.get("members", []):
            if not member.get("candidate"):
                continue
            name = Path(member["original_rel"]).name
            displays = re.findall(r"\[\s*(\S+)\s*\]", map_payload)
            if any(display_matches(display, name) for display in displays):
                fail(f"original oversized REL entered final map: {name}")
            excluded.append(name)

        audit["final_link"] = {
            "outcome": "PASS",
            "map": str(map_path),
            "map_sha256": digest(map_path),
            "link_arguments": str(link_arguments),
            "link_arguments_sha256": digest(link_arguments),
            "archive_argument_count": 1,
            "loaded_archive_member_count": len(loaded),
            "loaded_archive_members": loaded,
            "excluded_original_oversized_rels": sorted(excluded),
        }
        audit_path.write_text(
            json.dumps(audit, indent=2) + "\n", encoding="utf-8", newline="\n"
        )


if __name__ == "__main__":
    main()
