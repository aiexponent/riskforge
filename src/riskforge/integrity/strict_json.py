"""Strict JSON reading for files RiskForge verifies: receipts and RMF files (ADR-04 section 2).

Python keeps the last of two duplicate keys and other parsers may keep the first, so a
file with duplicates could show one value to a reader and hash another. ``NaN`` and
``Infinity`` are not JSON, and a number such as ``1e400`` reads as infinity. RiskForge
never writes any of these, nor arrays and objects nested hundreds of levels deep, which
can exhaust the recursion of the parser or of the hashing that follows. A file that
holds one is refused.

Each refusal's message is a noun phrase, such as "a NaN value", so a caller can say
"it holds <message>, which RiskForge never writes."
"""

from __future__ import annotations

import json
import math
import re
from typing import Any

# RiskForge writes about 7 levels; deeper than this is refused before parsing.
MAX_DEPTH = 64

# A JSON string, or one bracket outside strings. Exact for valid JSON, where a quote
# outside a string always opens one. An unterminated string runs to the end of the
# text, so each quote is scanned once and the scan stays linear.
_STRING_OR_BRACKET = re.compile(r'"[^"\\]*(?:\\.[^"\\]*)*(?:"|\\?\Z)|[\[\]{}]', re.DOTALL)


class StrictJsonError(ValueError):
    """Valid JSON for ``json.loads`` that RiskForge refuses, such as a duplicate key."""


class NumberTooLongError(ValueError):
    """An integer with more digits than Python reads (``sys.get_int_max_str_digits``)."""


def _object_without_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise StrictJsonError(f"a duplicate key {key!r} in one object")
        result[key] = value
    return result


def _refuse_constant(name: str) -> Any:
    article = "an" if name == "Infinity" else "a"
    raise StrictJsonError(f"{article} {name} value")


def _finite_float(text: str) -> float:
    value = float(text)
    if not math.isfinite(value):
        raise StrictJsonError(f"a number outside the range of a float ({text})")
    return value


def _int(text: str) -> int:
    try:
        return int(text)
    except ValueError as exc:
        raise NumberTooLongError(
            f"an integer too long to read ({len(text.lstrip('-'))} digits)"
        ) from exc


def refuse_deep_nesting(text: str) -> None:
    """Raise :class:`StrictJsonError` if *text* nests arrays or objects over ``MAX_DEPTH``.

    Audit log lines are checked with this too, so no entry reaches the entry hash
    nested deeper than the hashing can follow.
    """
    if text.count("[") + text.count("{") <= MAX_DEPTH:
        return  # too few brackets to go that deep; skips the scan for a typical line
    depth = 0
    for match in _STRING_OR_BRACKET.finditer(text):
        token = match.group()
        if token in ("[", "{"):
            depth += 1
            if depth > MAX_DEPTH:
                raise StrictJsonError(
                    f"an array or object nested more than {MAX_DEPTH} levels deep"
                )
        elif token in ("]", "}"):
            depth = max(depth - 1, 0)


def loads_strict(text: str) -> Any:
    """``json.loads`` that refuses duplicate keys, non-finite numbers and deep nesting.

    Raises
    ------
    StrictJsonError
        If the text holds a duplicate key, ``NaN``, ``Infinity``, ``-Infinity``, a
        number that overflows a float, or arrays and objects nested more than
        ``MAX_DEPTH`` levels deep.
    NumberTooLongError
        If the text holds an integer with more digits than Python reads.
    json.JSONDecodeError
        If the text is not JSON.
    """
    refuse_deep_nesting(text)
    return json.loads(
        text,
        object_pairs_hook=_object_without_duplicates,
        parse_constant=_refuse_constant,
        parse_float=_finite_float,
        parse_int=_int,
    )
