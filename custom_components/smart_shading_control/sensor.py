"""Sensor platform for Smart Shading Control."""

from __future__ import annotations

from typing import Any, ClassVar

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    ATTR_UNIT_OF_MEASUREMENT,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
    UnitOfRatio,
    UnitOfTemperature,
    UnitOfTime,
)
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.util import dt as dt_util

from .const import (
    CONF_COVER_CONTACTS,
    CONF_ROOM_TEMP_SENSOR,
    CONTACT_CLOSED,
    CONTACT_OPEN,
    CONTACT_TILTED,
    CONTACT_UNKNOWN,
    STATUS_CONTACT_PROTECTION,
    STATUS_DISABLED,
    STATUS_DRY_RUN,
    STATUS_FROST_BLOCK,
    STATUS_FROST_PROTECTION,
    STATUS_HEAT_PROTECTION,
    STATUS_MANUAL_OVERRIDE,
    STATUS_NORMAL,
    STATUS_PAUSED,
    STATUS_PREVENTIVE,
    STATUS_RAIN_PROTECTION,
    STATUS_SCHEDULE,
    STATUS_SOLAR_GAIN,
    STATUS_STORM_PROTECTION,
    STATUS_STRONG_HEAT,
    STATUS_UNAVAILABLE,
    STATUS_WIND_PROTECTION,
)
from .contacts import classify_contact_state
from .controller import SmartShadingController
from .cover import (
    legacy_source_unique_id,
    migrate_legacy_source_unique_id,
    remove_stale_dynamic_entities,
    source_entity_registry_key,
)
from .entity import SmartShadingEntity
from .state_helpers import (
    entity_display_name,
    temperature_state,
    without_role_prefix,
)

PARALLEL_UPDATES = 0

REASON_CODES = [
    "initializing",
    "no_covers",
    "control_disabled",
    "mode_pause",
    "mode_open",
    "mode_closed",
    "mode_heat_protection",
    "time_rule_event",
    "time_rule_open_retry",
    "time_rule_open_skipped_heat_protection",
    "time_rule_closed",
    "time_rule_close_blocked_contact",
    "time_rule_close_contact_delay",
    "all_manual_override",
    "storm_protection",
    "wind_protection",
    "rain_protection",
    "frost_protection",
    "dry_run",
    "dynamic_strong_heat",
    "dynamic_heat_protection",
    "dynamic_preventive",
    "dynamic_solar_gain",
    "dynamic_normal",
    "dynamic_no_solar_heat_gain",
    "dynamic_inputs_unavailable",
]

