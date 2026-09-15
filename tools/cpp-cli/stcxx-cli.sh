#!/usr/bin/env bash
set -euo pipefail
export PYTHONDONTWRITEBYTECODE=1

if [[ $# -ne 4 ]]; then
  printf 'usage: %s MODE SOURCE_WIN OBJECT_WIN ARGFILE_WIN\n' "$0" >&2
  exit 2
fi

mode="$1"
source_win="$2"
object_win="$3"
argfile_win="$4"
script_dir="$(cd "$(dirname "$0")" && pwd)"
platform_root="$(cd "${script_dir}/../.." && pwd)"
cpp_include_root="${platform_root}/cores/STC/cpp"
lock_file="${script_dir}/toolchain-lock.json"
if [[ "$(uname -s)" == Darwin ]]; then
  lock_file="${script_dir}/toolchain-lock.macos-arm64.json"
fi
adapter="${script_dir}/adapt.py"
member_function_aligner="${script_dir}/align-member-functions.py"
root_collector="${script_dir}/collect-c-abi-roots.py"
native_storage="${script_dir}/native-storage.py"
archive_selector="${script_dir}/select-cpp-archive-sidecars.py"
readonly_const_slicer="${script_dir}/slice-readonly-const-rel.py"
function_tu_splitter="${script_dir}/split-c-function-tu.py"
function_archive_builder="${script_dir}/build-function-split-archive.py"
function_link_map_auditor="${script_dir}/audit-function-split-link-map.py"
aslink_map_symbols="${script_dir}/aslink_map_symbols.py"
shared_cbe_adapter="${script_dir}/../cpp-core-pipeline/audit_and_adapt.py"
python="${PYTHON:-python3}"

to_linux_path() {
  local value="${1//\\//}"
  # Use the same absolute conversion as the launcher for drive-letter, UNC,
  # POSIX and relative paths.  This keeps the argument-file-derived ready
  # marker identity stable even when Arduino supplies a relative TEMP path.
  case "${value}" in
    [A-Za-z]:/*|//*) wslpath -a "${value}" ;;
    *) realpath -m -- "${value}" ;;
  esac
}

source_path="$(to_linux_path "${source_win}")"
if [[ "${object_win,,}" == "nul" || "${object_win}" == "/dev/null" ]]; then
  object_path="/dev/null"
else
  object_path="$(to_linux_path "${object_win}")"
fi
argfile="$(to_linux_path "${argfile_win}")"

test -f "${lock_file}"
test -f "${adapter}"
test -f "${member_function_aligner}"
test -f "${root_collector}"
test -f "${archive_selector}"
test -f "${readonly_const_slicer}"
test -f "${function_tu_splitter}"
test -f "${function_archive_builder}"
test -f "${function_link_map_auditor}"
test -f "${aslink_map_symbols}"
test -f "${shared_cbe_adapter}"
test -f "${argfile}"
if [[ "${mode}" != "link" ]]; then
  test -f "${source_path}" || {
    printf 'missing Arduino compile input: %s\n' "${source_path}" >&2
    exit 2
  }
fi
command -v "${python}" >/dev/null
command -v sha256sum >/dev/null

pipeline_ready_marker="${STCXX_PIPELINE_READY_MARKER:-}"
[[ "${pipeline_ready_marker}" == /* ]] || {
  printf 'missing absolute STCXX pipeline-ready marker path\n' >&2
  exit 2
}
[[ "${pipeline_ready_marker}" == "${argfile}.stcxx-pipeline-ready" ]] || {
  printf 'STCXX pipeline-ready marker is not bound to the argument file\n' >&2
  exit 2
}
mark_pipeline_ready() {
  : >"${pipeline_ready_marker}" || {
    printf 'cannot create STCXX pipeline-ready marker: %s\n' \
      "${pipeline_ready_marker}" >&2
    exit 2
  }
  [[ -f "${pipeline_ready_marker}" ]] || {
    printf 'STCXX pipeline-ready marker is not a regular file: %s\n' \
      "${pipeline_ready_marker}" >&2
    exit 2
  }
}

mapfile -d '' -t original_args <"${argfile}"

json_value() {
  "${python}" - "${lock_file}" "$1" <<'PY'
import json
import sys
value = json.load(open(sys.argv[1], encoding="utf-8"))
for component in sys.argv[2].split("."):
    value = value[component]
print(value)
PY
}

verify_tool() {
  local path="$1"
  local expected="$2"
  local label="$3"
  test -x "${path}" || { printf 'missing %s: %s\n' "${label}" "${path}" >&2; exit 2; }
  local observed
  observed="$(sha256sum "${path}" | awk '{print $1}')"
  [[ "${observed}" == "${expected}" ]] || {
    printf '%s SHA-256 mismatch: expected %s, got %s\n' \
      "${label}" "${expected}" "${observed}" >&2
    exit 2
  }
}

verify_file_hash() {
  local path="$1"
  local expected="$2"
  local label="$3"
  test -f "${path}" || { printf 'missing %s: %s\n' "${label}" "${path}" >&2; exit 2; }
  local observed
  observed="$(sha256sum "${path}" | awk '{print $1}')"
  [[ "${observed}" == "${expected}" ]] || {
    printf '%s SHA-256 mismatch: expected %s, got %s\n' \
      "${label}" "${expected}" "${observed}" >&2
    exit 2
  }
}

verify_frontend_tools() {
  if [[ "$(uname -s)" == Darwin ]] || [[ "$(json_value host)" == linux-x86_64 ]]; then
    verify_file_hash "${script_dir}/verify-macos-frontend.py" \
      "$(json_value pipeline_helpers.macos_frontend_verifier.sha256)" macos-frontend-verifier
    "${python}" "${script_dir}/verify-macos-frontend.py" --lock "${lock_file}" \
      --root "${STCXX_CPP_TOOLS_ROOT:?missing pinned frontend package}" \
      --tool clang "${clang}" --tool llvm-link "${llvm_link}" --tool opt "${opt}" \
      --tool llvm-dis "${llvm_dis}" --tool llvm-cbe "${llvm_cbe}" >/dev/null
  fi
  verify_tool "${clang}" "$(json_value tools.clang.sha256)" clang
  local clang_cpp_library
  clang_cpp_library="$(stcxx_resolve_library "${clang}" libclang-cpp.so.20.1)"
  verify_file_hash "${clang_cpp_library}" \
    "$(json_value tools.clang.shared_library_sha256)" libclang-cpp
  verify_tool "${llvm_dis}" "$(json_value tools.llvm_dis.sha256)" llvm-dis
  verify_tool "${llvm_cbe}" "$(json_value tools.llvm_cbe.sha256)" llvm-cbe
  verify_tool "${llvm_link}" "$(json_value tools.llvm_link.sha256)" llvm-link
  verify_tool "${opt}" "$(json_value tools.opt.sha256)" opt
  local frontend llvm_library llvm_library_hash
  local -A verified_llvm_libraries=()
  llvm_library_hash="$(json_value tools.llvm_shared_library.sha256)"
  for frontend in "${clang}" "${llvm_link}" "${opt}" "${llvm_dis}" "${llvm_cbe}"; do
    llvm_library="$(stcxx_resolve_library "${frontend}" libLLVM.so.20.1)"
    llvm_library="$(realpath -e -- "${llvm_library}")"
    if [[ -z "${verified_llvm_libraries[${llvm_library}]:-}" ]]; then
      verify_file_hash "${llvm_library}" "${llvm_library_hash}" libLLVM
      verified_llvm_libraries["${llvm_library}"]=1
    fi
  done
  verify_file_hash "${archive_selector}" \
    "$(json_value pipeline_helpers.cpp_archive_selector.sha256)" cpp-archive-selector
  verify_file_hash "${aslink_map_symbols}" \
    "$(json_value pipeline_helpers.aslink_map_symbols.sha256)" aslink-map-symbols
  verify_file_hash "${shared_cbe_adapter}" \
    "$(json_value pipeline_helpers.cbe_audit_adapter.sha256)" cbe-audit-adapter
  verify_file_hash "${adapter}" \
    "$(json_value pipeline_helpers.arduino_cli_adapter.sha256)" arduino-cli-adapter
  verify_file_hash "${native_storage}" \
    "$(json_value pipeline_helpers.native_storage.sha256)" native-storage
  verify_file_hash "${member_function_aligner}" \
    "$(json_value pipeline_helpers.member_function_aligner.sha256)" \
    member-function-aligner
  verify_file_hash "${readonly_const_slicer}" \
    "$(json_value pipeline_helpers.readonly_const_slicer.sha256)" readonly-const-slicer
  verify_file_hash "${function_tu_splitter}" \
    "$(json_value pipeline_helpers.function_tu_splitter.sha256)" function-tu-splitter
  verify_file_hash "${function_archive_builder}" \
    "$(json_value pipeline_helpers.function_archive_builder.sha256)" function-archive-builder
  verify_file_hash "${function_link_map_auditor}" \
    "$(json_value pipeline_helpers.function_link_map_auditor.sha256)" function-link-map-auditor
  local version
  version="$("${clang}" --version | head -n 1)"
  [[ "${version}" == *"clang version $(json_value tools.clang.version)"* ]] || {
    printf 'unexpected Clang version: %s\n' "${version}" >&2
    exit 2
  }
}

toolchain_paths="${script_dir}/toolchain-paths.sh"
verify_file_hash "${toolchain_paths}" \
  "$(json_value pipeline_helpers.toolchain_paths.sha256)" toolchain-paths
source "${toolchain_paths}"
stcxx_resolve_tools "$(json_value tools.sdcc.source_project_wsl)" "${platform_root}" "${lock_file}"
sdcc_shared_include="${sdcc_include_root}/mcs51"
sdcc_canonical_include="$(to_linux_path "${sdcc_include_root}")"
sdas251="${sdcc_build_root}/bin/sdas251"
sdld="${sdcc_build_root}/bin/sdld"
sdldmcs251="${sdcc_build_root}/bin/sdldmcs251"
sdcpp="${sdcc_build_root}/bin/sdcpp"

verify_sdcc() {
  verify_tool "${sdcc}" "$(json_value tools.sdcc.sha256)" patched-sdcc-driver
  verify_tool "${sdcc_elf}" "$(json_value tools.sdcc.elf_sha256)" patched-sdcc-elf
  verify_tool "${sdas251}" "$(json_value tools.sdas251.sha256)" patched-sdas251
  verify_tool "${sdld}" "$(json_value tools.sdld.sha256)" patched-sdld
  verify_tool "${sdldmcs251}" "$(json_value tools.sdldmcs251.sha256)" patched-sdldmcs251
  verify_tool "${sdcpp}" "$(json_value tools.sdcpp.sha256)" patched-sdcpp
  if [[ ${#sdcc_section_args[@]} -ne 0 ]]; then
    local section_help
    section_help="$("${sdcc}" -mmcs251 --help)"
    [[ "${section_help}" == *--function-sections* &&
       "${section_help}" == *--data-sections* ]] || {
      printf 'full-Flash layout requires rebuilt sdcc-c251 section support\n' >&2
      exit 2
    }
  fi
  local version
  version="$("${sdcc}" --version | head -n 1)"
  [[ "${version}" == "$(json_value tools.sdcc.version_prefix)"* ]] || {
    printf 'unexpected patched SDCC version: %s\n' "${version}" >&2
    exit 2
  }
  for input in \
    "${sdcc_include_root}/stddef.h" \
    "${sdcc_include_root}/stdint.h" \
    "${sdcc_runtime_lib}/libsdcc.lib" \
    "${sdcc_runtime_lib}/${sdcc_runtime_archive}"; do
    test -f "${input}" || { printf 'missing patched SDCC input: %s\n' "${input}" >&2; exit 2; }
  done
  [[ "$(sha256sum "${sdcc_runtime_lib}/libsdcc.lib" | awk '{print $1}')" == \
      "$(json_value targets.${sdcc_target}.sdcc_inputs.libsdcc_sha256)" ]]
  [[ "$(sha256sum "${sdcc_runtime_lib}/${sdcc_runtime_archive}" | awk '{print $1}')" == \
      "$(json_value targets.${sdcc_target}.sdcc_inputs.target_runtime_sha256)" ]]
  [[ "$(sha256sum "${sdcc_include_root}/stddef.h" | awk '{print $1}')" == \
      "$(json_value tools.sdcc_inputs.stddef_sha256)" ]]
  [[ "$(sha256sum "${sdcc_include_root}/stdint.h" | awk '{print $1}')" == \
      "$(json_value tools.sdcc_inputs.stdint_sha256)" ]]
}

normalize_include_arg() {
  local value="$1"
  local prefix="$2"
  local path="${value#${prefix}}"
  printf '%s%s\n' "${prefix}" "$(to_linux_path "${path}")"
}

clang_user_args=()
sdcc_user_args=()
sdcc_section_args=()
dependency_file=""
expect_dependency_file=0
cpp_enabled=0
cpp_optimization=0
cpp_optimization_count=0
clock_hz=""
clock_definition_count=0
target_ai8051u_34k64=0
target_stc32g144k246=0
declared_target_mcs251=0
mcs251_iram_size=""
mcs251_stack_loc=""
mcs251_stack_size=""
mcs251_constrained_heap=0
sdcc_target=""
for argument in "${original_args[@]}"; do
  if [[ ${expect_dependency_file} -eq 1 ]]; then
    dependency_file="$(to_linux_path "${argument}")"
    expect_dependency_file=0
    continue
  fi
  case "${argument}" in
    -DSTCXX_CPP_OPT|-DSTCXX_CPP_OPT=*)
      cpp_optimization_count=$((cpp_optimization_count + 1))
      cpp_optimization="${argument#*=}"
      if [[ ${cpp_optimization_count} -ne 1 ]] ||
         [[ ! "${cpp_optimization}" =~ ^[012sz]$ ]]; then
        printf 'STCXX_CPP_OPT must occur once with value 0, 1, 2, s or z\n' >&2
        exit 2
      fi
      ;;
    -DSTCXX_CPP_CORE=1)
      cpp_enabled=1
      clang_user_args+=("${argument}")
      sdcc_user_args+=("${argument}")
      ;;
    -DSTCXX_TARGET_MCS251=1)
      declared_target_mcs251=1
      clang_user_args+=("${argument}")
      sdcc_user_args+=("${argument}")
      ;;
    -DSTCXX_TARGET_MCS51=1|-DSTC_EXECUTION_MODE_MCS51|-DSTC_EXECUTION_MODE_MCS51=*)
      printf 'MCS51 support has been removed; select an MCS251 board\n' >&2
      exit 2
      ;;
    -DSTCXX_MCS251_IRAM_SIZE=*)
      mcs251_iram_size="${argument#*=}"
      ;;
    -DSTCXX_MCS251_STACK_LOC=*)
      mcs251_stack_loc="${argument#*=}"
      ;;
    -DSTCXX_MCS251_STACK_SIZE=*)
      mcs251_stack_size="${argument#*=}"
      ;;
    -DSTCXX_MCS251_CONSTRAINED_HEAP=1)
      mcs251_constrained_heap=$((mcs251_constrained_heap + 1))
      clang_user_args+=("${argument}")
      sdcc_user_args+=("${argument}")
      ;;
    -DSTCXX_MCS251_CONSTRAINED_HEAP=*)
      printf 'STCXX_MCS251_CONSTRAINED_HEAP must be exactly 1\n' >&2
      exit 2
      ;;
    -DAI8051U_34K64)
      target_ai8051u_34k64=1
      clang_user_args+=("${argument}")
      sdcc_user_args+=("${argument}")
      ;;
    -DSTC16F40K128)
      printf 'STC16F40K128 support has been removed\n' >&2
      exit 2
      ;;
    -DSTC32G144K246)
      target_stc32g144k246=1
      clang_user_args+=("${argument}")
      sdcc_user_args+=("${argument}")
      ;;
    -DF_CPU=*)
      clock_definition_count=$((clock_definition_count + 1))
      case "${argument#-DF_CPU=}" in
        12000000L|12000000UL|12000000) clock_hz=12000000 ;;
        40000000L|40000000UL|40000000) clock_hz=40000000 ;;
        48000000L|48000000UL|48000000) clock_hz=48000000 ;;
        *) clock_hz="" ;;
      esac
      clang_user_args+=("${argument}")
      sdcc_user_args+=("${argument}")
      ;;
    -mmcs251)
      sdcc_target="mcs251"
      sdcc_user_args+=("${argument}")
      ;;
    -mmcs51)
      printf "MCS51 support has been removed; use -mmcs251\n" >&2
      exit 2
      ;;
    -Ddouble=float)
      # A keyword macro is forbidden by the versioned target C++ ABI.
      ;;
    -D*)
      clang_user_args+=("${argument}")
      sdcc_user_args+=("${argument}")
      ;;
    -I*)
      normalized="$(normalize_include_arg "${argument}" -I)"
      # Arduino appends the SDCC C include directories to every recipe. They
      # define C-only wchar_t/bool/size_t types and must never shadow the
      # custom Clang target resource headers.
      if [[ "${normalized}" != *"/tools/sdcc-mcs251/"* &&
            "${normalized}" != "-I${sdcc_canonical_include}" &&
            "${normalized}" != "-I${sdcc_canonical_include}/"* ]]; then
        clang_user_args+=("${normalized}")
      fi
      sdcc_user_args+=("${normalized}")
      ;;
    --function-sections|--data-sections)
      sdcc_user_args+=("${argument}")
      sdcc_section_args+=("${argument}")
      ;;
    -c|--std-sdcc11|--opt-code-size|--less-pedantic|--stack-auto|--model-large|-MMD|-Wp-Wall|-V)
      sdcc_user_args+=("${argument}")
      ;;
    -M|-MG|-MP|-E|-dM)
      ;;
    -MF)
      # Arduino Builder appends this during library discovery. Capture it so
      # Clang can report unresolved headers (for example SPI.h) back to the
      # normal Arduino library resolver.
      expect_dependency_file=1
      ;;
    *)
      if [[ "${mode}" == "compile-c" ]]; then
        sdcc_user_args+=("${argument}")
      elif [[ "${mode}" == "compile-cpp" ||
              "${mode}" == "preprocess-deps" ||
              "${mode}" == "preprocess-macros" ]]; then
        printf 'unsupported Arduino C++ compiler argument: %s\n' \
          "${argument}" >&2
        exit 2
      fi
      ;;
  esac
done
[[ ${expect_dependency_file} -eq 0 ]] || {
  printf 'Arduino C++ compiler argument -MF is missing its destination\n' >&2
  exit 2
}

[[ ${cpp_enabled} -eq 1 ]] || { printf 'STCXX_CPP_CORE=1 is missing\n' >&2; exit 2; }
[[ ${clock_definition_count} -eq 1 &&
   "${sdcc_target}" == "mcs251" &&
   ("${clock_hz}" == "12000000" ||
    ("${clock_hz}" == "40000000" && ${target_ai8051u_34k64} -eq 1 &&
     "${sdcc_target}" == "mcs251") ||
    ("${clock_hz}" == "48000000" && ${target_stc32g144k246} -eq 1 &&
     "${sdcc_target}" == "mcs251")) ]] || {
  printf 'the Arduino CLI C++ route requires one F_CPU: 12 MHz for MCS251, 40 MHz only for AI8051U_34K64 MCS251, or 48 MHz only for STC32G144K246 MCS251\n' >&2
  exit 2
}

if [[ ${target_stc32g144k246} -eq 1 &&
      ("${sdcc_target}" != "mcs251" || ${target_ai8051u_34k64} -ne 0) ]]; then
  printf 'STC32G144K246 requires its own MCS251 target identity\n' >&2
  exit 2
fi

if [[ ${mcs251_constrained_heap} -gt 1 ]]; then
  printf 'STCXX MCS251 constrained-heap identity is duplicated\n' >&2
  exit 2
fi
if [[ "${sdcc_target}" != "mcs251" &&
      ${mcs251_constrained_heap} -ne 0 ]]; then
  printf 'the constrained STCXX heap contract requires MCS251\n' >&2
  exit 2
fi

sdcc_target_option=-mmcs251
sdcc_runtime_subdir=mcs251-large-stack-auto
sdcc_runtime_archive=mcs251.lib
target_cpp_args=(
  -DSTCXX_TARGET_ABI=1
  -DSTCXX_TARGET_MCS251=1 -DSTCXX_TARGET_ENDIAN_LITTLE=0
  -DSTCXX_TARGET_ENDIAN_BIG=1
)
target_stack_link_args=()
bridge_assembler="${sdas251}"
if [[ "${mode}" == "link" ]]; then
  for value in "${mcs251_iram_size}" "${mcs251_stack_loc}" "${mcs251_stack_size}"; do
    [[ "${value}" =~ ^0x[0-9A-Fa-f]+$ ]] || {
      printf 'MCS251 C++ extended-stack layout is missing or malformed\n' >&2
      exit 2
    }
  done
  target_stack_link_args=(
    --iram-size "${mcs251_iram_size}"
    --stack-loc "${mcs251_stack_loc}"
    --stack-size "${mcs251_stack_size}"
  )
fi
sdcc_runtime_lib="${sdcc_runtime_root}/${sdcc_runtime_subdir}"
clang_user_args+=("${target_cpp_args[@]}")
sdcc_user_args+=("${target_cpp_args[@]}")

target_triple="$(json_value targets.${sdcc_target}.target_triple)"
data_layout="$(json_value targets.${sdcc_target}.data_layout)"
abi_symbol="$(json_value targets.${sdcc_target}.abi_identity_symbol)"

resource_dir=""
clang_base=()
prepare_clang() {
  verify_frontend_tools
  test -d "${cpp_include_root}" || {
    printf 'missing freestanding C++ include root: %s\n' \
      "${cpp_include_root}" >&2
    exit 2
  }
  resource_dir="$("${clang}" --print-resource-dir)"
  test -d "${resource_dir}/include"
  clang_base=(
    "${clang}" "--target=${target_triple}" -x c++ -std=gnu++11 "-O${cpp_optimization}"
    -fno-vectorize -fno-slp-vectorize
    -ffreestanding -fno-builtin -funsigned-char -fno-exceptions -fno-rtti
    -fno-threadsafe-statics -fno-use-cxa-atexit -fno-c++-static-destructors
    -fno-unwind-tables -fno-asynchronous-unwind-tables
    -Xclang -mno-constructor-aliases -Xclang -disable-O0-optnone
    -nostdinc "-I${cpp_include_root}" "-isystem${resource_dir}/include" -Werror
    # Keep upstream portability notices (#warning, e.g. OneWire's generic
    # GPIO path) and redundant function-type qualifiers visible, but do not
    # misclassify them as C++ language errors. No SDCC/ABI warning gate is
    # relaxed; peripheral timing still needs a separate behavioral test.
    -Wno-error=cpp -Wno-error=ignored-qualifiers
  )
}

case "${mode}" in
  preprocess-deps)
    prepare_clang
    mark_pipeline_ready
    "${clang_base[@]}" "${clang_user_args[@]}" -M -MG -MP "${source_path}"
    ;;

  preprocess-macros)
    prepare_clang
    mark_pipeline_ready
    if [[ -n "${dependency_file}" ]]; then
      mkdir -p "$(dirname "${dependency_file}")"
      discovery_log="${dependency_file}.stcxx-discovery-$$.log"
      set +e
      "${clang_base[@]}" "${clang_user_args[@]}" -dM -E \
        "${source_path}" >/dev/null 2>"${discovery_log}"
      discovery_status=$?
      set -e
      if [[ ${discovery_status} -ne 0 ]]; then
        # Arduino Builder discovers one library at a time by parsing the
        # compiler's missing-header diagnostic. Normalize Clang's wording to
        # the GCC form understood by Arduino CLI, without hiding any other
        # frontend diagnostic.
        "${python}" - "${discovery_log}" <<'PY' >&2
import re
import sys
from pathlib import Path

pattern = re.compile(
    r"^(.*:[0-9]+:[0-9]+): fatal error: '([^']+)' file not found$"
)
for line in Path(sys.argv[1]).read_text(
    encoding="utf-8", errors="replace"
).splitlines():
    match = pattern.match(line)
    if match:
        print(f"{match.group(1)}: fatal error: "
              f"{match.group(2)}: No such file or directory")
    else:
        print(line)
PY
        rm -f "${discovery_log}"
        exit "${discovery_status}"
      fi
      rm -f "${discovery_log}"
      "${clang_base[@]}" "${clang_user_args[@]}" -M -MP \
        -MF "${dependency_file}" "${source_path}"
      test -s "${dependency_file}"
      exit 0
    fi
    if [[ "${object_path}" == "/dev/null" ]]; then
      "${clang_base[@]}" "${clang_user_args[@]}" -dM -E "${source_path}"
    else
      mkdir -p "$(dirname "${object_path}")"
      "${clang_base[@]}" "${clang_user_args[@]}" -E -CC \
        "${source_path}" -o "${object_path}"
    fi
    ;;

  compile-cpp)
    prepare_clang
    verify_sdcc
    mark_pipeline_ready
    mkdir -p "$(dirname "${object_path}")"
    bitcode="${object_path}.stcxx.bc"
    llvm_ir="${object_path}.stcxx.ll"
    # Do not use a .c suffix: Arduino Builder recursively rescans build
    # directories and would mistake this diagnostic CBE output for a library
    # source translation unit on an incremental build.
    module_c="${object_path}.stcxx.module.cbe"
    command_log="${object_path}.stcxx-command.txt"
    printf '%q ' "${clang_base[@]}" "${clang_user_args[@]}" \
      -emit-llvm -c "${source_path}" -o "${bitcode}" >"${command_log}"
    printf '\n' >>"${command_log}"
    "${clang_base[@]}" "${clang_user_args[@]}" -emit-llvm -c \
      "${source_path}" -o "${bitcode}"
    "${llvm_dis}" "${bitcode}" -o "${llvm_ir}"
    grep -Fqx "target datalayout = \"${data_layout}\"" "${llvm_ir}"
    grep -Fqx "target triple = \"${target_triple}\"" "${llvm_ir}"
    alias_count="$(grep -Ec '^@[A-Za-z0-9_.$"-]+[[:space:]]*=[^;]*[[:space:]]alias[[:space:]]' "${llvm_ir}" || true)"
    [[ "${alias_count}" == 0 ]] || {
      printf 'constructor/function alias gate failed for %s: %s alias(es)\n' \
        "${source_path}" "${alias_count}" >&2
      exit 1
    }
    "${llvm_cbe}" "${bitcode}" -o "${module_c}"

    object_rel="${object_path%.o}.rel"
    placeholder="${object_path}.stcxx-placeholder.c"
    symbol_hash="$(printf '%s\n%s\n' "${source_path}" "${object_path}" | sha256sum | cut -c1-16)"
    printf 'void __stcxx_placeholder_%s(void) {}\n' "${symbol_hash}" >"${placeholder}"
    "${sdcc}" "${sdcc_target_option}" --model-large --stack-auto --std-sdcc11 \
      --opt-code-size --less-pedantic -c "${placeholder}" -o "${object_rel}"
    cp -f "${object_rel}" "${object_path}"
    rm -f "${placeholder}"

    "${python}" - "${source_path}" "${object_path}" "${bitcode}" \
      "${llvm_ir}" "${module_c}" "${target_triple}" "${data_layout}" "${cpp_optimization}" <<'PY'
import hashlib
import json
import sys
from pathlib import Path

source, object_path, bitcode, llvm_ir, module_c, triple, layout, optimization = sys.argv[1:]
def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()
metadata = {
    "schema_version": 1,
    "source": str(Path(source).resolve()),
    "source_sha256": digest(source),
    "object": str(Path(object_path).resolve()),
    "object_sha256": digest(object_path),
    "bitcode": str(Path(bitcode).resolve()),
    "bitcode_sha256": digest(bitcode),
    "llvm_ir_sha256": digest(llvm_ir),
    "module_c_sha256": digest(module_c),
    "target_triple": triple,
    "data_layout": layout,
    "alias_count": 0,
    "module_llvm_cbe": "pass",
    "clang_optimization": "-O" + optimization,
    "clang_vectorization": "disabled-loop-and-slp",
}
Path(object_path + ".stcxx.json").write_text(
    json.dumps(metadata, indent=2) + "\n", encoding="utf-8", newline="\n"
)
PY
    ;;

  compile-c)
    verify_sdcc
    prepare_clang
    mark_pipeline_ready
    mkdir -p "$(dirname "${object_path}")"
    object_rel="${object_path%.o}.rel"
    # Always use the stack ABI in the C++ profile, even if a stale platform
    # package omitted the menu's explicit --stack-auto property.
    filtered_sdcc_args=()
    has_stack_auto=0
    for argument in "${sdcc_user_args[@]}"; do
      [[ "${argument}" == --stack-auto ]] && has_stack_auto=1
      filtered_sdcc_args+=("${argument}")
    done
    [[ ${has_stack_auto} -eq 1 ]] || filtered_sdcc_args+=(--stack-auto)
    # SDCC ignores GCC's -MF convention and writes -MMD output beside its
    # process cwd.  Bind that cwd to the object directory so a library build
    # can never leak basename.d files into the repository or caller cwd.
    (
      cd "$(dirname "${object_rel}")"
      "${sdcc}" "${filtered_sdcc_args[@]}" "${source_path}" -o "${object_rel}"
    )
    cp -f "${object_rel}" "${object_path}"
    "${python}" - "${object_rel}.stcxx-c.json" "${source_path}" "${object_rel}" \
      "${clang}" "${sdcc}" "${target_triple}" "${cpp_include_root}" "${resource_dir}" "${#filtered_sdcc_args[@]}" \
      "${filtered_sdcc_args[@]}" "${clang_user_args[@]}" <<'PY'
import hashlib
import json
import re
import sys
from pathlib import Path

metadata_path, source, rel, clang, sdcc, triple, cpp_headers, resource_dir, sdcc_count, *arguments = sys.argv[1:]
sdcc_count = int(sdcc_count)
sdcc_arguments = arguments[:sdcc_count]
clang_arguments = [
    f"--target={triple}", "-std=gnu11", "-ffreestanding", "-funsigned-char",
    "-nostdinc", "-I" + cpp_headers, "-isystem" + str(Path(resource_dir) / "include"),
    # AST extraction uses only source ranges and function references. Native
    # SDCC recompiles the retained source with its original storage/ABI flags.
    "-D__code=", "-D__reentrant=",
] + arguments[sdcc_count:]

def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

result = {
    "schema_version": 1,
    "source": str(Path(source).resolve()),
    "source_sha256": digest(source),
    "original_rel": str(Path(rel).resolve()),
    "original_rel_sha256": digest(rel),
    "clang": str(Path(clang).resolve()),
    "clang_sha256": digest(clang),
    "clang_arguments": clang_arguments,
    "sdcc": str(Path(sdcc).resolve()),
    "sdcc_sha256": digest(sdcc),
    "sdcc_arguments": sdcc_arguments,
    "relocated_source_parent_include": str(Path(source).resolve().parent),
}
Path(metadata_path).write_text(
    json.dumps(result, indent=2) + "\n", encoding="utf-8", newline="\n"
)
PY
    ;;

  link)
    verify_frontend_tools
    verify_tool "${llvm_link}" "$(json_value tools.llvm_link.sha256)" llvm-link
    verify_tool "${opt}" "$(json_value tools.opt.sha256)" opt
    verify_sdcc
    output_hex="${object_path}"
    [[ "${output_hex}" == *.hex ]] || {
      printf 'unexpected Arduino C++ output extension: %s\n' "${output_hex}" >&2
      exit 2
    }
    recipe_output=""
    output_count=0
    expect_recipe_output=0
    for argument in "${original_args[@]}"; do
      if [[ ${expect_recipe_output} -eq 1 ]]; then
        recipe_output="$(to_linux_path "${argument}")"
        output_count=$((output_count + 1))
        expect_recipe_output=0
      elif [[ "${argument}" == -o ]]; then
        expect_recipe_output=1
      fi
    done
    [[ ${expect_recipe_output} -eq 0 && ${output_count} -eq 1 &&
       "${recipe_output}" == "${output_hex}" ]] || {
      printf 'Arduino C++ link output mismatch: wrapper=%s recipe=%s count=%s\n' \
        "${output_hex}" "${recipe_output}" "${output_count}" >&2
      exit 2
    }
    sdar="${sdcc_build_root}/bin/sdar"
    verify_tool "${sdar}" "$(json_value tools.sdar.sha256)" patched-sdar
    mark_pipeline_ready
    build_root="$(dirname "${output_hex}")"
    work="${build_root}/stcxx"
    mkdir -p "${work}"

    # Select C++ sidecars only from objects participating in this exact link.
    # A recursive build-root scan is unsafe because Arduino deliberately reuses
    # build directories and leaves removed translation-unit diagnostics behind.
    direct_objects=()
    archives=()
    for argument in "${original_args[@]}"; do
      case "${argument}" in
        *.o) direct_objects+=("$(to_linux_path "${argument}")") ;;
        *.a) archives+=("$(to_linux_path "${argument}")") ;;
      esac
    done

    for object in "${direct_objects[@]}"; do
      [[ "$(basename "${object}")" != stcxx_heap.c.o ]] || {
        printf 'STCXX heap object unexpectedly entered Arduino direct inputs: %s\n' \
          "${object}" >&2
        exit 2
      }
    done

    bitcode_files=()
    direct_bitcode_files=()
    archive_candidate_args=()
    native_direct_rels=()
    for object in "${direct_objects[@]}"; do
      bitcode="${object}.stcxx.bc"
      if [[ -f "${bitcode}" ]]; then
        bitcode_files+=("${bitcode}")
        direct_bitcode_files+=("${bitcode}")
      else
        native_rel="${object%.o}.rel"
        test -f "${native_rel}" || {
          printf 'missing native SDCC relocatable mirror: %s\n' "${native_rel}" >&2
          exit 2
        }
        native_direct_rels+=("${native_rel}")
      fi
    done

    heap_rel_candidates=()
    heap_archive_candidates=()
    cpp_archive_members_file="${work}/cpp-archive-members.tsv"
    : >"${cpp_archive_members_file}"
    for archive in "${archives[@]}"; do
      test -f "${archive}" || {
        printf 'missing Arduino archive: %s\n' "${archive}" >&2
        exit 2
      }
      archive_lib="${archive%.a}.lib"
      test -f "${archive_lib}" || {
        printf 'missing SDCC mirror archive: %s\n' "${archive_lib}" >&2
        exit 2
      }
      archive_hash="$(sha256sum "${archive}" | awk '{print $1}')"
      archive_lib_hash="$(sha256sum "${archive_lib}" | awk '{print $1}')"
      [[ "${archive_hash}" == "${archive_lib_hash}" ]] || {
        printf 'Arduino .a and SDCC .lib archive mismatch: %s %s\n' \
          "${archive}" "${archive_lib}" >&2
        exit 2
      }
      mapfile -t archive_members < <("${sdar}" -t "${archive}")
      archive_dir="$(dirname "${archive}")"
      heap_archive_member_count=0
      for archive_member in "${archive_members[@]}"; do
        [[ "${archive_member}" == stcxx_heap.c.rel ]] && \
          heap_archive_member_count=$((heap_archive_member_count + 1))
      done
      [[ ${heap_archive_member_count} -eq 0 ]] || {
        printf 'STCXX heap must not be stored in Arduino core archive: %s\n' \
          "${archive}" >&2
        exit 2
      }
      heap_candidate="${archive_dir}/stcxx_heap.c.rel"
      if [[ -f "${heap_candidate}" ]]; then
        heap_object_candidate="${archive_dir}/stcxx_heap.c.o"
        test -f "${heap_object_candidate}" || {
          printf 'STCXX heap Arduino object mirror is missing: %s\n' \
            "${heap_object_candidate}" >&2
          exit 2
        }
        heap_rel_hash="$(sha256sum "${heap_candidate}" | awk '{print $1}')"
        heap_object_hash="$(sha256sum "${heap_object_candidate}" | awk '{print $1}')"
        [[ "${heap_rel_hash}" == "${heap_object_hash}" ]] || {
          printf 'STCXX heap .o/.rel payload mismatch: %s\n' \
            "${heap_candidate}" >&2
          exit 2
        }
        heap_rel_candidates+=("${heap_candidate}")
        heap_archive_candidates+=("${archive}")
      fi
      declare -A selected_archive_members=()
      while IFS= read -r -d '' bitcode; do
        object="${bitcode%.stcxx.bc}"
        rel="${object%.o}.rel"
        member="$(basename "${object%.o}.rel")"
        member_matches=0
        for archive_member in "${archive_members[@]}"; do
          [[ "${archive_member}" == "${member}" ]] && member_matches=$((member_matches + 1))
        done
        if [[ ${member_matches} -gt 1 ]]; then
          printf 'duplicate archive member cannot be mapped safely: %s in %s\n' \
            "${member}" "${archive}" >&2
          exit 2
        fi
        # Arduino/SDAR archives flatten object paths to member basenames.  A
        # filename match alone can therefore select a removed TU's sidecar.
        # Select only when the current candidate .rel is byte-for-byte the
        # member that Arduino actually placed in this archive.
        if [[ ${member_matches} -eq 1 && -f "${rel}" ]]; then
          member_hash="$("${sdar}" -p "${archive}" "${member}" | sha256sum | awk '{print $1}')"
          rel_hash="$(sha256sum "${rel}" | awk '{print $1}')"
          if [[ "${member_hash}" == "${rel_hash}" ]]; then
            selected_archive_members["${member}"]=$((
              ${selected_archive_members["${member}"]:-0} + 1
            ))
            [[ ${selected_archive_members["${member}"]} -eq 1 ]] || {
              printf 'multiple C++ sidecars match archive member %s in %s\n' \
                "${member}" "${archive}" >&2
              exit 2
            }
            bitcode_files+=("${bitcode}")
            archive_candidate_args+=(
              --candidate "${archive}" "${member}" "${bitcode}"
            )
            printf '%s\t%s\n' "${archive}" "${member}" \
              >>"${cpp_archive_members_file}"
          fi
        fi
      done < <(find "${archive_dir}" -type f -name '*.stcxx.bc' -print0 | sort -z)
      unset selected_archive_members
    done


    [[ ${#heap_rel_candidates[@]} -eq 1 &&
       ${#heap_archive_candidates[@]} -eq 1 ]] || {
      printf 'expected exactly one out-of-archive STCXX heap object, got %s\n' \
        "${#heap_rel_candidates[@]}" >&2
      exit 2
    }
    heap_rel="${heap_rel_candidates[0]}"
    heap_archive="${heap_archive_candidates[0]}"
    heap_state_rel="$(dirname "${heap_rel}")/stcxx_heap_state.c.rel"
    [[ -f "${heap_state_rel}" ]] || {
      printf 'STCXX heap telemetry state object is missing: %s\n' \
        "${heap_state_rel}" >&2
      exit 2
    }
    "${python}" - "${heap_rel}" "${heap_state_rel}" "${sdcc_target}" \
      "${mcs251_constrained_heap}" <<'PY'
import re
import sys
from pathlib import Path

heap_rel = Path(sys.argv[1])
state_rel = Path(sys.argv[2])
target = sys.argv[3]
constrained = int(sys.argv[4])
heap_size_symbol = "___sdcc_heap_size32" if target == "mcs251" else "___sdcc_heap_size"
opposite_heap_size_symbol = "___sdcc_heap_size" if target == "mcs251" else "___sdcc_heap_size32"
payload = heap_rel.read_text(encoding="ascii")
if re.search(
    rf"^S {re.escape(opposite_heap_size_symbol)} Def[0-9A-Fa-f]+$",
    payload, re.MULTILINE,
):
    raise SystemExit(f"STCXX heap must not provide opposite-ABI {opposite_heap_size_symbol}: {heap_rel}")
if len(re.findall(r"^M stcxx_heap$", payload, re.MULTILINE)) != 1:
    raise SystemExit(f"unexpected STCXX heap module identity: {heap_rel}")
for symbol in ("___sdcc_heap", heap_size_symbol, "___stcxx_heap_init"):
    count = len(re.findall(
        rf"^S {re.escape(symbol)} Def[0-9A-Fa-f]+$", payload, re.MULTILINE
    ))
    if count != 1:
        raise SystemExit(
            f"STCXX heap must define {symbol} exactly once, observed {count}: "
            f"{heap_rel}"
        )
xseg = re.findall(r"^A XSEG size ([0-9A-Fa-f]+) flags ", payload, re.MULTILINE)
heap_bytes = int(xseg[0], 16) if len(xseg) == 1 else -1
if constrained:
    valid_heap = target == "mcs251" and constrained == 1 and heap_bytes == 3584
else:
    minimum = 4096 if target == "mcs251" else 512
    valid_heap = heap_bytes >= minimum
if not valid_heap:
    raise SystemExit(f"invalid STCXX heap XSEG allocation: {heap_rel}")

state_payload = state_rel.read_text(encoding="ascii")
if len(re.findall(r"^M stcxx_heap_state$", state_payload, re.MULTILINE)) != 1:
    raise SystemExit(f"unexpected STCXX heap-state module identity: {state_rel}")
state_xseg = re.findall(
    r"^A XSEG size ([0-9A-Fa-f]+) flags ", state_payload, re.MULTILINE
)
if len(state_xseg) != 1 or int(state_xseg[0], 16) != 8:
    raise SystemExit(f"STCXX heap-state XSEG is not exactly 8 bytes: {state_rel}")
for symbol in ("___sdcc_heap", "___sdcc_heap_size", "___sdcc_heap_size32", "___stcxx_heap_init"):
    if re.search(
        rf"^S {re.escape(symbol)} Def[0-9A-Fa-f]+$",
        state_payload, re.MULTILINE,
    ):
        raise SystemExit(
            f"STCXX heap-state object must not provide {symbol}: {state_rel}"
        )
for symbol in (
    "___stcxx_heap_telemetry_ready_state",
    "___stcxx_heap_telemetry_valid_state",
    "___stcxx_heap_initial_total_free_state",
    "___stcxx_heap_minimum_total_free_state",
    "___stcxx_heap_minimum_largest_free_state",
):
    count = len(re.findall(
        rf"^S {re.escape(symbol)} Def[0-9A-Fa-f]+$",
        state_payload, re.MULTILINE,
    ))
    if count != 1:
        raise SystemExit(
            f"STCXX heap-state must define {symbol} exactly once, "
            f"observed {count}: {state_rel}"
        )
PY
    heap_archive_members_file="${work}/core-archive-members.txt"
    "${sdar}" -t "${heap_archive}" >"${heap_archive_members_file}"
    [[ "$(grep -c '^stcxx_heap\.c\.rel$' "${heap_archive_members_file}" || true)" -eq 0 ]] || {
      printf 'STCXX heap unexpectedly remained in core archive: %s\n' \
        "${heap_archive}" >&2
      exit 2
    }
    [[ "$(grep -c '^stcxx_heap_state\.c\.rel$' "${heap_archive_members_file}" || true)" -eq 1 ]] || {
      printf 'STCXX heap telemetry state archive member is not unique: %s\n' \
        "${heap_archive}" >&2
      exit 2
    }
    state_member_hash="$("${sdar}" -p "${heap_archive}" \
      stcxx_heap_state.c.rel | sha256sum | awk '{print $1}')"
    state_rel_hash="$(sha256sum "${heap_state_rel}" | awk '{print $1}')"
    [[ "${state_member_hash}" == "${state_rel_hash}" ]] || {
      printf 'STCXX heap telemetry state archive member differs from REL\n' >&2
      exit 2
    }

    # A bitcode sidecar may only belong to one current link input.  Duplicates
    # indicate an ambiguous basename/archive layout and fail closed.
    if [[ ${#bitcode_files[@]} -gt 0 ]]; then
      mapfile -t duplicate_bitcode < <(printf '%s\n' "${bitcode_files[@]}" | sort | uniq -d)
      [[ ${#duplicate_bitcode[@]} -eq 0 ]] || {
        printf 'C++ sidecar selected by multiple link inputs: %s\n' \
          "${duplicate_bitcode[*]}" >&2
        exit 2
      }
      mapfile -t bitcode_files < <(printf '%s\n' "${bitcode_files[@]}" | sort)
    fi
    [[ ${#bitcode_files[@]} -gt 0 ]] || {
      printf 'no Arduino C++ bitcode sidecars belong to the current link inputs\n' >&2
      exit 2
    }

    "${python}" - "${target_triple}" "${data_layout}" "${bitcode_files[@]}" <<'PY'
import hashlib
import json
import sys
from pathlib import Path

triple, layout, *bitcode_paths = sys.argv[1:]

def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

for value in bitcode_paths:
    bitcode = Path(value).resolve()
    metadata_path = Path(value.replace(".stcxx.bc", ".stcxx.json"))
    if not metadata_path.is_file():
        raise SystemExit(f"missing C++ sidecar metadata: {metadata_path}")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    source = Path(metadata.get("source", "")).resolve()
    object_path = Path(metadata.get("object", "")).resolve()
    recorded_bitcode = Path(metadata.get("bitcode", "")).resolve()
    expected_object = Path(value.removesuffix(".stcxx.bc")).resolve()
    llvm_ir = Path(str(expected_object) + ".stcxx.ll")
    module_c = Path(str(expected_object) + ".stcxx.module.cbe")
    rel = Path(str(expected_object).removesuffix(".o") + ".rel")
    if (type(metadata.get("schema_version")) is not int
            or metadata.get("schema_version") != 1):
        raise SystemExit(f"unsupported C++ sidecar schema: {metadata_path}")
    if not source.is_file():
        raise SystemExit(f"C++ sidecar source no longer exists: {source}")
    if object_path != expected_object or recorded_bitcode != bitcode:
        raise SystemExit(f"C++ sidecar path mismatch: {metadata_path}")
    for artifact in (object_path, bitcode, llvm_ir, module_c, rel):
        if not artifact.is_file():
            raise SystemExit(f"missing C++ sidecar artifact: {artifact}")
    checks = {
        "source_sha256": digest(source),
        "object_sha256": digest(object_path),
        "bitcode_sha256": digest(bitcode),
        "llvm_ir_sha256": digest(llvm_ir),
        "module_c_sha256": digest(module_c),
    }
    mismatches = [name for name, observed in checks.items()
                  if metadata.get(name) != observed]
    if digest(rel) != checks["object_sha256"]:
        mismatches.append("rel_sha256")
    if mismatches:
        raise SystemExit(
            f"stale or modified C++ sidecar {metadata_path}: "
            + ", ".join(mismatches)
        )
    if metadata.get("target_triple") != triple or metadata.get("data_layout") != layout:
        raise SystemExit(f"C++ sidecar target mismatch: {metadata_path}")
print(f"STCXX_CURRENT_LINK_SIDECARS={len(bitcode_paths)}")
PY

    "${llvm_link}" "${bitcode_files[@]}" -o "${work}/all-candidates-linked.bc"
    "${llvm_dis}" "${work}/all-candidates-linked.bc" \
      -o "${work}/all-candidates-linked.ll"
    discovery_preserve_file="${work}/c-abi-preserve-discovery.txt"
    discovery_root_audit="${work}/c-abi-root-discovery-audit.json"
    discovery_root_args=(
      "${python}" "${root_collector}"
      --ir "${work}/all-candidates-linked.ll"
      --output "${discovery_preserve_file}"
      --audit-json "${discovery_root_audit}"
      --sdar "${sdar}"
      --cpp-members "${cpp_archive_members_file}"
      --required-root setup
      --required-root loop
      --required-root __stcxx_run_global_ctors
      --required-root "${abi_symbol}"
      --required-root stcxx_runtime_panic
    )
    for native_rel in "${native_direct_rels[@]}"; do
      discovery_root_args+=(--direct-rel "${native_rel}")
    done
    for archive in "${archives[@]}"; do
      discovery_root_args+=(--archive "${archive}")
    done
    "${discovery_root_args[@]}" >/dev/null

    selector_args=(
      "${python}" "${archive_selector}"
      --llvm-link "${llvm_link}"
      --llvm-dis "${llvm_dis}"
      --roots "${discovery_preserve_file}"
      --work-dir "${work}/archive-selection"
      --output-bc "${work}/linked.bc"
      --audit-json "${work}/cpp-archive-selection-audit.json"
    )
    for bitcode in "${direct_bitcode_files[@]}"; do
      selector_args+=(--direct "${bitcode}")
    done
    selector_args+=("${archive_candidate_args[@]}")
    "${selector_args[@]}" >/dev/null
    "${llvm_dis}" "${work}/linked.bc" -o "${work}/linked.ll"
    c_abi_preserve_file="${work}/c-abi-preserve.txt"
    c_abi_root_audit="${work}/c-abi-root-audit.json"
    root_args=(
      "${python}" "${root_collector}"
      --ir "${work}/linked.ll"
      --output "${c_abi_preserve_file}"
      --audit-json "${c_abi_root_audit}"
      --sdar "${sdar}"
      --cpp-members "${cpp_archive_members_file}"
      --required-root setup
      --required-root loop
      --required-root __stcxx_run_global_ctors
      --required-root "${abi_symbol}"
      --required-root stcxx_runtime_panic
    )
    for native_rel in "${native_direct_rels[@]}"; do
      root_args+=(--direct-rel "${native_rel}")
    done
    for archive in "${archives[@]}"; do
      root_args+=(--archive "${archive}")
    done
    c_abi_preserve="$("${root_args[@]}")"
    [[ -n "${c_abi_preserve}" ]] || {
      printf 'empty C ABI preservation set\n' >&2
      exit 2
    }
    cmp -s "${discovery_preserve_file}" "${c_abi_preserve_file}" || {
      printf 'C ABI roots changed after C++ archive selection\n' >&2
      exit 2
    }
    # Resolve C++ COMDAT/ODR definitions in LLVM while preserving every plain
    # C ABI definition that separately lowered C/assembly objects may call.
    # globalopt is deliberately excluded: it can fold dynamic constructors
    # into LLVM static initializers that are not equivalent after CBE/SDCC.
    # The generated bridge must retain and invoke every global ctor explicitly.
    # TU optimization may replace unused arguments with poison while the
    # callee still has public linkage. After whole-program internalization,
    # LLVM can remove those arguments without changing any escaping ABI.
    "${opt}" -passes=internalize,deadargelim,globaldce \
      "-internalize-public-api-list=${c_abi_preserve}" \
      "${work}/linked.bc" -o "${work}/optimized.bc"
    "${llvm_dis}" "${work}/optimized.bc" -o "${work}/optimized.ll"
    storage_args=("${python}" "${native_storage}" --ir "${work}/optimized.ll"
      --output "${work}/native-storage.json" --sdar "${sdar}"
      --cpp-members "${cpp_archive_members_file}")
    for native_rel in "${native_direct_rels[@]}"; do
      storage_args+=(--direct-rel "${native_rel}")
    done
    for archive in "${archives[@]}"; do
      storage_args+=(--archive "${archive}")
    done
    "${storage_args[@]}"
    "${llvm_cbe}" "${work}/optimized.bc" -o "${work}/raw.c"
    "${python}" "${adapter}" \
      --ir "${work}/optimized.ll" \
      --raw-c "${work}/raw.c" \
      --native-storage "${work}/native-storage.json" \
      --c-abi-preserve "${c_abi_preserve_file}" \
      --output-c "${work}/adapted.c" \
      --audit-json "${work}/audit.json" \
      --expected-triple "${target_triple}" \
      --expected-layout "${data_layout}" \
      --abi-identity-symbol "${abi_symbol}" \
      --target-profile "${sdcc_target}"

    # SDCC 4.6.0's GCSE pass can alias distinct inline temporaries across
    # basic blocks in a large LLVM-CBE generated bridge on either backend.
    # Keep native-C and placeholder compilation unchanged, but disable that
    # pass for every generated whole-program C++ bridge.

    bridge_raw_asm="${work}/cpp-bridge.raw.asm"
    bridge_asm="${work}/cpp-bridge.asm"
    bridge_rel="${work}/cpp-bridge.rel"
    bridge_lst="${work}/cpp-bridge.lst"
    bridge_rst="${work}/cpp-bridge.rst"
    bridge_log="${work}/sdcc-bridge.log"
    bridge_assembly_log="${work}/sdcc-bridge-assembly.log"
    warning_audit="${work}/sdcc-warning-audit.json"
    member_function_alignment_audit="${work}/member-function-alignment-audit.json"
    member_function_alignment_prior_audit="${work}/member-function-alignment-prior-audit.json"
    bridge_prior_even_asm="${work}/cpp-bridge.prior-even.asm"
    bridge_prior_even_rel="${work}/cpp-bridge.prior-even.rel"
    bridge_prior_even_lst="${work}/cpp-bridge.prior-even.lst"
    bridge_prior_even_rst="${work}/cpp-bridge.prior-even.rst"
    rm -f -- "${bridge_raw_asm}" "${bridge_asm}" "${bridge_rel}" \
      "${bridge_lst}" "${bridge_rst}" "${member_function_alignment_audit}" \
      "${member_function_alignment_prior_audit}" "${bridge_prior_even_asm}" \
      "${bridge_prior_even_rel}" "${bridge_prior_even_lst}" \
      "${bridge_prior_even_rst}"
    if ! "${sdcc}" "${sdcc_target_option}" --model-large --stack-auto --std-sdcc11 \
      --opt-code-size --nogcse --less-pedantic \
      "${sdcc_section_args[@]}" \
      "-I${sdcc_include_root}" "-I${sdcc_shared_include}" \
      -S "${work}/adapted.c" -o "${bridge_raw_asm}" 2>&1 | tee "${bridge_log}" >&2; then
      rm -f -- "${output_hex}"
      exit 1
    fi
    test -s "${bridge_raw_asm}"
    "${python}" "${member_function_aligner}" align \
      --input-assembly "${bridge_raw_asm}" \
      --output-assembly "${bridge_asm}" \
      --adapter-audit "${work}/audit.json" \
      --target-profile "${sdcc_target}" \
      --local-parity even \
      --audit-json "${member_function_alignment_audit}"
    "${bridge_assembler}" -plosgffw "${bridge_rel}" "${bridge_asm}" \
      2>&1 | tee "${bridge_assembly_log}"
    test -s "${bridge_rel}"
    test -s "${bridge_lst}"

    # Patched SDCC still diagnoses a small, understood set of LLVM-CBE
    # patterns.  Record those diagnostics and fail closed if a new warning
    # code/message appears, rather than silently accepting a bridge regression.
    "${python}" - "${bridge_log}" "${warning_audit}" "${sdcc_target}" \
      "${work}/audit.json" <<'PY'
import collections
import json
import re
import sys
from pathlib import Path

log_path, audit_path = map(Path, sys.argv[1:3])
target_profile = sys.argv[3]
ir_audit_path = Path(sys.argv[4])
adapted_path = log_path.with_name("adapted.c").resolve()
allowed = {
    84: {"'auto' variable 'r' may be used before initialization"},
}
warnings = []
preprocessor_warnings = []
unparsed = []
allowed_preprocessor_warnings = {
    '<command-line>: warning: "__has_builtin" redefined',
    '<command-line>: warning: "__STDC_HOSTED__" redefined',
}
for line in log_path.read_text(encoding="utf-8", errors="replace").splitlines():
    match = re.search(r"^(.*):([0-9]+): warning ([0-9]+):\s*(.*?)\s*$", line)
    if match:
        source_file = match.group(1)
        source_line = int(match.group(2))
        code = int(match.group(3))
        message = match.group(4)
        warnings.append(
            {
                "code": code,
                "message": message,
                "source_file": source_file,
                "source_line": source_line,
            }
        )
    elif line in allowed_preprocessor_warnings:
        preprocessor_warnings.append(line)
    elif "warning" in line.lower():
        unparsed.append(line)

adapted_c = adapted_path.read_text(encoding="utf-8")
adapted_lines = adapted_c.splitlines()
ir_audit = json.loads(ir_audit_path.read_text(encoding="utf-8"))
expected_member_pointer_casts = int(
    ir_audit["ir"]["pointer_integer_conversions"].get(
        "program_address_space_member_calls", 0
    )
)
expected_integer_to_pointer_casts = int(
    ir_audit["ir"]["pointer_integer_conversions"].get(
        "member_integer_to_pointer_count", 0
    )
)
expected_program_member_casts = int(
    ir_audit["ir"].get("program_address_space_audit", {}).get(
        "virtual_member_generic_to_program_casts", 0
    )
)
if target_profile != "mcs251" or expected_program_member_casts or expected_member_pointer_casts:
    raise SystemExit("MCS251 must not carry cross-address-space program-pointer conversions")
if "llvm_cbe_program_pointer" in adapted_c:
    raise SystemExit("unexpected cross-address-space program-pointer type in MCS251 CBE output")
program_member_cast_source_lines = []
wrong_source = []
for warning in warnings:
    # Source-relative structural checks are valid only for this generated C
    # file.  SDCC's one target-wide code-space qualifier diagnostic is emitted
    # as `-:0`; all other warning locations must resolve to adapted.c.
    if (warning["source_file"] == "-" and warning["source_line"] == 0 and
            warning["code"] == 357):
        continue
    if Path(warning["source_file"]).resolve() != adapted_path:
        wrong_source.append(warning)
if any(warning["code"] == 84 for warning in warnings):
    # LLVM-CBE's arithmetic helpers name their initialized return temporary
    # `r`; patched SDCC reports a known false positive for some call sites.
    # Never tolerate the diagnostic if an actually uninitialized declaration
    # of that name enters the generated bridge.
    # Match a declaration such as `uint16_t r;`, but never mistake the
    # initialized helper's `return r;` statement for one.  The latter was the
    # source of SDCC's known false-positive diagnostic in this bridge.
    uninitialized_r = [
        line for line in adapted_c.splitlines()
        if not line.strip().startswith("return ")
        and re.fullmatch(
            r"\s*(?:[A-Za-z_][A-Za-z0-9_]*\s+)+"
            r"(?:\*+\s*)?r(?:\s*\[[^\]]+\])?\s*;\s*",
            line,
        )
    ]
    if uninitialized_r:
        unexpected = [{"code": 84, "message": "uninitialized r declaration"}]
    else:
        unexpected = []
else:
    unexpected = []

def warning_source_line(warning):
    line_number = warning["source_line"]
    if line_number < 1 or line_number > len(adapted_lines):
        return None
    return adapted_lines[line_number - 1]


def verified_unused_cbe_temporary(warning):
    match = re.fullmatch(
        r"in function (\S+) unreferenced "
        r"(local variable|function parameter) : '(_[0-9]+)'",
        warning["message"],
    )
    if not match:
        return False

    symbol, kind, variable = match.groups()
    warning_index = warning["source_line"] - 1
    if warning_index < 0 or warning_index >= len(adapted_lines):
        return False
    # Optimized tail calls can place this diagnostic on the final call or
    # closing brace. The complete function below still proves the named
    # declaration/parameter has exactly one occurrence and no use.

    header_index = None
    symbol_pattern = re.compile(
        rf"^static\s+.*\b{re.escape(symbol)}\s*\(.*\)\s*\{{\s*$"
    )
    for index in range(warning_index, -1, -1):
        if symbol_pattern.fullmatch(adapted_lines[index]):
            header_index = index
            break
    if header_index is None:
        return False

    end_index = None
    for index in range(header_index + 1, len(adapted_lines)):
        if adapted_lines[index] == "}":
            end_index = index
            break
    if end_index is None or warning_index > end_index:
        return False

    function_lines = adapted_lines[header_index:end_index + 1]
    function_text = "\n".join(function_lines)
    if len(re.findall(rf"\b{re.escape(variable)}\b", function_text)) != 1:
        return False

    if kind == "function parameter":
        header = function_lines[0]
        parameters = header[header.find("(") + 1:header.rfind(")")]
        return bool(re.search(rf"\b{re.escape(variable)}\b", parameters))

    declaration_pattern = re.compile(
        rf"\s*(?:struct\s+[A-Za-z_][A-Za-z0-9_]*\s+|"
        rf"[A-Za-z_][A-Za-z0-9_]*(?:\s+|\s*\*+\s*))"
        rf"{re.escape(variable)}(?:\s*\[[^\]]+\])?\s*;"
        rf"(?:\s*/\*.*\*/)?\s*"
    )
    return any(
        declaration_pattern.fullmatch(line)
        for line in function_lines[1:]
    )


def verified_read_only_pgm_warning(warning):
    """Prove the locked ArduinoJson 7.4.3 f_str() read-only call chain.

    LLVM opaque pointers erase the pointee constness from
    `pgm_read(const T* const*)`.  For ArduinoJson 7.4.3 that makes SDCC warn at
    the generated f_str() call even though both generated helpers form a
    straight-line, read-only chain ending in exactly one load.  Keep this
    exception intentionally version- and symbol-specific: every caller,
    constant object, temporary, helper edge, and load must match before warning
    357 is accepted.
    """
    source_line = warning_source_line(warning)
    if source_line is None or target_profile != "mcs251":
        return False

    f_str_symbol = (
        "_ZNK11ArduinoJson8V743JB4220DeserializationError5f_strEv"
    )
    pgm_read_symbol = (
        "_ZN11ArduinoJson8V743JB426detail8pgm_readIcEEPKT_PKS5_"
    )
    pgm_read_ptr_symbol = "_ZL12pgm_read_ptrPKv"
    messages_symbol = (
        "_ZZNK11ArduinoJson8V743JB4220DeserializationError5f_strEvE8messages"
    )
    message_symbols = [
        ("_ZZNK11ArduinoJson8V743JB4220DeserializationError5f_strEvE2s" +
         str(index))
        for index in range(6)
    ]

    call = re.fullmatch(
        r"\s*_[0-9]+\s*=\s*"
        rf"(?P<callee>{re.escape(pgm_read_symbol)})"
        r"\((?P<argument>.*)\);\s*",
        source_line,
    )
    if not call:
        return False

    warning_index = warning["source_line"] - 1

    def find_exact_void_pointer_function(symbol):
        header = re.compile(
            rf"^static void\* {re.escape(symbol)}"
            rf"\(void\* (?P<parameter>_[0-9]+)\) \{{\s*$"
        )
        matches = [
            (index, match)
            for index, line in enumerate(adapted_lines)
            if (match := header.fullmatch(line))
        ]
        if len(matches) != 1:
            return None
        header_index, match = matches[0]
        end_index = next(
            (index for index in range(header_index + 1, len(adapted_lines))
             if adapted_lines[index] == "}"),
            None,
        )
        if end_index is None:
            return None
        statements = []
        for line in adapted_lines[header_index + 1:end_index]:
            stripped = re.sub(r"/\*.*?\*/", "", line).strip()
            if stripped:
                statements.append(stripped)
        return {
            "header_index": header_index,
            "end_index": end_index,
            "parameter": match.group("parameter"),
            "statements": statements,
        }

    f_str = find_exact_void_pointer_function(f_str_symbol)
    outer = find_exact_void_pointer_function(pgm_read_symbol)
    inner = find_exact_void_pointer_function(pgm_read_ptr_symbol)
    if f_str is None or outer is None or inner is None:
        return False
    if not (f_str["header_index"] < warning_index < f_str["end_index"]):
        return False

    def declared_void_temporaries(statements):
        return [
            match.group("temporary")
            for statement in statements
            if (match := re.fullmatch(
                r"void\* (?P<temporary>_[0-9]+);", statement
            ))
        ]

    # Bind the f_str() body to the generated read-only error-code lookup.  This
    # also proves that the index in the warning line came from the receiver and
    # that the warning result is returned without any intervening side effect.
    f_statements = f_str["statements"]
    f_voids = declared_void_temporaries(f_statements)
    if len(f_voids) != 3 or len(set(f_voids)) != 3:
        return False
    code_declarations = [
        match.group("temporary")
        for statement in f_statements
        if (match := re.fullmatch(
            r"uint16_t (?P<temporary>_[0-9]+);", statement
        ))
    ]
    if len(code_declarations) != 1:
        return False
    receiver_alias, receiver, result = f_voids
    code = code_declarations[0]
    expected_f_statements = [
        f"void* {receiver_alias};",
        f"void* {receiver};",
        f"uint16_t {code};",
        f"void* {result};",
        f"{receiver_alias} = {f_str['parameter']};",
        f"{receiver} = {receiver_alias};",
        (f"{code} = *(uint16_t*)(((&(((struct "
         "l_struct_class_OC_ArduinoJson_KD__KD_V743JB42_KD__KD_"
         f"DeserializationError*){receiver})->field0))));"),
        source_line.strip(),
        f"return {result};",
    ]
    if f_statements != expected_f_statements:
        return False
    if not source_line.lstrip().startswith(f"{result} = "):
        return False

    argument = re.sub(r"\s+", "", call.group("argument"))
    expected_argument = (
        "(((&((void**)(&" + messages_symbol + "))["
        "((signed_BitInt(24))(((((signed_BitInt(24))(int16_t)" + code +
        "))&16777215)))])))"
    )
    if argument != expected_argument:
        return False

    # The table itself must be one exact const definition whose six entries are
    # the six exact const byte arrays from DeserializationError::f_str().
    messages_definition = re.compile(
        rf"^static const struct l_array_6_void_KC_ "
        rf"{re.escape(messages_symbol)} = \{{ \{{ "
        rf"(?P<initializer>.*) \}} \}};$"
    )
    message_definitions = [
        match for line in adapted_lines
        if (match := messages_definition.fullmatch(line))
    ]
    if len(message_definitions) != 1:
        return False
    expected_initializer = ", ".join(
        f"(&{symbol})" for symbol in message_symbols
    )
    if message_definitions[0].group("initializer") != expected_initializer:
        return False
    expected_strings = [
        (3, "Ok"),
        (11, "EmptyInput"),
        (16, "IncompleteInput"),
        (13, "InvalidInput"),
        (9, "NoMemory"),
        (8, "TooDeep"),
    ]
    for symbol, (array_size, literal) in zip(message_symbols, expected_strings):
        definition = re.compile(
            rf"^static const struct l_array_{array_size}_uint8_t "
            rf"{re.escape(symbol)} = \{{ \"{literal}\" \}};$"
        )
        if sum(bool(definition.fullmatch(line)) for line in adapted_lines) != 1:
            return False

    def verify_alias_call_return(function, callee):
        statements = function["statements"]
        temporaries = declared_void_temporaries(statements)
        if len(temporaries) != 3 or len(set(temporaries)) != 3:
            return False
        first, second, result = temporaries
        return statements == [
            f"void* {first};",
            f"void* {second};",
            f"void* {result};",
            f"{first} = {function['parameter']};",
            f"{second} = {first};",
            f"{result} = {callee}({second});",
            f"return {result};",
        ]

    if not verify_alias_call_return(outer, pgm_read_ptr_symbol):
        return False

    inner_statements = inner["statements"]
    inner_temporaries = declared_void_temporaries(inner_statements)
    if len(inner_temporaries) != 3 or len(set(inner_temporaries)) != 3:
        return False
    first, second, result = inner_temporaries
    return inner_statements == [
        f"void* {first};",
        f"void* {second};",
        f"void* {result};",
        f"{first} = {inner['parameter']};",
        f"{second} = {first};",
        f"{result} = *(void**){second};",
        f"return {result};",
    ]


def verified_constant_array_gep_warning(warning):
    # LLVM opaque ptr carries no pointee const qualifier. CBE materializes a
    # constant aggregate element address in void*, then reads scalar fields.
    # Limit this exception to that complete spelling and a read-only local use
    # chain; stores, escapes, mutable globals and new pointer forms still fail.
    line = warning_source_line(warning)
    if line is None:
        return False
    match = re.fullmatch(
        r"\s*(?P<temporary>_[0-9]+) = \(\(&\(&(?P<symbol>[A-Za-z_][A-Za-z_0-9]*)\)"
        r"->array\[[^;\n]+\]\)\);\s*", line)
    if not match:
        return False
    symbol, temporary = match.group("symbol", "temporary")
    declaration = re.compile(
        rf"^static const struct l_array_[A-Za-z_0-9]+ {re.escape(symbol)} = \{{.*\}};$",
        re.MULTILINE)
    if len(declaration.findall(adapted_c)) != 1:
        return False
    warning_index = warning["source_line"] - 1
    start = next((i for i in range(warning_index - 1, -1, -1)
                  if adapted_lines[i].startswith("static ") and adapted_lines[i].endswith(" {")), None)
    end = next((i for i in range(warning_index + 1, len(adapted_lines))
                if adapted_lines[i] == "}"), None)
    if start is None or end is None:
        return False
    uses = [(i, text.strip()) for i, text in enumerate(adapted_lines[start + 1:end], start + 1)
            if re.search(rf"\b{re.escape(temporary)}\b", text)]
    declarations = [(i, text) for i, text in uses if text == f"void* {temporary};"]
    if len(declarations) != 1 or declarations[0][0] >= warning_index:
        return False
    reads = 0
    for index, text in uses:
        if index == warning_index or (index, text) in declarations:
            continue
        if index <= warning_index or not re.fullmatch(
            r"_[0-9]+ = \*\((?:u?int(?:8|16|32|64)_t|float|double)\*\)"
            r"[^;\n]+;", text):
            return False
        expression = text.split("=", 1)[1]
        if any(token in expression for token in ("=", "++", "--", '"', "'")):
            return False
        if re.search(r"\b_[0-9]+\s*\(", expression):
            return False
        # Address arithmetic may call only the already-audited scalar CBE
        # helpers. An arbitrary call hidden inside the load is still an escape.
        for identifier in re.findall(r"[A-Za-z_][A-Za-z_0-9]*", expression):
            if not re.fullmatch(
                r"_[0-9]+|u?int(?:8|16|32|64)_t|float|double|signed|unsigned|"
                r"_BitInt|struct|array|field[0-9]+|l_(?:array|struct)_[A-Za-z_0-9]+|"
                r"llvm_(?:add|sub|mul|lshr|ashr|shl|udiv|urem|sdiv|srem)_[ui](?:8|16|24|32|64)",
                identifier):
                return False
        reads += 1
    return reads > 0


def is_verified_cbe_warning(warning):
    code = warning["code"]
    message = warning["message"]
    if message in allowed.get(code, set()):
        return True

    # Optimization can erase uses while retaining an internal callback's ABI.
    # Accept only a generated name proved unused in its complete function.
    if code == 85:
        return verified_unused_cbe_temporary(warning)

    source_line = warning_source_line(warning)

    # These const-loss diagnostics are accepted only at CBE's exact vtable
    # materialization or constant-string PHI spellings.  A new pointer
    # conversion with the same warning number still fails closed.
    if code == 196 and message == "pointer target lost const qualifier":
        if source_line is None:
            return False
        vtable_assignment = re.fullmatch(
            r"\s*\*\(void\*\*\)_[0-9]+\s*=\s*.*"
            r"&_ZTV[A-Za-z0-9_]+.*->field0.*->array.*;\s*",
            source_line,
        )
        constant_phi = re.fullmatch(
            r"\s*_[0-9]+__PHI_TEMPORARY\s*=\s*"
            r"\(&_OC_str_OC_[0-9]+\);\s*/\* for PHI node \*/\s*",
            source_line,
        )
        return bool(
            (target_profile == "mcs251" and vtable_assignment)
            or constant_phi
            or verified_constant_array_gep_warning(warning)
        )

    # LLVM-CBE represents ordinary indirect calls through a named l_fptr_N
    # typedef.  Bind warning 244 to that complete legacy one-line expression.
    if code == 244 and message == "pointer types incompatible":
        if source_line is None:
            return False
        indirect_call = re.fullmatch(
            r"\s*(?:_[0-9]+\s*=\s*)?"
            r"\(\(l_fptr_[0-9]+\*\)\(void\*\)_[0-9]+\)"
            r"\([^;]*\);\s*",
            source_line,
        )
        return bool(indirect_call)


    return False

target_wide_const_warnings = [
    warning for warning in warnings
    if (warning["code"] == 357 and warning["source_file"] == "-" and
        warning["source_line"] == 0)
]
if len(target_wide_const_warnings) > 1:
    unexpected.extend(target_wide_const_warnings[1:])

verified_source_pgm_warnings = [
    warning for warning in warnings
    if (warning["code"] == 357
        and warning["source_file"] != "-"
        and warning["message"] ==
        "pointer to object in read-only code space should be pointer to const"
        and verified_read_only_pgm_warning(warning))
]
if len(verified_source_pgm_warnings) > 1:
    unexpected.extend(verified_source_pgm_warnings[1:])

unexpected.extend(wrong_source)
unexpected.extend(
    warning for warning in warnings if not is_verified_cbe_warning(warning)
)
if unparsed or unexpected:
    details = []
    if unparsed:
        details.append("unparsed=" + repr(unparsed))
    if unexpected:
        details.append("unexpected=" + repr(unexpected))
    raise SystemExit("SDCC bridge warning audit failed: " + "; ".join(details))

histogram = collections.Counter(warning["code"] for warning in warnings)
program_member_cast_warning_count = sum(
    1 for warning in warnings
    if warning["code"] == 244
    and warning["message"] == "pointer types incompatible"
    and warning["source_line"] in program_member_cast_source_lines
)
result = {
    "schema_version": 1,
    "outcome": "pass",
    "policy": "known-llvm-cbe-sdcc-diagnostics-only",
    "warning_count": len(warnings) + len(preprocessor_warnings),
    "sdcc_warning_count": len(warnings),
    "preprocessor_warning_count": len(preprocessor_warnings),
    "warning_codes": {str(code): count for code, count in sorted(histogram.items())},
    "unexpected_warning_count": 0,
    "target_profile": target_profile,
    "program_member_cast_source_count": len(program_member_cast_source_lines),
    "program_member_cast_warning_count": program_member_cast_warning_count,
    "program_member_cast_policy": (
        "audited-ir-as1-via-uintptr-no-warning244"
    ),
    "verified_source_pgm_warning_count": len(verified_source_pgm_warnings),
    "verified_source_pgm_warning_policy": (
        "exact-arduinojson-7.4.3-f_str-two-level-read-only-chain"
    ),
}
audit_path.write_text(
    json.dumps(result, indent=2) + "\n", encoding="utf-8", newline="\n"
)
PY

    link_args=("${bridge_rel}" "-L${sdcc_runtime_lib}" "${target_stack_link_args[@]}")
    heap_injection_count=0
    skip_next_mf=0
    for argument in "${original_args[@]}"; do
      if [[ ${skip_next_mf} -eq 1 ]]; then
        skip_next_mf=0
        continue
      fi
      case "${argument}" in
        -DSTCXX*|-Ddouble=float) continue ;;
        -MF) skip_next_mf=1; continue ;;
        *.o)
          path="$(to_linux_path "${argument}")"
          link_args+=("${path%.o}.rel")
          ;;
        *.a)
          path="$(to_linux_path "${argument}")"
          if [[ "${path}" == "${heap_archive}" ]]; then
            link_args+=("${heap_rel}")
            heap_injection_count=$((heap_injection_count + 1))
          fi
          link_args+=("${path%.a}.lib")
          ;;
        -o)
          link_args+=(-o)
          ;;
        [A-Za-z]:[\\/]*|/*)
          link_args+=("$(to_linux_path "${argument}")")
          ;;
        *) link_args+=("${argument}") ;;
      esac
    done
    [[ ${heap_injection_count} -eq 1 ]] || {
      printf 'STCXX heap explicit link injection count is %s, expected 1\n' \
        "${heap_injection_count}" >&2
      exit 2
    }
    pre_slice_link_args=("${link_args[@]}")

    # Arduino directly links C objects from libraries that do not request
    # dot_a_linkage.  A generated data source can therefore contribute a
    # multi-megabyte CONST area even when only one exported array is used.
    # Slice only an object larger than this target's entire code budget, and
    # only after the helper proves a relocation-free, source-sized const-array
    # shape.  Any unfamiliar REL/source shape fails closed.
    code_size_values=()
    expect_code_size=0
    for argument in "${link_args[@]}"; do
      if [[ ${expect_code_size} -eq 1 ]]; then
        code_size_values+=("${argument}")
        expect_code_size=0
      elif [[ "${argument}" == --code-size ]]; then
        expect_code_size=1
      fi
    done
    [[ ${expect_code_size} -eq 0 && ${#code_size_values[@]} -eq 1 &&
       "${code_size_values[0]}" =~ ^[0-9]+$ && ${code_size_values[0]} -gt 0 ]] || {
      printf 'expected exactly one positive decimal --code-size for readonly CONST slicing\n' >&2
      exit 2
    }
    xram_size_values=()
    expect_xram_size=0
    for argument in "${link_args[@]}"; do
      if [[ ${expect_xram_size} -eq 1 ]]; then
        xram_size_values+=("${argument}")
        expect_xram_size=0
      elif [[ "${argument}" == --xram-size ]]; then
        expect_xram_size=1
      fi
    done
    [[ ${expect_xram_size} -eq 0 && ${#xram_size_values[@]} -eq 1 &&
       "${xram_size_values[0]}" =~ ^[0-9]+$ && ${xram_size_values[0]} -gt 0 ]] || {
      printf 'expected exactly one positive decimal --xram-size for C function splitting\n' >&2
      exit 2
    }
    readonly_slice_work="${work}/readonly-const-slices"
    mkdir -p "${readonly_slice_work}"
    readonly_slice_audit_list="${readonly_slice_work}/audit-files.txt"
    : >"${readonly_slice_audit_list}"
    readonly_roots="${readonly_slice_work}/direct-rel-link-closure.txt"
    : >"${readonly_roots}"
    for argument in "${link_args[@]}"; do
      [[ "${argument}" == *.rel && -f "${argument}" ]] || continue
      printf '%s\n' "${argument}" >>"${readonly_roots}"
    done

    declare -A readonly_slices=()
    while IFS= read -r candidate_rel; do
      mapfile -t const_sizes < <(
        awk '$1 == "A" && ($2 == "CONST" || $2 ~ /^CONST_D_/) { print $4 }' "${candidate_rel}"
      )
      [[ ${#const_sizes[@]} -gt 0 ]] || continue
      const_size=0
      for const_hex in "${const_sizes[@]}"; do
        [[ "${const_hex}" =~ ^[0-9A-F]+$ ]] || {
          printf 'invalid CONST size in %s: %s\n' "${candidate_rel}" "${const_hex}" >&2
          exit 2
        }
        const_size=$((const_size + 16#${const_hex}))
      done
      [[ ${const_size} -gt ${code_size_values[0]} ]] || continue
      candidate_hash="$(sha256sum "${candidate_rel}" | awk '{print $1}')"
      slice_stem="$(basename "${candidate_rel}").${candidate_hash:0:16}"
      sliced_rel="${readonly_slice_work}/${slice_stem}.rel"
      slice_audit="${readonly_slice_work}/${slice_stem}.audit.json"
      "${python}" "${readonly_const_slicer}" \
        --input "${candidate_rel}" \
        --root-list "${readonly_roots}" \
        --expect-input-sha256 "${candidate_hash}" \
        --output "${sliced_rel}" \
        --audit "${slice_audit}"
      printf '%s\n' "${slice_audit}" >>"${readonly_slice_audit_list}"
      readonly_slices["${candidate_rel}"]="${sliced_rel}"
    done <"${readonly_roots}"

    if [[ ${#readonly_slices[@]} -gt 0 ]]; then
      sliced_link_args=()
      for argument in "${link_args[@]}"; do
        if [[ -n "${readonly_slices[${argument}]:-}" ]]; then
          sliced_link_args+=("${readonly_slices[${argument}]}")
        else
          sliced_link_args+=("${argument}")
        fi
      done
      link_args=("${sliced_link_args[@]}")
    fi

    # Preserve normal archive extraction semantics for a directly-linked
    # Arduino C library only when one of its modules alone exceeds the entire
    # target CSEG or XRAM budget.  The helper starts from references outside
    # that library, computes the archive closure, and uses locked Clang source
    # ranges to split only oversized, function-only translation units.
    # File-scope data, assembly, unknown ranges, symbol leakage, or hash drift
    # are hard errors; no library or source filename is special-cased.
    declare -A actual_rel_by_original=()
    for argument in "${pre_slice_link_args[@]}"; do
      [[ "${argument}" == *.rel && -f "${argument}.stcxx-c.json" ]] || continue
      actual_rel_by_original["${argument}"]="${readonly_slices[${argument}]:-${argument}}"
    done
    declare -A oversized_function_groups=()
    for original_rel in "${!actual_rel_by_original[@]}"; do
      mapfile -t cseg_area_hex < <(
        awk '$1 == "A" && ($2 == "CSEG" || $2 ~ /^CSEG_F_/) { print $4 }' "${original_rel}"
      )
      mapfile -t xram_area_hex < <(
        awk '$1 == "A" && ($2 == "XSEG" || $2 == "XISEG") { print $4 }' "${original_rel}"
      )
      [[ ${#cseg_area_hex[@]} -gt 0 ]] || {
        printf 'invalid CSEG/XRAM area sizes for C function split candidate: %s\n' "${original_rel}" >&2
        exit 2
      }
      cseg_size=0
      for cseg_hex in "${cseg_area_hex[@]}"; do
        [[ "${cseg_hex}" =~ ^[0-9A-F]+$ ]] || {
          printf 'invalid CSEG area size for C function split candidate: %s\n' "${original_rel}" >&2
          exit 2
        }
        cseg_size=$((cseg_size + 16#${cseg_hex}))
      done
      xseg_size=0
      for xram_hex in "${xram_area_hex[@]}"; do
        [[ "${xram_hex}" =~ ^[0-9A-F]+$ ]] || {
          printf 'invalid XRAM area size for C function split candidate: %s\n' "${original_rel}" >&2
          exit 2
        }
        xseg_size=$((xseg_size + 16#${xram_hex}))
      done
      [[ ${cseg_size} -gt ${code_size_values[0]} ||
         ${xseg_size} -gt ${xram_size_values[0]} ]] || continue
      if [[ "${original_rel}" =~ ^(.*/libraries/[^/]+)/ ]]; then
        oversized_function_groups["${BASH_REMATCH[1]}"]=1
      else
        printf 'oversized function-split candidate is outside an Arduino library: %s\n' \
          "${original_rel}" >&2
        exit 2
      fi
    done

    function_split_work="${work}/c-function-split-archives"
    mkdir -p "${function_split_work}"
    function_split_audit_list="${function_split_work}/audit-files.txt"
    : >"${function_split_audit_list}"
    for group in "${!oversized_function_groups[@]}"; do
      group_hash="$(printf '%s' "${group}" | sha256sum | awk '{print $1}')"
      group_work="${function_split_work}/${group_hash:0:16}"
      group_archive="${group_work}/selected.lib"
      group_audit="${group_work}/audit.json"
      mkdir -p "${group_work}"
      builder_args=(
        "${python}" "${function_archive_builder}"
        --code-limit "${code_size_values[0]}"
        --xram-limit "${xram_size_values[0]}"
        --splitter "${function_tu_splitter}"
        --sdar "${sdar}"
        --work-dir "${group_work}"
        --output-archive "${group_archive}"
        --audit "${group_audit}"
      )
      declare -A group_actual_rels=()
      for original_rel in "${!actual_rel_by_original[@]}"; do
        [[ "${original_rel}" == "${group}/"* ]] || continue
        actual_rel="${actual_rel_by_original[${original_rel}]}"
        group_actual_rels["${actual_rel}"]=1
        builder_args+=(--member "${original_rel}.stcxx-c.json" "${actual_rel}")
      done
      for argument in "${link_args[@]}"; do
        if [[ "${argument}" == *.rel && -f "${argument}" &&
              -z "${group_actual_rels[${argument}]:-}" ]]; then
          builder_args+=(--root-rel "${argument}")
        elif [[ "${argument}" == *.lib && -f "${argument}" ]]; then
          builder_args+=(--root-archive "${argument}")
        fi
      done
      "${builder_args[@]}"
      printf '%s\n' "${group_audit}" >>"${function_split_audit_list}"

      grouped_link_args=()
      inserted_group_archive=0
      for argument in "${link_args[@]}"; do
        if [[ -n "${group_actual_rels[${argument}]:-}" ]]; then
          if [[ ${inserted_group_archive} -eq 0 ]]; then
            grouped_link_args+=("${group_archive}")
            inserted_group_archive=1
          fi
        else
          grouped_link_args+=("${argument}")
        fi
      done
      [[ ${inserted_group_archive} -eq 1 ]] || {
        printf 'function-split archive group did not replace a direct REL: %s\n' "${group}" >&2
        exit 2
      }
      link_args=("${grouped_link_args[@]}")
    done
    # Ordinary native libraries may fit individually while the complete sketch
    # exceeds Flash. Trim their proven function closures at every capacity.
    # Keep each resulting object directly linked, including unreferenced or
    # unsupported objects, so this optimization cannot drop data/startup code.
    declare -A direct_trim_metadata=()
    for original_rel in "${!actual_rel_by_original[@]}"; do
      [[ "${original_rel}" =~ /libraries/[^/]+/ ]] || continue
      actual_rel="${actual_rel_by_original[${original_rel}]}"
      for argument in "${link_args[@]}"; do
        [[ "${argument}" == "${actual_rel}" ]] || continue
        direct_trim_metadata["${actual_rel}"]="${original_rel}.stcxx-c.json"
      done
    done
    if [[ ${#direct_trim_metadata[@]} -gt 0 ]]; then
      direct_trim_work="${function_split_work}/direct"
      mkdir -p "${direct_trim_work}"
      direct_trim_list="${direct_trim_work}/replacements.txt"
      direct_trim_audit="${direct_trim_work}/audit.json"
      direct_trim_args=("${python}" "${function_archive_builder}"
        --code-limit "${code_size_values[0]}" --xram-limit "${xram_size_values[0]}"
        --splitter "${function_tu_splitter}" --sdar "${sdar}"
        --work-dir "${direct_trim_work}" --output-rel-list "${direct_trim_list}"
        --audit "${direct_trim_audit}")
      for argument in "${link_args[@]}"; do
        if [[ -n "${direct_trim_metadata[${argument}]:-}" ]]; then
          direct_trim_args+=(--member "${direct_trim_metadata[${argument}]}" "${argument}")
        elif [[ "${argument}" == *.rel && -f "${argument}" ]]; then
          direct_trim_args+=(--root-rel "${argument}")
        elif [[ "${argument}" == *.lib && -f "${argument}" ]]; then
          direct_trim_args+=(--root-archive "${argument}")
        fi
      done
      "${direct_trim_args[@]}"
      mapfile -t direct_trim_pairs <"${direct_trim_list}"
      [[ ${#direct_trim_pairs[@]} -eq $((${#direct_trim_metadata[@]} * 2)) ]] || {
        printf 'direct function replacement list has an invalid length\n' >&2; exit 2;
      }
      declare -A direct_trim_replacements=()
      for ((index=0; index<${#direct_trim_pairs[@]}; index+=2)); do
        original_rel="${direct_trim_pairs[index]}"
        actual_rel="${direct_trim_pairs[index+1]}"
        [[ -n "${direct_trim_metadata[${original_rel}]:-}" && -f "${actual_rel}" &&
           -z "${direct_trim_replacements[${original_rel}]:-}" ]] || {
          printf 'invalid or duplicate direct function replacement\n' >&2; exit 2;
        }
        direct_trim_replacements["${original_rel}"]="${actual_rel}"
      done
      trimmed_link_args=()
      for argument in "${link_args[@]}"; do
        trimmed_link_args+=("${direct_trim_replacements[${argument}]:-${argument}}")
      done
      link_args=("${trimmed_link_args[@]}")
      printf '%s\n' "${direct_trim_audit}" >>"${function_split_audit_list}"
    fi
    # A successful driver invocation must create this build's output, never
    # inherit a stale HEX from an earlier failed/misdirected link.
    link_log="${work}/sdcc-link.log"
    link_args_file="${work}/sdcc-link-arguments.txt"
    printf '%s\n' "${link_args[@]}" >"${link_args_file}"
    map_file="${output_hex%.hex}.map"
    run_sdcc_link() {
      rm -f -- "${output_hex}" "${output_hex%.hex}.mem" "${map_file}" \
        "${bridge_rst}"
      "${sdcc}" "${link_args[@]}" 2>&1 | tee "${link_log}" >&2
      test -s "${output_hex}"
      test -s "${map_file}"
      test -s "${bridge_rst}"
    }
    run_sdcc_link

    set +e
    "${python}" "${member_function_aligner}" verify \
      --audit-json "${member_function_alignment_audit}" \
      --relocated-listing "${bridge_rst}" \
      --target-profile "${sdcc_target}"
    alignment_verify_status=$?
    set -e
    if [[ ${alignment_verify_status} -eq 3 ]]; then
      cp -f -- "${member_function_alignment_audit}" \
        "${member_function_alignment_prior_audit}"
      cp -f -- "${bridge_asm}" "${bridge_prior_even_asm}"
      cp -f -- "${bridge_rel}" "${bridge_prior_even_rel}"
      cp -f -- "${bridge_lst}" "${bridge_prior_even_lst}"
      cp -f -- "${bridge_rst}" "${bridge_prior_even_rst}"
      "${python}" "${member_function_aligner}" align \
        --input-assembly "${bridge_raw_asm}" \
        --output-assembly "${bridge_asm}" \
        --adapter-audit "${work}/audit.json" \
        --target-profile "${sdcc_target}" \
        --local-parity odd \
        --audit-json "${member_function_alignment_audit}"
      rm -f -- "${bridge_rel}" "${bridge_lst}" "${bridge_rst}"
      "${bridge_assembler}" -plosgffw "${bridge_rel}" "${bridge_asm}" \
        2>&1 | tee "${bridge_assembly_log}"
      test -s "${bridge_rel}"
      test -s "${bridge_lst}"
      run_sdcc_link
      "${python}" "${member_function_aligner}" verify \
        --audit-json "${member_function_alignment_audit}" \
        --relocated-listing "${bridge_rst}" \
        --target-profile "${sdcc_target}"
    elif [[ ${alignment_verify_status} -ne 0 ]]; then
      printf 'member-function alignment relocation audit failed: %s\n' \
        "${alignment_verify_status}" >&2
      exit "${alignment_verify_status}"
    fi

    "${python}" "${function_link_map_auditor}" \
      --audit-list "${function_split_audit_list}" \
      --map "${map_file}" \
      --link-arguments "${link_args_file}"
    "${python}" "${native_storage}" --ir "${work}/optimized.ll" \
      --verify "${work}/native-storage.json" --map "${map_file}"

    heap_link_audit="${work}/heap-link-audit.json"
    "${python}" - "${heap_link_audit}" "${link_log}" "${link_args_file}" \
      "${map_file}" "${heap_rel}" "${heap_state_rel}" "${heap_archive}" \
      "${heap_archive_members_file}" "${aslink_map_symbols}" \
      "${sdcc_target}" "${mcs251_iram_size}" "${mcs251_stack_loc}" \
      "${mcs251_stack_size}" <<'PY'
import hashlib
import importlib.util
import json
import re
import sys
from pathlib import Path

if len(sys.argv) != 14:
    raise SystemExit("heap-link audit argument vector differs")

path_arguments = list(map(Path, sys.argv[1:10]))
(
    audit_path,
    log_path,
    arguments_path,
    map_path,
    heap_rel_path,
    heap_state_rel_path,
    core_archive_path,
    archive_members_path,
    aslink_map_symbols_path,
) = path_arguments
(
    target_profile,
    mcs251_iram_size,
    mcs251_stack_loc,
    mcs251_stack_size,
) = sys.argv[10:14]

helper_spec = importlib.util.spec_from_file_location(
    "aslink_map_symbols", aslink_map_symbols_path
)
if helper_spec is None or helper_spec.loader is None:
    raise SystemExit("cannot load locked ASlink map-symbol helper")
aslink = importlib.util.module_from_spec(helper_spec)
helper_spec.loader.exec_module(aslink)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


link_log = log_path.read_text(encoding="utf-8", errors="replace")
duplicate_public_symbols = [
    line.strip()
    for line in link_log.splitlines()
    if "Definition of public symbol" in line or "found more than once" in line
]
if duplicate_public_symbols:
    raise SystemExit(
        "duplicate public symbol warning survived explicit STCXX heap link: "
        + repr(duplicate_public_symbols)
    )

arguments = arguments_path.read_text(encoding="utf-8").splitlines()
if target_profile == "mcs251":
    expected_stack_arguments = [
        "--iram-size", mcs251_iram_size,
        "--stack-loc", mcs251_stack_loc,
        "--stack-size", mcs251_stack_size,
    ]
    if (not all(re.fullmatch(r"0x[0-9A-Fa-f]+", value) for value in (
            mcs251_iram_size, mcs251_stack_loc, mcs251_stack_size))
            or sum(
                arguments[index:index + len(expected_stack_arguments)]
                == expected_stack_arguments
                for index in range(
                    len(arguments) - len(expected_stack_arguments) + 1
                )
            ) != 1
            or any(arguments.count(flag) != 1 for flag in (
                "--iram-size", "--stack-loc", "--stack-size"
            ))):
        raise SystemExit(
            "final MCS251 link arguments do not contain one exact extended-stack tuple"
        )
else:
    raise SystemExit(f"unexpected STCXX link target profile: {target_profile}")
heap_rel = str(heap_rel_path)
core_lib = str(core_archive_path.with_suffix(".lib"))
if arguments.count(heap_rel) != 1 or arguments.count(core_lib) != 1:
    raise SystemExit("STCXX heap/core archive link arguments are not unique")
if arguments.index(heap_rel) >= arguments.index(core_lib):
    raise SystemExit("STCXX heap object is not linked before core.lib")

heap_payload = heap_rel_path.read_text(encoding="ascii")
heap_size_symbol = "___sdcc_heap_size32"
opposite_heap_size_symbol = "___sdcc_heap_size"
heap_xseg = re.findall(
    r"^A XSEG size ([0-9A-Fa-f]+) flags ", heap_payload, re.MULTILINE
)
if len(heap_xseg) != 1:
    raise SystemExit("STCXX heap object has no unique XSEG allocation")
heap_bytes = int(heap_xseg[0], 16)
heap_state_payload = heap_state_rel_path.read_text(encoding="ascii")
heap_state_xseg = re.findall(
    r"^A XSEG size ([0-9A-Fa-f]+) flags ",
    heap_state_payload,
    re.MULTILINE,
)
if len(heap_state_xseg) != 1 or int(heap_state_xseg[0], 16) != 8:
    raise SystemExit("STCXX telemetry-state object is not exactly 8 XSEG bytes")
state_heap_provider_counts = {
    symbol: len(re.findall(
        rf"^S {re.escape(symbol)} Def[0-9A-Fa-f]+$",
        heap_state_payload,
        re.MULTILINE,
    ))
    for symbol in ("___sdcc_heap", "___sdcc_heap_size", "___sdcc_heap_size32", "___stcxx_heap_init")
}
if any(state_heap_provider_counts.values()):
    raise SystemExit("STCXX telemetry-state object provides a heap symbol")
state_symbols = (
    "___stcxx_heap_telemetry_ready_state",
    "___stcxx_heap_telemetry_valid_state",
    "___stcxx_heap_initial_total_free_state",
    "___stcxx_heap_minimum_total_free_state",
    "___stcxx_heap_minimum_largest_free_state",
)
state_object_providers = {
    symbol: len(re.findall(
        rf"^S {re.escape(symbol)} Def[0-9A-Fa-f]+$",
        heap_state_payload,
        re.MULTILINE,
    ))
    for symbol in state_symbols
}
if any(count != 1 for count in state_object_providers.values()):
    raise SystemExit(
        "STCXX telemetry-state object does not define each full state symbol "
        f"exactly once: {state_object_providers}"
    )
archive_members = archive_members_path.read_text(encoding="utf-8").splitlines()
archive_heap_members = archive_members.count("stcxx_heap.c.rel")
if archive_heap_members != 0:
    raise SystemExit("STCXX heap object remains in core archive")
archive_state_members = archive_members.count("stcxx_heap_state.c.rel")
if archive_state_members != 1:
    raise SystemExit("STCXX telemetry-state archive member is not unique")

link_map = map_path.read_text(encoding="utf-8", errors="replace")
if re.search(
    rf"^[A-Z]:[ \t]+[0-9A-Fa-f]+[ \t]+{re.escape(opposite_heap_size_symbol)}(?:[ \t]+[^\r\n]*)?$",
    link_map, re.MULTILINE,
):
    raise SystemExit(f"final map contains opposite-ABI heap-size provider: {opposite_heap_size_symbol}")
default_heap_members = len(re.findall(
    r"\[\s*_heap\.rel\s*\]", link_map
))
archived_custom_heap_members = len(re.findall(
    r"\[\s*stcxx_heap\.c\.rel\s*\]", link_map
))
linked_state_members = len(re.findall(
    r"\[\s*stcxx_heap_state\.c\.rel\s*\]", link_map
))
explicit_heap_objects = link_map.count(str(heap_rel_path))


def provider_count(symbol: str) -> int:
    return len(re.findall(
        rf"^[A-Z]:\s+[0-9A-Fa-f]+\s+{re.escape(symbol)}\s+stcxx_heap\s*$",
        link_map,
        re.MULTILINE,
    ))


providers = {
    "___sdcc_heap": provider_count("___sdcc_heap"),
    heap_size_symbol: provider_count(heap_size_symbol),
    "___stcxx_heap_init": provider_count("___stcxx_heap_init"),
}
try:
    state_map_displays = aslink.unique_aslink_global_displays(state_symbols)
except ValueError as error:
    raise SystemExit(str(error)) from error
state_providers = {
    symbol: aslink.provider_count(
        link_map, symbol, "stcxx_heap_state", state_map_displays
    )
    for symbol in state_symbols
}
xseg_match = re.search(
    r"^C:\s+([0-9A-Fa-f]+)\s+l_XSEG\s*$", link_map, re.MULTILINE
)
if (
    default_heap_members != 0
    or archived_custom_heap_members != 0
    or linked_state_members != 1
    or explicit_heap_objects != 1
    or any(count != 1 for count in providers.values())
    or any(count != 1 for count in state_providers.values())
    or xseg_match is None
    or int(xseg_match.group(1), 16) < heap_bytes + 8
):
    raise SystemExit(
        "final map does not prove one explicit STCXX heap and no default heap: "
        f"default={default_heap_members}, archived={archived_custom_heap_members}, "
        f"explicit={explicit_heap_objects}, state={linked_state_members}, "
        f"providers={providers}, state_providers={state_providers}"
    )

result = {
    "schema_version": 1,
    "outcome": "pass",
    "link_arguments": {
        "path": str(arguments_path.resolve()),
        "sha256": digest(arguments_path),
        "argument_count": len(arguments),
        "target_profile": target_profile,
        "mcs251_extended_stack": expected_stack_arguments,
    },
    "heap_object": {
        "path": str(heap_rel_path.resolve()),
        "sha256": digest(heap_rel_path),
        "xseg_bytes": heap_bytes,
        "explicit_link_argument_count": arguments.count(heap_rel),
        "map_file_occurrence_count": explicit_heap_objects,
    },
    "telemetry_state": {
        "path": str(heap_state_rel_path.resolve()),
        "sha256": digest(heap_state_rel_path),
        "xseg_bytes": int(heap_state_xseg[0], 16),
        "archive_member_count": archive_state_members,
        "map_file_occurrence_count": linked_state_members,
        "providers": state_providers,
        "object_providers": state_object_providers,
        "map_displays": state_map_displays,
        "heap_provider_counts": state_heap_provider_counts,
        "provides_heap_symbols": any(state_heap_provider_counts.values()),
    },
    "core_archive": {
        "path": str(core_archive_path.resolve()),
        "sha256": digest(core_archive_path),
        "members_sha256": digest(archive_members_path),
        "stcxx_heap_member_count": archive_heap_members,
        "stcxx_heap_state_member_count": archive_state_members,
        "linked_after_heap_object": True,
    },
    "link_log": {
        "path": str(log_path.resolve()),
        "sha256": digest(log_path),
        "duplicate_public_symbol_warning_count": len(duplicate_public_symbols),
    },
    "map": {
        "path": str(map_path.resolve()),
        "sha256": digest(map_path),
        "default_heap_member_count": default_heap_members,
        "archived_custom_heap_member_count": archived_custom_heap_members,
        "providers": providers,
        "xseg_bytes": int(xseg_match.group(1), 16),
    },
}
audit_path.write_text(
    json.dumps(result, indent=2) + "\n", encoding="utf-8", newline="\n"
)
PY

    "${python}" - "${work}/manifest.json" "${output_hex}" "${lock_file}" \
      "${work}/audit.json" "${warning_audit}" "${heap_link_audit}" \
      "${member_function_alignment_audit}" \
      "${c_abi_preserve_file}" "${c_abi_root_audit}" \
      "${discovery_root_audit}" "${work}/cpp-archive-selection-audit.json" \
      "${root_collector}" "${archive_selector}" \
      "${member_function_aligner}" \
      "${readonly_const_slicer}" "${function_tu_splitter}" \
      "${function_archive_builder}" "${function_link_map_auditor}" \
      "${readonly_slice_audit_list}" \
      "${function_split_audit_list}" \
      "${work}/all-candidates-linked.bc" "${work}/linked.bc" \
      "${work}/linked.ll" "${work}/optimized.bc" "${work}/optimized.ll" \
      "${work}/raw.c" "${work}/adapted.c" \
      "${bridge_raw_asm}" "${bridge_asm}" "${bridge_rel}" \
      "${bridge_lst}" "${bridge_rst}" \
      "${sdcc_target}" "${target_triple}" "${data_layout}" "${abi_symbol}" \
      "${mcs251_iram_size}" "${mcs251_stack_loc}" "${mcs251_stack_size}" \
      "${clock_hz}" \
      -- "${bitcode_files[@]}" <<'PY'
import hashlib
import json
import re
import sys
from pathlib import Path

(
    manifest_path,
    firmware,
    lock_path,
    audit_path,
    warning_audit_path,
    heap_link_audit_path,
    member_function_alignment_audit_path,
    c_abi_path,
    c_abi_root_audit_path,
    discovery_root_audit_path,
    archive_selection_audit_path,
    root_collector_path,
    archive_selector_path,
    member_function_aligner_path,
    readonly_const_slicer_path,
    function_tu_splitter_path,
    function_archive_builder_path,
    function_link_map_auditor_path,
    readonly_slice_audit_list_path,
    function_split_audit_list_path,
    all_candidates_bc_path,
    selected_bc_path,
    selected_ir_path,
    optimized_bc_path,
    optimized_ir_path,
    raw_c_path,
    adapted_c_path,
    bridge_raw_asm_path,
    bridge_asm_path,
    bridge_rel_path,
    bridge_lst_path,
    bridge_rst_path,
    target_profile,
    target_triple,
    data_layout,
    abi_identity_symbol,
    mcs251_iram_size,
    mcs251_stack_loc,
    mcs251_stack_size,
    build_f_cpu_hz,
    separator,
    *bitcode,
) = sys.argv[1:]
if separator != "--":
    raise SystemExit("manifest argument separator is missing")
build_f_cpu_hz = int(build_f_cpu_hz)
def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))
SDCC_SYMNAME_MAX = 256
ASXXXX_NCPS = 256
SAFE_C_SYMBOL = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")
def alignment_function_records(functions, directive, label):
    expected_keys = {
        "asxxxx_ncps", "c_symbols", "llvm_symbols",
        "member_function_symbols", "records", "sdcc_symname_max",
    }
    if (not isinstance(functions, dict) or set(functions) != expected_keys
            or type(functions.get("sdcc_symname_max")) is not int
            or functions.get("sdcc_symname_max") != SDCC_SYMNAME_MAX
            or type(functions.get("asxxxx_ncps")) is not int
            or functions.get("asxxxx_ncps") != ASXXXX_NCPS):
        raise SystemExit(f"{label} function symbol contract differs")
    c_symbols = functions.get("c_symbols")
    if (not isinstance(c_symbols, list)
            or any(not isinstance(symbol, str)
                   or SAFE_C_SYMBOL.fullmatch(symbol) is None
                   for symbol in c_symbols)
            or c_symbols != sorted(c_symbols)
            or len(c_symbols) != len(set(c_symbols))):
        raise SystemExit(f"{label} C symbol set differs")
    mappings = [
        {
            "assembly_label": "_" + symbol[:SDCC_SYMNAME_MAX],
            "asxxxx_symbol": (
                "_" + symbol[:SDCC_SYMNAME_MAX]
            )[:ASXXXX_NCPS - 1],
            "c_symbol": symbol,
            "directive": directive,
        }
        for symbol in c_symbols
    ]
    for key in ("assembly_label", "asxxxx_symbol"):
        values = [record[key] for record in mappings]
        if len(values) != len(set(values)):
            raise SystemExit(f"{label} has a truncated {key} collision")
    if functions.get("records") != mappings:
        raise SystemExit(f"{label} function mapping records differ")
    return c_symbols, mappings
def validate_relocation_records(records, mappings, expected_even, label):
    expected_keys = {
        "address", "address_hex", "assembly_label", "asxxxx_symbol",
        "c_symbol", "even",
    }
    if not isinstance(records, list) or len(records) != len(mappings):
        raise SystemExit(f"{label} record count differs")
    for record, mapping in zip(records, mappings):
        address = record.get("address") if isinstance(record, dict) else None
        if (not isinstance(record, dict) or set(record) != expected_keys
                or type(address) is not int
                or type(record.get("even")) is not bool
                or record.get("even") is not expected_even
                or address % 2 != (0 if expected_even else 1)
                or record.get("address_hex") != f"{address:06X}"
                or record.get("assembly_label") != mapping["assembly_label"]
                or record.get("asxxxx_symbol") != mapping["asxxxx_symbol"]
                or record.get("c_symbol") != mapping["c_symbol"]):
            raise SystemExit(f"{label} differs")
def load_audit_list(path, label):
    paths = [Path(item) for item in Path(path).read_text(encoding="utf-8").splitlines() if item]
    if len(paths) != len(set(paths)):
        raise SystemExit(f"duplicate {label} audit path")
    result = []
    for audit_path in paths:
        audit = load_json(audit_path)
        outcome = audit.get("outcome")
        if outcome is not None and str(outcome).lower() != "pass":
            raise SystemExit(f"{label} audit did not pass: {audit_path}")
        result.append({
            "path": str(audit_path.resolve()),
            "sha256": digest(audit_path),
            "audit": audit,
        })
    return result
archive_selection = load_json(archive_selection_audit_path)
member_alignment = load_json(member_function_alignment_audit_path)
alignment_directory = Path(member_function_alignment_audit_path).parent
prior_alignment_audit_path = alignment_directory / "member-function-alignment-prior-audit.json"
prior_even_paths = {
    "aligned_assembly_sha256": alignment_directory / "cpp-bridge.prior-even.asm",
    "sdcc_bridge_rel_sha256": alignment_directory / "cpp-bridge.prior-even.rel",
    "assembly_listing_sha256": alignment_directory / "cpp-bridge.prior-even.lst",
    "relocated_listing_sha256": alignment_directory / "cpp-bridge.prior-even.rst",
}
member_alignment_relocation = member_alignment.get("relocation_verification")
member_alignment_assembly = member_alignment.get("assembly")
member_alignment_functions = member_alignment.get("function_alignment")
member_alignment_tool = member_alignment.get("tool")
member_alignment_adapter = member_alignment.get("adapter_audit")
if (type(member_alignment.get("schema_version")) is not int
        or member_alignment.get("schema_version") != 2
        or member_alignment.get("outcome") != "pass"
        or member_alignment.get("phase") != "verified"
        or member_alignment.get("target_profile") != target_profile
        or member_alignment.get("alignment_bytes") != 2
        or not isinstance(member_alignment_relocation, dict)
        or member_alignment_relocation.get("outcome") != "pass"
        or not isinstance(member_alignment_assembly, dict)
        or type(member_alignment_assembly.get("mutation_count")) is not int
        or not isinstance(member_alignment_functions, dict)
        or not isinstance(member_alignment_tool, dict)
        or not isinstance(member_alignment_adapter, dict)):
    raise SystemExit("member-function alignment audit is not a final exact PASS")
member_alignment_c_symbols, member_alignment_function_records = (
    alignment_function_records(
        member_alignment_functions,
        member_alignment.get("directive"),
        "member-function alignment audit",
    )
)
member_alignment_realignment = member_alignment.get("realignment")
prior_member_alignment = None
prior_bridge_artifacts = {}
if member_alignment_realignment is not None:
    if (set(member_alignment_realignment) != {
            "from_local_parity", "prior_audit_sha256", "reason"}
            or member_alignment_realignment.get("from_local_parity") != "even"
            or member_alignment_realignment.get("reason")
            != "uniform-odd-final-addresses"
            or member_alignment.get("directive") != ".odd"
            or member_alignment_assembly.get("local_parity") != "odd"):
        raise SystemExit("member-function realignment contract differs")
    if not prior_alignment_audit_path.is_file() or any(
            not path.is_file() for path in prior_even_paths.values()):
        raise SystemExit("member-function prior realignment artifacts are incomplete")
    if (member_alignment_realignment.get("prior_audit_sha256")
            != digest(prior_alignment_audit_path)):
        raise SystemExit("member-function prior realignment audit hash differs")
    prior_member_alignment = load_json(prior_alignment_audit_path)
    prior_assembly = prior_member_alignment.get("assembly")
    prior_relocation = prior_member_alignment.get("relocation_verification")
    prior_functions = prior_member_alignment.get("function_alignment")
    if (set(prior_member_alignment) != {
            "adapter_audit", "alignment_bytes", "assembly", "directive",
            "function_alignment", "outcome", "phase", "policy",
            "relocation_verification", "schema_version", "target_profile", "tool"}
            or type(prior_member_alignment.get("schema_version")) is not int
            or prior_member_alignment.get("schema_version") != 2
            or prior_member_alignment.get("outcome") != "realign_required"
            or prior_member_alignment.get("phase") != "realign_required"
            or prior_member_alignment.get("directive") != ".even"
            or prior_member_alignment.get("target_profile") != target_profile
            or prior_member_alignment.get("alignment_bytes") != 2
            or not isinstance(prior_assembly, dict)
            or type(prior_assembly.get("mutation_count")) is not int
            or prior_assembly.get("local_parity") != "even"
            or prior_assembly.get("input_sha256") != digest(bridge_raw_asm_path)
            or prior_assembly.get("output_sha256")
            != digest(prior_even_paths["aligned_assembly_sha256"])
            or not isinstance(prior_relocation, dict)
            or prior_relocation.get("outcome") != "realign_required"
            or prior_relocation.get("recommended_local_parity") != "odd"
            or prior_relocation.get("relocated_listing_sha256")
            != digest(prior_even_paths["relocated_listing_sha256"])
            or not isinstance(prior_functions, dict)
            or prior_functions.get("c_symbols")
            != member_alignment_functions.get("c_symbols")):
        raise SystemExit("member-function prior realignment audit differs")
    prior_c_symbols, prior_function_records = alignment_function_records(
        prior_functions, ".even", "prior member-function alignment audit"
    )
    if prior_c_symbols != member_alignment_c_symbols:
        raise SystemExit("prior/final member-function symbols differ")
    prior_records = prior_relocation.get("records")
    if (not prior_function_records
            or prior_relocation.get("checked_symbol_count")
            != len(prior_function_records)):
        raise SystemExit("member-function prior relocated addresses are not uniformly odd")
    validate_relocation_records(
        prior_records, prior_function_records, False,
        "member-function prior relocated addresses",
    )
    prior_bridge_artifacts = {
        "member_function_alignment_prior_audit_sha256": digest(
            prior_alignment_audit_path
        ),
        **{f"prior_even_{key}": digest(path) for key, path in prior_even_paths.items()},
    }
else:
    if (member_alignment.get("directive") != ".even"
            or member_alignment_assembly.get("local_parity") != "even"
            or any(
                path.exists()
                for path in [prior_alignment_audit_path, *prior_even_paths.values()]
            )):
        raise SystemExit("unexpected member-function prior realignment artifacts")
member_alignment_records = member_alignment_relocation.get("records")
if (not isinstance(member_alignment_records, list)
        or not isinstance(member_alignment_c_symbols, list)
        or member_alignment_relocation.get("checked_symbol_count")
        != len(member_alignment_c_symbols)
        or len(member_alignment_records) != len(member_alignment_c_symbols)):
    raise SystemExit("member-function relocated address evidence differs")
validate_relocation_records(
    member_alignment_records, member_alignment_function_records, True,
    "member-function relocated address evidence",
)
if (member_alignment_tool.get("path")
        != str(Path(member_function_aligner_path).resolve())
        or member_alignment_tool.get("sha256")
        != digest(member_function_aligner_path)
        or member_alignment_adapter.get("path")
        != str(Path(audit_path).resolve())
        or member_alignment_adapter.get("sha256") != digest(audit_path)
        or member_alignment_assembly.get("input_path")
        != str(Path(bridge_raw_asm_path).resolve())
        or member_alignment_assembly.get("input_sha256")
        != digest(bridge_raw_asm_path)
        or member_alignment_assembly.get("output_path")
        != str(Path(bridge_asm_path).resolve())
        or member_alignment_assembly.get("output_sha256")
        != digest(bridge_asm_path)
        or member_alignment_relocation.get("relocated_listing")
        != str(Path(bridge_rst_path).resolve())
        or member_alignment_relocation.get("relocated_listing_sha256")
        != digest(bridge_rst_path)):
    raise SystemExit("member-function alignment provenance differs")
readonly_slice_audits = load_audit_list(
    readonly_slice_audit_list_path, "readonly CONST slice"
)
function_split_audits = load_audit_list(
    function_split_audit_list_path, "C function split"
)
direct_bitcode = {
    str(Path(item["path"]).resolve())
    for item in archive_selection["direct_inputs"]
}
candidate_by_bitcode = {
    str(Path(item["bitcode"]).resolve()): item
    for item in archive_selection["candidates"]
}
modules = []
for path in bitcode:
    meta_path = Path(path.replace(".stcxx.bc", ".stcxx.json"))
    metadata = load_json(meta_path)
    resolved = str(Path(path).resolve())
    if resolved in direct_bitcode:
        metadata["link_disposition"] = "direct"
        metadata["selected_for_bridge"] = True
    else:
        candidate = candidate_by_bitcode.get(resolved)
        if candidate is None:
            raise SystemExit(f"module is absent from archive-selection audit: {path}")
        metadata["link_disposition"] = (
            "selected-archive-member" if candidate["selected"]
            else "discarded-archive-candidate"
        )
        metadata["selected_for_bridge"] = candidate["selected"]
        metadata["archive"] = candidate["archive"]
        metadata["archive_member"] = candidate["member"]
        metadata["selection_reason"] = candidate["selection_reason"]
    modules.append(metadata)
qualification = (
    f"EXPERIMENTAL_{target_profile.upper()}_{build_f_cpu_hz // 1000000}MHZ_ARDUINO_CLI_COMPILE_LINK"
)
runtime_qualification = "SEPARATE_EXACT_QEMU_VARIANT_MATRIX_GATE"
stack_identity = None
if target_profile == "mcs251":
    stack_identity = {
        "iram_size": mcs251_iram_size,
        "stack_loc": mcs251_stack_loc,
        "stack_size": mcs251_stack_size,
    }
result = {
    "schema_version": 2,
    "outcome": "pass",
    "qualification": qualification,
    "runtime_qualification": runtime_qualification,
    "target": {
        "profile": target_profile,
        "build_f_cpu_hz": build_f_cpu_hz,
        "target_triple": target_triple,
        "data_layout": data_layout,
        "abi_identity_symbol": abi_identity_symbol,
        "memory_model": "large",
        "calling_model": "stack-auto",
        "mcs251_extended_stack": stack_identity,
    },
    "firmware": str(Path(firmware).resolve()),
    "firmware_sha256": digest(firmware),
    "lock_sha256": digest(lock_path),
    "audit_sha256": digest(audit_path),
    "audit": load_json(audit_path),
    "sdcc_warning_audit_sha256": digest(warning_audit_path),
    "sdcc_warning_audit": json.loads(
        Path(warning_audit_path).read_text(encoding="utf-8")
    ),
    "heap_link_audit_sha256": digest(heap_link_audit_path),
    "heap_link_audit": json.loads(
        Path(heap_link_audit_path).read_text(encoding="utf-8")
    ),
    "member_function_alignment_audit_sha256": digest(
        member_function_alignment_audit_path
    ),
    "member_function_alignment_audit": member_alignment,
    "c_abi_preserve_sha256": digest(c_abi_path),
    "c_abi_preserved_symbols": Path(c_abi_path).read_text(
        encoding="utf-8"
    ).splitlines(),
    "c_abi_root_collector": {
        "path": str(Path(root_collector_path).resolve()),
        "sha256": digest(root_collector_path),
    },
    "c_abi_root_discovery_audit_sha256": digest(discovery_root_audit_path),
    "c_abi_root_discovery_audit": load_json(discovery_root_audit_path),
    "c_abi_root_audit_sha256": digest(c_abi_root_audit_path),
    "c_abi_root_audit": load_json(c_abi_root_audit_path),
    "cpp_archive_selector": {
        "path": str(Path(archive_selector_path).resolve()),
        "sha256": digest(archive_selector_path),
    },
    "member_function_aligner": {
        "path": str(Path(member_function_aligner_path).resolve()),
        "sha256": digest(member_function_aligner_path),
    },
    "cpp_archive_selection_audit_sha256": digest(archive_selection_audit_path),
    "cpp_archive_selection_audit": archive_selection,
    "native_c_size_reduction": {
        "readonly_const_slicer": {
            "path": str(Path(readonly_const_slicer_path).resolve()),
            "sha256": digest(readonly_const_slicer_path),
        },
        "function_tu_splitter": {
            "path": str(Path(function_tu_splitter_path).resolve()),
            "sha256": digest(function_tu_splitter_path),
        },
        "function_archive_builder": {
            "path": str(Path(function_archive_builder_path).resolve()),
            "sha256": digest(function_archive_builder_path),
        },
        "function_link_map_auditor": {
            "path": str(Path(function_link_map_auditor_path).resolve()),
            "sha256": digest(function_link_map_auditor_path),
        },
        "readonly_const_slices": {
            "outcome": "PASS",
            "audit_count": len(readonly_slice_audits),
            "input_const_bytes": sum(
                item["audit"]["input"]["const_size"] for item in readonly_slice_audits
            ),
            "output_const_bytes": sum(
                item["audit"]["output"]["const_size"] for item in readonly_slice_audits
            ),
            "selected_definition_count": sum(
                len(item["audit"]["selected"]) for item in readonly_slice_audits
            ),
            "discarded_definition_count": sum(
                len(item["audit"]["discarded"]) for item in readonly_slice_audits
            ),
            "audits": readonly_slice_audits,
        },
        "function_split_archives": {
            "outcome": "PASS",
            "audit_count": len(function_split_audits),
            "selected_archive_member_count": sum(
                item["audit"]["selected_member_count"] for item in function_split_audits
            ),
            "selected_direct_object_count": sum(
                item["audit"].get("selected_direct_object_count", 0) for item in function_split_audits
            ),
            "discarded_input_member_count": sum(
                item["audit"]["discarded_input_member_count"] for item in function_split_audits
            ),
            "selected_split_candidate_count": sum(
                item["audit"]["selected_split_candidate_count"] for item in function_split_audits
            ),
            "discarded_split_candidate_count": sum(
                item["audit"]["discarded_split_candidate_count"] for item in function_split_audits
            ),
            "audits": function_split_audits,
        },
    },
    "bridge_artifacts": {
        "all_candidates_linked_bitcode_sha256": digest(all_candidates_bc_path),
        "selected_linked_bitcode_sha256": digest(selected_bc_path),
        "selected_linked_ir_sha256": digest(selected_ir_path),
        "optimized_bitcode_sha256": digest(optimized_bc_path),
        "optimized_ir_sha256": digest(optimized_ir_path),
        "llvm_cbe_raw_c_sha256": digest(raw_c_path),
        "adapted_c_sha256": digest(adapted_c_path),
        "raw_assembly_sha256": digest(bridge_raw_asm_path),
        "aligned_assembly_sha256": digest(bridge_asm_path),
        "sdcc_bridge_rel_sha256": digest(bridge_rel_path),
        "assembly_listing_sha256": digest(bridge_lst_path),
        "relocated_listing_sha256": digest(bridge_rst_path),
        **prior_bridge_artifacts,
    },
    "cpp_translation_units": len(modules),
    "selected_cpp_translation_units": sum(
        1 for module in modules if module["selected_for_bridge"]
    ),
    "modules": modules,
}
if prior_member_alignment is not None:
    result["member_function_alignment_prior_audit_sha256"] = digest(
        prior_alignment_audit_path
    )
    result["member_function_alignment_prior_audit"] = prior_member_alignment
Path(manifest_path).write_text(
    json.dumps(result, indent=2) + "\n", encoding="utf-8", newline="\n"
)
PY
    printf 'STCXX_ARDUINO_CLI_LINK=PASS\n'
    ;;

  *)
    printf 'unsupported STCXX Arduino CLI mode: %s\n' "${mode}" >&2
    exit 2
    ;;
esac
