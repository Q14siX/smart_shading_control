"""Switch platform for Smart Shading Control."""

from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .controller import SmartShadingController
from .entity import SmartShadingEntity

PARALLEL_UPDATES = 0


class SmartShadingAutomationSwitch(SmartShadingEntity, RestoreEntity, SwitchEntity):
    """Enable or disable all control for this room."""

    _attr_translation_key = "control_enabled"
    _attr_icon = "mdi:blinds-horizontal-closed"

    def __init__(
        self, entry: ConfigEntry, controller: SmartShadingController
    ) -> None:
        super().__init__(entry, controller, "automation")

    @property
    def is_on(self) -> bool:
        return self.controller.enabled

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if not self.controller.enabled_state_loaded:
            if (
                (last_state := await self.async_get_last_state()) is not None
                and last_state.state in {"on", "off"}
            ):
                self.controller.enabled = last_state.state == "on"
            self.controller.mark_enabled_state_loaded()
            await self.controller.async_save_control_state()
            if self.controller.started:
                await self.controller.async_evaluate(force=True)

    async def async_turn_on(self, **kwargs) -> None:
        await self.controller.async_set_enabled(True)

    async def async_turn_off(self, **kwargs) -> None:
        await self.controller.async_set_enabled(False)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    controller: SmartShadingController = entry.runtime_data
    async_add_entities([SmartShadingAutomationSwitch(entry, controller)])
