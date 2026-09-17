#!/usr/bin/env python3
"""Bind verified native Windows compiler packages to the Arduino runtime lock."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tarfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--package-metadata', required=True, type=Path)
    parser.add_argument('--sdcc-root', required=True, type=Path)
    parser.add_argument('--sdcc-archive', required=True, type=Path)
    args = parser.parse_args()
    package = json.loads(args.package_metadata.read_text(encoding='utf-8'))
    archive = Path(package['archive'])
    if package['host'] != 'windows-x86_64' or digest(archive) != package['archive_sha256']:
        raise ValueError('frontend archive differs from its native build metadata')
    lock = json.loads((ROOT / 'tools/cpp-cli/toolchain-lock.macos-arm64.json').read_text(encoding='utf-8'))
    tools = json.loads((ROOT / 'tools/toolchain-manifest.json').read_text(encoding='utf-8'))['components']
    sdcc_tool = next(t for t in tools if t['id'] == 'sdcc-mcs251')
    windows = next(s for s in sdcc_tool['systems'] if s['host'] == 'x86_64-mingw32')
    expected_sdcc = windows['sha256']
    if windows['sourcePatchSha256'] != lock['tools']['sdcc']['patch_sha256']:
        raise ValueError('Windows SDCC source patch differs from the native target ABI')
    if digest(args.sdcc_archive) != expected_sdcc:
        raise ValueError('SDCC archive differs from the source-bound Windows compiler')
    with zipfile.ZipFile(args.sdcc_archive) as packed:
        for item in packed.infolist():
            if item.is_dir():
                continue
            relative = Path(item.filename).parts[1:]
            path = args.sdcc_root.joinpath(*relative)
            if hashlib.sha256(packed.read(item)).hexdigest() != digest(path):
                raise ValueError('installed SDCC differs from archive: ' + str(path))
    with tarfile.open(archive) as packed:
        manifest = packed.extractfile('stcxx-frontend/MANIFEST.sha256').read()
        if hashlib.sha256(manifest).hexdigest() != package['manifest_sha256']:
            raise ValueError('frontend manifest differs from archive')
    lock['host'] = 'windows-x86_64'
    lock['qualification'] = 'native Windows x64 distribution; release execution evidence recorded separately'
    lock.pop('macos_frontend', None)
    lock['tools'].pop('llvm_shared_library', None)
    for name, row in package['tools'].items():
        lock['tools'][name].update(row)
        lock['tools'][name].pop('shared_library_sha256', None)
    for name in ('sdcc', 'sdar', 'sdas251', 'sdld', 'sdldmcs251', 'sdcpp'):
        lock['tools'][name]['sha256'] = digest(args.sdcc_root / 'bin' / (name + '.exe'))
    sdcc = lock['tools']['sdcc']
    sdcc['windows_package_archive_sha256'] = expected_sdcc
    sdcc['native_package_manifest_sha256'] = digest(args.sdcc_root / 'MANIFEST.sha256')
    sdcc['elf_sha256'] = sdcc['sha256']  # Historical key; this host runs a PE executable.
    for name in ('native_package_archive_sha256', 'distribution_archive_sha256', 'distribution_provenance_sha256'):
        sdcc.pop(name, None)
    version = subprocess.check_output([str(args.sdcc_root / 'bin/sdcc.exe'), '--version'], text=True).splitlines()[0]
    if not version.startswith(sdcc['version_prefix']):
        raise ValueError('unexpected native SDCC version: ' + version)
    for filename, key in [('stddef.h', 'stddef_sha256'), ('stdint.h', 'stdint_sha256')]:
        lock['tools']['sdcc_inputs'][key] = digest(args.sdcc_root / 'include' / filename)
    runtime = args.sdcc_root / 'lib/mcs251-large-stack-auto'
    lock['targets']['mcs251']['sdcc_inputs'] = {'libsdcc_sha256': digest(runtime / 'libsdcc.lib'),
                                             'target_runtime_sha256': digest(runtime / 'mcs251.lib')}
    lock['tools']['sdcc_inputs']['libsdcc_sha256'] = digest(runtime / 'libsdcc.lib')
    lock['tools']['sdcc_inputs']['mcs251_sha256'] = digest(runtime / 'mcs251.lib')
    lock['windows_sdcc_files'] = {p.relative_to(args.sdcc_root).as_posix(): digest(p)
                                  for p in sorted((args.sdcc_root / 'bin').iterdir()) if p.is_file()}
    lock['windows_frontend'] = {key: package[key] for key in ('archive_sha256', 'manifest_sha256', 'bootstrap_files')}
    # A changed component requires repackaging and rebinding the unified archive.
    lock.pop('toolchain_package', None)
    driver = {'path': 'tools/cpp-cli/stcxx-cli.py', 'sha256': digest(ROOT / 'tools/cpp-cli/stcxx-cli.py')}
    lock['pipeline_helpers']['windows_cli_driver'] = driver
    lock['pipeline_helpers']['arduino_cli_driver'] = driver
    output = ROOT / 'tools/cpp-cli/toolchain-lock.windows-x86_64.json'
    output.write_text(json.dumps(lock, indent=2) + '\n', encoding='utf-8', newline='\n')
    print('PASS:', output)


if __name__ == '__main__':
    main()
