# Article 9 Mapping

> Reference documentation for practitioners. Reads paragraph-by-paragraph against
> Regulation (EU) 2024/1689 (the "EU AI Act") and shows what RiskForge addresses,
> what it does not, and which validation gate enforces each control.
>
> Primary source for every regulatory quote in this file: EUR-Lex CELEX:32024R1689,
> retrieved 2026-05-10. URL: <https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32024R1689>.

## Audience

You are a compliance lead, in-house counsel, or AI governance engineer who has
read Articles 9 through 15 of the EU AI Act and Annex IV. You want to know,
control by control, where RiskForge fits in your evidence pack and where it does
not. This document is reference material, not marketing. If a control is not
implemented, the section will say so plainly and point at the planned milestone.

---

## 1. Article 9 overview

Article 9 (Risk management system) is the cornerstone obligation for providers of
high-risk AI systems under Chapter III, Section 2 of the EU AI Act. It requires:

- a documented, **lifecycle-long** risk management system, not a one-off
  assessment;
- identification of known and reasonably foreseeable risks to **health, safety
  and fundamental rights**;
- estimation and evaluation of those risks under the system's intended purpose
  and under reasonably foreseeable misuse;
- targeted **mitigation measures** with residual-risk acceptance;
- testing evidence sufficient to demonstrate that mitigations actually work;
- explicit consideration of impacts on **children and other vulnerable groups**.

### When it applies

Article 9 obligations for high-risk AI systems apply from **2 December 2027** for
standalone Annex III systems and **2 August 2028** for high-risk AI embedded in
products under Annex I. The original Article 113 date was 2 August 2026; the
Digital Omnibus deferred it. That package was endorsed by the European Parliament
on 16 June 2026 and by the Council on 29 June 2026 and is pending publication in
the Official Journal, entering into force on the third day after publication.
Until it publishes, the original 2 August 2026 date remains technically in force,
so re-verify the status when the date matters.

For the avoidance of doubt:

- Articles 5 (prohibited practices) and 4 (AI literacy) became enforceable on
  2 February 2025, earlier than Article 9.
- The Article 6+ high-risk obligations that Article 9 belongs to apply from
  2 December 2027 (Annex III) or 2 August 2028 (Annex I) under the Digital Omnibus.
- Some general-purpose AI model obligations have a different timeline and are not
  in scope for this document.

### Penalty band

Non-compliance with Article 9 routes through the Article 16 provider obligations
and is sanctionable under Article 99(4):

> *"Non-compliance with any of the following provisions related to operators or
> notified bodies, other than those laid down in Article 5, shall be subject to
> administrative fines of up to EUR 15 000 000 or, if the offender is an
> undertaking, up to 3 % of its total worldwide annual turnover for the
> preceding financial year, **whichever is higher**: …"*
> — Article 99(4), EU AI Act (verbatim per EUR-Lex 2026-05-10)

The "whichever is higher" wording is verified verbatim against the consolidated
text. Earlier secondary summaries that read "whichever is lower" or omit the
clause are wrong; consult the primary source.

---

## 2. Paragraph-by-paragraph mapping

The following sections walk Article 9(1) through Article 9(10). For each
paragraph:

1. The verbatim text from EUR-Lex CELEX:32024R1689.
2. A plain-English summary.
3. **What RiskForge does** to address the paragraph — with file paths and
   question IDs from the question bank at
   `src/riskforge/_data/question_bank/`.
4. **What RiskForge does NOT do** — the named gap. Where applicable, this
   cites the `paragraph_refs_omitted` block in the website tool record at
   `aiexponent-web/lib/tools.ts:333-342`.
5. **Validation gate(s)** — which of the eight readiness gates in
   `src/riskforge/engine/validate.py` enforce the paragraph before export.

The eight gates (`G1`–`G8`) are documented inline so the cross-references make
sense without flipping files:

