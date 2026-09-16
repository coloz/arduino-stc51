#!/usr/bin/env python3
import hashlib
import importlib.util
import json
import re
import sys
from pathlib import Path

if len(sys.argv) != 14:
    raise SystemExit("heap-link audit argument vector differs")

path_arguments = list(map(Path, sys.argv[1:10]))
(
    audit_path,
    log_path,
    arguments_path,
    map_path,
    heap_rel_path,
    heap_state_rel_path,
    core_archive_path,
    archive_members_path,
    aslink_map_symbols_path,
) = path_arguments
(
    target_profile,
    mcs251_iram_size,
    mcs251_stack_loc,
    mcs251_stack_size,
) = sys.argv[10:14]

helper_spec = importlib.util.spec_from_file_location(
    "aslink_map_symbols", aslink_map_symbols_path
)
if helper_spec is None or helper_spec.loader is None:
    raise SystemExit("cannot load locked ASlink map-symbol helper")
aslink = importlib.util.module_from_spec(helper_spec)
helper_spec.loader.exec_module(aslink)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


link_log = log_path.read_text(encoding="utf-8", errors="replace")
duplicate_public_symbols = [
    line.strip()
    for line in link_log.splitlines()
    if "Definition of public symbol" in line or "found more than once" in line
]
if duplicate_public_symbols:
    raise SystemExit(
        "duplicate public symbol warning survived explicit STCXX heap link: "
        + repr(duplicate_public_symbols)
    )

arguments = arguments_path.read_text(encoding="utf-8").splitlines()
if target_profile == "mcs251":
    expected_stack_arguments = [
        "--iram-size", mcs251_iram_size,
        "--stack-loc", mcs251_stack_loc,
        "--stack-size", mcs251_stack_size,
    ]
    if (not all(re.fullmatch(r"0x[0-9A-Fa-f]+", value) for value in (
            mcs251_iram_size, mcs251_stack_loc, mcs251_stack_size))
            or sum(
                arguments[index:index + len(expected_stack_arguments)]
                == expected_stack_arguments
                for index in range(
                    len(arguments) - len(expected_stack_arguments) + 1
                )
            ) != 1
            or any(arguments.count(flag) != 1 for flag in (
                "--iram-size", "--stack-loc", "--stack-size"
            ))):
        raise SystemExit(
            "final MCS251 link arguments do not contain one exact extended-stack tuple"
        )
else:
    raise SystemExit(f"unexpected STCXX link target profile: {target_profile}")
heap_rel = str(heap_rel_path)
core_lib = str(core_archive_path.with_suffix(".lib"))
if arguments.count(heap_rel) != 1 or arguments.count(core_lib) != 1:
    raise SystemExit("STCXX heap/core archive link arguments are not unique")
if arguments.index(heap_rel) >= arguments.index(core_lib):
    raise SystemExit("STCXX heap object is not linked before core.lib")

heap_payload = heap_rel_path.read_text(encoding="ascii")
heap_size_symbol = "___sdcc_heap_size32"
opposite_heap_size_symbol = "___sdcc_heap_size"
heap_xseg = re.findall(
    r"^A XSEG size ([0-9A-Fa-f]+) flags ", heap_payload, re.MULTILINE
)
if len(heap_xseg) != 1:
    raise SystemExit("STCXX heap object has no unique XSEG allocation")
heap_bytes = int(heap_xseg[0], 16)
heap_state_payload = heap_state_rel_path.read_text(encoding="ascii")
heap_state_xseg = re.findall(
    r"^A XSEG size ([0-9A-Fa-f]+) flags ",
    heap_state_payload,
    re.MULTILINE,
)
if len(heap_state_xseg) != 1 or int(heap_state_xseg[0], 16) != 8:
    raise SystemExit("STCXX telemetry-state object is not exactly 8 XSEG bytes")
state_heap_provider_counts = {
    symbol: len(re.findall(
        rf"^S {re.escape(symbol)} Def[0-9A-Fa-f]+$",
        heap_state_payload,
        re.MULTILINE,
    ))
    for symbol in ("___sdcc_heap", "___sdcc_heap_size", "___sdcc_heap_size32", "___stcxx_heap_init")
}
if any(state_heap_provider_counts.values()):
    raise SystemExit("STCXX telemetry-state object provides a heap symbol")
state_symbols = (
    "___stcxx_heap_telemetry_ready_state",
    "___stcxx_heap_telemetry_valid_state",
    "___stcxx_heap_initial_total_free_state",
    "___stcxx_heap_minimum_total_free_state",
    "___stcxx_heap_minimum_largest_free_state",
)
state_object_providers = {
    symbol: len(re.findall(
        rf"^S {re.escape(symbol)} Def[0-9A-Fa-f]+$",
        heap_state_payload,
        re.MULTILINE,
    ))
    for symbol in state_symbols
}
if any(count != 1 for count in state_object_providers.values()):
    raise SystemExit(
        "STCXX telemetry-state object does not define each full state symbol "
        f"exactly once: {state_object_providers}"
    )
