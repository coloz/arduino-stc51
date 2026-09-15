#!/usr/bin/env python3
"""Build and execute real C++ library configuration/lifecycle probes on Linux/WSL.

Default: all declared C++ board/clock profiles, six libraries, Oz. This is
functional and capacity evidence, not external-bus or physical timing proof.
Build/capacity errors remain FAIL and are never converted into passing cases.
"""
import argparse
import concurrent.futures
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('qualification', Path(__file__).with_name('qualify-release.py'))
qualification = importlib.util.module_from_spec(spec)
spec.loader.exec_module(qualification)
sha, require = qualification.sha256, qualification.require
LIBRARIES = ('Wire', 'SPI', 'SoftwareSerial', 'LiquidCrystal', 'Stepper', 'SD')


def helper_inventory():
    # These live outside the staged platform whose inventory is checked below.
    # Binding just this runner cannot detect changes in its imported verifier
    # or the executable QEMU oracle/board metadata.
    paths = (Path(qualification.__file__).resolve(), ROOT / 'scripts/check-qemu-smoke.py',
             ROOT / 'tools/variants/devices.json', Path(sys.executable).resolve())
    return {str(path): sha(path) for path in paths}


def matrix_profiles(devices, boards, clocks, libraries, levels):
    require(boards and libraries and levels, 'empty library matrix')
    for values in (boards, clocks, libraries, levels):
        require(len(values) == len(set(values)), 'duplicate library matrix selection')
    require(all(board in devices for board in boards), 'unknown board')
    require(all(name in LIBRARIES for name in libraries), 'unknown library')
    require(all(level in ('0', '1', '2', 's', 'z') for level in levels), 'unsupported optimization')
    profiles = []
    for board in boards:
        device = devices[board]
        supported = device.get('cpp_mcs251_clock_options_hz', [12000000])
        selected = clocks or supported
        require(device['target'] == 'mcs251' and supported and len(supported) == len(set(supported)), 'invalid C++ board profile')
        require(all(isinstance(clock, int) and clock > 0 and clock % 1000000 == 0 and clock in supported for clock in selected),
                'unsupported C++ clock: ' + board)
        profiles += [(board, clock, library, level) for clock in selected for library in libraries for level in levels]
    return profiles


