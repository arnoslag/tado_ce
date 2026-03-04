"""Tado CE Water Heater Platform."""
import asyncio
import json
import logging
import time
from datetime import timedelta
from typing import TYPE_CHECKING

from homeassistant.components.water_heater import (
    WaterHeaterEntity,
    WaterHeaterEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_OFF, UnitOfTemperature
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
from .device_manager import get_zone_device_info
from .format_helpers import format_overlay_type as _format_overlay_type
from .helpers import async_trigger_immediate_refresh

if TYPE_CHECKING:
    from .coordinator import TadoDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)
SCAN_INTERVAL = timedelta(seconds=30)

# Operation modes for hot water
STATE_AUTO = "auto"  # Follow schedule (no overlay)
STATE_HEAT = "heat"  # Timer or manual heating
OPERATION_MODES = [STATE_AUTO, STATE_HEAT, STATE_OFF]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Tado CE water heater from a config entry."""
    _LOGGER.debug("Tado CE water_heater: Setting up...")
    coordinator: TadoDataUpdateCoordinator = entry.runtime_data
    data_loader = coordinator.data_loader
    home_id = coordinator.home_id
    zones_info = await hass.async_add_executor_job(data_loader.load_zones_info_file)

    water_heaters = []

    if zones_info:
        _LOGGER.debug("Tado CE water_heater: Found %s zones", len(zones_info))
        for zone in zones_info:
            zone_id = str(zone.get("id"))
            zone_name = zone.get("name", f"Zone {zone_id}")
            zone_type = zone.get("type")

            if zone_type == "HOT_WATER":
                _LOGGER.debug("Tado CE water_heater: Creating entity for zone %s (%s)", zone_id, zone_name)
                water_heaters.append(TadoWaterHeater(coordinator, zone_id, zone_name, home_id))

    if water_heaters:
        async_add_entities(water_heaters, True)  # noqa: FBT003
        _LOGGER.info("Tado CE water heaters loaded: %s", len(water_heaters))
    else:
        _LOGGER.debug("Tado CE: No hot water zones found")


class TadoWaterHeater(CoordinatorEntity["TadoDataUpdateCoordinator"], WaterHeaterEntity):
    """TadoWaterHeater."""

    _attr_has_entity_name = True


    """Tado CE Water Heater Entity."""

    def __init__(self, coordinator: "TadoDataUpdateCoordinator", zone_id: str, zone_name: str, home_id: str) -> None:
        """Initialize."""
        super().__init__(coordinator)
        self._zone_id = zone_id
        self._zone_name = zone_name
        self._home_id = home_id
        # Convenience alias — used by action_helpers that still accept entry_id
        self._entry_id = coordinator.config_entry.entry_id

        self._attr_name = None
        # Use zone_id for unique_id to maintain entity_id stability across zone name changes
        self._attr_unique_id = f"tado_ce_{home_id}_zone_{zone_id}_water_heater"
        self._attr_temperature_unit = UnitOfTemperature.CELSIUS
        self._attr_min_temp = 30
        self._attr_max_temp = 65
        # Use zone device info instead of hub device info
        self._attr_device_info = get_zone_device_info(zone_id, zone_name, "HOT_WATER", home_id)

        self._attr_current_operation = None
        self._attr_current_temperature = None
        self._attr_target_temperature = None
        self._attr_available = False

        # Supported features - will be updated based on zone capabilities
        self._supports_temperature = False
        self._attr_supported_features = WaterHeaterEntityFeature.OPERATION_MODE
        self._attr_operation_list = OPERATION_MODES

        self._overlay_type = None

        # Optimistic update tracking
        self._optimistic_set_at: float | None = None

        # Layer 2: Sequence number tracking
        self._optimistic_sequence: int | None = None
        # Layer 3: Expected state confirmation
        self._expected_operation: str | None = None
        self._expected_temperature: float | None = None

    def _clear_optimistic_state(self) -> None:
        """Clear all optimistic state tracking."""
        clear_optimistic_state(self)

    def _is_within_optimistic_window(self) -> bool:
        """Check if we're within the optimistic update window."""
        return _is_within_optimistic_window(self.hass, self._optimistic_set_at, entry_id=self._entry_id)

    @property
    def extra_state_attributes(self) -> None:
        """Return extra state attributes."""
        return {
            "overlay_type": _format_overlay_type(self._overlay_type),
            "zone_id": self._zone_id,
        }

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle coordinator data update."""
        self.update()
        self.async_write_ha_state()

    @callback
    def update(self) -> None:  # noqa: C901, PLR0912, PLR0915
        """Update water heater state from JSON file."""
        _LOGGER.debug("TadoWaterHeater.update() called for %s (zone %s)", self._zone_name, self._zone_id)

        # Layer 1 - Skip update if entity is fresh (coordinator-level protection)
        if self.coordinator.is_entity_fresh(self.entity_id):
            _LOGGER.debug("Hot water %s: Skipping update (entity is fresh)", self._zone_name)
            return

        try:
            # Use coordinator cached zones data (async-loaded, no file I/O)
            coord_data = self.coordinator.data or {}
            data = coord_data.get("zones")
            if not data:
                _LOGGER.debug("No zones data for %s (zone %s)", self._zone_name, self._zone_id)
                self._attr_available = False
                return

            # Use 'or {}' pattern for null safety
            zone_states = data.get("zoneStates") or {}
            zone_data = zone_states.get(self._zone_id)

            if not zone_data:
                _LOGGER.debug("No zone data for %s (zone %s)", self._zone_name, self._zone_id)
                self._attr_available = False
                return

            # Check link state - if offline, mark unavailable
            link = zone_data.get("link") or {}
            link_state = link.get("state")
            if link_state != "ONLINE":
                _LOGGER.debug("Zone %s link state: %s", self._zone_name, link_state)
                self._attr_available = False
                return

            _LOGGER.debug("Zone %s link state OK, setting available=True", self._zone_name)
            setting = zone_data.get("setting") or {}
            power = setting.get("power")
            overlay = zone_data.get("overlay")
            api_overlay_type = zone_data.get("overlayType")

            # Read target temperature from setting (for systems that support it)
            temp_data = setting.get("temperature") or {}
            api_target_temp = temp_data.get("celsius")

            # Enable temperature feature if zone supports it
            if api_target_temp is not None and not self._supports_temperature:
                self._supports_temperature = True
                self._attr_supported_features = (
                    WaterHeaterEntityFeature.OPERATION_MODE |
                    WaterHeaterEntityFeature.TARGET_TEMPERATURE
                )
                _LOGGER.debug("Hot water zone %s supports temperature control", self._zone_name)

            # Detect API operation mode based on overlay state
            if not overlay or api_overlay_type is None:
                api_operation = STATE_AUTO
            elif api_overlay_type == "TIMER":
                api_operation = STATE_HEAT
            elif api_overlay_type == "MANUAL":
                api_operation = STATE_OFF if power == "OFF" else STATE_HEAT
            else:
                api_operation = STATE_AUTO

            # Layer 3 - Explicit state confirmation
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
                        "Hot water %s: API confirmed optimistic state (operation=%s, temp=%s), clearing",
                        self._zone_name, api_operation, api_target_temp,
                    )
                    self._clear_optimistic_state()
                else:
                    # API hasn't caught up yet - preserve optimistic state
                    should_preserve_optimistic = True
                    _LOGGER.debug(
                        "Hot water %s: Preserving optimistic state "
                        "(expected operation=%s, temp=%s; API shows operation=%s, temp=%s)",
                        self._zone_name, self._expected_operation,
                        self._expected_temperature, api_operation, api_target_temp,
                    )

            # Also check time-based window as fallback
            if not should_preserve_optimistic and self._is_within_optimistic_window():
                should_preserve_optimistic = True
                _LOGGER.debug("Hot water %s: Preserving optimistic state (within time window)", self._zone_name)

            if should_preserve_optimistic:
                # Keep optimistic state until API confirms
                if self._expected_operation is not None:
                    self._attr_current_operation = self._expected_operation
                if self._expected_temperature is not None:
                    self._attr_target_temperature = self._expected_temperature
                _LOGGER.debug(
                    "Hot water %s: Using optimistic state: operation=%s, temp=%s",
                    self._zone_name, self._attr_current_operation, self._attr_target_temperature,
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
            _LOGGER.warning("Data file not found for %s: %s", self.name, e)
            self._attr_available = False
        except json.JSONDecodeError as e:
            _LOGGER.warning("Invalid JSON for %s: %s", self.name, e)
            self._attr_available = False
        except Exception as e:
            _LOGGER.exception("Failed to update %s: %s", self.name, e)  # noqa: TRY401
            self._attr_available = False

    async def async_set_operation_mode(self, operation_mode: str) -> None:  # noqa: C901
        """Set new operation mode with retry logic (async)."""
        # Bootstrap Reserve - block action when quota critically low
        await _check_bootstrap_reserve(self.hass, f"hot water {self._zone_name}", entry_id=self._entry_id)

        # Store previous state for rollback on failure
        previous_mode = self._attr_current_operation
        previous_overlay = self._overlay_type

        # Optimistic update BEFORE API call
        self._attr_current_operation = operation_mode
        if operation_mode == STATE_AUTO:
            self._overlay_type = None
        elif operation_mode == STATE_HEAT:
            self._overlay_type = "TIMER"
        elif operation_mode == STATE_OFF:
            self._overlay_type = "MANUAL"
        self._optimistic_set_at = time.time()

        # Layer 2 - Sequence number tracking
        self._optimistic_sequence = self.coordinator.get_next_sequence()

        # Layer 3 - Expected state confirmation
        self._expected_operation = operation_mode

        # Layer 1 - Mark entity as fresh to prevent stale data overwrites
        await self.coordinator.mark_entity_fresh(self.entity_id)

        _LOGGER.debug(
            "Hot water %s: Set optimistic state: operation=%s, seq=%s",
            self._zone_name, operation_mode, self._optimistic_sequence,
        )

        self.async_write_ha_state()

        success = False
        max_retries = 2  # Initial attempt + 1 retry
        client = self.coordinator.api_client

        for attempt in range(max_retries):
            if operation_mode == STATE_AUTO:
                # AUTO mode: Delete overlay to follow schedule
                success = await client.delete_zone_overlay(self._zone_id)
                if success:
                    _LOGGER.info("Resumed schedule for %s", self._zone_name)
                    await async_trigger_immediate_refresh(self.hass, self.entity_id, "hot_water_auto")
                    break
            elif operation_mode == STATE_HEAT:
                # HEAT mode: Turn on with timer
                duration = self._get_timer_duration()
                success = await self._async_set_timer(duration, None)
                if success:
                    await async_trigger_immediate_refresh(self.hass, self.entity_id, "hot_water_heat")
                    break
            elif operation_mode == STATE_OFF:
                # OFF mode: Turn off with manual overlay
                success = await self._async_turn_off()
                if success:
                    await async_trigger_immediate_refresh(self.hass, self.entity_id, "hot_water_off")
                    break

            # If failed and not last attempt, wait and retry
            if not success and attempt < max_retries - 1:
                _LOGGER.warning(
                    "Failed to set operation mode to %s (attempt %s/%s), retrying in 5 seconds...",
                    operation_mode, attempt + 1, max_retries,
                )
                await asyncio.sleep(5)

        if not success:
            _LOGGER.error(
                "ROLLBACK: Failed to set operation mode to %s after %s attempts.",
                operation_mode, max_retries,
            )
            # Rollback to previous state and clear all optimistic tracking
            self._attr_current_operation = previous_mode
            self._overlay_type = previous_overlay
            self._clear_optimistic_state()
            self.async_write_ha_state()

    def set_operation_mode(self, operation_mode: str) -> None:
        """Set new operation mode (sync wrapper for backward compatibility).

        Home Assistant will call async_set_operation_mode() directly.
        This is kept for backward compatibility only.
        """
        # Home Assistant handles async methods automatically


    def _get_timer_duration(self) -> int:
        """Get configured timer duration in minutes (default 60)."""
        try:
            config_manager = self.coordinator.config_manager
            if config_manager:
                return config_manager.get_hot_water_timer_duration()
        except Exception as e:  # noqa: BLE001
            _LOGGER.debug("Failed to get timer duration from config: %s", e)

        # Default to 60 minutes
        return 60


    async def _async_turn_on(self) -> bool:
        """Turn on hot water (async)."""
        if not self._home_id:
            _LOGGER.error("No home_id configured")
            return False

        client = self.coordinator.api_client

        setting = {"type": "HOT_WATER", "power": "ON"}
        termination = {"type": "MANUAL"}

        success = await client.set_zone_overlay(self._zone_id, setting, termination)
        if success:
            _LOGGER.info("Turned on %s", self._zone_name)
            self._attr_current_operation = STATE_HEAT
        return success

    async def _async_turn_off(self) -> bool:
        """Turn off hot water (async)."""
        if not self._home_id:
            _LOGGER.error("No home_id configured for hot water zone")
            return False

        client = self.coordinator.api_client

        setting = {"type": "HOT_WATER", "power": "OFF"}
        termination = {"type": "MANUAL"}

        success = await client.set_zone_overlay(self._zone_id, setting, termination)
        if success:
            _LOGGER.info("Turned off %s", self._zone_name)
            self._attr_current_operation = STATE_OFF
        return success

    async def _async_set_timer(self, duration_minutes: int, temperature: float | None = None) -> bool:
        """Turn on hot water with timer (async)."""
        if not self._home_id:
            _LOGGER.error("No home_id configured for hot water zone")
            return False

        client = self.coordinator.api_client

        # Build setting payload
        setting = {"type": "HOT_WATER", "power": "ON"}

        # Add temperature if provided (for solar water heater systems)
        if temperature is not None:
            setting["temperature"] = {"celsius": temperature}

        termination = {"type": "TIMER", "durationInSeconds": duration_minutes * 60}

        success = await client.set_zone_overlay(self._zone_id, setting, termination)
        if success:
            temp_str = f" at {temperature}°C" if temperature is not None else ""
            _LOGGER.info("Turned on %s for %s minutes%s", self._zone_name, duration_minutes, temp_str)
            self._attr_current_operation = STATE_HEAT
        return success

    async def async_set_timer(self, duration_minutes: int, temperature: float | None = None) -> bool:
        """Public async method to set timer (for service calls)."""
        # Bootstrap Reserve - block action when quota critically low
        await _check_bootstrap_reserve(self.hass, f"hot water {self._zone_name}", entry_id=self._entry_id)

        success = await self._async_set_timer(duration_minutes, temperature)
        if success:
            await async_trigger_immediate_refresh(self.hass, self.entity_id, "hot_water_timer")
        return success

    async def async_set_temperature(self, **kwargs) -> None:  # noqa: ANN003
        """Set new target temperature (async)."""
        temperature = kwargs.get("temperature")
        if temperature is None:
            _LOGGER.warning("No temperature provided")
            return

        if not self._supports_temperature:
            _LOGGER.warning("Hot water zone %s does not support temperature control", self._zone_name)
            return

        if not self._home_id:
            _LOGGER.error("No home_id configured")
            return

        # Bootstrap Reserve - block action when quota critically low
        await _check_bootstrap_reserve(self.hass, f"hot water {self._zone_name}", entry_id=self._entry_id)

        # Store previous state for rollback
        old_temp = self._attr_target_temperature
        old_operation = self._attr_current_operation
        old_overlay = self._overlay_type

        # Optimistic update BEFORE API call
        self._attr_target_temperature = temperature
        self._attr_current_operation = STATE_HEAT
        self._overlay_type = "MANUAL"
        self._optimistic_set_at = time.time()

        # Layer 2 - Sequence number tracking
        self._optimistic_sequence = self.coordinator.get_next_sequence()

        # Layer 3 - Expected state confirmation
        self._expected_operation = STATE_HEAT
        self._expected_temperature = temperature

        # Layer 1 - Mark entity as fresh to prevent stale data overwrites
        await self.coordinator.mark_entity_fresh(self.entity_id)

        _LOGGER.debug(
            "Hot water %s: Set optimistic state: temp=%s, seq=%s",
            self._zone_name, temperature, self._optimistic_sequence,
        )

        self.async_write_ha_state()

        client = self.coordinator.api_client

        # Set temperature with manual overlay
        setting = {
            "type": "HOT_WATER",
            "power": "ON",
            "temperature": {"celsius": temperature},
        }
        termination = {"type": "MANUAL"}

        api_success = False
        try:
            async with asyncio.timeout(10):
                api_success = await client.set_zone_overlay(self._zone_id, setting, termination)
        except TimeoutError:
            _LOGGER.warning("TIMEOUT: %s temperature API call timed out", self._zone_name)
        except Exception as e:  # noqa: BLE001
            _LOGGER.warning("ERROR: %s temperature API call failed (%s)", self._zone_name, e)

        if api_success:
            _LOGGER.info("Set %s temperature to %s°C", self._zone_name, temperature)
            await async_trigger_immediate_refresh(self.hass, self.entity_id, "hot_water_temperature")
        else:
            _LOGGER.warning("ROLLBACK: %s temperature change failed", self._zone_name)
            self._attr_target_temperature = old_temp
            self._attr_current_operation = old_operation
            self._overlay_type = old_overlay
            self._clear_optimistic_state()
            self.async_write_ha_state()
