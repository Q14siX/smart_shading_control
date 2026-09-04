"""Schemas and validation helpers for Smart Shading Control config flows."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_FRIENDLY_NAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import selector

from .const import (
    CONF_AZIMUTH_NORTH,
    CONF_COMFORT_TEMPERATURE,
    CONF_COVERS_EAST,
    CONF_COVERS_NORTH,
    CONF_COVERS_SOUTH,
    CONF_COVERS_WEST,
    CONF_DRY_RUN,
    CONF_DST_AMBIGUOUS_POLICY,
    CONF_DST_NONEXISTENT_POLICY,
    CONF_ENTRY_TYPE,
    CONF_EVALUATION_INTERVAL,
    CONF_FORECAST_HOURS,
    CONF_FORECAST_THRESHOLD,
    CONF_FROST_ACTION,
    CONF_FROST_PROTECTION_ENABLED,
    CONF_FROST_SAFE_POSITION,
    CONF_FROST_THRESHOLD,
    CONF_GLOBAL_MANUAL_OVERRIDE_MINUTES,
    CONF_GLOBAL_POSITION_VALUES,
    CONF_GLOBAL_TIME_RULES,
    CONF_HEAT_POSITION,
    CONF_HEAT_TEMPERATURE,
    CONF_ILLUMINANCE_SENSOR,
    CONF_IRRADIANCE_SENSOR,
    CONF_MANUAL_OVERRIDE_MINUTES,
    CONF_MIN_MOVE_INTERVAL,
    CONF_MIN_POSITION_CHANGE,
    CONF_MIN_SUN_ELEVATION,
    CONF_OPEN_POSITION,
    CONF_OPENING_CONTACT,
    CONF_OUTSIDE_TEMP_SENSOR,
    CONF_PREVENTIVE_POSITION,
    CONF_PROTECTION_ACTIVATION_DELAY,
    CONF_PROTECTION_RELEASE_DELAY,
    CONF_RAIN_PROTECTION_ENABLED,
    CONF_RAIN_SAFE_POSITION,
    CONF_RAIN_SENSOR,
    CONF_RISK_HYSTERESIS,
    CONF_ROOM_NAME,
    CONF_ROOM_TEMP_SENSOR,
    CONF_RULE_ACTION,
    CONF_RULE_COVERS,
    CONF_RULE_DAY_TYPE,
    CONF_RULE_ENABLED,
    CONF_RULE_FRIDAY,
    CONF_RULE_ID,
    CONF_RULE_MONDAY,
    CONF_RULE_NAME,
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
    CONF_STORM_SAFE_POSITION,
    CONF_STORM_THRESHOLD,
    CONF_STRONG_HEAT_POSITION,
    CONF_STRONG_HEAT_TEMPERATURE,
    CONF_SUN_ENTITY,
    CONF_SUN_EVENT_SOURCE,
    CONF_SUN_HALF_ANGLE,
    CONF_TILT_CONTROL_ENABLED,
    CONF_TILT_DEFAULT_POSITION,
    CONF_TILT_HEAT_POSITION,
    CONF_TILT_SAFETY_POSITION,
    CONF_TILT_STRONG_HEAT_POSITION,
    CONF_TIME_RULE_CLOSE_POSITION,
    CONF_TIME_RULES,
    CONF_WEATHER_ENTITY,
    CONF_WIND_PROTECTION_ENABLED,
    CONF_WIND_SAFE_POSITION,
    CONF_WIND_SENSOR,
    CONF_WIND_THRESHOLD,
    CONF_WORKDAY_ENTITY,
    DAY_TYPE_ANY,
    DAY_TYPES,
    DOMAIN,
    DST_AMBIGUOUS_POLICIES,
    DST_NONEXISTENT_POLICIES,
    ENTRY_TYPE_GLOBAL,
    ENTRY_TYPE_ROOM,
    FROST_ACTIONS,
    GLOBAL_DEFAULTS,
    POSITION_DEFAULTS,
    POSITION_SETTING_KEYS,
    ROOM_DEFAULTS,
    RULE_ACTION_CLOSE,
    RULE_ACTION_OPEN,
    RULE_ACTIONS,
    RULE_SCOPE_GLOBAL,
    RULE_SCOPE_ROOM,
    SUN_EVENT_SOURCES,
    TIME_REFERENCE_FIXED,
    TIME_REFERENCES,
    WEEKDAY_KEYS,
)
from .logic import as_list
from .schedule import normalize_boolean, normalize_rule, normalize_time

_COVER_KEYS = (
    CONF_COVERS_NORTH,
    CONF_COVERS_EAST,
    CONF_COVERS_SOUTH,
    CONF_COVERS_WEST,
)
_OPTIONAL_GLOBAL_ENTITIES = (
    CONF_WORKDAY_ENTITY,
    CONF_OUTSIDE_TEMP_SENSOR,
    CONF_IRRADIANCE_SENSOR,
    CONF_ILLUMINANCE_SENSOR,
    CONF_WIND_SENSOR,
    CONF_RAIN_SENSOR,
)


def _entry_kind(entry: ConfigEntry) -> str:
    """Return the entry kind, treating old entries as rooms."""
    return str(entry.data.get(CONF_ENTRY_TYPE) or ENTRY_TYPE_ROOM)


def _global_entry(hass: HomeAssistant) -> ConfigEntry | None:
    """Return the single central settings entry when configured."""
    return next(
        (
            entry
            for entry in hass.config_entries.async_entries(DOMAIN)
            if _entry_kind(entry) == ENTRY_TYPE_GLOBAL
        ),
        None,
    )


def _configured_workday_entity(hass: HomeAssistant) -> str | None:
    """Return the centrally configured Workday entity."""
    entry = _global_entry(hass)
    if entry is None:
        return None
    value = entry.options.get(CONF_WORKDAY_ENTITY, entry.data.get(CONF_WORKDAY_ENTITY))
    return str(value) if value else None


def _workday_dependent_rules_exist(hass: HomeAssistant) -> bool:
    """Return whether any configured rule requires Workday classification."""
    for entry in hass.config_entries.async_entries(DOMAIN):
        current = dict(entry.data)
        current.update(entry.options)
        for key in (CONF_TIME_RULES, CONF_GLOBAL_TIME_RULES):
            for raw_rule in as_list(current.get(key)):
                if not isinstance(raw_rule, dict) or not normalize_boolean(
                    raw_rule.get(CONF_RULE_ENABLED), True
                ):
                    continue
                if str(raw_rule.get(CONF_RULE_DAY_TYPE) or DAY_TYPE_ANY) != DAY_TYPE_ANY:
                    return True
    return False


def _entity(
    domain: str | list[str],
    *,
    multiple: bool = False,
    include_entities: list[str] | None = None,
) -> selector.EntitySelector:
    """Return an entity selector."""
    config: selector.EntitySelectorConfig = {
        "domain": domain,
        "multiple": multiple,
        "reorder": multiple,
    }
    if include_entities:
        config["include_entities"] = include_entities
    return selector.EntitySelector(config)


def _workday_entity_selector() -> selector.EntitySelector:
    """Return a selector limited to Workday binary sensors."""
    return selector.EntitySelector(
        selector.EntitySelectorConfig(
            filter={"domain": "binary_sensor", "integration": "workday"},
            multiple=False,
        )
    )


def _number(
    minimum: float,
    maximum: float,
    step: float = 1.0,
    unit: str | None = None,
) -> selector.NumberSelector:
    config: selector.NumberSelectorConfig = {
        "min": minimum,
        "max": maximum,
        "step": step,
        "mode": selector.NumberSelectorMode.BOX,
    }
    if unit:
        config["unit_of_measurement"] = unit
    return selector.NumberSelector(config)


def _time_reference_selector() -> selector.SelectSelector:
    return selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=TIME_REFERENCES,
            mode=selector.SelectSelectorMode.DROPDOWN,
            translation_key="time_reference",
        )
    )


def _day_type_selector() -> selector.SelectSelector:
    return selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=DAY_TYPES,
            mode=selector.SelectSelectorMode.DROPDOWN,
            translation_key="day_type",
        )
    )


def _translated_select(options: list[str], translation_key: str) -> selector.SelectSelector:
    return selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=options,
            mode=selector.SelectSelectorMode.DROPDOWN,
            translation_key=translation_key,
        )
    )


def _required_marker(
    key: str,
    values: dict[str, Any],
    fallback: Any | None = None,
) -> vol.Marker:
    if key in values and values[key] is not None:
        return vol.Required(key, default=values[key])
    if fallback is not None:
        return vol.Required(key, default=fallback)
    return vol.Required(key)


def _optional_marker(key: str, values: dict[str, Any]) -> vol.Marker:
    if key in values and values[key] not in (None, ""):
        return vol.Optional(key, description={"suggested_value": values[key]})
    return vol.Optional(key)


def _global_schema(values: dict[str, Any] | None = None) -> vol.Schema:
    current = dict(GLOBAL_DEFAULTS)
    current.update(values or {})
    return vol.Schema(
        {
            _required_marker(CONF_SUN_ENTITY, current, "sun.sun"): _entity("sun"),
            _required_marker(CONF_WEATHER_ENTITY, current): _entity("weather"),
            _optional_marker(CONF_WORKDAY_ENTITY, current): _workday_entity_selector(),
            _optional_marker(CONF_OUTSIDE_TEMP_SENSOR, current): _entity(
                ["sensor", "input_number", "number"]
            ),
            _optional_marker(CONF_IRRADIANCE_SENSOR, current): _entity(
                ["sensor", "input_number", "number"]
            ),
            _optional_marker(CONF_ILLUMINANCE_SENSOR, current): _entity(
                ["sensor", "input_number", "number"]
            ),
            _optional_marker(CONF_WIND_SENSOR, current): _entity(
                ["sensor", "input_number", "number"]
            ),
            _optional_marker(CONF_RAIN_SENSOR, current): _entity(
                ["binary_sensor", "sensor", "input_boolean", "input_number", "number"]
            ),
            vol.Required(CONF_WIND_PROTECTION_ENABLED, default=current[CONF_WIND_PROTECTION_ENABLED]): selector.BooleanSelector(),
            vol.Required(CONF_RAIN_PROTECTION_ENABLED, default=current[CONF_RAIN_PROTECTION_ENABLED]): selector.BooleanSelector(),
            vol.Required(CONF_FROST_PROTECTION_ENABLED, default=current[CONF_FROST_PROTECTION_ENABLED]): selector.BooleanSelector(),
            vol.Required(CONF_AZIMUTH_NORTH, default=current[CONF_AZIMUTH_NORTH]): _number(0, 359, 1, "°"),
            vol.Required(CONF_MIN_SUN_ELEVATION, default=current[CONF_MIN_SUN_ELEVATION]): _number(-5, 45, 1, "°"),
            vol.Required(CONF_SUN_HALF_ANGLE, default=current[CONF_SUN_HALF_ANGLE]): _number(15, 90, 1, "°"),
            vol.Required(CONF_FROST_THRESHOLD, default=current[CONF_FROST_THRESHOLD]): _number(-20, 10, 0.1, "°C"),
            vol.Required(CONF_FORECAST_HOURS, default=current[CONF_FORECAST_HOURS]): _number(1, 24, 1, "h"),
            vol.Required(CONF_EVALUATION_INTERVAL, default=current[CONF_EVALUATION_INTERVAL]): _number(1, 30, 1, "min"),
            vol.Required(CONF_WIND_THRESHOLD, default=current[CONF_WIND_THRESHOLD]): _number(1, 200, 1, "km/h"),
            vol.Required(CONF_STORM_THRESHOLD, default=current[CONF_STORM_THRESHOLD]): _number(1, 250, 1, "km/h"),
            vol.Required(CONF_FROST_ACTION, default=current[CONF_FROST_ACTION]): _translated_select(FROST_ACTIONS, "frost_action"),
            vol.Required(CONF_PROTECTION_ACTIVATION_DELAY, default=current[CONF_PROTECTION_ACTIVATION_DELAY]): _number(0, 600, 5, "s"),
            vol.Required(CONF_PROTECTION_RELEASE_DELAY, default=current[CONF_PROTECTION_RELEASE_DELAY]): _number(0, 120, 1, "min"),
            vol.Required(CONF_SUN_EVENT_SOURCE, default=current[CONF_SUN_EVENT_SOURCE]): _translated_select(SUN_EVENT_SOURCES, "sun_event_source"),
            vol.Required(CONF_DST_NONEXISTENT_POLICY, default=current[CONF_DST_NONEXISTENT_POLICY]): _translated_select(DST_NONEXISTENT_POLICIES, "dst_nonexistent_policy"),
            vol.Required(CONF_DST_AMBIGUOUS_POLICY, default=current[CONF_DST_AMBIGUOUS_POLICY]): _translated_select(DST_AMBIGUOUS_POLICIES, "dst_ambiguous_policy"),
        }
    )

def _clean_global_input(user_input: dict[str, Any]) -> dict[str, Any]:
    """Remove empty optional selectors before storing the central settings."""
    result = dict(user_input)
    for key in _OPTIONAL_GLOBAL_ENTITIES:
        if not result.get(key):
            result.pop(key, None)
    result[CONF_AZIMUTH_NORTH] = float(result[CONF_AZIMUTH_NORTH]) % 360.0
    return result


def _room_schema(
    values: dict[str, Any] | None = None, language: str = "en"
) -> vol.Schema:
    values = values or {}
    default_room_name = "Wohnzimmer" if str(language).lower().startswith("de") else "Living room"
    return vol.Schema(
        {
            _required_marker(CONF_ROOM_NAME, values, default_room_name): selector.TextSelector(),
            _required_marker(CONF_ROOM_TEMP_SENSOR, values): _entity(
                ["sensor", "input_number", "number"]
            ),
        }
    )


def _covers_schema(values: dict[str, Any] | None = None) -> vol.Schema:
    values = values or {}
    return vol.Schema(
        {
            vol.Required(
                CONF_COVERS_NORTH,
                default=values.get(CONF_COVERS_NORTH, []),
            ): _entity("cover", multiple=True),
            vol.Required(
                CONF_COVERS_EAST,
                default=values.get(CONF_COVERS_EAST, []),
            ): _entity("cover", multiple=True),
            vol.Required(
                CONF_COVERS_SOUTH,
                default=values.get(CONF_COVERS_SOUTH, []),
            ): _entity("cover", multiple=True),
            vol.Required(
                CONF_COVERS_WEST,
                default=values.get(CONF_COVERS_WEST, []),
            ): _entity("cover", multiple=True),
        }
    )


def _cover_contact_schema(contact: str | None) -> vol.Schema:
    marker: vol.Marker
    if contact:
        marker = vol.Optional(
            CONF_OPENING_CONTACT,
            description={"suggested_value": contact},
        )
    else:
        marker = vol.Optional(CONF_OPENING_CONTACT)
    return vol.Schema(
        {
            marker: _entity(
                ["binary_sensor", "sensor", "select", "input_select"]
            )
        }
    )


def _behavior_schema(
    values: dict[str, Any] | None = None,
    *,
    defaults: dict[str, Any] | None = None,
) -> vol.Schema:
    current = dict(ROOM_DEFAULTS)
    current.update(defaults or {})
    current.update(values or {})
    return vol.Schema(
        {
            vol.Required(CONF_COMFORT_TEMPERATURE, default=current[CONF_COMFORT_TEMPERATURE]): _number(15, 30, 0.1, "°C"),
            vol.Required(CONF_HEAT_TEMPERATURE, default=current[CONF_HEAT_TEMPERATURE]): _number(16, 35, 0.1, "°C"),
            vol.Required(CONF_STRONG_HEAT_TEMPERATURE, default=current[CONF_STRONG_HEAT_TEMPERATURE]): _number(17, 40, 0.1, "°C"),
            vol.Required(CONF_FORECAST_THRESHOLD, default=current[CONF_FORECAST_THRESHOLD]): _number(10, 45, 0.1, "°C"),
            vol.Required(CONF_MIN_POSITION_CHANGE, default=current[CONF_MIN_POSITION_CHANGE]): _number(1, 50, 1, "%"),
            vol.Required(CONF_MIN_MOVE_INTERVAL, default=current[CONF_MIN_MOVE_INTERVAL]): _number(0, 120, 1, "min"),
            vol.Required(CONF_MANUAL_OVERRIDE_MINUTES, default=current[CONF_MANUAL_OVERRIDE_MINUTES]): _number(0, 1440, 5, "min"),
            vol.Required(CONF_RISK_HYSTERESIS, default=current[CONF_RISK_HYSTERESIS]): _number(0, 25, 1),
            vol.Required(CONF_DRY_RUN, default=current[CONF_DRY_RUN]): selector.BooleanSelector(),
            vol.Required(CONF_TILT_CONTROL_ENABLED, default=current[CONF_TILT_CONTROL_ENABLED]): selector.BooleanSelector(),
        }
    )

def _normalized_position_values(raw: Any) -> dict[str, int]:
    """Return a complete, range-limited position dictionary."""
    source = raw if isinstance(raw, dict) else {}
    result: dict[str, int] = {}
    for key, default in POSITION_DEFAULTS.items():
        try:
            value = int(source.get(key, default))
        except (TypeError, ValueError):
            value = int(default)
        result[key] = max(0, min(100, value))
    return result


def _configured_global_position_values(hass: HomeAssistant) -> dict[str, int]:
    """Return central position templates or built-in defaults."""
    entry = _global_entry(hass)
    if entry is None:
        return dict(POSITION_DEFAULTS)
    current = dict(entry.data)
    current.update(entry.options)
    raw = current.get(CONF_GLOBAL_POSITION_VALUES)
    if not isinstance(raw, dict):
        raw = {
            key: current.get(key, default)
            for key, default in POSITION_DEFAULTS.items()
        }
    return _normalized_position_values(raw)


def _configured_global_manual_override_minutes(hass: HomeAssistant) -> int:
    """Return the central manual-override template for new rooms."""
    entry = _global_entry(hass)
    raw: Any = ROOM_DEFAULTS[CONF_MANUAL_OVERRIDE_MINUTES]
    if entry is not None:
        current = dict(entry.data)
        current.update(entry.options)
        raw = current.get(CONF_GLOBAL_MANUAL_OVERRIDE_MINUTES, raw)
    try:
        value = int(raw)
    except (TypeError, ValueError):
        value = int(ROOM_DEFAULTS[CONF_MANUAL_OVERRIDE_MINUTES])
    return max(0, min(1440, value))


def _global_manual_override_schema(
    values: dict[str, Any] | None = None,
) -> vol.Schema:
    """Return the central manual-override template schema."""
    current = dict(GLOBAL_DEFAULTS)
    current.update(values or {})
    return vol.Schema(
        {
            vol.Required(
                CONF_GLOBAL_MANUAL_OVERRIDE_MINUTES,
                default=current[CONF_GLOBAL_MANUAL_OVERRIDE_MINUTES],
            ): _number(0, 1440, 5, "min")
        }
    )


def _clean_global_manual_override_input(
    user_input: dict[str, Any],
) -> dict[str, int]:
    """Normalize the central manual-override template."""
    try:
        value = int(user_input[CONF_GLOBAL_MANUAL_OVERRIDE_MINUTES])
    except (KeyError, TypeError, ValueError):
        value = int(GLOBAL_DEFAULTS[CONF_GLOBAL_MANUAL_OVERRIDE_MINUTES])
    return {CONF_GLOBAL_MANUAL_OVERRIDE_MINUTES: max(0, min(1440, value))}


def _position_order_is_valid(data: dict[str, Any]) -> bool:
    """Return whether the four dynamic vertical positions are ordered."""
    positions = [
        int(data[CONF_OPEN_POSITION]),
        int(data[CONF_PREVENTIVE_POSITION]),
        int(data[CONF_HEAT_POSITION]),
        int(data[CONF_STRONG_HEAT_POSITION]),
    ]
    return positions[0] >= positions[1] >= positions[2] >= positions[3]


def _validate_room_position_settings(
    hass: HomeAssistant, data: dict[str, Any]
) -> str | None:
    """Validate independently stored room positions."""
    del hass
    return _validate_positions(data)


def _validate_global_position_settings(
    hass: HomeAssistant, data: dict[str, Any]
) -> str | None:
    """Validate the complete template copied to every room on save."""
    del hass
    return _validate_positions(data)


def _positions_schema(
    values: dict[str, Any] | None = None,
    *,
    defaults: dict[str, int] | None = None,
) -> vol.Schema:
    """Return all independently stored room target positions."""
    current = dict(POSITION_DEFAULTS)
    current.update(defaults or {})
    current.update(values or {})
    return vol.Schema(
        {
            vol.Required(CONF_OPEN_POSITION, default=current[CONF_OPEN_POSITION]): _number(0, 100, 1, "%"),
            vol.Required(CONF_TIME_RULE_CLOSE_POSITION, default=current[CONF_TIME_RULE_CLOSE_POSITION]): _number(0, 100, 1, "%"),
            vol.Required(CONF_PREVENTIVE_POSITION, default=current[CONF_PREVENTIVE_POSITION]): _number(0, 100, 1, "%"),
            vol.Required(CONF_HEAT_POSITION, default=current[CONF_HEAT_POSITION]): _number(0, 100, 1, "%"),
            vol.Required(CONF_STRONG_HEAT_POSITION, default=current[CONF_STRONG_HEAT_POSITION]): _number(0, 100, 1, "%"),
            vol.Required(CONF_WIND_SAFE_POSITION, default=current[CONF_WIND_SAFE_POSITION]): _number(0, 100, 1, "%"),
            vol.Required(CONF_STORM_SAFE_POSITION, default=current[CONF_STORM_SAFE_POSITION]): _number(0, 100, 1, "%"),
            vol.Required(CONF_RAIN_SAFE_POSITION, default=current[CONF_RAIN_SAFE_POSITION]): _number(0, 100, 1, "%"),
            vol.Required(CONF_FROST_SAFE_POSITION, default=current[CONF_FROST_SAFE_POSITION]): _number(0, 100, 1, "%"),
            vol.Required(CONF_TILT_DEFAULT_POSITION, default=current[CONF_TILT_DEFAULT_POSITION]): _number(0, 100, 1, "%"),
            vol.Required(CONF_TILT_HEAT_POSITION, default=current[CONF_TILT_HEAT_POSITION]): _number(0, 100, 1, "%"),
            vol.Required(CONF_TILT_STRONG_HEAT_POSITION, default=current[CONF_TILT_STRONG_HEAT_POSITION]): _number(0, 100, 1, "%"),
            vol.Required(CONF_TILT_SAFETY_POSITION, default=current[CONF_TILT_SAFETY_POSITION]): _number(0, 100, 1, "%"),
        }
    )


def _global_positions_schema(
    values: dict[str, Any] | None = None,
) -> vol.Schema:
    """Return the complete central position template."""
    current = dict(values or {})
    if any(key in current for key in POSITION_SETTING_KEYS):
        positions = _normalized_position_values(current)
    else:
        positions = _normalized_position_values(
            current.get(CONF_GLOBAL_POSITION_VALUES)
        )
    fields: dict[vol.Marker, Any] = {}
    for key in POSITION_SETTING_KEYS:
        fields[vol.Required(key, default=positions[key])] = _number(0, 100, 1, "%")
    return vol.Schema(fields)


def _clean_global_positions_input(user_input: dict[str, Any]) -> dict[str, Any]:
    """Store central templates without persisting transient transfer controls."""
    return {CONF_GLOBAL_POSITION_VALUES: _normalized_position_values(user_input)}


def _validate_positions(data: dict[str, Any]) -> str | None:
    """Validate semantically ordered shading positions."""
    if not _position_order_is_valid(data):
        return "position_order"
    return None


def _ordered_covers(data: dict[str, Any]) -> list[str]:
    return list(
        dict.fromkeys(
            str(cover)
            for key in _COVER_KEYS
            for cover in as_list(data.get(key))
        )
    )


def _covers_in_other_rooms(
    hass: HomeAssistant,
    *,
    exclude_entry_id: str | None = None,
) -> set[str]:
    """Return covers configured in other room entries."""
    result: set[str] = set()
    for entry in hass.config_entries.async_entries(DOMAIN):
        if entry.entry_id == exclude_entry_id or _entry_kind(entry) != ENTRY_TYPE_ROOM:
            continue
        current = dict(entry.data)
        current.update(entry.options)
        result.update(_ordered_covers(current))
    return result


def _integration_cover_entities(hass: HomeAssistant) -> set[str]:
    """Return virtual covers created by Smart Shading Control itself."""
    registry = er.async_get(hass)
    result: set[str] = set()
    for entry in hass.config_entries.async_entries(DOMAIN):
        for registry_entry in er.async_entries_for_config_entry(
            registry, entry.entry_id
        ):
            if registry_entry.domain == "cover":
                result.add(registry_entry.entity_id)
    return result


def _validate_cover_groups(
    data: dict[str, Any],
    *,
    covers_in_other_rooms: set[str] | None = None,
    integration_covers: set[str] | None = None,
) -> str | None:
    all_covers = [
        str(cover)
        for key in _COVER_KEYS
        for cover in as_list(data.get(key))
        if cover
    ]
    if not all_covers:
        return "no_covers"
    if len(all_covers) != len(set(all_covers)):
        return "duplicate_cover"
    if set(all_covers) & (covers_in_other_rooms or set()):
        return "cover_in_other_room"
    if set(all_covers) & (integration_covers or set()):
        return "integration_cover_not_allowed"
    return None


def _validate_global_settings(data: dict[str, Any]) -> str | None:
    """Validate safety thresholds and positions."""
    if float(data[CONF_STORM_THRESHOLD]) < float(data[CONF_WIND_THRESHOLD]):
        return "storm_below_wind"
    return None


def _validate_temperatures(data: dict[str, Any]) -> str | None:
    comfort = float(data[CONF_COMFORT_TEMPERATURE])
    heat = float(data[CONF_HEAT_TEMPERATURE])
    strong = float(data[CONF_STRONG_HEAT_TEMPERATURE])
    if not comfort < heat < strong:
        return "temperature_order"
    return None

def _entity_display_name(hass: HomeAssistant, entity_id: str) -> str:
    """Return the most useful user-facing name for an entity."""
    entity_entry = er.async_get(hass).async_get(entity_id)
    if entity_entry is not None:
        if entity_entry.device_id:
            device = dr.async_get(hass).async_get(entity_entry.device_id)
            if device is not None:
                if device.name_by_user:
                    return str(device.name_by_user)
                if device.name:
                    return str(device.name)
        if entity_entry.name:
            return str(entity_entry.name)

    state = hass.states.get(entity_id)
    if state is not None:
        friendly_name = state.attributes.get(ATTR_FRIENDLY_NAME)
        if friendly_name:
            return str(friendly_name)
        if state.name:
            return str(state.name)

    if entity_entry is not None and entity_entry.original_name:
        return str(entity_entry.original_name)
    return entity_id


def _cover_choice_selector(
    hass: HomeAssistant,
    room_covers: list[str],
) -> selector.SelectSelector:
    """Return a labeled selector containing only covers from this room."""
    display_names = {
        entity_id: _entity_display_name(hass, entity_id)
        for entity_id in room_covers
    }
    counts: dict[str, int] = {}
    for name in display_names.values():
        counts[name] = counts.get(name, 0) + 1
    options = []
    for entity_id in room_covers:
        name = display_names[entity_id]
        label = name if counts[name] == 1 else f"{name} ({entity_id})"
        options.append({"value": entity_id, "label": label})
    return selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=options,
            multiple=True,
            mode=selector.SelectSelectorMode.DROPDOWN,
            sort=False,
        )
    )


def _rule_defaults(
    values: dict[str, Any] | None = None,
    *,
    scope: str,
    room_covers: list[str] | None = None,
    language: str = "en",
) -> dict[str, Any]:
    covers = list(room_covers or [])
    is_german = str(language).lower().startswith("de")
    defaults: dict[str, Any] = {
        CONF_RULE_NAME: "Abends schließen" if is_german else "Close in the evening",
        CONF_RULE_DAY_TYPE: DAY_TYPE_ANY,
        CONF_RULE_SCOPE: scope,
        CONF_RULE_ACTION: RULE_ACTION_CLOSE,
        CONF_RULE_MONDAY: True,
        CONF_RULE_TUESDAY: True,
        CONF_RULE_WEDNESDAY: True,
        CONF_RULE_THURSDAY: True,
        CONF_RULE_FRIDAY: True,
        CONF_RULE_SATURDAY: True,
        CONF_RULE_SUNDAY: True,
        CONF_RULE_TRIGGER_REFERENCE: TIME_REFERENCE_FIXED,
        CONF_RULE_TRIGGER: "22:00:00",
        CONF_RULE_TRIGGER_OFFSET: 0,
        CONF_RULE_PRIORITY: 50,
        CONF_RULE_COVERS: covers if scope == RULE_SCOPE_ROOM else [],
    }
    defaults.update(values or {})
    defaults[CONF_RULE_SCOPE] = scope
    if scope == RULE_SCOPE_ROOM:
        selected = [
            cover
            for cover in (defaults.get(CONF_RULE_COVERS) or covers)
            if cover in covers
        ]
        defaults[CONF_RULE_COVERS] = selected or covers
    else:
        defaults[CONF_RULE_COVERS] = []
    return defaults


def _rule_action_selector() -> selector.SelectSelector:
    return selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=RULE_ACTIONS,
            translation_key="time_rule_action",
            mode=selector.SelectSelectorMode.DROPDOWN,
        )
    )


def _rule_basics_schema(
    hass: HomeAssistant,
    *,
    scope: str,
    room_covers: list[str] | None = None,
    values: dict[str, Any] | None = None,
) -> vol.Schema:
    current = _rule_defaults(
        values,
        scope=scope,
        room_covers=room_covers,
        language=hass.config.language,
    )
    fields: dict[vol.Marker, Any] = {
        vol.Required(
            CONF_RULE_NAME,
            default=current[CONF_RULE_NAME],
        ): selector.TextSelector(),
        vol.Required(
            CONF_RULE_ACTION,
            default=current[CONF_RULE_ACTION],
        ): _rule_action_selector(),
        vol.Required(
            CONF_RULE_DAY_TYPE,
            default=current[CONF_RULE_DAY_TYPE],
        ): _day_type_selector(),
    }
    if scope == RULE_SCOPE_ROOM:
        covers = list(room_covers or [])
        fields[
            vol.Required(
                CONF_RULE_COVERS,
                default=current[CONF_RULE_COVERS],
            )
        ] = _cover_choice_selector(hass, covers)
    fields.update(
        {
            vol.Required(
                CONF_RULE_PRIORITY,
                default=current[CONF_RULE_PRIORITY],
            ): _number(1, 100, 1),
            vol.Required(
                CONF_RULE_MONDAY,
                default=current[CONF_RULE_MONDAY],
            ): selector.BooleanSelector(),
            vol.Required(
                CONF_RULE_TUESDAY,
                default=current[CONF_RULE_TUESDAY],
            ): selector.BooleanSelector(),
            vol.Required(
                CONF_RULE_WEDNESDAY,
                default=current[CONF_RULE_WEDNESDAY],
            ): selector.BooleanSelector(),
            vol.Required(
                CONF_RULE_THURSDAY,
                default=current[CONF_RULE_THURSDAY],
            ): selector.BooleanSelector(),
            vol.Required(
                CONF_RULE_FRIDAY,
                default=current[CONF_RULE_FRIDAY],
            ): selector.BooleanSelector(),
            vol.Required(
                CONF_RULE_SATURDAY,
                default=current[CONF_RULE_SATURDAY],
            ): selector.BooleanSelector(),
            vol.Required(
                CONF_RULE_SUNDAY,
                default=current[CONF_RULE_SUNDAY],
            ): selector.BooleanSelector(),
        }
    )
    return vol.Schema(fields)


def _rule_reference_schema(current: str) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(
                CONF_RULE_TRIGGER_REFERENCE,
                default=current,
            ): _time_reference_selector()
        }
    )


def _rule_time_or_offset_schema(
    *,
    reference: str,
    values: dict[str, Any],
) -> vol.Schema:
    if reference == TIME_REFERENCE_FIXED:
        return vol.Schema(
            {
                vol.Required(
                    CONF_RULE_TRIGGER,
                    default=normalize_time(values.get(CONF_RULE_TRIGGER, "00:00:00")),
                ): selector.TimeSelector()
            }
        )
    return vol.Schema(
        {
            vol.Required(
                CONF_RULE_TRIGGER_OFFSET,
                default=int(values.get(CONF_RULE_TRIGGER_OFFSET, 0)),
            ): _number(-720, 720, 1, "min")
        }
    )


def _rule_choice_selector(choices: dict[str, str]) -> selector.SelectSelector:
    return selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=[
                {"value": rule_id, "label": label}
                for rule_id, label in choices.items()
            ],
            mode=selector.SelectSelectorMode.DROPDOWN,
            sort=False,
        )
    )


def _validate_rule_basics(
    data: dict[str, Any],
    *,
    scope: str,
    room_covers: set[str] | None,
    workday_available: bool,
) -> str | None:
    if not str(data.get(CONF_RULE_NAME) or "").strip():
        return "rule_name_required"
    if str(data.get(CONF_RULE_ACTION) or "") not in RULE_ACTIONS:
        return "rule_action_invalid"
    day_type = str(data.get(CONF_RULE_DAY_TYPE) or DAY_TYPE_ANY)
    if day_type not in DAY_TYPES:
        return "rule_day_type_invalid"
    if day_type != DAY_TYPE_ANY and not workday_available:
        return "workday_sensor_required"
    if not any(normalize_boolean(data.get(key), False) for key in WEEKDAY_KEYS):
        return "rule_weekday_required"
    if scope == RULE_SCOPE_ROOM:
        available = room_covers or set()
        selected = [
            str(cover)
            for cover in as_list(data.get(CONF_RULE_COVERS))
            if cover
        ]
        if not selected:
            return "rule_cover_required"
        if any(cover not in available for cover in selected):
            return "rule_cover_outside_room"
    return None


def _validate_complete_time_rule(
    data: dict[str, Any],
    *,
    scope: str,
    room_covers: set[str] | None,
    workday_available: bool,
) -> str | None:
    if error := _validate_rule_basics(
        data,
        scope=scope,
        room_covers=room_covers,
        workday_available=workday_available,
    ):
        return error
    reference = str(data.get(CONF_RULE_TRIGGER_REFERENCE) or "")
    if reference not in TIME_REFERENCES:
        return "rule_reference_invalid"
    try:
        if reference == TIME_REFERENCE_FIXED:
            normalize_time(data.get(CONF_RULE_TRIGGER))
        else:
            int(data.get(CONF_RULE_TRIGGER_OFFSET, 0))
    except (TypeError, ValueError):
        return "rule_time_invalid"
    return None


def _normalized_rule_from_input(
    data: dict[str, Any],
    *,
    scope: str,
    rule_id: str | None = None,
) -> dict[str, Any]:
    raw = dict(data)
    raw[CONF_RULE_ID] = rule_id or str(uuid4())
    raw[CONF_RULE_NAME] = str(raw[CONF_RULE_NAME]).strip()
    raw[CONF_RULE_SCOPE] = scope
    if scope == RULE_SCOPE_GLOBAL:
        raw[CONF_RULE_COVERS] = []
    return normalize_rule(raw)


def _trigger_summary(rule: dict[str, Any], language: str = "en") -> str:
    reference = str(rule[CONF_RULE_TRIGGER_REFERENCE])
    if reference == TIME_REFERENCE_FIXED:
        return normalize_time(rule[CONF_RULE_TRIGGER])[:5]
    is_german = str(language).lower().startswith("de")
    if reference == "sunrise":
        event = "Sonnenaufgang" if is_german else "Sunrise"
    else:
        event = "Sonnenuntergang" if is_german else "Sunset"
    offset = int(rule[CONF_RULE_TRIGGER_OFFSET])
    return event if offset == 0 else f"{event} {offset:+d} min"


def _action_summary(action: str, language: str = "en") -> str:
    is_german = str(language).lower().startswith("de")
    if action == RULE_ACTION_OPEN:
        return "Hochfahren" if is_german else "Open"
    return "Runterfahren" if is_german else "Close"

