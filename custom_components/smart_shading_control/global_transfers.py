"""One-time transfers from central templates into room config entries."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from homeassistant.config_entries import ConfigEntry, ConfigEntryState
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
from .schedule_conflicts import first_blocking_conflict

_COVER_KEYS = (
    CONF_COVERS_NORTH,
    CONF_COVERS_EAST,
    CONF_COVERS_SOUTH,
    CONF_COVERS_WEST,
)

MIGRATION_SOURCE_KEY = "_ssc_migration_source"


def migration_rule_tombstone(rule: dict[str, Any]) -> dict[str, Any] | None:
    """Return a hidden retry tombstone for a deleted migrated room rule."""
    if not str(rule.get(MIGRATION_SOURCE_KEY) or "").strip():
        return None
    tombstone = dict(rule)
    tombstone[CONF_RULE_ENABLED] = False
    return tombstone


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


def schedule_room_entry_reloads(
    hass: HomeAssistant,
    entry_ids: Iterable[str],
) -> None:
    """Reload changed room entries once, after all of their updates are committed."""
    pending = set(entry_ids)
    if not pending:
        return
    for room_entry in hass.config_entries.async_entries(DOMAIN):
        if (
            room_entry.entry_id in pending
            and entry_kind(room_entry) == ENTRY_TYPE_ROOM
            and (
                (
                    room_entry.state.recoverable
                    and room_entry.state is not ConfigEntryState.NOT_LOADED
                )
                # Core's scheduled reload task waits for the Config Entry's
                # setup lock.  Scheduling here therefore safely rebuilds a
                # room which was already setting up when a central update was
                # committed, instead of leaving it with the old source
                # listeners.  Other non-recoverable states (notably unload and
                # migration failures) remain intentionally excluded.
                or room_entry.state is ConfigEntryState.SETUP_IN_PROGRESS
            )
        ):
            hass.config_entries.async_schedule_reload(room_entry.entry_id)


def append_global_time_rule_to_rooms(
    hass: HomeAssistant,
    raw_rule: Any,
    *,
    schedule_reload: bool = True,
) -> tuple[list[str], str | None]:
    """Append one newly created central rule to every existing room.

    The central options flow is only a creation wizard. The rule is never
    persisted in the central Config Entry. Each room receives an independent
    copy targeting all covers assigned to that room, while existing room rules
    remain unchanged. Every room is preflighted before the first Config Entry
    update so a conflict can never leave a partially distributed rule behind.

    Return ``(updated_entry_ids, error_key)``. ``error_key`` is either the same
    localized conflict key used by the room rule flow or the no-target error
    when no existing room can persist the create-only rule.
    """
    planned_updates: list[tuple[ConfigEntry, dict[str, Any]]] = []
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

        active_rules = [
            rule
            for rule in existing_rules
            if normalize_boolean(rule.get(CONF_RULE_ENABLED), True)
        ]
        if conflict := first_blocking_conflict(
            new_rule,
            active_rules,
            room_covers,
        ):
            return [], conflict

        options = dict(room_entry.options)
        options[CONF_TIME_RULES] = [*existing_rules, new_rule]
        planned_updates.append((room_entry, options))

    if not planned_updates:
        return [], "global_rule_no_target_rooms"

    updated_entries: list[str] = []
    for room_entry, options in planned_updates:
        if hass.config_entries.async_update_entry(room_entry, options=options):
            updated_entries.append(room_entry.entry_id)

    if schedule_reload:
        schedule_room_entry_reloads(hass, updated_entries)

    return updated_entries, None


def migrate_global_time_rules_to_rooms(
    hass: HomeAssistant,
    global_entry: ConfigEntry,
    rules: list[dict[str, Any]],
    *,
    schedule_reload: bool = True,
) -> tuple[list[str], bool]:
    """Idempotently copy legacy central rules into every existing room.

    The source marker is retained in each copied rule so a migration retry after
    partial progress updates the same copy instead of appending a duplicate.
    Existing room rules, including rules whose IDs collide with a central rule,
    are never replaced.

    Return ``(updated_entry_ids, complete)``. ``complete`` is false when at
    least one source rule could not be represented in every room, including
    when no room exists yet. The caller must retain the central source in that
    case.
    """
    if not rules:
        return [], True

    room_entries = [
        entry
        for entry in hass.config_entries.async_entries(DOMAIN)
        if entry_kind(entry) == ENTRY_TYPE_ROOM
    ]
    if not room_entries:
        return [], False

    updated_entries: list[str] = []
    complete = True
    for room_entry in room_entries:
        current = dict(room_entry.data)
        current.update(room_entry.options)
        room_covers = ordered_room_covers(current)
        if not room_covers:
            complete = False
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
        changed = False

        for index, raw_rule in enumerate(rules, start=1):
            try:
                copied_rule = normalize_rule(raw_rule)
            except (KeyError, TypeError, ValueError):
                complete = False
                continue

            copied_rule[CONF_RULE_SCOPE] = RULE_SCOPE_ROOM
            copied_rule[CONF_RULE_COVERS] = list(room_covers)
            if not normalize_boolean(raw_rule.get(CONF_RULE_ENABLED), True):
                # Preserve a disabled legacy rule without activating it. The
                # runtime checks this flag before normalizing a stored rule.
                copied_rule[CONF_RULE_ENABLED] = False

            source_id = str(copied_rule.get(CONF_RULE_ID) or f"rule-{index}")
            source = f"v20:{global_entry.entry_id}:{index}:{source_id}"
            copied_rule[MIGRATION_SOURCE_KEY] = source

            existing_index = next(
                (
                    item_index
                    for item_index, existing in enumerate(existing_rules)
                    if existing.get(MIGRATION_SOURCE_KEY) == source
                ),
                None,
            )
            if existing_index is not None:
                # The first copy becomes an independent room rule immediately.
                # A later retry exists only to reach other rooms and must never
                # overwrite edits the user has meanwhile made to this copy.
                continue

            base_id = source_id.strip() or f"global-rule-{index}"
            unique_id = base_id
            suffix = 2
            while unique_id in used_ids:
                unique_id = f"{base_id}-{suffix}"
                suffix += 1
            copied_rule[CONF_RULE_ID] = unique_id
            used_ids.add(unique_id)
            existing_rules.append(copied_rule)
            changed = True

        if not changed:
            continue
        options = dict(room_entry.options)
        options[CONF_TIME_RULES] = existing_rules
        if hass.config_entries.async_update_entry(room_entry, options=options):
            updated_entries.append(room_entry.entry_id)

    if schedule_reload:
        schedule_room_entry_reloads(hass, updated_entries)
    return updated_entries, complete
