"""Entry lifecycle helpers for Tado CE.

Contains per-entry infrastructure creation and cleanup:
- async_create_entry_components: API tracker, client, timers, refresh handler
- async_cleanup_entry_components: timer cancellation, manager cleanup
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import TYPE_CHECKING

from homeassistant.helpers.event import async_track_time_interval

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

    from .configuration_manager import ConfigurationManager
    from .entry_data import EntryData

_LOGGER = logging.getLogger(__name__)


async def async_create_entry_components(
    hass: HomeAssistant,
    entry: ConfigEntry,
    entry_data: EntryData,
    config_manager: ConfigurationManager,
    home_id: str | None,
) -> None:
    """Create per-entry infrastructure components.

    Creates: API tracker, API client, freshness cleanup timer,
    refresh handler, and runs device cleanup.
    """
    import time

    from homeassistant.helpers.aiohttp_client import async_get_clientsession

    from .api_call_tracker import APICallTracker
    from .api_client import TadoApiClient
    from .const import DATA_DIR
    from .migration import cleanup_duplicate_devices

    # Create per-entry API call tracker
    retention_days = config_manager.get_api_history_retention_days()
    api_tracker = APICallTracker(DATA_DIR, retention_days=retention_days, home_id=home_id)
    await api_tracker.async_init()
    entry_data.api_tracker = api_tracker
    _LOGGER.debug("Tado CE: Per-entry API call tracker created")

    # Create per-entry API client
    session = async_get_clientsession(hass)
    api_client = TadoApiClient(
        session, hass,
        home_id=home_id,
        refresh_token=entry.data.get("refresh_token", ""),
        config_manager=config_manager,
        api_tracker=api_tracker,
    )
    entry_data.api_client = api_client
    _LOGGER.debug("Tado CE: Per-entry API client created")

    # Periodic freshness cleanup (entities use EntryData methods directly)
    async def cleanup_entity_freshness() -> None:
        """Periodic cleanup of expired entity freshness entries.

        Prevents memory leak from entities that are always fresh or removed.
        Called every 5 minutes by async_track_time_interval.
        """
        async with entry_data.freshness_lock:
            now = time.time()
            expired = [
                eid for eid, timestamp in entry_data.entity_freshness.items()
                if now - timestamp > 60  # Remove entries older than 1 minute
            ]
            for eid in expired:
                del entry_data.entity_freshness[eid]
            if expired:
                _LOGGER.debug("Cleaned up %d expired entity freshness entries", len(expired))

    def _schedule_cleanup(now):
        """Schedule async cleanup from time interval callback."""
        hass.async_create_task(cleanup_entity_freshness())

    cleanup_cancel = async_track_time_interval(
        hass,
        _schedule_cleanup,
        timedelta(minutes=5),
    )
    entry_data.freshness_cleanup_cancel = cleanup_cancel

    # Sync configuration to config.json for tado_api.py
    await config_manager.async_sync_all_to_config_json()

    # Load version early to avoid race conditions in device_manager
    from .device_manager import load_version
    await hass.async_add_executor_job(load_version)

    # Cleanup duplicate hub/zone devices (migration safety net)
    if home_id:
        cleanup_duplicate_devices(hass, home_id)


async def async_cleanup_entry_components(
    hass: HomeAssistant,
    entry_data: EntryData | None,
) -> None:
    """Clean up per-entry infrastructure components.

    Cancels timers and cleans up managers for a single config entry.
    """
    if entry_data is None:
        return

    def _ed(field: str):
        """Get field from entry_data, or None if missing."""
        return getattr(entry_data, field, None)

    # --- Cancel per-entry timers ---

    cancel_func = _ed('polling_cancel')
    if cancel_func:
        cancel_func()
        _LOGGER.debug("Cancelled polling timer")

    cancel_func = _ed('freshness_cleanup_cancel')
    if cancel_func:
        cancel_func()
        _LOGGER.debug("Cancelled freshness cleanup timer")

    cancel_func = _ed('heating_cycle_timeout_cancel')
    if cancel_func:
        cancel_func()
        _LOGGER.debug("Cancelled heating cycle timeout timer")

    # --- Clean up per-entry managers ---

    ac = _ed('api_client')
    if ac is not None:
        ac._access_token = None
        ac._token_expiry = None
        entry_data.api_client = None
        _LOGGER.debug("Cleaned up per-entry TadoApiClient")

    # Save data before cleanup
    scm = _ed('smart_comfort_manager')
    if scm is not None:
        await hass.async_add_executor_job(scm.save_to_file)
        entry_data.smart_comfort_manager = None
        _LOGGER.debug("Cleaned up per-entry SmartComfortManager")

    apm = _ed('adaptive_preheat_manager')
    if apm is not None:
        await apm.async_unload()
        entry_data.adaptive_preheat_manager = None
        _LOGGER.debug("Cleaned up per-entry AdaptivePreheatManager")

    if _ed('data_loader') is not None:
        entry_data.data_loader = None
        _LOGGER.debug("Cleaned up per-entry DataLoader")
