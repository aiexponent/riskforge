# How to Add a Risk Pattern

Risk patterns are pre-configured risk item clusters that `riskforge assess` adds when an AI system matches a pattern's high-risk route and one of its purpose keywords.

## When to add a pattern

Add a pattern when:
- A use case falls under a high-risk route of Regulation (EU) 2024/1689 (an Annex III point, or Article 6(1) with the Annex I legislation) and creates a well-known, documented risk cluster
- The risk cluster has established Article references in the EU AI Act or related regulation
- The risk is specific enough to generate useful pre-populated risk items (not just generic statements)

A use case with neither route does not get a pattern.

## Step 1: Edit the patterns file

Patterns live in `src/riskforge/_data/patterns/patterns.yaml`. Changes to this file need a regulatory review: flag them at the top of the pull request description.

An Annex III pattern:

```yaml
- pattern_id: YOUR_PATTERN_ID        # SCREAMING_SNAKE_CASE, unique
  name: "Human-readable pattern name"
  annex_iii_point: "4(a)"            # The Annex III point this pattern covers
  triggers:
    annex_iii_categories: [employment]           # Must include the point's category
    purpose_keywords: ["keyword1", "two words"]  # Any of these in the system purpose
    exclude_keywords: ["keyword2"]               # Optional: any of these skips the pattern
  risks:
    - dimension: discrimination
      title: "Short, specific risk title"
      description: "One to two sentences. Cite the Article that creates the obligation."
      likelihood_hint: 3
      severity_hint: 4
      article_refs: ["Art.9(2)(a)"]
      nist_rmf_ref: "MEASURE 2.11"
      iso42001_ref: "Annex A.7"
```

A product-route pattern (Article 6(1)) replaces `annex_iii_point` with:

```yaml
  high_risk_route: annex_i
  article_6_ref: "Art.6(1)"
  annex_i_legislation:
    - "Regulation (EU) 2017/745 on medical devices (Annex I, Section A, point 11)"
  triggers:
    annex_iii_categories: []        # Matches on purpose keywords alone
    purpose_keywords: ["keyword1"]
```

## Guidelines

- Every pattern names its high-risk route, checked against the Official Journal text on EUR-Lex (the AI Act Service Desk can be used as a cross-check). An Annex III pattern names the point it covers in `annex_iii_point` and lists that point's category in `annex_iii_categories`. A product-route pattern sets `high_risk_route: annex_i`, cites `article_6_ref: "Art.6(1)"`, names the Annex I legislation in `annex_i_legislation` and leaves `annex_iii_categories` empty.
- Each pattern should generate 2-4 risk items, not just one
- `likelihood_hint` and `severity_hint` are starting points; assessors always override them
- A keyword matches when it starts a word, or a run of words, in the system purpose. Matching ignores case, accents and punctuation, so `credit` matches "Creditworthiness" and `facial recognition` matches "facial-recognition", but `test` does not match "contest". Pick keywords that do not also start unrelated words.
- Use `exclude_keywords` only for a use the pattern clearly does not cover but that shares its keywords, such as `unlock`, for a system that opens a phone by face. They match the same way, and any one of them skips the pattern, even when a purpose keyword also appears.
- Do not change a kept risk's `title`: `assess` matches existing register items by pattern id and title, so a new title adds a new item when a project is assessed again
- Include at least one NIST AI RMF reference and one ISO/IEC 42001 reference per risk
