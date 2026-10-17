"""riskforge export: export the risk management file."""

from __future__ import annotations

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
    sign: Optional[Path] = typer.Option(
        None,
        "--sign",
        help="Ed25519 private key file to sign the export with (create one with riskforge keygen)",
    ),
    public_key: Optional[list[Path]] = typer.Option(
        None,
        "--public-key",
        help=(
            "Ed25519 public key file (PEM) of a key that signed audit entries in this "
            "project, embedded so the chain proof can be checked. Repeatable."
        ),
    ),
    force: bool = typer.Option(False, "--force", help="Export even if a validation gate fails"),
) -> None:
    """Export the Risk Management File to JSON, PDF or Markdown.

    Every format of one register state shows the same content digest (SHA-256). The file
    embeds a chain proof (the project audit log up to the export) and a receipt for its
    last entry, and with --sign an Ed25519 signature and its public key. An audit entry
    signed outside the CLI needs its public key given with --public-key. The file is
    written in full, with mode 600 on Linux and macOS, before the export is recorded in
    the audit log as rmf.exported. A register last written by an older RiskForge is first
    rewritten in the current format, recorded as register.checkpoint; no value changes.

    Exit codes:
      0: exported
      1: a validation gate failed (run `riskforge validate`, or use --force), or the
         export could not be built; nothing was written
      2: the project failed its integrity check; nothing was written
      3: no project or no such system, unknown format, the output directory is missing
         or cannot be written, the output path is a directory or lies inside .riskforge/
         or is riskforge.yaml, the --sign or --public-key key file is refused, or a
         signed audit entry has no --public-key
    """
    import asyncio
    import uuid

    from rich.markup import escape

    from riskforge.cli.errors import EXIT_FAILED, EXIT_TAMPERED, fail
    from riskforge.cli.project import (
        load_signer,
        load_trusted_keys,
        open_project,
        print_integrity_warnings,
        print_refusal,
        read_register_or_fail,
    )
    from riskforge.engine.audit import AuditEngine
    from riskforge.engine.export import (
        CheckpointError,
        EntrySignatureError,
        ExportEngine,
        ExportTargetError,
        MissingPublicKeyError,
        SchemaViolationError,
        ValidationGateError,
    )
    from riskforge.engine.integrity import IntegrityError
    from riskforge.models.audit import AuditActor
    from riskforge.plugins.registry import PluginRegistry

    registry = PluginRegistry()
    registry.load_all()
    if fmt not in registry.list_exporters():
        raise typer.BadParameter(
            f"unknown format '{fmt}'. Available: {', '.join(registry.list_exporters())}.",
            param_hint="'--format' / '-f'",
        )
    signer = load_signer(sign) if sign is not None else None
    public_keys = load_trusted_keys(public_key or [])
    store = open_project(project_dir)
    export_id = uuid.uuid4()
    if output is None:
        ext = {"json": "json", "pdf": "pdf", "markdown": "md"}.get(fmt, fmt)
        output = project_dir / f"rmf-{system_id[:8]}-{str(export_id)[:8]}.{ext}"
    audit = AuditEngine(store, AuditActor(type="human", identity="cli"))
    engine = ExportEngine(registry, audit, store)

    async def _export():
        async with audit.unit_of_work() as report:
            if report is not None:
                print_integrity_warnings(report)
            await read_register_or_fail(store, system_id)
            return await engine.export(
                system_id,
                fmt,
                output,
                force=force,
                signer=signer,
                export_id=export_id,
                public_keys=public_keys,
            )

    try:
        result = asyncio.run(_export())
    except IntegrityError as exc:
        print_refusal(exc)
        raise typer.Exit(EXIT_TAMPERED) from None
    except ValidationGateError:
        fail(
            "Validation failed, so nothing was exported. Run `riskforge validate` for "
            "details, or use --force.",
            EXIT_FAILED,
        )
    except EntrySignatureError as exc:
        fail(str(exc), EXIT_TAMPERED)
    except (ExportTargetError, MissingPublicKeyError) as exc:
        fail(str(exc))
    except (CheckpointError, SchemaViolationError) as exc:
        fail(str(exc), EXIT_FAILED)

    console.print(
        f"[green]✓[/green] Exported: [bold]{escape(str(result.path))}[/bold]", soft_wrap=True
    )
    console.print(f"  Content digest (SHA-256): [dim]{result.content_digest}[/dim]", soft_wrap=True)
    console.print(f"  File SHA-256: [dim]{result.file_sha256}[/dim]", soft_wrap=True)
    if signer is not None:
        console.print(f"  Signed by: [dim]{signer.key_id}[/dim]", soft_wrap=True)
    if result.checkpoint is not None:
        console.print(
            "  The register was rewritten in the current format first (register.checkpoint, "
            f"seq {result.checkpoint.seq}); no value changed.",
            soft_wrap=True,
        )
