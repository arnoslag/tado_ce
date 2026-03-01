"""Tado CE Select Platform (Presence Mode).

v2.0.2: New select entity for presence mode control.
Discussion #102 (@wyx087) - Adds "Auto" option to resume geofencing.
"""
import logging
import time
from datetime import timedelta

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import (
    DOMAIN, 
    OVERLAY_MODE_OPTIONS, OVERLAY_MODE_MAP, OVERLAY_MODE_REVERSE_MAP,
    OVERLAY_MODE_DEFAULT, OVERLAY_MODE_DEFAULT_DISPLAY,
    TIMER_DURATION_OPTIONS, TIMER_DURATION_DEFAULT,
)
from .device_manager import get_hub_device_info
from .entry_data import get_entry_data
from .action_helpers import (
    check_bootstrap_reserve as _check_bootstrap_reserve,
    is_within_optimistic_window as _is_within_optimistic_window,
)

_LOGGER = logging.getLogger(__name__)
SCAN_INTERVAL = timedelta(seconds=30)

# Cached home_id to avoid blocking calls in event loop
_CACHED_HOME_ID = None


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback):
    """Set up Tado CE select entities from a config entry."""
    global _CACHED_HOME_ID
    _LOGGER.debug("Tado CE select: Setting up...")
    from .data_loader import get_current_home_id
    _CACHED_HOME_ID = await hass.async_add_executor_job(get_current_home_id)
    entry_id = entry.entry_id
    
    entities = []
    
    # Add Presence Mode select (global, 1 API call per change)
    entities.append(TadoPresenceModeSelect(entry_id))
    
    # v2.0.2: Add Overlay Mode select (Issue #101 - @leoogermenia)
    # 0 API calls - purely local setting
    entities.append(TadoOverlayModeSelect(entry_id))
    
    # v2.1.0: Add Timer Duration select (for Timer overlay mode)
    # 0 API calls - purely local setting
    entities.append(TadoTimerDurationSelect(entry_id))
    
    if entities:
        async_add_entities(entities, True)
        _LOGGER.info(f"Tado CE select entities loaded: {len(entities)}")
    
    # v2.1.0: Zone configuration select entities (per-zone settings)
    from .zone_config import async_setup_zone_config_select
    await async_setup_zone_config_select(hass, entry, async_add_entities)


