# Article 9 Mapping

> Reference documentation for practitioners. Reads paragraph-by-paragraph against
> Regulation (EU) 2024/1689 (the "EU AI Act") and shows what RiskForge addresses,
> what it does not, and which validation gate enforces each control.
>
> Primary source for every regulatory quote in this file: the Official Journal text
> of Regulation (EU) 2024/1689 (CELEX:32024R1689) and its consolidated text as at
> 27 July 2026, which includes the amendments made by Regulation (EU) 2026/1744.
> Re-checked 2026-10-17. URL: <https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32024R1689>.

## Audience

You are a compliance lead, in-house counsel, or AI governance engineer who has
read Articles 9 through 15 of the EU AI Act and Annex IV. You want to know,
control by control, where RiskForge fits in your evidence pack and where it does
not. This document is reference material, not marketing. If a control is not
implemented, the section will say so plainly and point at the planned milestone.

---

## 1. Article 9 overview

Article 9 (Risk management system) is a core obligation for providers of
high-risk AI systems under Chapter III, Section 2 of the EU AI Act. It requires:

- a documented, **lifecycle-long** risk management system, not a one-off
  assessment;
- identification of known and reasonably foreseeable risks to **health, safety
  and fundamental rights**;
- estimation and evaluation of those risks under the system's intended purpose
  and under reasonably foreseeable misuse;
- targeted **mitigation measures** with residual-risk acceptance;
- testing to identify the most appropriate and targeted risk management measures and to ensure the system performs consistently for its intended purpose (Article 9(6) to (8));
- consideration of whether the system is likely to have an adverse impact on **persons under 18** and, as appropriate, other vulnerable groups.

### When it applies

Article 9 obligations for high-risk AI systems apply from **2 December 2027** for
systems classified as high-risk under Article 6(2) and Annex III, and **2 August 2028**
for systems classified as high-risk under Article 6(1) and Annex I, Section A. These dates are set by Article 113, third paragraph,
point (c), as amended by Regulation (EU) 2026/1744, which was published in the
Official Journal on 24 July 2026 and has been in force since 27 July 2026. The
original dates were 2 August 2026 (the general date, which covered Annex III)
and 2 August 2027 (Article 6(1)).

Article 9 does not apply to systems classified as high-risk under Article 6(1)
that are related to products covered by the legislation in Annex I, Section B.
For those systems Article 2(2), as replaced by Regulation (EU) 2026/1744, provides
that "only Article 6(1), Article 60a and Articles 102 to 112 shall apply". The
original Article 2(2) also left Article 9 out for these systems.

For the avoidance of doubt:

- Articles 5 (prohibited practices) and 4 (AI literacy) apply from
  2 February 2025 (Article 113, third paragraph, point (a)), earlier than
  Article 9. Article 99 (penalties) applies from 2 August 2025 (point (b)), and the
  points added to Article 5 by Regulation (EU) 2026/1744 (Article 5(1), first
  subparagraph, points (ba) and (bb), and Article 5(1a) and (1b)) apply from
  2 December 2026.
- The high-risk requirements and obligations in Chapter III, Sections 1 to 3
  (including Article 9) apply from
  2 December 2027 (Annex III) or 2 August 2028 (Annex I, Section A) under Article 113,
  third paragraph, point (c), as amended by Regulation (EU) 2026/1744. Systems
  related to products covered by Annex I, Section B are outside Article 9
  (Article 2(2)).
- Some general-purpose AI model obligations have a different timeline and are not
  in scope for this document.

### Penalty band

Non-compliance with Article 9 routes through the Article 16 provider obligations
and is sanctionable under Article 99(4):

> *"Non-compliance with any of the following provisions related to operators or
> notified bodies, other than those laid down in Articles 5, shall be subject to
> administrative fines of up to EUR 15 000 000 or, if the offender is an
> undertaking, up to 3 % of its total worldwide annual turnover for the
> preceding financial year, **whichever is higher**: …"*
> Article 99(4), EU AI Act (verbatim per the Official Journal text, re-checked
> 2026-10-17; "Articles 5" is as published)

"Whichever is higher" applies in general. For SMEs, including start-ups, the
lower of the two amounts applies (Article 99(6)), and since Regulation (EU)
2026/1744 the same holds for small mid-cap enterprises (Article 99(6a)).

---

## 2. Paragraph-by-paragraph mapping

