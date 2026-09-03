"""Helpers for event-based Smart Shading Control time rules."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime, time, timedelta, timezone, tzinfo
from typing import Any

from .logic import as_list
from .const import (
    CONF_RULE_ACTION,
    CONF_RULE_COVERS,
    CONF_RULE_DAY_TYPE,
    CONF_RULE_ENABLED,
    CONF_RULE_FRIDAY,
    CONF_RULE_END,
    CONF_RULE_END_OFFSET,
    CONF_RULE_END_REFERENCE,
    CONF_RULE_ID,
    CONF_RULE_MONDAY,
    CONF_RULE_NAME,
    CONF_RULE_POSITION,
    CONF_RULE_PRIORITY,
    CONF_RULE_SATURDAY,
    CONF_RULE_SCOPE,
    CONF_RULE_START,
    CONF_RULE_START_OFFSET,
    CONF_RULE_START_REFERENCE,
    CONF_RULE_SUNDAY,
    CONF_RULE_THURSDAY,
    CONF_RULE_TRIGGER,
    CONF_RULE_TRIGGER_OFFSET,
    CONF_RULE_TRIGGER_REFERENCE,
    CONF_RULE_TUESDAY,
    CONF_RULE_WEDNESDAY,
    DAY_TYPE_ANY,
    DAY_TYPE_NON_WORKDAY,
    DAY_TYPE_WORKDAY,
    DAY_TYPES,
    DST_AMBIGUOUS_FIRST,
    DST_NONEXISTENT_SHIFT_FORWARD,
    RULE_ACTION_CLOSE,
    RULE_ACTIONS,
    RULE_SCOPE_ROOM,
    TIME_REFERENCE_FIXED,
    TIME_REFERENCE_SUNRISE,
    TIME_REFERENCE_SUNSET,
    TIME_REFERENCES,
)

SolarEventResolver = Callable[[str, date], datetime | None]
DayTypeResolver = Callable[[date], bool | None]

_WEEKDAY_FIELDS = (
    CONF_RULE_MONDAY,
    CONF_RULE_TUESDAY,
    CONF_RULE_WEDNESDAY,
    CONF_RULE_THURSDAY,
    CONF_RULE_FRIDAY,
    CONF_RULE_SATURDAY,
    CONF_RULE_SUNDAY,
)


def normalize_time(value: Any) -> str:
    """Return a selector value as HH:MM:SS."""
    if isinstance(value, time):
        return value.replace(microsecond=0).isoformat()
    text = str(value or "").strip()
    if not text:
        return "00:00:00"
    parts = text.split(":")
    if len(parts) not in {2, 3}:
        raise ValueError(f"Unsupported time value: {value!r}")
    hour = int(parts[0])
    minute = int(parts[1])
    second = int(float(parts[2])) if len(parts) == 3 else 0
    return time(hour=hour, minute=minute, second=second).isoformat()


def parse_time(value: Any) -> time:
    """Parse a stored time value."""
    hour, minute, second = (int(part) for part in normalize_time(value).split(":"))
    return time(hour=hour, minute=minute, second=second)


def _normalize_reference(value: Any) -> str:
    reference = str(value or TIME_REFERENCE_FIXED)
    return reference if reference in TIME_REFERENCES else TIME_REFERENCE_FIXED


def _normalize_day_type(value: Any) -> str:
    day_type = str(value or DAY_TYPE_ANY)
    return day_type if day_type in DAY_TYPES else DAY_TYPE_ANY


def _normalize_action(value: Any) -> str:
    action = str(value or RULE_ACTION_CLOSE)
    return action if action in RULE_ACTIONS else RULE_ACTION_CLOSE


def normalize_boolean(value: Any, default: bool = True) -> bool:
    """Return a stored selector value as a real boolean.

    Config entries normally contain JSON booleans. Older development builds
    and manually edited storage can, however, contain strings such as
    ``"false"``. Python's normal ``bool("false")`` would incorrectly enable
    the corresponding weekday or legacy rule.
    """
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    normalized = str(value).strip().lower()
    if normalized in {"0", "false", "no", "off", "disabled"}:
        return False
    if normalized in {"1", "true", "yes", "on", "enabled"}:
        return True
    return bool(value)


def normalize_rule(rule: dict[str, Any]) -> dict[str, Any]:
    """Return a JSON-serializable, complete event rule dictionary."""
    result = dict(rule)
    result[CONF_RULE_ID] = str(result.get(CONF_RULE_ID, ""))
    result[CONF_RULE_NAME] = str(result.get(CONF_RULE_NAME, "Rule")).strip() or "Rule"
    result.pop(CONF_RULE_ENABLED, None)
    for legacy_key in (
        CONF_RULE_START_REFERENCE,
        CONF_RULE_START,
        CONF_RULE_START_OFFSET,
        CONF_RULE_END_REFERENCE,
        CONF_RULE_END,
        CONF_RULE_END_OFFSET,
        CONF_RULE_POSITION,
    ):
        result.pop(legacy_key, None)
    result[CONF_RULE_DAY_TYPE] = _normalize_day_type(result.get(CONF_RULE_DAY_TYPE))
    result[CONF_RULE_SCOPE] = str(result.get(CONF_RULE_SCOPE) or RULE_SCOPE_ROOM)
    result[CONF_RULE_ACTION] = _normalize_action(result.get(CONF_RULE_ACTION))
    result[CONF_RULE_TRIGGER_REFERENCE] = _normalize_reference(
        result.get(CONF_RULE_TRIGGER_REFERENCE)
    )
    result[CONF_RULE_TRIGGER] = normalize_time(
        result.get(CONF_RULE_TRIGGER, "22:00:00")
    )
    result[CONF_RULE_TRIGGER_OFFSET] = max(
        -720, min(720, int(result.get(CONF_RULE_TRIGGER_OFFSET, 0)))
    )
    result[CONF_RULE_PRIORITY] = max(
        1, min(100, int(result.get(CONF_RULE_PRIORITY, 50)))
    )
    result[CONF_RULE_COVERS] = list(
        dict.fromkeys(
            str(item) for item in as_list(result.get(CONF_RULE_COVERS)) if item
        )
    )
    for field in _WEEKDAY_FIELDS:
        result[field] = normalize_boolean(result.get(field), True)
    return result


def resolve_local_wall_time(
    nominal_date: date,
    wall_time: time,
    local_tz: tzinfo,
    *,
    nonexistent_policy: str = DST_NONEXISTENT_SHIFT_FORWARD,
    ambiguous_policy: str = DST_AMBIGUOUS_FIRST,
) -> datetime | None:
    """Resolve a local wall time across daylight-saving transitions."""
    naive = datetime.combine(nominal_date, wall_time)

    def valid_candidates(candidate_naive: datetime) -> list[datetime]:
        candidates: list[datetime] = []
        for fold in (0, 1):
            candidate = candidate_naive.replace(tzinfo=local_tz, fold=fold)
            roundtrip = candidate.astimezone(timezone.utc).astimezone(local_tz)
            if roundtrip.replace(tzinfo=None) != candidate_naive:
                continue
            if not any(existing.utcoffset() == candidate.utcoffset() for existing in candidates):
                candidates.append(candidate)
        return candidates

    candidates = valid_candidates(naive)
    if not candidates:
        if nonexistent_policy != DST_NONEXISTENT_SHIFT_FORWARD:
            return None
        shifted = naive
        for _ in range(180):
            shifted += timedelta(minutes=1)
            candidates = valid_candidates(shifted)
            if candidates:
                break
        else:
            return None
    if len(candidates) == 1:
        return candidates[0]
    candidates.sort(key=lambda value: value.astimezone(timezone.utc))
    return candidates[0] if ambiguous_policy == DST_AMBIGUOUS_FIRST else candidates[-1]


def resolve_rule_datetime(
    rule: dict[str, Any],
    nominal_date: date,
    local_tz: tzinfo,
    solar_resolver: SolarEventResolver | None = None,
    *,
    nonexistent_policy: str = DST_NONEXISTENT_SHIFT_FORWARD,
    ambiguous_policy: str = DST_AMBIGUOUS_FIRST,
) -> datetime | None:
    """Resolve the event trigger for one nominal calendar day."""
    rule = normalize_rule(rule)
    reference = rule[CONF_RULE_TRIGGER_REFERENCE]
    offset = timedelta(minutes=int(rule[CONF_RULE_TRIGGER_OFFSET]))

    if reference == TIME_REFERENCE_FIXED:
        return resolve_local_wall_time(
            nominal_date,
            parse_time(rule[CONF_RULE_TRIGGER]),
            local_tz,
            nonexistent_policy=nonexistent_policy,
            ambiguous_policy=ambiguous_policy,
        )

    if solar_resolver is None:
        return None
    event = (
        TIME_REFERENCE_SUNRISE
        if reference == TIME_REFERENCE_SUNRISE
        else TIME_REFERENCE_SUNSET
    )
    event_time = solar_resolver(event, nominal_date)
    if event_time is None:
        return None
    if event_time.tzinfo is None:
        event_time = event_time.replace(tzinfo=local_tz)
    else:
        event_time = event_time.astimezone(local_tz)
    return event_time + offset


def _day_type_matches(rule: dict[str, Any], is_workday: bool | None) -> bool:
    day_type = str(rule.get(CONF_RULE_DAY_TYPE) or DAY_TYPE_ANY)
    if day_type == DAY_TYPE_ANY:
        return True
    if day_type == DAY_TYPE_WORKDAY:
        return is_workday is True
    if day_type == DAY_TYPE_NON_WORKDAY:
        return is_workday is False
    return False


def rule_occurrences_between(
    rule: dict[str, Any],
    local_start_exclusive: datetime,
    local_end_inclusive: datetime,
    solar_resolver: SolarEventResolver | None = None,
    *,
    is_workday: bool | None = None,
    day_type_resolver: DayTypeResolver | None = None,
    nonexistent_policy: str = DST_NONEXISTENT_SHIFT_FORWARD,
    ambiguous_policy: str = DST_AMBIGUOUS_FIRST,
) -> list[datetime]:
    """Return matching event occurrences in the supplied local time window."""
    rule = normalize_rule(rule)
    if local_start_exclusive.tzinfo is None or local_end_inclusive.tzinfo is None:
        raise ValueError("time-rule windows must be timezone-aware")
    if local_end_inclusive.astimezone(timezone.utc) <= local_start_exclusive.astimezone(timezone.utc):
        return []

    occurrences: list[datetime] = []
    first_date = local_start_exclusive.date() - timedelta(days=1)
    last_date = local_end_inclusive.date() + timedelta(days=1)
    nominal_date = first_date
    while nominal_date <= last_date:
        trigger = resolve_rule_datetime(
            rule,
            nominal_date,
            local_end_inclusive.tzinfo,
            solar_resolver,
            nonexistent_policy=nonexistent_policy,
            ambiguous_policy=ambiguous_policy,
        )
        if trigger is not None:
            trigger_utc = trigger.astimezone(timezone.utc)
            if (
                local_start_exclusive.astimezone(timezone.utc)
                < trigger_utc
                <= local_end_inclusive.astimezone(timezone.utc)
            ):
                event_date = trigger.astimezone(local_end_inclusive.tzinfo).date()
                event_is_workday = (
                    day_type_resolver(event_date)
                    if day_type_resolver is not None
                    else is_workday
                )
                if (
                    rule[_WEEKDAY_FIELDS[event_date.weekday()]]
                    and _day_type_matches(rule, event_is_workday)
                ):
                    occurrences.append(trigger)
        nominal_date += timedelta(days=1)

    occurrences.sort(key=lambda value: value.astimezone(timezone.utc))
    return occurrences


def resolve_rule_actions(
    rules: list[dict[str, Any]],
    local_start_exclusive: datetime,
    local_end_inclusive: datetime,
    all_covers: list[str],
    solar_resolver: SolarEventResolver | None = None,
    *,
    is_workday: bool | None = None,
    day_type_resolver: DayTypeResolver | None = None,
    nonexistent_policy: str = DST_NONEXISTENT_SHIFT_FORWARD,
    ambiguous_policy: str = DST_AMBIGUOUS_FIRST,
    already_executed: set[str] | None = None,
) -> tuple[dict[str, str], list[dict[str, Any]], set[str]]:
    """Resolve due rule events independently for every cover.

    The newest event wins. Events at the same instant are ordered by higher
    priority and then by stable stored-rule order. Central templates are copied
    into room entries before runtime and therefore require no cross-scope
    suppression here.
    """
    if local_start_exclusive.tzinfo is None or local_end_inclusive.tzinfo is None:
        raise ValueError("time-rule windows must be timezone-aware")

    available = set(all_covers)
    executed = already_executed or set()
    normalized_rules: list[dict[str, Any]] = []
    for raw_rule in rules:
        if not isinstance(raw_rule, dict):
            continue
        try:
            if not normalize_boolean(raw_rule.get(CONF_RULE_ENABLED), True):
                continue
            normalized_rules.append(normalize_rule(raw_rule))
        except (KeyError, TypeError, ValueError):
            # Damaged legacy storage is reported by schedule-conflict
            # diagnostics, but must never abort room control.
            continue
    rule_id_counts: dict[tuple[str, str], int] = {}
    for rule in normalized_rules:
        identity = (str(rule[CONF_RULE_SCOPE]), str(rule[CONF_RULE_ID]).strip())
        rule_id_counts[identity] = rule_id_counts.get(identity, 0) + 1
    due: list[tuple[float, int, int, dict[str, Any], datetime, str]] = []

    for index, rule in enumerate(normalized_rules):
        for trigger in rule_occurrences_between(
            rule,
            local_start_exclusive,
            local_end_inclusive,
            solar_resolver,
            is_workday=is_workday,
            day_type_resolver=day_type_resolver,
            nonexistent_policy=nonexistent_policy,
            ambiguous_policy=ambiguous_policy,
        ):
            rule_id = str(rule[CONF_RULE_ID]).strip()
            identity = (str(rule[CONF_RULE_SCOPE]), rule_id)
            # Properly created rules have a unique ID. Keep malformed legacy
            # rules independent as well so an empty or duplicated ID cannot
            # cause one event to suppress another event at the same instant.
            occurrence_rule_id = (
                rule_id
                if rule_id and rule_id_counts.get(identity, 0) == 1
                else f"{rule_id or 'legacy'}@{index}"
            )
            occurrence_key = (
                f"{rule[CONF_RULE_SCOPE]}:{occurrence_rule_id}:"
                f"{trigger.astimezone(timezone.utc).isoformat()}"
            )
            if occurrence_key in executed:
                continue
            due.append(
                (
                    -trigger.astimezone(timezone.utc).timestamp(),
                    -int(rule[CONF_RULE_PRIORITY]),
                    index,
                    rule,
                    trigger,
                    occurrence_key,
                )
            )

    actions: dict[str, str] = {}
    diagnostics: list[dict[str, Any]] = []
    new_occurrences: set[str] = set()
    for _, _, _, rule, trigger, occurrence_key in sorted(
        due, key=lambda item: (item[0], item[1], item[2])
    ):
        configured = [
            cover for cover in list(rule[CONF_RULE_COVERS]) if cover in available
        ]
        suppressed_by_room_rules: list[str] = []
        selected = configured
        won: list[str] = []
        for cover in selected:
            if cover not in actions:
                actions[cover] = str(rule[CONF_RULE_ACTION])
                won.append(cover)
        new_occurrences.add(occurrence_key)
        diagnostics.append(
            {
                "id": rule[CONF_RULE_ID],
                "name": rule[CONF_RULE_NAME],
                "scope": rule[CONF_RULE_SCOPE],
                "day_type": rule[CONF_RULE_DAY_TYPE],
                "action": rule[CONF_RULE_ACTION],
                "priority": rule[CONF_RULE_PRIORITY],
                "configured_covers": configured,
                "suppressed_by_room_rules": suppressed_by_room_rules,
                "effective_covers": won,
                "trigger_reference": rule[CONF_RULE_TRIGGER_REFERENCE],
                "trigger_time": rule[CONF_RULE_TRIGGER],
                "trigger_offset_minutes": rule[CONF_RULE_TRIGGER_OFFSET],
                "resolved_trigger": trigger.isoformat(),
                "occurrence_key": occurrence_key,
            }
        )

    return actions, diagnostics, new_occurrences

def resolve_rule_states(
    rules: list[dict[str, Any]],
    local_now: datetime,
    all_covers: list[str],
    solar_resolver: SolarEventResolver | None = None,
    *,
    is_workday: bool | None = None,
    day_type_resolver: DayTypeResolver | None = None,
    nonexistent_policy: str = DST_NONEXISTENT_SHIFT_FORWARD,
    ambiguous_policy: str = DST_AMBIGUOUS_FIRST,
    lookback_days: int = 8,
) -> tuple[dict[str, str], list[dict[str, Any]]]:
    """Return the latest matching action for every cover.

    Weekly rules need at most seven days of history. One additional day covers
    solar offsets and daylight-saving transitions. The latest close action is
    used by the controller as a persistent night closure until a newer open
    event releases it.
    """
    if local_now.tzinfo is None:
        raise ValueError("time-rule state evaluation requires a timezone-aware time")
    window_days = max(8, int(lookback_days))
    actions, diagnostics, _ = resolve_rule_actions(
        rules,
        local_now - timedelta(days=window_days),
        local_now,
        all_covers,
        solar_resolver,
        is_workday=is_workday,
        day_type_resolver=day_type_resolver,
        nonexistent_policy=nonexistent_policy,
        ambiguous_policy=ambiguous_policy,
    )
    return actions, [
        item for item in diagnostics if item.get("effective_covers")
    ]

