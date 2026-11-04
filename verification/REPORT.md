# RiskForge independent test: report

**Package tested:** riskforge 2.0.0, installed from PyPI by version and hash (`requirements.lock`)
**Subject:** a credit-scoring model on the UCI Statlog (German Credit Data) dataset, CC BY 4.0, DOI 10.24432/C5NC77
**Date of the run:** 4 November 2026
**Tester:** a separate session that read only the public README, user guide, question bank and `--help`

RiskForge records a provider's own risk management decisions. Neither the tool nor this test is a legal opinion, a conformity assessment or a certification. A file that passes every check here is a well-formed, repeatable and tamper-evident record. It is not proof that a system meets Article 9 of Regulation (EU) 2024/1689.

## Summary

| Area | Result |
|---|---|
| Tamper evidence | One changed byte failed `riskforge verify` in all four places tried: the RMF content, its signature, a register file and the audit log. Restoring the byte passed each time. |
| Repeatability | The same register exported twice gave the same content digest. Two full runs gave the same RMF once ids and timestamps were replaced. |
| Exports | JSON, Markdown and PDF carry the same content digest, and `riskforge.api.content_digest` recomputes it. The signed JSON verified with the trusted key. The PDF (22 pages) opened. |
| Coverage of Article 9 | Of 22 things a file can show, 9 present, 8 partial, 5 missing. |
| Checks | 19 of 21 passed. The two failures are gate G3 in each run, caused by the tester's decisions (see "Checks"). |
| Defects | 12 defects in the exported content and the CLI, each confirmed against the committed files. None breaks the integrity checks. Three affect what a reader of the file can rely on. |

**Read these results with two cautions:**
- **The inputs are one tester's reading.** The answers, scores and decisions rest on public facts about the dataset plus stated assumptions about a provider and a lender. Another tester would score some risks differently. Coverage does not depend on those choices; the risk list does.
- **The test checks the record, not the judgement.** It does not say whether the risks RiskForge proposes are the right ones for this system.

## Method

The order of work is in the git history. Each step was committed before the next began:

| Commit | Step |
|---|---|
| `825c9cc` | `expected.md` and `inputs/subject.md`, written before RiskForge was installed |
| `906cc8b` | `inputs/system.yaml` and `inputs/answers.yaml`, from the user guide and the question bank |
| `c14c683` | `inputs/decisions.yaml`, written after one run had printed the risk list |
| `114379b` | the results of `run.sh --update`, then `coverage.csv` and `NOTES.md` |

**What the tester read.** The tester read Article 9 in the English text of Regulation (EU) 2024/1689, fetched from the Publications Office on 4 November 2026. The tester checked for amending acts through the Publications Office SPARQL endpoint. One came back, Regulation (EU) 2026/1744, and none of its points amends Article 9. The facts about the subject come from the UCI dataset page and `german.doc` only; `subject.md` gives the source and read date of each.

**What the tester did not read:** the RiskForge source (apart from the question bank), `examples/`, `tests/`, the ADRs, `docs/article-9-mapping.md` and `verification/replay.py`.

**Two departures from the brief,** both recorded by the tester in `NOTES.md` under "Post-run notes":
- **`run.sh`.** After commit 2, the tester read the first 80 lines of `verification/run.sh`, its header and option parsing. That file was not on the allowed list. It describes the test, not RiskForge.
- **Provider name.** The made-up provider name, "Northwind Scoring Labs (fictional)", shares a word with the user guide's example provider.

Neither affects the results.

## Checks

`verification/run.sh --no-docker --update` replayed the whole flow twice, each time in a new project. Each run issued 30 commands: init, classify, assess, risk list, 18 mitigations, 1 acceptance, tests generate, validate and three exports. Full output is in `results/results.json`.

| Check | Run a | Run b |
|---|---|---|
| Every command exits as expected | PASS | PASS |
| `validate` passes its FAIL gates | FAIL (G3) | FAIL (G3) |
| Digest in the file equals `riskforge.api.content_digest` | PASS | PASS |
| JSON, Markdown and PDF show the same digest | PASS | PASS |
| `check_rmf_document` verifies with the trusted key | PASS | PASS |
| Markdown export names the digest | PASS | PASS |
| PDF opens in pypdf | PASS (22 pages) | PASS (22 pages) |