The following sections walk Article 9(1) through Article 9(10). For each
paragraph:

1. The verbatim text from the Official Journal (CELEX:32024R1689).
2. A plain-English summary.
3. **What RiskForge does** to address the paragraph, with file paths and
   question IDs from the question bank at
   `src/riskforge/_data/question_bank/`.
4. **What RiskForge does NOT do**: the named gap.
5. **Validation gate(s)**: which of the eight readiness gates in
   `src/riskforge/engine/validate.py` enforce the paragraph before export.

The eight gates (`G1` to `G8`) are documented inline so the cross-references make
sense without flipping files:

| Gate | Purpose | Severity |
| --- | --- | --- |
| G1 | All 8 risk dimensions have at least one risk item | FAIL |
| G2 | Article 6(2) self-classification documented | FAIL |
| G3 | Residual score above the risk-appetite threshold must be reduced or accepted | FAIL |
| G4 | Knowledge gaps have saved test requirements | WARN |
| G5 | System metadata complete (name, version, purpose, provider) | FAIL |
| G6 | Assessor identity recorded | FAIL |
| G7 | Risk score distribution plausible (catches all-low-score whitewash) | WARN |
| G8 | No vague mitigations | WARN |

A `FAIL` gate blocks export unless `--force` is passed. A `WARN` gate is surfaced
in the export but does not block. All eight gates run before every export unless
`--force` is given (`ValidateEngine.run` in `src/riskforge/engine/validate.py`).

---

### Article 9(1)

> *"A risk management system shall be established, implemented, documented and
> maintained in relation to high-risk AI systems."*

**Plain English.** A provider of a high-risk system needs a *system*, a
recurring process, to manage risk. Not a checklist, not a one-page memo. It has
to be set up, run, written down, and kept up to date.

**What RiskForge does.**

- Initialises a versioned project on disk: `riskforge init` writes a
  `riskforge.yaml` manifest plus a `.riskforge/` working tree containing
  the system record, the risk register, and the audit chain (the layout is
  described at the top of `src/riskforge/storage/filesystem.py`).
- Captures the assessment as data (`register.yaml`, `mitigations.yaml`) so it
  is diffable and reviewable in git rather than living inside a Word document
  no one re-opens.
- Stamps every state mutation into an append-only audit log
  (`audit.jsonl`), together with a fingerprint of the register it produced;
  see `docs/audit-chain-design.md`.
- Produces a **Risk Management File (RMF)** as JSON, Markdown, and PDF via
  `riskforge export`. The RMF is the "documented" artefact Article 9(1)
  refers to.

**What RiskForge does NOT do.**

- It does not enforce a maintenance cadence. Article 9(1) requires the system
  to be *maintained*; RiskForge does not currently emit reminders, schedule
  reviews, or notify owners when an assessment is stale. Operationalising
  cadence is the provider's responsibility, typically by attaching the
  project to a calendar or ticketing process.
- It does not federate across multiple high-risk systems within an
  organisation (no cross-system rollup view).

**Validation gate(s).**

- **G5** enforces system metadata completeness (name, version, purpose,
  provider_name). Without these the RMF is not a "documented" artefact in any
  defensible sense.
- **G2** enforces that Annex III self-classification under Article 6(2) is
  documented before export.

---

### Article 9(2)(a)

> *"The risk management system shall be understood as a continuous iterative
> process planned and run throughout the entire lifecycle of a high-risk AI
> system, requiring regular systematic review and updating. It shall comprise
> the following steps:*
>
> *(a) the identification and analysis of the known and the reasonably
> foreseeable risks that the high-risk AI system can pose to health, safety or
> fundamental rights when the high-risk AI system is used in accordance with
> its intended purpose;"*

**Plain English.** Identify *known* risks and *reasonably foreseeable* risks
across three categories (health, safety, fundamental rights) for the system
operating as intended.

**What RiskForge does.**

The 37-question bank is structured to force a sweep across all three categories:

- **Health & safety**, file `src/riskforge/_data/question_bank/health_safety.yaml`:
  6 questions: HS-001 (clinical/safety/physical decisions without mandatory
  human review), HS-002 (physical harm from failure), HS-003 (emergency
  override), HS-004 (FMEA / failure-mode analysis), HS-005 (production
  monitoring), HS-006 (vulnerable populations). HS-006 is the explicit
  Article 9(9) hook on children and vulnerable groups.