| Gate | Purpose | Severity |
| --- | --- | --- |
| G1 | All 8 risk dimensions have entries (or marked not-applicable with justification) | FAIL |
| G2 | Article 6(2) self-classification documented | FAIL |
| G3 | All high-scoring risks mitigated or accepted | FAIL |
| G4 | Knowledge gaps have test requirements | WARN |
| G5 | System metadata complete (name, version, purpose, provider) | FAIL |
| G6 | Assessor identity recorded | FAIL |
| G7 | Risk score distribution plausible (catches all-low-score whitewash) | WARN |
| G8 | No vague mitigations | WARN |

A `FAIL` gate blocks export unless `--force` is passed. A `WARN` gate is surfaced
in the export but does not block. All eight gates are run on every export — see
`ValidateEngine.run` at `src/riskforge/engine/validate.py:36-46`.

---

### Article 9(1)

> *"A risk management system shall be established, implemented, documented and
> maintained in relation to high-risk AI systems."*

**Plain English.** A provider of a high-risk system needs a *system* — a
recurring process — to manage risk. Not a checklist, not a one-page memo. It has
to be set up, run, written down, and kept up to date.

**What RiskForge does.**

- Initialises a versioned project on disk: `riskforge init` writes a
  `riskforge.yaml` manifest plus a `.riskforge/` working tree containing
  the system record, the risk register, the audit chain, and exports
  (`src/riskforge/storage/filesystem.py:1-50`).
- Captures the assessment as data (`register.yaml`, `mitigations.yaml`) so it
  is diffable and reviewable in git rather than living inside a Word document
  no one re-opens.
- Stamps every state mutation into an append-only audit log
  (`audit.jsonl`) for reproducibility — see `docs/audit-chain-design.md`.
- Produces a **Risk Management File (RMF)** as JSON, Markdown, and PDF via
  `riskforge export`. The RMF is the "documented" artefact Article 9(1)
  refers to.

**What RiskForge does NOT do.**

- It does not enforce a maintenance cadence. Article 9(1) requires the system
  to be *maintained*; RiskForge does not currently emit reminders, schedule
  reviews, or notify owners when an assessment is stale. Operationalising
  cadence is the deployer's responsibility — typically by attaching the
  `.riskforge/` tree to a calendar/ticketing process.
- It does not federate across multiple high-risk systems within an
  organisation (no cross-system rollup view in v0.1.x).

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
across three categories — health, safety, fundamental rights — for the system
operating as intended.

**What RiskForge does.**

The 37-question bank is structured to force a sweep across all three categories:

- **Health & safety**, file `src/riskforge/_data/question_bank/health_safety.yaml`
  — 6 questions: HS-001 (clinical/safety/physical decisions without mandatory
  human review), HS-002 (physical harm from failure), HS-003 (emergency
  override), HS-004 (FMEA / failure-mode analysis), HS-005 (production
  monitoring), HS-006 (vulnerable populations). HS-006 is the explicit
  Article 9(9) hook on children and vulnerable groups.
- **Fundamental rights**, file
  `src/riskforge/_data/question_bank/fundamental_rights.yaml` — 4 questions:
  FR-001 (FRIA conducted), FR-002 (Charter rights affected), FR-003 (subjects
  informed), FR-004 (human review for fundamental-rights-significant
  decisions).
- **Discrimination**, file
  `src/riskforge/_data/question_bank/discrimination.yaml` — 4 questions
  (DI-001 through DI-004): representation imbalance, fairness metrics, proxy
  discrimination, drift-aware bias monitoring. Maps to Art. 9(2)(a) and
  Art. 10(2)(f).
- **Privacy**, file `src/riskforge/_data/question_bank/privacy.yaml` —
  PR-001 through PR-005, anchoring the GDPR overlay (special category data,
  DPIA, minimisation, training-data PII screening, output-side membership
  inference).

Hazard identification is not optional: gate **G1** fails the export if any of
the 8 dimensions is left empty *and* not explicitly marked not-applicable with
a justification.

**What RiskForge does NOT do.**

