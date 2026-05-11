"""Offset Sync Controller — per-zone device offset synchronisation.

Writes device temperature offsets so that the Tado API (and app) displays
the external sensor's reading. With accurate temperature data, Tado's own
modulation algorithm works correctly without needing external compensation.

Unlike SmartValveController (state machine with IDLE/ACTIVE/BACKED_OFF),
OffsetSyncController is stateless: sensor changes → calculate → rate limit → write.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import logging
import time
from typing import TYPE_CHECKING, Any

from .const import (
    DEVICE_OFFSET_MAX,
    DEVICE_OFFSET_MIN,
    SMART_VALVE_CLOUD_RATE_LIMIT,
    SMART_VALVE_DEBOUNCE_WINDOW,
    SVC_OFFSET_MIN_CHANGE,
)

if TYPE_CHECKING:
    from homeassistant.core import CALLBACK_TYPE, HomeAssistant

    from .coordinator import TadoDataUpdateCoordinator

from .climate_helpers import SensorProxy, subscribe_external_sensors

_LOGGER = logging.getLogger(__name__)

# Pause duration after external offset write (seconds)
_EXTERNAL_WRITE_PAUSE: float = SMART_VALVE_CLOUD_RATE_LIMIT


@dataclass
class OffsetSyncRuntime:
    """Runtime state for OffsetSyncController (not persisted directly)."""

    last_written_offset: float | None = None
    last_offset_write_ts: float | None = None  # time.monotonic() clock
    pending_offset: float | None = None  # queued when rate-limited
    paused_until_ts: float | None = None  # manual override pause expiry (monotonic)
    unsub_external_sensors: list[CALLBACK_TYPE] = field(default_factory=list)
    # Lifecycle flag — set in async_deactivate before unsub/cancel so any
    # in-flight sensor callbacks or scheduled debounce timers short-circuit
    # instead of writing to a deactivated controller.
    deactivated: bool = False


class OffsetSyncController:
    """Per-zone offset sync controller — writes device offsets to match external sensor."""

    def __init__(
        self,
        hass: HomeAssistant,
        coordinator: TadoDataUpdateCoordinator,
        zone_id: str,
    ) -> None:
        """Initialize the OffsetSyncController."""
        self._hass = hass
        self._coordinator = coordinator
        self._zone_id = zone_id

        # Convenience references
        self._zcm = coordinator.zone_config_manager
        self._api_client = coordinator.api_client
        self._action_debouncer = coordinator.action_debouncer

        # Runtime state (in-memory)
        self._runtime = OffsetSyncRuntime()

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def zone_id(self) -> str:
        """Return the zone ID."""
        return self._zone_id

    # ------------------------------------------------------------------
    # Core pure functions (static, testable)
    # ------------------------------------------------------------------

    @staticmethod
    def calculate_desired_offset(
        inside_temperature: float,
        current_device_offset: float,
        external_temp: float,
    ) -> float:
        """Calculate and clamp desired offset.

        Formula: clamp(external_temp - (inside_temperature - current_device_offset), -10, +10)

        The TRV raw reading is: inside_temperature - current_device_offset.
        The desired offset makes Tado display external_temp:
            desired_offset = external_temp - TRV_raw
        """
        trv_raw = inside_temperature - current_device_offset
        desired = external_temp - trv_raw
        return round(max(DEVICE_OFFSET_MIN, min(desired, DEVICE_OFFSET_MAX)), 1)

    @staticmethod
    def should_write(
        desired_offset: float,
        current_offset: float,
        min_change: float = SVC_OFFSET_MIN_CHANGE,
    ) -> bool:
        """Return True if |desired - current| >= min_change."""
        return abs(desired_offset - current_offset) >= min_change

    # ------------------------------------------------------------------
    # Rate limiting and pause
    # ------------------------------------------------------------------

    def is_rate_limited(self) -> bool:
        """Return True if last write was less than 300s ago."""
        last_ts = self._runtime.last_offset_write_ts
        if last_ts is None:
            return False
        return (time.monotonic() - last_ts) < SMART_VALVE_CLOUD_RATE_LIMIT

    def is_paused(self) -> bool:
        """Return True if within manual override pause window."""
        paused_until = self._runtime.paused_until_ts
        if paused_until is None:
            return False
        return time.monotonic() < paused_until

    def on_external_offset_write(self) -> None:
        """Handle external offset write — pause sync for one rate limit window.

        Called when handle_set_temp_offset writes to this zone.
        """
        self._runtime.paused_until_ts = time.monotonic() + _EXTERNAL_WRITE_PAUSE
        _LOGGER.info(
            "Offset Sync: zone %s paused for %ss due to external offset write",
            self._zone_id, int(_EXTERNAL_WRITE_PAUSE),
        )

    # ------------------------------------------------------------------
    # Evaluation cycle
    # ------------------------------------------------------------------

    async def async_evaluate(self) -> None:
        """Run evaluation: read inputs → calculate → threshold → rate limit → write."""
        if self._runtime.deactivated:
            return

        from .climate_helpers import read_external_sensor
        from .helpers import get_zone_state

        # Read zone data from coordinator
        zone_data = get_zone_state(self._coordinator.data, self._zone_id)
        if zone_data is None:
            _LOGGER.debug(
                "Offset Sync: zone %s has no zone data — skipping evaluation",
                self._zone_id,
            )
            return

        # Read insideTemperature from zone data
        try:
            inside_temperature = float(
                zone_data["sensorDataPoints"]["insideTemperature"]["celsius"],
            )
        except (KeyError, TypeError, ValueError):
            _LOGGER.warning(
                "Offset Sync: zone %s could not read TRV temperature from "
                "Tado API — skipping this cycle, will retry on next poll",
                self._zone_id,
            )
            return

        # Gate on the schedule/overlay having a heating target (setting.power == "ON").
        # This is a *schedule-level* gate — it's True whenever the current
        # schedule block or overlay has a temperature target, regardless of
        # whether the valve is physically open right now. A 17°C overnight
        # block still counts as ON; only an explicit OFF block / overlay sets
        # power to OFF.
        #
        # Rationale: offset changes trigger TRV motor recalibration (noise),
        # and the offset has no effect anyway when the schedule has no target
        # (no heating decisions to influence). So we only skip during truly
        # inactive schedule blocks — not just because the valve happens to be
        # closed at this instant.
        zone_setting = zone_data.get("setting") or {}
        power = zone_setting.get("power", "OFF")
        if power != "ON":
            _LOGGER.debug(
                "Offset Sync: zone %s schedule has no heating target "
                "(setting.power=%s) — skipping offset write",
                self._zone_id, power,
            )
            return

        # Read external sensor temperature
        external_temp = read_external_sensor(
            self._hass, self._zcm, self._zone_id, "external_temp_sensor",
        )
        if external_temp is None:
            _LOGGER.debug(
                "Offset Sync: zone %s external sensor unavailable — retaining last offset",
                self._zone_id,
            )
            return

        # Read current device offset from offsets cache
        offsets_data = self._coordinator.data.get("offsets", {}) if self._coordinator.data else {}
        current_device_offset: float = 0.0
        if isinstance(offsets_data, dict):
            cached_offset = offsets_data.get(self._zone_id)
            if cached_offset is not None:
                try:
                    current_device_offset = float(cached_offset)
                except (ValueError, TypeError):
                    pass

        # Check pause window (manual override)
        if self.is_paused():
            _LOGGER.debug(
                "Offset Sync: zone %s paused (manual override) — skipping",
                self._zone_id,
            )
            return

        # Calculate desired offset
        desired_offset = self.calculate_desired_offset(
            inside_temperature, current_device_offset, external_temp,
        )

        # Minimum change threshold (per-zone configurable)
        zone_config = self._zcm.get_zone_config(self._zone_id)
        min_change = float(zone_config.get("svc_offset_min_change", SVC_OFFSET_MIN_CHANGE))
        effective_current = (
            self._runtime.last_written_offset
            if self._runtime.last_written_offset is not None
            else current_device_offset
        )

        # Diagnostic summary — one line per evaluation for remote debugging.
        # Visible at DEBUG level. Mirrors the format used by SmartValveController
        # so that "Offset Sync: eval" and "Smart Valve: eval" both answer the
        # same question: what inputs did the controller see this cycle?
        target = (zone_setting.get("temperature") or {}).get("celsius")
        _LOGGER.debug(
            "Offset Sync: zone %s eval — power=%s, target=%s, ext=%.1f, "
            "trv=%.1f, current_offset=%.1f, desired=%.1f, min_change=%.1f",
            self._zone_id, power,
            f"{target:.1f}" if target is not None else "None",
            external_temp, inside_temperature,
            current_device_offset, desired_offset, min_change,
        )

        if not self.should_write(desired_offset, effective_current, min_change):
            return

        # Rate limit check
        if self.is_rate_limited():
            # Queue the latest desired offset for deferred write
            self._runtime.pending_offset = desired_offset
            _LOGGER.debug(
                "Offset Sync: zone %s rate limited, queued offset %.1f°C",
                self._zone_id, desired_offset,
            )
            return

        # Write offset
        await self._async_write_offset(desired_offset)

        # Flush any pending offset if rate limit has expired
        await self._async_flush_pending()

    async def _async_flush_pending(self) -> None:
        """Write pending offset if rate limit window has expired."""
        pending = self._runtime.pending_offset
        if pending is None:
            return

        if self.is_rate_limited():
            return

        # Window expired — write the latest queued offset
        self._runtime.pending_offset = None
        await self._async_write_offset(pending)

    # ------------------------------------------------------------------
    # Write operations
    # ------------------------------------------------------------------

    async def _async_write_offset(self, offset: float) -> None:
        """Write offset to all zone devices via DeviceSyncQueue."""
        from .write_optimizer import DeviceOperation

        serials = self._get_zone_device_serials()
        if not serials:
            _LOGGER.warning(
                "Offset Sync: zone %s has no devices — cannot write offset",
                self._zone_id,
            )
            return

        device_sync_queue = self._coordinator.device_sync_queue
        any_enqueued = False

        for serial in serials:
            async def _do_write(s: str = serial, o: float = offset) -> bool:
                """Write offset to a single device."""
                return await self._api_client.set_device_offset(s, o)

            operation = DeviceOperation(
                device_serial=serial,
                operation_name=f"offset_sync_{self._zone_id}",
                callback=_do_write,
                entity_id=f"offset_sync.zone_{self._zone_id}",
            )
            enqueued = await device_sync_queue.enqueue(operation)
            if enqueued:
                any_enqueued = True
            else:
                _LOGGER.warning(
                    "Offset Sync: zone %s device %s could not be scheduled for "
                    "offset write (too many pending writes) — dropping this update",
                    self._zone_id, serial[:6],
                )

        # If every write was dropped, the TRVs never received the update — do
        # not update internal state or cache, otherwise the next correction
        # attempt would be suppressed as if the write had succeeded.
        if not any_enqueued:
            _LOGGER.warning(
                "Offset Sync: zone %s could not schedule offset write for any "
                "device — leaving state unchanged, will retry on next sensor change",
                self._zone_id,
            )
            return

        # Update runtime state
        self._runtime.last_written_offset = offset
        self._runtime.last_offset_write_ts = time.monotonic()
        self._runtime.pending_offset = None

        # Update coordinator offsets cache so next evaluation uses correct
        # current_device_offset (prevents oscillation from stale cache)
        raw_offsets = self._coordinator.data_loader.get_cached("offsets")
        cached_offsets: dict[str, float] = raw_offsets if isinstance(raw_offsets, dict) else {}
        cached_offsets[self._zone_id] = offset
        self._coordinator.data_loader.update_cache("offsets", cached_offsets)
        if self._coordinator.data and isinstance(self._coordinator.data, dict):
            self._coordinator.data["offsets"] = cached_offsets

        # Persist state
        await self.async_persist_state()

        _LOGGER.info(
            "Offset Sync: zone %s wrote offset %.1f°C to %s device(s)",
            self._zone_id, offset, len(serials),
        )

    def _get_zone_device_serials(self) -> list[str]:
        """Get device serials for this zone from zones_info cache."""
        zones_info = self._coordinator.data_loader.get_cached("zones_info")
        if not zones_info or not isinstance(zones_info, list):
            return []

        for zone in zones_info:
            if str(zone.get("id")) == self._zone_id:
                serials: list[str] = []
                for device in zone.get("devices") or []:
                    serial = device.get("shortSerialNo")
                    if serial:
                        serials.append(serial)
                return serials
        return []

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def async_activate(self) -> None:
        """Activate: load persisted state, subscribe to sensors, evaluate on first poll."""
        await self.async_load_state()

        # Subscribe to external sensor state changes
        proxy = SensorProxy(self._hass, self._coordinator)
        unsubs = subscribe_external_sensors(
            proxy,
            self._zone_id,
            self._on_external_sensor_change,
            include_humidity=False,
        )
        self._runtime.unsub_external_sensors = unsubs

        _LOGGER.info(
            "Offset Sync: zone %s controller activated (last_offset=%s)",
            self._zone_id,
            f"{self._runtime.last_written_offset:.1f}" if self._runtime.last_written_offset is not None else "None",
        )

    async def async_deactivate(self) -> None:
        """Deactivate: unsubscribe sensors, persist state. Does NOT reset offset."""
        # Order: flag → cancel → unsub → persist.
        # Flag first so any sensor event that slips through short-circuits.
        # Cancel before unsub so a pending debounce callback firing between
        # these steps also sees the flag.
        self._runtime.deactivated = True
        self._action_debouncer.cancel(f"offset_sync_{self._zone_id}")

        for unsub in self._runtime.unsub_external_sensors:
            unsub()
        self._runtime.unsub_external_sensors.clear()

        # Persist final state
        await self.async_persist_state()

        _LOGGER.info(
            "Offset Sync: zone %s controller deactivated (offset preserved at %s)",
            self._zone_id,
            f"{self._runtime.last_written_offset:.1f}" if self._runtime.last_written_offset is not None else "None",
        )

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    async def async_persist_state(self) -> None:
        """Persist last_written_offset to zone config.

        last_offset_write_ts is intentionally not persisted — it's a monotonic
        clock value that is meaningless across process restarts.

        Note: async_set_zone_value replaces the entire offset_sync_state dict,
        so any stale last_offset_write_ts left over from older versions is
        cleaned up automatically on the first persist after upgrade.
        """
        state_dict: dict[str, float | None] = {
            "last_written_offset": self._runtime.last_written_offset,
        }
        await self._zcm.async_set_zone_value(
            self._zone_id, "offset_sync_state", state_dict,
        )

    async def async_load_state(self) -> None:
        """Load persisted state on startup."""
        config = self._zcm.get_zone_config(self._zone_id)
        raw = config.get("offset_sync_state")
        if not isinstance(raw, dict):
            # Fresh install — try to read current offset from API
            _LOGGER.info(
                "Offset Sync: zone %s no persisted state, reading offset from API",
                self._zone_id,
            )
            await self._async_load_offset_from_api()
            return

        try:
            offset_raw = raw.get("last_written_offset")
            # Cast inside try so a non-numeric value (e.g. "not-a-float" from
            # a manual edit or schema change) triggers the except fallback
            # rather than leaking a string into runtime.
            self._runtime.last_written_offset = (
                float(offset_raw) if offset_raw is not None else None
            )
            # Do NOT restore last_offset_write_ts — it's a monotonic clock value
            # that is meaningless across process restarts (monotonic resets on
            # boot). Persisting it would cause is_rate_limited() to compare
            # current-monotonic against a pre-restart-monotonic, which can
            # block writes for as long as the previous HA uptime.
            self._runtime.last_offset_write_ts = None
            _LOGGER.info(
                "Offset Sync: zone %s restored state (offset=%s)",
                self._zone_id,
                self._runtime.last_written_offset,
            )
        except (ValueError, TypeError, KeyError):
            _LOGGER.warning(
                "Offset Sync: zone %s corrupt persisted state, starting fresh",
                self._zone_id,
            )
            await self._async_load_offset_from_api()

    async def _async_load_offset_from_api(self) -> None:
        """Read current device offset from API as fallback for fresh install."""
        serials = self._get_zone_device_serials()
        if not serials:
            return

        try:
            offset = await self._api_client.get_device_offset(serials[0])
            if offset is not None:
                self._runtime.last_written_offset = offset
                _LOGGER.info(
                    "Offset Sync: zone %s read current offset from API: %.1f°C",
                    self._zone_id, offset,
                )
        except Exception:
            _LOGGER.info(
                "Offset Sync: zone %s could not read offset from API, starting with 0.0",
                self._zone_id, exc_info=True,
            )

    # ------------------------------------------------------------------
    # Sensor change handler
    # ------------------------------------------------------------------

    def _on_external_sensor_change(self, _event: Any) -> None:
        """Handle external sensor state change — debounce and evaluate."""
        if self._runtime.deactivated:
            return
        self._hass.async_create_task(
            self._action_debouncer.debounce(
                f"offset_sync_{self._zone_id}",
                self.async_evaluate,
                window=SMART_VALVE_DEBOUNCE_WINDOW,
            ),
        )

    # ------------------------------------------------------------------
    # Attributes
    # ------------------------------------------------------------------

    def get_attributes(self) -> dict[str, Any]:
        """Return attributes for climate entity extra_state_attributes."""
        active = not self._runtime.deactivated and not self.is_paused()
        return {
            "valve_control_active": active,
            "valve_control_mode": "offset_sync",
        }
