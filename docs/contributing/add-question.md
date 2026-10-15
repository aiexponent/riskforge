# How to Add a Question to the Question Bank

This is the easiest contribution to RiskForge. **No Python required.**

## Step 1: Find the right dimension file

Question banks live in `src/riskforge/_data/question_bank/`. There is one YAML file per risk dimension:

- `health_safety.yaml` — physical harm, safety-critical decisions
- `fundamental_rights.yaml` — EU Charter rights
- `discrimination.yaml` — bias, protected characteristics
- `privacy.yaml` — PII, GDPR, DPIA
- `transparency.yaml` — explainability, user notification
- `human_oversight.yaml` — override mechanisms, review processes
- `robustness.yaml` — accuracy, adversarial testing
- `data_governance.yaml` — dataset provenance, licenses

## Step 2: Add your question

Open the appropriate YAML file and add a block:

```yaml
- id: HS-007          # Prefix = dimension code. Use next available number.
  text: "Your question here — must be answerable with yes/no/unknown."
  guidance: "Help text for the assessor. Cite Article numbers and explain what to look for."
  annex_iii_categories: [essential_services, employment]   # Where this question applies
  default_likelihood_hint: 3    # 1-5, or null if not applicable
  default_severity_hint: 4      # 1-5, or null if not applicable
  article_refs: ["Art.9(2)(a)", "Art.14"]
  nist_rmf_ref: "MAP 5.1"
  iso42001_ref: "Clause 6.1"
  regulatory_status: settled    # or "pending_implementing_act"
```

## Step 3: Test your question

```bash
make dev-setup
pytest tests/ -k "test_schema"
```

## Step 4: Submit a PR

Include in your PR description:
- Why this question is needed for Article 9 compliance
- Which Annex III categories it applies to
- The Article reference that motivates it

Questions without an Article reference will be rejected.
