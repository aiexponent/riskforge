# Subject: credit scoring on the UCI Statlog German Credit data

All facts below were read on 2026-11-04. Sources:

- **[UCI]** The dataset page, https://archive.ics.uci.edu/dataset/144/statlog+german+credit+data (UCI dataset 144,
  DOI 10.24432/C5NC77). SHA-256 of the HTML as received: `055d12df0cea8babad9d461c59c4c2293c5aa3157e4c45ded9328552ce62acb5`.
- **[DOC]** `german.doc` in the download `statlog+german+credit+data.zip` from the same page. SHA-256:
  `69b92cb551111bc37098698288849c96f0fd87ce81a2e54451ff39aa1e53fe49`. The `Index` file in the download dates
  `german.doc` and the data files 17 Nov 1994.

I did not read the data files themselves, papers that cite the dataset, or any other source. Each fact has an id
(S01, S02, ...) that the inputs refer to.

## Facts from the sources

| id | Fact | Source |
|---|---|---|
| S01 | The data classifies people, described by a set of attributes, as good or bad credit risks. | [UCI] summary |
| S02 | The creator is Professor Hans Hofmann, Institut fur Statistik und Okonometrie, Universitat Hamburg. The page says the dataset was donated on 11/16/1994 and its citation gives the year 1994. | [DOC] section 2, [UCI] |
| S03 | Licence: CC BY 4.0. Sharing and adaptation for any purpose are allowed with credit. | [UCI] |
| S04 | 1000 instances. | [DOC] section 3, [UCI] |
| S05 | Two files. `german.data` is the original form from Prof. Hofmann, with 20 attributes (7 numerical, 13 categorical). `german.data-numeric` was produced by Strathclyde University for algorithms that need numbers: 24 numerical attributes, with indicator variables added and some ordered categories coded as integers. | [DOC] sections 3 and 6, [UCI] |
| S06 | The page reports no missing values. | [UCI] |
| S07 | Money amounts in the attribute codes are in DM (Deutsche Mark), for example checking account and savings bands. | [DOC] attributes 1 and 6 |
| S08 | Attribute 9, "Personal status and sex", combines sex and marital status in one code: male divorced/separated; female divorced/separated/married; male single; male married/widowed; female single. There is no code for a single female separate from the others, and married and divorced women share one code. The page tags it as demographic "Marital Status". | [DOC] attribute 9, [UCI] variables table |
| S09 | Attribute 13 is age in years. The page tags it as demographic "Age". | [DOC], [UCI] |
| S10 | Attribute 20 is "foreign worker", yes or no. The page tags it as demographic "Other". | [DOC], [UCI] |
| S11 | Attribute 17 is job, with codes including "unemployed/ unskilled - non-resident" and "unskilled - resident". The page tags it as demographic "Occupation". | [DOC], [UCI] |
| S12 | Other attributes about the person's life: present employment since (7, tagged demographic "Other"), housing: rent, own or for free (15, tagged "Other"), number of people the applicant is liable to maintain (18), telephone registered under the customer's name (19), property (12), present residence since (11). | [DOC], [UCI] |
| S13 | Financial attributes: checking account status (1), duration in months (2), credit history including past delays and critical accounts (3), purpose (4), credit amount (5), savings (6), instalment rate as a percentage of disposable income (8), other debtors or guarantors (10), other instalment plans (14), number of existing credits at this bank (16). | [DOC] |
| S14 | Purpose code A47 is listed as "(vacation - does not exist?)". The documentation itself is unsure of this code. | [DOC] attribute 4 |
| S15 | Target: a binary class, 1 = Good, 2 = Bad. | [DOC] section 8, [UCI] variables table |
| S16 | Cost matrix: rows are the actual class, columns the predicted class. Predicting good for a bad customer costs 5; predicting bad for a good customer costs 1; correct predictions cost 0. The documentation says the dataset requires use of this matrix. | [DOC] section 8, [UCI] |
| S17 | The page and `german.doc` do not say when, where or how the records were collected, from which lender or population, or over what period. | [DOC], [UCI]: absent |
| S18 | They say nothing about consent of the people in the data, about anonymisation, or about the legal basis for collecting or sharing it. No attribute is a name or an identifier. | [DOC], [UCI]: absent |
| S19 | They say nothing about whether the 1000 records represent any population of applicants, nor how many records are in each class. | [DOC], [UCI]: absent |
| S20 | They do not say how "good" and "bad" risk were decided (for example by default within a period, or by a credit officer). | [DOC], [UCI]: absent |
| S21 | The "Baseline Model Performance" section of the page shows headings (accuracy, precision) with no values. | [UCI] |
| S22 | The source address in the documentation is in Hamburg, Germany. | [DOC] section 2 |

## The system under test

The rest of this section is my assumption about a system, not a fact from the sources.

A provider, here called "Northwind Scoring Labs (fictional)", trains a binary classifier on the 1000 records of
`german.data` to score retail credit applicants as good or bad risk. The model takes the 20 attributes as inputs,
including age, the personal status and sex code and the foreign worker flag, unless the provider removes them. It outputs a
good or bad label with a score. A lender in the EU uses the score as one input when deciding on a consumer credit
application; a credit officer sees the score and makes the decision. The system is placed on the market now, so the
training data is about three decades older than the applicants it scores (S02, S07, S17), and the provider has no
post-market monitoring data yet. I also assume the provider has run a hold-out test with the cost matrix (S16) but
has no group fairness test results, no data on who the records describe (S17, S19), and no consent record (S18).

Facts versus assumptions, in short:

- From the sources: S01 to S22 above.
- Assumed: the provider and lender, the use for live retail credit decisions in the EU, that all 20 attributes are
  inputs, a credit officer in the loop, the hold-out test, no fairness tests, no post-market data, and the provider name.
