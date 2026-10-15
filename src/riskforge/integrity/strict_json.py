"""Strict JSON reading for files RiskForge verifies: receipts and RMF files (ADR-04 section 2).

Python keeps the last of two duplicate keys and other parsers may keep the first, so a
file with duplicates could show one value to a reader and hash another. ``NaN`` and
``Infinity`` are not JSON, and a number such as ``1e400`` reads as infinity. RiskForge
never writes any of these, so a file that holds one is refused.
"""

from __future__ import annotations

import json
import math
from typing import Any


class StrictJsonError(ValueError):
    """Valid JSON for ``json.loads`` that RiskForge refuses: a duplicate key or a non-finite number."""


def _object_without_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise StrictJsonError(f"duplicate key {key!r} in one object")
        result[key] = value
    return result


def _refuse_constant(name: str) -> Any:
    raise StrictJsonError(f"{name} is not a JSON number")


def _finite_float(text: str) -> float:
    value = float(text)
    if not math.isfinite(value):
        raise StrictJsonError(f"the number {text} is not finite as a float")
    return value


def loads_strict(text: str) -> Any:
    """``json.loads`` that refuses duplicate keys at any depth and non-finite numbers.

    Raises
    ------
    StrictJsonError
        If the text holds a duplicate key, ``NaN``, ``Infinity``, ``-Infinity`` or a
        number that overflows a float.
    json.JSONDecodeError
        If the text is not JSON.
    """
    return json.loads(
        text,
        object_pairs_hook=_object_without_duplicates,
        parse_constant=_refuse_constant,
        parse_float=_finite_float,
    )