archive_members = archive_members_path.read_text(encoding="utf-8").splitlines()
archive_heap_members = archive_members.count("stcxx_heap.c.rel")
if archive_heap_members != 0:
    raise SystemExit("STCXX heap object remains in core archive")
archive_state_members = archive_members.count("stcxx_heap_state.c.rel")
if archive_state_members != 1:
    raise SystemExit("STCXX telemetry-state archive member is not unique")

link_map = map_path.read_text(encoding="utf-8", errors="replace")
if re.search(
    rf"^[A-Z]:[ \t]+[0-9A-Fa-f]+[ \t]+{re.escape(opposite_heap_size_symbol)}(?:[ \t]+[^\r\n]*)?$",
    link_map, re.MULTILINE,
):
    raise SystemExit(f"final map contains opposite-ABI heap-size provider: {opposite_heap_size_symbol}")
default_heap_members = len(re.findall(
    r"\[\s*_heap\.rel\s*\]", link_map
))
archived_custom_heap_members = len(re.findall(
    r"\[\s*stcxx_heap\.c\.rel\s*\]", link_map
))
linked_state_members = len(re.findall(
    r"\[\s*stcxx_heap_state\.c\.rel\s*\]", link_map
))
explicit_heap_objects = link_map.count(str(heap_rel_path))


def provider_count(symbol: str) -> int:
    return len(re.findall(
        rf"^[A-Z]:\s+[0-9A-Fa-f]+\s+{re.escape(symbol)}\s+stcxx_heap\s*$",
        link_map,
        re.MULTILINE,
    ))


providers = {
    "___sdcc_heap": provider_count("___sdcc_heap"),
    heap_size_symbol: provider_count(heap_size_symbol),
    "___stcxx_heap_init": provider_count("___stcxx_heap_init"),
}
try:
    state_map_displays = aslink.unique_aslink_global_displays(state_symbols)
except ValueError as error:
    raise SystemExit(str(error)) from error
state_providers = {
    symbol: aslink.provider_count(
        link_map, symbol, "stcxx_heap_state", state_map_displays
    )
    for symbol in state_symbols
}
xseg_match = re.search(
    r"^C:\s+([0-9A-Fa-f]+)\s+l_XSEG\s*$", link_map, re.MULTILINE
)
if (
    default_heap_members != 0
    or archived_custom_heap_members != 0
    or linked_state_members != 1
    or explicit_heap_objects != 1
    or any(count != 1 for count in providers.values())
    or any(count != 1 for count in state_providers.values())
    or xseg_match is None
    or int(xseg_match.group(1), 16) < heap_bytes + 8
):
    raise SystemExit(
        "final map does not prove one explicit STCXX heap and no default heap: "
        f"default={default_heap_members}, archived={archived_custom_heap_members}, "
        f"explicit={explicit_heap_objects}, state={linked_state_members}, "
        f"providers={providers}, state_providers={state_providers}"
    )

result = {
    "schema_version": 1,
    "outcome": "pass",
    "link_arguments": {
        "path": str(arguments_path.resolve()),
        "sha256": digest(arguments_path),
        "argument_count": len(arguments),
        "target_profile": target_profile,
        "mcs251_extended_stack": expected_stack_arguments,
    },
    "heap_object": {
        "path": str(heap_rel_path.resolve()),
        "sha256": digest(heap_rel_path),
        "xseg_bytes": heap_bytes,
        "explicit_link_argument_count": arguments.count(heap_rel),
        "map_file_occurrence_count": explicit_heap_objects,
    },
    "telemetry_state": {
        "path": str(heap_state_rel_path.resolve()),
        "sha256": digest(heap_state_rel_path),
        "xseg_bytes": int(heap_state_xseg[0], 16),
        "archive_member_count": archive_state_members,
        "map_file_occurrence_count": linked_state_members,
        "providers": state_providers,
        "object_providers": state_object_providers,
        "map_displays": state_map_displays,
        "heap_provider_counts": state_heap_provider_counts,
        "provides_heap_symbols": any(state_heap_provider_counts.values()),
    },
    "core_archive": {
        "path": str(core_archive_path.resolve()),
        "sha256": digest(core_archive_path),
        "members_sha256": digest(archive_members_path),
        "stcxx_heap_member_count": archive_heap_members,
        "stcxx_heap_state_member_count": archive_state_members,
        "linked_after_heap_object": True,
    },
    "link_log": {
        "path": str(log_path.resolve()),
        "sha256": digest(log_path),
        "duplicate_public_symbol_warning_count": len(duplicate_public_symbols),
    },
    "map": {
        "path": str(map_path.resolve()),
        "sha256": digest(map_path),
        "default_heap_member_count": default_heap_members,
        "archived_custom_heap_member_count": archived_custom_heap_members,
        "providers": providers,
        "xseg_bytes": int(xseg_match.group(1), 16),
    },
}
audit_path.write_text(
    json.dumps(result, indent=2) + "\n", encoding="utf-8", newline="\n"
)
