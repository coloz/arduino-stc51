"""Exercise unified Arduino dependency bindings and POSIX tool discovery."""
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('candidate', ROOT / 'scripts/create-macos-candidate-index.py')
candidate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(candidate)


class CandidateTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='stcxx candidate ')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.toolchain = self.root / 'toolchain.tar.bz2'
        self.toolchain.write_bytes(b'locked unified toolchain fixture')
        self.uploader = self.root / 'uploader.zip'
        self.uploader.write_bytes(b'native uploader fixture')
        (self.root / 'tools').mkdir()
        manifest = {'tools': [{'id': 'stc-cli', 'version': '0.1.0-stc.1', 'systems': [{
            'host': 'x86_64-mingw32', 'archiveFileName': self.uploader.name,
            'size': self.uploader.stat().st_size, 'sha256': candidate.sha256(self.uploader)}]}]}
        (self.root / 'tools/toolchain-manifest.json').write_text(json.dumps(manifest))
        self.binding = {'packager': 'stc', 'name': 'stcxx-toolchain', 'version': '0.1.0'}
        self.platform = self.root / 'arduino-stc51-0.0.5.tar.bz2'
        self.sdk()

    def sdk(self, host='windows-x86_64'):
        lock = {'host': host, 'arduino_toolchain': self.binding,
                'toolchain_package': {'archive_sha256': candidate.sha256(self.toolchain)}}
        files = {'platform.txt': 'version=0.0.5\ncompiler.ar.path.windows={runtime.tools.stcxx-toolchain.path}/sdcc/bin\n'
                 'compiler.shell.cmd.windows=powershell.exe\n'
                 'compiler.wrapper.compile.windows="{compiler.wrapper.path}/stc-windows.ps1" compile\n',
                 'tools/wrapper/stc-windows.ps1': '# fixture\n',
                 'tools/cpp-cli/toolchain-lock.windows-x86_64.json': json.dumps(lock),
                 'tools/variants/devices.json': json.dumps({'devices': [{'id': 'board', 'model': 'Board', 'target': 'mcs251'}]})}
        with tarfile.open(self.platform, 'w:bz2') as archive:
            for name, value in files.items():
                payload = value.encode()
                entry = tarfile.TarInfo('arduino-stc51-0.0.5/' + name)
                entry.size = len(payload)
                archive.addfile(entry, io.BytesIO(payload))

    def create(self):
        with patch.object(candidate, '__file__', str(self.root / 'scripts/candidate.py')):
            return candidate.create(self.platform, self.toolchain, 'http://127.0.0.1:8000', self.root / 'index.json',
                                    'x86_64-mingw32', uploader=self.uploader)

    def test_installs_one_compiler_dependency(self):
        self.create()
        package = json.loads((self.root / 'index.json').read_text())['packages'][0]
        self.assertEqual(package['platforms'][0]['toolsDependencies'],
                         [self.binding, {'packager': 'stc', 'name': 'stc-cli', 'version': '0.1.0-stc.1'}])
        self.assertEqual([t['name'] for t in package['tools']], ['stcxx-toolchain', 'stc-cli'])

    def test_modified_bundle_is_rejected(self):
        self.toolchain.write_bytes(b'modified')
        with self.assertRaisesRegex(ValueError, 'Toolchain archive differs'):
            self.create()
        self.assertFalse((self.root / 'index.json').exists())

    def test_wrong_host_and_old_binding_are_rejected(self):
        self.sdk('darwin-arm64')
        with self.assertRaisesRegex(ValueError, 'SDK lock is not'):
            self.create()
        self.binding['name'] = 'stcxx-frontend'
        self.sdk()
        with self.assertRaisesRegex(ValueError, 'exact Arduino toolchain'):
            self.create()


@unittest.skipUnless(os.name == 'posix' and shutil.which('bash'), 'requires a POSIX shell')
class DiscoveryTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='stcxx paths ')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.platform = self.root / 'data/packages/stc/hardware/mcs251/0.0.5'
        self.platform.mkdir(parents=True)
        self.package = self.root / 'data/packages/stc/tools/stcxx-toolchain/0.1.0'
        for name in ('frontend/bin', 'sdcc/bin', 'sdcc/include', 'sdcc/lib'):
            (self.package / name).mkdir(parents=True)
        (self.package / 'sdcc/bin/sdcc').write_text('#!/bin/sh\nexit 0\n')
        (self.package / 'sdcc/bin/sdcc').chmod(0o755)
        self.lock = self.root / 'lock.json'
        self.lock.write_text(json.dumps({'arduino_toolchain': {
            'packager': 'stc', 'name': 'stcxx-toolchain', 'version': '0.1.0'}}))
        self.env = {k: v for k, v in os.environ.items() if not k.startswith('STCXX_')}

    def run_paths(self, extra):
        script = '. "$1"; stcxx_resolve_tools /unused "$2" "$3" || exit $?; printf "%s\n" "$clang" "$sdcc" "$sdcc_include_root"'
        return subprocess.run(['bash', '-c', script, 'test', str(ROOT / 'tools/cpp-cli/toolchain-paths.sh'),
                               str(self.platform), str(self.lock)], env={**self.env, **extra}, capture_output=True, text=True)

    def test_arduino_discovers_the_exact_unified_version(self):
        result = self.run_paths({'STCXX_ARDUINO_SDCC': str(self.package / 'sdcc/bin/sdcc')})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), [str(self.package / name) for name in
                                                      ('frontend/bin/clang', 'sdcc/bin/sdcc', 'sdcc/include')])

    def test_source_checkout_accepts_one_bundle_override(self):
        self.platform = self.root / 'source checkout'
        result = self.run_paths({'STCXX_TOOLS_ROOT': str(self.package)})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines()[0], str(self.package / 'frontend/bin/clang'))
        self.assertEqual(result.stdout.splitlines()[1], str(self.package / 'sdcc/bin/sdcc'))

    def test_missing_locked_version_does_not_select_another_version(self):
        lock = json.loads(self.lock.read_text())
        lock['arduino_toolchain']['version'] = '9.9.9'
        self.lock.write_text(json.dumps(lock))
        result = self.run_paths({'STCXX_ARDUINO_SDCC': str(self.package / 'sdcc/bin/sdcc')})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('missing locked Arduino toolchain dependency', result.stderr)


if __name__ == '__main__':
    unittest.main()
