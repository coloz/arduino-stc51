#!/usr/bin/env python3
"""Run actual SD C/C++ code against a FAT image with injected block-I/O faults.

Requires a POSIX host with GCC/G++, ASan and UBSan. This models block storage,
not physical SPI timing or SD power-loss behavior.
"""
import argparse
from pathlib import Path
import subprocess
import tempfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cc', default='gcc')
    parser.add_argument('--cxx', default='g++')
    parser.add_argument('--case', choices=('roundtrip', 'fat32', 'handles', 'failure'))
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    cpp = root / 'cores/STC/cpp'
    common = ['-O1', '-g', '-fsanitize=address,undefined',
              '-fno-sanitize-recover=all', '-fno-omit-frame-pointer',
              '-DSTCXX_CPP_CORE=1', '-DSTCXX_HOST_TEST=1', '-DSTC_SD_HOST_TEST=1',
              '-I', str(root / 'tests/host'), '-I', str(root / 'libraries/SD/src'),
              '-I', str(root / 'libraries/SPI/src'), '-I', str(root / 'cores/STC'),
              '-iquote', str(cpp)]
    with tempfile.TemporaryDirectory(prefix='stc-library-') as temporary:
        work = Path(temporary)
        obj, binary = work / 'sd.o', work / 'sd'
        subprocess.run([args.cc, '-std=c99', *common, '-c',
                        str(root / 'libraries/SD/src/SD.c'), '-o', str(obj)], check=True)
        subprocess.run([args.cxx, '-std=c++11', '-fno-exceptions', '-fno-rtti', *common,
                        str(root / 'tests/host/sd.cpp'), str(root / 'libraries/SD/src/SDClass.cpp'),
                        *(str(cpp / f) for f in ('Print.cpp', 'Stream.cpp', 'WString.cpp')),
                        str(obj), '-o', str(binary)], check=True)
        for case in ([args.case] if args.case else ['roundtrip', 'fat32', 'handles', 'failure']):
            subprocess.run([str(binary), case], check=True, timeout=60)


if __name__ == '__main__':
    main()
