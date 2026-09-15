"""Detect the actual stale macOS source-pin regression without building on macOS."""
import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('build_inputs', ROOT/'scripts/check-toolchain-build-inputs.py')
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)


class ToolchainBuildInputs(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        for name in ('tools/cpp-cli/toolchain-lock.json', 'tools/toolchain-manifest.json',
                     'tools/cpp-cli/toolchain-lock.linux-x86_64.json',
                     'tools/cpp-cli/toolchain-lock.macos-arm64.json',
                     'tools/toolchain-patches/sdcc-mcs251-arduino-cpp.patch',
                     'scripts/build-linux-toolchain.sh', 'scripts/build-macos-toolchain.sh'):
            target = self.root/name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT/name, target)
        self.mac = self.root/'scripts/build-macos-toolchain.sh'

    def test_stale_distribution_lock_is_rejected(self):
        for name in ('toolchain-lock.linux-x86_64.json', 'toolchain-lock.macos-arm64.json'):
            path = self.root/'tools/cpp-cli'/name
            before = path.read_bytes()
            value = json.loads(before)
            value['tools']['sdcc']['patch_sha256'] = '0' * 64
            path.write_text(json.dumps(value), encoding='utf-8')
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, 'distribution compiler sources differ'):
                gate.check(self.root)
            path.write_bytes(before)

    def compiler_fixture(self):
        compiler = self.root/'compiler'
        files = {'patch': b'patch', 'build': b'build', 'prepare': b'prepare',
                 'check': b'checker', 'out/libexec/sdcc': b'driver', 'out/bin/sdcc': b'wrapper',
                 'out/MANIFEST.sha256': b'manifest'}
        for name, data in files.items():
            path = compiler/name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        reproduction = {key: name for key, name in (
            ('build_script', 'build'), ('prepare_script', 'prepare'), ('source_check_script', 'check'))}
        reproduction.update({key+'_sha256': gate.digest(compiler/name) for key, name in list(reproduction.items())})
        source = {'sdcc': {'base_commit': 'base', 'patch': 'patch', 'patch_sha256': gate.digest(compiler/'patch'),
                           'patched_source_blobs': {'src/mcs251/gen.c': 'generator'},
                           'reference_elf_sha256': gate.digest(compiler/'out/libexec/sdcc')},
                  'clang': {'reproduction_inputs': reproduction}}
        source_path = compiler/'arduino/toolchain-lock.json'
        source_path.parent.mkdir()
        source_path.write_text(json.dumps(source), encoding='utf-8')
        shutil.copyfile(source_path, compiler/'out/toolchain-lock.json')
        sdk = {'upstream_base_commit': 'base', 'patch_sha256': source['sdcc']['patch_sha256'],
               'published_out_lock_sha256': gate.digest(source_path),
               'published_out_manifest_sha256': gate.digest(compiler/'out/MANIFEST.sha256'),
               'elf_sha256': source['sdcc']['reference_elf_sha256'], 'sha256': gate.digest(compiler/'out/bin/sdcc')}
        core = self.root/'cores/STC/cpp/core-manifest.json'
        core.parent.mkdir(parents=True)
        core.write_text(json.dumps({'publication': {k: v for k, v in sdk.items() if k.startswith('published_')}}), encoding='utf-8')
        return compiler, sdk, {'builder': {'PATCHED_GEN_BLOB': 'generator'}}

    def test_compiler_publication_and_stale_checker_driver_or_core(self):
        compiler, sdk, builders = self.compiler_fixture()
        gate.check_compiler(self.root, compiler, sdk, builders)
        for name in ('check', 'out/libexec/sdcc', 'out/toolchain-lock.json', 'out/MANIFEST.sha256'):
            path = compiler/name
            before = path.read_bytes()
            path.write_bytes(before+b'changed')
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, 'differs from lock'):
                gate.check_compiler(self.root, compiler, sdk, builders)
            path.write_bytes(before)
        core = self.root/'cores/STC/cpp/core-manifest.json'
        core.write_text('{}', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'core/SDK publication bindings differ'):
            gate.check_compiler(self.root, compiler, sdk, builders)

    def test_maintained_builders_use_locked_sources(self):
        report = gate.check(ROOT)
        self.assertEqual(report['status'], 'PASS')
        self.assertFalse(report['production_qualified'])

    def test_actual_old_macos_patch_pin_is_rejected(self):
        source = self.mac.read_text(encoding='utf-8')
        current = gate.literal(source, 'PATCH_SHA256')
        self.mac.write_text(source.replace(current, '341606fa0a60f4306e466b2065a9b8b02a835efb12c0634ba07317424ebcf8b1'), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'stale PATCH_SHA256'):
            gate.check(self.root)

    def test_old_generator_cannot_hide_behind_current_patch_pin(self):
        source = self.mac.read_text(encoding='utf-8')
        self.mac.write_text(source.replace(gate.literal(source, 'PATCHED_GEN_BLOB'),
                                          '2c0a10a4826dc873ed325a40a164ab2601b17362'), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'generator identities differ'):
            gate.check(self.root)

    def test_changed_patch_is_rejected_even_if_both_builders_match(self):
        patch = self.root/'tools/toolchain-patches/sdcc-mcs251-arduino-cpp.patch'
        with patch.open('ab') as stream:
            stream.write(b'changed\n')
        with self.assertRaisesRegex(ValueError, r'differs from the C\+\+ toolchain lock'):
            gate.check(self.root)

    def test_upstream_lock_drift_is_rejected(self):
        path = self.root/'tools/toolchain-manifest.json'
        value = json.loads(path.read_text(encoding='utf-8'))
        next(tool for tool in value['tools'] if tool['id']=='sdcc-mcs251')['sourceCommit'] = '0'*40
        path.write_text(json.dumps(value), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'source commits differ'):
            gate.check(self.root)

    def test_later_override_or_shell_expression_is_rejected(self):
        source = self.mac.read_text(encoding='utf-8')
        for changed in (source+'\nCOMMIT=overridden\n',
                        source.replace('COMMIT='+gate.literal(source, 'COMMIT'), 'COMMIT=$(git rev-parse HEAD)')):
            with self.subTest(source=changed[-40:]):
                self.mac.write_text(changed, encoding='utf-8')
                with self.assertRaisesRegex(ValueError, 'literal'):
                    gate.check(self.root)


if __name__ == '__main__':
    unittest.main()
