#!/usr/bin/env python3
"""Exercise Windows recipe argv, streams, sidecars and failure propagation.

Builds a small native-process fixture with the .NET compiler supplied with
Windows PowerShell. No installed Arduino compiler or external shell is needed.
"""
import os
from pathlib import Path
import subprocess
import tempfile

FIXTURE = r'''
using System;
using System.IO;
using System.Text;
class Fixture {
    static int Main(string[] args) {
        File.WriteAllBytes(Environment.GetEnvironmentVariable("STC_TEST_ARGV"),
                          Encoding.UTF8.GetBytes(String.Join("\0", args) + "\0"));
        Console.WriteLine("fixture stdout");
        Console.Error.WriteLine("fixture stderr");
        if (Array.IndexOf(args, "-DFAIL=1") >= 0) return 23;
        if (Array.IndexOf(args, "--help") >= 0) {
            Console.WriteLine("--function-sections --data-sections"); return 0;
        }
        if (args.Length > 0 && args[0] == "rcs") {
            File.AppendAllText(args[1], Path.GetFileName(args[2]) + "\n"); return 0;
        }
        int output = Array.IndexOf(args, "-o");
        if (output >= 0) File.WriteAllText(args[output + 1], "fixture object");
        else if (Array.IndexOf(args, "-E") >= 0) {
            string name = Path.GetFileName(args[args.Length - 1]);
            if (name.EndsWith(".merged")) name = name.Substring(0, name.Length - 7) + ".d";
            else name = Path.ChangeExtension(name, ".d");
            File.WriteAllText(name, "fixture dependency");
        }
        return 0;
    }
}
'''


def main():
    if os.name != 'nt':
        raise SystemExit('This check requires Windows PowerShell 5.1')
    wrapper = Path(__file__).resolve().parents[1] / 'tools/wrapper/stc-windows.ps1'
    windows = Path(os.environ['SYSTEMROOT'])
    powershell = windows / 'System32/WindowsPowerShell/v1.0/powershell.exe'
    compiler = windows / 'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
    with tempfile.TemporaryDirectory(prefix='stc wrapper ') as temporary:
        work = Path(temporary)
        source = work / 'fixture.cs'
        source.write_text(FIXTURE, encoding='utf-8')
        executable = work / 'fixture.exe'
        subprocess.run([str(compiler), '/nologo', '/out:' + str(executable), str(source)], check=True)
        env = dict(os.environ, STC_TEST_ARGV=str(work / 'argv.bin'))
        count = 0

        def invoke(label, *args, status=0):
            nonlocal count
            result = subprocess.run([str(powershell), '-NoLogo', '-NoProfile', '-NonInteractive',
                                     '-ExecutionPolicy', 'Bypass', '-File', str(wrapper), *map(str, args)],
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=work, env=env, timeout=60)
            if result.returncode != status:
                raise RuntimeError(f'{label}: exit {result.returncode}, expected {status}: {result.stderr!r}')
            count += 1
            return result

        def argv():
            return (work / 'argv.bin').read_bytes().decode('utf-8').split('\0')[:-1]

        c_source = work / 'input.c'
        c_source.write_text('int main(void) { return 0; }\n')
        obj = work / 'input.c.o'
        flags = ['-c', r'-ID:\path with spaces\include', '-DNAME="quoted value"',
                 '-DURL=scheme:value', '-DLITERAL=$(text);&|%!', r'-DTRAIL=C:\folder' + chr(92)]
        result = invoke('argv and streams', 'compile', executable, c_source, obj, 're1', *flags)
        assert argv() == flags + [str(c_source), '-o', str(obj)], argv()
        assert b'fixture stdout' in result.stdout and b'fixture stderr' in result.stderr
        assert obj.read_bytes() == obj.with_suffix('.rel').read_bytes()
        obj.unlink()
        obj.with_suffix('.rel').unlink()
        invoke('compiler failure', 'compile', executable, c_source, obj, 're1', '-DFAIL=1', status=23)
        assert not obj.exists() and not obj.with_suffix('.rel').exists()
        invoke('removed target', 'compile', executable, c_source, obj, 're1', '-mmcs51', status=4)

        merged = work / 'sketch.ino.cpp.merged'
        merged.write_text('#include <Arduino.h>\n')
        dependency = work / 'dependency output.d'
        # Match Arduino's unquoted -MF behavior at the outer process boundary.
        invoke('null output discovery', 'compile', executable, merged, 'nul', 're12', '-E', '-MMD',
               '-MF', *str(dependency).split(' '))
        assert dependency.read_text() == 'fixture dependency'
        assert argv() == ['-E', '-MMD', '-x', 'c', str(merged)]
        assert not (work / 'nul.d').exists()

        rel = work / 'member.c.rel'
        rel.write_text('member')
        archive = work / 'core.a'
        invoke('archive member', 'archive', executable, archive, rel.with_suffix('.o'), 'rcs')
        assert archive.read_bytes() == archive.with_suffix('.lib').read_bytes()
        heap = work / 'stcxx_heap.c.rel'
        heap.write_text('heap')
        before = archive.read_bytes()
        invoke('heap exclusion', 'archive', executable, archive, heap.with_suffix('.o'), 'rcs')
        assert archive.read_bytes() == before
        invoke('wrong heap archive', 'archive', executable, work / 'other.a', heap, 'rcs', status=4)
        invoke('missing object', 'archive', executable, archive, work / 'missing.o', 'rcs', status=4)
        archive.with_suffix('.lib').write_text('stale cached archive')
        firmware = work / 'output.hex'
        invoke('cached archive refresh', 'link', executable, rel.with_suffix('.o'), archive, '-o', firmware)
        assert archive.with_suffix('.lib').read_bytes() == before
        assert argv() == [str(rel), str(archive.with_suffix('.lib')), '-o', str(firmware)]
        invoke('link failure', 'link', executable, '-DFAIL=1', status=23)

        memory = work / 'image.mem'
        memory.write_text('Stack starts at: 0x20\nPAGED EXT. RAM 0x0 0x5 6\nEXTERNAL RAM 0x0 0x9 10\nROM/EPROM/FLASH 0x0 0xff 256\n')
        result = invoke('memory size', 'size', memory)
        assert b'\r' not in result.stdout
        assert result.stdout.decode().splitlines() == ['STC_PROGRAM_BYTES 256', 'STC_RAM_BYTES 48']
        memory.write_text('0x00:|R|R| |\nNo clue at where the stack begins and ends!\nROM/EPROM/FLASH 0x0 0xff 256\n')
        result = invoke('dynamic stack', 'size', memory)
        assert result.stdout.decode().splitlines() == ['STC_PROGRAM_BYTES 256', 'STC_RAM_BYTES 2']
        memory.write_text('unrecognized report\n')
        invoke('bad memory report', 'size', memory, status=4)
        print(f'PASS: {count} Windows recipe checks')


if __name__ == '__main__':
    main()
