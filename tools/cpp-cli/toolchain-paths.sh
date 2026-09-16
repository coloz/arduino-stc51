#!/bin/sh
# Shared by the actual pipeline and its inventory command. Callers verify the
# locked executable hash before asking ldd to resolve its implementation.

stcxx_installed_frontend_root() {
    stcxx_installed_tool_root "$1" "$2" arduino_frontend frontend
}

stcxx_installed_tool_root() {
    # The binding is an exact Arduino toolsDependency identity, not a search
    # for the newest installed LLVM. Callers have verified this helper's hash.
    python3 - "$1" "$2" "$3" "$4" <<'PY'
import json
from pathlib import Path
import re
import sys

try:
    platform = Path(sys.argv[1]).resolve()
    binding = json.loads(Path(sys.argv[2]).read_text(encoding='utf-8')).get(sys.argv[3])
    label = sys.argv[4]
    if binding is None:
        raise SystemExit(0)
    if (not isinstance(binding, dict) or set(binding) != {'packager', 'name', 'version'} or
            any(not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._+-]*', value)
                for value in binding.values())):
        raise ValueError('invalid locked Arduino ' + label + ' dependency')
    if (len(platform.parents) < 4 or platform.parent.name != 'mcs251' or
            platform.parents[1].name != 'hardware' or platform.parents[3].name != 'packages'):
        raise ValueError(label + ' discovery requires an Arduino package installation; set STCXX_CPP_TOOLS_ROOT / STCXX_SDCC for a development checkout')
    tools = platform.parents[3] / binding['packager'] / 'tools' / binding['name']
    selected = tools / binding['version']
    if not selected.is_dir():
        raise ValueError('missing locked Arduino ' + label + ' dependency: ' + str(selected))
    print(selected.resolve())
except (ValueError, OSError) as error:
    print(str(error), file=sys.stderr)
    raise SystemExit(2)
PY
}

stcxx_resolve_tools() {
    if [ -z "${STCXX_CPP_TOOLS_ROOT:-}" ] && [ "$#" -ge 3 ]; then
        STCXX_CPP_TOOLS_ROOT=$(stcxx_installed_frontend_root "$2" "$3") || return $?
        if [ -n "$STCXX_CPP_TOOLS_ROOT" ]; then export STCXX_CPP_TOOLS_ROOT; fi
    fi
    if [ -n "${STCXX_CPP_TOOLS_ROOT:-}" ]; then
        clang=${STCXX_CLANG:-$STCXX_CPP_TOOLS_ROOT/bin/clang}
        llvm_link=${STCXX_LLVM_LINK:-$STCXX_CPP_TOOLS_ROOT/bin/llvm-link}
        opt=${STCXX_OPT:-$STCXX_CPP_TOOLS_ROOT/bin/opt}
        llvm_dis=${STCXX_LLVM_DIS:-$STCXX_CPP_TOOLS_ROOT/bin/llvm-dis}
        llvm_cbe=${STCXX_LLVM_CBE:-$STCXX_CPP_TOOLS_ROOT/bin/llvm-cbe}
    else
        clang=${STCXX_CLANG:-${HOME}/.cache/arduino-stc51/clang-build-20.1.8/bin/clang}
        llvm_link=${STCXX_LLVM_LINK:-/usr/bin/llvm-link-20}
        opt=${STCXX_OPT:-/usr/bin/opt-20}
        llvm_dis=${STCXX_LLVM_DIS:-/usr/bin/llvm-dis-20}
        llvm_cbe=${STCXX_LLVM_CBE:-/var/tmp/arduino-stc51-cpp-bridge/llvm-cbe-local/build/tools/llvm-cbe/llvm-cbe}
    fi
    if [ -n "${STCXX_SDCC:-}" ]; then
        sdcc=$STCXX_SDCC
    elif [ -n "${STCXX_TOOLCHAIN_ROOT:-}" ]; then
        sdcc=$STCXX_TOOLCHAIN_ROOT/out/bin/sdcc
    else
        sdcc=${STCXX_ARDUINO_SDCC:-$1/out/bin/sdcc}
    fi
    case "$sdcc" in
        */*) ;;
        *) sdcc=$(command -v "$sdcc") || return 2 ;;
    esac
    sdcc=$(realpath -e -- "$sdcc") || return 2
    sdcc_build_root=$(dirname "$(dirname "$sdcc")")
    if [ -x "$sdcc_build_root/libexec/sdcc" ] && [ -d "$sdcc_build_root/share/sdcc" ]; then
        sdcc_elf=$sdcc_build_root/libexec/sdcc
        sdcc_include_root=$sdcc_build_root/share/sdcc/include
        sdcc_runtime_root=$sdcc_build_root/share/sdcc/lib
    elif [ -d "$sdcc_build_root/include" ] && [ -d "$sdcc_build_root/lib" ]; then
        sdcc_elf=$sdcc_build_root/bin/sdcc
        sdcc_include_root=$sdcc_build_root/include
        sdcc_runtime_root=$sdcc_build_root/lib
    elif [ -x "$sdcc_build_root/src/sdcc" ] && [ -d "$sdcc_build_root/device/lib/build" ]; then
        sdcc_elf=$sdcc_build_root/src/sdcc
        sdcc_include_root=$(dirname "$sdcc_build_root")/source/device/include
        sdcc_runtime_root=$sdcc_build_root/device/lib/build
    else
        printf 'unrecognized SDCC layout: %s\n' "$sdcc_build_root" >&2
        return 2
    fi
}

stcxx_resolve_library() {
    if [ "$(uname -s)" = Darwin ]; then
        # Callers first verify the complete pinned Mac package. Its load
        # commands contain only @loader_path references to these private files.
        stcxx_library_root=$(dirname "$(dirname "$(realpath -e -- "$1")")") || return 2
        case "$2" in
            libclang-cpp.so.20.1) stcxx_library_name=libclang-cpp.dylib ;;
            libLLVM.so.20.1) stcxx_library_name=libLLVM.dylib ;;
            *) return 2 ;;
        esac
        realpath -e -- "$stcxx_library_root/lib/$stcxx_library_name"
        return $?
    fi
    stcxx_library_listing=$(ldd "$1") || return 2
    stcxx_library_path=$(printf '%s\n' "$stcxx_library_listing" | awk -v soname="$2" '
        $1 == soname && $2 == "=>" {
            sub(/^[^=]*=>[[:space:]]*/, "")
            sub(/[[:space:]]+\(0x[[:xdigit:]]+\)[[:space:]]*$/, "")
            print
        }')
    case "$stcxx_library_path" in
        /*) if [ -f "$stcxx_library_path" ]; then
                printf '%s\n' "$stcxx_library_path"
                return 0
            fi ;;
    esac
    printf 'cannot resolve %s implementation for %s\n' "$2" "$1" >&2
    return 2
}
