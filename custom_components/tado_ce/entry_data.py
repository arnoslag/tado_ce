"""Per-entry state container for Tado CE multi-home support.

v3.0.0 Phase 1: Each config entry (home) gets its own EntryData instance,
eliminating all shared global state. This is the foundation for multi-home
support — all per-entry fields that were previously stored in
hass.data[DOMAIN] (flat dict) are now isolated per config entry.

Usage:
    # In async_setup_entry:
    entry_data = EntryData(home_id=home_id, ...)
    entry.runtime_data = entry_data  # HA official pattern

    # In entities:
    entry_data = self.hass.data[DOMAIN][self._entry_id]

Type alias:
    TadoConfigEntry = ConfigEntry[EntryData]  # HA official pattern for type safety
"""
from __future__ import annotations

import asyncio
import logging
import sys
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable, Optional

_LOGGER = logging.getLogger(__name__)

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry

    from .api_client import TadoApiClient
    from .api_call_tracker import APICallTracker
    from .config_manager import ConfigurationManager
    from .data_loader import DataLoader
    from .heating_coordinator import HeatingCycleCoordinator
    from .refresh_handler import RefreshHandler
    from .smart_comfort import SmartComfortManager
    from .zone_config_manager import ZoneConfigManager
    from .adaptive_preheat import AdaptivePreheatManager

    # HA official pattern — provides type safety for entry.runtime_data
    type TadoConfigEntry = ConfigEntry[EntryData]


@dataclass
class EntryData:
    """Per-entry state container for a single Tado home.

    All fields that were previously stored in hass.data[DOMAIN] as a flat dict
    are now isolated per config entry. This ensures that two homes running
    simultaneously cannot interfere with each other's state.

    Mutable fields use default_factory to ensure each instance gets its own
    independent copy (critical for isolation — GAP-27).
    """

    # === Identity ===
    home_id: str
    """Tado home ID (from config_entry.data["home_id"])."""

    # === Credentials ===
    refresh_token: str = ""
    """OAuth refresh token, passed to TadoApiClient at construction time (GAP-25).
    Stored here so token rotation writes to per-home config file."""

    # === Core managers (set during async_setup_entry) ===
    config_manager: Optional[ConfigurationManager] = None
    """Per-entry configuration manager (options flow settings)."""

    zone_config_manager: Optional[ZoneConfigManager] = None
    """Per-entry zone configuration manager (per-zone overrides)."""

    data_loader: Optional[DataLoader] = None
    """Per-entry data loader with home_id-scoped file paths (GAP-77)."""

    api_client: Optional[TadoApiClient] = None
    """Per-entry async API client (GAP-26: no more shared singleton)."""

    api_tracker: Optional[APICallTracker] = None
    """Per-entry API call tracker (GAP-28, GAP-67: per-entry executor)."""

    refresh_handler: Optional[RefreshHandler] = None
    """Per-entry refresh handler for immediate refresh after state changes."""

    smart_comfort_manager: Optional[SmartComfortManager] = None
    """Per-entry Smart Comfort analytics manager."""

    heating_cycle_coordinator: Optional[HeatingCycleCoordinator] = None
    """Per-entry heating cycle detection coordinator."""

    adaptive_preheat_manager: Optional[AdaptivePreheatManager] = None
    """Per-entry adaptive preheat manager."""

    # === Timers / Cancellation callbacks ===
    polling_cancel: Optional[Callable[[], None]] = None
    """Cancel callback for the periodic polling timer (GAP-79, CP-1).
    Cancelling one entry's timer must NOT affect another entry's timer."""

    freshness_cleanup_cancel: Optional[Callable[[], None]] = None
    """Cancel callback for the periodic entity freshness cleanup timer."""

    heating_cycle_timeout_cancel: Optional[Callable[[], None]] = None
    """Cancel callback for the heating cycle timeout check timer."""

    # === Per-entry overlay settings (from options flow) ===
    overlay_mode: str = "TADO_MODE"
    """Global overlay mode for this home (MANUAL, TADO_MODE, TIMER)."""

    timer_duration: int = 60
    """Global timer duration in minutes for TIMER overlay mode."""

    # === Closure-based state migrated from __init__.py (GAP-27) ===
    entity_freshness: dict[str, float] = field(default_factory=dict)
    """entity_id -> timestamp mapping for freshness tracking.
    Each entry has its own dict — mutating one entry's freshness
    must not affect another entry's entities."""

    freshness_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    """Async lock protecting concurrent access to entity_freshness."""

    sequence_counter: dict[str, int] = field(default_factory=dict)
    """Per-entity sequence counters for optimistic update ordering."""

    global_sequence: list[int] = field(default_factory=lambda: [0])
    """Monotonically increasing sequence number for this entry.
    Uses list[int] for mutability in closures (same pattern as current code)."""


    # === Methods migrated from __init__.py closures (Task 6.5) ===

    def get_next_sequence(self) -> int:
        """Get next sequence number for tracking data freshness.

        Includes overflow protection — resets at sys.maxsize to prevent
        memory issues in long-running instances.
        """
        self.global_sequence[0] += 1
        if self.global_sequence[0] >= sys.maxsize:
            _LOGGER.info("Sequence number reached max, resetting to 0")
            self.global_sequence[0] = 0
        return self.global_sequence[0]

    async def async_mark_entity_fresh(self, entity_id: str) -> None:
        """Mark entity as having a recent API call in progress."""
        async with self.freshness_lock:
            self.entity_freshness[entity_id] = time.time()
            _LOGGER.debug("Marked entity fresh: %s", entity_id)

    def is_entity_fresh(self, entity_id: str, debounce_seconds: int | None = None) -> bool:
        """Check if entity has a recent API call (within debounce window).

        Args:
            entity_id: Entity ID to check
            debounce_seconds: Override debounce window (uses config if None)
        """
        if entity_id not in self.entity_freshness:
            return False
        if debounce_seconds is None:
            if self.config_manager:
                debounce_seconds = self.config_manager.get_refresh_debounce_seconds() + 2
            else:
                debounce_seconds = 7  # safe default
        elapsed = time.time() - self.entity_freshness[entity_id]
        if elapsed > debounce_seconds:
            del self.entity_freshness[entity_id]
            return False
        return True




