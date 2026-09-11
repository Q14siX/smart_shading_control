"""Virtual room and individual cover controls for Smart Shading Control."""

from __future__ import annotations

from typing import Any

from homeassistant.components.cover import CoverEntity, CoverEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import Event, HomeAssistant, State, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.event import async_track_state_change_event

from .const import CONF_OPEN_POSITION, DOMAIN
from .controller import SmartShadingController
from .entity import SmartShadingEntity
from .state_helpers import entity_display_name, without_role_prefix

PARALLEL_UPDATES = 0

_BASE_SUPPORTED_FEATURES = (
    CoverEntityFeature.OPEN | CoverEntityFeature.CLOSE | CoverEntityFeature.SET_POSITION
)


def source_entity_registry_key(
    registry: er.EntityRegistry,
    source_entity_id: str,
) -> str:
    """Return an identity that survives renaming a registered source entity.

    Registry-entry IDs are persistent opaque identifiers.  Home Assistant's
    Energy integration uses the same identity for entities derived from a
    source entity.  Entities without a registry entry retain the legacy entity
    ID fallback because no rename-stable identity exists for them.
    """
    if (source_entry := registry.async_get(source_entity_id)) is not None:
        return source_entry.id
    return source_entity_id


def dynamic_source_unique_id(
    registry: er.EntityRegistry,
    entry_id: str,
    role: str,
    source_entity_id: str,
) -> str:
    """Build a room-local unique ID from a stable source identity."""
    source_key = source_entity_registry_key(registry, source_entity_id)
    return f"{entry_id}_{role}_{source_key}"


def legacy_source_unique_id(
    entry_id: str,
    role: str,
    source_entity_id: str,
) -> str:
    """Return the pre-migration entity-ID-based unique ID."""
    return f"{entry_id}_{role}_{source_entity_id}"


def migrate_legacy_source_unique_id(
    registry: er.EntityRegistry,
    *,
    entry_id: str,
    domain: str,
    role: str,
    source_entity_id: str,
) -> str:
    """Migrate an entity-ID-based dynamic unique ID without recreating it.

    Updating the existing registry entry preserves its entity ID, user name,
    disabled state, labels, and other registry customizations.  If a stable
    target already exists, leave both entries untouched here; normal stale
    cleanup can then remove only the inactive legacy duplicate.
    """
    stable_unique_id = dynamic_source_unique_id(
        registry,
        entry_id,
        role,
        source_entity_id,
    )
    legacy_unique_id = legacy_source_unique_id(entry_id, role, source_entity_id)
    if stable_unique_id == legacy_unique_id:
        return stable_unique_id

    legacy_entity_id = registry.async_get_entity_id(
        domain,
        DOMAIN,
        legacy_unique_id,
    )
    if legacy_entity_id is None:
        return stable_unique_id
    if registry.async_get_entity_id(domain, DOMAIN, stable_unique_id) is not None:
        return stable_unique_id

    legacy_entry = registry.async_get(legacy_entity_id)
    if (
        legacy_entry is not None
        and legacy_entry.config_entry_id == entry_id
        and legacy_entry.platform == DOMAIN
    ):
        registry.async_update_entity(
            legacy_entity_id,
            new_unique_id=stable_unique_id,
        )
    return stable_unique_id


def remove_stale_dynamic_entities(
    registry: er.EntityRegistry,
    *,
    entry_id: str,
    domain: str,
    unique_id_prefix: str,
    active_unique_ids: set[str],
) -> None:
    """Remove only inactive dynamic entities owned by this config entry."""
    for registry_entry in er.async_entries_for_config_entry(registry, entry_id):
        if (
            registry_entry.domain == domain
            and registry_entry.platform == DOMAIN
            and registry_entry.unique_id.startswith(unique_id_prefix)
            and registry_entry.unique_id not in active_unique_ids
        ):
            registry.async_remove(registry_entry.entity_id)


def _state_is_available(state: State | None) -> bool:
    """Return whether a physical cover currently participates in proxy control."""
    return state is not None and state.state not in {
        STATE_UNKNOWN,
        STATE_UNAVAILABLE,
    }


