"""Tado CE API write optimization — debounce, guard, queue, coalesce, schedule preview."""

from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass
from datetime import UTC, datetime
import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from homeassistant.components.climate import HVACMode  # type: ignore[attr-defined]

    from .coordinator import TadoDataUpdateCoordinator
    from .data_loader import DataLoader

_LOGGER = logging.getLogger(__name__)


class ActionGuard:
    """Skip redundant API calls when requested state matches current state."""

    @staticmethod
    def should_skip_temperature(
        requested_temp: float | None,
        current_temp: float | None,
        requested_mode: HVACMode | None,
        current_mode: HVACMode | None,
    ) -> bool:
        """Return True if temperature change is redundant.

        Only skips when ALL requested attributes match current state (AC-2.9).
        If either temp or mode differs, the call proceeds.
        """
        if requested_temp is None:
            return False
        if current_temp is None:
            return False
        # Both temp and mode must match to skip
        temp_matches = requested_temp == current_temp
        mode_matches = requested_mode == current_mode
        return temp_matches and mode_matches

    @staticmethod
    def should_skip_hvac_mode(
        requested_mode: HVACMode,
        current_mode: HVACMode | None,
    ) -> bool:
        """Return True if HVAC mode change is redundant."""
        return requested_mode == current_mode

    @staticmethod
    def should_skip_fan_mode(
        requested_fan: str,
        current_fan: str | None,
    ) -> bool:
        """Return True if fan mode change is redundant."""
        return requested_fan == current_fan

    @staticmethod
    def should_skip_swing_mode(
        requested_swing: str,
        current_swing: str | None,
    ) -> bool:
        """Return True if swing mode change is redundant."""
        return requested_swing == current_swing

    @staticmethod
    def should_skip_preset_mode(
        requested_preset: str,
        current_preset: str | None,
    ) -> bool:
        """Return True if preset mode change is redundant."""
        return requested_preset == current_preset


class ActionDebouncer:
    """Debounce zone-level write operations per zone."""

    def __init__(self, default_window: float = 3.0) -> None:
        """Initialize the ActionDebouncer."""
        self._pending: dict[str, asyncio.TimerHandle] = {}
        self._pending_coros: dict[str, Callable[[], Awaitable[None]]] = {}
        self._default_window: float = default_window
        self._loop: asyncio.AbstractEventLoop | None = None

    def _get_loop(self) -> asyncio.AbstractEventLoop:
        """Return the cached event loop, acquiring it on first call."""
        if self._loop is None:
            self._loop = asyncio.get_running_loop()
        return self._loop

    async def debounce(
        self,
        zone_id: str,
        callback: Callable[[], Awaitable[None]],
        window: float | None = None,
    ) -> None:
        """Schedule callback after debounce window, cancelling any pending call for same zone.

        If window is 0 or negative, execute immediately without scheduling.
        """
        effective_window = window if window is not None else self._default_window

        # Window <= 0 means no debounce — execute immediately
        if effective_window <= 0:
            await callback()
            return

        # Cancel existing pending call for this zone
        self.cancel(zone_id)

        loop = self._get_loop()
        self._pending_coros[zone_id] = callback

        def _fire() -> None:
            """Fire the debounced callback."""
            coro = self._pending_coros.pop(zone_id, None)
            self._pending.pop(zone_id, None)
            if coro is not None:
                asyncio.ensure_future(coro())  # noqa: RUF006 — fire-and-forget by design

        handle = loop.call_later(effective_window, _fire)
        self._pending[zone_id] = handle

    def cancel(self, zone_id: str) -> None:
        """Cancel pending debounce for a zone."""
        handle = self._pending.pop(zone_id, None)
        if handle is not None:
            handle.cancel()
        self._pending_coros.pop(zone_id, None)

    def cancel_all(self) -> None:
        """Cancel all pending debounces (cleanup on unload)."""
        for handle in self._pending.values():
            handle.cancel()
        self._pending.clear()
        self._pending_coros.clear()

    @property
    def pending_zones(self) -> set[str]:
        """Return set of zone IDs with pending debounced calls."""
        return set(self._pending.keys())


