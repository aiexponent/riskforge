"""riskforge assess: interactive 8-dimension Article 9 risk assessment."""

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING, Optional  # noqa: UP007 (Typer 0.12.3 needs Optional)

import typer
from rich.console import Console
from rich.rule import Rule
from rich.table import Table

if TYPE_CHECKING:
    from riskforge.engine.risk import RiskEngine
    from riskforge.models.register import RiskRegister
    from riskforge.models.risk import RiskDimension, RiskItem
    from riskforge.storage.filesystem import FileStore

console = Console()

# ── Likelihood / Severity choice menus ────────────────────────────────────────
_LIKELIHOOD_CHOICES = [
    "1: Rare (almost impossible under normal operation)",
    "2: Unlikely (could happen, but not expected)",
    "3: Possible (might occur during normal operation)",
    "4: Likely (expected to occur in most circumstances)",
    "5: Almost Certain (will occur in almost all circumstances)",
]
_SEVERITY_CHOICES = [
    "1: Negligible (no meaningful harm)",
    "2: Minor (limited harm, easily corrected)",
    "3: Moderate (significant harm to individuals or groups)",
    "4: Major (serious harm, potential legal consequences)",
    "5: Critical (severe/irreversible harm, fundamental rights breach)",
]
_APPLIES_CHOICES = [
    "yes: add as a risk item with scoring",
    "no: not applicable to this system",
    "unknown: flag as a knowledge gap (a test requirement can be generated)",
    "skip: defer this question (it stays incomplete)",
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
    import sys

    from riskforge.cli.errors import fail
    from riskforge.cli.project import parse_dimension

    dimension_enum = parse_dimension(dimension)
    if answers is None and (sys.stdin is None or not sys.stdin.isatty()):
        fail(
            "Interactive assessment needs a terminal. Run it in a terminal, "
            "or pass --answers FILE (format: docs/user-guide.md, Non-interactive assessment)."
        )
    if answers is not None:
        asyncio.run(
            _run_noninteractive(
                system_id=system_id,
                project_dir=project_dir,
                assessor_name=assessor_name,
                assessor_role=assessor_role,
                dimension_filter=dimension_enum,
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
            dimension_filter=dimension_enum,
            review_months=review_months,
        )
    )


async def _run_assess(
    system_id: str,
    project_dir: Path,
    assessor_name: str,
    assessor_role: str,
    dimension_filter: Optional["RiskDimension"],
    review_months: int,
) -> None:
    import questionary

    from riskforge.cli.project import open_project, preflight, read_system_or_fail
    from riskforge.engine.assess import AssessEngine
    from riskforge.engine.audit import AuditEngine
    from riskforge.engine.risk import RiskEngine
    from riskforge.models.audit import AuditActor
    from riskforge.models.risk import Likelihood, RiskDimension, RiskItem, Severity

    # ── Bootstrap storage + engines ───────────────────────────────────────────
    store = open_project(project_dir)

    # Refuse a tampered project before the first prompt. The lock is not held while
    # the assessor answers; each saved item runs the check again in its own change.
    async with preflight(store):
        pass

    actor = AuditActor(type="human", identity=assessor_name)
    audit = AuditEngine(store, actor)
    risk_engine = RiskEngine(store, audit)

    # Locate bundled _data directory via package __file__
    import riskforge._data as _data_pkg  # noqa: PLC0415

    data_dir = Path(_data_pkg.__file__).parent
    assess = AssessEngine(data_dir)

    # ── Load system ────────────────────────────────────────────────────────────
    system = await read_system_or_fail(store, system_id)

    # ── Get or create register ─────────────────────────────────────────────────
    register, created = await risk_engine.create_register(
        system_id, assessor_name, assessor_role, review_months
    )
    if not created and register.items:
        console.print(
            f"[yellow]ℹ[/yellow]  Register already has {len(register.items)} item(s). "
            "Answers update the matching items; nothing is duplicated."
        )

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
        "Press Ctrl+C at any time. Progress is saved after each item.\n"
    )

    # ── Pattern matching ───────────────────────────────────────────────────────
    purpose_words = system.purpose.lower().split()
    category_str = str(system.annex_iii_category.value) if system.annex_iii_category else ""
    matched_patterns = assess.match_patterns(category_str, purpose_words)
    counts = {"added": 0, "updated": 0, "unchanged": 0}
    attention: list[RiskItem] = []
    answered_no_or_skip: set[str] = set()

    if matched_patterns:
        console.print(
            f"[cyan]✦[/cyan]  Found [bold]{len(matched_patterns)}[/bold] pre-defined risk "
            "pattern(s) for your system type:"
        )
        for p in matched_patterns:
            console.print(f"    • [bold]{p['name']}[/bold]")
        console.print()

        add_patterns = await questionary.confirm(
            "Add pattern-derived risk items to the register?", default=True
        ).ask_async()

        if add_patterns is None:
            # Ctrl+C: stop here rather than reading it as "no" and starting the questions.
            console.print("\n[yellow]Session interrupted. Progress saved.[/yellow]")
            return

        if add_patterns:
            for pattern in matched_patterns:
                for risk_spec in pattern.get("risks", []):
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
                    await _apply(risk_engine, system_id, item, counts, attention)
            console.print(
                f"[green]✓[/green] Pattern-derived risk items: {counts['added']} added, "
                f"{counts['updated']} updated, {counts['unchanged']} unchanged.\n"
            )

    # ── Dimension question loop ────────────────────────────────────────────────
    dims_to_run = [dimension_filter] if dimension_filter else list(RiskDimension)

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
            answer = await questionary.select(
                "  Does this risk apply to your system?",
                choices=_APPLIES_CHOICES,
                use_shortcuts=True,
            ).ask_async()

            if answer is None:
                # Ctrl+C inside questionary returns None
                console.print("\n[yellow]Session interrupted. Progress saved.[/yellow]")
                break

            if answer.startswith("no"):
                answered_no_or_skip.add(question.get("id", ""))
                continue

            if answer.startswith("skip"):
                answered_no_or_skip.add(question.get("id", ""))
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
                lh_raw = await questionary.select(
                    "  Likelihood:",
                    choices=_LIKELIHOOD_CHOICES,
                    use_shortcuts=True,
                ).ask_async()
                if lh_raw is None:
                    console.print("\n[yellow]Session interrupted. Progress saved.[/yellow]")
                    break
                likelihood = int(lh_raw[0])

                # ── Severity ────────────────────────────────────────────────
                sv_raw = await questionary.select(
                    "  Severity:",
                    choices=_SEVERITY_CHOICES,
                    use_shortcuts=True,
                ).ask_async()
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
            await _apply(risk_engine, system_id, item, counts, attention)

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
    summary.add_row("Items added:", f"[green]{counts['added']}[/green]")
    summary.add_row("Items updated:", str(counts["updated"]))
    summary.add_row("Items unchanged:", str(counts["unchanged"]))
    summary.add_row("Knowledge gaps flagged:", f"[yellow]{gaps_added}[/yellow]")
    summary.add_row("Skipped:", str(skipped))
    summary.add_row("Total items in register:", f"[bold]{total_in_register}[/bold]")
    open_items = register_now.open_items()
    if open_items:
        summary.add_row(
            "Open (above threshold):",
            f"[red]{len(open_items)}[/red] (require mitigation or acceptance)",
        )
    console.print(summary)
    _print_review_notices(register_now, attention, answered_no_or_skip)

    if total_added == 0 and not matched_patterns:
        console.print(
            "\n[yellow]⚠[/yellow]  No risk items were added. "
            "This is unusual. Review your answers before exporting."
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
    dimension_filter: Optional["RiskDimension"],
    review_months: int,
    answers_path: Path,
) -> None:
    """File-driven assessment: same engine path as interactive, no prompts.

    Setup mirrors _run_assess; only the answer source differs (a YAML file rather
    than questionary). Kept separate so the interactive, TTY-only path is untouched.
    """
    import yaml

    from riskforge.cli.errors import fail
    from riskforge.cli.project import open_project, preflight

    if not answers_path.is_file():
        fail(f"Answers file not found: {answers_path}")
    try:
        answers_doc = yaml.safe_load(answers_path.read_text(encoding="utf-8")) or {}
    except UnicodeDecodeError:
        fail(f"Could not parse answers file: {answers_path} is not a text file.")
    except yaml.YAMLError as exc:
        fail(f"Could not parse answers file: {' '.join(str(exc).split())}")
    if not isinstance(answers_doc, dict):
        fail("Answers file must be a YAML mapping.")
    answers = answers_doc.get("answers", {}) or {}
    if not isinstance(answers, dict):
        fail("'answers' must be a mapping of question id to answer.")
    add_patterns = bool(answers_doc.get("add_patterns", True))

    store = open_project(project_dir)
    async with preflight(store):
        await _assess_from_answers(
            store,
            system_id,
            assessor_name,
            assessor_role,
            dimension_filter,
            review_months,
            answers,
            add_patterns,
        )


