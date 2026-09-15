"""Exercise the actual bridge warning gate, including source-bound rejections."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class BridgeWarningTest(unittest.TestCase):
    def run_audit(self, source, message, *, line=1, code=85, other_source=False):
        driver = (ROOT / 'tools/cpp-cli/stcxx-cli.sh').read_text(encoding='utf-8')
        marker = 'log_path, audit_path = map(Path, sys.argv[1:3])'
        start = driver.index(marker)
        body = driver[start:driver.index('\nPY\n', start)]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            adapted = root / 'adapted.c'
            adapted.write_text(source, encoding='utf-8')
            log = root / 'bridge.log'
            origin = root / 'unrelated.c' if other_source else adapted
            log.write_text(f'{origin}:{line}: warning {code}: {message}\n', encoding='utf-8')
            ir_audit = root / 'audit.json'
            ir_audit.write_text(json.dumps({'ir': {'pointer_integer_conversions': {}}}))
            report = root / 'warnings.json'
            completed = subprocess.run(
                [sys.executable, '-c', 'import collections, json, re, sys\nfrom pathlib import Path\n' + body,
                 str(log), str(report), 'mcs251', str(ir_audit)],
                capture_output=True, text=True, timeout=10)
            return completed, json.loads(report.read_text()) if report.exists() else None

    def test_unused_callback_parameter_is_source_proven(self):
        result, audit = self.run_audit('static void callback(void* _77) {\n  return;\n}\n',
                                      "in function callback unreferenced function parameter : '_77'")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(audit['warning_codes'], {'85': 1})

    def test_unused_generated_local_at_function_end_is_source_proven(self):
        result, _ = self.run_audit('static void callback(void) {\n  uint16_t _77;\n  return;\n}\n',
                                  "in function callback unreferenced local variable : '_77'", line=4)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_unproven_unused_warnings_fail(self):
        message = "in function callback unreferenced function parameter : '_77'"
        for source, kwargs in (
            ('static void callback(void* _77) {\n  consume(_77);\n}\n', {}),
            ('void callback(void* _77) {\n  return;\n}\n', {}),
            ('static void callback(void* _77) {\n  return;\n}\n', {'line': 9}),
            ('static void callback(void* _77) {\n  return;\n}\n', {'code': 84}),
        ):
            with self.subTest(source=source, kwargs=kwargs):
                result, audit = self.run_audit(source, message, **kwargs)
                self.assertNotEqual(result.returncode, 0)
                self.assertIsNone(audit)

    def test_same_warning_from_another_file_fails(self):
        result, audit = self.run_audit('static void callback(void* _77) {\n  return;\n}\n',
                                      "in function callback unreferenced function parameter : '_77'",
                                      other_source=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIsNone(audit)


if __name__ == '__main__':
    unittest.main()
