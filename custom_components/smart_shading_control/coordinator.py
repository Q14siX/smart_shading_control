"""Shared global data coordinator for Smart Shading Control."""

from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timedelta
from typing import Any

from homeassistant.components.weather.const import WeatherEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    ATTR_ENTITY_ID,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
)
from homeassistant.core import CoreState, HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .const import (
    CONF_WEATHER_ENTITY,
    DOMAIN,
    FORECAST_REFRESH_MINUTES,
)
from .global_repairs import update_global_repairs
from .state_helpers import temperature_to_celsius

_LOGGER = logging.getLogger(__name__)

COORDINATOR_KEY = "global_coordinator"
_PROVIDER_TIMEOUT_SECONDS = 10
_WORKDAY_RETRY_SECONDS = 30


class SmartShadingDataCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Load central forecast and Workday data once for every room."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry | None,
        config: dict[str, Any],
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=None,
            name=f"{DOMAIN}_shared_data",
            update_interval=timedelta(minutes=FORECAST_REFRESH_MINUTES),
            always_update=False,
        )
        self.entry = entry
        self.config = dict(config)
        self._workday_cache: dict[tuple[str, str], bool] = {}
        self._workday_retry_after: dict[str, datetime] = {}
        self._workday_lock = asyncio.Lock()
        self._initial_refresh_lock = asyncio.Lock()
        self._ready = False
        self._last_attempt: datetime | None = None
        self._config_revision = 0
        self.data = {
            "forecast": [],
            "forecast_updated": None,
            "forecast_type": None,
            "weather_entity": None,
            "last_error": None,
            "last_error_retryable": False,
        }

    def update_config(self, entry: ConfigEntry | None, config: dict[str, Any]) -> None:
        """Update central configuration without replacing the coordinator."""
        previous_weather = self.config.get(CONF_WEATHER_ENTITY)
        if self.entry is not entry or self.config != config:
            self._config_revision += 1
        self.entry = entry
        self.config = dict(config)
        if previous_weather != self.config.get(CONF_WEATHER_ENTITY):
            self._ready = False
            # An old provider call may still be awaiting its response. Clear
            # its published data now so neither diagnostics nor another room
            # can consume that provider after the configuration changed.
            self.data = {
                "forecast": [],
                "forecast_updated": None,
                "forecast_type": None,
                "weather_entity": (
                    str(self.config[CONF_WEATHER_ENTITY])
                    if self.config.get(CONF_WEATHER_ENTITY)
                    else None
                ),
                "last_error": None,
                "last_error_retryable": False,
            }
            self._last_attempt = None

    async def async_ensure_ready(self, *, force: bool = False) -> None:
        """Perform one shared refresh after Home Assistant finished starting."""
        async with self._initial_refresh_lock:
            expected_source = (
                str(self.config.get(CONF_WEATHER_ENTITY))
                if self.config.get(CONF_WEATHER_ENTITY)
                else None
            )
            current_source = (self.data or {}).get("weather_entity")
            if not force and self._ready and current_source == expected_source:
                return
            if (
                force
                and self._last_attempt is not None
                and current_source == expected_source
            ):
                age = (dt_util.utcnow() - self._last_attempt).total_seconds()
                if age < 30:
                    return
            await self.async_refresh()
            self._ready = bool(
                self.last_update_success
                and (self.data or {}).get("weather_entity")
                == (
                    str(self.config[CONF_WEATHER_ENTITY])
                    if self.config.get(CONF_WEATHER_ENTITY)
                    else None
                )
                and self._last_attempt is not None
            )

    async def _async_update_data(self) -> dict[str, Any]:
        """Load the best forecast type supported by the configured entity."""
        self._last_attempt = dt_util.utcnow()
        config_revision = self._config_revision
        weather_entity = self.config.get(CONF_WEATHER_ENTITY)
        previous = self.data or {}
        normalized_weather_entity = str(weather_entity) if weather_entity else None
        same_weather_source = previous.get("weather_entity") == normalized_weather_entity
        result = {
            # Never carry forecast data from a previously configured provider
            # into the diagnostics or decisions of a new weather entity.
            "forecast": (
                [dict(item) for item in previous.get("forecast", [])]
                if same_weather_source
                else []
            ),
            "forecast_updated": (
                previous.get("forecast_updated") if same_weather_source else None
            ),
            "forecast_type": (
                previous.get("forecast_type") if same_weather_source else None
            ),
            "weather_entity": normalized_weather_entity,
            "last_error": None,
            "last_error_retryable": False,
        }
        if not weather_entity:
            result["forecast"] = []
            result["forecast_updated"] = dt_util.utcnow().isoformat()
            result["forecast_type"] = None
            update_global_repairs(
                self.hass,
                self.entry,
                self.config,
                forecast_error=None,
            )
            return result

        entity_id = str(weather_entity)
        weather_state = self.hass.states.get(entity_id)
        if weather_state is None or weather_state.state in {
            STATE_UNKNOWN,
            STATE_UNAVAILABLE,
        }:
            result["last_error"] = "weather_entity_unavailable"
            result["last_error_retryable"] = True
            _LOGGER.debug(
                "Weather forecast deferred because %s is not available",
                entity_id,
            )
            update_global_repairs(
                self.hass,
                self.entry,
                self.config,
                forecast_error=result["last_error"],
            )
            return result

        try:
            supported = int(weather_state.attributes.get("supported_features", 0))
        except (OverflowError, TypeError, ValueError):
            supported = 0

        candidates: list[str] = []
        if supported & int(WeatherEntityFeature.FORECAST_HOURLY):
            candidates.append("hourly")
        if supported & int(WeatherEntityFeature.FORECAST_DAILY):
            candidates.append("daily")
        if supported & int(WeatherEntityFeature.FORECAST_TWICE_DAILY):
            candidates.append("twice_daily")

        if not candidates:
            # A weather entity can still provide useful current conditions even
            # when its provider exposes no forecast feature. This is therefore
            # not a broken configuration and must not create a Repairs error.
            result["forecast"] = []
            result["forecast_updated"] = None
            result["forecast_type"] = None
            result["last_error"] = None
            result["last_error_retryable"] = False
            _LOGGER.debug(
                "Weather entity %s provides current conditions without forecasts",
                entity_id,
            )
            update_global_repairs(
                self.hass,
                self.entry,
                self.config,
                forecast_error=None,
            )
            return result

        errors: list[str] = []
        for forecast_type in candidates:
            try:
                async with asyncio.timeout(_PROVIDER_TIMEOUT_SECONDS):
                    response = await self.hass.services.async_call(
                        "weather",
                        "get_forecasts",
                        {"type": forecast_type},
                        target={ATTR_ENTITY_ID: entity_id},
                        blocking=True,
                        return_response=True,
                    )
                if config_revision != self._config_revision:
                    return dict(self.data or {})
                weather_data = (response or {}).get(entity_id, {})
                if not isinstance(weather_data, dict) or not isinstance(
                    weather_data.get("forecast"), list
                ):
                    raise TypeError("Weather service returned an invalid forecast")
                temperature_unit = weather_state.attributes.get("temperature_unit")
                forecast: list[dict[str, Any]] = []
                for raw_item in weather_data.get("forecast") or []:
                    if not isinstance(raw_item, dict):
                        continue
                    item = dict(raw_item)
                    converted = temperature_to_celsius(
                        item.get("temperature"), temperature_unit
                    )
                    if converted is None:
                        item.pop("temperature", None)
                    else:
                        item["temperature"] = converted
                    forecast.append(item)
                result["forecast"] = forecast
                result["forecast_updated"] = dt_util.utcnow().isoformat()
                result["forecast_type"] = forecast_type
                result["last_error"] = None
                result["last_error_retryable"] = False
                update_global_repairs(
                    self.hass,
                    self.entry,
                    self.config,
                    forecast_error=None,
                )
                return result
            except Exception as err:
                if config_revision != self._config_revision:
                    return dict(self.data or {})
                errors.append(f"{forecast_type}: {type(err).__name__}: {err}")
                _LOGGER.debug(
                    "Shared %s forecast could not be loaded from %s",
                    forecast_type,
                    entity_id,
                    exc_info=True,
                )
                if isinstance(err, TimeoutError):
                    # Different forecast types use the same provider. Do not
                    # multiply its timeout while room evaluations await us.
                    break

        # Keep a previously valid forecast only for the same provider. A later
        # evaluation retries after the entity/provider had time to settle.
        result["forecast_type"] = (
            previous.get("forecast_type") if same_weather_source else None
        )
        result["last_error"] = "; ".join(errors)
        result["last_error_retryable"] = True
        if previous.get("last_error") != result["last_error"]:
            _LOGGER.warning(
                "Shared forecast could not be loaded from %s: %s",
                entity_id,
                result["last_error"],
            )
        update_global_repairs(
            self.hass,
            self.entry,
            self.config,
            forecast_error=result["last_error"],
        )
        return result

    @property
    def forecast(self) -> list[dict[str, Any]]:
        """Return a defensive copy of the current provider forecast."""
        return [dict(item) for item in (self.data or {}).get("forecast", [])]

    async def async_prepare_workday_dates(
        self,
        local_now: datetime,
        rules: list[dict[str, Any]],
        entity_id: str | None,
        current_state: bool | None,
        day_type_key: str,
        any_day_value: str,
    ) -> None:
        """Cache Workday results for calendar dates used by time-rule events."""
        if not entity_id:
            return
        if not any(
            str(rule.get(day_type_key) or any_day_value) != any_day_value
            for rule in rules
        ):
            return
        if current_state is not None:
            self._workday_cache[(entity_id, local_now.date().isoformat())] = current_state

        # Event rules derive the current closure state from the latest weekly
        # occurrence. Cache enough dates for an eight-day lookback plus solar
        # offsets that can cross midnight.
        needed_dates = [
            local_now.date() + timedelta(days=delta) for delta in range(-9, 2)
        ]
        async with self._workday_lock:
            retry_after = self._workday_retry_after.get(entity_id)
            if retry_after is not None and retry_after > dt_util.utcnow():
                return
            self._workday_retry_after.pop(entity_id, None)
            for check_date in needed_dates:
                key = (entity_id, check_date.isoformat())
                if key in self._workday_cache:
                    continue
                try:
                    async with asyncio.timeout(_PROVIDER_TIMEOUT_SECONDS):
                        response = await self.hass.services.async_call(
                            "workday",
                            "check_date",
                            {"check_date": check_date.isoformat()},
                            target={ATTR_ENTITY_ID: entity_id},
                            blocking=True,
                            return_response=True,
                        )
                    value = (response or {}).get(entity_id, {}).get("workday")
                    if isinstance(value, bool):
                        self._workday_cache[key] = value
                except Exception:
                    self._workday_retry_after[entity_id] = (
                        dt_util.utcnow() + timedelta(seconds=_WORKDAY_RETRY_SECONDS)
                    )
                    _LOGGER.debug(
                        "Could not check Workday state for %s on %s",
                        entity_id,
                        check_date,
                        exc_info=True,
                    )
                    # Other rooms share this provider and cache. One outage
                    # must not cause eleven waits per room per evaluation.
                    break
        cutoff = local_now.date() - timedelta(days=14)
        for key in list(self._workday_cache):
            try:
                cached_date = date.fromisoformat(key[1])
            except (IndexError, TypeError, ValueError):
                self._workday_cache.pop(key, None)
                continue
            if cached_date < cutoff:
                self._workday_cache.pop(key, None)

    def workday_for_date(self, entity_id: str | None, target_date: date) -> bool | None:
        """Return one cached Workday result."""
        if not entity_id:
            return None
        return self._workday_cache.get((str(entity_id), target_date.isoformat()))


