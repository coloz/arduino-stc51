import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('macos_index', Path(__file__).resolve().parents[1] / 'scripts/create-macos-candidate-index.py')
index = importlib.util.module_from_spec(spec)
spec.loader.exec_module(index)


class MacCandidateIndexTests(unittest.TestCase):
    host = 'arm64-apple-darwin'
    lock_host = 'darwin-arm64'
    lock_file = 'toolchain-lock.macos-arm64.json'
    sdcc_key = 'native_package_archive_sha256'
    frontend_key = 'macos_frontend'

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.sdcc = self.root / 'sdcc.tar.bz2'
        self.frontend = self.root / 'frontend.tar.bz2'
        self.sdcc.write_bytes(b'locked SDCC archive fixture')
        self.frontend.write_bytes(b'locked frontend archive fixture')
        self.platform = self.root / 'arduino-stc51-0.0.3.tar.bz2'
        self.output = self.root / 'package_candidate_index.json'
        self.lock = {'host': self.lock_host,
                     'arduino_frontend': {'packager': 'arduino-stc51', 'name': 'stcxx-frontend', 'version': '20.1.8-stc.1'},
                     'tools': {'sdcc': {self.sdcc_key: index.sha256(self.sdcc)}},
                     self.frontend_key: {'archive_sha256': index.sha256(self.frontend)}}
        self.write_sdk()

    def write_sdk(self, extra=None):
        files = {'platform.txt': 'name=arduino-stc51\nversion=0.0.3\n',
                 'tools/cpp-cli/' + self.lock_file: json.dumps(self.lock),
                 'tools/variants/devices.json': json.dumps({'devices': [{'id': 'board', 'model': 'STC32', 'target': 'mcs251'}]})}
        if extra:
            files.update(extra)
        with tarfile.open(self.platform, 'w:bz2') as archive:
            for name, text in files.items():
                content = text.encode()
                member = tarfile.TarInfo('arduino-stc51-0.0.3/' + name)
                member.size = len(content)
                archive.addfile(member, io.BytesIO(content))

    def create(self, url='http://127.0.0.1:8123'):
        return index.create(self.platform, self.sdcc, self.frontend, '4.6.0-stc.8', url, self.output, self.host)

    def test_index_binds_platform_and_both_exact_tool_archives(self):
        report = self.create()
        self.assertFalse(report['production_qualified'])
        package = json.loads(self.output.read_text())['packages'][0]
        platform = package['platforms'][0]
        self.assertEqual(platform['toolsDependencies'][1], self.lock['arduino_frontend'])
        self.assertEqual(platform['checksum'], 'SHA-256:' + index.sha256(self.platform))
        for tool, archive in zip(package['tools'], [self.sdcc, self.frontend]):
            self.assertEqual(tool['systems'][0]['host'], self.host)
            self.assertEqual(tool['systems'][0]['checksum'], 'SHA-256:' + index.sha256(archive))

    def test_wrong_tool_archives_are_rejected_before_index_creation(self):
        for tool in (self.sdcc, self.frontend):
            with self.subTest(tool=tool):
                previous = tool.read_bytes()
                tool.write_bytes(b'wrong candidate')
                with self.assertRaisesRegex(ValueError, 'archive differs from SDK lock'):
                    self.create()
                self.assertFalse(self.output.exists())
                tool.write_bytes(previous)

    def test_unbound_dependency_and_wrong_sdk_version_are_rejected(self):
        del self.lock['arduino_frontend']
        self.write_sdk()
        with self.assertRaisesRegex(ValueError, 'exact Arduino frontend'):
            self.create()
        self.write_sdk({'platform.txt': 'version=0.0.4\n'})
        with self.assertRaisesRegex(ValueError, 'root/version differ'):
            self.create()
        self.assertFalse(self.output.exists())

    def test_unsafe_sdk_path_network_url_and_existing_output_are_refused(self):
        self.write_sdk({'../outside': 'unsafe'})
        with self.assertRaisesRegex(ValueError, 'Unsafe SDK'):
            self.create()
        self.write_sdk()
        with self.assertRaisesRegex(ValueError, 'HTTPS or a loopback'):
            self.create('http://example.com/assets')
        self.output.write_bytes(b'keep existing index')
        with self.assertRaisesRegex(ValueError, 'already exists'):
            self.create()
        self.assertEqual(self.output.read_bytes(), b'keep existing index')