- **Fundamental rights**, file
  `src/riskforge/_data/question_bank/fundamental_rights.yaml`: 4 questions:
  FR-001 (FRIA conducted), FR-002 (Charter rights affected), FR-003 (subjects
  informed), FR-004 (human review for fundamental-rights-significant
  decisions).
- **Discrimination**, file
  `src/riskforge/_data/question_bank/discrimination.yaml`: 4 questions
  (DI-001 through DI-004): representation imbalance, fairness metrics, proxy
  discrimination, drift-aware bias monitoring. Maps to Art. 9(2)(a) and
  Art. 10(2)(f).
- **Privacy**, file `src/riskforge/_data/question_bank/privacy.yaml`:
  PR-001 through PR-005, anchoring the GDPR overlay (special category data,
  DPIA, minimisation, training-data PII screening, output-side membership
  inference).

Hazard identification is not optional: gate **G1** fails the export if any of
the 8 dimensions has no risk item. Its message names the missing dimensions and
tells you to run `riskforge assess <system-id> -a NAME -r ROLE --dimension <dimension>`
for each one.

**What RiskForge does NOT do.**

- It does not generate hazards from a corpus of past incidents: there is no
  built-in incident database. The question bank is a structured prompt, not an
  oracle.
- It does not perform automated hazard discovery from system artefacts (model
  cards, telemetry, and so on).
- It does not adjudicate whether an identified risk is "reasonably
  foreseeable": that judgement remains with the assessor.

**Validation gate(s).** **G1** (dimension coverage), **G6** (assessor identity
attached to that judgement).

---

### Article 9(2)(b)

> *"(b) the estimation and evaluation of the risks that may emerge when the
> high-risk AI system is used in accordance with its intended purpose, and
> under conditions of reasonably foreseeable misuse;"*

**Plain English.** For each identified risk, estimate likelihood and severity
under both intended-use and foreseeable-misuse conditions.

**What RiskForge does.**

- Implements a 5×5 likelihood × severity matrix. Each risk item carries
  `risk_score = likelihood * severity` (1 to 25). See risk model fields in
  `src/riskforge/models/risk.py`.
- Each question carries a `default_likelihood_hint` and `default_severity_hint`
  in its YAML record (for example HS-002: likelihood 2 and severity 5, a rare
  but catastrophic failure). Hints are starting points, not verdicts; the assessor
  must score the system in front of them.
- Annex III scenario tagging: each question carries
  `annex_iii_categories` (employment, education, law_enforcement,
  essential_services, biometric, justice, migration, health,
  critical_infrastructure). Patterns use the system's Annex III category to decide
  which pre-built risks to add; every question is asked whatever the category. The `health` tag in
  privacy.yaml is not an Annex III category.

**What RiskForge does NOT do.**

- It does **not** include a misuse-pattern library beyond **7 patterns**. Six
  are tied to the Annex III point they cover: credit scoring (5(b)), recruitment
  and CV screening (4(a)), remote biometric identification (1(a)), assessment of
  learning outcomes (3(b)), asylum, visa and residence applications (7(c)), and
  offending risk assessment (6(d)). One covers medical diagnosis and clinical
  decision support, high-risk under Art. 6(1) where the AI system is, or is a
  safety component of, a medical device covered by Annex I that must undergo a
  third-party conformity assessment. New patterns arrive through
  `docs/contributing/add-pattern.md`.
- It does not run automated stress tests against the system; the assessor must
  supply the misuse-scenario reasoning.

**Validation gate(s).** **G3** (residual score above threshold must be reduced
or explicitly accepted), **G7** (catches the "everything scored low" pattern that
neuters Article 9(2)(b)).

---

### Article 9(2)(c)

> *"(c) the evaluation of other risks possibly arising, based on the analysis
> of data gathered from the post-market monitoring system referred to in
> Article 72;"*

**Plain English.** Risk management is not just pre-deployment; the post-market
monitoring system has to feed back into the risk management system.

**What RiskForge does.** **Nothing directly.** Evaluating risks from post-market
monitoring under Article 72 is out of scope for RiskForge. It is planned as a
module of Sigil, another AI Exponent tool, which has not been released.

RiskForge addresses the **pre-deployment** half of the lifecycle. Several
questions reference Article 72 (HS-005, DI-004, RO-003, RO-004) but they document
the *requirement* that monitoring exist; they do not ingest monitoring telemetry.

