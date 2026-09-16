#!/usr/bin/env python3
"""Exercise Arduino upload recipes and the native uploader without opening hardware."""
import argparse
import json
from pathlib import Path
import subprocess


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ('cli', 'config', 'sdk', 'work'):
        parser.add_argument('--' + key, type=Path, required=True)
    args = parser.parse_args()
    args.work.mkdir(parents=True, exist_ok=True)
    firmware = args.work.resolve() / 'firmware with spaces.hex'
    # Deliberately invalid: the real native tool must reject this before serial I/O.
    firmware.write_text('INVALID HEX FOR UPLOAD RECIPE TEST\n', encoding='ascii')
    devices = json.loads((args.sdk / 'tools/variants/devices.json').read_text(encoding='utf-8'))['devices']
    boards = dict(line.split('=', 1) for line in (args.sdk / 'boards.txt').read_text().splitlines()
                  if line and not line.startswith('#') and '=' in line)
    checks = []
    for device in devices:
        board = device['id']
        require(boards[board + '.upload.tool.serial'] == 'stc-cli', 'missing IDE serial tool: ' + board)
        require(boards[board + '.upload.protocol'] == 'stc-isp', 'missing upload protocol: ' + board)
        variants = [''] + ([':uploadcheck=manual'] if device['upload_requires_manual_model_check'] else [])
        for options in variants:
            label = board + ('-manual' if options else '-default')
            command = [str(args.cli.resolve()), '--config-file', str(args.config.resolve()), 'upload',
                       '--fqbn', 'arduino-stc51:mcs251:' + board + options,
                       '--port', 'STC_NONEXISTENT_UPLOAD_TEST', '--input-file', str(firmware), '--verbose']
            result = subprocess.run([*command, '--dry-run'], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=30)
            output = result.stdout.decode(errors='replace')
            (args.work / (label + '.log')).write_text(output, encoding='utf-8')
            require(result.returncode == 0, output)
            require('{' not in output and '--expect "' + device['model'] + '"' in output, output)
            require('firmware with spaces.hex"' in output and '--port "STC_NONEXISTENT_UPLOAD_TEST"' in output, output)
            require(('--force-unverified-target' in output) == bool(options), output)
            require('--execution-mode mcs251' in output and '--allow-experimental' in output, output)
            if board == 'stc32g8k64':
                failed = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=30)
                failure = failed.stdout.decode(errors='replace')
                (args.work / 'native-invalid-hex.log').write_text(failure, encoding='utf-8')
                require(failed.returncode != 0 and 'exit status' in failure and 'hex' in failure.lower(), failure)
                require('Property ' not in failure and 'executable file not found' not in failure, failure)
                checks.append('native invalid HEX rejection and failure propagation')
            checks.append(label)
    (args.work / 'report.json').write_text(json.dumps({'status': 'PASS', 'checks': checks}, indent=2) + '\n')
    print('PASS: native uploader, spaced paths, failure propagation and all 10 board upload recipes')


if __name__ == '__main__':
    main()
