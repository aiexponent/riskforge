#!/usr/bin/env python3
"""Replay the RiskForge flow from verification inputs and check what it produces.

Run it through verification/run.sh, which installs the pinned RiskForge first:

    python replay.py --inputs DIR --out DIR [--riskforge PATH] [--baseline FILE]

The flow runs twice, each time in a new project, through the riskforge command
exactly as a user types it: init, system classify, assess --answers, risk list,
risk mitigate and risk accept from decisions.yaml, tests generate, validate,
export (JSON signed, Markdown, PDF) and verify. Then it checks:

- every command exits as expected;
- the three formats of one register carry the same content digest, and the
  digest recomputed through riskforge.api matches the one in the file;
- exporting the same register again gives the same digest;
- the two runs give the same RMF once the fields that are new in every run
  (random ids and timestamps) are replaced by placeholders;
- one changed byte in the RMF content or its signature fails
  `riskforge verify --file`, and restoring it passes again;
- one changed byte in a register file or the audit log fails `riskforge verify`
  on a copy of the project, and restoring it passes again;
- the PDF opens in pypdf and has at least one page, and the Markdown names the digest;
- both runs reach the same validate gate results.

A failing validate gate is the tool's verdict on the inputs, not a fault in the tool,
so it is recorded (gates.json) and the export goes ahead with --force, as a user who
accepts the result would do.

With --baseline, the normalised RMF and the gate results are also compared with the
committed ones (rmf.normalised.json and the gates.json beside it).

Exit codes: 0 every check passed; 1 checks passed but the RMF differs from the
baseline; 2 a check failed; 3 the inputs are incomplete (no decisions.yaml yet:
the first run stops after `risk list` so the decisions can be written).

Only the functions near the top are imported by the unit tests, which run with
the standard library alone. PyYAML, pypdf and riskforge are imported when used.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
from collections.abc import Iterator
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
SHORT_ID_RE = re.compile(r"(?<![\w-])[0-9a-f]{8}(?![\w-])")
TIME_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})")
VERSION_RE = re.compile(r"RiskForge v\d+\.\d+\.\d+\S*")
DIGEST_RE = re.compile(r"Content digest \(SHA-256\):\s*([0-9a-f]{64})")
SYSTEM_ID_RE = re.compile(r"System ID:\s*(" + UUID_RE.pattern + ")")

# The fields RiskForge documents as new in every export (ADR-04): left out of the
# content digest, and left out of the comparison between two runs.
PROVENANCE_FIELDS = (
    "id",
    "generated_at",
    "sha256_hash",
    "signatures",
    "public_keys",
    "chain_proof",
    "receipt",
)
TITLE_COLUMN = 40  # `riskforge risk list` prints the first 40 characters of a title
CONTROL_TYPES = ("preventive", "detective", "corrective")
STATUSES = ("planned", "implemented", "verified")


class InputError(ValueError):
    """An input file is missing a field or names a risk that is not in the register."""


# --------------------------------------------------------------------------- pure helpers


def normalise_rmf(document: dict[str, Any]) -> dict[str, Any]:
    """The RMF with what changes on every run replaced, so two runs can be compared.

    Provenance fields are dropped. Each UUID becomes ``<uuid-N>``, numbered in the
    order it first appears when keys are read in sorted order, so the same item gets
    the same placeholder wherever it is referenced. A short id, the first 8 characters
    of one of those UUIDs on its own (schema 1.2.0 gate details list risks that way),
    gets the placeholder of its UUID. Timestamps become ``<time>`` and the RiskForge
    version in the disclosure becomes ``RiskForge v<version>``.
    """
    body = {k: v for k, v in document.items() if k not in PROVENANCE_FIELDS}
    numbers: dict[str, str] = {}

    def strings(value: Any) -> Iterator[str]:
        """Every string in ``value``, in the order ``walk`` reads them."""
        if isinstance(value, dict):
            for k in sorted(value):
                yield from strings(value[k])
        elif isinstance(value, list):
            for v in value:
                yield from strings(v)
        elif isinstance(value, str):
            yield value

    for text in strings(body):
        for found in UUID_RE.findall(text):
            numbers.setdefault(found, f"<uuid-{len(numbers) + 1}>")
    prefixes: dict[str, list[str]] = {}
    for full, placeholder in numbers.items():
        prefixes.setdefault(full[:8], []).append(placeholder)
    short = {prefix: hits[0] for prefix, hits in prefixes.items() if len(hits) == 1}

    def walk(value: Any) -> Any:
        """``value`` with its keys sorted and every string normalised."""
        if isinstance(value, dict):
            return {k: walk(value[k]) for k in sorted(value)}
        if isinstance(value, list):
            return [walk(v) for v in value]
        if isinstance(value, str):
            text = UUID_RE.sub(lambda m: numbers[m.group(0)], value)
            text = SHORT_ID_RE.sub(lambda m: short.get(m.group(0), m.group(0)), text)
            text = TIME_RE.sub("<time>", text)
            return VERSION_RE.sub("RiskForge v<version>", text)
        return value

    return walk(body)


def first_difference(a: Any, b: Any, path: str = "$") -> str | None:
    """The JSON path of the first place two values differ, or None when they are equal."""
    if type(a) is not type(b):
        return f"{path}: {type(a).__name__} vs {type(b).__name__}"
    if isinstance(a, dict):
        for key in sorted(set(a) | set(b)):
            if key not in a or key not in b:
                return f"{path}.{key}: only in {'second' if key not in a else 'first'}"
            found = first_difference(a[key], b[key], f"{path}.{key}")
            if found:
                return found
        return None
    if isinstance(a, list):
        if len(a) != len(b):
            return f"{path}: {len(a)} vs {len(b)} entries"
        for index, (x, y) in enumerate(zip(a, b, strict=False)):
            found = first_difference(x, y, f"{path}[{index}]")
            if found:
                return found
        return None
    return None if a == b else f"{path}: {a!r} vs {b!r}"


def parse_digest(stdout: str) -> str | None:
    """The content digest `riskforge export` prints, or None."""
    match = DIGEST_RE.search(stdout)
    return match.group(1) if match else None


def parse_system_id(stdout: str) -> str | None:
    """The system id `riskforge init` prints, or None."""
    match = SYSTEM_ID_RE.search(stdout)
    return match.group(1) if match else None


def flip_one_byte(data: bytes, anchor: bytes) -> tuple[int, bytes]:
    """Swap the case of the first ASCII letter after ``anchor``: one changed byte.

    Returns the offset of the changed byte and the changed data. Raises ValueError
    when the anchor or a letter after it is missing.
    """
    start = data.find(anchor)
    if start < 0:
        raise ValueError(f"anchor {anchor!r} not found")
    for offset in range(start + len(anchor), len(data)):
        byte = data[offset]
        if 65 <= byte <= 90 or 97 <= byte <= 122:
            changed = bytearray(data)
            changed[offset] = byte ^ 0x20
            return offset, bytes(changed)
    raise ValueError(f"no letter after anchor {anchor!r}")


def check_system_inputs(data: Any) -> dict[str, Any]:
    """The init and assess parameters from system.yaml, checked."""
    if not isinstance(data, dict):
        raise InputError("system.yaml must be a mapping")
    required = ("name", "version", "purpose", "provider", "assessor_name", "assessor_role")
    missing = [k for k in required if not str(data.get(k) or "").strip()]
    if missing:
        raise InputError(f"system.yaml is missing {', '.join(missing)}")
    unknown = sorted(set(data) - set(required) - {"category", "review_months"})
    if unknown:
        raise InputError(f"system.yaml has unknown keys: {', '.join(unknown)}")
    return {k: str(v) for k, v in data.items() if v is not None}


def check_decisions(data: Any) -> dict[str, Any]:
    """The mitigations and acceptances from decisions.yaml, checked."""
    if not isinstance(data, dict):
        raise InputError("decisions.yaml must be a mapping")
    by = str(data.get("by") or "").strip()
    if not by:
        raise InputError('decisions.yaml needs `by: "Name, Role"`')
    unknown = sorted(set(data) - {"by", "mitigations", "acceptances"})
    if unknown:
        raise InputError(f"decisions.yaml has unknown keys: {', '.join(unknown)}")
    mitigations = data.get("mitigations") or []
    acceptances = data.get("acceptances") or []
    if not isinstance(mitigations, list) or not isinstance(acceptances, list):
        raise InputError("mitigations and acceptances must be lists")
    for number, m in enumerate(mitigations, start=1):
        where = f"mitigation {number}"
        if not isinstance(m, dict):
            raise InputError(f"{where} must be a mapping")
        for key in ("risk", "description", "control_type", "owner"):
            if not str(m.get(key) or "").strip():
                raise InputError(f"{where} is missing {key}")
        if m["control_type"] not in CONTROL_TYPES:
            raise InputError(f"{where}: control_type must be one of {', '.join(CONTROL_TYPES)}")
        if m.get("status", "planned") not in STATUSES:
            raise InputError(f"{where}: status must be one of {', '.join(STATUSES)}")
        for key in ("residual_likelihood", "residual_severity"):
            value = m.get(key)
            if value is not None and (not isinstance(value, int) or not 1 <= value <= 5):
                raise InputError(f"{where}: {key} must be a whole number from 1 to 5")
    for number, a in enumerate(acceptances, start=1):
        where = f"acceptance {number}"
        if not isinstance(a, dict):
            raise InputError(f"{where} must be a mapping")
        for key in ("risk", "rationale"):
            if not str(a.get(key) or "").strip():
                raise InputError(f"{where} is missing {key}")
    return {"by": by, "mitigations": mitigations, "acceptances": acceptances}


def match_risk(items: list[tuple[str, str, str]], title: str) -> str:
    """The id of the one item whose title starts with ``title`` (as `risk list` shows it).

    ``items`` are (id, full title, bank question) triples. A bank item also matches on
    the start of its question: before RiskForge 2.1.0 its title was the question text,
    and since 2.1.0 its description starts with ``Question <id>: <question>``. Raises
    InputError when no item or more than one item matches, so a decision never lands on
    the wrong risk.
    """
    key = title.strip()
    if not key:
        raise InputError("a decision names an empty risk title")
    hits = [
        rid
        for rid, full, question in items
        if full.startswith(key) or full[:TITLE_COLUMN] == key or question.startswith(key)
    ]
    if not hits:
        raise InputError(f"no risk item has a title starting {key!r}")
    if len(hits) > 1:
        raise InputError(f"{len(hits)} risk items have a title starting {key!r}")
    return hits[0]


QUESTION_PREFIX = re.compile(r"Question [A-Z]{2}-\d{3}: ")


def bank_question(description: str) -> str:
    """The question of a bank item from its description, or "" for any other item."""
    found = QUESTION_PREFIX.match(description)
    return description[found.end() :] if found else ""


def redact(argv: list[str], out: Path) -> list[str]:
    """argv with the output folder written as $OUT, for a results file that reads the same anywhere."""
    prefix = str(out)
    return [a.replace(prefix, "$OUT") for a in argv]


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# --------------------------------------------------------------------------- running riskforge


@dataclass
class Step:
    name: str
    argv: list[str]
    exit_code: int
    expected: int
    log: str

    @property
    def ok(self) -> bool:
        return self.exit_code == self.expected


@dataclass
class Check:
    id: str
    passed: bool
    detail: str


@dataclass
class Run:
    label: str
    steps: list[Step] = field(default_factory=list)
    system_id: str | None = None
    forced_export: bool = False
    gates: dict[str, str] = field(default_factory=dict)
    files: dict[str, str] = field(default_factory=dict)
    digests: dict[str, str | None] = field(default_factory=dict)


class Replay:
    def __init__(self, riskforge: str, out: Path) -> None:
        self.riskforge = riskforge
        self.out = out
        self.env = {k: v for k, v in os.environ.items() if k != "RISKFORGE_ACTOR"}
        # A wide, colourless terminal, so `risk list` prints whole rows the same way everywhere.
        self.env.update({"COLUMNS": "160", "NO_COLOR": "1", "TERM": "dumb"})

    def call(self, run: Run, name: str, args: list[str], expected: int = 0) -> tuple[Step, str]:
        logs = self.out / f"run-{run.label}" / "logs"
        logs.mkdir(parents=True, exist_ok=True)
        argv = [self.riskforge, *args]
        done = subprocess.run(  # noqa: S603 - fixed program, arguments from checked inputs
            argv,
            capture_output=True,
            text=True,
            env=self.env,
            stdin=subprocess.DEVNULL,
            timeout=600,
            check=False,
        )
        log = logs / f"{len(run.steps) + 1:02d}-{name}.txt"
        shown = ["riskforge", *redact(args, self.out)]
        log.write_text(
            f"$ {' '.join(shown)}\nexit {done.returncode}\n\n--- stdout\n{done.stdout}"
            f"\n--- stderr\n{done.stderr}",
            encoding="utf-8",
        )
        step = Step(name, shown, done.returncode, expected, str(log.relative_to(self.out)))
        run.steps.append(step)
        return step, done.stdout

    def verify_file(self, path: Path, public_key: Path) -> int:
        done = subprocess.run(  # noqa: S603
            [self.riskforge, "verify", "--file", str(path), "--trusted-key", str(public_key)],
            capture_output=True,
            text=True,
            env=self.env,
            stdin=subprocess.DEVNULL,
            timeout=300,
            check=False,
        )
        return done.returncode

    def verify_project(self, project: Path) -> int:
        done = subprocess.run(  # noqa: S603
            [self.riskforge, "verify", "--project-dir", str(project)],
            capture_output=True,
            text=True,
            env=self.env,
            stdin=subprocess.DEVNULL,
            timeout=300,
            check=False,
        )
        return done.returncode


def load_yaml(path: Path) -> Any:
    import yaml  # PyYAML is a dependency of riskforge

    with path.open(encoding="utf-8") as handle:
        return yaml.safe_load(handle)


async def register_titles(project: Path, system_id: str) -> list[tuple[str, str, str]]:
    """(id, title, bank question) of every risk item, read through the public API without writing."""
    import riskforge.api as rf

    store = rf.FileStore(project, read_only=True)
    audit = rf.AuditEngine(store, rf.AuditActor(type="api", identity="verification-replay"))
    items = await rf.RiskEngine(store, audit).list_risks(system_id)
    return [(str(item.id), item.title, bank_question(item.description)) for item in items]


async def gate_results(project: Path, system_id: str) -> dict[str, str]:
    """{gate id: PASS, WARN or FAIL}, from riskforge.api.ValidateEngine on the stored register."""
    import riskforge.api as rf

    store = rf.FileStore(project, read_only=True)
    register = await store.read_register(system_id)
    return {g.gate_id: g.status.value for g in rf.ValidateEngine().run(register)}


def replay_once(
    replay: Replay,
    label: str,
    inputs: Path,
    system: dict[str, Any],
    decisions: dict[str, Any] | None,
    private_key: Path,
) -> Run:
    run = Run(label)
    base = replay.out / f"run-{label}"
    project = base / "project"
    exports = base / "export"
    project.mkdir(parents=True)
    exports.mkdir(parents=True)
    pdir = ["--project-dir", str(project)]

    init_args = [
        "init",
        "--name", system["name"],
        "--sys-version", system["version"],
        "--purpose", system["purpose"],
        "--provider", system["provider"],
        *(["--category", system["category"]] if system.get("category") else []),
        *pdir,
        "--non-interactive",
    ]  # fmt: skip
    step, stdout = replay.call(run, "init", init_args)
    run.system_id = parse_system_id(stdout)
    if not step.ok or not run.system_id:
        return run
    sid = run.system_id

    replay.call(run, "classify", ["system", "classify", sid, "--confirm", *pdir])
    assess = [
        "assess", sid, *pdir,
        "--assessor-name", system["assessor_name"],
        "--assessor-role", system["assessor_role"],
        "--answers", str(inputs / "answers.yaml"),
        *(["--review-months", system["review_months"]] if system.get("review_months") else []),
    ]  # fmt: skip
    step, _ = replay.call(run, "assess", assess)
    if not step.ok:
        return run
    step, stdout = replay.call(run, "risk-list", ["risk", "list", sid, *pdir])
    (base / "risk-list.txt").write_text(stdout, encoding="utf-8")
    if decisions is None or not all(s.ok for s in run.steps):
        return run

    titles = asyncio.run(register_titles(project, sid))
    for number, m in enumerate(decisions["mitigations"], start=1):
        rid = match_risk(titles, m["risk"])
        args = [
            "risk", "mitigate", sid, rid,
            "--description", m["description"],
            "--control-type", m["control_type"],
            "--owner", m["owner"],
            "--status", m.get("status", "planned"),
            "--by", decisions["by"],
            *pdir,
        ]  # fmt: skip
        for key in ("residual_likelihood", "residual_severity"):
            if m.get(key) is not None:
                args += ["--" + key.replace("_", "-"), str(m[key])]
        replay.call(run, f"mitigate-{number}", args)
    for number, a in enumerate(decisions["acceptances"], start=1):
        rid = match_risk(titles, a["risk"])
        args = ["risk", "accept", sid, rid, "--rationale", a["rationale"], "--by", decisions["by"]]
        replay.call(run, f"accept-{number}", [*args, *pdir])

    replay.call(run, "tests-generate", ["tests", "generate", sid, *pdir])
    step, _ = replay.call(run, "validate", ["validate", sid, *pdir])
    run.gates = asyncio.run(gate_results(project, sid))
    if step.exit_code == 1 and "FAIL" in run.gates.values():
        # A failing gate is a result: record it and export anyway, as the user guide allows.
        step.expected = 1
        run.forced_export = True
    force = ["--force"] if run.forced_export else []

    paths = {
        "json": exports / "rmf.json",
        "markdown": exports / "rmf.md",
        "pdf": exports / "rmf.pdf",
    }
    for fmt, path in paths.items():
        sign = ["--sign", str(private_key)] if fmt == "json" else []
        _, stdout = replay.call(
            run, f"export-{fmt}", ["export", sid, "-f", fmt, "-o", str(path), *sign, *force, *pdir]
        )
        run.files[fmt] = str(path)
        run.digests[fmt] = parse_digest(stdout)
    public_key = Path(str(private_key) + ".pub")
    replay.call(
        run,
        "verify-file",
        ["verify", "--file", str(paths["json"]), "--trusted-key", str(public_key)],
    )
    replay.call(run, "verify-project", ["verify", *pdir])
    return run


# --------------------------------------------------------------------------- checks


def check_run(replay: Replay, run: Run, public_key: Path) -> list[Check]:
    import riskforge.api as rf

    checks = []
    bad = [f"{s.name} exited {s.exit_code}, expected {s.expected}" for s in run.steps if not s.ok]
    checks.append(
        Check(f"flow.{run.label}", not bad, "; ".join(bad) or f"{len(run.steps)} commands")
    )
    validate = [s for s in run.steps if s.name == "validate"]
    failing = sorted(g for g, status in run.gates.items() if status == "FAIL")
    if not validate or not run.gates:
        checks.append(Check(f"validate.{run.label}", False, "not reached"))
    else:
        # validate must exit 1 exactly when a gate fails; which gates fail is a result.
        agrees = (validate[0].exit_code == 1) == bool(failing)
        detail = (
            f"gates failing: {', '.join(failing)} (a result; exported with --force)"
            if failing
            else "no gate fails"
        )
        if not agrees:
            detail = f"validate exited {validate[0].exit_code} but gates failing: {failing}"
        checks.append(Check(f"validate.{run.label}", agrees, detail))
    if "json" not in run.files or not Path(run.files["json"]).exists():
        checks.append(Check(f"export.{run.label}", False, "no JSON export"))
        return checks

    json_path = Path(run.files["json"])
    document = rf.read_rmf_file(json_path)
    recorded = document.get("sha256_hash")
    recomputed = rf.content_digest(document)
    checks.append(
        Check(
            f"digest.recomputed.{run.label}",
            recorded == recomputed,
            f"file {recorded}, riskforge.api.content_digest {recomputed}",
        )
    )
    md_path = Path(run.files.get("markdown", ""))
    md_text = md_path.read_text(encoding="utf-8") if md_path.is_file() else ""
    printed = {fmt: run.digests.get(fmt) for fmt in ("json", "markdown", "pdf")}
    same = len({recorded, *printed.values()}) == 1 and recorded in md_text
    checks.append(
        Check(
            f"digest.formats.{run.label}",
            same,
            f"JSON field {recorded}; printed {printed}; in Markdown text: {recorded in md_text}",
        )
    )
    trusted = [rf.load_public_key_b64(public_key)]
    result = rf.check_rmf_document(document, trusted_keys=trusted)
    checks.append(
        Check(
            f"verify.api.{run.label}",
            bool(result.verified),
            "; ".join(result.findings) if result.findings else "verified with the trusted key",
        )
    )
    checks.append(
        Check(
            f"export.markdown.{run.label}",
            bool(md_text.strip()) and recorded in md_text,
            f"{len(md_text.splitlines())} lines",
        )
    )
    checks.append(pdf_check(run))
    return checks


def pdf_check(run: Run) -> Check:
    path = Path(run.files.get("pdf", ""))
    if not path.is_file():
        return Check(f"export.pdf.{run.label}", False, "no PDF written")
    from pypdf import PdfReader

    try:
        pages = len(PdfReader(str(path)).pages)
    except Exception as exc:  # noqa: BLE001 - any reader error is the finding
        return Check(f"export.pdf.{run.label}", False, f"pypdf cannot read it: {exc}")
    return Check(
        f"export.pdf.{run.label}", pages >= 1, f"{pages} pages, {path.stat().st_size} bytes"
    )


def same_register_check(replay: Replay, run: Run, private_key: Path) -> Check:
    """Export the same register again: the content digest must not change."""
    first = run.digests.get("json")
    again = Path(run.files["json"]).with_name("rmf-again.json")
    sid = run.system_id or ""
    project = replay.out / f"run-{run.label}" / "project"
    force = ["--force"] if run.forced_export else []
    step, stdout = replay.call(
        run,
        "export-json-again",
        ["export", sid, "-f", "json", "-o", str(again), "--sign", str(private_key), *force,
         "--project-dir", str(project)],
    )  # fmt: skip
    second = parse_digest(stdout)
    return Check(
        "repeat.same_register",
        step.ok and first is not None and first == second,
        f"first export {first}, second export {second}",
    )


def two_runs_check(a: Run, b: Run) -> tuple[Check, dict[str, Any] | None]:
    import riskforge.api as rf

    if "json" not in a.files or "json" not in b.files:
        return Check("repeat.two_runs", False, "a run has no JSON export"), None
    first = normalise_rmf(rf.read_rmf_file(Path(a.files["json"])))
    second = normalise_rmf(rf.read_rmf_file(Path(b.files["json"])))
    diff = first_difference(first, second)
    detail = diff or "same RMF after ids and timestamps are replaced by placeholders"
    return Check("repeat.two_runs", diff is None, detail), first


def tamper_checks(replay: Replay, run: Run, public_key: Path) -> list[Check]:
    checks = []
    work = replay.out / "tamper"
    work.mkdir(exist_ok=True)

    original = Path(run.files["json"]).read_bytes()
    copy = work / "rmf.json"
    # A content byte: the first letter of the first risk item title.
    for name, anchor in (("rmf_content", b'"title": "'), ("rmf_signature", b'"signature": "')):
        try:
            offset, changed = flip_one_byte(original, anchor)
        except ValueError as exc:
            checks.append(Check(f"tamper.{name}", False, str(exc)))
            continue
        copy.write_bytes(changed)
        tampered = replay.verify_file(copy, public_key)
        copy.write_bytes(original)
        restored = replay.verify_file(copy, public_key)
        checks.append(
            Check(
                f"tamper.{name}",
                tampered == 2 and restored == 0,
                f"byte {offset} changed: verify --file exit {tampered} (expected 2); "
                f"restored: exit {restored} (expected 0)",
            )
        )

    project = replay.out / f"run-{run.label}" / "project"
    tamper_project = work / "project"
    shutil.copytree(project, tamper_project)
    system_dir = tamper_project / ".riskforge" / "systems" / (run.system_id or "")
    targets = (
        ("register", system_dir / "register.yaml", b"title: "),
        ("audit_log", tamper_project / ".riskforge" / "audit.jsonl", b'"event":"'),
    )
    for name, path, anchor in targets:
        if not path.is_file():
            checks.append(Check(f"tamper.{name}", False, f"{path.name} not found"))
            continue
        before = path.read_bytes()
        try:
            offset, changed = flip_one_byte(before, anchor)
        except ValueError as exc:
            checks.append(Check(f"tamper.{name}", False, str(exc)))
            continue
        path.write_bytes(changed)
        tampered = replay.verify_project(tamper_project)
        path.write_bytes(before)
        restored = replay.verify_project(tamper_project)
        checks.append(
            Check(
                f"tamper.{name}",
                tampered == 2 and restored == 0,
                f"{path.name} byte {offset} changed: verify exit {tampered} (expected 2); "
                f"restored: exit {restored} (expected 0)",
            )
        )
    return checks


# --------------------------------------------------------------------------- main


def tool_versions(riskforge: str) -> dict[str, str]:
    versions = {"python": platform.python_version(), "platform": platform.platform()}
    done = subprocess.run(  # noqa: S603
        [riskforge, "--version"], capture_output=True, text=True, check=False, timeout=60
    )
    versions["riskforge"] = (done.stdout or done.stderr).strip()
    try:
        from importlib.metadata import version

        versions["pypdf"] = version("pypdf")
        versions["weasyprint"] = version("weasyprint")
    except Exception as exc:  # noqa: BLE001 - recorded, not fatal
        versions["note"] = f"version lookup failed: {exc}"
    return versions


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--inputs", type=Path, required=True, help="folder with the input YAML files"
    )
    parser.add_argument(
        "--out", type=Path, required=True, help="empty folder for everything written"
    )
    parser.add_argument("--riskforge", default="riskforge", help="the riskforge command to run")
    parser.add_argument(
        "--baseline", type=Path, help="committed rmf.normalised.json to compare with"
    )
    args = parser.parse_args(argv)

    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    if any(out.iterdir()):
        print(f"Error: {out} is not empty", file=sys.stderr)
        return 2
    inputs = args.inputs.resolve()
    try:
        system = check_system_inputs(load_yaml(inputs / "system.yaml"))
        if not (inputs / "answers.yaml").is_file():
            raise InputError("answers.yaml is missing")
        decisions_file = inputs / "decisions.yaml"
        decisions = check_decisions(load_yaml(decisions_file)) if decisions_file.is_file() else None
    except (InputError, OSError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    replay = Replay(args.riskforge, out)
    keys = out / "keys"
    keys.mkdir()
    private_key = keys / "signer.pem"
    keygen = Run("keys")
    replay.call(keygen, "keygen", ["keygen", "--output", str(private_key)])
    public_key = Path(str(private_key) + ".pub")

    results: dict[str, Any] = {
        "date": datetime.now(UTC).strftime("%Y-%m-%d"),
        "versions": tool_versions(args.riskforge),
        "inputs": {p.name: sha256_file(p) for p in sorted(inputs.glob("*.yaml"))},
    }
    checks: list[Check] = [
        Check("keygen", all(s.ok for s in keygen.steps), keygen.steps[0].log),
    ]
    try:
        run_a = replay_once(replay, "a", inputs, system, decisions, private_key)
        if decisions is None:
            results["runs"] = {"a": asdict(run_a)}
            bad = [f"{s.name} exited {s.exit_code}" for s in run_a.steps if not s.ok]
            if not bad and not run_a.system_id:
                bad.append("init printed no system id")
            elif not bad and not any(s.name == "risk-list" for s in run_a.steps):
                bad.append("risk list not reached")
            if bad or not checks[0].passed:
                # A command failed before the risk list: that is a failed run, not missing input.
                checks.append(
                    Check("flow.a", not bad, "; ".join(bad) or f"{len(run_a.steps)} commands")
                )
                write_results(out, results, checks)
                for c in checks:
                    print(f"{'PASS' if c.passed else 'FAIL'}  {c.id}: {c.detail}")
                return 2
            listed = out / "run-a" / "risk-list.txt"
            print(listed.read_text(encoding="utf-8") if listed.is_file() else "")
            print("No decisions.yaml yet: write it from the risk list above, then run again.")
            write_results(out, results, checks)
            return 3
        run_b = replay_once(replay, "b", inputs, system, decisions, private_key)
    except InputError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    for run in (run_a, run_b):
        checks += check_run(replay, run, public_key)
    if "json" in run_a.files:
        checks.append(same_register_check(replay, run_a, private_key))
        checks += tamper_checks(replay, run_a, public_key)
    two_runs, normalised = two_runs_check(run_a, run_b)
    checks.append(two_runs)
    checks.append(
        Check(
            "repeat.gates",
            bool(run_a.gates) and run_a.gates == run_b.gates,
            f"run a {run_a.gates}, run b {run_b.gates}",
        )
    )
    results["runs"] = {"a": asdict(run_a), "b": asdict(run_b)}

    drift = False
    if normalised is not None:
        (out / "rmf.normalised.json").write_text(
            json.dumps(normalised, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        (out / "gates.json").write_text(
            json.dumps(run_a.gates, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        if args.baseline:
            committed = json.loads(args.baseline.read_text(encoding="utf-8"))
            diff = first_difference(committed, normalised)
            committed_gates = args.baseline.with_name("gates.json")
            if diff is None and committed_gates.is_file():
                gates_then = json.loads(committed_gates.read_text(encoding="utf-8"))
                gates_diff = first_difference(gates_then, run_a.gates)
                diff = f"gates: {gates_diff}" if gates_diff else None
            drift = diff is not None
            results["baseline"] = {
                "file": args.baseline.name,
                "same": not drift,
                "first_difference": diff,
            }

    write_results(out, results, checks)
    failed = [c for c in checks if not c.passed]
    for c in checks:
        print(f"{'PASS' if c.passed else 'FAIL'}  {c.id}: {c.detail}")
    if failed:
        print(f"{len(failed)} of {len(checks)} checks failed.")
        return 2
    if drift:
        print(f"All {len(checks)} checks passed, but the RMF differs from the baseline: "
              f"{results['baseline']['first_difference']}")  # fmt: skip
        return 1
    print(f"All {len(checks)} checks passed.")
    return 0


def write_results(out: Path, results: dict[str, Any], checks: list[Check]) -> None:
    results["checks"] = [asdict(c) for c in checks]
    results["passed"] = sum(c.passed for c in checks)
    results["failed"] = sum(not c.passed for c in checks)
    text = json.dumps(results, indent=2, ensure_ascii=False, default=str)
    (out / "results.json").write_text(text.replace(str(out), "$OUT") + "\n", encoding="utf-8")


if __name__ == "__main__":
    try:
        code = main()
    except Exception as exc:  # noqa: BLE001 - a crash is a failed run, never exit 1 (drift)
        print(f"Error: {type(exc).__name__}: {exc}", file=sys.stderr)
        code = 2
    sys.exit(code)