@dataclass
class DeviceOperation:
    """Represent a queued device operation."""

    device_serial: str
    operation_name: str
    callback: Callable[[], Awaitable[bool]]
    entity_id: str  # for logging


class DeviceSyncQueue:
    """Sequential execution queue for device-level API operations."""

    def __init__(self, delay: float = 1.0, max_depth: int = 20) -> None:
        """Initialize the DeviceSyncQueue."""
        self._queue: asyncio.Queue[DeviceOperation] = asyncio.Queue(maxsize=max_depth)
        self._delay: float = delay
        self._max_depth: int = max_depth
        self._processor_task: asyncio.Task[None] | None = None
        self._is_processing: bool = False
        self._shutdown_event: asyncio.Event = asyncio.Event()

    async def enqueue(self, operation: DeviceOperation) -> bool:
        """Add operation to queue.

        Returns False if queue is full (AC-4.5).
        """
        try:
            self._queue.put_nowait(operation)
        except asyncio.QueueFull:
            _LOGGER.warning(
                "Device Sync queue full (%s/%s), rejecting %s for %s",
                self._queue.qsize(),
                self._max_depth,
                operation.operation_name,
                operation.entity_id,
            )
            return False

        _LOGGER.debug(
            "Device Sync enqueued %s for %s (depth: %s)",
            operation.operation_name,
            operation.entity_id,
            self._queue.qsize(),
        )

        # Start processor if not already running
        if self._processor_task is None or self._processor_task.done():
            self._shutdown_event.clear()
            self._processor_task = asyncio.create_task(self._process_queue())

        return True

    async def _process_queue(self) -> None:
        """Process operations sequentially with delay between each (CP-4 FIFO, CP-5 fail-forward)."""
        self._is_processing = True
        is_first = True
        try:
            while not self._queue.empty() and not self._shutdown_event.is_set():
                operation = self._queue.get_nowait()

                # Delay between operations (not before the first one)
                if not is_first and self._delay > 0:
                    await asyncio.sleep(self._delay)
                is_first = False

                try:
                    await operation.callback()
                    _LOGGER.debug(
                        "Device Sync completed %s for %s",
                        operation.operation_name,
                        operation.entity_id,
                    )
                except Exception:  # noqa: BLE001 — fail-forward: log and continue (AC-4.4)
                    _LOGGER.warning(
                        "Device Sync failed %s for %s",
                        operation.operation_name,
                        operation.entity_id,
                        exc_info=True,
                    )
                finally:
                    self._queue.task_done()
        finally:
            self._is_processing = False

    @property
    def queue_depth(self) -> int:
        """Return current queue depth."""
        return self._queue.qsize()

    async def shutdown(self) -> None:
        """Stop processing and clear queue."""
        self._shutdown_event.set()

        if self._processor_task is not None and not self._processor_task.done():
            self._processor_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._processor_task
            self._processor_task = None

        # Drain the queue
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
                self._queue.task_done()
            except asyncio.QueueEmpty:
                break

        self._is_processing = False


