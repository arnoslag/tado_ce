"""Tado CE DataUpdateCoordinator — adaptive polling and entity update propagation.

Adaptive polling and entity update propagation via HA's DataUpdateCoordinator.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
import json
import logging
import sys
import time
from typing import TYPE_CHECKING, Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    UpdateFailed,
)

from .const import DOMAIN, OVERLAY_MODE_DEFAULT, TIMER_DURATION_DEFAULT, get_data_file
from .exceptions import TadoAuthError, TadoBridgeApiError, TadoSyncError
from .insight_history import InsightHistoryTracker
from .polling import get_polling_interval, should_pause_polling

if TYPE_CHECKING:
    from collections.abc import Callable

    from homeassistant.const import Platform
    from homeassistant.core import HomeAssistant

    from .adaptive_preheat import AdaptivePreheatManager
    from .api_call_tracker import APICallTracker
    from .api_client import TadoApiClient
    from .bridge_api import TadoBridgeApiClient
    from .config_manager import ConfigurationManager
    from .data_loader import DataLoader
    from .heating_coordinator import HeatingCycleCoordinator
    from .smart_comfort import SmartComfortManager
    from .zone_config_manager import ZoneConfigManager

_LOGGER = logging.getLogger(__name__)

# Outdoor temperature history — 14 days × 24 hourly readings
_OUTDOOR_TEMP_HISTORY_MAX = 336


# HA official pattern — provides type safety for entry.runtime_data
type TadoConfigEntry = ConfigEntry[TadoDataUpdateCoordinator]


class TadoDataUpdateCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Tado CE data update coordinator with adaptive polling.

    Entities access per-entry state via self.coordinator attributes.
    """

    config_entry: TadoConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        *,
        config_manager: ConfigurationManager,
        zone_config_manager: ZoneConfigManager,
        data_loader: DataLoader,
        api_client: TadoApiClient,
        api_tracker: APICallTracker,
        smart_comfort_manager: SmartComfortManager | None = None,
        heating_cycle_coordinator: HeatingCycleCoordinator | None = None,
        adaptive_preheat_manager: AdaptivePreheatManager | None = None,
    ) -> None:
        """Initialize the coordinator with all per-entry dependencies."""
        initial_interval = get_polling_interval(config_manager)
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} ({config_manager.get_all_config().get('home_id', 'default')})",
            update_interval=timedelta(minutes=initial_interval),
        )

        # Per-entry dependencies (accessible by entities via self.coordinator)
        self.config_manager = config_manager
        self.zone_config_manager = zone_config_manager
        self.data_loader = data_loader
        self.api_client = api_client
        self.api_tracker = api_tracker
        self.smart_comfort_manager = smart_comfort_manager
        self.heating_cycle_coordinator = heating_cycle_coordinator
        self.adaptive_preheat_manager = adaptive_preheat_manager

        # RefreshHandler (self-reference resolves chicken-and-egg dependency)
        from .refresh_handler import RefreshHandler

        self.refresh_handler = RefreshHandler(self)

        self.home_id: str = entry.data.get("home_id") or "default"

        # Freshness tracking
        self.entity_freshness: dict[str, float] = {}
        self._freshness_lock = asyncio.Lock()
        self._freshness_cleanup_cancel: Callable[[], None] | None = None
        self._global_sequence: int = 0

        # Heating cycle timeout cancel handle
        self._heating_cycle_timeout_cancel: Callable[[], None] | None = None

        # Overlay/timer cache
        self.overlay_mode: str = OVERLAY_MODE_DEFAULT
        self.timer_duration: int = TIMER_DURATION_DEFAULT

        # Outdoor temp history (owned by coordinator, async I/O only)
        self._outdoor_temp_history: list[float] = []
        self._outdoor_temp_loaded: bool = False

        # Shared entity data store — entities publish computed values here
        # so other components (insight collector, adaptive preheat) can read
        # without cross-entity hass.states.get() coupling.
        # Structure: {zone_id: {"condensation_risk": {...}, "window_predicted": {...}, ...}}
        self.entity_data: dict[str, dict[str, dict[str, Any]]] = {}

        # Pending cleanup flags — set by options flow, consumed by migration
        # after reload. Avoids transient hass.data[DOMAIN_*] keys.
        self._pending_cleanup: dict[str, dict[str, bool]] = {}

        # Insight history tracker (persistent insight duration tracking)
        self.insight_history = InsightHistoryTracker(hass, self.home_id)

        # Full sync tracking
        self._last_full_sync: datetime | None = None
        self._cached_ratelimit: dict[str, Any] | None = None

        # Bridge API client (lazy-init from options when bridge credentials present)
        self.bridge_api_client: TadoBridgeApiClient | None = None

        # Platforms loaded during setup (used by unload to match exactly)
        self.loaded_platforms: frozenset[Platform] = frozenset()

    @property
    def outdoor_temp_history(self) -> list[float]:
        """Return outdoor temp history (read-only access for sensors)."""
        return self._outdoor_temp_history

    def publish_entity_data(self, zone_id: str, key: str, data: dict[str, Any]) -> None:
        """Publish computed entity data for cross-component access.

        Entities call this to share their computed values (e.g. condensation
        risk, window predicted state) so insight collectors and other
        components can read without hass.states.get() coupling.

        Args:
            zone_id: Zone ID string.
            key: Data key (e.g. "condensation_risk", "window_predicted").
            data: Dict of computed values (e.g. {"state": "High", "recommendation": "..."}).
        """
        if zone_id not in self.entity_data:
            self.entity_data[zone_id] = {}
        self.entity_data[zone_id][key] = data

    def get_entity_data(self, zone_id: str, key: str) -> dict[str, Any] | None:
        """Read published entity data for a zone.

        Args:
            zone_id: Zone ID string.
            key: Data key (e.g. "condensation_risk", "window_predicted").

        Returns:
            Dict of computed values, or None if not published yet.
        """
        return self.entity_data.get(zone_id, {}).get(key)

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch data from Tado API. Dynamically adjusts update_interval."""
        # Track previous success state for recovery logging
        was_failing = self.last_update_success is False

        # 1. Load ratelimit and check quota
        await self._async_load_ratelimit()
        if self._cached_ratelimit:
            should_pause, reason = should_pause_polling(
                self._cached_ratelimit,
                self.config_manager,
            )
            if should_pause:
                _LOGGER.warning("Tado CE: %s", reason)
                self.update_interval = timedelta(minutes=15)
                raise UpdateFailed(reason)

        # 2. Set adaptive interval for NEXT poll
        new_interval = get_polling_interval(self.config_manager, self._cached_ratelimit)
        self.update_interval = timedelta(minutes=new_interval)

        # 3. Execute API sync (full vs quick)
        do_full_sync = self._should_do_full_sync()
        cm = self.config_manager

        try:
            await self.api_client.async_sync(
                quick=not do_full_sync,
                weather_enabled=cm.get_weather_enabled(),
                mobile_devices_enabled=cm.get_mobile_devices_enabled(),
                mobile_devices_frequent_sync=cm.get_mobile_devices_frequent_sync(),
                offset_enabled=cm.get_offset_enabled(),
                home_state_sync_enabled=cm.get_home_state_sync_enabled(),
            )
        except TadoAuthError as e:
            from .repairs import async_create_auth_issue

            async_create_auth_issue(self.hass, self.home_id)
            raise ConfigEntryAuthFailed(
                "Refresh token expired — user must re-authenticate",
            ) from e
        except TadoSyncError as e:
            raise UpdateFailed(f"Tado CE sync failed: {e}") from e

        if do_full_sync:
            self._last_full_sync = datetime.now(UTC)

        # Log recovery after previous failure
        if was_failing:
            _LOGGER.info("Tado CE: Connection restored — sync successful after previous failure")

        # 4. Detect API reset time from history
        from .ratelimit import (
            async_detect_reset_from_history,
            async_update_ratelimit_reset_time,
        )

        detected_reset = await async_detect_reset_from_history(self.hass, self.home_id)
        if detected_reset:
            _LOGGER.debug(
                "Tado CE: HA history detected reset at %s UTC",
                detected_reset.strftime("%H:%M"),
            )
            await async_update_ratelimit_reset_time(
                self.hass, detected_reset, self.home_id, self.data_loader,
            )

        # 5. Read all data from in-memory cache (populated by api_client write-through)
        zone_data = self.data_loader.get_cached("zones")
        config_data = self.data_loader.get_cached("config")
        home_state_data = self.data_loader.get_cached("home_state")
        ratelimit_data = self.data_loader.get_cached("ratelimit")
        api_call_history_data = self.data_loader.get_cached("api_call_history")
        zones_info_data = self.data_loader.get_cached("zones_info")
        weather_data = self.data_loader.get_cached("weather")
        mobile_devices_data = self.data_loader.get_cached("mobile_devices")
        offsets_data = self.data_loader.get_cached("offsets")
        schedules_data = self.data_loader.get_cached("schedules")
        ac_capabilities = self.data_loader.get_cached("ac_capabilities")
        home_details_data = self.data_loader.get_cached("home_details")

        # 5e. Accumulate outdoor temp history (depends on weather_data above)
        if weather_data:
            outdoor_temp = (weather_data.get("outsideTemperature") or {}).get("celsius")  # type: ignore[union-attr]
            if outdoor_temp is not None:
                if not self._outdoor_temp_loaded:
                    loaded = await self.hass.async_add_executor_job(
                        self.data_loader.load_outdoor_temp_history,
                    )
                    self._outdoor_temp_history = loaded
                    self._outdoor_temp_loaded = True

                self._outdoor_temp_history.append(outdoor_temp)
                if len(self._outdoor_temp_history) > _OUTDOOR_TEMP_HISTORY_MAX:
                    del self._outdoor_temp_history[: len(self._outdoor_temp_history) - _OUTDOOR_TEMP_HISTORY_MAX]

                await self.hass.async_add_executor_job(
                    self.data_loader.save_outdoor_temp_history,
                    self._outdoor_temp_history,
                )

        # 6. Notify HeatingCycleCoordinator of zone updates
        if self.heating_cycle_coordinator and zone_data:
            # Tado API may return null for 'zoneStates'; 'or {}' handles None correctly
            zone_states = zone_data.get("zoneStates") or {}  # type: ignore[union-attr]
            for zone_id, data in zone_states.items():
                try:
                    setting = data.get("setting") or {}
                    target_temp = (setting.get("temperature") or {}).get("celsius")
                    sensor_data = data.get("sensorDataPoints") or {}
                    current_temp = (sensor_data.get("insideTemperature") or {}).get("celsius")
                    if target_temp is not None and current_temp is not None:
                        await self.heating_cycle_coordinator.on_zone_update(
                            zone_id,
                            target_temp,
                            current_temp,
                        )
                except Exception:
                    _LOGGER.debug("HeatingCycleCoordinator update failed for zone %s", zone_id)

        # 8. Cleanup expired entity freshness entries (replaces 5-min timer)
        await self._cleanup_entity_freshness()

        # 9. Save insight history if dirty (piggyback on poll cycle)
        if self.insight_history._dirty:
            await self.insight_history.async_save()

        # 10. Bridge API data (optional — only if bridge credentials configured)
        bridge_data = await self._async_fetch_bridge_data()

        result: dict[str, Any] = {
            "zones": zone_data or {},
            "config": config_data or {},
            "home_state": home_state_data or {},
            "ac_capabilities": ac_capabilities or {},
            "ratelimit": ratelimit_data or {},
            "api_call_history": api_call_history_data or {},
            "zones_info": zones_info_data or [],
            "weather": weather_data or {},
            "mobile_devices": mobile_devices_data or [],
            "offsets": offsets_data or {},
            "schedules": schedules_data or {},
            "home_details": home_details_data or {},
        }
        if bridge_data is not None:
            result["bridge"] = bridge_data
        return result

    def _should_do_full_sync(self) -> bool:
        """Check if full sync needed (vs quick). Only on first poll after restart/reload."""
        return self._last_full_sync is None

    async def _async_fetch_bridge_data(self) -> dict[str, object] | None:
        """Fetch bridge API data if credentials are configured.

        Lazy-initialises the bridge client from entry options on first call.
        Returns parsed wiring state dict, or None if credentials are missing
        or the bridge API call fails (graceful degradation — never affects
        cloud data).
        """
        options = self.config_entry.options
        bridge_serial = options.get("bridge_serial", "")
        bridge_auth_key = options.get("bridge_auth_key", "")

        if not bridge_serial or not bridge_auth_key:
            # No credentials → skip silently
            self.bridge_api_client = None
            return None

        # Lazy-init (or re-init if credentials changed)
        if self.bridge_api_client is None:
            from homeassistant.helpers.aiohttp_client import (
                async_get_clientsession,
            )

            from .bridge_api import TadoBridgeApiClient

            session = async_get_clientsession(self.hass)
            self.bridge_api_client = TadoBridgeApiClient(session, bridge_serial, bridge_auth_key)

        try:
            return await self.bridge_api_client.async_get_wiring_state()
        except TadoBridgeApiError:
            _LOGGER.debug("Tado CE: Bridge API fetch failed — cloud data unaffected")
            return None

    async def _async_load_ratelimit(self) -> None:
        """Load ratelimit data via async I/O."""
        try:
            ratelimit_path = get_data_file("ratelimit", self.home_id)
            path_exists = await self.hass.async_add_executor_job(
                ratelimit_path.exists,
            )
            if path_exists:
                content = await self.hass.async_add_executor_job(
                    ratelimit_path.read_text,
                )
                self._cached_ratelimit = json.loads(content)
                _LOGGER.debug(
                    "Tado CE: async_load_ratelimit - loaded used=%s",
                    self._cached_ratelimit.get("used"),
                )
            else:
                self._cached_ratelimit = None
        except Exception as e:
            self._cached_ratelimit = None
            _LOGGER.debug("Tado CE: async_load_ratelimit - exception: %s", e)

    async def mark_entity_fresh(self, entity_id: str) -> None:
        """Mark entity as having a recent API call."""
        async with self._freshness_lock:
            self.entity_freshness[entity_id] = time.monotonic()
            _LOGGER.debug("Marked entity fresh: %s", entity_id)

    def is_entity_fresh(self, entity_id: str, debounce_seconds: int | None = None) -> bool:
        """Check if entity has a recent API call (within debounce window)."""
        if entity_id not in self.entity_freshness:
            return False
        if debounce_seconds is None:
            debounce_seconds = self.config_manager.get_refresh_debounce_seconds() + 2
        elapsed = time.monotonic() - self.entity_freshness[entity_id]
        if elapsed > debounce_seconds:
            del self.entity_freshness[entity_id]
            return False
        return True

    def get_next_sequence(self) -> int:
        """Get next monotonically increasing sequence number (overflow-safe)."""
        self._global_sequence += 1
        if self._global_sequence >= sys.maxsize:
            _LOGGER.info("Sequence number reached max, resetting to 0")
            self._global_sequence = 0
        return self._global_sequence

    async def _cleanup_entity_freshness(self) -> None:
        """Remove expired freshness entries."""
        async with self._freshness_lock:
            now = time.monotonic()
            expired = [eid for eid, timestamp in self.entity_freshness.items() if now - timestamp > 60]
            for eid in expired:
                del self.entity_freshness[eid]
            if expired:
                _LOGGER.debug("Cleaned up %d expired entity freshness entries", len(expired))

    async def async_set_zone_overlay(self, zone_id: str, setting: dict[str, Any], termination: dict[str, Any]) -> bool:
        """Set zone overlay then trigger immediate refresh."""
        result = await self.api_client.set_zone_overlay(zone_id, setting, termination)
        if result:
            await self.async_request_refresh()
        return result

    async def async_reset_zone_overlay(self, zone_id: str) -> bool:
        """Delete zone overlay (return to schedule) then refresh."""
        result = await self.api_client.delete_zone_overlay(zone_id)
        if result:
            await self.async_request_refresh()
        return result

    async def async_set_presence(self, state: str) -> bool:
        """Set presence lock (HOME/AWAY) then refresh."""
        result = await self.api_client.set_presence_lock(state)
        if result:
            await self.async_request_refresh()
        return result

    async def async_set_home_state(self, state: str) -> bool:
        """Set home state — HOME/AWAY sets presence lock, AUTO deletes it."""
        if state.upper() == "AUTO":
            result = await self.api_client.delete_presence_lock()
        else:
            result = await self.api_client.set_presence_lock(state)
        if result:
            await self.async_request_refresh()
        return result
