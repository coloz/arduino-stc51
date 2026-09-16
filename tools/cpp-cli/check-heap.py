#!/usr/bin/env python3
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
