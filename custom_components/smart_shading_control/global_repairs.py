"""Central Repairs management for integration-wide settings."""

from __future__ import annotations

from collections.abc import Iterable
import math
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    ATTR_UNIT_OF_MEASUREMENT,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant, State
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from homeassistant.util import dt as dt_util
from homeassistant.util.unit_conversion import TemperatureConverter

from .const import (
    CONF_COVER_CONTACTS,
    CONF_COVERS_EAST,
    CONF_COVERS_NORTH,
    CONF_COVERS_SOUTH,
    CONF_COVERS_WEST,
    CONF_ENTRY_TYPE,
    CONF_GLOBAL_TIME_RULES,
    CONF_ILLUMINANCE_SENSOR,
    CONF_IRRADIANCE_SENSOR,
    CONF_OUTSIDE_TEMP_SENSOR,
    CONF_RAIN_SENSOR,
    CONF_ROOM_TEMP_SENSOR,
    CONF_RULE_DAY_TYPE,
    CONF_RULE_ENABLED,
    CONF_RULE_TRIGGER_REFERENCE,
    CONF_SUN_ENTITY,
    CONF_SUN_EVENT_SOURCE,
    CONF_TIME_RULES,
    CONF_WEATHER_ENTITY,
    CONF_WIND_SENSOR,
    CONF_WORKDAY_ENTITY,
    DAY_TYPE_ANY,
    DOMAIN,
    ENTRY_TYPE_GLOBAL,
    SUN_EVENT_SOURCE_ENTITY,
    TIME_REFERENCE_SUNRISE,
    TIME_REFERENCE_SUNSET,
)
from .logic import as_list
from .schedule import normalize_boolean
from .issues import create_issue, delete_issue, delete_stale_entity_issues
from .units import normalize_illuminance, normalize_irradiance, normalize_wind_speed

_GLOBAL_ENTITY_KEYS = (
    CONF_SUN_ENTITY,
    CONF_WEATHER_ENTITY,
    CONF_WORKDAY_ENTITY,
    CONF_OUTSIDE_TEMP_SENSOR,
    CONF_IRRADIANCE_SENSOR,
    CONF_ILLUMINANCE_SENSOR,
    CONF_WIND_SENSOR,
    CONF_RAIN_SENSOR,
)

# These issue kinds were previously emitted independently by every room.
_LEGACY_GLOBAL_ONLY_KINDS = {
    "weather_forecast_unavailable",
    "invalid_irradiance_unit",
    "invalid_illuminance_unit",
    "invalid_wind_unit",
    "workday_configuration_missing",
    "workday_unavailable",
    "sun_event_unavailable",
}
_LEGACY_CONDITIONAL_KINDS = {"missing_entity", "invalid_temperature_unit"}
_LEGACY_CLEANUP_KEY = "global_repairs_legacy_cleanup_done"


def _entry_type(entry: ConfigEntry) -> str:
    return str(entry.data.get(CONF_ENTRY_TYPE) or "room")


def _merged(entry: ConfigEntry) -> dict[str, Any]:
    result = dict(entry.data)
    result.update(entry.options)
    return result


def _configured_entity_ids(config: dict[str, Any]) -> set[str]:
    return {
        str(config[key])
        for key in _GLOBAL_ENTITY_KEYS
        if config.get(key) not in (None, "")
    }


def _iter_rules(hass: HomeAssistant) -> Iterable[dict[str, Any]]:
    for entry in hass.config_entries.async_entries(DOMAIN):
        current = _merged(entry)
        for key in (CONF_TIME_RULES, CONF_GLOBAL_TIME_RULES):
            for raw_rule in as_list(current.get(key)):
                if not isinstance(raw_rule, dict):
                    continue
                if not normalize_boolean(raw_rule.get(CONF_RULE_ENABLED), True):
                    continue
                yield raw_rule


