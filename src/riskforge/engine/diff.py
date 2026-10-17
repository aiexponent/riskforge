"""Compare two register documents: items added, removed, and changed field by field.

The input is the ``register`` block of a Risk Management File (or any register document
of the same shape). Every field of the register, its ``system`` block, its items and
their mitigations is compared, in the order the fields appear in the file, so a field
added to the models later is reported without a change here. A field absent on one side
equals ``None`` on the other.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

# Optional fields that RMF schema 1.0.0 forbids, so a 1.0.0 export of a register leaves
# them out even when they are set. Comparing against such a file skips them.
_ADDED_IN_RMF_1_1_0 = frozenset({"accepted_by", "recorded_by"})


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


def fields_absent_from_schema(rmf_schema_version: object) -> frozenset[str]:
    """Item and mitigation fields an RMF of *rmf_schema_version* cannot carry.

    A file without a version is treated as 1.0.0, the only version before 1.1.0.
    """
    if rmf_schema_version in (None, "1.0.0"):
        return _ADDED_IN_RMF_1_1_0
    return frozenset()


def _keys(before: dict, after: dict, skip: Iterable[str]) -> list[str]:
    """Keys of *after* in file order, then keys only in *before*, without *skip*."""
    skipped = set(skip)
    keys = [key for key in after if key not in skipped]
    keys += [key for key in before if key not in after and key not in skipped]
    return keys


def _field_changes(
    before: dict, after: dict, skip: Iterable[str], prefix: str = ""
) -> list[FieldChange]:
    return [
        FieldChange(prefix + key, before.get(key), after.get(key))
        for key in _keys(before, after, skip)
        if before.get(key) != after.get(key)
    ]


def _keyed_mitigations(item: dict) -> dict[str, tuple[str, dict]]:
    """Mitigations by id, or by position for one without an id, with a short label."""
    keyed: dict[str, tuple[str, dict]] = {}
    for position, mitigation in enumerate(item.get("mitigations") or [], start=1):
        mitigation_id = mitigation.get("id")
        if isinstance(mitigation_id, str) and mitigation_id:
            keyed[mitigation_id] = (mitigation_id[:8], mitigation)
        else:
            keyed[f"#{position}"] = (f"#{position}", mitigation)
    return keyed


def _mitigation_changes(before: dict, after: dict, ignore: frozenset[str]) -> list[FieldChange]:
    old = _keyed_mitigations(before)
    new = _keyed_mitigations(after)
    changes: list[FieldChange] = []
    if len(old) != len(new):
        changes.append(FieldChange("mitigations", len(old), len(new)))
    for key, (label, mitigation) in new.items():
        if key not in old:
            changes.append(FieldChange(f"mitigation {label}", None, mitigation.get("description")))
            continue
        changes += _field_changes(
            old[key][1], mitigation, skip={"id", *ignore}, prefix=f"mitigation {label} "
        )
    for key, (label, mitigation) in old.items():
        if key not in new:
            changes.append(FieldChange(f"mitigation {label}", mitigation.get("description"), None))
    return changes


def _item_changes(before: dict, after: dict, ignore: frozenset[str]) -> list[FieldChange]:
    changes: list[FieldChange] = []
    for key in _keys(before, after, skip={"id", *ignore}):
        if key == "mitigations":
            changes += _mitigation_changes(before, after, ignore)
        elif before.get(key) != after.get(key):
            changes.append(FieldChange(key, before.get(key), after.get(key)))
    return changes


def _register_changes(old: dict, new: dict) -> list[FieldChange]:
    changes: list[FieldChange] = []
    for key in _keys(old, new, skip={"items"}):
        before, after = old.get(key), new.get(key)
        if key == "system" and isinstance(before, dict) and isinstance(after, dict):
            changes += _field_changes(before, after, skip=(), prefix="system.")
        elif before != after:
            changes.append(FieldChange(key, before, after))
    return changes


def diff_registers(old: dict, new: dict, ignore: frozenset[str] = frozenset()) -> RegisterDiff:
    """Changes from register document *old* to *new*, in the order items appear.

    Items are matched by ``id`` and mitigations by their ``id`` (by position when they
    have none). Item and mitigation fields named in *ignore* are not compared; pass
    :func:`fields_absent_from_schema` for an RMF version that cannot carry them.
    Changes to the register's own fields and its ``system`` block (as ``system.<field>``)
    are ``register_changes``.
    """
    old_items = {item["id"]: item for item in old.get("items") or []}
    new_items = {item["id"]: item for item in new.get("items") or []}
    changed: list[ItemChange] = []
    for item_id, after in new_items.items():
        before = old_items.get(item_id)
        if before is None:
            continue
        changes = _item_changes(before, after, ignore)
        if changes:
            changed.append(ItemChange(item_id, str(after.get("title", "")), changes))
    return RegisterDiff(
        added=[item for item_id, item in new_items.items() if item_id not in old_items],
        removed=[item for item_id, item in old_items.items() if item_id not in new_items],
        changed=changed,
        register_changes=_register_changes(old, new),
    )
