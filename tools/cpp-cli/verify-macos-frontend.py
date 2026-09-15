#!/usr/bin/env python3
"""Verify complete pinned Mac and portable Linux frontends before execution.

The manifest binds the already relocated Mach-O load commands, all three
private libraries, resource headers, licenses and provenance. Loader environment
overrides are refused. The historical filename remains for SDK compatibility.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import sys


def sha256(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def verify(root, expected_digest, selected, environ):
    root = root.resolve(strict=True)
    if any(key.startswith(('DYLD_', 'LD_')) for key in environ):
        raise ValueError('remove DYLD_* and LD_* overrides before using the pinned frontend')
    manifest = root / 'MANIFEST.sha256'
    if manifest.is_symlink() or sha256(manifest) != expected_digest:
        raise ValueError('frontend manifest SHA-256 mismatch')
    expected = {}
    for line in manifest.read_text(encoding='utf-8').splitlines():
        digest, name = line.split('  ', 1)
        path = PurePosixPath(name)
        if (not re.fullmatch('[0-9a-f]{64}', digest) or path.is_absolute() or
                '..' in path.parts or path.as_posix() != name or name in expected or
                name == 'MANIFEST.sha256'):
            raise ValueError('invalid frontend manifest entry: ' + name)
        expected[name] = digest
    observed = {}
    for path in root.rglob('*'):
        if path.is_symlink():
            raise ValueError('symlink in pinned frontend: ' + str(path))
        if path.is_dir():
            continue
        if not path.is_file():
            raise ValueError('non-regular file in frontend: ' + str(path))
        name = path.relative_to(root).as_posix()
        if name != 'MANIFEST.sha256':
            observed[name] = sha256(path)
    if observed != expected:
        changed = sorted(name for name in set(observed) | set(expected) if observed.get(name) != expected.get(name))
        raise ValueError('frontend package differs: ' + ', '.join(changed))
    names = {'clang', 'llvm-link', 'opt', 'llvm-dis', 'llvm-cbe'}
    if set(selected) != names:
        raise ValueError('all five selected frontend tools must be verified')
    for name, path in selected.items():
        if Path(path).resolve(strict=True) != root / 'bin' / name or not os.access(path, os.X_OK):
            raise ValueError('selected frontend tool escapes pinned package: ' + name)
    return len(expected)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--lock', required=True, type=Path)
    parser.add_argument('--root', required=True, type=Path)
    parser.add_argument('--tool', nargs=2, action='append', required=True)
    args = parser.parse_args()
    try:
        lock = json.loads(args.lock.read_text(encoding='utf-8'))
        hosts = {'darwin-arm64': ('darwin', 'arm64', 'macos_frontend'),
                 'linux-x86_64': ('linux', 'x86_64', 'linux_frontend')}
        platform, machine, package_key = hosts[lock['host']]
        if sys.platform != platform or os.uname().machine != machine:
            raise ValueError('frontend lock requires native ' + lock['host'])
        if len(args.tool) != 5:
            raise ValueError('duplicate or missing selected frontend tools')
        digest = lock[package_key]['manifest_sha256']
        verify(args.root, digest, dict(args.tool), os.environ)
        print('frontend_manifest\t' + str(args.root / 'MANIFEST.sha256') + '\t' + digest)
        return 0
    except (KeyError, OSError, ValueError) as error:
        print(str(error), file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