**What RiskForge does NOT do.**

- No connector to deployed-system telemetry.
- No incident-loop mechanism to re-open a previously-closed risk item when
  post-market evidence contradicts it.
- No serious-incident reporting workflow under Article 73.

**Roadmap.** None in RiskForge. Post-market monitoring belongs to the planned
Sigil module named above.

**Validation gate(s).** No gate currently enforces 9(2)(c), by design,
because the data does not exist in scope. Adding a gate would create false
assurance.

---

### Article 9(2)(d)

> *"(d) the adoption of appropriate and targeted risk management measures
> designed to address the risks identified pursuant to point (a)."*

**Plain English.** For each risk you identified in (a), pick a specific
mitigation. Not "we'll do our best", but a targeted control.

**What RiskForge does.**

- Each risk item in the register can carry one or more `Mitigation` entries
  (see the model in `src/riskforge/models/risk.py`). Mitigations are flat-listed
  in `mitigations.yaml` for readability with a back-link to the parent risk.
- Gate **G8** flags vague mitigations, such as "tbd" or "we'll monitor it",
  using one whole-phrase list in `src/riskforge/models/risk.py`. WARN, not FAIL,
  but surfaced in the export.
- Gate **G3** fails the export if a risk's residual score is above the
  register's risk appetite threshold (9 by default) and the risk is not
  accepted. The provider must mitigate it until the residual score is within
  the threshold, or accept it with a rationale and a name (`--by`).

**What RiskForge does NOT do.**

- It does not propose mitigations from a control library. The assessor must
  draft the control text. A future feature could surface NIST
  AI RMF MANAGE controls or ISO/IEC 42001 Annex A controls as starting points;
  this is roadmap, not current.
- It does not test that a mitigation actually reduces residual risk. The
  acceptance is a self-attestation by the person named with `--by` (`accepted_by`).

**Validation gate(s).** **G3** (FAIL), **G8** (WARN).

---

### Article 9(3)

> *"The risks referred to in this Article shall concern only those which may be
> reasonably mitigated or eliminated through the development or design of the
> high-risk AI system, or the provision of adequate technical information."*

**Plain English.** The risks Article 9 deals with are only those that can
reasonably be mitigated or eliminated through how the system is developed or
designed, or through adequate technical information.

**What RiskForge does.** Nothing specific. The register records every risk the
assessor enters; it does not sort risks by whether development, design or
technical information can address them.

**What RiskForge does NOT do.** It does not decide which risks fall within
Article 9(3). That judgement remains with the assessor.

**Validation gate(s).** None.

---

### Article 9(4)

> *"The risk management measures referred to in paragraph 2, point (d), shall
> give due consideration to the effects and possible interaction resulting from
> the combined application of the requirements set out in this Section, with a
> view to minimising risks more effectively while achieving an appropriate
> balance in implementing the measures to fulfil those requirements."*

**Plain English.** Don't optimise one Article (e.g. accuracy under Art. 15) in
a way that breaks another (e.g. transparency under Art. 13).

**What RiskForge does.** The single risk register surfaces interactions
implicitly, e.g. a privacy mitigation that reduces logging will conflict with
a transparency mitigation that requires logging, and the assessor will see
both rows in the same register. This is conventional, not algorithmic.

**What RiskForge does NOT do.** No automated cross-control conflict
detection. No weighted multi-objective optimiser. The conflict-finding remains
human.

**Validation gate(s).** None directly. G3 + G8 indirectly catch obvious
self-cancelling mitigations.

---

### Article 9(5), first subparagraph

> *"The risk management measures referred to in paragraph 2, point (d), shall
> be such that the relevant residual risk associated with each hazard, as well
> as the overall residual risk of the high-risk AI systems is judged to be
> acceptable."*

**Plain English.** After mitigation, the residual risk of each hazard, and the
overall residual risk of the system, must be judged acceptable.

**What RiskForge does.**

- Risk items carry `accepted`, `acceptance_rationale` and `accepted_by` fields,
  and the `risk.accepted` audit entry records who accepted the risk and when.
  The name is self-declared (`--by`), not verified.
- The export lists every item's residual score, and the PDF's residual risk
  summary orders them from highest to lowest. RiskForge does not compute a
  system-level aggregate.

**What RiskForge does NOT do.**

