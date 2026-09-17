#!/usr/bin/env python3
"""Bind both package-toolchain.py outputs to the SDK locks and tool manifest.

Run after creating Windows and macOS bundles, before packaging the platform
and generating its index. This does not upload or publish any assets.
"""
import argparse
from datetime import date
import hashlib
import json
from pathlib import Path
import re
import tarfile

ROOT = Path(__file__).resolve().parents[1]
HOSTS = {
    'windows-x86_64': ('x86_64-mingw32', 'windows-x86_64', 'windows_frontend', 'windows_package_archive_sha256'),
    'macos-arm64': ('arm64-apple-darwin', 'darwin-arm64', 'macos_frontend', 'native_package_archive_sha256'),
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def finalize(assets, version, root=ROOT):
    require(re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+(?:-[A-Za-z0-9.+-]+)?', version), 'Invalid version')
    platform = (root / 'platform.txt').read_text(encoding='utf-8')
    release = re.search(r'^version=(\d+\.\d+\.\d+)$', platform, re.M).group(1)
    base_url = 'https://github.com/coloz/arduino-stc51/releases/download/v' + release
    manifest_path = root / 'tools/toolchain-manifest.json'
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    components = manifest.get('components', [t for t in manifest['tools'] if t['id'] in ('sdcc-mcs251', 'stcxx-frontend')])
    require({t['id'] for t in components} == {'sdcc-mcs251', 'stcxx-frontend'}, 'Missing component source identities')
    systems, updates = [], {}
    for suffix, (arduino_host, host, frontend_key, sdcc_key) in HOSTS.items():
        lock_path = root / ('tools/cpp-cli/toolchain-lock.' + suffix + '.json')
        lock = json.loads(lock_path.read_text(encoding='utf-8'))
        name = f'stcxx-toolchain-{version}-{suffix}.tar.bz2'
        report = json.loads((assets / (name + '.json')).read_text(encoding='utf-8'))
        archive = assets / name
        require(report['name'] == 'stcxx-toolchain' and report['version'] == version and
                report['host'] == host == lock['host'] and report['archiveFileName'] == name and
                report['archiveRoot'] == 'stcxx-toolchain', 'Unexpected toolchain identity')
        require(report['sha256'] == digest(archive) and report['size'] == archive.stat().st_size,
                'Toolchain archive differs from packaging report')
        require(report['components']['frontend']['archive_sha256'] == lock[frontend_key]['archive_sha256'] and
                report['components']['sdcc']['archive_sha256'] == lock['tools']['sdcc'][sdcc_key],
                'Toolchain components differ from SDK lock')
        for component, original in (('sdcc', 'sdcc-mcs251'), ('frontend', 'stcxx-frontend')):
            source = next(t for t in components if t['id'] == original)
            system = next(s for s in source['systems'] if s['host'] == arduino_host)
            require(report['components'][component]['archive_sha256'] == system['sha256'] and
                    report['components'][component]['archive'] == system['archiveFileName'],
                    'Toolchain component differs from source manifest')
        with tarfile.open(archive) as packed:
            inventory = packed.extractfile('stcxx-toolchain/MANIFEST.sha256').read()
            require(hashlib.sha256(inventory).hexdigest() == report['manifest_sha256'], 'Toolchain manifest mismatch')
            metadata = json.load(packed.extractfile('stcxx-toolchain/toolchain.json'))
            require(all(metadata[key] == report[key] for key in ('name', 'version', 'host', 'components')),
                    'Toolchain metadata mismatch')
        lock.pop('arduino_frontend', None)
        lock['arduino_toolchain'] = {'packager': 'stc', 'name': 'stcxx-toolchain', 'version': version}
        lock['toolchain_package'] = {'archive_sha256': report['sha256'], 'manifest_sha256': report['manifest_sha256']}
        updates[lock_path] = lock
        systems.append({'host': arduino_host, **{key: report[key] for key in ('archiveFileName', 'archiveRoot', 'size', 'sha256')},
                        'url': base_url + '/' + name})
    # The POSIX development lock shares these adapters, but does not install a native bundle.
    development = root / 'tools/cpp-cli/toolchain-lock.json'
    updates[development] = json.loads(development.read_text(encoding='utf-8'))
    for lock in updates.values():
        for key in ('toolchain_paths', 'arduino_cli_driver', 'windows_cli_driver'):
            if key in lock['pipeline_helpers']:
                helper = lock['pipeline_helpers'][key]
                helper['sha256'] = digest(root / helper['path'])
    manifest['schemaVersion'] = 3
    manifest['asOf'] = date.today().isoformat()
    manifest['components'] = components
    manifest['tools'] = [{'id': 'stcxx-toolchain', 'packageName': 'stcxx-toolchain', 'version': version,
                          'purpose': 'STC C/C++ toolchain: Clang/LLVM-CBE, SDCC, assembler, linker and runtime libraries',
                          'license': 'Component licenses are preserved under frontend/ and sdcc/', 'systems': systems},
                         *[t for t in manifest['tools'] if t['id'] == 'stc-cli']]
    updates[manifest_path] = manifest
    for path, value in updates.items():
        path.write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8', newline='\n')
    print('PASS: unified toolchain manifest and native SDK locks')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--assets', type=Path, required=True)
    parser.add_argument('--version', required=True)
    args = parser.parse_args()
    finalize(args.assets, args.version)


if __name__ == '__main__':
    main()
