"""The self-declared name recorded with a risk acceptance or a mitigation (PRD-356)."""

from __future__ import annotations

import unicodedata

# Bidirectional controls and invisible characters can make a name display as another
# name or hide text. U+200C and U+200D (zero-width non-joiner and joiner) stay allowed:
# Persian, Indic scripts and emoji need them.
_REFUSED_FORMAT_CHARACTERS = frozenset(
    [chr(c) for c in range(0x202A, 0x202F)]
    + [chr(c) for c in range(0x2066, 0x206A)]
    + ["\u200b", "\u200e", "\u200f", "\ufeff"]
)


class ActorNameError(ValueError):
    """Raised when an actor name is blank or does not fit on one line."""


def normalise_actor_name(value: str | None) -> str | None:
    """Return *value* without surrounding white space, or None when nothing is left.

    Raises
    ------
    ActorNameError
        If the name holds a control character, a line break, a bidirectional control or
        an invisible character other than a zero-width joiner or non-joiner: a name must
        be one line of plain text in the audit log, the register and every export.
    """
    if value is None:
        return None
    name = value.strip()
    if not name:
        return None
    for char in name:
        if unicodedata.category(char) in ("Cc", "Zl", "Zp") or char in _REFUSED_FORMAT_CHARACTERS:
            raise ActorNameError(
                f"The name contains a line break, control or invisible character "
                f"({ascii(char)}); give it as plain text on one line."
            )
    return name


def require_actor_name(value: str) -> str:
    """Return the normalised name, or raise ActorNameError when it is blank."""
    name = normalise_actor_name(value)
    if name is None:
        raise ActorNameError("A name is required and cannot be empty.")
    return name