def _workday_rules_exist(hass: HomeAssistant) -> bool:
    return any(
        str(rule.get(CONF_RULE_DAY_TYPE) or DAY_TYPE_ANY) != DAY_TYPE_ANY
        for rule in _iter_rules(hass)
    )


def _required_sun_events(hass: HomeAssistant) -> set[str]:
    required: set[str] = set()
    for rule in _iter_rules(hass):
        reference = str(rule.get(CONF_RULE_TRIGGER_REFERENCE) or "")
        if reference == TIME_REFERENCE_SUNRISE:
            required.add("next_rising")
        elif reference == TIME_REFERENCE_SUNSET:
            required.add("next_setting")
    return required


def _state_available(state: State | None) -> bool:
    return state is not None and state.state not in {STATE_UNKNOWN, STATE_UNAVAILABLE}


def _temperature_to_celsius(value: Any, unit: Any) -> float | None:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(numeric):
        return None
    if unit in (None, "", UnitOfTemperature.CELSIUS):
        return numeric
    try:
        return float(
            TemperatureConverter.convert(
                numeric,
                str(unit),
                UnitOfTemperature.CELSIUS,
            )
        )
    except (HomeAssistantError, TypeError, ValueError):
        return None


def _validate_temperature_entity(
    hass: HomeAssistant,
    owner_entry_id: str,
    entity_id: str,
    *,
    weather_attribute: bool = False,
) -> None:
    state = hass.states.get(entity_id)
    if not _state_available(state):
        delete_issue(hass, owner_entry_id, "invalid_temperature_unit", entity_id)
        return
    assert state is not None
    if weather_attribute:
        raw_value = state.attributes.get("temperature")
        unit = state.attributes.get("temperature_unit")
    else:
        raw_value = state.state
        unit = state.attributes.get(ATTR_UNIT_OF_MEASUREMENT)
    if raw_value is None:
        delete_issue(hass, owner_entry_id, "invalid_temperature_unit", entity_id)
        return
    if _temperature_to_celsius(raw_value, unit) is None:
        create_issue(
            hass,
            owner_entry_id,
            "invalid_temperature_unit",
            entity_id=entity_id,
            placeholders={"entity": entity_id, "unit": str(unit or "-")},
            severity=ir.IssueSeverity.WARNING,
        )
    else:
        delete_issue(hass, owner_entry_id, "invalid_temperature_unit", entity_id)


def _validate_numeric_unit(
    hass: HomeAssistant,
    owner_entry_id: str,
    entity_id: str | None,
    kind: str,
    normalizer: Any,
) -> None:
    if not entity_id:
        return
    state = hass.states.get(entity_id)
    if not _state_available(state):
        delete_issue(hass, owner_entry_id, kind, entity_id)
        return
    assert state is not None
    unit = state.attributes.get(ATTR_UNIT_OF_MEASUREMENT)
    if normalizer(state.state, unit) is None:
        create_issue(
            hass,
            owner_entry_id,
            kind,
            entity_id=entity_id,
            placeholders={"entity": entity_id, "unit": str(unit or "-")},
            severity=ir.IssueSeverity.WARNING,
        )
    else:
        delete_issue(hass, owner_entry_id, kind, entity_id)


def _validate_wind_unit(
    hass: HomeAssistant,
    owner_entry_id: str,
    config: dict[str, Any],
) -> None:
    sensor = config.get(CONF_WIND_SENSOR)
    if sensor:
        _validate_numeric_unit(
            hass,
            owner_entry_id,
            str(sensor),
            "invalid_wind_unit",
            normalize_wind_speed,
        )
        weather = config.get(CONF_WEATHER_ENTITY)
        if weather:
            delete_issue(hass, owner_entry_id, "invalid_wind_unit", str(weather))
        return

    weather = config.get(CONF_WEATHER_ENTITY)
    if not weather:
        return
    entity_id = str(weather)
    state = hass.states.get(entity_id)
    if not _state_available(state):
        delete_issue(hass, owner_entry_id, "invalid_wind_unit", entity_id)
        return
    assert state is not None
    raw_value = state.attributes.get("wind_speed")
    raw_unit = state.attributes.get("wind_speed_unit")
    if raw_value is None or normalize_wind_speed(raw_value, raw_unit) is not None:
        delete_issue(hass, owner_entry_id, "invalid_wind_unit", entity_id)
        return
    create_issue(
        hass,
        owner_entry_id,
        "invalid_wind_unit",
        entity_id=entity_id,
        placeholders={"entity": entity_id, "unit": str(raw_unit or "-")},
        severity=ir.IssueSeverity.WARNING,
    )


