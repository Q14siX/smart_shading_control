"""Smart Shading Control integration."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import Any
from uuid import NAMESPACE_URL, uuid4, uuid5

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
from homeassistant.core import CoreState, Event, HomeAssistant, valid_entity_id
from homeassistant.exceptions import ConfigEntryError, ConfigEntryNotReady
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.storage import Store

from .command_queue import async_shutdown_command_queue
from .const import (
    CONF_AZIMUTH_EAST,
    CONF_AZIMUTH_NORTH,
    CONF_AZIMUTH_SOUTH,
    CONF_AZIMUTH_WEST,
    CONF_COVER_CONTACTS,
    CONF_COVERS_EAST,
    CONF_COVERS_NORTH,
    CONF_COVERS_SOUTH,
    CONF_COVERS_WEST,
    CONF_ENTRY_TYPE,
    CONF_GLOBAL_MANUAL_OVERRIDE_MINUTES,
    CONF_GLOBAL_POSITION_OVERRIDES,
    CONF_GLOBAL_POSITION_VALUES,
    CONF_GLOBAL_TIME_RULES,
    CONF_MANUAL_OVERRIDE_MINUTES,
    CONF_OPENING_CONTACTS,
    CONF_PERSIST_MANUAL_OVERRIDES,
    CONF_RULE_ACTION,
    CONF_RULE_COVERS,
    CONF_RULE_DAY_TYPE,
    CONF_RULE_ENABLED,
    CONF_RULE_END,
    CONF_RULE_END_OFFSET,
    CONF_RULE_END_REFERENCE,
    CONF_RULE_FRIDAY,
    CONF_RULE_ID,
    CONF_RULE_MONDAY,
    CONF_RULE_NAME,
    CONF_RULE_POSITION,
    CONF_RULE_PRIORITY,
    CONF_RULE_SATURDAY,
    CONF_RULE_SCOPE,
    CONF_RULE_START,
    CONF_RULE_START_OFFSET,
    CONF_RULE_START_REFERENCE,
    CONF_RULE_SUNDAY,
    CONF_RULE_THURSDAY,
    CONF_RULE_TRIGGER,
    CONF_RULE_TRIGGER_OFFSET,
    CONF_RULE_TRIGGER_REFERENCE,
    CONF_RULE_TUESDAY,
    CONF_RULE_WEDNESDAY,
    CONF_TIME_RULE_CLOSE_POSITION,
    CONF_TIME_RULES,
    DAY_TYPES,
    DOMAIN,
    ENTRY_TYPE_GLOBAL,
    ENTRY_TYPE_ROOM,
    LEGACY_CONF_DOOR_SENSORS,
    LEGACY_CONF_OPEN_WINDOW_SENSORS,
    LEGACY_CONF_SCHEDULE_POSITION_PREFIX,
    LEGACY_CONF_SCHEDULE_PREFIX,
    LEGACY_CONF_SCHEDULE_PRIORITY_PREFIX,
    LEGACY_CONF_TILTED_WINDOW_SENSORS,
    LEGACY_MAX_SCHEDULES,
    PLATFORMS,
    POSITION_DEFAULTS,
    POSITION_SETTING_KEYS,
    ROOM_DEFAULTS,
    RULE_ACTION_CLOSE,
    RULE_ACTION_OPEN,
    RULE_ACTIONS,
    RULE_SCOPE_GLOBAL,
    RULE_SCOPE_ROOM,
    TIME_REFERENCE_FIXED,
    TIME_REFERENCE_SUNRISE,
    TIME_REFERENCE_SUNSET,
    TIME_REFERENCES,
)
from .controller import SmartShadingController
from .coordinator import (
    COORDINATOR_KEY,
    SmartShadingDataCoordinator,
    async_get_or_create_coordinator,
)
from .entity_references import (
    PENDING_ENTITY_RENAMES_KEY,
    apply_pending_config_entity_renames,
    apply_pending_entity_renames,
    iter_config_entity_id_candidates,
    normalize_pending_entity_renames,
)
from .global_repairs import update_global_repairs
from .global_transfers import (
    migrate_global_time_rules_to_rooms,
    schedule_room_entry_reloads,
)
from .issues import create_issue, delete_entry_issues, delete_issue
from .logic import as_list
from .schedule import normalize_boolean, normalize_rule, parse_time
from .storage_helpers import async_load_persistent_store

_LOGGER = logging.getLogger(__name__)

_ENTRY_VERSION = 20
_COVER_OWNERS_KEY = "cover_owners"
_SOURCE_RENAME_UNSUBSCRIBERS_KEY = "source_rename_unsubscribers"
_SOURCE_RENAME_LOCKS_KEY = "source_rename_locks"
_COVER_KEYS = (
    CONF_COVERS_NORTH,
    CONF_COVERS_EAST,
    CONF_COVERS_SOUTH,
    CONF_COVERS_WEST,
)
_PERSISTENT_ROOM_STORE_SUFFIXES = ("manual_overrides", "control_state")
_LEGACY_CONTACT_KEYS = (
    CONF_OPENING_CONTACTS,
    LEGACY_CONF_OPEN_WINDOW_SENSORS,
    LEGACY_CONF_TILTED_WINDOW_SENSORS,
    LEGACY_CONF_DOOR_SENSORS,
)
_RULE_BOOLEAN_FIELDS = (
    CONF_RULE_ENABLED,
    CONF_RULE_MONDAY,
    CONF_RULE_TUESDAY,
    CONF_RULE_WEDNESDAY,
    CONF_RULE_THURSDAY,
    CONF_RULE_FRIDAY,
    CONF_RULE_SATURDAY,
    CONF_RULE_SUNDAY,
)
_GLOBAL_TRANSFER_ONLY_KEYS = frozenset(
    {
        CONF_GLOBAL_MANUAL_OVERRIDE_MINUTES,
        CONF_GLOBAL_POSITION_OVERRIDES,
        CONF_GLOBAL_POSITION_VALUES,
        CONF_GLOBAL_TIME_RULES,
        CONF_TIME_RULES,
        PENDING_ENTITY_RENAMES_KEY,
    }
)


def entry_type(entry: ConfigEntry) -> str:
    """Return entry type while treating old entries as rooms."""
    return str(entry.data.get(CONF_ENTRY_TYPE) or ENTRY_TYPE_ROOM)


def global_entry(hass: HomeAssistant) -> ConfigEntry | None:
    """Return the central building settings entry."""
    return next(
        (
            item
            for item in hass.config_entries.async_entries(DOMAIN)
            if entry_type(item) == ENTRY_TYPE_GLOBAL
            and item.disabled_by is None
        ),
        None,
    )


def global_config(hass: HomeAssistant) -> dict[str, Any]:
    """Return central data/options merged into one dictionary."""
    entry = global_entry(hass)
    if entry is None:
        return {}
    result = dict(entry.data)
    result.update(entry.options)
    return result


def _merged_value(data: dict[str, Any], options: dict[str, Any], key: str, default: Any) -> Any:
    return options[key] if key in options else data.get(key, default)


def _configured_covers(
    data: dict[str, Any],
    options: dict[str, Any],
) -> list[str]:
    """Return configured covers while preserving duplicate assignments."""
    return [
        str(cover)
        for key in _COVER_KEYS
        for cover in as_list(_merged_value(data, options, key, []))
    ]


def _ordered_covers(data: dict[str, Any], options: dict[str, Any]) -> list[str]:
    return list(dict.fromkeys(_configured_covers(data, options)))


def _legacy_contacts(data: dict[str, Any], options: dict[str, Any]) -> list[str]:
    contacts: list[str] = []
    for key in _LEGACY_CONTACT_KEYS:
        raw = _merged_value(data, options, key, []) or []
        if isinstance(raw, str):
            raw = [raw]
        contacts.extend(str(entity_id) for entity_id in raw if entity_id)
    return list(dict.fromkeys(contacts))


def _clean_contact_mapping(raw_mapping: Any, covers: list[str]) -> dict[str, str]:
    if not isinstance(raw_mapping, dict):
        return {}
    available = set(covers)
    return {
        str(cover): str(contact)
        for cover, contact in raw_mapping.items()
        if str(cover) in available and contact
    }


def _shift_weekdays_forward(rule: dict[str, Any]) -> None:
    """Shift selected weekdays by one day for a migrated overnight end event."""
    fields = (
        CONF_RULE_MONDAY,
        CONF_RULE_TUESDAY,
        CONF_RULE_WEDNESDAY,
        CONF_RULE_THURSDAY,
        CONF_RULE_FRIDAY,
        CONF_RULE_SATURDAY,
        CONF_RULE_SUNDAY,
    )
    selected = [normalize_boolean(rule.get(field), True) for field in fields]
    shifted = [selected[-1], *selected[:-1]]
    for field, value in zip(fields, shifted, strict=True):
        rule[field] = value


def _legacy_interval_is_overnight(raw_rule: dict[str, Any]) -> bool:
    start_ref = str(raw_rule.get(CONF_RULE_START_REFERENCE) or TIME_REFERENCE_FIXED)
    end_ref = str(raw_rule.get(CONF_RULE_END_REFERENCE) or TIME_REFERENCE_FIXED)
    if start_ref == TIME_REFERENCE_FIXED and end_ref == TIME_REFERENCE_FIXED:
        try:
            return parse_time(raw_rule.get(CONF_RULE_END, "06:00:00")) <= parse_time(
                raw_rule.get(CONF_RULE_START, "22:00:00")
            )
        except (TypeError, ValueError):
            return False
    return start_ref == TIME_REFERENCE_SUNSET and end_ref == TIME_REFERENCE_SUNRISE


def _expand_rule(raw_rule: dict[str, Any]) -> list[dict[str, Any]]:
    """Return one event rule or migrate one legacy interval into two events."""
    if CONF_RULE_ACTION in raw_rule or CONF_RULE_TRIGGER_REFERENCE in raw_rule:
        return [raw_rule]

    try:
        position = int(raw_rule.get(CONF_RULE_POSITION, 0))
    except (TypeError, ValueError):
        position = 0
    start_action = RULE_ACTION_CLOSE if position <= 50 else RULE_ACTION_OPEN
    # The former interval end recalculated automatic control. Opening is the
    # safest deterministic migration and dynamic shading may adjust it again.
    end_action = RULE_ACTION_OPEN
    name = str(raw_rule.get(CONF_RULE_NAME) or "Time rule")

    start_rule = dict(raw_rule)
    start_rule[CONF_RULE_ID] = f"{raw_rule.get(CONF_RULE_ID) or uuid4().hex}-start"
    start_rule[CONF_RULE_NAME] = name
    start_rule[CONF_RULE_ACTION] = start_action
    start_rule[CONF_RULE_TRIGGER_REFERENCE] = raw_rule.get(
        CONF_RULE_START_REFERENCE, TIME_REFERENCE_FIXED
    )
    start_rule[CONF_RULE_TRIGGER] = raw_rule.get(CONF_RULE_START, "22:00:00")
    start_rule[CONF_RULE_TRIGGER_OFFSET] = raw_rule.get(CONF_RULE_START_OFFSET, 0)

    end_rule = dict(raw_rule)
    end_rule[CONF_RULE_ID] = f"{raw_rule.get(CONF_RULE_ID) or uuid4().hex}-end"
    end_rule[CONF_RULE_NAME] = name
    end_rule[CONF_RULE_ACTION] = end_action
    end_rule[CONF_RULE_TRIGGER_REFERENCE] = raw_rule.get(
        CONF_RULE_END_REFERENCE, TIME_REFERENCE_FIXED
    )
    end_rule[CONF_RULE_TRIGGER] = raw_rule.get(CONF_RULE_END, "06:00:00")
    end_rule[CONF_RULE_TRIGGER_OFFSET] = raw_rule.get(CONF_RULE_END_OFFSET, 0)
    if _legacy_interval_is_overnight(raw_rule):
        _shift_weekdays_forward(end_rule)

    return [start_rule, end_rule]


def _known_rule_boolean(value: Any) -> bool:
    """Return whether a stored migration value has unambiguous bool meaning."""
    if isinstance(value, bool):
        return True
    if isinstance(value, (int, float)):
        return not isinstance(value, bool) and value in {0, 1}
    if isinstance(value, str):
        return value.strip().lower() in {
            "0",
            "1",
            "false",
            "true",
            "no",
            "yes",
            "off",
            "on",
            "disabled",
            "enabled",
        }
    return False


def _rule_is_safe_to_migrate(raw_rule: dict[str, Any]) -> bool:
    """Reject values whose tolerant runtime normalization changes semantics."""
    for field in _RULE_BOOLEAN_FIELDS:
        if field in raw_rule and not _known_rule_boolean(raw_rule[field]):
            return False

    is_event_rule = (
        CONF_RULE_ACTION in raw_rule
        or CONF_RULE_TRIGGER_REFERENCE in raw_rule
    )
    if is_event_rule:
        if (
            raw_rule.get(CONF_RULE_ACTION) not in RULE_ACTIONS
            or raw_rule.get(CONF_RULE_TRIGGER_REFERENCE) not in TIME_REFERENCES
            or raw_rule.get(CONF_RULE_DAY_TYPE) not in DAY_TYPES
        ):
            return False
        if (
            raw_rule[CONF_RULE_TRIGGER_REFERENCE] == TIME_REFERENCE_FIXED
            and CONF_RULE_TRIGGER not in raw_rule
        ):
            return False
        time_fields = (CONF_RULE_TRIGGER,)
        integer_fields = (
            (CONF_RULE_TRIGGER_OFFSET, -720, 720),
            (CONF_RULE_PRIORITY, 1, 100),
        )
    else:
        for field in (CONF_RULE_START_REFERENCE, CONF_RULE_END_REFERENCE):
            if field in raw_rule and raw_rule[field] not in TIME_REFERENCES:
                return False
        time_fields = (CONF_RULE_START, CONF_RULE_END)
        integer_fields = (
            (CONF_RULE_START_OFFSET, -720, 720),
            (CONF_RULE_END_OFFSET, -720, 720),
            (CONF_RULE_POSITION, 0, 100),
            (CONF_RULE_PRIORITY, 1, 100),
        )

    try:
        for field in time_fields:
            if field in raw_rule:
                parse_time(raw_rule[field])
        for field, lower, upper in integer_fields:
            if field not in raw_rule:
                continue
            raw_value = raw_rule[field]
            if isinstance(raw_value, bool):
                return False
            if isinstance(raw_value, float) and not raw_value.is_integer():
                return False
            value = int(raw_value)
            if not lower <= value <= upper:
                return False
    except (OverflowError, TypeError, ValueError):
        return False
    return True


def _normalize_rules(
    raw_rules: Any,
    *,
    scope: str,
    covers: list[str] | None = None,
    id_namespace: str | None = None,
    preserve_disabled: bool = False,
    require_explicit_covers: bool = False,
    invalid_rules: list[Any] | None = None,
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    if raw_rules is not None and not isinstance(
        raw_rules,
        (dict, list, set, str, tuple),
    ):
        if invalid_rules is not None:
            invalid_rules.append(raw_rules)
        return result
    available = set(covers or [])
    used_ids: set[str] = set()
    for source_index, raw_rule in enumerate(as_list(raw_rules), start=1):
        if not isinstance(raw_rule, dict):
            if invalid_rules is not None:
                invalid_rules.append(raw_rule)
            continue
        if not _rule_is_safe_to_migrate(raw_rule):
            if invalid_rules is not None:
                invalid_rules.append(raw_rule)
            continue
        if require_explicit_covers:
            raw_rule_covers = raw_rule.get(CONF_RULE_COVERS)
            if not isinstance(raw_rule_covers, (list, set, str, tuple)) or not any(
                isinstance(cover, str) and cover in available
                for cover in as_list(raw_rule_covers)
            ):
                if invalid_rules is not None:
                    invalid_rules.append(raw_rule)
                continue

        enabled = normalize_boolean(raw_rule.get(CONF_RULE_ENABLED), True)
        if not enabled and not preserve_disabled:
            continue

        source = dict(raw_rule)
        if id_namespace and not str(source.get(CONF_RULE_ID) or "").strip():
            source[CONF_RULE_ID] = uuid5(
                NAMESPACE_URL,
                f"{id_namespace}:{source_index}",
            ).hex

        for expanded_index, expanded in enumerate(_expand_rule(source), start=1):
            try:
                rule = normalize_rule(expanded)
            except (KeyError, TypeError, ValueError):
                if invalid_rules is not None:
                    invalid_rules.append(raw_rule)
                continue
            rule_id = str(rule.get(CONF_RULE_ID) or "").strip()
            if not rule_id or rule_id in used_ids:
                rule_id = (
                    uuid5(
                        NAMESPACE_URL,
                        f"{id_namespace}:{source_index}:{expanded_index}:{rule_id}",
                    ).hex
                    if id_namespace
                    else uuid4().hex
                )
            used_ids.add(rule_id)
            rule[CONF_RULE_ID] = rule_id
            rule[CONF_RULE_SCOPE] = scope
            if scope == RULE_SCOPE_ROOM:
                selected = [
                    cover
                    for cover in as_list(rule.get(CONF_RULE_COVERS) or covers or [])
                    if isinstance(cover, str) and cover in available
                ]
                if not selected:
                    if invalid_rules is not None:
                        invalid_rules.append(raw_rule)
                    continue
                rule[CONF_RULE_COVERS] = selected
            else:
                rule[CONF_RULE_COVERS] = []
            if not enabled and preserve_disabled:
                rule[CONF_RULE_ENABLED] = False
            result.append(rule)
    return result


def _normalized_global_position_values(
    data: dict[str, Any], options: dict[str, Any]
) -> dict[str, int]:
    """Return complete central position values, including legacy top-level data."""
    raw = _merged_value(data, options, CONF_GLOBAL_POSITION_VALUES, {})
    source = raw if isinstance(raw, dict) else {}
    result: dict[str, int] = {}
    for key, default in POSITION_DEFAULTS.items():
        legacy_value = _merged_value(data, options, key, source.get(key, default))
        try:
            value = int(legacy_value)
        except (TypeError, ValueError):
            value = int(default)
        result[key] = max(0, min(100, value))
    return result


def _normalized_global_position_overrides(
    data: dict[str, Any], options: dict[str, Any], *, preserve_legacy: bool
) -> dict[str, bool]:
    """Return per-position central override switches."""
    raw = _merged_value(data, options, CONF_GLOBAL_POSITION_OVERRIDES, {})
    source = raw if isinstance(raw, dict) else {}
    legacy_forced = {
        "wind_safe_position",
        "storm_safe_position",
        "rain_safe_position",
        "frost_safe_position",
    }
    return {
        key: normalize_boolean(
            source.get(key), preserve_legacy and key in legacy_forced
        )
        for key in POSITION_SETTING_KEYS
    }


def _central_position_values_for_migration(hass: HomeAssistant) -> dict[str, int]:
    """Return central values while global and room entries migrate independently."""
    entry = global_entry(hass)
    if entry is None:
        return dict(POSITION_DEFAULTS)
    return _normalized_global_position_values(dict(entry.data), dict(entry.options))


def _transfer_legacy_global_overrides_to_rooms(
    hass: HomeAssistant, values: dict[str, int], selected_keys: set[str]
) -> list[str]:
    """Convert former continuous overrides into independent room values."""
    if not selected_keys:
        return []
    updated_entries: list[str] = []
    for room_entry in hass.config_entries.async_entries(DOMAIN):
        if entry_type(room_entry) != ENTRY_TYPE_ROOM:
            continue
        room_options = dict(room_entry.options)
        for key in selected_keys:
            room_options[key] = int(values[key])
        if hass.config_entries.async_update_entry(room_entry, options=room_options):
            updated_entries.append(room_entry.entry_id)
    return updated_entries


def _distribute_pending_global_time_rules(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> None:
    """Retry an idempotent legacy-rule transfer without blocking entry setup.

    Home Assistant treats a failed Config Entry migration as non-recoverable for
    the rest of the running process.  A central entry therefore cannot return a
    migration failure merely because no room (or no usable room cover) exists
    yet.  Version 20 retains that legacy source privately and retries whenever
    the central entry or a room is set up.  The source is removed only after
    every existing room has an independently stored copy.
    """
    if entry_type(entry) != ENTRY_TYPE_GLOBAL:
        return
    raw_rules = _merged_value(
        dict(entry.data),
        dict(entry.options),
        CONF_GLOBAL_TIME_RULES,
        _merged_value(
            dict(entry.data),
            dict(entry.options),
            CONF_TIME_RULES,
            [],
        ),
    )
    if not as_list(raw_rules):
        return

    invalid_rules: list[Any] = []
    rules = _normalize_rules(
        raw_rules,
        scope=RULE_SCOPE_GLOBAL,
        id_namespace=f"{entry.entry_id}:global",
        preserve_disabled=True,
        invalid_rules=invalid_rules,
    )
    if invalid_rules:
        _LOGGER.error(
            "Cannot safely distribute %s invalid retained central time rule(s) "
            "from %s",
            len(invalid_rules),
            entry.title,
        )
        return

    updated_room_ids, complete = migrate_global_time_rules_to_rooms(
        hass,
        entry,
        rules,
        schedule_reload=False,
    )
    if complete:
        data = dict(entry.data)
        options = dict(entry.options)
        for key in (CONF_GLOBAL_TIME_RULES, CONF_TIME_RULES):
            data.pop(key, None)
            options.pop(key, None)
        hass.config_entries.async_update_entry(
            entry,
            data=data,
            options=options,
        )
    schedule_room_entry_reloads(hass, updated_room_ids)


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate older entries to config-entry version 20."""
    if entry.version > _ENTRY_VERSION:
        _LOGGER.error("Cannot migrate Smart Shading Control entry version %s", entry.version)
        return False
    if entry.version == _ENTRY_VERSION:
        return True

    original_version = entry.version
    data = dict(entry.data)
    options = dict(entry.options)
    data.setdefault(CONF_ENTRY_TYPE, ENTRY_TYPE_ROOM)
    kind = str(data[CONF_ENTRY_TYPE])

    # Runtime persistence is no longer configurable. Removing this legacy flag
    # must not remove either of the room's state stores.
    data.pop(CONF_PERSIST_MANUAL_OVERRIDES, None)
    options.pop(CONF_PERSIST_MANUAL_OVERRIDES, None)

    if kind == ENTRY_TYPE_GLOBAL:
        if original_version < 17:
            options.setdefault(
                CONF_GLOBAL_MANUAL_OVERRIDE_MINUTES,
                int(ROOM_DEFAULTS[CONF_MANUAL_OVERRIDE_MINUTES]),
            )

        if original_version < 13:
            north_azimuth = options.get(
                CONF_AZIMUTH_NORTH,
                data.get(CONF_AZIMUTH_NORTH, 0.0),
            )
            try:
                normalized_north = float(north_azimuth) % 360.0
            except (TypeError, ValueError):
                normalized_north = 0.0

            for key in (CONF_AZIMUTH_EAST, CONF_AZIMUTH_SOUTH, CONF_AZIMUTH_WEST):
                data.pop(key, None)
                options.pop(key, None)

            if CONF_AZIMUTH_NORTH in options:
                options[CONF_AZIMUTH_NORTH] = normalized_north
            else:
                data[CONF_AZIMUTH_NORTH] = normalized_north

        raw_global_rules = _merged_value(
            data,
            options,
            CONF_GLOBAL_TIME_RULES,
            _merged_value(data, options, CONF_TIME_RULES, []),
        )
        invalid_global_rules: list[Any] = []
        global_rules = _normalize_rules(
            raw_global_rules,
            scope=RULE_SCOPE_GLOBAL,
            id_namespace=f"{entry.entry_id}:global",
            preserve_disabled=True,
            invalid_rules=invalid_global_rules,
        )
        if invalid_global_rules:
            _LOGGER.error(
                "Cannot safely migrate %s invalid central time rule(s) from %s",
                len(invalid_global_rules),
                entry.title,
            )
            return False

        updated_room_ids: set[str] = set()
        migrated_room_ids, rules_complete = migrate_global_time_rules_to_rooms(
            hass,
            entry,
            global_rules,
            schedule_reload=False,
        )
        updated_room_ids.update(migrated_room_ids)
        if not rules_complete:
            # A failed Config Entry migration is non-recoverable during this HA
            # process. Retain the normalized source privately in v20 instead;
            # setup retries the idempotent room transfer when rooms become
            # representable. The create-only UI never exposes this source as a
            # live central rule list.
            data.pop(CONF_TIME_RULES, None)
            options.pop(CONF_TIME_RULES, None)
            data.pop(CONF_GLOBAL_TIME_RULES, None)
            options[CONF_GLOBAL_TIME_RULES] = global_rules
            _LOGGER.warning(
                "Central time rules for %s were retained because they could not "
                "yet be copied to every room",
                entry.title,
            )

        position_values = _normalized_global_position_values(data, options)
        position_overrides = _normalized_global_position_overrides(
            data,
            options,
            preserve_legacy=original_version < 14,
        )
        if original_version < 16:
            updated_room_ids.update(
                _transfer_legacy_global_overrides_to_rooms(
                    hass,
                    position_values,
                    {key for key, enabled in position_overrides.items() if enabled},
                )
            )
        for key in POSITION_SETTING_KEYS:
            data.pop(key, None)
            options.pop(key, None)
        data.pop(CONF_GLOBAL_POSITION_VALUES, None)
        data.pop(CONF_GLOBAL_POSITION_OVERRIDES, None)
        options.pop(CONF_GLOBAL_POSITION_OVERRIDES, None)
        options[CONF_GLOBAL_POSITION_VALUES] = position_values

        if rules_complete:
            # The central rule wizard is create-only. Remove its legacy source
            # only after every existing room owns an independent, retry-safe
            # copy.
            data.pop(CONF_GLOBAL_TIME_RULES, None)
            options.pop(CONF_GLOBAL_TIME_RULES, None)
            data.pop(CONF_TIME_RULES, None)
            options.pop(CONF_TIME_RULES, None)

        hass.config_entries.async_update_entry(
            entry,
            data=data,
            options=options,
            version=_ENTRY_VERSION,
            minor_version=0,
        )
        schedule_room_entry_reloads(hass, updated_room_ids)
        return True

    covers = _ordered_covers(data, options)
    raw_room_rules = _merged_value(data, options, CONF_TIME_RULES, []) or []
    had_legacy_schedules = False
    if original_version < 13:
        existing_mapping = _merged_value(data, options, CONF_COVER_CONTACTS, {})
        contact_mapping = _clean_contact_mapping(existing_mapping, covers)
        old_contacts = _legacy_contacts(data, options)
        if not contact_mapping and len(covers) == 1 and len(old_contacts) == 1:
            contact_mapping[covers[0]] = old_contacts[0]
        elif old_contacts and not contact_mapping:
            _LOGGER.error(
                "Cannot safely assign room-wide legacy contacts for %s to "
                "individual covers",
                entry.title,
            )
            return False

        for index in range(1, LEGACY_MAX_SCHEDULES + 1):
            if _merged_value(data, options, f"{LEGACY_CONF_SCHEDULE_PREFIX}{index}", None):
                had_legacy_schedules = True
            for prefix in (
                LEGACY_CONF_SCHEDULE_PREFIX,
                LEGACY_CONF_SCHEDULE_POSITION_PREFIX,
                LEGACY_CONF_SCHEDULE_PRIORITY_PREFIX,
            ):
                data.pop(f"{prefix}{index}", None)
                options.pop(f"{prefix}{index}", None)

        for key in (*_LEGACY_CONTACT_KEYS, CONF_COVER_CONTACTS, CONF_TIME_RULES):
            data.pop(key, None)
            options.pop(key, None)
        options[CONF_COVER_CONTACTS] = contact_mapping

    # Event rules already existed in public v19 room entries. Validate every
    # pre-v20 room version before certifying it as v20; the tolerant runtime
    # normalizer must not reinterpret a damaged enum as an active CLOSE rule.
    invalid_room_rules: list[Any] = []
    normalized_rules = _normalize_rules(
        raw_room_rules,
        scope=RULE_SCOPE_ROOM,
        covers=covers,
        id_namespace=f"{entry.entry_id}:room",
        preserve_disabled=True,
        require_explicit_covers=original_version >= 13,
        invalid_rules=invalid_room_rules,
    )
    if invalid_room_rules:
        _LOGGER.error(
            "Cannot safely migrate %s invalid room time rule(s) from %s",
            len(invalid_room_rules),
            entry.title,
        )
        return False
    data.pop(CONF_TIME_RULES, None)
    options[CONF_TIME_RULES] = normalized_rules

    central_positions = _central_position_values_for_migration(hass)
    for key, default in POSITION_DEFAULTS.items():
        raw_value = options.get(key, data.get(key, central_positions.get(key, default)))
        try:
            value = int(raw_value)
        except (TypeError, ValueError):
            value = int(default)
        data.pop(key, None)
        options[key] = max(0, min(100, value))
    options.setdefault(CONF_TIME_RULE_CLOSE_POSITION, 0)

    hass.config_entries.async_update_entry(
        entry,
        data=data,
        options=options,
        version=_ENTRY_VERSION,
        minor_version=0,
    )

    if had_legacy_schedules:
        _LOGGER.warning(
            "External schedule helpers are no longer used. Recreate those periods "
            "as internal room time rules"
        )
    return True


