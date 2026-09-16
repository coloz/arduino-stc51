"""Read exact SDAR member bytes on both native hosts."""
from pathlib import Path
import subprocess
import sys
import tempfile


def read_member(sdar: Path, archive: Path, member: str) -> bytes:
    if sys.platform != 'win32':
        return subprocess.check_output([str(sdar), '-p', str(archive), member])
    # Native Windows sdar -p uses text-mode stdout and inserts CR bytes.
    # Extraction preserves the archive payload, including existing CRLF.
    if Path(member).name != member or member in ('.', '..'):
        raise ValueError('invalid archive member name: ' + member)
    with tempfile.TemporaryDirectory(prefix='stcxx-ar-') as directory:
        subprocess.run([str(sdar), '-x', str(archive.resolve()), member],
                       cwd=directory, check=True, stdout=subprocess.PIPE)
        return (Path(directory) / member).read_bytes()