async def _assess_from_answers(
    store: "FileStore",
    system_id: str,
    assessor_name: str,
    assessor_role: str,
    dimension_filter: Optional["RiskDimension"],
    review_months: int,
    answers: dict,
    add_patterns: bool,
) -> None:
    """The non-interactive assessment, run inside the caller's checked unit of work."""
    from riskforge.cli.errors import fail
    from riskforge.cli.project import read_system_or_fail
    from riskforge.engine.assess import AssessEngine
    from riskforge.engine.audit import AuditEngine
    from riskforge.engine.risk import RiskEngine
    from riskforge.models.audit import AuditActor
    from riskforge.models.risk import Likelihood, RiskDimension, RiskItem, Severity

    actor = AuditActor(type="human", identity=assessor_name)
    audit = AuditEngine(store, actor)
    risk_engine = RiskEngine(store, audit)

    import riskforge._data as _data_pkg  # noqa: PLC0415

    assess = AssessEngine(Path(_data_pkg.__file__).parent)

    system = await read_system_or_fail(store, system_id)

    register, created = await risk_engine.create_register(
        system_id, assessor_name, assessor_role, review_months
    )
    if not created and register.items:
        console.print(
            f"[yellow]ℹ[/yellow]  Register already has {len(register.items)} item(s). "
            "Answers update the matching items; nothing is duplicated."
        )

    # Pattern injection (identical to the interactive path)
    purpose_words = system.purpose.lower().split()
    category_str = str(system.annex_iii_category.value) if system.annex_iii_category else ""
    matched_patterns = assess.match_patterns(category_str, purpose_words)
    counts = {"added": 0, "updated": 0, "unchanged": 0}
    attention: list[RiskItem] = []
    answered_no_or_skip: set[str] = set()
    if add_patterns:
        for pattern in matched_patterns:
            for risk_spec in pattern.get("risks", []):
                lh_hint = risk_spec.get("likelihood_hint", 3)
                sv_hint = risk_spec.get("severity_hint", 3)
                await _apply(
                    risk_engine,
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
                    counts,
                    attention,
                )

    dims_to_run = [dimension_filter] if dimension_filter else list(RiskDimension)

    gaps_added = 0
    skipped = 0
    leftover = set(answers)
    for dim in dims_to_run:
        for question in assess.load_questions(dim):
            qid = question.get("id", "")
            leftover.discard(qid)
            ans = answers.get(qid)
            if ans is None:
                answered_no_or_skip.add(qid)
                skipped += 1
                continue
            if not isinstance(ans, dict):
                fail(f"Answer for {qid} must be a mapping.")
            # YAML parses bare yes/no as booleans; normalise them back.
            raw_applies = ans.get("applies", "skip")
            if raw_applies is True:
                applies = "yes"
            elif raw_applies is False:
                applies = "no"
            else:
                applies = str(raw_applies).lower()
            if applies == "no":
                answered_no_or_skip.add(qid)
                continue
            if applies == "skip":
                answered_no_or_skip.add(qid)
                skipped += 1
                continue
            if applies == "unknown":
                likelihood = int(question.get("default_likelihood_hint") or 3)
                severity = int(question.get("default_severity_hint") or 3)
                is_unknown = True
                gaps_added += 1
            elif applies == "yes":
                if "likelihood" not in ans or "severity" not in ans:
                    fail(f"Answer for {qid} has applies: yes but no likelihood/severity.")
                likelihood = _answer_score(qid, "likelihood", ans["likelihood"])
                severity = _answer_score(qid, "severity", ans["severity"])
                is_unknown = False
            else:
                fail(
                    f"Answer for {qid} has invalid applies '{applies}' "
                    "(use yes, no, unknown, or skip)."
                )
            await _apply(
                risk_engine,
                system_id,
                assess.question_to_risk_item(
                    question, dim, likelihood, severity, answer_unknown=is_unknown
                ),
                counts,
                attention,
            )

    if leftover:
        console.print(
            f"[yellow]![/yellow] Ignored {len(leftover)} answer id(s) not in the question bank "
            f"for the selected dimension(s): {', '.join(sorted(leftover))}"
        )

    register_now = await store.read_register(system_id)
    console.print(
        f"[green]✓[/green] Non-interactive assessment complete: {counts['added']} added, "
        f"{counts['updated']} updated, {counts['unchanged']} unchanged, "
        f"{gaps_added} knowledge-gap answer(s), {skipped} skipped. "
        f"Total in register: {len(register_now.items)}."
    )
    _print_review_notices(register_now, attention, answered_no_or_skip)
    console.print(f"\nNext: [bold]riskforge validate {system_id}[/bold]")


