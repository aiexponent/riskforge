"""The strict JSON reader for receipt and RMF files (ADR-04 section 2)."""

from __future__ import annotations

import json

import pytest
from riskforge.integrity.strict_json import StrictJsonError, loads_strict


def test_plain_json_reads_as_json_loads_reads_it() -> None:
    text = '{"a": 1, "b": [1.5, -2e3, {"c": null}], "d": "x"}'
    assert loads_strict(text) == json.loads(text)


@pytest.mark.parametrize(
    "text",
    [
        '{"a": 1, "a": 2}',
        '{"outer": {"k": 1, "k": 1}}',
        '{"list": [{"k": 1}, {"k": 1, "k": 2}]}',
        '[{"deep": [{"x": {"y": 1, "y": 1}}]}]',
    ],
)
def test_a_duplicate_key_at_any_depth_is_refused(text: str) -> None:
    with pytest.raises(StrictJsonError, match="duplicate key"):
        loads_strict(text)


@pytest.mark.parametrize("constant", ["NaN", "Infinity", "-Infinity"])
def test_non_finite_constants_are_refused(constant: str) -> None:
    with pytest.raises(StrictJsonError, match=constant):
        loads_strict(f'{{"seq": {constant}}}')


@pytest.mark.parametrize("number", ["1e400", "-1e400", "123456789e999"])
def test_numbers_that_overflow_a_float_are_refused(number: str) -> None:
    with pytest.raises(StrictJsonError, match="not finite"):
        loads_strict(f'{{"seq": [{number}]}}')


def test_text_that_is_not_json_raises_the_json_error() -> None:
    with pytest.raises(json.JSONDecodeError):
        loads_strict("{not json")
