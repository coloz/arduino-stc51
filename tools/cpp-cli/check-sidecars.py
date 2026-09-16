#!/usr/bin/env python3
import hashlib
import json
import sys
from pathlib import Path

triple, layout, *bitcode_paths = sys.argv[1:]

def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

for value in bitcode_paths:
    bitcode = Path(value).resolve()
    metadata_path = Path(value.replace(".stcxx.bc", ".stcxx.json"))
    if not metadata_path.is_file():
        raise SystemExit(f"missing C++ sidecar metadata: {metadata_path}")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    source = Path(metadata.get("source", "")).resolve()
    object_path = Path(metadata.get("object", "")).resolve()
    recorded_bitcode = Path(metadata.get("bitcode", "")).resolve()
    expected_object = Path(value.removesuffix(".stcxx.bc")).resolve()
    llvm_ir = Path(str(expected_object) + ".stcxx.ll")
    module_c = Path(str(expected_object) + ".stcxx.module.cbe")
    rel = Path(str(expected_object).removesuffix(".o") + ".rel")
    if (type(metadata.get("schema_version")) is not int
            or metadata.get("schema_version") != 1):
        raise SystemExit(f"unsupported C++ sidecar schema: {metadata_path}")
    if not source.is_file():
        raise SystemExit(f"C++ sidecar source no longer exists: {source}")
    if object_path != expected_object or recorded_bitcode != bitcode:
        raise SystemExit(f"C++ sidecar path mismatch: {metadata_path}")
    for artifact in (object_path, bitcode, llvm_ir, module_c, rel):
        if not artifact.is_file():
            raise SystemExit(f"missing C++ sidecar artifact: {artifact}")
    checks = {
        "source_sha256": digest(source),
        "object_sha256": digest(object_path),
        "bitcode_sha256": digest(bitcode),
        "llvm_ir_sha256": digest(llvm_ir),
        "module_c_sha256": digest(module_c),
    }
    mismatches = [name for name, observed in checks.items()
                  if metadata.get(name) != observed]
    if digest(rel) != checks["object_sha256"]:
        mismatches.append("rel_sha256")
    if mismatches:
        raise SystemExit(
            f"stale or modified C++ sidecar {metadata_path}: "
            + ", ".join(mismatches)
        )
    if metadata.get("target_triple") != triple or metadata.get("data_layout") != layout:
        raise SystemExit(f"C++ sidecar target mismatch: {metadata_path}")
print(f"STCXX_CURRENT_LINK_SIDECARS={len(bitcode_paths)}")
