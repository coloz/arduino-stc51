#!/bin/sh
# Emit and verify the exact executables used by tools/cpp-cli/stcxx-cli.sh.
set -eu

if [ "$#" -ne 1 ]; then
    echo "usage: $0 TOOLCHAIN_LOCK_JSON" >&2
    exit 2
fi

lock=$1
test -f "$lock"
command -v python3 >/dev/null
command -v sha256sum >/dev/null

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
repository_root=$(CDPATH= cd -- "$script_dir/.." && pwd)
toolchain_root=${STCXX_TOOLCHAIN_ROOT:-$(dirname -- "$repository_root")/stcxx}

lock_value() {
    python3 - "$lock" "$1" <<'PY'
import json
import sys
value = json.load(open(sys.argv[1], encoding="utf-8"))
for component in sys.argv[2].split("."):
    value = value[component]
print(value)
PY
}

clang=${STCXX_CLANG:-${HOME}/.cache/arduino-stc51/clang-build-20.1.8/bin/clang}
llvm_link=${STCXX_LLVM_LINK:-/usr/bin/llvm-link-20}
opt=${STCXX_OPT:-/usr/bin/opt-20}
llvm_dis=${STCXX_LLVM_DIS:-/usr/bin/llvm-dis-20}
llvm_cbe=${STCXX_LLVM_CBE:-/var/tmp/arduino-stc51-cpp-bridge/llvm-cbe-local/build/tools/llvm-cbe/llvm-cbe}
sdcc=${STCXX_SDCC:-$toolchain_root/out/bin/sdcc}
sdcc_root=$(dirname "$(dirname "$sdcc")")
if [ -x "$sdcc_root/libexec/sdcc" ]; then
    sdcc_elf=$sdcc_root/libexec/sdcc
else
    sdcc_elf=$sdcc_root/src/sdcc
fi
libclang_cpp=$(ldd "$clang" | awk '/libclang-cpp\.so\.20\.1/ {print $3; exit}')
test -n "$libclang_cpp"

emit_verified() {
    label=$1
    path=$2
    lock_key=$3
    test -f "$path" || {
        echo "missing C++ pipeline binary $label: $path" >&2
        exit 2
    }
    actual=$(sha256sum "$path" | awk '{print $1}')
    expected=$(lock_value "$lock_key")
    if [ "$actual" != "$expected" ]; then
        echo "$label hash differs: expected $expected, got $actual" >&2
        exit 2
    fi
    printf '%s\t%s\t%s\n' "$label" "$path" "$actual"
}

emit_verified clang_20 "$clang" tools.clang.sha256
emit_verified libclang_cpp "$libclang_cpp" tools.clang.shared_library_sha256
emit_verified llvm_link "$llvm_link" tools.llvm_link.sha256
emit_verified opt "$opt" tools.opt.sha256
emit_verified llvm_dis "$llvm_dis" tools.llvm_dis.sha256
emit_verified llvm_cbe "$llvm_cbe" tools.llvm_cbe.sha256
emit_verified sdcc_wrapper "$sdcc" tools.sdcc.sha256
emit_verified sdcc_elf "$sdcc_elf" tools.sdcc.elf_sha256
emit_verified sdar "$sdcc_root/bin/sdar" tools.sdar.sha256
emit_verified sdas251 "$sdcc_root/bin/sdas251" tools.sdas251.sha256
emit_verified sdas8051 "$sdcc_root/bin/sdas8051" tools.sdas8051.sha256
emit_verified sdld "$sdcc_root/bin/sdld" tools.sdld.sha256
emit_verified sdldmcs251 "$sdcc_root/bin/sdldmcs251" tools.sdldmcs251.sha256
emit_verified sdcpp "$sdcc_root/bin/sdcpp" tools.sdcpp.sha256
