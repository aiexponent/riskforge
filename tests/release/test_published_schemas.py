"""Release check: the RMF schemas on aiexponent.com are byte-identical to the bundled ones.

The schemas' $id values are these URLs, so a validator that follows $id must get the same
bytes the package validates with. Only the release workflow runs this, with `-m release`;
`addopts` deselects it from every other run.

The suite keeps sockets blocked in this process (pytest-socket, guarded by
tests/contract/test_offline_guard.py), so the download runs in a child interpreter started
with `-I`, which does not load the tests/netblock guard that rf_testkit adds to CLI
subprocesses. The test does nothing unless `-m release` is the whole marker expression,
so a run with some other `-m` that happens to select it stays offline.
"""

from __future__ import annotations

import json
import subprocess
import sys
from importlib.resources import files
from pathlib import Path

import pytest

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


@pytest.mark.release
@pytest.mark.parametrize("version", sorted(PUBLISHED))
def test_published_schema_is_byte_identical(
    version: str, tmp_path: Path, request: pytest.FixtureRequest
) -> None:
    if request.config.option.markexpr.strip() != "release":
        pytest.skip("the published-schema check runs only with -m release")
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
    assert body_path.read_bytes() == bundled
