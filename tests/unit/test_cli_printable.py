"""Text from files RiskForge reads is shown with its control characters made visible."""

from __future__ import annotations

import pytest
from riskforge.cli.errors import printable


@pytest.mark.parametrize(
    ("text", "shown"),
    [
        ("key\x1b[2J", "key\\x1b[2J"),  # C0: ESC
        ("a\x00b\x07", "a\\x00b\\x07"),
        ("del\x7f", "del\\x7f"),
        ("csi\x9b", "csi\\x9b"),  # C1
        ("‮evil", "\\u202eevil"),  # bidi override
        ("⁦x⁩", "\\u2066x\\u2069"),
        ("‎x‏؜", "\\u200ex\\u200f\\u061c"),
        ("two\nlines\ttab", "two\\nlines\\ttab"),
        ("plain text, é, 日本, emoji \U0001f600 and a ZWJ ‍", None),
    ],
)
def test_printable_makes_control_characters_visible(text: str, shown: str | None) -> None:
    assert printable(text) == (text if shown is None else shown)


def test_printable_can_keep_line_breaks() -> None:
    assert printable("one\ntwo\x1b", keep_newlines=True) == "one\ntwo\\x1b"
