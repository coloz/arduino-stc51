import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class ReleaseAssetsTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.name = 'arduino-stc51-0.0.3.tar.bz2'
        self.data = b'fixture-payload'
        (self.root / self.name).write_bytes(self.data)
        self.manifest = {'schema_version': 1, 'version': '0.0.3', 'assets': [
            {'name': self.name, 'size': len(self.data),
             'sha256': hashlib.sha256(self.data).hexdigest()}]}

    def check(self, success, *extra):
        path = self.root / 'manifest.json'
        path.write_text(json.dumps(self.manifest), encoding='utf-8')
        # Production checks must reject corrupt input even under -O / -OO.
        for flag in ([], ['-O'], ['-OO']):
            with self.subTest(flag=flag):
                result = subprocess.run([sys.executable, *flag,
                    str(ROOT / 'scripts/verify-release-assets.py'), str(path),
                    str(self.root), *map(str, extra)], capture_output=True, text=True)
                self.assertEqual(result.returncode == 0, success, result.stdout + result.stderr)

    def test_valid_release(self):
        self.check(True, '--platform-archive', self.root / self.name)

    def test_same_size_corruption(self):
        (self.root / self.name).write_bytes(b'x' * len(self.data))
        self.check(False)

    def test_missing_file(self):
        (self.root / self.name).unlink()
        self.check(False)

    def test_wrong_size(self):
        self.manifest['assets'][0]['size'] += 1
        self.check(False)

    def test_wrong_reproduced_archive(self):
        other = self.root / 'other.tar.bz2'
        other.write_bytes(b'x' * len(self.data))
        self.check(False, '--platform-archive', other)

    def test_empty_inventory(self):
        self.manifest['assets'] = []
        self.check(False)

    def test_duplicate_asset(self):
        self.manifest['assets'] *= 2
        self.check(False)

    def test_path_traversal_and_invalid_fields(self):
        for name in ('../outside', '/tmp/outside', 'C:\\outside', 'sub/file'):
            self.manifest['assets'][0]['name'] = name
            self.check(False)
        self.manifest['assets'][0]['name'] = self.name
        self.manifest['assets'][0]['size'] = True
        self.check(False)


if __name__ == '__main__':
    unittest.main()
