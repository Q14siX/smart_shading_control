"""Button platform for Smart Shading Control."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .controller import SmartShadingController
from .entity import SmartShadingEntity


DESCRIPTIONS = (
    ButtonEntityDescription(
        key="recalculate",
        translation_key="recalculate",
        icon="mdi:calculator-variant-outline",
    ),
    ButtonEntityDescription(
        key="clear_overrides",
        translation_key="clear_overrides",
        icon="mdi:gesture-tap-button",
    ),
    ButtonEntityDescription(
        key="clear_decision_log",
        translation_key="clear_decision_log",
        icon="mdi:delete-sweep-outline",
    ),
)


class SmartShadingButton(SmartShadingEntity, ButtonEntity):
    entity_description: ButtonEntityDescription

    def __init__(
        self,
        entry: ConfigEntry,
        controller: SmartShadingController,
        description: ButtonEntityDescription,
    ) -> None:
        super().__init__(entry, controller, description.key)
        self.entity_description = description

    async def async_press(self) -> None:
        if self.entity_description.key == "clear_overrides":
            await self.controller.async_clear_manual_overrides()
        elif self.entity_description.key == "clear_decision_log":
            await self.controller.async_clear_decision_log()
        else:
            await self.controller.async_evaluate(force=True)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    controller: SmartShadingController = entry.runtime_data
    async_add_entities(
        SmartShadingButton(entry, controller, description)
        for description in DESCRIPTIONS
    )
