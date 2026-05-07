"""Smart Valve Controller — per-zone proportional offset TRV control.

Uses external temperature sensors to automatically adjust TRV target
temperatures, ensuring rooms reach the user's desired temperature rather
than relying on the TRV's inaccurate built-in sensor.

The controller writes directly to TRVs via HomeKit (preferred) or cloud
API (fallback), bypassing the climate entity pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
import logging
import time
from typing import TYPE_CHECKING, Any

from .const import (
    ABSOLUTE_MAX_VALVE_TARGET,
    HOMEKIT_WRITE_GRACE_SECONDS,
    SMART_VALVE_CLOUD_RATE_LIMIT,
    SMART_VALVE_DEBOUNCE_WINDOW,
    SMART_VALVE_HYSTERESIS,
    SMART_VALVE_MIN_CHANGE,
)

if TYPE_CHECKING:
    from homeassistant.core import CALLBACK_TYPE, HomeAssistant

    from .coordinator import TadoDataUpdateCoordinator

from .climate_helpers import SensorProxy, subscribe_external_sensors
from .helpers import get_zone_overlay_termination

_LOGGER = logging.getLogger(__name__)


class ControllerState(StrEnum):
    """Smart valve controller states."""

    IDLE = "idle"
    ACTIVE = "active"
    BACKED_OFF = "backed_off"


@dataclass
class ValveControllerRuntime:
    """Runtime state for SmartValveController (not persisted)."""

    state: ControllerState = ControllerState.IDLE
    last_valve_target: float | None = None
    last_evaluation_ts: float | None = None
    last_schedule_target: float | None = None
    last_cloud_write_ts: float | None = None
    pending_cloud_target: float | None = None
    overlay_set_by_controller: bool = False
    backed_off_overlay_target: float | None = None  # overlay target when entering backed-off
    desired_target: float | None = None  # user's desired temp captured at IDLE→ACTIVE transition
    unsub_external_sensors: list[CALLBACK_TYPE] = field(default_factory=list)



class SmartValveController:
    """Per-zone proportional offset controller for TRV valve management.

    Calculates a proportional offset based on the difference between the
    user's desired room temperature and the external sensor reading, then
    writes the adjusted target to the TRV via HomeKit or cloud API.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        coordinator: TadoDataUpdateCoordinator,
        zone_id: str,
        *,
        hysteresis: float = SMART_VALVE_HYSTERESIS,
        min_change: float = SMART_VALVE_MIN_CHANGE,
        cloud_rate_limit_seconds: float = SMART_VALVE_CLOUD_RATE_LIMIT,
    ) -> None:
        """Initialize the SmartValveController."""
        self._hass = hass
        self._coordinator = coordinator
        self._zone_id = zone_id
        self._hysteresis = hysteresis
        self._min_change = min_change
        self._cloud_rate_limit_seconds = cloud_rate_limit_seconds

        # Convenience references to coordinator dependencies
        self._zcm = coordinator.zone_config_manager
        self._homekit_provider = coordinator.homekit_provider
        self._api_client = coordinator.api_client
        self._action_debouncer = coordinator.action_debouncer

        # Runtime state (in-memory)
        self._runtime = ValveControllerRuntime()

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def state(self) -> ControllerState:
        """Return the current controller state."""
        return self._runtime.state

    @property
    def last_valve_target(self) -> float | None:
        """Return the last written valve target."""
        return self._runtime.last_valve_target

    # ------------------------------------------------------------------
    # Core pure functions
    # ------------------------------------------------------------------

    @staticmethod
    def calculate_valve_target(
        trv_reading: float,
        desired_target: float,
        external_temp: float,
        min_temp: float,
        max_temp: float,
    ) -> float:
        """Calculate clamped valve target from proportional offset.

        Pure function — no side effects, fully testable.
        Applies absolute safety cap after min/max clamp.

        Returns:
            min(clamp(trv_reading + (desired_target - external_temp), min_temp, max_temp),
                ABSOLUTE_MAX_VALVE_TARGET)
        """
        offset = desired_target - external_temp
        raw = trv_reading + offset
        clamped = max(min_temp, min(raw, max_temp))
        return round(min(clamped, ABSOLUTE_MAX_VALVE_TARGET), 1)

    def should_write(self, new_valve_target: float) -> bool:
        """Check minimum change guard: |new - last_written| >= min_change.

        Returns True if the new target differs enough from the last written
        value to warrant a write operation.
        """
        last = self._runtime.last_valve_target
        if last is None:
            return True
        return abs(new_valve_target - last) >= self._min_change

    def should_transition(
        self,
        external_temp: float,
        desired_target: float,
    ) -> ControllerState | None:
        """Determine if a state transition should occur based on hysteresis.

        Returns new state if transition needed, None if holding current state.
        """
        current = self._runtime.state

        if current == ControllerState.IDLE:
            if external_temp < desired_target - self._hysteresis:
                return ControllerState.ACTIVE
        elif current == ControllerState.ACTIVE:
            if external_temp >= desired_target + self._hysteresis:
                return ControllerState.IDLE

        # Within hysteresis band or backed_off — hold current state
        return None

    # ------------------------------------------------------------------
    # Manual override / schedule block detection
    # ------------------------------------------------------------------

    def detect_manual_override(self, zone_data: dict[str, Any]) -> bool:
        """Check if zone overlay was changed externally (not by this controller).

        Compares zone's current overlay target against last written valve_target.
        Returns True if mismatch or overlay deleted externally.
        Suppresses detection within HOMEKIT_WRITE_GRACE_SECONDS of last write
        to avoid false positives during HomeKit-to-cloud sync delay.
        """
        if not self._runtime.overlay_set_by_controller:
            return False

        # Grace period: suppress false override detection after recent write
        last_ts = self._runtime.last_evaluation_ts
        if last_ts is not None:
            if time.monotonic() - last_ts < HOMEKIT_WRITE_GRACE_SECONDS:
                return False

        overlay = zone_data.get("overlay")
        if overlay is None:
            # Overlay deleted externally — manual override
            return True

        overlay_temp = (
            overlay.get("setting", {})
            .get("temperature") or {}
        ).get("celsius")
        if overlay_temp is None:
            return True

        last = self._runtime.last_valve_target
        if last is None:
            return False

        return abs(float(overlay_temp) - last) >= 0.1

    def detect_schedule_block_change(
        self, current_schedule_target: float | None,
    ) -> bool:
        """Check if the schedule block has changed since last recorded.

        Detects ON→OFF, OFF→ON, and target temperature changes.
        """
        last = self._runtime.last_schedule_target
        # None↔value transitions are always a change (ON↔OFF)
        if (current_schedule_target is None) != (last is None):
            return True
        # Both None — no change (still OFF)
        if current_schedule_target is None:
            return False
        # Both have values — check if target changed
        return abs(current_schedule_target - last) >= 0.1  # type: ignore[operator]

    def detect_overlay_change_while_backed_off(
        self, zone_data: dict[str, Any],
    ) -> bool:
        """Check if the overlay changed or was deleted since entering backed-off.

        Covers the case where all schedule blocks are OFF (schedule target is
        always None) and the user's HA automation sets a new overlay or resumes
        the schedule. Without this, backed-off state would be permanent.
        """
        overlay = zone_data.get("overlay")

        # Overlay deleted — user or automation resumed schedule
        if overlay is None:
            return self._runtime.backed_off_overlay_target is not None

        overlay_temp = (
            overlay.get("setting", {})
            .get("temperature") or {}
        ).get("celsius")
        if overlay_temp is None:
            return True

        saved = self._runtime.backed_off_overlay_target
        if saved is None:
            # No saved target — overlay appeared while backed off
            return True

        return abs(float(overlay_temp) - saved) >= 0.1

    # ------------------------------------------------------------------
    # Write operations
    # ------------------------------------------------------------------

    async def _async_write_valve_target(self, valve_target: float) -> bool:
        """Write valve target via HomeKit-first with cloud fallback.

        Bypasses climate entity — writes directly to TRV.
        Returns True if write succeeded via either path.
        """
        # Try HomeKit first
        if self._homekit_provider is not None:
            try:
                success = await self._homekit_provider.set_temperature(
                    self._zone_id, valve_target,
                )
                if success:
                    _LOGGER.info(
                        "Smart Valve: zone %s set TRV to %s°C via homekit",
                        self._zone_id, valve_target,
                    )
                    self._runtime.last_valve_target = valve_target
                    self._runtime.overlay_set_by_controller = True
                    self._runtime.last_evaluation_ts = time.monotonic()
                    return True
            except Exception:
                _LOGGER.info(
                    "Smart Valve: HomeKit write failed for zone %s, trying cloud",
                    self._zone_id, exc_info=True,
                )

        # Cloud fallback with rate limiting
        return await self._async_write_cloud(valve_target)

    async def _async_write_cloud(self, valve_target: float) -> bool:
        """Write valve target via cloud API with rate limiting.

        Non-idempotent — no retry. Rate limited to 1 write per zone per 5 minutes.
        """
        now = time.monotonic()
        last_cloud = self._runtime.last_cloud_write_ts

        if last_cloud is not None and (now - last_cloud) < self._cloud_rate_limit_seconds:
            # Rate limited — queue latest target
            self._runtime.pending_cloud_target = valve_target
            _LOGGER.info(
                "Smart Valve: zone %s cloud write rate limited, queued %.1f°C",
                self._zone_id, valve_target,
            )
            return False

        try:
            setting = {"type": "HEATING", "power": "ON", "temperature": {"celsius": valve_target}}
            entry_id = self._coordinator.config_entry.entry_id
            termination = get_zone_overlay_termination(
                self._hass, self._zone_id, entry_id=entry_id,
            )
            success = await self._api_client.set_zone_overlay(
                self._zone_id, setting, termination,
            )
            if success:
                _LOGGER.info(
                    "Smart Valve: zone %s set TRV to %s°C via cloud",
                    self._zone_id, valve_target,
                )
                self._runtime.last_valve_target = valve_target
                self._runtime.last_cloud_write_ts = now
                self._runtime.overlay_set_by_controller = True
                self._runtime.pending_cloud_target = None
                self._runtime.last_evaluation_ts = time.monotonic()
                return True
            _LOGGER.warning(
                "Smart Valve: zone %s cloud write failed", self._zone_id,
            )
            return False
        except Exception:
            _LOGGER.warning(
                "Smart Valve: zone %s cloud write exception",
                self._zone_id, exc_info=True,
            )
            return False

    async def _async_resume_schedule(self) -> bool:
        """Delete zone overlay to resume Tado schedule (cloud only).

        Returns True if successful. Handles 404 as success (overlay already gone).
        """
        try:
            success = await self._api_client.delete_zone_overlay(self._zone_id)
            if success:
                _LOGGER.info(
                    "Smart Valve: zone %s resumed schedule (overlay deleted)",
                    self._zone_id,
                )
                self._runtime.overlay_set_by_controller = False
                return True
            _LOGGER.warning(
                "Smart Valve: zone %s schedule resume failed, will retry next cycle",
                self._zone_id,
            )
            return False
        except Exception:
            _LOGGER.warning(
                "Smart Valve: zone %s schedule resume exception",
                self._zone_id, exc_info=True,
            )
            return False

    # ------------------------------------------------------------------
    # Main evaluation cycle
    # ------------------------------------------------------------------

    async def async_evaluate(self) -> None:
        """Run a full evaluation cycle: read inputs → decide state → write if needed.

        Called on external sensor change (debounced) and coordinator poll update.
        """
        from .climate_helpers import read_external_sensor
        from .schedule_helpers import get_current_schedule_target

        zone_data = self._get_zone_data()
        if zone_data is None:
            _LOGGER.warning(
                "Smart Valve: zone %s has no zone data — skipping evaluation",
                self._zone_id,
            )
            return

        # Read inputs
        zone_config = self._zcm.get_zone_config(self._zone_id)
        min_temp: float = zone_config.get("min_temp", 5.0)
        max_temp: float = zone_config.get("max_temp", 25.0)

        # Ensure min <= max
        if min_temp > max_temp:
            _LOGGER.warning(
                "Smart Valve: zone %s min_temp (%.1f) > max_temp (%.1f), using defaults",
                self._zone_id, min_temp, max_temp,
            )
            min_temp, max_temp = 5.0, 25.0

        external_temp = read_external_sensor(
            self._hass, self._zcm, self._zone_id, "external_temp_sensor",
        )

        trv_reading = self._read_trv_temperature(zone_data)

        schedule_target = get_current_schedule_target(
            self._zone_id, data_loader=self._coordinator.data_loader,
        )

        # --- State machine logic ---

        current_state = self._runtime.state

        # Diagnostic summary — one line per evaluation cycle for remote debugging
        _LOGGER.info(
            "Smart Valve: zone %s eval — state=%s, ext=%s, trv=%s, schedule=%s, desired=%s",
            self._zone_id,
            self._runtime.state.value,
            f"{external_temp:.1f}" if external_temp is not None else "None",
            f"{trv_reading:.1f}" if trv_reading is not None else "None",
            f"{schedule_target:.1f}" if schedule_target is not None else "None",
            f"{self._runtime.desired_target:.1f}" if self._runtime.desired_target is not None else "None",
        )

        # Handle backed-off state
        if current_state == ControllerState.BACKED_OFF:
            if self.detect_schedule_block_change(schedule_target):
                _LOGGER.info(
                    "Smart Valve: zone %s schedule block changed, resuming from backed-off",
                    self._zone_id,
                )
                self._runtime.state = ControllerState.IDLE
                self._runtime.last_schedule_target = schedule_target
                self._runtime.backed_off_overlay_target = None
                self._runtime.desired_target = None
            elif self.detect_overlay_change_while_backed_off(zone_data):
                _LOGGER.info(
                    "Smart Valve: zone %s overlay changed externally, resuming from backed-off",
                    self._zone_id,
                )
                self._runtime.state = ControllerState.IDLE
                self._runtime.backed_off_overlay_target = None
                self._runtime.desired_target = None
            # No further action while backed off
            return

        # Check manual override (only when active)
        if current_state == ControllerState.ACTIVE:
            if self.detect_manual_override(zone_data):
                # Save current overlay target for overlay-change detection
                overlay = zone_data.get("overlay")
                if overlay is not None:
                    self._runtime.backed_off_overlay_target = (
                        overlay.get("setting", {})
                        .get("temperature") or {}
                    ).get("celsius")
                else:
                    self._runtime.backed_off_overlay_target = None
                _LOGGER.info(
                    "Smart Valve: zone %s manual override detected, backing off",
                    self._zone_id,
                )
                self._runtime.state = ControllerState.BACKED_OFF
                self._runtime.last_schedule_target = schedule_target
                return

        # Check schedule changes while ACTIVE (FR-1 + FR-2)
        if current_state == ControllerState.ACTIVE:
            if schedule_target is None:
                # Schedule went OFF — respect it immediately
                _LOGGER.info(
                    "Smart Valve: zone %s schedule is OFF, resuming schedule",
                    self._zone_id,
                )
                await self._async_resume_schedule()
                self._runtime.state = ControllerState.IDLE
                self._runtime.desired_target = None
                self._runtime.last_schedule_target = schedule_target
                return
            if (
                self._runtime.desired_target is not None
                and abs(schedule_target - self._runtime.desired_target) >= 0.1
            ):
                # Schedule target changed (e.g. 19°C → 21°C) — update in-place
                _LOGGER.info(
                    "Smart Valve: zone %s schedule target changed (%.1f → %.1f), updating",
                    self._zone_id, self._runtime.desired_target, schedule_target,
                )
                self._runtime.desired_target = schedule_target
                self._runtime.last_schedule_target = schedule_target

        # Handle sensor unavailability
        if external_temp is None:
            if current_state == ControllerState.ACTIVE:
                _LOGGER.info(
                    "Smart Valve: zone %s external sensor unavailable while active, resuming schedule",
                    self._zone_id,
                )
                await self._async_resume_schedule()
                self._runtime.state = ControllerState.IDLE
            return

        # Read desired_target: use stored value while ACTIVE, fresh read otherwise
        desired_target: float | None
        if current_state == ControllerState.ACTIVE and self._runtime.desired_target is not None:
            desired_target = self._runtime.desired_target
        else:
            desired_target = self._read_desired_target(zone_data)

        if desired_target is None:
            return

        # Evaluate state transition
        new_state = self.should_transition(external_temp, desired_target)
        if new_state is not None:
            if new_state == ControllerState.ACTIVE and current_state == ControllerState.IDLE:
                # IDLE → ACTIVE: capture desired_target at transition
                self._runtime.desired_target = desired_target
            if new_state == ControllerState.IDLE and current_state == ControllerState.ACTIVE:
                # Active → Idle: resume schedule
                _LOGGER.info(
                    "Smart Valve: zone %s room warm (%.1f°C ≥ %.1f°C + %.1f), resuming schedule",
                    self._zone_id, external_temp, desired_target, self._hysteresis,
                )
                await self._async_resume_schedule()
            self._runtime.state = new_state

        # If active, calculate and write
        if self._runtime.state == ControllerState.ACTIVE:
            if trv_reading is None:
                # TRV unavailable — bang-bang fallback (doesn't need desired_target)
                _LOGGER.warning(
                    "Smart Valve: zone %s TRV reading unavailable, bang-bang fallback to %.1f°C",
                    self._zone_id, max_temp,
                )
                if self.should_write(max_temp):
                    await self._async_debounced_write(max_temp)
                return

            # Use stored desired_target for calculations
            active_desired = self._runtime.desired_target
            if active_desired is None:
                return

            valve_target = self.calculate_valve_target(
                trv_reading, active_desired, external_temp, min_temp, max_temp,
            )

            if self.should_write(valve_target):
                await self._async_debounced_write(valve_target)

        # Flush pending cloud writes if rate limit window expired
        await self._async_flush_pending_cloud()

    async def _async_debounced_write(self, valve_target: float) -> None:
        """Write valve target through ActionDebouncer."""
        async def _do_write() -> None:
            await self._async_write_valve_target(valve_target)
            await self.async_persist_state()

        await self._action_debouncer.debounce(
            f"svc_{self._zone_id}",
            _do_write,
            window=SMART_VALVE_DEBOUNCE_WINDOW,
        )

    async def _async_flush_pending_cloud(self) -> None:
        """Flush pending cloud target if rate limit window has expired."""
        pending = self._runtime.pending_cloud_target
        if pending is None:
            return

        now = time.monotonic()
        last_cloud = self._runtime.last_cloud_write_ts
        if last_cloud is not None and (now - last_cloud) < self._cloud_rate_limit_seconds:
            return

        # Window expired — write the latest queued target
        self._runtime.pending_cloud_target = None
        await self._async_write_cloud(pending)

    # ------------------------------------------------------------------
    # Input readers
    # ------------------------------------------------------------------

    def _get_zone_data(self) -> dict[str, Any] | None:
        """Read zone data from coordinator, merged with fresh HomeKit readings.

        Merges HomeKit temperature into sensorDataPoints so that
        _read_trv_temperature() uses the freshest available TRV reading
        instead of potentially stale cloud-polled data.
        """
        from .helpers import get_zone_state, merge_homekit_into_zone_data

        zone_data = get_zone_state(self._coordinator.data, self._zone_id)
        if zone_data is None:
            return None
        return merge_homekit_into_zone_data(
            zone_data, self._zone_id, self._coordinator,
        )

    @staticmethod
    def _read_trv_temperature(zone_data: dict[str, Any]) -> float | None:
        """Read TRV built-in sensor temperature from zone data."""
        try:
            return float(
                zone_data["sensorDataPoints"]["insideTemperature"]["celsius"],
            )
        except (KeyError, TypeError, ValueError):
            return None

    def _read_desired_target(self, zone_data: dict[str, Any]) -> float | None:
        """Read desired target from overlay or schedule.

        Priority: active overlay target → schedule target.
        """
        from .schedule_helpers import get_current_schedule_target

        # Check overlay first
        overlay = zone_data.get("overlay")
        if overlay is not None:
            overlay_temp = (
                overlay.get("setting", {})
                .get("temperature") or {}
            ).get("celsius")
            if overlay_temp is not None:
                try:
                    return float(overlay_temp)
                except (ValueError, TypeError):
                    pass

        # Fall back to schedule
        return get_current_schedule_target(
            self._zone_id, data_loader=self._coordinator.data_loader,
        )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def async_activate(self) -> None:
        """Activate controller: subscribe to sensors, load persisted state."""
        await self.async_load_state()

        # Safety: if restored as ACTIVE but desired_target is missing (upgrade
        # from older version without this field), reset to IDLE so the next
        # evaluation captures a fresh desired_target instead of reading the
        # controller's own inflated overlay.
        if self._runtime.state == ControllerState.ACTIVE and self._runtime.desired_target is None:
            _LOGGER.info(
                "Smart Valve: zone %s restored ACTIVE without desired_target, resetting to IDLE",
                self._zone_id,
            )
            self._runtime.state = ControllerState.IDLE

        # Finding 3: Clean up stale overlay from previous crash
        if self._runtime.overlay_set_by_controller and self._runtime.state == ControllerState.IDLE:
            _LOGGER.info(
                "Smart Valve: zone %s cleaning up stale overlay from previous session",
                self._zone_id,
            )
            await self._async_resume_schedule()
            self._runtime.overlay_set_by_controller = False

        # Finding 2: Warn if device has a non-zero temperature offset
        await self._async_check_device_offset()

        # Subscribe to external sensor state changes
        proxy = SensorProxy(self._hass, self._coordinator)
        unsubs = subscribe_external_sensors(
            proxy,
            self._zone_id,
            self._on_external_sensor_change,
            include_humidity=False,
        )
        self._runtime.unsub_external_sensors = unsubs

        # If previously active, recalculate before writing
        if self._runtime.state == ControllerState.ACTIVE:
            await self.async_evaluate()

        _LOGGER.info(
            "Smart Valve: zone %s controller activated (state=%s)",
            self._zone_id, self._runtime.state,
        )

    async def async_deactivate(self) -> None:
        """Deactivate controller: resume schedule if active, clean up subscriptions."""
        if self._runtime.state == ControllerState.ACTIVE and self._runtime.overlay_set_by_controller:
            await self._async_resume_schedule()

        # Clean up sensor subscriptions
        for unsub in self._runtime.unsub_external_sensors:
            unsub()
        self._runtime.unsub_external_sensors.clear()

        # Cancel pending debounce
        self._action_debouncer.cancel(f"svc_{self._zone_id}")

        # Persist final state
        await self.async_persist_state()

        _LOGGER.info(
            "Smart Valve: zone %s controller deactivated", self._zone_id,
        )

    async def _async_check_device_offset(self) -> None:
        """Warn if any device in this zone has a non-zero temperature offset.

        A non-zero device offset causes double compensation because the Tado API
        returns offset-adjusted temperatures in sensorDataPoints.insideTemperature.
        Smart Valve Control reads that adjusted value and adds its own compensation
        on top, resulting in overshoot.
        """
        try:
            zone_data = self._get_zone_data()
            if zone_data is None:
                return

            devices = zone_data.get("devices", [])
            if not devices:
                return

            for device in devices:
                serial = device.get("serialNo", "")
                offset = device.get("temperatureOffset", {}).get("celsius")
                if offset is not None and abs(float(offset)) >= 0.1:
                    _LOGGER.warning(
                        "Smart Valve: zone %s device %s…  has a temperature offset of %.1f°C — "
                        "this will cause double compensation. Reset the device offset to 0 "
                        "for accurate Smart Valve Control",
                        self._zone_id, serial[:6], float(offset),
                    )
        except Exception:
            _LOGGER.info(
                "Smart Valve: zone %s could not check device offset",
                self._zone_id, exc_info=True,
            )

    def _on_external_sensor_change(self, _event: Any) -> None:
        """Handle external sensor state change — debounce and evaluate."""
        self._hass.async_create_task(
            self._action_debouncer.debounce(
                f"svc_{self._zone_id}",
                self.async_evaluate,
                window=SMART_VALVE_DEBOUNCE_WINDOW,
            ),
        )

    def get_attributes(self) -> dict[str, Any]:
        """Return attributes for climate entity extra_state_attributes."""
        state = self._runtime.state
        attrs: dict[str, Any] = {
            "valve_control_enabled": True,
            "valve_control_active": state == ControllerState.ACTIVE,
        }
        if state == ControllerState.BACKED_OFF:
            attrs["valve_control_backed_off"] = True
        if state == ControllerState.ACTIVE and self._runtime.last_valve_target is not None:
            attrs["valve_target"] = self._runtime.last_valve_target
        if state == ControllerState.ACTIVE and self._runtime.desired_target is not None:
            attrs["desired_target"] = self._runtime.desired_target
        return attrs

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    async def async_persist_state(self) -> None:
        """Persist controller state via ZoneConfigManager."""
        state_dict = {
            "state": self._runtime.state.value,
            "last_valve_target": self._runtime.last_valve_target,
            "last_evaluation_ts": self._runtime.last_evaluation_ts,
            "last_schedule_target": self._runtime.last_schedule_target,
            "overlay_set_by_controller": self._runtime.overlay_set_by_controller,
            "backed_off_overlay_target": self._runtime.backed_off_overlay_target,
            "desired_target": self._runtime.desired_target,
        }
        await self._zcm.async_set_zone_value(
            self._zone_id, "svc_state", state_dict,
        )

    async def async_load_state(self) -> None:
        """Load persisted controller state on startup."""
        config = self._zcm.get_zone_config(self._zone_id)
        raw = config.get("svc_state")
        if not isinstance(raw, dict):
            _LOGGER.info(
                "Smart Valve: zone %s no persisted state, starting fresh",
                self._zone_id,
            )
            return

        try:
            state_str = raw.get("state", "idle")
            self._runtime.state = ControllerState(state_str)
            self._runtime.last_valve_target = raw.get("last_valve_target")
            self._runtime.last_evaluation_ts = raw.get("last_evaluation_ts")
            self._runtime.last_schedule_target = raw.get("last_schedule_target")
            self._runtime.overlay_set_by_controller = bool(
                raw.get("overlay_set_by_controller", False),
            )
            self._runtime.backed_off_overlay_target = raw.get("backed_off_overlay_target")
            self._runtime.desired_target = raw.get("desired_target")
            _LOGGER.info(
                "Smart Valve: zone %s restored state=%s, last_target=%s",
                self._zone_id, self._runtime.state, self._runtime.last_valve_target,
            )
        except (ValueError, KeyError):
            _LOGGER.warning(
                "Smart Valve: zone %s corrupt persisted state, starting fresh",
                self._zone_id,
            )
            self._runtime = ValveControllerRuntime()
