#!/usr/bin/env python3
"""Parse ASlink's fixed-width global-symbol display without losing identity.

ASlink 5.50 prints at most 32 characters in the ``Global`` column of its map
file.  Callers must first prove that every full symbol under audit has a
unique display value, while object/symbol-table checks continue to use the
complete symbol names.
"""

from __future__ import annotations

import re
from collections.abc import Iterable


ASLINK_GLOBAL_DISPLAY_WIDTH = 32


def aslink_global_display(symbol: str) -> str:
    if not isinstance(symbol, str) or not symbol:
        raise ValueError("ASlink symbol name must be a nonempty string")
    return symbol[:ASLINK_GLOBAL_DISPLAY_WIDTH]


def unique_aslink_global_displays(symbols: Iterable[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    owners: dict[str, str] = {}
    for symbol in symbols:
        if symbol in result:
            raise ValueError(f"duplicate full ASlink symbol under audit: {symbol}")
        display = aslink_global_display(symbol)
        previous = owners.get(display)
        if previous is not None:
            raise ValueError(
                "ambiguous ASlink 32-character symbol display: "
                f"{previous} and {symbol} both map to {display}"
            )
        owners[display] = symbol
        result[symbol] = display
    return result


def provider_count(
    map_payload: str,
    full_symbol: str,
    module: str,
    displays: dict[str, str],
) -> int:
    if full_symbol not in displays:
        raise ValueError(f"ASlink symbol was not uniqueness-audited: {full_symbol}")
    if not isinstance(module, str) or not module:
        raise ValueError("ASlink provider module must be a nonempty string")
    display = displays[full_symbol]
    return len(
        re.findall(
            rf"^[A-Z]:\s+[0-9A-Fa-f]+\s+{re.escape(display)}\s+"
            rf"{re.escape(module)}\s*$",
            map_payload,
            re.MULTILINE,
        )
    )
