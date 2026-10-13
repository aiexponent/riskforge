# RiskForge 1.1.3 project fixture

Written by RiskForge v1.1.3 (git 5ae29c8) on 2026-10-12
from `examples/credit-scoring`: init, system classify, assess --answers, one risk mitigate,
risk accept for the other open items, and export -f json.

The files sit flat because the repository .gitignore excludes `.riskforge/`, `systems/` and
`riskforge.yaml`. `manifest.yaml` is the project's `riskforge.yaml`.
`tests/conftest.py::materialise_v113` rebuilds the on-disk layout in a temporary directory.

Do not edit these files. `SHA256SUMS` pins them, and every later RiskForge version must keep
verifying this chain and this rmf.json.
