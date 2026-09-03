"""Base entities for Smart Shading Control."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import Entity

from .const import DOMAIN, NAME, VERSION
from .controller import SmartShadingController


class SmartShadingEntity(Entity):
    """Base entity linked to one room controller."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(
        self,
        entry: ConfigEntry,
        controller: SmartShadingController,
        key: str,
    ) -> None:
        self.entry = entry
        self.controller = controller
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_device_info = DeviceInfo(
            entry_type=DeviceEntryType.SERVICE,
            identifiers={(DOMAIN, entry.entry_id)},
            name=controller.room_name,
            manufacturer="Q14siX",
            model=NAME,
            sw_version=VERSION,
        )

    async def async_added_to_hass(self) -> None:
        """Subscribe to controller updates."""
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                self.controller.signal,
                self._handle_controller_update,
            )
        )

    @callback
    def _handle_controller_update(self) -> None:
        self.async_write_ha_state()
