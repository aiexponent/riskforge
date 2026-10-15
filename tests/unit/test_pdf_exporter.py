"""Unit tests for PDFExporter: WeasyPrint rendering, report layout and error handling."""

from __future__ import annotations

import builtins
import logging
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pypdf import PdfReader
from rf_testkit import pdf_text
from riskforge.exporters.pdf.pdf_exporter import PDFExporter
from riskforge.models.audit import AuditActor, AuditEntry
from riskforge.models.receipt import Receipt
from riskforge.models.register import RiskRegister
from riskforge.models.requirements import TestRequirement
from riskforge.models.risk import (
    Likelihood,
    Mitigation,
    RiskDimension,
    RiskItem,
    Severity,
)
from riskforge.models.rmf import ChainProof, RiskManagementFile, RmfSignature, SignOff
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


SECTIONS = [
    "1. Executive summary",
    "2. Methodology",
    "3. Risk register",
    "4. Residual risk summary",
    "5. Article 9(6) to 9(8) test requirements",
    "6. Audit metadata",
]
OTHER_SYSTEM = "00000000-0000-4000-8000-000000000000"


def _flat(text: str) -> str:
    return " ".join(text.split())


def _section(text: str, heading: str) -> str:
    """The text from *heading* to the next numbered section heading."""
    flat = _flat(text)
    start = flat.index(heading)
    later = [flat.find(h, start + 1) for h in SECTIONS if flat.find(h, start + 1) > start]
    return flat[start : min(later) if later else len(flat)].strip()


def _with_provenance(rmf: RiskManagementFile) -> RiskManagementFile:
    """The sample RMF plus every provenance block and an accepted risk, so each branch renders."""
    system_id = str(rmf.register.system.id)
    actor = AuditActor(type="human", identity="alice@example.com")
    events = [
        (system_id, "system.created"),
        (OTHER_SYSTEM, "other_system.event"),
        (system_id, "register.created"),
        ("", "project.event"),
        (system_id, "risk_item.created"),
    ]
    rmf.chain_proof = ChainProof(
        scope="project",
        entries=[
            AuditEntry(
                seq=seq,
                event=event,
                actor=actor,
                system_id=owner,
                prev_hash="p",
                entry_hash=f"{seq:064x}",
            )
            for seq, (owner, event) in enumerate(events)
        ],
    )
    now = datetime.now(UTC)
    rmf.receipt = Receipt(system_id=system_id, seq=4, entry_hash="4" * 64, issued_at=now)
    rmf.signatures = [
        RmfSignature(key_id="ed25519:0123456789abcdef", signed_at=now, signature="c2ln")
    ]
    rmf.signoffs = [
        SignOff(
            approver="Bob Approver",
            decision="approved",
            version_number=1,
            register_fingerprint="f" * 64,
            totp_verified_at=now,
            signed_at=now,
            key_id="ed25519:0123456789abcdef",
            signature="c2ln",
        )
    ]
    rmf.test_requirements = [
        TestRequirement(
            risk_item_id=rmf.register.items[0].id,
            description="Statistical parity difference across protected groups.",
            metric_type="demographic_parity",
            threshold_range="<= 0.10",
            article_ref="Art.9(8)",
        )
    ]
    rmf.register.items.append(
        RiskItem(
            dimension=RiskDimension.privacy,
            title="Re-identification of applicants from model outputs",
            description="Score explanations may reveal attributes of individual applicants.",
            source="manual",
            likelihood=Likelihood.likely,
            severity=Severity.major,
            residual_likelihood=Likelihood.possible,
            residual_severity=Severity.major,
            accepted=True,
            acceptance_rationale="Explanations are shown only to the applicant they describe.",
            accepted_by="Carol Risk Owner",
        )
    )
    return rmf


@pytest.fixture(scope="module", params=[False, True], ids=["plain", "with-provenance"])
def rendered(
    request: pytest.FixtureRequest, tmp_path_factory: pytest.TempPathFactory
) -> tuple[RiskManagementFile, str, list[str]]:
    rmf = _with_provenance(_sample_rmf()) if request.param else _sample_rmf()
    rmf.sha256_hash = "ab" * 32
    path = tmp_path_factory.mktemp("pdf") / "rmf.pdf"
    path.write_bytes(PDFExporter().render(rmf))
    pages = [page.extract_text() for page in PdfReader(str(path)).pages]
    return rmf, pdf_text(path), pages


