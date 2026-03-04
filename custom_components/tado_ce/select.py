"""Tado CE Select Platform (Presence Mode).

Select entity for presence mode control with "Auto" option to resume geofencing.
"""
import logging
import time
from datetime import timedelta
from typing import TYPE_CHECKING

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .action_helpers import (
    check_bootstrap_reserve as _check_bootstrap_reserve,
)
from .action_helpers import (
    is_within_optimistic_window as _is_within_optimistic_window,
)
from .optimistic import clear_optimistic_state
from .const import (
    OVERLAY_MODE_DEFAULT,
    OVERLAY_MODE_DEFAULT_DISPLAY,
    OVERLAY_MODE_MAP,
    OVERLAY_MODE_OPTIONS,
    OVERLAY_MODE_REVERSE_MAP,
    TIMER_DURATION_DEFAULT,
    TIMER_DURATION_OPTIONS,
)
from .device_manager import get_hub_device_info
from .helpers import async_trigger_immediate_refresh

if TYPE_CHECKING:
    from .coordinator import TadoDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)
SCAN_INTERVAL = timedelta(seconds=30)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Tado CE select entities from a config entry."""
    _LOGGER.debug("Tado CE select: Setting up...")
    coordinator: TadoDataUpdateCoordinator = entry.runtime_data
    home_id = coordinator.home_id

    entities = []

    # Add Presence Mode select (global, 1 API call per change)
    entities.append(TadoPresenceModeSelect(coordinator, home_id))

    # Add Overlay Mode select
    # 0 API calls - purely local setting
    entities.append(TadoOverlayModeSelect(coordinator, home_id))

    # Add Timer Duration select (for Timer overlay mode)
    # 0 API calls - purely local setting
    entities.append(TadoTimerDurationSelect(coordinator, home_id))

    if entities:
        async_add_entities(entities, True)  # noqa: FBT003
        _LOGGER.info("Tado CE select entities loaded: %s", len(entities))

    # Zone configuration select entities (per-zone settings)
    from .zone_config import async_setup_zone_config_select  # noqa: PLC0415
    await async_setup_zone_config_select(hass, entry, async_add_entities)


class TadoPresenceModeSelect(CoordinatorEntity["TadoDataUpdateCoordinator"], SelectEntity):
    """TadoPresenceModeSelect."""

    _attr_has_entity_name = True


    """Tado CE Presence Mode Select Entity.

    Allows control of presence mode: auto (geofencing), home, away.

    3-layer defense for optimistic state management:
    - Layer 1: _optimistic_set_at freshness tracking
    - Layer 2: Sequence numbers via get_next_sequence()
    - Layer 3: Expected state confirmation

    Uses 1 API call per change.
    """

    _attr_options = ["Auto", "Home", "Away"]  # noqa: RUF012
    _attr_translation_key = "presence_mode"

    def __init__(self, coordinator: "TadoDataUpdateCoordinator", home_id: str) -> None:
        """Initialize."""
        super().__init__(coordinator)
        # Convenience alias — used by action_helpers that still accept entry_id
        self._entry_id = coordinator.config_entry.entry_id
        self._attr_unique_id = f"tado_ce_{home_id}_presence_mode"
        self._attr_name = "[CE] Presence Mode"
        self._attr_current_option = "Auto"
        self._attr_available = True
        self._attr_device_info = get_hub_device_info(home_id)
        self.entity_id = "select.tado_ce_presence_mode"

        # State tracking
        self._presence = "HOME"
        self._presence_locked = False

        # 3-layer defense (parity with climate/water_heater)
        self._optimistic_set_at: float | None = None
        self._optimistic_sequence: int | None = None
        self._expected_mode: str | None = None

    # ========== Helper Methods ==========

    def _is_within_optimistic_window(self) -> bool:
        """Check if we're within the optimistic update window."""
        return _is_within_optimistic_window(self.hass, self._optimistic_set_at, entry_id=self._entry_id)

    def _clear_optimistic_state(self) -> None:
        """Clear all optimistic state tracking.

        Delegates to shared optimistic.clear_optimistic_state().
        """
        clear_optimistic_state(self)

    # ========== End Helper Methods ==========

    @property
    def icon(self) -> None:
        """Return icon based on current mode."""
        if self._attr_current_option == "Auto":
            return "mdi:home-account"
        if self._attr_current_option == "Home":
            return "mdi:home"
        # Away
        return "mdi:home-export-outline"

    @property
    def extra_state_attributes(self) -> None:
        """Return extra state attributes."""
        return {
            "presence": self._presence,
            "presence_locked": self._presence_locked,
            "automatic_geofencing": not self._presence_locked,
            "api_calls_per_change": 1,
        }

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle coordinator data update.

        CoordinatorEntity calls this automatically.
        """
        self.update()
        self.async_write_ha_state()

    @callback
    def update(self) -> None:  # noqa: C901, PLR0912
        """Update state from home_state.json.

        3-layer defense - preserve optimistic state if within window
        or if API hasn't confirmed expected state yet.
        """
        # Layer 1: Skip if within optimistic window
        if self._is_within_optimistic_window():
            _LOGGER.debug("Presence Mode: Preserving optimistic state (within window)")
            return

        # Window expired, clear optimistic tracking
        if self._optimistic_set_at is not None:
            self._optimistic_set_at = None

        # Load from coordinator cache (async-loaded, no file I/O)
        try:
            coord_data = self.coordinator.data or {}
            home_state = coord_data.get("home_state")
            if not home_state:
                return

            api_presence = home_state.get("presence", "HOME")
            api_locked = home_state.get("presenceLocked", False)

            # Layer 3: Check if API confirmed expected state
            if self._optimistic_sequence is not None and self._expected_mode is not None:
                # Determine what mode API is showing
                if not api_locked:
                    api_mode = "Auto"
                elif api_presence == "HOME":
                    api_mode = "Home"
                else:
                    api_mode = "Away"

                if api_mode == self._expected_mode:
                    # API confirmed - clear optimistic state
                    self._clear_optimistic_state()
                else:
                    # Preserve optimistic state - API hasn't caught up yet
                    _LOGGER.debug(
                        "Presence Mode: Preserving optimistic state (expected=%s, api=%s)",
                        self._expected_mode, api_mode,
                    )
                    return

            # Update from API
            self._presence = api_presence
            self._presence_locked = api_locked

            # Determine mode from API state
            if not api_locked:
                self._attr_current_option = "Auto"
            elif api_presence == "HOME":
                self._attr_current_option = "Home"
            else:
                self._attr_current_option = "Away"

        except Exception as e:  # noqa: BLE001
            _LOGGER.warning("Failed to update presence mode: %s", e)
            # Keep last known state

    async def async_select_option(self, option: str) -> None:
        """Select presence mode with 3-layer defense.

        Bootstrap Reserve check
        Full 3-layer optimistic update
        """
        # Bootstrap Reserve - block action when quota critically low
        await _check_bootstrap_reserve(self.hass, "Presence Mode", entry_id=self._entry_id)

        # Store previous state for rollback
        old_mode = self._attr_current_option
        old_presence = self._presence
        old_locked = self._presence_locked

        # Layer 1 & 2: Optimistic update BEFORE API call
        self._attr_current_option = option
        self._optimistic_set_at = time.time()
        self._optimistic_sequence = self.coordinator.get_next_sequence()

        # Layer 3: Set expected state
        self._expected_mode = option

        # Update internal state optimistically
        if option == "Auto":
            self._presence_locked = False
        else:
            self._presence_locked = True
            self._presence = option.upper()

        self.async_write_ha_state()

        # API call - normalize to lowercase for API
        option_lower = option.lower()
        client = self.coordinator.api_client
        if option_lower == "auto":
            success = await client.delete_presence_lock()
        else:
            success = await client.set_presence_lock(option.upper())

        if success:
            _LOGGER.info("Set presence mode to %s", option)
            await async_trigger_immediate_refresh(self.hass, self.entity_id, f"presence_mode_{option}", include_home_state=True)  # noqa: E501
        else:
            # Rollback on failure
            _LOGGER.warning("ROLLBACK: Presence mode %s failed", option)
            self._attr_current_option = old_mode
            self._presence = old_presence
            self._presence_locked = old_locked
            self._clear_optimistic_state()
            self.async_write_ha_state()



# ============================================================
# Overlay Mode Select
# ============================================================

class TadoOverlayModeSelect(CoordinatorEntity["TadoDataUpdateCoordinator"], SelectEntity):
    """TadoOverlayModeSelect."""

    _attr_has_entity_name = True


    """Tado CE Overlay Mode Select Entity.

    Allows control of overlay termination type for manual temperature changes.
    Configurable overlay mode.

    Options:
    - Tado Mode: Follows per-device "Manual Control" settings in Tado app
    - Next Time Block: Override lasts until next scheduled change
    - Timer: Override lasts for specified duration (see Timer Duration)
    - Manual: Infinite override until user manually changes

    Uses 0 API calls - purely local setting stored in .storage/tado_ce/.

    Uses hass.data cache to avoid blocking I/O in update(),
    and async_add_executor_job for file saves.
    """

    _attr_options = OVERLAY_MODE_OPTIONS
    _attr_translation_key = "overlay_mode"

    def __init__(self, coordinator: "TadoDataUpdateCoordinator", home_id: str) -> None:
        """Initialize."""
        super().__init__(coordinator)
        # Convenience alias — used by action_helpers that still accept entry_id
        self._entry_id = coordinator.config_entry.entry_id
        self._attr_unique_id = f"tado_ce_{home_id}_overlay_mode"
        self._attr_name = "[CE] Overlay Mode"
        self._attr_current_option = OVERLAY_MODE_DEFAULT_DISPLAY
        self._attr_available = True
        self._attr_device_info = get_hub_device_info(home_id)
        self._attr_icon = "mdi:timer-cog-outline"
        self.entity_id = "select.tado_ce_overlay_mode"

    @property
    def extra_state_attributes(self) -> None:
        """Return extra state attributes."""
        return {
            "description": "Controls how long manual temperature changes last",
            "tado_mode_info": "Follows per-device settings in Tado app",
            "next_time_block_info": "Until next scheduled change",
            "timer_info": "For specified duration (see Timer Duration)",
            "manual_info": "Until you manually change back",
            "api_calls_per_change": 0,
        }

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle coordinator data update.

        CoordinatorEntity calls this automatically.
        """
        self.update()
        self.async_write_ha_state()

    @callback
    def update(self) -> None:
        """Load overlay mode from coordinator cache.

        Reads from coordinator cache instead of hass.data.
        """
        try:
            overlay_mode = self.coordinator.overlay_mode or OVERLAY_MODE_DEFAULT
            self._attr_current_option = OVERLAY_MODE_REVERSE_MAP.get(overlay_mode, OVERLAY_MODE_DEFAULT_DISPLAY)
        except Exception as e:  # noqa: BLE001
            _LOGGER.warning("Failed to get overlay mode from cache: %s", e)
            # Keep current option

    async def async_select_option(self, option: str) -> None:
        """Select overlay mode (local only, no API call)."""
        # Update state immediately
        self._attr_current_option = option
        self.async_write_ha_state()

        # Save to storage (non-blocking)
        api_mode = OVERLAY_MODE_MAP.get(option, OVERLAY_MODE_DEFAULT)
        success = await self.hass.async_add_executor_job(self.coordinator.data_loader.save_overlay_mode, api_mode)

        if success:
            # Update coordinator cache
            self.coordinator.overlay_mode = api_mode
            _LOGGER.info("Overlay mode set to %s (%s)", option, api_mode)
        else:
            _LOGGER.error("Failed to save overlay mode: %s", option)


