#!/usr/bin/env python3
import hashlib
import json
import sys
from pathlib import Path

source, object_path, bitcode, llvm_ir, module_c, triple, layout, optimization = sys.argv[1:]
def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()
metadata = {
    "schema_version": 1,
    "source": str(Path(source).resolve()),
    "source_sha256": digest(source),
    "object": str(Path(object_path).resolve()),
    "object_sha256": digest(object_path),
    "bitcode": str(Path(bitcode).resolve()),
    "bitcode_sha256": digest(bitcode),
    "llvm_ir_sha256": digest(llvm_ir),
    "module_c_sha256": digest(module_c),
    "target_triple": triple,
    "data_layout": layout,
    "alias_count": 0,
    "module_llvm_cbe": "pass",
    "clang_optimization": "-O" + optimization,
    "clang_vectorization": "disabled-loop-and-slp",
}
Path(object_path + ".stcxx.json").write_text(
    json.dumps(metadata, indent=2) + "\n", encoding="utf-8", newline="\n"
)
