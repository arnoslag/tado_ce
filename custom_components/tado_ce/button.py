"""Tado CE Button Platform.

Uses entry.runtime_data (coordinator) for setup, stores coordinator
reference for runtime access.
"""
import asyncio
import logging
from typing import TYPE_CHECKING

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .action_helpers import check_bootstrap_reserve as _check_bootstrap_reserve
from .const import DOMAIN
from .device_manager import get_hub_device_info, get_zone_device_info
from .helpers import async_trigger_immediate_refresh

if TYPE_CHECKING:
    from .coordinator import TadoDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)

# Default timer preset durations (in minutes)
DEFAULT_TIMER_PRESETS = [30, 60, 90]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Tado CE buttons from a config entry."""
    _LOGGER.debug("Tado CE button: Setting up...")
    coordinator: TadoDataUpdateCoordinator = entry.runtime_data
    data_loader = coordinator.data_loader
    home_id = coordinator.home_id
    zones_info = await hass.async_add_executor_job(data_loader.load_zones_info_file)

    # Get config manager to check feature toggles
    config_manager = coordinator.config_manager
    schedule_calendar_enabled = config_manager.get_schedule_calendar_enabled() if config_manager else False
    boost_buttons_enabled = config_manager.get_boost_buttons_enabled() if config_manager else True

    buttons = []

    # Add Resume All Schedules button (hub-level)
    buttons.append(TadoResumeAllSchedulesButton(coordinator, home_id))

    # Add Refresh AC Capabilities button (hub-level) - only if there are AC zones
    has_ac_zones = any(z.get("type") == "AIR_CONDITIONING" for z in (zones_info or []))
    if has_ac_zones:
        buttons.append(TadoRefreshACCapabilitiesButton(coordinator, home_id))

    if zones_info:
        for zone in zones_info:
            zone_id = str(zone.get("id"))
            zone_name = zone.get("name", f"Zone {zone_id}")
            zone_type = zone.get("type")

            # Create timer preset buttons for hot water zones
            if zone_type == "HOT_WATER":
                for duration in DEFAULT_TIMER_PRESETS:
                    buttons.append(  # noqa: PERF401
                        TadoWaterHeaterTimerButton(coordinator, zone_id, zone_name, duration, home_id),
                    )

            # Create boost buttons for heating zones (controlled by boost_buttons_enabled)
            if zone_type == "HEATING" and boost_buttons_enabled:
                # Boost button (official Tado-style: max temp for 30 min)
                buttons.append(
                    TadoBoostButton(coordinator, zone_id, zone_name, home_id),
                )
                # Smart Boost button (calculated duration based on heating rate)
                buttons.append(
                    TadoSmartBoostButton(coordinator, zone_id, zone_name, home_id),
                )

            # Create refresh schedule button for heating zones (only if calendar enabled)
            if zone_type == "HEATING" and schedule_calendar_enabled:
                buttons.append(
                    TadoRefreshScheduleButton(coordinator, zone_id, zone_name, home_id),
                )

    if buttons:
        async_add_entities(buttons, True)  # noqa: FBT003
        _LOGGER.info("Tado CE buttons loaded: %s", len(buttons))
    else:
        _LOGGER.info("Tado CE: No buttons to create")


class TadoResumeAllSchedulesButton(ButtonEntity):
    """TadoResumeAllSchedulesButton."""

    _attr_has_entity_name = True


    """Button to resume schedules for all zones (delete all overlays)."""

    def __init__(self, coordinator: "TadoDataUpdateCoordinator", home_id: str) -> None:
        """Initialize the button."""
        self._coordinator = coordinator
        # Convenience alias — used by action_helpers that still accept entry_id
        self._entry_id = coordinator.config_entry.entry_id

        self._attr_name = "[CE] Resume All"
        self.entity_id = "button.tado_ce_resume_all_schedules"
        self._attr_unique_id = f"tado_ce_{home_id}_resume_all"
        self._attr_device_info = get_hub_device_info(home_id)
        self._attr_icon = "mdi:calendar-refresh"

    async def async_press(self) -> None:
        """Handle button press - resume schedules for all zones.

        Added bootstrap reserve check - blocks action when quota critically low.
        DRY refactor - uses shared async_trigger_immediate_refresh().
        """
        # Bootstrap Reserve - block action when quota critically low
        await _check_bootstrap_reserve(self.hass, "Immediate Refresh", entry_id=self._entry_id)

        _LOGGER.info("Resume All Schedules button pressed")

        client = self._coordinator.api_client
        zones_info = await self.hass.async_add_executor_job(self._coordinator.data_loader.load_zones_info_file)

        if not zones_info:
            _LOGGER.warning("No zones found to resume schedules")
            return

        success_count = 0
        fail_count = 0

        for zone in zones_info:
            zone_id = str(zone.get("id"))
            zone_name = zone.get("name", f"Zone {zone_id}")

            try:
                if await client.delete_zone_overlay(zone_id):
                    _LOGGER.debug("Resumed schedule for %s (zone %s)", zone_name, zone_id)
                    success_count += 1
                else:
                    # API returned False - might mean no overlay existed
                    _LOGGER.debug("No overlay to delete for %s (zone %s)", zone_name, zone_id)
                    success_count += 1  # Still count as success
            except Exception as e:
                _LOGGER.exception("Failed to resume schedule for %s: %s", zone_name, e)  # noqa: TRY401
                fail_count += 1

        if fail_count == 0:
            _LOGGER.info("Resume All Schedules complete: %s zones processed", success_count)
        else:
            _LOGGER.warning("Resume All Schedules: %s succeeded, %s failed", success_count, fail_count)

        # Trigger immediate refresh to update all entities
        await async_trigger_immediate_refresh(
            self.hass, self.entity_id, "resume_all_schedules", force=True, skip_debounce=True,
        )


class TadoRefreshACCapabilitiesButton(ButtonEntity):
    """TadoRefreshACCapabilitiesButton."""

    _attr_has_entity_name = True


    """Button to refresh AC capabilities cache."""

    def __init__(self, coordinator: "TadoDataUpdateCoordinator", home_id: str) -> None:
        """Initialize the button."""
        self._coordinator = coordinator
        # Convenience alias — used by action_helpers that still accept entry_id
        self._entry_id = coordinator.config_entry.entry_id

        self._attr_name = "[CE] Refresh AC"
        self.entity_id = "button.tado_ce_refresh_ac_capabilities"
        self._attr_unique_id = f"tado_ce_{home_id}_refresh_ac"
        self._attr_device_info = get_hub_device_info(home_id)
        self._attr_entity_category = EntityCategory.CONFIG
        self._attr_icon = "mdi:air-conditioner"

    async def async_press(self) -> None:
        """Handle button press - refresh AC capabilities from API."""
        from .const import get_data_file  # noqa: PLC0415

        _LOGGER.info("Refresh AC Capabilities button pressed")

        # Use home-aware file path (TECH-2)
        home_id = self._coordinator.home_id
        ac_caps_file = get_data_file("ac_capabilities", home_id)

        # Delete existing cache to force re-fetch
        def _delete_cache() -> None:
            if ac_caps_file.exists():
                ac_caps_file.unlink()
                _LOGGER.debug("Deleted AC capabilities cache")

        await self.hass.async_add_executor_job(_delete_cache)

        # Fetch fresh capabilities
        client = self._coordinator.api_client
        zones_info = await self.hass.async_add_executor_job(self._coordinator.data_loader.load_zones_info_file)

        if not zones_info:
            _LOGGER.warning("No zones found")
            return

        # Call the sync method to re-fetch AC capabilities
        try:
            await client._sync_ac_capabilities(zones_info)  # noqa: SLF001
            _LOGGER.info("AC capabilities refreshed successfully")

            # Trigger coordinator refresh so AC entities
            # pick up new capabilities via _handle_coordinator_update()
            await self._coordinator.async_request_refresh()
            _LOGGER.debug("Triggered coordinator refresh for AC capabilities")
        except Exception as e:
            _LOGGER.exception("Failed to refresh AC capabilities: %s", e)  # noqa: TRY401


class TadoWaterHeaterTimerButton(ButtonEntity):
    """TadoWaterHeaterTimerButton."""

    _attr_has_entity_name = True


    """Button to set water heater timer with preset duration."""

    def __init__(self, coordinator: "TadoDataUpdateCoordinator", zone_id: str, zone_name: str, duration: int, home_id: str) -> None:  # noqa: E501, PLR0913
        """Initialize the button.

        Args:
            coordinator: Data update coordinator
            zone_id: Zone ID
            zone_name: Zone name
            duration: Timer duration in minutes
            home_id: Tado home ID

        """
        self._coordinator = coordinator
        # Convenience alias — used by action_helpers that still accept entry_id
        self._entry_id = coordinator.config_entry.entry_id
        self._zone_id = zone_id
        self._zone_name = zone_name
        self._duration = duration

        self._attr_name = "[CE] {duration}min Timer"
        self._attr_unique_id = f"tado_ce_{home_id}_zone_{zone_id}_timer_{duration}min"
        self._attr_device_info = get_zone_device_info(zone_id, zone_name, "HOT_WATER", home_id)
        self._attr_entity_category = EntityCategory.CONFIG
        self._attr_icon = "mdi:timer"

    async def async_press(self) -> None:
        """Handle button press - set water heater timer with preset duration."""
        from homeassistant.exceptions import HomeAssistantError  # noqa: PLC0415
        from homeassistant.helpers import entity_registry as er  # noqa: PLC0415

        _LOGGER.info("Timer button pressed - %s for %s minutes", self._zone_name, self._duration)

        # Find water heater entity by unique_id (more reliable than constructing from name)
        # This handles cases where HA adds suffix like _2 due to entity_id conflicts
        registry = er.async_get(self.hass)
        unique_id = f"tado_ce_zone_{self._zone_id}_water_heater"
        entry = registry.async_get_entity_id("water_heater", DOMAIN, unique_id)

        if entry:  # noqa: SIM108
            water_heater_entity_id = entry
        else:
            # Fallback to name-based construction for backwards compatibility
            water_heater_entity_id = f"water_heater.{self._zone_name.lower().replace(' ', '_')}"

        # Verify entity exists before calling service
        if not self.hass.states.get(water_heater_entity_id):
            error_msg = f"Water heater entity not found: {water_heater_entity_id}"
            _LOGGER.error("Timer button failed - %s", error_msg)
            raise HomeAssistantError(error_msg)

        # Convert duration (minutes) to HH:MM:SS format
        hours = self._duration // 60
        minutes = self._duration % 60
        time_period = f"{hours:02d}:{minutes:02d}:00"

        _LOGGER.info("Calling set_water_heater_timer for %s with %s", water_heater_entity_id, time_period)

        try:
            # Call the set_water_heater_timer service
            await self.hass.services.async_call(
                "tado_ce",
                "set_water_heater_timer",
                {
                    "entity_id": water_heater_entity_id,
                    "time_period": time_period,
                },
                blocking=True,
            )

            _LOGGER.info("Timer set successfully - %s for %s minutes", self._zone_name, self._duration)

        except HomeAssistantError:
            # Re-raise HomeAssistantError as-is (already has good error message)
            raise
        except Exception as e:
            # Catch any other unexpected errors and provide detailed message
            error_type = type(e).__name__
            error_msg = f"Failed to set {self._duration}min timer for {self._zone_name}: {error_type}: {e!s}"
            _LOGGER.exception("Timer button failed - %s", error_msg)
            raise HomeAssistantError(error_msg) from e


class TadoRefreshScheduleButton(ButtonEntity):
    """TadoRefreshScheduleButton."""

    _attr_has_entity_name = True


    """Button to refresh schedule for a specific zone."""

    def __init__(self, coordinator: "TadoDataUpdateCoordinator", zone_id: str, zone_name: str, home_id: str) -> None:
        """Initialize the button.

        Args:
            coordinator: Data update coordinator
            zone_id: Zone ID
            zone_name: Zone name
            home_id: Tado home ID

        """
        self._coordinator = coordinator
        # Convenience alias — used by action_helpers that still accept entry_id
        self._entry_id = coordinator.config_entry.entry_id
        self._zone_id = zone_id
        self._zone_name = zone_name

        self._attr_name = "[CE] Refresh Schedule"
        self._attr_unique_id = f"tado_ce_{home_id}_zone_{zone_id}_refresh_schedule"
        self._attr_device_info = get_zone_device_info(zone_id, zone_name, "HEATING", home_id)
        # No entity_category = Controls section (action button, not config)
        self._attr_icon = "mdi:calendar-refresh"

    async def async_press(self) -> None:
        """Handle button press - refresh schedule for this zone."""
        import json  # noqa: PLC0415

        from .calendar import _get_schedules_file  # noqa: PLC0415
        from .const import DATA_DIR  # noqa: PLC0415

        _LOGGER.info("Refresh Schedule button pressed for %s (zone %s)", self._zone_name, self._zone_id)

        client = self._coordinator.api_client

        try:
            # Fetch fresh schedule from API
            schedule_data = await client.get_zone_schedule(self._zone_id)

            if not schedule_data:
                _LOGGER.warning("No schedule data returned for %s", self._zone_name)
                return

            # Get per-home schedules file path
            home_id = self._coordinator.home_id
            schedules_file = _get_schedules_file(home_id)

            # Load existing schedules
            def _load_schedules() -> None:
                if schedules_file.exists():
                    with open(schedules_file) as f:  # noqa: PTH123
                        return json.load(f)
                return {}

            schedules = await self.hass.async_add_executor_job(_load_schedules)

            # Update this zone's schedule
            schedules[self._zone_id] = {
                "name": self._zone_name,
                "type": schedule_data.get("type", "ONE_DAY"),
                # Tado API may return null for existing keys; 'or {}' handles None correctly
                "blocks": schedule_data.get("blocks") or {},
            }

            # Save back to file using atomic write
            def _save_schedules() -> None:
                import shutil  # noqa: PLC0415
                import tempfile  # noqa: PLC0415

                DATA_DIR.mkdir(parents=True, exist_ok=True)
                # Atomic write: write to temp file then move
                with tempfile.NamedTemporaryFile(
                    mode="w", dir=DATA_DIR, delete=False, suffix=".tmp",
                ) as tmp:
                    json.dump(schedules, tmp, indent=2)
                    temp_path = tmp.name
                shutil.move(temp_path, schedules_file)

            await self.hass.async_add_executor_job(_save_schedules)

            _LOGGER.info("Schedule refreshed for %s", self._zone_name)

            # Fire event to notify calendar entity to update
            self.hass.bus.async_fire(
                f"{DOMAIN}_schedule_updated",
                {"zone_id": self._zone_id, "zone_name": self._zone_name},
            )

        except Exception as e:
            _LOGGER.exception("Failed to refresh schedule for %s: %s", self._zone_name, e)  # noqa: TRY401


# Boost button constants
BOOST_TEMPERATURE = 25.0  # Maximum temperature for boost
BOOST_DURATION_MINUTES = 30  # Default boost duration

# Smart Boost constants
SMART_BOOST_MIN_DURATION = 15  # Minimum duration in minutes
SMART_BOOST_MAX_DURATION = 180  # Maximum duration in minutes (3 hours)
SMART_BOOST_DEFAULT_RATE = 1.0  # Default heating rate if unknown (°C/h)


class TadoBoostButton(ButtonEntity):
    """TadoBoostButton."""

    _attr_has_entity_name = True


    """Button to boost heating to maximum temperature for 30 minutes.

    Mimics official Tado app boost functionality:
    - Sets zone to maximum temperature (25°C)
    - Timer for 30 minutes
    - Automatically resumes schedule after timer expires
    """

    def __init__(self, coordinator: "TadoDataUpdateCoordinator", zone_id: str, zone_name: str, home_id: str) -> None:
        """Initialize the button."""
        self._coordinator = coordinator
        # Convenience alias — used by action_helpers that still accept entry_id
        self._entry_id = coordinator.config_entry.entry_id
        self._zone_id = zone_id
        self._zone_name = zone_name

        self._attr_name = "[CE] Boost"
        self._attr_unique_id = f"tado_ce_{home_id}_zone_{zone_id}_boost"
        self._attr_device_info = get_zone_device_info(zone_id, zone_name, "HEATING", home_id)
        self._attr_icon = "mdi:fire"

    async def async_press(self) -> None:
        """Handle button press - boost heating to max for 30 minutes.

        Added bootstrap reserve check - blocks action when quota critically low.
        DRY refactor - uses shared async_trigger_immediate_refresh().
        """
        # Bootstrap Reserve - block action when quota critically low
        await _check_bootstrap_reserve(self.hass, f"Boost {self._zone_name}", entry_id=self._entry_id)

        _LOGGER.info("Boost button pressed for %s", self._zone_name)

        client = self._coordinator.api_client

        setting = {
            "type": "HEATING",
            "power": "ON",
            "temperature": {"celsius": BOOST_TEMPERATURE},
        }
        termination = {
            "type": "TIMER",
            "durationInSeconds": BOOST_DURATION_MINUTES * 60,
        }

        api_success = False
        try:
            async with asyncio.timeout(10):
                api_success = await client.set_zone_overlay(self._zone_id, setting, termination)
        except TimeoutError:
            _LOGGER.warning("Boost TIMEOUT: %s API call timed out", self._zone_name)
        except Exception as e:
            _LOGGER.exception("Boost ERROR: %s API call failed (%s)", self._zone_name, e)  # noqa: TRY401

        if api_success:
            _LOGGER.info(
                "Boost activated: %s set to %s°C for %s minutes",
                self._zone_name, BOOST_TEMPERATURE, BOOST_DURATION_MINUTES,
            )
            # Trigger immediate refresh
            await async_trigger_immediate_refresh(self.hass, self.entity_id, "boost_activated")
        else:
            _LOGGER.error("Boost failed for %s", self._zone_name)


class TadoSmartBoostButton(ButtonEntity):
    """TadoSmartBoostButton."""

    _attr_has_entity_name = True


    """Button to smart boost heating with calculated duration.

    Uses heating rate sensor to calculate optimal boost duration:
    - Target: Schedule's next target temperature (or current + 3°C if unavailable)
    - Duration: (target - current) / heating_rate
    - Capped between 15 minutes and 3 hours
    """

    def __init__(self, coordinator: "TadoDataUpdateCoordinator", zone_id: str, zone_name: str, home_id: str) -> None:
        """Initialize the button."""
        self._coordinator = coordinator
        # Convenience alias — used by action_helpers that still accept entry_id
        self._entry_id = coordinator.config_entry.entry_id
        self._zone_id = zone_id
        self._zone_name = zone_name

        self._attr_name = "[CE] Smart Boost"
        self._attr_unique_id = f"tado_ce_{home_id}_zone_{zone_id}_smart_boost"
        self._attr_device_info = get_zone_device_info(zone_id, zone_name, "HEATING", home_id)
        self._attr_icon = "mdi:fire-alert"

    def _get_climate_entity_id(self) -> str | None:
        """Get the climate entity ID for this zone.

        Uses entity registry lookup for reliability, with name-based fallback.
        This handles cases where HA adds suffix (e.g., _2) due to entity_id conflicts.

        Returns:
            Climate entity ID, or None if not found

        """
        from homeassistant.helpers import entity_registry as er  # noqa: PLC0415

        # Strategy 1: Entity registry lookup by unique_id (most reliable)
        registry = er.async_get(self.hass)
        unique_id = f"tado_ce_zone_{self._zone_id}_climate"
        entry = registry.async_get_entity_id("climate", DOMAIN, unique_id)

        if entry:
            return entry

        # Strategy 2: Fallback to name-based construction for backwards compatibility
        return f"climate.{self._zone_name.lower().replace(' ', '_')}"

    def _get_heating_rate(self) -> float:
        """Get heating rate with fallback chain.

        Priority:
        1. HeatingCycleCoordinator (°C/min → convert to °C/h)
        2. SmartComfortManager (°C/h)
        3. Default rate

        Returns:
            Heating rate in °C/h

        """
        # Strategy 1: HeatingCycleCoordinator (most accurate)
        heating_cycle_coordinator = self._coordinator.heating_cycle_coordinator
        if heating_cycle_coordinator:
            zone_data = heating_cycle_coordinator.get_zone_data(self._zone_id)
            if zone_data and zone_data.get("heating_rate") is not None:
                # HeatingCycleCoordinator rate is in °C/min, convert to °C/h
                rate = zone_data.get("heating_rate") * 60
                if rate > 0.1:  # noqa: PLR2004
                    _LOGGER.debug("Smart Boost: Using HeatingCycleCoordinator rate %.2f°C/h", rate)
                    return rate

        # Strategy 2: SmartComfortManager
        smart_comfort_manager = self._coordinator.smart_comfort_manager
        if smart_comfort_manager:
            rate = smart_comfort_manager.get_heating_rate(self._zone_id)
            if rate is not None and rate > 0.1:  # noqa: PLR2004
                _LOGGER.debug("Smart Boost: Using SmartComfort rate %.2f°C/h", rate)
                return rate

        # Strategy 3: Default
        _LOGGER.debug("Smart Boost: Using default rate %s°C/h", SMART_BOOST_DEFAULT_RATE)
        return SMART_BOOST_DEFAULT_RATE

    async def async_press(self) -> None:
        """Handle button press - smart boost with calculated duration.

        Added bootstrap reserve check - blocks action when quota critically low.
        DRY refactor - uses shared async_trigger_immediate_refresh().
        """
        # Bootstrap Reserve - block action when quota critically low
        await _check_bootstrap_reserve(self.hass, f"Smart Boost {self._zone_name}", entry_id=self._entry_id)

        _LOGGER.info("Smart Boost button pressed for %s", self._zone_name)

        # Get current temperature from climate entity
        climate_entity_id = self._get_climate_entity_id()
        climate_state = self.hass.states.get(climate_entity_id)

        if not climate_state:
            _LOGGER.error("Smart Boost: Climate entity not found: %s", climate_entity_id)
            return

        current_temp = climate_state.attributes.get("current_temperature")
        if current_temp is None:
            _LOGGER.error("Smart Boost: No current temperature for %s", self._zone_name)
            return

        # Get target temperature (schedule target or current + 3°C)
        target_temp = climate_state.attributes.get("temperature")
        if target_temp is None or target_temp <= current_temp:
            # No schedule target or already at/above target, use current + 3°C
            target_temp = min(current_temp + 3.0, 25.0)
            _LOGGER.debug("Smart Boost: Using default target %s°C (current + 3)", target_temp)

        # Get heating rate using fallback chain
        heating_rate = self._get_heating_rate()

        # Calculate duration: (target - current) / rate * 60 minutes
        temp_diff = target_temp - current_temp
        if temp_diff <= 0:
            _LOGGER.info("Smart Boost: Already at or above target (%s°C >= %s°C)", current_temp, target_temp)
            return

        duration_hours = temp_diff / heating_rate
        duration_minutes = int(duration_hours * 60)

        # Apply caps
        duration_minutes = max(SMART_BOOST_MIN_DURATION, min(duration_minutes, SMART_BOOST_MAX_DURATION))

        _LOGGER.info(
            "Smart Boost calculation: %s°C → %s°C, rate=%s°C/h, duration=%smin",
            current_temp, target_temp, heating_rate, duration_minutes,
        )

        # Set the overlay
        client = self._coordinator.api_client

        setting = {
            "type": "HEATING",
            "power": "ON",
            "temperature": {"celsius": target_temp},
        }
        termination = {
            "type": "TIMER",
            "durationInSeconds": duration_minutes * 60,
        }

        api_success = False
        try:
            async with asyncio.timeout(10):
                api_success = await client.set_zone_overlay(self._zone_id, setting, termination)
        except TimeoutError:
            _LOGGER.warning("Smart Boost TIMEOUT: %s API call timed out", self._zone_name)
        except Exception as e:
            _LOGGER.exception("Smart Boost ERROR: %s API call failed (%s)", self._zone_name, e)  # noqa: TRY401

        if api_success:
            _LOGGER.info(
                "Smart Boost activated: %s set to %s°C for %s minutes (rate: %s°C/h)",
                self._zone_name, target_temp, duration_minutes, heating_rate,
            )
            # Trigger immediate refresh
            await async_trigger_immediate_refresh(self.hass, self.entity_id, "smart_boost_activated")
        else:
            _LOGGER.error("Smart Boost failed for %s", self._zone_name)
