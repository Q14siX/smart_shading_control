"""Smart Shading Control integration."""

from __future__ import annotations

import logging
from typing import Any
from uuid import uuid4

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryError
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.storage import Store

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
    CONF_GLOBAL_TIME_RULES,
    CONF_GLOBAL_POSITION_VALUES,
    CONF_GLOBAL_MANUAL_OVERRIDE_MINUTES,
    CONF_GLOBAL_POSITION_OVERRIDES,
    CONF_OPENING_CONTACTS,
    CONF_TIME_RULE_CLOSE_POSITION,
    CONF_MANUAL_OVERRIDE_MINUTES,
    CONF_PERSIST_MANUAL_OVERRIDES,
    CONF_RULE_ACTION,
    CONF_RULE_COVERS,
    CONF_RULE_ENABLED,
    CONF_RULE_END,
    CONF_RULE_END_OFFSET,
    CONF_RULE_END_REFERENCE,
    CONF_RULE_FRIDAY,
    CONF_RULE_ID,
    CONF_RULE_MONDAY,
    CONF_RULE_NAME,
    CONF_RULE_POSITION,
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
    CONF_TIME_RULES,
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
    RULE_SCOPE_GLOBAL,
    RULE_SCOPE_ROOM,
    TIME_REFERENCE_FIXED,
    TIME_REFERENCE_SUNRISE,
    TIME_REFERENCE_SUNSET,
)
from .controller import SmartShadingController
from .command_queue import async_shutdown_command_queue
from .coordinator import async_get_or_create_coordinator
from .issues import create_issue, delete_entry_issues, delete_issue
from .logic import as_list
from .schedule import normalize_boolean, normalize_rule, parse_time

_LOGGER = logging.getLogger(__name__)

