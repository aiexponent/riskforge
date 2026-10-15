"""Receipts for a project: one for the head of its audit chain (ADR-04 section 5)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from riskforge.engine.integrity import IntegrityError, IntegrityReport, latest_fingerprints
from riskforge.integrity.receipts import build_receipt
from riskforge.models.receipt import Receipt

if TYPE_CHECKING:
    from riskforge.integrity.signing import Ed25519Signer


class NoChainEntryError(RuntimeError):
    """The audit log holds no entry yet, so there is nothing for a receipt to name."""


def issue_receipt(
    report: IntegrityReport, system_id: str, signer: Ed25519Signer | None = None
) -> Receipt:
    """A receipt for the last entry of the chain ``report``'s integrity check read.

    ``register_fingerprint`` is the latest fingerprint the chain records for
    ``system_id``, or None when it records none. Signed when ``signer`` is given.

    Raises
    ------
    IntegrityError
        If the report holds any error: a receipt is only taken of an intact project.
    NoChainEntryError
        If the audit log holds no entry.
    """
    if not report.ok:
        raise IntegrityError(report)
    head = report.head
    if head is None:
        raise NoChainEntryError(
            "The audit log holds no entries yet, so there is no entry for a receipt to name. "
            "Make a change first, for example `riskforge assess`."
        )
    fingerprint = latest_fingerprints(report.entries).get(system_id)
    return build_receipt(head, system_id, fingerprint, signer)
