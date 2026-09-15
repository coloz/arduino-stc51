"""The Mac launch gate pins dependencies and headers as well as executables."""
import importlib.util
import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

HELPER = Path(__file__).resolve().parents[1] / 'tools/cpp-cli/verify-macos-frontend.py'
spec = importlib.util.spec_from_file_location('macos_frontend_gate', HELPER)
gate = importlib.util.module_from_spec(spec); spec.loader.exec_module(gate)


class MacFrontendManifestTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.root = Path(temp.name) / 'frontend with spaces'; self.root.mkdir()
        self.selected = {}
        for name in ('clang', 'llvm-link', 'opt', 'llvm-dis', 'llvm-cbe'):
            path = self.root / 'bin' / name; path.parent.mkdir(exist_ok=True)
            path.write_bytes(b'tool ' + name.encode()); path.chmod(0o755)
            self.selected[name] = path
        self.library = self.root / 'lib/libzstd.1.5.7.dylib'
        self.library.parent.mkdir(); self.library.write_bytes(b'private dependency')
        self.header = self.root / 'lib/clang/20/include/stddef.h'
        self.header.parent.mkdir(parents=True); self.header.write_bytes(b'resource header')
        self.manifest = self.root / 'MANIFEST.sha256'
        self.manifest.write_text(''.join(gate.sha256(p) + '  ' + p.relative_to(self.root).as_posix() + '\n'
                                        for p in sorted(self.root.rglob('*')) if p.is_file()))
        self.digest = gate.sha256(self.manifest)

    def verify(self, **kwargs):
        return gate.verify(self.root, self.digest, self.selected, kwargs.get('env', {}))

    def test_complete_bundle_and_changed_dependency_or_header(self):
        self.assertEqual(self.verify(), 7)
        for path in (self.library, self.header):
            payload = path.read_bytes(); path.write_bytes(payload + b'changed')
            with self.assertRaisesRegex(ValueError, 'package differs'): self.verify()
            path.write_bytes(payload)
        self.library.unlink()
        with self.assertRaisesRegex(ValueError, 'package differs'): self.verify()

    def test_added_file_or_modified_manifest(self):
        extra = self.root / 'lib/extra.dylib'; extra.write_bytes(b'extra')
        with self.assertRaisesRegex(ValueError, 'package differs'): self.verify()
        extra.unlink(); self.manifest.write_text(self.manifest.read_text() + '\n')
        with self.assertRaisesRegex(ValueError, 'manifest SHA-256 mismatch'): self.verify()

    def test_external_tool_and_loader_override(self):
        other = self.root.parent / 'clang'; other.write_bytes(self.selected['clang'].read_bytes()); other.chmod(0o755)
        self.selected['clang'] = other
        with self.assertRaisesRegex(ValueError, 'escapes pinned package'): self.verify()
        self.selected['clang'] = self.root / 'bin/clang'
        for variable in ('DYLD_LIBRARY_PATH', 'DYLD_INSERT_LIBRARIES', 'LD_PRELOAD'):
            with self.assertRaisesRegex(ValueError, 'remove DYLD_'): self.verify(env={variable: '/outside'})

    @unittest.skipIf(os.name == 'nt', 'symlink privilege is not assumed on Windows')
    def test_same_content_symlink_is_refused(self):
        external = self.root.parent / 'library'; external.write_bytes(self.library.read_bytes())
        self.library.unlink(); self.library.symlink_to(external)
        with self.assertRaisesRegex(ValueError, 'symlink in pinned'): self.verify()

    @unittest.skipIf(os.name == 'nt', 'native POSIX host gate')
    def test_host_lock_selection_and_wrong_host_refusal(self):
        lock = self.root.parent / 'lock.json'
        argv = ['verify', '--lock', str(lock), '--root', str(self.root)]
        for name, path in self.selected.items():
            argv += ['--tool', name, str(path)]
        for host, platform, machine, key in (
                ('linux-x86_64', 'linux', 'x86_64', 'linux_frontend'),
                ('darwin-arm64', 'darwin', 'arm64', 'macos_frontend')):
            lock.write_text(json.dumps({'host': host, key: {'manifest_sha256': self.digest}}))
            with patch.object(gate.sys, 'argv', argv), patch.object(gate.sys, 'platform', platform), \
                    patch.object(gate.os, 'uname') as uname, patch.dict(gate.os.environ, {}, clear=True), \
                    contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                uname.return_value.machine = machine
                self.assertEqual(gate.main(), 0)
                uname.return_value.machine = 'wrong-architecture'
                self.assertEqual(gate.main(), 2)


if __name__ == '__main__': unittest.main()
