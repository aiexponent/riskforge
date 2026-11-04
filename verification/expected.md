# What an Article 9 risk management file should contain

Written by the tester before RiskForge was installed, from the text of Article 9 alone.

## Source and amendment check

- Source: Regulation (EU) 2024/1689, Article 9 "Risk management system", English text (DOC_1), fetched from
  `https://publications.europa.eu/resource/celex/32024R1689` with `Accept: application/xhtml+xml`. The request
  redirected to Cellar expression `dc8116a1-3fe6-11ef-865a-01aa75ed71a1.0006.03/DOC_1` (Official Journal L series,
  2024/1689). SHA-256 of the file as received: `8f0b656302f9864cc87e040c371f209a9d65ae1a6cecc25ca5eb737e872d721a`.
- Date read: 2026-11-04.
- Amendment check, 2026-11-04. The EUR-Lex page for 32024R1689 returned an empty HTTP 202 reply to a script, so I
  asked the Publications Office SPARQL endpoint (`https://publications.europa.eu/webapi/rdf/sparql`) for every act
  linked to the CELEX work 32024R1689 by `cdm:resource_legal_amends_resource_legal` or `cdm:resource_legal_corrects_resource_legal`.
  - One amending act came back: Regulation (EU) 2026/1744 of 8 July 2026 (the "Digital Omnibus on AI",
    CELEX 32026R1744, OJ L 2026/1744 of 24.7.2026). I fetched its English text the same way and listed every
    amending point in its enacting terms. It amends, among others, Articles 10, 11, 17 and 72(3) of
    Regulation (EU) 2024/1689, but has no point that amends Article 9. Article 9 is named in it only in the recitals and in a
    new point on guidance about Article 9(10). So the wording below is the original 2024 wording.
  - Four corrigenda came back (32024R1689R(01) to R(04)). Their language versions are DEU, FRA, GLE, HUN, LIT,
    SLK, SLV, SPA, SWE (R(01)), NLD, SLV (R(02)), CES (R(03)) and NLD, SPA (R(04)). None is in English, so none changes the
    English text used here.
  - Note: Article 9(2)(c) refers to Article 72, whose paragraph 3 is replaced by Regulation (EU) 2026/1744. This does not
    change Article 9 itself.
- "This Section" in Article 9(4) and 9(6) is Section 2 "Requirements for high-risk AI systems", Articles 8 to 15, as the
  headings in the same text show.

## Requirements a written file can show

| id | Article 9 ref | What the file should show |
|---|---|---|
| E01 | Art. 9(1) | That a risk management system exists and is documented for a named high-risk AI system: the system, its provider and version, and who prepared the file. |
| E02 | Art. 9(2), first subparagraph | That the process is planned for the whole lifecycle and is reviewed and updated regularly: a review date or interval and a record of past changes (versions or a change log). |
| E03 | Art. 9(2)(a) | The intended purpose of the system, stated clearly, since the risks in point (a) are judged against it. |
| E04 | Art. 9(2)(a) | A list of the known and reasonably foreseeable risks the system can pose to health, safety or fundamental rights under its intended purpose. |
| E05 | Art. 9(2)(a) | An analysis of each identified risk: its cause or source, who is affected, and whether health, safety or fundamental rights are at stake. |
| E06 | Art. 9(2)(b) | An estimate of each risk under intended use, for example a likelihood and a severity, with the scale used. |
| E07 | Art. 9(2)(b) | An evaluation of each risk: a judgement against stated criteria, such as a risk level or priority and the threshold for acceptance. |
| E08 | Art. 9(2)(b) | The reasonably foreseeable misuse scenarios considered, and the estimate and evaluation of risks that arise under them. |
| E09 | Art. 9(2)(c) | Where other risks are evaluated from post-market monitoring data (Art. 72): a place for that evaluation, the data it rests on, or a statement that no such data exists yet. |
| E10 | Art. 9(2)(d) | For each risk from point (a), the risk management measures adopted, specific to that risk and linked to it. |
| E11 | Art. 9(3) | That the risks in the file are ones that can reasonably be mitigated or eliminated through development or design, or through adequate technical information, for example by naming that route for each measure. |
| E12 | Art. 9(4) | That the measures take account of the effects and interaction of applying the Section 2 requirements (Arts. 8 to 15) together, for example cross-references to data governance, transparency, human oversight or accuracy measures. |
| E13 | Art. 9(5), first subparagraph | For each hazard, the residual risk after measures, and a recorded judgement that it is acceptable (with who judged it and why). |
| E14 | Art. 9(5), first subparagraph | The overall residual risk of the system, and a recorded judgement that it is acceptable. |
| E15 | Art. 9(5)(a) | Which risks are eliminated or reduced by design and development, as far as technically feasible. |
| E16 | Art. 9(5)(b) | For risks that cannot be eliminated, the mitigation and control measures put in place. |
| E17 | Art. 9(5)(c) | The information given under Art. 13 and, where appropriate, the training given to deployers. |
| E18 | Art. 9(5), second subparagraph | How the deployer's expected technical knowledge, experience, education and training, and the presumable context of use, were taken into account. |
| E19 | Art. 9(6) | The testing done to choose the most appropriate measures, and its results, showing consistent performance for the intended purpose and compliance with Section 2. |
| E20 | Art. 9(8) | The metrics and probabilistic thresholds, defined before testing, that the tests were run against, and why they fit the intended purpose. |
| E21 | Art. 9(8) | When testing was done, including testing before the system is placed on the market or put into service. |
| E22 | Art. 9(9) | Whether the system is likely to have an adverse impact on persons under 18 and, as appropriate, other vulnerable groups, and the conclusion. |

## Not checkable in a file

| Article 9 ref | Duty | Why a file cannot show it |
|---|---|---|
| Art. 9(1) | The system is established, implemented and maintained. | A file can show that it is documented; that it is actually run and kept up over time can only be seen in practice. |
| Art. 9(2), first subparagraph | The process is continuous and iterative and run throughout the lifecycle. | A single file is one point in time; it can show a plan and past changes (E02), not that the process keeps running. |
| Art. 9(5), first subparagraph | Residual risk is judged acceptable. | The file can record the judgement (E13, E14); whether the judgement is sound is a matter for the reader, not the file. |
| Art. 9(6) | Testing ensures consistent performance and compliance. | A file can report tests (E19); it cannot show that the tests were enough. |
| Art. 9(7) | Testing may include real-world testing under Art. 60. | A permission, not a duty. A file may mention it but need not. |
| Art. 9(8) | Testing is performed, as appropriate, at any time during development. | A file can give test dates (E21); whether testing was done at the right times during development can only be seen from the development record. |
| Art. 9(10) | The risk management aspects may be combined with procedures under other Union law. | A permission for providers already under such law, not a duty on every file. |
