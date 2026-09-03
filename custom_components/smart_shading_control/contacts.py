"""Opening-contact state classification helpers."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timedelta
from typing import Any

from .const import (
    CONTACT_CLOSED,
    CONTACT_NONE,
    CONTACT_OPEN,
    CONTACT_TILTED,
    CONTACT_UNKNOWN,
)

_TILTED_TOKENS = {
    "ajar",
    "kip",
    "kipp",
    "gekippt",
    "tilt",
    "tilted",
    "vent",
    "ventilation",
}
_OPEN_TOKENS = {
    "1",
    "detected",
    "ein",
    "on",
    "open",
    "opened",
    "opening",
    "offen",
    "geöffnet",
    "geoeffnet",
    "true",
    "unlocked",
}
_CLOSED_TOKENS = {
    "0",
    "clear",
    "closed",
    "closing",
    "geschlossen",
    "false",
    "locked",
    "off",
    "zu",
}
_UNKNOWN_TOKENS = {"", "none", "null", "unavailable", "unknown"}
_ATTRIBUTE_KEYS = (
    "contact_state",
    "opening_state",
    "window_state",
    "door_state",
    "position",
    "status",
)


def _normalize(value: Any) -> str:
    return str(value if value is not None else "").strip().lower().replace("-", "_")


def classify_contact_state(
    state: Any,
    attributes: Mapping[str, Any] | None = None,
) -> str:
    """Classify a contact entity as closed, tilted, open or unknown.

    Multi-state sensors may expose words such as ``tilted`` or ``open`` either
    as their state or in a common state attribute. A binary sensor's ``on``
    state is treated as open, which is the safest interpretation.
    """
    primary_state = _normalize(state)
    if primary_state in {"unavailable", "unknown"}:
        return CONTACT_UNKNOWN

    values = [primary_state]
    attrs = attributes or {}
    values.extend(_normalize(attrs.get(key)) for key in _ATTRIBUTE_KEYS if key in attrs)

    tokens: set[str] = set()
    for value in values:
        tokens.add(value)
        tokens.update(part for part in value.replace("/", "_").split("_") if part)

    # A specific tilted/ventilation value takes precedence over a generic
    # binary ``on`` attribute so a multi-state contact remains visible as
    # tilted instead of being flattened to open.
    if tokens & _TILTED_TOKENS:
        return CONTACT_TILTED
    if tokens & _OPEN_TOKENS:
        return CONTACT_OPEN
    if tokens & _CLOSED_TOKENS:
        return CONTACT_CLOSED
    if not tokens or tokens <= _UNKNOWN_TOKENS:
        return CONTACT_UNKNOWN
    return CONTACT_UNKNOWN


def summarize_cover_contacts(
    all_covers: list[str],
    assignments: Mapping[str, str],
    classified_contacts: Mapping[str, str],
) -> dict[str, Any]:
    """Return per-cover and aggregate opening-contact diagnostics."""
    by_cover: dict[str, dict[str, str | None]] = {}
    by_contact: dict[str, dict[str, Any]] = {}
    grouped: dict[str, list[str]] = {
        CONTACT_OPEN: [],
        CONTACT_TILTED: [],
        CONTACT_UNKNOWN: [],
        CONTACT_CLOSED: [],
        CONTACT_NONE: [],
    }

    for cover in all_covers:
        entity_id = str(assignments.get(cover) or "").strip()
        state = (
            classified_contacts.get(entity_id, CONTACT_UNKNOWN)
            if entity_id
            else CONTACT_NONE
        )
        grouped[state].append(cover)
        by_cover[cover] = {
            "entity_id": entity_id or None,
            "state": state,
        }
        if entity_id:
            contact_details = by_contact.setdefault(
                entity_id,
                {"state": state, "covers": []},
            )
            contact_details["state"] = state
            contact_details["covers"].append(cover)

    if grouped[CONTACT_OPEN]:
        overall = CONTACT_OPEN
    elif grouped[CONTACT_UNKNOWN]:
        overall = CONTACT_UNKNOWN
    elif grouped[CONTACT_TILTED]:
        overall = CONTACT_TILTED
    elif grouped[CONTACT_CLOSED]:
        overall = CONTACT_CLOSED
    else:
        overall = CONTACT_NONE

    return {
        "overall": overall,
        "by_cover": by_cover,
        "by_contact": by_contact,
        "open_covers": grouped[CONTACT_OPEN],
        "tilted_covers": grouped[CONTACT_TILTED],
        "unknown_covers": grouped[CONTACT_UNKNOWN],
        "closed_covers": grouped[CONTACT_CLOSED],
        "unassigned_covers": grouped[CONTACT_NONE],
    }


# Kept for backwards-compatible diagnostics/tests from the earlier alpha.
def summarize_contacts(contact_states: Mapping[str, str]) -> dict[str, Any]:
    """Return an aggregate summary for a plain contact mapping."""
    grouped = {
        CONTACT_OPEN: [],
        CONTACT_TILTED: [],
        CONTACT_UNKNOWN: [],
        CONTACT_CLOSED: [],
    }
    for entity_id, state in contact_states.items():
        grouped.setdefault(state, []).append(entity_id)

    if grouped[CONTACT_OPEN]:
        overall = CONTACT_OPEN
    elif grouped[CONTACT_UNKNOWN]:
        overall = CONTACT_UNKNOWN
    elif grouped[CONTACT_TILTED]:
        overall = CONTACT_TILTED
    else:
        overall = CONTACT_CLOSED

    return {
        "overall": overall,
        "open": grouped[CONTACT_OPEN],
        "tilted": grouped[CONTACT_TILTED],
        "unknown": grouped[CONTACT_UNKNOWN],
        "closed": grouped[CONTACT_CLOSED],
    }


def resolve_night_close_contact(
    contact_state: str | None,
    *,
    pending: bool,
    retry_at: datetime | None,
    now: datetime,
    delay_seconds: int,
) -> tuple[bool, bool, datetime | None]:
    """Resolve whether an automatic time-rule close must be held back.

    Returns ``(blocked, pending, retry_at)``. Open, tilted and unknown contacts
    block immediately. After the contact becomes closed, the close remains
    blocked for ``delay_seconds`` so bouncing contacts cannot trigger a drive.
    Unassigned contacts (``None``/``CONTACT_NONE``) never restrict a rule.
    """
    if contact_state in {CONTACT_OPEN, CONTACT_TILTED, CONTACT_UNKNOWN}:
        return True, True, None
    if contact_state != CONTACT_CLOSED:
        return False, False, None
    if not pending:
        return False, False, None
    if retry_at is None:
        retry_at = now + timedelta(seconds=max(0, int(delay_seconds)))
    if now < retry_at:
        return True, True, retry_at
    return False, False, None
