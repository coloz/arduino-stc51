"""Reject broken native release payloads without losing older host support."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

spec = importlib.util.spec_from_file_location('native_release',
    Path(__file__).resolve().parents[1] / 'create-native-release-index.py')
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


class NativeReleaseTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.platform = self.root / 'arduino-stc51-0.0.6.zip'
        self.previous = {'packages': [{'name': 'stc', 'platforms': [{'version': '0.0.5'}],
            'tools': [{'name': 'stcxx-toolchain', 'version': '0.1.0',
                       'systems': [{'host': 'arm64-apple-darwin'}]}]}]}
        self.files = {
            'platform.txt': b'version=0.0.6\ncompiler.driver={runtime.platform.path}/tools/stcxx-driver/stcxx\n',
            'tools/variants/devices.json': b'{"devices":[{"target":"mcs251","model":"Board"}]}',
            'tools/stcxx-driver/stcxx.exe': b'native-driver',
            'tools/stcxx-driver/toolchain-lock.windows-x86_64.json': b'{}'}
        self.write(self.platform, 'arduino-stc51-0.0.6', self.files)
        self.manifest = {'tools': []}
        for name, version, files in [
            ('stcxx-toolchain', '0.2.0', {'toolchain.json':
                b'{"version":"0.2.0","execution":"native","runtime_interpreters":[]}'}),
            ('stc-cli', '0.1.0-stc.2', {'stc-cli.exe': b'uploader',
                'build-info.json': b'{"sourceCommit":"fixture"}'})]:
            path = self.root / (name + '.zip')
            self.write(path, name, files)
            self.manifest['tools'].append({'id': name, 'version': version, 'sourceCommit': 'fixture',
                'systems': [{'host': 'x86_64-mingw32', 'archiveFileName': path.name, 'archiveRoot': name,
                    'size': path.stat().st_size, 'sha256': release.sha256(path),
                    'url': 'https://github.com/coloz/arduino-stc51/releases/download/v0.0.6/' + path.name}]})

    def write(self, path, root, files):
        with zipfile.ZipFile(path, 'w') as archive:
            for name, content in files.items():
                archive.writestr(root + '/' + name, content)
            manifest = ''.join(hashlib.sha256(content).hexdigest() + '  ' + name + '\n'
                               for name, content in files.items())
            archive.writestr(root + '/MANIFEST.sha256', manifest)

    def create(self):
        return release.create(self.platform, self.root, self.previous, self.manifest)

    def test_retains_old_platform_and_mac_tool_without_mutating_input(self):
        before = copy.deepcopy(self.previous)
        result = self.create()['packages'][0]
        self.assertEqual(self.previous, before)
        self.assertEqual(result['platforms'][1:], before['packages'][0]['platforms'])
        self.assertEqual(result['tools'][-1], before['packages'][0]['tools'][0])
        self.previous = {'packages': [result]}
        with self.assertRaisesRegex(ValueError, 'version already exists'):
            self.create()

    def test_missing_host_driver_and_modified_archive_are_rejected(self):
        del self.files['tools/stcxx-driver/stcxx.exe']
        self.write(self.platform, 'arduino-stc51-0.0.6', self.files)
        with self.assertRaisesRegex(ValueError, 'Missing driver'):
            self.create()
        self.files['tools/stcxx-driver/stcxx.exe'] = b'driver'
        self.write(self.platform, 'arduino-stc51-0.0.6', self.files)
        with (self.root / 'stc-cli.zip').open('ab') as stream:
            stream.write(b'tampered')
        with self.assertRaisesRegex(ValueError, 'differs from manifest'):
            self.create()

    def test_unlisted_payload_and_traversal_are_rejected(self):
        with zipfile.ZipFile(self.platform, 'a') as archive:
            archive.writestr('arduino-stc51-0.0.6/unlisted.exe', b'extra')
        with self.assertRaisesRegex(ValueError, 'manifest mismatch'):
            self.create()
        self.files['../escape'] = b'escape'
        self.write(self.platform, 'arduino-stc51-0.0.6', self.files)
        with self.assertRaisesRegex(ValueError, 'Unsafe ZIP member'):
            self.create()


if __name__ == '__main__':
    unittest.main()
