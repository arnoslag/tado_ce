"""Tado CE Water Heater Platform."""
import asyncio
import json
import logging
import time
from datetime import timedelta

from homeassistant.components.water_heater import (
    WaterHeaterEntity,
    WaterHeaterEntityFeature,
)
from homeassistant.const import STATE_OFF, UnitOfTemperature
from homeassistant.core import HomeAssistant, callback
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import DOMAIN
from .device_manager import get_zone_device_info
from .data_loader import load_zones_file, load_zones_info_file, load_config_file, get_current_home_id
from .format_helpers import format_overlay_type as _format_overlay_type
from .action_helpers import (
    check_bootstrap_reserve as _check_bootstrap_reserve,
    is_within_optimistic_window as _is_within_optimistic_window,
)

_LOGGER = logging.getLogger(__name__)
SCAN_INTERVAL = timedelta(seconds=30)

# Cached home_id to avoid blocking calls in event loop
_CACHED_HOME_ID = None

# Operation modes for hot water
STATE_AUTO = "auto"  # Follow schedule (no overlay)
STATE_HEAT = "heat"  # Timer or manual heating
OPERATION_MODES = [STATE_AUTO, STATE_HEAT, STATE_OFF]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback):
    """Set up Tado CE water heater from a config entry."""
    global _CACHED_HOME_ID
    _CACHED_HOME_ID = await hass.async_add_executor_job(get_current_home_id)
    _LOGGER.debug("Tado CE water_heater: Setting up...")
    zones_info = await hass.async_add_executor_job(load_zones_info_file)
    
    water_heaters = []
    
    if zones_info:
        _LOGGER.debug(f"Tado CE water_heater: Found {len(zones_info)} zones")
        for zone in zones_info:
            zone_id = str(zone.get('id'))
            zone_name = zone.get('name', f"Zone {zone_id}")
            zone_type = zone.get('type')
            
            if zone_type == 'HOT_WATER':
                _LOGGER.debug(f"Tado CE water_heater: Creating entity for zone {zone_id} ({zone_name})")
                water_heaters.append(TadoWaterHeater(hass, zone_id, zone_name))
    
    if water_heaters:
        async_add_entities(water_heaters, True)
        _LOGGER.info(f"Tado CE water heaters loaded: {len(water_heaters)}")
    else:
        _LOGGER.debug("Tado CE: No hot water zones found")


