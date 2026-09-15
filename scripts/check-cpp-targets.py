#!/usr/bin/env python3
"""Build, execute and validate C++ ABI probes for declared MCS251 profiles.

Default coverage is ReturnIdentity and NativeCallbacks at O0/Oz on every
declared C++ board/clock combination. Library and physical-hardware gates
remain separate; a successful subset is never reported as full coverage.
HeapTelemetry, StepperPhases and SerialReceive are explicitly selected regressions.
RuntimeArithmetic checks native C library division and checked arithmetic.
SmallControl is a separate basic application probe for resource-limited devices;
its success does not claim support for complex library combinations.
"""
import argparse
import concurrent.futures
from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path, PureWindowsPath
import re
import shutil
import signal
import subprocess
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('qualification', Path(__file__).with_name('qualify-release.py'))
qualification = importlib.util.module_from_spec(spec)
spec.loader.exec_module(qualification)
sha, require = qualification.sha256, qualification.require
BASELINE_PROBES = ('ReturnIdentity', 'NativeCallbacks')
PROBES = (*BASELINE_PROBES, 'HeapTelemetry', 'StepperPhases', 'SerialReceive', 'SmallControl', 'RuntimeArithmetic')
LEVELS = ('0', 'z')


def profiles(devices, boards=None, clocks=None, probes=None, levels=None):
    require(isinstance(devices, list) and devices, 'empty device inventory')
    by_id = {device['id']: device for device in devices}
    require(len(by_id) == len(devices), 'duplicate device inventory')
    boards = list(by_id) if boards is None else boards
    probes = list(BASELINE_PROBES) if probes is None else probes
    levels = list(LEVELS) if levels is None else levels
    for values in (boards, probes, levels):
        require(values and len(values) == len(set(values)), 'empty or duplicate C++ matrix selection')
    require(all(board in by_id for board in boards), 'unknown C++ board')
    require(all(probe in PROBES for probe in probes), 'unknown C++ probe')
    require(all(level in LEVELS for level in levels), 'unsupported baseline optimization')
    require(clocks is None or clocks and len(clocks) == len(set(clocks)), 'empty or duplicate clock selection')
    cases = []
    for board in boards:
        device = by_id[board]
        # The variant generator declares 12 MHz when this optional per-board
        # field is absent; the actual expanded clock is also checked per build.
        supported = device.get('cpp_mcs251_clock_options_hz', [12000000])
        require(device['target'] == 'mcs251' and isinstance(supported, list) and supported
                and len(supported) == len(set(supported)), 'missing or invalid declared C++ clocks: ' + board)
        selected = supported if clocks is None else clocks
        require(all(type(clock) is int and clock > 0 and clock % 1000000 == 0 and clock in supported
                    for clock in selected), 'unsupported C++ clock: ' + board)
        cases.extend((board, clock, probe, level) for clock in selected for probe in probes for level in levels)
    return cases


def tree_inventory(root):
    require(root.is_dir(), 'missing input tree: ' + str(root))
    result = {p.relative_to(root).as_posix(): sha(p) for p in sorted(root.rglob('*'))
              if p.is_file() and '__pycache__' not in p.parts and p.suffix not in ('.pyc', '.pyo')}
    require(result, 'empty input tree: ' + str(root))
    return result


