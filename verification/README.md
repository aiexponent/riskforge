# Independent verification of RiskForge

This folder tests a released RiskForge from PyPI the way a user runs it, and keeps
the evidence. It is not part of the package. Its inputs are written by a tester who
did not build RiskForge and who reads only the public documentation.

RiskForge builds an Article 9 risk register and exports it as a signed Risk
Management File (RMF). There is no single right answer to compare an RMF with, so
the test checks what can be checked:

| Area | What is checked |
|---|---|
| Coverage | Before any run, the tester lists what an Article 9 risk management file should contain, read from the Article 9 text at EUR-Lex (`verification/expected.md`). After the run, each item is marked present, partly present or missing in the RMF (`coverage.csv`). |
| Repeatability | The whole flow runs twice, each time in a new project. The two RMFs must be the same once the values that are new in every run (random ids and timestamps) are replaced by placeholders. Exporting the same register twice must give the same content digest. |
| Tamper evidence | A signed RMF verifies with `riskforge verify --file rmf.json --trusted-key KEY.pub`. One changed byte in its content or its signature fails, and restoring the byte passes again. The same for one changed byte in a register file and in the audit log, checked with `riskforge verify` on a copy of the project. |
| Exports | The JSON, Markdown and PDF exports of one register carry the same content digest, and the digest recomputed with `riskforge.api.content_digest` matches the one in the file. The PDF opens in pypdf; the Markdown names the digest. |
| Usability | Every step of the public README and user guide that was unclear or failed (`NOTES.md`). |

## Run it

```bash
verification/run.sh                 # in Docker, with the versions pinned in requirements.lock
verification/run.sh --no-docker     # in a throwaway venv (Python 3.11+, and the WeasyPrint
                                    # system libraries from the RiskForge README for the PDF)
verification/run.sh --version 2.0.1 # another released version, not hash-pinned
verification/run.sh --smoke         # with the made-up inputs in tests/fixtures/smoke-inputs
```

Everything goes to a new temporary folder (or `--out DIR`), and the last line prints
where. Nothing is written into the checkout unless you pass `--update`, which copies
the results into `results/`, also when a check failed: a failure is a result too, and the
exit code still reports it. Only a run in which every check passed replaces the baseline
`results/rmf.normalised.json`.

| Exit code | Meaning |
|---|---|
| 0 | Every check passed, and the RMF matches `results/rmf.normalised.json` when that file is committed. |
| 1 | Every check passed, but the RMF or the gate results differ from the committed baseline (`results/rmf.normalised.json`, `results/gates.json`). A new release changed them, so the report needs redoing for it. |
| 2 | A check failed: the install, a command, a digest, repeatability, tamper evidence or an export. `results.json` lists each check. |
| 3 | `inputs/decisions.yaml` does not exist yet. The risk list is printed so the decisions can be written. |

`replay.py` runs each command through the installed `riskforge` and keeps its output
in `run-a/logs/` and `run-b/logs/`. It reads the risk ids for the decisions through
the documented `riskforge.api` and never writes a project file itself.

## Inputs

The tester writes four files in `inputs/`.

`subject.md`: the facts the inputs rest on, from the dataset page and its
documentation only, each with its source and the date it was read.

`system.yaml`: the `riskforge init` parameters and the assessor for `riskforge assess`.

```yaml
name: "..."
version: "..."
purpose: "..."
provider: "..."
category: ...          # optional, an Annex III category as `riskforge init --category` takes it
assessor_name: "..."
assessor_role: "..."
review_months: 12      # optional
```

`answers.yaml`: the answers file `riskforge assess --answers` reads, in the format
the user guide gives.

`decisions.yaml`: the mitigations and acceptances, written after a first run has
printed the risk list. `risk` is the title as `riskforge risk list` prints it (its
first 40 characters); a longer start of the title also works. A title that matches
no item, or more than one, stops the run.

```yaml
by: "Name, Role"               # who records the decisions (the --by option)
mitigations:
  - risk: "..."
    description: "..."
    control_type: preventive   # preventive, detective or corrective
    owner: "..."
    status: implemented        # optional: planned (the default), implemented or verified
    residual_likelihood: 2     # optional, 1 to 5
    residual_severity: 3       # optional, 1 to 5
acceptances:
  - risk: "..."
    rationale: "..."
```

The decisions are applied in file order, mitigations first. If `riskforge validate`
reports a FAIL gate, that is the tool's verdict on the inputs, not a fault in the tool.
The replay records the gate results in `gates.json`, checks that `validate` exits 1
exactly when a gate fails and that both runs reach the same gates, and exports with
`--force`, so the other checks still run.

## Order of the tester's commits

1. `expected.md` and `subject.md`, before RiskForge is installed.
2. `system.yaml` and `answers.yaml`.
3. `decisions.yaml`, after one run has printed the risk list.
4. The results of `run.sh --update`, then `coverage.csv` (against the committed
   `expected.md`) and `NOTES.md`.

The git history shows that each file was fixed before the next step.

## What this does not check

- Whether the risks RiskForge proposes are the right risks for the system. That is
  the provider's judgement, and the coverage table records only whether the RMF has
  a place for each part of Article 9.
- Legal compliance. An RMF that passes every check here is a well-formed, repeatable
  and tamper-evident record, not proof that a system meets Article 9.
- Who signed. The test generates its own key; a signature shows only that the file
  was not changed after that key signed it.

## Files

| File | What it is |
|---|---|
| `run.sh` | The one command. |
| `replay.py` | Runs the flow twice and the checks, writes `results.json`. |
| `Dockerfile` | Python and the WeasyPrint system libraries, as a non-root user. |
| `requirements.in`, `requirements.lock` | The RiskForge release under test and pypdf, pinned with hashes. |
| `tests/` | Unit tests for the helpers in `replay.py` (`python -m unittest discover -s verification/tests`), and the made-up smoke inputs. |
| `expected.md` | What an Article 9 risk management file should contain, written by the tester before any run. |
| `inputs/` | The tester's inputs. |
| `coverage.csv`, `NOTES.md` | The tester's coverage table and usability notes, written after the run. |
| `results/` | `results.json`, the exported RMF in three formats, the risk list, and the baseline later runs are compared with: the normalised RMF (`rmf.normalised.json`) and the gate results (`gates.json`). |
