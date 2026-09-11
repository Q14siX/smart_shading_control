"""Constants for Smart Shading Control."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "smart_shading_control"
NAME: Final = "Smart Shading Control"
VERSION: Final = "20260911.154309"

PLATFORMS: Final = ["sensor", "binary_sensor", "switch", "select", "button", "cover"]

CONF_ENTRY_TYPE: Final = "entry_type"
ENTRY_TYPE_GLOBAL: Final = "global"
ENTRY_TYPE_ROOM: Final = "room"
GLOBAL_UNIQUE_ID: Final = "global_settings"

# Global building configuration, shared by every room.
CONF_SUN_ENTITY: Final = "sun_entity"
CONF_WEATHER_ENTITY: Final = "weather_entity"
CONF_WORKDAY_ENTITY: Final = "workday_entity"
CONF_OUTSIDE_TEMP_SENSOR: Final = "outside_temperature_sensor"
CONF_IRRADIANCE_SENSOR: Final = "irradiance_sensor"
CONF_ILLUMINANCE_SENSOR: Final = "illuminance_sensor"
CONF_AZIMUTH_NORTH: Final = "azimuth_north"
# Legacy keys retained only so older central entries can be migrated cleanly.
CONF_AZIMUTH_EAST: Final = "azimuth_east"
CONF_AZIMUTH_SOUTH: Final = "azimuth_south"
CONF_AZIMUTH_WEST: Final = "azimuth_west"
CONF_MIN_SUN_ELEVATION: Final = "min_sun_elevation"
CONF_SUN_HALF_ANGLE: Final = "sun_half_angle"
CONF_FROST_THRESHOLD: Final = "frost_threshold"
CONF_FORECAST_HOURS: Final = "forecast_hours"
CONF_EVALUATION_INTERVAL: Final = "evaluation_interval"
CONF_GLOBAL_TIME_RULES: Final = "global_time_rules"
CONF_WIND_SENSOR: Final = "wind_sensor"
CONF_WIND_PROTECTION_ENABLED: Final = "wind_protection_enabled"
CONF_RAIN_PROTECTION_ENABLED: Final = "rain_protection_enabled"
CONF_FROST_PROTECTION_ENABLED: Final = "frost_protection_enabled"
CONF_RAIN_SENSOR: Final = "rain_sensor"
CONF_WIND_THRESHOLD: Final = "wind_threshold"
CONF_STORM_THRESHOLD: Final = "storm_threshold"
CONF_WIND_SAFE_POSITION: Final = "wind_safe_position"
CONF_STORM_SAFE_POSITION: Final = "storm_safe_position"
CONF_RAIN_SAFE_POSITION: Final = "rain_safe_position"
CONF_FROST_ACTION: Final = "frost_action"
CONF_FROST_SAFE_POSITION: Final = "frost_safe_position"
CONF_PROTECTION_ACTIVATION_DELAY: Final = "protection_activation_delay"
CONF_PROTECTION_RELEASE_DELAY: Final = "protection_release_delay"
CONF_SUN_EVENT_SOURCE: Final = "sun_event_source"
CONF_DST_NONEXISTENT_POLICY: Final = "dst_nonexistent_policy"
CONF_DST_AMBIGUOUS_POLICY: Final = "dst_ambiguous_policy"

# Room configuration.
CONF_ROOM_NAME: Final = "room_name"
CONF_ROOM_TEMP_SENSOR: Final = "room_temperature_sensor"
CONF_FORECAST_THRESHOLD: Final = "forecast_threshold"

CONF_COVERS_NORTH: Final = "covers_north"
CONF_COVERS_EAST: Final = "covers_east"
CONF_COVERS_SOUTH: Final = "covers_south"
CONF_COVERS_WEST: Final = "covers_west"

# One optional opening contact may be assigned to every configured cover.
CONF_COVER_CONTACTS: Final = "cover_contacts"
CONF_OPENING_CONTACT: Final = "opening_contact"

# Legacy keys used exclusively for config-entry migration.
CONF_OPENING_CONTACTS: Final = "opening_contacts"
LEGACY_CONF_OPEN_WINDOW_SENSORS: Final = "open_window_sensors"
LEGACY_CONF_TILTED_WINDOW_SENSORS: Final = "tilted_window_sensors"
LEGACY_CONF_DOOR_SENSORS: Final = "door_sensors"
LEGACY_CONF_SCHEDULE_PREFIX: Final = "schedule_"
LEGACY_CONF_SCHEDULE_POSITION_PREFIX: Final = "schedule_position_"
LEGACY_CONF_SCHEDULE_PRIORITY_PREFIX: Final = "schedule_priority_"
LEGACY_MAX_SCHEDULES: Final = 5

CONF_COMFORT_TEMPERATURE: Final = "comfort_temperature"
CONF_HEAT_TEMPERATURE: Final = "heat_temperature"
CONF_STRONG_HEAT_TEMPERATURE: Final = "strong_heat_temperature"
CONF_OPEN_POSITION: Final = "open_position"
CONF_PREVENTIVE_POSITION: Final = "preventive_position"
CONF_HEAT_POSITION: Final = "heat_position"
CONF_STRONG_HEAT_POSITION: Final = "strong_heat_position"
CONF_TIME_RULE_CLOSE_POSITION: Final = "time_rule_close_position"
CONF_MIN_POSITION_CHANGE: Final = "min_position_change"
CONF_MIN_MOVE_INTERVAL: Final = "min_move_interval"
CONF_MANUAL_OVERRIDE_MINUTES: Final = "manual_override_minutes"
CONF_RISK_HYSTERESIS: Final = "risk_hysteresis"
CONF_DRY_RUN: Final = "dry_run"
CONF_PERSIST_MANUAL_OVERRIDES: Final = "persist_manual_overrides"
CONF_TILT_CONTROL_ENABLED: Final = "tilt_control_enabled"
CONF_TILT_DEFAULT_POSITION: Final = "tilt_default_position"
CONF_TILT_HEAT_POSITION: Final = "tilt_heat_position"
CONF_TILT_STRONG_HEAT_POSITION: Final = "tilt_strong_heat_position"
CONF_TILT_SAFETY_POSITION: Final = "tilt_safety_position"

# Central position templates. The override key is retained only for migration
# from versions that applied central values continuously at runtime.
CONF_GLOBAL_POSITION_VALUES: Final = "global_position_values"
CONF_GLOBAL_MANUAL_OVERRIDE_MINUTES: Final = "global_manual_override_minutes"
CONF_GLOBAL_POSITION_OVERRIDES: Final = "global_position_overrides"

# Event-based time rules. Each rule performs exactly one opening or closing
# action at one fixed time or solar event. The legacy interval keys are retained
# exclusively for config-entry migration from development versions.
CONF_TIME_RULES: Final = "time_rules"
CONF_RULE_ID: Final = "id"
CONF_RULE_NAME: Final = "name"
CONF_RULE_ENABLED: Final = "enabled"  # Legacy only.
CONF_RULE_DAY_TYPE: Final = "day_type"
CONF_RULE_ACTION: Final = "action"
RULE_ACTION_OPEN: Final = "open"
RULE_ACTION_CLOSE: Final = "close"
RULE_ACTIONS: Final = [RULE_ACTION_OPEN, RULE_ACTION_CLOSE]
CONF_RULE_TRIGGER_REFERENCE: Final = "trigger_reference"
CONF_RULE_TRIGGER: Final = "trigger_time"
CONF_RULE_TRIGGER_OFFSET: Final = "trigger_offset_minutes"
CONF_RULE_PRIORITY: Final = "priority"
CONF_RULE_COVERS: Final = "covers"
CONF_RULE_SCOPE: Final = "scope"
RULE_SCOPE_ROOM: Final = "room"
RULE_SCOPE_GLOBAL: Final = "global"

# Legacy interval-rule fields used only by migration to config-entry version 10.
CONF_RULE_START_REFERENCE: Final = "start_reference"
CONF_RULE_START: Final = "start_time"
CONF_RULE_START_OFFSET: Final = "start_offset_minutes"
CONF_RULE_END_REFERENCE: Final = "end_reference"
CONF_RULE_END: Final = "end_time"
CONF_RULE_END_OFFSET: Final = "end_offset_minutes"
CONF_RULE_POSITION: Final = "position"
CONF_RULE_MONDAY: Final = "monday"
CONF_RULE_TUESDAY: Final = "tuesday"
CONF_RULE_WEDNESDAY: Final = "wednesday"
CONF_RULE_THURSDAY: Final = "thursday"
CONF_RULE_FRIDAY: Final = "friday"
CONF_RULE_SATURDAY: Final = "saturday"
CONF_RULE_SUNDAY: Final = "sunday"
CONF_SELECTED_RULE: Final = "selected_rule"
CONF_CONFIRM_DELETE: Final = "confirm_delete"

DAY_TYPE_ANY: Final = "any_day"
DAY_TYPE_WORKDAY: Final = "workday"
DAY_TYPE_NON_WORKDAY: Final = "non_workday"
DAY_TYPES: Final = [DAY_TYPE_ANY, DAY_TYPE_WORKDAY, DAY_TYPE_NON_WORKDAY]

TIME_REFERENCE_FIXED: Final = "fixed_time"
TIME_REFERENCE_SUNRISE: Final = "sunrise"
TIME_REFERENCE_SUNSET: Final = "sunset"
TIME_REFERENCES: Final = [
    TIME_REFERENCE_FIXED,
    TIME_REFERENCE_SUNRISE,
    TIME_REFERENCE_SUNSET,
]

WEEKDAY_KEYS: Final = (
    CONF_RULE_MONDAY,
    CONF_RULE_TUESDAY,
    CONF_RULE_WEDNESDAY,
    CONF_RULE_THURSDAY,
    CONF_RULE_FRIDAY,
    CONF_RULE_SATURDAY,
    CONF_RULE_SUNDAY,
)

POSITION_DEFAULTS: Final = {
    CONF_OPEN_POSITION: 100,
    CONF_TIME_RULE_CLOSE_POSITION: 0,
    CONF_PREVENTIVE_POSITION: 60,
    CONF_HEAT_POSITION: 25,
    CONF_STRONG_HEAT_POSITION: 5,
    CONF_WIND_SAFE_POSITION: 100,
    CONF_STORM_SAFE_POSITION: 100,
    CONF_RAIN_SAFE_POSITION: 100,
    CONF_FROST_SAFE_POSITION: 100,
    CONF_TILT_DEFAULT_POSITION: 100,
    CONF_TILT_HEAT_POSITION: 50,
    CONF_TILT_STRONG_HEAT_POSITION: 20,
    CONF_TILT_SAFETY_POSITION: 100,
}

POSITION_SETTING_KEYS: Final = tuple(POSITION_DEFAULTS)
GLOBAL_DEFAULTS: Final = {
    CONF_SUN_ENTITY: "sun.sun",
    CONF_WEATHER_ENTITY: None,
    CONF_OUTSIDE_TEMP_SENSOR: None,
    CONF_IRRADIANCE_SENSOR: None,
    CONF_ILLUMINANCE_SENSOR: None,
    CONF_WORKDAY_ENTITY: None,
    CONF_AZIMUTH_NORTH: 0.0,
    CONF_MIN_SUN_ELEVATION: 5.0,
    CONF_SUN_HALF_ANGLE: 65.0,
    CONF_FROST_THRESHOLD: 2.0,
    CONF_FORECAST_HOURS: 6,
    CONF_EVALUATION_INTERVAL: 5,
    CONF_GLOBAL_POSITION_VALUES: dict(POSITION_DEFAULTS),
    CONF_GLOBAL_MANUAL_OVERRIDE_MINUTES: 240,
    CONF_WIND_SENSOR: None,
    CONF_WIND_PROTECTION_ENABLED: False,
    CONF_RAIN_PROTECTION_ENABLED: False,
    CONF_FROST_PROTECTION_ENABLED: True,
    CONF_RAIN_SENSOR: None,
    CONF_WIND_THRESHOLD: 45.0,
    CONF_STORM_THRESHOLD: 70.0,
    CONF_WIND_SAFE_POSITION: 100,
    CONF_STORM_SAFE_POSITION: 100,
    CONF_RAIN_SAFE_POSITION: 100,
    CONF_FROST_ACTION: "block",
    CONF_FROST_SAFE_POSITION: 100,
    CONF_PROTECTION_ACTIVATION_DELAY: 0,
    CONF_PROTECTION_RELEASE_DELAY: 15,
    CONF_SUN_EVENT_SOURCE: "location",
    CONF_DST_NONEXISTENT_POLICY: "shift_forward",
    CONF_DST_AMBIGUOUS_POLICY: "first",
}

ROOM_DEFAULTS: Final = {
    CONF_COMFORT_TEMPERATURE: 23.0,
    CONF_HEAT_TEMPERATURE: 25.0,
    CONF_STRONG_HEAT_TEMPERATURE: 27.0,
    CONF_FORECAST_THRESHOLD: 26.0,
    CONF_OPEN_POSITION: 100,
    CONF_TIME_RULE_CLOSE_POSITION: 0,
    CONF_PREVENTIVE_POSITION: 60,
    CONF_HEAT_POSITION: 25,
    CONF_STRONG_HEAT_POSITION: 5,
    CONF_WIND_SAFE_POSITION: 100,
    CONF_STORM_SAFE_POSITION: 100,
    CONF_RAIN_SAFE_POSITION: 100,
    CONF_FROST_SAFE_POSITION: 100,
    CONF_MIN_POSITION_CHANGE: 8,
    CONF_MIN_MOVE_INTERVAL: 10,
    CONF_MANUAL_OVERRIDE_MINUTES: 240,
    CONF_RISK_HYSTERESIS: 5,
    CONF_COVER_CONTACTS: {},
    CONF_TIME_RULES: [],
    CONF_DRY_RUN: False,
    CONF_TILT_CONTROL_ENABLED: False,
    CONF_TILT_DEFAULT_POSITION: 100,
    CONF_TILT_HEAT_POSITION: 50,
    CONF_TILT_STRONG_HEAT_POSITION: 20,
    CONF_TILT_SAFETY_POSITION: 100,
}

# Backwards-compatible merged defaults used by the controller.
DEFAULTS: Final = {**GLOBAL_DEFAULTS, **ROOM_DEFAULTS}

MODE_AUTOMATIC: Final = "automatic"
MODE_HEAT_PROTECTION: Final = "heat_protection"
MODE_OPEN: Final = "open"
MODE_CLOSED: Final = "closed"
MODE_PAUSE: Final = "pause"

FROST_ACTION_BLOCK: Final = "block"
FROST_ACTION_SAFE_POSITION: Final = "safe_position"
FROST_ACTIONS: Final = [FROST_ACTION_BLOCK, FROST_ACTION_SAFE_POSITION]

SUN_EVENT_SOURCE_LOCATION: Final = "location"
SUN_EVENT_SOURCE_ENTITY: Final = "configured_entity"
SUN_EVENT_SOURCES: Final = [SUN_EVENT_SOURCE_LOCATION, SUN_EVENT_SOURCE_ENTITY]

DST_NONEXISTENT_SHIFT_FORWARD: Final = "shift_forward"
DST_NONEXISTENT_SKIP: Final = "skip"
DST_NONEXISTENT_POLICIES: Final = [DST_NONEXISTENT_SHIFT_FORWARD, DST_NONEXISTENT_SKIP]
DST_AMBIGUOUS_FIRST: Final = "first"
DST_AMBIGUOUS_SECOND: Final = "second"
DST_AMBIGUOUS_POLICIES: Final = [DST_AMBIGUOUS_FIRST, DST_AMBIGUOUS_SECOND]
MODES: Final = [
    MODE_AUTOMATIC,
    MODE_HEAT_PROTECTION,
    MODE_OPEN,
    MODE_CLOSED,
    MODE_PAUSE,
]

STATUS_DISABLED: Final = "disabled"
STATUS_PAUSED: Final = "paused"
STATUS_CONTACT_PROTECTION: Final = "contact_protection"
STATUS_FROST_BLOCK: Final = "frost_block"
STATUS_FROST_PROTECTION: Final = "frost_protection"
STATUS_RAIN_PROTECTION: Final = "rain_protection"
STATUS_WIND_PROTECTION: Final = "wind_protection"
STATUS_STORM_PROTECTION: Final = "storm_protection"
STATUS_DRY_RUN: Final = "dry_run"
STATUS_MANUAL_OVERRIDE: Final = "manual_override"
STATUS_SCHEDULE: Final = "schedule"
STATUS_STRONG_HEAT: Final = "strong_heat"
STATUS_HEAT_PROTECTION: Final = "heat_protection"
STATUS_PREVENTIVE: Final = "preventive"
STATUS_SOLAR_GAIN: Final = "solar_gain"
STATUS_NORMAL: Final = "normal"
STATUS_UNAVAILABLE: Final = "unavailable"

CONTACT_NONE: Final = "none"
CONTACT_CLOSED: Final = "closed"
CONTACT_TILTED: Final = "tilted"
CONTACT_OPEN: Final = "open"
CONTACT_UNKNOWN: Final = "unknown"

SIGNAL_UPDATE: Final = f"{DOMAIN}_update_{{entry_id}}"

FORECAST_REFRESH_MINUTES: Final = 30
COMMAND_GRACE_SECONDS: Final = 180
POSITION_TOLERANCE: Final = 3