def _translation_key(issue: Any, issue_id: str) -> str:
    value = str(getattr(issue, "translation_key", "") or "")
    if value:
        return value
    for candidate in (*_LEGACY_GLOBAL_ONLY_KINDS, *_LEGACY_CONDITIONAL_KINDS):
        if issue_id.startswith(f"{candidate}_"):
            return candidate
    return ""


def _room_owned_entities(hass: HomeAssistant) -> dict[str, set[str]]:
    """Return entities that legitimately belong to each room entry."""
    result: dict[str, set[str]] = {}
    for entry in hass.config_entries.async_entries(DOMAIN):
        if _entry_type(entry) == ENTRY_TYPE_GLOBAL:
            continue
        current = _merged(entry)
        entities: set[str] = set()
        for key in (
            CONF_COVERS_NORTH,
            CONF_COVERS_EAST,
            CONF_COVERS_SOUTH,
            CONF_COVERS_WEST,
        ):
            entities.update(
                str(value) for value in as_list(current.get(key)) if value
            )
        room_temperature = current.get(CONF_ROOM_TEMP_SENSOR)
        if room_temperature:
            entities.add(str(room_temperature))
        mapping = current.get(CONF_COVER_CONTACTS) or {}
        if isinstance(mapping, dict):
            entities.update(str(value) for value in mapping.values() if value)
        result[entry.entry_id] = entities
    return result


def cleanup_legacy_room_global_issues(
    hass: HomeAssistant,
    global_entry: ConfigEntry,
    config: dict[str, Any],
) -> None:
    """Remove duplicated global issues created by older room controllers."""
    runtime = hass.data.setdefault(DOMAIN, {})
    if runtime.get(_LEGACY_CLEANUP_KEY):
        return
    runtime[_LEGACY_CLEANUP_KEY] = True

    global_entities = _configured_entity_ids(config)
    room_entities = _room_owned_entities(hass)
    registry = ir.async_get(hass)
    for (domain, issue_id), issue in list(registry.issues.items()):
        if domain != DOMAIN or not isinstance(issue.data, dict):
            continue
        old_owner = str(issue.data.get("entry_id") or "")
        if not old_owner or old_owner == global_entry.entry_id:
            continue
        kind = _translation_key(issue, issue_id)
        entity_id = str(issue.data.get("entity_id") or "")
        if kind in _LEGACY_GLOBAL_ONLY_KINDS or (
            kind in _LEGACY_CONDITIONAL_KINDS
            and (
                entity_id in global_entities
                or entity_id not in room_entities.get(old_owner, set())
            )
        ):
            ir.async_delete_issue(hass, DOMAIN, issue_id)


