"""The strict JSON reader for receipt and RMF files (ADR-04 section 2)."""

from __future__ import annotations

import json

import pytest
from riskforge.integrity.strict_json import (
    MAX_DEPTH,
    NumberTooLongError,
    StrictJsonError,
    loads_strict,
)


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
    with pytest.raises(StrictJsonError, match="outside the range of a float"):
        loads_strict(f'{{"seq": [{number}]}}')


def test_text_that_is_not_json_raises_the_json_error() -> None:
    with pytest.raises(json.JSONDecodeError):
        loads_strict("{not json")


@pytest.mark.parametrize("digits", ["9" * 5000, "-" + "9" * 5000])
def test_an_integer_too_long_for_python_raises_its_own_error(digits: str) -> None:
    with pytest.raises(NumberTooLongError, match="too long"):
        loads_strict('{"n": ' + digits + "}")


def test_long_integers_python_can_read_still_read() -> None:
    assert loads_strict("[" + "9" * 4000 + "]") == [int("9" * 4000)]


# --- nesting depth ---------------------------------------------------------------------


@pytest.mark.parametrize("open_close", [("[", "]"), ('{"a": ', "}")])
def test_nesting_deeper_than_riskforge_writes_is_refused(open_close: tuple[str, str]) -> None:
    opening, closing = open_close
    text = opening * (MAX_DEPTH + 1) + "1" + closing * (MAX_DEPTH + 1)
    with pytest.raises(StrictJsonError, match=f"nested more than {MAX_DEPTH} levels deep"):
        loads_strict(text)


def test_nesting_too_deep_for_the_parser_is_refused_the_same_way() -> None:
    with pytest.raises(StrictJsonError, match="nested more than"):
        loads_strict("[" * 100_000 + "]" * 100_000)


def test_nesting_up_to_the_limit_reads() -> None:
    text = "[" * MAX_DEPTH + "1" + "]" * MAX_DEPTH
    assert loads_strict(text) == json.loads(text)


def test_brackets_inside_strings_do_not_count_as_nesting() -> None:
    text = json.dumps({"note": "[" * 500 + '{\\"' * 100, "x": ["]]]}}}"]})
    assert loads_strict(text) == json.loads(text)


def test_many_shallow_brackets_read() -> None:
    text = json.dumps([[1]] * 100 + [{"a": [2]}] * 100)
    assert loads_strict(text) == json.loads(text)


def test_the_depth_limit_is_well_above_what_riskforge_writes() -> None:
    assert MAX_DEPTH >= 64


# --- messages read as noun phrases -------------------------------------------------------
# verify and the receipt reader embed them as "it holds <message>, which RiskForge never writes".


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ('{"a": 1, "a": 2}', "a duplicate key 'a' in one object"),
        ('{"a": NaN}', "a NaN value"),
        ('{"a": Infinity}', "an Infinity value"),
        ('{"a": -Infinity}', "a -Infinity value"),
        ('{"a": 1e400}', "a number outside the range of a float (1e400)"),
        ("[" * 70 + "]" * 70, f"an array or object nested more than {MAX_DEPTH} levels deep"),
    ],
)
def test_refusals_read_as_noun_phrases(text: str, message: str) -> None:
    with pytest.raises(StrictJsonError) as caught:
        loads_strict(text)
    assert str(caught.value) == message


def test_an_integer_too_long_reads_as_a_noun_phrase() -> None:
    with pytest.raises(NumberTooLongError) as caught:
        loads_strict("[" + "9" * 5000 + "]")
    assert str(caught.value) == "an integer too long to read (5000 digits)"
