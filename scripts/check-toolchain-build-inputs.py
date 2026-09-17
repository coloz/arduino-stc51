#!/usr/bin/env python3
"""Check that POSIX SDCC builders consume the SDK's locked compiler sources.

This is a source-input consistency check, not a host compiler build or a
release qualification. Public binary archive identities are left untouched.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
BUILDERS = ('build-linux-toolchain.sh', 'build-macos-toolchain.sh')
FIELDS = ('TAG', 'COMMIT', 'PACKAGE_REVISION', 'PATCH_SHA256', 'PREPROCESSOR_PATCH_SHA256', 'PATCHED_GEN_BLOB')


def require(condition, message):
    if not condition:
        raise ValueError(message)


def literal(source, field):
    # Fail on a later override or an expression rather than evaluating shell
    # code while inspecting its source identity.
    assignments = re.findall(r'^\s*(?:export\s+)?' + field + r'\s*=(.*)$', source, re.M)
    require(len(assignments) == 1, 'expected one literal assignment: ' + field)
    value = assignments[0].strip()
    require(re.fullmatch(r'[A-Za-z0-9_.-]+', value) is not None,
            'nonliteral source identity: ' + field)
    return value


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check_compiler(root, compiler_root, sdk_lock, builders):
    """Check the development publication without changing any pinned input."""
    compiler_root = Path(compiler_root).resolve()
    source_path = compiler_root / 'arduino/toolchain-lock.json'
    source = json.loads(source_path.read_text(encoding='utf-8'))
    sdcc = source['sdcc']
    require(sdcc['base_commit'] == sdk_lock['upstream_base_commit'], 'compiler/SDK base commits differ')
    require(sdcc['patch_sha256'] == sdk_lock['patch_sha256'], 'compiler/SDK patch locks differ')
    require(all(row['PATCHED_GEN_BLOB'] == sdcc['patched_source_blobs']['src/mcs251/gen.c']
                for row in builders.values()), 'builders differ from the locked compiler generator')
    inputs = [source_path]

    def checked(relative, expected):
        path = compiler_root / relative
        require(path.resolve().is_relative_to(compiler_root), 'compiler input escapes root: ' + relative)
        require(digest(path) == expected, 'compiler input differs from lock: ' + relative)
        inputs.append(path)

    checked(sdcc['patch'], sdcc['patch_sha256'])
    reproduction = source['clang']['reproduction_inputs']
    for key in ('build_script', 'prepare_script', 'source_check_script'):
        checked(reproduction[key], reproduction[key + '_sha256'])
    checked('out/toolchain-lock.json', digest(source_path))
    require(sdk_lock['published_out_lock_sha256'] == digest(source_path), 'SDK published source lock differs')
    checked('out/MANIFEST.sha256', sdk_lock['published_out_manifest_sha256'])
    require(sdcc['reference_elf_sha256'] == sdk_lock['elf_sha256'], 'compiler/SDK driver identities differ')
    checked('out/libexec/sdcc', sdcc['reference_elf_sha256'])
    checked('out/bin/sdcc', sdk_lock['sha256'])
    core_path = root / 'cores/STC/cpp/core-manifest.json'
    core = json.loads(core_path.read_text(encoding='utf-8'))

    def bindings(value, key):
        if isinstance(value, dict):
            return ([value[key]] if key in value else []) + [item for child in value.values()
                    for item in bindings(child, key)]
        if isinstance(value, list):
            return [item for child in value for item in bindings(child, key)]
        return []

    for key in ('published_out_lock_sha256', 'published_out_manifest_sha256'):
        require(bindings(core, key) == [sdk_lock[key]], 'core/SDK publication bindings differ: ' + key)
    return {'inputs_sha256': {p.relative_to(compiler_root).as_posix(): digest(p) for p in inputs},
            'core_manifest_sha256': digest(core_path)}


def check(root, compiler_root=None):
    root = Path(root)
    lock_path = root / 'tools/cpp-cli/toolchain-lock.json'
    manifest_path = root / 'tools/toolchain-manifest.json'
    lock = json.loads(lock_path.read_text(encoding='utf-8'))['tools']['sdcc']
    tools = json.loads(manifest_path.read_text(encoding='utf-8'))['components']
    source_entries = [tool for tool in tools if tool['id'] == 'sdcc-mcs251']
    require(len(source_entries) == 1, 'missing or duplicate compiler source identity')
    upstream = source_entries[0]
    require(lock['upstream_base_commit'] == upstream['sourceCommit'], 'SDK source commits differ')
    patch = root / 'tools/toolchain-patches/sdcc-mcs251-arduino-cpp.patch'
    patch_sha = digest(patch)
    require(patch_sha == lock['patch_sha256'], 'SDK patch differs from the C++ toolchain lock')
    preprocessor_patch = root / lock['preprocessor_patch_file']
    preprocessor_sha = digest(preprocessor_patch)
    require(preprocessor_sha == lock['preprocessor_patch_sha256'], 'Preprocessor patch differs from its lock')
    expected = {'TAG': upstream['sourceTag'], 'COMMIT': lock['upstream_base_commit'],
                'PATCH_SHA256': patch_sha, 'PREPROCESSOR_PATCH_SHA256': preprocessor_sha}
    inputs = [lock_path, manifest_path, patch, preprocessor_patch]
    for name in ('toolchain-lock.windows-x86_64.json', 'toolchain-lock.macos-arm64.json'):
        path = root / 'tools/cpp-cli' / name
        distributed = json.loads(path.read_text(encoding='utf-8'))['tools']['sdcc']
        require(distributed['patch_sha256'] == patch_sha and
                distributed['preprocessor_patch_sha256'] == preprocessor_sha and
                distributed['upstream_base_commit'] == lock['upstream_base_commit'],
                'distribution compiler sources differ: ' + name)
        inputs.append(path)
    builders = {}
    for name in BUILDERS:
        path = root / 'scripts' / name
        source = path.read_text(encoding='utf-8')
        pins = {field: literal(source, field) for field in FIELDS}
        for field, value in expected.items():
            require(pins[field] == value, name + ': stale ' + field)
        require(re.fullmatch(r'[1-9][0-9]*', pins['PACKAGE_REVISION']) is not None,
                name + ': invalid package revision')
        require(re.fullmatch(r'[0-9a-f]{40}', pins['PATCHED_GEN_BLOB']) is not None,
                name + ': invalid patched generator identity')
        builders[name] = pins
        inputs.append(path)
    require(len({pins['PATCHED_GEN_BLOB'] for pins in builders.values()}) == 1,
            'Linux/macOS patched generator identities differ')
    report = {'status': 'PASS', 'production_qualified': False, 'scope': __doc__, 'builders': builders,
              'inputs_sha256': {p.relative_to(root).as_posix(): digest(p) for p in inputs}}
    if compiler_root is not None:
        report['compiler'] = check_compiler(root, compiler_root, lock, builders)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--compiler-root', type=Path,
                        help='also verify the stcxx source lock, reproduction scripts and published development driver')
    args = parser.parse_args()
    try:
        report = check(args.root, args.compiler_root)
    except (OSError, ValueError, KeyError, TypeError) as error:
        report = {'status': 'FAIL', 'production_qualified': False, 'error': str(error)}
    print(json.dumps(report, indent=2))
    return 0 if report['status'] == 'PASS' else 1


if __name__ == '__main__':
    sys.exit(main())
