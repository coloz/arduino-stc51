"""Installed frontend selection must use the locked Arduino dependency version."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

HELPER = Path(__file__).resolve().parents[1] / 'tools/cpp-cli/toolchain-paths.sh'


@unittest.skipUnless(sys.platform.startswith('linux') or sys.platform == 'darwin', 'native POSIX tool lookup')
class InstalledFrontendTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve() / 'isolated data'
        self.packages = self.root / 'packages'
        self.sdk = self.packages / 'arduino-stc51/hardware/mcs251/0.0.3'
        self.sdk.mkdir(parents=True)
        self.binding = {'packager': 'arduino-stc51', 'name': 'stcxx-frontend', 'version': '20.1.8-stc.1'}
        self.lock = self.root / 'lock.json'
        self.lock.write_text(json.dumps({'arduino_frontend': self.binding}))
        self.sdcc = self.root / 'sdcc/bin/sdcc'
        self.sdcc.parent.mkdir(parents=True)
        self.sdcc.write_text('fixture')
        for name in ('include', 'lib'):
            (self.sdcc.parents[1] / name).mkdir()
        self.env = {key: value for key, value in os.environ.items() if not key.startswith('STCXX_')}

    def install(self, version, packager='arduino-stc51'):
        target = self.packages / packager / 'tools/stcxx-frontend' / version
        (target / 'bin').mkdir(parents=True)
        return target

    def resolve(self, **overrides):
        env = dict(self.env, STCXX_ARDUINO_SDCC=str(self.sdcc), **overrides)
        script = '. "$1"; stcxx_resolve_tools /absent "$2" "$3" || exit $?; '
        script += 'printf "%s\\0" "${STCXX_CPP_TOOLS_ROOT:-}" "$clang" "$llvm_link" "$opt" "$llvm_dis" "$llvm_cbe"'
        return subprocess.run(['sh', '-eu', '-c', script, 'test', str(HELPER), str(self.sdk), str(self.lock)],
                              env=env, capture_output=True, timeout=10)

    def test_exact_version_selected_with_other_versions_installed(self):
        selected = self.install(self.binding['version'])
        self.install('99.0.0')
        self.install('1.0.0')
        result = self.resolve()
        self.assertEqual(result.returncode, 0, result.stderr.decode())
        self.assertEqual(result.stdout.split(b'\0')[:-1], [str(selected).encode()] +
                         [str(selected / 'bin' / name).encode() for name in ('clang', 'llvm-link', 'opt', 'llvm-dis', 'llvm-cbe')])

    def test_missing_exact_version_fails_without_fallback(self):
        self.install('99.0.0')
        result = self.resolve()
        self.assertEqual(result.returncode, 2)
        self.assertIn(b'missing locked Arduino frontend', result.stderr)
        self.assertIn(self.binding['version'].encode(), result.stderr)
        self.assertEqual(result.stdout, b'')

    def test_explicit_root_takes_precedence(self):
        explicit = self.root / 'external frontend'
        result = self.resolve(STCXX_CPP_TOOLS_ROOT=str(explicit))
        self.assertEqual(result.returncode, 0, result.stderr.decode())
        self.assertEqual(result.stdout.split(b'\0')[0], str(explicit).encode())

    def test_dependency_packager_is_respected(self):
        self.binding['packager'] = 'separate-vendor'
        self.lock.write_text(json.dumps({'arduino_frontend': self.binding}))
        selected = self.install(self.binding['version'], 'separate-vendor')
        result = self.resolve()
        self.assertEqual(result.returncode, 0, result.stderr.decode())
        self.assertEqual(result.stdout.split(b'\0')[0], str(selected).encode())

    def test_malformed_dependency_is_rejected(self):
        for binding in ({**self.binding, 'version': '../escape'}, [], {'name': 'only-name'},
                        {**self.binding, 'packager': '/absolute'}, {**self.binding, 'version': 1}):
            with self.subTest(binding=binding):
                self.lock.write_text(json.dumps({'arduino_frontend': binding}))
                result = self.resolve()
                self.assertEqual(result.returncode, 2)
                self.assertIn(b'invalid locked Arduino', result.stderr)
                self.assertEqual(result.stdout, b'')

    def test_development_checkout_has_actionable_diagnostic(self):
        self.sdk = self.root / 'development checkout'
        self.sdk.mkdir()
        result = self.resolve()
        self.assertEqual(result.returncode, 2)
        self.assertIn(b'set STCXX_CPP_TOOLS_ROOT', result.stderr)

    def test_legacy_lock_preserves_explicit_development_tools(self):
        self.lock.write_text('{}')
        result = self.resolve(STCXX_CLANG='/developer/clang')
        self.assertEqual(result.returncode, 0, result.stderr.decode())
        self.assertEqual(result.stdout.split(b'\0')[1], b'/developer/clang')

    def test_windows_route_selects_locked_wsl_backend_and_native_keeps_arduino_sdcc(self):
        self.install(self.binding['version'])
        binding = {'packager': 'arduino-stc51', 'name': 'sdcc-mcs251-wsl', 'version': '4.6.0-stc.7'}
        self.lock.write_text(json.dumps({'arduino_frontend': self.binding, 'arduino_wsl_sdcc': binding}))
        backend = self.packages / 'arduino-stc51/tools/sdcc-mcs251-wsl' / binding['version']
        for name in ('bin', 'include', 'lib'):
            (backend / name).mkdir(parents=True)
        (backend / 'bin/sdcc').write_text('Linux backend fixture')
        script = '. "$1"; stcxx_resolve_tools /absent "$2" "$3" || exit $?; printf "%s" "$sdcc"'
        def run(**overrides):
            return subprocess.run(['sh', '-eu', '-c', script, 'test', str(HELPER), str(self.sdk), str(self.lock)],
                                  env={**self.env, 'STCXX_ARDUINO_SDCC': str(self.sdcc), **overrides},
                                  capture_output=True, text=True, timeout=10)
        native = run()
        self.assertEqual(native.returncode, 0, native.stderr)
        self.assertEqual(native.stdout, str(self.sdcc))
        windows = run(STCXX_WINDOWS_HOST='1')
        self.assertEqual(windows.returncode, 0, windows.stderr)
        self.assertEqual(windows.stdout, str(backend / 'bin/sdcc'))
        explicit = run(STCXX_WINDOWS_HOST='1', STCXX_SDCC=str(self.sdcc))
        self.assertEqual(explicit.returncode, 0, explicit.stderr)
        self.assertEqual(explicit.stdout, str(self.sdcc))
        binding['version'] = 'missing-version'
        self.lock.write_text(json.dumps({'arduino_frontend': self.binding, 'arduino_wsl_sdcc': binding}))
        missing = run(STCXX_WINDOWS_HOST='1')
        self.assertEqual(missing.returncode, 2)
        self.assertIn('missing locked Arduino WSL SDCC', missing.stderr)
        self.assertEqual(missing.stdout, '')


if __name__ == '__main__':
    unittest.main()
