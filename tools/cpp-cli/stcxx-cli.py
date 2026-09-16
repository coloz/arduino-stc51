#!/usr/bin/env python3
"""Native Windows C++ driver. All compiler processes are Windows executables.

The shared metadata and ABI/link audits are also used by the macOS driver.
Arguments arrive as NUL-delimited UTF-8; no command is evaluated by a shell.
"""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

HERE = Path(__file__).resolve().parent
PLATFORM = HERE.parents[1]
HELPERS = {
    'archive_member_reader': 'archive_members.py',
    'cpp_archive_selector': 'select-cpp-archive-sidecars.py',
    'aslink_map_symbols': 'aslink_map_symbols.py',
    'cbe_audit_adapter': '../cpp-core-pipeline/audit_and_adapt.py',
    'arduino_cli_adapter': 'adapt.py',
    'native_storage': 'native-storage.py',
    'member_function_aligner': 'align-member-functions.py',
    'readonly_const_slicer': 'slice-readonly-const-rel.py',
    'function_tu_splitter': 'split-c-function-tu.py',
    'function_archive_builder': 'build-function-split-archive.py',
    'function_link_map_auditor': 'audit-function-split-link-map.py',
    'c_abi_root_collector': 'collect-c-abi-roots.py',
}
SHARED_CHECKS = ('cpp-metadata', 'c-metadata', 'check-heap', 'check-sidecars',
                 'audit-bridge-warnings', 'audit-heap-link', 'write-link-manifest')


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha256(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def check_hash(path, expected):
    require(Path(path).is_file() and sha256(path) == expected, 'SHA-256 mismatch: ' + str(path))


def absolute(value):
    return Path(value).resolve()


def write(path, value):
    Path(path).write_text(value, encoding='utf-8', newline='\n')


def nonempty(path):
    require(Path(path).is_file() and Path(path).stat().st_size, 'missing or empty output: ' + str(path))


def run(argv, *, capture=False, log=None, cwd=None, allowed=(0,)):
    command = list(map(str, argv))
    result = subprocess.run(command, cwd=cwd, stdout=subprocess.PIPE if capture or log else None,
                            stderr=subprocess.STDOUT if log else None)
    if log:
        Path(log).write_bytes(result.stdout)
        sys.stderr.buffer.write(result.stdout)
    if result.returncode not in allowed:
        if capture and not log and result.stdout:
            sys.stderr.buffer.write(result.stdout)
        raise subprocess.CalledProcessError(result.returncode, command)
    return result if capture or log or len(allowed) > 1 else None


def helper(name, *args, **kwargs):
    return run([sys.executable, '-B', HERE / (name + '.py'), *args], **kwargs)


def archive_member(sdar, archive, member):
    # Isolated Python excludes the script directory from sys.path.
    spec = importlib.util.spec_from_file_location('archive_members', HERE / 'archive_members.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.read_member(sdar, archive, member)


def installed_tool(binding):
    require(isinstance(binding, dict) and set(binding) == {'packager', 'name', 'version'} and
            all(isinstance(v, str) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._+-]*', v)
                for v in binding.values()), 'invalid Arduino tool binding')
    require(PLATFORM.parent.name == 'mcs251' and PLATFORM.parents[1].name == 'hardware' and
            PLATFORM.parents[3].name == 'packages', 'set STCXX_CPP_TOOLS_ROOT for a source checkout')
    return PLATFORM.parents[3] / binding['packager'] / 'tools' / binding['name'] / binding['version']


class Driver:
    def __init__(self, mode, source, output, argument_file):
        require(sys.platform == 'win32', 'this driver requires native Windows')
        self.mode, self.source = mode, absolute(source)
        self.output = None if output.lower() in ('nul', 'nul:', '/dev/null') else absolute(output)
        self.lock_path = HERE / 'toolchain-lock.windows-x86_64.json'
        self.lock = json.loads(self.lock_path.read_text(encoding='utf-8'))
        require(self.lock['host'] == 'windows-x86_64', 'not a native Windows tool lock')
        payload = Path(argument_file).read_bytes()
        require(not payload or payload.endswith(b'\0'), 'unterminated argument file')
        self.arguments = payload.decode('utf-8').split('\0')[:-1]
        require(mode == 'link' or self.source.is_file(), 'missing compile input: ' + str(self.source))
        root = os.environ.get('STCXX_CPP_TOOLS_ROOT')
        self.frontend = absolute(root) if root else installed_tool(self.lock['arduino_frontend']).resolve()
        self.tools = {n: self.frontend / 'bin' / (n + '.exe') for n in ('clang', 'llvm-link', 'opt', 'llvm-dis', 'llvm-cbe')}
        sdcc = os.environ.get('STCXX_SDCC') or os.environ.get('STCXX_ARDUINO_SDCC')
        require(sdcc, 'native Arduino SDCC path is missing')
        if not Path(sdcc).is_file():
            sdcc += '.exe'
        self.sdcc = absolute(sdcc)
        self.sdcc_root = self.sdcc.parents[1]
        self.includes = self.sdcc_root / 'include'
        self.runtime = self.sdcc_root / 'lib/mcs251-large-stack-auto'
        self.cpp_headers = PLATFORM / 'cores/STC/cpp'
        self.sdar = self.sdcc_root / 'bin/sdar.exe'
        self.assembler = self.sdcc_root / 'bin/sdas251.exe'
        self.target = self.lock['targets']['mcs251']
        self.triple = self.target['target_triple']
        self.layout = self.target['data_layout']
        self.abi = self.target['abi_identity_symbol']
        self.clang_args, self.sdcc_args, self.sections = [], [], []
        self.dependency = None
        self.optimization = '0'
        self.stack = {}
        self.parse_arguments()

    def parse_arguments(self):
        optimization_count = clock_count = constrained = 0
        cpp = False
        target = ''
        clock = ''
        pending_dependency = False
        for arg in self.arguments:
            if pending_dependency:
                self.dependency = absolute(arg)
                pending_dependency = False
                continue
            if arg == '-MF':
                pending_dependency = True
            elif arg == '-DSTCXX_CPP_OPT' or arg.startswith('-DSTCXX_CPP_OPT='):
                optimization_count += 1
                self.optimization = arg.partition('=')[2]
                require(optimization_count == 1 and self.optimization in ('0', '1', '2', 's', 'z'),
                        'STCXX_CPP_OPT must occur once with value 0, 1, 2, s or z')
            elif arg in ('-mmcs51', '-DSTCXX_TARGET_MCS51=1', '-DSTC16F40K128') or arg.startswith('-DSTC_EXECUTION_MODE_MCS51'):
                raise ValueError('MCS51 support has been removed; select an MCS251 board')
            elif any(arg.startswith('-DSTCXX_MCS251_' + name + '=') for name in ('IRAM_SIZE', 'STACK_LOC', 'STACK_SIZE')):
                key, value = arg.removeprefix('-DSTCXX_MCS251_').split('=', 1)
                self.stack[key] = value
            elif arg.startswith('-DSTCXX_MCS251_CONSTRAINED_HEAP='):
                require(arg.endswith('=1'), 'STCXX_MCS251_CONSTRAINED_HEAP must be exactly 1')
                constrained += 1
                self.clang_args.append(arg)
                self.sdcc_args.append(arg)
            elif arg.startswith('-DF_CPU='):
                clock_count += 1
                clock = arg.split('=', 1)[1].rstrip('UL')
                self.clang_args.append(arg)
                self.sdcc_args.append(arg)
            elif arg == '-mmcs251':
                target = 'mcs251'
                self.sdcc_args.append(arg)
            elif arg == '-Ddouble=float':
                pass
            elif arg.startswith('-D'):
                cpp |= arg == '-DSTCXX_CPP_CORE=1'
                self.clang_args.append(arg)
                self.sdcc_args.append(arg)
            elif arg.startswith('-I'):
                path = absolute(arg[2:])
                normalized = '-I' + str(path)
                if path != self.includes and self.includes not in path.parents:
                    self.clang_args.append(normalized)
                self.sdcc_args.append(normalized)
            elif arg in ('--function-sections', '--data-sections'):
                self.sdcc_args.append(arg)
                self.sections.append(arg)
            elif arg in ('-c', '--std-sdcc11', '--opt-code-size', '--less-pedantic', '--stack-auto', '--model-large', '-MMD', '-Wp-Wall', '-V'):
                self.sdcc_args.append(arg)
            elif arg in ('-M', '-MG', '-MP', '-E', '-dM'):
                pass
            elif self.mode == 'compile-c':
                self.sdcc_args.append(arg)
            elif self.mode != 'link':
                raise ValueError('unsupported Arduino C++ compiler argument: ' + arg)
        require(not pending_dependency, '-MF is missing its destination')
        require(cpp and target == 'mcs251', 'MCS251 C++ profile is required')
        require(clock_count == 1 and (clock == '12000000' or
                clock == '40000000' and '-DAI8051U_34K64' in self.arguments or
                clock == '48000000' and '-DSTC32G144K246' in self.arguments), 'unsupported C++ clock/profile')
        require(not ('-DSTC32G144K246' in self.arguments and '-DAI8051U_34K64' in self.arguments), 'conflicting board identities')
        require(constrained <= 1, 'duplicate constrained-heap identity')
        self.clock, self.constrained = clock, constrained
        flags = ['-DSTCXX_TARGET_ABI=1', '-DSTCXX_TARGET_MCS251=1', '-DSTCXX_TARGET_ENDIAN_LITTLE=0', '-DSTCXX_TARGET_ENDIAN_BIG=1']
        self.clang_args += flags
        self.sdcc_args += flags
        if self.mode == 'link':
            require(set(self.stack) == {'IRAM_SIZE', 'STACK_LOC', 'STACK_SIZE'} and
                    all(re.fullmatch(r'0x[0-9A-Fa-f]+', v) for v in self.stack.values()), 'invalid extended-stack layout')

    def verify(self):
        check_hash(HERE / 'verify-macos-frontend.py', self.lock['pipeline_helpers']['macos_frontend_verifier']['sha256'])
        spec = importlib.util.spec_from_file_location('frontend_verifier', HERE / 'verify-macos-frontend.py')
        verifier = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(verifier)
        verifier.verify(self.frontend, self.lock['windows_frontend']['manifest_sha256'], self.tools, os.environ)
        for name, executable in self.tools.items():
            check_hash(executable, self.lock['tools'][name.replace('-', '_')]['sha256'])
        for key, filename in HELPERS.items():
            check_hash(HERE / filename, self.lock['pipeline_helpers'][key]['sha256'])
        for name in SHARED_CHECKS:
            check_hash(HERE / (name + '.py'), self.lock['shared_checks'][name])
        for name in ('sdcc', 'sdar', 'sdas251', 'sdld', 'sdldmcs251', 'sdcpp'):
            check_hash(self.sdcc_root / 'bin' / (name + '.exe'), self.lock['tools'][name]['sha256'])
        for name, expected in self.lock['windows_sdcc_files'].items():
            check_hash(self.sdcc_root / name, expected)
        for name, key in [('stddef.h', 'stddef_sha256'), ('stdint.h', 'stdint_sha256')]:
            check_hash(self.includes / name, self.lock['tools']['sdcc_inputs'][key])
        check_hash(self.runtime / 'libsdcc.lib', self.target['sdcc_inputs']['libsdcc_sha256'])
        check_hash(self.runtime / 'mcs251.lib', self.target['sdcc_inputs']['target_runtime_sha256'])
        if self.sections:
            help_text = run([self.sdcc, '-mmcs251', '--help'], capture=True).stdout.decode(errors='replace')
            require('--function-sections' in help_text and '--data-sections' in help_text, 'SDCC lacks full-Flash section support')
        version = run([self.sdcc, '--version'], capture=True).stdout.decode(errors='replace')
        require(version.startswith(self.lock['tools']['sdcc']['version_prefix']), 'unexpected SDCC version')
        version = run([self.tools['clang'], '--version'], capture=True).stdout.decode(errors='replace')
        require('clang version ' + self.lock['tools']['clang']['version'] in version, 'unexpected Clang version')

    def prepare_clang(self):
        self.resource = absolute(run([self.tools['clang'], '--print-resource-dir'], capture=True).stdout.decode().strip())
        require((self.resource / 'include').is_dir() and self.cpp_headers.is_dir(), 'missing C++ resource headers')
        self.clang_base = [self.tools['clang'], '--target=' + self.triple, '-x', 'c++', '-std=gnu++11', '-O' + self.optimization,
                           '-fno-vectorize', '-fno-slp-vectorize', '-ffreestanding', '-fno-builtin', '-funsigned-char',
                           '-fno-exceptions', '-fno-rtti', '-fno-threadsafe-statics', '-fno-use-cxa-atexit',
                           '-fno-c++-static-destructors', '-fno-unwind-tables', '-fno-asynchronous-unwind-tables',
                           '-Xclang', '-mno-constructor-aliases', '-Xclang', '-disable-O0-optnone',
                           '-nostdinc', '-I' + str(self.cpp_headers), '-isystem' + str(self.resource / 'include'),
                           '-Werror', '-Wno-error=cpp', '-Wno-error=ignored-qualifiers']

    def compile(self):
        self.verify()
        self.prepare_clang()
        if self.output:
            self.output.parent.mkdir(parents=True, exist_ok=True)
        if self.mode == 'preprocess-deps':
            run([*self.clang_base, *self.clang_args, '-M', '-MG', '-MP', self.source])
        elif self.mode == 'preprocess-macros':
            if self.dependency:
                self.dependency.parent.mkdir(parents=True, exist_ok=True)
                result = subprocess.run(list(map(str, [*self.clang_base, *self.clang_args, '-dM', '-E', self.source])),
                                        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
                if result.returncode:
                    error = result.stderr.decode('utf-8', errors='replace')
                    error = re.sub(r"^(.*:\d+:\d+): fatal error: '([^']+)' file not found$",
                                   r'\1: fatal error: \2: No such file or directory', error, flags=re.M)
                    sys.stderr.write(error)
                    raise subprocess.CalledProcessError(result.returncode, str(self.tools['clang']))
                run([*self.clang_base, *self.clang_args, '-M', '-MP', '-MF', self.dependency, self.source])
                nonempty(self.dependency)
            elif self.output:
                run([*self.clang_base, *self.clang_args, '-E', '-CC', self.source, '-o', self.output])
            else:
                run([*self.clang_base, *self.clang_args, '-dM', '-E', self.source])
        elif self.mode == 'compile-cpp':
            require(self.output is not None, 'missing object output')
            bc, ir, cbe = [Path(str(self.output) + suffix) for suffix in ('.stcxx.bc', '.stcxx.ll', '.stcxx.module.cbe')]
            command = [*self.clang_base, *self.clang_args, '-emit-llvm', '-c', self.source, '-o', bc]
            write(str(self.output) + '.stcxx-command.txt', subprocess.list2cmdline(list(map(str, command))) + '\n')
            run(command)
            run([self.tools['llvm-dis'], bc, '-o', ir])
            content = ir.read_text(encoding='utf-8')
            require('target datalayout = "' + self.layout + '"' in content.splitlines() and
                    'target triple = "' + self.triple + '"' in content.splitlines(), 'C++ target ABI mismatch')
            require(not re.search(r'^@[A-Za-z0-9_.$"-]+\s*=[^;\n]*\salias\s', content, re.M), 'constructor/function alias gate failed')
            run([self.tools['llvm-cbe'], bc, '-o', cbe])
            rel = self.output.with_suffix('.rel')
            placeholder = Path(str(self.output) + '.stcxx-placeholder.c')
            identity = hashlib.sha256((str(self.source) + '\n' + str(self.output) + '\n').encode()).hexdigest()[:16]
            write(placeholder, 'void __stcxx_placeholder_' + identity + '(void) {}\n')
            try:
                run([self.sdcc, '-mmcs251', '--model-large', '--stack-auto', '--std-sdcc11', '--opt-code-size',
                     '--less-pedantic', '-c', placeholder, '-o', rel], cwd=self.output.parent)
                shutil.copyfile(rel, self.output)
            finally:
                placeholder.unlink(missing_ok=True)
            helper('cpp-metadata', self.source, self.output, bc, ir, cbe, self.triple, self.layout, self.optimization)
        elif self.mode == 'compile-c':
            require(self.output is not None, 'missing object output')
            flags = list(self.sdcc_args)
            if '--stack-auto' not in flags:
                flags.append('--stack-auto')
            rel = self.output.with_suffix('.rel')
            run([self.sdcc, *flags, self.source, '-o', rel], cwd=rel.parent)
            shutil.copyfile(rel, self.output)
            helper('c-metadata', str(rel) + '.stcxx-c.json', self.source, rel, self.tools['clang'], self.sdcc,
                   self.triple, self.cpp_headers, self.resource, len(flags), *flags, *self.clang_args)
        else:
            raise ValueError('unsupported compile mode: ' + self.mode)

    def link(self):
        self.verify()
        output = self.output
        require(output is not None and output.suffix == '.hex', 'expected HEX output')
        outputs = [self.arguments[i + 1] for i, a in enumerate(self.arguments[:-1]) if a == '-o']
        require(len(outputs) == 1 and absolute(outputs[0]) == output, 'link output mismatch')
        work = output.parent / 'stcxx'
        work.mkdir(parents=True, exist_ok=True)
        # Never retain a successful-looking firmware after a failed audit.
        output.unlink(missing_ok=True)
        try:
            self.link_pipeline(work)
        except BaseException:
            output.unlink(missing_ok=True)
            raise

    def link_pipeline(self, work):
        direct_objects = [absolute(a) for a in self.arguments if a.endswith('.o')]
        archives = [absolute(a) for a in self.arguments if a.endswith('.a')]
        require(all(p.name != 'stcxx_heap.c.o' for p in direct_objects), 'heap entered direct Arduino inputs')
        bitcodes, direct_bitcodes, native_rels, candidates, heap_candidates = [], [], [], [], []
        members_tsv = work / 'cpp-archive-members.tsv'
        member_rows = []
        for obj in direct_objects:
            bc = Path(str(obj) + '.stcxx.bc')
            if bc.is_file():
                bitcodes.append(bc)
                direct_bitcodes.append(bc)
            else:
                rel = obj.with_suffix('.rel')
                nonempty(rel)
                native_rels.append(rel)
        for archive in archives:
            nonempty(archive)
            check_hash(archive.with_suffix('.lib'), sha256(archive))
            members = run([self.sdar, '-t', archive], capture=True).stdout.decode('utf-8').splitlines()
            require('stcxx_heap.c.rel' not in members, 'heap must not be stored in the core archive')
            heap = archive.parent / 'stcxx_heap.c.rel'
            if heap.is_file():
                check_hash(heap.with_suffix('.o'), sha256(heap))
                heap_candidates.append((heap, archive, members))
            selected = set()
            for bc in sorted(archive.parent.rglob('*.stcxx.bc')):
                obj = Path(str(bc).removesuffix('.stcxx.bc'))
                rel = obj.with_suffix('.rel')
                member = rel.name
                count = members.count(member)
                require(count <= 1, 'duplicate archive member: ' + member)
                if count == 1 and rel.is_file():
                    member_data = archive_member(self.sdar, archive, member)
                    if hashlib.sha256(member_data).hexdigest() == sha256(rel):
                        require(member not in selected, 'multiple sidecars match archive member: ' + member)
                        selected.add(member)
                        bitcodes.append(bc)
                        candidates += ['--candidate', archive, member, bc]
                        member_rows.append(str(archive) + '\t' + member)
        write(members_tsv, ''.join(row + '\n' for row in member_rows))
        require(len(heap_candidates) == 1, 'expected exactly one out-of-archive heap object')
        heap, heap_archive, heap_members = heap_candidates[0]
        heap_state = heap.parent / 'stcxx_heap_state.c.rel'
        helper('check-heap', heap, heap_state, 'mcs251', self.constrained)
        require(heap_members.count('stcxx_heap_state.c.rel') == 1, 'heap-state archive member is not unique')
        state_data = archive_member(self.sdar, heap_archive, 'stcxx_heap_state.c.rel')
        require(hashlib.sha256(state_data).hexdigest() == sha256(heap_state), 'heap-state archive payload differs')
        heap_members_file = work / 'core-archive-members.txt'
        write(heap_members_file, '\n'.join(heap_members) + '\n')
        require(bitcodes and len(set(bitcodes)) == len(bitcodes), 'missing or duplicate current-link bitcode sidecars')
        bitcodes.sort()
        helper('check-sidecars', self.triple, self.layout, *bitcodes)
        run([self.tools['llvm-link'], *bitcodes, '-o', work / 'all-candidates-linked.bc'])
        run([self.tools['llvm-dis'], work / 'all-candidates-linked.bc', '-o', work / 'all-candidates-linked.ll'])
        root_options = ['--sdar', self.sdar, '--cpp-members', members_tsv]
        for name in ('setup', 'loop', '__stcxx_run_global_ctors', self.abi, 'stcxx_runtime_panic'):
            root_options += ['--required-root', name]
        native_options = []
        for rel in native_rels:
            native_options += ['--direct-rel', rel]
        for archive in archives:
            native_options += ['--archive', archive]
        root_options += native_options
        helper('collect-c-abi-roots', '--ir', work / 'all-candidates-linked.ll',
               '--output', work / 'c-abi-preserve-discovery.txt', '--audit-json', work / 'c-abi-root-discovery-audit.json',
               *root_options, capture=True)
        selection = ['--llvm-link', self.tools['llvm-link'], '--llvm-dis', self.tools['llvm-dis'],
                     '--roots', work / 'c-abi-preserve-discovery.txt', '--work-dir', work / 'archive-selection',
                     '--output-bc', work / 'linked.bc', '--audit-json', work / 'cpp-archive-selection-audit.json']
        for bc in direct_bitcodes:
            selection += ['--direct', bc]
        helper('select-cpp-archive-sidecars', *selection, *candidates, capture=True)
        run([self.tools['llvm-dis'], work / 'linked.bc', '-o', work / 'linked.ll'])
        preserve = helper('collect-c-abi-roots', '--ir', work / 'linked.ll', '--output', work / 'c-abi-preserve.txt',
                          '--audit-json', work / 'c-abi-root-audit.json', *root_options, capture=True).stdout.decode().strip()
        require(preserve, 'empty C ABI preservation set')
        require((work / 'c-abi-preserve.txt').read_bytes() == (work / 'c-abi-preserve-discovery.txt').read_bytes(),
                'C ABI roots changed after archive selection')
        run([self.tools['opt'], '-passes=internalize,deadargelim,globaldce', '-internalize-public-api-list=' + preserve,
             work / 'linked.bc', '-o', work / 'optimized.bc'])
        run([self.tools['llvm-dis'], work / 'optimized.bc', '-o', work / 'optimized.ll'])
        helper('native-storage', '--ir', work / 'optimized.ll', '--output', work / 'native-storage.json',
               '--sdar', self.sdar, '--cpp-members', members_tsv, *native_options)
        run([self.tools['llvm-cbe'], work / 'optimized.bc', '-o', work / 'raw.c'])
        helper('adapt', '--ir', work / 'optimized.ll', '--raw-c', work / 'raw.c',
               '--native-storage', work / 'native-storage.json', '--c-abi-preserve', work / 'c-abi-preserve.txt',
               '--output-c', work / 'adapted.c', '--audit-json', work / 'audit.json',
               '--expected-triple', self.triple, '--expected-layout', self.layout,
               '--abi-identity-symbol', self.abi, '--target-profile', 'mcs251')
        raw_asm, asm, rel, lst, rst = [work / ('cpp-bridge.' + suffix) for suffix in ('raw.asm', 'asm', 'rel', 'lst', 'rst')]
        alignment = work / 'member-function-alignment-audit.json'
        prior_alignment = work / 'member-function-alignment-prior-audit.json'
        for path in (raw_asm, asm, rel, lst, rst, alignment, prior_alignment,
                     *(work / ('cpp-bridge.prior-even.' + s) for s in ('asm', 'rel', 'lst', 'rst'))):
            path.unlink(missing_ok=True)
        run([self.sdcc, '-mmcs251', '--model-large', '--stack-auto', '--std-sdcc11', '--opt-code-size',
             '--nogcse', '--less-pedantic', *self.sections, '-I' + str(self.includes),
             '-I' + str(self.includes / 'mcs51'), '-S', work / 'adapted.c', '-o', raw_asm],
            log=work / 'sdcc-bridge.log', cwd=work)
        nonempty(raw_asm)

        def assemble(parity):
            helper('align-member-functions', 'align', '--input-assembly', raw_asm, '--output-assembly', asm,
                   '--adapter-audit', work / 'audit.json', '--target-profile', 'mcs251',
                   '--local-parity', parity, '--audit-json', alignment)
            for path in (rel, lst, rst):
                path.unlink(missing_ok=True)
            run([self.assembler, '-plosgffw', rel, asm], log=work / 'sdcc-bridge-assembly.log', cwd=work)
            nonempty(rel)
            nonempty(lst)

        assemble('even')
        helper('audit-bridge-warnings', work / 'sdcc-bridge.log', work / 'sdcc-warning-audit.json', 'mcs251', work / 'audit.json')
        link_args = [str(rel), '-L' + str(self.runtime), '--iram-size', self.stack['IRAM_SIZE'],
                     '--stack-loc', self.stack['STACK_LOC'], '--stack-size', self.stack['STACK_SIZE']]
        heap_count = 0
        skip = False
        for arg in self.arguments:
            if skip:
                skip = False
                continue
            if arg.startswith('-DSTCXX') or arg == '-Ddouble=float':
                continue
            if arg == '-MF':
                skip = True
            elif arg.endswith('.o'):
                link_args.append(str(absolute(arg).with_suffix('.rel')))
            elif arg.endswith('.a'):
                archive = absolute(arg)
                if archive == heap_archive:
                    link_args.append(str(heap))
                    heap_count += 1
                link_args.append(str(archive.with_suffix('.lib')))
            elif Path(arg).is_absolute():
                link_args.append(str(absolute(arg)))
            else:
                link_args.append(arg)
        require(heap_count == 1, 'heap must be injected exactly once')
        link_args, readonly_audits, split_audits = self.trim_native_inputs(work, link_args)
        arguments_file = work / 'sdcc-link-arguments.txt'
        write(arguments_file, '\n'.join(link_args) + '\n')
        map_file = self.output.with_suffix('.map')

        def link():
            for path in (self.output, self.output.with_suffix('.mem'), map_file, rst):
                path.unlink(missing_ok=True)
            run([self.sdcc, *link_args], log=work / 'sdcc-link.log', cwd=work)
            for path in (self.output, map_file, rst):
                nonempty(path)

        link()
        verification = ['verify', '--audit-json', alignment, '--relocated-listing', rst, '--target-profile', 'mcs251']
        result = helper('align-member-functions', *verification, allowed=(0, 3))
        if result.returncode == 3:
            shutil.copyfile(alignment, prior_alignment)
            for path in (asm, rel, lst, rst):
                shutil.copyfile(path, work / ('cpp-bridge.prior-even' + path.suffix))
            assemble('odd')
            link()
            helper('align-member-functions', *verification)
        helper('audit-function-split-link-map', '--audit-list', split_audits, '--map', map_file, '--link-arguments', arguments_file)
        helper('native-storage', '--ir', work / 'optimized.ll', '--verify', work / 'native-storage.json', '--map', map_file)
        helper('audit-heap-link', work / 'heap-link-audit.json', work / 'sdcc-link.log', arguments_file,
               map_file, heap, heap_state, heap_archive, heap_members_file, HERE / 'aslink_map_symbols.py',
               'mcs251', self.stack['IRAM_SIZE'], self.stack['STACK_LOC'], self.stack['STACK_SIZE'])
        helper('write-link-manifest', work / 'manifest.json', self.output, self.lock_path, work / 'audit.json',
               work / 'sdcc-warning-audit.json', work / 'heap-link-audit.json', alignment,
               work / 'c-abi-preserve.txt', work / 'c-abi-root-audit.json', work / 'c-abi-root-discovery-audit.json',
               work / 'cpp-archive-selection-audit.json', HERE / 'collect-c-abi-roots.py',
               HERE / 'select-cpp-archive-sidecars.py', HERE / 'align-member-functions.py',
               HERE / 'slice-readonly-const-rel.py', HERE / 'split-c-function-tu.py',
               HERE / 'build-function-split-archive.py', HERE / 'audit-function-split-link-map.py',
               readonly_audits, split_audits, work / 'all-candidates-linked.bc', work / 'linked.bc', work / 'linked.ll',
               work / 'optimized.bc', work / 'optimized.ll', work / 'raw.c', work / 'adapted.c', raw_asm, asm, rel, lst, rst,
               'mcs251', self.triple, self.layout, self.abi, self.stack['IRAM_SIZE'], self.stack['STACK_LOC'],
               self.stack['STACK_SIZE'], self.clock, '--', *bitcodes)
        print('STCXX_ARDUINO_CLI_LINK=PASS')

    def trim_native_inputs(self, work, arguments):
        def limit(flag):
            indices = [i for i, value in enumerate(arguments) if value == flag]
            require(len(indices) == 1 and indices[0] + 1 < len(arguments), 'missing or duplicate ' + flag)
            value = arguments[indices[0] + 1]
            require(value.isdecimal() and int(value) > 0, 'invalid ' + flag)
            return int(value)

        code_limit, xram_limit = limit('--code-size'), limit('--xram-size')
        slice_work = work / 'readonly-const-slices'
        slice_work.mkdir(exist_ok=True)
        readonly_audits = slice_work / 'audit-files.txt'
        root_file = slice_work / 'direct-rel-link-closure.txt'
        direct = [a for a in arguments if a.endswith('.rel') and Path(a).is_file()]
        write(root_file, ''.join(a + '\n' for a in direct))
        readonly = {}
        slice_audits = []

        def area_sizes(path, pattern, required=False):
            sizes = re.findall(r'^A (' + pattern + r') size (\S+) flags ', Path(path).read_text(encoding='ascii'), re.M)
            require(not required or sizes, 'missing code area: ' + path)
            require(all(re.fullmatch('[0-9A-F]+', size) for _, size in sizes), 'invalid area size: ' + path)
            return sum(int(size, 16) for _, size in sizes)

        for path in direct:
            if area_sizes(path, r'CONST|CONST_D_\S+') <= code_limit:
                continue
            digest = sha256(path)
            stem = Path(path).name + '.' + digest[:16]
            output = slice_work / (stem + '.rel')
            audit = slice_work / (stem + '.audit.json')
            helper('slice-readonly-const-rel', '--input', path, '--root-list', root_file, '--expect-input-sha256', digest,
                   '--output', output, '--audit', audit)
            readonly[path] = str(output)
            slice_audits.append(str(audit))
        write(readonly_audits, ''.join(a + '\n' for a in slice_audits))
        actual = {p: readonly.get(p, p) for p in direct if Path(p + '.stcxx-c.json').is_file()}
        arguments = [readonly.get(a, a) for a in arguments]

        def library_group(path):
            match = re.match(r'^(.*?/libraries/[^/]+)/', Path(path).as_posix())
            return str(Path(match.group(1))) if match else None

        groups = set()
        for path in actual:
            if area_sizes(path, r'CSEG|CSEG_F_\S+', required=True) > code_limit or area_sizes(path, 'XSEG|XISEG') > xram_limit:
                group = library_group(path)
                require(group, 'oversized function-split input is outside an Arduino library: ' + path)
                groups.add(group)
        split_work = work / 'c-function-split-archives'
        split_work.mkdir(exist_ok=True)
        split_audits = split_work / 'audit-files.txt'
        audit_paths = []
        builder_base = ['--code-limit', code_limit, '--xram-limit', xram_limit,
                        '--splitter', HERE / 'split-c-function-tu.py', '--sdar', self.sdar]

        def add_roots(options, members):
            for arg in arguments:
                if arg in members:
                    continue
                if arg.endswith('.rel') and Path(arg).is_file():
                    options += ['--root-rel', arg]
                elif arg.endswith('.lib') and Path(arg).is_file():
                    options += ['--root-archive', arg]

        for group in sorted(groups):
            group_work = split_work / hashlib.sha256(group.encode()).hexdigest()[:16]
            group_work.mkdir(exist_ok=True)
            archive, audit = group_work / 'selected.lib', group_work / 'audit.json'
            members = {replacement: original + '.stcxx-c.json' for original, replacement in actual.items()
                       if library_group(original) == group}
            options = [*builder_base, '--work-dir', group_work, '--output-archive', archive, '--audit', audit]
            for path, metadata in members.items():
                options += ['--member', metadata, path]
            add_roots(options, members)
            helper('build-function-split-archive', *options)
            audit_paths.append(str(audit))
            grouped, inserted = [], False
            for arg in arguments:
                if arg in members:
                    if not inserted:
                        grouped.append(str(archive))
                        inserted = True
                else:
                    grouped.append(arg)
            require(inserted, 'function split did not replace a direct object')
            arguments = grouped
        trim = {replacement: original + '.stcxx-c.json' for original, replacement in actual.items()
                if library_group(original) and replacement in arguments}
        if trim:
            trim_work = split_work / 'direct'
            trim_work.mkdir(exist_ok=True)
            pairs_file, audit = trim_work / 'replacements.txt', trim_work / 'audit.json'
            options = [*builder_base, '--work-dir', trim_work, '--output-rel-list', pairs_file, '--audit', audit]
            for arg in arguments:
                if arg in trim:
                    options += ['--member', trim[arg], arg]
            add_roots(options, trim)
            helper('build-function-split-archive', *options)
            pairs = pairs_file.read_text(encoding='utf-8').splitlines()
            require(len(pairs) == len(trim) * 2, 'invalid direct function replacement count')
            replacements = {}
            for original, replacement in zip(pairs[::2], pairs[1::2]):
                require(original in trim and original not in replacements and Path(replacement).is_file(),
                        'invalid or duplicate direct function replacement')
                replacements[original] = replacement
            arguments = [replacements.get(arg, arg) for arg in arguments]
            audit_paths.append(str(audit))
        write(split_audits, ''.join(a + '\n' for a in audit_paths))
        return arguments, readonly_audits, split_audits


def main():
    require(len(sys.argv) == 5, 'usage: stcxx-cli.py MODE SOURCE OBJECT ARGFILE')
    driver = Driver(*sys.argv[1:])
    if driver.mode == 'link':
        driver.link()
    else:
        driver.compile()


if __name__ == '__main__':
    try:
        main()
    except subprocess.CalledProcessError as error:
        sys.exit(error.returncode if 0 < error.returncode < 256 else 1)
    except (OSError, ValueError, KeyError) as error:
        print(str(error), file=sys.stderr)
        sys.exit(2)
