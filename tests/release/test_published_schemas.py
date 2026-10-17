"""Release check: the RMF schemas on aiexponent.com are byte-identical to the bundled ones.

The schemas' $id values are these URLs, so a validator that follows $id must get the same
bytes the package validates with. Only the release workflow runs this, with `-m release`;
`addopts` deselects it from every other run.

The suite keeps sockets blocked in this process (pytest-socket, guarded by
tests/contract/test_offline_guard.py), so the download runs in a child interpreter started
with `-I`, which does not load the tests/netblock guard that rf_testkit adds to CLI
subprocesses. The test does nothing unless `-m release` is the whole marker expression,
so a run with some other `-m` that happens to select it stays offline. The release workflow
sets RISKFORGE_RELEASE_CHECK=1, and then the test fails instead of skipping, so a workflow
edit cannot let a release publish without the check.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from collections.abc import Mapping
from importlib.resources import files
from pathlib import Path

import pytest
from rf_testkit import RELEASE_ENV, offline_env

REPO = Path(__file__).resolve().parents[2]
PUBLISHED = {
    "1.0.0": "https://aiexponent.com/schemas/riskforge/rmf/1.0.0.json",
    "1.1.0": "https://aiexponent.com/schemas/riskforge/rmf/1.1.0.json",
}

FETCH = """
import json, sys, urllib.request
with urllib.request.urlopen(sys.argv[1], timeout=30) as response:
    body = response.read()
    meta = {"status": response.status, "content_type": response.headers.get_content_type()}
with open(sys.argv[2], "wb") as out:
    out.write(body)
print(json.dumps(meta))
"""


def release_gate(markexpr: str, env: Mapping[str, str]) -> tuple[str, str]:
    """Whether the check runs ("run"), skips ("skip") or fails ("fail"), and why."""
    if markexpr.strip() == "release":
        return "run", "selected with -m release"
    if env.get(RELEASE_ENV):
        return "fail", (
            f"{RELEASE_ENV} is set, so the published-schema check must run, "
            f"but the marker expression is {markexpr!r}, not 'release'"
        )
    return "skip", "the published-schema check runs only with -m release"


def _describe(data: bytes) -> str:
    return f"sha256 {hashlib.sha256(data).hexdigest()}, {len(data)} bytes"


def mismatch_message(url: str, served: bytes, bundled: bytes) -> str:
    return (
        f"{url} does not match the bundled schema:\n"
        f"  served:  {_describe(served)}\n"
        f"  bundled: {_describe(bundled)}"
    )


@pytest.mark.release
@pytest.mark.parametrize("version", sorted(PUBLISHED))
def test_published_schema_is_byte_identical(
    version: str, tmp_path: Path, request: pytest.FixtureRequest
) -> None:
    decision, reason = release_gate(request.config.option.markexpr, os.environ)
    if decision == "fail":
        pytest.fail(reason)
    if decision == "skip":
        pytest.skip(reason)
    bundled = files("riskforge._data.schemas").joinpath(f"rmf-{version}.schema.json").read_bytes()
    body_path = tmp_path / f"{version}.json"
    result = subprocess.run(
        [sys.executable, "-I", "-c", FETCH, PUBLISHED[version], str(body_path)],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, f"fetching {PUBLISHED[version]} failed:\n{result.stderr}"
    meta = json.loads(result.stdout)
    assert meta["status"] == 200
    assert meta["content_type"] == "application/json"
    served = body_path.read_bytes()
    assert served == bundled, mismatch_message(PUBLISHED[version], served, bundled)


# --- the helpers above, checked offline in every run ------------------------------------


def test_mismatch_message_names_the_url_and_both_digests() -> None:
    url = PUBLISHED["1.1.0"]
    message = mismatch_message(url, served=b"served", bundled=b"bundled!")
    assert url in message
    assert f"sha256 {hashlib.sha256(b'served').hexdigest()}, 6 bytes" in message
    assert f"sha256 {hashlib.sha256(b'bundled!').hexdigest()}, 8 bytes" in message


@pytest.mark.parametrize(
    ("markexpr", "env", "expected"),
    [
        ("release", {}, "run"),
        ("release", {RELEASE_ENV: "1"}, "run"),
        (" release ", {RELEASE_ENV: "1"}, "run"),
        ("not integration", {}, "skip"),
        ("", {}, "skip"),
        ("release or unit", {}, "skip"),
        ("not integration", {RELEASE_ENV: "1"}, "fail"),
        ("", {RELEASE_ENV: "1"}, "fail"),
        ("release or unit", {RELEASE_ENV: "1"}, "fail"),
    ],
)
def test_release_gate(markexpr: str, env: dict[str, str], expected: str) -> None:
    decision, reason = release_gate(markexpr, env)
    assert decision == expected
    assert reason


def _pytest_in_child(*args: str, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "-q", *args],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
        cwd=REPO,
        env=offline_env(env),
    )


def test_release_env_refuses_a_run_that_selects_no_release_test() -> None:
    result = _pytest_in_child("tests/release", "--collect-only", env={RELEASE_ENV: "1"})
    assert result.returncode == pytest.ExitCode.USAGE_ERROR, result.stdout + result.stderr
    assert "no release test is selected" in result.stdout + result.stderr


def test_release_env_accepts_a_run_that_selects_the_release_tests() -> None:
    result = _pytest_in_child(
        "-m", "release", "tests/release", "--collect-only", env={RELEASE_ENV: "1"}
    )
    assert result.returncode == pytest.ExitCode.OK, result.stdout + result.stderr