class TadoWaterHeater(WaterHeaterEntity):
    _attr_has_entity_name = True

    """Tado CE Water Heater Entity."""
    
    def __init__(self, hass: HomeAssistant, zone_id: str, zone_name: str):
        self.hass = hass
        self._zone_id = zone_id
        self._zone_name = zone_name
        self._home_id = None
        
        self._attr_name = None
        # Use zone_id for unique_id to maintain entity_id stability across zone name changes
        self._attr_unique_id = f"tado_ce_{_CACHED_HOME_ID}_zone_{zone_id}_water_heater"
        self._attr_temperature_unit = UnitOfTemperature.CELSIUS
        self._attr_min_temp = 30
        self._attr_max_temp = 65
        # Use zone device info instead of hub device info
        self._attr_device_info = get_zone_device_info(zone_id, zone_name, "HOT_WATER")
        
        self._attr_current_operation = None
        self._attr_current_temperature = None
        self._attr_target_temperature = None
        self._attr_available = False
        
        # Supported features - will be updated based on zone capabilities
        self._supports_temperature = False
        self._attr_supported_features = WaterHeaterEntityFeature.OPERATION_MODE
        self._attr_operation_list = OPERATION_MODES
        
        self._overlay_type = None
        
        # v1.9.6: Optimistic update tracking (parity with climate entities)
        self._optimistic_set_at: float | None = None
        
        # v2.0.1: Full 3-layer defense (parity with climate entities)
        # Layer 2: Sequence number tracking
        self._optimistic_sequence: int | None = None
        # Layer 3: Expected state confirmation
        self._expected_operation: str | None = None
        self._expected_temperature: float | None = None

    # ========== v1.9.6: Helper Methods ==========
    
    def _clear_optimistic_state(self):
        """Clear all optimistic state tracking.
        
        v2.0.1: Added for full parity with climate entities.
        """
        self._optimistic_set_at = None
        self._optimistic_sequence = None
        self._expected_operation = None
        self._expected_temperature = None
    
    def _is_within_optimistic_window(self) -> bool:
        """Check if we're within the optimistic update window."""
        return _is_within_optimistic_window(self.hass, self._optimistic_set_at)

    # ========== End Helper Methods ==========

    @property
    def extra_state_attributes(self):
        return {
            "overlay_type": _format_overlay_type(self._overlay_type),
            "zone_id": self._zone_id,
        }

    @callback
    def update(self):
        """Update water heater state from JSON file.
        
        v1.9.6: Added optimistic window protection (parity with climate entities).
        v2.0.1: Added full 3-layer defense for parity with climate entities.
        """
        _LOGGER.debug(f"TadoWaterHeater.update() called for {self._zone_name} (zone {self._zone_id})")
        
        # v2.0.1: Layer 1 - Skip update if entity is fresh (coordinator-level protection)
        # This prevents stale data from overwriting optimistic state after user actions
        is_entity_fresh = self.hass.data.get(DOMAIN, {}).get('is_entity_fresh')
        if is_entity_fresh and is_entity_fresh(self.entity_id):
            _LOGGER.debug(f"Hot water {self._zone_name}: Skipping update (entity is fresh)")
            return
        
        try:
            # Load home_id from config (uses data_loader for per-home file support)
            config = load_config_file()
            if config:
                self._home_id = config.get("home_id")
            
            # Load zones data (uses data_loader for per-home file support)
            data = load_zones_file()
            if not data:
                _LOGGER.debug(f"No zones data for {self._zone_name} (zone {self._zone_id})")
                self._attr_available = False
                return
            
            # Use 'or {}' pattern for null safety
            zone_states = data.get('zoneStates') or {}
            zone_data = zone_states.get(self._zone_id)
            
            if not zone_data:
                _LOGGER.debug(f"No zone data for {self._zone_name} (zone {self._zone_id})")
                self._attr_available = False
                return
            
            # Check link state - if offline, mark unavailable
            link = zone_data.get('link') or {}
            link_state = link.get('state')
            if link_state != 'ONLINE':
                _LOGGER.debug(f"Zone {self._zone_name} link state: {link_state}")
                self._attr_available = False
                return
            
            _LOGGER.debug(f"Zone {self._zone_name} link state OK, setting available=True")
            setting = zone_data.get('setting') or {}
            power = setting.get('power')
            overlay = zone_data.get('overlay')
            api_overlay_type = zone_data.get('overlayType')
            
            # Read target temperature from setting (for systems that support it)
            temp_data = setting.get('temperature') or {}
            api_target_temp = temp_data.get('celsius')
            
            # Enable temperature feature if zone supports it
            if api_target_temp is not None and not self._supports_temperature:
                self._supports_temperature = True
                self._attr_supported_features = (
                    WaterHeaterEntityFeature.OPERATION_MODE |
                    WaterHeaterEntityFeature.TARGET_TEMPERATURE
                )
                _LOGGER.debug(f"Hot water zone {self._zone_name} supports temperature control")
            
            # Detect API operation mode based on overlay state
            if not overlay or api_overlay_type is None:
                api_operation = STATE_AUTO
            elif api_overlay_type == 'TIMER':
                api_operation = STATE_HEAT
            elif api_overlay_type == 'MANUAL':
                api_operation = STATE_OFF if power == 'OFF' else STATE_HEAT
            else:
                api_operation = STATE_AUTO
            
            # v2.0.1: Layer 3 - Explicit state confirmation
            # Check if API has confirmed our expected state
            should_preserve_optimistic = False
            
            if self._optimistic_sequence is not None:
                # We have optimistic state - check if API confirms it
                operation_confirmed = (self._expected_operation is None or 
                                       api_operation == self._expected_operation)
                temp_confirmed = (self._expected_temperature is None or 
                                  api_target_temp == self._expected_temperature)
                
                if operation_confirmed and temp_confirmed:
                    # API confirmed our expected state - clear optimistic tracking
                    _LOGGER.debug(
                        f"Hot water {self._zone_name}: API confirmed optimistic state "
                        f"(operation={api_operation}, temp={api_target_temp}), clearing"
                    )
                    self._clear_optimistic_state()
                else:
                    # API hasn't caught up yet - preserve optimistic state
                    should_preserve_optimistic = True
                    _LOGGER.debug(
                        f"Hot water {self._zone_name}: Preserving optimistic state "
                        f"(expected operation={self._expected_operation}, temp={self._expected_temperature}; "
                        f"API shows operation={api_operation}, temp={api_target_temp})"
                    )
            
            # v1.9.6: Also check time-based window as fallback
            if not should_preserve_optimistic and self._is_within_optimistic_window():
                should_preserve_optimistic = True
                _LOGGER.debug(f"Hot water {self._zone_name}: Preserving optimistic state (within time window)")
            
            if should_preserve_optimistic:
                # Keep optimistic state until API confirms
                if self._expected_operation is not None:
                    self._attr_current_operation = self._expected_operation
                if self._expected_temperature is not None:
                    self._attr_target_temperature = self._expected_temperature
                _LOGGER.debug(
                    f"Hot water {self._zone_name}: Using optimistic state: "
                    f"operation={self._attr_current_operation}, temp={self._attr_target_temperature}"
                )
            else:
                # No optimistic state or confirmed - use API values
                self._attr_current_operation = api_operation
                self._overlay_type = api_overlay_type
                self._attr_target_temperature = api_target_temp
                # Clear any stale optimistic tracking
                if self._optimistic_set_at is not None:
                    self._clear_optimistic_state()
            
            self._attr_available = True
                
        except FileNotFoundError as e:
            _LOGGER.warning(f"Data file not found for {self.name}: {e}")
            self._attr_available = False
        except json.JSONDecodeError as e:
            _LOGGER.warning(f"Invalid JSON for {self.name}: {e}")
            self._attr_available = False
        except Exception as e:
            import traceback
            _LOGGER.error(f"Failed to update {self.name}: {e}\n{traceback.format_exc()}")
            self._attr_available = False

    async def async_set_operation_mode(self, operation_mode: str):
        """Set new operation mode with retry logic (async).
        
        Uses TadoApiClient for non-blocking API calls.
        
        v1.9.6: Added optimistic tracking and proper rollback (parity with climate entities).
        v2.0.1: Added full 3-layer defense for parity with climate entities.
        v2.0.1: Added bootstrap reserve check - blocks action when quota critically low.
        """
        from .api_client import get_async_client
        
        # v2.0.1: Bootstrap Reserve - block action when quota critically low
        await _check_bootstrap_reserve(self.hass, f"hot water {self._zone_name}")
        
        # Store previous state for rollback on failure
        previous_mode = self._attr_current_operation
        previous_overlay = self._overlay_type
        
        # v1.9.6: Optimistic update BEFORE API call
        self._attr_current_operation = operation_mode
        if operation_mode == STATE_AUTO:
            self._overlay_type = None
        elif operation_mode == STATE_HEAT:
            self._overlay_type = "TIMER"
        elif operation_mode == STATE_OFF:
            self._overlay_type = "MANUAL"
        self._optimistic_set_at = time.time()
        
        # v2.0.1: Layer 2 - Sequence number tracking
        get_next_sequence = self.hass.data.get(DOMAIN, {}).get('get_next_sequence')
        if get_next_sequence:
            self._optimistic_sequence = get_next_sequence()
        else:
            self._optimistic_sequence = int(time.time())
        
        # v2.0.1: Layer 3 - Expected state confirmation
        self._expected_operation = operation_mode
        
        # v2.0.1: Layer 1 - Mark entity as fresh to prevent stale data overwrites
        mark_entity_fresh = self.hass.data.get(DOMAIN, {}).get('mark_entity_fresh')
        if mark_entity_fresh:
            await mark_entity_fresh(self.entity_id)
        
        _LOGGER.debug(f"Hot water {self._zone_name}: Set optimistic state: operation={operation_mode}, seq={self._optimistic_sequence}")
        
        self.async_write_ha_state()
        
        success = False
        max_retries = 2  # Initial attempt + 1 retry
        client = get_async_client(self.hass)
        
        for attempt in range(max_retries):
            if operation_mode == STATE_AUTO:
                # AUTO mode: Delete overlay to follow schedule
                success = await client.delete_zone_overlay(self._zone_id)
                if success:
                    _LOGGER.info(f"Resumed schedule for {self._zone_name}")
                    await self._async_trigger_immediate_refresh("hot_water_auto")
                    break
            elif operation_mode == STATE_HEAT:
                # HEAT mode: Turn on with timer
                duration = self._get_timer_duration()
                success = await self._async_set_timer(duration, None)
                if success:
                    await self._async_trigger_immediate_refresh("hot_water_heat")
                    break
            elif operation_mode == STATE_OFF:
                # OFF mode: Turn off with manual overlay
                success = await self._async_turn_off()
                if success:
                    await self._async_trigger_immediate_refresh("hot_water_off")
                    break
            
            # If failed and not last attempt, wait and retry
            if not success and attempt < max_retries - 1:
                _LOGGER.warning(
                    f"Failed to set operation mode to {operation_mode} (attempt {attempt + 1}/{max_retries}), "
                    f"retrying in 5 seconds..."
                )
                await asyncio.sleep(5)
        
        if not success:
            _LOGGER.error(
                f"ROLLBACK: Failed to set operation mode to {operation_mode} after {max_retries} attempts."
            )
            # Rollback to previous state and clear all optimistic tracking
            self._attr_current_operation = previous_mode
            self._overlay_type = previous_overlay
            self._clear_optimistic_state()
            self.async_write_ha_state()
    
    def set_operation_mode(self, operation_mode: str):
        """Set new operation mode (sync wrapper for backward compatibility).
        
        Home Assistant will call async_set_operation_mode() directly.
        This is kept for backward compatibility only.
        """
        # Home Assistant handles async methods automatically
        pass

    
    def _get_timer_duration(self) -> int:
        """Get configured timer duration in minutes (default 60)."""
        try:
            # Try to get from hass.data
            from .const import DOMAIN
            if DOMAIN in self.hass.data and 'config_manager' in self.hass.data[DOMAIN]:
                config_manager = self.hass.data[DOMAIN]['config_manager']
                return config_manager.get_hot_water_timer_duration()
        except Exception as e:
            _LOGGER.debug(f"Failed to get timer duration from config: {e}")
        
        # Default to 60 minutes
        return 60
    
    async def _async_trigger_immediate_refresh(self, reason: str):
        """Trigger immediate refresh after state change (async).
        
        v2.0.1: DRY refactor - delegates to shared async_trigger_immediate_refresh().
        """
        from . import async_trigger_immediate_refresh
        await async_trigger_immediate_refresh(self.hass, self.entity_id, reason)

    async def _async_turn_on(self) -> bool:
        """Turn on hot water (async)."""
        from .api_client import get_async_client
        
        if not self._home_id:
            _LOGGER.error("No home_id configured")
            return False
        
        client = get_async_client(self.hass)
        
        setting = {"type": "HOT_WATER", "power": "ON"}
        termination = {"type": "MANUAL"}
        
        success = await client.set_zone_overlay(self._zone_id, setting, termination)
        if success:
            _LOGGER.info(f"Turned on {self._zone_name}")
            self._attr_current_operation = STATE_HEAT
        return success

    async def _async_turn_off(self) -> bool:
        """Turn off hot water (async)."""
        from .api_client import get_async_client
        
        if not self._home_id:
            _LOGGER.error("No home_id configured for hot water zone")
            return False
        
        client = get_async_client(self.hass)
        
        setting = {"type": "HOT_WATER", "power": "OFF"}
        termination = {"type": "MANUAL"}
        
        success = await client.set_zone_overlay(self._zone_id, setting, termination)
        if success:
            _LOGGER.info(f"Turned off {self._zone_name}")
            self._attr_current_operation = STATE_OFF
        return success

    async def _async_set_timer(self, duration_minutes: int, temperature: float = None) -> bool:
        """Turn on hot water with timer (async)."""
        from .api_client import get_async_client
        
        if not self._home_id:
            _LOGGER.error("No home_id configured for hot water zone")
            return False
        
        client = get_async_client(self.hass)
        
        # Build setting payload
        setting = {"type": "HOT_WATER", "power": "ON"}
        
        # Add temperature if provided (for solar water heater systems)
        if temperature is not None:
            setting["temperature"] = {"celsius": temperature}
        
        termination = {"type": "TIMER", "durationInSeconds": duration_minutes * 60}
        
        success = await client.set_zone_overlay(self._zone_id, setting, termination)
        if success:
            temp_str = f" at {temperature}°C" if temperature is not None else ""
            _LOGGER.info(f"Turned on {self._zone_name} for {duration_minutes} minutes{temp_str}")
            self._attr_current_operation = STATE_HEAT
        return success

    async def async_set_timer(self, duration_minutes: int, temperature: float = None) -> bool:
        """Public async method to set timer (for service calls).
        
        v2.0.1: Added bootstrap reserve check - blocks action when quota critically low.
        """
        # v2.0.1: Bootstrap Reserve - block action when quota critically low
        await _check_bootstrap_reserve(self.hass, f"hot water {self._zone_name}")
        
        success = await self._async_set_timer(duration_minutes, temperature)
        if success:
            await self._async_trigger_immediate_refresh("hot_water_timer")
        return success

    async def async_set_temperature(self, **kwargs) -> None:
        """Set new target temperature (async).
        
        For hot water systems that support temperature control (e.g., hot water tanks).
        
        v1.9.6: Added optimistic tracking and proper rollback (parity with climate entities).
        v2.0.1: Added full 3-layer defense for parity with climate entities.
        v2.0.1: Added bootstrap reserve check - blocks action when quota critically low.
        """
        from .api_client import get_async_client
        
        temperature = kwargs.get("temperature")
        if temperature is None:
            _LOGGER.warning("No temperature provided")
            return
        
        if not self._supports_temperature:
            _LOGGER.warning(f"Hot water zone {self._zone_name} does not support temperature control")
            return
        
        if not self._home_id:
            _LOGGER.error("No home_id configured")
            return
        
        # v2.0.1: Bootstrap Reserve - block action when quota critically low
        await _check_bootstrap_reserve(self.hass, f"hot water {self._zone_name}")
        
        # Store previous state for rollback
        old_temp = self._attr_target_temperature
        old_operation = self._attr_current_operation
        old_overlay = self._overlay_type
        
        # v1.9.6: Optimistic update BEFORE API call
        self._attr_target_temperature = temperature
        self._attr_current_operation = STATE_HEAT
        self._overlay_type = "MANUAL"
        self._optimistic_set_at = time.time()
        
        # v2.0.1: Layer 2 - Sequence number tracking
        get_next_sequence = self.hass.data.get(DOMAIN, {}).get('get_next_sequence')
        if get_next_sequence:
            self._optimistic_sequence = get_next_sequence()
        else:
            self._optimistic_sequence = int(time.time())
        
        # v2.0.1: Layer 3 - Expected state confirmation
        self._expected_operation = STATE_HEAT
        self._expected_temperature = temperature
        
        # v2.0.1: Layer 1 - Mark entity as fresh to prevent stale data overwrites
        mark_entity_fresh = self.hass.data.get(DOMAIN, {}).get('mark_entity_fresh')
        if mark_entity_fresh:
            await mark_entity_fresh(self.entity_id)
        
        _LOGGER.debug(f"Hot water {self._zone_name}: Set optimistic state: temp={temperature}, seq={self._optimistic_sequence}")
        
        self.async_write_ha_state()
        
        client = get_async_client(self.hass)
        
        # Set temperature with manual overlay
        setting = {
            "type": "HOT_WATER",
            "power": "ON",
            "temperature": {"celsius": temperature}
        }
        termination = {"type": "MANUAL"}
        
        api_success = False
        try:
            async with asyncio.timeout(10):
                api_success = await client.set_zone_overlay(self._zone_id, setting, termination)
        except asyncio.TimeoutError:
            _LOGGER.warning(f"TIMEOUT: {self._zone_name} temperature API call timed out")
        except Exception as e:
            _LOGGER.warning(f"ERROR: {self._zone_name} temperature API call failed ({e})")
        
        if api_success:
            _LOGGER.info(f"Set {self._zone_name} temperature to {temperature}°C")
            await self._async_trigger_immediate_refresh("hot_water_temperature")
        else:
            _LOGGER.warning(f"ROLLBACK: {self._zone_name} temperature change failed")
            self._attr_target_temperature = old_temp
            self._attr_current_operation = old_operation
            self._overlay_type = old_overlay
            self._clear_optimistic_state()
            self.async_write_ha_state()
