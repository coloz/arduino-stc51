#!/usr/bin/env python3
import hashlib
import json
import re
import sys
from pathlib import Path

(
    manifest_path,
    firmware,
    lock_path,
    audit_path,
    warning_audit_path,
    heap_link_audit_path,
    member_function_alignment_audit_path,
    c_abi_path,
    c_abi_root_audit_path,
    discovery_root_audit_path,
    archive_selection_audit_path,
    root_collector_path,
    archive_selector_path,
    member_function_aligner_path,
    readonly_const_slicer_path,
    function_tu_splitter_path,
    function_archive_builder_path,
    function_link_map_auditor_path,
    readonly_slice_audit_list_path,
    function_split_audit_list_path,
    all_candidates_bc_path,
    selected_bc_path,
    selected_ir_path,
    optimized_bc_path,
    optimized_ir_path,
    raw_c_path,
    adapted_c_path,
    bridge_raw_asm_path,
    bridge_asm_path,
    bridge_rel_path,
    bridge_lst_path,
    bridge_rst_path,
    target_profile,
    target_triple,
    data_layout,
    abi_identity_symbol,
    mcs251_iram_size,
    mcs251_stack_loc,
    mcs251_stack_size,
    build_f_cpu_hz,
    separator,
    *bitcode,
) = sys.argv[1:]
if separator != "--":
    raise SystemExit("manifest argument separator is missing")
build_f_cpu_hz = int(build_f_cpu_hz)
def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))
SDCC_SYMNAME_MAX = 256
ASXXXX_NCPS = 256
SAFE_C_SYMBOL = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")
def alignment_function_records(functions, directive, label):
    expected_keys = {
        "asxxxx_ncps", "c_symbols", "llvm_symbols",
        "member_function_symbols", "records", "sdcc_symname_max",
    }
    if (not isinstance(functions, dict) or set(functions) != expected_keys
            or type(functions.get("sdcc_symname_max")) is not int
            or functions.get("sdcc_symname_max") != SDCC_SYMNAME_MAX
            or type(functions.get("asxxxx_ncps")) is not int
            or functions.get("asxxxx_ncps") != ASXXXX_NCPS):
        raise SystemExit(f"{label} function symbol contract differs")
    c_symbols = functions.get("c_symbols")
    if (not isinstance(c_symbols, list)
            or any(not isinstance(symbol, str)
                   or SAFE_C_SYMBOL.fullmatch(symbol) is None
                   for symbol in c_symbols)
            or c_symbols != sorted(c_symbols)
            or len(c_symbols) != len(set(c_symbols))):
        raise SystemExit(f"{label} C symbol set differs")
    mappings = [
        {
            "assembly_label": "_" + symbol[:SDCC_SYMNAME_MAX],
            "asxxxx_symbol": (
                "_" + symbol[:SDCC_SYMNAME_MAX]
            )[:ASXXXX_NCPS - 1],
            "c_symbol": symbol,
            "directive": directive,
        }
        for symbol in c_symbols
    ]
    for key in ("assembly_label", "asxxxx_symbol"):
        values = [record[key] for record in mappings]
        if len(values) != len(set(values)):
            raise SystemExit(f"{label} has a truncated {key} collision")
    if functions.get("records") != mappings:
        raise SystemExit(f"{label} function mapping records differ")
    return c_symbols, mappings
def validate_relocation_records(records, mappings, expected_even, label):
    expected_keys = {
        "address", "address_hex", "assembly_label", "asxxxx_symbol",
        "c_symbol", "even",
    }
    if not isinstance(records, list) or len(records) != len(mappings):
        raise SystemExit(f"{label} record count differs")
    for record, mapping in zip(records, mappings):
        address = record.get("address") if isinstance(record, dict) else None
        if (not isinstance(record, dict) or set(record) != expected_keys
                or type(address) is not int
                or type(record.get("even")) is not bool
                or record.get("even") is not expected_even
                or address % 2 != (0 if expected_even else 1)
                or record.get("address_hex") != f"{address:06X}"
                or record.get("assembly_label") != mapping["assembly_label"]
                or record.get("asxxxx_symbol") != mapping["asxxxx_symbol"]
                or record.get("c_symbol") != mapping["c_symbol"]):
            raise SystemExit(f"{label} differs")
