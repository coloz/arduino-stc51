#!/usr/bin/env python3
"""Check the actual buffered Serial baud functions against exact integer oracles.

The host translation uses uint32_t for the target's unsigned long. This checks
arithmetic, not the target ABI, peripheral ownership or physical baud timing.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import random
import shutil
import subprocess
import sys
import tempfile


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def oracle_cases():
    maximum, marker = 0xffffffff, 0x71892345
    rng = random.Random(0x73519)
    rounds, errors, configs = [], [], []
    edges = [0, 1, 2, 3, 4, 99, 100, 101, 65535, 65536, 12000000,
             24000000, 0x7fffffff, 0xfffffffe, maximum]
    for clock in edges:
        for denominator in edges:
            rounds.append([clock, denominator, int(denominator != 0),
                           (clock + denominator // 2) // denominator if denominator else marker])
    for _ in range(80):
        clock, denominator = rng.getrandbits(32), rng.getrandbits(32)
        rounds.append([clock, denominator, 1, (clock + denominator // 2) // denominator])
    for ticks in [0, 1, 2, 32, 33, 34, 99, 100, 101, 65535, 12000000, maximum - 99, maximum]:
        allowance = (ticks * 3 + 99) // 100
        for distance in [0, max(0, allowance - 1), allowance, allowance + 1]:
            for clock in sorted({max(0, ticks - distance), min(maximum, ticks + distance)}):
                errors.append([clock, 1, ticks, int(abs(clock - ticks) <= allowance)])
    for _ in range(80):
        clock, denominator, divisor = (rng.getrandbits(32) for _ in range(3))
        ticks = (denominator * divisor) & maximum
        errors.append([clock, denominator, divisor, int(abs(clock - ticks) <= (ticks * 3 + 99) // 100)])
    for clock in [0, 1, 12000000, 24000000, 32000000, 48000000, maximum]:
        for baud in [0, 1, 2, 45, 46, 47, 50, 300, 1200, 2400, 9600, 19200, 57600, 115200,
                     230400, 1000000, 3000000, 4000000, maximum // 4, maximum // 4 + 1, maximum]:
            valid, reload = False, 0xa53d
            if 0 < baud <= maximum // 4:
                denominator = baud * 4
                divisor = (clock + denominator // 2) // denominator
                ticks = (denominator * divisor) & maximum
                valid = 0 < divisor < 65536 and abs(clock - ticks) <= (ticks * 3 + 99) // 100
                if valid:
                    reload = 65536 - divisor
            configs.append([clock, baud, int(valid), reload, 0 if valid else 0x5a])
    return {'rounding': rounds, 'tolerance': errors, 'configuration': configs}


CHECKER = r'''
static int check_cases(void) {
    unsigned int i;
    for (i = 0; i < sizeof(rounding) / sizeof(rounding[0]); ++i) {
        uint32_t value = UINT32_C(0x71892345);
        uint8_t ok = stc_serial_rounded_divisor(rounding[i][0], rounding[i][1], &value);
        if (ok != rounding[i][2] || value != rounding[i][3]) return 1;
    }
    for (i = 0; i < sizeof(tolerance) / sizeof(tolerance[0]); ++i) {
        if (stc_serial_baud_error_is_acceptable(tolerance[i][0], tolerance[i][1], tolerance[i][2]) != tolerance[i][3]) return 2;
    }
    for (i = 0; i < sizeof(configuration) / sizeof(configuration[0]); ++i) {
        uint16_t reload = 0xa53d;
        uint8_t double_baud = 0x5a;
        test_clock = configuration[i][0];
        if (stc_serial_calculate_reload(configuration[i][1], &reload, &double_baud) != configuration[i][2]
            || reload != configuration[i][3] || double_baud != configuration[i][4]) return 3;
    }
    return 0;
}
static uint32_t random_state = UINT32_C(0x829a31fd);
static uint32_t random32(void) {
    random_state ^= random_state << 13;
    random_state ^= random_state >> 17;
    random_state ^= random_state << 5;
    return random_state;
}
int main(void) {
    uint32_t i;
    int error = check_cases();
    if (error) { fprintf(stderr, "fixed arithmetic oracle failed: %d\n", error); return error; }
    for (i = 0; i < 2000000UL; ++i) {
        uint32_t clock = random32(), denominator = random32(), divisor = random32();
        uint32_t value = UINT32_C(0x71892345);
        uint32_t ticks = (uint32_t)((uint64_t)denominator * divisor);
        uint64_t difference = clock >= ticks ? (uint64_t)clock - ticks : (uint64_t)ticks - clock;
        uint64_t limit = ((uint64_t)ticks * 3 + 99) / 100;
        uint8_t ok = stc_serial_rounded_divisor(clock, denominator, &value);
        if (denominator == 0) {
            if (ok || value != UINT32_C(0x71892345)) return 4;
        } else if (!ok || value != ((uint64_t)clock + denominator / 2) / denominator) return 5;
        if (stc_serial_baud_error_is_acceptable(clock, denominator, divisor) != (difference <= limit)) return 6;
    }
    puts("PASS baud arithmetic: fixed boundary/configuration cases and 2000000 random pairs");
    return 0;
}
'''


def main(argv=None):
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cc', default='gcc')
    parser.add_argument('--source', type=Path, default=root / 'cores/STC/HardwareSerial.c')
    parser.add_argument('--output', type=Path, help='new directory for retained evidence; otherwise use temporary files')
    args = parser.parse_args(argv)
    args.source = args.source.resolve()
    if args.output is None:
        with tempfile.TemporaryDirectory(prefix='stc-serial-arithmetic-') as directory:
            return main(['--cc', args.cc, '--source', str(args.source), '--output', str(Path(directory) / 'result')])
    output = args.output.resolve()
    if output == root or output in args.source.parents or args.source in output.parents or any(
            output == root / folder or root / folder in output.parents
            for folder in ('cores', 'libraries', 'scripts', 'tests', 'tools', 'variants')):
        parser.error('output must be separate from input and maintained source directories')
    output.mkdir(parents=True, exist_ok=False)
    report = {'status': 'RUNNING', 'scope': __doc__, 'commands': [],
              'started_utc': datetime.now(timezone.utc).isoformat()}

    def run(label, command, timeout):
        log = output / (label + '.log')
        with log.open('wb') as stream:
            completed = subprocess.run(command, stdout=stream, stderr=subprocess.STDOUT, timeout=timeout)
        report['commands'].append({'label': label, 'command': command,
                                   'exit_code': completed.returncode, 'log_sha256': sha(log)})
        if completed.returncode:
            raise RuntimeError(f'{label} failed; see {log}')

    try:
        compiler = shutil.which(args.cc)
        if compiler is None:
            raise RuntimeError('host C compiler not found: ' + args.cc)
        inputs = [Path(__file__).resolve(), args.source, Path(compiler).resolve()]
        report['inputs_sha256'] = {str(p): sha(p) for p in inputs}
        source = args.source.read_text(encoding='utf-8')
        start = source.index('static uint8_t stc_serial_rounded_divisor(')
        end = source.index('static void stc_serial_reset_rx(void)', start)
        functions = source[start:end]
        if functions.count('static uint8_t ') != 3:
            raise RuntimeError('buffered baud function extraction changed; review the harness')
        cases = oracle_cases()
        report['fixed_case_counts'] = {name: len(rows) for name, rows in cases.items()}
        report['random_pairs'] = 2000000
        oracle = output / 'oracle-cases.json'
        oracle.write_text(json.dumps(cases, indent=2) + '\n', encoding='utf-8')
        report['oracle_sha256'] = sha(oracle)
        data = ''
        for name, rows in cases.items():
            data += f'static const uint32_t {name}[][{len(rows[0])}] = {{\n'
            data += ',\n'.join('    {' + ', '.join(str(x) + 'UL' for x in row) + '}' for row in rows) + '\n};\n'
        generated = output / 'arithmetic.c'
        generated.write_text('#include <stdint.h>\n#include <stdio.h>\n#define __reentrant\n'
                             'static uint32_t test_clock;\n#define F_CPU test_clock\n' +
                             functions.replace('unsigned long', 'uint32_t') + data + CHECKER, encoding='utf-8')
        report['generated_source_sha256'] = sha(generated)
        binary = output / 'arithmetic-check'
        run('compile', [compiler, '-std=c99', '-O2', '-Wall', '-Wextra', '-Werror', '-fsanitize=undefined',
                        '-fno-sanitize-recover=all', str(generated), '-o', str(binary)], 90)
        run('execute', [str(binary)], 30)
        if any(sha(Path(p)) != digest for p, digest in report['inputs_sha256'].items()):
            raise RuntimeError('arithmetic input changed during the check')
        report.update(status='PASS', inputs_unchanged=True, binary_sha256=sha(binary))
    except Exception as error:
        report.update(status='FAIL', error=str(error))
    finally:
        report['finished_utc'] = datetime.now(timezone.utc).isoformat()
        (output / 'arithmetic.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(report['status'], report.get('error', 'serial baud arithmetic'), flush=True)
    return 0 if report['status'] == 'PASS' else 1


if __name__ == '__main__':
    sys.exit(main())
