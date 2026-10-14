"""AssessEngine — interactive question runner and pattern matcher."""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path
from typing import Any

import yaml

from riskforge.models.risk import Likelihood, RiskDimension, RiskItem, Severity

PATTERN_SCHEMA_VERSION = "1.1.0"


def _normalise(text: str) -> str:
    # Fold accents and case first, so "crédit" reads as "credit" and an accented
    # letter is not taken for a word break.
    decomposed = unicodedata.normalize("NFKD", text)
    folded = "".join(c for c in decomposed if not unicodedata.combining(c)).casefold()
    return " ".join(re.sub(r"[^a-z0-9]+", " ", folded).split())


def keyword_matches(keyword: str, purpose: str) -> bool:
    """True when the keyword starts a word, or a run of words, in the purpose.

    "credit" matches "Creditworthiness", "facial recognition" matches
    "facial-recognition", and "test" does not match "contest".
    """
    needle = _normalise(keyword)
    if not needle:
        return False
    return re.search(rf"(?<![a-z0-9]){re.escape(needle)}", _normalise(purpose)) is not None


class AssessEngine:
    """Loads question banks, runs questions interactively, matches patterns.

    Designed to be called by the CLI assess command. All IO is via callbacks
    so the engine remains independently testable without terminal interaction.
    """

    def __init__(self, data_dir: Path) -> None:
        self._question_bank_dir = data_dir / "question_bank"
        self._patterns_path = data_dir / "patterns" / "patterns.yaml"

    def load_questions(self, dimension: RiskDimension) -> list[dict[str, Any]]:
        """Load questions for a given dimension from the YAML question bank."""
        path = self._question_bank_dir / f"{dimension.value}.yaml"
        if not path.exists():
            return []
        data = yaml.safe_load(path.read_text())
        return data.get("questions", [])

    def load_all_questions(self) -> dict[str, list[dict[str, Any]]]:
        """Load all 8 dimension question banks."""
        return {dim.value: self.load_questions(dim) for dim in RiskDimension}

    def load_patterns(self) -> list[dict[str, Any]]:
        """Load risk patterns from the pattern library."""
        if not self._patterns_path.exists():
            return []
        data = yaml.safe_load(self._patterns_path.read_text(encoding="utf-8"))
        version = data.get("schema_version") if isinstance(data, dict) else None
        if version != PATTERN_SCHEMA_VERSION:
            raise ValueError(
                f"{self._patterns_path} has pattern schema_version {version!r}; "
                f"this release reads schema_version {PATTERN_SCHEMA_VERSION!r}"
            )
        return data.get("patterns", [])

    def match_patterns(self, annex_iii_category: str, purpose: str) -> list[dict[str, Any]]:
        """Patterns whose route fits this system and whose keywords appear in its purpose.

        An Annex III pattern needs the system's Annex III category. A product-route
        pattern (``high_risk_route: annex_i``) matches on keywords alone, because an
        AI system covered by Article 6(1) usually has no Annex III category.
        """
        matched: list[dict[str, Any]] = []
        for pattern in self.load_patterns():
            triggers = pattern["triggers"]
            product_route = pattern.get("high_risk_route") == "annex_i"
            if not product_route and annex_iii_category not in triggers["annex_iii_categories"]:
                continue
            if any(keyword_matches(keyword, purpose) for keyword in triggers["purpose_keywords"]):
                matched.append(pattern)
        return matched

    def question_to_risk_item(
        self,
        question: dict[str, Any],
        dimension: RiskDimension,
        likelihood: int,
        severity: int,
        answer_unknown: bool = False,
    ) -> RiskItem:
        """Convert a question + answer into a RiskItem."""
        lh = Likelihood(min(max(likelihood, 1), 5))
        sv = Severity(min(max(severity, 1), 5))
        return RiskItem(
            dimension=dimension,
            title=question["text"][:120],
            description=question.get("guidance", question["text"]),
            source="question_bank",
            likelihood=lh,
            severity=sv,
            residual_likelihood=lh,
            residual_severity=sv,
            article_refs=question.get("article_refs", []),
            nist_rmf_ref=question.get("nist_rmf_ref", ""),
            iso42001_ref=question.get("iso42001_ref", ""),
            regulatory_status=question.get("regulatory_status", "settled"),
            knowledge_gap=answer_unknown,
            tags=[question.get("id", "")],
        )
