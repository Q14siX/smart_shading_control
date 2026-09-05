"""Unit normalization helpers for Smart Shading Control."""

from __future__ import annotations

import math
from typing import Any


def _unit(value: Any) -> str:
    return (
        str(value or "")
        .strip()
        .lower()
        .replace(" ", "")
        .replace("²", "2")
        .replace("^2", "2")
    )


def normalize_irradiance(value: Any, unit: Any) -> float | None:
    """Return irradiance in W/m².

    Unitless values are accepted as W/m² for backwards compatibility. Unknown
    units are rejected instead of being silently interpreted incorrectly.
    """
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(numeric) or numeric < 0:
        return None
    normalized = _unit(unit)
    if normalized in {"", "w/m2", "w/m²", "w·m-2", "wm-2"}:
        return numeric
    if normalized in {"kw/m2", "kw/m²", "kw·m-2", "kwm-2"}:
        converted = numeric * 1000.0
        return converted if math.isfinite(converted) else None
    return None


def normalize_illuminance(value: Any, unit: Any) -> float | None:
    """Return illuminance in lux."""
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(numeric) or numeric < 0:
        return None
    normalized = _unit(unit)
    if normalized in {"", "lx", "lux"}:
        return numeric
    if normalized in {"klx", "kilolux"}:
        converted = numeric * 1000.0
        return converted if math.isfinite(converted) else None
    return None


def normalize_wind_speed(value: Any, unit: Any) -> float | None:
    """Return wind speed in km/h."""
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(numeric) or numeric < 0:
        return None
    normalized = _unit(unit)
    if normalized in {"", "km/h", "kmh", "kph"}:
        return numeric
    if normalized in {"m/s", "mps", "ms-1"}:
        return numeric * 3.6
    if normalized in {"mph", "mi/h"}:
        return numeric * 1.609344
    if normalized in {"kn", "kt", "kts", "knot", "knots"}:
        return numeric * 1.852
    return None


def rain_is_active(value: Any, unit: Any = None) -> bool | None:
    """Interpret a binary or numeric rain sensor."""
    if value is None:
        return None
    normalized_value = str(value).strip().lower()
    if normalized_value in {"on", "true", "yes", "wet", "rain", "raining"}:
        return True
    if normalized_value in {"off", "false", "no", "dry", "none"}:
        return False
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(numeric) or numeric < 0:
        return None
    # Any positive precipitation rate/amount means rain is present. The exact
    # unit is not relevant to this binary safety decision.
    return numeric > 0.0