def test_pdf_has_the_seven_sections_in_order(rendered) -> None:
    _rmf, text, _pages = rendered
    flat = _flat(text)
    positions = [flat.find(heading) for heading in SECTIONS]
    assert all(p >= 0 for p in positions), positions
    assert positions == sorted(positions)


def test_cover_is_a_page_of_its_own_with_a_three_number_summary(rendered) -> None:
    """Only the stylesheet's page break keeps the executive summary off page 1."""
    rmf, _text, pages = rendered
    cover = _flat(pages[0])
    register = rmf.register
    assert register.system.name in cover
    assert "executive summary" not in cover.lower()
    # The figure and its label are separate blocks, so text extraction may join them.
    assert re.search(rf"\b{len(register.items)} ?risk items", cover)
    assert re.search(rf"\b{len(register.open_items())} ?open above appetite", cover)
    assert re.search(rf"\b{len(register.knowledge_gaps())} ?knowledge gaps", cover)


def test_executive_summary_ends_with_the_disclosure(rendered) -> None:
    rmf, text, _pages = rendered
    summary = _section(text, SECTIONS[0])
    assert summary.endswith(_flat(rmf.disclosure))


def test_methodology_names_the_scoring_and_the_gate_results(rendered) -> None:
    rmf, text, _pages = rendered
    methodology = _section(text, SECTIONS[1])
    assert f"version {rmf.register.question_bank_version}" in methodology
    assert "critical 17 to 25" in methodology
    for gate in [f"G{n}" for n in range(1, 9)]:
        assert re.search(rf"{gate} (PASS|WARN|FAIL)", methodology), gate


def test_residual_summary_lists_every_item_with_its_decision(rendered) -> None:
    rmf, text, _pages = rendered
    residual = _section(text, SECTIONS[3])
    for item in rmf.register.items:
        assert item.title in residual
        if item.accepted:
            assert f"Accepted: {item.acceptance_rationale}" in residual
    assert "Within appetite" in residual


def test_test_requirements_section_lists_the_saved_requirements(rendered) -> None:
    rmf, text, _pages = rendered
    tests_section = _section(text, SECTIONS[4])
    if rmf.test_requirements:
        assert "demographic_parity" in tests_section
    else:
        assert "riskforge tests generate" in tests_section


def test_audit_metadata_has_the_provenance_and_this_systems_change_log(rendered) -> None:
    rmf, text, _pages = rendered
    audit = _section(text, SECTIONS[5])
    assert rmf.sha256_hash in audit.replace(" ", "")
    if rmf.chain_proof is None:
        assert "Unsigned" in audit
        assert "no chain proof" in audit
        return
    assert "ed25519:0123456789abcdef" in audit
    assert "4" * 64 in audit.replace(" ", "")
    assert "Bob Approver: approved (version 1)" in audit
    log = audit[audit.index("Change log") :]
    for event in ("system.created", "register.created", "project.event", "risk_item.created"):
        assert event in log
    assert "other_system.event" not in log


def test_pdf_shows_the_content_digest_and_risk_titles(rendered) -> None:
    rmf, text, _pages = rendered
    assert rmf.sha256_hash in "".join(text.split())
    assert rmf.register.items[0].title in _flat(text)


def test_pdf_uses_no_serif_font(rendered, tmp_path: Path) -> None:
    """The stylesheet sets a sans-serif font everywhere, footers included.

    Margin boxes do not inherit the body font, so a footer without its own
    font-family falls back to the default serif face.
    """
    rmf, _text, _pages = rendered
    path = tmp_path / "rmf.pdf"
    path.write_bytes(PDFExporter().render(rmf))
    fonts = {
        str(font.get_object()["/BaseFont"])
        for page in PdfReader(str(path)).pages
        for font in page["/Resources"]["/Font"].values()
    }
    assert fonts
    assert not [f for f in fonts if re.search(r"Times|Serif|Roman|Georgia", f)], fonts


def test_render_logs_no_weasyprint_errors(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING, logger="weasyprint"):
        PDFExporter().render(_sample_rmf())
    assert [r.getMessage() for r in caplog.records if r.name.startswith("weasyprint")] == []


def test_report_html_references_no_external_resource() -> None:
    """The stylesheet comes from package data, so the HTML needs no URL resolved."""
    html = PDFExporter().render_html(_sample_rmf())
    assert "<link" not in html
    assert not re.search(r"""(?:src|href)\s*=|url\(""", html)
