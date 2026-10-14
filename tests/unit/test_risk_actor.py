"""Who accepted a risk or recorded a mitigation (PRD-356): models, engine and exporters."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import jsonschema
import pytest
import yaml
from riskforge.engine.audit import AuditEngine
from riskforge.engine.actor import ActorNameError, normalise_actor_name
from riskforge.engine.risk import RiskEngine
from riskforge.exporters.markdown_exporter import MarkdownExporter
from riskforge.exporters.pdf.pdf_exporter import PDFExporter
from riskforge.models.audit import AuditActor
from riskforge.models.register import RiskRegister
from riskforge.models.risk import Likelihood, Mitigation, RiskDimension, RiskItem, Severity
from riskforge.models.rmf import RiskManagementFile
from riskforge.models.system import AISystem
from riskforge.storage.filesystem import FileStore

FIXTURE_REGISTER = Path(__file__).resolve().parents[1] / "fixtures/v1_1_3_project/register.yaml"
SCHEMA = Path(__file__).resolve().parents[2] / "src/riskforge/_data/schemas/rmf.schema.json"


def _mitigation(**kwargs) -> Mitigation:
    return Mitigation(
        description="Block release above a 0.10 parity gap",
        control_type="preventive",
        owner="ML team",
        status="implemented",
        **kwargs,
    )


def _item(**kwargs) -> RiskItem:
    return RiskItem(
        dimension=RiskDimension.discrimination,
        title="Bias",
        description="Desc.",
        likelihood=Likelihood.likely,
        severity=Severity.major,
        residual_likelihood=Likelihood.unlikely,
        residual_severity=Severity.minor,
        **kwargs,
    )


def _rmf(item: RiskItem) -> RiskManagementFile:
    system = AISystem(name="S", version="1", purpose="p", provider_name="P")
    now = datetime(2026, 10, 1, tzinfo=UTC)
    register = RiskRegister(
        system=system,
        assessor_name="A",
        assessor_role="R",
        assessment_date=now,
        review_date=now + timedelta(days=365),
        question_bank_version="1.0.0",
        items=[item],
    )
    return RiskManagementFile(register=register)


# --- models -------------------------------------------------------------------------


def test_unset_names_are_left_out_of_the_stored_document() -> None:
    item = _item(mitigations=[_mitigation()])
    dumped = item.model_dump(mode="json")
    assert "accepted_by" not in dumped
    assert "recorded_by" not in dumped["mitigations"][0]


def test_set_names_are_stored() -> None:
    item = _item(accepted_by="Jane", mitigations=[_mitigation(recorded_by="Sam")])
    dumped = item.model_dump(mode="json")
    assert dumped["accepted_by"] == "Jane"
    assert dumped["mitigations"][0]["recorded_by"] == "Sam"


def test_v113_register_rewrites_to_the_same_bytes() -> None:
    """A register 1.1.3 wrote loads and dumps back unchanged, so old items gain no keys."""
    stored = FIXTURE_REGISTER.read_bytes()
    register = RiskRegister.model_validate(yaml.safe_load(stored))
    rewritten = yaml.dump(register.model_dump(mode="json"), sort_keys=False, allow_unicode=True)
    assert rewritten.encode("utf-8") == stored


def test_rmf_1_0_0_leaves_the_names_out_and_validates() -> None:
    rmf = _rmf(_item(accepted=True, accepted_by="Jane", mitigations=[_mitigation(recorded_by="S")]))
    payload = rmf.model_dump(mode="json", by_alias=True)
    item = payload["register"]["items"][0]
    assert "accepted_by" not in item
    assert "recorded_by" not in item["mitigations"][0]
    jsonschema.validate(payload, json.loads(SCHEMA.read_text(encoding="utf-8")))
    # The register itself keeps them for the Markdown and PDF exporters.
    assert rmf.register.items[0].accepted_by == "Jane"


# --- actor name ---------------------------------------------------------------------


def test_normalise_actor_name_strips_surrounding_space() -> None:
    assert normalise_actor_name("  Jane Doe, Head of AI \t") == "Jane Doe, Head of AI"


@pytest.mark.parametrize("value", [None, "", "   ", "\t\n"])
def test_normalise_actor_name_treats_blank_as_missing(value: str | None) -> None:
    assert normalise_actor_name(value) is None


@pytest.mark.parametrize("value", ["Jane\nDoe", "Jane\rDoe", "Jane\x00", "Jane\x1b[31m", "a\x85b"])
def test_normalise_actor_name_rejects_control_characters(value: str) -> None:
    with pytest.raises(ActorNameError):
        normalise_actor_name(value)


# --- engine -------------------------------------------------------------------------


async def _engine(tmp_path: Path) -> tuple[RiskEngine, str, str]:
    store = FileStore(tmp_path)
    system = AISystem(name="S", version="1", purpose="p", provider_name="P")
    sid = str(system.id)
    await store.init_project("proj", {"system_name": system.name})
    await store.write_system(sid, system)
    engine = RiskEngine(store, AuditEngine(store, AuditActor(type="human", identity="Jane")))
    await engine.create_register(sid, "A", "R")
    item = await engine.add_risk(sid, _item())
    return engine, sid, str(item.id)


def test_accept_risk_stores_the_actor(tmp_path: Path) -> None:
    async def run() -> RiskItem:
        engine, sid, rid = await _engine(tmp_path)
        await engine.accept_risk(sid, rid, "Within appetite.", "Jane")
        return (await engine.list_risks(sid))[0]

    assert asyncio.run(run()).accepted_by == "Jane"


def test_add_mitigation_stores_recorded_by(tmp_path: Path) -> None:
    async def run() -> tuple[RiskItem, RiskItem]:
        engine, sid, rid = await _engine(tmp_path)
        await engine.add_mitigation(sid, rid, _mitigation(), recorded_by="Sam")
        await engine.add_mitigation(sid, rid, _mitigation())
        return (await engine.list_risks(sid))[0]

    item = asyncio.run(run())
    assert [m.recorded_by for m in item.mitigations] == ["Sam", None]


@pytest.mark.parametrize("value", ["", "  ", "Jane\nDoe"])
def test_accept_risk_refuses_a_blank_or_multi_line_actor(tmp_path: Path, value: str) -> None:
    async def run() -> None:
        engine, sid, rid = await _engine(tmp_path)
        await engine.accept_risk(sid, rid, "Within appetite.", value)

    with pytest.raises(ActorNameError):
        asyncio.run(run())


# --- exporters ----------------------------------------------------------------------


def test_markdown_shows_accepted_by_and_recorded_by() -> None:
    item = _item(
        accepted=True,
        acceptance_rationale="Within appetite.",
        accepted_by="Jane Doe, Head of AI",
        mitigations=[_mitigation(recorded_by="Sam Lee, ML Lead"), _mitigation()],
    )
    text = MarkdownExporter().render(_rmf(item)).decode("utf-8")
    assert "Accepted by: Jane Doe, Head of AI" in text
    assert "Recorded by: Sam Lee, ML Lead" in text
    assert text.count("Recorded by:") == 1


def test_markdown_says_when_the_acceptor_was_not_recorded() -> None:
    item = _item(accepted=True, acceptance_rationale="Within appetite.")
    text = MarkdownExporter().render(_rmf(item)).decode("utf-8")
    assert "Accepted by: not recorded" in text


def test_pdf_template_shows_accepted_by_and_recorded_by() -> None:
    item = _item(
        accepted=True,
        acceptance_rationale="Within appetite.",
        accepted_by="Jane Doe, Head of AI",
        mitigations=[_mitigation(recorded_by="Sam Lee, ML Lead")],
    )
    html = PDFExporter().render_html(_rmf(item))
    assert "Accepted by:</strong> Jane Doe, Head of AI" in html
    assert "Recorded by: Sam Lee, ML Lead" in html


def test_pdf_template_says_when_the_acceptor_was_not_recorded() -> None:
    html = PDFExporter().render_html(_rmf(_item(accepted=True, acceptance_rationale="Ok.")))
    assert "Accepted by:</strong> not recorded" in html
