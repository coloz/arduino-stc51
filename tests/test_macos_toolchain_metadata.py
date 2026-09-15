"""Native Mac metadata must reject unresolved/non-system dylib dependencies."""
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('macos_metadata', Path(__file__).resolve().parents[1] / 'scripts/finalize-macos-toolchain.py')
metadata = importlib.util.module_from_spec(spec)
spec.loader.exec_module(metadata)


class MacToolchainMetadataTests(unittest.TestCase):
    def listing(self, path):
        return '/path with spaces/sdcc:\n\t' + path + ' (compatibility version 1.0.0, current version 1351.0.0)\n'

    def test_system_dependency_and_framework_path(self):
        for path in ('/usr/lib/libSystem.B.dylib', '/System/Library/Frameworks/Core Foundation.framework/CoreFoundation'):
            self.assertEqual(metadata.system_dependencies(self.listing(path)), [path])

    def test_external_and_unresolved_dependency_rejected(self):
        for path in ('/opt/homebrew/lib/libz.dylib', '@rpath/libz.dylib', '@loader_path/libz.dylib', '/usr/lib/../../opt/libz.dylib'):
            with self.subTest(path=path), self.assertRaisesRegex(ValueError, 'non-system'):
                metadata.system_dependencies(self.listing(path))

    def test_missing_or_unrecognized_dependencies_rejected(self):
        for listing in ('tool:\n', 'tool:\n\t/usr/lib/libSystem.B.dylib\n'):
            with self.subTest(listing=listing), self.assertRaises(ValueError): metadata.system_dependencies(listing)


if __name__ == '__main__': unittest.main()
