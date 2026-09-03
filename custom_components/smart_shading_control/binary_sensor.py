"""Binary sensor platform for Smart Shading Control."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import (
    STATUS_HEAT_PROTECTION,
    STATUS_PREVENTIVE,
    STATUS_STRONG_HEAT,
)
from .controller import SmartShadingController
from .entity import SmartShadingEntity


DESCRIPTIONS = (
    BinarySensorEntityDescription(
        key="direct_sun",
        translation_key="direct_sun",
        icon="mdi:weather-sunny-alert",
    ),
    BinarySensorEntityDescription(
        key="heat_protection_active",
        translation_key="heat_protection_active",
        icon="mdi:shield-sun",
    ),
    BinarySensorEntityDescription(
        key="forecast_stale",
        translation_key="forecast_stale",
        icon="mdi:weather-cloudy-alert",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    BinarySensorEntityDescription(
        key="pending_time_rule_open",
        translation_key="pending_time_rule_open",
        icon="mdi:calendar-clock-outline",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    BinarySensorEntityDescription(
        key="command_queue_busy",
        translation_key="command_queue_busy",
        icon="mdi:progress-clock",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    BinarySensorEntityDescription(
        key="provider_degraded",
        translation_key="provider_degraded",
        icon="mdi:cloud-alert-outline",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
)


class SmartShadingBinarySensor(SmartShadingEntity, BinarySensorEntity):
    entity_description: BinarySensorEntityDescription

    def __init__(
        self,
        entry: ConfigEntry,
        controller: SmartShadingController,
        description: BinarySensorEntityDescription,
    ) -> None:
        super().__init__(entry, controller, description.key)
        self.entity_description = description
        if description.key == "command_queue_busy":
            self._attr_entity_registry_enabled_default = False

    @property
    def is_on(self) -> bool:
        if self.entity_description.key == "direct_sun":
            return bool(self.controller.data.get("direct_sun"))
        if self.entity_description.key == "provider_degraded":
            return (self.controller.data.get("provider_health") or {}).get("state") == "degraded"
        if self.entity_description.key == "forecast_stale":
            return bool(self.controller.data.get("forecast_stale"))
        if self.entity_description.key == "pending_time_rule_open":
            return bool(self.controller.data.get("pending_time_rule_open_count"))
        if self.entity_description.key == "command_queue_busy":
            return bool(self.controller.data.get("command_queue_busy"))
        return self.controller.data.get("status") in {
            STATUS_PREVENTIVE,
            STATUS_HEAT_PROTECTION,
            STATUS_STRONG_HEAT,
        }


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    controller: SmartShadingController = entry.runtime_data
    async_add_entities(
        SmartShadingBinarySensor(entry, controller, description)
        for description in DESCRIPTIONS
    )
