"""State parsing helpers shared by the runtime controller."""

from __future__ import annotations

import math
from typing import Any

from homeassistant.components.cover import (
    ATTR_CURRENT_POSITION,
    ATTR_CURRENT_TILT_POSITION,
    CoverEntityFeature,
)
from homeassistant.const import (
    ATTR_UNIT_OF_MEASUREMENT,
    STATE_CLOSED,
    STATE_OPEN,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant, State
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.util.unit_conversion import TemperatureConverter


def entity_display_name(hass: HomeAssistant, entity_id: str) -> str:
    """Return the best available display name for an entity.

    State names are preferred because they already include the current friendly
    name. The entity registry is used as a startup-safe fallback before the
    source integration has published its first state.
    """
    state = hass.states.get(entity_id)
    if state is not None and state.name:
        return str(state.name)

    registry_entry = er.async_get(hass).async_get(entity_id)
    if registry_entry is not None:
        for value in (registry_entry.name, registry_entry.original_name):
            if value:
                return str(value)

    object_id = entity_id.split(".", 1)[-1]
    return object_id.replace("_", " ").strip().title()


def without_role_prefix(name: str) -> str:
    """Remove a redundant cover role prefix from a source display name."""
    cleaned = " ".join(str(name).split()).strip()
    lowered = cleaned.casefold()
    prefixes = (
        "rollladen ",
        "rollläden ",
        "rolladen ",
        "rolläden ",
        "jalousie ",
        "raffstore ",
        "cover ",
        "covers ",
        "shutter ",
        "shutters ",
        "blind ",
        "blinds ",
    )
    for prefix in prefixes:
        if lowered.startswith(prefix):
            remainder = cleaned[len(prefix):].strip()
            return remainder or cleaned
    return cleaned


def attribute_float(state: State | None, attribute: str) -> float | None:
    if state is None:
        return None
    try:
        value = state.attributes.get(attribute)
        numeric = float(value) if value is not None else None
        return numeric if numeric is not None and math.isfinite(numeric) else None
    except (OverflowError, TypeError, ValueError):
        return None


def temperature_to_celsius(value: Any, unit: Any) -> float | None:
    try:
        numeric = float(value)
        if not math.isfinite(numeric):
            return None
    except (OverflowError, TypeError, ValueError):
        return None
    source_unit = str(unit or UnitOfTemperature.CELSIUS)
    try:
        converted = float(
            TemperatureConverter.convert(
                numeric,
                source_unit,
                UnitOfTemperature.CELSIUS,
            )
        )
        return converted if math.isfinite(converted) else None
    except (HomeAssistantError, OverflowError, TypeError, ValueError):
        return None


def temperature_state(hass: HomeAssistant, entity_id: str | None) -> float | None:
    if not entity_id:
        return None
    state = hass.states.get(entity_id)
    if state is None:
        return None
    return temperature_to_celsius(
        state.state,
        state.attributes.get(ATTR_UNIT_OF_MEASUREMENT),
    )


def position_from_state(state: State | None) -> int | None:
    if state is None:
        return None
    position = attribute_float(state, ATTR_CURRENT_POSITION)
    if position is not None:
        return max(0, min(100, round(position)))
    if state.state == STATE_OPEN:
        try:
            supported = max(0, int(state.attributes.get("supported_features", 0)))
        except (OverflowError, TypeError, ValueError):
            supported = 0
        if supported & int(CoverEntityFeature.SET_POSITION):
            # OPEN means not closed; it does not confirm a percentage target.
            return None
        return 100
    if state.state == STATE_CLOSED:
        return 0
    return None


def tilt_position_from_state(state: State | None) -> int | None:
    position = attribute_float(state, ATTR_CURRENT_TILT_POSITION)
    return None if position is None else max(0, min(100, round(position)))
