"""Fail-closed loading helpers for safety-relevant Home Assistant stores."""

from __future__ import annotations

import glob
import os
from typing import Any


class PersistentStoreUnreadableError(RuntimeError):
    """Raised when a previously existing persistent store cannot be read."""


async def async_load_persistent_store(hass: Any, store: Any) -> Any:
    """Load a Store without confusing corruption with a first-time setup.

    Home Assistant moves malformed JSON aside to ``.corrupt.*`` and returns
    ``None``. Remembering pre-load existence catches that first load; checking
    for the backup afterwards keeps later Config Entry retries fail-closed too.
    A newly written valid store remains authoritative even if an older corrupt
    backup is still present.
    """
    store_path = os.fspath(store.path)
    existed_before = await hass.async_add_executor_job(
        os.path.isfile, store_path
    )
    stored = await store.async_load()
    if stored is not None:
        return stored
    corrupt_backups = await hass.async_add_executor_job(
        glob.glob, f"{glob.escape(store_path)}.corrupt.*"
    )
    if existed_before or corrupt_backups:
        raise PersistentStoreUnreadableError(
            f"Persistent store {store_path!r} exists but could not be read"
        )
    return None
