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
    parser.add_argument('--version', help='platform version; defaults to platform.txt')
    args = parser.parse_args()
    if args.version is None:
        properties = (Path(__file__).resolve().parents[1] / 'platform.txt').read_text(encoding='utf-8')
        args.version = next(line.split('=', 1)[1] for line in properties.splitlines() if line.startswith('version='))
    base = 'https://github.com/coloz/arduino-stc51/releases/download/v' + args.version
    assets = args.assets.resolve()
    spec = importlib.util.spec_from_file_location('candidate', Path(__file__).with_name('create-macos-candidate-index.py'))
    candidate = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(candidate)
    manifest = json.loads((Path(__file__).resolve().parents[1] / 'tools/toolchain-manifest.json').read_text(encoding='utf-8'))
    tools = {tool['id']: tool for tool in manifest['tools']}

    def archive(name, host):
        system = next(system for system in tools[name]['systems'] if system['host'] == host)
        path = assets / system['archiveFileName']
        candidate.require(path.stat().st_size == system['size'] and candidate.sha256(path) == system['sha256'],
                          'Archive differs from release manifest: ' + path.name)
        return path

    sdcc_version = tools['sdcc-mcs251']['version']
    platform = assets / ('arduino-stc51-' + args.version + '.tar.bz2')
    with tempfile.TemporaryDirectory() as temporary:
        win_path, mac_path = [Path(temporary) / n for n in ('windows.json', 'macos.json')]
        for host, output in [('x86_64-mingw32', win_path), ('arm64-apple-darwin', mac_path)]:
            candidate.create(platform, archive('sdcc-mcs251', host), archive('stcxx-frontend', host),
                             sdcc_version, base, output, host, uploader=archive('stc-cli', host))
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
