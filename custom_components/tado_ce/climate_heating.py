"""Tado CE heating climate entity — TRV / thermostat control with overlay management.

Carries the optimistic-update + rollback pattern from
`climate_helpers.api_call_with_rollback`, and consults the state
reconciler to merge cloud + HomeKit targets so the bridge can't
push stale values over fresh user actions during the
write-protection window.
"""

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
from homeassistant.helpers.event import async_track_state_change_event

from .climate_helpers import (
    api_call_with_rollback,
    inject_presence_state,
    read_external_sensor,
    setup_climate_external_sensor_subscription,
    unsubscribe_external_sensors,
    update_offset,
    update_offset_clamp,
    update_preset_mode,
)
from .const import (
    CLOUD_VERIFICATION_BUFFER_SECONDS,
    OPEN_WINDOW_DEFAULT_TEMP,
    SIGNAL_HOMEKIT_UPDATE,
    CONF_WINDOW_SENSOR,
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

        # Per-zone min/max temp (set in _update_temp_limits() from zone_config_manager,
        # called on add-to-hass and on every zone-config change)
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
        self._expected_target_temperature: float | None = None

        # Unsubscribe callback for zone config changes
        self._unsub_zone_config = None

        # Unsubscribe callbacks for external sensor state change listeners
        self._unsub_external_sensors: list[CALLBACK_TYPE] = []

        # Cloud verification timer handle
        self._cloud_verification_handle: asyncio.TimerHandle | None = None

        # Unsubscribe callback for HomeKit dispatcher signal
        self._unsub_homekit_signal: Callable[[], None] | None = None

        # STAP 3.1: Status van voor het geopende raam onthouden
        self._saved_hvac_mode: HVACMode | None = None

    # ------------------------------------------------------------------
    # Public API (TadoZoneEntity Protocol — see entity_types.py)
    # ------------------------------------------------------------------

    @property
    def zone_id(self) -> str:
        """Return the Tado zone ID as a string."""
        return str(self._zone_id)

    @property
    def zone_type(self) -> str:
        """Return the zone type — always HEATING for this entity."""
        return "HEATING"

    @property
    def entity_type(self) -> str:
        """Return the entity type tag for state-capture routing."""
        return self._entity_type

    def _calculate_hvac_action(self, target_temp: float | None = None) -> HVACAction:
        """Calculate hvac_action for heating zone."""
        if self._attr_hvac_mode == HVACMode.OFF:
            return HVACAction.OFF

        if target_temp is not None and self._attr_hvac_mode == HVACMode.HEAT:
            return HVACAction.HEATING

        if self._expected_hvac_action is not None:
            return self._expected_hvac_action

        if self._heating_power and self._heating_power > 0:
            return HVACAction.HEATING

        if self._attr_hvac_mode == HVACMode.HEAT:
            target = self._attr_target_temperature
            current = self._attr_current_temperature
            if target is not None and current is not None:
                if target > current + 0.5:
                    return HVACAction.HEATING

        return HVACAction.IDLE

    async def async_added_to_hass(self) -> None:
        """Register listeners when entity is added to hass."""
        await super().async_added_to_hass()

        # Restore last known target temperature across HA restarts
        last_state = await self.async_get_last_state()
        if last_state and last_state.attributes.get(ATTR_TEMPERATURE) is not None:
            self._attr_target_temperature = last_state.attributes[ATTR_TEMPERATURE]
            _LOGGER.debug(
                "Climate Heating: %s restored target %s°C from previous HA state",
                self._zone_name,
                self._attr_target_temperature,
            )
        elif self._attr_target_temperature is None:
            self._attr_target_temperature = 20.0
            _LOGGER.debug(
                "Climate Heating: %s has no previous state — defaulting target to %s°C",
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
                    _LOGGER.debug(
                        "Climate Heating: %s zone config %s changed to %s",
                        self._zone_name, key, value,
                    )

            self._unsub_zone_config = zone_config_manager.add_listener(_handle_zone_config_change)  # type: ignore[assignment]
            self._update_temp_limits()

        # Subscribe to external sensor state changes for real-time updates
        self._subscribe_external_sensors()

        # Subscribe to HomeKit dispatcher signal for real-time sensor updates
        self._unsub_homekit_signal = async_dispatcher_connect(
            self.hass,
            SIGNAL_HOMEKIT_UPDATE.format(home_id=self._home_id),
            self._handle_homekit_update,
        )

        # STAP 3.2: Luisteren naar de gekoppelde raamsensor uit de opties
        window_sensor_id = self.coordinator.config_entry.options.get(CONF_WINDOW_SENSOR)
        if window_sensor_id:
            _LOGGER.debug("Raamsensor %s gekoppeld aan zone %s", window_sensor_id, self._zone_name)
            self.async_on_remove(
                async_track_state_change_event(
                    self.hass, [window_sensor_id], self._async_window_state_changed
                )
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

    # STAP 3.3: De Schakel-logica voor ramen open/dicht
    async def _async_window_state_changed(self, event) -> None:
        """Verwerk de statusverandering van de raamsensor."""
        new_state = event.data.get("new_state")
        if new_state is None:
            return

        # Raam gaat OPEN -> Verwarming UIT
        if new_state.state == "on" and self.hvac_mode != HVACMode.OFF:
            self._saved_hvac_mode = self.hvac_mode
            _LOGGER.info("Raam geopend in %s, verwarming wordt uitgeschakeld", self._zone_name)
            await self.async_turn_off()

        # Raam gaat DICHT -> Herstel de oude status
        elif new_state.state == "off":
            target_mode = self._saved_hvac_mode if self._saved_hvac_mode else HVACMode.AUTO
            _LOGGER.info("Raam gesloten in %s, status wordt hersteld naar %s", self._zone_name, target_mode)
            await self.async_set_hvac_mode(target_mode)
            self._saved_hvac_mode = None  # Reset de opgeslagen status

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

        reconciler = self.coordinator.state_reconciler
        provider = self.coordinator.homekit_provider
        if reconciler and provider and provider.is_connected:
            reconciler.local_provider = provider

            zcm = self.coordinator.zone_config_manager
            display_source = zcm.get_zone_value(self._zone_id, "display_temp_source", "auto") if zcm else "auto"
            cloud_target = self._attr_target_temperature
            merged_target, target_src = reconciler.merge_zone_target_temperature(
                self._zone_id, cloud_target, display_source=display_source,
            )
            if merged_target is not None and merged_target != self._attr_target_temperature:
                self._attr_target_temperature = merged_target
                _LOGGER.debug(
                    "Climate Heating: %s target %s → %s°C (source %s)",
                    self._zone_name, cloud_target, merged_target, target_src,
                )

        self.async_write_ha_state()

        if self._attr_target_temperature is not None:
            self._schedule_heating_cycle_update(self._attr_target_temperature)

    @callback
    def _update_temp_limits(self) -> None:
        """Update min/max temp from zone config."""
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
        if self._offset_celsius is not None:
            attrs["offset_celsius"] = self._offset_celsius
            clamp_direction = update_offset_clamp(self.coordinator, self._zone_id)
            if clamp_direction is not None:
                attrs["offset_clamped"] = clamp_direction != "none"
                attrs["offset_clamp_direction"] = clamp_direction

        scheduled_temp = get_current_schedule_target(self._zone_id, data_loader=self.coordinator.data_loader)
        if scheduled_temp is not None:
            attrs["scheduled_target_temperature"] = scheduled_temp

        controller = self.coordinator.valve_controllers.get(self._zone_id)
        if controller is not None:
            attrs.update(controller.get_attributes())
        else:
            os_controller = self.coordinator.offset_sync_controllers.get(self._zone_id)
            if os_controller is not None:
                attrs.update(os_controller.get_attributes())
            else:
                attrs["valve_control_active"] = False

        return attrs

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle coordinator data update."""
        self.update()
        self.async_write_ha_state()

    def _update_sensor_data(self, zone_data: dict[str, Any]) -> None:
        """Extract sensor data with priority: external > homekit > cloud."""
        sensor_data = zone_data.get("sensorDataPoints") or {}
        cloud_temp = (sensor_data.get("insideTemperature") or {}).get("celsius")
        cloud_humidity = (sensor_data.get("humidity") or {}).get("percentage")

        zcm = self.coordinator.zone_config_manager
        ext_temp = read_external_sensor(self.hass, zcm, self._zone_id, "external_temp_sensor")
        ext_hum = read_external_sensor(self.hass, zcm, self._zone_id, "external_humidity_sensor")

        reconciler = self.coordinator.state_reconciler
        provider = self.coordinator.homekit_provider
        if reconciler and provider and provider.is_connected:
            reconciler.local_provider = provider
            display_source = zcm.get_zone_value(self._zone_id, "display_temp_source", "auto") if zcm else "auto"
            merged_temp, temp_source = reconciler.merge_zone_temperature(
                self._zone_id, cloud_temp, external_value=ext_temp,
                display_source=display_source, purpose="display",
            )
            merged_hum, hum_source = reconciler.merge_zone_humidity(self._zone_id, cloud_humidity, external_value=ext_hum)
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

        if temp_source != getattr(self, "_prev_temp_source", None) or hum_source != getattr(self, "_prev_hum_source", None):
            _LOGGER.debug(
                "Climate Heating: %s merge — temp=%s (%s), humidity=%s (%s)",
                self._zone_name, merged_temp, temp_source, merged_hum, hum_source,
            )
            self._prev_temp_source = temp_source
            self._prev_hum_source = hum_source

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

        if self._overlay_type == "MANUAL":
            self._attr_target_temperature = OPEN_WINDOW_DEFAULT_TEMP
        else:
            scheduled = get_current_schedule_target(self._zone_id, data_loader=self.coordinator.data_loader)
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
            try:
                await heating_cycle_coordinator.on_zone_update(_zone_id, temp, _current_temp)
            except (KeyError, TypeError, ValueError):
                _LOGGER.debug("Climate Heating: %s heating-cycle update failed", _zone_name, exc_info=True)

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
        self,
        api_hvac_mode: HVACMode,
        api_hvac_action: HVACAction,
        power: str | None,
        api_target_temperature: float | None = None,
    ) -> None:
        """Apply optimistic or API state based on sequence comparison."""
        api_values: dict[str, Any] = {"hvac_mode": api_hvac_mode, "hvac_action": api_hvac_action}
        if api_target_temperature is not None:
            api_values["target_temperature"] = api_target_temperature

        result = resolve_optimistic_update(self, api_values=api_values, entry_id=self._entry_id)

        if result == OptimisticUpdateResult.PRESERVE_OPTIMISTIC:
            self._attr_hvac_mode = self._expected_hvac_mode
            self._attr_hvac_action = self._expected_hvac_action
            if self._expected_target_temperature is not None:
                self._attr_target_temperature = self._expected_target_temperature
        else:
            if result == OptimisticUpdateResult.EXPIRED:
                _LOGGER.warning(
                    "Climate Heating: %s — Tado did not confirm change, reverting.", self._zone_name
                )
                if self._last_write_source == "homekit":
                    write_tracker = self.coordinator.write_health_tracker
                    if write_tracker is not None:
                        write_tracker.record_failure()
                    self._last_write_source = ""
            elif result == OptimisticUpdateResult.ACCEPT_API and self._last_write_source == "homekit":
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
            _LOGGER.debug("Climate Heating: %s could not record Smart Comfort data (%s)", self._zone_name, e)

    @callback
    def update(self) -> None:
        """Update climate state from the coordinator's cached zone data."""
        if self.coordinator.is_entity_fresh(self.entity_id):
            if self._attr_current_temperature is not None:
                return

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

            activity_data = zone_data.get("activityDataPoints") or {}
            self._heating_power = (activity_data.get("heatingPower") or {}).get("percentage", 0)

            setting = zone_data.get("setting") or {}
            power = setting.get("power")
            api_hvac_mode = self._determine_api_hvac_mode(power, zone_data)
            api_target_temp = (setting.get("temperature") or {}).get("celsius")

            old_hvac_mode = self._attr_hvac_mode
            self._attr_hvac_mode = api_hvac_mode
            api_hvac_action = self._calculate_hvac_action()
            self._attr_hvac_mode = old_hvac_mode

            self._apply_optimistic_or_api_state(
                api_hvac_mode, api_hvac_action, power, api_target_temperature=api_target_temp
            )
            self._attr_available = True
            self._record_smart_comfort()
            self._update_preset_mode()
            self._update_offset()

        except Exception as e:
            _LOGGER.warning("Climate Heating: %s update failed (%s)", self.name, e)
            self._attr_available = False

    @callback
    def _update_offset(self) -> None:
        """Update temperature offset from cached offsets file."""
        self._offset_celsius = update_offset(self.coordinator, self._zone_id)  # type: ignore[assignment]

    @callback
    def _update_preset_mode(self) -> None:
        """Update preset mode based on home state."""
        result = update_preset_mode(self.coordinator)
        if result is not None:
            self._attr_preset_mode = result

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        """Set preset mode (Home/Away)."""
        if ActionGuard.should_skip_preset_mode(preset_mode, self._attr_preset_mode):
            _LOGGER.debug("Climate Heating: %s preset already %s — skipping", self._zone_name, preset_mode)
            return

        await _check_bootstrap_reserve_or_raise(self.hass, self._zone_name, coordinator=self.coordinator)
        client = self.coordinator.api_client
        state = "AWAY" if preset_mode == PRESET_AWAY else "HOME"

        old_preset = self._attr_preset_mode
        self._attr_preset_mode = preset_mode
        self._optimistic_set_at = time.monotonic()
        self.async_write_ha_state()

        api_success = False
        try:
            async with asyncio.timeout(10):
                api_success = await client.set_presence_lock(state)
        except Exception as e:
            _LOGGER.warning("Climate Heating: %s preset-mode call failed (%s)", self._zone_name, e)

        if api_success:
            _LOGGER.info("Climate Heating: %s set preset mode to %s", self._zone_name, preset_mode)
            await self.coordinator.async_request_refresh()
        else:
            self._attr_preset_mode = old_preset
            self.async_write_ha_state()

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set new target temperature."""
        if (temperature := kwargs.get(ATTR_TEMPERATURE)) is None:
            return

        await _check_bootstrap_reserve_or_raise(self.hass, self._zone_name, coordinator=self.coordinator)
        client = self.coordinator.api_client

        old_temp = self._attr_target_temperature
        self._attr_target_temperature = temperature
        self._expected_target_temperature = temperature
        self._optimistic_set_at = time.monotonic()
        self.async_write_ha_state()

        try:
            async with asyncio.timeout(10):
                await client.set_zone_overlay(self._zone_id, "MANUAL", temperature=temperature)
            _LOGGER.info("Climate Heating: Set temperature to %s°C in %s", temperature, self._zone_name)
            await self.coordinator.async_request_refresh()
        except Exception as e:
            _LOGGER.error("Climate Heating: Failed to set temperature for %s: %s", self._zone_name, e)
            self._attr_target_temperature = old_temp
            self._expected_target_temperature = old_temp
            self.async_write_ha_state()

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set new target hvac mode."""
        if hvac_mode == HVACMode.OFF:
            await self.async_turn_off()
            return

        await _check_bootstrap_reserve_or_raise(self.hass, self._zone_name, coordinator=self.coordinator)
        client = self.coordinator.api_client

        old_mode = self._attr_hvac_mode
        self._attr_hvac_mode = hvac_mode
        self._optimistic_set_at = time.monotonic()
        self.async_write_ha_state()

        try:
            async with asyncio.timeout(10):
                if hvac_mode == HVACMode.AUTO:
                    await client.delete_zone_overlay(self._zone_id)
                elif hvac_mode == HVACMode.HEAT:
                    temp = self._attr_target_temperature or 20.0
                    await client.set_zone_overlay(self._zone_id, "MANUAL", temperature=temp)
            _LOGGER.info("Climate Heating: Set HVAC mode to %s in %s", hvac_mode, self._zone_name)
            await self.coordinator.async_request_refresh()
        except Exception as e:
            _LOGGER.error("Climate Heating: Failed to set HVAC mode for %s: %s", self._zone_name, e)
            self._attr_hvac_mode = old_mode
            self.async_write_ha_state()

    async def async_turn_off(self) -> None:
        """Turn the climate device off."""
        await _check_bootstrap_reserve_or_raise(self.hass, self._zone_name, coordinator=self.coordinator)
        client = self.coordinator.api_client

        old_mode = self._attr_hvac_mode
        self._attr_hvac_mode = HVACMode.OFF
        self._optimistic_set_at = time.monotonic()
        self.async_write_ha_state()

        try:
            async with asyncio.timeout(10):
                await client.set_zone_overlay(self._zone_id, "MANUAL", power="OFF")
            _LOGGER.info("Climate Heating: Turned off heating in %s", self._zone_name)
            await self.coordinator.async_request_refresh()
        except Exception as e:
            _LOGGER.error("Climate Heating: Failed to turn off heating for %s: %s", self._zone_name, e)
            self._attr_hvac_mode = old_mode
            self.async_write_ha_state()

    async def async_turn_on(self) -> None:
        """Turn the climate device on."""
        await self.async_set_hvac_mode(HVACMode.AUTO)
