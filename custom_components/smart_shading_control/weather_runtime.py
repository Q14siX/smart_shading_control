"""Weather and protection runtime for Smart Shading Control."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import datetime, timedelta
from typing import Any

from homeassistant.const import (
    ATTR_UNIT_OF_MEASUREMENT,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
)
from homeassistant.core import HomeAssistant

from .const import (
    CONF_EVALUATION_INTERVAL,
    CONF_FROST_ACTION,
    CONF_FROST_PROTECTION_ENABLED,
    CONF_FROST_SAFE_POSITION,
    CONF_FROST_THRESHOLD,
    CONF_ILLUMINANCE_SENSOR,
    CONF_IRRADIANCE_SENSOR,
    CONF_OUTSIDE_TEMP_SENSOR,
    CONF_PROTECTION_ACTIVATION_DELAY,
    CONF_PROTECTION_RELEASE_DELAY,
    CONF_RAIN_PROTECTION_ENABLED,
    CONF_RAIN_SAFE_POSITION,
    CONF_RAIN_SENSOR,
    CONF_STORM_SAFE_POSITION,
    CONF_STORM_THRESHOLD,
    CONF_WEATHER_ENTITY,
    CONF_WIND_PROTECTION_ENABLED,
    CONF_WIND_SAFE_POSITION,
    CONF_WIND_SENSOR,
    CONF_WIND_THRESHOLD,
    FROST_ACTION_SAFE_POSITION,
    STATUS_FROST_BLOCK,
    STATUS_FROST_PROTECTION,
    STATUS_RAIN_PROTECTION,
    STATUS_STORM_PROTECTION,
    STATUS_WIND_PROTECTION,
)
from .runtime_state import parse_utc_timestamp
from .schedule import normalize_boolean
from .solar import SolarInput, build_solar_input
from .state_helpers import attribute_float, temperature_state, temperature_to_celsius
from .units import (
    normalize_illuminance,
    normalize_irradiance,
    normalize_wind_speed,
    rain_is_active,
)

ConfigProvider = Callable[[], dict[str, Any]]


class WeatherRuntime:
    """Read weather inputs and maintain delayed protection state."""

    def __init__(self, hass: HomeAssistant, config_provider: ConfigProvider) -> None:
        self.hass = hass
        self._config_provider = config_provider
        self._protection_seen_since: dict[str, datetime] = {}
        self._protection_clear_since: dict[str, datetime] = {}
        self.active_protection: str | None = None

    @property
    def config(self) -> dict[str, Any]:
        return self._config_provider()

    def storage_state(self) -> dict[str, Any]:
        """Return absolute protection timers for restart-safe persistence."""
        return {
            "active": self.active_protection,
            "seen_since": {
                kind: timestamp.isoformat()
                for kind, timestamp in self._protection_seen_since.items()
            },
            "clear_since": {
                kind: timestamp.isoformat()
                for kind, timestamp in self._protection_clear_since.items()
            },
        }

    def restore_storage_state(self, raw: Any, *, now: datetime) -> None:
        """Restore protection timers without restarting their configured delays."""
        self._protection_seen_since = {}
        self._protection_clear_since = {}
        self.active_protection = None
        if not isinstance(raw, dict):
            return

        kinds = {"storm", "wind", "rain", "frost"}
        for field, target in (
            ("seen_since", self._protection_seen_since),
            ("clear_since", self._protection_clear_since),
        ):
            values = raw.get(field)
            if not isinstance(values, dict):
                continue
            for raw_kind, raw_timestamp in values.items():
                kind = str(raw_kind)
                if kind not in kinds:
                    continue
                timestamp = parse_utc_timestamp(raw_timestamp)
                # A future start timestamp cannot describe elapsed protection
                # time and is treated as corrupt rather than extending a delay.
                if timestamp is not None and timestamp <= now:
                    target[kind] = timestamp

        active = str(raw.get("active") or "")
        # A regular active protection always has either its activation marker
        # or an in-progress release marker.  Restoring only the bare enum from
        # a truncated/corrupt Store would otherwise hold that protection
        # forever while the corresponding input remains unknown.
        if active in kinds and (
            active in self._protection_seen_since
            or active in self._protection_clear_since
        ):
            self.active_protection = active

    def solar_input(self, *, now: datetime) -> SolarInput:
        """Read every solar input before choosing measured or estimated evidence."""
        config = self.config
        warnings: list[str] = []
        max_age = timedelta(minutes=max(30, int(config.get(CONF_EVALUATION_INTERVAL, 5)) * 3))

        def measurement_available(state: Any, source: str) -> bool:
            if state is None or state.state in {STATE_UNKNOWN, STATE_UNAVAILABLE}:
                return False
            # last_reported also changes when an unchanged value is republished.
            # Do not mistake a stable but freshly reported sensor for stale data.
            reported = getattr(state, "last_reported", None)
            if reported is None:
                reported = getattr(state, "last_updated", None)
            if isinstance(reported, datetime) and reported.tzinfo is not None:
                age = now - reported
                if age > max_age or age < -timedelta(minutes=5):
                    warnings.append(f"{source}_stale_or_future")
                    return False
            if normalize_boolean(state.attributes.get("restored"), False):
                warnings.append(f"{source}_restored_without_live_report")
                return False
            return True
        weather_entity = config.get(CONF_WEATHER_ENTITY)
        weather_state = self.hass.states.get(str(weather_entity)) if weather_entity else None
        weather_available = (
            weather_state is not None
            and weather_state.state not in {STATE_UNKNOWN, STATE_UNAVAILABLE}
        )
        condition = weather_state.state if weather_available else None
        cloud_coverage = attribute_float(weather_state, "cloud_coverage") if weather_available else None
        if cloud_coverage is not None and not 0.0 <= cloud_coverage <= 100.0:
            cloud_coverage = None

        irradiance_entity = config.get(CONF_IRRADIANCE_SENSOR)
        irradiance_state = self.hass.states.get(str(irradiance_entity)) if irradiance_entity else None
        irradiance = None
        if measurement_available(irradiance_state, "irradiance"):
            irradiance = normalize_irradiance(
                irradiance_state.state,
                irradiance_state.attributes.get(ATTR_UNIT_OF_MEASUREMENT),
            )

        illuminance_entity = config.get(CONF_ILLUMINANCE_SENSOR)
        illuminance_state = self.hass.states.get(str(illuminance_entity)) if illuminance_entity else None
        illuminance = None
        if measurement_available(illuminance_state, "illuminance"):
            illuminance = normalize_illuminance(
                illuminance_state.state,
                illuminance_state.attributes.get(ATTR_UNIT_OF_MEASUREMENT),
            )

        result = build_solar_input(
            condition=condition,
            cloud_coverage=cloud_coverage,
            rain_active=self.rain_active(condition),
            irradiance=irradiance,
            illuminance=illuminance,
            measurement_configured=bool(irradiance_entity or illuminance_entity),
        )
        return replace(result, input_warnings=tuple(warnings))

    def wind_speed(self) -> float | None:
        config = self.config
        entity_id = config.get(CONF_WIND_SENSOR)
        if entity_id:
            state = self.hass.states.get(str(entity_id))
            if state is None or state.state in {STATE_UNKNOWN, STATE_UNAVAILABLE}:
                return None
            return normalize_wind_speed(
                state.state, state.attributes.get(ATTR_UNIT_OF_MEASUREMENT)
            )
        weather_entity = config.get(CONF_WEATHER_ENTITY)
        state = self.hass.states.get(str(weather_entity)) if weather_entity else None
        if state is None or state.state in {STATE_UNKNOWN, STATE_UNAVAILABLE}:
            return None
        return normalize_wind_speed(
            state.attributes.get("wind_speed"),
            state.attributes.get("wind_speed_unit"),
        )

    def rain_active(self, condition: str | None) -> bool | None:
        entity_id = self.config.get(CONF_RAIN_SENSOR)
        if entity_id:
            state = self.hass.states.get(str(entity_id))
            if state is None or state.state in {STATE_UNKNOWN, STATE_UNAVAILABLE}:
                return None
            return rain_is_active(
                state.state, state.attributes.get(ATTR_UNIT_OF_MEASUREMENT)
            )
        if condition is None:
            return None
        return condition in {"rainy", "pouring", "lightning-rainy", "snowy-rainy"}

    def outside_temperature(self) -> float | None:
        config = self.config
        sensor_value = temperature_state(self.hass, config.get(CONF_OUTSIDE_TEMP_SENSOR))
        if sensor_value is not None:
            return sensor_value
        weather_entity = config.get(CONF_WEATHER_ENTITY)
        weather_state = self.hass.states.get(str(weather_entity)) if weather_entity else None
        if weather_state is None or weather_state.state in {STATE_UNKNOWN, STATE_UNAVAILABLE}:
            return None
        return temperature_to_celsius(
            weather_state.attributes.get("temperature"),
            weather_state.attributes.get("temperature_unit"),
        )

    def resolve_protection(
        self,
        now: datetime,
        *,
        outside_temperature: float | None,
        wind_speed: float | None,
        rain_active: bool | None,
    ) -> tuple[str, int | None, str] | None:
        config = self.config
        wind_enabled = normalize_boolean(config.get(CONF_WIND_PROTECTION_ENABLED), False)
        rain_enabled = normalize_boolean(config.get(CONF_RAIN_PROTECTION_ENABLED), False)
        frost_enabled = normalize_boolean(config.get(CONF_FROST_PROTECTION_ENABLED), True)
        raw: dict[str, bool | None] = {
            "storm": (
                None
                if wind_enabled and wind_speed is None
                else wind_enabled
                and wind_speed is not None
                and wind_speed >= float(config[CONF_STORM_THRESHOLD])
            ),
            "wind": (
                None
                if wind_enabled and wind_speed is None
                else wind_enabled
                and wind_speed is not None
                and wind_speed >= float(config[CONF_WIND_THRESHOLD])
            ),
            "rain": (
                None
                if rain_enabled and rain_active is None
                else rain_enabled and rain_active is True
            ),
            "frost": (
                None
                if frost_enabled and outside_temperature is None
                else frost_enabled
                and outside_temperature is not None
                and outside_temperature <= float(config[CONF_FROST_THRESHOLD])
            ),
        }
        activation = timedelta(seconds=max(0, int(config[CONF_PROTECTION_ACTIVATION_DELAY])))
        release = timedelta(minutes=max(0, int(config[CONF_PROTECTION_RELEASE_DELAY])))

        matured: set[str] = set()
        for kind, active in raw.items():
            if active is True:
                self._protection_clear_since.pop(kind, None)
                self._protection_seen_since.setdefault(kind, now)
                if now - self._protection_seen_since[kind] >= activation:
                    matured.add(kind)
            elif active is False:
                self._protection_seen_since.pop(kind, None)
                if self.active_protection == kind:
                    self._protection_clear_since.setdefault(kind, now)
                else:
                    # Release timing is meaningful only for the protection that
                    # is actually active. Keeping timestamps for every disabled
                    # input caused needless persistent-state churn.
                    self._protection_clear_since.pop(kind, None)
            else:
                self._protection_clear_since.pop(kind, None)
                # Unknown input must not count as continuous evidence toward a
                # new activation. An already active protection is retained
                # conservatively by the hold logic below.
                if self.active_protection != kind:
                    self._protection_seen_since.pop(kind, None)

        priority = ("storm", "wind", "rain", "frost")
        selected = next((kind for kind in priority if kind in matured), None)
        current = self.active_protection
        if current is not None:
            clear_since = self._protection_clear_since.get(current)
            current_is_held = (
                bool(raw.get(current))
                or clear_since is None
                or now - clear_since < release
            )
            if current_is_held:
                selected_is_higher = (
                    selected is not None
                    and priority.index(selected) < priority.index(current)
                )
                if not selected_is_higher:
                    selected = current

        self.active_protection = selected
        if selected is None:
            return None
        if selected == "storm":
            return selected, int(config[CONF_STORM_SAFE_POSITION]), STATUS_STORM_PROTECTION
        if selected == "wind":
            return selected, int(config[CONF_WIND_SAFE_POSITION]), STATUS_WIND_PROTECTION
        if selected == "rain":
            return selected, int(config[CONF_RAIN_SAFE_POSITION]), STATUS_RAIN_PROTECTION
        if str(config.get(CONF_FROST_ACTION)) == FROST_ACTION_SAFE_POSITION:
            return selected, int(config[CONF_FROST_SAFE_POSITION]), STATUS_FROST_PROTECTION
        return selected, None, STATUS_FROST_BLOCK
