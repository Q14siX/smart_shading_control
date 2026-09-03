"""Diagnostics support for Smart Shading Control."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.redact import async_redact_data

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
    CONF_ROOM_NAME,
    CONF_ROOM_TEMP_SENSOR,
    CONF_SUN_ENTITY,
    CONF_WIND_SENSOR,
    CONF_TIME_RULES,
    CONF_WEATHER_ENTITY,
    CONF_WORKDAY_ENTITY,
    ENTRY_TYPE_GLOBAL,
)
from .controller import SmartShadingController

_CONFIG_REDACT = {
    CONF_ROOM_NAME,
    CONF_ROOM_TEMP_SENSOR,
    CONF_GLOBAL_TIME_RULES,
    CONF_SUN_ENTITY,
    CONF_WIND_SENSOR,
    CONF_TIME_RULES,
    CONF_WEATHER_ENTITY,
    CONF_WORKDAY_ENTITY,
    CONF_OUTSIDE_TEMP_SENSOR,
    CONF_RAIN_SENSOR,
    CONF_IRRADIANCE_SENSOR,
    CONF_ILLUMINANCE_SENSOR,
    CONF_COVERS_NORTH,
    CONF_COVERS_EAST,
    CONF_COVERS_SOUTH,
    CONF_COVERS_WEST,
    CONF_COVER_CONTACTS,
}
_RUNTIME_REDACT = {
    "reason",
    "desired_positions",
    "commanded_positions",
    "would_command_positions",
    "commanded_tilt_positions",
    "would_command_tilt_positions",
    "actual_positions",
    "actual_tilt_positions",
    "manual_overrides",
    "manual_override_details",
    "last_manual_override_event",
    "last_manual_group_command",
    "provider_health_by_cover",
    "reason_context",
    "decision_trace",
    "decision_log",
    "contacts",
    "last_time_rule_event",
    "last_provider_error",
    "pending_time_rule_opens",
    "pending_time_rule_closes",
    "command_queue",
    "time_rule_conflicts",
    "triggered_time_rules",
    "time_rule_states",
    "sun_entity",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> dict[str, Any]:
    """Return configuration and current decision data with personal data removed."""
    base: dict[str, Any] = {
        "entry": {
            "title": "**REDACTED**",
            "data": async_redact_data(dict(entry.data), _CONFIG_REDACT),
            "options": async_redact_data(dict(entry.options), _CONFIG_REDACT),
            "version": entry.version,
            "minor_version": entry.minor_version,
        }
    }
    if str(entry.data.get(CONF_ENTRY_TYPE) or "") == ENTRY_TYPE_GLOBAL:
        base["type"] = ENTRY_TYPE_GLOBAL
        return base

    controller: SmartShadingController = entry.runtime_data
    base.update(
        {
            "type": "room",
            "effective_configuration": async_redact_data(
                controller.config, _CONFIG_REDACT
            ),
            "runtime": async_redact_data(
                dict(controller.data), _RUNTIME_REDACT
            ),
            "enabled": controller.enabled,
            "mode": controller.mode,
            "covers": "**REDACTED**",
            "decision_chronicle": controller.decision_history_export(),
        }
    )
    return base