def load_audit_list(path, label):
    paths = [Path(item) for item in Path(path).read_text(encoding="utf-8").splitlines() if item]
    if len(paths) != len(set(paths)):
        raise SystemExit(f"duplicate {label} audit path")
    result = []
    for audit_path in paths:
        audit = load_json(audit_path)
        outcome = audit.get("outcome")
        if outcome is not None and str(outcome).lower() != "pass":
            raise SystemExit(f"{label} audit did not pass: {audit_path}")
        result.append({
            "path": str(audit_path.resolve()),
            "sha256": digest(audit_path),
            "audit": audit,
        })
    return result
archive_selection = load_json(archive_selection_audit_path)
member_alignment = load_json(member_function_alignment_audit_path)
alignment_directory = Path(member_function_alignment_audit_path).parent
prior_alignment_audit_path = alignment_directory / "member-function-alignment-prior-audit.json"
prior_even_paths = {
    "aligned_assembly_sha256": alignment_directory / "cpp-bridge.prior-even.asm",
    "sdcc_bridge_rel_sha256": alignment_directory / "cpp-bridge.prior-even.rel",
    "assembly_listing_sha256": alignment_directory / "cpp-bridge.prior-even.lst",
    "relocated_listing_sha256": alignment_directory / "cpp-bridge.prior-even.rst",
}
member_alignment_relocation = member_alignment.get("relocation_verification")
member_alignment_assembly = member_alignment.get("assembly")
member_alignment_functions = member_alignment.get("function_alignment")
member_alignment_tool = member_alignment.get("tool")
member_alignment_adapter = member_alignment.get("adapter_audit")
if (type(member_alignment.get("schema_version")) is not int
        or member_alignment.get("schema_version") != 2
        or member_alignment.get("outcome") != "pass"
        or member_alignment.get("phase") != "verified"
        or member_alignment.get("target_profile") != target_profile
        or member_alignment.get("alignment_bytes") != 2
        or not isinstance(member_alignment_relocation, dict)
        or member_alignment_relocation.get("outcome") != "pass"
        or not isinstance(member_alignment_assembly, dict)
        or type(member_alignment_assembly.get("mutation_count")) is not int
        or not isinstance(member_alignment_functions, dict)
        or not isinstance(member_alignment_tool, dict)
        or not isinstance(member_alignment_adapter, dict)):
    raise SystemExit("member-function alignment audit is not a final exact PASS")
