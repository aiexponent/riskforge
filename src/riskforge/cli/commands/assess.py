"""riskforge assess — interactive 8-dimension Article 9 risk assessment."""

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Optional  # noqa: UP007 — Typer 0.12.3 compat

import typer
from rich.console import Console
from rich.rule import Rule
from rich.table import Table

console = Console()

# ── Likelihood / Severity choice menus ────────────────────────────────────────
_LIKELIHOOD_CHOICES = [
    "1 — Rare          (almost impossible under normal operation)",
    "2 — Unlikely      (could happen, but not expected)",
    "3 — Possible      (might occur during normal operation)",
    "4 — Likely        (expected to occur in most circumstances)",
    "5 — Almost Certain (will occur in almost all circumstances)",
]
_SEVERITY_CHOICES = [
    "1 — Negligible (no meaningful harm)",
    "2 — Minor      (limited harm, easily corrected)",
    "3 — Moderate   (significant harm to individuals or groups)",
    "4 — Major      (serious harm, potential legal consequences)",
    "5 — Critical   (severe/irreversible harm, fundamental rights breach)",
]
_APPLIES_CHOICES = [
    "yes     — add as a risk item with scoring",
    "no      — not applicable to this system",
    "unknown — flag as knowledge gap (test requirement will be generated)",
    "skip    — defer this question (will appear as incomplete)",
]

_BAND_COLOUR = {
    "low": "green",
    "medium": "yellow",
    "high": "orange1",
    "critical": "red",
}


def cmd(
    system_id: str = typer.Argument(..., help="System ID from riskforge init"),
    project_dir: Path = typer.Option(Path("."), "--project-dir", "-d"),
    assessor_name: str = typer.Option(..., "--assessor-name", "-a", help="Full name of assessor"),
    assessor_role: str = typer.Option(..., "--assessor-role", "-r", help="Role/title of assessor"),
    dimension: Optional[str] = typer.Option(
        None, "--dimension", help="Scope to a single dimension (e.g. privacy)"
    ),
    review_months: int = typer.Option(12, "--review-months", help="Months until next review"),
    answers: Optional[Path] = typer.Option(
        None, "--answers", help="YAML answers file for a non-interactive assessment (for CI)"
    ),
) -> None:
    """Run the 8-dimension Article 9 risk assessment.

    Interactive by default: walks through each EU AI Act risk dimension, presents
    questions from the question bank, prompts for likelihood and severity scores,
    and writes every risk item to the register with a hash-chained audit entry.

    With --answers <file.yaml>, runs the same assessment non-interactively from a
    YAML answers file (suitable for CI re-assessment and reproducible fixtures).

    After completing the session, run:

        riskforge validate <system_id>
        riskforge export <system_id> --format pdf
    """
    if answers is not None:
        asyncio.run(
            _run_noninteractive(
                system_id=system_id,
                project_dir=project_dir,
                assessor_name=assessor_name,
                assessor_role=assessor_role,
                dimension_filter=dimension,
                review_months=review_months,
                answers_path=answers,
            )
        )
        return
    asyncio.run(
        _run_assess(
            system_id=system_id,
            project_dir=project_dir,
            assessor_name=assessor_name,
            assessor_role=assessor_role,
            dimension_filter=dimension,
            review_months=review_months,
        )
    )


