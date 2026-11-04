"""Tests for the pure helpers in verification/replay.py. Standard library only.

Run from the repository root:

    python -m unittest discover -s verification/tests -v
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import replay  # noqa: E402

A = "11111111-1111-4111-8111-111111111111"
B = "22222222-2222-4222-8222-222222222222"
C = "33333333-3333-4333-8333-333333333333"


class NormaliseRmf(unittest.TestCase):
    def test_drops_the_provenance_fields(self) -> None:
        doc = {k: "x" for k in replay.PROVENANCE_FIELDS}
        doc["register"] = {"items": []}
        self.assertEqual(replay.normalise_rmf(doc), {"register": {"items": []}})

    def test_same_item_gets_the_same_placeholder_everywhere(self) -> None:
        doc = {
            "register": {"items": [{"id": A}, {"id": B}]},
            "cross_references": [{"risk_item_ids": [B, A]}],
        }
        got = replay.normalise_rmf(doc)
        # Keys are read in sorted order: cross_references first, so B is numbered 1.
        self.assertEqual(got["cross_references"][0]["risk_item_ids"], ["<uuid-1>", "<uuid-2>"])
        self.assertEqual(got["register"]["items"], [{"id": "<uuid-2>"}, {"id": "<uuid-1>"}])

    def test_two_runs_with_new_ids_and_times_normalise_the_same(self) -> None:
        first = {"register": {"items": [{"id": A, "identified_at": "2026-11-04T08:40:32.001391Z"}]}}
        second = {"register": {"items": [{"id": C, "identified_at": "2026-11-05T10:00:00Z"}]}}
        self.assertEqual(replay.normalise_rmf(first), replay.normalise_rmf(second))

    def test_a_changed_value_still_differs(self) -> None:
        first = {"register": {"items": [{"id": A, "title": "Bias"}]}}
        second = {"register": {"items": [{"id": C, "title": "Bias in scoring"}]}}
        self.assertNotEqual(replay.normalise_rmf(first), replay.normalise_rmf(second))

    def test_uuid_inside_text_and_version_in_disclosure(self) -> None:
        doc = {
            "note": f"risk {A} was reviewed",
            "disclosure": "produced using RiskForge v2.0.0, ok",
        }
        got = replay.normalise_rmf(doc)
        self.assertEqual(got["note"], "risk <uuid-1> was reviewed")
        self.assertEqual(got["disclosure"], "produced using RiskForge v<version> ok")

    def test_numbers_and_booleans_are_kept(self) -> None:
        doc = {"register": {"risk_appetite_threshold": 9, "accepted": False}}
        self.assertEqual(replay.normalise_rmf(doc), doc)


class FirstDifference(unittest.TestCase):
    def test_equal(self) -> None:
        self.assertIsNone(replay.first_difference({"a": [1, {"b": 2}]}, {"a": [1, {"b": 2}]}))

    def test_paths(self) -> None:
        self.assertEqual(replay.first_difference({"a": [1, 2]}, {"a": [1, 3]}), "$.a[1]: 2 vs 3")
        self.assertEqual(replay.first_difference({"a": 1}, {}), "$.a: only in first")
        self.assertEqual(replay.first_difference({}, {"a": 1}), "$.a: only in second")
        self.assertEqual(replay.first_difference([1], [1, 2]), "$: 1 vs 2 entries")
        self.assertEqual(replay.first_difference({"a": 1}, {"a": "1"}), "$.a: int vs str")


class ParseOutput(unittest.TestCase):
    def test_digest(self) -> None:
        digest = "a" * 64
        out = f"✓ Exported: rmf.md\n  Content digest (SHA-256): {digest}\n  File SHA-256: {'b' * 64}\n"
        self.assertEqual(replay.parse_digest(out), digest)
        self.assertIsNone(replay.parse_digest("File SHA-256: " + "b" * 64))

    def test_system_id(self) -> None:
        out = f"✓ Initialised RiskForge project: X v1\n  System ID: {A}\n  Project dir: /p\n"
        self.assertEqual(replay.parse_system_id(out), A)
        self.assertIsNone(replay.parse_system_id("Project dir: /p"))


class FlipOneByte(unittest.TestCase):
    def test_changes_exactly_one_byte(self) -> None:
        data = b'{"title": "Bias", "x": 1}'
        offset, changed = replay.flip_one_byte(data, b'"title": "')
        self.assertEqual(changed, b'{"title": "bias", "x": 1}')
        self.assertEqual(offset, data.index(b"Bias"))
        self.assertEqual(sum(x != y for x, y in zip(data, changed, strict=False)), 1)

    def test_skips_to_the_first_letter(self) -> None:
        _, changed = replay.flip_one_byte(b'"signature": "+9az"', b'"signature": "')
        self.assertEqual(changed, b'"signature": "+9Az"')

    def test_missing_anchor_or_letter(self) -> None:
        with self.assertRaises(ValueError):
            replay.flip_one_byte(b"abc", b"zzz")
        with self.assertRaises(ValueError):
            replay.flip_one_byte(b"title: 123", b"title: ")


class MatchRisk(unittest.TestCase):
    ITEMS = [
        (A, "Demographic bias in credit scoring outputs"),
        (B, "Does the system process personal data or special category data?"),
        (C, "Does the system process personal data at all?"),
    ]

    def test_title_as_risk_list_prints_it(self) -> None:
        self.assertEqual(
            replay.match_risk(self.ITEMS, "Demographic bias in credit scoring outpu"), A
        )

    def test_full_title(self) -> None:
        self.assertEqual(
            replay.match_risk(self.ITEMS, "Demographic bias in credit scoring outputs"), A
        )

    def test_ambiguous_prefix_is_refused(self) -> None:
        with self.assertRaisesRegex(replay.InputError, "2 risk items"):
            replay.match_risk(self.ITEMS, "Does the system process personal data")

    def test_longer_prefix_resolves_it(self) -> None:
        self.assertEqual(
            replay.match_risk(self.ITEMS, "Does the system process personal data or special"), B
        )

    def test_no_match_or_empty(self) -> None:
        with self.assertRaisesRegex(replay.InputError, "no risk item"):
            replay.match_risk(self.ITEMS, "Something else")
        with self.assertRaises(replay.InputError):
            replay.match_risk(self.ITEMS, "  ")


class CheckInputs(unittest.TestCase):
    SYSTEM = {
        "name": "N",
        "version": "1.0",
        "purpose": "P",
        "provider": "Org",
        "assessor_name": "A",
        "assessor_role": "R",
    }

    def test_system_ok_and_optional_keys(self) -> None:
        got = replay.check_system_inputs({**self.SYSTEM, "category": "x", "review_months": 6})
        self.assertEqual(got["review_months"], "6")

    def test_system_missing_and_unknown(self) -> None:
        with self.assertRaisesRegex(replay.InputError, "missing assessor_role"):
            replay.check_system_inputs(
                {k: v for k, v in self.SYSTEM.items() if k != "assessor_role"}
            )
        with self.assertRaisesRegex(replay.InputError, "unknown keys: colour"):
            replay.check_system_inputs({**self.SYSTEM, "colour": "red"})
        with self.assertRaises(replay.InputError):
            replay.check_system_inputs(["not", "a", "mapping"])

    def test_decisions_ok(self) -> None:
        got = replay.check_decisions(
            {
                "by": "Name, Role",
                "mitigations": [
                    {
                        "risk": "T",
                        "description": "D",
                        "control_type": "detective",
                        "owner": "O",
                        "residual_likelihood": 2,
                    }
                ],
                "acceptances": [{"risk": "T", "rationale": "R"}],
            }
        )
        self.assertEqual(got["by"], "Name, Role")
        self.assertEqual(len(got["mitigations"]), 1)

    def test_decisions_refused(self) -> None:
        base = {"risk": "T", "description": "D", "control_type": "detective", "owner": "O"}
        cases = [
            ({"mitigations": []}, "by"),
            ({"by": "x", "extra": 1}, "unknown keys"),
            ({"by": "x", "mitigations": [{**base, "control_type": "manual"}]}, "control_type"),
            ({"by": "x", "mitigations": [{**base, "status": "done"}]}, "status"),
            ({"by": "x", "mitigations": [{**base, "residual_severity": 6}]}, "residual_severity"),
            ({"by": "x", "mitigations": [{**base, "residual_severity": "2"}]}, "residual_severity"),
            (
                {"by": "x", "mitigations": [{k: v for k, v in base.items() if k != "owner"}]},
                "owner",
            ),
            ({"by": "x", "acceptances": [{"risk": "T"}]}, "rationale"),
        ]
        for data, message in cases:
            with self.subTest(data=data), self.assertRaisesRegex(replay.InputError, message):
                replay.check_decisions(data)


class Redact(unittest.TestCase):
    def test_out_folder_becomes_a_placeholder(self) -> None:
        out = Path("/tmp/run-123")
        self.assertEqual(
            replay.redact(["export", "-o", "/tmp/run-123/run-a/rmf.json", "x"], out),
            ["export", "-o", "$OUT/run-a/rmf.json", "x"],
        )


if __name__ == "__main__":
    unittest.main()