SENSOR_DESCRIPTIONS = (
    SensorEntityDescription(
        key="status",
        translation_key="status",
        icon="mdi:blinds-horizontal",
        device_class=SensorDeviceClass.ENUM,
        options=[
            STATUS_DISABLED,
            STATUS_PAUSED,
            STATUS_CONTACT_PROTECTION,
            STATUS_FROST_BLOCK,
            STATUS_FROST_PROTECTION,
            STATUS_RAIN_PROTECTION,
            STATUS_WIND_PROTECTION,
            STATUS_STORM_PROTECTION,
            STATUS_DRY_RUN,
            STATUS_MANUAL_OVERRIDE,
            STATUS_SCHEDULE,
            STATUS_STRONG_HEAT,
            STATUS_HEAT_PROTECTION,
            STATUS_PREVENTIVE,
            STATUS_SOLAR_GAIN,
            STATUS_NORMAL,
            STATUS_UNAVAILABLE,
        ],
    ),
    SensorEntityDescription(
        key="reason_code",
        translation_key="reason_code",
        icon="mdi:source-branch-check",
        device_class=SensorDeviceClass.ENUM,
        options=REASON_CODES,
    ),
    SensorEntityDescription(
        key="heat_risk",
        translation_key="heat_risk",
        icon="mdi:thermometer-alert",
        native_unit_of_measurement=UnitOfRatio.PERCENTAGE,
    ),
    SensorEntityDescription(
        key="sun_load",
        translation_key="sun_load",
        icon="mdi:white-balance-sunny",
        native_unit_of_measurement=UnitOfRatio.PERCENTAGE,
    ),
    SensorEntityDescription(
        key="forecast_age",
        translation_key="forecast_age",
        icon="mdi:clock-alert-outline",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SensorEntityDescription(
        key="pending_time_rule_open_count",
        translation_key="pending_time_rule_open_count",
        icon="mdi:calendar-clock-outline",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SensorEntityDescription(
        key="pending_time_rule_close_count",
        translation_key="pending_time_rule_close_count",
        icon="mdi:window-open-variant",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SensorEntityDescription(
        key="next_time_rule_close_retry",
        translation_key="next_time_rule_close_retry",
        icon="mdi:timer-lock-open-outline",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SensorEntityDescription(
        key="provider_failures",
        translation_key="provider_failures",
        icon="mdi:cloud-alert-outline",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SensorEntityDescription(
        key="command_queue_depth",
        translation_key="command_queue_depth",
        icon="mdi:format-list-numbered",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SensorEntityDescription(
        key="time_rule_conflict_count",
        translation_key="time_rule_conflict_count",
        icon="mdi:calendar-alert",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SensorEntityDescription(
        key="last_provider_error",
        translation_key="last_provider_error",
        icon="mdi:alert-circle-outline",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SensorEntityDescription(
        key="next_provider_retry",
        translation_key="next_provider_retry",
        icon="mdi:cloud-sync-outline",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SensorEntityDescription(
        key="last_successful_command",
        translation_key="last_successful_command",
        icon="mdi:check-circle-outline",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SensorEntityDescription(
        key="decision_diagnostics",
        translation_key="decision_diagnostics",
        icon="mdi:file-tree-outline",
        device_class=SensorDeviceClass.ENUM,
        options=REASON_CODES,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
)


class SmartShadingSensor(SmartShadingEntity, SensorEntity):
    """Sensor backed by controller data."""

    entity_description: SensorEntityDescription

    def __init__(
        self,
        entry: ConfigEntry,
        controller: SmartShadingController,
        description: SensorEntityDescription,
    ) -> None:
        super().__init__(entry, controller, description.key)
        self.entity_description = description
        if description.key in {
            "decision_diagnostics",
            "command_queue_depth",
            "time_rule_conflict_count",
            "pending_time_rule_open_count",
            "pending_time_rule_close_count",
        }:
            self._attr_entity_registry_enabled_default = False

    @property
    def native_value(self) -> Any:
        key = self.entity_description.key
        if key == "decision_diagnostics":
            return self.controller.data.get("reason_code")
        if key == "forecast_age":
            return self.controller.data.get("forecast_age_minutes")
        if key in {
            "last_successful_command",
            "next_provider_retry",
            "next_time_rule_close_retry",
        }:
            value = self.controller.data.get(key)
            return dt_util.parse_datetime(str(value)) if value else None
        if key == "last_provider_error":
            value = self.controller.data.get(key)
            return str(value)[:255] if value else None
        return self.controller.data.get(key)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if self.entity_description.key == "status":
            return {
                "reason_code": self.controller.data.get("reason_code"),
                "active_weather_protection": self.controller.data.get(
                    "active_weather_protection"
                ),
                "dry_run": self.controller.data.get("dry_run", False),
                "manual_overrides": dict(
                    self.controller.data.get("manual_overrides") or {}
                ),
                "manual_override_details": dict(
                    self.controller.data.get("manual_override_details") or {}
                ),
            }
        if self.entity_description.key in {"heat_risk", "sun_load", "reason_code"}:
            return {
                "solar_input": dict(self.controller.data.get("solar_input") or {}),
                "heat_assessment_by_orientation": dict(
                    self.controller.data.get("heat_assessment_by_orientation") or {}
                ),
                "room_temperature": self.controller.data.get("room_temperature"),
                "outside_temperature": self.controller.data.get("outside_temperature"),
                "temperature_difference_inside_outside": self.controller.data.get(
                    "temperature_difference_inside_outside"
                ),
                "temperature_trend": self.controller.data.get("temperature_trend"),
                "forecast_max": self.controller.data.get("forecast_max"),
            }
        if self.entity_description.key == "command_queue_depth":
            return dict(self.controller.data.get("command_queue") or {})
        if self.entity_description.key == "pending_time_rule_open_count":
            return {
                "pending": dict(
                    self.controller.data.get("pending_time_rule_opens") or {}
                )
            }
        if self.entity_description.key == "pending_time_rule_close_count":
            return {
                "pending": dict(
                    self.controller.data.get("pending_time_rule_closes") or {}
                ),
                "next_retry": self.controller.data.get(
                    "next_time_rule_close_retry"
                ),
            }
        if self.entity_description.key == "time_rule_conflict_count":
            return {
                "conflicts": list(
                    self.controller.data.get("time_rule_conflicts") or []
                )
            }
        if self.entity_description.key == "last_provider_error":
            return {
                "occurred_at": self.controller.data.get("last_provider_error_at"),
                "provider_health_by_cover": dict(
                    self.controller.data.get("provider_health_by_cover") or {}
                ),
            }
        if self.entity_description.key != "decision_diagnostics":
            return None
        return {
            key: value
            for key, value in self.controller.data.items()
            if key not in {"status", "heat_risk", "sun_load", "reason"}
        }


class SmartShadingRoomTemperatureSensor(SmartShadingEntity, SensorEntity):
    """Mirror the configured room temperature sensor on the room device."""

    _attr_translation_key = "room_temperature"
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS

    def __init__(
        self,
        entry: ConfigEntry,
        controller: SmartShadingController,
        source_entity_id: str,
    ) -> None:
        super().__init__(entry, controller, "room_temperature")
        self._source_entity_id = source_entity_id

    async def async_added_to_hass(self) -> None:
        """Subscribe directly to the configured source temperature sensor."""
        await super().async_added_to_hass()
        self.async_on_remove(
            async_track_state_change_event(
                self.hass,
                [self._source_entity_id],
                self._handle_source_update,
            )
        )

    @callback
    def _handle_source_update(self, _event: Event) -> None:
        """Publish temperature changes without waiting for an evaluation."""
        self.async_write_ha_state()

    @property
    def _source_state(self):
        """Return the current source state."""
        return self.hass.states.get(self._source_entity_id)

    @property
    def available(self) -> bool:
        """Return whether the source currently provides a numeric value."""
        state = self._source_state
        return (
            state is not None
            and state.state not in {STATE_UNKNOWN, STATE_UNAVAILABLE}
            and self.native_value is not None
        )

    @property
    def native_value(self) -> float | None:
        """Return the configured room temperature normalized to Celsius."""
        return temperature_state(self.hass, self._source_entity_id)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose the source used for the room temperature display."""
        state = self._source_state
        return {
            "source_entity_id": self._source_entity_id,
            "source_state": state.state if state is not None else None,
            "source_unit": (
                state.attributes.get(ATTR_UNIT_OF_MEASUREMENT)
                if state is not None
                else None
            ),
        }


class SmartShadingContactStateSensor(SmartShadingEntity, SensorEntity):
    """Expose the contact state for one configured window or cover."""

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options: ClassVar[list[str]] = [
        CONTACT_CLOSED,
        CONTACT_TILTED,
        CONTACT_OPEN,
        CONTACT_UNKNOWN,
    ]
    _attr_translation_key = "contact_state"

    def __init__(
        self,
        entry: ConfigEntry,
        controller: SmartShadingController,
        cover_entity_id: str,
        contact_entity_id: str,
    ) -> None:
        # The unique ID follows the configured window/cover, not the source
        # sensor. This creates one clearly named status entity per assignment
        # and keeps it stable when the user replaces the physical contact.
        registry = er.async_get(controller.hass)
        super().__init__(
            entry,
            controller,
            f"contact_state_{source_entity_registry_key(registry, cover_entity_id)}",
        )
        self._cover_entity_id = cover_entity_id
        self._contact_entity_id = contact_entity_id
        self._assigned_covers = (cover_entity_id,)
        cover_name = without_role_prefix(
            entity_display_name(controller.hass, cover_entity_id)
        )
        self._attr_translation_placeholders = {"window": cover_name}

    async def async_added_to_hass(self) -> None:
        """Subscribe to the controller and directly to the source contact."""
        await super().async_added_to_hass()
        self.async_on_remove(
            async_track_state_change_event(
                self.hass,
                [self._contact_entity_id],
                self._handle_source_update,
            )
        )

    @callback
    def _handle_source_update(self, _event: Event) -> None:
        """Publish contact changes without waiting for a room evaluation."""
        self.async_write_ha_state()

    @property
    def native_value(self) -> str:
        """Return closed, tilted, open or unknown."""
        state = self.hass.states.get(self._contact_entity_id)
        return classify_contact_state(
            state.state if state is not None else None,
            state.attributes if state is not None else None,
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose the source entity and every assigned physical cover."""
        source_state = self.hass.states.get(self._contact_entity_id)
        assigned_cover_names = {
            cover: (
                cover_state.name
                if (cover_state := self.hass.states.get(cover)) is not None
                else cover
            )
            for cover in self._assigned_covers
        }
        return {
            "source_entity_id": self._contact_entity_id,
            "source_state": source_state.state if source_state is not None else None,
            "assigned_covers": list(self._assigned_covers),
            "assigned_cover_names": assigned_cover_names,
        }


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    controller: SmartShadingController = entry.runtime_data
    entities: list[SensorEntity] = [
        SmartShadingSensor(entry, controller, description)
        for description in SENSOR_DESCRIPTIONS
    ]

    room_temperature_entity_id = str(
        controller.config.get(CONF_ROOM_TEMP_SENSOR) or ""
    ).strip()
    if room_temperature_entity_id:
        entities.append(
            SmartShadingRoomTemperatureSensor(
                entry,
                controller,
                room_temperature_entity_id,
            )
        )

    assignments = controller.config.get(CONF_COVER_CONTACTS) or {}
    contact_assignments: list[tuple[str, str]] = []
    if isinstance(assignments, dict):
        for cover, contact in assignments.items():
            cover_entity_id = str(cover).strip()
            contact_entity_id = str(contact or "").strip()
            if not cover_entity_id or not contact_entity_id:
                continue
            contact_assignments.append((cover_entity_id, contact_entity_id))

    entity_registry = er.async_get(hass)
    for cover_entity_id, _contact_entity_id in contact_assignments:
        migrate_legacy_source_unique_id(
            entity_registry,
            entry_id=entry.entry_id,
            domain="sensor",
            role="contact_state",
            source_entity_id=cover_entity_id,
        )

    contact_entities = [
        SmartShadingContactStateSensor(
            entry,
            controller,
            cover_entity_id,
            contact_entity_id,
        )
        for cover_entity_id, contact_entity_id in sorted(contact_assignments)
    ]
    entities.extend(contact_entities)

    active_contact_unique_ids = {entity.unique_id for entity in contact_entities}
    active_contact_unique_ids.update(
        legacy_source_unique_id(
            entry.entry_id,
            "contact_state",
            cover_entity_id,
        )
        for cover_entity_id, _contact_entity_id in contact_assignments
    )
    contact_unique_id_prefix = f"{entry.entry_id}_contact_state_"
    remove_stale_dynamic_entities(
        entity_registry,
        entry_id=entry.entry_id,
        domain="sensor",
        unique_id_prefix=contact_unique_id_prefix,
        active_unique_ids=active_contact_unique_ids,
    )

    room_temperature_unique_id = f"{entry.entry_id}_room_temperature"
    if not room_temperature_entity_id:
        for registry_entry in er.async_entries_for_config_entry(
            entity_registry, entry.entry_id
        ):
            if (
                registry_entry.domain == "sensor"
                and registry_entry.unique_id == room_temperature_unique_id
            ):
                entity_registry.async_remove(registry_entry.entity_id)

    async_add_entities(entities)
