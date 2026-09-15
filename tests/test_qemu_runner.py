import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipIf(sys.platform == 'win32', 'QEMU runner uses POSIX pipes')
class QemuRunnerTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.firmware = self.root / 'test.hex'
        self.firmware.write_bytes(b'fixture')
        self.expected = self.root / 'expected.txt'
        self.expected.write_bytes(b'BEGIN test\nPASS test\n')

    def run_fixture(self, body, expected_status, timeout=0.5):
        fake = self.root / 'qemu'
        fake.write_text(f'#!{sys.executable}\nimport os, sys, time\n{body}\n', encoding='utf-8')
        fake.chmod(0o755)
        output = self.root / 'output'
        result = subprocess.run([sys.executable, str(ROOT / 'scripts/check-qemu-smoke.py'),
            '--qemu', str(fake), '--firmware', str(self.firmware),
            '--board', 'stc32g12k128', '--expected', str(self.expected),
            '--output', str(output), '--timeout', str(timeout)], capture_output=True, timeout=10)
        report = json.loads((output / 'qemu.json').read_text(encoding='utf-8'))
        self.assertEqual(report['status'], expected_status, result.stdout + result.stderr)
        self.assertEqual(result.returncode, 0 if expected_status == 'PASS' else 1)
        return report

    def test_split_crlf(self):
        self.run_fixture("os.write(1,b'BEGIN test\\r'); time.sleep(0.02); os.write(1,b'\\nPASS test\\r\\n'); time.sleep(2)", 'PASS')

    def test_fail_marker(self):
        self.run_fixture("os.write(1,b'BEGIN test\\nFAIL test\\n')", 'FAIL')

    def test_incomplete_transcript(self):
        self.run_fixture("os.write(1,b'BEGIN test\\n')", 'FAIL')

    def test_timeout(self):
        report = self.run_fixture('time.sleep(2)', 'FAIL')
        self.assertIn('timed out', report['error'])

    def test_configured_deadline_allows_complete_delayed_oracle(self):
        body = "time.sleep(0.2); os.write(1,b'BEGIN test\\nPASS test\\n'); time.sleep(2)"
        self.run_fixture(body, 'FAIL', timeout=0.05)
        report = self.run_fixture(body, 'PASS', timeout=1.5)
        self.assertEqual(report['timeout_seconds'], 1.5)

    def test_larger_deadline_still_rejects_wrong_oracle(self):
        self.run_fixture("os.write(1,b'BEGIN test\\nFAIL test\\n'); time.sleep(2)", 'FAIL', timeout=1.5)

    def test_invalid_deadlines_are_rejected_before_starting_qemu(self):
        for value in ('0', '-1', 'nan', 'inf', '-inf', '3600.1'):
            with self.subTest(value=value):
                output = self.root / 'invalid-output'
                result = subprocess.run([sys.executable, str(ROOT / 'scripts/check-qemu-smoke.py'),
                    '--qemu', str(self.root / 'never-started'), '--firmware', str(self.firmware),
                    '--board', 'stc32g12k128', '--expected', str(self.expected),
                    '--output', str(output), '--timeout=' + value], capture_output=True, timeout=10)
                self.assertEqual(result.returncode, 2)
                self.assertIn(b'timeout in (0, 3600]', result.stderr)
                self.assertFalse(output.exists())

    def test_changed_firmware(self):
        self.run_fixture("open(sys.argv[sys.argv.index('-bios')+1],'wb').write(b'changed'); os.write(1,b'BEGIN test\\nPASS test\\n'); time.sleep(2)", 'FAIL')

    def test_failed_run_replaces_stale_pass(self):
        self.run_fixture("os.write(1,b'BEGIN test\\nPASS test\\n'); time.sleep(2)", 'PASS')
        self.firmware.unlink()
        self.run_fixture('time.sleep(2)', 'FAIL')


if __name__ == '__main__':
    unittest.main()
