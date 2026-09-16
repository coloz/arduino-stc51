#!/usr/bin/env python3
"""Record native Mac SDCC package inputs, notices and a complete file manifest.

This metadata does not qualify Arduino execution or replace corresponding
source and build materials for a public distribution.
"""
import argparse
import importlib.util
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import sys

shared_path = Path(__file__).with_name('finalize-linux-toolchain.py')
spec = importlib.util.spec_from_file_location('stc51_package_metadata', shared_path)
shared = importlib.util.module_from_spec(spec)
spec.loader.exec_module(shared)
sha256, run, inventory, write_manifest = shared.sha256, shared.run, shared.inventory, shared.write_manifest


def system_dependencies(listing):
    """Parse otool's full dependency paths, including possible embedded spaces."""
    result = []
    for line in listing.splitlines()[1:]:
        path, separator, version = line.strip().partition(' (compatibility version ')
        if not separator or not version.endswith(')'):
            raise ValueError('unrecognized Mach-O dependency record')
        parsed = PurePosixPath(path)
        if '..' in parsed.parts or not (path.startswith('/usr/lib/') or path.startswith('/System/Library/')):
            raise ValueError('non-system Mach-O dependency: ' + path)
        result.append(path)
    if not result:
        raise ValueError('missing Mach-O dependency records')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('source', 'build', 'package', 'builder', 'patch', 'preprocessor-patch', 'boost-license'):
        parser.add_argument('--' + name, required=True, type=Path)
    for name in ('commit', 'tag', 'epoch', 'arch', 'minimum-macos'):
        parser.add_argument('--' + name, required=True)
    args = parser.parse_args()
    if sys.platform != 'darwin': parser.error('native macOS is required')
    if args.arch not in ('arm64', 'x86_64') or not re.fullmatch(r'[0-9]+\.[0-9]+', args.minimum_macos):
        parser.error('invalid architecture or deployment target')
    source, package = args.source.resolve(), args.package.resolve()
    for name in ('candidate-provenance.json', 'MANIFEST.sha256', 'build-inputs', 'licenses'):
        if (package / name).exists() or (package / name).is_symlink():
            parser.error('metadata destination already exists: ' + name)
    if not re.fullmatch(r'[0-9a-f]{40}', args.commit) or not args.epoch.isdecimal():
        parser.error('invalid source identity or timestamp')
    if run(['git', '-C', source, 'rev-parse', 'HEAD']) != args.commit:
        parser.error('source commit mismatch')
    run(['git', '-C', source, 'apply', '--reverse', '--check', args.patch.resolve()])
    if sha256(args.boost_license) != 'c9bff75738922193e67fa726fa225535870d2aa1059f91452c411736284ad566':
        parser.error('Boost license differs from the verified upstream text')
    run(['git', '-C', source, 'apply', '--reverse', '--check', args.preprocessor_patch.resolve()])
    initial = inventory(package)
    boost = Path(run(['brew', '--prefix', 'boost'])).resolve()
    inputs = {
        'build-inputs/build-macos-toolchain.sh': args.builder.resolve(),
        'build-inputs/finalize-macos-toolchain.py': Path(__file__).resolve(),
        'build-inputs/finalize-linux-toolchain.py': shared_path.resolve(),
        'build-inputs/sdcc-mcs251-arduino-cpp.patch': args.patch.resolve(),
        'build-inputs/sdcc-target-preprocessor.patch': args.preprocessor_patch.resolve(),
        'licenses/boost/LICENSE_1_0.txt': args.boost_license.resolve(),
        'build-inputs/boost-version.hpp': boost / 'include/boost/version.hpp',
    }
    for name in ('COPYING', 'COPYING3', 'COPYING.LIB', 'COPYING3.LIB'):
        inputs['licenses/binutils/' + name] = source / 'support/sdbinutils' / name
    inputs['licenses/assembler/COPYING3'] = source / 'sdas/COPYING3'
    inputs['licenses/preprocessor/COPYING3'] = source / 'support/sdbinutils/COPYING3'
    hashes = {}
    for name, path in inputs.items():
        if not path.is_file() or not path.stat().st_size: raise RuntimeError('missing packaging input: ' + str(path))
        hashes[name] = sha256(path)
    native = {}
    for name in initial:
        path = package / name
        with path.open('rb') as stream: magic = stream.read(4)
        if magic not in (b'\xcf\xfa\xed\xfe', b'\xfe\xed\xfa\xcf', b'\xca\xfe\xba\xbe', b'\xbe\xba\xfe\xca'):
            continue
        architecture = run(['lipo', '-archs', path])
        if architecture != args.arch: raise RuntimeError('Mach-O architecture mismatch: ' + name)
        commands = run(['otool', '-l', path])
        if re.search(r'cmd\s+LC_RPATH\b', commands): raise RuntimeError('unexpected LC_RPATH: ' + name)
        build_version = run(['vtool', '-show-build', path])
        if not re.search(r'\bminos\s+' + re.escape(args.minimum_macos) + r'(?:\.0)*\s*$', build_version, re.M):
            raise RuntimeError('Mach-O deployment target mismatch: ' + name)
        native[name] = {'architecture': architecture, 'build_version': build_version,
                        'dependencies': system_dependencies(run(['otool', '-L', path]))}
    if not native: raise RuntimeError('package contains no Mach-O files')
    tools = {}
    for command in ('clang', 'clang++', 'make', 'bison', 'flex', 'gtar', 'git'):
        path = Path('/usr/bin') / command if command in ('clang', 'clang++') else Path(shutil.which(command) or command).absolute()
        tools[command] = {'path': str(path), 'sha256': sha256(path), 'version': run([path, '--version']).splitlines()[0]}
    receipt = boost / 'INSTALL_RECEIPT.json'
    metadata = {'schema_version': 1, 'scope': __doc__, 'production_qualified': False,
                'source_repository': 'https://github.com/gevico/sdcc-c251.git',
                'source_tag': args.tag, 'source_commit': args.commit, 'source_date_epoch': int(args.epoch),
                'source_patch_sha256': sha256(args.patch),
                'preprocessor_patch_sha256': sha256(args.preprocessor_patch), 'inputs': hashes, 'payload_before_metadata': initial,
                'macho_files': native, 'build_tools': tools,
                'host': {'version': run(['sw_vers', '-productVersion']), 'build': run(['sw_vers', '-buildVersion']),
                         'machine': run(['uname', '-m'])},
                'apple_sdk': {'path': run(['xcrun', '--sdk', 'macosx', '--show-sdk-path']),
                              'version': run(['xcrun', '--sdk', 'macosx', '--show-sdk-version'])},
                'boost': {'prefix': str(boost), 'receipt_sha256': sha256(receipt),
                          'installed_version': run(['brew', 'list', '--versions', 'boost'])},
                'configure_arguments': run([args.build.resolve() / 'config.status', '--config']),
                'source_changes': run(['git', '-C', source, 'status', '--porcelain'])}
    for name, path in inputs.items():
        destination = package / name; destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, destination); destination.chmod(0o644)
        if sha256(destination) != hashes[name]: raise RuntimeError('packaging input changed while copying: ' + name)
    readme = package / 'build-inputs/README.txt'
    readme.write_text('This is a locally patched SDCC candidate. candidate-provenance.json records\n'
                     'the source, patch, native build environment and system dependencies.\n'
                     'MANIFEST.sha256 covers every payload file and internal file link except itself.\n'
                     'A public release still needs corresponding source and build materials.\n'
                     'Package metadata does not qualify Arduino or physical device execution.\n', encoding='utf-8')
    readme.chmod(0o644)
    if any(sha256(path) != hashes[name] for name, path in inputs.items()): raise RuntimeError('packaging input changed')
    current = inventory(package)
    if {name: current[name] for name in initial} != initial: raise RuntimeError('package payload changed during finalization')
    provenance = package / 'candidate-provenance.json'
    provenance.write_text(json.dumps(metadata, indent=2, sort_keys=True) + '\n', encoding='utf-8'); provenance.chmod(0o644)
    print('MACOS_METADATA_FILES=' + str(len(write_manifest(package))))


if __name__ == '__main__': main()
