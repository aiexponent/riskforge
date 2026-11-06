# How to Add a Question to the Question Bank

This is the easiest contribution to RiskForge. **No Python required.**

## Step 1: Find the right dimension file

Question banks live in `src/riskforge/_data/question_bank/`. There is one YAML file per risk dimension:

- `health_safety.yaml`: physical harm, safety-critical decisions
- `fundamental_rights.yaml`: EU Charter rights
- `discrimination.yaml`: bias, protected characteristics
- `privacy.yaml`: PII, GDPR, DPIA
- `transparency.yaml`: explainability, user notification
- `human_oversight.yaml`: override mechanisms, review processes
- `robustness.yaml`: accuracy, adversarial testing
- `data_governance.yaml`: dataset provenance, licenses

## Step 2: Add your question

Open the appropriate YAML file and add a block:

```yaml
- id: HS-007          # Prefix = dimension code. Use next available number.
  text: "Your question here. It must be answerable with yes, no or unknown."
  risk_title: "The risk, stated as it would apply"   # the risk item's title, at most 120 characters
  guidance: "Help text for the assessor. Cite Article numbers and explain what to look for."
  annex_iii_categories: [essential_services, employment]   # Where this question applies
  default_likelihood_hint: 3    # 1-5, or null if not applicable
  default_severity_hint: 4      # 1-5, or null if not applicable
  article_refs: ["Art.9(2)(a)", "Art.14"]
  nist_rmf_ref: "MAP 5.1"
  iso42001_ref: "Clause 6.1"
  regulatory_status: settled    # or "pending_implementing_act"
  test_metric_type: "override_success_rate"   # snake_case, unique in the bank
  test_measure: "Share of test overrides that stop or change the output in real time"
```

## Step 3: Test your question

```bash
make dev-setup
make test
```

`tests/unit/test_bank_risk_titles.py` checks that the question has a `risk_title` of at
most 120 characters that is not itself a question, that each hint is null or 1 to 5,
and that the question names a unique `test_metric_type` and a `test_measure`: the
metric `riskforge tests generate` suggests for a test of the risk. Name no threshold,
because the provider sets it.
Write the title as the risk the item records when the assessor answers `yes`: for a
question that asks whether a control is in place, that is the control missing, for
example "Bias tests not repeated at each model update". The item's description is the
full question followed by the guidance. No test checks the id, categories or references,
so compare them by hand with an existing question. `tests/contract/test_legal_references.py`
fails if your question cites an article that is not on its checked list.

## Step 4: Submit a PR

Include in your PR description:
- Why this question is needed for Article 9 compliance
- Which Annex III categories it applies to
- The Article reference that motivates it

Questions without an Article reference will be rejected.
