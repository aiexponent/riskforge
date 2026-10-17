# RiskForge examples

Each subdirectory is a worked, end-to-end example: a sample high-risk AI system,
a non-interactive assessment, and the golden Risk Management File it produces.

| Example | Annex III use case |
|---|---|
| `cv-screening/` | Employment: automated resume screening and candidate ranking |
| `credit-scoring/` | Essential services: automated credit and mortgage underwriting |

Each directory contains:

- `config.yaml`: the `riskforge init` parameters (name, version, purpose, provider, category).
- `answers.yaml`: the non-interactive `assess --answers` input (one answer per dimension).
- `expected.json`: the golden RMF, with volatile fields (uuids, timestamps, integrity
  hashes) normalised to placeholders so it is stable across runs.

## Run an example yourself

```bash
d=$(mktemp -d)
riskforge init -n "TalentScreen CV Ranker" -s 3.2.0 \
  -p "Automated resume screening and candidate ranking for hiring." \
  --provider "Northwind HR Technologies GmbH" -c employment --project-dir "$d"
sid=... # the printed System ID
riskforge system classify "$sid" --confirm --project-dir "$d"
riskforge assess "$sid" -a "Example Assessor" -r "AI Governance Lead" \
  --answers examples/cv-screening/answers.yaml --project-dir "$d"
riskforge export "$sid" -f pdf -o "$d/rmf.pdf" --force --project-dir "$d"
```

## Regression check

`scripts/eval.py` runs every example headless and compares the produced RMF against
its golden. It is wired into CI (`tests/integration/test_examples.py`).

```bash
make eval          # check all examples against their goldens (exit 1 on drift)
make eval-update   # regenerate the goldens after an intended change, then commit them
```

A drift is a signal: if it was intended (a scoring change, a new question, a schema
field), run `make eval-update` and commit the updated goldens in the same PR.
