#!/usr/bin/env python3
"""Qualify a staged release with Arduino CLI and offline stc-cli validation."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def require(condition, message):
    # Qualification checks must remain active with python -O as well.
    if not condition:
        raise RuntimeError(str(message))


def source_inventory(platform):
    files = [platform / name for name in ('platform.txt', 'boards.txt')]
    files.extend(platform / name for name in ('platform.local.txt', 'boards.local.txt')
                 if (platform / name).is_file())
    for directory in ('cores', 'variants', 'libraries', 'tools', 'examples'):
        files.extend(p for p in (platform / directory).rglob('*') if p.is_file()
                     and '__pycache__' not in p.parts and p.suffix not in ('.pyc', '.pyo'))
    return {p.relative_to(platform).as_posix(): sha256(p) for p in sorted(files)}


def executable_path(value):
    path = Path(value)
    if path.is_file():
        return path.resolve()
    found = shutil.which(str(value))
    require(found, f'executable does not exist: {value}')
    return Path(found).resolve()


def tool_inventory(properties):
    roots = sorted({str(Path(value).resolve()) for key, value in properties.items()
                    if key.startswith('runtime.tools.') and key.endswith('.path')})
    require(roots, 'Arduino properties contain no installed tool roots')
    files = {}
    for root in map(Path, roots):
        require(root.is_dir(), f'missing installed tool directory: {root}')
        entries = {p.relative_to(root).as_posix(): sha256(p) for p in sorted(root.rglob('*'))
                   if p.is_file() and '__pycache__' not in p.parts and p.suffix not in ('.pyc', '.pyo')}
        require(entries, f'empty installed tool directory: {root}')
        files[str(root)] = entries
    executables = {}
    for key, directory in (('compiler.c.cmd', 'compiler.path'),
                           ('compiler.cpp.cmd', 'compiler.path'),
                           ('compiler.c.elf.cmd', 'compiler.path'),
                           ('compiler.ar.cmd', 'compiler.ar.path')):
        require(key in properties and directory in properties, f'missing Arduino property: {key}/{directory}')
        path = executable_path(Path(properties[directory]) / properties[key])
        require(any(Path(root) in path.parents for root in roots),
                f'{key} is outside the inventoried tool directories: {path}')
        executables[key] = {'path': str(path), 'sha256': sha256(path)}
    require('compiler.shell.cmd' in properties, 'missing Arduino shell property')
    shell = executable_path(properties['compiler.shell.cmd'])
    executables['compiler.shell.cmd'] = {'path': str(shell), 'sha256': sha256(shell)}
    return {'files': files, 'executables': executables}


def execution_profiles(devices, all_clocks):
    profiles = []
    for device in devices:
        clocks = device['clock_options_hz'] if all_clocks else [None]
        require(clocks and len(clocks) == len(set(clocks)), 'empty or duplicate clock inventory')
        for clock in clocks:
            if clock is not None:
                require(isinstance(clock, int) and clock > 0 and clock % 1000000 == 0,
                        f'unsupported clock menu encoding: {clock}')
            label = device['id'] + '-mcs251'
            fqbn = 'stc:mcs251:' + device['id']
            if clock is not None:
                label += f'-{clock // 1000000}m'
                fqbn += f':clock={clock // 1000000}m'
            profiles.append((device, label, fqbn, clock or device['default_clock_hz']))
    return profiles


def save_report(output, report):
    pending = output / 'qualification.json.part'
    pending.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    pending.replace(output / 'qualification.json')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('platform', 'config', 'stc', 'output', 'host'):
        parser.add_argument('--' + name, required=True)
    parser.add_argument('--cli', default='arduino-cli')
    parser.add_argument('--all-clocks', action='store_true',
                        help='compile every declared board/clock combination')
    parser.add_argument('--build-property', action='append', default=[],
                        help='explicit Arduino property override, recorded with the evidence')
    parser.add_argument('--timeout', type=float, default=600,
                        help='maximum seconds per CLI invocation')
    args = parser.parse_args(argv)
    platform = Path(args.platform).resolve()
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    report = {'host': args.host, 'scope': 'C++ Blink compile/link, HEX integrity/capacity, offline programmer validation; no hardware qualification',
              'status': 'RUNNING', 'results': [],
              'started_utc': datetime.now(timezone.utc).isoformat()}
    # Replace stale success even when input loading or the first tool fails.
    save_report(output, report)
    try:
        require(output != platform and platform not in output.parents,
                'Qualification output must be outside the staged platform')
        require(args.timeout > 0, 'timeout must be positive')
        qualify(args, platform, output, report)
        report['status'] = 'PASS'
    except (Exception, KeyboardInterrupt) as error:
        report['status'] = 'FAIL'
        report['error'] = str(error) or type(error).__name__
        print(f"FAIL: {report['error']}", file=sys.stderr)
    finally:
        report['finished_utc'] = datetime.now(timezone.utc).isoformat()
        save_report(output, report)
    return 0 if report['status'] == 'PASS' else 1


def qualify(args, platform, output, report):
    devices_path = platform / 'tools/variants/devices.json'
    devices = json.loads(devices_path.read_text(encoding='utf-8'))['devices']
    require(devices and len({d['id'] for d in devices}) == len(devices),
            'empty or duplicate device inventory')
    require(all(d['target'] == 'mcs251' for d in devices), 'retired target in inventory')
    report['source_sha256'] = source_inventory(platform)
    report['qualifier_sha256'] = sha256(__file__)
    report['devices_sha256'] = sha256(devices_path)
    report['config_sha256'] = sha256(args.config)
    report['stc_cli_sha256'] = sha256(args.stc)
    args.cli = str(executable_path(args.cli))
    report['arduino_cli_path'] = args.cli
    report['arduino_cli_sha256'] = sha256(args.cli)
    report['build_properties'] = args.build_property
    tool_properties = None

    def run(command, log, expected=0):
        report['stage'] = log
        save_report(output, report)
        try:
            result = subprocess.run([str(x) for x in command], stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, timeout=args.timeout)
        except subprocess.TimeoutExpired as error:
            (output / log).write_bytes(error.stdout or b'')
            raise RuntimeError(f'{log}: exceeded {args.timeout}s') from error
        (output / log).write_bytes(result.stdout)
        if result.returncode != expected:
            raise RuntimeError(f'{log}: exit {result.returncode}, expected {expected}\n' + result.stdout.decode(errors='replace')[-4000:])
        return result.stdout.decode(errors='replace')

    report['arduino_cli_version'] = run([args.cli, 'version'], 'arduino-version.log').strip()
    report['stc_cli_version'] = run([args.stc, '--version'], 'stc-version.log').strip()
    profiles = execution_profiles(devices, args.all_clocks)
    report['expected_profiles'] = len(profiles)
    for device, label, fqbn, clock in profiles:
        mode = device['target']
        build = output / label
        command = [args.cli, 'compile', '--clean', '--fqbn', fqbn, '--build-path', build, '--config-file', args.config, platform / 'examples/Blink']
        for value in args.build_property:
            command[-1:-1] = ['--build-property', value]
        properties = run([*command[:-1], '--show-properties=expanded', command[-1]],
                         label + '-properties.log')
        selected = [line.partition('=')[2].strip() for line in properties.splitlines()
                    if line.startswith('runtime.platform.path=')]
        require(len(selected) == 1 and Path(selected[0]).resolve() == platform,
                f'{label}: Arduino selected a different platform')
        parsed = {}
        for line in properties.splitlines():
            key, separator, value = line.partition('=')
            if separator:
                require(key not in parsed, f'{label}: duplicate Arduino property: {key}')
                parsed[key] = value.strip()
        require(parsed.get('build.f_cpu', '').rstrip('Ll') == str(clock),
                f'{label}: selected clock does not match the device profile')
        require('-DSTCXX_CPP_CORE=1' in parsed.get('build.cpp_core_flags', '') and
                '-DSTCXX_CPP_CORE=1' in parsed.get('build.cpp_link_flags', ''),
                f'{label}: default build did not enable the C++ compiler and linker')
        require(not any('cppcore' in key for key in parsed),
                f'{label}: removed language menu is still exposed')
        relevant = {key: value for key, value in parsed.items()
                    if key.startswith('runtime.tools.') or key in
                    ('compiler.path', 'compiler.ar.path', 'compiler.c.cmd', 'compiler.cpp.cmd',
                     'compiler.c.elf.cmd', 'compiler.ar.cmd', 'compiler.shell.cmd')}
        if tool_properties is None:
            tool_properties = relevant
            report['tool_properties'] = relevant
            report['toolchain_sha256'] = tool_inventory(relevant)
        else:
            require(relevant == tool_properties, f'{label}: selected toolchain changed')
        run(command, label + '-compile.log')
        manifest = json.loads((build / 'stcxx/manifest.json').read_text(encoding='utf-8'))
        require(manifest.get('outcome') == 'pass', f'{label}: C++ link audits did not finish')
        hexes = list(build.glob('*.hex'))
        require(len(hexes) == 1, (label, 'expected one HEX'))
        firmware = hexes[0]
        memory = {}
        upper = 0
        eof = False
        for line in firmware.read_text().splitlines():
            require(line.startswith(':') and not eof, (label, 'invalid HEX record'))
            data = bytes.fromhex(line[1:])
            require(len(data) >= 5 and len(data) == data[0] + 5 and sum(data) % 256 == 0, (label, 'bad HEX checksum/length'))
            count, address, kind = data[0], int.from_bytes(data[1:3], 'big'), data[3]
            if kind == 0:
                require(address + count <= 0x10000, (label, 'HEX record crosses address boundary'))
                for i, value in enumerate(data[4:4+count]):
                    absolute = upper + address + i
                    require(absolute not in memory, (label, 'overlap'))
                    memory[absolute] = value
            elif kind == 4:
                require(count == 2 and address == 0, (label, 'invalid linear address record'))
                upper = int.from_bytes(data[4:6], 'big') << 16
            elif kind == 2:
                require(count == 2 and address == 0, (label, 'invalid segment address record'))
                upper = int.from_bytes(data[4:6], 'big') << 4
            elif kind == 1:
                require(count == 0 and address == 0, (label, 'invalid EOF record'))
                eof = True
            else:
                raise RuntimeError((label, 'unexpected HEX type', kind))
        require(memory and eof, (label, 'empty/missing EOF'))
        require(mode == 'mcs251', 'only MCS251 is supported')
        linker = device['linker']
        floor = linker.get('flash_loc', 0x1000000 - device['flash_bytes'])
        require(floor <= min(memory) <= max(memory) < floor + device['flash_bytes'], (label, 'outside flash window'))
        require(len(memory) <= device['maximum_code_bytes'], (label, 'code capacity'))
        if mode == 'mcs251':
            require(linker['code_loc'] in memory, (label, 'missing reset HOME'))
        validation = run([args.stc, 'validate', '--expect', device['model'], '--file', firmware, '--execution-mode', mode, '--json'], label + '-validate.json')
        validated = json.loads(validation)
        require(isinstance(validated, dict) and validated.get('valid') is True and
                isinstance(validated.get('device'), dict) and
                validated['device'].get('name') == device['model'] and
                validated.get('execution_mode') == mode and
                validated.get('input_bytes') == len(memory) and
                validated.get('base_address') == min(memory) and
                Path(validated.get('file', '')).resolve() == firmware.resolve(),
                f'{label}: programmer validation does not describe this firmware/profile')
        report['results'].append({'profile': label, 'fqbn': fqbn, 'clock_hz': clock, 'status': 'PASS', 'firmware_sha256': sha256(firmware), 'bytes': len(memory), 'first_address': min(memory), 'last_address': max(memory)})
        print('PASS', label, len(memory), flush=True)
    # Exercise the cached Arduino build path and ensure it preserves firmware.
    before = sha256(firmware)
    run([x for x in command if x != '--clean'], 'cache-compile.log')
    require(sha256(firmware) == before, 'cached firmware changed')
    report['cache_rebuild'] = 'PASS'
    bad = output / 'bad-checksum.hex'
    bad.write_text(':0100000000FE\n:00000001FF\n')
    run([args.stc, 'validate', '--expect', 'STC32G12K128', '--file', bad], 'bad-hex.log', expected=8)
    report['negative_validation'] = 'PASS'
    require(source_inventory(platform) == report['source_sha256'],
            'platform sources changed during qualification')
    require(sha256(args.config) == report['config_sha256'] and
            sha256(args.stc) == report['stc_cli_sha256'], 'qualification inputs changed')
    require(sha256(args.cli) == report['arduino_cli_sha256'] and
            tool_inventory(tool_properties) == report['toolchain_sha256'],
            'qualification toolchain changed')
    require(sha256(__file__) == report['qualifier_sha256'], 'qualification script changed')
    print(f"PASS: {len(report['results'])} execution profiles on {args.host}")


if __name__ == '__main__':
    sys.exit(main())
