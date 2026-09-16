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
    parser.add_argument('--board', action='append', help='Limit checks to specific board IDs')
    args = parser.parse_args()
    args.work.mkdir(parents=True, exist_ok=True)
    firmware = args.work.resolve() / 'firmware with spaces.hex'
    # Deliberately invalid: the real native tool must reject this before serial I/O.
    firmware.write_text('INVALID HEX FOR UPLOAD RECIPE TEST\n', encoding='ascii')
    devices = json.loads((args.sdk / 'tools/variants/devices.json').read_text(encoding='utf-8'))['devices']
    if args.board:
        require(set(args.board) <= {device['id'] for device in devices}, 'unknown board filter')
        devices = [device for device in devices if device['id'] in args.board]
    boards = dict(line.split('=', 1) for line in (args.sdk / 'boards.txt').read_text().splitlines()
                  if line and not line.startswith('#') and '=' in line)
    checks = []
    for device in devices:
        board = device['id']
        require(boards[board + '.upload.tool.serial'] == 'stc-cli', 'missing IDE serial tool: ' + board)
        require(boards[board + '.upload.protocol'] == 'stc-isp', 'missing upload protocol: ' + board)
        variants = [''] + ([':uploadcheck=manual', ':uploadcheck=detect'] if device['upload_requires_manual_model_check'] else [])
        if board == 'stc32g144k246':
            variants = variants + [options + (',' if options else ':') + 'uploadtransport=' + transport
                                   for transport in ('uart', 'usb') for options in variants]
        for options in variants:
            label = board + '-' + (options.lstrip(':').replace('uploadcheck=', '').replace('uploadtransport=', '').replace(',', '-') if options else 'default')
            command = [str(args.cli.resolve()), '--config-file', str(args.config.resolve()), 'upload',
                       '--fqbn', 'arduino-stc51:mcs251:' + board + options,
                       '--port', 'STC_NONEXISTENT_UPLOAD_TEST', '--input-file', str(firmware), '--verbose']
            result = subprocess.run([*command, '--dry-run'], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=30)
            output = result.stdout.decode(errors='replace')
            (args.work / (label + '.log')).write_text(output, encoding='utf-8')
            require(result.returncode == 0, output)
            require('{' not in output and '--expect "' + device['model'] + '"' in output, output)
            transport = next((part.split('=')[1] for part in options.lstrip(':').split(',')
                              if part.startswith('uploadtransport=')), 'auto' if board == 'stc32g144k246' else 'uart')
            require('firmware with spaces.hex"' in output, output)
            if transport == 'usb':
                require(' usb flash ' in output and '--port' not in output and '--reset-port' not in output, output)
            else:
                require('--transport ' + transport in output and '--port "STC_NONEXISTENT_UPLOAD_TEST"' in output, output)
            bypass = transport != 'usb' and device['upload_requires_manual_model_check'] and 'uploadcheck=detect' not in options
            require(('--force-unverified-target' in output) == bypass, output)
            require('--debug' not in output, 'IDE verbose upload must not enable raw ISP traces: ' + output)
            require('--execution-mode mcs251' in output and '--allow-experimental' in output, output)
            if (not options and board in ('stc32g8k64', 'ai8051u_34k64', 'stc32g144k246')) or (board == 'stc32g144k246' and options == ':uploadtransport=usb'):
                failed = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=30)
                failure = failed.stdout.decode(errors='replace')
                (args.work / (label + '-native-invalid-hex.log')).write_text(failure, encoding='utf-8')
                require(failed.returncode != 0 and 'exit status' in failure and 'hex' in failure.lower(), failure)
                require('Property ' not in failure and 'executable file not found' not in failure, failure)
                checks.append('native invalid HEX rejection and failure propagation')
            checks.append(label)
        if board == 'stc32g144k246':
            no_port = [str(args.cli.resolve()), '--config-file', str(args.config.resolve()), 'upload',
                       '--fqbn', 'arduino-stc51:mcs251:' + board + ':uploadtransport=usb',
                       '--input-file', str(firmware), '--verbose']
            for dry in [True, False]:
                result = subprocess.run(no_port + (['--dry-run'] if dry else []), stdout=subprocess.PIPE,
                                        stderr=subprocess.STDOUT, timeout=30)
                output = result.stdout.decode(errors='replace')
                (args.work / ('usb-no-port-' + ('dry-run' if dry else 'invalid-hex') + '.log')).write_text(output, encoding='utf-8')
                require(' usb flash ' in output and 'no upload port provided' not in output, output)
                require(result.returncode == 0 if dry else result.returncode != 0 and 'invalid firmware image' in output, output)
                checks.append('native USB without COM port: ' + ('dry-run' if dry else 'invalid HEX'))
    (args.work / 'report.json').write_text(json.dumps({'status': 'PASS', 'checks': checks}, indent=2) + '\n')
    print(f'PASS: native uploader, spaced paths, failure propagation and {len(devices)} board upload recipes')


if __name__ == '__main__':
    main()