| Check across runs | Result |
|---|---|
| Same register exported twice: same digest | PASS |
| Two full runs: same RMF after ids and timestamps are replaced | PASS |
| One byte changed in the RMF content: `verify --file` exits 2, restored exits 0 | PASS |
| One byte changed in the RMF signature: same | PASS |
| One byte changed in `register.yaml` on a copy of the project: `verify` exits 2, restored exits 0 | PASS |
| One byte changed in `audit.jsonl`: same | PASS |

**Why G3 failed.** Gate G3 requires every risk's residual score to be at or below the risk appetite threshold (9), or the risk to be accepted. The tester lowered a residual score only where a control was already in place. Most controls in `decisions.yaml` are planned, so 14 of the 28 risks stayed above 9 and unaccepted. That is the outcome the gate exists to show. The replay then exported with `--force`, as `verification/README.md` describes, so the other checks still ran.

**No baseline yet.** `results/rmf.normalised.json` is written only by a run in which every check passes. This run's G3 result means no baseline is committed, so later release checks cannot yet detect RMF drift (see "Follow-up").

## Coverage of Article 9

The tester listed what an Article 9 file can show before running anything (`expected.md`, 22 rows), and what it cannot show (7 rows, with reasons). After the run, each of the 22 was marked against the exported file (`coverage.csv`).

| Status | Count | Items |
|---|---|---|
| Present | 9 | E01 system and provider, E03 intended purpose, E04 list of risks, E06 likelihood and severity, E07 evaluation against a threshold, E10 measures per risk, E13 residual risk and acceptance per risk, E16 mitigation and control measures, E22 vulnerable groups |
| Partial | 8 | E02 review and change record, E05 analysis of each risk, E12 interaction of Section 2 requirements, E15 risks reduced by design, E17 information and training for deployers, E18 deployer context, E19 testing done, E20 metrics and thresholds |
| Missing | 5 | E08 reasonably foreseeable misuse, E09 post-market monitoring data, E11 design or technical-information route of each measure, E14 overall residual risk, E21 when testing was done |

**Note on the partial items.** Several are partial because the file has a field but RiskForge offers no way to fill it, or fills it with a template. Examples:
- **E18:** the system's `deployment_context` and `intended_users` exist, but `riskforge init` has no option for them.
- **E20:** test requirements are per-dimension templates (see D5).
- **E19:** the file lists required tests but has no place for test results.

## Defects

Each defect below was confirmed against `results/rmf.json`, `results/rmf.md` and `results/rmf.pdf` as committed, or against `riskforge --help`. Severity is for a reader who relies on the file.