class RefreshCoalescer:
    """Coalesce multiple post-write coordinator refreshes into one."""

    def __init__(
        self,
        coordinator: TadoDataUpdateCoordinator,
        window: float = 2.0,
        *,
        skip_when_fresh: bool = False,
    ) -> None:
        """Initialize the RefreshCoalescer."""
        self._coordinator = coordinator
        self._window: float = window
        self._pending_timer: asyncio.TimerHandle | None = None
        self._pending_count: int = 0
        self._skip_when_fresh: bool = skip_when_fresh
        self._loop: asyncio.AbstractEventLoop | None = None

    def _get_loop(self) -> asyncio.AbstractEventLoop:
        """Return the cached event loop, acquiring it on first call."""
        if self._loop is None:
            self._loop = asyncio.get_running_loop()
        return self._loop

    def schedule_refresh(self, entity_id: str | None = None) -> None:
        """Schedule a coalesced refresh after the window expires.

        If entity_id is provided and the entity is fresh (and skip_when_fresh
        is enabled), the refresh is skipped entirely — the next scheduled poll
        will naturally sync the state.
        """
        # Conditional Refresh Skip (CP-8)
        if (
            entity_id
            and self._skip_when_fresh
            and self._coordinator.is_entity_fresh(entity_id)
        ):
            _LOGGER.debug(
                "Conditional Refresh Skip: %s is fresh, deferring to next poll",
                entity_id,
            )
            return

        self._pending_count += 1

        # Cancel existing pending refresh and reschedule
        if self._pending_timer is not None:
            self._pending_timer.cancel()

        loop = self._get_loop()
        self._pending_timer = loop.call_later(self._window, self._fire_refresh)

    def _fire_refresh(self) -> None:
        """Execute the coalesced refresh."""
        self._pending_count = 0
        self._pending_timer = None
        asyncio.ensure_future(  # noqa: RUF006 — fire-and-forget by design
            self._coordinator.async_request_refresh(),
        )

    def cancel(self) -> None:
        """Cancel pending refresh (cleanup on unload)."""
        if self._pending_timer is not None:
            self._pending_timer.cancel()
            self._pending_timer = None
        self._pending_count = 0

    @property
    def pending_count(self) -> int:
        """Return number of writes waiting for coalesced refresh."""
        return self._pending_count


class ResumeGuard:
    """Skip resume calls for zones without active overlays."""

    @staticmethod
    def should_skip_resume(
        coordinator: TadoDataUpdateCoordinator,
        zone_id: str,
    ) -> bool:
        """Return True if zone has no active overlay (already following schedule).

        Uses coordinator's cached zone state — no additional API call needed.
        """
        coord_data = coordinator.data or {}
        zones = coord_data.get("zones") or {}
        zone_states = zones.get("zoneStates") or {}
        zone_data = zone_states.get(zone_id) or {}
        overlay_type = zone_data.get("overlayType")
        return overlay_type is None


def _resolve_current_time(current_time: datetime | None) -> datetime:
    """Resolve current time, falling back to UTC if HA is unavailable."""
    if current_time is not None:
        return current_time
    try:
        from homeassistant.util import dt as dt_util  # noqa: PLC0415

        return dt_util.now()
    except ImportError:
        return datetime.now(UTC)


def _find_current_block(
    day_blocks: list[Any],
    current_time_str: str,
) -> dict[str, Any] | None:
    """Find the schedule block covering the given time.

    Blocks are assumed sorted by start time. The current block is the last
    one whose start <= *current_time_str*.
    """
    current_block: dict[str, Any] | None = None
    for block in day_blocks:
        block_start: str = block.get("start", "00:00")
        if block_start <= current_time_str:
            current_block = block
        else:
            break
    return current_block


def _extract_block_celsius(block: dict[str, Any]) -> float | None:
    """Extract the target celsius from a schedule block, or None if OFF/missing."""
    setting: dict[str, Any] = block.get("setting") or {}
    if setting.get("power", "OFF") != "ON":
        return None
    temp_data: dict[str, Any] | None = setting.get("temperature")
    if not temp_data:
        return None
    return temp_data.get("celsius")


def get_current_schedule_target(
    zone_id: str,
    data_loader: DataLoader | None = None,
    current_time: datetime | None = None,
) -> float | None:
    """Get the scheduled target temperature for the current time block.

    Returns the target temperature from the active schedule block that
    covers the current time, or None if no schedule data is available
    or heating is OFF in the current block.

    Reuses ``_get_day_blocks`` from ``smart_comfort`` to avoid duplicating
    schedule-type resolution logic.
    """
    from .smart_comfort import _get_day_blocks  # noqa: PLC0415 — avoid circular import

    if data_loader is None:
        return None

    schedule = data_loader.get_zone_schedule(zone_id)
    if not schedule:
        return None

    now = _resolve_current_time(current_time)
    blocks_dict: dict[str, Any] = schedule.get("blocks") or {}
    schedule_type: str = schedule.get("type", "ONE_DAY")
    day_blocks = _get_day_blocks(blocks_dict, schedule_type, now.weekday())

    if not day_blocks:
        return None

    current_block = _find_current_block(day_blocks, now.strftime("%H:%M"))
    if current_block is None:
        return None

    return _extract_block_celsius(current_block)
