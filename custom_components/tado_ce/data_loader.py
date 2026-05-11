"""Tado CE Data Loader — per-home HA Store persistence and in-memory cache.

Manages two categories of persistent data via HA Store:

**API Data** (10 stores, immediate save):
    Written on every API response via ``async_update_store()``.
    Uses ``Store.async_save()`` for immediate persistence.
    Stores: zones, config, home_state, ratelimit,
    zones_info, weather, mobile_devices, offsets, schedules, ac_capabilities.

**Auxiliary Data** (9 stores, debounced save):
    Written via ``save_auxiliary()`` with configurable delay.
    Uses ``Store.async_delay_save()`` for batched writes.
    HA automatically persists pending data on shutdown via
    ``EVENT_HOMEASSISTANT_FINAL_WRITE``.
    Stores: window_detection, wc_state, bridge_health, outdoor_temp_history,
    zone_config, smart_comfort_cache, overlay_mode,
    timer_duration, homekit_savings.

**Standalone Stores** (not managed by DataLoader):
    HeatingCycleStorage, InsightHistoryTracker, StateRestoreManager,
    APICallTracker manage their own Store instances because they have
    complex data-format migration, dirty-flag tracking, or domain-specific
    save/load logic that doesn't fit the DataLoader pattern.

**When to use DataLoader vs standalone Store:**
    - DataLoader: Simple key-value data, no complex transforms on load/save
    - Standalone: Needs data-format migration, dirty tracking, or domain logic

**JSON file exceptions** (not managed by DataLoader):
    - config_flow bootstrap writes (DataLoader not yet created)
    - homekit_pairing / homekit_device_map (independent lifecycle)
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.storage import Store

from .const import (
    DATA_DIR,
    OUTDOOR_TEMP_HISTORY_MAX,
    OVERLAY_MODE_DEFAULT,
    TIMER_DURATION_DEFAULT,
    TIMER_DURATION_MAX,
    TIMER_DURATION_MIN,
)
from .storage import async_migrate_json_to_store

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

_CACHE_MISSING = object()
"""Sentinel for negative cache entries (store empty / file not found)."""

# Store configuration: name -> save_delay_seconds
# delay=0 means immediate save (async_save), used for API data.
# delay>0 means debounced save (async_delay_save), used for auxiliary data.
_ALL_STORES: dict[str, int] = {
    # API Data — immediate save (written on every API response)
    "zones": 0,
    "config": 0,
    "home_state": 0,
    "ratelimit": 0,
    "zones_info": 0,
    "weather": 0,
    "mobile_devices": 0,
    "offsets": 0,
    "schedules": 0,
    "ac_capabilities": 0,
    # Auxiliary Data — debounced save
    "window_detection": 10,
    "wc_state": 10,
    "bridge_health": 10,
    "outdoor_temp_history": 10,
    "zone_config": 5,
    "smart_comfort_cache": 30,
    "overlay_mode": 5,
    "timer_duration": 5,
    "homekit_savings": 10,
    "insight_runtime_state": 30,
}

STORE_VERSION = 1


class DataLoader:
    """Per-entry data loader with home_id-scoped HA Store persistence.

    Each config entry (home) gets its own DataLoader instance.
    All persistence uses HA Store — API data with immediate save,
    auxiliary data with debounced save.

    Usage::

        loader = DataLoader(home_id="12345", hass=hass)
        await loader.async_load_all_to_cache()
        zones = loader.get_cached("zones")
        wc = await loader.async_load_wc_state()
    """

    def __init__(self, home_id: str, hass: HomeAssistant | None = None) -> None:
        """Initialize DataLoader for a specific home.

        Args:
            home_id: Tado home ID for Store key scoping.
            hass: HomeAssistant instance (required for Store operations).
        """
        self._home_id = home_id
        self._hass = hass
        self._cache: dict[str, Any] = {}
        self._stores: dict[str, Store[dict[str, Any] | list[Any]]] = {}
        if hass:
            self._init_stores(hass)

    def _init_stores(self, hass: HomeAssistant) -> None:
        """Create Store instances for all managed data."""
        for name in _ALL_STORES:
            self._stores[name] = Store(
                hass,
                STORE_VERSION,
                f"tado_ce/{name}_{self._home_id}",
            )

    @property
    def home_id(self) -> str:
        """Return the home_id this loader is scoped to."""
        return self._home_id

    # --- Cache API ---

    def update_cache(self, base_name: str, data: dict[str, Any] | list[Any]) -> None:
        """Update in-memory cache entry.

        Called by async_update_store after Store write. Also used by
        legacy callers during transition.

        Args:
            base_name: Store name (e.g. "zones").
            data: Parsed data to cache.
        """
        self._cache[base_name] = data

    def get_cached(self, base_name: str) -> dict[str, Any] | list[Any] | None:
        """Get data from in-memory cache.

        Returns:
            Cached data, or None if not cached or negatively cached.
        """
        result = self._cache.get(base_name)
        if result is _CACHE_MISSING:
            return None
        return result

    # --- API Data Store Operations ---

    async def async_update_store(self, name: str, data: dict[str, Any] | list[Any]) -> None:
        """Save API data to Store immediately and update in-memory cache.

        Used by api_client after each API response. Replaces the old
        JSON file write-through pattern.

        Args:
            name: Store name (e.g. "zones", "ratelimit").
            data: Data to persist.
        """
        store = self._stores.get(name)
        if store is None:
            _LOGGER.warning("Unknown storage key: %s", name)
            return
        await store.async_save(data)
        self._cache[name] = data

    async def async_load_all_to_cache(self) -> None:
        """Load all API data stores into in-memory cache.

        Called once during cold start. For each API data store:
        1. Try ``Store.async_load()``
        2. If None, try v3.5.3 JSON migration via ``async_migrate_json_to_store``
        3. Cache result (including negative sentinel for missing data)

        Handles v3.5.3 / v4.0.0-beta.x → v4.x migration: old JSON files
        in DATA_DIR are migrated to HA Store on first load, then renamed
        to ``.json.migrated``.
        """
        api_store_names = [name for name, delay in _ALL_STORES.items() if delay == 0]
        for name in api_store_names:
            store = self._stores.get(name)
            if store is None:
                self._cache[name] = _CACHE_MISSING
                continue
            try:
                data = await store.async_load()
            except HomeAssistantError:
                _LOGGER.exception("Failed to load store %s", name)
                self._cache[name] = _CACHE_MISSING
                continue

            if data is None and self._hass is not None:
                # v3.5.3 migration: try loading from old JSON file
                old_path = self._old_api_data_path(name)
                _LOGGER.debug("DataLoader: Store %s empty, trying JSON migration from %s", name, old_path)
                data = await async_migrate_json_to_store(
                    self._hass, old_path, store, label=name,
                )
            if data is not None:
                _LOGGER.debug("DataLoader: Loaded %s (type=%s)", name, type(data).__name__)
            self._cache[name] = data if data is not None else _CACHE_MISSING

    def _old_api_data_path(self, name: str) -> Path:
        """Get old JSON file path for API data (v3.5.3 format).

        v3.5.3 used: ``DATA_DIR / "{name}_{home_id}.json"``
        """
        return DATA_DIR / f"{name}_{self._home_id}.json"

    # --- Backward-compatible cache read methods ---
    # These methods previously did blocking file I/O. Now they are thin
    # wrappers over the in-memory cache (populated by async_load_all_to_cache
    # or async_update_store). Signatures preserved for backward compatibility.

    def load_zones_file(self) -> dict[str, Any] | None:
        """Load zone states from cache."""
        return self.get_cached("zones")  # type: ignore[return-value]

    def load_zones_info_file(self) -> list[Any] | None:
        """Load zone metadata from cache."""
        return self.get_cached("zones_info")  # type: ignore[return-value]

    def load_mobile_devices_file(self) -> list[Any] | None:
        """Load mobile devices from cache."""
        return self.get_cached("mobile_devices")  # type: ignore[return-value]

    def load_ratelimit_file(self) -> dict[str, Any] | None:
        """Load rate limit data from cache."""
        return self.get_cached("ratelimit")  # type: ignore[return-value]

    def load_schedules_file(self) -> dict[str, Any] | None:
        """Load zone schedules from cache."""
        return self.get_cached("schedules")  # type: ignore[return-value]

    # === Convenience methods ===

    def get_zone_schedule(self, zone_id: str) -> dict[str, Any] | None:
        """Get schedule data for a specific zone."""
        schedules = self.load_schedules_file()
        if schedules:
            return schedules.get(zone_id)
        return None

    # === Auxiliary Data — Store-backed with debounced writes ===

    def _old_auxiliary_path(self, name: str) -> Path:
        """Get the pre-Store JSON path for an auxiliary file (migration lookup only).

        In the legacy v3.5.3 JSON format, overlay_mode and timer_duration were
        shared across homes (no home_id suffix). All other files were home-scoped.
        Current Store keys are home-scoped uniformly; this path is only used when
        migrating old on-disk JSON into the new Store.
        """
        if name in ("overlay_mode", "timer_duration"):
            return DATA_DIR / f"{name}.json"
        return DATA_DIR / f"{name}_{self._home_id}.json"

    async def async_load_auxiliary(self, name: str) -> dict[str, Any] | list[Any] | None:
        """Load auxiliary data from Store, with JSON migration fallback.

        Args:
            name: Auxiliary store name.

        Returns:
            Loaded data, or None if not found.
        """
        store = self._stores.get(name)
        if not store:
            _LOGGER.warning("Unknown auxiliary storage key: %s", name)
            return None

        data = await store.async_load()
        if data is not None:
            return data

        # Try migrating from old JSON file
        if self._hass is None:
            return None
        old_path = self._old_auxiliary_path(name)
        return await async_migrate_json_to_store(
            self._hass, old_path, store, label=name,
        )

    def save_auxiliary(self, name: str, data: dict[str, Any] | list[Any]) -> None:
        """Schedule debounced save for auxiliary data via Store.

        Args:
            name: Auxiliary store name.
            data: Data to save.
        """
        store = self._stores.get(name)
        if store:
            delay = _ALL_STORES.get(name, 10)
            store.async_delay_save(lambda: data, delay)
        else:
            _LOGGER.warning("Unknown auxiliary storage key for save: %s", name)

    # === Overlay mode (per-home, Store-backed) ===

    async def async_load_overlay_mode(self) -> str:
        """Load overlay mode from Store.

        Returns:
            "TADO_MODE", "NEXT_TIME_BLOCK", "TIMER", or "MANUAL".
            Defaults to "TADO_MODE" if not found.
        """
        try:
            data = await self.async_load_auxiliary("overlay_mode")
            if data is None:
                return OVERLAY_MODE_DEFAULT
            if not isinstance(data, dict):
                _LOGGER.warning("Invalid overlay_mode format, defaulting to TADO_MODE")
                return OVERLAY_MODE_DEFAULT
            mode = data.get("overlay_mode", OVERLAY_MODE_DEFAULT)
            if mode not in ("TADO_MODE", "NEXT_TIME_BLOCK", "TIMER", "MANUAL"):
                _LOGGER.warning("Invalid overlay mode '%s', defaulting to TADO_MODE", mode)
                return OVERLAY_MODE_DEFAULT
            return mode  # type: ignore[no-any-return]
        except (HomeAssistantError, OSError) as e:
            _LOGGER.warning("Failed to load overlay mode: %s", e)
            return OVERLAY_MODE_DEFAULT

    def save_overlay_mode(self, mode: str) -> bool:
        """Save overlay mode via Store.

        Args:
            mode: "TADO_MODE", "NEXT_TIME_BLOCK", "TIMER", or "MANUAL"

        Returns:
            True if valid mode, False otherwise.
        """
        if mode not in ("TADO_MODE", "NEXT_TIME_BLOCK", "TIMER", "MANUAL"):
            _LOGGER.error("Invalid overlay mode: %s", mode)
            return False
        self.save_auxiliary("overlay_mode", {"overlay_mode": mode})
        _LOGGER.debug("Saved overlay mode: %s", mode)
        return True

    # === Timer duration (per-home, Store-backed) ===

    async def async_load_timer_duration(self) -> int:
        """Load timer duration from Store.

        Returns:
            Duration in minutes (default TIMER_DURATION_DEFAULT if not set or error).
        """
        try:
            data = await self.async_load_auxiliary("timer_duration")
            if data is None:
                return TIMER_DURATION_DEFAULT
            if isinstance(data, dict):
                return data.get("timer_duration", TIMER_DURATION_DEFAULT)  # type: ignore[no-any-return]
        except (HomeAssistantError, OSError) as e:
            _LOGGER.debug("Failed to load timer duration: %s", e)
        return TIMER_DURATION_DEFAULT

    def save_timer_duration(self, duration: int) -> bool:
        """Save timer duration via Store.

        Args:
            duration: Duration in minutes (15-180)

        Returns:
            True if valid duration, False otherwise.
        """
        if not isinstance(duration, int) or duration < TIMER_DURATION_MIN or duration > TIMER_DURATION_MAX:
            _LOGGER.error("Invalid timer duration: %s", duration)
            return False
        self.save_auxiliary("timer_duration", {"timer_duration": duration})
        _LOGGER.debug("Saved timer duration: %s minutes", duration)
        return True

    # === Outdoor temperature history (Store-backed) ===

    async def async_load_outdoor_temp_history(self) -> list[Any]:
        """Load outdoor temperature history from Store.

        Returns:
            List of float temperature readings (most recent last), max 336 entries.
        """
        try:
            data = await self.async_load_auxiliary("outdoor_temp_history")
            if data is None:
                _LOGGER.debug("outdoor_temp_history not found - starting fresh")
                return []
            if isinstance(data, dict):
                readings = data.get("readings", [])
                readings = [float(r) for r in readings if isinstance(r, (int, float))]
                return readings[-OUTDOOR_TEMP_HISTORY_MAX:]
            return []
        except (HomeAssistantError, OSError) as e:
            _LOGGER.warning("Failed to load outdoor_temp_history: %s", e)
            return []

    def save_outdoor_temp_history(self, readings: list[Any]) -> bool:
        """Save outdoor temperature history via Store.

        Args:
            readings: List of float temperature readings (most recent last).

        Returns:
            True (always succeeds — Store handles async write).
        """
        trimmed = readings[-OUTDOOR_TEMP_HISTORY_MAX:]
        data = {"readings": trimmed}
        self.save_auxiliary("outdoor_temp_history", data)
        return True

    # === Weather Compensation State (Store-backed) ===

    async def async_load_wc_state(self) -> dict[str, Any] | None:
        """Load weather compensation state from Store.

        Returns:
            Parsed dict, or None if not found.
        """
        try:
            data = await self.async_load_auxiliary("wc_state")
        except (HomeAssistantError, OSError) as e:
            _LOGGER.warning("Failed to load wc_state: %s", e)
            return None
        if data is not None and isinstance(data, dict):
            return data
        return None

    def save_wc_state(self, data: dict[str, Any]) -> bool:
        """Save weather compensation state via Store.

        Args:
            data: Serialized WeatherCompensationState dict.

        Returns:
            True (always succeeds — Store handles async write).
        """
        self.save_auxiliary("wc_state", data)
        return True

    # === Bridge Health State (Store-backed) ===

    async def async_load_bridge_health(self) -> dict[str, Any] | None:
        """Load bridge health state from Store.

        Returns:
            Parsed dict, or None if not found.
        """
        try:
            data = await self.async_load_auxiliary("bridge_health")
        except (HomeAssistantError, OSError) as e:
            _LOGGER.warning("Failed to load bridge_health: %s", e)
            return None
        if data is not None and isinstance(data, dict):
            return data
        return None

    def save_bridge_health(self, data: dict[str, Any]) -> bool:
        """Save bridge health state via Store.

        Args:
            data: Serialized BridgeHealthState dict.

        Returns:
            True (always succeeds — Store handles async write).
        """
        self.save_auxiliary("bridge_health", data)
        return True

    # === HomeKit Savings Counters (Store-backed) ===

    async def async_load_homekit_savings(self) -> dict[str, Any] | None:
        """Load HomeKit API savings counters from Store.

        Returns:
            Dict with reads_saved, writes_saved, last_reset_utc, or None if not found.
        """
        try:
            data = await self.async_load_auxiliary("homekit_savings")
        except (HomeAssistantError, OSError) as e:
            _LOGGER.warning("Failed to load homekit_savings: %s", e)
            return None
        if data is not None and isinstance(data, dict):
            return data
        return None

    def save_homekit_savings(self, data: dict[str, Any]) -> bool:
        """Save HomeKit API savings counters via Store.

        Args:
            data: Dict with reads_saved, writes_saved, last_reset_utc.

        Returns:
            True (always succeeds — Store handles async write).
        """
        self.save_auxiliary("homekit_savings", data)
        return True

    # === Window Detection State (Store-backed) ===

    async def async_load_window_detection(self) -> dict[str, Any] | None:
        """Load window detection state from Store.

        Returns:
            Parsed dict with per-zone detection state, or None if not found.
        """
        try:
            data = await self.async_load_auxiliary("window_detection")
        except (HomeAssistantError, OSError) as e:
            _LOGGER.warning("Failed to load window_detection: %s", e)
            return None
        if data is not None and isinstance(data, dict):
            return data
        return None

    def save_window_detection(self, data: dict[str, Any]) -> bool:
        """Save window detection state via Store.

        Args:
            data: Dict of per-zone detection state.

        Returns:
            True (always succeeds — Store handles async write).
        """
        self.save_auxiliary("window_detection", data)
        return True
