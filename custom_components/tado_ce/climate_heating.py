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
from homeassistant.core import CALLBACK_TYPE, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .climate_helpers import (
    api_call_with_rollback,
    inject_presence_state,
    read_external_sensor,
    setup_climate_external_sensor_subscription,
    unsubscribe_external_sensors,
    update_offset,
    update_preset_mode,
)
from .const import CLOUD_VERIFICATION_BUFFER_SECONDS, DOMAIN, SIGNAL_HOMEKIT_UPDATE
from .device_manager import get_zone_device_info
from .entity_registry import ENTITY_REGISTRY
from .format_helpers import (
    format_overlay_type as _format_overlay_type,
)
from .helpers import (
    async_trigger_immediate_refresh,
    build_timer_termination,
    get_zone_overlay_termination,
    get_zone_state,
    should_use_homekit_for_overlay,
)
from .optimistic_helpers import (
    OptimisticUpdateResult,
    clear_optimistic_state,
    resolve_optimistic_update,
    set_optimistic_fields,
)
from .ratelimit import async_check_bootstrap_reserve_or_raise as _check_bootstrap_reserve_or_raise
from .schedule_helpers import get_current_schedule_target
from .write_optimizer import ActionGuard

if TYPE_CHECKING:
    from collections.abc import Callable

    from .api_client import TadoApiClient
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
        self._entity_type = "climate_heating"

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
        self._temperature_source = "cloud"
        self._humidity_source = "cloud"
        self._external_temp_sensor = ""
        self._external_humidity_sensor = ""
        self._last_write_source = ""

        # Track last target temp from API for heating cycle detection
        self._last_target_temp_from_api: float | None = None

        # Optimistic state tracking with sequence numbers
        self._optimistic_set_at: float | None = None
        self._optimistic_sequence: int | None = None
        self._optimistic_preserved: dict[str, Any] | None = None
        self._expected_hvac_mode: HVACMode | None = None
        self._expected_hvac_action: HVACAction | None = None

        # Unsubscribe callback for zones_updated signal
        self._unsub_zones_updated = None

        # Unsubscribe callback for zone config changes
        self._unsub_zone_config = None

        # Unsubscribe callbacks for external sensor state change listeners
        self._unsub_external_sensors: list[CALLBACK_TYPE] = []

        # Cloud verification timer handle
        self._cloud_verification_handle: asyncio.TimerHandle | None = None

        # Unsubscribe callback for HomeKit dispatcher signal
        self._unsub_homekit_signal: Callable[[], None] | None = None

    def _calculate_hvac_action(self, target_temp: float | None = None) -> HVACAction:
        """Calculate hvac_action for heating zone.

        Updated for optimistic update fix.

        Priority:
        1. If hvac_mode == OFF -> OFF
        2. If target_temp provided (optimistic call) -> HEATING
        3. If in optimistic window with expected action -> return expected action
        4. If heating_power > 0 -> HEATING (API confirms active heating)
        5. If hvac_mode == HEAT and target > current + 0.5 -> HEATING (temperature fallback)
        6. Otherwise -> IDLE

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
        elif self._attr_target_temperature is None:
            # First install or no previous state — default to 20°C so climate
            # card controls are usable immediately (#182 follow-up)
            self._attr_target_temperature = 20.0
            _LOGGER.debug(
                "%s: No previous state, defaulting target temperature to %s",
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

        # Subscribe to HomeKit dispatcher signal for real-time sensor updates
        self._unsub_homekit_signal = async_dispatcher_connect(
            self.hass,
            SIGNAL_HOMEKIT_UPDATE.format(home_id=self._home_id),
            self._handle_homekit_update,
        )

    async def async_will_remove_from_hass(self) -> None:
        """Unregister listeners when entity is removed."""
        self._unsubscribe_external_sensors()
        if self._unsub_homekit_signal:
            self._unsub_homekit_signal()
            self._unsub_homekit_signal = None
        if self._unsub_zone_config:
            self._unsub_zone_config()
            self._unsub_zone_config = None
        if self._cloud_verification_handle is not None:
            self._cloud_verification_handle.cancel()
            self._cloud_verification_handle = None
        await super().async_will_remove_from_hass()

    @callback
    def _subscribe_external_sensors(self) -> None:
        """Subscribe to external sensor state changes for real-time updates."""
        self._unsub_external_sensors = setup_climate_external_sensor_subscription(
            self, self._zone_id, self._unsub_external_sensors, label=self._zone_name,
        )

    @callback
    def _unsubscribe_external_sensors(self) -> None:
        """Unsubscribe from external sensor state change listeners."""
        unsubscribe_external_sensors(self._unsub_external_sensors)

    @callback
    def _handle_homekit_update(self, zone_id: str) -> None:
        """Handle HomeKit data update for this zone."""
        if zone_id != self._zone_id:
            return
        if self.coordinator.is_entity_fresh(self.entity_id):
            return
        zone_data = get_zone_state(self.coordinator.data, self._zone_id) or {}
        self._update_sensor_data(zone_data)
        self.async_write_ha_state()

        # Record temperature for heating cycle analysis (real-time HomeKit data
        # gives denser readings → more accurate heating rate/acceleration)
        if self._attr_target_temperature is not None:
            self._schedule_heating_cycle_update(self._attr_target_temperature)

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
        attrs: dict[str, Any] = {
            "overlay_type": _format_overlay_type(self._overlay_type),
            "heating_power": self._heating_power,
            "zone_id": self._zone_id,
            "temperature_source": self._temperature_source,
            "humidity_source": self._humidity_source,
            "external_temp_sensor": self._external_temp_sensor,
            "external_humidity_sensor": self._external_humidity_sensor,
            "last_write_source": self._last_write_source,
        }
        # Only include offset_celsius if enabled and available
        if self._offset_celsius is not None:
            attrs["offset_celsius"] = self._offset_celsius
        # Schedule Preview — show current schedule target temperature
        scheduled_temp = get_current_schedule_target(
            self._zone_id,
            data_loader=self.coordinator.data_loader,
        )
        if scheduled_temp is not None:
            attrs["scheduled_target_temperature"] = scheduled_temp

        # Smart Valve Control attributes
        controller = self.coordinator.valve_controllers.get(self._zone_id)
        if controller is not None:
            attrs.update(controller.get_attributes())
        else:
            attrs["valve_control_active"] = False

        return attrs

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle coordinator data update.

        Replaces manual SIGNAL_ZONES_UPDATED handler.
        CoordinatorEntity calls this automatically after each coordinator poll.
        """
        self.update()
        self.async_write_ha_state()

    def _update_sensor_data(self, zone_data: dict[str, Any]) -> None:
        """Extract sensor data with priority: external > homekit > cloud."""
        sensor_data = zone_data.get("sensorDataPoints") or {}
        cloud_temp = (sensor_data.get("insideTemperature") or {}).get("celsius")
        cloud_humidity = (sensor_data.get("humidity") or {}).get("percentage")

        # External sensor overrides
        zcm = self.coordinator.zone_config_manager
        ext_temp = read_external_sensor(self.hass, zcm, self._zone_id, "external_temp_sensor")
        ext_hum = read_external_sensor(self.hass, zcm, self._zone_id, "external_humidity_sensor")

        # Priority chain via StateReconciler (external > homekit if fresh > cloud)
        reconciler = self.coordinator.state_reconciler
        provider = self.coordinator.homekit_provider
        if reconciler and provider and provider.is_connected:
            reconciler.local_provider = provider
            merged_temp, temp_source = reconciler.merge_zone_temperature(
                self._zone_id, cloud_temp, external_value=ext_temp,
            )
            merged_hum, hum_source = reconciler.merge_zone_humidity(
                self._zone_id, cloud_humidity, external_value=ext_hum,
            )
        elif ext_temp is not None:
            merged_temp, temp_source = ext_temp, "external"
            merged_hum, hum_source = (ext_hum, "external") if ext_hum is not None else (cloud_humidity, "cloud")
        elif ext_hum is not None:
            merged_temp, temp_source = cloud_temp, "cloud"
            merged_hum, hum_source = ext_hum, "external"
        else:
            merged_temp, temp_source = cloud_temp, "cloud"
            merged_hum, hum_source = cloud_humidity, "cloud"

        self._attr_current_temperature = merged_temp
        self._temperature_source = temp_source
        self._attr_current_humidity = merged_hum
        self._humidity_source = hum_source

        # Log source changes for diagnostic tracing
        if temp_source != getattr(self, "_prev_temp_source", None) or hum_source != getattr(self, "_prev_hum_source", None):
            _LOGGER.debug(
                "%s climate merge: temp=%s (%s), humidity=%s (%s), cloud_temp=%s, cloud_hum=%s",
                self._zone_name, merged_temp, temp_source, merged_hum, hum_source,
                cloud_temp, cloud_humidity,
            )
            self._prev_temp_source = temp_source
            self._prev_hum_source = hum_source

        # Track configured entity_ids for extra_state_attributes
        if zcm:
            zc = zcm.get_zone_config(self._zone_id)
            self._external_temp_sensor = zc.get("external_temp_sensor", "")
            self._external_humidity_sensor = zc.get("external_humidity_sensor", "")

    def _determine_api_hvac_mode(self, power: str | None, zone_data: dict[str, Any]) -> HVACMode:
        """Determine HVAC mode from API power state and overlay type."""
        self._overlay_type = zone_data.get("overlayType")

        if power == "ON":
            setting = zone_data.get("setting") or {}
            temp = (setting.get("temperature") or {}).get("celsius")
            self._attr_target_temperature = temp
            self._schedule_heating_cycle_update(temp)
            return HVACMode.HEAT if self._overlay_type == "MANUAL" else HVACMode.AUTO

        # Power is OFF — show scheduled target for context, but mode is OFF
        # regardless of whether it's a manual overlay, schedule block, or Away mode
        if self._overlay_type != "MANUAL":
            scheduled = get_current_schedule_target(
                self._zone_id, data_loader=self.coordinator.data_loader,
            )
            if scheduled is not None:
                self._attr_target_temperature = scheduled

        return HVACMode.OFF

    def _schedule_heating_cycle_update(self, temp: float | None) -> None:
        """Schedule async heating cycle coordinator update if applicable."""
        if temp is None or self._attr_current_temperature is None:
            return
        heating_cycle_coordinator = self.coordinator.heating_cycle_coordinator
        if not heating_cycle_coordinator:
            return

        _zone_id = self._zone_id
        _zone_name = self._zone_name
        _current_temp = self._attr_current_temperature

        async def _safe_heating_cycle_update() -> None:
            """Fire-and-forget wrapper with error logging."""
            try:
                await heating_cycle_coordinator.on_zone_update(
                    _zone_id, temp, _current_temp,
                )
            except (KeyError, TypeError, ValueError):
                _LOGGER.debug(
                    "HeatingCycleCoordinator update failed for zone %s",
                    _zone_name,
                    exc_info=True,
                )

        self.hass.async_create_task(_safe_heating_cycle_update())

    def _schedule_cloud_verification(self) -> None:
        """Schedule a coordinator refresh to verify HomeKit write."""
        if self._cloud_verification_handle is not None:
            self._cloud_verification_handle.cancel()
            self._cloud_verification_handle = None

        from .helpers import get_optimistic_window

        delay = get_optimistic_window(self.hass, entry_id=self._entry_id) + CLOUD_VERIFICATION_BUFFER_SECONDS
        entity_id = self.entity_id

        def _fire() -> None:
            self._cloud_verification_handle = None
            self.hass.async_create_task(
                async_trigger_immediate_refresh(self.hass, entity_id, "homekit_verification"),
            )

        try:
            loop = asyncio.get_running_loop()
            self._cloud_verification_handle = loop.call_later(delay, _fire)
        except RuntimeError:
            pass

    def _apply_optimistic_or_api_state(
        self, api_hvac_mode: HVACMode, api_hvac_action: HVACAction, power: str | None,
    ) -> None:
        """Apply optimistic or API state based on sequence comparison."""
        result = resolve_optimistic_update(
            self,
            api_values={"hvac_mode": api_hvac_mode, "hvac_action": api_hvac_action},
            entry_id=self._entry_id,
        )

        if result == OptimisticUpdateResult.PRESERVE_OPTIMISTIC:
            self._attr_hvac_mode = self._expected_hvac_mode
            self._attr_hvac_action = self._expected_hvac_action
            _LOGGER.debug(
                "%s: Using optimistic state: mode=%s, action=%s",
                self._zone_name, self._attr_hvac_mode, self._attr_hvac_action,
            )
        else:
            if result == OptimisticUpdateResult.EXPIRED:
                _LOGGER.warning(
                    "%s: Optimistic state expired, accepting API state",
                    self._zone_name,
                )
                # Record failure if this was a HomeKit write
                if self._last_write_source == "homekit":
                    write_tracker = self.coordinator.write_health_tracker
                    if write_tracker is not None:
                        write_tracker.record_failure()
                    self._last_write_source = ""

            elif result == OptimisticUpdateResult.ACCEPT_API and self._last_write_source == "homekit":
                # API confirmed the HomeKit write
                write_tracker = self.coordinator.write_health_tracker
                if write_tracker is not None:
                    write_tracker.record_success()
                self._last_write_source = ""

            self._attr_hvac_mode = api_hvac_mode
            self._attr_hvac_action = api_hvac_action
            if power != "ON" and api_hvac_mode == HVACMode.OFF:
                self._attr_hvac_action = HVACAction.OFF

    def _record_smart_comfort(self) -> None:
        """Record temperature for Smart Comfort analytics."""
        _scm = self.coordinator.smart_comfort_manager
        if not (_scm and _scm.is_enabled and self._attr_current_temperature is not None):
            return
        try:
            _scm.record_temperature(
                zone_id=self._zone_id,
                zone_name=self._zone_name,
                temperature=self._attr_current_temperature,
                is_heating=(self._heating_power is not None and self._heating_power > 0),
                target_temperature=self._attr_target_temperature,
            )
        except (KeyError, TypeError, ValueError) as e:
            _LOGGER.debug("Failed to record smart comfort data for %s: %s", self._zone_name, e)

    @callback
    def update(self) -> None:
        """Update climate state from JSON file."""
        if self.coordinator.is_entity_fresh(self.entity_id):
            # Safety net: never skip if entity has no data yet (#246 — boot freshness false positive)
            if self._attr_current_temperature is not None:
                _LOGGER.debug("%s: Skipping update (entity is fresh)", self._zone_name)
                return
            _LOGGER.debug("%s: Entity marked fresh but has no data — updating anyway", self._zone_name)

        try:
            coord_data = self.coordinator.data or {}
            config = coord_data.get("config")
            if config:
                self._home_id = config.get("home_id")

            zone_data = get_zone_state(coord_data, self._zone_id)

            if not zone_data:
                self._attr_available = False
                return

            self._update_sensor_data(zone_data)

            # Heating power
            activity_data = zone_data.get("activityDataPoints") or {}
            self._heating_power = (activity_data.get("heatingPower") or {}).get("percentage", 0)

            # Determine API state
            setting = zone_data.get("setting") or {}
            power = setting.get("power")
            api_hvac_mode = self._determine_api_hvac_mode(power, zone_data)

            # Calculate hvac_action
            old_hvac_mode = self._attr_hvac_mode
            self._attr_hvac_mode = api_hvac_mode
            api_hvac_action = self._calculate_hvac_action()
            self._attr_hvac_mode = old_hvac_mode

            # Apply state
            self._apply_optimistic_or_api_state(api_hvac_mode, api_hvac_action, power)
            self._attr_available = True

            self._record_smart_comfort()
            self._update_preset_mode()
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

        """
        # Action Guard — skip if preset already matches current state
        if ActionGuard.should_skip_preset_mode(preset_mode, self._attr_preset_mode):
            _LOGGER.debug(
                "Action Guard: skip %s set_preset_mode (already %s)",
                self._zone_name, preset_mode,
            )
            return

        await _check_bootstrap_reserve_or_raise(self.hass, self._zone_name, coordinator=self.coordinator)

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
            _LOGGER.warning("Timeout: %s preset mode API call timed out", self._zone_name)
        except Exception as e:
            _LOGGER.warning("Error: %s preset mode API call failed (%s)", self._zone_name, e)

        if api_success:
            _LOGGER.info("Set %s preset mode to %s", self._zone_name, preset_mode)
            # Inject home_state locally so all climate entities update preset_mode
            # even when Home State Sync is disabled
            inject_presence_state(self.coordinator, state, locked=True)
            await async_trigger_immediate_refresh(self.hass, self.entity_id, "preset_mode_change")
        else:
            _LOGGER.warning("%s: preset mode change failed, reverted", self._zone_name)
            self._attr_preset_mode = old_preset
            clear_optimistic_state(self)
            self.async_write_ha_state()

    async def _execute_set_temp_api(
        self,
        client: TadoApiClient,
        setting: dict[str, Any],
        termination: dict[str, Any],
        temperature: float,
        old_temp: float | None,
        old_mode: object,
        old_action: object,
        *,
        raise_on_failure: bool = False,
    ) -> None:
        """Execute set_zone_overlay API call with rollback on failure."""
        # Local-first: try HomeKit write before cloud API
        # Only when overlay mode is Tado Default — HomeKit writes don't carry
        # termination info, so non-default overlay modes must use cloud (#219)
        local_success = False
        use_homekit = should_use_homekit_for_overlay(self.hass, self._zone_id, entry_id=self._entry_id)
        write_tracker = self.coordinator.write_health_tracker
        if (
            use_homekit
            and self.coordinator.homekit_provider
            and self.coordinator.homekit_provider.is_connected
            and write_tracker is not None
            and write_tracker.should_try_homekit()
        ):
            import time as _time

            self.coordinator._homekit_write_attempts += 1
            t0 = _time.monotonic()
            try:
                local_success = await self.coordinator.homekit_provider.set_temperature(
                    self._zone_id, temperature,
                )
            except Exception:
                _LOGGER.debug(
                    "HomeKit write failed for %s, falling back to cloud",
                    self._zone_name,
                    exc_info=True,
                )
            elapsed_ms = (_time.monotonic() - t0) * 1000
            self.coordinator._homekit_write_latency_sum += elapsed_ms
            self.coordinator._homekit_write_latency_count += 1
            if local_success:
                # Don't record_success yet — deferred to cloud verification
                self.coordinator._homekit_write_successes += 1
            else:
                write_tracker.record_failure()
                self.coordinator._homekit_write_fallbacks += 1
                _LOGGER.info(
                    "%s: HomeKit write failed, falling back to cloud API",
                    self._zone_name,
                )

        if local_success:
            self.coordinator.record_homekit_write_saved(self._zone_id)
            self._last_write_source = "homekit"
            _LOGGER.info("Set %s to %s°C via HomeKit", self._zone_name, temperature)
            heating_cycle_coordinator = self.coordinator.heating_cycle_coordinator
            if heating_cycle_coordinator:
                await heating_cycle_coordinator.on_zone_update(
                    self._zone_id, temperature, self._attr_current_temperature or temperature,
                )
            # Schedule cloud verification to confirm write reached Tado server
            self._schedule_cloud_verification()
            return

        # Cloud fallback
        api_success = False
        try:
            async with asyncio.timeout(10):
                api_success = await client.set_zone_overlay(self._zone_id, setting, termination)
        except TimeoutError:
            _LOGGER.warning("Timeout: %s API call timed out, reverting to %s", self._zone_name, old_temp)
        except Exception as e:
            _LOGGER.warning("Error: %s API call failed (%s), reverting to %s", self._zone_name, e, old_temp)

        if api_success:
            self._last_write_source = "cloud"
            _LOGGER.info("Set %s to %s°C", self._zone_name, temperature)
            heating_cycle_coordinator = self.coordinator.heating_cycle_coordinator
            if heating_cycle_coordinator:
                await heating_cycle_coordinator.on_zone_update(
                    self._zone_id, temperature, self._attr_current_temperature or temperature,
                )
            await async_trigger_immediate_refresh(self.hass, self.entity_id, "temperature_change")
        else:
            self._attr_target_temperature = old_temp
            self._attr_hvac_mode = old_mode  # type: ignore[assignment]
            self._attr_hvac_action = old_action  # type: ignore[assignment]
            clear_optimistic_state(self)
            self.async_write_ha_state()
            if raise_on_failure:
                raise HomeAssistantError(
                    f"{self._zone_name}: Set temperature to {temperature}°C failed",
                    translation_domain=DOMAIN,
                )

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set new target temperature.

        Optimized to use single API call when both temperature and hvac_mode are provided.
        This saves 1 API call (1% of 100-call limit) compared to calling set_hvac_mode first.


        """
        temperature = kwargs.get(ATTR_TEMPERATURE)
        hvac_mode = kwargs.get(ATTR_HVAC_MODE)

        # Handle hvac_mode without temperature (delegate to set_hvac_mode)
        if hvac_mode is not None and temperature is None:
            await self.async_set_hvac_mode(hvac_mode)
            return

        # Handle OFF/AUTO mode specially (no temperature needed)
        if hvac_mode in (HVACMode.OFF, HVACMode.AUTO):
            await self.async_set_hvac_mode(hvac_mode)
            return

        if temperature is None:
            return

        # Action Guard — skip if temp + mode already match current state
        if ActionGuard.should_skip_temperature(
            temperature, self._attr_target_temperature,
            HVACMode.HEAT, self._attr_hvac_mode,
            optimistic_active=self._optimistic_sequence is not None,
        ):
            _LOGGER.debug(
                "Action Guard: skip %s set_temperature (already %s°C)",
                self._zone_name, temperature,
            )
            return

        await _check_bootstrap_reserve_or_raise(self.hass, self._zone_name, coordinator=self.coordinator)

        # Capture current state before overlay (state restoration)
        await self.coordinator.async_capture_state(
            self._zone_id, self._entity_type, "set_temperature",
        )

        old_temp = self._attr_target_temperature
        old_mode = self._attr_hvac_mode
        old_action = self._attr_hvac_action
        self._attr_target_temperature = temperature
        self._attr_hvac_mode = HVACMode.HEAT
        self._overlay_type = "MANUAL"  # type: ignore[assignment]
        new_hvac_action = self._calculate_hvac_action(target_temp=temperature)
        self._attr_hvac_action = new_hvac_action
        await set_optimistic_fields(
            self, self.coordinator,
            expected={"hvac_mode": HVACMode.HEAT, "hvac_action": new_hvac_action},
        )
        _LOGGER.debug(
            "Optimistic update: %s target_temp=%s, hvac_action=%s",
            self._zone_name, temperature, self._attr_hvac_action,
        )
        self.async_write_ha_state()

        # Build API call parameters
        client = self.coordinator.api_client
        setting = {
            "type": "HEATING",
            "power": "ON",
            "temperature": {"celsius": temperature},
        }
        termination = get_zone_overlay_termination(self.hass, self._zone_id, entry_id=self._entry_id)

        # Smart Actions debounce
        debounce_window = self.coordinator.config_manager.get_smart_actions_debounce_seconds()
        if debounce_window > 0:
            async def _execute_api_call() -> None:
                """Execute the debounced API call."""
                await self._execute_set_temp_api(
                    client, setting, termination, temperature,
                    old_temp, old_mode, old_action,
                )

            await self.coordinator.action_debouncer.debounce(
                self._zone_id, _execute_api_call, window=float(debounce_window),
            )
        else:
            await self._execute_set_temp_api(
                client, setting, termination, temperature,
                old_temp, old_mode, old_action, raise_on_failure=True,
            )

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set new HVAC mode."""
        # Action Guard — skip if mode already matches current state
        if ActionGuard.should_skip_hvac_mode(
            hvac_mode, self._attr_hvac_mode,
            optimistic_active=self._optimistic_sequence is not None,
        ):
            _LOGGER.debug(
                "Action Guard: skip %s set_hvac_mode (already %s)",
                self._zone_name, hvac_mode,
            )
            return

        await _check_bootstrap_reserve_or_raise(self.hass, self._zone_name, coordinator=self.coordinator)

        client = self.coordinator.api_client

        if hvac_mode == HVACMode.HEAT:
            # Local-first: try HomeKit write (only when overlay mode is Tado Default,
            # because HomeKit writes don't carry termination info — #219 mpartington)
            local_success = False
            use_homekit = should_use_homekit_for_overlay(self.hass, self._zone_id, entry_id=self._entry_id)
            write_tracker = self.coordinator.write_health_tracker
            if (
                use_homekit
                and self.coordinator.homekit_provider
                and self.coordinator.homekit_provider.is_connected
                and write_tracker is not None
                and write_tracker.should_try_homekit()
            ):
                import time as _time

                self.coordinator._homekit_write_attempts += 1
                t0 = _time.monotonic()
                try:
                    local_success = await self.coordinator.homekit_provider.set_hvac_mode(
                        self._zone_id, 1,  # 1=Heat
                    )
                except Exception:
                    _LOGGER.debug("HomeKit set_hvac_mode failed for %s", self._zone_name, exc_info=True)
                elapsed_ms = (_time.monotonic() - t0) * 1000
                self.coordinator._homekit_write_latency_sum += elapsed_ms
                self.coordinator._homekit_write_latency_count += 1
                if local_success:
                    self.coordinator._homekit_write_successes += 1
                else:
                    write_tracker.record_failure()
                    self.coordinator._homekit_write_fallbacks += 1
                    _LOGGER.info(
                        "%s: HomeKit set_hvac_mode HEAT failed, falling back to cloud API",
                        self._zone_name,
                    )

            if local_success:
                self.coordinator.record_homekit_write_saved(self._zone_id)
                self._last_write_source = "homekit"
                _LOGGER.info("Set %s to HEAT via HomeKit", self._zone_name)
                self._schedule_cloud_verification()
                return

            # Cloud fallback
            # Capture current state before overlay (state restoration)
            await self.coordinator.async_capture_state(
                self._zone_id, self._entity_type, "set_hvac_mode",
            )

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
            self._last_write_source = "cloud"

        elif hvac_mode == HVACMode.OFF:
            # Local-first: try HomeKit write (only when overlay mode is Tado Default,
            # because HomeKit writes don't carry termination info — #219 mpartington)
            local_success = False
            use_homekit = should_use_homekit_for_overlay(self.hass, self._zone_id, entry_id=self._entry_id)
            write_tracker = self.coordinator.write_health_tracker
            if (
                use_homekit
                and self.coordinator.homekit_provider
                and self.coordinator.homekit_provider.is_connected
                and write_tracker is not None
                and write_tracker.should_try_homekit()
            ):
                import time as _time

                self.coordinator._homekit_write_attempts += 1
                t0 = _time.monotonic()
                try:
                    local_success = await self.coordinator.homekit_provider.set_hvac_mode(
                        self._zone_id, 0,  # 0=Off
                    )
                except Exception:
                    _LOGGER.debug("HomeKit set_hvac_mode OFF failed for %s", self._zone_name, exc_info=True)
                elapsed_ms = (_time.monotonic() - t0) * 1000
                self.coordinator._homekit_write_latency_sum += elapsed_ms
                self.coordinator._homekit_write_latency_count += 1
                if local_success:
                    self.coordinator._homekit_write_successes += 1
                else:
                    write_tracker.record_failure()
                    self.coordinator._homekit_write_fallbacks += 1
                    _LOGGER.info(
                        "%s: HomeKit set_hvac_mode OFF failed, falling back to cloud API",
                        self._zone_name,
                    )

            if local_success:
                self.coordinator.record_homekit_write_saved(self._zone_id)
                self._last_write_source = "homekit"
                _LOGGER.info("Set %s to OFF via HomeKit", self._zone_name)
                self._schedule_cloud_verification()
                return

            # Cloud fallback
            # Capture current state before overlay (state restoration)
            await self.coordinator.async_capture_state(
                self._zone_id, self._entity_type, "set_hvac_mode",
            )

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
            self._last_write_source = "cloud"

        elif hvac_mode == HVACMode.AUTO:
            await api_call_with_rollback(
                self,
                client.delete_zone_overlay(self._zone_id),
                hvac_mode=HVACMode.AUTO,
                hvac_action=HVACAction.IDLE,
                overlay_type=None,
                reason="Set AUTO mode (deleted overlay)",
            )
            self._last_write_source = "cloud"

    async def async_set_timer(
        self, temperature: float, duration_minutes: int | None = None, overlay: str | None = None,
    ) -> bool:
        """Set temperature with timer or overlay type.

        Args:
            temperature: Target temperature in Celsius
            duration_minutes: Duration in minutes (for TIMER termination)
            overlay: Overlay type - 'next_time_block' for TADO_MODE, None for MANUAL


        """
        await _check_bootstrap_reserve_or_raise(self.hass, self._zone_name, coordinator=self.coordinator)

        # Capture current state before overlay (state restoration)
        await self.coordinator.async_capture_state(
            self._zone_id, self._entity_type, "set_timer",
        )

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

        api_success = False
        try:
            async with asyncio.timeout(10):
                api_success = await client.set_zone_overlay(self._zone_id, setting, termination)
        except TimeoutError:
            _LOGGER.warning("Timeout: %s set_timer API call timed out", self._zone_name)
        except Exception as e:
            _LOGGER.warning("Error: %s set_timer API call failed (%s)", self._zone_name, e)

        if api_success:
            _LOGGER.info("Set %s to %s°C %s", self._zone_name, temperature, term_desc)
            await async_trigger_immediate_refresh(self.hass, self.entity_id, "set_timer")
            return True
        return False
