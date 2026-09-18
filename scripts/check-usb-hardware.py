#!/usr/bin/env python3
"""Exercise an already-flashed HardwareValidation sketch on Windows.

Requires pyserial; --composite also requires hidapi. Does not flash, touch
1200 baud with reboot enabled, or enter ISP. It tests USB detach/attach.
--port is mandatory so
private-test VID/PIDs never select an unrelated device automatically.
"""
import argparse
import concurrent.futures
import json
import random
import struct
import time
from pathlib import Path
import serial
from serial.tools import list_ports

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--port', required=True)
parser.add_argument('--composite', action='store_true')
parser.add_argument('--output', type=Path, required=True)
args = parser.parse_args()
results = {'port': args.port, 'composite': args.composite, 'tests': []}

def check(name, fn):
    start = time.monotonic()
    detail = fn()
    results['tests'].append({'name': name, 'pass': True, 'seconds': round(time.monotonic()-start, 3), 'detail': detail})
    print(name + ': PASS', flush=True)

def exact(port, size):
    result = port.read(size)
    assert len(result) == size, ('short read', size, len(result), result[:64].hex())
    return result

def status(port):
    port.write(b'S')
    data = exact(port, 24)
    assert data[:4] == b'STC\x01', data.hex()
    values = struct.unpack('<IIBBBBBBBBI', data[4:])
    return dict(zip(('millis','baud','dtr','rts','stop','parity','bits','connected','write_error','reboot','toggles'), values))

def echo(port, data, pause=False):
    port.write((b'P' if pause else b'') + b'E' + struct.pack('<H', len(data)))
    # Read concurrently so a large host write cannot deadlock the echo ring.
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        received = pool.submit(exact, port, len(data))
        port.write(data)
        reply = received.result(timeout=20)
    if reply != data:
        offset = next(i for i, (a, b) in enumerate(zip(reply, data)) if a != b)
        raise AssertionError(('echo mismatch', len(data), offset,
                              reply[offset:offset+16].hex(), data[offset:offset+16].hex()))

