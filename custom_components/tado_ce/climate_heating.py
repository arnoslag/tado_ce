"""Tado CE Heating Climate Entity — TRV/thermostat control, timer, overlay."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING, Any

from homeassistant.components.climate import ATTR_HVAC_MODE, ClimateEntity  # type: ignore[attr-defined]
from homeassistant.components.climate.const import (
    PRESET_AWAY,
    PRESET_HOME,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import CALLBACK_TYPE, Event, EventStateChangedData, callback
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .action_helpers import (
    check_bootstrap_reserve as _check_bootstrap_reserve,
)
from .action_helpers import (
    record_smart_comfort_data as _record_smart_comfort_data,
)
from .climate_helpers import (
    api_call_with_rollback,
    read_external_sensor,
    update_offset,
    update_preset_mode,
)
from .device_manager import get_zone_device_info
from .entity_registry import ENTITY_REGISTRY
from .format_helpers import (
    format_overlay_type as _format_overlay_type,
)
from .helpers import (
    async_trigger_immediate_refresh,
    build_timer_termination,
    get_zone_overlay_termination,
)
from .optimistic_helpers import (
    clear_optimistic_state,
    resolve_optimistic_vs_api,
    set_optimistic_state,
)

if TYPE_CHECKING:
    from .coordinator import TadoDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)


class TadoClimate(CoordinatorEntity["TadoDataUpdateCoordinator"], ClimateEntity, RestoreEntity):
    """Tado CE Heating Climate Entity."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: TadoDataUpdateCoordinator, zone_id: str, zone_name: str, home_id: str) -> None:
        """Initialize."""
        super().__init__(coordinator)
        self._zone_id = zone_id
        self._zone_name = zone_name
        self._home_id = home_id
        self._entry_id = coordinator.config_entry.entry_id

        _meta = ENTITY_REGISTRY["climate_heating"]
        self._attr_name = None
        self._attr_translation_key = _meta.translation_key
        # Use zone_id for unique_id to maintain entity_id stability across zone name changes
        self._attr_unique_id = f"tado_ce_{home_id}_{_meta.unique_id_suffix.format(zone_id=zone_id)}"
        self._attr_temperature_unit = UnitOfTemperature.CELSIUS
        self._attr_device_info = get_zone_device_info(zone_id, zone_name, "HEATING", home_id)
        self._attr_supported_features = (
            ClimateEntityFeature.TARGET_TEMPERATURE
            | ClimateEntityFeature.TURN_OFF
            | ClimateEntityFeature.TURN_ON
            | ClimateEntityFeature.PRESET_MODE
        )
        self._attr_hvac_modes = [HVACMode.HEAT, HVACMode.OFF, HVACMode.AUTO]
        self._attr_preset_modes = [PRESET_HOME, PRESET_AWAY]
        self._attr_target_temperature_step = 0.5

        # Per-zone min/max temp (will be updated in update() from zone_config_manager)
        self._attr_min_temp = 5
        self._attr_max_temp = 25

        self._attr_current_temperature = None
        self._attr_target_temperature = None
        self._attr_hvac_mode = None
        self._attr_hvac_action = None
        self._attr_available = False
        self._attr_current_humidity = None

        # Extra attributes
        self._overlay_type = None
        self._heating_power = None
        self._offset_celsius = None  # Temperature offset (optional, enabled in config)
        self._attr_preset_mode = PRESET_HOME

        # External sensor override tracking
        self._temperature_source = "tado"
        self._humidity_source = "tado"
        self._external_temp_sensor = ""
        self._external_humidity_sensor = ""

        # Track last target temp from API for heating cycle detection
        self._last_target_temp_from_api: float | None = None

        # Optimistic state tracking with sequence numbers
        # Sequence-based optimistic state tracking with coordinator-aware approach
        self._optimistic_state: dict[str, Any] | None = None  # Current optimistic state
        self._optimistic_sequence: int | None = None  # Sequence number of optimistic state
        self._expected_hvac_mode: HVACMode | None = None  # Expected mode after API call
        self._expected_hvac_action: HVACAction | None = None  # Expected action after API call

        # Unsubscribe callback for zones_updated signal
        self._unsub_zones_updated = None

        # Unsubscribe callback for zone config changes
        self._unsub_zone_config = None

        # Unsubscribe callbacks for external sensor state change listeners
        self._unsub_external_sensors: list[CALLBACK_TYPE] = []

    def _clear_optimistic_state(self) -> None:
        """Clear all optimistic state tracking.

        Delegates to shared optimistic.clear_optimistic_state().
        """
        clear_optimistic_state(self)

    async def _set_optimistic_state(
        self, hvac_mode: HVACMode, hvac_action: HVACAction, target_temp: float | None = None,
    ) -> None:
        """Set optimistic state with sequence number tracking.

        Delegates to shared optimistic.set_optimistic_state().
        """
        await set_optimistic_state(self, hvac_mode, hvac_action, target_temp=target_temp)

    def _calculate_hvac_action(self, target_temp: float | None = None) -> HVACAction:
        """Calculate hvac_action for heating zone.

        Updated for optimistic update fix.

        Priority:
        1. If hvac_mode == OFF → OFF
        2. If target_temp provided (optimistic call) → HEATING
        3. If in optimistic window with expected action → return expected action
        4. If heating_power > 0 → HEATING (API confirms active heating)
        5. If hvac_mode == HEAT and target > current + 0.5 → HEATING (temperature fallback)
        6. Otherwise → IDLE

        Args:
            target_temp: Optional target temperature for optimistic updates.
                        If None, uses self._attr_target_temperature.

        Returns:
            HVACAction.HEATING, HVACAction.IDLE, or HVACAction.OFF

        """
        # OFF mode always returns OFF
        if self._attr_hvac_mode == HVACMode.OFF:
            return HVACAction.OFF

        # If target_temp is provided (optimistic call), assume HEATING
        # This MUST be checked before _expected_hvac_action to ensure new
        # optimistic updates override stale expected actions
        if target_temp is not None and self._attr_hvac_mode == HVACMode.HEAT:
            return HVACAction.HEATING

        # If we have optimistic state with expected action, use it
        # This ensures optimistic updates work even when current temp >= target
        if self._expected_hvac_action is not None:
            return self._expected_hvac_action

        # API confirms heating (highest priority when available)
        if self._heating_power and self._heating_power > 0:
            return HVACAction.HEATING

        # Temperature-aware fallback for HEAT mode
        # This handles the case where API hasn't updated heating_power yet
        if self._attr_hvac_mode == HVACMode.HEAT:
            target = self._attr_target_temperature
            current = self._attr_current_temperature
            if target is not None and current is not None:
                # 0.5°C buffer for hysteresis to prevent flip-flopping
                if target > current + 0.5:
                    return HVACAction.HEATING

        return HVACAction.IDLE

    async def async_added_to_hass(self) -> None:
        """Register listeners when entity is added to hass.

        CoordinatorEntity handles update subscription
        automatically — removed manual SIGNAL_ZONES_UPDATED dispatcher signal.
        Zone config listener retained (not a coordinator update).
        """
        await super().async_added_to_hass()

        # Restore last known target temperature across HA restarts (#182)
        last_state = await self.async_get_last_state()
        if last_state and last_state.attributes.get(ATTR_TEMPERATURE) is not None:
            self._attr_target_temperature = last_state.attributes[ATTR_TEMPERATURE]
            _LOGGER.debug(
                "%s: Restored target temperature %s from previous state",
                self._zone_name,
                self._attr_target_temperature,
            )

        # Listen for zone config changes
        zone_config_manager = self.coordinator.zone_config_manager
        if zone_config_manager:

            @callback
            def _handle_zone_config_change(zone_id: str, key: str, value: Any) -> None:
                """Handle zone config change."""
                if zone_id == self._zone_id and key in ("min_temp", "max_temp"):
                    self._update_temp_limits()
                    self.async_write_ha_state()
                    _LOGGER.debug("%s: Zone config %s changed to %s", self._zone_name, key, value)

            self._unsub_zone_config = zone_config_manager.add_listener(_handle_zone_config_change)  # type: ignore[assignment]
            # Initial update of temp limits
            self._update_temp_limits()

        # Subscribe to external sensor state changes for real-time updates
        self._subscribe_external_sensors()

    async def async_will_remove_from_hass(self) -> None:
        """Unregister listeners when entity is removed.

        CoordinatorEntity handles update unsubscription.
        Only zone config listener needs manual cleanup.
        """
        self._unsubscribe_external_sensors()
        if self._unsub_zone_config:
            self._unsub_zone_config()
            self._unsub_zone_config = None
        await super().async_will_remove_from_hass()

    @callback
    def _subscribe_external_sensors(self) -> None:
        """Subscribe to external sensor state changes for real-time updates."""
        self._unsubscribe_external_sensors()

        zcm = self.coordinator.zone_config_manager
        if not zcm:
            return

        config = zcm.get_zone_config(self._zone_id)
        entity_ids: list[str] = []

        temp_sensor = config.get("external_temp_sensor", "")
        if temp_sensor:
            entity_ids.append(temp_sensor)

        humidity_sensor = config.get("external_humidity_sensor", "")
        if humidity_sensor:
            entity_ids.append(humidity_sensor)

        if not entity_ids:
            return

        @callback
        def _handle_external_sensor_change(event: Event[EventStateChangedData]) -> None:
            """Handle external sensor state change — update climate entity immediately."""
            new_state = event.data.get("new_state")
            if new_state is None or new_state.state in ("unknown", "unavailable", ""):
                return

            try:
                float(new_state.state)
            except (ValueError, TypeError):
                return

            # Re-read external sensors and update state
            ext_temp = read_external_sensor(self.hass, zcm, self._zone_id, "external_temp_sensor")
            if ext_temp is not None:
                self._attr_current_temperature = ext_temp
                self._temperature_source = "external"

            ext_hum = read_external_sensor(self.hass, zcm, self._zone_id, "external_humidity_sensor")
            if ext_hum is not None:
                self._attr_current_humidity = ext_hum
                self._humidity_source = "external"

            self.async_write_ha_state()
            _LOGGER.debug("%s: External sensor updated → refreshed climate state", self._zone_name)

        unsub = async_track_state_change_event(self.hass, entity_ids, _handle_external_sensor_change)
        self._unsub_external_sensors.append(unsub)
        _LOGGER.debug("%s: Subscribed to external sensor updates: %s", self._zone_name, entity_ids)

    @callback
    def _unsubscribe_external_sensors(self) -> None:
        """Unsubscribe from external sensor state change listeners."""
        for unsub in self._unsub_external_sensors:
            unsub()
        self._unsub_external_sensors.clear()

    @callback
    def _update_temp_limits(self) -> None:
        """Update min/max temp from zone config.

        Only applies user-explicit overrides (has_zone_override check).
        If user never set min/max_temp in Zone Configuration, use
        defaults (5°C / 25°C) — consistent with AC fix (#180).
        """
        zone_config_manager = self.coordinator.zone_config_manager
        if zone_config_manager:
            if zone_config_manager.has_zone_override(self._zone_id, "min_temp"):
                self._attr_min_temp = zone_config_manager.get_zone_value(self._zone_id, "min_temp", 5.0)
            else:
                self._attr_min_temp = 5.0

            if zone_config_manager.has_zone_override(self._zone_id, "max_temp"):
                self._attr_max_temp = zone_config_manager.get_zone_value(self._zone_id, "max_temp", 25.0)
            else:
                self._attr_max_temp = 25.0

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return extra state attributes."""
        attrs = {
            "overlay_type": _format_overlay_type(self._overlay_type),
            "heating_power": self._heating_power,
            "zone_id": self._zone_id,
            "temperature_source": self._temperature_source,
            "humidity_source": self._humidity_source,
            "external_temp_sensor": self._external_temp_sensor,
            "external_humidity_sensor": self._external_humidity_sensor,
        }
        # Only include offset_celsius if enabled and available
        if self._offset_celsius is not None:
            attrs["offset_celsius"] = self._offset_celsius
        return attrs

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle coordinator data update.

        Replaces manual SIGNAL_ZONES_UPDATED handler.
        CoordinatorEntity calls this automatically after each coordinator poll.
        """
        self.update()
        self.async_write_ha_state()

    @callback
    def update(self) -> None:
        """Update climate state from JSON file."""
        # Layer 1 - Skip update if entity is fresh (coordinator-level protection)
        # This prevents unnecessary file I/O and processing when entity has recent API call
        if self.coordinator.is_entity_fresh(self.entity_id):
            _LOGGER.debug("%s: Skipping update (entity is fresh)", self._zone_name)
            return

        try:
            coord_data = self.coordinator.data or {}
            config = coord_data.get("config")
            if config:
                self._home_id = config.get("home_id")

            data = coord_data.get("zones")
            if data:
                # Use 'or {}' pattern for null safety
                zone_states = data.get("zoneStates") or {}
                zone_data = zone_states.get(self._zone_id)
            else:
                zone_data = None

            if not zone_data:
                self._attr_available = False
                return

            # Current temperature (use 'or {}' pattern for null safety)
            sensor_data = zone_data.get("sensorDataPoints") or {}
            self._attr_current_temperature = (sensor_data.get("insideTemperature") or {}).get("celsius")

            # Current humidity
            self._attr_current_humidity = (sensor_data.get("humidity") or {}).get("percentage")

            # External sensor overrides (fallback to Tado API values above)
            zcm = self.coordinator.zone_config_manager
            ext_temp = read_external_sensor(self.hass, zcm, self._zone_id, "external_temp_sensor")
            if ext_temp is not None:
                self._attr_current_temperature = ext_temp
                self._temperature_source = "external"
            else:
                self._temperature_source = "tado"

            ext_hum = read_external_sensor(self.hass, zcm, self._zone_id, "external_humidity_sensor")
            if ext_hum is not None:
                self._attr_current_humidity = ext_hum
                self._humidity_source = "external"
            else:
                self._humidity_source = "tado"

            # Track configured entity_ids for extra_state_attributes
            if zcm:
                zc = zcm.get_zone_config(self._zone_id)
                self._external_temp_sensor = zc.get("external_temp_sensor", "")
                self._external_humidity_sensor = zc.get("external_humidity_sensor", "")

            # Heating power
            activity_data = zone_data.get("activityDataPoints") or {}
            self._heating_power = (activity_data.get("heatingPower") or {}).get("percentage", 0)

            # Setting (target temp and mode)
            setting = zone_data.get("setting") or {}
            power = setting.get("power")
            self._overlay_type = zone_data.get("overlayType")

            # Determine API-reported state first
            if power == "ON":
                temp = (setting.get("temperature") or {}).get("celsius")
                self._attr_target_temperature = temp

                # fix: Use SINGLE atomic call to heating cycle coordinator
                # This eliminates race conditions between setpoint and temperature updates
                if temp is not None and self._attr_current_temperature is not None:
                    heating_cycle_coordinator = self.coordinator.heating_cycle_coordinator
                    if heating_cycle_coordinator:
                        # Use on_zone_update for atomic operation
                        self.hass.async_create_task(
                            heating_cycle_coordinator.on_zone_update(
                                self._zone_id,
                                temp,
                                self._attr_current_temperature,
                            ),
                        )

                # Determine HVAC mode - match official Tado integration behavior
                if self._overlay_type == "MANUAL":
                    api_hvac_mode = HVACMode.HEAT
                else:
                    api_hvac_mode = HVACMode.AUTO
            # Power is OFF
            elif self._overlay_type == "MANUAL":
                api_hvac_mode = HVACMode.OFF
            else:
                api_hvac_mode = HVACMode.AUTO

            # Calculate hvac_action based on API state
            # Temporarily set hvac_mode to calculate action correctly
            old_hvac_mode = self._attr_hvac_mode
            self._attr_hvac_mode = api_hvac_mode
            api_hvac_action = self._calculate_hvac_action()
            self._attr_hvac_mode = old_hvac_mode  # Restore for comparison

            # Sequence-based optimistic state handling
            # Delegates to shared optimistic.resolve_optimistic_vs_api()
            should_preserve = resolve_optimistic_vs_api(self, api_hvac_mode, api_hvac_action)

            # Apply state based on preservation decision
            if should_preserve:
                # Keep optimistic mode and action until API confirms
                self._attr_hvac_mode = self._expected_hvac_mode
                self._attr_hvac_action = self._expected_hvac_action
                _LOGGER.debug(
                    "%s: Using optimistic state: mode=%s, action=%s",
                    self._zone_name,
                    self._attr_hvac_mode,
                    self._attr_hvac_action,
                )
            else:
                # Use API state
                self._attr_hvac_mode = api_hvac_mode
                self._attr_hvac_action = api_hvac_action

                # Handle OFF mode specifics
                if power != "ON" and api_hvac_mode in (HVACMode.OFF, HVACMode.AUTO):
                    # Preserve last known target temperature for UX (#182)
                    # — keeps climate card controls usable when zone is OFF
                    if api_hvac_mode == HVACMode.OFF:
                        self._attr_hvac_action = HVACAction.OFF

            self._attr_available = True

            # Record temperature for Smart Comfort analytics
            _record_smart_comfort_data(
                self.hass,
                self._zone_id,
                self._zone_name,
                self._attr_current_temperature,
                self._attr_target_temperature,
                is_active=(self._heating_power is not None and self._heating_power > 0),
                entry_id=self._entry_id,
            )

            # Update preset mode from home state
            self._update_preset_mode()

            # Update offset if enabled
            self._update_offset()

        except Exception as e:
            _LOGGER.warning("Failed to update %s: %s", self.name, e)
            self._attr_available = False

    @callback
    def _update_offset(self) -> None:
        """Update temperature offset from cached offsets file.

        Delegates to shared climate_helpers.update_offset().
        """
        self._offset_celsius = update_offset(self.coordinator, self._zone_id)  # type: ignore[assignment]

    @callback
    def _update_preset_mode(self) -> None:
        """Update preset mode based on home state.

        Delegates to shared climate_helpers.update_preset_mode().
        """
        result = update_preset_mode(self.coordinator)
        if result is not None:
            self._attr_preset_mode = result

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        """Set preset mode (Home/Away).

        Uses 1 API call to set presence lock.

        Added timeout protection for consistency with other methods.
        Added bootstrap reserve check - blocks action when quota critically low.
        """
        await _check_bootstrap_reserve(self.hass, self._zone_name, entry_id=self._entry_id)

        client = self.coordinator.api_client
        state = "AWAY" if preset_mode == PRESET_AWAY else "HOME"

        # Optimistic update BEFORE API call
        old_preset = self._attr_preset_mode
        self._attr_preset_mode = preset_mode
        self._optimistic_set_at = time.monotonic()
        self.async_write_ha_state()

        api_success = False
        try:
            async with asyncio.timeout(10):
                api_success = await client.set_presence_lock(state)
        except TimeoutError:
            _LOGGER.warning("TIMEOUT: %s preset mode API call timed out", self._zone_name)
        except Exception as e:
            _LOGGER.warning("ERROR: %s preset mode API call failed (%s)", self._zone_name, e)

        if api_success:
            _LOGGER.info("Set %s preset mode to %s", self._zone_name, preset_mode)
            await async_trigger_immediate_refresh(self.hass, self.entity_id, "preset_mode_change")
        else:
            _LOGGER.warning("ROLLBACK: %s preset mode failed", self._zone_name)
            self._attr_preset_mode = old_preset
            self._clear_optimistic_state()
            self.async_write_ha_state()

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set new target temperature.

        Optimized to use single API call when both temperature and hvac_mode are provided.
        This saves 1 API call (1% of 100-call limit) compared to calling set_hvac_mode first.

        Changed from fire-and-forget to await pattern to fix grey loading state issue.
        Service call now awaits API completion (with timeout) for proper HA Frontend state sync.

        Added bootstrap reserve check - blocks action when quota critically low.
        """
        temperature = kwargs.get(ATTR_TEMPERATURE)
        hvac_mode = kwargs.get(ATTR_HVAC_MODE)

        # Handle hvac_mode without temperature (delegate to set_hvac_mode)
        if hvac_mode is not None and temperature is None:
            await self.async_set_hvac_mode(hvac_mode)
            return

        # Handle OFF mode specially (no temperature needed)
        if hvac_mode == HVACMode.OFF:
            await self.async_set_hvac_mode(HVACMode.OFF)
            return

        # Handle AUTO mode specially (delete overlay, no temperature)
        if hvac_mode == HVACMode.AUTO:
            await self.async_set_hvac_mode(HVACMode.AUTO)
            return

        if temperature is None:
            return

        await _check_bootstrap_reserve(self.hass, self._zone_name, entry_id=self._entry_id)

        old_temp = self._attr_target_temperature
        old_mode = self._attr_hvac_mode
        old_action = self._attr_hvac_action
        self._attr_target_temperature = temperature
        self._attr_hvac_mode = HVACMode.HEAT
        self._overlay_type = "MANUAL"  # type: ignore[assignment]
        # Calculate hvac_action
        new_hvac_action = self._calculate_hvac_action(target_temp=temperature)
        self._attr_hvac_action = new_hvac_action
        # Set optimistic state with sequence number and mark entity fresh
        await self._set_optimistic_state(HVACMode.HEAT, new_hvac_action, target_temp=temperature)
        _LOGGER.debug(
            "Optimistic update: %s target_temp=%s, hvac_action=%s",
            self._zone_name,
            temperature,
            self._attr_hvac_action,
        )
        self.async_write_ha_state()

        # Await API call with timeout (fixes #44 grey loading state)
        client = self.coordinator.api_client
        setting = {
            "type": "HEATING",
            "power": "ON",
            "temperature": {"celsius": temperature},
        }
        # Use per-zone overlay mode
        termination = get_zone_overlay_termination(self.hass, self._zone_id, entry_id=self._entry_id)

        api_success = False
        try:
            async with asyncio.timeout(10):  # 10 second timeout
                api_success = await client.set_zone_overlay(self._zone_id, setting, termination)
        except TimeoutError:
            _LOGGER.warning("TIMEOUT: %s API call timed out, reverting to %s", self._zone_name, old_temp)
        except Exception as e:
            _LOGGER.warning("ERROR: %s API call failed (%s), reverting to %s", self._zone_name, e, old_temp)

        if api_success:
            _LOGGER.info("Set %s to %s°C", self._zone_name, temperature)
            # Notify heating cycle coordinator of setpoint change
            heating_cycle_coordinator = self.coordinator.heating_cycle_coordinator
            if heating_cycle_coordinator:
                await heating_cycle_coordinator.on_setpoint_change(
                    self._zone_id,
                    temperature,
                    self._attr_current_temperature,
                )
            # Refresh is best-effort, don't rollback if it fails
            await async_trigger_immediate_refresh(self.hass, self.entity_id, "temperature_change")
        else:
            # Rollback on API failure
            self._attr_target_temperature = old_temp
            self._attr_hvac_mode = old_mode
            self._attr_hvac_action = old_action
            self._clear_optimistic_state()
            self.async_write_ha_state()

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set new HVAC mode.

        Changed from fire-and-forget to await pattern to fix grey loading state issue.
        Service call now awaits API completion (with timeout) for proper HA Frontend state sync.

        Added bootstrap reserve check - blocks action when quota critically low.
        """
        await _check_bootstrap_reserve(self.hass, self._zone_name, entry_id=self._entry_id)

        client = self.coordinator.api_client

        if hvac_mode == HVACMode.HEAT:
            temp = self._attr_target_temperature or 20
            setting = {
                "type": "HEATING",
                "power": "ON",
                "temperature": {"celsius": temp},
            }
            termination = get_zone_overlay_termination(self.hass, self._zone_id, entry_id=self._entry_id)
            new_hvac_action = self._calculate_hvac_action(target_temp=temp)
            await api_call_with_rollback(
                self,
                client.set_zone_overlay(self._zone_id, setting, termination),
                hvac_mode=HVACMode.HEAT,
                hvac_action=new_hvac_action,
                target_temp=temp,
                reason=f"Set HEAT mode at {temp}°C",
            )

        elif hvac_mode == HVACMode.OFF:
            setting = {
                "type": "HEATING",
                "power": "OFF",
            }
            termination = get_zone_overlay_termination(self.hass, self._zone_id, entry_id=self._entry_id)
            await api_call_with_rollback(
                self,
                client.set_zone_overlay(self._zone_id, setting, termination),
                hvac_mode=HVACMode.OFF,
                hvac_action=HVACAction.OFF,
                reason="Set OFF mode",
            )

        elif hvac_mode == HVACMode.AUTO:
            await api_call_with_rollback(
                self,
                client.delete_zone_overlay(self._zone_id),
                hvac_mode=HVACMode.AUTO,
                hvac_action=HVACAction.IDLE,
                overlay_type=None,
                reason="Set AUTO mode (deleted overlay)",
            )

    async def async_set_timer(
        self, temperature: float, duration_minutes: int | None = None, overlay: str | None = None,
    ) -> bool:
        """Set temperature with timer or overlay type.

        Args:
            temperature: Target temperature in Celsius
            duration_minutes: Duration in minutes (for TIMER termination)
            overlay: Overlay type - 'next_time_block' for TADO_MODE, None for MANUAL

        Added bootstrap reserve check - blocks action when quota critically low.

        """
        await _check_bootstrap_reserve(self.hass, self._zone_name, entry_id=self._entry_id)

        client = self.coordinator.api_client

        setting = {
            "type": "HEATING",
            "power": "ON",
            "temperature": {"celsius": temperature},
        }

        # Determine termination type
        # DRY — use shared build_timer_termination
        termination = build_timer_termination(
            duration_minutes=duration_minutes,
            overlay=overlay,
            hass=self.hass,
            zone_id=self._zone_id,
            entry_id=self._entry_id,
        )
        if duration_minutes:
            term_desc = f"for {duration_minutes} minutes"
        elif overlay and overlay.upper() == "NEXT_TIME_BLOCK":
            term_desc = "until next schedule block"
        else:
            term_desc = "manually"

        # Added timeout protection for consistency
        api_success = False
        try:
            async with asyncio.timeout(10):
                api_success = await client.set_zone_overlay(self._zone_id, setting, termination)
        except TimeoutError:
            _LOGGER.warning("TIMEOUT: %s set_timer API call timed out", self._zone_name)
        except Exception as e:
            _LOGGER.warning("ERROR: %s set_timer API call failed (%s)", self._zone_name, e)

        if api_success:
            _LOGGER.info("Set %s to %s°C %s", self._zone_name, temperature, term_desc)
            return True
        return False