- It does not generate hazards from a corpus of past incidents — there is no
  built-in incident database. The question bank is a structured prompt, not an
  oracle.
- It does not perform automated hazard discovery from system artefacts (model
  cards, telemetry, etc.). That belongs to TraceForge (in development).
- It does not adjudicate whether an identified risk is "reasonably
  foreseeable" — that judgement remains with the assessor.

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
  in its YAML record (e.g. HS-002: likelihood 2, severity 5 — low-frequency,
  catastrophic-impact). Hints are starting points, not verdicts; the assessor
  must score the system in front of them.
- Annex III scenario tagging: each question carries
  `annex_iii_categories` (employment, education, law_enforcement,
  essential_services, biometric, justice, migration, health,
  critical_infrastructure). The assess engine surfaces questions relevant to
  the deployment context.

**What RiskForge does NOT do.**

- It does **not** include a built-in misuse-pattern library. Per the v0.1.4
  documentation correction (CHANGELOG line 17-21), the "20 pre-built risk
  patterns" claim was an aspirational PRD target. Shipped reality is **6
  patterns** covering credit scoring, hiring, facial recognition, medical
  imaging, content moderation, and criminal risk assessment. Future patterns
  arrive via community contribution per `docs/contributing/add-pattern.md`.
- It does not run automated stress tests against the system; the deployer must
  provide the misuse-scenario reasoning.

**Validation gate(s).** **G3** (high-scoring risks must be mitigated or
explicitly accepted), **G7** (catches the "everything scored low" pattern that
neuters Article 9(2)(b)).

---

### Article 9(2)(c)

> *"(c) the evaluation of other risks possibly arising, based on the analysis
> of data gathered from the post-market monitoring system referred to in
> Article 72;"*

**Plain English.** Risk management is not just pre-deployment; the post-market
monitoring system has to feed back into the risk management system.

**What RiskForge does.** **Nothing directly.** This paragraph is named in the
website's `paragraph_refs_omitted` block at
`aiexponent-web/lib/tools.ts:333-342` with the rationale:

> *"Post-market monitoring evaluation per Article 72 — out of scope for
> RiskForge; addressed by TraceForge (in development)."*

RiskForge addresses the **pre-deployment** half of the lifecycle. Several
questions reference Article 72 (HS-005, DI-004, RO-003, RO-004) but they document
the *requirement* that monitoring exist; they do not ingest monitoring telemetry.

**What RiskForge does NOT do.**

- No connector to deployed-system telemetry.
- No incident-loop mechanism to re-open a previously-closed risk item when
  post-market evidence contradicts it.
- No serious-incident reporting workflow under Article 73.

