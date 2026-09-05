"""Source-aware solar evidence and per-facade heat decisions.

The thresholds below are conservative control heuristics, not a thermal model
of the building. Illuminance and weather estimates are never treated as a
measurement of energy arriving at a window.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from .logic import (
    allow_solar_gain,
    calculate_heat_risk,
    choose_dynamic_level,
    clamp,
    weather_factor,
)

IRRADIANCE_ENTER = 200.0
IRRADIANCE_HOLD = 160.0
IRRADIANCE_STRONG_ENTER = 400.0
IRRADIANCE_STRONG_HOLD = 350.0
ILLUMINANCE_ENTER = 30000.0
ILLUMINANCE_HOLD = 24000.0
ILLUMINANCE_STRONG_ENTER = 45000.0
ILLUMINANCE_STRONG_HOLD = 40000.0
WEATHER_ENTER = 0.40
WEATHER_HOLD = 0.32
WEATHER_STRONG_ENTER = 0.65
WEATHER_STRONG_HOLD = 0.55
FACADE_ENTER = 0.12
FACADE_HOLD = 0.09
FACADE_STRONG_ENTER = 0.25
FACADE_STRONG_HOLD = 0.20
TEMPERATURE_HYSTERESIS = 0.3
_OBSCURED_CONDITIONS = frozenset({
    "clear-night", "cloudy", "fog", "rainy", "pouring", "lightning",
    "lightning-rainy", "snowy", "snowy-rainy", "hail", "exceptional",
})


@dataclass(frozen=True)
class SolarInput:
    """One numeric, privacy-safe snapshot of the available solar evidence."""

    condition: str | None
    cloud_coverage: float | None
    rain_active: bool | None
    source: str
    radiation_factor: float
    irradiance_w_m2: float | None = None
    illuminance_lux: float | None = None
    blocked_reason: str | None = None
    input_warnings: tuple[str, ...] = ()

    def diagnostics(self) -> dict[str, Any]:
        return asdict(self)

    def permits_shading(self, previous_level: str | None) -> bool:
        """Require evidence before temperature or forecast may select a level."""
        if self.blocked_reason:
            return False
        holding = previous_level in {"preventive", "heat", "strong"}
        if self.source == "irradiance":
            threshold = IRRADIANCE_HOLD if holding else IRRADIANCE_ENTER
            return self.irradiance_w_m2 is not None and self.irradiance_w_m2 >= threshold
        if self.source == "illuminance":
            threshold = ILLUMINANCE_HOLD if holding else ILLUMINANCE_ENTER
            return (
                self.illuminance_lux is not None
                and self.illuminance_lux >= threshold
                and self.radiation_factor >= (WEATHER_HOLD if holding else WEATHER_ENTER)
            )
        return self.source == "weather" and self.radiation_factor >= (
            WEATHER_HOLD if holding else WEATHER_ENTER
        )

    def permits_strong(self, previous_level: str | None) -> bool:
        """Near-closure needs stronger evidence than ordinary shading."""
        if self.blocked_reason:
            return False
        holding = previous_level == "strong"
        if self.source == "irradiance":
            threshold = IRRADIANCE_STRONG_HOLD if holding else IRRADIANCE_STRONG_ENTER
            return self.irradiance_w_m2 is not None and self.irradiance_w_m2 >= threshold
        if self.source == "illuminance":
            threshold = ILLUMINANCE_STRONG_HOLD if holding else ILLUMINANCE_STRONG_ENTER
            if self.illuminance_lux is None or self.illuminance_lux < threshold:
                return False
        return self.source in {"illuminance", "weather"} and self.radiation_factor >= (
            WEATHER_STRONG_HOLD if holding else WEATHER_STRONG_ENTER
        )


def build_solar_input(
    *,
    condition: str | None,
    cloud_coverage: float | None,
    rain_active: bool | None,
    irradiance: float | None,
    illuminance: float | None,
    measurement_configured: bool = False,
) -> SolarInput:
    """Fuse normalized inputs without making rain/clouds disappear behind lux.

    A valid irradiance measurement is energy evidence in its own right; even
    under clouds or during a sun shower it can justify shading. Invalid or
    unavailable configured measurements do not silently become synthetic sun.
    """
    common = {
        "condition": condition,
        "cloud_coverage": cloud_coverage,
        "rain_active": rain_active,
        "irradiance_w_m2": irradiance,
        "illuminance_lux": illuminance,
    }
    if irradiance is not None:
        return SolarInput(
            **common, source="irradiance", radiation_factor=clamp(irradiance / 800.0)
        )

    factor = weather_factor(condition, cloud_coverage)
    if illuminance is not None:
        source = "illuminance"
        measured_factor = clamp(illuminance / 60000.0)
        factor = min(measured_factor, factor) if condition is not None else measured_factor
    elif measurement_configured:
        return SolarInput(
            **common, source="unavailable", radiation_factor=0.0,
            blocked_reason="solar_measurement_unavailable",
        )
    else:
        source = "weather" if condition is not None else "unavailable"

    blocked = None
    if rain_active is True or condition in {
        "rainy", "pouring", "lightning-rainy", "snowy-rainy",
    }:
        factor = min(factor, 0.10)
        blocked = "rain_without_measured_irradiance"
    elif condition in _OBSCURED_CONDITIONS or (
        cloud_coverage is not None and cloud_coverage >= 85.0
    ):
        blocked = "overcast_without_measured_irradiance"
    elif source == "unavailable":
        blocked = "solar_data_unavailable"
    elif source == "illuminance" and condition is None:
        blocked = "weather_data_unavailable"

    return SolarInput(
        **common, source=source, radiation_factor=factor, blocked_reason=blocked,
    )


@dataclass(frozen=True)
class FacadeHeatAssessment:
    """Separate thermal pressure, solar eligibility and the resulting level."""

    risk: int
    level: str
    solar_eligible: bool
    strong_solar_eligible: bool
    incidence: float
    reason: str

    def diagnostics(self) -> dict[str, Any]:
        return asdict(self)


def assess_facade_heat(
    *,
    solar: SolarInput,
    incidence: float,
    daylight: bool,
    previous_level: str | None,
    room_temperature: float | None,
    outside_temperature: float | None,
    forecast_max: float | None,
    temperature_trend: float,
    comfort_temperature: float,
    heat_temperature: float,
    strong_heat_temperature: float,
    forecast_threshold: float,
    risk_hysteresis: int,
    geometry_valid: bool = True,
) -> FacadeHeatAssessment:
    """Assess one facade; a hot room alone never creates solar eligibility."""
    risk = calculate_heat_risk(
        room_temperature=room_temperature,
        outside_temperature=outside_temperature,
        forecast_max=forecast_max,
        sun_load=incidence,
        temperature_trend=temperature_trend,
        comfort_temperature=comfort_temperature,
        heat_temperature=heat_temperature,
        forecast_threshold=forecast_threshold,
    )
    holding = previous_level in {"preventive", "heat", "strong"}
    minimum = FACADE_HOLD if holding else FACADE_ENTER
    if not daylight:
        reason = "sun_below_minimum_elevation"
    elif (
        not geometry_valid
        or room_temperature is None
        or solar.source == "unavailable"
        or solar.blocked_reason == "weather_data_unavailable"
    ):
        reason = (
            "sun_geometry_unavailable" if not geometry_valid
            else "room_temperature_unavailable" if room_temperature is None
            else solar.blocked_reason or "solar_data_unavailable"
        )
        return FacadeHeatAssessment(risk, "hold", False, False, incidence, reason)
    elif incidence < minimum:
        reason = solar.blocked_reason or "insufficient_facade_exposure"
    elif not solar.permits_shading(previous_level):
        reason = solar.blocked_reason or "insufficient_solar_evidence"
    else:
        reason = None
    if reason is not None:
        return FacadeHeatAssessment(risk, "normal", False, False, incidence, reason)

    strong_solar = (
        solar.permits_strong(previous_level)
        and incidence >= (
            FACADE_STRONG_HOLD if previous_level == "strong" else FACADE_STRONG_ENTER
        )
    )
    if allow_solar_gain(
        risk=risk,
        room_temperature=room_temperature,
        outside_temperature=outside_temperature,
        forecast_max=forecast_max,
        comfort_temperature=comfort_temperature,
        forecast_threshold=forecast_threshold,
    ):
        return FacadeHeatAssessment(risk, "solar_gain", True, strong_solar, incidence, "solar_gain")

    level = choose_dynamic_level(risk, previous_level, risk_hysteresis)
    strong_threshold = strong_heat_temperature - (
        TEMPERATURE_HYSTERESIS if previous_level == "strong" else 0.0
    )
    heat_threshold = heat_temperature - (
        TEMPERATURE_HYSTERESIS if previous_level in {"heat", "strong"} else 0.0
    )
    if room_temperature >= strong_threshold and strong_solar:
        level = "strong"
    elif room_temperature >= heat_threshold and level in {"normal", "preventive"}:
        level = "heat"
    if level == "strong" and not strong_solar:
        level = "heat"
    return FacadeHeatAssessment(risk, level, True, strong_solar, incidence, f"solar_{level}")
