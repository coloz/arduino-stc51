#!/usr/bin/env python3
"""Verify every versioned release asset against the committed manifest."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys


def require(condition, message):
    if not condition:
        raise ValueError(message)


def verify_file(path, asset):
    require(path.is_file(), f'Missing {path}')
    require(path.stat().st_size == asset['size'], f'Size mismatch: {path}')
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    require(digest.hexdigest() == asset['sha256'], f'SHA-256 mismatch: {path}')


def verify(manifest_path, directory, platform_archive=None):
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    require(manifest.get('schema_version') == 1, 'Unsupported manifest schema')
    require(isinstance(manifest.get('version'), str) and
            re.fullmatch(r'\d+\.\d+\.\d+', manifest['version']), 'Invalid release version')
    assets = manifest.get('assets')
    require(isinstance(assets, list) and assets, 'Release assets must be a nonempty list')
    names = set()
    directory = directory.resolve()
    # Validate the complete inventory before inspecting any payload.
    for asset in assets:
        require(isinstance(asset, dict), 'Invalid asset entry')
        name = asset.get('name')
        require(isinstance(name, str) and
                re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._+-]*', name), 'Unsafe asset name')
        require(name not in names, f'Duplicate asset: {name}')
        names.add(name)
        require(type(asset.get('size')) is int and asset['size'] > 0, f'Invalid size: {name}')
        require(isinstance(asset.get('sha256'), str) and
                re.fullmatch(r'[0-9a-f]{64}', asset['sha256']), f'Invalid SHA-256: {name}')
        path = directory / name
        require(path.resolve().parent == directory, f'Asset escapes release directory: {name}')
    for asset in assets:
        verify_file(directory / asset['name'], asset)
        print('PASS', asset['name'])
    if platform_archive:
        name = f"arduino-stc51-{manifest['version']}.tar.bz2"
        require(name in names, f'Missing platform asset: {name}')
        verify_file(platform_archive, next(asset for asset in assets if asset['name'] == name))
    print(f'Verified {len(assets)} immutable release assets')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest', type=Path)
    parser.add_argument('directory', type=Path)
    parser.add_argument('--platform-archive', type=Path)
    args = parser.parse_args()
    try:
        verify(args.manifest, args.directory, args.platform_archive)
    except (ValueError, OSError) as error:
        print(f'FAIL: {error}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
