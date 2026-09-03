"""Virtual room and individual cover controls for Smart Shading Control."""

from __future__ import annotations

from typing import Any

from homeassistant.components.cover import CoverEntity, CoverEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.event import async_track_state_change_event

from .const import CONF_OPEN_POSITION
from .controller import SmartShadingController
from .entity import SmartShadingEntity
from .state_helpers import entity_display_name, without_role_prefix

PARALLEL_UPDATES = 0

_SUPPORTED_FEATURES = (
    CoverEntityFeature.OPEN
    | CoverEntityFeature.CLOSE
    | CoverEntityFeature.STOP
    | CoverEntityFeature.SET_POSITION
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the room cover and one control entity per physical cover."""
    controller = entry.runtime_data
    if not isinstance(controller, SmartShadingController):
        return

    individual_entities = [
        SmartShadingIndividualCover(entry, controller, entity_id)
        for entity_id in controller.all_covers
    ]
    async_add_entities(
        [SmartShadingRoomCover(entry, controller), *individual_entities]
    )

    # Remove virtual controls whose physical cover is no longer configured.
    active_unique_ids = {entity.unique_id for entity in individual_entities}
    registry = er.async_get(hass)
    prefix = f"{entry.entry_id}_individual_cover_"
    for registry_entry in er.async_entries_for_config_entry(
        registry, entry.entry_id
    ):
        if (
            registry_entry.domain == "cover"
            and registry_entry.unique_id.startswith(prefix)
            and registry_entry.unique_id not in active_unique_ids
        ):
            registry.async_remove(registry_entry.entity_id)


class SmartShadingRoomCover(SmartShadingEntity, CoverEntity):
    """Control all covers assigned to one room as a single cover entity."""

    _attr_translation_key = "room_covers"
    _attr_supported_features = _SUPPORTED_FEATURES

    def __init__(self, entry: ConfigEntry, controller: SmartShadingController) -> None:
        super().__init__(entry, controller, "room_covers")

    @property
    def available(self) -> bool:
        """Return whether at least one configured physical cover is available."""
        return any(
            (state := self.hass.states.get(entity_id)) is not None
            and state.state not in {STATE_UNKNOWN, STATE_UNAVAILABLE}
            for entity_id in self.controller.all_covers
        )

    @property
    def current_cover_position(self) -> int | None:
        """Return the rounded mean of all known physical cover positions."""
        positions = []
        for entity_id in self.controller.all_covers:
            state = self.hass.states.get(entity_id)
            position = self.controller.position_from_state(state)
            if position is not None:
                positions.append(position)
        return round(sum(positions) / len(positions)) if positions else None

    @property
    def is_opening(self) -> bool:
        return any(
            (state := self.hass.states.get(entity_id)) is not None
            and state.state == "opening"
            for entity_id in self.controller.all_covers
        )

    @property
    def is_closing(self) -> bool:
        return any(
            (state := self.hass.states.get(entity_id)) is not None
            and state.state == "closing"
            for entity_id in self.controller.all_covers
        )

    @property
    def is_closed(self) -> bool | None:
        position = self.current_cover_position
        return None if position is None else position == 0

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose every physical cover currently assigned to the room."""
        assigned = list(self.controller.all_covers)
        return {
            "assigned_covers": assigned,
            "assigned_cover_count": len(assigned),
        }

    async def async_open_cover(self, **kwargs: Any) -> None:
        await self.controller.async_group_set_position(
            int(self.controller.config[CONF_OPEN_POSITION])
        )

    async def async_close_cover(self, **kwargs: Any) -> None:
        await self.controller.async_group_set_position(0)

    async def async_stop_cover(self, **kwargs: Any) -> None:
        await self.controller.async_group_stop()

    async def async_set_cover_position(self, **kwargs: Any) -> None:
        await self.controller.async_group_set_position(int(kwargs["position"]))


class SmartShadingIndividualCover(SmartShadingEntity, CoverEntity):
    """Proxy one physical cover through Smart Shading Control."""

    _attr_translation_key = "individual_cover"
    _attr_supported_features = _SUPPORTED_FEATURES

    def __init__(
        self,
        entry: ConfigEntry,
        controller: SmartShadingController,
        source_entity_id: str,
    ) -> None:
        super().__init__(
            entry,
            controller,
            f"individual_cover_{source_entity_id}",
        )
        self._source_entity_id = source_entity_id
        source_name = without_role_prefix(
            entity_display_name(controller.hass, source_entity_id)
        )
        self._attr_translation_placeholders = {"cover": source_name}

    async def async_added_to_hass(self) -> None:
        """Subscribe to room updates and the physical cover directly."""
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
        """Mirror source movements without waiting for a room evaluation."""
        self.async_write_ha_state()

    @property
    def _source_state(self):
        """Return the current in-memory state of the physical cover."""
        return self.hass.states.get(self._source_entity_id)

    @property
    def available(self) -> bool:
        """Return whether the physical cover is currently available."""
        state = self._source_state
        return state is not None and state.state not in {
            STATE_UNKNOWN,
            STATE_UNAVAILABLE,
        }

    @property
    def current_cover_position(self) -> int | None:
        """Mirror the current position of the physical cover."""
        return self.controller.position_from_state(self._source_state)

    @property
    def is_opening(self) -> bool:
        state = self._source_state
        return state is not None and state.state == "opening"

    @property
    def is_closing(self) -> bool:
        state = self._source_state
        return state is not None and state.state == "closing"

    @property
    def is_closed(self) -> bool | None:
        state = self._source_state
        if state is None or state.state in {STATE_UNKNOWN, STATE_UNAVAILABLE}:
            return None
        position = self.controller.position_from_state(state)
        if position is not None:
            return position == 0
        if state.state == "closed":
            return True
        if state.state in {"open", "opening", "closing"}:
            return False
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose the physical cover represented by this control."""
        return {"source_cover_entity_id": self._source_entity_id}

    async def async_open_cover(self, **kwargs: Any) -> None:
        await self.controller.async_cover_set_position(
            self._source_entity_id,
            int(self.controller.config[CONF_OPEN_POSITION]),
        )

    async def async_close_cover(self, **kwargs: Any) -> None:
        await self.controller.async_cover_set_position(self._source_entity_id, 0)

    async def async_stop_cover(self, **kwargs: Any) -> None:
        await self.controller.async_cover_stop(self._source_entity_id)

    async def async_set_cover_position(self, **kwargs: Any) -> None:
        await self.controller.async_cover_set_position(
            self._source_entity_id,
            int(kwargs["position"]),
        )
