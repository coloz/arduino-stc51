"""Execute merged C closures to verify shared state and callback identity."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'tools/cpp-cli/split-c-function-tu.py'
SPEC = importlib.util.spec_from_file_location('function_splitter', SCRIPT)
SPLIT = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = SPLIT
SPEC.loader.exec_module(SPLIT)
CLANG = os.environ.get('STCXX_TEST_CLANG') or shutil.which('clang')
CC = shutil.which('cc')


@unittest.skipIf(sys.platform == 'win32', 'native execution uses the Linux/WSL host toolchain')
class FunctionSplitterTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not CLANG or not CC:
            raise RuntimeError('C closure regression needs Clang (or STCXX_TEST_CLANG) and cc')

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def check_closure(self, source_text, harness):
        source = self.root / 'state.c'
        source.write_text(source_text)
        main = self.root / 'main.c'
        main.write_text(harness)
        plan = self.root / 'plan.json'
        result = subprocess.run([sys.executable, str(SCRIPT), '--clang', CLANG,
            '--source', str(source), '--output-dir', str(self.root / 'merged'),
            '--audit', str(plan), '--root', 'first', '--root', 'second', '--merge-roots'],
            capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr.decode())
        audit = json.loads(plan.read_text())
        self.assertEqual(audit['emitted_member_count'], 1)
        member = Path(audit['members'][0]['source'])
        self.assertNotIn('unused_entry', audit['members'][0]['external_definitions'])
        for label, implementation in [('original', source), ('merged', member)]:
            executable = self.root / (label + '.bin')
            compiled = subprocess.run([CC, '-std=c11', str(implementation), str(main),
                '-o', str(executable)], capture_output=True, timeout=30)
            self.assertEqual(compiled.returncode, 0, compiled.stderr.decode())
            self.assertEqual(subprocess.run([str(executable)], timeout=10).returncode, 0, label)
        return source

    def test_shared_global_static_local_and_initializer_callback(self):
        source = self.check_closure('''
#define INITIAL 7
static int counter = INITIAL;
static int step(int amount) { static int calls; counter += amount; return counter + ++calls; }
static int (*callback)(int) = step;
int first(void) { return callback(2); }
int second(void) { return callback(3); }
int unused_entry(void) { return -1; }
''', '''int first(void); int second(void);
int main(void) { if (first() != 10) return 1; return second() != 14; }
''')
        ast = json.loads(subprocess.check_output([CLANG, '-x', 'c', '-fsyntax-only',
            '-Xclang', '-ast-dump=json', str(source)], timeout=30))
        with self.assertRaisesRegex(SystemExit, 'file-scope data|macro-expanded top-level'):
            SPLIT.parse_translation_unit(ast, source, source.read_bytes())

    def test_external_callback_in_retained_initializer(self):
        self.check_closure('''
int callback(int amount);
static int (*dispatch)(int) = callback;
static int state;
int callback(int amount) { state += amount; return state; }
int first(void) { return dispatch(2); }
int second(void) { return dispatch(3); }
int unused_entry(void) { return -1; }
''', '''int first(void); int second(void);
int main(void) { if (first() != 2) return 1; return second() != 5; }
''')

    def test_optional_trimming_rejects_retained_entries_but_allows_unrelated_header_attributes(self):
        builder_spec = importlib.util.spec_from_file_location('attribute_archive_builder',
            ROOT / 'tools/cpp-cli/build-function-split-archive.py')
        builder = importlib.util.module_from_spec(builder_spec)
        sys.modules[builder_spec.name] = builder
        builder_spec.loader.exec_module(builder)
        source = self.root / 'attributes.c'
        for retained in (False, True):
            source.write_text('#include <string.h>\n' +
                ('__attribute__((used)) ' if retained else '') +
                'int first(void) { return 1; }\nint second(void) { return 2; }\n')
            metadata = {'source': str(source), 'clang': CLANG, 'clang_arguments': []}
            parsed = {'areas': {'CSEG': 100}, 'definitions': {'_first', '_second'}, 'references': set()}
            member = builder.Member(source, source, metadata, parsed, parsed, False)
            with self.subTest(retained=retained):
                self.assertEqual(builder.can_trim_member(member, SCRIPT), not retained)

    def test_external_entry_reached_through_static_helper(self):
        self.check_closure('''
int leaf(int amount) { static int value; value += amount; return value; }
static int helper(int amount) { return leaf(amount); }
int first(void) { return helper(2); }
int second(void) { return helper(3); }
int unused_entry(void) { return -1; }
''', '''int first(void); int second(void);
int main(void) { if (first() != 2) return 1; return second() != 5; }
''')


if __name__ == '__main__':
    unittest.main()
