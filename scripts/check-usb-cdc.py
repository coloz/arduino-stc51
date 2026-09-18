#!/usr/bin/env python3
"""Exercise the real C USB class drivers through a host-side SIE model.

Run with Python + GCC (Windows: wsl -e python3 scripts/check-usb-cdc.py).
No USB hardware is accessed. Arduino/SDCC builds are a separate check.
"""
import os
import pathlib
import shlex
import subprocess

root = pathlib.Path(__file__).resolve().parents[1]
boards = dict(line.split('=', 1) for line in (root / 'boards.txt').read_text().splitlines()
              if '=' in line and not line.startswith('#'))
work = root / '.tmp/usb-cdc/host'
work.mkdir(parents=True, exist_ok=True)
for board in ('stc32g12k128', 'stc32g144k246', 'ai8051u_34k64'):
    flags = shlex.split(boards[f'{board}.build.core_flags'])
    flags += ['-D__STC_MCS251__=1', '-DF_CPU=12000000UL', '-DSTC_USB_TEST=1']
    flags += ['-I' + str(root / p) for p in ('cores/STC',
        'variants/' + boards[f'{board}.build.variant'], 'libraries/HID/src', 'scripts/tests/usb')]
    output = work / board
    sources = ['cores/STC/stc_usb.c', 'cores/STC/stc_usb_cdc.c',
               'libraries/HID/src/USB.c', 'scripts/tests/usb/device_test.c']
    subprocess.run([os.environ.get('CC', 'gcc'), '-std=c11', '-Wall', '-Wextra', '-Werror',
        '-g', '-fsanitize=address,undefined', '-fno-pie', '-no-pie', *flags,
        *(str(root / p) for p in sources), '-o', str(output)], check=True)
    for mode in ([], ['hid'], ['composite']):
        subprocess.run([str(output), *mode], check=True)
    for enabled in (0, 1):
        subprocess.run([os.environ.get('CXX', 'g++'), '-std=c++11', '-Wall', '-Wextra', '-Werror',
            *flags, f'-DARDUINO_USB_CDC_ON_BOOT={enabled}', '-fsyntax-only',
            str(root / 'scripts/tests/usb/api_test.cpp')], check=True)
    print(board + ': PASS', flush=True)

# The 16 KB profile keeps only one USB function to fit in Flash.
for macro, mode in [('STC_USB_CDC_ONLY', []), ('STC_USB_HID_ONLY', ['hid'])]:
    subprocess.run([os.environ.get('CC', 'gcc'), '-std=c11', '-Wall', '-Wextra', '-Werror',
        '-g', '-fsanitize=address,undefined', '-fno-pie', '-no-pie', *flags, f'-D{macro}=1',
        *(str(root / p) for p in sources), '-o', str(output)], check=True)
    subprocess.run([str(output), *mode], check=True)

# The board generator must expose the menu only for native application USB.
import json
devices = json.loads((root / 'tools/variants/devices.json').read_text())['devices']
for device in devices:
    assert (f"{device['id']}.menu.cdc.enabled" in boards) == bool(device['capabilities'].get('usb_layout'))
flags = shlex.split(boards['stc32g8k64.build.core_flags'])
flags += ['-D__STC_MCS251__=1', '-DF_CPU=12000000UL', '-DARDUINO_USB_CDC_ON_BOOT=1',
          '-I' + str(root / 'cores/STC'), '-I' + str(root / 'variants/STC32G8K64')]
result = subprocess.run([os.environ.get('CC', 'gcc'), '-x', 'c', '-fsyntax-only', *flags, '-'],
                        input='#include <Arduino.h>\n', text=True, capture_output=True)
assert result.returncode != 0 and 'USB CDC requires a variant' in result.stderr
print('CDC/HID-only profiles and unsupported-variant rejection: PASS')
