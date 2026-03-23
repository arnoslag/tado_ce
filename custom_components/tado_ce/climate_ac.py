"""Tado CE Air Conditioning Climate Entity — AC mode, fan speed, swing control."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from homeassistant.components.climate import ATTR_HVAC_MODE, ClimateEntity  # type: ignore[attr-defined]
from homeassistant.components.climate.const import (
    FAN_AUTO,
    FAN_HIGH,
    FAN_LOW,
    FAN_MEDIUM,
    SWING_ON,
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
from .climate_helpers import api_call_with_rollback, read_external_sensor
from .climate_maps import (
    HA_TO_TADO_FAN,
    HA_TO_TADO_HVAC_MODE,
    TADO_TO_HA_FAN,
    TADO_TO_HA_HVAC_MODE,
    build_fan_mapping,
)
from .device_manager import get_zone_device_info
from .entity_registry import ENTITY_REGISTRY
from .format_helpers import (
    format_overlay_type as _format_overlay_type,
)
from .format_helpers import (
    format_zone_type as _format_zone_type,
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
from .write_optimizer import ActionGuard, get_current_schedule_target

if TYPE_CHECKING:
    from .coordinator import TadoDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)


class TadoACClimate(CoordinatorEntity["TadoDataUpdateCoordinator"], ClimateEntity, RestoreEntity):
    """Tado CE Air Conditioning Climate Entity."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: TadoDataUpdateCoordinator,
        zone_id: str,
        zone_name: str,
        capabilities: dict[str, Any],
        home_id: str,
    ) -> None:
        """Initialize."""
        super().__init__(coordinator)
        self._zone_id = zone_id
        self._zone_name = zone_name
        self._home_id = home_id
        self._capabilities = capabilities
        self._entry_id = coordinator.config_entry.entry_id
        self._entity_type = "climate_ac"

        _meta = ENTITY_REGISTRY["climate_ac"]
        self._attr_name = None
        self._attr_translation_key = _meta.translation_key
        self._attr_unique_id = f"tado_ce_{home_id}_{_meta.unique_id_suffix.format(zone_id=zone_id)}"
        self._attr_temperature_unit = UnitOfTemperature.CELSIUS
        self._attr_device_info = get_zone_device_info(zone_id, zone_name, "AIR_CONDITIONING", home_id)

        # Get AC capabilities from dedicated API endpoint
        # Format: {"COOL": {...}, "HEAT": {...}, "DRY": {...}, "FAN": {...}, "AUTO": {...}}
        # Use 'or {}' pattern for null safety
        ac_caps = capabilities.get("ac_capabilities") or {}

        # Build supported features based on capabilities
        features = (
            ClimateEntityFeature.TARGET_TEMPERATURE | ClimateEntityFeature.TURN_OFF | ClimateEntityFeature.TURN_ON
        )

        # Check if any mode has fan levels (fanLevel = newer firmware, fanSpeeds = older firmware)
        has_fan = any(
            (ac_caps.get(mode) or {}).get("fanLevel") or (ac_caps.get(mode) or {}).get("fanSpeeds")
            for mode in ["COOL", "HEAT", "DRY", "FAN", "AUTO"]
        )
        if has_fan:
            features |= ClimateEntityFeature.FAN_MODE

        # Check if any mode has swing options
        has_swing = any(
            (ac_caps.get(mode) or {}).get("verticalSwing") or (ac_caps.get(mode) or {}).get("horizontalSwing")
            for mode in ["COOL", "HEAT", "DRY", "FAN", "AUTO"]
        )
        if has_swing:
            features |= ClimateEntityFeature.SWING_MODE

        self._attr_supported_features = features

        # Build HVAC modes based on capabilities
        # Removed HVACMode.AUTO from AC to avoid confusion
        # - HVACMode.AUTO in HA means "follow schedule" (delete overlay)
        # - Users confused it with Tado's AUTO mode (heat/cool as needed)
        # - Tado's AUTO = HA's HEAT_COOL
        # - AC users can still delete overlay via Resume Schedule button
        self._attr_hvac_modes = [HVACMode.OFF]

        # Add modes that exist in capabilities
        for tado_mode in ["COOL", "HEAT", "DRY", "FAN"]:
            if tado_mode in ac_caps:
                ha_mode = TADO_TO_HA_HVAC_MODE.get(tado_mode)
                if ha_mode and ha_mode not in self._attr_hvac_modes:
                    self._attr_hvac_modes.append(ha_mode)

        # If AUTO mode exists in capabilities, add HEAT_COOL
        # Tado's AUTO = HA's HEAT_COOL (heat or cool as needed)
        if "AUTO" in ac_caps:
            if HVACMode.HEAT_COOL not in self._attr_hvac_modes:
                self._attr_hvac_modes.append(HVACMode.HEAT_COOL)

        _LOGGER.debug("AC zone %s HVAC modes: %s", zone_id, self._attr_hvac_modes)

        # Fan modes - collect from all modes that have fanLevel or fanSpeeds (legacy firmware)
        fan_levels = set()
        for mode_caps in ac_caps.values():
            if isinstance(mode_caps, dict):
                if "fanLevel" in mode_caps:
                    fan_levels.update(mode_caps["fanLevel"])
                elif "fanSpeeds" in mode_caps:
                    fan_levels.update(mode_caps["fanSpeeds"])

        if fan_levels:
            # Dynamic per-zone fan mapping
            # Build bidirectional mapping from actual capabilities instead of static lookup.
            # Different AC brands use different fan level names:
            #   Mitsubishi: ONE, TWO, THREE, FOUR, AUTO
            #   Fujitsu:    ONE, TWO, THREE, FOUR, AUTO
            #   Older units: LEVEL1, LEVEL2, LEVEL3, LEVEL4, LEVEL5, AUTO
            #   Legacy:      LOW, MIDDLE, HIGH, AUTO
            # Strategy: sort non-AUTO levels, divide evenly into low/medium/high buckets.
            self._tado_to_ha_fan, self._ha_to_tado_fan = build_fan_mapping(fan_levels)
            self._attr_fan_modes = list(dict.fromkeys(self._tado_to_ha_fan.values()))  # dedupe
            _LOGGER.debug(
                "AC zone %s fan modes: %s (from %s), ha→tado: %s",
                zone_id,
                self._attr_fan_modes,
                fan_levels,
                self._ha_to_tado_fan,
            )
        else:
            self._tado_to_ha_fan = dict(TADO_TO_HA_FAN)
            self._ha_to_tado_fan = dict(HA_TO_TADO_FAN)
            self._attr_fan_modes = [FAN_AUTO, FAN_LOW, FAN_MEDIUM, FAN_HIGH]

        # Swing modes - dynamically built from capabilities
        # Don't hardcode swing options - different AC units have different supported values
        # Some units (e.g., Mitsubishi) don't support "OFF" as a swing value
        if has_swing:
            # Collect all supported swing values across all modes
            all_v_swings = set()
            all_h_swings = set()
            for mode in ["COOL", "HEAT", "DRY", "FAN", "AUTO"]:
                mode_caps = ac_caps.get(mode) or {}
                if "verticalSwing" in mode_caps:
                    all_v_swings.update(mode_caps["verticalSwing"])
                if "horizontalSwing" in mode_caps:
                    all_h_swings.update(mode_caps["horizontalSwing"])

            # Build swing_modes based on actual capabilities
            swing_modes = []
            has_v_off = "OFF" in all_v_swings
            has_h_off = "OFF" in all_h_swings
            has_v_on = any(v != "OFF" for v in all_v_swings)
            has_h_on = any(h != "OFF" for h in all_h_swings)

            # "off" option - only if at least one swing type supports OFF
            if has_v_off or has_h_off or (not all_v_swings and not all_h_swings):
                swing_modes.append("off")

            # "vertical" option - only if vertical swing has non-OFF values
            if has_v_on:
                swing_modes.append("vertical")

            # "horizontal" option - only if horizontal swing has non-OFF values
            if has_h_on:
                swing_modes.append("horizontal")

            # "both" option - only if both have non-OFF values
            if has_v_on and has_h_on:
                swing_modes.append("both")

            self._attr_swing_modes = swing_modes or ["off"]
            _LOGGER.debug(
                "AC zone %s swing modes: %s (v_swings=%s, h_swings=%s)",
                zone_id,
                self._attr_swing_modes,
                all_v_swings,
                all_h_swings,
            )
        else:
            self._attr_swing_modes = None

        # Temperature range from capabilities
        # Get from any mode that has temperatures (COOL is most common)
        temp_caps = None
        for mode in ["COOL", "HEAT", "AUTO", "DRY"]:
            if mode in ac_caps and "temperatures" in ac_caps[mode]:
                # Use 'or {}' pattern for null safety
                temp_caps = ac_caps[mode]["temperatures"].get("celsius") or {}
                break

        if temp_caps:
            self._attr_min_temp = temp_caps.get("min", 16)
            self._attr_max_temp = temp_caps.get("max", 30)
            self._attr_target_temperature_step = temp_caps.get("step", 1)
        else:
            self._attr_min_temp = 16
            self._attr_max_temp = 30
            self._attr_target_temperature_step = 1

        self._attr_current_temperature = None
        self._attr_target_temperature = None
        self._attr_hvac_mode = None
        self._attr_hvac_action = None
        # Set default fan/swing modes to suppress HA startup validation warnings
        # HA validates that current mode is in the modes list, so we set valid defaults
        self._attr_fan_mode = self._attr_fan_modes[0] if self._attr_fan_modes else None
        self._attr_swing_mode = self._attr_swing_modes[0] if self._attr_swing_modes else None
        self._attr_available = False
        self._attr_current_humidity = None

        self._overlay_type = None
        self._ac_power_percentage = None

        # External sensor override tracking
        self._temperature_source = "tado"
        self._humidity_source = "tado"
        self._external_temp_sensor = ""
        self._external_humidity_sensor = ""

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

        # Unsubscribe callback for AC capabilities updated signal
        self._unsub_ac_caps = None

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
        AC passes fan_mode/swing_mode as extra_attrs.
        """
        await set_optimistic_state(
            self,
            hvac_mode,
            hvac_action,
            target_temp=target_temp,
            extra_attrs={
                "fan_mode": self._attr_fan_mode,
                "swing_mode": self._attr_swing_mode,
            },
        )

    def _calculate_hvac_action(self, hvac_mode: HVACMode | None = None, ac_power_on: bool | None = None) -> HVACAction:
        """Calculate hvac_action for AC zone.

        Updated for optimistic update fix.

        Priority:
        1. If hvac_mode == OFF → OFF
        2. If in optimistic window with expected action → return expected action
        3. If API confirms AC is off → IDLE
        4. Mode-based action (COOL→COOLING, HEAT→HEATING, etc.)

        Args:
            hvac_mode: Optional mode for optimistic updates.
                      If None, uses self._attr_hvac_mode.
            ac_power_on: Optional AC power state from API.
                        If None, assumes AC is ON (for optimistic updates).
                        If False, returns IDLE (API confirms AC is off).

        Returns:
            HVACAction based on mode (COOLING, HEATING, DRYING, FAN, IDLE, or OFF)

        """
        mode = hvac_mode if hvac_mode is not None else self._attr_hvac_mode

        # OFF mode always returns OFF
        if mode == HVACMode.OFF:
            return HVACAction.OFF

        # If we have optimistic state with expected action, use it
        # This ensures optimistic updates work immediately
        if self._expected_hvac_action is not None:
            return self._expected_hvac_action

        # If API confirms AC is off, return IDLE
        if ac_power_on is False:
            return HVACAction.IDLE

        # Mode-based action (AC is ON or assumed ON for optimistic)
        if mode == HVACMode.COOL:
            return HVACAction.COOLING
        if mode == HVACMode.HEAT:
            return HVACAction.HEATING
        if mode == HVACMode.DRY:
            return HVACAction.DRYING
        if mode == HVACMode.FAN_ONLY:
            return HVACAction.FAN
        if mode == HVACMode.HEAT_COOL:
            # Tado AUTO mode - AC decides to heat or cool as needed
            return HVACAction.IDLE

        return HVACAction.IDLE

    async def async_added_to_hass(self) -> None:
        """Register listeners when entity is added to hass.

        CoordinatorEntity handles update subscription
        automatically — removed manual SIGNAL_ZONES_UPDATED and
        SIGNAL_AC_CAPABILITIES_UPDATED dispatcher signals.
        AC capabilities now read from coordinator.data["ac_capabilities"]
        in _handle_coordinator_update().
        Zone config listener retained (not a coordinator update).
        """
        await super().async_added_to_hass()

        # Restore last known target temperature across HA restarts (#182)
        last_state = await self.async_get_last_state()
        if last_state and last_state.attributes.get(ATTR_TEMPERATURE) is not None:
            self._attr_target_temperature = last_state.attributes[ATTR_TEMPERATURE]
            _LOGGER.debug(
                "AC %s: Restored target temperature %s from previous state",
                self._zone_name,
                self._attr_target_temperature,
            )
        elif self._attr_target_temperature is None:
            # First install or no previous state — default to 24°C so climate
            # card controls are usable immediately (#182 follow-up)
            self._attr_target_temperature = 24.0
            _LOGGER.debug(
                "AC %s: No previous state, defaulting target temperature to %s",
                self._zone_name,
                self._attr_target_temperature,
            )

        # Listen for zone config changes
        zone_config_manager = self.coordinator.zone_config_manager
        if zone_config_manager:

            @callback
            def _handle_zone_config_change(zone_id: str, key: str, value: Any) -> None:  # noqa: ANN401 — zone config values are heterogeneous
                """Handle zone config change."""
                if zone_id == self._zone_id and key in ("min_temp", "max_temp"):
                    self._update_temp_limits()
                    self.async_write_ha_state()
                    _LOGGER.debug("AC %s: Zone config %s changed to %s", self._zone_name, key, value)

            self._unsub_zone_config = zone_config_manager.add_listener(_handle_zone_config_change)  # type: ignore[assignment]
            # Initial update of temp limits
            self._update_temp_limits()

        # Subscribe to external sensor state changes for real-time updates
        self._subscribe_external_sensors()

    async def async_will_remove_from_hass(self) -> None:
        """Unregister listeners when entity is removed.

        CoordinatorEntity handles update unsubscription.
        Only zone config and external sensor listeners need manual cleanup.
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
            _LOGGER.debug("AC %s: External sensor updated → refreshed climate state", self._zone_name)

        unsub = async_track_state_change_event(self.hass, entity_ids, _handle_external_sensor_change)
        self._unsub_external_sensors.append(unsub)
        _LOGGER.debug("AC %s: Subscribed to external sensor updates: %s", self._zone_name, entity_ids)

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
        If user never set min/max_temp in Zone Configuration, use API
        capabilities directly — avoids DEFAULT_ZONE_CONFIG (25°C max)
        capping AC zones that support up to 30°C (fixes #180).
        """
        zone_config_manager = self.coordinator.zone_config_manager
        if zone_config_manager:
            caps_min = self._get_capabilities_temp_limit("min", 16)
            caps_max = self._get_capabilities_temp_limit("max", 30)

            if zone_config_manager.has_zone_override(self._zone_id, "min_temp"):
                # User explicitly set min_temp — clamp to hardware minimum
                user_min = zone_config_manager.get_zone_value(self._zone_id, "min_temp", caps_min)
                self._attr_min_temp = max(float(user_min), caps_min)
            else:
                self._attr_min_temp = caps_min

            if zone_config_manager.has_zone_override(self._zone_id, "max_temp"):
                # User explicitly set max_temp — clamp to hardware maximum
                user_max = zone_config_manager.get_zone_value(self._zone_id, "max_temp", caps_max)
                self._attr_max_temp = min(float(user_max), caps_max)
            else:
                self._attr_max_temp = caps_max

    def _get_capabilities_temp_limit(self, limit_type: str, default: float) -> float:
        """Get temperature limit from AC capabilities.

        Args:
            limit_type: 'min' or 'max'
            default: Default value if not found in capabilities

        Returns:
            Temperature limit from capabilities or default

        """
        ac_caps = self._capabilities.get("ac_capabilities") or {}
        for mode in ["COOL", "HEAT", "AUTO", "DRY"]:
            if mode in ac_caps and "temperatures" in ac_caps[mode]:
                temp_caps = ac_caps[mode]["temperatures"].get("celsius") or {}
                if limit_type in temp_caps:
                    return temp_caps[limit_type]  # type: ignore[no-any-return]
        return default

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return extra state attributes."""
        attrs: dict[str, Any] = {
            "overlay_type": _format_overlay_type(self._overlay_type),
            "ac_power_percentage": self._ac_power_percentage,
            "zone_id": self._zone_id,
            "zone_type": _format_zone_type("AIR_CONDITIONING"),
            "temperature_source": self._temperature_source,
            "humidity_source": self._humidity_source,
            "external_temp_sensor": self._external_temp_sensor,
            "external_humidity_sensor": self._external_humidity_sensor,
        }
        # Schedule Preview — show current schedule target temperature
        scheduled_temp = get_current_schedule_target(
            self._zone_id,
            data_loader=self.coordinator.data_loader,
        )
        if scheduled_temp is not None:
            attrs["scheduled_target_temperature"] = scheduled_temp
        return attrs

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle coordinator data update.

        Replaces manual SIGNAL_ZONES_UPDATED and
        SIGNAL_AC_CAPABILITIES_UPDATED handlers. CoordinatorEntity calls
        this automatically after each coordinator poll.
        Also reloads AC capabilities from coordinator.data if changed.
        """
        # Reload AC capabilities from coordinator data (replaces SIGNAL_AC_CAPABILITIES_UPDATED)
        coord_data = self.coordinator.data or {}
        ac_caps_all = coord_data.get("ac_capabilities") or {}
        zone_caps = ac_caps_all.get(self._zone_id)
        if zone_caps and zone_caps != self._capabilities.get("ac_capabilities"):
            self._capabilities["ac_capabilities"] = zone_caps
            # Rebuild fan mapping from new capabilities
            fan_levels = set()
            for mode_caps in zone_caps.values():
                if isinstance(mode_caps, dict):
                    if "fanLevel" in mode_caps:
                        fan_levels.update(mode_caps["fanLevel"])
                    elif "fanSpeeds" in mode_caps:
                        fan_levels.update(mode_caps["fanSpeeds"])
            if fan_levels:
                self._tado_to_ha_fan, self._ha_to_tado_fan = build_fan_mapping(fan_levels)
                self._attr_fan_modes = list(dict.fromkeys(self._tado_to_ha_fan.values()))
                _LOGGER.info("AC %s: Rebuilt fan mapping: %s", self._zone_name, self._ha_to_tado_fan)

        self.update()
        self.async_write_ha_state()

    @callback
    def update(self) -> None:
        """Update AC climate state from JSON file."""
        # This prevents unnecessary file I/O and processing when entity has recent API call
        if self.coordinator.is_entity_fresh(self.entity_id):
            _LOGGER.debug("AC %s: Skipping update (entity is fresh)", self._zone_name)
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

            # AC power state - API returns {'value': 'ON'/'OFF'} not percentage
            activity_data = zone_data.get("activityDataPoints") or {}
            ac_power = activity_data.get("acPower") or {}
            ac_power_value = ac_power.get("value")  # 'ON' or 'OFF'
            # Keep percentage for backwards compatibility attribute
            self._ac_power_percentage = ac_power.get("percentage")

            # Setting
            setting = zone_data.get("setting") or {}
            power = setting.get("power")
            self._overlay_type = zone_data.get("overlayType")

            if power == "ON":
                # Temperature
                temp = (setting.get("temperature") or {}).get("celsius")
                self._attr_target_temperature = temp

                # Mode
                tado_mode = setting.get("mode")
                self._attr_hvac_mode = TADO_TO_HA_HVAC_MODE.get(tado_mode, HVACMode.AUTO)  # type: ignore[arg-type]

                # Fan - API returns fanLevel (newer firmware) or fanSpeed (older firmware)
                # Use per-zone dynamic mapping instead of static global
                fan_level = setting.get("fanLevel") or setting.get("fanSpeed")
                self._attr_fan_mode = self._tado_to_ha_fan.get(fan_level) or TADO_TO_HA_FAN.get(fan_level, FAN_AUTO)  # type: ignore[arg-type]

                # Swing - API returns verticalSwing/horizontalSwing (not swing)
                # Don't assume "OFF" is valid - check capabilities
                # Map to unified swing mode: off/vertical/horizontal/both
                vertical_swing = setting.get("verticalSwing")  # None if not present
                horizontal_swing = setting.get("horizontalSwing")  # None if not present

                # Determine if swing is "on" - any value that's not OFF or None
                v_on = vertical_swing is not None and vertical_swing != "OFF"
                h_on = horizontal_swing is not None and horizontal_swing != "OFF"

                if v_on and h_on:
                    self._attr_swing_mode = "both"
                elif v_on:
                    self._attr_swing_mode = "vertical"
                elif h_on:
                    self._attr_swing_mode = "horizontal"
                else:
                    # Default to first available swing mode (may not be "off" for some units)
                    self._attr_swing_mode = self._attr_swing_modes[0] if self._attr_swing_modes else "off"

                # HVAC action - based on acPower.value ('ON'/'OFF')
                ac_power_on = ac_power_value == "ON"
                api_hvac_action = self._calculate_hvac_action(hvac_mode=self._attr_hvac_mode, ac_power_on=ac_power_on)

                # Sequence-based optimistic state handling
                # Delegates to shared optimistic.resolve_optimistic_vs_api()
                should_preserve = resolve_optimistic_vs_api(self, self._attr_hvac_mode, api_hvac_action)

                # Apply state based on preservation decision
                if should_preserve:
                    # Keep optimistic mode and action until API confirms
                    self._attr_hvac_mode = self._expected_hvac_mode
                    self._attr_hvac_action = self._expected_hvac_action
                    # Also restore fan/swing from optimistic state (HIGH-1)
                    if self._optimistic_state:
                        if self._optimistic_state.get("fan_mode") is not None:
                            self._attr_fan_mode = self._optimistic_state["fan_mode"]
                        if self._optimistic_state.get("swing_mode") is not None:
                            self._attr_swing_mode = self._optimistic_state["swing_mode"]
                    _LOGGER.debug(
                        "AC %s: Using optimistic state: mode=%s, action=%s",
                        self._zone_name,
                        self._attr_hvac_mode,
                        self._attr_hvac_action,
                    )
                else:
                    self._attr_hvac_action = api_hvac_action
            # Power is OFF - keep last temperature for reference
            # Sequence-based optimistic state handling for AC OFF
            elif self._optimistic_sequence is not None:
                if self._expected_hvac_mode == HVACMode.OFF:
                    # We expected OFF and API confirms OFF - clear optimistic state
                    _LOGGER.debug("AC %s: API confirmed OFF mode, clearing optimistic state", self._zone_name)
                    self._clear_optimistic_state()
                    self._attr_hvac_mode = HVACMode.OFF
                    self._attr_hvac_action = HVACAction.OFF
                else:
                    # We expected a different mode but API shows OFF
                    # PRESERVE optimistic state - API hasn't caught up yet
                    _LOGGER.debug(
                        "AC %s: Preserving optimistic state (expected=%s, API shows OFF)",
                        self._zone_name,
                        self._expected_hvac_mode,
                    )
                    self._attr_hvac_mode = self._expected_hvac_mode
                    self._attr_hvac_action = self._expected_hvac_action
            else:
                # No optimistic state - trust API
                self._attr_hvac_mode = HVACMode.OFF
                self._attr_hvac_action = HVACAction.OFF

            self._attr_available = True

            # Record temperature for Smart Comfort analytics
            _record_smart_comfort_data(
                self.hass,
                self._zone_id,
                self._zone_name,
                self._attr_current_temperature,
                self._attr_target_temperature,
                is_active=(ac_power_value == "ON"),
                entry_id=self._entry_id,
            )

        except Exception as e:
            _LOGGER.warning("Failed to update %s: %s", self.name, e)
            self._attr_available = False

    async def async_set_temperature(self, **kwargs: Any) -> None:  # noqa: ANN401 — HA entity interface
        """Set new target temperature.

        Optimized to use single API call when both temperature and hvac_mode are provided.
        This saves 1 API call (1% of 100-call limit) compared to calling set_hvac_mode first.

        Changed from fire-and-forget to await pattern to fix grey loading state issue.
        Service call now awaits API completion (with timeout) for proper HA Frontend state sync.

        Added bootstrap reserve check - blocks action when quota critically low.
        Added Action Guard + Smart Actions debounce for write optimization.
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
        # Note: For AC, HVACMode.AUTO means "follow schedule" (delete overlay)
        if hvac_mode == HVACMode.AUTO:
            await self.async_set_hvac_mode(HVACMode.AUTO)
            return

        if temperature is None:
            return

        # Action Guard — skip if temp + mode already match current state
        # Skip guard when AC is OFF (smart mode selection will change mode)
        if self._attr_hvac_mode != HVACMode.OFF and ActionGuard.should_skip_temperature(
            temperature, self._attr_target_temperature,
            hvac_mode or self._attr_hvac_mode, self._attr_hvac_mode,
        ):
            _LOGGER.debug(
                "Action Guard: skip AC %s set_temperature (already %s°C)",
                self._zone_name, temperature,
            )
            return

        await _check_bootstrap_reserve(self.hass, f"AC {self._zone_name}", entry_id=self._entry_id)

        # Capture current state before overlay (state restoration)
        if self.coordinator._sr_manager:
            await self.coordinator._sr_manager.capture(
                self._zone_id, self._entity_type, source="set_temperature",
            )

        # Convert hvac_mode to Tado mode for the overlay
        tado_mode = HA_TO_TADO_HVAC_MODE.get(hvac_mode) if hvac_mode else None

        # Optimistic update BEFORE API call
        old_temp = self._attr_target_temperature
        old_mode = self._attr_hvac_mode
        old_action = self._attr_hvac_action

        self._attr_target_temperature = temperature
        if hvac_mode is not None:
            self._attr_hvac_mode = hvac_mode

        # If AC is OFF, setting temperature will turn it ON
        # Smart mode selection (#182): pick COOL/HEAT based on current vs target temp
        if old_mode == HVACMode.OFF:
            if hvac_mode is not None:
                self._attr_hvac_mode = hvac_mode
            elif (
                self._attr_current_temperature is not None
                and temperature is not None
                and HVACMode.HEAT in self._attr_hvac_modes
                and temperature > self._attr_current_temperature
            ):
                self._attr_hvac_mode = HVACMode.HEAT
            else:
                self._attr_hvac_mode = HVACMode.COOL

        new_hvac_action = self._calculate_hvac_action()
        self._attr_hvac_action = new_hvac_action

        self._overlay_type = "MANUAL"  # type: ignore[assignment]
        # Use new optimistic state tracking with sequence numbers
        await self._set_optimistic_state(self._attr_hvac_mode, new_hvac_action, target_temp=temperature)  # type: ignore[arg-type]
        _LOGGER.debug(
            "AC Optimistic update: %s target_temp=%s, hvac_action=%s",
            self._zone_name,
            temperature,
            new_hvac_action,
        )
        self.async_write_ha_state()

        # Smart Actions debounce — wrap API call in closure
        debounce_window = self.coordinator.config_manager.get_smart_actions_debounce_seconds()
        if debounce_window > 0:
            async def _execute_api_call() -> None:
                """Execute the debounced API call."""
                api_success = False
                try:
                    async with asyncio.timeout(10):
                        api_success = await self._async_set_ac_overlay(temperature=temperature, mode=tado_mode)
                except TimeoutError:
                    _LOGGER.warning("AC TIMEOUT: %s temperature change timed out", self._zone_name)
                except Exception as e:
                    _LOGGER.warning("AC ERROR: %s temperature change failed (%s)", self._zone_name, e)

                if api_success:
                    _LOGGER.info("AC Set %s to %s°C", self._zone_name, temperature)
                    await async_trigger_immediate_refresh(self.hass, self.entity_id, "temperature_change")
                else:
                    _LOGGER.warning("AC ROLLBACK: %s temperature change failed", self._zone_name)
                    self._attr_target_temperature = old_temp
                    self._attr_hvac_mode = old_mode
                    self._attr_hvac_action = old_action
                    self._clear_optimistic_state()
                    self.async_write_ha_state()

            await self.coordinator.action_debouncer.debounce(
                self._zone_id, _execute_api_call, window=float(debounce_window),
            )
        else:
            # No debounce — execute immediately (existing behavior)
            api_success = False
            try:
                async with asyncio.timeout(10):
                    api_success = await self._async_set_ac_overlay(temperature=temperature, mode=tado_mode)
            except TimeoutError:
                _LOGGER.warning("AC TIMEOUT: %s temperature change timed out", self._zone_name)
            except Exception as e:
                _LOGGER.warning("AC ERROR: %s temperature change failed (%s)", self._zone_name, e)

            if api_success:
                _LOGGER.info("AC Set %s to %s°C", self._zone_name, temperature)
                await async_trigger_immediate_refresh(self.hass, self.entity_id, "temperature_change")
            else:
                _LOGGER.warning("AC ROLLBACK: %s temperature change failed", self._zone_name)
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
        Added Action Guard for write optimization.
        """
        # Action Guard — skip if mode already matches current state
        if ActionGuard.should_skip_hvac_mode(hvac_mode, self._attr_hvac_mode):
            _LOGGER.debug(
                "Action Guard: skip AC %s set_hvac_mode (already %s)",
                self._zone_name, hvac_mode,
            )
            return

        await _check_bootstrap_reserve(self.hass, f"AC {self._zone_name}", entry_id=self._entry_id)

        client = self.coordinator.api_client

        if hvac_mode == HVACMode.OFF:
            # Capture current state before overlay (state restoration)
            if self.coordinator._sr_manager:
                await self.coordinator._sr_manager.capture(
                    self._zone_id, self._entity_type, source="set_hvac_mode",
                )

            setting = {
                "type": "AIR_CONDITIONING",
                "power": "OFF",
            }
            termination = get_zone_overlay_termination(self.hass, self._zone_id, entry_id=self._entry_id)
            await api_call_with_rollback(
                self,
                client.set_zone_overlay(self._zone_id, setting, termination),
                hvac_mode=HVACMode.OFF,
                hvac_action=HVACAction.OFF,
                reason="AC Set OFF mode",
            )

        elif hvac_mode == HVACMode.AUTO:
            await api_call_with_rollback(
                self,
                client.delete_zone_overlay(self._zone_id),
                hvac_mode=HVACMode.AUTO,
                hvac_action=HVACAction.IDLE,
                overlay_type=None,
                reason="AC Set AUTO mode (deleted overlay)",
            )
        else:
            # Capture current state before overlay (state restoration)
            if self.coordinator._sr_manager:
                await self.coordinator._sr_manager.capture(
                    self._zone_id, self._entity_type, source="set_hvac_mode",
                )

            # Include all attributes that will be set by _async_set_ac_overlay
            old_mode = self._attr_hvac_mode
            old_temp = self._attr_target_temperature
            old_fan = self._attr_fan_mode
            old_swing = self._attr_swing_mode
            old_action = self._attr_hvac_action

            self._attr_hvac_mode = hvac_mode
            self._overlay_type = "MANUAL"  # type: ignore[assignment]

            # Set default temperature if not already set (matches _async_set_ac_overlay logic)
            # Clear temperature for FAN/DRY modes that don't support it
            tado_mode = HA_TO_TADO_HVAC_MODE.get(hvac_mode, "COOL")

            # Check if this mode supports temperature (from capabilities)
            ac_caps = self._capabilities.get("ac_capabilities") or {}
            mode_caps = ac_caps.get(tado_mode) or {}
            mode_has_temp = "temperatures" in mode_caps

            if tado_mode == "FAN" or not mode_has_temp:
                # FAN mode and modes without temperature support: clear temperature display
                self._attr_target_temperature = None
            elif not self._attr_target_temperature:
                # Use midpoint of capabilities range instead of hardcoded 24°C
                self._attr_target_temperature = (self._attr_min_temp + self._attr_max_temp) / 2

            # Set default fan mode if not already set
            if not self._attr_fan_mode:
                self._attr_fan_mode = "auto"

            new_hvac_action = self._calculate_hvac_action()
            self._attr_hvac_action = new_hvac_action

            await self._set_optimistic_state(hvac_mode, new_hvac_action)
            self.async_write_ha_state()

            api_success = False
            try:
                async with asyncio.timeout(10):
                    api_success = await self._async_set_ac_overlay(mode=tado_mode)
            except TimeoutError:
                _LOGGER.warning("AC TIMEOUT: %s %s mode API call timed out", self._zone_name, hvac_mode)
            except Exception as e:
                _LOGGER.warning("AC ERROR: %s %s mode API call failed (%s)", self._zone_name, hvac_mode, e)

            if api_success:
                _LOGGER.info("AC Set %s to %s mode", self._zone_name, hvac_mode)
                await async_trigger_immediate_refresh(self.hass, self.entity_id, "hvac_mode_change")
            else:
                _LOGGER.warning("AC ROLLBACK: %s %s mode failed", self._zone_name, hvac_mode)
                self._attr_hvac_mode = old_mode
                self._attr_target_temperature = old_temp
                self._attr_fan_mode = old_fan
                self._attr_swing_mode = old_swing
                self._attr_hvac_action = old_action
                self._clear_optimistic_state()
                self.async_write_ha_state()

    async def async_set_fan_mode(self, fan_mode: str) -> None:
        """Set new fan mode.

        Changed from fire-and-forget to await pattern to fix grey loading state issue.
        Service call now awaits API completion (with timeout) for proper HA Frontend state sync.

        Added bootstrap reserve check - blocks action when quota critically low.
        Added Action Guard for write optimization.
        """
        # Action Guard — skip if fan mode already matches current state
        if ActionGuard.should_skip_fan_mode(fan_mode, self._attr_fan_mode):
            _LOGGER.debug(
                "Action Guard: skip AC %s set_fan_mode (already %s)",
                self._zone_name, fan_mode,
            )
            return

        await _check_bootstrap_reserve(self.hass, f"AC {self._zone_name}", entry_id=self._entry_id)

        # Capture current state before overlay (state restoration)
        if self.coordinator._sr_manager:
            await self.coordinator._sr_manager.capture(
                self._zone_id, self._entity_type, source="set_fan_mode",
            )

        old_fan = self._attr_fan_mode
        old_mode = self._attr_hvac_mode
        old_action = self._attr_hvac_action

        self._attr_fan_mode = fan_mode

        # If AC is OFF, setting fan mode will turn it ON
        if self._attr_hvac_mode == HVACMode.OFF:
            self._attr_hvac_mode = HVACMode.COOL  # Default mode when turning on via fan
            self._overlay_type = "MANUAL"  # type: ignore[assignment]

        new_hvac_action = self._calculate_hvac_action()
        self._attr_hvac_action = new_hvac_action

        await self._set_optimistic_state(self._attr_hvac_mode, new_hvac_action)  # type: ignore[arg-type]
        self.async_write_ha_state()

        tado_fan = self._ha_to_tado_fan.get(fan_mode)
        if not tado_fan:
            _LOGGER.warning("AC %s: no tado fan mapping for '%s', using AUTO", self._zone_name, fan_mode)
            tado_fan = "AUTO"

        api_success = False
        try:
            async with asyncio.timeout(10):
                api_success = await self._async_set_ac_overlay(fan_level=tado_fan)
        except TimeoutError:
            _LOGGER.warning("AC TIMEOUT: %s fan mode change timed out", self._zone_name)
        except Exception as e:
            _LOGGER.warning("AC ERROR: %s fan mode change failed (%s)", self._zone_name, e)

        if api_success:
            _LOGGER.info("AC Set %s fan mode to %s", self._zone_name, fan_mode)
            await async_trigger_immediate_refresh(self.hass, self.entity_id, "fan_mode_change")
        else:
            _LOGGER.warning("AC ROLLBACK: %s fan mode change failed", self._zone_name)
            self._attr_fan_mode = old_fan
            self._attr_hvac_mode = old_mode
            self._attr_hvac_action = old_action
            self._clear_optimistic_state()
            self.async_write_ha_state()

    async def async_set_swing_mode(self, swing_mode: str) -> None:
        """Set new swing mode.

        Unified swing dropdown like official Tado integration:
        - off: verticalSwing=OFF, horizontalSwing=OFF
        - vertical: verticalSwing=ON, horizontalSwing=OFF
        - horizontal: verticalSwing=OFF, horizontalSwing=ON
        - both: verticalSwing=ON, horizontalSwing=ON

        Changed from fire-and-forget to await pattern to fix grey loading state issue.
        Service call now awaits API completion (with timeout) for proper HA Frontend state sync.

        Added bootstrap reserve check - blocks action when quota critically low.
        Added Action Guard for write optimization.
        """
        # Action Guard — skip if swing mode already matches current state
        if ActionGuard.should_skip_swing_mode(swing_mode, self._attr_swing_mode):
            _LOGGER.debug(
                "Action Guard: skip AC %s set_swing_mode (already %s)",
                self._zone_name, swing_mode,
            )
            return

        await _check_bootstrap_reserve(self.hass, f"AC {self._zone_name}", entry_id=self._entry_id)

        # Capture current state before overlay (state restoration)
        if self.coordinator._sr_manager:
            await self.coordinator._sr_manager.capture(
                self._zone_id, self._entity_type, source="set_swing_mode",
            )

        if swing_mode == "off":
            v_swing, h_swing = "OFF", "OFF"
        elif swing_mode == "vertical":
            v_swing, h_swing = "ON", "OFF"
        elif swing_mode == "horizontal":
            v_swing, h_swing = "OFF", "ON"
        elif swing_mode == "both":
            v_swing, h_swing = "ON", "ON"
        else:
            # Fallback for legacy SWING_ON/SWING_OFF
            v_swing = "ON" if swing_mode == SWING_ON else "OFF"
            h_swing = "OFF"

        old_swing = self._attr_swing_mode
        old_mode = self._attr_hvac_mode
        old_action = self._attr_hvac_action

        self._attr_swing_mode = swing_mode

        # If AC is OFF, setting swing mode will turn it ON
        if self._attr_hvac_mode == HVACMode.OFF:
            self._attr_hvac_mode = HVACMode.COOL  # Default mode when turning on via swing
            self._overlay_type = "MANUAL"  # type: ignore[assignment]

        new_hvac_action = self._calculate_hvac_action()
        self._attr_hvac_action = new_hvac_action

        await self._set_optimistic_state(self._attr_hvac_mode, new_hvac_action)  # type: ignore[arg-type]
        self.async_write_ha_state()

        api_success = False
        try:
            async with asyncio.timeout(10):
                api_success = await self._async_set_ac_overlay(vertical_swing=v_swing, horizontal_swing=h_swing)
        except TimeoutError:
            _LOGGER.warning("AC TIMEOUT: %s swing mode change timed out", self._zone_name)
        except Exception as e:
            _LOGGER.warning("AC ERROR: %s swing mode change failed (%s)", self._zone_name, e)

        if api_success:
            _LOGGER.info("AC Set %s swing mode to %s", self._zone_name, swing_mode)
            await async_trigger_immediate_refresh(self.hass, self.entity_id, "swing_mode_change")
        else:
            _LOGGER.warning("AC ROLLBACK: %s swing mode change failed", self._zone_name)
            self._attr_swing_mode = old_swing
            self._attr_hvac_mode = old_mode
            self._attr_hvac_action = old_action
            self._clear_optimistic_state()
            self.async_write_ha_state()

    async def _async_set_ac_overlay(
        self,
        temperature: float | None = None,
        mode: str | None = None,
        fan_level: str | None = None,
        vertical_swing: str | None = None,
        horizontal_swing: str | None = None,
        duration_minutes: int | None = None,
        overlay: str | None = None,
    ) -> bool:
        """Set AC overlay with optional parameters.

        Uses Tado API v2 format with fanLevel, verticalSwing, horizontalSwing.
        Only sends fields that are supported by the current mode (per capabilities).

        Added overlay parameter for explicit termination control.
        """
        client = self.coordinator.api_client

        # Build setting from current state + changes
        setting = {
            "type": "AIR_CONDITIONING",
            "power": "ON",
        }

        # Mode
        if mode:
            setting["mode"] = mode
        elif self._attr_hvac_mode and self._attr_hvac_mode not in (HVACMode.OFF, HVACMode.AUTO):
            setting["mode"] = HA_TO_TADO_HVAC_MODE.get(self._attr_hvac_mode, "COOL")
        else:
            setting["mode"] = "COOL"

        current_mode = setting["mode"]

        # Get capabilities for current mode to check what fields are supported
        ac_caps = self._capabilities.get("ac_capabilities") or {}
        mode_caps = ac_caps.get(current_mode) or {}

        # Temperature - only send if mode supports it (check capabilities)
        # Some AC units require temperature for DRY mode, others don't
        mode_has_temp = "temperatures" in mode_caps
        if current_mode != "FAN" and mode_has_temp:
            if temperature:
                setting["temperature"] = {"celsius": temperature}  # type: ignore[assignment]
            elif self._attr_target_temperature:
                setting["temperature"] = {"celsius": self._attr_target_temperature}  # type: ignore[assignment]
            else:
                # Use midpoint of capabilities range instead of hardcoded 24°C
                setting["temperature"] = {"celsius": (self._attr_min_temp + self._attr_max_temp) / 2}  # type: ignore[assignment]

        # Fan level - only send if mode supports it AND value is in supported list
        # Use per-zone dynamic mapping
        # Validate fan level against capabilities
        # Support both fanLevel (newer firmware) and fanSpeeds (legacy firmware)
        fan_key = "fanLevel" if "fanLevel" in mode_caps else ("fanSpeeds" if "fanSpeeds" in mode_caps else None)
        if fan_key:
            supported_fan_levels = mode_caps.get(fan_key) or []
            if fan_level:
                # Explicit value passed - validate it
                if fan_level in supported_fan_levels:
                    setting[fan_key] = fan_level
                elif supported_fan_levels:
                    fallback = "AUTO" if "AUTO" in supported_fan_levels else supported_fan_levels[0]
                    setting[fan_key] = fallback
                    _LOGGER.warning("AC %s: fan level %s not supported, using %s", self._zone_name, fan_level, fallback)
            elif self._attr_fan_mode:
                # Use per-zone mapping first, fall back to global static
                tado_fan = self._ha_to_tado_fan.get(self._attr_fan_mode) or HA_TO_TADO_FAN.get(
                    self._attr_fan_mode, "AUTO",
                )
                if tado_fan in supported_fan_levels:
                    setting[fan_key] = tado_fan
                elif supported_fan_levels:
                    # Try to find the closest supported level
                    fallback = "AUTO" if "AUTO" in supported_fan_levels else supported_fan_levels[-1]
                    setting[fan_key] = fallback
                    _LOGGER.debug(
                        "AC %s: mapped fan %s→%s not in %s, using %s",
                        self._zone_name,
                        self._attr_fan_mode,
                        tado_fan,
                        supported_fan_levels,
                        fallback,
                    )
            elif "AUTO" in supported_fan_levels:
                setting[fan_key] = "AUTO"
            elif supported_fan_levels:
                setting[fan_key] = supported_fan_levels[0]

        # Swing - only send if mode supports it AND value is in supported list
        # Validate swing values against capabilities
        # Some AC units (e.g., Mitsubishi) don't support "OFF" as a swing value
        if "verticalSwing" in mode_caps:
            supported_v_swings = mode_caps.get("verticalSwing") or []
            if vertical_swing is not None:
                # Explicit value passed - validate it
                if vertical_swing in supported_v_swings:
                    setting["verticalSwing"] = vertical_swing
                # else: don't send unsupported value
            elif self._attr_swing_mode in ("vertical", "both"):
                if "ON" in supported_v_swings:
                    setting["verticalSwing"] = "ON"
                elif supported_v_swings:
                    # Fallback to first supported value
                    setting["verticalSwing"] = supported_v_swings[0]
            # User wants swing off - only send if "OFF" is supported
            elif "OFF" in supported_v_swings:
                setting["verticalSwing"] = "OFF"
                # else: don't send verticalSwing field at all

        if "horizontalSwing" in mode_caps:
            supported_h_swings = mode_caps.get("horizontalSwing") or []
            if horizontal_swing is not None:
                # Explicit value passed - validate it
                if horizontal_swing in supported_h_swings:
                    setting["horizontalSwing"] = horizontal_swing
                # else: don't send unsupported value
            elif self._attr_swing_mode in ("horizontal", "both"):
                if "ON" in supported_h_swings:
                    setting["horizontalSwing"] = "ON"
                elif supported_h_swings:
                    # Fallback to first supported value
                    setting["horizontalSwing"] = supported_h_swings[0]
            # User wants swing off - only send if "OFF" is supported
            elif "OFF" in supported_h_swings:
                setting["horizontalSwing"] = "OFF"
                # else: don't send horizontalSwing field at all

        # Termination
        # Use per-zone overlay mode
        # DRY — use shared build_timer_termination
        termination = build_timer_termination(
            duration_minutes=duration_minutes,
            overlay=overlay,
            hass=self.hass,
            zone_id=self._zone_id,
            entry_id=self._entry_id,
        )

        _LOGGER.debug("AC overlay payload: setting=%s, termination=%s", setting, termination)

        if await client.set_zone_overlay(self._zone_id, setting, termination):
            _LOGGER.info("Set AC %s: %s", self._zone_name, setting)
            return True
        return False

    async def async_set_timer(
        self, temperature: float, duration_minutes: int | None = None, overlay: str | None = None,
    ) -> bool:
        """Set AC with timer or overlay type.

        Added overlay parameter for parity with TadoClimate.
        When overlay='next_time_block', uses TADO_MODE termination (no timer needed).
        When overlay='manual', uses MANUAL termination.

        Added timeout protection for consistency.
        Simplified — delegates to _async_set_ac_overlay with overlay param.
        """
        await _check_bootstrap_reserve(self.hass, f"AC {self._zone_name}", entry_id=self._entry_id)

        # Capture current state before overlay (state restoration)
        if self.coordinator._sr_manager:
            await self.coordinator._sr_manager.capture(
                self._zone_id, self._entity_type, source="set_timer",
            )

        api_success = False
        try:
            async with asyncio.timeout(10):
                api_success = await self._async_set_ac_overlay(
                    temperature=temperature,
                    mode=None,
                    duration_minutes=duration_minutes,
                    overlay=overlay,
                )
        except TimeoutError:
            _LOGGER.warning("AC TIMEOUT: %s set_timer API call timed out", self._zone_name)
        except Exception as e:
            _LOGGER.warning("AC ERROR: %s set_timer API call failed (%s)", self._zone_name, e)

        return api_success
