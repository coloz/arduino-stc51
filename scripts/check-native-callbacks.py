#!/usr/bin/env python3
"""Verify native callback interoperability and aggregate-ABI rejection on Linux/WSL.

Uses an installed candidate, Arduino CLI and matching QEMU machines. Physical
timing and peripherals require separate qualification. Unsafe fixtures must
fail specifically at the ABI gate, with no firmware or passing C++ manifest.
"""
import argparse
import concurrent.futures
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('qualification', Path(__file__).with_name('qualify-release.py'))
qualification = importlib.util.module_from_spec(spec)
spec.loader.exec_module(qualification)
sha = qualification.sha256
require = qualification.require
DIAGNOSTIC = 'STCXX_ARDUINO_CLI_ADAPTER=FAIL: unsupported native C aggregate callback ABI:'


def check_rejection(exit_code, log, build):
    require(exit_code > 0 and DIAGNOSTIC in log, 'expected a specific aggregate callback ABI rejection')
    require((build / 'stcxx/raw.c').is_file(), 'negative fixture did not reach the adapter')
    require(not list(build.glob('*.hex')) and not (build / 'stcxx/manifest.json').exists(),
            'a rejected callback left firmware or a passing manifest')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('platform', 'config', 'cli', 'qemu', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--board', action='append', help='positive-test board; repeatable (default G12K128 and AI8051U-34K16)')
    parser.add_argument('--optimization', choices=('0', '1', '2', 's', 'z'), action='append', help='default: 0 and z')
    args = parser.parse_args(argv)
    args.platform, args.output = args.platform.resolve(), args.output.resolve()
    for source in (args.platform, ROOT / 'tests', ROOT / 'scripts'):
        if args.output == source or source in args.output.parents or args.output in source.parents:
            parser.error('output must be separate from platform and test sources')
    args.output.mkdir(parents=True, exist_ok=True)
    report = {'status': 'RUNNING', 'scope': 'native scalar/explicit-result callbacks, internal aggregate returns, and rejected native aggregate callbacks; no physical timing qualification',
              'started_utc': datetime.now(timezone.utc).isoformat(), 'results': []}

    def save():
        pending = args.output / 'native-callbacks.json.part'
        pending.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
        pending.replace(args.output / 'native-callbacks.json')

    save()
    try:
        require(sys.platform.startswith('linux'), 'run this matrix on Linux/WSL')
        boards = args.board or ['stc32g12k128', 'ai8051u_34k16']
        levels = args.optimization or ['0', 'z']
        require(len(set(boards)) == len(boards) and len(set(levels)) == len(levels), 'duplicate matrix profile')
        devices = {d['id']: d for d in json.loads((args.platform / 'tools/variants/devices.json').read_text())['devices']}
        require(all(b in devices and devices[b]['target'] == 'mcs251' and
                    12000000 in devices[b].get('cpp_mcs251_clock_options_hz', [12000000]) for b in boards),
                'unknown or unsupported callback test board/clock')
        report.update(platform=str(args.platform), platform_sha256=qualification.source_inventory(args.platform),
                      config_sha256=sha(args.config), arduino_cli_sha256=sha(args.cli), qemu_sha256=sha(args.qemu),
                      runner_sha256=sha(Path(__file__)), cpp_lock_sha256=sha(args.platform / 'tools/cpp-cli/toolchain-lock.json'))
        stage = args.output / ('run-' + uuid.uuid4().hex)
        stage.mkdir()
        cases = [(board, sketch, level, 0) for board in boards for level in levels
                 for sketch in ('NativeCallbacks', 'ReturnIdentity')]
        cases += [(boards[0], 'NativeAggregateCallbacks', level, bad) for level in levels for bad in (1, 2, 3, 4)]
        report['expected_cases'] = len(cases)
        save()

        def run_case(board, sketch, level, bad):
            case = stage / f'{board}-{sketch}-O{level}-{bad}'
            case.mkdir()
            source = ROOT / 'tests' / ('negative' if bad else 'target') / sketch
            identity = {p.name: sha(p) for p in source.iterdir() if p.is_file()}
            build = case / 'build'
            command = [str(args.cli), 'compile', '--clean', '--fqbn',
                       f'arduino-stc51:mcs251:{board}:cppcore=enabled,clock=12m',
                       '--build-path', str(build), '--config-file', str(args.config), '--build-property',
                       f'compiler.cpp.extra_flags=-DSTCXX_CPP_OPT={level} -DSTCXX_CALLBACK_BAD_CASE={bad}', str(source)]
            result = {'status': 'RUNNING', 'board': board, 'sketch': sketch, 'optimization': level,
                      'negative_case': bad, 'source_sha256': identity, 'command': command, 'path': str(case)}
            try:
                properties_run = subprocess.run([*command[:-1], '--show-properties=expanded', command[-1]],
                                                capture_output=True, timeout=120)
                properties_log = case / 'properties.log'
                properties_log.write_bytes(properties_run.stdout + properties_run.stderr)
                require(properties_run.returncode == 0, 'cannot resolve Arduino build properties')
                properties = {}
                for line in properties_run.stdout.decode(errors='replace').splitlines():
                    key, separator, value = line.partition('=')
                    if separator:
                        require(key not in properties, 'duplicate Arduino property: ' + key)
                        properties[key] = value.strip()
                require(Path(properties.get('runtime.platform.path', '')).resolve() == args.platform and
                        properties.get('build.f_cpu', '').rstrip('LlUu') == '12000000' and
                        properties.get('build.variant') == devices[board]['macro'],
                        'Arduino selected a different platform, clock or variant')
                result['properties_log_sha256'] = sha(properties_log)
                log = case / 'compile.log'
                with log.open('wb') as stream:
                    completed = subprocess.run(command, stdout=stream, stderr=subprocess.STDOUT, timeout=900)
                text = log.read_text(errors='replace')
                result.update(compile_exit=completed.returncode, compile_log_sha256=sha(log), compile_log_tail=text[-1800:])
                if bad:
                    check_rejection(completed.returncode, text, build)
                    result['verification'] = 'EXPECTED_ABI_REJECTION'
                else:
                    require(completed.returncode == 0, 'positive callback build failed')
                    firmware = build / (sketch + '.ino.hex')
                    manifest_file = build / 'stcxx/manifest.json'
                    manifest = json.loads(manifest_file.read_text())
                    require(manifest['outcome'] == 'pass' and manifest['firmware_sha256'] == sha(firmware) and
                            manifest['lock_sha256'] == report['cpp_lock_sha256'] and
                            manifest['target']['profile'] == 'mcs251' and manifest['target']['build_f_cpu_hz'] == 12000000,
                            'C++ manifest does not describe this build')
                    result.update(firmware=str(firmware), firmware_sha256=sha(firmware), cpp_manifest_sha256=sha(manifest_file),
                                  callback_provenance=manifest['audit']['ir']['native_aggregate_abi']['callback_provenance'])
                    qemu_command = [sys.executable, str(ROOT / 'scripts/check-qemu-smoke.py'), '--qemu', str(args.qemu),
                                    '--firmware', str(firmware), '--board', board, '--expected', str(source / 'expected-uart.txt'),
                                    '--output', str(case / 'qemu')]
                    checked = subprocess.run(qemu_command, capture_output=True, timeout=90)
                    result['qemu'] = json.loads((case / 'qemu/qemu.json').read_text())
                    require(checked.returncode == 0 and result['qemu']['status'] == 'PASS' and
                            result['qemu']['firmware_sha256'] == result['firmware_sha256'], 'callback execution oracle failed')
                    result['verification'] = 'EXACT_TARGET_UART_PASS'
                require(identity == {p.name: sha(p) for p in source.iterdir() if p.is_file()}, 'test source changed during build')
                result['status'] = 'PASS'
            except Exception as error:
                result.update(status='FAIL', error=str(error))
            (case / 'result.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
            return result

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            for future in concurrent.futures.as_completed([pool.submit(run_case, *case) for case in cases]):
                result = future.result()
                report['results'].append(result)
                save()
                print(result['status'], result['board'], result['sketch'], result['optimization'], result['negative_case'], flush=True)
        require(len(report['results']) == report['expected_cases'] and all(r['status'] == 'PASS' for r in report['results']),
                'callback matrix has failing or incomplete cases')
        require(qualification.source_inventory(args.platform) == report['platform_sha256'] and
                sha(args.config) == report['config_sha256'] and sha(args.cli) == report['arduino_cli_sha256'] and
                sha(args.qemu) == report['qemu_sha256'] and sha(Path(__file__)) == report['runner_sha256'],
                'matrix inputs changed during execution')
        report['status'] = 'PASS'
    except (Exception, KeyboardInterrupt) as error:
        report.update(status='FAIL', error=str(error) or type(error).__name__)
        print(report['error'], file=sys.stderr)
    finally:
        report['finished_utc'] = datetime.now(timezone.utc).isoformat()
        save()
    return 0 if report['status'] == 'PASS' else 1


if __name__ == '__main__':
    sys.exit(main())
