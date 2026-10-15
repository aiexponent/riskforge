"""GPG signing is gone: `export --sign` takes an Ed25519 key file (ADR-04 section 3).

Signed exports are tested end to end in tests/integration/test_export_command.py.
"""

from __future__ import annotations

import inspect

import riskforge.engine.export as export_module


def test_no_gpg_code_path_remains() -> None:
    assert not hasattr(export_module, "SigningError")
    source = inspect.getsource(export_module).lower()
    assert "gpg" not in source
    assert "subprocess" not in source
