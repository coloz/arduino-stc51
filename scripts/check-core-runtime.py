#!/usr/bin/env python3
"""Host regressions for the C++ core and plain-C archive wrapper.

Requires a POSIX host with g++, AddressSanitizer and UBSan. All generated
sources and binaries live in a temporary directory and are removed on exit.
Target ABI and peripheral behavior still require compiler/QEMU checks.
"""
import argparse
from pathlib import Path
import subprocess
import tempfile


SOURCE = r'''
#include "Stream.h"
#include <cassert>
#include <climits>
#include <cstdio>
#include <cstdlib>
#include <cstring>

extern "C" unsigned long millis() { static unsigned long t; return t++; }
extern "C" void yield() {}
extern "C" void *stcxx_malloc(size_t n) { return malloc(n); }
extern "C" void *stcxx_realloc(void *p, size_t n) { return realloc(p, n); }
extern "C" void stcxx_free(void *p) { free(p); }

class Input : public Stream {
    const char *next;
public:
    explicit Input(const char *s) : next(s) { setTimeout(0); }
    int available() { return *next != 0; }
    int peek() { return *next ? (unsigned char)*next : -1; }
    int read() { int c = peek(); if (c >= 0) ++next; return c; }
    void flush() {}
    size_t write(uint8_t) { return 1; }
};

int main() {
    char text[80];
    const long values[] = { LONG_MIN, LONG_MIN + 1, -257, -1, 0, 1, 257, LONG_MAX };
    for (unsigned i = 0; i < sizeof(values) / sizeof(values[0]); ++i) {
        snprintf(text, sizeof text, "%ld!", values[i]);
        Input input(text);
        assert(input.parseInt() == values[i]);
        assert(input.read() == '!');
    }
    snprintf(text, sizeof text, "%lu!", ULONG_MAX);
    Input overflow(text);
    assert(overflow.parseInt() == -1L);
    snprintf(text, sizeof text, "-%lu!", ULONG_MAX);
    Input negativeOverflow(text);
    assert(negativeOverflow.parseInt() == 1L);
    Input separated("noise -1,234!");
    assert(separated.parseInt(SKIP_ALL, ',') == -1234);
    assert(separated.read() == '!');
    Input none("x12");
    assert(none.parseInt(SKIP_NONE) == 0 && none.read() == 'x');
    Input whitespace(" \t\r\n-42!");
    assert(whitespace.parseInt(SKIP_WHITESPACE) == -42);
    Input fraction("-12.50!");
    const float parsed = fraction.parseFloat();
    assert(parsed > -12.5001f && parsed < -12.4999f && fraction.read() == '!');
    Input overlap("ababababac!");
    assert(overlap.find("ababac") && overlap.read() == '!');
    Input terminated("ababENDtarget");
    assert(!terminated.findUntil("target", "END"));
    assert(terminated.read() == 't');
    Input bytes("abc\nxyz");
    char buffer[4] = {};
    assert(bytes.readBytesUntil('\n', buffer, 3) == 3);
    assert(strcmp(buffer, "abc") == 0 && bytes.read() == '\n');
    String s("abcdef");
    s = s.c_str() + 2;
    assert(s == "cdef");
    assert(s.concat(s.c_str() + 1) && s == "cdefdef");
    s.replace(String("def"), String("-"));
    assert(s == "c--");
    // Long searches and shrinking replacements near the 16-bit length limit.
    char *longText = static_cast<char *>(malloc(40001));
    char *pattern = static_cast<char *>(malloc(30001));
    assert(longText && pattern);
    memset(longText, 'a', 40000); longText[29999] = 'b'; longText[40000] = 0;
    memset(pattern, 'a', 30000); pattern[29999] = 'b'; pattern[30000] = 0;
    String big(longText), find(pattern);
    big.replace(find, String("x"));
    assert(big.length() == 10001 && big[0] == 'x');
    for (unsigned i = 1; i < big.length(); ++i) assert(big[i] == 'a');
    big.replace(find, String(""));
    assert(big.length() == 10001);
    free(pattern); free(longText);
    puts("PASS: Stream integer boundaries, lookahead, matching, reads and String aliases");
}
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cxx', default='g++')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    cpp = root / 'cores/STC/cpp'
    with tempfile.TemporaryDirectory(prefix='stc-core-') as temporary:
        work = Path(temporary)
        source = work / 'core.cpp'
        binary = work / 'core'
        source.write_text(SOURCE, encoding='utf-8')
        subprocess.run([
            args.cxx, '-std=c++11', '-O2', '-g',
            '-fsanitize=address,undefined', '-fno-sanitize-recover=all',
            '-fno-exceptions', '-fno-rtti', '-DSTCXX_CPP_CORE=1',
            '-DSTCXX_HOST_TEST=1', '-iquote', str(cpp), str(source),
            *(str(cpp / name) for name in ('Stream.cpp', 'WString.cpp', 'Print.cpp')),
            '-o', str(binary),
        ], check=True)
        subprocess.run([str(binary)], check=True)

        # Simulate Arduino replacing its cached archive while an old SDCC
        # sidecar remains. A matching glob decoy also catches argv expansion.
        archive = work / 'core[1].a'
        sidecar = archive.with_suffix('.lib')
        archive.write_bytes(b'current core')
        sidecar.write_bytes(b'stale core')
        (work / 'core1.lib').write_bytes(b'glob decoy')
        result = subprocess.run([
            'sh', str(root / 'tools/wrapper/stc-link.sh'),
            '/usr/bin/printf', '%s\n', str(archive),
        ], check=True, capture_output=True, text=True)
        if result.stdout.splitlines() != [str(sidecar)] or sidecar.read_bytes() != archive.read_bytes():
            raise RuntimeError('link wrapper used a stale archive or expanded an argument glob')
        print('PASS: cached archive refresh and literal linker arguments')


if __name__ == '__main__':
    main()
