#!/usr/bin/env python3
"""Run a bounded MCS251 UART oracle, retaining firmware, QEMU and log hashes."""
import argparse
import hashlib
import json
from pathlib import Path
import selectors
import subprocess
import sys
import time


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--qemu', type=Path, required=True)
    parser.add_argument('--firmware', type=Path, required=True)
    parser.add_argument('--board', required=True)
    parser.add_argument('--expected', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--timeout', type=float, default=60)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    devices = json.loads((root / 'tools/variants/devices.json').read_text(encoding='utf-8'))['devices']
    if args.board not in [d['id'] for d in devices] or not 0 < args.timeout <= 3600:
        parser.error('select a current MCS251 board and a timeout in (0, 3600] seconds')
    machine = args.board.replace('_', '-')
    if machine.startswith('ai8051u-'):
        machine += '-mcs251'
    args.output.mkdir(parents=True, exist_ok=True)
    result_file = args.output / 'qemu.json'
    report = {'status': 'RUNNING', 'board': args.board, 'machine': machine, 'timeout_seconds': args.timeout,
              'scope': 'target execution and exact UART oracle; no peripheral/electrical qualification'}
    result_file.write_text(json.dumps(report), encoding='utf-8')
    received = bytearray()
    process = None
    started = time.monotonic()
    try:
        report.update(firmware_sha256=digest(args.firmware), qemu_sha256=digest(args.qemu),
                      oracle_sha256=digest(args.expected))
        expected = args.expected.read_bytes().replace(b'\r\n', b'\n')
        if not expected or not expected.endswith(b'\n'):
            raise RuntimeError('oracle must be nonempty complete lines')
        command = [str(args.qemu.resolve()), '-machine', machine,
                   '-bios', str(args.firmware.resolve()), '-display', 'none',
                   '-monitor', 'none', '-serial', 'stdio',
                   '-icount', 'shift=0,align=off,sleep=off']
        report['command'] = command
        with (args.output / 'qemu-stderr.log').open('wb') as error_log:
            process = subprocess.Popen(command, stdin=subprocess.DEVNULL,
                                       stdout=subprocess.PIPE, stderr=error_log)
            with selectors.DefaultSelector() as selector:
                selector.register(process.stdout, selectors.EVENT_READ)
                while time.monotonic() - started < args.timeout:
                    if not selector.select(timeout=min(1, args.timeout)):
                        if process.poll() is not None:
                            raise RuntimeError(f'QEMU exited early: {process.returncode}')
                        continue
                    chunk = process.stdout.read1(4096)
                    if not chunk:
                        raise RuntimeError('QEMU closed UART before the oracle completed')
                    received.extend(chunk)
                    normalized = bytes(received).replace(b'\r\n', b'\n')
                    if normalized == expected:
                        break
                    # UART chunks may split CRLF between the two bytes.
                    prefix = normalized[:-1] if normalized.endswith(b'\r') else normalized
                    if not expected.startswith(prefix):
                        raise RuntimeError('UART output differs from the expected oracle')
                else:
                    raise RuntimeError(f'QEMU oracle timed out after {args.timeout}s')
        if digest(args.firmware) != report['firmware_sha256'] or digest(args.qemu) != report['qemu_sha256']:
            raise RuntimeError('firmware or QEMU changed during execution')
        if digest(args.expected) != report['oracle_sha256']:
            raise RuntimeError('UART oracle changed during execution')
        report['status'] = 'PASS'
    except Exception as error:
        report['status'], report['error'] = 'FAIL', str(error)
    finally:
        if process is not None:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
            process.stdout.close()
        uart = args.output / 'uart.log'
        uart.write_bytes(received)
        report.update(uart_sha256=digest(uart), elapsed_seconds=time.monotonic() - started)
        result_file.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, indent=2))
    return 0 if report['status'] == 'PASS' else 1


if __name__ == '__main__':
    sys.exit(main())
