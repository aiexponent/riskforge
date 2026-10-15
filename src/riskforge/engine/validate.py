"""ValidateEngine — 8 readiness gates before export."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from riskforge.models.register import RiskRegister
from riskforge.models.risk import RiskDimension


class GateStatus(str, Enum):
    PASS = "PASS"
    WARN = "WARN"
    FAIL = "FAIL"


@dataclass
class GateResult:
    gate_id: str
    description: str
    status: GateStatus
    details: str = field(default="")


class ValidateEngine:
    """Pre-export readiness checks.

    FAIL gates block export (unless --force flag is provided).
    WARN gates allow export but are surfaced in the output.
    All 8 gates must be run — do not short-circuit on first failure.
    """

    ALL_DIMENSIONS = set(RiskDimension)

    def run(self, register: RiskRegister) -> list[GateResult]:
        return [
            self._gate_dimensions_covered(register),
            self._gate_article_6_classification(register),
            self._gate_high_risks_addressed(register),
            self._gate_knowledge_gaps_have_tests(register),
            self._gate_metadata_complete(register),
            self._gate_assessor_identity(register),
            self._gate_low_score_warning(register),
            self._gate_vague_mitigations(register),
        ]

    def has_failures(self, results: list[GateResult]) -> bool:
        return any(r.status == GateStatus.FAIL for r in results)

    def _gate_dimensions_covered(self, r: RiskRegister) -> GateResult:
        covered = r.covered_dimensions()
        missing = self.ALL_DIMENSIONS - covered
        if missing:
            return GateResult(
                "G1",
                "All 8 risk dimensions have entries",
                GateStatus.FAIL,
                f"Missing: {', '.join(d.value for d in sorted(missing, key=lambda d: d.value))}. "
                f"Add a risk item for each: `riskforge assess {r.system.id} -a NAME -r ROLE "
                "--dimension <dimension>`.",
            )
        return GateResult("G1", "All 8 risk dimensions have entries", GateStatus.PASS)

    def _gate_article_6_classification(self, r: RiskRegister) -> GateResult:
        if not r.system.annex_iii_self_classification_documented:
            return GateResult(
                "G2",
                "Article 6(2) self-classification documented",
                GateStatus.FAIL,
                "Provider must confirm Annex III self-classification before export. "
                "Run `riskforge system classify <system-id> --confirm` to record it.",
            )
        return GateResult("G2", "Article 6(2) self-classification documented", GateStatus.PASS)

    def _gate_high_risks_addressed(self, r: RiskRegister) -> GateResult:
        open_items = r.open_items()
        if open_items:
            return GateResult(
                "G3",
                "All high-scoring risks mitigated or accepted",
                GateStatus.FAIL,
                f"{len(open_items)} risk(s) above threshold not accepted or mitigated: "
                + ", ".join(str(i.id)[:8] for i in open_items),
            )
        return GateResult("G3", "All high-scoring risks mitigated or accepted", GateStatus.PASS)

    def _gate_knowledge_gaps_have_tests(self, r: RiskRegister) -> GateResult:
        gaps_without_tests = [i for i in r.knowledge_gaps() if not i.tags]
        if gaps_without_tests:
            return GateResult(
                "G4",
                "Knowledge gaps have test requirements",
                GateStatus.WARN,
                f"{len(gaps_without_tests)} knowledge gap(s) without test requirements. "
                "Run `riskforge tests generate` to derive tests.",
            )
        return GateResult("G4", "Knowledge gaps have test requirements", GateStatus.PASS)

    def _gate_metadata_complete(self, r: RiskRegister) -> GateResult:
        required = [r.system.name, r.system.version, r.system.purpose, r.system.provider_name]
        if not all(required):
            return GateResult(
                "G5",
                "System metadata complete",
                GateStatus.FAIL,
                "Missing required fields: name, version, purpose, or provider_name.",
            )
        return GateResult("G5", "System metadata complete", GateStatus.PASS)

    def _gate_assessor_identity(self, r: RiskRegister) -> GateResult:
        if not r.assessor_name.strip() or not r.assessor_role.strip():
            return GateResult(
                "G6",
                "Assessor identity recorded",
                GateStatus.FAIL,
                "assessor_name and assessor_role are required.",
            )
        return GateResult("G6", "Assessor identity recorded", GateStatus.PASS)

    def _gate_low_score_warning(self, r: RiskRegister) -> GateResult:
        if r.items and all(i.risk_score <= 4 for i in r.items):
            return GateResult(
                "G7",
                "Risk score distribution plausible",
                GateStatus.WARN,
                "All risks scored low (<=4). This is unusual and may reduce regulator "
                "confidence. Review scoring before export.",
            )
        return GateResult("G7", "Risk score distribution plausible", GateStatus.PASS)

    def _gate_vague_mitigations(self, r: RiskRegister) -> GateResult:
        vague = [m for i in r.items for m in i.mitigations if m.is_vague]
        if vague:
            return GateResult(
                "G8",
                "No vague mitigations",
                GateStatus.WARN,
                f"{len(vague)} mitigation(s) flagged as vague. "
                "Replace generic descriptions with specific control measures.",
            )
        return GateResult("G8", "No vague mitigations", GateStatus.PASS)