port = None
try:
    info = next(p for p in list_ports.comports() if p.device.lower() == args.port.lower())
    assert (info.vid, info.pid) == (0x1209, 3 if args.composite else 2), str(info)
    results['device'] = {'vid': info.vid, 'pid': info.pid, 'description': info.description, 'hwid': info.hwid}
    port = serial.Serial(args.port, 115200, timeout=15, write_timeout=15)
    time.sleep(0.2)
    check('status', lambda: status(port))
    def utf8():
        port.write(b'U')
        data = port.readline()
        assert data == '你好啊 / STC USB CDC\r\n'.encode(), data.hex()
        return data.decode().strip()
    check('utf8', utf8)
    def packets():
        rng = random.Random(314159)
        sizes = [1, 7, 63, 64, 65, 127, 128, 129, 255, 256, 512, 1024, 4096, 8192]
        for size in sizes: echo(port, rng.randbytes(size))
        echo(port, b'@STCISP#\x00\xff')
        return {'sizes': sizes, 'bytes': sum(sizes) + 10}
    check('packet_boundaries_and_binary_transparency', packets)
    check('rx_backpressure_250ms', lambda: echo(port, bytes(range(256))*16, True))
    def sustained():
        rng = random.Random(271828)
        start = time.monotonic()
        for _ in range(64): echo(port, rng.randbytes(4096))
        return {'bytes': 262144, 'bytes_per_second': round(262144/(time.monotonic()-start))}
    check('sustained_256KiB', sustained)
    def coding():
        found = []
        for baud, bits, parity, stop, want_parity, want_stop in [
            (9600, 8, serial.PARITY_NONE, serial.STOPBITS_ONE, 0, 0),
            (230400, 7, serial.PARITY_EVEN, serial.STOPBITS_TWO, 2, 2),
            (115200, 8, serial.PARITY_NONE, serial.STOPBITS_ONE, 0, 0)]:
            port.apply_settings({'baudrate':baud, 'bytesize':bits, 'parity':parity, 'stopbits':stop})
            time.sleep(0.05)
            s = status(port)
            assert (s['baud'], s['bits'], s['parity'], s['stop']) == (baud,bits,want_parity,want_stop), s
            found.append(s)
        rts_results = []
        for requested in (False, True):
            port.rts = requested
            time.sleep(0.05)
            observed = status(port)['rts']
            entry = {'requested': int(requested), 'immediate': observed}
            if observed != int(requested):
                # On the tested Windows usbser stack, an RTS-only change is
                # delivered with the next DTR transition. Record this limitation
                # rather than claiming independent RTS updates passed.
                port.dtr = False; time.sleep(.05)
                port.dtr = True; time.sleep(.05)
                observed = status(port)['rts']
                entry['after_dtr_cycle'] = observed
            assert observed == int(requested), entry
            rts_results.append(entry)
        return {'line_coding': found, 'rts': rts_results}
    check('line_coding_and_rts', coding)
    def dtr():
        port.dtr = False
        time.sleep(0.2)
        port.dtr = True
        time.sleep(0.1)
        s = status(port)
        assert s['dtr'] and s['connected'], s
        echo(port, b'dtr-reopened')
    check('dtr_reopen', dtr)
    def break_signal():
        port.break_condition = True
        time.sleep(0.05)
        port.write(b'B')
        assert struct.unpack('<I', exact(port,4))[0] == 65535
        port.break_condition = False
        time.sleep(0.05)
        port.write(b'B')
        assert struct.unpack('<I', exact(port,4))[0] == 0
    check('send_break', break_signal)
    def clock_test():
        a = status(port); start = time.monotonic(); time.sleep(3); b = status(port)
        elapsed = time.monotonic() - start
        target_ms = (b['millis'] - a['millis']) & 0xffffffff
        toggles = (b['toggles'] - a['toggles']) & 0xffffffff
        assert abs(target_ms / 1000 / elapsed - 1) < .1, (target_ms,elapsed)
        assert 25 <= toggles <= 35, toggles
        return {'host_seconds':elapsed, 'device_ms':target_ms, 'led_toggles':toggles}
    check('millis_and_gpio_schedule', clock_test)
    def reopen():
        for _ in range(5):
            port.close(); time.sleep(.1); port.open(); time.sleep(.1)
            echo(port, b'reopened\x00\xff')
    check('port_close_open_5x', reopen)
    def reboot_disabled():
        port.write(b'R\x00'); port.flush(); time.sleep(.05)
        assert not status(port)['reboot']
        port.baudrate = 1200; port.dtr = False; time.sleep(.3); port.dtr = True; time.sleep(.1)
        s = status(port); assert s['baud'] == 1200, s
        port.baudrate = 115200; time.sleep(.1)
        port.write(b'R\x01'); port.flush(); time.sleep(.05)
        assert status(port)['reboot']
    check('disable_1200_reboot', reboot_disabled)
    def end_begin():
        port.write(b'N'); port.flush(); time.sleep(.2)
        echo(port,b'end-begin')
    check('serial_end_begin', end_begin)
    def detach_attach():
        port.write(b'D'); port.flush(); port.close()
        time.sleep(.7)
        deadline = time.monotonic() + 15
        while True:
            try:
                port.open()
                break
            except serial.SerialException:
                if time.monotonic() >= deadline: raise
                time.sleep(.2)
        time.sleep(.2)
        echo(port, b'usb-reattached')
    check('device_detach_attach', detach_attach)
    if args.composite:
        import hid
        interfaces = hid.enumerate(0x1209, 3)
        results['hid_interfaces'] = [{k:v for k,v in item.items() if k != 'path'} for item in interfaces]
        raw = [item for item in interfaces if item['usage_page'] == 0xff00 and item['usage'] == 1]
        assert len(raw) == 1, interfaces
        device = hid.device(); device.open_path(raw[0]['path'])
        def raw_echo():
            rng = random.Random(42)
            for _ in range(64):
                packet = b'\x03' + rng.randbytes(8)
                assert device.write(packet) == 9
                assert bytes(device.read(9, 2000)) == packet
                echo(port, rng.randbytes(129))
            port.write(b'H'); assert exact(port, 1) == b'H'
            return {'raw_reports':64, 'cdc_bytes':64*129, 'neutral_mouse_keyboard':True}
        try: check('raw_hid_with_cdc_and_neutral_reports', raw_echo)
        finally: device.close()
    results['final_status'] = status(port)
    assert not results['final_status']['write_error'], results['final_status']
    results['pass'] = True
except Exception as error:
    results['pass'] = False
    results['error'] = repr(error)
    raise
finally:
    if port: port.close()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf8')
