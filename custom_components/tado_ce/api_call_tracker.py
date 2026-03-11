"""Tado CE API Call Tracker — quota monitoring, rate calculation, reset prediction."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
import json
import logging
import os
from pathlib import Path
import shutil
import tempfile
from threading import Lock
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .config_manager import ConfigurationManager

_LOGGER = logging.getLogger(__name__)

# Call type codes
CALL_TYPE_ZONE_STATES = 1
CALL_TYPE_WEATHER = 2
CALL_TYPE_ZONES = 3
CALL_TYPE_MOBILE_DEVICES = 4
CALL_TYPE_OVERLAY = 5
CALL_TYPE_PRESENCE_LOCK = 6
CALL_TYPE_HOME_STATE = 7
CALL_TYPE_CAPABILITIES = 8

CALL_TYPE_NAMES = {
    CALL_TYPE_ZONE_STATES: "zoneStates",
    CALL_TYPE_WEATHER: "weather",
    CALL_TYPE_ZONES: "zones",
    CALL_TYPE_MOBILE_DEVICES: "mobileDevices",
    CALL_TYPE_OVERLAY: "overlay",
    CALL_TYPE_PRESENCE_LOCK: "presenceLock",
    CALL_TYPE_HOME_STATE: "homeState",
    CALL_TYPE_CAPABILITIES: "capabilities",
}

# Rate extrapolation thresholds
_MIN_CALLS_FOR_RATE = 20
_MAX_REASONABLE_RATE = 100
_HOURS_IN_DAY = 24
_DEFAULT_CALLS_PER_HOUR = 15
_DEFAULT_DAY_INTERVAL_MIN = 10
_AVG_CALLS_PER_POLL = 2.5
_MIN_TIME_SPAN_HOURS = 1.0


class APICallTracker:
    """Track API calls with persistent storage.

    Async methods use hass executor for non-blocking I/O.
    Sync methods are kept for compatibility with non-async contexts.
    Supports per-home file paths for multi-home setups.
    """

    def __init__(
        self,
        data_dir: Path,
        retention_days: int = 14,
        home_id: str | None = None,
        config_manager: ConfigurationManager | None = None,
    ) -> None:
        """Initialize API call tracker.

        Args:
            data_dir: Directory for storing call history
            retention_days: Number of days to retain history (0 = forever)
            home_id: Optional home ID for per-home file paths
            config_manager: Optional ConfigurationManager for config-based rate estimation
        """
        self.data_dir = data_dir
        self.retention_days = retention_days
        self.home_id = home_id
        self._config_manager = config_manager

        # Use per-home file path if home_id provided
        from .const import get_data_file  # avoid circular import

        self.history_file = get_data_file("api_call_history", home_id)

        self._lock = Lock()
        self._async_lock = asyncio.Lock()
        self._call_history: dict[str, list[dict[str, Any]]] = {}
        self._last_cleanup_date = None
        self._initialized = False

        # Do not call blocking mkdir here — __init__ runs in the event loop.
        # Directory creation is deferred to _save_history_sync() / _save_history_async().

    def _load_history_sync(self) -> dict[str, Any]:
        """Load call history from disk synchronously."""
        try:
            if self.history_file.exists():
                with self.history_file.open() as f:
                    return json.load(f)  # type: ignore[no-any-return]
        except (OSError, json.JSONDecodeError):
            _LOGGER.exception("Failed to load API call history")
        return {}

    def _save_history_sync(self, data: dict[str, Any]) -> None:
        """Save call history to disk synchronously with atomic write."""
        try:
            self.history_file.parent.mkdir(parents=True, exist_ok=True)

            # Write to temp file first
            with tempfile.NamedTemporaryFile(
                mode="w",
                dir=self.data_dir,
                delete=False,
                suffix=".tmp",
            ) as tmp:
                json.dump(data, tmp, indent=2)
                temp_path = tmp.name

            # Atomic rename (move) to final location
            shutil.move(temp_path, self.history_file)
        except (OSError, json.JSONDecodeError, TypeError):
            _LOGGER.exception("Failed to save API call history")
            # Clean up temp file if it exists
            try:
                if "temp_path" in locals():
                    Path(temp_path).unlink(missing_ok=True)
            except OSError as cleanup_err:
                _LOGGER.debug("Failed to clean up temp file: %s", cleanup_err)

    async def _load_history_async(self) -> dict[str, Any]:
        """Load call history from disk using executor."""
        try:
            loop = asyncio.get_running_loop()
            exists = await loop.run_in_executor(None, self.history_file.exists)
            if exists:
                content = await loop.run_in_executor(
                    None,
                    self.history_file.read_text,
                )
                return json.loads(content)  # type: ignore[no-any-return]
        except (OSError, json.JSONDecodeError):
            _LOGGER.exception("Failed to load API call history")
        return {}

    async def _save_history_async(self, data: dict[str, Any]) -> None:
        """Save call history to disk using executor with atomic write.

        Uses asyncio.Lock to serialize concurrent writes and a unique temp file
        to prevent race conditions where multiple saves compete for the same
        .tmp file path.
        """
        async with self._async_lock:
            try:
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(
                    None,
                    lambda: self.history_file.parent.mkdir(parents=True, exist_ok=True),
                )

                # Use unique temp file to avoid collisions (matches _save_history_sync pattern)
                _temp_fd, temp_path_str = await loop.run_in_executor(
                    None,
                    lambda: tempfile.mkstemp(
                        dir=self.history_file.parent,
                        suffix=".tmp",
                    ),
                )
                temp_path = Path(temp_path_str)

                try:
                    content = json.dumps(data, indent=2)

                    def _write_and_close() -> None:
                        """Write content and close file descriptor."""
                        with os.fdopen(_temp_fd, "w") as f:
                            f.write(content)

                    await loop.run_in_executor(None, _write_and_close)

                    # Atomic move
                    await loop.run_in_executor(
                        None,
                        temp_path.replace,
                        self.history_file,
                    )
                except BaseException:
                    # Clean up temp file on any failure
                    await loop.run_in_executor(None, lambda: temp_path.unlink(missing_ok=True))
                    raise
            except (OSError, TypeError):
                _LOGGER.exception("Failed to save API call history")

    async def async_init(self) -> None:
        """Initialize tracker asynchronously (load history from disk).

        Cleanup is performed outside the lock to avoid deadlock — async_cleanup_old_records
        calls _save_history_async which also acquires _async_lock (non-reentrant).
        Fixes #170.
        """
        if self._initialized:
            return

        async with self._async_lock:
            if self._initialized:  # Double-check after acquiring lock
                return

            self._call_history = await self._load_history_async()
            self._initialized = True
            _LOGGER.debug("Loaded API call history: %s dates", len(self._call_history))

        # Cleanup outside lock — async_cleanup_old_records → _save_history_async
        # also acquires _async_lock, so calling it inside would deadlock.
        await self.async_cleanup_old_records()
        self._last_cleanup_date = datetime.now(UTC).date()  # type: ignore[assignment]

    def _ensure_initialized_sync(self) -> None:
        """Ensure tracker is initialized synchronously.

        Should only be used when async_init() cannot be called.
        """
        if not self._initialized:
            self._call_history = self._load_history_sync()
            self._initialized = True
            _LOGGER.debug("Loaded API call history (sync): %s dates", len(self._call_history))

    async def async_record_call(self, call_type: int, status_code: int, timestamp: datetime | None = None) -> None:
        """Record an API call asynchronously.

        Args:
            call_type: Type of API call (1-7)
            status_code: HTTP status code
            timestamp: Call timestamp (defaults to now in UTC)
        """
        if not self._initialized:
            await self.async_init()

        if timestamp is None:
            timestamp = datetime.now(UTC)
        elif timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=UTC)

        date_key = timestamp.strftime("%Y-%m-%d")
        today = timestamp.date()
        should_cleanup = False

        call_record = {
            "type": call_type,
            "type_name": CALL_TYPE_NAMES.get(call_type, "unknown"),
            "status": status_code,
            "timestamp": timestamp.isoformat(),
        }

        with self._lock:
            if date_key not in self._call_history:
                self._call_history[date_key] = []
            self._call_history[date_key].append(call_record)

            if self._last_cleanup_date is None or self._last_cleanup_date < today:
                self._last_cleanup_date = today  # type: ignore[assignment]
                should_cleanup = True

        # Save using native async I/O
        await self._save_history_async(dict(self._call_history))

        if should_cleanup:
            await self.async_cleanup_old_records()

        _LOGGER.debug("Recorded API call: %s (status %s)", CALL_TYPE_NAMES.get(call_type), status_code)

    def record_call(self, call_type: int, status_code: int, timestamp: datetime | None = None) -> None:
        """Record an API call (sync version, schedules async save).

        This method is sync-compatible but schedules the file write asynchronously.
        Use async_record_call() when in an async context for better performance.
        """
        self._ensure_initialized_sync()

        if timestamp is None:
            timestamp = datetime.now(UTC)
        elif timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=UTC)

        date_key = timestamp.strftime("%Y-%m-%d")

        call_record = {
            "type": call_type,
            "type_name": CALL_TYPE_NAMES.get(call_type, "unknown"),
            "status": status_code,
            "timestamp": timestamp.isoformat(),
        }

        with self._lock:
            if date_key not in self._call_history:
                self._call_history[date_key] = []
            self._call_history[date_key].append(call_record)

        self._save_history_sync(dict(self._call_history))

        _LOGGER.debug("Recorded API call: %s (status %s)", CALL_TYPE_NAMES.get(call_type), status_code)

    def get_call_history(self, days: int = 1) -> list[dict[str, Any]]:
        """Get list of API calls from the last N days.

        Args:
            days: Number of days to retrieve

        Returns:
            List of call records sorted by timestamp (newest first)
        """
        self._ensure_initialized_sync()

        cutoff_date = (datetime.now(UTC) - timedelta(days=days)).strftime("%Y-%m-%d")
        calls = []

        with self._lock:
            for date_key, date_calls in self._call_history.items():
                if date_key >= cutoff_date:
                    calls.extend(date_calls)

        calls.sort(key=lambda x: x["timestamp"], reverse=True)
        return calls

    def get_recent_calls(self, limit: int = 50) -> list[dict[str, Any]]:
        """Get the most recent N calls for sensor attributes."""
        self._ensure_initialized_sync()

        all_calls = []
        with self._lock:
            for date_calls in self._call_history.values():
                all_calls.extend(date_calls)

        all_calls.sort(key=lambda x: x["timestamp"], reverse=True)
        return all_calls[:limit]

    def get_call_counts(self, days: int = 1) -> dict[str, int]:
        """Get counts by call type for the last N days."""
        calls = self.get_call_history(days)
        counts: dict[str, Any] = {}
        for call in calls:
            type_name = call.get("type_name", "unknown")
            counts[type_name] = counts.get(type_name, 0) + 1
        return counts

    async def async_cleanup_old_records(self) -> None:
        """Remove records older than retention period (async)."""
        if self.retention_days == 0:
            return

        cutoff_str = (datetime.now(UTC) - timedelta(days=self.retention_days)).strftime("%Y-%m-%d")
        removed = 0

        with self._lock:
            dates_to_remove = [k for k in self._call_history if k < cutoff_str]
            for date_key in dates_to_remove:
                del self._call_history[date_key]
                removed += 1

        if removed > 0:
            await self._save_history_async(dict(self._call_history))
            _LOGGER.info("Cleaned up %s days of old API call records", removed)

    def cleanup_old_records(self) -> None:
        """Remove records older than retention period (sync)."""
        if self.retention_days == 0:
            return

        self._ensure_initialized_sync()
        cutoff_str = (datetime.now(UTC) - timedelta(days=self.retention_days)).strftime("%Y-%m-%d")

        with self._lock:
            dates_to_remove = [k for k in self._call_history if k < cutoff_str]
            for date_key in dates_to_remove:
                del self._call_history[date_key]

            if dates_to_remove:
                self._save_history_sync(dict(self._call_history))
                _LOGGER.info("Cleaned up %s days of old API call records", len(dates_to_remove))

    def get_daily_usage(self, date: datetime) -> dict[str, Any]:
        """Get API usage statistics for a specific date."""
        self._ensure_initialized_sync()
        date_key = date.strftime("%Y-%m-%d")

        with self._lock:
            date_calls = self._call_history.get(date_key, [])

        by_type: dict[str, Any] = {}
        for call in date_calls:
            type_name = call.get("type_name", "unknown")
            by_type[type_name] = by_type.get(type_name, 0) + 1

        return {"date": date_key, "total_calls": len(date_calls), "by_type": by_type}

    def _rate_from_history(self) -> tuple[float, str] | None:
        """Estimate calls-per-hour from recent call history.

        Returns:
            Tuple of (calls_per_hour, description) or None if insufficient data.
        """
        calls = self.get_call_history(days=1)
        if len(calls) < _MIN_CALLS_FOR_RATE:
            return None

        call_times: list[datetime] = []
        for call in calls:
            try:
                call_time = datetime.fromisoformat(call["timestamp"])
                if call_time.tzinfo is None:
                    call_time = call_time.replace(tzinfo=UTC)
                call_times.append(call_time)
            except (ValueError, TypeError, KeyError):
                continue

        if len(call_times) < _MIN_CALLS_FOR_RATE:
            return None

        call_times.sort()
        time_span_hours = (call_times[-1] - call_times[0]).total_seconds() / 3600
        if time_span_hours < _MIN_TIME_SPAN_HOURS:
            return None

        rate = len(call_times) / time_span_hours
        if not 1 <= rate <= _MAX_REASONABLE_RATE:
            return None

        return rate, f"history ({len(call_times)} calls / {time_span_hours:.1f}h)"

    def _rate_from_config(self) -> tuple[float, str]:
        """Estimate calls-per-hour from polling config.

        Returns:
            Tuple of (calls_per_hour, description).
        """
        try:
            config_manager = self._config_manager
            custom_day = config_manager.get_custom_day_interval() if config_manager else None
            day_interval = custom_day or _DEFAULT_DAY_INTERVAL_MIN
            polls_per_hour = 60 / day_interval
            return polls_per_hour * _AVG_CALLS_PER_POLL, f"config (day={day_interval}min)"
        except (AttributeError, TypeError, ValueError) as e:
            _LOGGER.debug("Failed to get config rate: %s", e)
            return _DEFAULT_CALLS_PER_HOUR, "default"

    def extrapolate_reset_time(self, current_used: int) -> datetime | None:
        """Extrapolate when the API reset happened by looking at usage rate.

        Uses a hybrid approach:
        1. If call history has enough data, use actual call rate (more accurate)
        2. Otherwise, fall back to config-based rate estimation

        Args:
            current_used: Current number of API calls used today (from Tado API)

        Returns:
            Estimated reset time (datetime in UTC), or None if not enough data
        """
        if current_used <= 0:
            return None

        self._ensure_initialized_sync()

        # Try history-based rate first, fall back to config-based
        history_result = self._rate_from_history()
        if history_result is not None:
            calls_per_hour, rate_source = history_result
        else:
            calls_per_hour, rate_source = self._rate_from_config()

        if calls_per_hour < 1:
            _LOGGER.debug("Calls per hour invalid: %s", calls_per_hour)
            return None

        # Extrapolate backwards: how many hours ago was used = 0?
        hours_since_reset = current_used / calls_per_hour

        if hours_since_reset > _HOURS_IN_DAY or hours_since_reset < 0:
            _LOGGER.debug("Extrapolated reset time out of range: %.2fh ago", hours_since_reset)
            return None

        now_utc = datetime.now(UTC)
        estimated_reset = now_utc - timedelta(hours=hours_since_reset)

        _LOGGER.debug(
            "Extrapolated reset time: %s UTC (used=%s, rate=%.1f/h [%s], %.1fh ago)",
            estimated_reset.strftime("%H:%M"),
            current_used,
            calls_per_hour,
            rate_source,
            hours_since_reset,
        )

        return estimated_reset