member_alignment_c_symbols, member_alignment_function_records = (
    alignment_function_records(
        member_alignment_functions,
        member_alignment.get("directive"),
        "member-function alignment audit",
    )
)
member_alignment_realignment = member_alignment.get("realignment")
prior_member_alignment = None
prior_bridge_artifacts = {}
if member_alignment_realignment is not None:
    if (set(member_alignment_realignment) != {
            "from_local_parity", "prior_audit_sha256", "reason"}
            or member_alignment_realignment.get("from_local_parity") != "even"
            or member_alignment_realignment.get("reason")
            != "uniform-odd-final-addresses"
            or member_alignment.get("directive") != ".odd"
            or member_alignment_assembly.get("local_parity") != "odd"):
        raise SystemExit("member-function realignment contract differs")
    if not prior_alignment_audit_path.is_file() or any(
            not path.is_file() for path in prior_even_paths.values()):
        raise SystemExit("member-function prior realignment artifacts are incomplete")
    if (member_alignment_realignment.get("prior_audit_sha256")
            != digest(prior_alignment_audit_path)):
        raise SystemExit("member-function prior realignment audit hash differs")
    prior_member_alignment = load_json(prior_alignment_audit_path)
    prior_assembly = prior_member_alignment.get("assembly")
    prior_relocation = prior_member_alignment.get("relocation_verification")
    prior_functions = prior_member_alignment.get("function_alignment")
    if (set(prior_member_alignment) != {
            "adapter_audit", "alignment_bytes", "assembly", "directive",
            "function_alignment", "outcome", "phase", "policy",
            "relocation_verification", "schema_version", "target_profile", "tool"}
            or type(prior_member_alignment.get("schema_version")) is not int
            or prior_member_alignment.get("schema_version") != 2
            or prior_member_alignment.get("outcome") != "realign_required"
            or prior_member_alignment.get("phase") != "realign_required"
            or prior_member_alignment.get("directive") != ".even"
            or prior_member_alignment.get("target_profile") != target_profile
            or prior_member_alignment.get("alignment_bytes") != 2
            or not isinstance(prior_assembly, dict)
            or type(prior_assembly.get("mutation_count")) is not int
            or prior_assembly.get("local_parity") != "even"
            or prior_assembly.get("input_sha256") != digest(bridge_raw_asm_path)
            or prior_assembly.get("output_sha256")
            != digest(prior_even_paths["aligned_assembly_sha256"])
            or not isinstance(prior_relocation, dict)
            or prior_relocation.get("outcome") != "realign_required"
            or prior_relocation.get("recommended_local_parity") != "odd"
            or prior_relocation.get("relocated_listing_sha256")
            != digest(prior_even_paths["relocated_listing_sha256"])
            or not isinstance(prior_functions, dict)
            or prior_functions.get("c_symbols")
            != member_alignment_functions.get("c_symbols")):
        raise SystemExit("member-function prior realignment audit differs")
    prior_c_symbols, prior_function_records = alignment_function_records(
        prior_functions, ".even", "prior member-function alignment audit"
    )
    if prior_c_symbols != member_alignment_c_symbols:
        raise SystemExit("prior/final member-function symbols differ")
    prior_records = prior_relocation.get("records")
    if (not prior_function_records
            or prior_relocation.get("checked_symbol_count")
            != len(prior_function_records)):
        raise SystemExit("member-function prior relocated addresses are not uniformly odd")
    validate_relocation_records(
        prior_records, prior_function_records, False,
        "member-function prior relocated addresses",
    )
    prior_bridge_artifacts = {
        "member_function_alignment_prior_audit_sha256": digest(
            prior_alignment_audit_path
        ),
        **{f"prior_even_{key}": digest(path) for key, path in prior_even_paths.items()},
    }
else:
    if (member_alignment.get("directive") != ".even"
            or member_alignment_assembly.get("local_parity") != "even"
            or any(
                path.exists()
                for path in [prior_alignment_audit_path, *prior_even_paths.values()]
            )):
        raise SystemExit("unexpected member-function prior realignment artifacts")
member_alignment_records = member_alignment_relocation.get("records")
if (not isinstance(member_alignment_records, list)
        or not isinstance(member_alignment_c_symbols, list)
        or member_alignment_relocation.get("checked_symbol_count")
        != len(member_alignment_c_symbols)
        or len(member_alignment_records) != len(member_alignment_c_symbols)):
    raise SystemExit("member-function relocated address evidence differs")
validate_relocation_records(
    member_alignment_records, member_alignment_function_records, True,
    "member-function relocated address evidence",
)
if (member_alignment_tool.get("path")
        != str(Path(member_function_aligner_path).resolve())
        or member_alignment_tool.get("sha256")
        != digest(member_function_aligner_path)
        or member_alignment_adapter.get("path")
        != str(Path(audit_path).resolve())
        or member_alignment_adapter.get("sha256") != digest(audit_path)
        or member_alignment_assembly.get("input_path")
        != str(Path(bridge_raw_asm_path).resolve())
        or member_alignment_assembly.get("input_sha256")
        != digest(bridge_raw_asm_path)
        or member_alignment_assembly.get("output_path")
        != str(Path(bridge_asm_path).resolve())
        or member_alignment_assembly.get("output_sha256")
        != digest(bridge_asm_path)
        or member_alignment_relocation.get("relocated_listing")
        != str(Path(bridge_rst_path).resolve())
        or member_alignment_relocation.get("relocated_listing_sha256")
        != digest(bridge_rst_path)):
    raise SystemExit("member-function alignment provenance differs")
