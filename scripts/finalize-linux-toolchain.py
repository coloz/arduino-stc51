#!/usr/bin/env python3
"""Attach source/dependency notices and verifiable metadata to a Linux SDCC stage.

This records packaging inputs; it does not certify runtime behavior or replace
the corresponding source distribution required for a public candidate.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess


def sha256(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest() if hasattr(hashlib, 'file_digest') else hashlib.sha256(stream.read()).hexdigest()


def run(command):
    return subprocess.run([str(x) for x in command], check=True, capture_output=True,
                          text=True, timeout=60).stdout.strip()


def inventory(root):
    """Inventory regular files and internal file links; reject escaping links."""
    root = Path(root).resolve()
    result = {}
    for path in sorted(root.rglob('*')):
        relative = path.relative_to(root).as_posix()
        if any(character in relative for character in ('\n', '\r', '\\')):
            raise ValueError('unrepresentable manifest path: ' + relative)
        kind = path.lstat().st_mode
        if stat.S_ISDIR(kind):
            continue
        link = None
        if stat.S_ISLNK(kind):
            link = os.readlink(path)
            resolved = path.resolve(strict=True)
            if Path(link).is_absolute() or root not in resolved.parents or not resolved.is_file():
                raise ValueError('unsafe package link: ' + relative)
        elif not stat.S_ISREG(kind):
            raise ValueError('unsupported package entry: ' + relative)
        result[relative] = {'sha256': sha256(path), 'size': path.stat().st_size,
                            'mode': stat.S_IMODE(kind), 'link_target': link}
    if not result:
        raise ValueError('empty package')
    return result


def write_manifest(root):
    root = Path(root)
    destination = root / 'MANIFEST.sha256'
    if destination.exists() or destination.is_symlink():
        raise ValueError('refusing to overwrite an existing manifest')
    files = inventory(root)
    with destination.open('x', encoding='utf-8', newline='\n') as stream:
        stream.write(''.join(f"{entry['sha256']}  {name}\n" for name, entry in files.items()))
    destination.chmod(0o644)
    return files


def package_owner(path):
    for candidate in dict.fromkeys((str(path), str(Path(path).resolve()))):
        result = subprocess.run(['dpkg-query', '-S', candidate], capture_output=True, text=True, timeout=30)
        if result.returncode == 0:
            owners = {line.partition(': ')[0] for line in result.stdout.splitlines() if ': ' in line}
            if len(owners) == 1:
                owner = owners.pop()
                if re.fullmatch(r'[a-z0-9][a-z0-9+.\-]*(?::[a-z0-9-]+)?', owner):
                    return owner
    raise RuntimeError('cannot identify dependency package: ' + str(path))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('source', 'build', 'package', 'builder', 'patch'):
        parser.add_argument('--' + name, required=True, type=Path)
    for name in ('commit', 'tag', 'epoch'):
        parser.add_argument('--' + name, required=True)
    args = parser.parse_args()
    source, package = args.source.resolve(), args.package.resolve()
    for name in ('candidate-provenance.json', 'MANIFEST.sha256', 'build-inputs', 'licenses'):
        if (package / name).exists() or (package / name).is_symlink():
            parser.error('metadata destination already exists: ' + name)
    if not re.fullmatch(r'[0-9a-f]{40}', args.commit) or not args.epoch.isdecimal():
        parser.error('invalid source identity or timestamp')
    if run(['git', '-C', source, 'rev-parse', 'HEAD']) != args.commit:
        parser.error('source commit mismatch')
    run(['git', '-C', source, 'apply', '--reverse', '--check', args.patch.resolve()])
    initial = inventory(package)
    inputs = {
        'build-inputs/build-linux-toolchain.sh': args.builder.resolve(),
        'build-inputs/finalize-linux-toolchain.py': Path(__file__).resolve(),
        'build-inputs/sdcc-mcs251-arduino-cpp.patch': args.patch.resolve(),
    }
    for name in ('COPYING', 'COPYING3', 'COPYING.LIB', 'COPYING3.LIB'):
        inputs['licenses/binutils/' + name] = source / 'support/sdbinutils' / name
    inputs['licenses/assembler/COPYING3'] = source / 'sdas/COPYING3'
    # GCC's preprocessor files refer to COPYING3; retain that complete GPL text.
    inputs['licenses/preprocessor/COPYING3'] = source / 'support/sdbinutils/COPYING3'
    dependencies = {package_owner('/usr/include/boost/version.hpp'), package_owner('/usr/include/zlib.h')}
    for command in ('gcc', 'g++'):
        dependencies.add(package_owner(shutil.which(command)))
    dynamic_dependencies = {}
    for name in initial:
        executable = package / name
        with executable.open('rb') as stream:
            if stream.read(4) != b'\x7fELF':
                continue
        program_headers = run(['readelf', '-l', executable])
        if 'Requesting program interpreter' not in program_headers:
            continue
        listing = run(['ldd', executable])
        if 'not found' in listing:
            raise RuntimeError('unresolved runtime dependency: ' + name)
        libraries = sorted(set(re.findall(r'(/[^\s()]+)', listing)))
        if not libraries:
            raise RuntimeError('no resolved libraries for dynamic executable: ' + name)
        dynamic_dependencies[name] = []
        for library in libraries:
            owner = package_owner(library); dependencies.add(owner)
            dynamic_dependencies[name].append({'soname_path': library, 'package': owner, 'sha256': sha256(library)})
    for owner in sorted(dependencies):
        inputs['licenses/dependencies/' + owner.replace(':', '_') + '.copyright'] = Path('/usr/share/doc') / owner.split(':')[0] / 'copyright'
    # Debian copyright files refer to these complete, separately installed texts.
    for path in sorted(Path('/usr/share/common-licenses').iterdir()):
        if path.is_file(): inputs['licenses/common/' + path.name] = path
    hashes = {}
    for name, path in inputs.items():
        if not path.is_file() or path.stat().st_size == 0:
            raise RuntimeError('missing or empty packaging input: ' + str(path))
        hashes[name] = sha256(path)
    packages = run(['dpkg-query', '-W', '-f=${Package}\t${Version}\t${Architecture}\n'])
    metadata = {'schema_version': 1, 'scope': 'Linux package provenance; runtime and corresponding-source distribution gates remain separate',
                'production_qualified': False, 'source_tag': args.tag, 'source_commit': args.commit,
                'source_date_epoch': int(args.epoch), 'source_repository': 'https://github.com/gevico/sdcc-c251.git',
                'source_patch_sha256': sha256(args.patch), 'inputs': hashes, 'payload_before_metadata': initial,
                'dynamic_dependencies': dynamic_dependencies,
                'dependency_packages': {owner: run(['dpkg-query', '-W', '-f=${Version}', owner]) for owner in sorted(dependencies)},
                'build_packages': [dict(zip(('package', 'version', 'architecture'), line.split('\t'))) for line in packages.splitlines()],
                'configure_arguments': run([args.build.resolve() / 'config.status', '--config']),
                'tools': {command: run([command, '--version']).splitlines()[0] for command in ('gcc', 'g++', 'make', 'bison', 'flex', 'tar')},
                'source_changes': run(['git', '-C', source, 'status', '--porcelain'])}
    for name, path in inputs.items():
        destination = package / name; destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, destination); destination.chmod(0o644)
        if sha256(destination) != hashes[name]:
            raise RuntimeError('input changed while copying: ' + name)
    (package / 'build-inputs/README.txt').write_text(
        'This is a locally patched SDCC candidate. candidate-provenance.json records\n'
        'the base commit, patch, build configuration, dependency versions and inputs.\n'
        'MANIFEST.sha256 covers every regular file and internal file link except itself.\n'
        'Link destinations and modes are additionally recorded for the original payload.\n\n'
        'Packaging does not certify Arduino behavior, device execution or hardware.\n'
        'A public distribution still needs the corresponding source and build materials\n'
        'alongside the qualified binary artifact; the included patch alone is insufficient.\n', encoding='utf-8')
    for name, path in inputs.items():
        if sha256(path) != hashes[name]: raise RuntimeError('input changed during packaging: ' + name)
    current_inventory = inventory(package)
    if {name: current_inventory[name] for name in initial} != initial:
        raise RuntimeError('installed payload changed during metadata generation')
    (package / 'candidate-provenance.json').write_text(json.dumps(metadata, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    for name in ('build-inputs/README.txt', 'candidate-provenance.json'):
        (package / name).chmod(0o644)
    files = write_manifest(package)
    print('LINUX_METADATA_FILES=' + str(len(files)))


if __name__ == '__main__':
    main()
