#!/usr/bin/env python3
import hashlib
import json
import re
import sys
from pathlib import Path

metadata_path, source, rel, clang, sdcc, triple, cpp_headers, resource_dir, sdcc_count, *arguments = sys.argv[1:]
sdcc_count = int(sdcc_count)
sdcc_arguments = arguments[:sdcc_count]
clang_arguments = [
    f"--target={triple}", "-std=gnu11", "-ffreestanding", "-funsigned-char",
    "-nostdinc", "-I" + cpp_headers, "-isystem" + str(Path(resource_dir) / "include"),
    # AST extraction uses only source ranges and function references. Native
    # SDCC recompiles the retained source with its original storage/ABI flags.
    "-D__code=", "-D__reentrant=",
] + arguments[sdcc_count:]

def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

result = {
    "schema_version": 1,
    "source": str(Path(source).resolve()),
    "source_sha256": digest(source),
    "original_rel": str(Path(rel).resolve()),
    "original_rel_sha256": digest(rel),
    "clang": str(Path(clang).resolve()),
    "clang_sha256": digest(clang),
    "clang_arguments": clang_arguments,
    "sdcc": str(Path(sdcc).resolve()),
    "sdcc_sha256": digest(sdcc),
    "sdcc_arguments": sdcc_arguments,
    "relocated_source_parent_include": str(Path(source).resolve().parent),
}
Path(metadata_path).write_text(
    json.dumps(result, indent=2) + "\n", encoding="utf-8", newline="\n"
)