readonly_slice_audits = load_audit_list(
    readonly_slice_audit_list_path, "readonly CONST slice"
)
function_split_audits = load_audit_list(
    function_split_audit_list_path, "C function split"
)
direct_bitcode = {
    str(Path(item["path"]).resolve())
    for item in archive_selection["direct_inputs"]
}
candidate_by_bitcode = {
    str(Path(item["bitcode"]).resolve()): item
    for item in archive_selection["candidates"]
}
modules = []
for path in bitcode:
    meta_path = Path(path.replace(".stcxx.bc", ".stcxx.json"))
    metadata = load_json(meta_path)
    resolved = str(Path(path).resolve())
    if resolved in direct_bitcode:
        metadata["link_disposition"] = "direct"
        metadata["selected_for_bridge"] = True
    else:
        candidate = candidate_by_bitcode.get(resolved)
        if candidate is None:
            raise SystemExit(f"module is absent from archive-selection audit: {path}")
        metadata["link_disposition"] = (
            "selected-archive-member" if candidate["selected"]
            else "discarded-archive-candidate"
        )
        metadata["selected_for_bridge"] = candidate["selected"]
        metadata["archive"] = candidate["archive"]
        metadata["archive_member"] = candidate["member"]
        metadata["selection_reason"] = candidate["selection_reason"]
    modules.append(metadata)
qualification = (
    f"EXPERIMENTAL_{target_profile.upper()}_{build_f_cpu_hz // 1000000}MHZ_ARDUINO_CLI_COMPILE_LINK"
)
runtime_qualification = "SEPARATE_EXACT_QEMU_VARIANT_MATRIX_GATE"
stack_identity = None
if target_profile == "mcs251":
    stack_identity = {
        "iram_size": mcs251_iram_size,
        "stack_loc": mcs251_stack_loc,
        "stack_size": mcs251_stack_size,
    }
