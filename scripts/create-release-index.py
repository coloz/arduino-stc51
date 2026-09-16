#!/usr/bin/env python3
"""Create the Windows/Apple Silicon release index from locked local archives.

This verifies archive bindings before writing the index; it does not publish.
"""
import argparse
import importlib.util
import json
from pathlib import Path
import tempfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--assets', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--version', default='0.0.1')
    args = parser.parse_args()
    base = 'https://github.com/coloz/arduino-stc51/releases/download/v' + args.version
    assets = args.assets.resolve()
    spec = importlib.util.spec_from_file_location('candidate', Path(__file__).with_name('create-macos-candidate-index.py'))
    candidate = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(candidate)
    commit = 'b09075b6a93e6afe10645181e3aeff041ea37f87'
    sdcc_version = '4.6.0-stc.' + args.version
    platform = assets / ('arduino-stc51-' + args.version + '.tar.bz2')
    with tempfile.TemporaryDirectory() as temporary:
        win_path, mac_path = [Path(temporary) / n for n in ('windows.json', 'macos.json')]
        candidate.create(platform, assets / f'sdcc-mcs251-windows-x86_64-{commit}-r8.zip',
                         assets / 'stcxx-frontend-20.1.8-windows-x86_64-r1.tar.bz2',
                         sdcc_version, base, win_path, 'x86_64-mingw32')
        candidate.create(platform, assets / f'sdcc-mcs251-macos-arm64-{commit}-r9.tar.bz2',
                         assets / 'stcxx-frontend-20.1.8-macos-arm64-r1.tar.bz2',
                         sdcc_version, base, mac_path, 'arm64-apple-darwin')
        package = json.loads(win_path.read_text())['packages'][0]
        mac = json.loads(mac_path.read_text())['packages'][0]
    assert package['platforms'][0]['checksum'] == mac['platforms'][0]['checksum']
    by_name = {t['name']: t for t in package['tools']}
    for tool in mac['tools']:
        assert by_name[tool['name']]['version'] == tool['version']
        by_name[tool['name']]['systems'].extend(tool['systems'])
    for tool in package['tools']:
        assert {s['host'] for s in tool['systems']} == {'x86_64-mingw32', 'arm64-apple-darwin'}
    args.output.write_text(json.dumps({'packages': [package]}, indent=2) + '\n', encoding='utf-8', newline='\n')
    print('PASS: Windows x64 and Apple Silicon index; all compiler/frontend archives match SDK locks')


if __name__ == '__main__':
    main()
