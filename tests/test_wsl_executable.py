"""WSL lookup must handle Windows' 32-bit filesystem redirection explicitly."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

HELPER = Path(__file__).resolve().parents[1] / 'tools/wrapper/stc-wsl-env.sh'


@unittest.skipIf(os.name == 'nt', 'POSIX fixtures; actual BusyBox/WSL execution is an integration gate')
class WslExecutableLookup(unittest.TestCase):
    def test_native_alias_precedence_and_system32_fallback(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / 'Windows root'
            native = root / 'Sysnative/wsl.exe'
            system = root / 'System32/wsl.exe'
            for path in (native, system):
                path.parent.mkdir(parents=True)
                path.write_text('fixture')
            env = {**os.environ, 'SYSTEMROOT': str(root)}
            command = ['sh', '-eu', '-c', '. "$1"; printf "%s" "$STCXX_WSL_EXECUTABLE"', 'lookup', str(HELPER)]
            first = subprocess.run(command, env=env, capture_output=True, text=True, timeout=10)
            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertEqual(first.stdout, str(native))
            native.unlink()
            second = subprocess.run(command, env=env, capture_output=True, text=True, timeout=10)
            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertEqual(second.stdout, str(system))


if __name__ == '__main__':
    unittest.main()
