#!/bin/sh
# Emit and verify the exact executables used by tools/cpp-cli/stcxx-cli.sh.
set -eu

if [ "$#" -ne 1 ]; then
    echo "usage: $0 TOOLCHAIN_LOCK_JSON" >&2
    exit 2
fi

lock=$1
test -f "$lock"
script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
repository_root=$(CDPATH= cd -- "$script_dir/.." && pwd)
if [ "$(uname -s)" = Darwin ]; then
    . "$repository_root/tools/wrapper/stc-macos-env.sh"
fi
command -v python3 >/dev/null
command -v sha256sum >/dev/null
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

paths_helper=$repository_root/tools/cpp-cli/toolchain-paths.sh
emit_verified toolchain_paths "$paths_helper" pipeline_helpers.toolchain_paths.sha256
. "$paths_helper"
stcxx_resolve_tools "$(lock_value tools.sdcc.source_project_wsl)" "$repository_root" "$lock"
sdcc_root=$sdcc_build_root
if [ "$(uname -s)" = Darwin ] || [ "$(lock_value host)" = linux-x86_64 ]; then
    macos_verifier=$repository_root/tools/cpp-cli/verify-macos-frontend.py
    emit_verified macos_frontend_verifier "$macos_verifier" pipeline_helpers.macos_frontend_verifier.sha256
    python3 "$macos_verifier" --lock "$lock" \
        --root "${STCXX_CPP_TOOLS_ROOT:?missing pinned frontend package}" \
        --tool clang "$clang" --tool llvm-link "$llvm_link" --tool opt "$opt" \
        --tool llvm-dis "$llvm_dis" --tool llvm-cbe "$llvm_cbe"
fi
emit_verified clang_20 "$clang" tools.clang.sha256
libclang_cpp=$(stcxx_resolve_library "$clang" libclang-cpp.so.20.1)
emit_verified libclang_cpp "$libclang_cpp" tools.clang.shared_library_sha256
emit_verified llvm_link "$llvm_link" tools.llvm_link.sha256
emit_verified opt "$opt" tools.opt.sha256
emit_verified llvm_dis "$llvm_dis" tools.llvm_dis.sha256
emit_verified llvm_cbe "$llvm_cbe" tools.llvm_cbe.sha256
for frontend_name in clang llvm_link opt llvm_dis llvm_cbe; do
    case "$frontend_name" in
        clang) frontend=$clang ;;
        llvm_link) frontend=$llvm_link ;;
        opt) frontend=$opt ;;
        llvm_dis) frontend=$llvm_dis ;;
        llvm_cbe) frontend=$llvm_cbe ;;
    esac
    libllvm=$(stcxx_resolve_library "$frontend" libLLVM.so.20.1)
    emit_verified "${frontend_name}_libllvm" "$libllvm" tools.llvm_shared_library.sha256
done
emit_verified sdcc_wrapper "$sdcc" tools.sdcc.sha256
emit_verified sdcc_elf "$sdcc_elf" tools.sdcc.elf_sha256
emit_verified sdar "$sdcc_root/bin/sdar" tools.sdar.sha256
emit_verified sdas251 "$sdcc_root/bin/sdas251" tools.sdas251.sha256
emit_verified sdld "$sdcc_root/bin/sdld" tools.sdld.sha256
emit_verified sdldmcs251 "$sdcc_root/bin/sdldmcs251" tools.sdldmcs251.sha256
emit_verified sdcpp "$sdcc_root/bin/sdcpp" tools.sdcpp.sha256
