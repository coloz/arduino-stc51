"""Release-runner checks use simulated tools; target execution is separate."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('cpp_targets', ROOT / 'scripts/check-cpp-targets.py')
GATE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GATE)


def record(address, kind, payload):
    data = bytes([len(payload), address >> 8, address & 255, kind, *payload])
    return ':' + (data + bytes([-sum(data) & 255])).hex().upper() + '\n'


class CppTargetGate(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.platform, self.tools = self.root / 'platform', self.root / 'toolchain'
        self.source = self.root / 'source'
        self.device = {'id': 'board', 'model': 'STC32G8K64', 'macro': 'STC32G8K64', 'target': 'mcs251',
                       'flash_bytes': 65536, 'maximum_code_bytes': 65536, 'linker': {'code_loc': 0xff0000}}
        for path in (self.platform / 'tools/variants', self.source / 'tools/variants',
                     self.platform / 'tools/cpp-cli', self.source / 'scripts', self.tools):
            path.mkdir(parents=True)
        for base in (self.platform, self.source):
            (base / 'tools/variants/devices.json').write_text(json.dumps({'devices': [self.device]}))
        (self.platform / 'platform.txt').write_text('fixture')
        (self.platform / 'boards.txt').write_text('fixture')
        self.lock = self.platform / 'tools/cpp-cli/toolchain-lock.json'
        self.lock.write_text('{}')
        self.frontend = self.root / 'frontend'
        self.frontend.mkdir()
        (self.frontend / 'clang').write_text('fixture frontend')
        for name in ('sdcc', 'sdar', 'shell'):
            (self.tools / name).write_text('fixture tool')
        for name in ('cli', 'qemu', 'stc', 'config'):
            (self.root / name).write_text('fixture')
        (self.source / 'scripts/check-qemu-smoke.py').write_text('fixture helper')
        for probe in GATE.PROBES:
            source = self.source / 'tests/target' / probe
            source.mkdir(parents=True)
            (source / (probe + '.ino')).write_text('fixture source')
            (source / 'expected-uart.txt').write_text('PASS fixture\n')
        (self.source / 'tests/target/HeapTelemetry/faults.c').write_text('fixture native companion')
        self.output = self.root / 'output'
        self.args = [part for name in ('platform', 'config', 'cli', 'qemu', 'stc', 'frontend', 'output')
                     for part in ('--' + name, str(getattr(self, name, self.root / name)))]
        self.args += ['--jobs', '1']
        self.hex = record(0, 4, [0, 255]) + record(0, 0, [2, 0, 3]) + record(0, 1, [])
        self.failure = None

    def fake_process(self, command, **kwargs):
        command = list(map(str, command))
        code, output = 0, b'fixture version\n'
        if '--show-properties=expanded' in command:
            values = {'runtime.platform.path': str(self.platform), 'build.variant': self.device['macro'],
                      'build.f_cpu': '24000000L' if self.failure == 'clock' else '12000000L',
                      'runtime.tools.sdcc.path': str(self.tools), 'compiler.path': str(self.tools),
                      'compiler.ar.path': str(self.tools), 'compiler.c.cmd': 'sdcc', 'compiler.cpp.cmd': 'sdcc',
                      'compiler.c.elf.cmd': 'sdcc', 'compiler.ar.cmd': 'sdar', 'compiler.shell.cmd': str(self.tools / 'shell')}
            output = ''.join(f'{key}={value}\n' for key, value in values.items()).encode()
        elif 'compile' in command:
            build = Path(command[command.index('--build-path') + 1])
            (build / 'stcxx').mkdir(parents=True)
            probe = Path(command[-1]).name
            firmware = build / (probe + '.ino.hex')
            firmware.write_text(self.hex)
            level = command[command.index('--build-property') + 1].split('=')[-1]
            manifest = {'outcome': 'pass', 'firmware_sha256': GATE.sha(firmware), 'lock_sha256': GATE.sha(self.lock),
                        'target': {'profile': 'mcs251', 'build_f_cpu_hz': 12000000},
                        'modules': [{'clang_optimization': '-O' + level}]}
            if self.failure == 'optimization':
                manifest['modules'] = []
            if self.failure == 'manifest':
                manifest['firmware_sha256'] = '0' * 64
            (build / 'stcxx/manifest.json').write_text(json.dumps(manifest))
            if self.failure == 'source':
                (self.platform / 'boards.txt').write_text('changed')
            if self.failure == 'tool':
                (self.tools / 'sdcc').write_text('changed')
            if self.failure == 'frontend':
                (self.frontend / 'new-library').write_text('added')
            if self.failure == 'native_probe':
                (self.source / 'tests/target/HeapTelemetry/faults.c').write_text('changed native companion')
            maximum = 131072 if self.failure == 'capacity' else 65536
            output = f'Sketch uses 22 bytes. Maximum is {maximum} bytes. Global variables use 8 bytes.\n'.encode()
        elif '--firmware' in command:
            firmware = Path(command[command.index('--firmware') + 1])
            expected = Path(command[command.index('--expected') + 1])
            out = Path(command[command.index('--output') + 1])
            out.mkdir()
            uart = out / 'uart.log'
            uart.write_bytes(b'FAIL\n' if self.failure == 'uart' else expected.read_bytes())
            report = {'status': 'PASS', 'board': 'board', 'firmware_sha256': GATE.sha(firmware),
                      'qemu_sha256': GATE.sha(self.root / 'qemu'), 'oracle_sha256': GATE.sha(expected), 'uart_sha256': GATE.sha(uart)}
            (out / 'qemu.json').write_text(json.dumps(report))
        elif 'validate' in command:
            filename = command[command.index('--file') + 1]
            if filename.endswith('bad-checksum.hex'):
                code, output = 8, b'invalid checksum'
            else:
                validated = {'valid': True, 'device': {'name': self.device['model']}, 'file': filename,
                             'execution_mode': 'mcs251', 'input_bytes': 3, 'base_address': 0xff0000}
                if self.failure == 'programmer':
                    validated['input_bytes'] = 22
                output = json.dumps(validated).encode()
        elif '-w' in command:
            self.assertEqual(Path(command[0]).name, 'wslpath')
            output = ('D:/fixture/' + Path(command[-1]).name + '\n').encode()
        kwargs['stdout'].write(output)
        kwargs['stdout'].flush()
        class Process:
            pid = 12345
            def wait(self, timeout):
                return code
        return Process()

    def run_gate(self, extra=()):
        with patch.object(GATE, 'ROOT', self.source), patch.object(GATE.sys, 'platform', 'linux'), \
             patch.dict(GATE.os.environ, {}, clear=True), patch.object(GATE.subprocess, 'Popen', side_effect=self.fake_process):
            code = GATE.main([*self.args, *extra])
        report = json.loads((self.output / 'cpp-targets.json').read_text())
        return code, report

    def test_complete_baseline_and_input_binding(self):
        code, report = self.run_gate()
        self.assertEqual(code, 0)
        self.assertEqual(len(report['results']), 4)
        self.assertTrue(report['full_baseline_coverage'])
        self.assertEqual(report['final_input_verification'], 'PASS')
        self.assertFalse(report['production_qualified'])
        self.assertIn(str(GATE.__file__), report['input_files_sha256'])

    def test_subset_does_not_claim_complete_baseline(self):
        code, report = self.run_gate(['--probe', 'ReturnIdentity', '--optimization', '0'])
        self.assertEqual(code, 0)
        self.assertFalse(report['full_baseline_coverage'])
        self.assertEqual(len(report['results']), 1)

    def installed_frontend_args(self):
        index = self.args.index('--frontend')
        self.args[index:index + 2] = ['--installed-frontend']
        helper = self.platform / 'tools/cpp-cli/toolchain-paths.sh'
        helper.write_text('fixture discovery helper\n')
        self.lock.write_text(json.dumps({'pipeline_helpers': {'toolchain_paths': {'sha256': GATE.sha(helper)}}}))
        return helper

    def test_installed_frontend_does_not_inject_tool_environment(self):
        self.installed_frontend_args()
        result = subprocess.CompletedProcess([], 0, str(self.frontend) + '\n', '')
        def process(command, **kwargs):
            self.assertFalse(any(key.startswith('STCXX_') for key in kwargs['env']))
            return CppTargetGate.fake_process(self, command, **kwargs)
        with patch.object(self, 'fake_process', side_effect=process), \
                patch.object(GATE.subprocess, 'run', return_value=result) as discovery:
            code, report = self.run_gate(['--probe', 'SmallControl', '--optimization', 'z'])
        self.assertEqual(code, 0)
        discovery.assert_called_once()
        self.assertEqual(report['environment_overrides'], {})
        self.assertEqual(report['frontend'], str(self.frontend.resolve()))
        self.assertEqual(report['final_input_verification'], 'PASS')

    def test_changed_installed_discovery_helper_is_rejected_before_execution(self):
        helper = self.installed_frontend_args()
        helper.write_text('changed discovery helper\n')
        with patch.object(GATE.subprocess, 'run') as discovery:
            code, report = self.run_gate()
        discovery.assert_not_called()
        self.assertEqual(code, 1)
        self.assertIn('discovery helper differs', report['error'])

    def test_heap_regression_is_explicit_and_binds_native_companion(self):
        code, report = self.run_gate(['--probe', 'HeapTelemetry'])
        self.assertEqual(code, 0)
        self.assertEqual(len(report['results']), 2)
        self.assertFalse(report['full_baseline_coverage'])
        self.assertTrue(all(row['probe'] == 'HeapTelemetry' for row in report['results']))
        self.assertIn('faults.c', report['probe_sources_sha256']['HeapTelemetry'])

    def test_changed_native_heap_companion_invalidates_run(self):
        self.failure = 'native_probe'
        code, report = self.run_gate(['--probe', 'HeapTelemetry', '--optimization', 'z'])
        self.assertEqual(code, 1)
        self.assertEqual(report['status'], 'FAIL')

    def test_stepper_regression_is_explicit_and_source_bound(self):
        code, report = self.run_gate(['--probe', 'StepperPhases'])
        self.assertEqual(code, 0)
        self.assertEqual(len(report['results']), 2)
        self.assertFalse(report['full_baseline_coverage'])
        self.assertTrue(all(row['probe'] == 'StepperPhases' for row in report['results']))
        self.assertIn('StepperPhases.ino', report['probe_sources_sha256']['StepperPhases'])

    def test_false_success_evidence_is_rejected(self):
        for failure in ('clock', 'optimization', 'manifest', 'capacity', 'uart', 'programmer'):
            with self.subTest(failure=failure):
                self.failure = failure
                code, report = self.run_gate(['--probe', 'ReturnIdentity', '--optimization', '0'])
                self.assertEqual(code, 1)
                self.assertEqual(report['status'], 'FAIL')

    def test_input_mutation_invalidates_otherwise_passing_run(self):
        for failure in ('source', 'tool', 'frontend'):
            with self.subTest(failure=failure):
                self.failure = failure
                code, report = self.run_gate(['--probe', 'ReturnIdentity', '--optimization', '0'])
                self.assertEqual(code, 1)
                self.assertEqual(report['status'], 'FAIL')

    def test_failed_repeat_replaces_stale_pass_and_preserves_stage(self):
        self.assertEqual(self.run_gate()[0], 0)
        old_stage = json.loads((self.output / 'cpp-targets.json').read_text())['stage']
        self.failure = 'programmer'
        code, report = self.run_gate()
        self.assertEqual(code, 1)
        self.assertEqual(report['status'], 'FAIL')
        self.assertNotEqual(report['stage'], old_stage)
        self.assertTrue(Path(old_stage).is_dir())

    def test_hex_integrity_capacity_and_home(self):
        path = self.root / 'firmware.hex'
        for bad in (self.hex.replace('020003', '020004'), self.hex + ':00000001FF\n',
                    record(0, 4, [0, 254]) + record(0, 0, [2, 0, 3]) + record(0, 1, []),
                    record(0, 4, [0, 255]) + record(1, 0, [2, 0, 3]) + record(0, 1, [])):
            with self.subTest(bad=bad), self.assertRaises((ValueError, RuntimeError)):
                path.write_text(bad)
                GATE.read_hex(path, self.device)
        path.write_text(self.hex)
        with self.assertRaisesRegex(RuntimeError, 'code capacity'):
            GATE.read_hex(path, dict(self.device, maximum_code_bytes=2))

    def test_invalid_profile_selection(self):
        for arguments in ({'boards': []}, {'boards': ['missing']}, {'boards': ['board', 'board']},
                          {'clocks': [24000000]}, {'clocks': [True]}, {'probes': []}, {'levels': ['2']}):
            with self.subTest(arguments=arguments), self.assertRaises(RuntimeError):
                GATE.profiles([self.device], **arguments)

    def test_windows_programmer_path_and_byte_identity(self):
        image = {'bytes': 3, 'first_address': 0xff0000}
        value = {'valid': True, 'device': {'name': self.device['model']}, 'execution_mode': 'mcs251',
                 'file': 'D:\\firmware folder\\case.hex', 'input_bytes': 3, 'base_address': 0xff0000}
        GATE.check_validation(value, self.device, 'd:/firmware folder/case.hex', image, True)
        with self.assertRaises(RuntimeError):
            GATE.check_validation(value, self.device, 'D:/different.hex', image, True)
        with self.assertRaises(RuntimeError):
            GATE.check_validation(dict(value, input_bytes=True), self.device, value['file'], image, True)

    @unittest.skipUnless(os.name == 'posix', 'requires POSIX symlink semantics')
    def test_wslpath_multicall_basename_is_preserved(self):
        target = self.root / 'init'
        target.write_bytes(b'multicall fixture')
        link = self.root / 'wslpath'
        link.symlink_to(target)
        (self.root / 'stc').write_bytes(b'MZfixture')
        with patch.object(GATE.shutil, 'which', return_value=str(link)):
            code, report = self.run_gate(['--probe', 'ReturnIdentity', '--optimization', '0', '--stc-windows-paths'])
        self.assertEqual(code, 0)
        command = next(row['command'] for row in report['preflight']['commands'] if row['name'] == 'bad-hex-path')
        self.assertEqual(command[0], str(link))

    def test_timeout_retains_command_logs_and_reaps_process_group(self):
        original = self.fake_process
        def timeout(command, **kwargs):
            process = original(command, **kwargs)
            from unittest.mock import Mock
            process.wait = Mock(side_effect=[subprocess.TimeoutExpired('fixture', 1), 0])
            return process
        with patch.object(self, 'fake_process', side_effect=timeout), patch.object(GATE.os, 'killpg', create=True) as kill:
            code, report = self.run_gate()
        self.assertEqual(code, 1)
        entry = report['preflight']['commands'][0]
        self.assertEqual(entry['error'], 'TimeoutExpired')
        self.assertIn('stdout_sha256', entry)
        self.assertIn('stderr_sha256', entry)
        kill.assert_called_once_with(12345, GATE.signal.SIGTERM)


if __name__ == '__main__':
    unittest.main()