def _global_runtime_config(config: dict[str, Any]) -> dict[str, Any]:
    """Return central values consumed directly by shared runtime logic."""
    return {
        key: value
        for key, value in config.items()
        if key not in _GLOBAL_TRANSFER_ONLY_KEYS
    }


async def _async_global_updated(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Apply committed central runtime changes and then reload dependants."""
    updated_config = global_config(hass)
    runtime_data = getattr(entry, "runtime_data", None)
    if isinstance(runtime_data, SmartShadingDataCoordinator):
        coordinator = runtime_data
        previous_config = dict(coordinator.config)
    else:
        previous_config = {}
        coordinator = await async_get_or_create_coordinator(
            hass,
            entry,
            updated_config,
        )

    runtime_changed = _global_runtime_config(
        previous_config
    ) != _global_runtime_config(updated_config)
    coordinator.update_config(entry, updated_config)
    if not runtime_changed:
        return

    await coordinator.async_request_refresh()
    schedule_room_entry_reloads(
        hass,
        (
            room_entry.entry_id
            for room_entry in hass.config_entries.async_entries(DOMAIN)
            if entry_type(room_entry) == ENTRY_TYPE_ROOM
        ),
    )


def _claim_covers(hass: HomeAssistant, entry: ConfigEntry, covers: list[str]) -> None:
    """Claim configured covers so two room controllers cannot command them."""
    runtime = hass.data.setdefault(DOMAIN, {})
    owners: dict[str, str] = runtime.setdefault(_COVER_OWNERS_KEY, {})
    conflicts = {
        cover: owner
        for cover in covers
        if (owner := owners.get(cover)) is not None and owner != entry.entry_id
    }
    if conflicts:
        conflict_list = ", ".join(sorted(conflicts))
        create_issue(
            hass,
            entry.entry_id,
            "duplicate_cover_assignment",
            placeholders={"covers": conflict_list, "room": entry.title},
            severity=ir.IssueSeverity.ERROR,
            persistent=True,
        )
        raise ConfigEntryError(
            "The following covers are already controlled by another Smart Shading "
            f"Control room: {conflict_list}"
        )
    owners.update({cover: entry.entry_id for cover in covers})
    delete_issue(hass, entry.entry_id, "duplicate_cover_assignment")


def _release_covers(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Release covers owned by a room entry."""
    runtime = hass.data.get(DOMAIN)
    if not isinstance(runtime, dict):
        return
    owners = runtime.get(_COVER_OWNERS_KEY)
    if not isinstance(owners, dict):
        return
    for cover, owner in list(owners.items()):
        if owner == entry.entry_id:
            owners.pop(cover, None)


def _entry_source_entity_ids(entry: ConfigEntry) -> set[str]:
    """Return valid entity IDs referenced by one config entry."""
    data = dict(entry.data)
    data.pop(PENDING_ENTITY_RENAMES_KEY, None)
    return {
        candidate
        for payload in (data, dict(entry.options))
        for candidate in iter_config_entity_id_candidates(payload)
        if valid_entity_id(candidate)
    }


def _entry_tracked_source_entity_ids(entry: ConfigEntry) -> set[str]:
    """Return current source IDs plus pending rename-chain destinations."""
    entity_ids = _entry_source_entity_ids(entry)
    for rename in normalize_pending_entity_renames(
        entry.data.get(PENDING_ENTITY_RENAMES_KEY)
    ):
        new_entity_id = rename["new_entity_id"]
        if valid_entity_id(new_entity_id):
            entity_ids.add(new_entity_id)
    return entity_ids


def _entry_data_with_pending_entity_rename(
    entry: ConfigEntry,
    old_entity_id: str,
    new_entity_id: str,
) -> dict[str, Any]:
    """Persist a rename marker without changing live source references yet."""
    data = dict(entry.data)
    pending = normalize_pending_entity_renames(
        data.get(PENDING_ENTITY_RENAMES_KEY)
    )
    pending.append(
        {
            "old_entity_id": old_entity_id,
            "new_entity_id": new_entity_id,
        }
    )
    data[PENDING_ENTITY_RENAMES_KEY] = normalize_pending_entity_renames(pending)
    if entry_type(entry) == ENTRY_TYPE_ROOM:
        data.setdefault("_entity_rename_transaction", uuid4().hex)
    return data


async def _async_apply_pending_entity_renames(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> None:
    """Apply a staged rename after the old controller completed its unload."""
    if PENDING_ENTITY_RENAMES_KEY not in entry.data:
        return
    while True:
        renames = normalize_pending_entity_renames(
            entry.data.get(PENDING_ENTITY_RENAMES_KEY)
        )
        if entry_type(entry) == ENTRY_TYPE_ROOM:
            transaction = entry.data.get("_entity_rename_transaction")
            if not isinstance(transaction, str) or not transaction:
                # Older staged renames have no transaction identifier. Persist it
                # before touching either Store so a setup retry shares the same ID.
                transaction = uuid4().hex
                data = dict(entry.data)
                data["_entity_rename_transaction"] = transaction
                hass.config_entries.async_update_entry(entry, data=data)
            try:
                for suffix in _PERSISTENT_ROOM_STORE_SUFFIXES:
                    store = Store(
                        hass,
                        1,
                        f"{DOMAIN}.{entry.entry_id}.{suffix}",
                        atomic_writes=True,
                    )
                    stored = await async_load_persistent_store(hass, store)
                    if stored is None:
                        continue
                    if not isinstance(stored, dict):
                        raise TypeError(f"Store {store.key} has an invalid structure")
                    payload = dict(stored)
                    progress = payload.pop("_entity_rename_progress", None)
                    completed = 0
                    if (
                        isinstance(progress, dict)
                        and progress.get("transaction") == transaction
                    ):
                        completed = progress.get("completed")
                        if (
                            type(completed) is not int
                            or not 0 <= completed <= len(renames)
                        ):
                            raise ValueError(f"Store {store.key} has invalid rename progress")
                    migrated = apply_pending_entity_renames(payload, renames[completed:])
                    # The payload and checkpoint commit together. Reapplying a
                    # sequence is not safe when a later source reused an earlier
                    # source's old ID, even though an individual rename is safe.
                    migrated["_entity_rename_progress"] = {
                        "transaction": transaction,
                        "completed": len(renames),
                    }
                    if migrated != stored:
                        await store.async_save(migrated)
            except Exception as err:
                # Keep both the old live references and the marker. A later setup
                # resumes each Store at its own atomically saved checkpoint.
                raise ConfigEntryNotReady(
                    "Could not migrate persistent state after an entity registry rename"
                ) from err

        if normalize_pending_entity_renames(
            entry.data.get(PENDING_ENTITY_RENAMES_KEY)
        ) != renames:
            # A registry event may append another rename while this setup waits
            # for a Store. Resume from each Store's checkpoint before committing
            # configuration, so no newly staged rename is discarded.
            continue

        data = dict(entry.data)
        data.pop(PENDING_ENTITY_RENAMES_KEY, None)
        data.pop("_entity_rename_transaction", None)
        data = apply_pending_config_entity_renames(data, renames)
        options = apply_pending_config_entity_renames(dict(entry.options), renames)
        # Store migration can yield long enough for new options forms to open.
        # Close those drafts in the same event-loop turn as the final commit,
        # so none can restore the source IDs visible before migration finished.
        _abort_source_entity_options_flows(hass)
        hass.config_entries.async_update_entry(entry, data=data, options=options)

        return


def _abort_source_entity_options_flows(hass: HomeAssistant) -> None:
    """Discard open settings drafts which can retain source entity references."""
    options = hass.config_entries.options
    for configured_entry in hass.config_entries.async_entries(DOMAIN):
        for flow in options.async_progress_by_handler(
            configured_entry.entry_id, include_uninitialized=True
        ):
            options.async_abort(flow["flow_id"])


async def _async_handle_source_entity_rename(
    hass: HomeAssistant,
    entry: ConfigEntry,
    event: Event[er.EventEntityRegistryUpdatedData],
) -> None:
    """Migrate every reference when Home Assistant renames a source entity."""
    event_data = event.data
    old_entity_id = event_data.get("old_entity_id")
    new_entity_id = event_data.get("entity_id")
    if (
        event_data.get("action") != "update"
        or not isinstance(old_entity_id, str)
        or not isinstance(new_entity_id, str)
        or old_entity_id == new_entity_id
    ):
        return

    # Open options forms can retain old source IDs even after this entry has
    # reloaded. Central rule drafts may also refer to another room's covers.
    # End SSC drafts before migration so a later submit cannot restore stale
    # references; options flows of other integrations remain untouched.
    _abort_source_entity_options_flows(hass)

    is_global = entry_type(entry) == ENTRY_TYPE_GLOBAL
    data = _entry_data_with_pending_entity_rename(
        entry,
        old_entity_id,
        new_entity_id,
    )
    hass.config_entries.async_update_entry(entry, data=data)

    if entry.disabled_by is not None:
        # Keep references durable while disabled without starting its runtime.
        # The pending rename is applied before the next enabled setup.
        return

    if not await hass.config_entries.async_reload(entry.entry_id):
        _LOGGER.error(
            "Could not reload %s after entity registry rename %s to %s; the "
            "durable migration marker will retry on the next setup",
            entry.title,
            old_entity_id,
            new_entity_id,
        )
        return

    if is_global:
        # Central source listeners also feed every room controller. The global
        # setup has already committed the reference and refreshed its shared
        # coordinator; now rebuild all dependent room listeners.
        schedule_room_entry_reloads(
            hass,
            (
                room_entry.entry_id
                for room_entry in hass.config_entries.async_entries(DOMAIN)
                if entry_type(room_entry) == ENTRY_TYPE_ROOM
            ),
        )


async def _async_finish_source_entity_renames(
    hass: HomeAssistant,
    entry: ConfigEntry,
    source_data: dict[str, Any],
    renames: list[dict[str, str]],
) -> None:
    """Finish changes observed between a setup form commit and entry setup."""
    runtime = hass.data.setdefault(DOMAIN, {})
    locks = runtime.setdefault(_SOURCE_RENAME_LOCKS_KEY, {})
    rename_lock = locks.setdefault(entry.entry_id, asyncio.Lock())
    async with rename_lock:
        while True:
            if not any(
                candidate.entry_id == entry.entry_id
                for candidate in hass.config_entries.async_entries(DOMAIN)
            ):
                return
            sequence = normalize_pending_entity_renames(renames)
            current = apply_pending_config_entity_renames(
                dict(entry.data), entry.data.get(PENDING_ENTITY_RENAMES_KEY)
            )
            current.pop(PENDING_ENTITY_RENAMES_KEY, None)
            current.pop("_entity_rename_transaction", None)
            expected = dict(source_data)
            completed = 0 if current == expected else None
            for index, rename in enumerate(sequence, start=1):
                expected = apply_pending_config_entity_renames(expected, [rename])
                if current == expected:
                    completed = index
            if completed is None:
                _LOGGER.warning(
                    "Source settings for %s changed during setup; retaining the "
                    "current configuration instead of replaying an older draft",
                    entry.title,
                )
                return
            if completed == len(sequence):
                return
            # Use the longest matching prefix: A -> B -> A may already have
            # completed, and must not be replayed just because A appears again.
            rename = sequence[completed]
            await _async_handle_source_entity_rename(
                hass,
                entry,
                Event(
                    er.EVENT_ENTITY_REGISTRY_UPDATED,
                    {"action": "update", "old_entity_id": rename["old_entity_id"],
                     "entity_id": rename["new_entity_id"]},
                ),
            )


def _register_source_entity_rename_listener(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> Callable[[], None] | None:
    """Track source renames for the Config Entry's complete registered lifetime."""
    entity_ids = _entry_tracked_source_entity_ids(entry)
    if not entity_ids:
        return None

    runtime = hass.data.setdefault(DOMAIN, {})
    unsubscribers = runtime.setdefault(_SOURCE_RENAME_UNSUBSCRIBERS_KEY, {})
    if not isinstance(unsubscribers, dict):
        unsubscribers = {}
        runtime[_SOURCE_RENAME_UNSUBSCRIBERS_KEY] = unsubscribers
    existing = unsubscribers.get(entry.entry_id)
    if callable(existing):
        return existing

    locks = runtime.setdefault(_SOURCE_RENAME_LOCKS_KEY, {})
    if not isinstance(locks, dict):
        locks = {}
        runtime[_SOURCE_RENAME_LOCKS_KEY] = locks
    rename_lock = locks.setdefault(entry.entry_id, asyncio.Lock())

    async def async_registry_updated(
        event: Event[er.EventEntityRegistryUpdatedData],
    ) -> None:
        async with rename_lock:
            # A callback queued before removal may acquire the lock afterwards.
            # Do not resurrect a Config Entry which is no longer registered.
            if not any(
                candidate.entry_id == entry.entry_id
                for candidate in hass.config_entries.async_entries(DOMAIN)
            ):
                return
            old_entity_id = event.data.get("old_entity_id")
            if (
                not isinstance(old_entity_id, str)
                or old_entity_id not in _entry_tracked_source_entity_ids(entry)
            ):
                return
            await _async_handle_source_entity_rename(hass, entry, event)

    remove_listener = hass.bus.async_listen(
        er.EVENT_ENTITY_REGISTRY_UPDATED,
        async_registry_updated,
    )
    removed = False

    def remove() -> None:
        nonlocal removed
        if removed:
            return
        removed = True
        remove_listener()
        current_runtime = hass.data.get(DOMAIN)
        current_unsubscribers = (
            current_runtime.get(_SOURCE_RENAME_UNSUBSCRIBERS_KEY)
            if isinstance(current_runtime, dict)
            else None
        )
        if (
            isinstance(current_unsubscribers, dict)
            and current_unsubscribers.get(entry.entry_id) is remove
        ):
            current_unsubscribers.pop(entry.entry_id, None)
            if not current_unsubscribers:
                current_runtime.pop(_SOURCE_RENAME_UNSUBSCRIBERS_KEY, None)

    unsubscribers[entry.entry_id] = remove
    # A rename can arrive while platforms or persistent Stores are reloading.
    # Keep this lightweight listener until entry removal, otherwise a second
    # rename during that gap permanently loses the source association.
    return remove


def _remove_source_entity_rename_listener(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> None:
    """Remove one entry listener even when Core could not finish its unload."""
    runtime = hass.data.get(DOMAIN)
    if not isinstance(runtime, dict):
        return
    unsubscribers = runtime.get(_SOURCE_RENAME_UNSUBSCRIBERS_KEY)
    remove = (
        unsubscribers.get(entry.entry_id)
        if isinstance(unsubscribers, dict)
        else None
    )
    if callable(remove):
        remove()
    locks = runtime.get(_SOURCE_RENAME_LOCKS_KEY)
    if isinstance(locks, dict):
        locks.pop(entry.entry_id, None)
        if not locks:
            runtime.pop(_SOURCE_RENAME_LOCKS_KEY, None)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up central settings or one smart shading room."""
    _register_source_entity_rename_listener(hass, entry)
    await _async_apply_pending_entity_renames(hass, entry)
    if entry_type(entry) == ENTRY_TYPE_GLOBAL:
        _distribute_pending_global_time_rules(hass, entry)
        runtime = hass.data.get(DOMAIN)
        previous_coordinator = (
            runtime.get(COORDINATOR_KEY) if isinstance(runtime, dict) else None
        )
        is_reattaching = (
            isinstance(previous_coordinator, SmartShadingDataCoordinator)
            and previous_coordinator.entry is None
        )
        coordinator = await async_get_or_create_coordinator(
            hass, entry, global_config(hass)
        )
        entry.runtime_data = coordinator
        entry.async_on_unload(entry.add_update_listener(_async_global_updated))
        _register_source_entity_rename_listener(hass, entry)

        # A DataUpdateCoordinator refresh interval runs only while it has at
        # least one listener. Keep central Repairs and provider health current
        # even when the building currently has no room entries.
        entry.async_on_unload(coordinator.async_add_listener(lambda: None))
        if hass.state is not CoreState.running:

            async def _async_global_started(_event: Event) -> None:
                await coordinator.async_ensure_ready()

            entry.async_on_unload(
                hass.bus.async_listen_once(
                    EVENT_HOMEASSISTANT_STARTED,
                    _async_global_started,
                )
            )
        if is_reattaching:
            schedule_room_entry_reloads(
                hass,
                (
                    room_entry.entry_id
                    for room_entry in hass.config_entries.async_entries(DOMAIN)
                    if entry_type(room_entry) == ENTRY_TYPE_ROOM
                ),
            )
        return True

    if (central_entry := global_entry(hass)) is not None:
        _distribute_pending_global_time_rules(hass, central_entry)

    configured_covers = _configured_covers(dict(entry.data), dict(entry.options))
    if len(configured_covers) != len(set(configured_covers)):
        raise ConfigEntryError(
            "A cover is assigned to more than one facade in this room"
        )

    await async_get_or_create_coordinator(
        hass, global_entry(hass), global_config(hass)
    )
    controller = SmartShadingController(hass, entry)
    try:
        # Constructing a controller also acquires its per-entry command queue.
        # Keep the claim inside the guarded section so a duplicate-cover setup
        # error cannot leave that otherwise empty queue behind.
        _claim_covers(hass, entry, controller.all_covers)
        entry.runtime_data = controller
        # Persistent enable, mode, time-rule and per-cover manual state must be
        # loaded before RestoreEntity callbacks are added and before the first
        # forced evaluation is allowed to move a cover.
        await controller.async_prepare()
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
        await controller.async_start()
        _register_source_entity_rename_listener(hass, entry)
    except (Exception, asyncio.CancelledError):
        try:
            await controller.async_stop()
        except Exception:
            _LOGGER.exception("Could not stop a partially started room controller")
        _release_covers(hass, entry)
        try:
            await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
        except Exception:
            _LOGGER.exception("Could not unload partially set up room platforms")
        # The queue is owned exclusively by this room entry. A failed setup
        # must remove it so no orphan worker or stale queued command survives a
        # later retry. Queues of all other rooms remain untouched.
        await async_shutdown_command_queue(hass, entry.entry_id)
        raise
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload central settings or one room."""
    if entry_type(entry) == ENTRY_TYPE_GLOBAL:
        if entry.disabled_by is not None:
            runtime = hass.data.get(DOMAIN)
            coordinator = (
                runtime.get(COORDINATOR_KEY) if isinstance(runtime, dict) else None
            )
            if isinstance(coordinator, SmartShadingDataCoordinator):
                coordinator.update_config(None, {})
            schedule_room_entry_reloads(
                hass,
                (
                    room_entry.entry_id
                    for room_entry in hass.config_entries.async_entries(DOMAIN)
                    if entry_type(room_entry) == ENTRY_TYPE_ROOM
                ),
            )
        return True
    controller: SmartShadingController = entry.runtime_data
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        try:
            await controller.async_stop()
        finally:
            # Platforms are already gone. Even a shutdown/storage failure
            # must release this room's worker and cover ownership so a later
            # reload cannot inherit an orphan command queue.
            try:
                await async_shutdown_command_queue(hass, entry.entry_id)
            finally:
                _release_covers(hass, entry)
    return unload_ok


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Clean entry-owned state and refresh dependants after removal."""
    _remove_source_entity_rename_listener(hass, entry)
    if entry_type(entry) == ENTRY_TYPE_ROOM:
        controller = getattr(entry, "runtime_data", None)
        if isinstance(controller, SmartShadingController):
            try:
                # Core still invokes the removal callback after a failed
                # platform unload. Explicitly stop the surviving controller so
                # its timers, tasks and state listeners cannot outlive the
                # deleted entry or recreate its removed Stores.
                await controller.async_stop()
            except Exception:
                _LOGGER.exception("Could not stop removed room controller")
        _release_covers(hass, entry)
        # Removal normally follows a successful unload. This additional
        # per-entry cleanup also covers disabled, failed, or partially set-up
        # entries without touching queues owned by another room.
        await async_shutdown_command_queue(hass, entry.entry_id)
        await Store(
            hass, 1, f"{DOMAIN}.{entry.entry_id}.manual_overrides"
        ).async_remove()
        await Store(
            hass, 1, f"{DOMAIN}.{entry.entry_id}.control_state"
        ).async_remove()
        delete_entry_issues(hass, entry.entry_id)

        # The removed entry is already absent from ConfigEntries at this point.
        # Re-evaluate central Repairs immediately; otherwise deleting the last
        # Workday/sun-event rule can leave its former issue stale indefinitely
        # when no room remains to drive the shared coordinator.
        central_entry = global_entry(hass)
        if central_entry is not None:
            runtime = hass.data.get(DOMAIN)
            coordinator = (
                runtime.get(COORDINATOR_KEY) if isinstance(runtime, dict) else None
            )
            forecast_error = (
                str((coordinator.data or {}).get("last_error") or "") or None
                if isinstance(coordinator, SmartShadingDataCoordinator)
                else None
            )
            update_global_repairs(
                hass,
                central_entry,
                global_config(hass),
                forecast_error=forecast_error,
            )
        return

    # Stop all shared work from referring to a removed central Config Entry
    # before deleting its issues or scheduling room reloads. A room evaluation
    # racing this callback can then no longer recreate issues owned by it.
    runtime = hass.data.get(DOMAIN)
    coordinator = runtime.get(COORDINATOR_KEY) if isinstance(runtime, dict) else None
    if isinstance(coordinator, SmartShadingDataCoordinator):
        coordinator.update_config(None, {})
    delete_entry_issues(hass, entry.entry_id)
    schedule_room_entry_reloads(
        hass,
        (
            room_entry.entry_id
            for room_entry in hass.config_entries.async_entries(DOMAIN)
            if entry_type(room_entry) == ENTRY_TYPE_ROOM
        ),
    )