**Roadmap.** Post-market monitoring loopback is planned for v1.x via the
TraceForge integration adapter referenced in
`src/riskforge/adapters/` and the v0.1.0 release notes
(CHANGELOG line 119: *"Integration adapters for rag-benchmarking and
TraceForge"*). The current adapter is a stub; the data pipe is unverified.

**Validation gate(s).** No gate currently enforces 9(2)(c) — by design,
because the data does not exist in scope. Adding a gate would create false
assurance.

---

### Article 9(2)(d)

> *"(d) the adoption of appropriate and targeted risk management measures
> designed to address the risks identified pursuant to point (a)."*

**Plain English.** For each risk you identified in (a), pick a specific
mitigation. Not "we'll do our best" — a targeted control.

**What RiskForge does.**

- Each risk item in the register can carry one or more `Mitigation` entries —
  see the model in `src/riskforge/models/risk.py`. Mitigations are flat-listed
  in `mitigations.yaml` for readability with a back-link to the parent risk.
- Gate **G8** flags vague mitigations (e.g. "improve training", "have policy")
  via an `is_vague` heuristic on the mitigation model. WARN, not FAIL — but
  surfaced in the export.
- Gate **G3** fails the export if a high-scoring risk is left without an
  accepted mitigation status. The provider must either mitigate, accept (with
  a residual-risk justification), or downgrade the score.

**What RiskForge does NOT do.**

- It does not propose mitigations from a control library. The assessor must
  draft the control text. A future v1.x feature could surface NIST
  AI RMF MANAGE controls or ISO/IEC 42001 Annex A controls as starting points;
  this is roadmap, not current.
- It does not test that a mitigation actually reduces residual risk. The
  acceptance is a self-attestation by the assessor (whose identity G6 records).

**Validation gate(s).** **G3** (FAIL), **G8** (WARN).

---

### Article 9(2)(e), (f), (g), (h)

These four sub-paragraphs cover the iterative testing-and-mitigation cycle —
testing procedures, performance metrics, residual-risk re-evaluation,
information to the deployer.

**Plain English.** Pick metrics, define thresholds, test, document, and tell
the deployer what they need to know to use the system safely.

**What RiskForge does.**

- The `riskforge tests generate` subcommand derives test requirements from
  knowledge-gap risks (any risk item flagged as "evidence not yet collected").
- Robustness questions RO-001 through RO-005 force the assessor to record
  which tests have been run: out-of-distribution testing, slice-level metrics,
  performance floors, drift response procedures, adversarial robustness
  (prompt injection, model inversion, membership inference). Note RO-005's
  `regulatory_status: pending_implementing_act` — this question rides on
  forthcoming Article 15 implementing acts and is flagged in the YAML so it
  can be re-graded when the act lands.
- Transparency questions TR-001 through TR-004 cover the deployer-information
  surface (Art. 13 obligations).

**What RiskForge does NOT do.**

- It does **not** run the tests. The runner-of-tests question — does the AI
  system actually pass — is answered by tools like `rag-benchmarking`
  (RAG eval), `litmusai` (portfolio screening / fairness), or a deployer's
  own test harness. RiskForge records the test plan and the result claim;
  the underlying execution is out of scope.
- These four sub-paragraphs are explicitly named in the website's
  `paragraph_refs_omitted` block as covered "structurally by the Risk
  Management File output rather than verbatim quoted" — meaning the RMF
  contains the pointers and judgements, not the raw test telemetry.

**Roadmap.** Tighter integration with `rag-benchmarking` and `litmusai` so
that test artefacts attach automatically to the matching risk item is a v1.x
target.

**Validation gate(s).** **G4** (knowledge gaps have test requirements — WARN).

---

### Article 9(3)

> *"The risk management measures referred to in this Article shall give due
> consideration to the effects and possible interaction resulting from the
> combined application of the requirements set out in this Section 2."*

**Plain English.** Don't optimise one Article (e.g. accuracy under Art. 15) in
a way that breaks another (e.g. transparency under Art. 13).

**What RiskForge does.** The single risk register surfaces interactions
implicitly — e.g. a privacy mitigation that reduces logging will conflict with
a transparency mitigation that requires logging, and the assessor will see
both rows in the same register. This is conventional, not algorithmic.

**What RiskForge does NOT do.** No automated cross-control conflict
detection. No weighted multi-objective optimiser. The conflict-finding remains
human.

**Validation gate(s).** None directly. G3 + G8 indirectly catch obvious
self-cancelling mitigations.

---

### Article 9(4)

> *"The risk management measures referred to in paragraph 2, point (d), shall
> be such that the relevant residual risk associated with each hazard, as well
> as the overall residual risk of the high-risk AI systems is judged to be
> acceptable."*

**Plain English.** After mitigations, residual risk has to be defensible — for
each hazard *and* for the system as a whole.

**What RiskForge does.**

- Risk items carry an explicit `accepted_at` / acceptance-rationale field on
  the risk model. The acceptance is attributed to the recorded assessor (G6).
- The export contains both per-risk residual scores and a system-level
  rollup (max / weighted aggregate, depending on register configuration).

**What RiskForge does NOT do.**

- It does not adjudicate whether a residual-risk acceptance is *reasonable*.
  That judgement is the assessor's; RiskForge only records and exposes it.
- It does not enforce a quantitative system-level acceptance threshold. The
  PRD intentionally avoids hard-coding a "below 12 is acceptable" rule — the
  threshold is context-dependent and disputed.

**Validation gate(s).** **G3** (acceptance status required), **G6**
(assessor attached to the acceptance), **G7** (catches the all-acceptable
pattern that hides a whitewash).

---

### Article 9(5)

> *"In identifying the most appropriate risk management measures, the
> following shall be ensured: (a) elimination or reduction of risks identified
> and evaluated pursuant to paragraph 2 in as far as technically feasible
> through adequate design and development of the high-risk AI system; (b)
> where appropriate, implementation of adequate mitigation and control
> measures addressing risks that cannot be eliminated; (c) provision of
> information required pursuant to Article 13 and, where appropriate,
> training to deployers."*

**Plain English.** Hierarchy of controls: design-out first, mitigate second,
inform/train the deployer third.

**What RiskForge does.** The risk model accepts mitigations of either type
and the export distinguishes them, but the *hierarchy of controls* itself is
not enforced as a gate — the assessor records what they did. Transparency
questions TR-001 through TR-004 cover Article 13 information provision.

**What RiskForge does NOT do.** It does not refuse a register where every
mitigation is "deployer training" — even though that would arguably violate
Article 9(5)(a) by skipping the design step.

**Roadmap.** A v1.x gate could check the design-vs-mitigate-vs-inform ratio
and warn on imbalance. Not currently shipped.

**Validation gate(s).** None directly.

---

### Article 9(6)

> *"High-risk AI systems shall be tested for the purpose of identifying the
> most appropriate and targeted risk management measures. Testing shall ensure
> that high-risk AI systems perform consistently for their intended purpose
> and that they are in compliance with the requirements set out in this
> Section."*

**Plain English.** You must test. Testing is not optional and is not
"whatever the data scientist had time for last Friday."

**What RiskForge does.**

- `riskforge tests generate` derives test requirements from risk items.
- Robustness dimension (RO-001 to RO-005) and the relevant health/safety
  questions (HS-002, HS-004, HS-005) force a test-existence answer.
- Output references can attach to external test artefacts (e.g. a
  `rag-benchmarking` report URL).

**What RiskForge does NOT do.**

- It does not execute tests. Repeating the point: this is a documentation
  scaffold, not a test runner.
- It does not validate that an attached test artefact actually demonstrates
  what the assessor claims it demonstrates.

**Validation gate(s).** **G4** (knowledge gaps must have tests — WARN).

---

### Article 9(7)

> *"Testing procedures may include testing in real-world conditions in
> accordance with Article 60."*

**Plain English.** You may run real-world (sandboxed) testing under Art. 60,
which carries its own conformity safeguards. You don't have to — synthetic
and lab testing are still acceptable — but if you do, the Art. 60 regime
applies.

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
is taken offline. RO-002 forces slice-level metric documentation.

**What RiskForge does NOT do.** It does not enforce that the metrics were
defined *before* the test — there is no time-stamping of metric definition vs
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

**Plain English.** Children and vulnerable groups get explicit consideration.
Not implicit, not assumed-covered-by-the-fairness-section. Explicit.

**What RiskForge does.** Question **HS-006** *("Could vulnerable populations
(elderly, children, people with disabilities) be disproportionately harmed by
system errors?")* exists exclusively to satisfy this paragraph. Its
`article_refs` field cites Art. 9(9), which matches the consolidated EUR-Lex
text (verified 2026-05-10).

**What RiskForge does NOT do.** It does not maintain a separate
vulnerable-group register. The single hazard question is the only forced
touchpoint.

**Validation gate(s).** **G1** (forces health_safety dimension to be answered,
which surfaces HS-006).

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

Article 9 is one obligation. **Annex IV** (technical documentation) is a
broader requirement under Article 11 — the documentation pack a provider must
hand to a notified body or competent authority on request.

**The relationship.** A RiskForge RMF satisfies the Annex IV(2)(g) sub-section
on the risk management system, plus parts of (2)(c) and (2)(h). It does **not**
constitute the full Annex IV pack. The table below names every Annex IV(1)–(8)
section and where RiskForge output sits.

| Annex IV section | Subject | RiskForge coverage | Where the rest comes from |
| --- | --- | --- | --- |
| IV(1) | General description of the system | Partial — `system.yaml` (name, version, purpose, provider) | Architecture diagrams, deployment topology — out of scope |
| IV(2)(a) | Methods and steps performed for development | None | Engineering process docs, source control history |
| IV(2)(b) | Design specifications | None | Design docs |
| IV(2)(c) | System architecture, computational resources | Partial — surfaced through robustness Qs (RO-001/003) | Architecture diagrams, infrastructure inventory |
| IV(2)(d) | Data requirements (datasheets, provenance) | Partial — DG-001 to DG-005 capture the *attestation*, not the data itself | Datasheet-for-datasets; TraceForge planned |
| IV(2)(e) | Human oversight assessment | Yes — HO-001 to HO-004, FR-004 | — |
| IV(2)(f) | Pre-determined changes & continuous learning | None | Change-management policy |
| IV(2)(g) | **Risk management system per Article 9** | **Yes — this is the primary RMF artefact** | — |
| IV(2)(h) | Lifecycle changes log | Partial — audit chain (`audit.jsonl`) records changes to the RMF itself, not to the AI system | Engineering change log |
| IV(2)(i) | Standards applied | Partial — IDs cite NIST RMF + ISO/IEC 42001 references | Conformity-assessment evidence |
| IV(2)(j) | EU declaration of conformity | None | Legal artefact, post-CA |
| IV(2)(k) | Post-market monitoring plan | None | TraceForge planned |
| IV(3) | Detailed information about monitoring, functioning, control | Partial via transparency Qs (TR-001 to TR-004) | Operations runbooks |
| IV(4) | Performance metrics description | Partial via RO-002, RO-003 | Test reports |
| IV(5) | Risk management system | Yes — same as IV(2)(g) | — |
| IV(6) | Logging capabilities of the system | None | System logging design |
| IV(7) | Other relevant documentation | N/A | — |
| IV(8) | Quality management system | None | ISO/IEC 42001 / ISO 9001 QMS docs |

Read this table the same way you'd read a coverage report: a green cell means
RiskForge produces evidence that lands in that section. An empty cell means
**you need a different tool or a different document**. RiskForge does not
attempt to be a unified Annex IV authoring system.

---

## 4. What RiskForge is NOT

This section is mandatory reading before anyone in your organisation uses the
output as a compliance claim.

1. **Not a substitute for notified-body conformity assessment.** Where Article
   43 + Annex VI / Annex VII require a notified-body involvement (e.g. for
   biometric identification systems under Annex III(1)), RiskForge does not
   replace any step of that process. The RMF is one input to a CA; not the
   CA itself.
2. **Not legal advice.** Question guidance text is informational. The text
   was drafted by AI governance practitioners, not by qualified counsel, and
   does not establish a lawyer-client relationship.
3. **Not an Article 9 lifecycle replacement.** Article 9(1) requires
   *continuous* risk management. RiskForge handles **initiation** and
   **documentation scaffolding**. The deployer must operate the cadence —
   review schedule, owner notifications, evidence refresh. RiskForge will not
   tell you that your assessment from 18 months ago is stale.
4. **Not Article 9(2)(c) post-market monitoring loopback.** Out of scope; see
   the `paragraph_refs_omitted` entry at
   `aiexponent-web/lib/tools.ts:333-342`. Planned for v1.x via TraceForge
   integration.
5. **Not Article 9(2)(e)–(h) iterative testing.** Test execution (running the
   tests, collecting telemetry, computing slice-level metrics) is not
   RiskForge's job. Use `rag-benchmarking`, `litmusai`, or your own test
   harness; RiskForge records the test plan and the claim.
6. **Not a fairness oracle.** Discrimination questions (DI-001 to DI-004)
   force a documented answer; they do not compute the fairness metrics for
   you. `litmusai` does that.
7. **Not a regulator.** The output of `riskforge validate` is "your gates
   passed" — not "your system is compliant." Compliance is determined by the
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
| data_governance | GOVERN | GOVERN 1.6, 1.7 |
| discrimination | MEASURE | MEASURE 2.9 |
| fundamental_rights | GOVERN / MAP | GOVERN 1.1, MAP 1.5 |
| health_safety | MAP / MEASURE | MAP 1.5, MAP 5.1, MAP 5.2, MEASURE 2.5 |
| human_oversight | MANAGE | MANAGE 1.1 |
| privacy | GOVERN / MEASURE | GOVERN 1.6, MEASURE 2.5 |
| robustness | MEASURE / MANAGE | MEASURE 2.5, MANAGE 1.3 |
| transparency | GOVERN / MEASURE | GOVERN 1.7, MEASURE 1.1 |

Source: NIST AI Risk Management Framework 1.0
(<https://www.nist.gov/itl/ai-risk-management-framework>). Functions cited:
GOVERN, MAP, MEASURE, MANAGE.

### EU AI Act Article 9 ↔ ISO/IEC 42001:2023 (AI management system)

| ISO/IEC 42001 reference | Subject | RiskForge mapping |
| --- | --- | --- |
| Clause 6.1 | Actions to address risks and opportunities | Direct — fundamental_rights, health_safety items |
| Clause 8.4 | Communication on AI system | Surfaced via transparency dimension |
| Clause 9.1 | Performance evaluation, monitoring | RO-003, RO-004, DI-004, HS-005 |
| Annex A.6 | AI system documentation | transparency questions |
| Annex A.7 | Data for AI systems | discrimination + data_governance |
| Annex A.8 | Information for interested parties | data_governance + privacy |
| Annex A.9 | Use of AI systems | human_oversight + privacy + robustness |

Source: ISO/IEC 42001:2023 *Information technology — Artificial intelligence
— Management system*. Clause numbers per the published standard.

### US state-law touchpoints

These are not equivalents; they are overlapping obligations whose evidence
needs are similar.

| Statute | Relevant content | RiskForge dimension(s) |
| --- | --- | --- |
| Colorado AI Act (SB 24-205, repealed and reenacted by SB 26-189, effective 1 January 2027) | SB 26-189 replaced the high-risk risk-management and impact-assessment duties with a narrower automated-decision-making disclosure framework; the earlier structure still informs evidence needs | data_governance, discrimination, fundamental_rights, transparency |
| Texas HB 149 ("TRAIGA", signed 22 June 2025, effective 1 January 2026) | Intent-based prohibitions on harmful AI uses plus transparency and disclosure duties, enforced by the Attorney General | discrimination, transparency, privacy |
| New York City Local Law 144 (in force) | Bias audits for automated employment decision tools | discrimination |
| Illinois 820 ILCS 42 (AI Video Interview Act) | Notice + consent for AI-assisted interview analysis | transparency, privacy |

The Colorado and Texas statutes were enacted after the EU AI Act. Colorado's
original risk-management structure has since been narrowed by SB 26-189, and
neither statute is a one-for-one substitute for Article 9. Always confirm against
the current text of the statute.

Sources:

- Colorado AI Act (SB 24-205, reset by SB 26-189): <https://leg.colorado.gov/bills/sb24-205>
- Texas HB 149 (TRAIGA): Texas Legislature Online
- NYC LL 144: DCWP rules

If your organisation operates in additional US states, contribute the
mapping back to `docs/contributing/add-jurisdiction.md` (planned).

---

## Verification & feedback

If you find a regulatory mis-citation in this document, file an issue at
<https://github.com/aiexponent/riskforge/issues> with the EUR-Lex paragraph
reference and the proposed correction. Authenticity is non-negotiable; we
would rather correct than be quietly wrong.

Last verified against EUR-Lex CELEX:32024R1689 on **2026-05-10**.
