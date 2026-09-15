"""Resolve selected tools after relocation and reject unresolved implementations."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import shutil
import sys
import tempfile
import unittest

HELPER = Path(__file__).resolve().parents[1] / 'tools/cpp-cli/toolchain-paths.sh'


@unittest.skipUnless(sys.platform.startswith('linux'), 'Linux toolchain layouts')
class CppToolchainPathsTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name) / 'tools with spaces'
        self.root.mkdir()
        self.env = {key: value for key, value in os.environ.items() if not key.startswith('STCXX_')}

    def file(self, path, data=b'fixture', mode=0o755):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data); path.chmod(mode)
        return path

    def layout(self, name, kind):
        root = self.root / name
        sdcc = self.file(root / 'bin/sdcc')
        if kind == 'published':
            elf = self.file(root / 'libexec/sdcc')
            include, runtime = root / 'share/sdcc/include', root / 'share/sdcc/lib'
        elif kind == 'distribution':
            elf = sdcc
            include, runtime = root / 'include', root / 'lib'
        else:
            elf = self.file(root / 'src/sdcc')
            sdcc.unlink(); sdcc.symlink_to('../src/sdcc')
            include, runtime = root.parent / 'source/device/include', root / 'device/lib/build'
        include.mkdir(parents=True, exist_ok=True); runtime.mkdir(parents=True, exist_ok=True)
        return sdcc, elf, include, runtime

    def resolve(self, **overrides):
        env = dict(self.env, **{key: str(value) for key, value in overrides.items()})
        script = '. "$1"; stcxx_resolve_tools /absent-default || exit $?; '
        script += 'printf "%s\\0" "$sdcc" "$sdcc_elf" "$sdcc_include_root" "$sdcc_runtime_root" '
        script += '"$clang" "$llvm_link" "$opt" "$llvm_dis" "$llvm_cbe"'
        return subprocess.run(['sh', '-eu', '-c', script, 'test', str(HELPER)],
                              env=env, capture_output=True, timeout=10)

    def test_all_layouts_through_directory_and_file_symlinks(self):
        for kind in ('published', 'distribution', 'raw'):
            sdcc, elf, include, runtime = self.layout(kind, kind)
            directory = self.root / (kind + '-directory'); directory.symlink_to(sdcc.parent)
            file_link = self.root / (kind + '-file'); file_link.symlink_to(directory / sdcc.name)
            for entry in (sdcc, directory / sdcc.name, file_link):
                with self.subTest(kind=kind, entry=entry):
                    result = self.resolve(STCXX_SDCC=entry)
                    self.assertEqual(result.returncode, 0, result.stderr.decode())
                    self.assertEqual(result.stdout.split(b'\0')[:4],
                                     [str(p.resolve()).encode() for p in (sdcc, elf, include, runtime)])

    def test_selected_arduino_compiler_and_explicit_overrides(self):
        selected = self.layout('selected', 'distribution')[0]
        explicit = self.layout('developer/out', 'published')[0]
        cases = [({'STCXX_ARDUINO_SDCC': selected}, selected),
                 ({'STCXX_ARDUINO_SDCC': selected, 'STCXX_TOOLCHAIN_ROOT': explicit.parents[2]}, explicit),
                 ({'STCXX_ARDUINO_SDCC': selected, 'STCXX_SDCC': explicit}, explicit)]
        for env, expected in cases:
            with self.subTest(env=env):
                result = self.resolve(**env)
                self.assertEqual(result.returncode, 0, result.stderr.decode())
                self.assertEqual(result.stdout.split(b'\0')[0], str(expected).encode())

    def test_explicit_frontend_root_does_not_fall_back_to_host_tools(self):
        sdcc = self.layout('sdk', 'distribution')[0]
        frontend = self.root / 'frontend'
        override = self.root / 'custom clang'
        result = self.resolve(STCXX_SDCC=sdcc, STCXX_CPP_TOOLS_ROOT=frontend, STCXX_CLANG=override)
        self.assertEqual(result.returncode, 0, result.stderr.decode())
        self.assertEqual(result.stdout.split(b'\0')[4:-1], [str(override).encode()] +
                         [str(frontend / 'bin' / name).encode() for name in ('llvm-link', 'opt', 'llvm-dis', 'llvm-cbe')])

    def test_missing_or_unknown_selected_compiler_fails(self):
        for path in (self.root / 'missing/sdcc', self.file(self.root / 'unknown/bin/sdcc')):
            with self.subTest(path=path):
                result = self.resolve(STCXX_ARDUINO_SDCC=path)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(result.stdout, b'')

    def test_library_resolution_keeps_spaces_and_rejects_missing_or_ambiguous(self):
        library = self.file(self.root / 'shared libraries/libLLVM.so.20.1', mode=0o644)
        fake_bin = self.root / 'fake-bin'
        self.file(fake_bin / 'ldd', b'#!/bin/sh\nprintf "%s\\n" "$LDD_OUTPUT"\nexit "$LDD_EXIT"\n')
        script = '. "$1"; stcxx_resolve_library "$2" libLLVM.so.20.1'
        valid = f'\tlibLLVM.so.20.1 => {library} (0x0123456789ab)'
        for listing, code, success in [(valid, 0, True), ('libLLVM.so.20.1 => not found', 0, False),
                                       ('libLLVM.so.21.1 => /absent (0x123)', 0, False),
                                       (valid + '\n' + valid, 0, False), (valid, 1, False)]:
            with self.subTest(listing=listing, code=code):
                env = dict(self.env, PATH=str(fake_bin) + ':' + self.env['PATH'], LDD_OUTPUT=listing, LDD_EXIT=str(code))
                result = subprocess.run(['sh', '-eu', '-c', script, 'test', str(HELPER), '/tool with spaces'],
                                        env=env, capture_output=True, timeout=10)
                self.assertEqual(result.returncode == 0, success, result.stderr.decode())
                self.assertEqual(result.stdout, (str(library) + '\n').encode() if success else b'')

    @unittest.skipUnless(shutil.which('gcc'), 'real ELF dependency regression requires GCC')
    def test_inventory_rejects_changed_shared_implementation_with_unchanged_tools(self):
        frontend = self.root / 'frontend'
        libraries = frontend / 'lib'; libraries.mkdir(parents=True)
        sources = self.root / 'sources'; sources.mkdir()
        for filename, function in [('libLLVM.so.20.1', 'llvm_fixture'), ('libclang-cpp.so.20.1', 'clang_fixture')]:
            source = sources / (function + '.c'); source.write_text('int ' + function + '(void) { return 0; }\n')
            subprocess.run(['gcc', '-shared', '-fPIC', '-Wl,-soname,' + filename, str(source), '-o', str(libraries / filename)],
                           check=True, capture_output=True, timeout=30)
        main = sources / 'main.c'
        main.write_text('int llvm_fixture(void); int clang_fixture(void);\nint main(void) { return llvm_fixture() + clang_fixture(); }\n')
        executable = frontend / 'bin/clang'; executable.parent.mkdir()
        subprocess.run(['gcc', str(main), '-L' + str(libraries), '-l:libLLVM.so.20.1', '-l:libclang-cpp.so.20.1',
                        '-Wl,-rpath,$ORIGIN/../lib', '-o', str(executable)], check=True, capture_output=True, timeout=30)
        for name in ('llvm-link', 'opt', 'llvm-dis', 'llvm-cbe'):
            (executable.parent / name).symlink_to('clang')
        sdcc = self.layout('sdk', 'distribution')[0]
        for name in ('sdar', 'sdas251', 'sdld', 'sdldmcs251', 'sdcpp'):
            (sdcc.parent / name).symlink_to('sdcc')
        sha = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
        lock = {'pipeline_helpers': {'toolchain_paths': {'sha256': sha(HELPER)}}, 'tools': {
            'clang': {'sha256': sha(executable), 'shared_library_sha256': sha(libraries / 'libclang-cpp.so.20.1')},
            'llvm_shared_library': {'sha256': sha(libraries / 'libLLVM.so.20.1')},
            'sdcc': {'sha256': sha(sdcc), 'elf_sha256': sha(sdcc), 'source_project_wsl': '/absent-default'}}}
        lock['tools'].update({name: {'sha256': sha(executable)} for name in ('llvm_link', 'opt', 'llvm_dis', 'llvm_cbe')})
        lock['tools'].update({name: {'sha256': sha(sdcc)} for name in ('sdar', 'sdas251', 'sdld', 'sdldmcs251', 'sdcpp')})
        lock_path = self.root / 'lock.json'; lock_path.write_text(json.dumps(lock))
        script = HELPER.parents[2] / 'scripts/inspect-cpp-toolchain.sh'
        env = dict(self.env, STCXX_CPP_TOOLS_ROOT=str(frontend), STCXX_SDCC=str(sdcc))
        command = ['sh', str(script), str(lock_path)]
        before = subprocess.run(command, env=env, capture_output=True, timeout=30)
        self.assertEqual(before.returncode, 0, before.stderr.decode())
        self.assertEqual(sum(b'_libllvm\t' in line for line in before.stdout.splitlines()), 5)
        with (libraries / 'libLLVM.so.20.1').open('ab') as stream: stream.write(b'changed implementation')
        self.assertEqual(sha(executable), lock['tools']['clang']['sha256'])
        after = subprocess.run(command, env=env, capture_output=True, timeout=30)
        self.assertEqual(after.returncode, 2)
        self.assertIn(b'clang_libllvm hash differs', after.stderr)


if __name__ == '__main__':
    unittest.main()
