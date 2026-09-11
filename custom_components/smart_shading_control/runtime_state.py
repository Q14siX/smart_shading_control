"""Validation helpers for restart-persistent controller state.

The helpers in this module intentionally have no Home Assistant dependencies.
They keep storage parsing deterministic and make the safety-relevant restart
semantics testable without constructing a complete Home Assistant instance.
"""

from __future__ import annotations

import math
from collections.abc import Collection, Mapping
from datetime import datetime, timedelta, timezone
from typing import Any


def parse_utc_timestamp(value: Any) -> datetime | None:
    """Parse one stored timestamp and return an aware UTC datetime."""
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value or "").strip()
        if not text:
            return None
        if text.endswith("Z"):
            text = f"{text[:-1]}+00:00"
        try:
            parsed = datetime.fromisoformat(text)
        except (TypeError, ValueError):
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    try:
        return parsed.astimezone(timezone.utc)
    except (OSError, OverflowError, ValueError):
        return None


def parse_aware_utc_timestamp(value: Any) -> datetime | None:
    """Parse a stored timestamp only when it carries an explicit timezone."""
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value or "").strip()
        if not text:
            return None
        if text.endswith("Z"):
            text = f"{text[:-1]}+00:00"
        try:
            parsed = datetime.fromisoformat(text)
        except (TypeError, ValueError):
            return None
    if parsed.tzinfo is None:
        return None
    try:
        return parsed.astimezone(timezone.utc)
    except (OSError, OverflowError, ValueError):
        return None


def restore_future_timestamps(
    raw: Any,
    *,
    now: datetime,
    allowed_keys: Collection[str] | None = None,
    max_future: timedelta | None = None,
) -> dict[str, datetime]:
    """Restore bounded, non-expired absolute timestamps independently per key."""
    if not isinstance(raw, Mapping):
        return {}
    allowed = set(allowed_keys) if allowed_keys is not None else None
    result: dict[str, datetime] = {}
    for raw_key, raw_value in raw.items():
        key = str(raw_key)
        if allowed is not None and key not in allowed:
            continue
        parsed = parse_utc_timestamp(raw_value)
        if (
            parsed is not None
            and parsed > now
            and (max_future is None or parsed - now <= max_future)
        ):
            result[key] = parsed
    return result


def restore_recent_target_commands(
    raw: Any,
    *,
    now: datetime,
    allowed_keys: Collection[str],
    max_age: timedelta,
) -> dict[str, tuple[int, datetime]]:
    """Restore unexpired target/issued-at command markers."""
    if not isinstance(raw, Mapping):
        return {}
    allowed = set(allowed_keys)
    result: dict[str, tuple[int, datetime]] = {}
    for raw_key, raw_value in raw.items():
        key = str(raw_key)
        if key not in allowed or not isinstance(raw_value, Mapping):
            continue
        try:
            target = max(0, min(100, int(raw_value.get("target"))))
        except (OverflowError, TypeError, ValueError):
            continue
        issued_at = parse_utc_timestamp(raw_value.get("issued_at"))
        if issued_at is None or issued_at > now or now - issued_at > max_age:
            continue
        result[key] = (target, issued_at)
    return result


def restore_pending_target_commands(
    raw: Any,
    *,
    now: datetime,
    allowed_keys: Collection[str],
    max_future: timedelta,
) -> dict[str, tuple[int, datetime]]:
    """Restore bounded target intents with their absolute expiry timestamps."""
    if not isinstance(raw, Mapping):
        return {}
    allowed = set(allowed_keys)
    result: dict[str, tuple[int, datetime]] = {}
    for raw_key, raw_value in raw.items():
        key = str(raw_key)
        if key not in allowed or not isinstance(raw_value, Mapping):
            continue
        try:
            target = max(0, min(100, int(raw_value.get("target"))))
        except (OverflowError, TypeError, ValueError):
            continue
        expires_at = parse_utc_timestamp(raw_value.get("expires_at"))
        if (
            expires_at is None
            or expires_at <= now
            or expires_at - now > max_future
        ):
            continue
        result[key] = (target, expires_at)
    return result


def restore_origin_markers(
    raw: Any,
    *,
    now: datetime,
    allowed_keys: Collection[str],
) -> dict[str, tuple[str, datetime]]:
    """Restore durable per-cover command origins used by contact safety."""
    if not isinstance(raw, Mapping):
        return {}
    allowed = set(allowed_keys)
    result: dict[str, tuple[str, datetime]] = {}
    for raw_key, raw_value in raw.items():
        key = str(raw_key)
        if key not in allowed or not isinstance(raw_value, Mapping):
            continue
        origin = str(raw_value.get("origin") or "").strip()
        issued_at = parse_utc_timestamp(raw_value.get("issued_at"))
        if not origin or issued_at is None or issued_at > now:
            continue
        result[key] = (origin, issued_at)
    return result


def restore_temperature_samples(
    raw: Any,
    *,
    now: datetime,
    horizon: timedelta,
    limit: int,
) -> list[tuple[datetime, float]]:
    """Restore a bounded, ordered temperature history inside its live horizon."""
    if not isinstance(raw, list) or limit <= 0:
        return []
    cutoff = now - horizon
    result: list[tuple[datetime, float]] = []
    for item in raw:
        if not isinstance(item, (list, tuple)) or len(item) != 2:
            continue
        timestamp = parse_utc_timestamp(item[0])
        try:
            value = float(item[1])
        except (OverflowError, TypeError, ValueError):
            continue
        if (
            timestamp is None
            or timestamp < cutoff
            or timestamp > now
            or not math.isfinite(value)
        ):
            continue
        result.append((timestamp, value))
    result.sort(key=lambda item: item[0])
    return result[-max(0, int(limit)) :]
