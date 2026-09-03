"""One-time transfers from central templates into room config entries."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import (
    CONF_COVERS_EAST,
    CONF_COVERS_NORTH,
    CONF_COVERS_SOUTH,
    CONF_COVERS_WEST,
    CONF_ENTRY_TYPE,
    CONF_RULE_COVERS,
    CONF_RULE_ENABLED,
    CONF_RULE_ID,
    CONF_RULE_SCOPE,
    CONF_TIME_RULES,
    DOMAIN,
    ENTRY_TYPE_ROOM,
    RULE_SCOPE_ROOM,
)
from .logic import as_list
from .schedule import normalize_boolean, normalize_rule

_COVER_KEYS = (
    CONF_COVERS_NORTH,
    CONF_COVERS_EAST,
    CONF_COVERS_SOUTH,
    CONF_COVERS_WEST,
)


def entry_kind(entry: ConfigEntry) -> str:
    """Return the entry kind while treating old entries as rooms."""
    return str(entry.data.get(CONF_ENTRY_TYPE) or ENTRY_TYPE_ROOM)


def ordered_room_covers(values: dict[str, Any]) -> list[str]:
    """Return all covers assigned to one room in stable order."""
    return list(
        dict.fromkeys(
            str(cover)
            for key in _COVER_KEYS
            for cover in as_list(values.get(key))
            if cover
        )
    )


def room_rules_from_global(
    raw_rules: Any,
    room_covers: list[str],
) -> list[dict[str, Any]]:
    """Create independent room rules from one-time central rule drafts."""
    if not room_covers:
        return []

    result: list[dict[str, Any]] = []
    used_ids: set[str] = set()
    for index, raw_rule in enumerate(as_list(raw_rules), start=1):
        if not isinstance(raw_rule, dict) or not normalize_boolean(
            raw_rule.get(CONF_RULE_ENABLED), True
        ):
            continue
        try:
            rule = normalize_rule(raw_rule)
        except (KeyError, TypeError, ValueError):
            continue
        rule[CONF_RULE_SCOPE] = RULE_SCOPE_ROOM
        rule[CONF_RULE_COVERS] = list(room_covers)

        rule_id = str(rule.get(CONF_RULE_ID) or "").strip() or f"global-draft-{index}"
        unique_id = rule_id
        suffix = 2
        while unique_id in used_ids:
            unique_id = f"{rule_id}-{suffix}"
            suffix += 1
        rule[CONF_RULE_ID] = unique_id
        used_ids.add(unique_id)
        result.append(rule)
    return result


def append_global_time_rule_to_rooms(
    hass: HomeAssistant,
    raw_rule: Any,
    *,
    schedule_reload: bool = True,
) -> list[str]:
    """Append one newly created central rule to every existing room.

    The central options flow is only a creation wizard. The rule is never
    persisted in the central Config Entry. Each room receives an independent
    copy targeting all covers assigned to that room, while existing room rules
    remain unchanged.
    """
    updated_entries: list[str] = []
    for room_entry in hass.config_entries.async_entries(DOMAIN):
        if entry_kind(room_entry) != ENTRY_TYPE_ROOM:
            continue

        current = dict(room_entry.data)
        current.update(room_entry.options)
        room_covers = ordered_room_covers(current)
        copied = room_rules_from_global([raw_rule], room_covers)
        if not copied:
            continue

        existing_rules = [
            dict(rule)
            for rule in as_list(current.get(CONF_TIME_RULES))
            if isinstance(rule, dict)
        ]
        used_ids = {
            str(rule.get(CONF_RULE_ID) or "").strip()
            for rule in existing_rules
            if str(rule.get(CONF_RULE_ID) or "").strip()
        }
        new_rule = copied[0]
        base_id = str(new_rule.get(CONF_RULE_ID) or "global-draft").strip()
        unique_id = base_id
        suffix = 2
        while unique_id in used_ids:
            unique_id = f"{base_id}-{suffix}"
            suffix += 1
        new_rule[CONF_RULE_ID] = unique_id

        options = dict(room_entry.options)
        options[CONF_TIME_RULES] = [*existing_rules, new_rule]
        hass.config_entries.async_update_entry(room_entry, options=options)
        updated_entries.append(room_entry.entry_id)

        if schedule_reload and room_entry.state.recoverable:
            hass.config_entries.async_schedule_reload(room_entry.entry_id)

    return updated_entries