def read_hex(path, device):
    """Independently enforce the actual device window and populated-byte budget."""
    memory, upper, eof = {}, 0, False
    for line in path.read_text(encoding='ascii').splitlines():
        require(line.startswith(':') and not eof, 'invalid HEX record or data after EOF')
        data = bytes.fromhex(line[1:])
        require(len(data) >= 5 and len(data) == data[0] + 5 and sum(data) % 256 == 0,
                'bad HEX checksum/length')
        count, address, kind = data[0], int.from_bytes(data[1:3], 'big'), data[3]
        if kind == 0:
            require(address + count <= 0x10000, 'HEX record crosses address boundary')
            for offset, value in enumerate(data[4:4 + count]):
                absolute = upper + address + offset
                require(absolute not in memory, 'overlapping HEX records')
                memory[absolute] = value
        elif kind in (2, 4):
            require(count == 2 and address == 0, 'invalid HEX address record')
            upper = int.from_bytes(data[4:6], 'big') << (4 if kind == 2 else 16)
        elif kind == 1:
            require(count == 0 and address == 0, 'invalid HEX EOF record')
            eof = True
        else:
            raise RuntimeError('unsupported HEX record type')
    require(memory and eof, 'empty HEX or missing EOF')
    floor = device['linker'].get('flash_loc', 0x1000000 - device['flash_bytes'])
    require(floor <= min(memory) <= max(memory) < floor + device['flash_bytes'], 'firmware outside device Flash window')
    require(len(memory) <= device['maximum_code_bytes'], 'firmware exceeds device code capacity')
    require(device['linker']['code_loc'] in memory, 'missing reset HOME')
    return {'bytes': len(memory), 'first_address': min(memory), 'last_address': max(memory)}


def check_validation(value, device, filename, image, windows_paths=False):
    path_type = PureWindowsPath if windows_paths else Path
    require(isinstance(value, dict) and value.get('valid') is True
            and isinstance(value.get('device'), dict) and value['device'].get('name') == device['model']
            and value.get('execution_mode') == 'mcs251'
            and type(value.get('input_bytes')) is int and value['input_bytes'] == image['bytes']
            and type(value.get('base_address')) is int and value['base_address'] == image['first_address']
            and isinstance(value.get('file'), str) and path_type(value['file']) == path_type(filename),
            'programmer validation does not describe this firmware/profile')


