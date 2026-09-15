#!/bin/sh
# A 32-bit Windows shell sees System32 redirected to SysWOW64, which has no
# wsl.exe. Sysnative explicitly accesses the native system directory there.
stcxx_find_wsl_executable() {
    stcxx_windows_root=$(printf '%s' "${SYSTEMROOT:-${SystemRoot:-C:/Windows}}" | tr '\\' '/')
    for stcxx_wsl_candidate in "$stcxx_windows_root/Sysnative/wsl.exe" "$stcxx_windows_root/System32/wsl.exe"; do
        if [ -f "$stcxx_wsl_candidate" ]; then
            printf '%s\n' "$stcxx_wsl_candidate"
            return 0
        fi
    done
    command -v wsl.exe || {
        printf 'Cannot find Windows WSL. Install WSL and the configured Linux distribution before compiling C++.\n' >&2
        return 127
    }
}

STCXX_WSL_EXECUTABLE=$(stcxx_find_wsl_executable) || return $?
