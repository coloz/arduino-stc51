#!/usr/bin/env python3
"""Create a Mac or Linux Board Manager candidate from pinned SDK/tool archives.

This creates an index for installation testing; it neither publishes assets nor
grants release qualification. The SDK archive supplies its version and tool lock.
"""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import tarfile
from urllib.parse import urlsplit


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha256(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


HOSTS = {'arm64-apple-darwin': ('toolchain-lock.macos-arm64.json', 'darwin-arm64',
                               'native_package_archive_sha256', 'macos_frontend'),
         'x86_64-pc-linux-gnu': ('toolchain-lock.json', 'linux-x86_64',
                               'distribution_archive_sha256', 'linux_frontend'),
         'x86_64-mingw32': ('toolchain-lock.windows-x86_64.json', 'windows-x86_64',
                            'windows_package_archive_sha256', 'windows_frontend')}


def sdk_metadata(path, host='arm64-apple-darwin'):
    require(host in HOSTS, 'Unsupported candidate host')
    with tarfile.open(path) as archive:
        members = {}
        roots = set()
        for member in archive:
            name = PurePosixPath(member.name)
            require(not name.is_absolute() and '..' not in name.parts and '\\' not in member.name,
                    'Unsafe SDK archive path')
            require(member.name not in members and (member.isfile() or member.isdir()),
                    'Duplicate or unsupported SDK archive entry')
            members[member.name] = member
            roots.add(name.parts[0])
        require(len(roots) == 1, 'SDK archive must have one root directory')
        root = next(iter(roots))

        def read(name):
            member = members.get(root + '/' + name)
            require(member is not None and member.isfile(), 'Missing SDK metadata: ' + name)
            return archive.extractfile(member).read().decode('utf-8')

        properties = {}
        for line in read('platform.txt').splitlines():
            if line and not line.startswith('#') and '=' in line:
                key, value = line.split('=', 1)
                require(key not in properties, 'Duplicate platform property: ' + key)
                properties[key] = value
        version = properties.get('version', '')
        require(re.fullmatch(r'\d+\.\d+\.\d+', version), 'Invalid platform version')
        require(root == 'arduino-stc51-' + version, 'Archive root/version differ')
        if host == 'x86_64-mingw32':
            require(properties.get('compiler.ar.path.windows') == '{runtime.tools.sdcc-mcs251.path}/bin',
                    'Windows distribution must select the current SDCC archive helper')
            require(properties.get('compiler.shell.cmd.windows') == 'powershell.exe' and
                    properties.get('compiler.wrapper.compile.windows') ==
                    '"{compiler.wrapper.path}/stc-windows.ps1" compile',
                    'Windows distribution must use the system PowerShell adapter')
            read('tools/wrapper/stc-windows.ps1')
        lock = json.loads(read('tools/cpp-cli/' + HOSTS[host][0]))
        devices = json.loads(read('tools/variants/devices.json'))['devices']
        require(devices and all(d['target'] == 'mcs251' for d in devices), 'Invalid SDK target scope')
        require(len({d['id'] for d in devices}) == len(devices), 'Duplicate SDK board')
        return version, lock, devices


def create(platform, sdcc, frontend, sdcc_version, base_url, output, host='arm64-apple-darwin'):
    require(host in HOSTS, 'Unsupported candidate host')
    parsed = urlsplit(base_url)
    require(parsed.scheme == 'https' or (parsed.scheme == 'http' and parsed.hostname in ('127.0.0.1', 'localhost', '::1')),
            'Use HTTPS or a loopback HTTP URL for local installation tests')
    require(parsed.netloc and not parsed.query and not parsed.fragment and not parsed.username and not parsed.password,
            'Invalid asset base URL')
    require(re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._+-]*', sdcc_version), 'Invalid SDCC tool version')
    archives = [platform, sdcc, frontend]
    require(len({p.name for p in archives}) == len(archives), 'Archive filenames must be distinct')
    require(all(re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._+-]*', p.name) for p in archives), 'Unsafe archive filename')
    require(not output.exists() and not output.is_symlink(), 'Output index already exists')
    before = {str(p): sha256(p) for p in archives}
    version, lock, devices = sdk_metadata(platform, host)
    binding = lock.get('arduino_frontend')
    require(isinstance(binding, dict) and set(binding) == {'packager', 'name', 'version'} and
            binding['packager'] == 'arduino-stc51' and binding['name'] == 'stcxx-frontend' and
            isinstance(binding['version'], str) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._+-]*', binding['version']),
            'SDK must bind its exact Arduino frontend dependency')
    _, lock_host, sdcc_archive_key, frontend_key = HOSTS[host]
    require(lock.get('host') == lock_host, 'SDK lock is not for ' + host)
    require(before[str(sdcc)] == lock['tools']['sdcc'][sdcc_archive_key], 'SDCC archive differs from SDK lock')
    require(before[str(frontend)] == lock[frontend_key]['archive_sha256'], 'Frontend archive differs from SDK lock')

    def asset(path):
        return {'url': base_url.rstrip('/') + '/' + path.name, 'archiveFileName': path.name,
                'checksum': 'SHA-256:' + before[str(path)], 'size': str(path.stat().st_size)}

    dependencies = [{'packager': 'arduino-stc51', 'name': 'sdcc-mcs251', 'version': sdcc_version}, binding]
    tool_assets = [('sdcc-mcs251', sdcc_version, sdcc), (binding['name'], binding['version'], frontend)]
    package = {'name': 'arduino-stc51', 'maintainer': 'arduino-stc51 contributors',
               'websiteURL': 'https://github.com/coloz/arduino-stc51', 'email': '',
               'help': {'online': 'https://github.com/coloz/arduino-stc51/issues'},
               'platforms': [{'name': 'arduino-stc51', 'architecture': 'mcs251', 'version': version,
                              'category': 'Contributed', **asset(platform),
                              'boards': [{'name': d['model']} for d in devices], 'toolsDependencies': dependencies}],
               'tools': [{'name': name, 'version': tool_version,
                          'systems': [{'host': host, **asset(path)}]}
                         for name, tool_version, path in tool_assets]}
    require(all(sha256(p) == before[str(p)] for p in archives), 'Archive input changed during index generation')
    with output.open('x', encoding='utf-8') as stream:
        json.dump({'packages': [package]}, stream, indent=2)
        stream.write('\n')
    return {'status': 'PASS_CANDIDATE_INDEX_GENERATION', 'production_qualified': False,
            'host': host, 'version': version, 'index_sha256': sha256(output), 'inputs': before}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('platform', 'sdcc', 'frontend', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--sdcc-version', required=True)
    parser.add_argument('--base-url', required=True)
    parser.add_argument('--host', choices=sorted(HOSTS), default='arm64-apple-darwin')
    args = parser.parse_args()
    try:
        result = create(args.platform, args.sdcc, args.frontend, args.sdcc_version, args.base_url, args.output, args.host)
    except (ValueError, OSError, KeyError, tarfile.TarError) as error:
        parser.exit(2, str(error) + '\n')
    print(json.dumps(result))


if __name__ == '__main__':
    main()
