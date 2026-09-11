"""Static conflict detection for event-based time rules."""

from __future__ import annotations

from typing import Any

from .const import (
    CONF_RULE_ACTION,
    CONF_RULE_COVERS,
    CONF_RULE_DAY_TYPE,
    CONF_RULE_ENABLED,
    CONF_RULE_FRIDAY,
    CONF_RULE_ID,
    CONF_RULE_MONDAY,
    CONF_RULE_PRIORITY,
    CONF_RULE_SATURDAY,
    CONF_RULE_SCOPE,
    CONF_RULE_SUNDAY,
    CONF_RULE_THURSDAY,
    CONF_RULE_TRIGGER,
    CONF_RULE_TRIGGER_OFFSET,
    CONF_RULE_TRIGGER_REFERENCE,
    CONF_RULE_TUESDAY,
    CONF_RULE_WEDNESDAY,
    DAY_TYPE_ANY,
    RULE_SCOPE_GLOBAL,
    TIME_REFERENCE_FIXED,
)
from .schedule import normalize_boolean, normalize_rule

_WEEKDAY_FIELDS = (
    CONF_RULE_MONDAY,
    CONF_RULE_TUESDAY,
    CONF_RULE_WEDNESDAY,
    CONF_RULE_THURSDAY,
    CONF_RULE_FRIDAY,
    CONF_RULE_SATURDAY,
    CONF_RULE_SUNDAY,
)


def _day_types_overlap(left: str, right: str) -> bool:
    return left == DAY_TYPE_ANY or right == DAY_TYPE_ANY or left == right


def _covers(rule: dict[str, Any], all_covers: set[str]) -> set[str]:
    if str(rule.get(CONF_RULE_SCOPE)) == RULE_SCOPE_GLOBAL:
        return set(all_covers)
    configured = rule.get(CONF_RULE_COVERS, [])
    if isinstance(configured, str):
        configured = [configured]
    if not isinstance(configured, (list, tuple, set, frozenset)):
        return set()
    return {str(item) for item in configured if str(item) in all_covers}


def _same_trigger(left: dict[str, Any], right: dict[str, Any]) -> bool:
    """Compare the fields actually used to resolve each event.

    Switching reference type retains the previous time or solar offset in
    storage. Those inactive fields must not hide an actual schedule conflict.
    """
    reference = left[CONF_RULE_TRIGGER_REFERENCE]
    if reference != right[CONF_RULE_TRIGGER_REFERENCE]:
        return False
    if reference == TIME_REFERENCE_FIXED:
        return left[CONF_RULE_TRIGGER] == right[CONF_RULE_TRIGGER]
    return left[CONF_RULE_TRIGGER_OFFSET] == right[CONF_RULE_TRIGGER_OFFSET]


def detect_rule_conflicts(
    rules: list[dict[str, Any]],
    all_covers: list[str] | set[str],
) -> list[dict[str, Any]]:
    """Return deterministic warnings for impossible or ambiguous rules."""
    covers = {str(item) for item in all_covers}
    normalized: list[dict[str, Any]] = []
    conflicts: list[dict[str, Any]] = []
    for raw_rule in rules:
        if isinstance(raw_rule, dict) and not normalize_boolean(
            raw_rule.get(CONF_RULE_ENABLED), True
        ):
            continue
        try:
            normalized.append(normalize_rule(raw_rule))
        except (KeyError, TypeError, ValueError):
            invalid_rule = raw_rule if isinstance(raw_rule, dict) else {}
            conflicts.append(
                {
                    "type": "invalid_rule",
                    "rule_ids": [
                        str(invalid_rule.get(CONF_RULE_ID) or "unknown")
                    ],
                    "covers": sorted(_covers(invalid_rule, covers)),
                }
            )

    for rule in normalized:
        if not any(bool(rule[field]) for field in _WEEKDAY_FIELDS):
            conflicts.append(
                {
                    "type": "no_weekdays",
                    "rule_ids": [rule[CONF_RULE_ID]],
                    "covers": sorted(_covers(rule, covers)),
                }
            )

    for index, left in enumerate(normalized):
        left_covers = _covers(left, covers)
        for right in normalized[index + 1 :]:
            if not _same_trigger(left, right):
                continue
            if not _day_types_overlap(
                str(left[CONF_RULE_DAY_TYPE]), str(right[CONF_RULE_DAY_TYPE])
            ):
                continue
            if not any(
                bool(left[field]) and bool(right[field]) for field in _WEEKDAY_FIELDS
            ):
                continue
            overlap = left_covers & _covers(right, covers)
            if not overlap:
                continue
            same_action = left[CONF_RULE_ACTION] == right[CONF_RULE_ACTION]
            same_priority = left[CONF_RULE_PRIORITY] == right[CONF_RULE_PRIORITY]
            cross_scope = left[CONF_RULE_SCOPE] != right[CONF_RULE_SCOPE]
            conflicts.append(
                {
                    "type": (
                        "room_overrides_global"
                        if cross_scope
                        else "duplicate_rule"
                        if same_action and same_priority
                        else "same_trigger_opposite_action"
                        if not same_action
                        else "same_trigger_different_priority"
                    ),
                    "rule_ids": [left[CONF_RULE_ID], right[CONF_RULE_ID]],
                    "covers": sorted(overlap),
                    "trigger_reference": left[CONF_RULE_TRIGGER_REFERENCE],
                    "trigger_time": left[CONF_RULE_TRIGGER],
                    "trigger_offset_minutes": left[CONF_RULE_TRIGGER_OFFSET],
                }
            )
    return conflicts


def first_blocking_conflict(
    candidate: dict[str, Any],
    existing_rules: list[dict[str, Any]],
    all_covers: list[str] | set[str],
    *,
    editing_rule_id: str | None = None,
) -> str | None:
    """Return the config-flow error key for a newly introduced conflict."""
    candidate = normalize_rule(candidate)
    if not any(bool(candidate[field]) for field in _WEEKDAY_FIELDS):
        return "rule_no_weekdays"
    combined: list[dict[str, Any]] = []
    for rule in existing_rules:
        if not isinstance(rule, dict) or not normalize_boolean(
            rule.get(CONF_RULE_ENABLED), True
        ):
            continue
        if str(rule.get(CONF_RULE_ID)) == str(editing_rule_id or ""):
            continue
        try:
            combined.append(normalize_rule(rule))
        except (KeyError, TypeError, ValueError):
            # A damaged legacy rule must not prevent users from repairing or
            # extending the remaining schedule through the config flow.
            continue
    combined.append(candidate)
    candidate_id = str(candidate[CONF_RULE_ID])
    for conflict in detect_rule_conflicts(combined, all_covers):
        if candidate_id not in {str(item) for item in conflict.get("rule_ids", [])}:
            continue
        if conflict["type"] == "same_trigger_opposite_action":
            return "rule_conflict_opposite_action"
        if conflict["type"] == "duplicate_rule":
            return "rule_conflict_duplicate"
    return None