def verify_optimization(manifest, level):
    modules = manifest.get('modules')
    require(isinstance(modules, list) and modules and
            all(module.get('clang_optimization') == '-O' + level for module in modules),
            'C++ optimization differs from the requested library matrix level')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('platform', 'config', 'cli', 'qemu', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--board', action='append', help='repeatable; default all declared boards')
    parser.add_argument('--clock', action='append', type=int, help='Hz; repeatable; default each board\'s declared C++ clocks')
    parser.add_argument('--library', action='append', choices=LIBRARIES, help='repeatable; default all six')
    parser.add_argument('--optimization', action='append', choices=('0', '1', '2', 's', 'z'), help='repeatable; default z')
    parser.add_argument('--qemu-timeout', type=float, default=180,
                        help='wall-clock seconds per UART oracle, in (0, 3600]; default 180 permits LCD initialization on slower hosts')
    args = parser.parse_args(argv)
    if not 0 < args.qemu_timeout <= 3600:
        parser.error('QEMU timeout must be in (0, 3600] seconds')
    args.platform, args.output = args.platform.resolve(), args.output.resolve()
    for source in (args.platform, ROOT / 'tests', ROOT / 'scripts'):
        if args.output == source or source in args.output.parents or args.output in source.parents:
            parser.error('output must be separate from platform and test sources')
    args.output.mkdir(parents=True, exist_ok=True)
    report = {'status': 'RUNNING', 'scope': 'real C++ library configuration, buffering, transactions and object lifetime; no physical bus/SD media qualification',
              'started_utc': datetime.now(timezone.utc).isoformat(),
              'qemu_timeout_seconds': args.qemu_timeout, 'results': []}
    def save():
        pending = args.output / 'library-targets.json.part'
        pending.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
        pending.replace(args.output / 'library-targets.json')
    save()
    try:
        require(sys.platform.startswith('linux'), 'run on Linux/WSL')
        report['helper_files_sha256'] = helper_inventory()
        require(sha(args.platform / 'tools/variants/devices.json') == sha(ROOT / 'tools/variants/devices.json'),
                'staged devices differ from the QEMU oracle device inventory')
        devices = {d['id']: d for d in json.loads((args.platform / 'tools/variants/devices.json').read_text())['devices']}
        cases = matrix_profiles(devices, args.board or list(devices), args.clock or [],
                                args.library or list(LIBRARIES), args.optimization or ['z'])
        source = ROOT / 'tests/target/LibraryProbes'
        identity = {p.name: sha(p) for p in source.iterdir() if p.is_file()}
        report.update(platform=str(args.platform), platform_sha256=qualification.source_inventory(args.platform),
                      config_sha256=sha(args.config), arduino_cli_sha256=sha(args.cli), qemu_sha256=sha(args.qemu),
                      runner_sha256=sha(Path(__file__)), cpp_lock_sha256=sha(args.platform / 'tools/cpp-cli/toolchain-lock.json'),
                      source_sha256=identity, expected_cases=len(cases))
        stage = args.output / ('run-' + uuid.uuid4().hex)
        stage.mkdir()
        save()

        def run_case(board, clock, library, level):
            case = stage / f'{board}-{clock}-{library}-O{level}'
            case.mkdir()
            build = case / 'build'
            command = [str(args.cli), 'compile', '--clean', '--fqbn',
                       f'arduino-stc51:mcs251:{board}:cppcore=enabled,clock={clock // 1000000}m',
                       '--build-path', str(build), '--config-file', str(args.config), '--build-property',
                       f'compiler.cpp.extra_flags=-DSTCXX_CPP_OPT={level} -DSTCXX_LIBRARY_CASE={LIBRARIES.index(library) + 1}', str(source)]
            row = {'status': 'RUNNING', 'board': board, 'clock_hz': clock, 'library': library, 'optimization': level,
                   'command': command, 'path': str(case)}
            try:
                properties_run = subprocess.run([*command[:-1], '--show-properties=expanded', command[-1]],
                                                capture_output=True, timeout=120)
                properties_log = case / 'properties.log'
                properties_log.write_bytes(properties_run.stdout + properties_run.stderr)
                require(properties_run.returncode == 0, 'cannot resolve Arduino properties')
                properties = {}
                for line in properties_run.stdout.decode(errors='replace').splitlines():
                    key, separator, value = line.partition('=')
                    if separator:
                        require(key not in properties, 'duplicate Arduino property: ' + key)
                        properties[key] = value.strip()
                require(Path(properties.get('runtime.platform.path', '')).resolve() == args.platform and
                        properties.get('build.f_cpu', '').rstrip('LlUu') == str(clock) and
                        properties.get('build.variant') == devices[board]['macro'], 'wrong platform, clock or variant')
                row['properties_log_sha256'] = sha(properties_log)
                log = case / 'compile.log'
                with log.open('wb') as stream:
                    completed = subprocess.run(command, stdout=stream, stderr=subprocess.STDOUT, timeout=1200)
                text = log.read_text(errors='replace')
                row.update(compile_exit=completed.returncode, compile_log_sha256=sha(log), compile_log_tail=text[-2400:])
                require(completed.returncode == 0, 'library build failed')
                firmware = build / 'LibraryProbes.ino.hex'
                manifest_file = build / 'stcxx/manifest.json'
                manifest = json.loads(manifest_file.read_text())
                verify_optimization(manifest, level)
                require(manifest['outcome'] == 'pass' and manifest['firmware_sha256'] == sha(firmware) and
                        manifest['lock_sha256'] == report['cpp_lock_sha256'] and
                        manifest['target']['profile'] == 'mcs251' and manifest['target']['build_f_cpu_hz'] == clock,
                        'C++ manifest does not match the selected build')
                size = re.search(r'Sketch uses (\d+) bytes.*?Maximum is (\d+) bytes.*?Global variables use (\d+) bytes', text, re.S)
                require(size is not None, 'missing memory usage report')
                row.update(firmware=str(firmware), firmware_sha256=sha(firmware), cpp_manifest_sha256=sha(manifest_file),
                           arduino_flash_bytes=int(size[1]), flash_capacity_bytes=int(size[2]), arduino_ram_bytes=int(size[3]))
                qemu_command = [sys.executable, str(ROOT / 'scripts/check-qemu-smoke.py'), '--qemu', str(args.qemu),
                                '--firmware', str(firmware), '--board', board, '--expected', str(source / ('expected-' + library + '.txt')),
                                '--output', str(case / 'qemu'), '--timeout', str(args.qemu_timeout)]
                checked = subprocess.run(qemu_command, capture_output=True, timeout=args.qemu_timeout + 30)
                row['qemu'] = json.loads((case / 'qemu/qemu.json').read_text())
                row['uart'] = (case / 'qemu/uart.log').read_text(errors='replace')
                require(checked.returncode == 0 and row['qemu']['status'] == 'PASS' and
                        row['qemu']['firmware_sha256'] == row['firmware_sha256'], 'library target oracle failed')
                require(identity == {p.name: sha(p) for p in source.iterdir() if p.is_file()}, 'test source changed during build')
                row['status'] = 'PASS'
            except Exception as error:
                row.update(status='FAIL', error=str(error))
            (case / 'result.json').write_text(json.dumps(row, indent=2) + '\n', encoding='utf-8')
            return row

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            for future in concurrent.futures.as_completed([pool.submit(run_case, *case) for case in cases]):
                row = future.result()
                report['results'].append(row)
                save()
                print(row['status'], row['board'], row['clock_hz'], row['library'], row['optimization'], flush=True)
        require(helper_inventory() == report['helper_files_sha256'], 'verification helper inputs changed')
        require(qualification.source_inventory(args.platform) == report['platform_sha256'] and
                sha(args.config) == report['config_sha256'] and sha(args.cli) == report['arduino_cli_sha256'] and
                sha(args.qemu) == report['qemu_sha256'] and sha(Path(__file__)) == report['runner_sha256'] and
                identity == {p.name: sha(p) for p in source.iterdir() if p.is_file()}, 'matrix input changed')
        report['final_input_verification'] = 'PASS'
        require(len(report['results']) == len(cases) and all(r['status'] == 'PASS' for r in report['results']), 'failing/incomplete library matrix')
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
