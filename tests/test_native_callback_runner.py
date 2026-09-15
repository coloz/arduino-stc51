"""Negative callback builds must fail at the intended gate without stale outputs."""
import importlib.util
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('callback_runner',
    Path(__file__).resolve().parents[1] / 'scripts/check-native-callbacks.py')
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


class CallbackRunnerTest(unittest.TestCase):
    def test_other_errors_or_success_cannot_pass_negative_case(self):
        with tempfile.TemporaryDirectory() as temporary:
            build = Path(temporary)
            (build / 'stcxx').mkdir()
            (build / 'stcxx/raw.c').write_text('generated')
            for code, log in ((0, runner.DIAGNOSTIC), (1, 'missing compiler'), (-9, runner.DIAGNOSTIC)):
                with self.subTest(code=code, log=log), self.assertRaises(RuntimeError):
                    runner.check_rejection(code, log, build)
            runner.check_rejection(1, runner.DIAGNOSTIC, build)

    def test_rejection_must_reach_adapter(self):
        with tempfile.TemporaryDirectory() as temporary, self.assertRaises(RuntimeError):
            runner.check_rejection(1, runner.DIAGNOSTIC, Path(temporary))

    def test_rejection_cannot_leave_firmware_or_manifest(self):
        with tempfile.TemporaryDirectory() as temporary:
            build = Path(temporary)
            (build / 'stcxx').mkdir()
            (build / 'stcxx/raw.c').write_text('generated')
            for name in ('result.hex', 'stcxx/manifest.json'):
                with self.subTest(name=name):
                    artifact = build / name
                    artifact.write_text('stale')
                    with self.assertRaises(RuntimeError):
                        runner.check_rejection(1, runner.DIAGNOSTIC, build)
                    artifact.unlink()


if __name__ == '__main__':
    unittest.main()