class LinuxCandidateIndexTests(MacCandidateIndexTests):
    host = 'x86_64-pc-linux-gnu'
    lock_host = 'linux-x86_64'
    lock_file = 'toolchain-lock.json'
    sdcc_key = 'distribution_archive_sha256'
    frontend_key = 'linux_frontend'

    def test_development_runtime_lock_cannot_produce_distribution_index(self):
        self.lock['host'] = 'linux-x86_64-development'
        # A valid sibling distribution lock is insufficient: the runtime lock
        # at the standard path must have been selected during packaging.
        self.write_sdk({'tools/cpp-cli/toolchain-lock.linux-x86_64.json':
                        json.dumps({**self.lock, 'host': 'linux-x86_64'})})
        with self.assertRaisesRegex(ValueError, 'SDK lock is not for'):
            self.create()
        self.assertFalse(self.output.exists())


class WindowsCandidateIndexTests(MacCandidateIndexTests):
    host = 'x86_64-mingw32'
    lock_host = 'linux-x86_64'
    lock_file = 'toolchain-lock.json'
    sdcc_key = 'windows_package_archive_sha256'
    frontend_key = 'linux_frontend'

    def setUp(self):
        super().setUp()
        self.wsl = self.root / 'wsl-sdcc.tar.bz2'
        self.host_tools = self.root / 'host-tools.tar.bz2'
        self.wsl.write_bytes(b'Linux backend archive')
        self.host_tools.write_bytes(b'Windows BusyBox archive')
        self.lock['tools']['sdcc']['distribution_archive_sha256'] = index.sha256(self.wsl)
        self.lock['arduino_wsl_sdcc'] = {'packager': 'arduino-stc51', 'name': 'sdcc-mcs251-wsl', 'version': '4.6.0-stc.7'}
        self.lock['arduino_host_tools'] = {'packager': 'arduino-stc51', 'name': 'STCHostTools', 'version': '2026.07.10'}
        self.lock['windows_host_tools'] = {'archive_sha256': index.sha256(self.host_tools)}
        self.write_sdk()

    def write_sdk(self, extra=None):
        extra = dict(extra or {})
        extra['platform.txt'] = extra.get('platform.txt', 'name=arduino-stc51\nversion=0.0.3\n') + \
            'compiler.ar.path.windows={runtime.tools.sdcc-mcs251.path}/bin\n'
        super().write_sdk(extra)

    def create(self, url='http://127.0.0.1:8123'):
        return index.create(self.platform, self.sdcc, self.frontend, '4.6.0-stc.7', url, self.output, self.host,
                            wsl_sdcc=self.wsl, host_tools=self.host_tools)

    def test_all_windows_dependencies_are_bound_and_extra_archives_checked(self):
        self.create()
        package = json.loads(self.output.read_text())['packages'][0]
        self.assertEqual([d['name'] for d in package['platforms'][0]['toolsDependencies']],
                         ['sdcc-mcs251', 'stcxx-frontend', 'sdcc-mcs251-wsl', 'STCHostTools'])
        self.output.unlink()
        for archive in (self.wsl, self.host_tools):
            original = archive.read_bytes()
            archive.write_bytes(b'changed dependency')
            with self.assertRaisesRegex(ValueError, 'archive differs from SDK lock'):
                self.create()
            self.assertFalse(self.output.exists())
            archive.write_bytes(original)

    def test_windows_requires_extra_archives(self):
        with self.assertRaisesRegex(ValueError, 'Windows requires'):
            index.create(self.platform, self.sdcc, self.frontend, '4.6.0-stc.7', 'http://127.0.0.1:8123', self.output, self.host)


if __name__ == '__main__':
    unittest.main()
