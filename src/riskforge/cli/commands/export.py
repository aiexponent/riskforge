"""riskforge export: export the risk management file."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Optional  # noqa: UP007 (Typer 0.12.3 compat)

import typer
from rich.console import Console

console = Console()


def cmd(
    system_id: str = typer.Argument(..., help="System ID to export"),
    fmt: str = typer.Option("json", "--format", "-f", help="Export format: json, pdf, markdown"),
    output: Optional[Path] = typer.Option(None, "--output", "-o", help="Output file path"),
    project_dir: Path = typer.Option(Path("."), "--project-dir"),
    sign: Optional[str] = typer.Option(
        None, "--sign", help="GPG key id, email, or fingerprint to sign with (detached .asc)"
    ),
    force: bool = typer.Option(False, "--force", help="Skip validation gates"),
) -> None:
    """Export the Risk Management File to JSON, PDF, or Markdown.

    The export is SHA-256 signed, schema-validated, and linked to the
    audit trail. The output file is written with chmod 600.
    """

    from riskforge.cli.errors import EXIT_FAILED, EXIT_TAMPERED, fail
    from riskforge.cli.project import open_project, read_register_or_fail
    from riskforge.engine.audit import AuditEngine
    from riskforge.engine.export import ExportEngine, SigningError
    from riskforge.engine.validate import ValidateEngine
    from riskforge.models.audit import AuditActor
    from riskforge.models.rmf import RiskManagementFile
    from riskforge.plugins.registry import PluginRegistry

    registry = PluginRegistry()
    registry.load_all()
    if fmt not in registry.list_exporters():
        raise typer.BadParameter(
            f"unknown format '{fmt}'. Available: {', '.join(registry.list_exporters())}.",
            param_hint="'--format' / '-f'",
        )

    store = open_project(project_dir)

    # Pre-flight continuity check
    is_valid, violations = asyncio.run(store.verify_chain())
    if not is_valid:
        console.print(f"[red]✗[/red] Audit chain is corrupt: {violations}")
        raise typer.Exit(EXIT_TAMPERED)

    register = asyncio.run(read_register_or_fail(store, system_id))

    # Run validation gates unless --force
    if not force:
        val_engine = ValidateEngine()
        results = val_engine.run(register)
        if val_engine.has_failures(results):
            console.print(
                "[red]✗[/red] Validation failed. Run `riskforge validate` for details "
                "or use --force to override."
            )
            raise typer.Exit(EXIT_FAILED)

    # Build the RMF artefact, deriving test requirements and cross-references from
    # the register so they land in the exported file (both are deterministic).
    import datetime

    from riskforge.engine.tests import TestDerivationEngine

    rmf = RiskManagementFile(
        register=register,
        test_requirements=TestDerivationEngine().derive(register.items),
        cross_references=_build_cross_references(register.items),
        generated_at=datetime.datetime.now(datetime.UTC),
    )

    # Determine output path
    if output is None:
        ext = {"json": "json", "pdf": "pdf", "markdown": "md"}.get(fmt, fmt)
        export_id = str(rmf.id)[:8]
        output = project_dir / f"rmf-{system_id[:8]}-{export_id}.{ext}"

    actor = AuditActor(type="human", identity="cli")
    audit = AuditEngine(store, actor)
    engine = ExportEngine(registry, audit)

    try:
        result_path = asyncio.run(engine.export(rmf, fmt, output, sign_with=sign))
    except SigningError as exc:
        fail(str(exc))

    console.print(f"[green]✓[/green] Exported: [bold]{result_path}[/bold]")
    console.print(f"  SHA-256: [dim]{rmf.sha256_hash}[/dim]")


def _build_cross_references(items: list) -> list:
    """Cluster risk items by Article 9 reference for the RMF cross_references block.

    Each distinct article ref becomes one cluster listing the risk-item ids that
    carry it, with the first associated NIST and ISO reference for the cluster.
    """
    from collections import OrderedDict

    from riskforge.models.rmf import CrossReference

    clusters: OrderedDict[str, dict] = OrderedDict()
    for item in items:
        for art in item.article_refs:
            cluster = clusters.setdefault(art, {"ids": [], "nist": "", "iso": ""})
            cluster["ids"].append(item.id)
            if not cluster["nist"]:
                cluster["nist"] = (
                    item.nist_rmf_refs[0] if item.nist_rmf_refs else ""
                ) or item.nist_rmf_ref
            if not cluster["iso"]:
                cluster["iso"] = (
                    item.iso42001_refs[0] if item.iso42001_refs else ""
                ) or item.iso42001_ref
    return [
        CrossReference(
            article_ref=art,
            risk_item_ids=cluster["ids"],
            nist_rmf_ref=cluster["nist"],
            iso42001_ref=cluster["iso"],
        )
        for art, cluster in clusters.items()
    ]
