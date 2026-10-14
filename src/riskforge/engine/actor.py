"""The self-declared name recorded with a risk acceptance or a mitigation (PRD-356)."""

from __future__ import annotations

import unicodedata


class ActorNameError(ValueError):
    """Raised when an actor name is blank or does not fit on one line."""


def normalise_actor_name(value: str | None) -> str | None:
    """Return *value* without surrounding white space, or None when nothing is left.

    Raises
    ------
    ActorNameError
        If the name holds a control character or a line break: a name must be one line
        of text in the audit log, the register and every export.
    """
    if value is None:
        return None
    name = value.strip()
    if not name:
        return None
    for char in name:
        if unicodedata.category(char) in ("Cc", "Zl", "Zp"):
            raise ActorNameError(
                f"The name contains a line break or control character ({ascii(char)}); "
                "give it on one line."
            )
    return name


def require_actor_name(value: str) -> str:
    """Return the normalised name, or raise ActorNameError when it is blank."""
    name = normalise_actor_name(value)
    if name is None:
        raise ActorNameError("A name is required and cannot be empty.")
    return name