- It does not adjudicate whether a residual-risk acceptance is *reasonable*.
  That judgement is the assessor's; RiskForge only records and exposes it.
- It does not enforce a quantitative system-level acceptance threshold. It
  deliberately has no "below 12 is acceptable" rule; the register's risk
  appetite threshold (9 by default) only decides which items gate G3 checks.

**Validation gate(s).** **G3** (residual score above threshold must be reduced or
accepted), **G6** (assessor name and role on the register), **G7** (warns when
every inherent score is 4 or below).

---

### Article 9(5), second subparagraph

> *"In identifying the most appropriate risk management measures, the
> following shall be ensured: (a) elimination or reduction of risks identified
> and evaluated pursuant to paragraph 2 in as far as technically feasible
> through adequate design and development of the high-risk AI system; (b)
> where appropriate, implementation of adequate mitigation and control
> measures addressing risks that cannot be eliminated; (c) provision of
> information required pursuant to Article 13 and, where appropriate,
> training to deployers."*

**Plain English.** In choosing measures: eliminate or reduce risks as far as
technically feasible through design and development; where appropriate, add
mitigation and control measures for risks that cannot be eliminated; and give
deployers the information Article 13 requires and, where appropriate, training.

**What RiskForge does.** Each mitigation records a control type (preventive,
detective or corrective) and a status; RiskForge does not record whether a
measure is a design change, a control or information, and the hierarchy is not
enforced. Transparency
questions TR-001 through TR-004 cover the deployer-information surface: the
Article 13 information that Article 9(5)(c) refers to.

**What RiskForge does NOT do.** It does not refuse a register where every
mitigation is "deployer training", even though that would arguably violate
Article 9(5)(a) by skipping the design step.

**Roadmap.** A future gate could check the design-vs-mitigate-vs-inform ratio
and warn on imbalance. Not currently shipped.

**Validation gate(s).** None directly.

---

### Article 9(6)

> *"High-risk AI systems shall be tested for the purpose of identifying the
> most appropriate and targeted risk management measures. Testing shall ensure
> that high-risk AI systems perform consistently for their intended purpose
> and that they are in compliance with the requirements set out in this
> Section."*

**Plain English.** High-risk systems must be tested, both to find the most
appropriate and targeted risk management measures and to ensure the system
performs consistently for its intended purpose and meets the Section 2
requirements.

**What RiskForge does.**

- `riskforge tests generate` derives Article 9(6) to 9(8) test requirements
  and saves them on the register as an audited change; the export carries
  the saved requirements. It derives them from knowledge-gap risks and from
  risks whose inherent score is 9 or more, one requirement per item.
- Robustness questions RO-001 through RO-005 force the assessor to record
  which tests have been run: out-of-distribution testing, slice-level metrics,
  performance floors, drift response procedures, adversarial robustness
  (prompt injection, model inversion, membership inference). Note RO-005's
  `regulatory_status: pending_implementing_act`: this status is under review,
  because Article 15 provides for no implementing act (Article 15(2) has the
  Commission encourage benchmarks and measurement methodologies).
- The relevant health/safety questions (HS-002, HS-004, HS-005) also force a
  test-existence answer.
- Output references can attach to external test artefacts (e.g. a
  `rag-benchmarking` report URL).

**What RiskForge does NOT do.**

- It does not execute tests. This is a documentation scaffold, not a test
  runner. The runner-of-tests question (does the AI system actually pass) is
  answered by tools like `rag-benchmarking` (RAG eval), `litmusai` (portfolio
  screening / fairness), or the provider's own test suite. RiskForge records
  the test plan and the result claim; the underlying execution is out of scope.
- It does not validate that an attached test artefact actually demonstrates
  what the assessor claims it demonstrates.
- The RMF contains the test plan and the assessor's judgements, not raw test
  telemetry.

**Roadmap.** Tighter integration with `rag-benchmarking` and `litmusai` so
that test artefacts attach automatically to the matching risk item is a future
target.

**Validation gate(s).** **G4** (every knowledge-gap risk must have a saved test
requirement from `riskforge tests generate`, WARN).

---

### Article 9(7)

> *"Testing procedures may include testing in real-world conditions in
> accordance with Article 60."*