async def _run_assess(
    system_id: str,
    project_dir: Path,
    assessor_name: str,
    assessor_role: str,
    dimension_filter: Optional[str],
    review_months: int,
) -> None:
    import questionary

    from riskforge.engine.assess import AssessEngine
    from riskforge.engine.audit import AuditEngine
    from riskforge.engine.risk import RiskEngine
    from riskforge.models.audit import AuditActor
    from riskforge.models.register import RiskRegister
    from riskforge.models.risk import Likelihood, RiskDimension, Severity
    from riskforge.storage.filesystem import FileStore

    # ── Bootstrap storage + engines ───────────────────────────────────────────
    store = FileStore(project_dir)

    # Pre-flight continuity check
    is_valid, violations = await store.verify_chain()
    if not is_valid:
        console.print(f"[red]✗[/red] Audit chain is corrupt: {violations}")
        raise typer.Exit(2)

    actor = AuditActor(type="human", identity=assessor_name)
    audit = AuditEngine(store, actor)
    risk_engine = RiskEngine(store, audit)

    # Locate bundled _data directory via package __file__
    import riskforge._data as _data_pkg  # noqa: PLC0415

    data_dir = Path(_data_pkg.__file__).parent
    assess = AssessEngine(data_dir)

    # ── Load system ────────────────────────────────────────────────────────────
    try:
        system = await store.read_system(system_id)
    except FileNotFoundError:
        console.print(
            f"[red]✗[/red] System [bold]{system_id}[/bold] not found in {project_dir}.\n"
            "Run [bold]riskforge init[/bold] first."
        )
        raise typer.Exit(1)

    # ── Get or create register ─────────────────────────────────────────────────
    try:
        register = await store.read_register(system_id)
        existing_count = len(register.items)
        if existing_count:
            console.print(
                f"[yellow]ℹ[/yellow]  Register already has {existing_count} item(s). "
                "New items will be appended."
            )
    except FileNotFoundError:
        register = RiskRegister(
            system=system,
            assessor_name=assessor_name,
            assessor_role=assessor_role,
            assessment_date=datetime.now(UTC),
            review_date=datetime.now(UTC) + timedelta(days=30 * review_months),
            question_bank_version="1.0.0",
        )
        await store.write_register(system_id, register)

    # ── Header ─────────────────────────────────────────────────────────────────
    console.print(Rule("[bold]RiskForge: EU AI Act Article 9 Assessment[/bold]"))
    console.print(f"  System:   [bold]{system.name} v{system.version}[/bold]")
    console.print(f"  Assessor: {assessor_name} ({assessor_role})")
    if system.annex_iii_category:
        console.print(
            f"  Category: [cyan]{system.annex_iii_category.value.replace('_', ' ').title()}[/cyan]"
        )
    console.print(
        "\nFor each question answer [green]yes[/green] / [red]no[/red] / "
        "[yellow]unknown[/yellow] / [dim]skip[/dim]. "
        "Press Ctrl+C at any time — progress is saved after each item.\n"
    )

    # ── Pattern matching ───────────────────────────────────────────────────────
    purpose_words = system.purpose.lower().split()
    category_str = str(system.annex_iii_category.value) if system.annex_iii_category else ""
    matched_patterns = assess.match_patterns(category_str, purpose_words)

    if matched_patterns:
        console.print(
            f"[cyan]✦[/cyan]  Found [bold]{len(matched_patterns)}[/bold] pre-defined risk "
            "pattern(s) for your system type:"
        )
        for p in matched_patterns:
            console.print(f"    • [bold]{p['name']}[/bold]")
        console.print()

        add_patterns = questionary.confirm(
            "Add pattern-derived risk items to the register?", default=True
        ).ask()

        if add_patterns:
            pattern_count = 0
            for pattern in matched_patterns:
                for risk_spec in pattern.get("risks", []):
                    from riskforge.models.risk import RiskItem

                    lh_hint = risk_spec.get("likelihood_hint", 3)
                    sv_hint = risk_spec.get("severity_hint", 3)
                    item = RiskItem(
                        dimension=RiskDimension(risk_spec["dimension"]),
                        title=risk_spec["title"][:120],
                        description=risk_spec.get("description", risk_spec["title"]),
                        source="pattern",
                        likelihood=Likelihood(lh_hint),
                        severity=Severity(sv_hint),
                        residual_likelihood=Likelihood(lh_hint),
                        residual_severity=Severity(sv_hint),
                        article_refs=risk_spec.get("article_refs", []),
                        nist_rmf_ref=risk_spec.get("nist_rmf_ref", ""),
                        iso42001_ref=risk_spec.get("iso42001_ref", ""),
                        tags=[f"pattern:{pattern['pattern_id']}"],
                    )
                    await risk_engine.add_risk(system_id, item)
                    pattern_count += 1
            console.print(f"[green]✓[/green] Added {pattern_count} pattern-derived risk item(s).\n")

    # ── Dimension question loop ────────────────────────────────────────────────
    if dimension_filter:
        try:
            dims_to_run = [RiskDimension(dimension_filter)]
        except ValueError:
            valid = [d.value for d in RiskDimension]
            console.print(
                f"[red]✗[/red] Unknown dimension '{dimension_filter}'. Valid: {', '.join(valid)}"
            )
            raise typer.Exit(1)
    else:
        dims_to_run = list(RiskDimension)

    # Pre-load all questions to know the total for progress display
    all_pairs: list[tuple[RiskDimension, dict]] = [
        (dim, q) for dim in dims_to_run for q in assess.load_questions(dim)
    ]
    total_q = len(all_pairs)

    if total_q == 0:
        console.print(
            "[yellow]No questions found in question bank for the selected dimension(s).[/yellow]"
        )
        raise typer.Exit(0)

    risks_added = 0
    gaps_added = 0
    skipped = 0
    current_dim: Optional[RiskDimension] = None

    try:
        for q_num, (dim, question) in enumerate(all_pairs, 1):
            # ── Dimension header when dimension changes ─────────────────────
            if dim != current_dim:
                current_dim = dim
                dim_idx = dims_to_run.index(dim) + 1
                console.print(
                    f"\n[bold cyan]── Dimension {dim_idx}/{len(dims_to_run)}: "
                    f"{dim.value.replace('_', ' ').title()} ──[/bold cyan]"
                )

            # ── Progress bar ────────────────────────────────────────────────
            pct = (q_num - 1) / total_q
            filled = int(pct * 12)
            bar = "█" * filled + "░" * (12 - filled)
            console.print(
                f"[dim]Q{q_num}/{total_q} | "
                f"{risks_added} risks · {gaps_added} unknown · {skipped} skipped | "
                f"{bar} {int(pct * 100)}%[/dim]"
            )

            # ── Question display ────────────────────────────────────────────
            console.print(f"\n  [bold]{question['text']}[/bold]")
            if question.get("guidance"):
                console.print(f"  [dim italic]{question['guidance']}[/dim italic]")
            if question.get("article_refs"):
                console.print(f"  [dim]Refs: {', '.join(question['article_refs'])}[/dim]")

            # ── Answer prompt ───────────────────────────────────────────────
            answer = questionary.select(
                "  Does this risk apply to your system?",
                choices=_APPLIES_CHOICES,
                use_shortcuts=True,
            ).ask()

            if answer is None:
                # Ctrl+C inside questionary returns None
                console.print("\n[yellow]Session interrupted. Progress saved.[/yellow]")
                break

            if answer.startswith("no"):
                continue

            if answer.startswith("skip"):
                skipped += 1
                continue

            is_unknown = answer.startswith("unknown")

            if is_unknown:
                # Use question's default hints; fall back to 3
                likelihood = int(question.get("default_likelihood_hint") or 3)
                severity = int(question.get("default_severity_hint") or 3)
                gaps_added += 1
                console.print(
                    f"  [yellow]↳ Flagged as knowledge gap.[/yellow] "
                    f"Likelihood hint: {likelihood}, Severity hint: {severity}"
                )
            else:
                # ── Likelihood ──────────────────────────────────────────────
                lh_raw = questionary.select(
                    "  Likelihood:",
                    choices=_LIKELIHOOD_CHOICES,
                    use_shortcuts=True,
                ).ask()
                if lh_raw is None:
                    console.print("\n[yellow]Session interrupted. Progress saved.[/yellow]")
                    break
                likelihood = int(lh_raw[0])

                # ── Severity ────────────────────────────────────────────────
                sv_raw = questionary.select(
                    "  Severity:",
                    choices=_SEVERITY_CHOICES,
                    use_shortcuts=True,
                ).ask()
                if sv_raw is None:
                    console.print("\n[yellow]Session interrupted. Progress saved.[/yellow]")
                    break
                severity = int(sv_raw[0])

                score = likelihood * severity
                band = (
                    "low"
                    if score <= 4
                    else "medium"
                    if score <= 9
                    else "high"
                    if score <= 16
                    else "critical"
                )
                col = _BAND_COLOUR[band]
                console.print(f"  [dim]Score: {score} → [{col}]{band.upper()}[/{col}][/dim]")
                risks_added += 1

            # ── Create and persist risk item ────────────────────────────────
            item = assess.question_to_risk_item(
                question, dim, likelihood, severity, answer_unknown=is_unknown
            )
            await risk_engine.add_risk(system_id, item)

    except KeyboardInterrupt:
        console.print("\n[yellow]Session interrupted. Progress saved.[/yellow]")

    # ── Session summary ────────────────────────────────────────────────────────
    console.print()
    console.print(Rule("[bold green]Assessment Session Complete[/bold green]"))

    summary = Table(show_header=False, box=None, padding=(0, 2))
    summary.add_column(style="dim")
    summary.add_column()

    total_added = risks_added + gaps_added
    register_now = await store.read_register(system_id)
    total_in_register = len(register_now.items)

    summary.add_row("Questions answered:", str(q_num if "q_num" in dir() else 0))
    summary.add_row("Risk items added this session:", f"[green]{risks_added}[/green]")
    summary.add_row("Knowledge gaps flagged:", f"[yellow]{gaps_added}[/yellow]")
    summary.add_row("Skipped:", str(skipped))
    summary.add_row("Total items in register:", f"[bold]{total_in_register}[/bold]")
    open_items = register_now.open_items()
    if open_items:
        summary.add_row(
            "Open (above threshold):",
            f"[red]{len(open_items)}[/red] — require mitigation or acceptance",
        )
    console.print(summary)

    if total_added == 0 and not matched_patterns:
        console.print(
            "\n[yellow]⚠[/yellow]  No risk items were added. "
            "This is unusual — review your answers before exporting."
        )

    console.print("\n[bold]Next steps:[/bold]")
    console.print(f"  riskforge validate [dim]{system_id}[/dim]")
    console.print(f"  riskforge export [dim]{system_id}[/dim] --format pdf --output rmf.pdf")
    if gaps_added:
        console.print(
            f"  riskforge tests generate [dim]{system_id}[/dim]  "
            f"[dim]({gaps_added} test requirement(s) to derive)[/dim]"
        )