result = {
    "schema_version": 2,
    "outcome": "pass",
    "qualification": qualification,
    "runtime_qualification": runtime_qualification,
    "target": {
        "profile": target_profile,
        "build_f_cpu_hz": build_f_cpu_hz,
        "target_triple": target_triple,
        "data_layout": data_layout,
        "abi_identity_symbol": abi_identity_symbol,
        "memory_model": "large",
        "calling_model": "stack-auto",
        "mcs251_extended_stack": stack_identity,
    },
    "firmware": str(Path(firmware).resolve()),
    "firmware_sha256": digest(firmware),
    "lock_sha256": digest(lock_path),
    "audit_sha256": digest(audit_path),
    "audit": load_json(audit_path),
    "sdcc_warning_audit_sha256": digest(warning_audit_path),
    "sdcc_warning_audit": json.loads(
        Path(warning_audit_path).read_text(encoding="utf-8")
    ),
    "heap_link_audit_sha256": digest(heap_link_audit_path),
    "heap_link_audit": json.loads(
        Path(heap_link_audit_path).read_text(encoding="utf-8")
    ),
    "member_function_alignment_audit_sha256": digest(
        member_function_alignment_audit_path
    ),
    "member_function_alignment_audit": member_alignment,
    "c_abi_preserve_sha256": digest(c_abi_path),
    "c_abi_preserved_symbols": Path(c_abi_path).read_text(
        encoding="utf-8"
    ).splitlines(),
    "c_abi_root_collector": {
        "path": str(Path(root_collector_path).resolve()),
        "sha256": digest(root_collector_path),
    },
    "c_abi_root_discovery_audit_sha256": digest(discovery_root_audit_path),
    "c_abi_root_discovery_audit": load_json(discovery_root_audit_path),
    "c_abi_root_audit_sha256": digest(c_abi_root_audit_path),
    "c_abi_root_audit": load_json(c_abi_root_audit_path),
    "cpp_archive_selector": {
        "path": str(Path(archive_selector_path).resolve()),
        "sha256": digest(archive_selector_path),
    },
    "member_function_aligner": {
        "path": str(Path(member_function_aligner_path).resolve()),
        "sha256": digest(member_function_aligner_path),
    },
    "cpp_archive_selection_audit_sha256": digest(archive_selection_audit_path),
    "cpp_archive_selection_audit": archive_selection,
    "native_c_size_reduction": {
        "readonly_const_slicer": {
            "path": str(Path(readonly_const_slicer_path).resolve()),
            "sha256": digest(readonly_const_slicer_path),
        },
        "function_tu_splitter": {
            "path": str(Path(function_tu_splitter_path).resolve()),
            "sha256": digest(function_tu_splitter_path),
        },
        "function_archive_builder": {
            "path": str(Path(function_archive_builder_path).resolve()),
            "sha256": digest(function_archive_builder_path),
        },
        "function_link_map_auditor": {
            "path": str(Path(function_link_map_auditor_path).resolve()),
            "sha256": digest(function_link_map_auditor_path),
        },
        "readonly_const_slices": {
            "outcome": "PASS",
            "audit_count": len(readonly_slice_audits),
            "input_const_bytes": sum(
                item["audit"]["input"]["const_size"] for item in readonly_slice_audits
            ),
            "output_const_bytes": sum(
                item["audit"]["output"]["const_size"] for item in readonly_slice_audits
            ),
            "selected_definition_count": sum(
                len(item["audit"]["selected"]) for item in readonly_slice_audits
            ),
            "discarded_definition_count": sum(
                len(item["audit"]["discarded"]) for item in readonly_slice_audits
            ),
            "audits": readonly_slice_audits,
        },
        "function_split_archives": {
            "outcome": "PASS",
            "audit_count": len(function_split_audits),
            "selected_archive_member_count": sum(
                item["audit"]["selected_member_count"] for item in function_split_audits
            ),
            "selected_direct_object_count": sum(
                item["audit"].get("selected_direct_object_count", 0) for item in function_split_audits
            ),
            "discarded_input_member_count": sum(
                item["audit"]["discarded_input_member_count"] for item in function_split_audits
            ),
            "selected_split_candidate_count": sum(
                item["audit"]["selected_split_candidate_count"] for item in function_split_audits
            ),
            "discarded_split_candidate_count": sum(
                item["audit"]["discarded_split_candidate_count"] for item in function_split_audits
            ),
            "audits": function_split_audits,
        },
    },
    "bridge_artifacts": {
        "all_candidates_linked_bitcode_sha256": digest(all_candidates_bc_path),
        "selected_linked_bitcode_sha256": digest(selected_bc_path),
        "selected_linked_ir_sha256": digest(selected_ir_path),
        "optimized_bitcode_sha256": digest(optimized_bc_path),
        "optimized_ir_sha256": digest(optimized_ir_path),
        "llvm_cbe_raw_c_sha256": digest(raw_c_path),
        "adapted_c_sha256": digest(adapted_c_path),
        "raw_assembly_sha256": digest(bridge_raw_asm_path),
        "aligned_assembly_sha256": digest(bridge_asm_path),
        "sdcc_bridge_rel_sha256": digest(bridge_rel_path),
        "assembly_listing_sha256": digest(bridge_lst_path),
        "relocated_listing_sha256": digest(bridge_rst_path),
        **prior_bridge_artifacts,
    },
    "cpp_translation_units": len(modules),
    "selected_cpp_translation_units": sum(
        1 for module in modules if module["selected_for_bridge"]
    ),
    "modules": modules,
}
if prior_member_alignment is not None:
    result["member_function_alignment_prior_audit_sha256"] = digest(
        prior_alignment_audit_path
    )
    result["member_function_alignment_prior_audit"] = prior_member_alignment
Path(manifest_path).write_text(
    json.dumps(result, indent=2) + "\n", encoding="utf-8", newline="\n"
)
