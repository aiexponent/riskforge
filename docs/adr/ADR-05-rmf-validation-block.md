# ADR-05: RMF Schema 1.2.0 Records the Validation Gates

**Status:** Accepted, amended before release on 2026-11-06 (section 1a, cross-reference lists)
**Date:** November 2026
**Deciders:** Maintainer

## Context

`riskforge export` runs the validation gates G1 to G8 and refuses to export while one fails, unless `--force` is given. RiskForge 2.0.0 writes RMF schema 1.1.0, which has no place for the gate results. A forced export therefore looks, in the JSON and Markdown files, exactly like an export that passed every gate. The PDF re-runs the gates when it renders and prints "Exported with failing gates: G3" on its cover, but that sentence is not part of the content digest the PDF prints, so the digest does not vouch for it.

The independent test of 2.0.0 (`verification/REPORT.md`, defect D1) found this on its German Credit inputs: gate G3 failed, the export was forced, and the signed JSON gave no sign of it.

The same test found that each cross-reference group carried the NIST AI RMF and ISO/IEC 42001 references of one item only (defect D4). The `Art.9(2)(a)` group showed `MEASURE 2.11` and `Annex A.7`, yet it also held items citing `GOVERN 1.1` and `MAP 5.1`. The single string fields `nist_rmf_ref` and `iso42001_ref` cannot hold more than one reference.

The gate results are content a reader relies on. AGENTS.md hard rule 5 says a change to what the export digest covers needs an ADR, and ADR-04's Consequence section says a change to the RMF's fields needs a new schema version. Schema 1.1.0 forbids extra top-level properties, so the results cannot be added to it. This ADR defines RMF schema 1.2.0.

## Decision

### 1. RMF schema 1.2.0

New exports declare `"rmf_schema_version": "1.2.0"`. The schema file is `src/riskforge/_data/schemas/rmf-1.2.0.schema.json` and its `$id` is `https://aiexponent.com/schemas/riskforge/rmf/1.2.0.json`, the URL the website serves it from.

Schema 1.2.0 is schema 1.1.0 with one required top-level object added, `validation`, and two required fields added to each cross-reference (section 1a):

```json
"validation": {
  "status": "FAIL",
  "gates": [
    {"gate_id": "G1", "description": "All 8 risk dimensions have entries", "status": "PASS", "details": ""},
    {"gate_id": "G3", "description": "Every risk's residual score ...", "status": "FAIL", "details": "..."}
  ]
}
```

| Field | Rule |
| --- | --- |
| `status` | `PASS`, `WARN` or `FAIL`: the most severe status among the gates |
| `gates` | At least one item, in the order `ValidateEngine.run` returns them |
| `gates[].gate_id` | Matches `^G[0-9]+$` |
| `gates[].description` | Non-empty string, the gate's description |
| `gates[].status` | `PASS`, `WARN` or `FAIL` |
| `gates[].details` | String, empty when the gate gives none |

Both objects have `additionalProperties: false`.

### 1a. Cross-reference lists

Each item of `cross_references` gains two required arrays:

| Field | Rule |
| --- | --- |
| `nist_rmf_refs` | Every distinct NIST AI RMF reference of the group's risk items, non-empty strings, no repeats |
| `iso42001_refs` | Every distinct ISO/IEC 42001 reference of the group's risk items, non-empty strings, no repeats |

`ExportEngine.build_rmf` lists the references in the order of the group's items, and within an item in the order the item gives them. An item's references are its `nist_rmf_refs` and `iso42001_refs`, or its legacy single field when its list is empty. `nist_rmf_ref` and `iso42001_ref` stay, each the first item of its list or an empty string, so a reader of the 1.1.0 fields finds what it found before. The schema cannot say that the single field is the first of the list, and `verify` does not check it: both are inside the digest, so neither can change unnoticed.

Nothing else in schema 1.1.0 changes.

### 2. Content digest

The 1.2.0 digest uses the 1.1.0 rule of ADR-04 section 2 unchanged: the document without `id`, `generated_at`, `sha256_hash`, `signatures`, `public_keys`, `chain_proof` and `receipt`, with `signoffs` read as `[]` when absent. `validation` and the cross-reference lists are not left out, so the digest covers them, and so does every signature over the digest. No field joins the left-out list.

### 3. What an export records

`ExportEngine.build_rmf` runs the gates on the register it exports and records them in `validation`. `export` runs the same gates first and refuses an export with a FAIL gate unless it is forced, as before. The gates depend only on the register, so two exports of one register state by one RiskForge version still share a digest (AGENTS.md hard rule 2). The disclosure names the RiskForge version, so a release that changes a gate's rule or wording also changes the digest, as it already does.

A file whose `status` is `FAIL` was exported with `--force`. The flag itself is not recorded: an export without it cannot have a failing gate, so the gate results say everything the flag would.

### 4. Verification

`riskforge verify --file` reads files of schema 1.0.0, 1.1.0 and 1.2.0. For 1.2.0 it checks, after the schema and before the provenance steps of ADR-04 section 6, what the schema cannot:

- no `gate_id` appears twice, and
- `status` equals the most severe gate status.

