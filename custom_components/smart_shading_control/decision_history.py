"""Privacy-aware decision history for Smart Shading Control."""

from __future__ import annotations

from collections import deque
from copy import deepcopy
from datetime import datetime
from typing import Any


class DecisionHistory:
    """Keep a bounded machine-readable chronicle and export aliases."""

    def __init__(self, *, max_entries: int = 100) -> None:
        self._records: deque[dict[str, Any]] = deque(maxlen=max(10, max_entries))

    def append(
        self,
        *,
        timestamp: datetime,
        status: str,
        reason_code: str,
        desired_positions: dict[str, int],
        commanded_positions: dict[str, int],
        actual_positions: dict[str, int | None] | None = None,
        dry_run: bool,
        active_weather_protection: str | None,
        command_queue: dict[str, Any] | None = None,
    ) -> None:
        """Append one complete control decision."""
        self._records.append(
            {
                "timestamp": timestamp.isoformat(),
                "status": status,
                "reason_code": reason_code,
                "desired_positions": dict(desired_positions),
                "commanded_positions": dict(commanded_positions),
                "actual_positions": dict(actual_positions or {}),
                "dry_run": bool(dry_run),
                "active_weather_protection": active_weather_protection,
                "command_queue": deepcopy(command_queue or {}),
            }
        )

    def clear(self) -> None:
        self._records.clear()

    def sanitized(self, covers: list[str]) -> dict[str, Any]:
        """Return an export payload without entity IDs or room names."""
        ordered_entities = list(dict.fromkeys(str(entity_id) for entity_id in covers))
        for record in self._records:
            for key in (
                "desired_positions",
                "commanded_positions",
                "actual_positions",
            ):
                value = record.get(key)
                if isinstance(value, dict):
                    for entity_id in value:
                        text = str(entity_id)
                        if text not in ordered_entities:
                            ordered_entities.append(text)
            queue = record.get("command_queue")
            if isinstance(queue, dict):
                for item in queue.get("active_commands", []):
                    if isinstance(item, dict) and item.get("entity_id"):
                        text = str(item["entity_id"])
                        if text not in ordered_entities:
                            ordered_entities.append(text)
                for queue_key in ("active", "last_result"):
                    item = queue.get(queue_key)
                    if isinstance(item, dict) and item.get("entity_id"):
                        text = str(item["entity_id"])
                        if text not in ordered_entities:
                            ordered_entities.append(text)
        aliases = {
            entity_id: f"cover_{index}"
            for index, entity_id in enumerate(ordered_entities, 1)
        }

        def alias_mapping(value: Any) -> Any:
            if not isinstance(value, dict):
                return value
            return {
                aliases.get(str(key), "unassigned_cover"): item
                for key, item in value.items()
            }

        entries: list[dict[str, Any]] = []
        for record in self._records:
            cleaned = dict(record)
            for key in (
                "desired_positions",
                "commanded_positions",
                "actual_positions",
            ):
                cleaned[key] = alias_mapping(cleaned.get(key))
            queue = deepcopy(cleaned.get("command_queue") or {})
            for item in queue.get("active_commands", []):
                if isinstance(item, dict) and item.get("entity_id"):
                    item["entity_id"] = aliases.get(
                        str(item["entity_id"]), "unassigned_cover"
                    )
            active = queue.get("active")
            if isinstance(active, dict) and active.get("entity_id"):
                active = dict(active)
                active["entity_id"] = aliases.get(
                    str(active["entity_id"]), "unassigned_cover"
                )
                queue["active"] = active
            last_result = queue.get("last_result")
            if isinstance(last_result, dict) and last_result.get("entity_id"):
                last_result = dict(last_result)
                last_result["entity_id"] = aliases.get(
                    str(last_result["entity_id"]), "unassigned_cover"
                )
                queue["last_result"] = last_result
            cleaned["command_queue"] = queue
            entries.append(cleaned)
        return {
            "format": 1,
            "cover_aliases": list(aliases.values()),
            "entry_count": len(entries),
            "entries": entries,
        }