class TadoPresenceModeSelect(SelectEntity):
    _attr_has_entity_name = True

    """Tado CE Presence Mode Select Entity.
    
    Allows control of presence mode: auto (geofencing), home, away.
    Replaces the old switch.tado_ce_away_mode (v2.0.2 breaking change).
    
    v2.0.2: Full 3-layer defense (lesson from v2.0.1 hot water fix)
    - Layer 1: _optimistic_set_at freshness tracking
    - Layer 2: Sequence numbers via get_next_sequence()
    - Layer 3: Expected state confirmation
    
    Uses 1 API call per change.
    """
    
    _attr_options = ["Auto", "Home", "Away"]
    _attr_translation_key = "presence_mode"
    
    def __init__(self, entry_id: str):
        self._entry_id = entry_id
        self._attr_unique_id = f"tado_ce_{_CACHED_HOME_ID}_presence_mode"
        self._attr_name = "[CE] Presence Mode"
        self._attr_current_option = "Auto"
        self._attr_available = True
        self._attr_device_info = get_hub_device_info(_CACHED_HOME_ID)
        # v2.0.2: Force entity_id for consistent naming (lesson learned)
        self.entity_id = "select.tado_ce_presence_mode"
        
        # State tracking
        self._presence = "HOME"
        self._presence_locked = False
        
        # v2.0.2: 3-layer defense (parity with climate/water_heater)
        self._optimistic_set_at: float | None = None
        self._optimistic_sequence: int | None = None
        self._expected_mode: str | None = None

    # ========== v2.0.2: Helper Methods ==========
    
    def _is_within_optimistic_window(self) -> bool:
        """Check if we're within the optimistic update window."""
        return _is_within_optimistic_window(self.hass, self._optimistic_set_at)
    
    def _clear_optimistic_state(self):
        """Clear all optimistic state tracking."""
        self._optimistic_set_at = None
        self._optimistic_sequence = None
        self._expected_mode = None
    
    # ========== End Helper Methods ==========
    
    @property
    def icon(self):
        """Return icon based on current mode."""
        if self._attr_current_option == "Auto":
            return "mdi:home-account"
        elif self._attr_current_option == "Home":
            return "mdi:home"
        else:  # Away
            return "mdi:home-export-outline"
    
    @property
    def extra_state_attributes(self):
        return {
            "presence": self._presence,
            "presence_locked": self._presence_locked,
            "automatic_geofencing": not self._presence_locked,
            "api_calls_per_change": 1,
        }
    
    @callback
    def update(self):
        """Update state from home_state.json.
        
        v2.0.2: 3-layer defense - preserve optimistic state if within window
        or if API hasn't confirmed expected state yet.
        """
        # Layer 1: Skip if within optimistic window
        if self._is_within_optimistic_window():
            _LOGGER.debug("Presence Mode: Preserving optimistic state (within window)")
            return
        
        # Window expired, clear optimistic tracking
        if self._optimistic_set_at is not None:
            self._optimistic_set_at = None
        
        # Load from file
        try:
            from .data_loader import load_home_state_file
            home_state = load_home_state_file()
            if not home_state:
                return
            
            api_presence = home_state.get('presence', 'HOME')
            api_locked = home_state.get('presenceLocked', False)
            
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
                    _LOGGER.debug(f"Presence Mode: Preserving optimistic state (expected={self._expected_mode}, api={api_mode})")
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
                
        except Exception as e:
            _LOGGER.warning(f"Failed to update presence mode: {e}")
            # Keep last known state
    
    async def async_select_option(self, option: str) -> None:
        """Select presence mode with 3-layer defense.
        
        v2.0.1: Bootstrap Reserve check
        v2.0.2: Full 3-layer optimistic update
        """
        
        # v2.0.1: Bootstrap Reserve - block action when quota critically low
        await _check_bootstrap_reserve(self.hass, "Presence Mode")
        
        # Store previous state for rollback
        old_mode = self._attr_current_option
        old_presence = self._presence
        old_locked = self._presence_locked
        
        # Layer 1 & 2: Optimistic update BEFORE API call
        self._attr_current_option = option
        self._optimistic_set_at = time.time()
        _ed = get_entry_data(self.hass, self._entry_id)
        self._optimistic_sequence = _ed.get_next_sequence()
        
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
        client = get_entry_data(self.hass, self._entry_id).api_client
        if option_lower == "auto":
            success = await client.delete_presence_lock()
        else:
            success = await client.set_presence_lock(option.upper())
        
        if success:
            _LOGGER.info(f"Set presence mode to {option}")
            await self._async_trigger_immediate_refresh(f"presence_mode_{option}")
        else:
            # Rollback on failure
            _LOGGER.warning(f"ROLLBACK: Presence mode {option} failed")
            self._attr_current_option = old_mode
            self._presence = old_presence
            self._presence_locked = old_locked
            self._clear_optimistic_state()
            self.async_write_ha_state()
    
    async def _async_trigger_immediate_refresh(self, reason: str):
        """Trigger immediate refresh after state change.
        
        v2.0.2: DRY refactor - delegates to shared async_trigger_immediate_refresh().
        Includes home_state refresh for presence mode changes.
        """
        from . import async_trigger_immediate_refresh
        await async_trigger_immediate_refresh(self.hass, self.entity_id, reason, include_home_state=True)


# ============================================================
# v2.0.2: Overlay Mode Select (Issue #101 - @leoogermenia)
# ============================================================