Either failure exits 2. A signer can therefore not produce a valid file that reports `PASS` over a failing gate, even by redoing the digest and the signature.

`verify` does not run the gates again on the register in the file. A later release may change a gate, and a file must keep verifying with the rules of the version that wrote it.

### 5. The audit entry

The `rmf.exported` payload gains `failing_gates`, the list of FAIL gate ids, only when that list is not empty. An export that passed every gate writes the same payload as before. The audit log then shows which exports were forced without opening the files.

### 6. Renderers

The PDF and Markdown exporters render `validation` from the file. They no longer run the gates themselves, so what they show is what the digest covers. The Markdown export gains a "Validation Gates" section. Its result line names the failing gates of a forced export. The PDF keeps its cover line and gate list.

### 7. Compatibility

- RiskForge writes only 1.2.0 files from this release on. Files of schema 1.0.0 and 1.1.0 keep verifying with their own rules. `tests/fixtures/v2_0_0_rmf/rmf.json`, the signed 1.1.0 export of the 2.0.0 independent test, is the reference for 1.1.0.
- A receipt in a 1.2.0 file is read like one in a 1.1.0 file. `--receipt` accepts both.
- RiskForge 2.0.0 does not read 1.2.0 files: its `verify --file` exits 3 with "RMF schema version '1.2.0' is not one this RiskForge reads". Downgrade is not supported, as in ADR-03 and ADR-04.
- The 1.2.0 schema must be published at its `$id` URL before a release that writes it. `tests/release/test_published_schemas.py` checks this on every release.

## Rationale

- **A new block, not a sentence.** A tool reading the JSON can find which gates failed without parsing prose, and every format renders the same data.
- **Inside the digest.** The gate results describe the register's state, not the act of exporting, so they belong with the content the signature covers. Outside the digest they would carry no more weight than the PDF line they replace.
- **Every gate, not only failures.** A reader sees the WARN gates too, and that every gate ran.
- **Lists beside the single fields.** The lists give every reference, and the single fields keep their 1.1.0 meaning for a tool that reads only them.
- **A consistency check in verify.** The schema cannot say that `status` is the worst gate status. Without the check, a hand-made file could carry a PASS summary over a FAIL gate and still verify.

## Alternatives Considered

- **Append the failing gates to `disclosure`.** No schema change and covered by the digest, but only a sentence: a tool cannot read the gate results, and WARN gates are not shown. Considered and rejected by the maintainer on 2026-11-05.
- **Record `forced: true`.** Redundant with the gate results, and two exports of one passing register, one with `--force` and one without, would then have different digests.
- **Record the gates only in the `rmf.exported` audit entry.** The chain proof would carry it, but the digest would not, and a reader of the Markdown or PDF would not see it.
- **One cross-reference group per article and framework reference.** Every reference would be shown, but the groups would multiply, and a reader looking up an article would find it split across groups.
- **Replace the single reference fields with the lists.** Cleaner, but a tool written for 1.1.0 would lose the fields it reads.
- **Re-run the gates in `verify` and compare.** That would tie verification to the gate rules of the verifying release, so a file written by one release could fail under the next for no change in the file.

## Trade-offs Accepted

- Every export of 2.1 has a new digest compared with 2.0.0 for the same register, because the content changed. The verification baseline is regenerated at the release.
- The gate descriptions and details are text, so a change of wording in a later release changes the digest of an otherwise identical register. The version in the disclosure already has that effect.
- A file says that it was forced only through its gate results. It does not say who forced it. The `rmf.exported` entry names the actor.

## Enforcement

- `tests/contract/test_rmf_schemas.py`: the 1.2.0 schema and its `$id`; new documents are 1.2.0 and carry all eight gates with the worst status; 1.2.0 requires the block and refuses an extra field, an unknown status, a bad gate id, an empty description, a missing `details` and an empty gate list; the digest covers the block; the 2.0.0 fixture is pinned and still validates as 1.1.0 and matches its digest; 1.1.0 cannot carry the block; 1.2.0 cross-references carry both lists, refuse a missing list, a repeated or empty reference and a string in place of a list; 1.1.0 cannot carry the lists; the digest covers them.
- `tests/integration/test_export_command.py`: a forced export records FAIL and the failing gates in JSON, Markdown and PDF under one digest, and in `rmf.exported`; an edited gate result fails `verify --file` with exit code 2.
- `tests/integration/test_verify_file.py`: the 2.0.0 fixture verifies as 1.1.0; a PASS status over a failing gate fails even when re-signed by the trusted key; a gate listed twice fails.
- `tests/unit/test_validation_record.py`: the status is the most severe gate status, and every gate keeps its order and details.
- `tests/unit/test_cross_references.py`: a group lists the references of every item in order, once each; each article gets its own items' references; the legacy single field counts; a group without references has empty lists and empty single fields.

## Consequence

Any later change to the `validation` block, to the gates it records, to the cross-reference lists of section 1a, or to the verify checks in section 4 needs a new ADR, and a change to the block's fields needs a new RMF schema version. Files written under 1.0.0, 1.1.0 and 1.2.0 must keep verifying with the rules above and in ADR-04.
