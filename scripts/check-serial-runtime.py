#!/usr/bin/env python3
"""Run the actual serial C APIs/ISR with host register and queue models.

Requires POSIX GCC with ASan/UBSan. Byte-sized tentative SFR definitions use
-fcommon to represent one shared register bank across translation units.
The model checks receive behavior, not target ABI, timing or physical hardware.
"""
import argparse
from pathlib import Path
import subprocess
import tempfile


def main():
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cc', default='gcc')
    parser.add_argument('--source-core', type=Path, default=root / 'cores/STC',
                        help='directory holding serial sources/private header; permits preserved unsplit baseline')
    args = parser.parse_args()
    core = root / 'cores/STC'
    source_core = args.source_core.resolve()
    sources = [source_core / name for name in ('HardwareSerial.c', 'HardwareSerial_isr.c')]
    receive = source_core / 'HardwareSerial_receive.c'
    if receive.is_file():
        sources.append(receive)
    common = ['-std=c99', '-O1', '-g', '-Wall', '-Wextra', '-Werror', '-fcommon',
              '-fsanitize=address,undefined', '-fno-sanitize-recover=all', '-fno-omit-frame-pointer',
              '-D__SDCC=1', '-D__STC_MCS251__=1', '-D__sfr=volatile unsigned char',
              '-D__at(x)=', '-D__interrupt(x)=', '-D__reentrant=', '-D__code=', '-D__xdata=',
              '-DF_CPU=12000000UL', '-DSTC_CORE_FAMILY_AI8051U=1',
              '-DSTC_CORE_HAS_PORT_MODE=1', '-DSTC_CORE_HAS_SEPARATE_PULLUP=0',
              '-DSTC_CORE_TIMER1_IS_1T=1', '-DSTC_CORE_HAS_ADC=0',
              '-DSTC_CORE_ADC_LAYOUT=0', '-DSTC_CORE_ADC_NATIVE_BITS=0',
              '-I', str(source_core), '-I', str(core), '-I', str(root / 'variants/AI8051U_34K16')]
    for port in '0123456789AB':
        common.append('-DSTC_CORE_HAS_PORT' + port + '=' + ('1' if port in '01234567' else '0'))
    with tempfile.TemporaryDirectory(prefix='stc-serial-') as temporary:
        work = Path(temporary)
        for uart, buffered, size in ((1, 1, 2), (1, 1, 16), (1, 1, 255), (1, 0, 16), (0, 0, 16)):
            binary = work / f'serial-{uart}-{buffered}-{size}'
            flags = [f'-DSTC_CORE_HAS_UART1={uart}', f'-DSTC_CORE_SERIAL_BUFFERED_RX={buffered}',
                     f'-DSERIAL_RX_BUFFER_SIZE={size}']
            subprocess.run([args.cc, *common, *flags, str(root / 'tests/host/serial/receive.c'),
                            *map(str, sources), '-o', str(binary)], check=True, timeout=90)
            subprocess.run([str(binary)], check=True, timeout=30)


if __name__ == '__main__':
    main()