async def _apply(
    risk_engine: "RiskEngine",
    system_id: str,
    item: "RiskItem",
    counts: dict[str, int],
    attention: "list[RiskItem]",
) -> None:
    """Add or update ``item`` by its origin; note updated items a person has worked on."""
    outcome, stored = await risk_engine.upsert_item(system_id, item)
    counts[outcome] += 1
    reworked = (stored.residual_likelihood, stored.residual_severity) != (
        stored.likelihood,
        stored.severity,
    )
    if outcome == "updated" and (stored.mitigations or stored.accepted or reworked):
        attention.append(stored)


def _print_review_notices(
    register: "RiskRegister", attention: "list[RiskItem]", answered_no_or_skip: set[str]
) -> None:
    """List updated items to review, and kept items whose question is now no or skip."""
    from rich.markup import escape

    for item in attention:
        reasons = []
        if item.mitigations:
            reasons.append(f"has {len(item.mitigations)} mitigation(s)")
        elif (item.residual_likelihood, item.residual_severity) != (
            item.likelihood,
            item.severity,
        ):
            reasons.append("has a re-scored residual")
        if item.accepted:
            reasons.append("is accepted")
        title = item.title if len(item.title) <= 60 else f"{item.title[:57]}..."
        console.print(
            f"[yellow]![/yellow] {str(item.id)[:8]} {escape(title)}: the new answer changed its "
            f"inherent score to {item.risk_score} (residual {item.residual_risk_score}). "
            f"It {' and '.join(reasons)}; review its residual score and acceptance."
        )
    kept = sorted(
        {
            item.tags[0]
            for item in register.items
            if item.source == "question_bank" and item.tags and item.tags[0] in answered_no_or_skip
        }
    )
    if kept:
        console.print(
            f"[yellow]![/yellow] Answered no or skip this time but kept in the register: "
            f"{', '.join(kept)}. assess never removes items; review them with "
            "riskforge risk list."
        )


def _answer_score(qid: str, name: str, value: object) -> int:
    """A 1-5 score from the answers file, or exit 3 naming the bad value."""
    from riskforge.cli.errors import fail

    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 5:
        fail(f"Answer for {qid} has {name} {value!r}; use a whole number from 1 to 5.")
    return value
