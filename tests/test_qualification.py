import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('qualification', ROOT / 'scripts/qualify-release.py')
QUAL = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(QUAL)


def record(address, kind, payload):
    data = bytes([len(payload), address >> 8, address & 255, kind, *payload])
    return ':' + (data + bytes([-sum(data) & 255])).hex().upper() + '\n'


class QualificationTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.platform = self.root / 'platform'
        devices = self.platform / 'tools/variants/devices.json'
        devices.parent.mkdir(parents=True)
        self.device = {'id': 'stc32g8k64', 'model': 'STC32G8K64', 'target': 'mcs251',
                       'flash_bytes': 65536, 'maximum_code_bytes': 65536,
                       'clock_options_hz': [12000000, 24000000], 'default_clock_hz': 24000000,
                       'linker': {'code_loc': 0xff0000}}
        devices.write_text(json.dumps({'devices': [self.device]}), encoding='utf-8')
        (self.platform / 'platform.txt').write_text('version=0.0.3', encoding='utf-8')
        (self.platform / 'boards.txt').write_text('fixture', encoding='utf-8')
        self.config, self.stc = self.root / 'config.yaml', self.root / 'stc'
        self.config.write_text('fixture', encoding='utf-8')
        self.stc.write_text('fixture', encoding='utf-8')
        self.cli = self.root / 'arduino-cli'
        self.cli.write_text('fixture CLI', encoding='utf-8')
        self.tools = self.root / 'tools'
        self.tools.mkdir()
        for name in ('sdcc', 'sdar', 'shell'):
            (self.tools / name).write_text('fixture executable', encoding='utf-8')
        self.output = self.root / 'output'
        self.args = ['--platform', str(self.platform), '--config', str(self.config),
                     '--stc', str(self.stc), '--output', str(self.output),
                     '--host', 'fixture', '--timeout', '1', '--cli', str(self.cli)]
        self.hex = record(0, 4, [0, 255]) + record(0, 0, [2, 0, 3]) + record(0, 1, [])
        self.mutate_source = False
        self.wrong_platform = False
        self.mutate_tool = False
        self.mutate_override = False
        self.missing_tool = False
        self.wrong_validation = False
        self.wrong_clock = False

    def fake_run(self, command, **kwargs):
        command = list(map(str, command))
        if '--show-properties=expanded' in command:
            selected = self.root if self.wrong_platform else self.platform
            properties = {'runtime.platform.path': str(selected),
                          'build.f_cpu': '24000000L',
                          'runtime.tools.sdcc-mcs251.path': str(self.tools),
                          'compiler.path': str(self.tools), 'compiler.ar.path': str(self.tools),
                          'compiler.c.cmd': 'sdcc', 'compiler.cpp.cmd': 'sdcc',
                          'compiler.c.elf.cmd': 'sdcc', 'compiler.ar.cmd': 'sdar',
                          'compiler.shell.cmd': str(self.tools / 'shell')}
            fqbn = command[command.index('--fqbn') + 1]
            if ':clock=12m' in fqbn and not self.wrong_clock:
                properties['build.f_cpu'] = '12000000L'
            if self.missing_tool:
                properties.pop('runtime.tools.sdcc-mcs251.path')
            return subprocess.CompletedProcess(command, 0,
                ''.join(f'{k}={v}\n' for k, v in properties.items()).encode())
        if 'compile' in command:
            build = Path(command[command.index('--build-path') + 1])
            build.mkdir(exist_ok=True)
            (build / 'Blink.hex').write_text(self.hex, encoding='ascii')
            if self.mutate_source:
                (self.platform / 'boards.txt').write_text('changed', encoding='utf-8')
            if self.mutate_tool:
                (self.tools / 'sdcc').write_text('changed', encoding='utf-8')
            if self.mutate_override:
                (self.platform / 'platform.local.txt').write_text('compiler.path=changed', encoding='utf-8')
        if 'validate' in command:
            validation = {'valid': True, 'device': {'name': self.device['model']},
                          'file': command[command.index('--file') + 1],
                          'execution_mode': 'mcs251', 'input_bytes': 3, 'base_address': 0xff0000}
            if self.wrong_validation:
                validation = {}
            return subprocess.CompletedProcess(command, 8 if 'bad-checksum.hex' in command[-1] else 0,
                                               json.dumps(validation).encode())
        return subprocess.CompletedProcess(command, 0, b'fixture version')

    def run_gate(self, fake=None):
        with patch.object(QUAL.subprocess, 'run', side_effect=fake or self.fake_run):
            status = QUAL.main(self.args)
        report = json.loads((self.output / 'qualification.json').read_text(encoding='utf-8'))
        return status, report

    def test_success_binds_inputs(self):
        status, report = self.run_gate()
        self.assertEqual(status, 0)
        self.assertEqual(report['status'], 'PASS')
        self.assertIn('boards.txt', report['source_sha256'])
        self.assertEqual(len(report['results']), 1)
        self.assertIn('sdcc', report['toolchain_sha256']['files'][str(self.tools)])
        self.assertEqual(report['arduino_cli_sha256'], QUAL.sha256(self.cli))

    def test_missing_tool_identity_rejected(self):
        self.missing_tool = True
        status, report = self.run_gate()
        self.assertEqual(status, 1)
        self.assertIn('no installed tool roots', report['error'])

    def test_all_declared_clocks_are_executed(self):
        self.args.append('--all-clocks')
        status, report = self.run_gate()
        self.assertEqual(status, 0)
        self.assertEqual([x['clock_hz'] for x in report['results']], [12000000, 24000000])
        self.assertEqual(report['expected_profiles'], 2)

    def test_selected_clock_mismatch_rejected(self):
        self.args.append('--all-clocks')
        self.wrong_clock = True
        status, report = self.run_gate()
        self.assertEqual(status, 1)
        self.assertIn('selected clock', report['error'])

    def test_empty_programmer_validation_rejected(self):
        self.wrong_validation = True
        status, report = self.run_gate()
        self.assertEqual(status, 1)
        self.assertIn('programmer validation', report['error'])

    def test_changed_compiler_rejected(self):
        self.mutate_tool = True
        status, report = self.run_gate()
        self.assertEqual(status, 1)
        self.assertIn('toolchain changed', report['error'])

    def test_added_platform_override_rejected(self):
        self.mutate_override = True
        status, report = self.run_gate()
        self.assertEqual(status, 1)
        self.assertIn('sources changed', report['error'])

    def test_failed_run_replaces_stale_pass(self):
        self.run_gate()
        status, report = self.run_gate(lambda *a, **kw: subprocess.CompletedProcess(a, 1, b'failed'))
        self.assertEqual(status, 1)
        self.assertEqual(report['status'], 'FAIL')
        self.assertEqual(report['results'], [])

    def test_timeout_is_recorded(self):
        def timeout(*a, **kw):
            raise subprocess.TimeoutExpired('fixture', 1, output=b'partial output')
        status, report = self.run_gate(timeout)
        self.assertEqual(status, 1)
        self.assertIn('exceeded', report['error'])
        self.assertEqual((self.output / 'arduino-version.log').read_bytes(), b'partial output')

    def test_wrong_platform_rejected(self):
        self.wrong_platform = True
        status, report = self.run_gate()
        self.assertEqual(status, 1)
        self.assertIn('different platform', report['error'])

    def test_changed_sources_rejected(self):
        self.mutate_source = True
        status, report = self.run_gate()
        self.assertEqual(status, 1)
        self.assertIn('sources changed', report['error'])

    def test_malformed_hex(self):
        for invalid in (self.hex[:-12], self.hex + ':00000001FF\n',
                        record(0, 4, [0, 255]) + record(0, 0, [2]) + record(0, 0, [2]) + record(0, 1, []),
                        record(0, 4, [0, 254]) + record(0, 0, [2]) + record(0, 1, []),
                        ':0100000000FE\n:00000001FF\n'):
            self.hex = invalid
            status, report = self.run_gate()
            self.assertEqual(status, 1)
            self.assertEqual(report['status'], 'FAIL')


if __name__ == '__main__':
    unittest.main()
