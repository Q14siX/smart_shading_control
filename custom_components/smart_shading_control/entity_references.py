"""Entity-reference helpers for registry rename handling."""

from __future__ import annotations

from typing import Any

PENDING_ENTITY_RENAMES_KEY = "_pending_entity_renames"

_SCALAR_ENTITY_ID_FIELDS = frozenset(
    {
        "sun_entity",
        "weather_entity",
        "workday_entity",
        "outside_temperature_sensor",
        "irradiance_sensor",
        "illuminance_sensor",
        "wind_sensor",
        "rain_sensor",
        "room_temperature_sensor",
        "opening_contact",
    }
)
_COLLECTION_ENTITY_ID_FIELDS = frozenset(
    {
        "covers_north",
        "covers_east",
        "covers_south",
        "covers_west",
        "opening_contacts",
        "open_window_sensors",
        "tilted_window_sensors",
        "door_sensors",
    }
)
_RULE_COLLECTION_FIELDS = ("time_rules", "global_time_rules")
_RULE_COVERS_FIELD = "covers"
_COVER_CONTACTS_FIELD = "cover_contacts"


def _collection_items(value: Any) -> tuple[Any, ...]:
    """Return collection items without iterating a scalar entity ID."""
    if isinstance(value, (list, tuple, set, frozenset)):
        return tuple(value)
    return (value,) if value is not None else ()


def iter_config_entity_id_candidates(value: Any) -> set[str]:
    """Return entity IDs from the known serialized Config Entry fields only."""
    if not isinstance(value, dict):
        return set()

    result = {
        candidate
        for field in _SCALAR_ENTITY_ID_FIELDS
        if isinstance((candidate := value.get(field)), str)
    }
    for field in _COLLECTION_ENTITY_ID_FIELDS:
        result.update(
            item
            for item in _collection_items(value.get(field))
            if isinstance(item, str)
        )

    contacts = value.get(_COVER_CONTACTS_FIELD)
    if isinstance(contacts, dict):
        result.update(key for key in contacts if isinstance(key, str))
        result.update(item for item in contacts.values() if isinstance(item, str))

    for field in _RULE_COLLECTION_FIELDS:
        for raw_rule in _collection_items(value.get(field)):
            if not isinstance(raw_rule, dict):
                continue
            result.update(
                item
                for item in _collection_items(raw_rule.get(_RULE_COVERS_FIELD))
                if isinstance(item, str)
            )
    return result


def replace_entity_id_references(
    value: Any,
    old_entity_id: str,
    new_entity_id: str,
) -> Any:
    """Return ``value`` with exact entity-ID references replaced recursively.

    Persistent Store payloads contain entity IDs both as values and as per-cover
    mapping keys. If a stale destination key already exists, the value attached
    to the registry-renamed source wins. Config Entries use the schema-aware
    wrapper below so entity-shaped user labels and rule IDs remain untouched.
    """
    if isinstance(value, str):
        return new_entity_id if value == old_entity_id else value
    if isinstance(value, list):
        return [
            replace_entity_id_references(item, old_entity_id, new_entity_id)
            for item in value
        ]
    if isinstance(value, tuple):
        return tuple(
            replace_entity_id_references(item, old_entity_id, new_entity_id)
            for item in value
        )
    if isinstance(value, set):
        return {
            replace_entity_id_references(item, old_entity_id, new_entity_id)
            for item in value
        }
    if isinstance(value, frozenset):
        return frozenset(
            replace_entity_id_references(item, old_entity_id, new_entity_id)
            for item in value
        )
    if not isinstance(value, dict):
        return value

    result = {
        replace_entity_id_references(
            key, old_entity_id, new_entity_id
        ): replace_entity_id_references(nested_value, old_entity_id, new_entity_id)
        for key, nested_value in value.items()
        if key != old_entity_id
    }
    if old_entity_id in value:
        result[new_entity_id] = replace_entity_id_references(
            value[old_entity_id],
            old_entity_id,
            new_entity_id,
        )
    return result


def replace_config_entity_id_references(
    value: Any,
    old_entity_id: str,
    new_entity_id: str,
) -> Any:
    """Replace an entity ID only in fields whose Config Entry schema stores one."""
    if not isinstance(value, dict):
        return value

    result = dict(value)
    for field in _SCALAR_ENTITY_ID_FIELDS:
        if result.get(field) == old_entity_id:
            result[field] = new_entity_id
    for field in _COLLECTION_ENTITY_ID_FIELDS:
        if field in result:
            result[field] = replace_entity_id_references(
                result[field], old_entity_id, new_entity_id
            )
    if _COVER_CONTACTS_FIELD in result:
        result[_COVER_CONTACTS_FIELD] = replace_entity_id_references(
            result[_COVER_CONTACTS_FIELD], old_entity_id, new_entity_id
        )

    def replace_rule(raw_rule: Any) -> Any:
        if not isinstance(raw_rule, dict):
            return raw_rule
        rule = dict(raw_rule)
        if _RULE_COVERS_FIELD in rule:
            rule[_RULE_COVERS_FIELD] = replace_entity_id_references(
                rule[_RULE_COVERS_FIELD], old_entity_id, new_entity_id
            )
        return rule

    for field in _RULE_COLLECTION_FIELDS:
        raw_rules = result.get(field)
        if isinstance(raw_rules, list):
            result[field] = [replace_rule(rule) for rule in raw_rules]
        elif isinstance(raw_rules, tuple):
            result[field] = tuple(replace_rule(rule) for rule in raw_rules)
        elif isinstance(raw_rules, dict):
            result[field] = replace_rule(raw_rules)
    return result


def normalize_pending_entity_renames(value: Any) -> list[dict[str, str]]:
    """Validate a rename sequence, removing adjacent duplicate notifications.

    Non-adjacent repeats are significant: A → B → A → B must end at B.
    Removing every previously seen pair would incorrectly stop at A and lose
    the association between the current entity and its persisted overrides.
    """
    if not isinstance(value, list):
        return []
    result: list[dict[str, str]] = []
    previous_pair: tuple[str, str] | None = None
    for item in value:
        if not isinstance(item, dict):
            continue
        old_entity_id = str(item.get("old_entity_id") or "").strip()
        new_entity_id = str(item.get("new_entity_id") or "").strip()
        pair = (old_entity_id, new_entity_id)
        if not old_entity_id or not new_entity_id or old_entity_id == new_entity_id:
            continue
        if pair == previous_pair:
            continue
        previous_pair = pair
        result.append(
            {
                "old_entity_id": old_entity_id,
                "new_entity_id": new_entity_id,
            }
        )
    return result


def apply_pending_entity_renames(value: Any, renames: Any) -> Any:
    """Apply a validated pending rename sequence to one payload."""
    result = value
    for rename in normalize_pending_entity_renames(renames):
        result = replace_entity_id_references(
            result,
            rename["old_entity_id"],
            rename["new_entity_id"],
        )
    return result


def apply_pending_config_entity_renames(value: Any, renames: Any) -> Any:
    """Apply pending renames only to schema-defined Config Entry references."""
    result = value
    for rename in normalize_pending_entity_renames(renames):
        result = replace_config_entity_id_references(
            result,
            rename["old_entity_id"],
            rename["new_entity_id"],
        )
    return result
