#!/usr/bin/env python3
"""Run the actual Stepper C/C++ library with GPIO/time models under ASan/UBSan.

Requires POSIX GCC/G++. The model does not qualify hardware electrical timing.
--source permits explicit comparison against a preserved candidate's C source.
"""
import argparse
from pathlib import Path
import subprocess
import tempfile


def main():
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cc', default='gcc')
    parser.add_argument('--cxx', default='g++')
    parser.add_argument('--source', type=Path, default=root / 'libraries/Stepper/src/Stepper.c')
    args = parser.parse_args()
    fixture = root / 'tests/host/stepper'
    common = ['-O1', '-g', '-Wall', '-Wextra', '-Werror',
              '-fsanitize=address,undefined', '-fno-sanitize-recover=all',
              '-fno-omit-frame-pointer', '-I', str(fixture),
              '-I', str(root / 'libraries/Stepper/src')]
    with tempfile.TemporaryDirectory(prefix='stc-stepper-') as temporary:
        work = Path(temporary)
        objects = []
        for name, source in [('stepper', args.source), ('model', fixture / 'model.c')]:
            obj = work / (name + '.o')
            subprocess.run([args.cc, '-std=c99', *common, '-c', str(source), '-o', str(obj)], check=True)
            objects.append(str(obj))
        binary = work / 'stepper'
        subprocess.run([args.cxx, '-std=c++11', '-DSTCXX_CPP_CORE=1', *common,
                        str(fixture / 'contexts.cpp'), *objects, '-o', str(binary)], check=True)
        subprocess.run([str(binary)], check=True, timeout=30)


if __name__ == '__main__':
    main()
