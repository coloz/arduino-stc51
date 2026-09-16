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

to_native_path() {
  realpath -m -- "$1"
}

source_path="$(to_native_path "${source_win}")"
if [[ "${object_win,,}" == "nul" || "${object_win}" == "/dev/null" ]]; then
  object_path="/dev/null"
else
  object_path="$(to_native_path "${object_win}")"
fi
argfile="$(to_native_path "${argfile_win}")"

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
  local check
  for check in cpp-metadata c-metadata check-heap check-sidecars audit-bridge-warnings audit-heap-link write-link-manifest; do
    verify_file_hash "${script_dir}/${check}.py" "$(json_value shared_checks.${check})" "${check}"
  done
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
  verify_file_hash "${script_dir}/archive_members.py" \
    "$(json_value pipeline_helpers.archive_member_reader.sha256)" archive-member-reader
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
stcxx_resolve_tools "$(json_value tools.sdcc.source_project_posix)" "${platform_root}" "${lock_file}"
sdcc_shared_include="${sdcc_include_root}/mcs51"
sdcc_canonical_include="$(to_native_path "${sdcc_include_root}")"
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
  printf '%s%s\n' "${prefix}" "$(to_native_path "${path}")"
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
    dependency_file="$(to_native_path "${argument}")"
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

    "${python}" "${script_dir}/cpp-metadata.py" "${source_path}" "${object_path}" "${bitcode}" \
      "${llvm_ir}" "${module_c}" "${target_triple}" "${data_layout}" "${cpp_optimization}"
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
    "${python}" "${script_dir}/c-metadata.py" "${object_rel}.stcxx-c.json" "${source_path}" "${object_rel}" \
      "${clang}" "${sdcc}" "${target_triple}" "${cpp_include_root}" "${resource_dir}" "${#filtered_sdcc_args[@]}" \
      "${filtered_sdcc_args[@]}" "${clang_user_args[@]}"
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
        recipe_output="$(to_native_path "${argument}")"
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
        *.o) direct_objects+=("$(to_native_path "${argument}")") ;;
        *.a) archives+=("$(to_native_path "${argument}")") ;;
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
    "${python}" "${script_dir}/check-heap.py" "${heap_rel}" "${heap_state_rel}" "${sdcc_target}" \
      "${mcs251_constrained_heap}"
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

    "${python}" "${script_dir}/check-sidecars.py" "${target_triple}" "${data_layout}" "${bitcode_files[@]}"

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
    "${python}" "${script_dir}/audit-bridge-warnings.py" "${bridge_log}" "${warning_audit}" "${sdcc_target}" \
      "${work}/audit.json"

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
          path="$(to_native_path "${argument}")"
          link_args+=("${path%.o}.rel")
          ;;
        *.a)
          path="$(to_native_path "${argument}")"
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
          link_args+=("$(to_native_path "${argument}")")
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
    "${python}" "${script_dir}/audit-heap-link.py" "${heap_link_audit}" "${link_log}" "${link_args_file}" \
      "${map_file}" "${heap_rel}" "${heap_state_rel}" "${heap_archive}" \
      "${heap_archive_members_file}" "${aslink_map_symbols}" \
      "${sdcc_target}" "${mcs251_iram_size}" "${mcs251_stack_loc}" \
      "${mcs251_stack_size}"

    "${python}" "${script_dir}/write-link-manifest.py" "${work}/manifest.json" "${output_hex}" "${lock_file}" \
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
      -- "${bitcode_files[@]}"
    printf 'STCXX_ARDUINO_CLI_LINK=PASS\n'
    ;;

  *)
    printf 'unsupported STCXX Arduino CLI mode: %s\n' "${mode}" >&2
    exit 2
    ;;
esac
