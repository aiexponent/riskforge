# Risk Management File: Retail Credit Risk Scorer v1.0.0

**Provider:** Northwind Scoring Labs (fictional)
**Purpose:** Credit scoring of retail consumer credit applicants: a binary classifier, trained on the UCI Statlog German Credit data, scores each applicant as good or bad credit risk, and a lender's credit officer uses the score when deciding on the application.
**Generated:** 2026-11-04
**RMF Schema Version:** 1.1.0
**SHA-256:** `9e53abfb36a7d22a8ed445f185e3ef0e8fc484d72f3a1c170845985f8af4bb23`

---

## Assessor
- **Name:** Mara Lindqvist
- **Role:** Head of Model Risk
- **Assessment Date:** 2026-11-04
- **Review Date:** 2027-10-30

---

## Risk Items (28 total)

### Health Safety

**🟠 Are system performance metrics (accuracy, error rates, latency) monitored in production with alerts for degradation?** (Score: 12 → Residual: 12)
> Post-market monitoring under Article 72 requires tracking of actual performance against stated specifications.
> *Article refs: Art.9(8), Art.72*
> - *Mitigation (detective, planned):* Track approval rate, observed bad rate at 12 months and cost-weighted error each month against the validation values, with an alert at a 20 percent relative change. (Owner: MLOps team; Recorded by: Mara Lindqvist, Head of Model Risk)

**🟠 Could vulnerable populations (elderly, children, people with disabilities) be disproportionately harmed by system errors...** (Score: 12 → Residual: 12)
> Article 9(9) requires explicit consideration of impacts on children and other vulnerable groups.
> *Article refs: Art.9(9)*
> - *Mitigation (detective, planned):* Report error rates and cost-weighted error by age band (under 25, 25 to 59, 60 and over) at each release and block release if a band is worse than the overall rate by more than 10 percent. (Owner: Model Validation team; Recorded by: Mara Lindqvist, Head of Model Risk)

### Fundamental Rights

**🟡 Has a fundamental rights impact assessment (FRIA) been conducted prior to deployment?** (Score: 9 → Residual: 9)
> Article 9(2)(a) requires identification of known and foreseeable risks to fundamental rights. A FRIA is the standard mechanism for this.
> *Article refs: Art.9(2)(a)*

**🟠 Could the system restrict or affect access to rights protected under the EU Charter of Fundamental Rights?** (Score: 12 → Residual: 12)
> Consider right to an effective remedy, right to a fair trial, presumption of innocence, freedom of expression, right to education.
> *Article refs: Art.9(2)(a)*
> - *Mitigation (corrective, planned):* State in the instructions for use that a refused applicant can ask for a second review by a credit officer who did not make the first decision, and that the score alone must not refuse an application. (Owner: Product team; Recorded by: Mara Lindqvist, Head of Model Risk)

**🟡 Are affected individuals informed of the AI system's role in decisions that affect them, in a language they understand?** (Score: 6 → Residual: 6)
> Transparency is a foundational right. The obligation to inform subjects is strengthened in high-risk AI contexts.
> *Article refs: Art.26(11)*

### Discrimination

**🟠 Demographic bias in credit scoring outputs** (Score: 12 → Residual: 12)
> Credit scoring models trained on historical data may encode systemic biases against protected groups (age, gender, ethnicity). Article 9(9) requires consideration of impacts on vulnerable groups.
> *Article refs: Art.9(2)(a), Art.9(9), Art.10(2)(f)*
> - *Mitigation (detective, planned):* Apply the release gate on demographic parity and equal opportunity difference (above 0.10 blocks release) by sex, age band and foreign worker flag. (Owner: Model Validation team; Recorded by: Mara Lindqvist, Head of Model Risk)