async def _run_noninteractive(
    system_id: str,
    project_dir: Path,
    assessor_name: str,
    assessor_role: str,
    dimension_filter: Optional[str],
    review_months: int,
    answers_path: Path,
) -> None:
    """File-driven assessment: same engine path as interactive, no prompts.

    Setup mirrors _run_assess; only the answer source differs (a YAML file rather
    than questionary). Kept separate so the interactive, TTY-only path is untouched.
    """
    import yaml

    from riskforge.engine.assess import AssessEngine
    from riskforge.engine.audit import AuditEngine
    from riskforge.engine.risk import RiskEngine
    from riskforge.models.audit import AuditActor
    from riskforge.models.register import RiskRegister
    from riskforge.models.risk import Likelihood, RiskDimension, RiskItem, Severity
    from riskforge.storage.filesystem import FileStore

    if not answers_path.exists():
        console.print(f"[red]✗[/red] Answers file not found: {answers_path}")
        raise typer.Exit(1)
    try:
        answers_doc = yaml.safe_load(answers_path.read_text()) or {}
    except yaml.YAMLError as exc:
        console.print(f"[red]✗[/red] Could not parse answers file: {exc}")
        raise typer.Exit(1)
    if not isinstance(answers_doc, dict):
        console.print("[red]✗[/red] Answers file must be a YAML mapping.")
        raise typer.Exit(1)
    answers = answers_doc.get("answers", {}) or {}
    if not isinstance(answers, dict):
        console.print("[red]✗[/red] 'answers' must be a mapping of question id to answer.")
        raise typer.Exit(1)
    add_patterns = bool(answers_doc.get("add_patterns", True))

    store = FileStore(project_dir)
    is_valid, violations = await store.verify_chain()
    if not is_valid:
        console.print(f"[red]✗[/red] Audit chain is corrupt: {violations}")
        raise typer.Exit(2)

    actor = AuditActor(type="human", identity=assessor_name)
    audit = AuditEngine(store, actor)
    risk_engine = RiskEngine(store, audit)

    import riskforge._data as _data_pkg  # noqa: PLC0415

    assess = AssessEngine(Path(_data_pkg.__file__).parent)

    try:
        system = await store.read_system(system_id)
    except FileNotFoundError:
        console.print(
            f"[red]✗[/red] System [bold]{system_id}[/bold] not found in {project_dir}. "
            "Run riskforge init first."
        )
        raise typer.Exit(1)

    try:
        register = await store.read_register(system_id)
        _ = register
    except FileNotFoundError:
        register = RiskRegister(
            system=system,
            assessor_name=assessor_name,
            assessor_role=assessor_role,
            assessment_date=datetime.now(UTC),
            review_date=datetime.now(UTC) + timedelta(days=30 * review_months),
            question_bank_version="1.0.0",
        )
        await store.write_register(system_id, register)

    # Pattern injection (identical to the interactive path)
    purpose_words = system.purpose.lower().split()
    category_str = str(system.annex_iii_category.value) if system.annex_iii_category else ""
    matched_patterns = assess.match_patterns(category_str, purpose_words)
    pattern_count = 0
    if add_patterns:
        for pattern in matched_patterns:
            for risk_spec in pattern.get("risks", []):
                lh_hint = risk_spec.get("likelihood_hint", 3)
                sv_hint = risk_spec.get("severity_hint", 3)
                await risk_engine.add_risk(
                    system_id,
                    RiskItem(
                        dimension=RiskDimension(risk_spec["dimension"]),
                        title=risk_spec["title"][:120],
                        description=risk_spec.get("description", risk_spec["title"]),
                        source="pattern",
                        likelihood=Likelihood(lh_hint),
                        severity=Severity(sv_hint),
                        residual_likelihood=Likelihood(lh_hint),
                        residual_severity=Severity(sv_hint),
                        article_refs=risk_spec.get("article_refs", []),
                        nist_rmf_ref=risk_spec.get("nist_rmf_ref", ""),
                        iso42001_ref=risk_spec.get("iso42001_ref", ""),
                        tags=[f"pattern:{pattern['pattern_id']}"],
                    ),
                )
                pattern_count += 1

    if dimension_filter:
        try:
            dims_to_run = [RiskDimension(dimension_filter)]
        except ValueError:
            valid = [d.value for d in RiskDimension]
            console.print(
                f"[red]✗[/red] Unknown dimension '{dimension_filter}'. Valid: {', '.join(valid)}"
            )
            raise typer.Exit(1)
    else:
        dims_to_run = list(RiskDimension)

    risks_added = 0
    gaps_added = 0
    skipped = 0
    leftover = set(answers)
    for dim in dims_to_run:
        for question in assess.load_questions(dim):
            qid = question.get("id", "")
            leftover.discard(qid)
            ans = answers.get(qid)
            if ans is None:
                skipped += 1
                continue
            if not isinstance(ans, dict):
                console.print(f"[red]✗[/red] Answer for {qid} must be a mapping.")
                raise typer.Exit(1)
            # YAML parses bare yes/no as booleans; normalise them back.
            raw_applies = ans.get("applies", "skip")
            if raw_applies is True:
                applies = "yes"
            elif raw_applies is False:
                applies = "no"
            else:
                applies = str(raw_applies).lower()
            if applies == "no":
                continue
            if applies == "skip":
                skipped += 1
                continue
            if applies == "unknown":
                likelihood = int(question.get("default_likelihood_hint") or 3)
                severity = int(question.get("default_severity_hint") or 3)
                is_unknown = True
                gaps_added += 1
            elif applies == "yes":
                if "likelihood" not in ans or "severity" not in ans:
                    console.print(
                        f"[red]✗[/red] Answer for {qid} has applies: yes but no likelihood/severity."
                    )
                    raise typer.Exit(1)
                likelihood = int(ans["likelihood"])
                severity = int(ans["severity"])
                is_unknown = False
                risks_added += 1
            else:
                console.print(
                    f"[red]✗[/red] Answer for {qid} has invalid applies '{applies}' "
                    "(use yes, no, unknown, or skip)."
                )
                raise typer.Exit(1)
            await risk_engine.add_risk(
                system_id,
                assess.question_to_risk_item(
                    question, dim, likelihood, severity, answer_unknown=is_unknown
                ),
            )

    if leftover:
        console.print(
            f"[yellow]![/yellow] Ignored {len(leftover)} answer id(s) not in the question bank "
            f"for the selected dimension(s): {', '.join(sorted(leftover))}"
        )

    register_now = await store.read_register(system_id)
    console.print(
        f"[green]✓[/green] Non-interactive assessment complete: "
        f"{pattern_count} pattern, {risks_added} scored, {gaps_added} knowledge-gap item(s), "
        f"{skipped} skipped. Total in register: {len(register_now.items)}."
    )
    console.print(f"\nNext: [bold]riskforge validate {system_id}[/bold]")