class TadoOverlayModeSelect(SelectEntity):
    _attr_has_entity_name = True

    """Tado CE Overlay Mode Select Entity.
    
    Allows control of overlay termination type for manual temperature changes.
    Issue #101 (@leoogermenia) - Configurable overlay mode.
    
    Options:
    - Tado Mode: Follows per-device "Manual Control" settings in Tado app
    - Next Time Block: Override lasts until next scheduled change
    - Timer: Override lasts for specified duration (see Timer Duration)
    - Manual: Infinite override until user manually changes
    
    Uses 0 API calls - purely local setting stored in .storage/tado_ce/.
    
    v2.0.2: Lesson from v2.0.0 - uses hass.data cache to avoid blocking I/O
    in update(), and async_add_executor_job for file saves.
    v2.1.0: Added Timer option for consistency with per-zone config.
    """
    
    _attr_options = OVERLAY_MODE_OPTIONS
    _attr_translation_key = "overlay_mode"
    
    def __init__(self, entry_id: str):
        self._entry_id = entry_id
        self._attr_unique_id = f"tado_ce_{_CACHED_HOME_ID}_overlay_mode"
        self._attr_name = "[CE] Overlay Mode"
        self._attr_current_option = OVERLAY_MODE_DEFAULT_DISPLAY
        self._attr_available = True
        self._attr_device_info = get_hub_device_info(_CACHED_HOME_ID)
        self._attr_icon = "mdi:timer-cog-outline"
        # v2.0.2: Force entity_id for consistent naming (lesson learned)
        self.entity_id = "select.tado_ce_overlay_mode"
    
    @property
    def extra_state_attributes(self):
        return {
            "description": "Controls how long manual temperature changes last",
            "tado_mode_info": "Follows per-device settings in Tado app",
            "next_time_block_info": "Until next scheduled change",
            "timer_info": "For specified duration (see Timer Duration)",
            "manual_info": "Until you manually change back",
            "api_calls_per_change": 0,
        }
    
    @callback
    def update(self):
        """Load overlay mode from hass.data cache.
        
        v2.0.2: Lesson from v2.0.0 - Never do sync file I/O in update().
        Reads from hass.data cache which is populated during async_setup_entry.
        """
        try:
            overlay_mode = get_entry_data(self.hass, self._entry_id).overlay_mode or OVERLAY_MODE_DEFAULT
            self._attr_current_option = OVERLAY_MODE_REVERSE_MAP.get(overlay_mode, OVERLAY_MODE_DEFAULT_DISPLAY)
        except Exception as e:
            _LOGGER.warning(f"Failed to get overlay mode from cache: {e}")
            # Keep current option
    
    async def async_select_option(self, option: str) -> None:
        """Select overlay mode (local only, no API call).
        
        v2.0.2: Lesson from v2.0.0 - Uses async_add_executor_job for file I/O.
        """
        from .data_loader import save_overlay_mode
        
        # Update state immediately
        self._attr_current_option = option
        self.async_write_ha_state()
        
        # Save to storage (non-blocking)
        api_mode = OVERLAY_MODE_MAP.get(option, OVERLAY_MODE_DEFAULT)
        success = await self.hass.async_add_executor_job(save_overlay_mode, api_mode)
        
        if success:
            # Update hass.data cache
            get_entry_data(self.hass, self._entry_id).overlay_mode = api_mode
            _LOGGER.info(f"Overlay mode set to {option} ({api_mode})")
        else:
            _LOGGER.error(f"Failed to save overlay mode: {option}")


class TadoTimerDurationSelect(SelectEntity):
    _attr_has_entity_name = True

    """Tado CE Timer Duration Select Entity.
    
    Controls how long Timer overlay mode lasts.
    Only relevant when Overlay Mode = Timer.
    
    v2.1.0: Added for consistency with per-zone config.
    """
    
    _attr_options = TIMER_DURATION_OPTIONS
    _attr_translation_key = "timer_duration"
    
    def __init__(self, entry_id: str):
        self._entry_id = entry_id
        self._attr_unique_id = f"tado_ce_{_CACHED_HOME_ID}_overlay_timer"
        self._attr_name = "[CE] Overlay Timer"
        self._attr_current_option = str(TIMER_DURATION_DEFAULT)
        self._attr_available = True
        self._attr_device_info = get_hub_device_info(_CACHED_HOME_ID)
        self._attr_icon = "mdi:timer"
        self._attr_unit_of_measurement = "min"
        self.entity_id = "select.tado_ce_overlay_timer_duration"
    
    @property
    def extra_state_attributes(self):
        return {
            "description": "Duration for Timer overlay mode",
            "unit": "minutes",
            "api_calls_per_change": 0,
        }
    
    @callback
    def update(self):
        """Load timer duration from hass.data cache."""
        try:
            duration = get_entry_data(self.hass, self._entry_id).timer_duration or TIMER_DURATION_DEFAULT
            self._attr_current_option = str(duration)
        except Exception as e:
            _LOGGER.warning(f"Failed to get timer duration from cache: {e}")
    
    async def async_select_option(self, option: str) -> None:
        """Select timer duration (local only, no API call)."""
        from .data_loader import save_timer_duration
        
        # Update state immediately
        self._attr_current_option = option
        self.async_write_ha_state()
        
        # Save to storage (non-blocking)
        duration = int(option)
        success = await self.hass.async_add_executor_job(save_timer_duration, duration)
        
        if success:
            # Update hass.data cache
            get_entry_data(self.hass, self._entry_id).timer_duration = duration
            _LOGGER.info(f"Timer duration set to {duration} minutes")
        else:
            _LOGGER.error(f"Failed to save timer duration: {option}")