**🟠 Has the training dataset been audited for representation imbalances across protected characteristics (gender, ethnicity,...** (Score: 16 → Residual: 16)
> Biased training data produces biased outputs. Article 10(2)(f) requires data governance measures to address biases.
> *Article refs: Art.10(2)(f), Art.9(2)(a)*
> - *Mitigation (detective, implemented):* Report record counts and the share of bad class by the sex part of attribute 9, by age band (under 25, 25 to 59, 60 and over) and by foreign worker flag, and state that married and divorced women share one code. (Owner: Data Science team; Recorded by: Mara Lindqvist, Head of Model Risk)

**🟠 Have demographic parity, equalised odds, or other fairness metrics been computed and documented for each protected group...** (Score: 16 → Residual: 16)
> Quantified fairness metrics are required for meaningful bias assessment. Select metrics appropriate to the use case.
> *Article refs: Art.9(8), Art.10(2)(f)*
> - *Mitigation (detective, planned):* Compute demographic parity difference and equal opportunity difference by sex, age band and foreign worker flag on the hold-out set; block release if any difference is above 0.10. (Owner: Model Validation team; Recorded by: Mara Lindqvist, Head of Model Risk)

**🔴 Does the system use proxy variables that may correlate with protected characteristics (e.g. postcode, school name, emplo...** (Score: 20 → Residual: 12)
> Proxy discrimination occurs when facially neutral features encode protected characteristics. Legal exposure exists even without intent.
> *Article refs: Art.9(2)(a), Art.10(2)(f)*
> - *Mitigation (preventive, implemented):* Remove attributes 9 (personal status and sex), 13 (age) and 20 (foreign worker) from the model inputs. Keep them in a separate table used only for bias testing. (Owner: Model Development team; Recorded by: Mara Lindqvist, Head of Model Risk)
> - *Mitigation (detective, planned):* Measure the association of each remaining input with sex, age band and foreign worker status on the 1000 records, and drop or bin any input with Cramer's V above 0.3. (Owner: Model Validation team; Recorded by: Mara Lindqvist, Head of Model Risk)

**🟡 Are bias test results documented and reviewed at each model update, not just at initial deployment?** (Score: 6 → Residual: 6)
> Data drift and concept drift can re-introduce bias after initial mitigation. Continuous monitoring is required.
> *Article refs: Art.9(8), Art.72*

### Privacy

**🔴 Does the system process personal data or special category data (health, biometric, ethnicity, religion)?** (Score: 20 → Residual: 20)
> Processing of special category data triggers additional obligations under GDPR Article 9. EU AI Act Article 4a(1) allows providers of high-risk AI systems to process special categories of personal data exceptionally, to the extent strictly necessary to ensure bias detection and correction.
> *Article refs: Art.4a(1)*
> - *Mitigation (preventive, planned):* Record the legal basis for using the 1994 records and live applicant data, agreed with the lender's data protection officer, and list the personal data each input carries. (Owner: Legal and Privacy team; Recorded by: Mara Lindqvist, Head of Model Risk)

**🟡 Has a Data Protection Impact Assessment (DPIA) been carried out, with the advice of the Data Protection Officer where on...** (Score: 9 → Residual: 9)
> GDPR Article 35 requires a DPIA for high-risk processing. High-risk AI systems typically trigger this threshold.
> *Article refs: Art.26(9), Art.9(2)(a)*

**🟠 Is data minimisation enforced: does the model use only the minimum personal data necessary for the intended purpose?** (Score: 12 → Residual: 6)
> GDPR data minimisation and purpose limitation principles (GDPR Article 5(1)(b) and (c)) apply to AI systems processing personal data.
> - *Mitigation (preventive, implemented):* Remove attribute 19 (telephone) as well as attributes 9, 13 and 20 from the model inputs, and document why each remaining input is needed. (Owner: Model Development team; Recorded by: Mara Lindqvist, Head of Model Risk)

**🟡 Has the training data been scanned for inadvertent PII inclusion, and is PII redaction/pseudonymisation applied before t...** (Score: 6 → Residual: 6)
> Training data containing real PII creates privacy risk. Automated PII detection tools (e.g. TraceForge) can surface this.

### Transparency

**🟡 Lack of explanation for credit decisions** (Score: 9 → Residual: 9)
> Where a solely automated credit decision falls under GDPR Article 22(2)(a) or (c), GDPR Article 22(3) gives at least the right to obtain human intervention, to express a point of view and to contest the decision, and GDPR Articles 13(2)(f), 14(2)(g) and 15(1)(h) require meaningful information about the logic involved. The system may not currently support this.
> *Article refs: Art.13, Art.86(1)*
> - *Mitigation (preventive, planned):* Return the four inputs that contributed most to each score as reason codes, for the lender to pass to the applicant on request. (Owner: Model Development team; Recorded by: Mara Lindqvist, Head of Model Risk)

**🟡 Are users notified that they are interacting with or being assessed by an AI system?** (Score: 9 → Residual: 9)
> Article 26(11) requires deployers of Annex III high-risk AI systems that make or assist in making decisions related to natural persons to inform them that they are subject to the use of the system. Article 50(1) covers informing natural persons that they are interacting with an AI system.
> *Article refs: Art.26(11), Art.50(1)*

**🟠 Is an explanation of the system's decision-making logic available to affected individuals upon request?** (Score: 12 → Residual: 12)
> GDPR Article 22(1) gives a right not to be subject to a decision based solely on automated processing, including profiling, which produces legal effects or similarly significantly affects the person. GDPR Articles 13(2)(f), 14(2)(g) and 15(1)(h) require meaningful information about the logic involved. An explanation capability is a key technical control.
> *Article refs: Art.13(3)(b)(iv), Art.86(1)*
> - *Mitigation (preventive, planned):* Return the four inputs that contributed most to each score as reason codes, for the lender to pass to the applicant on request. (Owner: Model Development team; Recorded by: Mara Lindqvist, Head of Model Risk)

**🟡 Does the system documentation include clear capability limitations, known failure modes, and out-of-distribution behavio...** (Score: 9 → Residual: 6)
> Article 13(3)(b) requires information about the system's capabilities and limitations for the benefit of deployers.
> *Article refs: Art.13(3)(b)*
> - *Mitigation (preventive, implemented):* Add a limitations section to the instructions for use: the training data is from 1994 and in DM, the collection and the meaning of good and bad are not documented, representativeness is unknown, and code A47 is uncertain. (Owner: Product team; Recorded by: Mara Lindqvist, Head of Model Risk)

### Human Oversight

**🟡 Are human reviewers trained on the system's capabilities, limitations, and known biases before making decisions based on...** (Score: 9 → Residual: 9)
> Untrained human reviewers provide illusory oversight. Article 26(2) requires deployers to assign human oversight to natural persons who have the necessary competence, training and authority.
> *Article refs: Art.26(2)*

**🟠 Is the human oversight load (volume of cases reviewed per reviewer per day) realistic for meaningful review, not rubber-...** (Score: 12 → Residual: 12)
> Automation bias and review fatigue cause human oversight to become nominal. Workload design is a technical control.
> *Article refs: Art.14*

**🟠 Is the system designed to make its reasoning interpretable to human reviewers (e.g. via explainability methods, confiden...** (Score: 12 → Residual: 12)
> Human oversight is only meaningful if the reviewer can understand what the system decided and why.
> *Article refs: Art.14(4)(c)*
> - *Mitigation (preventive, planned):* Show the credit officer the reason codes and the score band next to each score. (Owner: Model Development team; Recorded by: Mara Lindqvist, Head of Model Risk)

### Robustness

**🟠 Has the system been tested against out-of-distribution inputs, edge cases, and adversarial perturbations?** (Score: 16 → Residual: 16)
> Article 9(6) and (8) require testing against prior defined metrics and probabilistic thresholds appropriate to the intended purpose. Article 15(5) covers resilience against adversarial examples.
> *Article refs: Art.9(6), Art.15*
> - *Mitigation (detective, planned):* Before release, test on a recent sample of the lender's own applicants with amounts converted from DM to euro, plus edge cases (extreme amount and duration) and small input perturbations; the cost-weighted error must not exceed the hold-out value by more than 10 percent. (Owner: Model Validation team; Recorded by: Mara Lindqvist, Head of Model Risk)

**🟠 Are accuracy, precision, recall, and calibration metrics documented across all relevant demographic subgroups?** (Score: 16 → Residual: 16)
> Aggregate metrics can mask poor performance for subpopulations. Slice-level evaluation is required for high-risk systems.
> *Article refs: Art.9(8), Art.10(2)(f)*
> - *Mitigation (detective, planned):* Report accuracy, precision, recall, calibration error and cost under the dataset's cost matrix (5 for a bad applicant scored good, 1 for the reverse) per subgroup on the hold-out set. (Owner: Model Validation team; Recorded by: Mara Lindqvist, Head of Model Risk)

**🟡 Is there a defined performance floor (minimum acceptable metric threshold) below which the system is taken offline?** (Score: 9 → Residual: 9)
> A defined performance floor ensures degraded models do not remain in production. This is a key operational control.
> *Article refs: Art.9(8), Art.72*

**🔴 Are model degradation scenarios (data drift, concept drift, distribution shift) monitored and have defined response proc...** (Score: 20 → Residual: 20)
> Models degrade over time as real-world data distributions shift. Post-market monitoring under Article 72 requires detection and response.
> *Article refs: Art.72*
> - *Mitigation (preventive, planned):* Retrain on recent applicant data from the lender before release, and do not put the model trained only on the 1994 records into production. (Owner: Model Development team; Recorded by: Mara Lindqvist, Head of Model Risk)
> - *Mitigation (detective, planned):* Compute the population stability index of every input and of the score each month; above 0.25 the lender is alerted and the model is reviewed within 30 days. (Owner: MLOps team; Recorded by: Mara Lindqvist, Head of Model Risk)

### Data Governance

**🟠 Is the provenance of all training, validation, and test datasets documented (source, collection date, license, version)?** (Score: 12 → Residual: 12)
> Article 10(2) requires data governance practices including documentation of dataset provenance. TraceForge can automate this.
> *Article refs: Art.10(2), Art.10(2)(b)*
> *Accepted: The creator, DOI, licence and file dates are recorded, but when, where and from whom the 1994 records were collected is not published and cannot be recovered. The gap is stated in the limitations section, and the model is retrained on recent lender data before release, so the remaining provenance gap is accepted.*
> *Accepted by: Mara Lindqvist, Head of Model Risk*

**🟡 Are data quality checks (completeness, consistency, accuracy) applied and documented before training and fine-tuning?** (Score: 9 → Residual: 9)
> Article 10(3) requires training, validation and testing data sets to be, to the best extent possible, free of errors and complete in view of the intended purpose. Article 10(2)(c) covers data-preparation processing operations such as cleaning.
> *Article refs: Art.10(3), Art.10(2)(c)*

**🟢 Is there a data retention and deletion schedule that covers both training data and inference logs?** (Score: 4 → Residual: 4)
> Data retained beyond its purpose creates ongoing legal and privacy risk. GDPR Article 5(1)(e) requires storage limitation.
> *Article refs: Art.19(1), Art.26(6)*

---

## Disclosure

*This document was produced using RiskForge v2.0.0, question bank version 1.0.0. It represents the team's documented risk assessment and has not been reviewed by a qualified legal professional. It does not constitute legal advice under the EU AI Act or any other regulation.*