def verify_cpp_manifest(manifest, device, clock, level, firmware, lock_sha):
    require(manifest.get('outcome') == 'pass' and manifest.get('firmware_sha256') == sha(firmware)
            and manifest.get('lock_sha256') == lock_sha, 'C++ manifest does not match firmware/lock')
    target = manifest.get('target', {})
    require(target.get('profile') == device['target'] == 'mcs251'
            and target.get('build_f_cpu_hz') == clock, 'C++ manifest target/clock mismatch')
    modules = manifest.get('modules')
    require(isinstance(modules, list) and modules and all(module.get('clang_optimization') == '-O' + level for module in modules),
            'C++ module optimization mismatch')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('platform', 'config', 'cli', 'qemu', 'stc', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    frontend_group = parser.add_mutually_exclusive_group(required=True)
    frontend_group.add_argument('--frontend', type=Path, help='explicit development frontend package')
    frontend_group.add_argument('--installed-frontend', action='store_true',
                                help='use the exact Arduino dependency without STCXX tool overrides')
    parser.add_argument('--stc-windows-paths', action='store_true', help='use WSL interop with a Windows stc-cli executable')
    parser.add_argument('--board', action='append')
    parser.add_argument('--clock', action='append', type=int)
    parser.add_argument('--probe', action='append', choices=PROBES)
    parser.add_argument('--optimization', action='append', choices=LEVELS)
    parser.add_argument('--jobs', type=int, default=2)
    parser.add_argument('--build-timeout', type=float, default=1200)
    args = parser.parse_args(argv)
    for name in ('platform', 'config', 'cli', 'qemu', 'stc', 'frontend', 'output'):
        if getattr(args, name) is not None:
            setattr(args, name, getattr(args, name).resolve())
    for source in filter(None, (args.platform, args.frontend, ROOT / 'tests', ROOT / 'scripts')):
        if args.output == source or source in args.output.parents or args.output in source.parents:
            parser.error('output must be separate from platform, frontend and test sources')
    args.output.mkdir(parents=True, exist_ok=True)
    stage = args.output / ('run-' + uuid.uuid4().hex)
    stage.mkdir()
    report = {'schema_version': 1, 'status': 'RUNNING', 'production_qualified': False,
              'scope': __doc__, 'started_utc': datetime.now(timezone.utc).isoformat(), 'stage': str(stage), 'results': []}

    def save():
        pending = args.output / 'cpp-targets.json.part'
        pending.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
        pending.replace(args.output / 'cpp-targets.json')

    env = os.environ.copy()
    save()
    try:
        require(sys.platform.startswith('linux'), 'run on Linux/WSL')
        require(1 <= args.jobs <= 4 and 0 < args.build_timeout <= 3600, 'invalid concurrency/timeout')
        require(not any(key.startswith('STCXX_') for key in env), 'ambient STCXX overrides are unsupported; pass --frontend')
        env['PYTHONDONTWRITEBYTECODE'] = '1'
        if args.installed_frontend:
            lock_path = args.platform / 'tools/cpp-cli/toolchain-lock.json'
            lock = json.loads(lock_path.read_text(encoding='utf-8'))
            helper = args.platform / 'tools/cpp-cli/toolchain-paths.sh'
            require(sha(helper) == lock['pipeline_helpers']['toolchain_paths']['sha256'],
                    'frontend discovery helper differs from lock')
            discovery = subprocess.run(['sh', '-c', '. "$1"; stcxx_installed_frontend_root "$2" "$3"',
                                        'discover', str(helper), str(args.platform), str(lock_path)],
                                       env=env, capture_output=True, text=True, timeout=30)
            require(discovery.returncode == 0 and discovery.stdout.strip(),
                    'installed frontend discovery failed: ' + discovery.stderr)
            args.frontend = Path(discovery.stdout.strip()).resolve(strict=True)
            require(args.frontend.is_dir() and args.output != args.frontend
                    and args.frontend not in args.output.parents and args.output not in args.frontend.parents,
                    'invalid installed frontend/output layout')
            report['frontend_selection'] = 'exact Arduino dependency; no tool environment override'
        else:
            env['STCXX_CPP_TOOLS_ROOT'] = str(args.frontend)
        devices_path = args.platform / 'tools/variants/devices.json'
        require(sha(devices_path) == sha(ROOT / 'tools/variants/devices.json'), 'staged and test-runner device inventories differ')
        devices = json.loads(devices_path.read_text(encoding='utf-8'))['devices']
        by_id = {device['id']: device for device in devices}
        cases = profiles(devices, args.board, args.clock, args.probe, args.optimization)
        required_cases = profiles(devices)
        report.update(platform=str(args.platform), platform_sha256=qualification.source_inventory(args.platform),
                      frontend=str(args.frontend), frontend_sha256=tree_inventory(args.frontend),
                      cpp_lock_sha256=sha(args.platform / 'tools/cpp-cli/toolchain-lock.json'),
                      expected_cases=len(cases), required_cases=[list(case) for case in required_cases],
                      selected_cases=[list(case) for case in cases], full_baseline_coverage=set(cases) == set(required_cases),
                      environment_overrides=({} if args.installed_frontend else {'STCXX_CPP_TOOLS_ROOT': str(args.frontend)}),
                      stc_windows_paths=args.stc_windows_paths)
        helper_files = [Path(__file__), Path(qualification.__file__), ROOT / 'scripts/check-qemu-smoke.py',
                        ROOT / 'tools/variants/devices.json', args.cli, args.qemu, args.stc, args.config,
                        Path(sys.executable).resolve()]
        if args.stc_windows_paths:
            located_wslpath = shutil.which('wslpath')
            require(located_wslpath, 'wslpath is required for Windows programmer paths')
            # wslpath is a multicall symlink to /init. Preserve argv[0]'s
            # basename while hashing the executable bytes through that link.
            wslpath = Path(located_wslpath).absolute()
            helper_files.append(wslpath)
            require(args.stc.read_bytes()[:2] == b'MZ', '--stc-windows-paths requires a Windows executable')
        else:
            wslpath = None
        report['input_files_sha256'] = {str(path): sha(path) for path in helper_files}
        source_hashes = {probe: tree_inventory(ROOT / 'tests/target' / probe) for probe in PROBES}
        report['probe_sources_sha256'] = source_hashes
        save()

        def run(row, case, name, command, timeout=120, allowed=(0,)):
            command = list(map(str, command))
            stdout_log, stderr_log = case / (name + '.stdout'), case / (name + '.stderr')
            entry = {'name': name, 'command': command, 'exit_code': None}
            row['commands'].append(entry)
            try:
                with stdout_log.open('xb') as stdout, stderr_log.open('xb') as stderr:
                    process = subprocess.Popen(command, stdout=stdout, stderr=stderr, env=env, start_new_session=True)
                    try:
                        code = process.wait(timeout=timeout)
                        entry['exit_code'] = code
                    except (subprocess.TimeoutExpired, KeyboardInterrupt) as error:
                        entry['error'] = type(error).__name__
                        os.killpg(process.pid, signal.SIGTERM)
                        try:
                            process.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            os.killpg(process.pid, signal.SIGKILL)
                            process.wait(timeout=5)
                        raise
            finally:
                for key, path in (('stdout_sha256', stdout_log), ('stderr_sha256', stderr_log)):
                    if path.is_file():
                        entry[key] = sha(path)
            require(code in allowed, f'{name} exited {code}; see {stdout_log} and {stderr_log}')
            return stdout_log.read_text(encoding='utf-8', errors='replace')

        def windows_filename(row, case, path, name):
            return run(row, case, name, [wslpath, '-w', path]).strip() if wslpath else str(path)

        def compile_command(board, clock, probe, level, build):
            return [args.cli, 'compile', '--clean', '--fqbn',
                    f'arduino-stc51:mcs251:{board}:cppcore=enabled,clock={clock // 1000000}m',
                    '--build-path', build, '--config-file', args.config, '--build-property',
                    f'compiler.cpp.extra_flags=-DSTCXX_CPP_OPT={level}', ROOT / 'tests/target' / probe]

        def properties_for(row, case, command, board, clock):
            text = run(row, case, 'properties', [*command[:-1], '--show-properties=expanded', command[-1]])
            properties = {}
            for line in text.splitlines():
                key, separator, value = line.partition('=')
                if separator:
                    require(key not in properties, 'duplicate Arduino property: ' + key)
                    properties[key] = value.strip()
            require(Path(properties.get('runtime.platform.path', '')).resolve() == args.platform
                    and properties.get('build.f_cpu', '').rstrip('LlUu') == str(clock)
                    and properties.get('build.variant') == by_id[board]['macro'], 'wrong platform, clock or variant')
            return {key: value for key, value in properties.items()
                    if key.startswith('runtime.tools.') or key in ('compiler.path', 'compiler.ar.path', 'compiler.c.cmd',
                        'compiler.cpp.cmd', 'compiler.c.elf.cmd', 'compiler.ar.cmd', 'compiler.shell.cmd')}

        preflight = {'commands': []}
        report['preflight'] = preflight
        first_board, first_clock, first_probe, first_level = cases[0]
        command = compile_command(*cases[0], stage / 'preflight-build')
        tool_properties = properties_for(preflight, stage, command, first_board, first_clock)
        report.update(preflight=preflight, tool_properties=tool_properties,
                      toolchain_sha256=qualification.tool_inventory(tool_properties))
        # Fail before lengthy builds if the programmer cannot execute or path
        # conversion is wrong; this also verifies rejection of corrupted HEX.
        run(preflight, stage, 'stc-version', [args.stc, '--version'])
        bad = stage / 'bad-checksum.hex'
        bad.write_text(':0100000000FE\n:00000001FF\n', encoding='ascii')
        bad_name = windows_filename(preflight, stage, bad, 'bad-hex-path')
        run(preflight, stage, 'bad-hex', [args.stc, 'validate', '--expect', by_id[first_board]['model'], '--file', bad_name], allowed=(8,))
        report['negative_validation'] = 'PASS'
        save()

        def run_case(board, clock, probe, level):
            case = stage / f'{board}-{clock}-{probe}-O{level}'
            case.mkdir()
            row = {'status': 'RUNNING', 'board': board, 'clock_hz': clock, 'probe': probe,
                   'optimization': level, 'path': str(case), 'commands': []}
            try:
                build = case / 'build'
                command = compile_command(board, clock, probe, level, build)
                require(properties_for(row, case, command, board, clock) == tool_properties, 'selected toolchain changed')
                text = run(row, case, 'compile', command, timeout=args.build_timeout)
                firmware = build / (probe + '.ino.hex')
                require(list(build.glob('*.hex')) == [firmware], 'expected exactly this build\'s HEX')
                manifest_path = build / 'stcxx/manifest.json'
                manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
                verify_cpp_manifest(manifest, by_id[board], clock, level, firmware, report['cpp_lock_sha256'])
                image = read_hex(firmware, by_id[board])
                size = re.search(r'Sketch uses (\d+) bytes.*?Maximum is (\d+) bytes.*?Global variables use (\d+) bytes', text, re.S)
                require(size is not None and int(size[2]) == by_id[board]['maximum_code_bytes']
                        and image['bytes'] <= int(size[1]) <= int(size[2]),
                        'Arduino capacity/usage differs from device and HEX')
                row.update(firmware=str(firmware), firmware_sha256=sha(firmware), image=image,
                           cpp_manifest_sha256=sha(manifest_path), arduino_flash_bytes=int(size[1]),
                           flash_capacity_bytes=int(size[2]), arduino_ram_bytes=int(size[3]))
                expected = ROOT / 'tests/target' / probe / 'expected-uart.txt'
                run(row, case, 'qemu', [sys.executable, ROOT / 'scripts/check-qemu-smoke.py', '--qemu', args.qemu,
                    '--firmware', firmware, '--board', board, '--expected', expected, '--output', case / 'qemu'], timeout=90)
                qemu_report = json.loads((case / 'qemu/qemu.json').read_text(encoding='utf-8'))
                uart = case / 'qemu/uart.log'
                require(qemu_report['status'] == 'PASS' and qemu_report['board'] == board
                        and qemu_report['firmware_sha256'] == sha(firmware) and qemu_report['qemu_sha256'] == sha(args.qemu)
                        and qemu_report['oracle_sha256'] == sha(expected) and qemu_report['uart_sha256'] == sha(uart)
                        and uart.read_bytes().replace(b'\r\n', b'\n') == expected.read_bytes().replace(b'\r\n', b'\n'),
                        'target execution evidence mismatch')
                filename = windows_filename(row, case, firmware, 'firmware-path')
                validated = json.loads(run(row, case, 'validate', [args.stc, 'validate', '--expect', by_id[board]['model'],
                    '--file', filename, '--execution-mode', 'mcs251', '--json']))
                check_validation(validated, by_id[board], filename, image, args.stc_windows_paths)
                require(sha(firmware) == row['firmware_sha256'], 'firmware changed during validation')
                row.update(qemu=qemu_report, validation=validated, uart_sha256=sha(uart), status='PASS')
            except Exception as error:
                row.update(status='FAIL', error=str(error) or type(error).__name__)
            (case / 'result.json').write_text(json.dumps(row, indent=2) + '\n', encoding='utf-8')
            return row

        with concurrent.futures.ThreadPoolExecutor(max_workers=args.jobs) as pool:
            for future in concurrent.futures.as_completed([pool.submit(run_case, *case) for case in cases]):
                row = future.result()
                report['results'].append(row)
                save()
                print(row['status'], row['board'], row['clock_hz'], row['probe'], row['optimization'], flush=True)
        require(qualification.source_inventory(args.platform) == report['platform_sha256'], 'platform inputs changed')
        require(qualification.tool_inventory(tool_properties) == report['toolchain_sha256'], 'installed toolchain changed')
        require(tree_inventory(args.frontend) == report['frontend_sha256'], 'frontend inputs changed')
        require(all(sha(Path(path)) == value for path, value in report['input_files_sha256'].items()), 'helper/tool/config input changed')
        require({probe: tree_inventory(ROOT / 'tests/target' / probe) for probe in PROBES} == source_hashes, 'probe sources changed')
        report['final_input_verification'] = 'PASS'
        require(len(report['results']) == len(cases) and all(row['status'] == 'PASS' for row in report['results']), 'failing/incomplete C++ matrix')
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