| ID | Severity | Where | Defect |
|---|---|---|---|
| D1 | High | JSON, Markdown, PDF | A forced export is not marked in the JSON or Markdown. The JSON was exported with `--force` while G3 failed, and nothing in `rmf.json` or `rmf.md` records the gate results. The PDF cover says "Exported with failing gates: G3", under the same content digest. So the gate status the PDF prints is not covered by the digest it shows, and a reader of the signed JSON cannot tell the file was forced. |
| D2 | Medium | `$.register.review_date` | A 12-month review gives a review date 360 days after the assessment (2026-11-04 to 2027-10-30), not 12 months. |
| D3 | Medium | `$.register.items[*].title` | Titles are the question text cut at 120 characters, mid-phrase, in the JSON (for example "...disproportionately harmed by system errors"). The Markdown and PDF add "...". Most titles are questions, so a score does not say whether it is for the control being missing or present. |
| D4 | Medium | `$.cross_references[*]` | Each cross-reference group carries one item's NIST AI RMF and ISO/IEC 42001 references. For example, the `Art.9(2)(a)` group shows `MEASURE 2.11` and `Annex A.7`, but it also holds items citing `GOVERN 1.1` and `MAP 5.1`. |
| D5 | Medium | `$.test_requirements[*]` | Test requirements are per-dimension templates. The four robustness risks of a tabular credit model get `faithfulness >= 0.85`, a metric for generated text. Reviewer training and workload get `override_latency_ms <= 500`. `fundamental_rights_impact_score = 0` is not defined anywhere. The PDF section is titled "Article 9(6) to 9(8) test requirements", yet the entries cite `Art.9(2)(a)`, `Art.9(2)(b)`, `Art.10`, `Art.13` and `Art.14`. |
| D6 | Medium | `$.register.items[*]` with `knowledge_gap: true` | An `unknown` answer to a question with no hints is scored 3 x 3 = 9 without saying so. `knowledge_gap_reason` is empty on all eight knowledge gaps, so these scores look the same as judged ones. |
| D7 | Medium | `riskforge init`, gate G5 | `init` has no options for intended users, inputs, outputs, deployment context or provider contact. The PDF prints "Not specified" for each, yet gate G5 "System metadata complete" passes. |
| D8 | Low | `$.register.items[13]`, `[14]` | Two question bank items (PR-003, PR-004) have no article reference. |
| D9 | Low | PDF | The PDF prints raw enum values ("Likelihood almost_certain (5)"). A stray bullet follows many risk blocks. The last page ends "Check the JSON export of this file with riskforge verify --file ." with no file name. |
| D10 | Low | `$.chain_proof.entries[*].actor` | The actor is `cli` for some events, "Mara Lindqvist" for others and "Mara Lindqvist, Head of Model Risk" for others in the same project. |
| D11 | Low | `riskforge validate --help` | `--force` is described as "Export even if FAIL gates present", but `validate` does not export. |
| D12 | Low | README contributing sample | The sample question id `PRIV-007` does not match the bank's `PR-001` to `PR-005`. |

**What the defects do not affect.** None of them weakens tamper evidence or repeatability. D1 is the exception: it concerns what the signed content leaves out, not whether the content can be changed unnoticed.

## Usability findings

From `NOTES.md`; each is a place where the public documentation left the tester unsure or was wrong:

1. The user guide does not say whether `applies: yes` means "the risk applies" or "the answer to the question is yes". Most questions are phrased as control checks, so two users could answer the same system in opposite ways.
2. The guide does not say that `unknown` on a question without hints is scored 3 x 3 (see D6).
3. `riskforge init --help` lists no allowed `--category` values; only the user guide does.
4. The same short flag means different things in different commands: `-r` is the assessor role in `assess` but the rationale in `risk accept`; `-d` is the project folder in `assess` but the dimension in `risk list`.
5. `--review-months` is missing from the guide's command table.
6. `tests generate --help` does not state its rule (knowledge gaps and inherent scores of 9 or more).
7. `risk list` shows only the inherent score, not the residual score that gate G3 uses.
8. The Markdown export has no test requirements, residual summary, knowledge-gap marks or change log, though it carries the same digest as the JSON. The guide does not describe the Markdown export.

## Limits

- **One subject, one tester.** The risk list depends on how the tester answered the question bank, and the answers rest partly on stated assumptions about the provider and lender.
- **The coverage list is the tester's reading of Article 9.** It was fixed before the run, so the tool's output could not shape it. Another reader might split or merge rows differently.
- **Not checked:**
  - interactive `assess`;
  - receipts kept outside the project (`riskforge receipt`, `verify --receipt`);
  - `diff`;
  - `import`;
  - audit entries signed outside the CLI.
- **The PDF was opened and its text read.** Its layout was not reviewed page by page.

## Reproduce

```bash
verification/run.sh                 # in Docker, with the versions pinned in requirements.lock
verification/run.sh --no-docker     # in a venv (needs the WeasyPrint system libraries for the PDF)
```

The inputs are in `inputs/`. Without `--update`, nothing is written into the checkout. Ids, timestamps and signatures differ on every run; the content digest of each run's register and the normalised RMF do not.

## Follow-up

- **Defects.** D1 to D12 are filed against RiskForge.
- **Baseline and gate result.** The replay is to record the validate gate outcome as a result to compare between runs, rather than a failed check. That gives `verify-release` a baseline to compare later releases with.
