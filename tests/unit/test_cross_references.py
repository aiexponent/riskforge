"""build_cross_references: every framework reference of a cluster (D4, ADR-05).

The 2.0.0 independent test found that each cross-reference group carried the NIST AI RMF
and ISO/IEC 42001 references of its first item only: the ``Art.9(2)(a)`` group showed
``MEASURE 2.11`` and ``Annex A.7`` while it also held items citing ``GOVERN 1.1`` and
``MAP 5.1``. Schema 1.2.0 adds ``nist_rmf_refs`` and ``iso42001_refs`` with every distinct
reference, and keeps the single fields as the first of each.
"""

from __future__ import annotations

from riskforge.engine.export import build_cross_references
from riskforge.models.risk import Likelihood, RiskDimension, RiskItem, Severity


def _item(articles: list[str], nist: list[str], iso: list[str], **legacy: str) -> RiskItem:
    return RiskItem(
        dimension=RiskDimension.robustness,
        title="Risk",
        description="Desc.",
        likelihood=Likelihood.possible,
        severity=Severity.moderate,
        residual_likelihood=Likelihood.unlikely,
        residual_severity=Severity.minor,
        article_refs=articles,
        nist_rmf_refs=nist,
        iso42001_refs=iso,
        **legacy,
    )


def test_a_cluster_lists_the_references_of_every_item_in_order() -> None:
    first = _item(["Art.9(2)(a)"], ["MEASURE 2.11"], ["Annex A.7"])
    second = _item(["Art.9(2)(a)"], ["GOVERN 1.1", "MAP 5.1"], ["Clause 6.1"])
    [cluster] = build_cross_references([first, second])
    assert cluster.risk_item_ids == [first.id, second.id]
    assert cluster.nist_rmf_refs == ["MEASURE 2.11", "GOVERN 1.1", "MAP 5.1"]
    assert cluster.iso42001_refs == ["Annex A.7", "Clause 6.1"]
    assert (cluster.nist_rmf_ref, cluster.iso42001_ref) == ("MEASURE 2.11", "Annex A.7")


def test_a_reference_shared_by_two_items_is_listed_once() -> None:
    items = [
        _item(["Art.10"], ["MAP 2.3"], ["Annex A.7"]),
        _item(["Art.10"], ["MAP 2.3", "MEASURE 2.5"], ["Annex A.7"]),
    ]
    [cluster] = build_cross_references(items)
    assert cluster.nist_rmf_refs == ["MAP 2.3", "MEASURE 2.5"]
    assert cluster.iso42001_refs == ["Annex A.7"]


def test_each_article_gets_the_references_of_its_own_items() -> None:
    both = _item(["Art.9(2)(a)", "Art.14"], ["GOVERN 1.1"], [])
    oversight = _item(["Art.14"], ["MANAGE 2.4"], ["Clause 8.4"])
    by_article = {c.article_ref: c for c in build_cross_references([both, oversight])}
    assert by_article["Art.9(2)(a)"].nist_rmf_refs == ["GOVERN 1.1"]
    assert by_article["Art.9(2)(a)"].iso42001_refs == []
    assert by_article["Art.14"].nist_rmf_refs == ["GOVERN 1.1", "MANAGE 2.4"]
    assert by_article["Art.14"].iso42001_refs == ["Clause 8.4"]


def test_an_item_with_only_the_legacy_single_field_still_counts() -> None:
    legacy = _item(["Art.13"], [], [], nist_rmf_ref="MAP 1.1", iso42001_ref="Clause 7.4")
    [cluster] = build_cross_references([legacy])
    assert (cluster.nist_rmf_refs, cluster.iso42001_refs) == (["MAP 1.1"], ["Clause 7.4"])
    assert (cluster.nist_rmf_ref, cluster.iso42001_ref) == ("MAP 1.1", "Clause 7.4")


def test_a_cluster_with_no_references_has_empty_lists_and_empty_fields() -> None:
    [cluster] = build_cross_references([_item(["Art.15"], ["", ""], [])])
    assert (cluster.nist_rmf_refs, cluster.iso42001_refs) == ([], [])
    assert (cluster.nist_rmf_ref, cluster.iso42001_ref) == ("", "")