def _state_supports_stop(state: State | None) -> bool:
    """Return whether an available physical cover advertises STOP."""
    if not _state_is_available(state):
        return False
    try:
        supported = int(state.attributes.get("supported_features", 0))
    except (OverflowError, TypeError, ValueError):
        return False
    return bool(supported & int(CoverEntityFeature.STOP))


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the room cover and one control entity per physical cover."""
    controller = entry.runtime_data
    if not isinstance(controller, SmartShadingController):
        return

    registry = er.async_get(hass)
    for source_entity_id in controller.all_covers:
        migrate_legacy_source_unique_id(
            registry,
            entry_id=entry.entry_id,
            domain="cover",
            role="individual_cover",
            source_entity_id=source_entity_id,
        )

    individual_entities = [
        SmartShadingIndividualCover(entry, controller, entity_id)
        for entity_id in controller.all_covers
    ]
    async_add_entities([SmartShadingRoomCover(entry, controller), *individual_entities])

    # Remove virtual controls whose physical cover is no longer configured.
    active_unique_ids = {entity.unique_id for entity in individual_entities}
    # A target collision is not expected in normal operation.  Preserve any
    # legacy entry for a still-configured source rather than deleting user
    # customizations when a stable entry already exists.
    active_unique_ids.update(
        legacy_source_unique_id(
            entry.entry_id,
            "individual_cover",
            source_entity_id,
        )
        for source_entity_id in controller.all_covers
    )
    prefix = f"{entry.entry_id}_individual_cover_"
    remove_stale_dynamic_entities(
        registry,
        entry_id=entry.entry_id,
        domain="cover",
        unique_id_prefix=prefix,
        active_unique_ids=active_unique_ids,
    )


class SmartShadingRoomCover(SmartShadingEntity, CoverEntity):
    """Control all covers assigned to one room as a single cover entity."""

    _attr_translation_key = "room_covers"
    _attr_supported_features = _BASE_SUPPORTED_FEATURES

    def __init__(self, entry: ConfigEntry, controller: SmartShadingController) -> None:
        super().__init__(entry, controller, "room_covers")

    async def async_added_to_hass(self) -> None:
        """Subscribe directly so aggregate features follow physical covers."""
        await super().async_added_to_hass()
        source_entities = list(self.controller.all_covers)
        if source_entities:
            self.async_on_remove(
                async_track_state_change_event(
                    self.hass,
                    source_entities,
                    self._handle_source_update,
                )
            )

    @callback
    def _handle_source_update(self, _event: Event) -> None:
        """Mirror aggregate state and feature changes without debounce latency."""
        self.async_write_ha_state()

    @property
    def supported_features(self) -> CoverEntityFeature:
        """Expose STOP only when it is valid for the available room group.

        A room action represents all currently actionable physical covers, so
        STOP is the intersection of their capabilities rather than their union.
        Unavailable members are excluded consistently with the room's availability
        and with the controller skipping commands to unavailable entities.
        """
        available_states = [
            state
            for entity_id in self.controller.all_covers
            if _state_is_available(state := self.hass.states.get(entity_id))
        ]
        features = _BASE_SUPPORTED_FEATURES
        if available_states and all(
            _state_supports_stop(state) for state in available_states
        ):
            features |= CoverEntityFeature.STOP
        return features

    @property
    def available(self) -> bool:
        """Return whether at least one configured physical cover is available."""
        return any(
            _state_is_available(self.hass.states.get(entity_id))
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
    _attr_supported_features = _BASE_SUPPORTED_FEATURES

    def __init__(
        self,
        entry: ConfigEntry,
        controller: SmartShadingController,
        source_entity_id: str,
    ) -> None:
        registry = er.async_get(controller.hass)
        super().__init__(
            entry,
            controller,
            (
                "individual_cover_"
                f"{source_entity_registry_key(registry, source_entity_id)}"
            ),
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
    def supported_features(self) -> CoverEntityFeature:
        """Expose STOP only when the represented physical cover supports it."""
        features = _BASE_SUPPORTED_FEATURES
        if _state_supports_stop(self._source_state):
            features |= CoverEntityFeature.STOP
        return features

    @property
    def available(self) -> bool:
        """Return whether the physical cover is currently available."""
        return _state_is_available(self._source_state)

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