class TadoTimerDurationSelect(CoordinatorEntity["TadoDataUpdateCoordinator"], SelectEntity):
    """TadoTimerDurationSelect."""

    _attr_has_entity_name = True


    """Tado CE Timer Duration Select Entity.

    Controls how long Timer overlay mode lasts.
    Only relevant when Overlay Mode = Timer.

    Added for consistency with per-zone config.
    """

    _attr_options = TIMER_DURATION_OPTIONS
    _attr_translation_key = "timer_duration"

    def __init__(self, coordinator: "TadoDataUpdateCoordinator", home_id: str) -> None:
        """Initialize."""
        super().__init__(coordinator)
        # Convenience alias — used by action_helpers that still accept entry_id
        self._entry_id = coordinator.config_entry.entry_id
        self._attr_unique_id = f"tado_ce_{home_id}_overlay_timer"
        self._attr_name = "[CE] Overlay Timer"
        self._attr_current_option = str(TIMER_DURATION_DEFAULT)
        self._attr_available = True
        self._attr_device_info = get_hub_device_info(home_id)
        self._attr_icon = "mdi:timer"
        self._attr_unit_of_measurement = "min"
        self.entity_id = "select.tado_ce_overlay_timer_duration"

    @property
    def extra_state_attributes(self) -> None:
        """Return extra state attributes."""
        return {
            "description": "Duration for Timer overlay mode",
            "unit": "minutes",
            "api_calls_per_change": 0,
        }

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle coordinator data update.

        CoordinatorEntity calls this automatically.
        """
        self.update()
        self.async_write_ha_state()

    @callback
    def update(self) -> None:
        """Load timer duration from coordinator cache."""
        try:
            duration = self.coordinator.timer_duration or TIMER_DURATION_DEFAULT
            self._attr_current_option = str(duration)
        except Exception as e:  # noqa: BLE001
            _LOGGER.warning("Failed to get timer duration from cache: %s", e)

    async def async_select_option(self, option: str) -> None:
        """Select timer duration (local only, no API call)."""
        # Update state immediately
        self._attr_current_option = option
        self.async_write_ha_state()

        # Save to storage (non-blocking)
        duration = int(option)
        success = await self.hass.async_add_executor_job(self.coordinator.data_loader.save_timer_duration, duration)

        if success:
            # Update coordinator cache
            self.coordinator.timer_duration = duration
            _LOGGER.info("Timer duration set to %s minutes", duration)
        else:
            _LOGGER.error("Failed to save timer duration: %s", option)
