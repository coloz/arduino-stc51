#!/usr/bin/env python3
"""Qualify a staged release with Arduino CLI and offline stc-cli validation."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('platform', 'config', 'stc', 'output', 'host'):
        parser.add_argument('--' + name, required=True)
    parser.add_argument('--cli', default='arduino-cli')
    args = parser.parse_args()
    platform = Path(args.platform).resolve()
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    devices = json.loads((platform / 'tools/variants/devices.json').read_text(encoding='utf-8'))['devices']
    report = {'host': args.host, 'scope': 'plain-C Blink compile/link, HEX integrity/capacity, offline programmer validation; no hardware or C++ qualification',
              'devices_sha256': sha256(platform / 'tools/variants/devices.json'),
              'stc_cli_sha256': sha256(args.stc), 'results': []}

    def run(command, log, expected=0):
        result = subprocess.run([str(x) for x in command], stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        (output / log).write_bytes(result.stdout)
        if result.returncode != expected:
            raise RuntimeError(f'{log}: exit {result.returncode}, expected {expected}\n' + result.stdout.decode(errors='replace')[-4000:])
        return result.stdout.decode(errors='replace')

    report['arduino_cli_version'] = run([args.cli, 'version'], 'arduino-version.log').strip()
    report['stc_cli_version'] = run([args.stc, '--version'], 'stc-version.log').strip()
    for device in devices:
        modes = ['mcs51', 'mcs251'] if device['target'] == 'dual' else [device['target']]
        for mode in modes:
            label = device['id'] + '-' + mode
            fqbn = 'arduino-stc51:mcs51:' + device['id']
            if device['target'] == 'dual':
                fqbn += ':execution=' + mode
            build = output / label
            command = [args.cli, 'compile', '--clean', '--fqbn', fqbn, '--build-path', build, '--config-file', args.config, platform / 'examples/Blink']
            run(command, label + '-compile.log')
            hexes = list(build.glob('*.hex'))
            assert len(hexes) == 1, (label, 'expected one HEX')
            firmware = hexes[0]
            memory = {}
            upper = 0
            eof = False
            for line in firmware.read_text().splitlines():
                assert line.startswith(':') and not eof, (label, 'invalid HEX record')
                data = bytes.fromhex(line[1:])
                assert len(data) == data[0] + 5 and sum(data) % 256 == 0, (label, 'bad HEX checksum/length')
                count, address, kind = data[0], int.from_bytes(data[1:3], 'big'), data[3]
                if kind == 0:
                    for i, value in enumerate(data[4:4+count]):
                        absolute = upper + address + i
                        assert absolute not in memory or memory[absolute] == value, (label, 'overlap')
                        memory[absolute] = value
                elif kind == 4:
                    upper = int.from_bytes(data[4:6], 'big') << 16
                elif kind == 2:
                    upper = int.from_bytes(data[4:6], 'big') << 4
                elif kind == 1:
                    eof = True
                else:
                    raise AssertionError((label, 'unexpected HEX type', kind))
            assert memory and eof, (label, 'empty/missing EOF')
            linker = (device['mcs251_linker'] if device['target'] == 'dual' else device['linker']) if mode == 'mcs251' else {}
            floor = 0 if mode == 'mcs51' else linker.get('flash_loc', 0x1000000 - device['flash_bytes'])
            assert floor <= min(memory) <= max(memory) < floor + device['flash_bytes'], (label, 'outside flash window')
            assert len(memory) <= device['maximum_code_bytes'], (label, 'code capacity')
            if mode == 'mcs251':
                assert linker['code_loc'] in memory, (label, 'missing reset HOME')
            validation = run([args.stc, 'validate', '--expect', device['model'], '--file', firmware, '--execution-mode', mode, '--json'], label + '-validate.json')
            json.loads(validation)
            report['results'].append({'profile': label, 'fqbn': fqbn, 'status': 'PASS', 'firmware_sha256': sha256(firmware), 'bytes': len(memory), 'first_address': min(memory), 'last_address': max(memory)})
            print('PASS', label, len(memory), flush=True)
    # Exercise the cached Arduino build path and ensure it preserves firmware.
    before = sha256(firmware)
    run([x for x in command if x != '--clean'], 'cache-compile.log')
    assert sha256(firmware) == before, 'cached firmware changed'
    report['cache_rebuild'] = 'PASS'
    bad = output / 'bad-checksum.hex'
    bad.write_text(':0100000000FE\n:00000001FF\n')
    run([args.stc, 'validate', '--expect', 'STC8G1K08A', '--file', bad], 'bad-hex.log', expected=8)
    for removed in ('STC8A8K64S4A12', 'STC32F12K54'):
        run([args.stc, 'validate', '--expect', removed, '--file', firmware], removed + '-removed.log', expected=9)
    report['negative_validation'] = 'PASS'
    report['status'] = 'PASS'
    (output / 'qualification.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(f"PASS: {len(report['results'])} execution profiles on {args.host}")


if __name__ == '__main__':
    main()