_ENTRY_VERSION = 19
_COVER_OWNERS_KEY = "cover_owners"
_COVER_KEYS = (
    CONF_COVERS_NORTH,
    CONF_COVERS_EAST,
    CONF_COVERS_SOUTH,
    CONF_COVERS_WEST,
)
_LEGACY_CONTACT_KEYS = (
    CONF_OPENING_CONTACTS,
    LEGACY_CONF_OPEN_WINDOW_SENSORS,
    LEGACY_CONF_TILTED_WINDOW_SENSORS,
    LEGACY_CONF_DOOR_SENSORS,
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


def _normalize_rules(
    raw_rules: Any,
    *,
    scope: str,
    covers: list[str] | None = None,
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    available = set(covers or [])
    used_ids: set[str] = set()
    for raw_rule in as_list(raw_rules):
        if not isinstance(raw_rule, dict) or not normalize_boolean(
            raw_rule.get(CONF_RULE_ENABLED), True
        ):
            continue
        for expanded in _expand_rule(raw_rule):
            try:
                rule = normalize_rule(expanded)
            except (TypeError, ValueError):
                continue
            rule_id = str(rule.get(CONF_RULE_ID) or "").strip()
            if not rule_id or rule_id in used_ids:
                rule_id = uuid4().hex
            used_ids.add(rule_id)
            rule[CONF_RULE_ID] = rule_id
            rule[CONF_RULE_SCOPE] = scope
            if scope == RULE_SCOPE_ROOM:
                selected = [
                    cover
                    for cover in as_list(rule.get(CONF_RULE_COVERS) or covers or [])
                    if cover in available
                ]
                if not selected:
                    continue
                rule[CONF_RULE_COVERS] = selected
            else:
                rule[CONF_RULE_COVERS] = []
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
) -> None:
    """Convert former continuous overrides into independent room values."""
    if not selected_keys:
        return
    for room_entry in hass.config_entries.async_entries(DOMAIN):
        if entry_type(room_entry) != ENTRY_TYPE_ROOM:
            continue
        room_options = dict(room_entry.options)
        for key in selected_keys:
            room_options[key] = int(values[key])
        hass.config_entries.async_update_entry(room_entry, options=room_options)
        if room_entry.state.recoverable:
            hass.config_entries.async_schedule_reload(room_entry.entry_id)


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate older entries to config-entry version 19."""
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

    # Version 13 restored optional persistence after version 12 removed it.
    if kind == ENTRY_TYPE_ROOM and original_version <= 12:
        default_persist = False if original_version == 12 else True
        persist_value = options.get(
            CONF_PERSIST_MANUAL_OVERRIDES,
            data.get(CONF_PERSIST_MANUAL_OVERRIDES, default_persist),
        )
        data.pop(CONF_PERSIST_MANUAL_OVERRIDES, None)
        options[CONF_PERSIST_MANUAL_OVERRIDES] = normalize_boolean(
            persist_value, default_persist
        )

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
            global_rules = _normalize_rules(
                raw_global_rules,
                scope=RULE_SCOPE_GLOBAL,
            )
            data.pop(CONF_TIME_RULES, None)
            options.pop(CONF_TIME_RULES, None)
            data.pop(CONF_GLOBAL_TIME_RULES, None)
            options.pop(CONF_GLOBAL_TIME_RULES, None)
            options[CONF_GLOBAL_TIME_RULES] = global_rules

        position_values = _normalized_global_position_values(data, options)
        position_overrides = _normalized_global_position_overrides(
            data,
            options,
            preserve_legacy=original_version < 14,
        )
        if original_version < 16:
            _transfer_legacy_global_overrides_to_rooms(
                hass,
                position_values,
                {key for key, enabled in position_overrides.items() if enabled},
            )
        for key in POSITION_SETTING_KEYS:
            data.pop(key, None)
            options.pop(key, None)
        data.pop(CONF_GLOBAL_POSITION_VALUES, None)
        data.pop(CONF_GLOBAL_POSITION_OVERRIDES, None)
        options.pop(CONF_GLOBAL_POSITION_OVERRIDES, None)
        options[CONF_GLOBAL_POSITION_VALUES] = position_values

        if original_version < 19:
            # Version 19 turns the global rule UI into a create-only distributor.
            # No time rule is retained in the central Config Entry.
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
        return True

    covers = _ordered_covers(data, options)
    had_legacy_schedules = False
    if original_version < 13:
        existing_mapping = _merged_value(data, options, CONF_COVER_CONTACTS, {})
        contact_mapping = _clean_contact_mapping(existing_mapping, covers)
        old_contacts = _legacy_contacts(data, options)
        if not contact_mapping and len(covers) == 1 and len(old_contacts) == 1:
            contact_mapping[covers[0]] = old_contacts[0]
        elif old_contacts and not contact_mapping:
            _LOGGER.warning(
                "Legacy room-wide contacts for %s could not be assigned safely. "
                "Assign an optional contact to each cover in the room options",
                entry.title,
            )

        raw_rules = _merged_value(data, options, CONF_TIME_RULES, []) or []
        normalized_rules = _normalize_rules(
            raw_rules,
            scope=RULE_SCOPE_ROOM,
            covers=covers,
        )

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
        options[CONF_TIME_RULES] = normalized_rules

    if original_version < 19:
        # The new create-only global workflow deliberately starts from a clean
        # schedule state. Remove every existing room rule regardless of whether
        # it originated globally, locally or from a legacy schedule helper.
        data.pop(CONF_TIME_RULES, None)
        options[CONF_TIME_RULES] = []

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

    if original_version < 15:
        # Earlier detector versions could mistake provider synchronization for
        # a user action. Remove the old runtime markers once so a false override
        # is not carried into the corrected detector, even when persistence is
        # enabled for this room.
        try:
            await Store(
                hass, 1, f"{DOMAIN}.{entry.entry_id}.manual_overrides"
            ).async_save({})
        except Exception:  # noqa: BLE001 - stale state must not block migration
            _LOGGER.debug("Could not clear legacy manual overrides", exc_info=True)
        control_store = Store(
            hass, 1, f"{DOMAIN}.{entry.entry_id}.control_state"
        )
        try:
            control_state = await control_store.async_load()
        except Exception:  # noqa: BLE001 - migration must remain recoverable
            control_state = None
        if isinstance(control_state, dict) and control_state.get(
            "time_rule_manual_releases"
        ):
            control_state = dict(control_state)
            control_state["time_rule_manual_releases"] = []
            try:
                await control_store.async_save(control_state)
            except Exception:  # noqa: BLE001 - stale state must not block migration
                _LOGGER.debug(
                    "Could not clear legacy manual night-rule releases",
                    exc_info=True,
                )

    if original_version < 19:
        # Remove all persisted execution markers and deferred commands belonging
        # to deleted time rules. Preserve unrelated room mode and enable state.
        control_store = Store(
            hass, 1, f"{DOMAIN}.{entry.entry_id}.control_state"
        )
        try:
            control_state = await control_store.async_load()
        except Exception:  # noqa: BLE001 - stale state must not block migration
            control_state = None
        if isinstance(control_state, dict):
            control_state = dict(control_state)
            control_state.update(
                {
                    "last_time_rule_check": None,
                    "time_rule_manual_releases": [],
                    "executed_time_rule_occurrences": [],
                    "pending_time_rule_opens": {},
                    "pending_time_rule_closes": [],
                    "pending_time_rule_close_ready_at": {},
                }
            )
            try:
                await control_store.async_save(control_state)
            except Exception:  # noqa: BLE001 - stale state must not block migration
                _LOGGER.debug(
                    "Could not clear time-rule runtime state during migration",
                    exc_info=True,
                )

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


async def _async_global_updated(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Refresh shared coordinator data after central changes."""
    coordinator = await async_get_or_create_coordinator(
        hass, entry, global_config(hass)
    )
    coordinator.update_config(entry, global_config(hass))
    await coordinator.async_request_refresh()


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


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up central settings or one smart shading room."""
    if entry_type(entry) == ENTRY_TYPE_GLOBAL:
        coordinator = await async_get_or_create_coordinator(
            hass, entry, global_config(hass)
        )
        entry.runtime_data = coordinator
        entry.async_on_unload(entry.add_update_listener(_async_global_updated))
        return True

    configured_covers = _configured_covers(dict(entry.data), dict(entry.options))
    if len(configured_covers) != len(set(configured_covers)):
        raise ConfigEntryError(
            "A cover is assigned to more than one facade in this room"
        )

    await async_get_or_create_coordinator(
        hass, global_entry(hass), global_config(hass)
    )
    controller = SmartShadingController(hass, entry)
    _claim_covers(hass, entry, controller.all_covers)
    entry.runtime_data = controller
    try:
        # Persistent enable, mode and time-rule state must be loaded before
        # RestoreEntity callbacks are added. Transient manual state is cleared
        # before the first forced evaluation can move a cover.
        await controller.async_prepare()
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
        await controller.async_start()
    except Exception:
        try:
            await controller.async_stop()
        except Exception:  # noqa: BLE001 - preserve the original setup error
            _LOGGER.exception("Could not stop a partially started room controller")
        _release_covers(hass, entry)
        try:
            await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
        except Exception:  # noqa: BLE001 - preserve the original setup error
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
        return True
    controller: SmartShadingController = entry.runtime_data
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        await controller.async_stop()
        await async_shutdown_command_queue(hass, entry.entry_id)
        _release_covers(hass, entry)
    return unload_ok


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Clean entry-owned state and refresh dependants after removal."""
    delete_entry_issues(hass, entry.entry_id)
    if entry_type(entry) == ENTRY_TYPE_ROOM:
        _release_covers(hass, entry)
        await Store(
            hass, 1, f"{DOMAIN}.{entry.entry_id}.manual_overrides"
        ).async_remove()
        await Store(
            hass, 1, f"{DOMAIN}.{entry.entry_id}.control_state"
        ).async_remove()
        return

    for room_entry in hass.config_entries.async_entries(DOMAIN):
        if entry_type(room_entry) == ENTRY_TYPE_ROOM and room_entry.state.recoverable:
            hass.config_entries.async_schedule_reload(room_entry.entry_id)
