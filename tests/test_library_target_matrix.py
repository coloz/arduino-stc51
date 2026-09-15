import importlib.util
import contextlib
import io
import json
import re
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('library_targets', ROOT / 'scripts/check-library-targets.py')
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


class LibraryTargetMatrixTest(unittest.TestCase):
    def setUp(self):
        self.devices = {d['id']: d for d in json.loads((ROOT / 'tools/variants/devices.json').read_text())['devices']}

    def test_default_matrix_covers_each_declared_cpp_clock_and_library(self):
        cases = runner.matrix_profiles(self.devices, list(self.devices), [], list(runner.LIBRARIES), ['z'])
        # Current release contract: 12 MHz on every board, plus the two
        # specifically qualified higher-clock C++ menu entries.
        expected_profiles = {(name, 12000000) for name in self.devices}
        expected_profiles.update({('stc32g144k246', 48000000), ('ai8051u_34k64', 40000000)})
        self.assertEqual({case[:2] for case in cases}, expected_profiles)
        self.assertEqual(len(cases), len(set(cases)))
        for profile in expected_profiles:
            self.assertEqual({case[2:] for case in cases if case[:2] == profile},
                             {(library, 'z') for library in runner.LIBRARIES})

    def test_fixture_and_lcd_example_pins_are_valid_on_each_model(self):
        for relative, prefix, count in (
            ('tests/target/LibraryProbes/LibraryProbes.ino', 'PROBE_PIN', 8),
            ('libraries/LiquidCrystal/examples/HelloWorld/HelloWorld.ino', 'LCD_', 6)):
            text = (ROOT / relative).read_text()
            pins = re.findall(r'^#define ' + prefix + r'\w+ P([0-9]+)_([0-7])$', text, re.M)
            self.assertEqual(len(pins), count)
            names = {'P' + port + '.' + bit for port, bit in pins}
            self.assertEqual(len(names), count)
            for name, device in self.devices.items():
                with self.subTest(source=relative, model=name):
                    for port, bit in pins:
                        self.assertTrue(device['port_masks'][int(port)] & (1 << int(bit)))
                    for aliases in device.get('pin_alias_groups', []):
                        self.assertLessEqual(len(names.intersection(aliases)), 1)

    def test_actual_module_optimization_must_match_request(self):
        runner.verify_optimization({'modules': [{'clang_optimization': '-Oz'}]}, 'z')
        for manifest in ({}, {'modules': []}, {'modules': [{}]},
                         {'modules': [{'clang_optimization': '-O0'}]},
                         {'modules': [{'clang_optimization': '-Oz'}, {'clang_optimization': '-O2'}]}):
            with self.subTest(manifest=manifest), self.assertRaises(RuntimeError):
                runner.verify_optimization(manifest, 'z')

    def test_invalid_deadline_is_rejected_before_output_creation(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'output'
            args = [part for name in ('platform', 'config', 'cli', 'qemu')
                    for part in ('--' + name, str(Path(directory) / name))]
            args += ['--output', str(output)]
            for value in ('0', '-1', 'nan', 'inf', '-inf', '3600.1'):
                with self.subTest(value=value), contextlib.redirect_stderr(io.StringIO()), \
                        self.assertRaises(SystemExit) as raised:
                    runner.main(args + ['--qemu-timeout=' + value])
                self.assertEqual(raised.exception.code, 2)
                self.assertFalse(output.exists())

    def test_selected_deadline_reaches_oracle_and_outer_process_bound(self):
        for override, expected_timeout in ((None, 180), ('1.25', 1.25)):
            with self.subTest(override=override), tempfile.TemporaryDirectory() as directory:
                temp = Path(directory)
                source, platform, output = temp/'source', temp/'platform', temp/'output'
                for root in (source, platform):
                    (root/'tools/variants').mkdir(parents=True)
                    (root/'tools/variants/devices.json').write_text(json.dumps({'devices': list(self.devices.values())}))
                (source/'scripts').mkdir()
                (source/'scripts/check-qemu-smoke.py').write_text('# fixture oracle\n')
                fixture = source/'tests/target/LibraryProbes'
                fixture.mkdir(parents=True)
                (fixture/'LibraryProbes.ino').write_text('void setup() {}\n')
                (fixture/'expected-Wire.txt').write_text('PASS fixture\n')
                for name in ('platform.txt', 'boards.txt'):
                    (platform/name).write_text('test=fixture\n')
                (platform/'tools/cpp-cli').mkdir()
                lock = platform/'tools/cpp-cli/toolchain-lock.json'
                lock.write_text('{}\n')
                for name in ('cli', 'qemu', 'config'):
                    (temp/name).write_text('fixture\n')
                oracle_calls = []

                def fake_process(command, **kwargs):
                    if '--show-properties=expanded' in command:
                        properties = f'runtime.platform.path={platform}\nbuild.f_cpu=12000000L\nbuild.variant=STC32G12K128\n'
                        return SimpleNamespace(returncode=0, stdout=properties.encode(), stderr=b'')
                    if 'compile' in command:
                        build = Path(command[command.index('--build-path')+1])
                        (build/'stcxx').mkdir(parents=True)
                        firmware = build/'LibraryProbes.ino.hex'
                        firmware.write_text('fixture firmware\n')
                        manifest = {'outcome': 'pass', 'firmware_sha256': runner.sha(firmware),
                                    'lock_sha256': runner.sha(lock), 'modules': [{'clang_optimization': '-Oz'}],
                                    'target': {'profile': 'mcs251', 'build_f_cpu_hz': 12000000}}
                        (build/'stcxx/manifest.json').write_text(json.dumps(manifest))
                        kwargs['stdout'].write(b'Sketch uses 123 bytes. Maximum is 131072 bytes. Global variables use 10 bytes.\n')
                    else:
                        self.assertIn('--firmware', command)
                        self.assertEqual(float(command[command.index('--timeout')+1]), expected_timeout)
                        self.assertEqual(kwargs['timeout'], expected_timeout + 30)
                        oracle_calls.append(command)
                        firmware = Path(command[command.index('--firmware')+1])
                        qemu_output = Path(command[command.index('--output')+1])
                        qemu_output.mkdir()
                        (qemu_output/'qemu.json').write_text(json.dumps({'status': 'PASS', 'firmware_sha256': runner.sha(firmware)}))
                        (qemu_output/'uart.log').write_text('PASS fixture\n')
                    return SimpleNamespace(returncode=0, stdout=b'', stderr=b'')

                args = ['--platform', str(platform), '--output', str(output), '--cli', str(temp/'cli'),
                        '--qemu', str(temp/'qemu'), '--config', str(temp/'config'),
                        '--board', 'stc32g12k128', '--library', 'Wire']
                if override is not None:
                    args += ['--qemu-timeout', override]
                with patch.object(runner, 'ROOT', source), patch.object(runner.sys, 'platform', 'linux'), \
                        patch.object(runner.subprocess, 'run', side_effect=fake_process):
                    self.assertEqual(runner.main(args), 0)
                report = json.loads((output/'library-targets.json').read_text())
                self.assertEqual(report['status'], 'PASS')
                self.assertEqual(report['qemu_timeout_seconds'], expected_timeout)
                self.assertEqual(len(oracle_calls), 1)

    def test_changed_external_oracle_invalidates_the_matrix_report(self):
        with tempfile.TemporaryDirectory() as directory:
            temp = Path(directory)
            source, platform, output = temp/'source', temp/'platform', temp/'output'
            for root in (source, platform):
                (root/'tools/variants').mkdir(parents=True)
                (root/'tools/variants/devices.json').write_text(json.dumps({'devices': list(self.devices.values())}))
            (source/'scripts').mkdir()
            oracle = source/'scripts/check-qemu-smoke.py'
            oracle.write_text('# original oracle\n')
            fixture = source/'tests/target/LibraryProbes'
            fixture.mkdir(parents=True)
            (fixture/'LibraryProbes.ino').write_text('void setup() {}\n')
            for name in ('platform.txt', 'boards.txt'):
                (platform/name).write_text('test=fixture\n')
            (platform/'tools/cpp-cli').mkdir()
            (platform/'tools/cpp-cli/toolchain-lock.json').write_text('{}\n')
            for name in ('cli', 'qemu', 'config'):
                (temp/name).write_text('fixture\n')
            def alter_oracle(*args, **kwargs):
                oracle.write_text('# changed while a matrix case was running\n')
                return SimpleNamespace(returncode=1, stdout=b'', stderr=b'forced properties failure')
            argv = ['--platform', str(platform), '--output', str(output), '--cli', str(temp/'cli'),
                    '--qemu', str(temp/'qemu'), '--config', str(temp/'config'),
                    '--board', 'stc32g12k128', '--library', 'Wire']
            with patch.object(runner, 'ROOT', source), patch.object(runner.sys, 'platform', 'linux'), \
                    patch.object(runner.subprocess, 'run', side_effect=alter_oracle):
                self.assertEqual(runner.main(argv), 1)
            report = json.loads((output/'library-targets.json').read_text())
            self.assertEqual(report['status'], 'FAIL')
            self.assertEqual(report['error'], 'verification helper inputs changed')
            self.assertIn(str(oracle), report['helper_files_sha256'])
            self.assertNotIn('final_input_verification', report)

    def test_subset_is_exact_and_keeps_optimization_profiles_separate(self):
        cases = runner.matrix_profiles(self.devices, ['stc32g12k128'], [12000000], ['SD', 'Wire'], ['0', 'z'])
        self.assertEqual(set(cases), {
            ('stc32g12k128', 12000000, 'SD', '0'), ('stc32g12k128', 12000000, 'SD', 'z'),
            ('stc32g12k128', 12000000, 'Wire', '0'), ('stc32g12k128', 12000000, 'Wire', 'z')})

    def test_invalid_or_repeated_profiles_are_not_silently_dropped(self):
        for selection in (
            ([], [], ['Wire'], ['z']), (['unknown'], [], ['Wire'], ['z']),
            (['stc32g12k128'] * 2, [], ['Wire'], ['z']),
            (['stc32g12k128'], [48000000], ['Wire'], ['z']),
            (['stc32g12k128'], [12000000, 12000000], ['Wire'], ['z']),
            (['stc32g12k128'], [], ['Wire', 'Wire'], ['z']),
            (['stc32g12k128'], [], ['missing'], ['z']),
            (['stc32g12k128'], [], ['Wire'], ['z', 'z']),
            (['stc32g12k128'], [], ['Wire'], ['3'])):
            with self.subTest(selection=selection), self.assertRaises(RuntimeError):
                runner.matrix_profiles(self.devices, *selection)


if __name__ == '__main__':
    unittest.main()