async def async_get_or_create_coordinator(
    hass: HomeAssistant,
    entry: ConfigEntry | None,
    config: dict[str, Any],
) -> SmartShadingDataCoordinator:
    """Return the single integration-wide coordinator."""
    runtime = hass.data.setdefault(DOMAIN, {})
    coordinator = runtime.get(COORDINATOR_KEY)
    if not isinstance(coordinator, SmartShadingDataCoordinator):
        coordinator = SmartShadingDataCoordinator(hass, entry, config)
        runtime[COORDINATOR_KEY] = coordinator
        await coordinator.async_register_shutdown()
        if hass.state is CoreState.running:
            await coordinator.async_ensure_ready()
    else:
        previous_entry_id = (
            coordinator.entry.entry_id if coordinator.entry is not None else None
        )
        coordinator.update_config(entry, config)
        current_entry_id = entry.entry_id if entry is not None else None
        if hass.state is CoreState.running and (
            previous_entry_id != current_entry_id
            or not coordinator.last_update_success
            or (coordinator.data or {}).get("weather_entity")
            != (
                str(config.get(CONF_WEATHER_ENTITY))
                if config.get(CONF_WEATHER_ENTITY)
                else None
            )
        ):
            await coordinator.async_ensure_ready(force=True)
    return coordinator
