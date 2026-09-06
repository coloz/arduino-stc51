#!/bin/sh
# Reduce SDCC's .mem report to the two counters consumed by Arduino.

MEMORY_REPORT="$1"

if [ ! -f "$MEMORY_REPORT" ]; then
    echo "SDCC memory report not found: $MEMORY_REPORT" >&2
    exit 2
fi

# SDCC reports internal allocation indirectly as the first stack address.  It
# reports pdata, xdata and flash directly in the "Other memory" table.  Sum
# the occupied RAM regions so small-model DATA is not incorrectly shown as 0.
awk '
function hex_to_decimal(value,    digits, index_value, digit, result) {
    sub(/^0[xX]/, "", value)
    value = tolower(value)
    digits = "0123456789abcdef"
    result = 0
    for (index_value = 1; index_value <= length(value); index_value++) {
        digit = index(digits, substr(value, index_value, 1)) - 1
        if (digit < 0) {
            return 0
        }
        result = (result * 16) + digit
    }
    return result
}

function first_decimal_field(    field_index) {
    for (field_index = 1; field_index <= NF; field_index++) {
        if ($field_index ~ /^[0-9]+$/) {
            return $field_index + 0
        }
    }
    return 0
}

# With --stack-auto SDCC correctly states that it cannot infer a fixed stack
# interval.  In that mode derive the conservative occupied internal-RAM high
# water mark from the 16-byte allocation grid instead of rejecting the report.
/^0x[0-9A-Fa-f]+:\|/ {
    address = $0
    sub(/:.*/, "", address)
    base = hex_to_decimal(address)
    row = $0
    sub(/^0x[0-9A-Fa-f]+:\|/, "", row)
    cell_count = split(row, cells, "|")
    for (cell_index = 1; cell_index <= 16 && cell_index <= cell_count; cell_index++) {
        cell = cells[cell_index]
        gsub(/[[:space:]]/, "", cell)
        if (cell != "" && base + cell_index > internal_grid_high) {
            internal_grid_high = base + cell_index
        }
    }
    internal_grid_seen = 1
}

/No clue at where the stack begins and ends!/ {
    dynamic_stack_report = 1
}

/[Ss]tack starts at:[[:space:]]*0[xX][0-9A-Fa-f]+/ {
    for (field_index = 1; field_index <= NF; field_index++) {
        if ($field_index ~ /^0[xX][0-9A-Fa-f]+$/) {
            internal_ram = hex_to_decimal($field_index)
            stack_seen = 1
            break
        }
    }
}

/^[[:space:]]*PAGED EXT[.] RAM[[:space:]]/ {
    paged_external_ram = first_decimal_field()
}

/^[[:space:]]*EXTERNAL RAM[[:space:]]/ {
    external_ram = first_decimal_field()
}

/^[[:space:]]*ROM\/EPROM\/FLASH[[:space:]]/ {
    program_bytes = first_decimal_field()
    program_seen = 1
}

END {
    if (!stack_seen && dynamic_stack_report && internal_grid_seen) {
        internal_ram = internal_grid_high
        stack_seen = 1
    }
    if (!stack_seen || !program_seen) {
        print "Unrecognized SDCC memory report format" > "/dev/stderr"
        exit 3
    }
    print "STC_PROGRAM_BYTES " program_bytes
    print "STC_RAM_BYTES " (internal_ram + paged_external_ram + external_ram)
}
' "$MEMORY_REPORT"
