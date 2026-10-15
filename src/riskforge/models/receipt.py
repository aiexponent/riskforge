"""Receipt: a record, kept outside the project, that the audit chain held an entry (ADR-04 section 5)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr


class Receipt(BaseModel):
    """The last entry of the project chain when the receipt was taken.

    ``key_id``, ``public_key`` and ``signature`` are set only on a signed receipt. The
    signature covers every other field, ``key_id`` included. A field this model does not
    define, or a value of the wrong JSON type, is refused, so nothing in a receipt file
    can sit outside its signature.
    """

    model_config = ConfigDict(extra="forbid")

    receipt_version: Literal["1"] = "1"
    system_id: StrictStr
    seq: StrictInt = Field(..., ge=0)
    entry_hash: StrictStr
    register_fingerprint: StrictStr | None = None
    issued_at: datetime
    key_id: StrictStr | None = None
    public_key: StrictStr | None = None  # base64 of the 32 raw Ed25519 public key bytes
    signature: StrictStr | None = None  # base64 of the 64 raw Ed25519 signature bytes
