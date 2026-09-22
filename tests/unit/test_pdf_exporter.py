"""Unit tests for PDFExporter — verifying WeasyPrint rendering and error handling."""

from __future__ import annotations

import builtins
from datetime import UTC, datetime, timedelta

import pytest
from riskforge.exporters.pdf.pdf_exporter import PDFExporter
from riskforge.models.register import RiskRegister
from riskforge.models.risk import (
    Likelihood,
    Mitigation,
    RiskDimension,
    RiskItem,
    Severity,
)
from riskforge.models.rmf import RiskManagementFile
from riskforge.models.system import AISystem


def _sample_rmf() -> RiskManagementFile:
    system = AISystem(
        name="Credit Scoring Engine",
        version="2.0",
        purpose="Automated credit risk evaluation for retail lending.",
        provider_name="Acme Finance",
        annex_iii_self_classification_documented=True,
    )
    item = RiskItem(
        dimension=RiskDimension.discrimination,
        title="Proxy demographic bias in training data",
        description="Historical loan approval dataset contains disparate impact on protected classes.",
        source="manual",
        likelihood=Likelihood.likely,
        severity=Severity.major,
        residual_likelihood=Likelihood.unlikely,
        residual_severity=Severity.minor,
        mitigations=[
            Mitigation(
                description="Implement disparate impact re-weighting and monitor statistical parity difference.",
                control_type="detective",
                owner="Risk & AI Governance",
                status="implemented",
                article_ref="Art.9(2)(d)",
                nist_rmf_ref="MANAGE 1.3",
            )
        ],
    )
    register = RiskRegister(
        system=system,
        assessor_name="Alice Chen",
        assessor_role="AI Governance Lead",
        assessment_date=datetime.now(UTC),
        review_date=datetime.now(UTC) + timedelta(days=365),
        question_bank_version="1.0.0",
        items=[item],
    )
    return RiskManagementFile(register=register)


def test_pdf_exporter_render_produces_valid_pdf() -> None:
    """PDFExporter.render must invoke WeasyPrint and produce a valid, well-formed PDF byte string."""
    rmf = _sample_rmf()
    exporter = PDFExporter()

    pdf_bytes = exporter.render(rmf)

    assert isinstance(pdf_bytes, bytes), "PDFExporter.render must return bytes"
    assert (
        len(pdf_bytes) > 5000
    ), f"Expected non-trivial PDF size (>5KB), got {len(pdf_bytes)} bytes"
    assert pdf_bytes.startswith(
        b"%PDF-"
    ), "PDF output must start with the standard PDF magic header '%PDF-'"
    assert (
        b"%%EOF" in pdf_bytes[-1024:]
    ), "PDF output must terminate with standard '%%EOF' trailer marker"


def test_pdf_exporter_missing_weasyprint_raises_actionable_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When WeasyPrint cannot be imported, PDFExporter must raise a clear, actionable RuntimeError."""
    orig_import = builtins.__import__

    def fake_import(name: str, *args: object, **kwargs: object) -> object:
        if name == "weasyprint":
            raise ImportError("No module named 'weasyprint'")
        return orig_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    rmf = _sample_rmf()
    exporter = PDFExporter()

    with pytest.raises(RuntimeError, match="WeasyPrint is required for PDF export"):
        exporter.render(rmf)
