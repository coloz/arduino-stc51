#!/usr/bin/env python3
"""Regress CLI helper accounting and audit boundaries for SDCC code sections."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_helper(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "tools/cpp-cli" / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


archive_builder = load_helper("build-function-split-archive")
function_splitter = load_helper("split-c-function-tu")
const_slicer = load_helper("slice-readonly-const-rel")


class SectionHelperTests(unittest.TestCase):
    def setUp(self):
        self.workspace = tempfile.TemporaryDirectory(prefix="stc-section-helpers-")
        self.addCleanup(self.workspace.cleanup)
        self.directory = Path(self.workspace.name)

    def write(self, name: str, payload: str) -> Path:
        path = self.directory / name
        path.write_text(payload, encoding="ascii")
        return path

    def candidate(self, areas: str, code_limit: int, xram_limit: int = 128):
        rel = self.write("candidate.rel", "XH3\nH 3 areas 1 global symbols\n" + areas + "S _entry Def000000\n")
        source = self.write("candidate.c", "void entry(void) {}\n")
        tool = self.write("tool", "fixture-tool\n")
        metadata = {"schema_version": 1}
        for path, key in ((rel, "original_rel"), (source, "source"), (tool, "clang"), (tool, "sdcc")):
            metadata[key] = str(path)
            metadata[key + "_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
        meta = self.write("candidate.json", json.dumps(metadata))
        return archive_builder.verify_metadata(meta, rel, code_limit, xram_limit).candidate

    def test_split_functions_share_original_tu_budget(self):
        self.assertTrue(self.candidate(
            "A CSEG size 0 flags 20 addr 0\n"
            "A CSEG_F_first size 40 flags 20 addr 0\n"
            "A CSEG_F_second size 40 flags 20 addr 0\n", 96))

    def test_legacy_function_budget_is_preserved(self):
        self.assertTrue(self.candidate("A CSEG size 80 flags 20 addr 0\n", 96))
        self.assertFalse(self.candidate("A CSEG size 60 flags 20 addr 0\n", 96))

    def test_const_sections_do_not_trigger_function_tu_splitting(self):
        self.assertFalse(self.candidate(
            "A CSEG size 0 flags 20 addr 0\n"
            "A CONST_D_array size 100 flags 20 addr 0\n", 96))

    def test_xram_budget_still_triggers(self):
        self.assertTrue(self.candidate(
            "A CSEG_F_entry size 1 flags 20 addr 0\n"
            "A XSEG size 81 flags 40 addr 0\n", 96))

    def test_function_symbol_gate_accepts_named_sections(self):
        rel = self.write("split.rel", "XH3\nH 2 areas 1 global symbols\n"
                         "A CSEG_F_entry size 10 flags 20 addr 0\nS _entry Def000000\n"
                         "A CSEG_F_static_helper size 10 flags 20 addr 0\n")
        result = function_splitter.verify_rel(rel, "entry", {"entry", "other"})
        self.assertEqual(result["symbol_gate"], "PASS")
        rel.write_text(rel.read_text() + "S _other Def000000\n", encoding="ascii")
        with self.assertRaisesRegex(SystemExit, "leaks other source entry"):
            function_splitter.verify_rel(rel, "entry", {"entry", "other"})

    def test_legacy_readonly_shape_and_relocation_gate(self):
        payload = ("XH3\nH 1 areas 2 global symbols\nS .__.ABS. Def000000\n"
                   "A CONST size 2 flags 20 addr 0\nS _array Def000000\n"
                   "T 00 00 00 AA BB\nR 00 00 00 00\n")
        rel = self.write("legacy.rel", payload)
        self.assertEqual(const_slicer.parse_rel(rel, require_slice_shape=True).const_data, b"\xaa\xbb")
        rel.write_text(payload.replace("R 00 00 00 00", "R 01 00 00 00"), encoding="ascii")
        with self.assertRaisesRegex(SystemExit, "real relocation"):
            const_slicer.parse_rel(rel, require_slice_shape=True)

    def test_per_object_readonly_shape_fails_closed(self):
        rel = self.write("sections.rel", "XH3\nH 2 areas 2 global symbols\nS .__.ABS. Def000000\n"
                         "A CONST size 0 flags 20 addr 0\nA CONST_D_array size 2 flags 20 addr 0\n"
                         "S _array Def000000\nT 00 00 00 AA BB\nR 00 00 00 01\n")
        with self.assertRaisesRegex(SystemExit, "per-object CONST_D_ sections require"):
            const_slicer.parse_rel(rel, require_slice_shape=True)


if __name__ == "__main__":
    unittest.main()
