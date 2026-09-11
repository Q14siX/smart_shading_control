"""Select platform for Smart Shading Control."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .const import MODE_AUTOMATIC, MODES
from .controller import SmartShadingController
from .entity import SmartShadingEntity

PARALLEL_UPDATES = 0


class SmartShadingModeSelect(SmartShadingEntity, RestoreEntity, SelectEntity):
    """Select room operating mode."""

    _attr_translation_key = "mode"
    _attr_icon = "mdi:tune-variant"
    _attr_options = MODES

    def __init__(
        self, entry: ConfigEntry, controller: SmartShadingController
    ) -> None:
        super().__init__(entry, controller, "mode")

    @property
    def current_option(self) -> str:
        return self.controller.mode

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if not self.controller.mode_state_loaded:
            if (last_state := await self.async_get_last_state()) is not None and last_state.state in MODES:
                self.controller.mode = last_state.state
            else:
                self.controller.mode = MODE_AUTOMATIC
            self.controller.mark_mode_state_loaded()
            await self.controller.async_save_control_state()
            if self.controller.started:
                await self.controller.async_evaluate(force=True)

    async def async_select_option(self, option: str) -> None:
        if option not in MODES:
            raise ValueError(f"Unsupported mode: {option}")
        await self.controller.async_set_mode(option)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    controller: SmartShadingController = entry.runtime_data
    async_add_entities([SmartShadingModeSelect(entry, controller)])
