"""Package metadata must expose tampering and reject unsafe archive links."""
import importlib.util
import os
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('linux_metadata', Path(__file__).resolve().parents[1] / 'scripts/finalize-linux-toolchain.py')
metadata = importlib.util.module_from_spec(spec)
spec.loader.exec_module(metadata)


class LinuxToolchainMetadataTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / 'package'
        (self.root / 'bin').mkdir(parents=True)
        (self.root / 'bin/sdcc').write_bytes(b'tool payload')
        (self.root / 'COPYING').write_text('license\n', encoding='utf-8')

    def test_manifest_covers_exact_files_and_exposes_mutation(self):
        before = metadata.write_manifest(self.root)
        recorded = dict(line.split('  ', 1)[::-1] for line in (self.root / 'MANIFEST.sha256').read_text().splitlines())
        self.assertEqual(set(recorded), {'bin/sdcc', 'COPYING'})
        self.assertEqual(recorded, {name: row['sha256'] for name, row in before.items()})
        (self.root / 'bin/sdcc').write_bytes(b'changed tool')
        self.assertNotEqual(recorded['bin/sdcc'], metadata.inventory(self.root)['bin/sdcc']['sha256'])

    def test_existing_manifest_is_preserved(self):
        manifest = self.root / 'MANIFEST.sha256'; manifest.write_bytes(b'existing evidence')
        with self.assertRaisesRegex(ValueError, 'overwrite'):
            metadata.write_manifest(self.root)
        self.assertEqual(manifest.read_bytes(), b'existing evidence')

    @unittest.skipIf(os.name == 'nt', 'POSIX link semantics')
    def test_internal_file_link_records_both_target_and_content(self):
        (self.root / 'bin/compiler').symlink_to('sdcc')
        entries = metadata.inventory(self.root)
        self.assertEqual(entries['bin/compiler']['link_target'], 'sdcc')
        self.assertEqual(entries['bin/compiler']['sha256'], entries['bin/sdcc']['sha256'])

    @unittest.skipIf(os.name == 'nt', 'POSIX link semantics')
    def test_external_link_rejected_before_manifest_creation(self):
        external = self.root.parent / 'outside'; external.write_bytes(b'outside')
        (self.root / 'bin/escape').symlink_to('../../outside')
        with self.assertRaisesRegex(ValueError, 'unsafe package link'):
            metadata.write_manifest(self.root)
        self.assertFalse((self.root / 'MANIFEST.sha256').exists())

    @unittest.skipIf(os.name == 'nt', 'POSIX link semantics')
    def test_absolute_internal_link_is_not_relocatable(self):
        (self.root / 'bin/absolute').symlink_to(self.root / 'bin/sdcc')
        with self.assertRaisesRegex(ValueError, 'unsafe package link'):
            metadata.inventory(self.root)

    @unittest.skipIf(os.name == 'nt', 'POSIX filenames')
    def test_newline_filename_cannot_inject_manifest_records(self):
        (self.root / 'new\nrecord').write_bytes(b'payload')
        with self.assertRaisesRegex(ValueError, 'unrepresentable'):
            metadata.write_manifest(self.root)
        self.assertFalse((self.root / 'MANIFEST.sha256').exists())


if __name__ == '__main__':
    unittest.main()
