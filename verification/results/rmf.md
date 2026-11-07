# Risk Management File: Retail Credit Risk Scorer v1.0.0

**Provider:** Northwind Scoring Labs (fictional)
**Purpose:** Credit scoring of retail consumer credit applicants: a binary classifier, trained on the UCI Statlog German Credit data, scores each applicant as good or bad credit risk, and a lender's credit officer uses the score when deciding on the application.
**Generated:** 2026-11-07
**RMF Schema Version:** 1.2.0
**SHA-256:** `55c7cb191f3775a63d61c889c6f96d9681ef0753a813fc9916a43bc5fd344827`

---

## Assessor
- **Name:** Mara Lindqvist
- **Role:** Head of Model Risk
- **Assessment Date:** 2026-11-07
- **Review Date:** 2027-11-07

---

## Validation Gates

**Result:** FAIL. Exported with --force past failing gates: G3.

- **G1 PASS:** All 8 risk dimensions have entries
- **G2 PASS:** Article 6(2) self-classification documented
- **G3 FAIL:** Every risk's residual score at or below the risk-appetite threshold, or accepted (14 risk(s) with a residual score above the risk-appetite threshold and not accepted: 4d19141a, 3fe03c51, 9a85d48a, a3baa3a9, 8f114d3b, 88979633, d589bef0, 7112e1e6, b4ce87da, 45d9b8c1, 6b73bccd, c582db0b, 6966164c, 8b37639c)
- **G4 PASS:** Knowledge gaps have test requirements
- **G5 WARN:** System metadata complete (The system description has no intended\_users, inputs, outputs, deployment\_context, provider\_contact. Set them with \`riskforge system describe\`.)
- **G6 PASS:** Assessor identity recorded
- **G7 PASS:** Risk score distribution plausible
- **G8 PASS:** No vague mitigations

---

## Risk Items (28 total)

### Health Safety

**🟠 Production performance not monitored for degradation** (Score: 12 → Residual: 12)
> Question HS-005: Are system performance metrics (accuracy, error rates, latency) monitored in production with alerts for degradation? Post-market monitoring under Article 72 requires tracking of actual performance against stated specifications.
> *Article refs: Art.9(8), Art.72*
> - *Mitigation (detective, planned):* Track approval rate, observed bad rate at 12 months and cost-weighted error each month against the validation values, with an alert at a 20 percent relative change. (Owner: MLOps team; Recorded by: Mara Lindqvist, Head of Model Risk)

**🟠 System errors may harm vulnerable groups disproportionately** (Score: 12 → Residual: 12)
> Question HS-006: Could vulnerable populations (elderly, children, people with disabilities) be disproportionately harmed by system errors? Article 9(9) requires explicit consideration of impacts on children and other vulnerable groups.
> *Article refs: Art.9(9)*
> - *Mitigation (detective, planned):* Report error rates and cost-weighted error by age band (under 25, 25 to 59, 60 and over) at each release and block release if a band is worse than the overall rate by more than 10 percent. (Owner: Model Validation team; Recorded by: Mara Lindqvist, Head of Model Risk)

### Fundamental Rights

**🟡 No fundamental rights impact assessment before deployment** (Score: 9 → Residual: 9)
> Question FR-001: Has a fundamental rights impact assessment (FRIA) been conducted prior to deployment? Article 9(2)(a) requires identification of known and foreseeable risks to fundamental rights. A FRIA is the standard mechanism for this.
> *Article refs: Art.9(2)(a)*
> *Knowledge gap: Answered unknown, so the provider has not judged this risk yet. It is scored at the default, likelihood 3 and severity 3, until it is assessed.*

**🟠 System may restrict access to rights under the EU Charter of Fundamental Rights** (Score: 12 → Residual: 12)
> Question FR-002: Could the system restrict or affect access to rights protected under the EU Charter of Fundamental Rights? Consider right to an effective remedy, right to a fair trial, presumption of innocence, freedom of expression, right to education.
> *Article refs: Art.9(2)(a)*
> - *Mitigation (corrective, planned):* State in the instructions for use that a refused applicant can ask for a second review by a credit officer who did not make the first decision, and that the score alone must not refuse an application. (Owner: Product team; Recorded by: Mara Lindqvist, Head of Model Risk)

**🟡 Affected people not told of the AI system's role in decisions about them** (Score: 6 → Residual: 6)
> Question FR-003: Are affected individuals informed of the AI system's role in decisions that affect them, in a language they understand? Transparency is a foundational right. The obligation to inform subjects is strengthened in high-risk AI contexts.
> *Article refs: Art.26(11)*
> *Knowledge gap: Answered unknown, so the provider has not judged this risk yet. It is scored at the question's hint, likelihood 2 and severity 3, until it is assessed.*

### Discrimination

**🟠 Demographic bias in credit scoring outputs** (Score: 12 → Residual: 12)
> Credit scoring models trained on historical data may encode systemic biases against protected groups (age, gender, ethnicity). Article 9(9) requires consideration of impacts on vulnerable groups.
> *Article refs: Art.9(2)(a), Art.9(9), Art.10(2)(f)*
> - *Mitigation (detective, planned):* Apply the release gate on demographic parity and equal opportunity difference (above 0.10 blocks release) by sex, age band and foreign worker flag. (Owner: Model Validation team; Recorded by: Mara Lindqvist, Head of Model Risk)

**🟠 Training data not audited for representation imbalance across protected groups** (Score: 16 → Residual: 16)
> Question DI-001: Has the training dataset been audited for representation imbalances across protected characteristics (gender, ethnicity, age, disability)? Biased training data produces biased outputs. Article 10(2)(f) requires data governance measures to address biases.
> *Article refs: Art.10(2)(f), Art.9(2)(a)*
> - *Mitigation (detective, implemented):* Report record counts and the share of bad class by the sex part of attribute 9, by age band (under 25, 25 to 59, 60 and over) and by foreign worker flag, and state that married and divorced women share one code. (Owner: Data Science team; Recorded by: Mara Lindqvist, Head of Model Risk)

**🟠 Fairness metrics not computed for each protected group** (Score: 16 → Residual: 16)
> Question DI-002: Have demographic parity, equalised odds, or other fairness metrics been computed and documented for each protected group? Quantified fairness metrics are required for meaningful bias assessment. Select metrics appropriate to the use case.
> *Article refs: Art.9(8), Art.10(2)(f)*
> - *Mitigation (detective, planned):* Compute demographic parity difference and equal opportunity difference by sex, age band and foreign worker flag on the hold-out set; block release if any difference is above 0.10. (Owner: Model Validation team; Recorded by: Mara Lindqvist, Head of Model Risk)

**🔴 Proxy variables may encode protected characteristics** (Score: 20 → Residual: 12)
> Question DI-003: Does the system use proxy variables that may correlate with protected characteristics (e.g. postcode, school name, employment gaps)? Proxy discrimination occurs when facially neutral features encode protected characteristics. Legal exposure exists even without intent.
> *Article refs: Art.9(2)(a), Art.10(2)(f)*
> - *Mitigation (preventive, implemented):* Remove attributes 9 (personal status and sex), 13 (age) and 20 (foreign worker) from the model inputs. Keep them in a separate table used only for bias testing. (Owner: Model Development team; Recorded by: Mara Lindqvist, Head of Model Risk)
> - *Mitigation (detective, planned):* Measure the association of each remaining input with sex, age band and foreign worker status on the 1000 records, and drop or bin any input with Cramer's V above 0.3. (Owner: Model Validation team; Recorded by: Mara Lindqvist, Head of Model Risk)

**🟡 Bias tests not repeated at each model update** (Score: 6 → Residual: 6)
> Question DI-004: Are bias test results documented and reviewed at each model update, not just at initial deployment? Data drift and concept drift can re-introduce bias after initial mitigation. Continuous monitoring is required.
> *Article refs: Art.9(8), Art.72*
> *Knowledge gap: Answered unknown, so the provider has not judged this risk yet. It is scored at the question's hint, likelihood 2 and severity 3, until it is assessed.*

### Privacy

**🔴 System processes personal or special category data** (Score: 20 → Residual: 20)
> Question PR-001: Does the system process personal data or special category data (health, biometric, ethnicity, religion)? Processing of special category data triggers additional obligations under GDPR Article 9. EU AI Act Article 4a(1) allows providers of high-risk AI systems to process special categories of personal data exceptionally, to the extent strictly necessary to ensure bias detection and correction.
> *Article refs: Art.4a(1)*
> - *Mitigation (preventive, planned):* Record the legal basis for using the 1994 records and live applicant data, agreed with the lender's data protection officer, and list the personal data each input carries. (Owner: Legal and Privacy team; Recorded by: Mara Lindqvist, Head of Model Risk)

**🟡 No Data Protection Impact Assessment carried out** (Score: 9 → Residual: 9)
> Question PR-002: Has a Data Protection Impact Assessment (DPIA) been carried out, with the advice of the Data Protection Officer where one is designated? GDPR Article 35 requires a DPIA for high-risk processing. High-risk AI systems typically trigger this threshold.
> *Article refs: Art.26(9), Art.9(2)(a)*
> *Knowledge gap: Answered unknown, so the provider has not judged this risk yet. It is scored at the default, likelihood 3 and severity 3, until it is assessed.*

**🟠 Model uses more personal data than its purpose needs** (Score: 12 → Residual: 6)
> Question PR-003: Is data minimisation enforced: does the model use only the minimum personal data necessary for the intended purpose? GDPR data minimisation and purpose limitation principles (GDPR Article 5(1)(b) and (c)) apply to AI systems processing personal data.
> - *Mitigation (preventive, implemented):* Remove attribute 19 (telephone) as well as attributes 9, 13 and 20 from the model inputs, and document why each remaining input is needed. (Owner: Model Development team; Recorded by: Mara Lindqvist, Head of Model Risk)

**🟡 Personal data in training data not found and redacted or pseudonymised** (Score: 6 → Residual: 6)
> Question PR-004: Has the training data been scanned for inadvertent PII inclusion, and is PII redaction/pseudonymisation applied before training? Training data containing real PII creates privacy risk. Automated PII detection tools (e.g. TraceForge) can surface this.

### Transparency

**🟡 Lack of explanation for credit decisions** (Score: 9 → Residual: 9)
> Where a solely automated credit decision falls under GDPR Article 22(2)(a) or (c), GDPR Article 22(3) gives at least the right to obtain human intervention, to express a point of view and to contest the decision, and GDPR Articles 13(2)(f), 14(2)(g) and 15(1)(h) require meaningful information about the logic involved. The system may not currently support this.
> *Article refs: Art.13, Art.86(1)*
> - *Mitigation (preventive, planned):* Return the four inputs that contributed most to each score as reason codes, for the lender to pass to the applicant on request. (Owner: Model Development team; Recorded by: Mara Lindqvist, Head of Model Risk)

**🟡 Users not told they are interacting with or assessed by an AI system** (Score: 9 → Residual: 9)
> Question TR-001: Are users notified that they are interacting with or being assessed by an AI system? Article 26(11) requires deployers of Annex III high-risk AI systems that make or assist in making decisions related to natural persons to inform them that they are subject to the use of the system. Article 50(1) covers informing natural persons that they are interacting with an AI system.
> *Article refs: Art.26(11), Art.50(1)*
> *Knowledge gap: Answered unknown, so the provider has not judged this risk yet. It is scored at the default, likelihood 3 and severity 3, until it is assessed.*

**🟠 No explanation of the decision logic available to affected people** (Score: 12 → Residual: 12)
> Question TR-002: Is an explanation of the system's decision-making logic available to affected individuals upon request? GDPR Article 22(1) gives a right not to be subject to a decision based solely on automated processing, including profiling, which produces legal effects or similarly significantly affects the person. GDPR Articles 13(2)(f), 14(2)(g) and 15(1)(h) require meaningful information about the logic involved. An explanation capability is a key technical control.
> *Article refs: Art.13(3)(b)(iv), Art.86(1)*
> - *Mitigation (preventive, planned):* Return the four inputs that contributed most to each score as reason codes, for the lender to pass to the applicant on request. (Owner: Model Development team; Recorded by: Mara Lindqvist, Head of Model Risk)

**🟡 Documentation omits capability limitations and known failure modes** (Score: 9 → Residual: 6)
> Question TR-003: Does the system documentation include clear capability limitations, known failure modes, and out-of-distribution behaviour? Article 13(3)(b) requires information about the system's capabilities and limitations for the benefit of deployers.
> *Article refs: Art.13(3)(b)*
> - *Mitigation (preventive, implemented):* Add a limitations section to the instructions for use: the training data is from 1994 and in DM, the collection and the meaning of good and bad are not documented, representativeness is unknown, and code A47 is uncertain. (Owner: Product team; Recorded by: Mara Lindqvist, Head of Model Risk)

### Human Oversight

**🟡 Reviewers not trained on the system's capabilities, limitations and known biases** (Score: 9 → Residual: 9)
> Question HO-002: Are human reviewers trained on the system's capabilities, limitations, and known biases before making decisions based on its output? Untrained human reviewers provide illusory oversight. Article 26(2) requires deployers to assign human oversight to natural persons who have the necessary competence, training and authority.
> *Article refs: Art.26(2)*
> *Knowledge gap: Answered unknown, so the provider has not judged this risk yet. It is scored at the question's hint, likelihood 3 and severity 3, until it is assessed.*

**🟠 Review workload too high for meaningful human oversight** (Score: 12 → Residual: 12)
> Question HO-003: Is the human oversight load (volume of cases reviewed per reviewer per day) realistic for meaningful review, not rubber-stamping? Automation bias and review fatigue cause human oversight to become nominal. Workload design is a technical control.
> *Article refs: Art.14*
> *Knowledge gap: Answered unknown, so the provider has not judged this risk yet. It is scored at the question's hint, likelihood 3 and severity 4, until it is assessed.*

**🟠 System reasoning not interpretable to human reviewers** (Score: 12 → Residual: 12)
> Question HO-004: Is the system designed to make its reasoning interpretable to human reviewers (e.g. via explainability methods, confidence scores, supporting evidence)? Human oversight is only meaningful if the reviewer can understand what the system decided and why.
> *Article refs: Art.14(4)(c)*
> - *Mitigation (preventive, planned):* Show the credit officer the reason codes and the score band next to each score. (Owner: Model Development team; Recorded by: Mara Lindqvist, Head of Model Risk)

### Robustness

**🟠 Not tested on out-of-distribution, edge-case and adversarial inputs** (Score: 16 → Residual: 16)
> Question RO-001: Has the system been tested against out-of-distribution inputs, edge cases, and adversarial perturbations? Article 9(6) and (8) require testing against prior defined metrics and probabilistic thresholds appropriate to the intended purpose. Article 15(5) covers resilience against adversarial examples.
> *Article refs: Art.9(6), Art.15*
> - *Mitigation (detective, planned):* Before release, test on a recent sample of the lender's own applicants with amounts converted from DM to euro, plus edge cases (extreme amount and duration) and small input perturbations; the cost-weighted error must not exceed the hold-out value by more than 10 percent. (Owner: Model Validation team; Recorded by: Mara Lindqvist, Head of Model Risk)

**🟠 Performance metrics not documented for each demographic subgroup** (Score: 16 → Residual: 16)
> Question RO-002: Are accuracy, precision, recall, and calibration metrics documented across all relevant demographic subgroups? Aggregate metrics can mask poor performance for subpopulations. Slice-level evaluation is required for high-risk systems.
> *Article refs: Art.9(8), Art.10(2)(f)*
> - *Mitigation (detective, planned):* Report accuracy, precision, recall, calibration error and cost under the dataset's cost matrix (5 for a bad applicant scored good, 1 for the reverse) per subgroup on the hold-out set. (Owner: Model Validation team; Recorded by: Mara Lindqvist, Head of Model Risk)

**🟡 No performance floor below which the system is taken offline** (Score: 9 → Residual: 9)
> Question RO-003: Is there a defined performance floor (minimum acceptable metric threshold) below which the system is taken offline? A defined performance floor ensures degraded models do not remain in production. This is a key operational control.
> *Article refs: Art.9(8), Art.72*

**🔴 Drift not monitored, or no procedure to respond to it** (Score: 20 → Residual: 20)
> Question RO-004: Are model degradation scenarios (data drift, concept drift, distribution shift) monitored and have defined response procedures? Models degrade over time as real-world data distributions shift. Post-market monitoring under Article 72 requires detection and response.
> *Article refs: Art.72*
> - *Mitigation (preventive, planned):* Retrain on recent applicant data from the lender before release, and do not put the model trained only on the 1994 records into production. (Owner: Model Development team; Recorded by: Mara Lindqvist, Head of Model Risk)
> - *Mitigation (detective, planned):* Compute the population stability index of every input and of the score each month; above 0.25 the lender is alerted and the model is reviewed within 30 days. (Owner: MLOps team; Recorded by: Mara Lindqvist, Head of Model Risk)

### Data Governance

**🟠 Dataset provenance not documented** (Score: 12 → Residual: 12)
> Question DG-001: Is the provenance of all training, validation, and test datasets documented (source, collection date, license, version)? Article 10(2) requires data governance practices including documentation of dataset provenance. TraceForge can automate this.
> *Article refs: Art.10(2), Art.10(2)(b)*
> *Accepted: The creator, DOI, licence and file dates are recorded, but when, where and from whom the 1994 records were collected is not published and cannot be recovered. The gap is stated in the limitations section, and the model is retrained on recent lender data before release, so the remaining provenance gap is accepted.*
> *Accepted by: Mara Lindqvist, Head of Model Risk*

**🟡 Data quality not checked before training** (Score: 9 → Residual: 9)
> Question DG-003: Are data quality checks (completeness, consistency, accuracy) applied and documented before training and fine-tuning? Article 10(3) requires training, validation and testing data sets to be, to the best extent possible, free of errors and complete in view of the intended purpose. Article 10(2)(c) covers data-preparation processing operations such as cleaning.
> *Article refs: Art.10(3), Art.10(2)(c)*

**🟢 No retention and deletion schedule for training data and inference logs** (Score: 4 → Residual: 4)
> Question DG-004: Is there a data retention and deletion schedule that covers both training data and inference logs? Data retained beyond its purpose creates ongoing legal and privacy risk. GDPR Article 5(1)(e) requires storage limitation.
> *Article refs: Art.19(1), Art.26(6)*
> *Knowledge gap: Answered unknown, so the provider has not judged this risk yet. It is scored at the question's hint, likelihood 2 and severity 2, until it is assessed.*

---

## Test Requirements

| Risk item | Metric | Test | Threshold | Article |
| --- | --- | --- | --- | --- |
| `4d19141a` | demographic\_parity\_gap | Risk: Demographic bias in credit scoring outputs. Measure: Largest difference in positive-outcome rate between protected groups. Set the threshold before testing, appropriate to the intended purpose. | set by the provider before testing | Art.9(8) |
| `b0a71cc7` | explanation\_request\_fulfilment | Risk: Lack of explanation for credit decisions. Measure: Share of explanation requests answered with the decision logic within the set time. Set the threshold before testing, appropriate to the intended purpose. | set by the provider before testing | Art.9(8) |
| `3fe03c51` | degradation\_alert\_time\_min | Risk: Production performance not monitored for degradation. Measure: Minutes from an injected performance drop to the alert. Set the threshold before testing, appropriate to the intended purpose. | set by the provider before testing | Art.9(8) |
| `9a85d48a` | vulnerable\_group\_error\_gap | Risk: System errors may harm vulnerable groups disproportionately. Measure: Largest difference in error rate between vulnerable groups and other people affected. Set the threshold before testing, appropriate to the intended purpose. | set by the provider before testing | Art.9(8) |
| `bfc52b79` | rights\_impact\_assessment\_coverage | Risk: No fundamental rights impact assessment before deployment. Measure: Share of deployment contexts covered by a completed fundamental rights impact assessment. Set the threshold before testing, appropriate to the intended purpose. | set by the provider before testing | Art.9(8) |
| `a3baa3a9` | adverse\_decision\_rate\_gap | Risk: System may restrict access to rights under the EU Charter of Fundamental Rights. Measure: Largest difference in adverse-decision rate between groups of affected people. Set the threshold before testing, appropriate to the intended purpose. | set by the provider before testing | Art.9(8) |
| `52fd5c53` | ai\_role\_notice\_coverage | Risk: Affected people not told of the AI system's role in decisions about them. Measure: Share of decisions about a person that come with a notice of the AI system's role. Set the threshold before testing, appropriate to the intended purpose. | set by the provider before testing | Art.9(8) |
| `8f114d3b` | representation\_gap | Risk: Training data not audited for representation imbalance across protected groups. Measure: Largest gap between a protected group's share of the training data and its share of the people the system serves. Set the threshold before testing, appropriate to the intended purpose. | set by the provider before testing | Art.9(8) |
| `88979633` | demographic\_parity\_gap | Risk: Fairness metrics not computed for each protected group. Measure: Largest difference in positive-outcome rate between protected groups. Set the threshold before testing, appropriate to the intended purpose. | set by the provider before testing | Art.9(8) |
| `d589bef0` | proxy\_correlation | Risk: Proxy variables may encode protected characteristics. Measure: Strongest correlation between an input feature and a protected characteristic. Set the threshold before testing, appropriate to the intended purpose. | set by the provider before testing | Art.9(8) |
| `58653409` | bias\_retest\_coverage | Risk: Bias tests not repeated at each model update. Measure: Share of model updates released with a documented bias test. Set the threshold before testing, appropriate to the intended purpose. | set by the provider before testing | Art.9(8) |
| `7112e1e6` | unprotected\_personal\_data\_rate | Risk: System processes personal or special category data. Measure: Share of personal data records stored or sent without the planned protection, such as encryption, access control or pseudonymisation. Set the threshold before testing, appropriate to the intended purpose. | set by the provider before testing | Art.9(8) |
| `470efd58` | dpia\_coverage | Risk: No Data Protection Impact Assessment carried out. Measure: Share of processing operations covered by a completed Data Protection Impact Assessment. Set the threshold before testing, appropriate to the intended purpose. | set by the provider before testing | Art.9(8) |
| `2fd59a99` | unneeded\_personal\_data\_fields | Risk: Model uses more personal data than its purpose needs. Measure: Number of personal data fields the model uses that its purpose does not need. Set the threshold before testing, appropriate to the intended purpose. | set by the provider before testing | Art.9(8) |
| `1f588c48` | ai\_disclosure\_coverage | Risk: Users not told they are interacting with or assessed by an AI system. Measure: Share of interactions and assessments that tell the person an AI system is involved. Set the threshold before testing, appropriate to the intended purpose. | set by the provider before testing | Art.9(8) |
| `b4ce87da` | explanation\_request\_fulfilment | Risk: No explanation of the decision logic available to affected people. Measure: Share of explanation requests answered with the decision logic within the set time. Set the threshold before testing, appropriate to the intended purpose. | set by the provider before testing | Art.9(8) |
| `4aec60b2` | documented\_failure\_mode\_coverage | Risk: Documentation omits capability limitations and known failure modes. Measure: Share of failure modes found in testing that the documentation describes. Set the threshold before testing, appropriate to the intended purpose. | set by the provider before testing | Art.9(8) |
| `a29fc827` | reviewer\_training\_coverage | Risk: Reviewers not trained on the system's capabilities, limitations and known biases. Measure: Share of human reviewers trained on the system's capabilities, limitations and known biases. Set the threshold before testing, appropriate to the intended purpose. | set by the provider before testing | Art.9(8) |
| `45d9b8c1` | review\_time\_per\_case\_s | Risk: Review workload too high for meaningful human oversight. Measure: Median seconds a reviewer spends on each case. Set the threshold before testing, appropriate to the intended purpose. | set by the provider before testing | Art.9(8) |
| `6b73bccd` | reviewer\_explanation\_coverage | Risk: System reasoning not interpretable to human reviewers. Measure: Share of outputs shown to reviewers with an explanation, confidence score or supporting evidence. Set the threshold before testing, appropriate to the intended purpose. | set by the provider before testing | Art.9(8) |
| `c582db0b` | stress\_set\_accuracy | Risk: Not tested on out-of-distribution, edge-case and adversarial inputs. Measure: Accuracy on a held-out set of edge-case, out-of-distribution and perturbed inputs. Set the threshold before testing, appropriate to the intended purpose. | set by the provider before testing | Art.9(8) |
| `6966164c` | subgroup\_performance\_gap | Risk: Performance metrics not documented for each demographic subgroup. Measure: Largest difference in accuracy, precision, recall or calibration between demographic subgroups. Set the threshold before testing, appropriate to the intended purpose. | set by the provider before testing | Art.9(8) |
| `4d9a0d99` | floor\_breach\_response\_time\_min | Risk: No performance floor below which the system is taken offline. Measure: Minutes from a breach of the performance floor to the system being taken offline. Set the threshold before testing, appropriate to the intended purpose. | set by the provider before testing | Art.9(8) |
| `8b37639c` | drift\_detection\_time\_h | Risk: Drift not monitored, or no procedure to respond to it. Measure: Hours from an injected data or concept drift to its detection. Set the threshold before testing, appropriate to the intended purpose. | set by the provider before testing | Art.9(8) |
| `9c0ab3b0` | dataset\_provenance\_coverage | Risk: Dataset provenance not documented. Measure: Share of training, validation and test datasets with a documented source, collection date, licence and version. Set the threshold before testing, appropriate to the intended purpose. | set by the provider before testing | Art.9(8) |
| `8f5d52fb` | data\_quality\_check\_pass\_rate | Risk: Data quality not checked before training. Measure: Share of completeness, consistency and accuracy checks passed before training. Set the threshold before testing, appropriate to the intended purpose. | set by the provider before testing | Art.9(8) |
| `a0daef02` | retention\_schedule\_coverage | Risk: No retention and deletion schedule for training data and inference logs. Measure: Share of training data stores and inference logs covered by a retention and deletion schedule. Set the threshold before testing, appropriate to the intended purpose. | set by the provider before testing | Art.9(8) |

---

## Change Log

| Seq | Time (UTC) | Event | Actor |
| --- | --- | --- | --- |
| 0 | 2026-11-07 18:32 | system.created | cli |
| 1 | 2026-11-07 18:32 | system.classified | cli |
| 2 | 2026-11-07 18:32 | register.created | Mara Lindqvist |
| 3 | 2026-11-07 18:32 | risk\_item.created | Mara Lindqvist |
| 4 | 2026-11-07 18:32 | risk\_item.created | Mara Lindqvist |
| 5 | 2026-11-07 18:32 | risk\_item.created | Mara Lindqvist |
| 6 | 2026-11-07 18:32 | risk\_item.created | Mara Lindqvist |
| 7 | 2026-11-07 18:32 | risk\_item.created | Mara Lindqvist |
| 8 | 2026-11-07 18:32 | risk\_item.created | Mara Lindqvist |
| 9 | 2026-11-07 18:32 | risk\_item.created | Mara Lindqvist |
| 10 | 2026-11-07 18:32 | risk\_item.created | Mara Lindqvist |
| 11 | 2026-11-07 18:32 | risk\_item.created | Mara Lindqvist |
| 12 | 2026-11-07 18:32 | risk\_item.created | Mara Lindqvist |
| 13 | 2026-11-07 18:32 | risk\_item.created | Mara Lindqvist |
| 14 | 2026-11-07 18:32 | risk\_item.created | Mara Lindqvist |
| 15 | 2026-11-07 18:32 | risk\_item.created | Mara Lindqvist |
| 16 | 2026-11-07 18:32 | risk\_item.created | Mara Lindqvist |
| 17 | 2026-11-07 18:32 | risk\_item.created | Mara Lindqvist |
| 18 | 2026-11-07 18:32 | risk\_item.created | Mara Lindqvist |
| 19 | 2026-11-07 18:32 | risk\_item.created | Mara Lindqvist |
| 20 | 2026-11-07 18:32 | risk\_item.created | Mara Lindqvist |
| 21 | 2026-11-07 18:32 | risk\_item.created | Mara Lindqvist |
| 22 | 2026-11-07 18:32 | risk\_item.created | Mara Lindqvist |
| 23 | 2026-11-07 18:32 | risk\_item.created | Mara Lindqvist |
| 24 | 2026-11-07 18:32 | risk\_item.created | Mara Lindqvist |
| 25 | 2026-11-07 18:32 | risk\_item.created | Mara Lindqvist |
| 26 | 2026-11-07 18:32 | risk\_item.created | Mara Lindqvist |
| 27 | 2026-11-07 18:32 | risk\_item.created | Mara Lindqvist |
| 28 | 2026-11-07 18:32 | risk\_item.created | Mara Lindqvist |
| 29 | 2026-11-07 18:32 | risk\_item.created | Mara Lindqvist |
| 30 | 2026-11-07 18:32 | risk\_item.created | Mara Lindqvist |
| 31 | 2026-11-07 18:32 | mitigation.added | Mara Lindqvist, Head of Model Risk |
| 32 | 2026-11-07 18:32 | mitigation.added | Mara Lindqvist, Head of Model Risk |
| 33 | 2026-11-07 18:32 | mitigation.added | Mara Lindqvist, Head of Model Risk |
| 34 | 2026-11-07 18:32 | mitigation.added | Mara Lindqvist, Head of Model Risk |
| 35 | 2026-11-07 18:32 | mitigation.added | Mara Lindqvist, Head of Model Risk |
| 36 | 2026-11-07 18:32 | mitigation.added | Mara Lindqvist, Head of Model Risk |
| 37 | 2026-11-07 18:32 | mitigation.added | Mara Lindqvist, Head of Model Risk |
| 38 | 2026-11-07 18:32 | mitigation.added | Mara Lindqvist, Head of Model Risk |
| 39 | 2026-11-07 18:32 | mitigation.added | Mara Lindqvist, Head of Model Risk |
| 40 | 2026-11-07 18:32 | mitigation.added | Mara Lindqvist, Head of Model Risk |
| 41 | 2026-11-07 18:32 | mitigation.added | Mara Lindqvist, Head of Model Risk |
| 42 | 2026-11-07 18:32 | mitigation.added | Mara Lindqvist, Head of Model Risk |
| 43 | 2026-11-07 18:32 | mitigation.added | Mara Lindqvist, Head of Model Risk |
| 44 | 2026-11-07 18:32 | mitigation.added | Mara Lindqvist, Head of Model Risk |
| 45 | 2026-11-07 18:32 | mitigation.added | Mara Lindqvist, Head of Model Risk |
| 46 | 2026-11-07 18:32 | mitigation.added | Mara Lindqvist, Head of Model Risk |
| 47 | 2026-11-07 18:32 | mitigation.added | Mara Lindqvist, Head of Model Risk |
| 48 | 2026-11-07 18:32 | mitigation.added | Mara Lindqvist, Head of Model Risk |
| 49 | 2026-11-07 18:32 | risk.accepted | Mara Lindqvist, Head of Model Risk |
| 50 | 2026-11-07 18:32 | tests.generated | cli |
| 51 | 2026-11-07 18:32 | rmf.exported | cli |

---

## Disclosure

*This document was produced using RiskForge v2.1.0, question bank version 1.0.0. It represents the team's documented risk assessment and has not been reviewed by a qualified legal professional. It does not constitute legal advice under the EU AI Act or any other regulation.*
