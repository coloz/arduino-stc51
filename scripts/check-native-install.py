#!/usr/bin/env python3
"""Install a staged release into fresh Arduino data and exercise both native hosts.

An isolated loopback server serves the exact candidate archives. All STCXX
overrides are removed; Windows uses only the system PATH and bundled tools.
"""
import argparse
import functools
import hashlib
import http.server
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tarfile
import threading
from datetime import datetime, timezone


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('assets', 'work', 'cli', 'stc'):
        parser.add_argument('--' + name, required=True, type=Path)
    parser.add_argument('--host', choices=('windows', 'macos'), required=True)
    parser.add_argument('--all-boards', action='store_true')
    parser.add_argument('--index-url', help='Use the published index and downloads instead of the loopback index')
    args = parser.parse_args()
    args.work.mkdir(parents=True, exist_ok=False)
    assets, work = args.assets.resolve(), args.work.resolve()
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith(('STCXX_', 'ARDUINO_', 'DYLD_', 'LD_'))}
    env['PYTHONDONTWRITEBYTECODE'] = '1'
    if args.host == 'windows':
        windows = Path(os.environ['SYSTEMROOT'])
        env['PATH'] = os.pathsep.join(str(windows / p) for p in ('System32', '', 'System32/WindowsPowerShell/v1.0'))
        env.pop('Path', None)
        # PowerShell 7 runners export a module path that can hide Windows
        # PowerShell 5.1's built-in Get-FileHash. Use the native system modules.
        for key in list(env):
            if key.upper() == 'PSMODULEPATH':
                env.pop(key)
        env['PSModulePath'] = str(windows / 'System32/WindowsPowerShell/v1.0/Modules')
    else:
        env['PATH'] = '/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin'
    report = {'status': 'RUNNING', 'host': args.host, 'checks': [],
              'started_utc': datetime.now(timezone.utc).isoformat()}

    def save():
        (work / 'report.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')

    def run(label, command):
        report['active'] = label
        save()
        print('RUN', label, flush=True)
        result = subprocess.run(list(map(str, command)), env=env, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, timeout=1800)
        (work / (label + '.log')).write_bytes(result.stdout)
        report['checks'].append({'name': label, 'status': result.returncode})
        save()
        require(result.returncode == 0, label + ': ' + result.stdout.decode(errors='replace')[-6000:])
        print('PASS', label, flush=True)
        return result.stdout.decode('utf-8', errors='replace')

    class Handler(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *values):
            pass

    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), functools.partial(Handler, directory=str(assets)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = 'http://127.0.0.1:' + str(server.server_port)
    index = json.loads((assets / 'package_arduino-stc51_candidate_index.json').read_text(encoding='utf-8'))
    for package in index['packages']:
        require({t['name'] for t in package['tools']} == {'sdcc-mcs251', 'stcxx-frontend', 'stc-cli'}, 'unexpected tool dependency')
        for entry in package['platforms'] + [s for tool in package['tools'] for s in tool['systems']]:
            entry['url'] = base + '/' + entry['archiveFileName']
    local_index = assets / ('package_arduino-stc51_' + args.host + '_index.json')
    local_index.write_text(json.dumps(index), encoding='utf-8')
    config = work / 'arduino-cli.json'
    config.write_text(json.dumps({'directories': {name: str(work / name) for name in ('data', 'downloads', 'user')},
                                 'board_manager': {'additional_urls': [args.index_url or base + '/' + local_index.name]}}), encoding='utf-8')
    cli = [args.cli.resolve(), '--config-file', config]
    sdk = work / 'data/packages/arduino-stc51/hardware/mcs251/0.0.1'
    try:
        run('update-index', [*cli, 'core', 'update-index'])
        run('install', [*cli, 'core', 'install', 'arduino-stc51:mcs251@0.0.1'])
        archive = assets / 'arduino-stc51-0.0.1.tar.bz2'
        with tarfile.open(archive) as stream:
            files = {m.name.split('/', 1)[1]: stream.extractfile(m).read() for m in stream if m.isfile()}
        require(all((sdk / name).read_bytes() == value for name, value in files.items()), 'installed platform differs from archive')
        report['platform_sha256'] = hashlib.sha256(archive.read_bytes()).hexdigest()
        report['installed_files'] = len(files)
        tools = sdk.parents[2] / 'tools'
        require({p.name for p in tools.iterdir()} == {'sdcc-mcs251', 'stcxx-frontend', 'stc-cli'}, 'installer added an unexpected tool')
        run('upload-recipes', [sys.executable, Path(__file__).with_name('check-upload.py'),
                               '--cli', args.cli.resolve(), '--config', config, '--sdk', sdk,
                               '--work', work / 'upload-recipes'])
        versions = {tool['name']: tool['version'] for tool in index['packages'][0]['tools']}
        compiler = tools / 'sdcc-mcs251' / versions['sdcc-mcs251'] / 'bin' / ('sdcc.exe' if args.host == 'windows' else 'sdcc')
        signature = compiler.read_bytes()[:4]
        require(signature[:2] == b'MZ' if args.host == 'windows' else signature == b'\xcf\xfa\xed\xfe', 'compiler is not a native image')
        cases = [('c-full', 'stc32g12k128', 'STC32G12K128', 'Blink', False),
                 ('c-small', 'ai8051u_34k16', 'AI8051U-34K16', 'Blink', False),
                 ('cpp-full', 'stc32g144k246', 'STC32G144K246', 'Blink', True),
                 ('cpp-ai64', 'ai8051u_34k64', 'AI8051U-34K64', 'Blink', True),
                 ('cpp-wire', 'stc32g12k128', 'STC32G12K128', 'Practical/CheckedWire', True)]
        if args.all_boards:
            devices = json.loads((sdk / 'tools/variants/devices.json').read_text(encoding='utf-8'))['devices']
            existing = {(board, cpp) for _, board, _, _, cpp in cases}
            cases += [('cpp-' + d['id'], d['id'], d['model'], 'Blink', True) for d in devices if (d['id'], True) not in existing]
        for label, board, model, example, cpp in cases:
            build = work / label
            fqbn = 'arduino-stc51:mcs251:' + board + ':clock=12m' + (',cppcore=enabled' if cpp else '')
            command = [*cli, 'compile', '--clean', '--fqbn', fqbn, '--build-path', build, sdk / 'examples' / example]
            text = run(label, command)
            require(not re.search(r'warning:.*(?:__has_builtin|__STDC_HOSTED__).*redefined', text),
                    'target macro redefinition warning returned')
            require(re.search(r'Sketch uses [1-9][0-9]* bytes', text), 'compiler did not report nonempty firmware')
            firmware = next(build.glob('*.hex'))
            validation = json.loads(run(label + '-hex', [args.stc.resolve(), 'validate', '--expect', model, '--file', firmware,
                                                       '--execution-mode', 'mcs251', '--json']))
            require(validation.get('valid') is True, 'invalid firmware: ' + label)
            if cpp:
                manifest = json.loads((build / 'stcxx/manifest.json').read_text(encoding='utf-8'))
                require(manifest.get('outcome') == 'pass', 'C++ link audits did not finish')
            if label == 'cpp-full':
                before = firmware.read_bytes()
                run('cpp-cache', [value for value in command if value != '--clean'])
                require(firmware.read_bytes() == before, 'cached build changed the firmware')
        require(all((sdk / name).read_bytes() == value for name, value in files.items()), 'build modified installed platform')
        report['status'] = 'PASS'
        report.pop('active', None)
    except Exception as error:
        report.update(status='FAIL', error=str(error))
        print(str(error), file=sys.stderr)
    finally:
        report['finished_utc'] = datetime.now(timezone.utc).isoformat()
        save()
        server.shutdown()
    return 0 if report['status'] == 'PASS' else 1


if __name__ == '__main__':
    sys.exit(main())