def get_entry_data(hass: Any, entry_id: str) -> EntryData:
    """Get EntryData for a config entry.

    Primary access pattern for entities to retrieve their entry's state.
    Entities store entry_id in __init__ and call this in properties/methods.

    Args:
        hass: Home Assistant instance
        entry_id: The config entry ID (from self._entry_id)

    Returns:
        EntryData instance for the given entry

    Raises:
        KeyError: If entry_id not found (entry was unloaded)
    """
    from .const import DOMAIN
    return hass.data[DOMAIN][entry_id]


def get_entry_data_or_none(hass: Any, entry_id: str) -> EntryData | None:
    """Get EntryData for a config entry, returning None if unavailable.

    Safe version of get_entry_data() for use in entity callbacks and
    properties that may fire during or after entry unload. Avoids KeyError
    when the entry has already been removed from hass.data.

    Use this instead of get_entry_data() when:
    - In @callback update() methods (coordinator may fire during unload)
    - In property accessors that HA may call at any time
    - In signal/event handlers that may outlive the entry

    Use get_entry_data() (the strict version) when:
    - In async_setup_entry() where the entry is guaranteed to exist
    - In service handlers where you want a clear error on bad entry_id

    Args:
        hass: Home Assistant instance
        entry_id: The config entry ID (from self._entry_id)

    Returns:
        EntryData instance, or None if entry was unloaded
    """
    from .const import DOMAIN
    try:
        return hass.data[DOMAIN][entry_id]
    except KeyError:
        _LOGGER.debug("EntryData not found for %s (entry may be unloaded)", entry_id)
        return None
