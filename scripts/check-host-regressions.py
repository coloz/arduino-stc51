#!/usr/bin/env python3
"""Run maintained host regressions and save source-bound evidence, not production certification."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def inventory(root):
    result = {path.relative_to(root).as_posix(): sha256(path)
            for folder in ('cores', 'libraries', 'scripts', 'tests', '.github',
                           'tools/cpp-core-pipeline', 'tools/cpp-cli', 'tools/wrapper',
                           'tools/toolchain-patches', 'tools/toolchain-licenses')
            for path in sorted((root / folder).rglob('*'))
            if path.is_file() and '__pycache__' not in path.parts
            and path.suffix not in ('.pyc', '.pyo')}
    # Source-pin tests also read the upstream source identity in this file.
    result['tools/toolchain-manifest.json'] = sha256(root / 'tools/toolchain-manifest.json')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    args.output = args.output.resolve()
    if any(args.output == root / folder or root / folder in args.output.parents
           for folder in ('cores', 'libraries', 'scripts', 'tests', '.github')):
        parser.error('output must be outside the checked source directories')
    args.output.mkdir(parents=True, exist_ok=True)
    report = {'status': 'RUNNING', 'scope': 'host models/sanitizers and verification tooling only',
              'started_utc': datetime.now(timezone.utc).isoformat(), 'checks': []}
    destination = args.output / 'host-regressions.json'

    def save():
        pending = destination.with_suffix('.json.part')
        pending.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
        pending.replace(destination)

    save()
    try:
        report['source_sha256'] = inventory(root)
        commands = [
            ('core', [sys.executable, 'scripts/check-core-runtime.py']),
            ('sd', [sys.executable, 'scripts/check-library-runtime.py']),
            ('stepper', [sys.executable, 'scripts/check-stepper-runtime.py']),
            ('serial', [sys.executable, 'scripts/check-serial-runtime.py']),
            ('serial-arithmetic', [sys.executable, 'scripts/check-serial-arithmetic.py',
                                   '--output', str(args.output / 'serial-arithmetic')]),
            ('verification', [sys.executable, '-m', 'unittest', 'discover', '-s', 'tests', '-p', 'test_*.py', '-v']),
        ]
        for name, command in commands:
            log = args.output / (name + '.log')
            with log.open('wb') as stream:
                completed = subprocess.run(command, cwd=root, stdout=stream,
                                           stderr=subprocess.STDOUT, timeout=180)
            report['checks'].append({'name': name, 'command': command,
                                     'exit_code': completed.returncode, 'log_sha256': sha256(log)})
            save()
            if completed.returncode:
                raise RuntimeError(f'{name} failed; see {log}')
            print('PASS', name, flush=True)
        if inventory(root) != report['source_sha256']:
            raise RuntimeError('sources changed during regression run')
        report['status'] = 'PASS'
    except (Exception, KeyboardInterrupt) as error:
        report['status'], report['error'] = 'FAIL', str(error) or type(error).__name__
        print(report['error'], file=sys.stderr)
    finally:
        report['finished_utc'] = datetime.now(timezone.utc).isoformat()
        save()
    return 0 if report['status'] == 'PASS' else 1


if __name__ == '__main__':
    sys.exit(main())
