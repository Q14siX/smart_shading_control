"""Pure calculation helpers for Smart Shading Control."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from math import cos, isfinite, radians
from typing import Any

WEATHER_FACTORS: dict[str, float] = {
    "sunny": 1.0,
    "clear-night": 0.0,
    "partlycloudy": 0.65,
    "cloudy": 0.25,
    "fog": 0.15,
    "rainy": 0.10,
    "pouring": 0.05,
    "lightning": 0.08,
    "lightning-rainy": 0.05,
    "snowy": 0.05,
    "snowy-rainy": 0.05,
    "hail": 0.05,
    "windy": 0.55,
    "windy-variant": 0.45,
    "exceptional": 0.50,
}


def as_list(value: Any) -> list[Any]:
    """Return list-like configuration values without iterating strings."""
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, (tuple, set)):
        return list(value)
    if isinstance(value, (str, dict)):
        return [value]
    return []


def clamp(value: float, minimum: float = 0.0, maximum: float = 1.0) -> float:
    """Clamp a finite number to a range."""
    numeric = float(value)
    if not isfinite(numeric):
        return minimum
    return max(minimum, min(maximum, numeric))


def angular_difference(first: float, second: float) -> float:
    """Return the smallest difference between two azimuth angles."""
    return abs((first - second + 180.0) % 360.0 - 180.0)


def facade_azimuths(north_azimuth: float) -> dict[str, float]:
    """Derive all four orthogonal facade azimuths from the north facade.

    Home Assistant uses 0° for geographic north and increases clockwise.
    Values are normalized to the range 0°..359.999°.
    """
    north = float(north_azimuth) % 360.0
    return {
        "north": north,
        "east": (north + 90.0) % 360.0,
        "south": (north + 180.0) % 360.0,
        "west": (north + 270.0) % 360.0,
    }


def weather_factor(condition: str | None, cloud_coverage: float | None = None) -> float:
    """Estimate solar availability conservatively, not measured irradiance.

    Cloud cover may reduce a condition estimate, never turn rain, fog or an
    overcast report into sunshine. Missing weather does not imply sunshine.
    """
    condition_factor = WEATHER_FACTORS.get(condition or "", 0.0)
    if cloud_coverage is None:
        return condition_factor
    try:
        numeric_clouds = float(cloud_coverage)
    except (TypeError, ValueError):
        return condition_factor
    if not isfinite(numeric_clouds) or not 0.0 <= numeric_clouds <= 100.0:
        return condition_factor
    return min(condition_factor, clamp(1.0 - numeric_clouds / 100.0))


def sun_incidence(
    sun_azimuth: float,
    sun_elevation: float,
    facade_azimuth: float,
    half_angle: float,
    min_elevation: float,
    radiation_factor: float,
) -> float:
    """Estimate exposure of a vertical facade, not irradiance in W/m²."""
    if not all(isfinite(value) for value in (
        sun_azimuth, sun_elevation, facade_azimuth, half_angle,
        min_elevation, radiation_factor,
    )) or sun_elevation < max(0.0, min_elevation) or sun_elevation > 90.0:
        return 0.0
    difference = angular_difference(sun_azimuth, facade_azimuth)
    if difference > half_angle:
        return 0.0
    azimuth_component = max(0.0, cos(radians(difference)))
    elevation_component = max(0.0, cos(radians(sun_elevation)))
    return clamp(azimuth_component * elevation_component * radiation_factor)


def normalized_score(value: float | None, low: float, high: float) -> float:
    """Normalize a value to 0..1."""
    if value is None:
        return 0.0
    if high <= low:
        return 1.0 if value >= high else 0.0
    return clamp((value - low) / (high - low))


def is_opening_target(
    requested: float,
    current: float | None,
    configured_open_position: float,
    *,
    binary_cover: bool = False,
) -> bool:
    """Return whether a target represents opening rather than closing.

    A configured open position may intentionally be below 100 %. When the
    provider cannot report a current position, that semantic open target still
    has to remain usable.
    """
    target = int(clamp(float(requested), 0.0, 100.0))
    open_position = int(clamp(float(configured_open_position), 0.0, 100.0))
    if binary_cover and open_position > 0 and target == open_position:
        # A binary cover can report only 0/100 and can never reach a configured
        # semantic open target such as 40 %. Re-selecting that target must stay
        # an OPEN/no-op request instead of being misread as closing from 100.
        return True
    if current is not None:
        try:
            current_position = int(clamp(float(current), 0.0, 100.0))
        except (TypeError, ValueError):
            current_position = None
        if current_position is not None:
            if target > current_position:
                return True
            if target < current_position:
                return False
            # Equal targets are a no-op. Treat only a semantic configured-open
            # target as opening intent; 0 == 0 must never become an OPEN command
            # on a binary cover.
            return target == 100 or (
                open_position > 0 and target >= open_position
            )
    return target == 100 or (open_position > 0 and target >= open_position)


def manual_movement_trigger(
    *,
    old_state: str,
    new_state: str,
    old_position: int | None,
    new_position: int | None,
    external_context: bool,
    position_threshold: int = 2,
) -> str | None:
    """Classify a cover state change that evidences manual operation.

    Command-related updates and provider-recovery events must be filtered by the
    caller before using this helper. Some physical wall switches and gateways do
    not publish an intermediate ``opening``/``closing`` state or HA context; a
    meaningful stationary position change therefore remains valid evidence.
    """
    moving_states = {"opening", "closing"}
    meaningful_position_change = (
        old_position is not None
        and new_position is not None
        and abs(new_position - old_position) >= max(1, int(position_threshold))
    )
    movement_started = old_state != new_state and new_state in moving_states
    movement_stopped = old_state in moving_states and new_state not in moving_states
    explicit_terminal_command = (
        external_context
        and old_state != new_state
        and new_state in {"open", "closed"}
    )
    confirmed_position_change = meaningful_position_change and (
        external_context or old_state in moving_states or new_state in moving_states
    )
    stationary_position_change = (
        meaningful_position_change
        and old_state not in moving_states
        and new_state not in moving_states
    )

    if movement_started:
        return "movement_started"
    if movement_stopped:
        return "movement_stopped"
    if explicit_terminal_command:
        return "external_context"
    if confirmed_position_change:
        return "position_changed_while_moving"
    if stationary_position_change:
        return "stationary_position_change"
    return None


def binary_cover_target(
    requested: float,
    *,
    safety_forced: bool = False,
    opening_requested: bool | None = None,
) -> int:
    """Map a target to OPEN/CLOSED for covers without position support.

    The requested percentage alone does not describe the movement direction:
    moving from 30 to 40 percent is opening, while moving from 80 to 60 percent
    is closing. Callers that know the current position therefore pass the
    semantic direction. The 50-percent fallback is retained only for legacy
    callers without that context. A positive safety target always opens.
    """
    target = int(clamp(float(requested), 0.0, 100.0))
    if safety_forced and target > 0:
        return 100
    if opening_requested is not None:
        return 100 if opening_requested else 0
    return 0 if target <= 50 else 100


def calculate_heat_risk(
    *,
    room_temperature: float | None,
    outside_temperature: float | None,
    forecast_max: float | None,
    sun_load: float,
    temperature_trend: float,
    comfort_temperature: float,
    heat_temperature: float,
    forecast_threshold: float,
) -> int:
    """Calculate thermal pressure; the solar eligibility gate is separate.

    A cooler exterior is only a potential for heat loss, not proof of open
    windows or ventilation. Its modest discount cannot veto measured solar
    gains. An observed falling room temperature supplies separate evidence.
    """
    room_score = normalized_score(room_temperature, comfort_temperature, heat_temperature + 1.5)
    forecast_score = normalized_score(forecast_max, forecast_threshold - 2.0, forecast_threshold + 6.0)
    outside_score = normalized_score(outside_temperature, comfort_temperature, heat_temperature + 5.0)
    trend_score = normalized_score(max(0.0, temperature_trend), 0.0, 1.5)
    solar_score = clamp(sun_load)

    score = (
        room_score * 35.0
        + forecast_score * 25.0
        + outside_score * 15.0
        + solar_score * 15.0
        + trend_score * 10.0
    )
    cooling_potential = (
        normalized_score(room_temperature - outside_temperature, 2.0, 10.0)
        if room_temperature is not None and outside_temperature is not None
        else 0.0
    )
    falling_trend = normalized_score(max(0.0, -temperature_trend), 0.0, 1.5)
    score -= cooling_potential * 10.0 + falling_trend * 10.0
    return round(clamp(score, 0.0, 100.0))


def choose_dynamic_level(
    risk: int,
    previous_level: str | None,
    hysteresis: int,
) -> str:
    """Choose a level with immediate escalation and delayed de-escalation."""
    enter = {"preventive": 35, "heat": 55, "strong": 75}
    exit_threshold = {key: value - hysteresis for key, value in enter.items()}

    # Escalation must never be blocked by the previously active lower level.
    if risk >= enter["strong"]:
        return "strong"
    if previous_level == "strong" and risk >= exit_threshold["strong"]:
        return "strong"

    if risk >= enter["heat"]:
        return "heat"
    if previous_level in {"strong", "heat"} and risk >= exit_threshold["heat"]:
        return "heat"

    if risk >= enter["preventive"]:
        return "preventive"
    if previous_level in {"strong", "heat", "preventive"} and risk >= exit_threshold["preventive"]:
        return "preventive"

    return "normal"


def allow_solar_gain(
    *,
    risk: int,
    room_temperature: float | None,
    outside_temperature: float | None,
    forecast_max: float | None,
    comfort_temperature: float,
    forecast_threshold: float,
) -> bool:
    """Return whether direct sun may intentionally warm a cool room."""
    return (
        risk < 35
        and room_temperature is not None
        and room_temperature < comfort_temperature - 0.5
        and outside_temperature is not None
        and outside_temperature < comfort_temperature
        and (forecast_max is None or forecast_max < forecast_threshold - 2.0)
    )


def forecast_max_temperature(
    forecast: list[dict[str, Any]],
    hours: int,
    *,
    now: datetime | None = None,
    forecast_type: str | None = None,
) -> float | None:
    """Return the maximum temperature from the selected forecast horizon."""
    horizon = max(1, hours)
    timestamped = now is not None and any(
        isinstance(item, dict) and "datetime" in item for item in forecast
    )
    if timestamped:
        if now.tzinfo is None:
            raise ValueError("forecast evaluation requires a timezone-aware time")
        now_utc = now.astimezone(timezone.utc)
        end_utc = now_utc + timedelta(hours=horizon)
        period = timedelta(hours=12 if forecast_type == "twice_daily" else 1)
        selected: list[dict[str, Any]] = []
        for item in forecast:
            if not isinstance(item, dict):
                continue
            try:
                timestamp = datetime.fromisoformat(str(item.get("datetime")))
                if timestamp.tzinfo is None:
                    continue
                if forecast_type == "daily":
                    # A daily maximum applies to its local calendar day even when
                    # the provider's timestamp for today precedes the current hour.
                    event_date = timestamp.astimezone(now.tzinfo).date()
                    if not now.date() <= event_date <= end_utc.astimezone(now.tzinfo).date():
                        continue
                else:
                    timestamp_utc = timestamp.astimezone(timezone.utc)
                    if timestamp_utc > end_utc or timestamp_utc + period <= now_utc:
                        continue
            except (OverflowError, TypeError, ValueError):
                # A parseable provider date can overflow during timezone
                # conversion. Ignore that entry without losing valid siblings.
                continue
            selected.append(item)
    else:
        # Older stored forecasts may lack timestamps. Preserve their bounded
        # fallback until the next provider refresh supplies dated entries.
        count = horizon
        if now is not None and forecast_type in {"daily", "twice_daily"}:
            period_hours = 24 if forecast_type == "daily" else 12
            count = max(1, (horizon + period_hours - 1) // period_hours + 1)
        selected = forecast[:count]
    values: list[float] = []
    for item in selected:
        if not isinstance(item, dict):
            continue
        value = item.get("temperature")
        try:
            if value is not None:
                numeric = float(value)
                if isfinite(numeric):
                    values.append(numeric)
        except (OverflowError, TypeError, ValueError):
            continue
    return max(values) if values else None
