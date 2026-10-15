#!/usr/bin/env python
"""RiskForge example evaluation harness.

For each directory under examples/ that has a config.yaml, run the full pipeline
headless (init, classify, assess --answers, accept open items, export json),
normalise the volatile fields (uuids, timestamps, hashes), and compare against the
committed golden `expected.json`.

    python scripts/eval.py            # check all examples against their goldens
    python scripts/eval.py --update   # regenerate the goldens (after an intended change)

Exit code 0 if every example matches its golden, 1 on any drift.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLES_DIR = REPO_ROOT / "examples"
_RF_BIN = str(Path(sys.executable).parent / "riskforge")

_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE)
_UUID_IN_LINE = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.IGNORECASE
)
_TS = re.compile(r"^\d{4}-\d{2}-\d{2}T")
# Hashes, keys and signatures that change from one run to the next.
_HASH_KEYS = frozenset(
    {
        "sha256_hash",
        "sha256",
        "file_sha256",
        "entry_hash",
        "prev_hash",
        "register_fingerprint",
        "signature",
        "public_key",
        "key_id",
    }
)


def _normalise(obj):
    """Replace volatile values (uuids, timestamps, integrity hashes) with placeholders."""
    if isinstance(obj, dict):
        out = {}
        for key, value in obj.items():
            if key in _HASH_KEYS:
                out[key] = "<hash>"
            else:
                out[key] = _normalise(value)
        return out
    if isinstance(obj, list):
        return [_normalise(v) for v in obj]
    if isinstance(obj, str):
        if _UUID.match(obj):
            return "<uuid>"
        if _TS.match(obj):
            return "<timestamp>"
        return obj
    return obj


def _rf(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run([_RF_BIN, *args], capture_output=True, text=True)


async def _accept_open_items(project_dir: Path, sid: str) -> None:
    from riskforge.engine.audit import AuditEngine
    from riskforge.engine.risk import RiskEngine
    from riskforge.models.audit import AuditActor
    from riskforge.storage.filesystem import FileStore

    store = FileStore(project_dir)
    audit = AuditEngine(store, AuditActor(type="human", identity="eval"))
    engine = RiskEngine(store, audit)
    register = await store.read_register(sid)
    for item in list(register.open_items()):
        await engine.accept_risk(
            sid, str(item.id), "Residual accepted for the example fixture.", "eval"
        )


def _run_example(example_dir: Path) -> dict:
    config = yaml.safe_load((example_dir / "config.yaml").read_text())
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        init = _rf(
            [
                "init",
                "-n",
                config["name"],
                "-s",
                str(config["version"]),
                "-p",
                config["purpose"],
                "--provider",
                config["provider"],
                "-c",
                config["category"],
                "--project-dir",
                str(d),
                "--non-interactive",
            ]
        )
        if init.returncode != 0:
            raise RuntimeError(f"init failed for {example_dir.name}:\n{init.stdout}{init.stderr}")
        sid = next(
            (
                m.group(0)
                for line in (init.stdout + init.stderr).splitlines()
                if (m := _UUID_IN_LINE.search(line))
            ),
            None,
        )
        if not sid:
            raise RuntimeError(f"could not read system id for {example_dir.name}")

        _rf(["system", "classify", sid, "--confirm", "--project-dir", str(d)])
        assess = _rf(
            [
                "assess",
                sid,
                "-a",
                "Example Assessor",
                "-r",
                "AI Governance Lead",
                "--answers",
                str(example_dir / "answers.yaml"),
                "--project-dir",
                str(d),
            ]
        )
        if assess.returncode != 0:
            raise RuntimeError(
                f"assess failed for {example_dir.name}:\n{assess.stdout}{assess.stderr}"
            )

        asyncio.run(_accept_open_items(d, sid))

        out = d / "rmf.json"
        export = _rf(["export", sid, "-f", "json", "-o", str(out), "--project-dir", str(d)])
        if export.returncode != 0:
            raise RuntimeError(
                f"export failed for {example_dir.name}:\n{export.stdout}{export.stderr}"
            )
        return _normalise(json.loads(out.read_text()))


def main() -> int:
    parser = argparse.ArgumentParser(description="RiskForge example evaluation harness")
    parser.add_argument(
        "--update", action="store_true", help="regenerate the golden expected.json files"
    )
    args = parser.parse_args()

    examples = sorted(p for p in EXAMPLES_DIR.iterdir() if (p / "config.yaml").exists())
    if not examples:
        print("no examples found")
        return 1

    failures: list[str] = []
    for example in examples:
        actual = _run_example(example)
        golden_path = example / "expected.json"
        rendered = json.dumps(actual, indent=2, sort_keys=True) + "\n"
        if args.update:
            golden_path.write_text(rendered)
            print(f"updated  {example.name}")
            continue
        if not golden_path.exists():
            failures.append(example.name)
            print(f"MISSING  {example.name} (run with --update to create it)")
            continue
        if rendered == golden_path.read_text():
            print(f"ok       {example.name}")
        else:
            failures.append(example.name)
            print(f"DRIFT    {example.name} (run with --update after an intended change)")

    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
