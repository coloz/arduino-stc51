#!/usr/bin/env python3
"""Verify every versioned release asset against the committed manifest."""
import argparse
import hashlib
import json
from pathlib import Path

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('manifest', type=Path)
parser.add_argument('directory', type=Path)
parser.add_argument('--platform-archive', type=Path)
args = parser.parse_args()
manifest = json.loads(args.manifest.read_text(encoding='utf-8'))
for asset in manifest['assets']:
    path = args.directory / asset['name']
    assert path.is_file(), f'Missing {path}'
    assert path.stat().st_size == asset['size'], f'Size mismatch: {path}'
    assert hashlib.sha256(path.read_bytes()).hexdigest() == asset['sha256'], f'SHA-256 mismatch: {path}'
    print('PASS', asset['name'])
if args.platform_archive:
    name = f"arduino-stc51-{manifest['version']}.tar.bz2"
    expected = next(asset for asset in manifest['assets'] if asset['name'] == name)
    assert hashlib.sha256(args.platform_archive.read_bytes()).hexdigest() == expected['sha256'], 'CI platform package differs from published package'
print(f"Verified {len(manifest['assets'])} immutable release assets")