**Plain English.** Testing may include testing in real-world conditions under
Article 60, which sets its own conditions (Article 60(4)) for such testing outside
AI regulatory sandboxes. Article 9(7) does not require it. Since Regulation (EU)
2026/1744, Article 60 covers systems listed in Annex III or covered by the
legislation in Annex I, Section A, and a new Article 60a lets Member States allow real-world testing
outside sandboxes for AI-enabled products covered by the legislation in Annex I,
Section B. Article 60a testing is not Article 9(7) testing: Article 9 does not
apply to high-risk systems related to Annex I, Section B products (Article 2(2)).

**What RiskForge does.** Out of scope. RiskForge does not orchestrate Art. 60
real-world testing or its supervisory notifications. The mitigation-and-testing
tracking captures *that* testing was done; the Art. 60 mechanics live elsewhere.

**What RiskForge does NOT do.** It does not interface with member-state
market-surveillance authorities under Art. 60(4). It does not maintain Art. 60
test-plan registers.

**Validation gate(s).** None directly.

---

### Article 9(8)

> *"The testing of high-risk AI systems shall be performed, as appropriate, at
> any time throughout the development process, and, in any event, prior to
> their being placed on the market or put into service. Testing shall be
> carried out against prior defined metrics and probabilistic thresholds that
> are appropriate to the intended purpose of the high-risk AI system."*

**Plain English.** Define metrics and thresholds *before* testing, and test
before going live. No ex-post threshold-fitting.

**What RiskForge does.** Question RO-003 forces an answer on whether a
performance floor (a *prior-defined* threshold) exists below which the system
is taken offline. RO-002 forces slice-level metric documentation. Each test
requirement from `riskforge tests generate` names a metric type and a target
threshold: the "prior defined metrics and probabilistic thresholds" of
Article 9(8).

**What RiskForge does NOT do.** It does not enforce that the metrics were
defined *before* the test: there is no time-stamping of metric definition vs
test execution. The audit chain timestamps the *recording* of the answer in
RiskForge, not the underlying engineering activity.

**Validation gate(s).** **G4** indirect.

---

### Article 9(9)

> *"When implementing the risk management system as provided for in
> paragraphs 1 to 7, providers shall give consideration to whether in view of
> its intended purpose the high-risk AI system is likely to have an adverse
> impact on persons under the age of 18 and, as appropriate, other vulnerable
> groups."*

**Plain English.** Providers must consider whether, given its intended purpose,
the system is likely to have an adverse impact on people under 18 and, as
appropriate, other vulnerable groups.

