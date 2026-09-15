"""Guard direct-link retention and final-map identity during native C trimming."""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module

BUILD = load('direct_function_builder', ROOT / 'tools/cpp-cli/build-function-split-archive.py')
AUDIT = load('direct_function_map_auditor', ROOT / 'tools/cpp-cli/audit-function-split-link-map.py')


class DirectFunctionsTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.splitter = ROOT / 'tools/cpp-cli/split-c-function-tu.py'
        self.args = SimpleNamespace(root_rel=[], root_archive=[], output_rel_list=self.root / 'pairs.txt',
                                    audit=self.root / 'audit.json')

    def rel(self, name, definitions, references=(), code=100, startup=0):
        path = self.root / name
        path.write_text('XH3\nH 2 areas 4 global symbols\n' +
            f'A CSEG size {code:X} flags 0 addr 0\nA GSINIT size {startup:X} flags 0 addr 0\n' +
            ''.join('S ' + s + ' Def000000\n' for s in definitions) +
            ''.join('S ' + s + ' Ref000000\n' for s in references))
        return path

    def member(self, name, definitions, references=(), startup=0):
        rel = self.rel(name + '.rel', definitions, references, startup=startup)
        source = self.root / (name + '.c')
        source.write_text('/* retained source */\n')
        metadata = {'source': str(source), 'original_rel': str(rel), 'original_rel_sha256': BUILD.digest_path(rel)}
        meta = self.root / (name + '.json')
        meta.write_text(json.dumps(metadata))
        parsed = BUILD.parse_rel(rel)
        member = BUILD.Member(meta, rel, metadata, parsed, parsed, False)
        member.external_functions = {'_used', '_unused'} & set(definitions)
        return member

    def run_trim(self, members, generated_defs=None, generated_refs=()):
        def compile_member(member, roots, work, splitter):
            self.assertIn('_used', roots)
            result = self.rel('generated.rel', generated_defs or ['_used', '_state'], generated_refs, code=40)
            member.compiled = [result]
            member.split_audit = self.root / 'split.json'
            member.split_audit.write_text('{}')
        with patch.object(BUILD, 'compile_candidate', side_effect=compile_member):
            BUILD.trim_direct_members(members, self.args, self.root, self.splitter, Path(sys.executable))
        return json.loads(self.args.audit.read_text())

    def test_unreferenced_startup_and_data_objects_stay_direct(self):
        members = [self.member('startup', ['_boot'], startup=3), self.member('data', ['_state'])]
        with patch.object(BUILD, 'can_trim_member', return_value=False):
            result = self.run_trim(members)
        self.assertEqual(result['discarded_input_member_count'], 0)
        self.assertEqual(result['selected_direct_object_count'], 2)
        self.assertTrue(all(b['input_rel'] == b['output_rel'] for b in result['bindings']))

    def test_cross_object_root_is_retained_and_unused_function_removed(self):
        callee = self.member('callee', ['_used', '_unused', '_state'])
        caller = self.member('caller', ['_entry'], ['_used', '_state'])
        with patch.object(BUILD, 'can_trim_member', side_effect=lambda m, s: m is callee):
            result = self.run_trim([callee, caller])
        self.assertTrue(result['bindings'][0]['transformed'])
        self.assertEqual(result['bindings'][0]['removed_definitions'], ['_unused'])
        self.assertFalse(result['bindings'][1]['transformed'])

    def test_no_function_root_keeps_whole_object_even_with_data_root(self):
        member = self.member('callee', ['_used', '_unused', '_state'])
        self.args.root_rel = [str(self.rel('root.rel', ['_main'], ['_state']))]
        with patch.object(BUILD, 'can_trim_member', return_value=True):
            result = self.run_trim([member])
        self.assertFalse(result['bindings'][0]['transformed'])

    def test_native_only_header_reference_keeps_original_object(self):
        member = self.member('callee', ['_used', '_unused', '_state'])
        self.args.root_rel = [str(self.rel('root.rel', ['_main'], ['_used']))]
        with patch.object(BUILD, 'can_trim_member', return_value=True):
            result = self.run_trim([member], generated_refs=['_private_helper'])
        self.assertFalse(result['bindings'][0]['transformed'])
        self.assertEqual(result['bindings'][0]['classification'], 'new-native-references-original-kept')

    def test_missing_global_definition_rejected(self):
        member = self.member('callee', ['_used', '_unused', '_state'])
        self.args.root_rel = [str(self.rel('root.rel', ['_main'], ['_used']))]
        with patch.object(BUILD, 'can_trim_member', return_value=True):
            with self.assertRaisesRegex(SystemExit, 'non-function definitions'):
                self.run_trim([member], ['_used'])

    def test_new_public_definition_rejected(self):
        member = self.member('callee', ['_used', '_unused', '_state'])
        self.args.root_rel = [str(self.rel('root.rel', ['_main'], ['_used']))]
        with patch.object(BUILD, 'can_trim_member', return_value=True):
            with self.assertRaisesRegex(SystemExit, 'unexpected public definitions'):
                self.run_trim([member], ['_used', '_state', '_extra'])

    def test_startup_code_rejected_before_ast_execution(self):
        member = self.member('startup', ['_used', '_unused'], startup=3)
        with patch.object(BUILD.subprocess, 'run', side_effect=AssertionError('must keep startup')):
            self.assertFalse(BUILD.can_trim_member(member, self.splitter))
        self.assertEqual(member.trim_classification, 'startup-code-kept')

    def test_final_map_requires_exactly_one_generated_rel_and_no_original(self):
        original = self.rel('original.rel', ['_used', '_unused'])
        output = self.rel('output.rel', ['_used'])
        audit = {'bindings': [{'input_rel': str(original), 'input_rel_sha256': BUILD.digest_path(original),
                              'output_rel': str(output), 'output_rel_sha256': BUILD.digest_path(output),
                              'transformed': True}]}
        lines = [str(output), '    [  ]']
        self.assertEqual(AUDIT.verify_direct_objects(audit, lines, [str(output)])['outcome'], 'PASS')
        for bad_lines, args in [(lines * 2, [str(output)]), ([], [str(output)]),
                                (lines, [str(output)] * 2), (lines, [str(output), str(original)])]:
            with self.subTest(lines=bad_lines, args=args), self.assertRaises(SystemExit):
                AUDIT.verify_direct_objects(audit, bad_lines, args)
        output.write_text('tampered')
        with self.assertRaisesRegex(SystemExit, 'hash mismatch'):
            AUDIT.verify_direct_objects(audit, lines, [str(output)])


if __name__ == '__main__':
    unittest.main()