def update_global_repairs(
    hass: HomeAssistant,
    global_entry: ConfigEntry | None,
    config: dict[str, Any],
    *,
    forecast_error: str | None = None,
) -> None:
    """Create exactly one Repairs issue for each central configuration problem."""
    if global_entry is None or _entry_type(global_entry) != ENTRY_TYPE_GLOBAL:
        return

    owner = global_entry.entry_id
    cleanup_legacy_room_global_issues(hass, global_entry, config)
    configured_entities = _configured_entity_ids(config)
    delete_stale_entity_issues(hass, owner, configured_entities)

    entity_registry = er.async_get(hass)
    for entity_id in configured_entities:
        state = hass.states.get(entity_id)
        registry_entry = entity_registry.async_get(entity_id)
        # During startup an entity can already be registered while its state is
        # not available yet. Only report a configuration error when Home
        # Assistant knows neither a state nor an entity-registry entry.
        if state is None and registry_entry is None:
            create_issue(
                hass,
                owner,
                "global_missing_entity",
                entity_id=entity_id,
                placeholders={"entity": entity_id},
                severity=ir.IssueSeverity.ERROR,
            )
        else:
            delete_issue(hass, owner, "global_missing_entity", entity_id)

    weather = str(config.get(CONF_WEATHER_ENTITY) or "")
    weather_state = hass.states.get(weather) if weather else None
    if weather and weather_state is not None and forecast_error:
        create_issue(
            hass,
            owner,
            "weather_forecast_unavailable",
            entity_id=weather,
            placeholders={"entity": weather},
            severity=ir.IssueSeverity.WARNING,
        )
    elif weather:
        delete_issue(hass, owner, "weather_forecast_unavailable", weather)

    workday = str(config.get(CONF_WORKDAY_ENTITY) or "")
    needs_workday = _workday_rules_exist(hass)
    if needs_workday and not workday:
        create_issue(
            hass,
            owner,
            "workday_configuration_missing",
            severity=ir.IssueSeverity.ERROR,
            persistent=True,
        )
    else:
        delete_issue(hass, owner, "workday_configuration_missing")

    if workday:
        state = hass.states.get(workday)
        if state is None:
            delete_issue(hass, owner, "workday_unavailable", workday)
        elif not _state_available(state):
            create_issue(
                hass,
                owner,
                "workday_unavailable",
                entity_id=workday,
                placeholders={"entity": workday},
                severity=ir.IssueSeverity.WARNING,
            )
        else:
            delete_issue(hass, owner, "workday_unavailable", workday)

    sun_entity = str(config.get(CONF_SUN_ENTITY) or "")
    required_events = _required_sun_events(hass)
    if (
        required_events
        and str(config.get(CONF_SUN_EVENT_SOURCE) or "") == SUN_EVENT_SOURCE_ENTITY
        and sun_entity
    ):
        state = hass.states.get(sun_entity)
        if state is None:
            delete_issue(hass, owner, "sun_event_unavailable", sun_entity)
        else:
            invalid = not _state_available(state)
            if not invalid:
                invalid = any(
                    not dt_util.parse_datetime(
                        str(state.attributes.get(attribute) or "")
                    )
                    for attribute in required_events
                )
            if invalid:
                create_issue(
                    hass,
                    owner,
                    "sun_event_unavailable",
                    entity_id=sun_entity,
                    placeholders={"entity": sun_entity},
                    severity=ir.IssueSeverity.WARNING,
                )
            else:
                delete_issue(hass, owner, "sun_event_unavailable", sun_entity)
    elif sun_entity:
        delete_issue(hass, owner, "sun_event_unavailable", sun_entity)

    outside = config.get(CONF_OUTSIDE_TEMP_SENSOR)
    if outside:
        _validate_temperature_entity(hass, owner, str(outside))
        if weather:
            delete_issue(hass, owner, "invalid_temperature_unit", weather)
    elif weather:
        _validate_temperature_entity(
            hass,
            owner,
            weather,
            weather_attribute=True,
        )

    irradiance = config.get(CONF_IRRADIANCE_SENSOR)
    _validate_numeric_unit(
        hass,
        owner,
        str(irradiance) if irradiance else None,
        "invalid_irradiance_unit",
        normalize_irradiance,
    )
    illuminance = config.get(CONF_ILLUMINANCE_SENSOR)
    _validate_numeric_unit(
        hass,
        owner,
        str(illuminance) if illuminance else None,
        "invalid_illuminance_unit",
        normalize_illuminance,
    )
    _validate_wind_unit(hass, owner, config)
