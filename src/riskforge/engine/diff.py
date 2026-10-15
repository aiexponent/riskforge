"""Compare two register documents: items added, removed, and changed field by field.

The input is the ``register`` block of a Risk Management File (or any register document
of the same shape), so the comparison does not depend on the RMF schema version.
"""

from __future__ import annotations

from dataclasses import dataclass, field

ITEM_FIELDS = (
    "likelihood",
    "severity",
    "risk_score",
    "residual_likelihood",
    "residual_severity",
    "residual_risk_score",
    "accepted",
    "knowledge_gap",
    "dimension",
    "title",
    "description",
    "acceptance_rationale",
)
REGISTER_FIELDS = ("risk_appetite_threshold", "assessor_name", "assessor_role", "review_date")
MITIGATION_FIELDS = ("description", "control_type", "owner", "status")


@dataclass(frozen=True)
class FieldChange:
    field: str
    old: object
    new: object


@dataclass(frozen=True)
class ItemChange:
    item_id: str
    title: str
    changes: list[FieldChange]


@dataclass(frozen=True)
class RegisterDiff:
    added: list[dict] = field(default_factory=list)
    removed: list[dict] = field(default_factory=list)
    changed: list[ItemChange] = field(default_factory=list)
    register_changes: list[FieldChange] = field(default_factory=list)


def _mitigations(item: dict) -> list[tuple[object, ...]]:
    return [
        tuple(mitigation.get(name) for name in MITIGATION_FIELDS)
        for mitigation in item.get("mitigations") or []
    ]


def _item_changes(before: dict, after: dict) -> list[FieldChange]:
    changes = [
        FieldChange(name, before.get(name), after.get(name))
        for name in ITEM_FIELDS
        if before.get(name) != after.get(name)
    ]
    old_mitigations, new_mitigations = _mitigations(before), _mitigations(after)
    if old_mitigations != new_mitigations:
        changes.append(FieldChange("mitigations", len(old_mitigations), len(new_mitigations)))
    return changes


def diff_registers(old: dict, new: dict) -> RegisterDiff:
    """Changes from register document *old* to *new*, in the order items appear.

    Items are matched by ``id``. A changed mitigation is reported as a ``mitigations``
    change from the old count to the new count, which can be equal when one was edited.
    """
    old_items = {item["id"]: item for item in old.get("items") or []}
    new_items = {item["id"]: item for item in new.get("items") or []}
    changed: list[ItemChange] = []
    for item_id, after in new_items.items():
        before = old_items.get(item_id)
        if before is None:
            continue
        changes = _item_changes(before, after)
        if changes:
            changed.append(ItemChange(item_id, str(after.get("title", "")), changes))
    return RegisterDiff(
        added=[item for item_id, item in new_items.items() if item_id not in old_items],
        removed=[item for item_id, item in old_items.items() if item_id not in new_items],
        changed=changed,
        register_changes=[
            FieldChange(name, old.get(name), new.get(name))
            for name in REGISTER_FIELDS
            if old.get(name) != new.get(name)
        ],
    )
