"""Home Assistant Repairs helpers for Smart Shading Control."""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir

from .const import DOMAIN


def _issue_id(entry_id: str, kind: str, entity_id: str | None = None) -> str:
    safe_entity = (entity_id or "global").replace(".", "_").replace("-", "_")
    return f"{kind}_{entry_id}_{safe_entity}"


def create_issue(
    hass: HomeAssistant,
    entry_id: str,
    kind: str,
    *,
    severity: ir.IssueSeverity = ir.IssueSeverity.ERROR,
    entity_id: str | None = None,
    placeholders: dict[str, str] | None = None,
    persistent: bool = False,
) -> None:
    """Create or update one localized Repairs issue."""
    ir.async_create_issue(
        hass,
        DOMAIN,
        _issue_id(entry_id, kind, entity_id),
        is_fixable=False,
        is_persistent=persistent,
        severity=severity,
        translation_key=kind,
        translation_placeholders=placeholders or {},
        data={"entry_id": entry_id, "entity_id": entity_id},
    )


def delete_issue(
    hass: HomeAssistant,
    entry_id: str,
    kind: str,
    entity_id: str | None = None,
) -> None:
    """Delete one Repairs issue after the condition recovered."""
    ir.async_delete_issue(hass, DOMAIN, _issue_id(entry_id, kind, entity_id))


def delete_entry_issues(hass: HomeAssistant, entry_id: str) -> None:
    """Delete every Repairs issue owned by one removed config entry."""
    registry = ir.async_get(hass)
    for domain, issue_id in list(registry.issues):
        if domain == DOMAIN and f"_{entry_id}_" in issue_id:
            ir.async_delete_issue(hass, DOMAIN, issue_id)


def delete_stale_entity_issues(
    hass: HomeAssistant, entry_id: str, valid_entity_ids: set[str]
) -> None:
    """Delete issues that still reference entities removed from configuration."""
    registry = ir.async_get(hass)
    for (domain, issue_id), issue in list(registry.issues.items()):
        if domain != DOMAIN or not isinstance(issue.data, dict):
            continue
        if issue.data.get("entry_id") != entry_id:
            continue
        entity_id = issue.data.get("entity_id")
        if entity_id and str(entity_id) not in valid_entity_ids:
            ir.async_delete_issue(hass, DOMAIN, issue_id)
