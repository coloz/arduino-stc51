#!/usr/bin/env python3
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
