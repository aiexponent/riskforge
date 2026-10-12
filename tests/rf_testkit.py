"""Helpers shared by tests: run the riskforge CLI with the network blocked."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

NETBLOCK_DIR = Path(__file__).resolve().parent / "netblock"

RF_BIN = str(Path(sys.executable).parent / "riskforge")
if not Path(RF_BIN).exists():
    RF_BIN = shutil.which("riskforge") or RF_BIN


def offline_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    """os.environ plus a PYTHONPATH that loads tests/netblock/sitecustomize.py first."""
    env = dict(os.environ)
    paths = [str(NETBLOCK_DIR)]
    if env.get("PYTHONPATH"):
        paths.append(env["PYTHONPATH"])
    env["PYTHONPATH"] = os.pathsep.join(paths)
    env["NO_COLOR"] = "1"
    env["COLUMNS"] = "200"
    if extra:
        env.update(extra)
    return env


def run_rf(
    args: list[str],
    cwd: Path | str | None = None,
    input_text: str | None = None,
    timeout: int = 180,
) -> subprocess.CompletedProcess:
    """Run ``riskforge <args>`` offline. The result gains ``.output`` (stdout plus stderr)."""
    stdin_kwargs = (
        {"input": input_text} if input_text is not None else {"stdin": subprocess.DEVNULL}
    )
    result = subprocess.run(
        [RF_BIN, *args],
        capture_output=True,
        text=True,
        cwd=cwd,
        env=offline_env(),
        timeout=timeout,
        **stdin_kwargs,
    )
    result.output = result.stdout + result.stderr  # type: ignore[attr-defined]
    return result
