"""Tado CE DataUpdateCoordinator.

Uses HA's built-in DataUpdateCoordinator + CoordinatorEntity pattern
for adaptive polling and entity update propagation.
"""
from __future__ import annotations

import asyncio
import json
import logging
import sys
import time
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    UpdateFailed,
)

import aiofiles
import aiofiles.os

from .const import DOMAIN, FULL_SYNC_INTERVAL_HOURS, get_data_file
from .exceptions import TadoAuthError, TadoSyncError
from .insight_history import InsightHistoryTracker
from .polling import get_polling_interval, should_pause_polling

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from .adaptive_preheat import AdaptivePreheatManager
    from .api_call_tracker import APICallTracker
    from .api_client import TadoApiClient
    from .config_manager import ConfigurationManager
    from .data_loader import DataLoader
    from .heating_coordinator import HeatingCycleCoordinator
    from .smart_comfort import SmartComfortManager
    from .zone_config_manager import ZoneConfigManager

_LOGGER = logging.getLogger(__name__)


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
            name="%s (%s)" % (DOMAIN, config_manager.get_all_config().get("home_id", "default")),
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
        from .refresh_handler import RefreshHandler  # noqa: PLC0415
        self.refresh_handler = RefreshHandler(self)

        self.home_id: str = entry.data.get("home_id") or "default"

        # Freshness tracking
        self.entity_freshness: dict[str, float] = {}
        self._freshness_lock = asyncio.Lock()
        self._global_sequence: int = 0

        # Overlay/timer cache
        self.overlay_mode: str = "TADO_MODE"
        self.timer_duration: int = 60

        # Outdoor temp history (owned by coordinator, async I/O only)
        self._outdoor_temp_history: list[float] = []
        self._outdoor_temp_loaded: bool = False

        # Insight history tracker (persistent insight duration tracking)
        self.insight_history = InsightHistoryTracker(hass, self.home_id)

        # Full sync tracking
        self._last_full_sync: datetime | None = None
        self._cached_ratelimit: dict | None = None

    @property
    def outdoor_temp_history(self) -> list[float]:
        """Return outdoor temp history (read-only access for sensors)."""
        return self._outdoor_temp_history


    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch data from Tado API. Dynamically adjusts update_interval."""
        # 1. Load ratelimit and check quota
        await self._async_load_ratelimit()
        if self._cached_ratelimit:
            should_pause, reason = should_pause_polling(
                self._cached_ratelimit, self.config_manager
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
            raise ConfigEntryAuthFailed(
                "Refresh token expired — user must re-authenticate"
            ) from e
        except TadoSyncError as e:
            raise UpdateFailed("Tado CE sync failed: %s" % e) from e

        if do_full_sync:
            self._last_full_sync = datetime.now()

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
            await async_update_ratelimit_reset_time(self.hass, detected_reset, self.home_id)

        # 5. Load all data files in parallel (no inter-dependencies)
        (
            zone_data,
            config_data,
            home_state_data,
            ratelimit_data,
            api_call_history_data,
            zones_info_data,
            weather_data,
            mobile_devices_data,
            offsets_data,
            schedules_data,
            ac_capabilities,
        ) = await asyncio.gather(
            self.hass.async_add_executor_job(self.data_loader.load_zones_file),
            self.hass.async_add_executor_job(self.data_loader.load_config_file),
            self.hass.async_add_executor_job(self.data_loader.load_home_state_file),
            self.hass.async_add_executor_job(self.data_loader.load_ratelimit_file),
            self.hass.async_add_executor_job(self.data_loader.load_api_call_history_file),
            self.hass.async_add_executor_job(self.data_loader.load_zones_info_file),
            self.hass.async_add_executor_job(self.data_loader.load_weather_file),
            self.hass.async_add_executor_job(self.data_loader.load_mobile_devices_file),
            self.hass.async_add_executor_job(self.data_loader.load_offsets_file),
            self.hass.async_add_executor_job(self.data_loader.load_schedules_file),
            self.hass.async_add_executor_job(self.data_loader.load_ac_capabilities_file),
        )

        # 5e. Accumulate outdoor temp history (depends on weather_data above)
        if weather_data:
            outdoor_temp = (weather_data.get("outsideTemperature") or {}).get("celsius")
            if outdoor_temp is not None:
                if not self._outdoor_temp_loaded:
                    loaded = await self.hass.async_add_executor_job(
                        self.data_loader.load_outdoor_temp_history
                    )
                    self._outdoor_temp_history = loaded
                    self._outdoor_temp_loaded = True

                self._outdoor_temp_history.append(outdoor_temp)
                if len(self._outdoor_temp_history) > 336:
                    del self._outdoor_temp_history[:len(self._outdoor_temp_history) - 336]

                await self.hass.async_add_executor_job(
                    self.data_loader.save_outdoor_temp_history,
                    self._outdoor_temp_history,
                )

        # 6. Notify HeatingCycleCoordinator of zone updates
        if self.heating_cycle_coordinator and zone_data:
            zone_states = zone_data.get("zoneStates", {})
            for zone_id, data in zone_states.items():
                try:
                    setting = data.get("setting") or {}
                    target_temp = (setting.get("temperature") or {}).get("celsius")
                    sensor_data = data.get("sensorDataPoints") or {}
                    current_temp = (
                        (sensor_data.get("insideTemperature") or {}).get("celsius")
                    )
                    if target_temp is not None and current_temp is not None:
                        await self.heating_cycle_coordinator.on_zone_update(
                            zone_id, target_temp, current_temp,
                        )
                except Exception:
                    _LOGGER.debug("HeatingCycleCoordinator update failed for zone %s", zone_id)

        # 8. Cleanup expired entity freshness entries (replaces 5-min timer)
        await self._cleanup_entity_freshness()

        # 9. Save insight history if dirty (piggyback on poll cycle)
        if self.insight_history._dirty:
            await self.insight_history.async_save()

        return {
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
        }


    def _should_do_full_sync(self) -> bool:
        """Check if full sync needed (vs quick). Runs on first poll + every N hours."""
        if self._last_full_sync is None:
            return True
        hours_since = (datetime.now() - self._last_full_sync).total_seconds() / 3600
        return hours_since >= FULL_SYNC_INTERVAL_HOURS

    async def _async_load_ratelimit(self) -> None:
        """Load ratelimit data via async I/O."""
        try:
            ratelimit_path = get_data_file("ratelimit", self.home_id)
            if await aiofiles.os.path.exists(ratelimit_path):
                async with aiofiles.open(ratelimit_path, "r") as f:
                    content = await f.read()
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
            self.entity_freshness[entity_id] = time.time()
            _LOGGER.debug("Marked entity fresh: %s", entity_id)

    def is_entity_fresh(self, entity_id: str, debounce_seconds: int | None = None) -> bool:
        """Check if entity has a recent API call (within debounce window)."""
        if entity_id not in self.entity_freshness:
            return False
        if debounce_seconds is None:
            debounce_seconds = self.config_manager.get_refresh_debounce_seconds() + 2
        elapsed = time.time() - self.entity_freshness[entity_id]
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
            now = time.time()
            expired = [
                eid for eid, timestamp in self.entity_freshness.items()
                if now - timestamp > 60
            ]
            for eid in expired:
                del self.entity_freshness[eid]
            if expired:
                _LOGGER.debug("Cleaned up %d expired entity freshness entries", len(expired))

    async def async_set_zone_overlay(
        self, zone_id: str, setting: dict, termination: dict) -> bool:
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
