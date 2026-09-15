"""Native wrappers must preserve argument boundaries and propagate failures."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(sys.platform.startswith('linux') or sys.platform == 'darwin', 'Unix launcher regression')
class CppLaunchTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name) / 'path with spaces'
        self.wrapper = self.root / 'tools/wrapper'
        self.wrapper.mkdir(parents=True)
        for name in ('stc-compile.sh', 'stc-link.sh', 'stc-wsl-launch.sh', 'stc-macos-env.sh'):
            shutil.copyfile(ROOT / 'tools/wrapper' / name, self.wrapper / name)
        cli = self.root / 'tools/cpp-cli/stcxx-cli.sh'
        cli.parent.mkdir()
        cli.write_text('''#!/bin/bash
printf '%s\\n' "$1" "$2" "$3" > "$STCXX_CAPTURE/mode.txt"
cat "$4" > "$STCXX_CAPTURE/arguments.bin"
printf '%s' "$STCXX_ARDUINO_SDCC" > "$STCXX_CAPTURE/compiler.txt"
printf '%s' "${STCXX_WINDOWS_HOST:-0}" > "$STCXX_CAPTURE/windows-host.txt"
if [ "$STCXX_FAKE_READY" = 1 ]; then : > "$STCXX_PIPELINE_READY_MARKER"; fi
exit "$STCXX_FAKE_EXIT"
''')
        self.env = dict(os.environ, STCXX_CAPTURE=str(self.root), STCXX_FAKE_READY='1',
                        STCXX_FAKE_EXIT='0', STCXX_WSL_RETRY_DELAY_SECONDS='0')
        self.source = self.root / 'source.cpp'
        self.source.write_text('fixture')
        self.object = self.root / 'output.o'
        self.flags = ['-mmcs251', '-DSTCXX_CPP_CORE=1', '-DSTRING=some words', '-Iquote"path']

    def run_wrapper(self, link=False):
        if link:
            arguments = [*self.flags, str(self.object), '-o', str(self.root / 'firmware.hex')]
            command = ['sh', str(self.wrapper / 'stc-link.sh'), '/selected path/sdcc', *arguments]
        else:
            arguments = self.flags
            command = ['sh', str(self.wrapper / 'stc-compile.sh'), '/selected path/sdcc',
                       str(self.source), str(self.object), 're2', *arguments]
        result = subprocess.run(command, env=self.env, capture_output=True, timeout=10)
        self.assertEqual((self.root / 'arguments.bin').read_bytes(),
                         b''.join(arg.encode() + b'\0' for arg in arguments))
        self.assertFalse(list(self.root.glob('*.stcxx-*')), 'temporary launch files leaked')
        return result

    def test_native_compile_and_link(self):
        for link in (False, True):
            with self.subTest(link=link):
                result = self.run_wrapper(link)
                self.assertEqual(result.returncode, 0, result.stderr.decode())
                self.assertEqual((self.root / 'compiler.txt').read_text(), '/selected path/sdcc')
                mode = (self.root / 'mode.txt').read_text().splitlines()[0]
                self.assertEqual(mode, 'link' if link else 'compile-cpp')

    def test_real_pipeline_failure_propagates(self):
        self.env['STCXX_FAKE_EXIT'] = '37'
        self.assertEqual(self.run_wrapper().returncode, 37)

    def test_zero_exit_without_ready_marker_fails(self):
        self.env['STCXX_FAKE_READY'] = '0'
        self.assertEqual(self.run_wrapper().returncode, 4)

    def test_windows_origin_is_explicit_and_native_clears_inherited_marker(self):
        self.env['STCXX_WINDOWS_HOST'] = '1'
        for link in (False, True):
            self.assertEqual(self.run_wrapper(link).returncode, 0)
            self.assertEqual((self.root / 'windows-host.txt').read_text(), '0')
        arguments = self.root / 'arguments'
        arguments.write_bytes(b'fixture\0')
        result = subprocess.run(['sh', str(self.wrapper / 'stc-wsl-launch.sh'), '--windows-host',
                                 str(self.root / 'tools/cpp-cli/stcxx-cli.sh'), str(self.root / 'handshake'),
                                 str(self.root / 'ready'), 'compile-cpp', str(self.source), str(self.object), str(arguments)],
                                env=self.env, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr.decode())
        self.assertEqual((self.root / 'windows-host.txt').read_text(), '1')


if __name__ == '__main__':
    unittest.main()
