"""Tado CE storage — JSON file I/O primitives and Store migration helper.

Provides:
- ``load_json_sync`` / ``save_json_sync`` — blocking JSON file I/O
  (used by config_flow bootstrap, homekit_client, homekit_mapping,
  button schedule refresh, calendar schedule refresh)
- ``async_load_json`` / ``async_save_json`` — async wrappers via executor
  (used by api_auth, api_client ratelimit, ratelimit module, migration)
- ``async_migrate_json_to_store`` — shared JSON → HA Store migration helper
  (used by DataLoader, HeatingCycleStorage, InsightHistoryTracker,
  StateRestoreManager)
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from homeassistant.helpers.json import save_json as ha_save_json
from homeassistant.helpers.storage import Store
from homeassistant.util.json import load_json as ha_load_json

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

_MISSING = object()
"""Sentinel for distinguishing 'file not found' from 'file returned None'."""


def save_json_sync(file_path: Path, data: dict[str, Any] | list[Any]) -> None:
    """Save data to JSON file atomically (sync — call from executor or sync context).

    Delegates to :func:`homeassistant.helpers.json.save_json` which uses
    ``write_utf8_file`` (tempfile + ``os.replace``).

    Args:
        file_path: Target file path.
        data: JSON-serializable dict or list.

    Raises:
        HomeAssistantError: If serialisation or file I/O fails.

    """
    file_path.parent.mkdir(parents=True, exist_ok=True)
    ha_save_json(str(file_path), data)


def load_json_sync(file_path: Path) -> dict[str, Any] | list[Any] | None:
    """Load and deserialise a JSON file (sync — call from executor or sync context).

    Delegates to :func:`homeassistant.util.json.load_json`.

    Args:
        file_path: Path to JSON file.

    Returns:
        Parsed data, or ``None`` if file does not exist.

    Raises:
        HomeAssistantError: If file contains invalid JSON or I/O fails.

    """
    result = ha_load_json(str(file_path), default=_MISSING)  # type: ignore[arg-type]
    if result is _MISSING:
        return None
    return result  # type: ignore[return-value]


async def async_save_json(
    hass: HomeAssistant,
    file_path: Path,
    data: dict[str, Any] | list[Any],
) -> None:
    """Save data to JSON file atomically via executor.

    Args:
        hass: Home Assistant instance.
        file_path: Target file path.
        data: JSON-serializable dict or list.

    Raises:
        HomeAssistantError: If serialisation or file I/O fails.

    """
    await hass.async_add_executor_job(save_json_sync, file_path, data)


async def async_load_json(
    hass: HomeAssistant,
    file_path: Path,
) -> dict[str, Any] | list[Any] | None:
    """Load and deserialise a JSON file via executor.

    Args:
        hass: Home Assistant instance.
        file_path: Path to JSON file.

    Returns:
        Parsed data, or ``None`` if file does not exist.

    Raises:
        HomeAssistantError: If file contains invalid JSON or I/O fails.

    """
    return await hass.async_add_executor_job(load_json_sync, file_path)


async def async_migrate_json_to_store(
    hass: HomeAssistant,
    old_path: Path,
    store: Store[Any],
    *,
    label: str = "",
) -> dict[str, Any] | list[Any] | None:
    """Migrate old JSON file to HA Store.

    Common pattern used across the codebase: load from old JSON file,
    save to HA Store, rename old file to ``.json.migrated``.

    Handles v3.5.3 → v4.x migration for API data files and serves as
    the shared migration helper for standalone stores (HeatingCycleStorage,
    InsightHistoryTracker, StateRestoreManager) and DataLoader auxiliary files.

    Args:
        hass: Home Assistant instance.
        old_path: Path to the old JSON file.
        store: Target HA Store instance.
        label: Human-readable label for log messages (defaults to filename stem).

    Returns:
        Migrated data, or ``None`` if old file does not exist or is unreadable.

    """
    exists = await hass.async_add_executor_job(old_path.exists)
    if not exists:
        return None

    old_data = await hass.async_add_executor_job(load_json_sync, old_path)
    if old_data is None:
        return None

    await store.async_save(old_data)

    migrated_path = old_path.with_suffix(".json.migrated")
    await hass.async_add_executor_job(old_path.rename, migrated_path)
    _LOGGER.info(
        "Migrated %s → Store (old file: %s)",
        label or old_path.stem,
        migrated_path,
    )
    return old_data
