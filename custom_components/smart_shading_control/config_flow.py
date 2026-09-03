"""Config and options flows for Smart Shading Control."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlowResult,
    OptionsFlowWithReload,
)
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
    CONF_CONFIRM_DELETE,
    CONF_COVER_CONTACTS,
    CONF_ENTRY_TYPE,
    CONF_GLOBAL_TIME_RULES,
    CONF_GLOBAL_POSITION_OVERRIDES,
    CONF_GLOBAL_POSITION_VALUES,
    CONF_GLOBAL_MANUAL_OVERRIDE_MINUTES,
    CONF_MANUAL_OVERRIDE_MINUTES,
    CONF_OPENING_CONTACT,
    CONF_ROOM_NAME,
    CONF_RULE_ACTION,
    CONF_RULE_COVERS,
    CONF_RULE_ENABLED,
    CONF_RULE_ID,
    CONF_RULE_NAME,
    CONF_RULE_SCOPE,
    CONF_RULE_TRIGGER_REFERENCE,
    CONF_SELECTED_RULE,
    CONF_TIME_RULES,
    CONF_WORKDAY_ENTITY,
    DOMAIN,
    ENTRY_TYPE_GLOBAL,
    ENTRY_TYPE_ROOM,
    GLOBAL_UNIQUE_ID,
    NAME,
    RULE_SCOPE_GLOBAL,
    RULE_SCOPE_ROOM,
)
from .global_transfers import append_global_time_rule_to_rooms
from .logic import as_list
from .schedule import normalize_boolean, normalize_rule


from .config_flow_helpers import (
    _OPTIONAL_GLOBAL_ENTITIES,
    _action_summary,
    _behavior_schema,
    _clean_global_input,
    _clean_global_positions_input,
    _clean_global_manual_override_input,
    _configured_global_position_values,
    _configured_global_manual_override_minutes,
    _configured_workday_entity,
    _cover_contact_schema,
    _covers_in_other_rooms,
    _covers_schema,
    _entity_display_name,
    _entry_kind,
    _global_entry,
    _global_schema,
    _global_positions_schema,
    _global_manual_override_schema,
    _integration_cover_entities,
    _normalized_rule_from_input,
    _ordered_covers,
    _room_schema,
    _positions_schema,
    _rule_basics_schema,
    _rule_choice_selector,
    _rule_defaults,
    _rule_reference_schema,
    _rule_time_or_offset_schema,
    _trigger_summary,
    _validate_complete_time_rule,
    _validate_cover_groups,
    _validate_global_settings,
    _validate_global_position_settings,
    _validate_room_position_settings,
    _validate_rule_basics,
    _validate_temperatures,
    _workday_dependent_rules_exist,
)
from .schedule_conflicts import first_blocking_conflict


class SmartShadingConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Create central settings first, then any number of rooms."""

    VERSION = 19
    MINOR_VERSION = 0

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}
        self._contact_queue: list[str] = []
        self._contact_index = 0
        self._cover_contacts: dict[str, str] = {}
        self._rule_draft: dict[str, Any] = {}
        self._initial_rules: list[dict[str, Any]] = []

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> SmartShadingOptionsFlow:
        return SmartShadingOptionsFlow()

    def _room_name(self) -> str:
        return str(self._data.get(CONF_ROOM_NAME) or NAME)

    def _room_covers_list(self) -> list[str]:
        return _ordered_covers(self._data)

    def _room_covers(self) -> set[str]:
        return set(self._room_covers_list())

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if _global_entry(self.hass) is None:
            return await self.async_step_global(user_input)
        return await self.async_step_room(user_input)

    async def async_step_global(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        await self.async_set_unique_id(GLOBAL_UNIQUE_ID)
        self._abort_if_unique_id_configured()
        errors: dict[str, str] = {}
        if user_input is not None:
            if error := _validate_global_settings(user_input):
                errors["base"] = error
            else:
                self._data = {
                    CONF_ENTRY_TYPE: ENTRY_TYPE_GLOBAL,
                    **_clean_global_input(user_input),
                }
                return await self.async_step_global_positions()
        return self.async_show_form(
            step_id="global",
            data_schema=_global_schema(user_input),
            errors=errors,
        )

    async def async_step_global_positions(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            if error := _validate_global_position_settings(self.hass, user_input):
                errors["base"] = error
            else:
                self._data.update(_clean_global_positions_input(user_input))
                return await self.async_step_global_manual_override()
        return self.async_show_form(
            step_id="global_positions",
            data_schema=_global_positions_schema(user_input),
            errors=errors,
        )

    async def async_step_global_manual_override(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            self._data.update(_clean_global_manual_override_input(user_input))
            return self.async_create_entry(title=NAME, data=self._data)
        return self.async_show_form(
            step_id="global_manual_override",
            data_schema=_global_manual_override_schema(user_input),
        )

    async def async_step_room(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            self._data = {CONF_ENTRY_TYPE: ENTRY_TYPE_ROOM, **user_input}
            return await self.async_step_covers()
        return self.async_show_form(step_id="room", data_schema=_room_schema(language=self.hass.config.language))

    async def async_step_covers(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            if error := _validate_cover_groups(
                user_input,
                covers_in_other_rooms=_covers_in_other_rooms(self.hass),
                integration_covers=_integration_cover_entities(self.hass),
            ):
                errors["base"] = error
            else:
                self._data.update(user_input)
                self._contact_queue = self._room_covers_list()
                self._contact_index = 0
                self._cover_contacts = {}
                return await self.async_step_cover_contact()
        return self.async_show_form(
            step_id="covers",
            data_schema=_covers_schema(user_input),
            errors=errors,
        )

    async def async_step_cover_contact(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if self._contact_index >= len(self._contact_queue):
            self._data[CONF_COVER_CONTACTS] = dict(self._cover_contacts)
            return await self.async_step_behavior()

        cover = self._contact_queue[self._contact_index]
        if user_input is not None:
            contact = str(user_input.get(CONF_OPENING_CONTACT) or "").strip()
            if contact:
                self._cover_contacts[cover] = contact
            self._contact_index += 1
            return await self.async_step_cover_contact()

        return self.async_show_form(
            step_id="cover_contact",
            data_schema=_cover_contact_schema(self._cover_contacts.get(cover)),
            description_placeholders={
                "cover": _entity_display_name(self.hass, cover),
                "number": str(self._contact_index + 1),
                "total": str(len(self._contact_queue)),
            },
        )

    async def async_step_behavior(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            if error := _validate_temperatures(user_input):
                errors["base"] = error
            else:
                self._data.update(user_input)
                return await self.async_step_positions()
        return self.async_show_form(
            step_id="behavior",
            data_schema=_behavior_schema(
                user_input,
                defaults={
                    CONF_MANUAL_OVERRIDE_MINUTES:
                        _configured_global_manual_override_minutes(self.hass)
                },
            ),
            errors=errors,
        )

    async def async_step_positions(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            if error := _validate_room_position_settings(self.hass, user_input):
                errors["base"] = error
            else:
                self._data.update(user_input)
                return await self.async_step_initial_time_rules()
        return self.async_show_form(
            step_id="positions",
            data_schema=_positions_schema(
                user_input,
                defaults=_configured_global_position_values(self.hass),
            ),
            errors=errors,
        )

    async def async_step_initial_time_rules(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return self.async_show_menu(
            step_id="initial_time_rules",
            menu_options=["add_initial_time_rule", "finish_room"],
        )

    async def async_step_add_initial_time_rule(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        self._rule_draft = _rule_defaults(
            scope=RULE_SCOPE_ROOM,
            room_covers=self._room_covers_list(),
            language=self.hass.config.language,
        )
        return await self.async_step_initial_rule_basics(user_input)

    async def async_step_finish_room(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        # Central time rules are not stored. A newly created room therefore
        # starts only with rules explicitly added during its own setup.
        self._data[CONF_TIME_RULES] = list(self._initial_rules)
        return self.async_create_entry(title=self._room_name(), data=self._data)

    async def async_step_initial_rule_basics(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            if error := _validate_rule_basics(
                user_input,
                scope=RULE_SCOPE_ROOM,
                room_covers=self._room_covers(),
                workday_available=bool(_configured_workday_entity(self.hass)),
            ):
                errors["base"] = error
            else:
                self._rule_draft.update(user_input)
                return await self.async_step_initial_rule_trigger()
        return self.async_show_form(
            step_id="initial_rule_basics",
            data_schema=_rule_basics_schema(
                self.hass,
                scope=RULE_SCOPE_ROOM,
                room_covers=self._room_covers_list(),
                values=user_input or self._rule_draft,
            ),
            errors=errors,
        )

    async def async_step_initial_rule_trigger(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            self._rule_draft.update(user_input)
            return await self.async_step_initial_rule_trigger_value()
        return self.async_show_form(
            step_id="initial_rule_trigger",
            data_schema=_rule_reference_schema(
                str(self._rule_draft[CONF_RULE_TRIGGER_REFERENCE]),
            ),
        )

    async def async_step_initial_rule_trigger_value(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        reference = str(self._rule_draft[CONF_RULE_TRIGGER_REFERENCE])
        if user_input is not None:
            self._rule_draft.update(user_input)
            if error := _validate_complete_time_rule(
                self._rule_draft,
                scope=RULE_SCOPE_ROOM,
                room_covers=self._room_covers(),
                workday_available=bool(_configured_workday_entity(self.hass)),
            ):
                errors["base"] = error
            else:
                updated = _normalized_rule_from_input(
                    self._rule_draft,
                    scope=RULE_SCOPE_ROOM,
                )
                conflict = first_blocking_conflict(
                    updated,
                    self._initial_rules,
                    self._room_covers(),
                )
                if conflict:
                    errors["base"] = conflict
                else:
                    self._initial_rules.append(updated)
                    self._rule_draft = {}
                    return await self.async_step_initial_time_rules()
        return self.async_show_form(
            step_id="initial_rule_trigger_value",
            data_schema=_rule_time_or_offset_schema(
                reference=reference,
                values=self._rule_draft,
            ),
            errors=errors,
        )


class SmartShadingOptionsFlow(OptionsFlowWithReload):
    """Edit central settings or one room and distribute new rules."""

    def __init__(self) -> None:
        self._rule_scope = RULE_SCOPE_ROOM
        self._editing_rule_id: str | None = None
        self._selected_rule_id: str | None = None
        self._pending_cover_data: dict[str, Any] | None = None
        self._contact_queue: list[str] = []
        self._contact_index = 0
        self._cover_contacts: dict[str, str] = {}
        self._rule_draft: dict[str, Any] = {}

    def _kind(self) -> str:
        return _entry_kind(self.config_entry)

    def _current(self) -> dict[str, Any]:
        current = dict(self.config_entry.data)
        current.update(self.config_entry.options)
        current.setdefault(CONF_COVER_CONTACTS, {})
        current.setdefault(CONF_TIME_RULES, [])
        current.setdefault(CONF_GLOBAL_TIME_RULES, [])
        return current

    def _room_name(self) -> str:
        return str(self._current().get(CONF_ROOM_NAME) or self.config_entry.title)

    def _room_covers_list(self) -> list[str]:
        return _ordered_covers(self._current())

    def _room_covers(self) -> set[str]:
        return set(self._room_covers_list())

    def _rules_key(self) -> str:
        return CONF_GLOBAL_TIME_RULES if self._rule_scope == RULE_SCOPE_GLOBAL else CONF_TIME_RULES

    def _rules(self) -> list[dict[str, Any]]:
        rules: list[dict[str, Any]] = []
        used_ids: set[str] = set()
        room_covers = self._room_covers_list()
        key = self._rules_key()
        for index, raw_rule in enumerate(as_list(self._current().get(key)), start=1):
            if not isinstance(raw_rule, dict) or not normalize_boolean(
                raw_rule.get(CONF_RULE_ENABLED), True
            ):
                continue
            try:
                rule = normalize_rule(raw_rule)
            except (TypeError, ValueError):
                continue
            rule[CONF_RULE_SCOPE] = self._rule_scope
            if self._rule_scope == RULE_SCOPE_ROOM:
                rule[CONF_RULE_COVERS] = [
                    cover for cover in rule[CONF_RULE_COVERS] if cover in room_covers
                ]
                if not rule[CONF_RULE_COVERS]:
                    continue
            else:
                rule[CONF_RULE_COVERS] = []
            rule_id = str(rule.get(CONF_RULE_ID) or "").strip()
            if not rule_id or rule_id in used_ids:
                base = f"legacy-{index}"
                rule_id = base
                suffix = 2
                while rule_id in used_ids:
                    rule_id = f"{base}-{suffix}"
                    suffix += 1
                rule[CONF_RULE_ID] = rule_id
            used_ids.add(rule_id)
            rules.append(rule)
        return rules

    def _rule_choices(self) -> dict[str, str]:
        choices: dict[str, str] = {}
        for rule in self._rules():
            label = (
                f"{rule[CONF_RULE_NAME]} · "
                f"{_action_summary(str(rule[CONF_RULE_ACTION]), self.hass.config.language)} · "
                f"{_trigger_summary(rule, self.hass.config.language)}"
            )
            if self._rule_scope == RULE_SCOPE_ROOM:
                targets = ", ".join(
                    _entity_display_name(self.hass, cover)
                    for cover in rule[CONF_RULE_COVERS]
                )
                label = f"{label} · {targets}"
            choices[str(rule[CONF_RULE_ID])] = label
        return choices

    def _find_rule(self, rule_id: str | None) -> dict[str, Any] | None:
        return next(
            (rule for rule in self._rules() if rule[CONF_RULE_ID] == rule_id),
            None,
        )

    def _schedule_all_room_reloads(self) -> None:
        """Reload every room once after a central options update."""
        for room_entry in self.hass.config_entries.async_entries(DOMAIN):
            if _entry_kind(room_entry) != ENTRY_TYPE_ROOM:
                continue
            if room_entry.state.recoverable:
                self.hass.config_entries.async_schedule_reload(room_entry.entry_id)

    def _save_options(
        self,
        changes: dict[str, Any],
        *,
        remove_keys: tuple[str, ...] = (),
    ) -> ConfigFlowResult:
        options = dict(self.config_entry.options)
        for key in remove_keys:
            options.pop(key, None)
        options.update(changes)
        if self._kind() == ENTRY_TYPE_GLOBAL:
            # The central entry keeps an update listener for shared coordinator
            # data only. Schedule dependent rooms here exactly once so central
            # transfers also take effect when the stored central value itself
            # did not change.
            self._schedule_all_room_reloads()
        return self.async_create_entry(data=options)

    def _save_rules(self, rules: list[dict[str, Any]]) -> ConfigFlowResult:
        """Persist a room's own rule list."""
        return self._save_options({CONF_TIME_RULES: rules})

    def _distribute_new_global_rule(
        self, rule: dict[str, Any]
    ) -> ConfigFlowResult:
        """Append one new rule to every room without storing it centrally."""
        append_global_time_rule_to_rooms(
            self.hass, rule, schedule_reload=False
        )
        return self._save_options(
            {},
            remove_keys=(CONF_GLOBAL_TIME_RULES, CONF_TIME_RULES),
        )

    def _transfer_positions_to_rooms(
        self, values: dict[str, int], selected_keys: set[str]
    ) -> None:
        """Copy central position values into every existing room."""
        if not selected_keys:
            return
        for room_entry in self.hass.config_entries.async_entries(DOMAIN):
            if _entry_kind(room_entry) != ENTRY_TYPE_ROOM:
                continue
            options = dict(room_entry.options)
            for key in selected_keys:
                options[key] = int(values[key])
            self.hass.config_entries.async_update_entry(
                room_entry, options=options
            )

    def _transfer_manual_override_to_rooms(self, minutes: int) -> None:
        """Replace every room's manual-override duration with the central value."""
        for room_entry in self.hass.config_entries.async_entries(DOMAIN):
            if _entry_kind(room_entry) != ENTRY_TYPE_ROOM:
                continue
            options = dict(room_entry.options)
            options[CONF_MANUAL_OVERRIDE_MINUTES] = int(minutes)
            self.hass.config_entries.async_update_entry(
                room_entry, options=options
            )

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        # The central entry has an update listener for shared coordinator data.
        # It has no runtime platforms of its own, so reloading the central entry
        # would be redundant and is incompatible with OptionsFlowWithReload when
        # an update listener is registered. Dependent rooms are reloaded once by
        # _save_options after every central options update.
        self.automatic_reload = self._kind() != ENTRY_TYPE_GLOBAL
        if self._kind() == ENTRY_TYPE_GLOBAL:
            return await self.async_step_global_menu(user_input)
        return await self.async_step_room_menu(user_input)

    async def async_step_global_menu(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return self.async_show_menu(
            step_id="global_menu",
            menu_options=[
                "global_settings",
                "global_positions",
                "global_manual_override",
                "add_global_time_rule",
            ],
        )

    async def async_step_room_menu(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return self.async_show_menu(
            step_id="room_menu",
            menu_options=["room", "covers", "behavior", "positions", "room_time_rules"],
        )

    async def async_step_global_settings(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            if (
                not user_input.get(CONF_WORKDAY_ENTITY)
                and _workday_dependent_rules_exist(self.hass)
            ):
                errors["base"] = "workday_sensor_required"
            elif error := _validate_global_settings(user_input):
                errors["base"] = error
            else:
                cleaned = _clean_global_input(user_input)
                # Initial values live in config_entry.data. Omitting a cleared
                # optional key from options would expose that old value again
                # when data and options are merged. Store an explicit None so
                # users can permanently disable an optional global entity.
                for key in _OPTIONAL_GLOBAL_ENTITIES:
                    cleaned.setdefault(key, None)
                return self._save_options(cleaned)
        return self.async_show_form(
            step_id="global_settings",
            data_schema=_global_schema(user_input or self._current()),
            errors=errors,
        )

    async def async_step_global_positions(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            if error := _validate_global_position_settings(self.hass, user_input):
                errors["base"] = error
            else:
                cleaned = _clean_global_positions_input(user_input)
                values = cleaned[CONF_GLOBAL_POSITION_VALUES]
                # Saving the central position page intentionally replaces all
                # corresponding room positions. Rooms may be customized again
                # afterwards until the next central save.
                self._transfer_positions_to_rooms(values, set(values))
                return self._save_options(
                    cleaned, remove_keys=(CONF_GLOBAL_POSITION_OVERRIDES,)
                )
        return self.async_show_form(
            step_id="global_positions",
            data_schema=_global_positions_schema(user_input or self._current()),
            errors=errors,
        )

    async def async_step_global_manual_override(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            cleaned = _clean_global_manual_override_input(user_input)
            minutes = cleaned[CONF_GLOBAL_MANUAL_OVERRIDE_MINUTES]
            self._transfer_manual_override_to_rooms(minutes)
            return self._save_options(cleaned)
        return self.async_show_form(
            step_id="global_manual_override",
            data_schema=_global_manual_override_schema(
                user_input or self._current()
            ),
        )

    async def async_step_room(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            self.hass.config_entries.async_update_entry(
                self.config_entry,
                title=str(user_input[CONF_ROOM_NAME]),
            )
            return self._save_options(user_input)
        return self.async_show_form(
            step_id="room",
            data_schema=_room_schema(self._current(), self.hass.config.language),
        )

    async def async_step_covers(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            if error := _validate_cover_groups(
                user_input,
                covers_in_other_rooms=_covers_in_other_rooms(
                    self.hass,
                    exclude_entry_id=self.config_entry.entry_id,
                ),
                integration_covers=_integration_cover_entities(self.hass),
            ):
                errors["base"] = error
            else:
                room_covers = _ordered_covers(user_input)
                room_cover_set = set(room_covers)
                self._rule_scope = RULE_SCOPE_ROOM
                rules = []
                for rule in self._rules():
                    rule[CONF_RULE_COVERS] = [
                        cover for cover in rule[CONF_RULE_COVERS] if cover in room_cover_set
                    ]
                    if rule[CONF_RULE_COVERS]:
                        rules.append(rule)
                self._pending_cover_data = dict(user_input)
                self._pending_cover_data[CONF_TIME_RULES] = rules
                current_contacts = dict(self._current().get(CONF_COVER_CONTACTS) or {})
                self._cover_contacts = {
                    cover: str(contact)
                    for cover, contact in current_contacts.items()
                    if cover in room_cover_set and contact
                }
                self._contact_queue = room_covers
                self._contact_index = 0
                return await self.async_step_cover_contact()
        return self.async_show_form(
            step_id="covers",
            data_schema=_covers_schema(user_input or self._current()),
            errors=errors,
        )

    async def async_step_cover_contact(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if self._pending_cover_data is None:
            return await self.async_step_covers()
        if self._contact_index >= len(self._contact_queue):
            data = dict(self._pending_cover_data)
            data[CONF_COVER_CONTACTS] = dict(self._cover_contacts)
            self._pending_cover_data = None
            return self._save_options(data)

        cover = self._contact_queue[self._contact_index]
        if user_input is not None:
            contact = str(user_input.get(CONF_OPENING_CONTACT) or "").strip()
            if contact:
                self._cover_contacts[cover] = contact
            else:
                self._cover_contacts.pop(cover, None)
            self._contact_index += 1
            return await self.async_step_cover_contact()

        return self.async_show_form(
            step_id="cover_contact",
            data_schema=_cover_contact_schema(self._cover_contacts.get(cover)),
            description_placeholders={
                "cover": _entity_display_name(self.hass, cover),
                "number": str(self._contact_index + 1),
                "total": str(len(self._contact_queue)),
            },
        )

    async def async_step_behavior(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            if error := _validate_temperatures(user_input):
                errors["base"] = error
            else:
                return self._save_options(user_input)
        return self.async_show_form(
            step_id="behavior",
            data_schema=_behavior_schema(self._current()),
            errors=errors,
        )

    async def async_step_positions(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            if error := _validate_room_position_settings(self.hass, user_input):
                errors["base"] = error
            else:
                return self._save_options(user_input)
        return self.async_show_form(
            step_id="positions",
            data_schema=_positions_schema(
                user_input or self._current(),
                defaults=_configured_global_position_values(self.hass),
            ),
            errors=errors,
        )

    async def async_step_room_time_rules(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        self._rule_scope = RULE_SCOPE_ROOM
        menu = ["add_room_time_rule"]
        if self._rules():
            menu.extend(["edit_room_time_rule", "delete_room_time_rule"])
        menu.append("back_room_menu")
        return self.async_show_menu(step_id="room_time_rules", menu_options=menu)

    async def async_step_back_global_menu(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return await self.async_step_global_menu()

    async def async_step_back_room_menu(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return await self.async_step_room_menu()

    async def async_step_add_global_time_rule(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        self._rule_scope = RULE_SCOPE_GLOBAL
        self._editing_rule_id = None
        self._rule_draft = _rule_defaults(
            scope=RULE_SCOPE_GLOBAL, language=self.hass.config.language
        )
        return await self.async_step_global_rule_basics(user_input)

    async def async_step_add_room_time_rule(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        self._rule_scope = RULE_SCOPE_ROOM
        self._editing_rule_id = None
        self._rule_draft = _rule_defaults(
            scope=RULE_SCOPE_ROOM,
            room_covers=self._room_covers_list(),
            language=self.hass.config.language,
        )
        return await self.async_step_room_rule_basics(user_input)

    async def async_step_edit_room_time_rule(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        self._rule_scope = RULE_SCOPE_ROOM
        return await self._async_step_select_rule_for_edit(
            step_id="edit_room_time_rule",
            next_step=self.async_step_room_rule_basics,
            user_input=user_input,
        )

    async def _async_step_select_rule_for_edit(
        self,
        *,
        step_id: str,
        next_step: Any,
        user_input: dict[str, Any] | None,
    ) -> ConfigFlowResult:
        choices = self._rule_choices()
        if not choices:
            return await self.async_step_room_time_rules()
        if user_input is not None:
            self._editing_rule_id = str(user_input[CONF_SELECTED_RULE])
            existing = self._find_rule(self._editing_rule_id)
            if existing is None:
                return await self.async_step_room_time_rules()
            self._rule_draft = _rule_defaults(
                existing,
                scope=self._rule_scope,
                room_covers=self._room_covers_list(),
                language=self.hass.config.language,
            )
            return await next_step()
        return self.async_show_form(
            step_id=step_id,
            data_schema=vol.Schema(
                {vol.Required(CONF_SELECTED_RULE): _rule_choice_selector(choices)}
            ),
        )

    async def async_step_global_rule_basics(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return await self._async_step_rule_basics(
            step_id="global_rule_basics",
            next_step=self.async_step_global_rule_trigger,
            user_input=user_input,
        )

    async def async_step_room_rule_basics(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return await self._async_step_rule_basics(
            step_id="room_rule_basics",
            next_step=self.async_step_room_rule_trigger,
            user_input=user_input,
        )

    async def _async_step_rule_basics(
        self,
        *,
        step_id: str,
        next_step: Any,
        user_input: dict[str, Any] | None,
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            if error := _validate_rule_basics(
                user_input,
                scope=self._rule_scope,
                room_covers=self._room_covers() if self._rule_scope == RULE_SCOPE_ROOM else None,
                workday_available=bool(_configured_workday_entity(self.hass)),
            ):
                errors["base"] = error
            else:
                self._rule_draft.update(user_input)
                return await next_step()
        return self.async_show_form(
            step_id=step_id,
            data_schema=_rule_basics_schema(
                self.hass,
                scope=self._rule_scope,
                room_covers=self._room_covers_list(),
                values=user_input or self._rule_draft,
            ),
            errors=errors,
        )

    async def async_step_global_rule_trigger(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return await self._async_step_rule_trigger(
            step_id="global_rule_trigger",
            next_step=self.async_step_global_rule_trigger_value,
            user_input=user_input,
        )

    async def async_step_room_rule_trigger(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return await self._async_step_rule_trigger(
            step_id="room_rule_trigger",
            next_step=self.async_step_room_rule_trigger_value,
            user_input=user_input,
        )

    async def _async_step_rule_trigger(
        self,
        *,
        step_id: str,
        next_step: Any,
        user_input: dict[str, Any] | None,
    ) -> ConfigFlowResult:
        if user_input is not None:
            self._rule_draft.update(user_input)
            return await next_step()
        return self.async_show_form(
            step_id=step_id,
            data_schema=_rule_reference_schema(
                str(self._rule_draft[CONF_RULE_TRIGGER_REFERENCE])
            ),
        )

    async def async_step_global_rule_trigger_value(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return await self._async_step_rule_trigger_value(
            step_id="global_rule_trigger_value",
            user_input=user_input,
        )

    async def async_step_room_rule_trigger_value(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return await self._async_step_rule_trigger_value(
            step_id="room_rule_trigger_value",
            user_input=user_input,
        )

    async def _async_step_rule_trigger_value(
        self,
        *,
        step_id: str,
        user_input: dict[str, Any] | None,
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        reference = str(self._rule_draft[CONF_RULE_TRIGGER_REFERENCE])
        if user_input is not None:
            self._rule_draft.update(user_input)
            if error := _validate_complete_time_rule(
                self._rule_draft,
                scope=self._rule_scope,
                room_covers=self._room_covers() if self._rule_scope == RULE_SCOPE_ROOM else None,
                workday_available=bool(_configured_workday_entity(self.hass)),
            ):
                errors["base"] = error
            else:
                updated = _normalized_rule_from_input(
                    self._rule_draft,
                    scope=self._rule_scope,
                    rule_id=self._editing_rule_id,
                )
                if self._rule_scope == RULE_SCOPE_GLOBAL:
                    # The global wizard creates exactly one new rule and appends
                    # an independent copy to every existing room. It does not
                    # maintain a central rule list and therefore offers no later
                    # global edit or delete operation.
                    self._rule_draft = {}
                    self._editing_rule_id = None
                    return self._distribute_new_global_rule(updated)

                rules = self._rules()
                conflict = first_blocking_conflict(
                    updated,
                    rules,
                    self._room_covers(),
                    editing_rule_id=self._editing_rule_id,
                )
                if conflict:
                    errors["base"] = conflict
                else:
                    if self._editing_rule_id is None:
                        rules.append(updated)
                    else:
                        rules = [
                            updated if rule[CONF_RULE_ID] == self._editing_rule_id else rule
                            for rule in rules
                        ]
                    self._rule_draft = {}
                    self._editing_rule_id = None
                    return self._save_rules(rules)
        return self.async_show_form(
            step_id=step_id,
            data_schema=_rule_time_or_offset_schema(
                reference=reference,
                values=self._rule_draft,
            ),
            errors=errors,
        )

    async def async_step_delete_room_time_rule(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        self._rule_scope = RULE_SCOPE_ROOM
        return await self._async_step_select_rule_for_delete(
            step_id="delete_room_time_rule",
            next_step=self.async_step_confirm_delete_room_rule,
            user_input=user_input,
        )

    async def _async_step_select_rule_for_delete(
        self,
        *,
        step_id: str,
        next_step: Any,
        user_input: dict[str, Any] | None,
    ) -> ConfigFlowResult:
        choices = self._rule_choices()
        if not choices:
            return await self.async_step_room_time_rules()
        if user_input is not None:
            self._selected_rule_id = str(user_input[CONF_SELECTED_RULE])
            return await next_step()
        return self.async_show_form(
            step_id=step_id,
            data_schema=vol.Schema(
                {vol.Required(CONF_SELECTED_RULE): _rule_choice_selector(choices)}
            ),
        )

    async def async_step_confirm_delete_room_rule(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        self._rule_scope = RULE_SCOPE_ROOM
        return await self._async_step_confirm_delete(
            step_id="confirm_delete_room_rule",
            user_input=user_input,
        )

    async def _async_step_confirm_delete(
        self,
        *,
        step_id: str,
        user_input: dict[str, Any] | None,
    ) -> ConfigFlowResult:
        selected = self._find_rule(self._selected_rule_id)
        if selected is None:
            return await self.async_step_room_time_rules()
        if user_input is not None:
            if bool(user_input[CONF_CONFIRM_DELETE]):
                rules = [
                    rule
                    for rule in self._rules()
                    if rule[CONF_RULE_ID] != self._selected_rule_id
                ]
                self._selected_rule_id = None
                return self._save_rules(rules)
            self._selected_rule_id = None
            return await self.async_step_room_time_rules()
        return self.async_show_form(
            step_id=step_id,
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_CONFIRM_DELETE,
                        default=False,
                    ): selector.BooleanSelector()
                }
            ),
        )
