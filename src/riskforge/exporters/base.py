"""Exporter abstract base class."""

from __future__ import annotations

from abc import ABC, abstractmethod

from riskforge.models.risk import QUESTION_TITLE_MAX_LENGTH
from riskforge.models.rmf import RiskManagementFile

_SENTENCE_ENDS = ("?", ".", "!")


def display_title(title: str) -> str:
    """The title as a report shows it: a title cut at creation gets a trailing "...".

    Display only. The register and the content digest keep the stored title.
    """
    if len(title) == QUESTION_TITLE_MAX_LENGTH and not title.endswith(_SENTENCE_ENDS):
        return f"{title}..."
    return title


class Exporter(ABC):
    """Base class for all RiskForge exporters.

    Each exporter receives a fully-populated and schema-validated
    RiskManagementFile and returns bytes for writing to disk.
    """

    @abstractmethod
    def render(self, rmf: RiskManagementFile) -> bytes:
        """Render the RMF to bytes in the target format."""
        ...