**What RiskForge does.** Question **HS-006** *("Could vulnerable populations
(elderly, children, people with disabilities) be disproportionately harmed by
system errors?")* is the question that addresses this paragraph. Its
`article_refs` field cites Art. 9(9), which matches the Official Journal text
(checked 2026-10-17).

**What RiskForge does NOT do.** It does not maintain a separate
vulnerable-group register. The single hazard question is the only forced
touchpoint.

**Validation gate(s).** **G1** (requires an item in the health_safety dimension;
it does not require HS-006 to be answered).

---

### Article 9(10)

> *"For providers of high-risk AI systems that are subject to requirements
> regarding internal risk management processes under other relevant provisions
> of Union law, the aspects provided in paragraphs 1 to 9 may be part of, or
> combined with, the risk management procedures established pursuant to that
> law."*

**Plain English.** If you already comply with another EU regime that requires
a risk management process (medical devices MDR, machinery, etc.), you can
fold AI Act risk management into it.

**What RiskForge does.** The exported RMF is a standalone document; nothing
prevents inclusion in a broader regulated-product technical file.

**What RiskForge does NOT do.** No format adapter for MDR / Machinery
Regulation / RED technical files. Roadmap; not current.

**Validation gate(s).** None.

---

## 3. Annex IV documentation pack

Article 9 is one obligation. **Annex IV** lists the technical documentation
that Article 11(1) requires, the pack a provider hands to a notified body or
competent authority on request.

**The relationship.** A RiskForge RMF is built to be the detailed description of
the risk management system that Annex IV point 5 asks for ("A detailed
description of the risk management system in accordance with Article 9"). How
complete it is depends on what the provider records: it does not describe your
review cadence or the post-market feedback of Article 9(2)(c). It does **not**
constitute the full Annex IV pack. The table below names every
Annex IV point and where RiskForge output sits.

| Annex IV section | Subject | RiskForge coverage | Where the rest comes from |
| --- | --- | --- | --- |
| IV(1) | General description of the system | Partial: `system.yaml` (name, version, purpose, provider) | Architecture diagrams, deployment topology: out of scope |
| IV(2)(a) | Methods and steps performed for development | None | Engineering process docs, source control history |
| IV(2)(b) | Design specifications | None | Design docs |
| IV(2)(c) | System architecture, computational resources | None | Architecture diagrams, infrastructure inventory |
| IV(2)(d) | Data requirements (datasheets, provenance) | Partial: DG-001 to DG-005 capture the *attestation*, not the data itself | Datasheets for the training data |
| IV(2)(e) | Human oversight assessment | Partial: HO-001 to HO-004 and FR-004 record the assessment | Oversight design and procedures |
| IV(2)(f) | Pre-determined changes & continuous learning | None | Change-management policy |
| IV(2)(g) | Validation and testing procedures used | Partial: saved test requirements (metric and threshold per risk); not the test runs or the signed reports | Test reports, for example from rag-benchmarking or litmusai |
| IV(2)(h) | Cybersecurity measures put in place | None | Security design docs |
| IV(3) | Detailed information about monitoring, functioning, control | Partial via transparency Qs (TR-001 to TR-004) | Operations runbooks |
| IV(4) | Appropriateness of the performance metrics | Partial via RO-002, RO-003 | Test reports |
| IV(5) | **Risk management system in accordance with Article 9** | **Primary: the RMF is built for this point; add your review cadence and post-market feedback process** | n/a |
| IV(6) | Relevant changes made by the provider to the system through its lifecycle | Partial: the audit chain (`audit.jsonl`) records changes to the RMF itself, not to the AI system | Engineering change log |
| IV(7) | Harmonised standards applied | None | Conformity-assessment evidence |
| IV(8) | Copy of the EU declaration of conformity (Article 47) | None | Legal artefact, post-CA |
| IV(9) | Post-market monitoring plan (Article 72(3)) | None | Your post-market monitoring plan; a Sigil module is planned for this, not released |

Read this table the same way you'd read a coverage report: a filled cell means
RiskForge produces evidence that lands in that section. "None" means
**you need a different tool or a different document**. RiskForge does not
attempt to be a unified Annex IV authoring system.

---

## 4. What RiskForge is NOT

This section is mandatory reading before anyone in your organisation uses the
output as a compliance claim.

1. **Not a substitute for notified-body conformity assessment.** Where Article
   43 requires the Annex VII procedure, which involves a notified body (for
   example, for some systems under Annex III point 1), RiskForge does not
   replace any step of that process. The RMF is one input to a CA; not the
   CA itself.
2. **Not legal advice.** Question guidance text is informational. The text
   was drafted by AI governance practitioners, not by qualified counsel, and
   does not establish a lawyer-client relationship.
3. **Not an Article 9 lifecycle replacement.** Article 9(1) requires
   *continuous* risk management. RiskForge handles **initiation** and
   **documentation scaffolding**. The provider must operate the cadence:
   review schedule, owner notifications, evidence refresh. RiskForge will not
   tell you that your assessment from 18 months ago is stale.
4. **Not Article 9(2)(c) post-market monitoring loopback.** Out of scope. It is
   planned as a module of Sigil, which has not been released.
5. **Not Article 9(6) to (8) testing.** Test execution (running the
   tests, collecting telemetry, computing slice-level metrics) is not
   RiskForge's job. Use `rag-benchmarking`, `litmusai`, or your own test
   suite; RiskForge records the test plan and the claim.
6. **Not a fairness oracle.** Discrimination questions (DI-001 to DI-004)
   force a documented answer; they do not compute the fairness metrics for
   you. `litmusai` does that.
7. **Not a regulator.** The output of `riskforge validate` is "your gates
   passed", not "your system is compliant." Compliance is determined by the
   competent authority, not by the tool.
8. **Not a substitute for an Article 27 Fundamental Rights Impact
   Assessment** for deployers in scope of that obligation. FR-001 captures
   *whether* a FRIA was conducted; RiskForge does not produce the FRIA
   document.

---

## 5. Cross-framework crosswalk

Each question in the bank carries `nist_rmf_ref` and `iso42001_ref` fields.
The crosswalk below summarises the mapping at the *dimension* level, plus
US-state-law touchpoints. For per-question references, read the YAML directly.

### EU AI Act Article 9 ↔ NIST AI RMF 1.0 (January 2023)

| RiskForge dimension | NIST AI RMF function | Representative subcategory |
| --- | --- | --- |
| data_governance | MAP / MEASURE | MAP 2.3, MAP 4.1, MEASURE 2.10 |
| discrimination | MEASURE | MEASURE 2.11 |
| fundamental_rights | GOVERN / MAP | GOVERN 1.1, MAP 5.1 |
| health_safety | MAP / MEASURE | MAP 3.5, MAP 5.1, MEASURE 2.4, MEASURE 2.6 |
| human_oversight | MANAGE / MAP | MANAGE 2.4, MAP 3.5 |
| privacy | MEASURE | MEASURE 2.10 |
| robustness | MEASURE / MANAGE | MEASURE 2.5, MANAGE 1.3 |
| transparency | MEASURE | MEASURE 2.8, MEASURE 2.9 |

Source: NIST AI Risk Management Framework 1.0, NIST AI 100-1
(<https://nvlpubs.nist.gov/nistpubs/ai/NIST.AI.100-1.pdf>). Functions cited:
GOVERN, MAP, MEASURE, MANAGE.

### EU AI Act Article 9 ↔ ISO/IEC 42001:2023 (AI management system)

| ISO/IEC 42001 reference | Subject | RiskForge mapping |
| --- | --- | --- |
| Clause 6.1 | Actions to address risks and opportunities | Direct: fundamental_rights, health_safety items |
| Clause 9.1 | Performance evaluation, monitoring | RO-003, RO-004, DI-004, HS-005 |
| Annex A.6 | AI system life cycle | transparency questions (fit to be confirmed against the Annex A control text) |
| Annex A.7 | Data for AI systems | discrimination + data_governance + privacy |
| Annex A.9 | Use of AI systems | human_oversight + privacy + robustness |

Source: ISO/IEC 42001:2023 *Information technology - Artificial intelligence
- Management system*. Clause numbers per the published standard.

### US state-law touchpoints

These are not equivalents; they are overlapping obligations whose evidence
needs are similar.

| Statute | Relevant content | RiskForge dimension(s) |
| --- | --- | --- |
| Colorado AI Act (SB 24-205, repealed and reenacted by SB 26-189, signed 14 May 2026; developer documentation duties start 1 January 2027) | SB 26-189 replaced SB 24-205's duties for high-risk AI systems with duties for automated decision-making technology used in consequential decisions: developer documentation for deployers, record keeping, a notice to consumers before use, a plain-language description of the decision and the technology's role within 30 days after an adverse outcome, and, on request, instructions to obtain and correct personal data and meaningful human review and reconsideration | data_governance, discrimination, fundamental_rights, transparency |
| Texas HB 149 ("TRAIGA", signed 22 June 2025, effective 1 January 2026) | Intent-based prohibitions on certain AI uses, AI-interaction disclosure duties for government agencies and health care providers, enforced by the Attorney General | discrimination, transparency, privacy |
| New York City Local Law 144 of 2021 (in force) | Bias audits for automated employment decision tools | discrimination |

Texas HB 149 and Colorado SB 26-189 were enacted after the EU AI Act; Colorado
SB 24-205 was approved shortly before it. Colorado's
original risk-management structure has since been narrowed by SB 26-189, and
neither statute is a one-for-one substitute for Article 9. Always confirm against
the current text of the statute.

Sources:

- Colorado AI Act (SB 24-205, repealed and reenacted by SB 26-189): <https://leg.colorado.gov/bills/sb24-205>, <https://leg.colorado.gov/bills/sb26-189>
- Texas HB 149 (TRAIGA): <https://capitol.texas.gov/BillLookup/History.aspx?LegSess=89R&Bill=HB149>
- NYC Local Law 144 of 2021: <https://www.nyc.gov/site/dca/about/automated-employment-decision-tools.page>

If your organisation operates in additional US states, contribute the
mapping back to `docs/contributing/add-jurisdiction.md` (planned).

---

## Verification & feedback

If you find a regulatory mis-citation in this document, file an issue at
<https://github.com/aiexponent/riskforge/issues> with the EUR-Lex paragraph
reference and the proposed correction. Authenticity is non-negotiable; we
would rather correct than be quietly wrong.

Last verified against the Official Journal text of Regulation (EU) 2024/1689
(CELEX:32024R1689) and Regulation (EU) 2026/1744 (CELEX:32026R1744) on
**2026-10-17**.
