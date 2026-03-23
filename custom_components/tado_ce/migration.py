"""Tado CE migration — config entry version migration and utilities."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from .const import DOMAIN

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

# Module-level set to track duplicate cleanup operations (prevents re-running)
_duplicate_cleanup_done: set[str] = set()


async def async_migrate_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Migrate old entry to current version.

    v4.0.0 dropped all v2.x → v3.x migration code.
    Minimum supported upgrade path is now v3.0.0+ (config entry version 11).
    Users on v2.x must upgrade to v3.x first, then to v4.0.0.
    """
    target_version = 11
    initial_version = config_entry.version

    if initial_version is None:
        _LOGGER.warning(
            "Config entry version is None (possibly from failed migration). "
            "Setting to target version %s.",
            target_version,
        )
        hass.config_entries.async_update_entry(config_entry, version=target_version)
        return True

    if initial_version < target_version:
        _LOGGER.error(
            "Config entry version %s is too old. "
            "Minimum supported version is 11 (v3.0.0). "
            "Please upgrade to v3.x first, then to v4.0.0.",
            initial_version,
        )
        return False

    _LOGGER.debug(
        "Config entry already at version %s, no migration needed",
        initial_version,
    )
    return True


async def async_handle_test_mode_transition(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> None:
    """Check if Test Mode was just disabled and refresh rate limit data.

    When Test Mode is disabled, triggers an API call to refresh rate limit
    data with real values instead of relying on backup.
    """
    import json

    from .const import get_data_file

    home_id = entry.data.get("home_id")
    ratelimit_path = get_data_file("ratelimit", home_id)

    prev_test_mode = False
    path_exists = await hass.async_add_executor_job(ratelimit_path.exists)
    if path_exists:
        content = await hass.async_add_executor_job(ratelimit_path.read_text)
        ratelimit_data = json.loads(content)
        prev_test_mode = ratelimit_data.get("test_mode", False)

    new_test_mode = entry.options.get("test_mode_enabled", False)
    _LOGGER.debug("Test Mode transition check: prev=%s, new=%s", prev_test_mode, new_test_mode)

    if prev_test_mode and not new_test_mode:
        _LOGGER.info("Tado CE: Test Mode disabled - triggering API refresh for real rate limit data")

        entry_data = getattr(entry, "runtime_data", None)
        client = entry_data.api_client if entry_data else None

        if client is None:
            _LOGGER.warning("No API client available for entry %s", entry.entry_id)
        else:
            try:
                await client.get_me()
                _LOGGER.info("Tado CE: API refresh completed - rate limit data updated with real values")
            except Exception as e:
                _LOGGER.warning("Tado CE: API refresh failed (will use backup): %s", e)


async def async_deduplicate_entries(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> bool:
    """Check for and remove duplicate config entries.

    Groups by unique_id — multi-home entries with different unique_ids
    are NOT duplicates.

    Returns True if this entry should continue setup, False if it's a duplicate
    that should abort.
    """
    from collections import defaultdict

    all_entries = hass.config_entries.async_entries(DOMAIN)

    # Group entries by unique_id
    entries_by_uid: dict[str | None, list[Any]] = defaultdict(list)
    for e in all_entries:
        entries_by_uid[e.unique_id].append(e)

    # Find the group that THIS entry belongs to
    my_group = entries_by_uid.get(entry.unique_id, [entry])

    if len(my_group) > 1:
        _LOGGER.warning(
            "Found %d entries with same unique_id '%s' - checking for duplicates",
            len(my_group),
            entry.unique_id,
        )
        _LOGGER.info("  Entries in group: %s", [(e.entry_id, e.version) for e in my_group])

        # Sort by version (descending), then by entry_id for deterministic ordering
        entries_by_version = sorted(
            my_group,
            key=lambda e: (getattr(e, "version", 0), e.entry_id),
            reverse=True,
        )

        keeper_entry_id = entries_by_version[0].entry_id
        _LOGGER.info("  Keeper entry: %s", keeper_entry_id)

        # If current entry is NOT the one to keep, abort this setup
        if entry.entry_id != keeper_entry_id:
            _LOGGER.warning(
                "Current entry %s (version %s) is duplicate of unique_id '%s'. "
                "Aborting setup - will be removed by keeper entry.",
                entry.entry_id,
                entry.version,
                entry.unique_id,
            )
            return False

        # Current entry IS the keeper - remove all others in this group
        cleanup_key = f"duplicate_cleanup_{keeper_entry_id}"
        if cleanup_key not in _duplicate_cleanup_done:
            _duplicate_cleanup_done.add(cleanup_key)

            _LOGGER.info(
                "Entry %s is keeper for unique_id '%s' - removing %d duplicates",
                keeper_entry_id,
                entry.unique_id,
                len(entries_by_version) - 1,
            )

            for old_entry in entries_by_version[1:]:
                _LOGGER.warning(
                    "Removing duplicate entry %s (version %s, unique_id '%s')",
                    old_entry.entry_id,
                    getattr(old_entry, "version", "unknown"),
                    old_entry.unique_id,
                )
                try:
                    await hass.config_entries.async_remove(old_entry.entry_id)
                    _LOGGER.info("Successfully removed duplicate entry %s", old_entry.entry_id)
                except Exception:
                    _LOGGER.exception("Failed to remove duplicate entry %s", old_entry.entry_id)

            _LOGGER.info(
                "Duplicate cleanup complete for unique_id '%s'. Keeper: %s",
                entry.unique_id,
                keeper_entry_id,
            )
    elif len(all_entries) > 1:
        _LOGGER.info(
            "Found %d Tado CE entries with %d distinct unique_ids — multi-home setup, no duplicates",
            len(all_entries),
            len(entries_by_uid),
        )

    return True
