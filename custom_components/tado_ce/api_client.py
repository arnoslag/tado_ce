"""Tado CE API Client — async HTTP with per-entry isolation for multi-home support.

Async HTTP client using aiohttp with per-entry isolation for multi-home support.
"""

from __future__ import annotations

import asyncio
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from http import HTTPStatus
import json
import logging
from typing import TYPE_CHECKING, Any

import aiohttp

from .api_call_tracker import (
    CALL_TYPE_CAPABILITIES,
    CALL_TYPE_HOME_STATE,
    CALL_TYPE_MOBILE_DEVICES,
    CALL_TYPE_OVERLAY,
    CALL_TYPE_PRESENCE_LOCK,
    CALL_TYPE_WEATHER,
    CALL_TYPE_ZONE_STATES,
    CALL_TYPE_ZONES,
)
from .const import API_ENDPOINT_DEVICES, CLIENT_ID, CONFIG_FILE, TADO_API_BASE, TADO_AUTH_URL
from .exceptions import TadoAuthError, TadoSyncError

if TYPE_CHECKING:
    from pathlib import Path

    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

    from .api_call_tracker import APICallTracker
    from .config_manager import ConfigurationManager
    from .data_loader import DataLoader

_LOGGER = logging.getLogger(__name__)


def _detect_call_type(endpoint: str) -> int | None:
    """Detect API call type from endpoint."""
    if "zoneStates" in endpoint:
        return CALL_TYPE_ZONE_STATES
    if "weather" in endpoint:
        return CALL_TYPE_WEATHER
    if "capabilities" in endpoint:
        return CALL_TYPE_CAPABILITIES
    if "zones" in endpoint and "overlay" not in endpoint:
        return CALL_TYPE_ZONES
    if "mobileDevices" in endpoint:
        return CALL_TYPE_MOBILE_DEVICES
    if "overlay" in endpoint:
        return CALL_TYPE_OVERLAY
    if "presenceLock" in endpoint:
        return CALL_TYPE_PRESENCE_LOCK
    if endpoint == "state":
        return CALL_TYPE_HOME_STATE
    return None


class TadoApiClient:
    """Async Tado API client with automatic token management."""

    # Token cache duration (5 minutes to be safe, Tado tokens valid for ~10 minutes)
    TOKEN_CACHE_DURATION = 300

    def __init__(
        self,
        session: aiohttp.ClientSession,
        hass: HomeAssistant | None = None,
        home_id: str | None = None,
        refresh_token: str | None = None,
        config_manager: ConfigurationManager | None = None,
        api_tracker: APICallTracker | None = None,
        data_loader: DataLoader | None = None,
        config_entry: ConfigEntry | None = None,
    ) -> None:
        """Initialize async client.

        Args:
            session: aiohttp ClientSession (should be from Home Assistant)
            hass: Home Assistant instance (for accessing config_manager)
            home_id: Tado home ID for per-home file paths.
                     If provided, client uses config_{home_id}.json instead of
                     global config.json. Required for multi-home isolation.
            refresh_token: OAuth refresh token injected from config entry data.
                           If provided, _load_config() uses this instead of reading
                           from config file. Required for multi-home isolation.
            config_manager: ConfigurationManager instance for this entry.
                           Used by save_ratelimit() for test_mode check.
            api_tracker: APICallTracker instance for this entry.
            data_loader: DataLoader instance for write-through cache updates.
            config_entry: HA ConfigEntry for persisting rotated tokens across restarts.
        """
        self._session = session
        self._hass = hass  # Store hass for real-time config access
        self._access_token: str | None = None
        self._token_expiry: datetime | None = None
        self._refresh_lock = asyncio.Lock()
        self._rate_limit: dict[str, Any] = {}
        self._home_id: str | None = home_id
        self._injected_refresh_token: str | None = refresh_token
        self._config_manager = config_manager
        self._api_tracker = api_tracker
        self._data_loader = data_loader
        self._config_entry = config_entry

    def _get_data_file(self, base_name: str) -> Path:
        """Get per-home data file path.

        Args:
            base_name: Base filename without extension (e.g., "zones", "weather")

        Returns:
            Path to the data file
        """
        from .const import get_data_file

        return get_data_file(base_name, self._home_id)

    def _extract_base_name(self, file_path: Path) -> str:
        """Extract base name from per-home file path.

        Strips the ``_{home_id}`` suffix from filenames to get the cache key.
        e.g. ``zones_12345.json`` → ``zones``, ``weather_12345.json`` → ``weather``.

        Args:
            file_path: Path to the per-home JSON file.

        Returns:
            Base name suitable for DataLoader cache key.
        """
        stem = file_path.stem
        if self._home_id and stem.endswith(f"_{self._home_id}"):
            return stem[: -(len(self._home_id) + 1)]
        return stem

    async def _ensure_home_id(self) -> str | None:
        """Ensure home_id is loaded and cached.

        If home_id was injected via constructor, returns immediately.
        Falls back to reading per-home config file if not injected.
        """
        if self._home_id is None:
            config = await self._load_config()
            self._home_id = config.get("home_id")
        return self._home_id

    async def _load_config(self) -> dict[str, Any]:
        """Load config from file using native async I/O.

        Uses per-home config file (config_{home_id}.json) when home_id is set.
        Falls back to DATA_DIR/config.json when no home_id (bootstrap only).
        If refresh_token was injected via constructor, it takes precedence.
        """
        try:
            # Use per-home config file when home_id is available
            if self._home_id:
                config_path = self._get_data_file("config")
            else:
                config_path = CONFIG_FILE

            if not await self._hass.async_add_executor_job(config_path.exists):  # type: ignore[union-attr]
                result = {"home_id": self._home_id, "refresh_token": None}
                # Use injected refresh_token if available
                if self._injected_refresh_token:
                    result["refresh_token"] = self._injected_refresh_token
                return result

            content = await self._hass.async_add_executor_job(  # type: ignore[union-attr]
                config_path.read_text,
            )
            config = json.loads(content)
            # Cache home_id when loading config
            if config.get("home_id"):
                self._home_id = config["home_id"]
            # Injected refresh_token takes precedence
            if self._injected_refresh_token:
                config["refresh_token"] = self._injected_refresh_token
            return config  # type: ignore[no-any-return]
        except (OSError, json.JSONDecodeError, KeyError):
            _LOGGER.exception("Failed to load config")
            result = {"home_id": self._home_id, "refresh_token": None}
            if self._injected_refresh_token:
                result["refresh_token"] = self._injected_refresh_token
            return result

    async def _save_config(self, config: dict[str, Any]) -> None:
        """Save config to file atomically using native async I/O.

        Writes to per-home config file (config_{home_id}.json) when home_id
        is set. Falls back to DATA_DIR/config.json when no home_id.
        Per-home isolation prevents token rotation for one home from
        corrupting another home's config.
        """
        try:
            # Use per-home config file when home_id is available
            if self._home_id:
                config_path = self._get_data_file("config")
            else:
                config_path = CONFIG_FILE

            await self._hass.async_add_executor_job(  # type: ignore[union-attr]
                lambda: config_path.parent.mkdir(parents=True, exist_ok=True),
            )

            temp_path = config_path.with_suffix(".tmp")
            content = json.dumps(config, indent=2)
            await self._hass.async_add_executor_job(  # type: ignore[union-attr]
                temp_path.write_text,
                content,
            )

            # Atomic move
            await self._hass.async_add_executor_job(  # type: ignore[union-attr]
                temp_path.replace,
                config_path,
            )

            # Write-through: update DataLoader cache
            if self._data_loader is not None:
                self._data_loader.update_cache("config", config)
        except OSError:
            _LOGGER.exception("Failed to save config")

    def _parse_ratelimit_headers(self, headers: dict[str, Any]) -> None:
        """Parse Tado rate limit headers.

        Expected format:
        - RateLimit-Policy: "perday";q=5000;w=86400
        - RateLimit: "perday";r=4962;t=xxxxx (t= may not always be present)

        Note: Header names are case-sensitive in dict, so we do case-insensitive lookup.
        Tado may not always return 't=' (reset seconds).
        """
        # Case-insensitive header lookup (Tado uses RateLimit-Policy, not ratelimit-policy)
        policy = ""
        ratelimit = ""
        for key, value in headers.items():
            key_lower = key.lower()
            if key_lower == "ratelimit-policy":
                policy = value
            elif key_lower == "ratelimit":
                ratelimit = value

        _LOGGER.debug("Rate limit headers - policy: %s, ratelimit: %s", policy, ratelimit)

        # Parse limit from policy (q=5000)
        if "q=" in policy:
            with suppress(ValueError, IndexError):
                self._rate_limit["limit"] = int(policy.split("q=")[1].split(";")[0])

        # Parse remaining from ratelimit (r=4962)
        if "r=" in ratelimit:
            with suppress(ValueError, IndexError):
                self._rate_limit["remaining"] = int(ratelimit.split("r=")[1].split(";")[0])

        # Tado API's t= header is unreliable (points to midnight UTC, not actual reset ~11:24 UTC).
        # w=86400 is the window size, not time until reset.
        # Clear stale reset_seconds so save_ratelimit uses Strategy 2/3/4.
        self._rate_limit.pop("reset_seconds", None)

        _LOGGER.debug("Parsed rate limit: %s", self._rate_limit)

    async def _load_ratelimit(self) -> dict[str, Any]:
        """Load rate limit file using executor I/O."""
        try:
            await self._ensure_home_id()
            ratelimit_path = self._get_data_file("ratelimit")
            path_exists = await self._hass.async_add_executor_job(  # type: ignore[union-attr]
                ratelimit_path.exists,
            )
            if path_exists:
                content = await self._hass.async_add_executor_job(  # type: ignore[union-attr]
                    ratelimit_path.read_text,
                )
                return json.loads(content)  # type: ignore[no-any-return]
        except (FileNotFoundError, json.JSONDecodeError, OSError) as e:
            _LOGGER.debug("Could not load ratelimit file: %s", e)
        return {}

    async def save_ratelimit(self, status: str = "ok") -> None:
        """Save current rate limit info to file for sensor updates.

        Includes advanced reset detection from tado_api.py:
        - Detects when rate limit resets (remaining increases significantly)
        - Uses multiple strategies to calculate reset time
        - Tracks last known reset time for accurate predictions

        Test Mode Full Simulation
        - When Test Mode is ON, simulates a 100-call API tier
        - Stores simulated values in ratelimit.json
        - All other components read from ratelimit.json without recalculation

        Args:
            status: Status string ("ok", "rate_limited", "error")
        """
        now_utc = datetime.now(UTC)

        # Load previous rate limit data to detect reset (native async)
        prev_data = await self._load_ratelimit()

        # Get real API values from parsed headers
        real_limit = self._rate_limit.get("limit", 5000)
        real_remaining = self._rate_limit.get("remaining", 5000)
        reset_seconds = self._rate_limit.get("reset_seconds", 0)

        # Check Test Mode from config_manager (real-time, not cached)
        test_mode_enabled = False
        config_manager = self._config_manager
        if config_manager is None:
            _LOGGER.debug("No config_manager available for test_mode check, assuming test_mode=False")

        if config_manager:
            try:
                test_mode_enabled = config_manager.get_test_mode_enabled()
            except (AttributeError, TypeError) as e:
                _LOGGER.warning("Could not get test_mode from config_manager: %s", e)

        _LOGGER.debug("save_ratelimit: test_mode_enabled=%s", test_mode_enabled)

        # Get previous remaining and last known reset time
        prev_remaining = prev_data.get("remaining")
        last_reset_utc = prev_data.get("last_reset_utc")

        if test_mode_enabled:
            # === TEST MODE: SIMULATED 100-CALL TIER ===
            # Independent 24-hour cycle per Test Mode session
            # Each enable starts a fresh cycle, disable returns to Live quota

            prev_test_mode = prev_data.get("test_mode", False)
            prev_test_mode_start = prev_data.get("test_mode_start_time")
            prev_test_mode_used = prev_data.get("test_mode_used", 0)

            _LOGGER.debug(
                "Test Mode: prev_test_mode=%s, prev_test_mode_start=%s, prev_test_mode_used=%s",
                prev_test_mode,
                prev_test_mode_start,
                prev_test_mode_used,
            )

            # Detect fresh enable (transition from disabled to enabled)
            # OR first time enabling (no start time recorded)
            fresh_enable = not prev_test_mode or prev_test_mode_start is None

            # Backup live last_reset_utc when entering Test Mode
            # This allows restoring the correct reset time when Test Mode is disabled
            if fresh_enable and last_reset_utc:
                _LOGGER.info("Test Mode: Backing up live last_reset_utc=%s", last_reset_utc)
                # Will be saved as live_last_reset_utc in the data dict below

            # Check for 24h cycle expiry
            cycle_expired = False
            if not fresh_enable and prev_test_mode_start:
                try:
                    start_time = datetime.fromisoformat(
                        prev_test_mode_start,
                    )
                    if start_time.tzinfo is None:
                        start_time = start_time.replace(tzinfo=UTC)
                    cycle_end = start_time + timedelta(hours=24)
                    if now_utc >= cycle_end:
                        cycle_expired = True
                        _LOGGER.info(
                            "Test Mode: 24h cycle expired (started: %s, now: %s)",
                            prev_test_mode_start,
                            now_utc.isoformat(),
                        )
                except (ValueError, TypeError) as e:
                    _LOGGER.warning("Test Mode: Failed to parse start time: %s", e)
                    fresh_enable = True  # Treat as fresh enable on parse error

            # Reset on fresh enable or cycle expiry
            if fresh_enable or cycle_expired:
                test_mode_start_time = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
                test_mode_used = 0
                _LOGGER.info(
                    "Test Mode: %s - starting new cycle at %s",
                    "Fresh enable" if fresh_enable else "24h cycle reset",
                    test_mode_start_time,
                )
            else:
                # Continue existing cycle
                test_mode_start_time = prev_test_mode_start  # type: ignore[assignment]
                test_mode_used = prev_test_mode_used

            # Handle error status - preserve test_mode_used
            if status == "error":
                _LOGGER.debug("Test Mode: Error status, preserving used=%s", test_mode_used)
            else:
                # Increment by 1, cap at 100
                test_mode_used = min(test_mode_used + 1, 100)
                _LOGGER.debug("Test Mode: Simulated used=%s", test_mode_used)

            # Calculate simulated values
            limit = 100
            used = test_mode_used
            remaining = max(0, 100 - test_mode_used)
            percentage_used = round(test_mode_used, 1)  # used is already percentage for 100-call tier
            test_mode_flag = True

            # Calculate simulated reset time from test_mode_start_time
            try:
                start_time = datetime.fromisoformat(
                    test_mode_start_time,
                )
                if start_time.tzinfo is None:
                    start_time = start_time.replace(tzinfo=UTC)
                test_mode_reset_at = start_time + timedelta(hours=24)
                test_mode_reset_seconds = int((test_mode_reset_at - now_utc).total_seconds())
                test_mode_reset_seconds = max(0, test_mode_reset_seconds)
            except (ValueError, TypeError) as e:
                _LOGGER.warning("Test Mode: Failed to calculate reset time: %s", e)
                test_mode_reset_at = now_utc + timedelta(hours=24)
                test_mode_reset_seconds = 86400

            _LOGGER.debug(
                "Test Mode: Storing simulated values - used=%s, remaining=%s, limit=%s, reset_at=%s",
                used,
                remaining,
                limit,
                test_mode_reset_at.isoformat(),
            )
        else:
            # === NORMAL MODE: REAL API VALUES ===
            limit = real_limit
            remaining = real_remaining
            used = limit - remaining
            percentage_used = round((used / limit) * 100, 1) if limit > 0 else 0
            test_mode_flag = False

            # Restore live last_reset_utc when exiting Test Mode
            # This ensures we use the correct reset time instead of re-estimating
            prev_test_mode = prev_data.get("test_mode", False)
            if prev_test_mode:
                # Just exited Test Mode - restore backed up reset time
                live_last_reset_utc = prev_data.get("live_last_reset_utc")
                if live_last_reset_utc:
                    last_reset_utc = live_last_reset_utc
                    _LOGGER.info("Test Mode disabled: Restored live last_reset_utc=%s", last_reset_utc)
                else:
                    _LOGGER.debug("Test Mode disabled: No live_last_reset_utc backup found, will re-estimate")

            # Detect if rate limit has reset (remaining increased significantly)
            # Use dynamic threshold: max(20, 5% of limit) to handle both 5000 and 100 call limits
            # - 5000 calls: threshold = max(20, 250) = 250
            # - 100 calls: threshold = max(20, 5) = 20
            if prev_remaining is not None and remaining is not None:
                reset_threshold = max(20, int(limit * 0.05))
                if remaining > prev_remaining + reset_threshold:  # Reset detected
                    last_reset_utc = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
                    _LOGGER.info(
                        "Rate limit reset detected at %s (remaining: %s -> %s, threshold: %s)",
                        last_reset_utc,
                        prev_remaining,
                        remaining,
                        reset_threshold,
                    )

        # Calculate reset time using multiple strategies
        calculated_reset_seconds = None

        # Strategy 1: Use API-provided reset_seconds if available and valid
        if reset_seconds and reset_seconds > 0:
            calculated_reset_seconds = reset_seconds

        # Strategy 2: Calculate from last known reset time (rolling 24h window)
        if calculated_reset_seconds is None and last_reset_utc:
            try:
                last_reset = datetime.fromisoformat(last_reset_utc)
                next_reset = last_reset + timedelta(hours=24)

                # If next_reset is in the past, add 24h until it's in the future
                while next_reset <= now_utc:
                    next_reset += timedelta(hours=24)

                seconds_until_reset = int((next_reset - now_utc).total_seconds())

                if seconds_until_reset > 0:
                    calculated_reset_seconds = seconds_until_reset
                    _LOGGER.debug("Using last_reset_utc: next reset at %s UTC", next_reset.strftime("%H:%M"))
            except (ValueError, TypeError) as e:
                _LOGGER.debug("Failed to calculate reset from last_reset_utc: %s", e)

        # Strategy 3: Extrapolate from usage rate (NEW)
        # Calculate average API calls per hour, then extrapolate backwards to find reset time.
        # This is more accurate than "first call mode" because it uses actual usage patterns.
        # NOTE: Only use this if we don't have last_reset_utc - don't overwrite existing value!
        if calculated_reset_seconds is None and used > 0:
            tracker = self._api_tracker
            if tracker:
                try:
                    estimated_reset = tracker.extrapolate_reset_time(used)
                    if estimated_reset:
                        # Only update last_reset_utc if we don't have one
                        # Don't overwrite existing value from detected reset!
                        if not last_reset_utc:
                            last_reset_utc = estimated_reset.strftime("%Y-%m-%dT%H:%M:%SZ")
                            _LOGGER.debug("Set last_reset_utc from extrapolation: %s", last_reset_utc)

                        next_reset = estimated_reset + timedelta(hours=24)
                        seconds_until_reset = int((next_reset - now_utc).total_seconds())

                        if seconds_until_reset > 0:
                            calculated_reset_seconds = seconds_until_reset
                            _LOGGER.debug("Using extrapolated reset time: %s UTC", estimated_reset.strftime("%H:%M"))
                except (ValueError, TypeError, KeyError) as e:
                    _LOGGER.debug("Failed to extrapolate reset time: %s", e)

        # Strategy 4: Estimate from call history (first call mode)
        # Look at the first call of each day and find the most common time (mode).
        # This filters out outliers like HA restarts at odd hours.
        # The reset time is fixed (~11:24 UTC) based on when the account first made API calls.
        if calculated_reset_seconds is None:
            tracker = self._api_tracker
            if tracker:
                try:
                    # Get first call of each day from history
                    first_calls_by_day: dict[str, Any] = {}
                    all_calls = tracker.get_call_history(days=14)

                    for call in all_calls:
                        ts = call["timestamp"]
                        call_time = datetime.fromisoformat(ts)
                        if call_time.tzinfo is None:
                            call_time = call_time.replace(tzinfo=UTC)

                        date_key = call_time.strftime("%Y-%m-%d")
                        if date_key not in first_calls_by_day or call_time < first_calls_by_day[date_key]:
                            first_calls_by_day[date_key] = call_time

                    if len(first_calls_by_day) >= 2:
                        # Round each first call time to nearest hour and count occurrences
                        hour_counts: dict[str, Any] = {}
                        for first_call in first_calls_by_day.values():
                            # Round to nearest hour
                            hour = first_call.hour
                            if first_call.minute >= 30:
                                hour = (hour + 1) % 24
                            hour_counts[hour] = hour_counts.get(hour, 0) + 1

                        # Find most common hour (mode) - require at least 2 occurrences
                        # to filter out outliers when we have limited data
                        most_common_hour = max(hour_counts, key=hour_counts.get)  # type: ignore[arg-type]
                        most_common_count = hour_counts[most_common_hour]

                        # If no hour has >= 2 occurrences, we don't have enough data
                        if most_common_count < 2:
                            _LOGGER.debug(
                                "Not enough data for mode calculation (%s days, no hour with 2+ occurrences)",
                                len(first_calls_by_day),
                            )
                        else:
                            # Get average minute from calls in that hour range
                            minutes_in_hour = []
                            for first_call in first_calls_by_day.values():
                                call_hour = first_call.hour
                                if first_call.minute >= 30:
                                    call_hour = (call_hour + 1) % 24
                                if call_hour == most_common_hour:
                                    # Use actual hour:minute for averaging
                                    minutes_in_hour.append(first_call.hour * 60 + first_call.minute)

                            if minutes_in_hour:
                                avg_minutes = sum(minutes_in_hour) // len(minutes_in_hour)
                                reset_hour = avg_minutes // 60
                                reset_minute = avg_minutes % 60

                                today_reset = now_utc.replace(
                                    hour=reset_hour,
                                    minute=reset_minute,
                                    second=0,
                                    microsecond=0,
                                )

                                if today_reset <= now_utc:
                                    next_reset = today_reset + timedelta(days=1)
                                else:
                                    next_reset = today_reset

                                seconds_until_reset = int((next_reset - now_utc).total_seconds())
                                if seconds_until_reset > 0:
                                    calculated_reset_seconds = seconds_until_reset
                                    _LOGGER.debug(
                                        "Estimated reset at %02d:%02d UTC (mode from %s days, %s matches)",
                                        reset_hour,
                                        reset_minute,
                                        len(first_calls_by_day),
                                        hour_counts.get(most_common_hour, 0),
                                    )
                except (ValueError, TypeError, KeyError) as e:
                    _LOGGER.debug("Failed to estimate reset from call history: %s", e)

        # Format reset time for display
        reset_at = None
        reset_human = None

        # Test Mode uses its own reset time calculation
        if test_mode_flag:
            # Use Test Mode reset time (test_mode_start_time + 24h)
            reset_seconds = test_mode_reset_seconds
            reset_at = test_mode_reset_at.isoformat()
            hours = test_mode_reset_seconds // 3600
            minutes = (test_mode_reset_seconds % 3600) // 60
            reset_human = f"{hours}h {minutes}m" if hours > 0 else f"{minutes}m"
        elif calculated_reset_seconds and calculated_reset_seconds > 0:
            hours = calculated_reset_seconds // 3600
            minutes = (calculated_reset_seconds % 3600) // 60
            reset_human = f"{hours}h {minutes}m" if hours > 0 else f"{minutes}m"
            reset_dt = now_utc + timedelta(seconds=calculated_reset_seconds)
            reset_at = reset_dt.isoformat()
            reset_seconds = calculated_reset_seconds

        # Update status based on usage
        if remaining == 0:
            status = "rate_limited"
        elif percentage_used > 80:
            status = "warning"

        data = {
            "limit": limit,
            "remaining": remaining,
            "used": used,
            "percentage_used": percentage_used,
            "reset_seconds": reset_seconds or None,
            "reset_at": reset_at,
            "reset_human": reset_human,
            "last_updated": now_utc.isoformat(),
            "last_reset_utc": last_reset_utc,
            "status": status,
            "test_mode": test_mode_flag,  # Indicate if values are simulated
        }

        if test_mode_flag:
            data["test_mode_start_time"] = test_mode_start_time
            data["test_mode_used"] = test_mode_used
            # Backup live last_reset_utc when in Test Mode
            # Use existing backup if available, otherwise use current last_reset_utc
            live_backup = prev_data.get("live_last_reset_utc") or last_reset_utc
            if live_backup:
                data["live_last_reset_utc"] = live_backup
        else:
            # Preserve previous Test Mode state when disabled (for debugging/logging)
            # but don't use it for calculations
            prev_start = prev_data.get("test_mode_start_time")
            prev_used = prev_data.get("test_mode_used")
            if prev_start is not None:
                data["test_mode_start_time"] = prev_start
            if prev_used is not None:
                data["test_mode_used"] = prev_used
            # Clear live_last_reset_utc backup after restoring (no longer needed)
            # Don't persist it in Normal Mode to keep data clean

        try:
            await self._save_ratelimit(data)
            if test_mode_flag:
                _LOGGER.debug("Test Mode: Rate limit saved (simulated): %s/%s", used, limit)
            else:
                _LOGGER.debug("Rate limit saved: %s/%s (%s%%)", used, limit, percentage_used)
        except OSError as e:
            _LOGGER.debug("Failed to save rate limit: %s", e)

    async def _save_ratelimit(self, data: dict[str, Any]) -> None:
        """Save rate limit using executor I/O with atomic write."""
        ratelimit_path = self._get_data_file("ratelimit")

        await self._hass.async_add_executor_job(  # type: ignore[union-attr]
            lambda: ratelimit_path.parent.mkdir(parents=True, exist_ok=True),
        )

        temp_path = ratelimit_path.with_suffix(".tmp")
        content = json.dumps(data, indent=2)
        await self._hass.async_add_executor_job(  # type: ignore[union-attr]
            temp_path.write_text,
            content,
        )

        # Atomic move
        await self._hass.async_add_executor_job(  # type: ignore[union-attr]
            temp_path.replace,
            ratelimit_path,
        )

    async def get_access_token(self) -> str | None:
        """Get valid access token with automatic refresh.

        Uses lock to prevent concurrent token refreshes which would
        waste API calls and potentially cause race conditions.

        Returns:
            Valid access token, or None if refresh failed
        """
        # All token checks must be inside lock to prevent race condition
        async with self._refresh_lock:
            # Check if cached token still valid (with 10s buffer for clock skew)
            if self._access_token and self._token_expiry:
                if datetime.now(UTC) < (self._token_expiry - timedelta(seconds=10)):
                    return self._access_token

            # Token expired or missing, refresh it
            return await self._refresh_token()

    async def _refresh_token(self) -> str | None:
        """Refresh access token using refresh token."""
        config = await self._load_config()
        refresh_token = config.get("refresh_token")

        if not refresh_token:
            _LOGGER.error("No refresh token available")
            return None

        _LOGGER.debug("Refreshing access token...")

        try:
            async with self._session.post(
                f"{TADO_AUTH_URL}/token",
                data={
                    "client_id": CLIENT_ID,
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                },
            ) as resp:
                if resp.status != HTTPStatus.OK:
                    error_text = await resp.text()
                    _LOGGER.error("Token refresh failed: %s - %s", resp.status, error_text)
                    if "invalid_grant" in error_text:
                        _LOGGER.error("Refresh token expired - user must re-authenticate")
                        config["refresh_token"] = None
                        await self._save_config(config)
                        raise TadoAuthError("Refresh token expired (invalid_grant)")
                    return None

                data = await resp.json()
                self._access_token = data.get("access_token")
                new_refresh_token = data.get("refresh_token")

                if not self._access_token:
                    _LOGGER.error("No access token in response")
                    return None

                # Save new refresh token if rotated
                if new_refresh_token and new_refresh_token != refresh_token:
                    config["refresh_token"] = new_refresh_token
                    await self._save_config(config)
                    # Update in-memory injected token so _load_config() uses the new one
                    self._injected_refresh_token = new_refresh_token
                    # Persist to ConfigEntry.data so token survives HA restarts
                    if self._hass and self._config_entry:
                        new_data = {**self._config_entry.data, "refresh_token": new_refresh_token}
                        self._hass.config_entries.async_update_entry(self._config_entry, data=new_data)
                    _LOGGER.debug("Refresh token rotated and saved")

                self._token_expiry = datetime.now(UTC) + timedelta(seconds=self.TOKEN_CACHE_DURATION)
                _LOGGER.debug("Access token refreshed successfully")
                return self._access_token

        except aiohttp.ClientError:
            _LOGGER.exception("Network error during token refresh")
            return None
        except Exception:
            _LOGGER.exception("Unexpected error during token refresh")
            return None

    async def api_call(
        self,
        endpoint: str,
        method: str = "GET",
        data: dict[str, Any] | None = None,
        parse_ratelimit: bool = True,
    ) -> dict[str, Any] | None:
        """Make authenticated API call.

        Args:
            endpoint: API endpoint (e.g., "zoneStates", "weather")
            method: HTTP method
            data: Request body data
            parse_ratelimit: Whether to parse rate limit headers

        Returns:
            Response data, or None if failed
        """
        token = await self.get_access_token()
        if not token:
            _LOGGER.error("Failed to get access token")
            return None

        config = await self._load_config()
        home_id = config.get("home_id")
        if not home_id:
            _LOGGER.error("No home_id configured")
            return None

        url = f"{TADO_API_BASE}/homes/{home_id}/{endpoint}"
        headers = {"Authorization": f"Bearer {token}"}

        # Detect call type for tracking
        call_type = _detect_call_type(endpoint)
        tracker = self._api_tracker

        try:
            if method == "GET":
                async with self._session.get(url, headers=headers) as resp:
                    if parse_ratelimit:
                        self._parse_ratelimit_headers(dict(resp.headers))

                    if tracker and call_type:
                        await tracker.async_record_call(call_type, resp.status)

                    if resp.status == HTTPStatus.UNAUTHORIZED:
                        _LOGGER.warning("Token expired, invalidating cache")
                        self._access_token = None
                        self._token_expiry = None
                        return None

                    if resp.status == HTTPStatus.TOO_MANY_REQUESTS:
                        _LOGGER.error("Rate limit exceeded")
                        return None

                    if resp.status != HTTPStatus.OK:
                        _LOGGER.error("API call failed: %s", resp.status)
                        return None

                    return await resp.json()  # type: ignore[no-any-return]

            elif method in ("PUT", "POST"):
                json_data = data or None
                async with self._session.request(
                    method,
                    url,
                    headers=headers,
                    json=json_data,
                ) as resp:
                    if parse_ratelimit:
                        self._parse_ratelimit_headers(dict(resp.headers))

                    if tracker and call_type:
                        await tracker.async_record_call(call_type, resp.status)

                    if resp.status in (HTTPStatus.OK, HTTPStatus.CREATED, HTTPStatus.NO_CONTENT):
                        if resp.content_length and resp.content_length > 0:
                            return await resp.json()  # type: ignore[no-any-return]
                        return {}

                    _LOGGER.error("API call failed: %s", resp.status)
                    return None

            elif method == "DELETE":
                async with self._session.delete(url, headers=headers) as resp:
                    if parse_ratelimit:
                        self._parse_ratelimit_headers(dict(resp.headers))

                    if tracker and call_type:
                        await tracker.async_record_call(call_type, resp.status)
                    if resp.status in (HTTPStatus.OK, HTTPStatus.NO_CONTENT):
                        return {}

                    _LOGGER.error("API call failed: %s", resp.status)
                    return None

        except aiohttp.ClientError:
            _LOGGER.exception("Network error")
            return None
        except TadoAuthError:
            # Re-raise auth errors — must propagate to async_sync/coordinator
            raise
        except Exception:
            _LOGGER.exception("Unexpected error")
            return None

        return None  # Unsupported method

    async def get_device_offset(self, serial: str) -> float | None:
        """Get temperature offset for a specific device."""
        token = await self.get_access_token()
        if not token:
            return None

        url = f"{API_ENDPOINT_DEVICES}/{serial}/temperatureOffset"
        headers = {"Authorization": f"Bearer {token}"}

        try:
            async with self._session.get(url, headers=headers) as resp:
                if resp.status != HTTPStatus.OK:
                    _LOGGER.warning("Failed to get offset for %s: %s", serial, resp.status)
                    return None

                data = await resp.json()
                return data.get("celsius")  # type: ignore[no-any-return]

        except Exception as e:
            _LOGGER.warning("Error getting offset for %s: %s", serial, e)
            return None

    async def set_device_offset(self, serial: str, offset: float) -> bool:
        """Set temperature offset for a specific device."""
        token = await self.get_access_token()
        if not token:
            return False

        url = f"{API_ENDPOINT_DEVICES}/{serial}/temperatureOffset"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

        try:
            async with self._session.put(
                url,
                headers=headers,
                json={"celsius": offset},
            ) as resp:
                if resp.status in (HTTPStatus.OK, HTTPStatus.NO_CONTENT):
                    _LOGGER.info("Set offset %s°C for device %s", offset, serial)
                    return True

                _LOGGER.error("Failed to set offset: %s", resp.status)
                return False

        except Exception:
            _LOGGER.exception("Error setting offset")
            return False

    async def set_child_lock(self, serial: str, enabled: bool) -> bool:
        """Set child lock state for a specific device.

        Args:
            serial: Device serial number.
            enabled: True to enable, False to disable.

        Returns:
            True if successful, False otherwise.
        """
        token = await self.get_access_token()
        if not token:
            return False

        url = f"{API_ENDPOINT_DEVICES}/{serial}/childLock"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

        try:
            async with self._session.put(
                url,
                headers=headers,
                json={"childLockEnabled": enabled},
            ) as resp:
                if resp.status in (HTTPStatus.OK, HTTPStatus.NO_CONTENT):
                    state_str = "enabled" if enabled else "disabled"
                    _LOGGER.info("Child lock %s for device %s", state_str, serial)
                    return True

                _LOGGER.error("Failed to set child lock: %s", resp.status)
                return False

        except Exception:
            _LOGGER.exception("Error setting child lock for %s", serial)
            return False

    async def set_zone_overlay(self, zone_id: str, setting: dict[str, Any], termination: dict[str, Any]) -> bool:
        """Set zone overlay (manual control)."""
        config = await self._load_config()
        home_id = config.get("home_id")
        if not home_id:
            return False

        token = await self.get_access_token()
        if not token:
            return False

        url = f"{TADO_API_BASE}/homes/{home_id}/zones/{zone_id}/overlay"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

        payload = {"setting": setting, "termination": termination}
        tracker = self._api_tracker

        try:
            async with self._session.put(url, headers=headers, json=payload) as resp:
                self._parse_ratelimit_headers(dict(resp.headers))

                if tracker:
                    await tracker.async_record_call(CALL_TYPE_OVERLAY, resp.status)

                if resp.status in (HTTPStatus.OK, HTTPStatus.CREATED):
                    return True

                # Log detailed error for debugging
                error_text = await resp.text()
                _LOGGER.error("Failed to set overlay: %s - %s", resp.status, error_text)
                _LOGGER.debug("Overlay payload was: %s", payload)
                return False

        except Exception:
            _LOGGER.exception("Error setting overlay")
            return False

    async def delete_zone_overlay(self, zone_id: str) -> bool:
        """Delete zone overlay (return to schedule)."""
        config = await self._load_config()
        home_id = config.get("home_id")
        if not home_id:
            return False

        token = await self.get_access_token()
        if not token:
            return False

        url = f"{TADO_API_BASE}/homes/{home_id}/zones/{zone_id}/overlay"
        headers = {"Authorization": f"Bearer {token}"}
        tracker = self._api_tracker

        try:
            async with self._session.delete(url, headers=headers) as resp:
                self._parse_ratelimit_headers(dict(resp.headers))

                if tracker:
                    await tracker.async_record_call(CALL_TYPE_OVERLAY, resp.status)

                if resp.status in (HTTPStatus.OK, HTTPStatus.NO_CONTENT):
                    return True

                _LOGGER.error("Failed to delete overlay: %s", resp.status)
                return False

        except Exception:
            _LOGGER.exception("Error deleting overlay")
            return False

    async def get_zone_schedule(self, zone_id: str) -> dict[str, Any] | None:
        """Get zone schedule (timetable and blocks).

        Returns:
            dict with 'type' (timetable type) and 'blocks' (dict of day_type -> blocks)
        """
        config = await self._load_config()
        home_id = config.get("home_id")
        if not home_id:
            return None

        token = await self.get_access_token()
        if not token:
            return None

        headers = {"Authorization": f"Bearer {token}"}

        try:
            # Get active timetable
            url = f"{TADO_API_BASE}/homes/{home_id}/zones/{zone_id}/schedule/activeTimetable"
            async with self._session.get(url, headers=headers) as resp:
                self._parse_ratelimit_headers(dict(resp.headers))
                if resp.status != HTTPStatus.OK:
                    _LOGGER.error("Failed to get active timetable: %s", resp.status)
                    return None
                active = await resp.json()

            timetable_id = active.get("id", 0)
            timetable_type = active.get("type", "ONE_DAY")

            # Determine which day types to fetch based on timetable type
            day_types_map = {
                "ONE_DAY": ["MONDAY_TO_SUNDAY"],
                "THREE_DAY": ["MONDAY_TO_FRIDAY", "SATURDAY", "SUNDAY"],
                "SEVEN_DAY": ["MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY", "SUNDAY"],
            }
            day_types = day_types_map.get(timetable_type, ["MONDAY_TO_SUNDAY"])

            # Fetch blocks for each day type
            blocks_by_day = {}
            for day_type in day_types:
                url = (
                    f"{TADO_API_BASE}/homes/{home_id}/zones/{zone_id}"
                    f"/schedule/timetables/{timetable_id}/blocks/{day_type}"
                )
                async with self._session.get(url, headers=headers) as resp:
                    self._parse_ratelimit_headers(dict(resp.headers))
                    if resp.status == HTTPStatus.OK:
                        blocks_by_day[day_type] = await resp.json()
                    else:
                        _LOGGER.warning("Failed to get blocks for %s: %s", day_type, resp.status)
                        blocks_by_day[day_type] = []

            return {
                "type": timetable_type,
                "timetable_id": timetable_id,
                "blocks": blocks_by_day,
            }

        except Exception:
            _LOGGER.exception("Error fetching zone schedule")
            return None

    async def set_presence_lock(self, state: str) -> bool:
        """Set home presence lock (HOME/AWAY)."""
        config = await self._load_config()
        home_id = config.get("home_id")
        if not home_id:
            return False

        token = await self.get_access_token()
        if not token:
            return False

        url = f"{TADO_API_BASE}/homes/{home_id}/presenceLock"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        tracker = self._api_tracker

        try:
            async with self._session.put(
                url,
                headers=headers,
                json={"homePresence": state},
            ) as resp:
                self._parse_ratelimit_headers(dict(resp.headers))

                if tracker:
                    await tracker.async_record_call(CALL_TYPE_PRESENCE_LOCK, resp.status)

                if resp.status in (HTTPStatus.OK, HTTPStatus.NO_CONTENT):
                    _LOGGER.info("Presence lock set to %s", state)
                    return True

                _LOGGER.error("Failed to set presence lock: %s", resp.status)
                return False

        except Exception:
            _LOGGER.exception("Error setting presence lock")
            return False

    async def delete_presence_lock(self) -> bool:
        """Delete presence lock to resume geofencing (Auto mode).

        Deleting the presence lock allows geofencing to resume control.
        """
        config = await self._load_config()
        home_id = config.get("home_id")
        if not home_id:
            return False

        token = await self.get_access_token()
        if not token:
            return False

        url = f"{TADO_API_BASE}/homes/{home_id}/presenceLock"
        headers = {
            "Authorization": f"Bearer {token}",
        }
        tracker = self._api_tracker

        try:
            async with self._session.delete(url, headers=headers) as resp:
                self._parse_ratelimit_headers(dict(resp.headers))

                if tracker:
                    await tracker.async_record_call(CALL_TYPE_PRESENCE_LOCK, resp.status)

                if resp.status in (HTTPStatus.OK, HTTPStatus.NO_CONTENT):
                    _LOGGER.info("Presence lock deleted (Auto mode - geofencing resumed)")
                    return True

                # 422 means presenceLock doesn't exist (already in auto mode)
                # This is success since the end state is what we want
                if resp.status == HTTPStatus.UNPROCESSABLE_ENTITY:
                    _LOGGER.info("Presence lock already deleted (already in Auto mode)")
                    return True

                # Log response body for debugging other errors
                try:
                    body = await resp.text()
                    _LOGGER.error("Failed to delete presence lock: %s, body: %s", resp.status, body)
                except Exception:
                    _LOGGER.exception("Failed to delete presence lock: %s (could not read response body)", resp.status)
                return False

        except Exception:
            _LOGGER.exception("Error deleting presence lock")
            return False

    def get_rate_limit(self) -> dict[str, Any]:
        """Get current rate limit info."""
        return self._rate_limit.copy()

    # =========================================================================
    # Sync Functions - Replace subprocess-based tado_api.py sync
    # =========================================================================

    async def async_sync(
        self,
        quick: bool = False,
        weather_enabled: bool = True,
        mobile_devices_enabled: bool = True,
        mobile_devices_frequent_sync: bool = False,
        offset_enabled: bool = False,
        home_state_sync_enabled: bool = False,
    ) -> None:
        """Perform async data sync from Tado API.

        Raises typed exceptions so the coordinator can distinguish auth failures
        from network failures:
        - TadoAuthError → ConfigEntryAuthFailed (triggers HA reauth flow)
        - TadoSyncError → UpdateFailed (coordinator retries on next poll)

        Args:
            quick: If True, only sync zoneStates (and weather if enabled).
                   If False, also sync zones_info, mobile_devices, offsets, AC caps.
            weather_enabled: Whether to fetch weather data.
            mobile_devices_enabled: Whether to fetch mobile devices.
            mobile_devices_frequent_sync: If True, fetch mobile devices on quick sync too.
            offset_enabled: Whether to fetch temperature offsets.
            home_state_sync_enabled: Whether to fetch home state (for away mode).

        Raises:
            TadoAuthError: If authentication fails (expired refresh token).
            TadoSyncError: If sync fails due to network/server errors.
        """
        sync_type = "quick" if quick else "full"
        _LOGGER.info("Tado CE async sync starting (%s)", sync_type)

        # Ensure home_id is loaded for per-home file paths
        await self._ensure_home_id()

        try:
            # Always fetch zone states (most important)
            zones_data = await self.api_call("zoneStates")
            if zones_data is None:
                _LOGGER.error("Failed to fetch zone states")
                await self.save_ratelimit("error")
                raise TadoSyncError("Failed to fetch zone states")

            await self._save_json_file(self._get_data_file("zones"), zones_data)
            zone_count = len((zones_data.get("zoneStates") or {}).keys())
            _LOGGER.debug("Zone states saved (%s zones)", zone_count)

            # Fetch weather if enabled
            if weather_enabled:
                weather_data = await self.api_call("weather")
                if weather_data:
                    await self._save_json_file(self._get_data_file("weather"), weather_data)
                    _LOGGER.debug("Weather data saved")

            # Fetch home state if enabled (needed for away mode)
            if home_state_sync_enabled:
                home_state = await self.api_call("state")
                if home_state:
                    await self._save_json_file(self._get_data_file("home_state"), home_state)
                    _LOGGER.debug("Home state saved (presence: %s)", home_state.get("presence"))

            # Fetch mobile devices on quick sync if frequent sync enabled
            if quick and mobile_devices_enabled and mobile_devices_frequent_sync:
                mobile_data = await self.api_call("mobileDevices")
                if mobile_data:
                    await self._save_json_file(self._get_data_file("mobile_devices"), mobile_data)
                    _LOGGER.debug("Mobile devices saved (frequent sync, %s devices)", len(mobile_data))

            # Full sync: also fetch zone info, mobile devices, offsets, AC caps
            if not quick:
                # Fetch zone info
                zones_info = await self.api_call("zones")
                if zones_info:
                    await self._save_json_file(self._get_data_file("zones_info"), zones_info)
                    _LOGGER.debug("Zone info saved (%s zones)", len(zones_info))

                    # Fetch mobile devices if enabled
                    if mobile_devices_enabled:
                        mobile_data = await self.api_call("mobileDevices")
                        if mobile_data:
                            await self._save_json_file(self._get_data_file("mobile_devices"), mobile_data)
                            _LOGGER.debug("Mobile devices saved (%s devices)", len(mobile_data))

                    # Fetch temperature offsets if enabled
                    if offset_enabled:
                        await self._sync_offsets(zones_info)  # type: ignore[arg-type]

                    # Fetch AC zone capabilities
                    await self._sync_ac_capabilities(zones_info)  # type: ignore[arg-type]

            # Save rate limit info
            await self.save_ratelimit("ok")

            rl = self._rate_limit
            used = rl.get("limit", 0) - rl.get("remaining", 0) if rl.get("limit") else 0
            _LOGGER.info("Tado CE async sync SUCCESS (%s): %s/%s API calls used", sync_type, used, rl.get("limit", "?"))

        except TadoAuthError:
            # Re-raise auth errors — coordinator needs to trigger reauth flow
            raise
        except TadoSyncError:
            # Re-raise sync errors — coordinator handles retry
            raise
        except aiohttp.ClientError as e:
            _LOGGER.exception("Tado CE async sync network error")
            await self.save_ratelimit("error")
            raise TadoSyncError(f"Network error during sync: {e}") from e
        except Exception as e:
            _LOGGER.exception("Tado CE async sync failed")
            await self.save_ratelimit("error")
            raise TadoSyncError(f"Sync failed: {e}") from e

    async def _save_json_file(self, file_path: Path, data: dict[str, Any] | list[Any]) -> None:
        """Save data to JSON file atomically using executor I/O.

        After a successful write, updates the DataLoader in-memory cache
        so that subsequent reads avoid disk I/O.

        Args:
            file_path: Path to save to.
            data: Data to serialize as JSON.
        """
        await self._hass.async_add_executor_job(  # type: ignore[union-attr]
            lambda: file_path.parent.mkdir(parents=True, exist_ok=True),
        )

        temp_path = file_path.with_suffix(".tmp")
        content = json.dumps(data, indent=2)
        await self._hass.async_add_executor_job(  # type: ignore[union-attr]
            temp_path.write_text,
            content,
        )

        # Atomic move
        await self._hass.async_add_executor_job(  # type: ignore[union-attr]
            temp_path.replace,
            file_path,
        )

        # Write-through: update DataLoader cache
        if self._data_loader is not None:
            base_name = self._extract_base_name(file_path)
            self._data_loader.update_cache(base_name, data)

    async def _load_json_file(self, file_path: Path) -> dict[str, Any] | list[Any]:
        """Load JSON file using executor I/O."""
        content = await self._hass.async_add_executor_job(  # type: ignore[union-attr]
            file_path.read_text,
        )
        return json.loads(content)  # type: ignore[no-any-return]

    async def _sync_offsets(self, zones_info: list[Any]) -> None:
        """Sync temperature offsets for all devices.

        Args:
            zones_info: List of zone info dicts from API.
        """
        offsets = {}

        for zone in zones_info:
            zone_id = str(zone.get("id"))
            zone_type = zone.get("type")

            # Only fetch offsets for heating/AC zones (not hot water)
            if zone_type not in ("HEATING", "AIR_CONDITIONING"):
                continue

            devices = zone.get("devices") or []
            for device in devices:
                serial = device.get("shortSerialNo")
                if serial:
                    try:
                        offset = await self.get_device_offset(serial)
                        if offset is not None:
                            offsets[zone_id] = offset
                            _LOGGER.debug("Offset for zone %s: %s°C", zone_id, offset)
                        break  # Only need first device per zone
                    except Exception as e:
                        _LOGGER.warning("Failed to fetch offset for device %s: %s", serial, e)

        if offsets:
            await self._save_json_file(self._get_data_file("offsets"), offsets)
            _LOGGER.debug("Offsets saved (%s zones)", len(offsets))

    async def _sync_ac_capabilities(self, zones_info: list[Any]) -> None:
        """Sync AC zone capabilities.

        Skip fetch if cache exists - AC capabilities don't change.
        This saves API calls on every restart.

        Args:
            zones_info: List of zone info dicts from API.
        """
        # Check if cache already exists - AC capabilities don't change
        ac_caps_path = self._get_data_file("ac_capabilities")
        try:
            path_exists = await self._hass.async_add_executor_job(  # type: ignore[union-attr]
                ac_caps_path.exists,
            )
            if path_exists:
                existing = await self._load_json_file(ac_caps_path)
                if existing:
                    _LOGGER.debug("AC capabilities loaded from cache (%s zones)", len(existing))
                    return
        except Exception as e:
            _LOGGER.debug("AC capabilities cache corrupted, fetching fresh: %s", e)

        ac_capabilities = {}

        for zone in zones_info:
            zone_id = str(zone.get("id"))
            zone_type = zone.get("type")

            # Only fetch capabilities for AC zones
            if zone_type != "AIR_CONDITIONING":
                continue

            try:
                caps = await self.api_call(f"zones/{zone_id}/capabilities")
                if caps:
                    ac_capabilities[zone_id] = caps
                    modes = [m for m in ["COOL", "HEAT", "DRY", "FAN", "AUTO"] if m in caps]
                    _LOGGER.debug("AC capabilities for zone %s: modes=%s", zone_id, modes)
            except Exception as e:
                _LOGGER.warning("Failed to fetch AC capabilities for zone %s: %s", zone_id, e)

        if ac_capabilities:
            await self._save_json_file(self._get_data_file("ac_capabilities"), ac_capabilities)
            _LOGGER.debug("AC capabilities saved (%s zones)", len(ac_capabilities))

    async def add_meter_reading(self, reading: int, date: str | None = None) -> bool:
        """Add energy meter reading.

        Args:
            reading: Meter reading value
            date: Date string in YYYY-MM-DD format (defaults to today)

        Returns:
            True if successful, False otherwise
        """
        config = await self._load_config()
        home_id = config.get("home_id")
        if not home_id:
            _LOGGER.error("No home_id configured")
            return False

        token = await self.get_access_token()
        if not token:
            return False

        if not date:
            # Use Home Assistant's timezone for local date
            try:
                from homeassistant.util import dt as dt_util

                date = dt_util.now().strftime("%Y-%m-%d")
            except ImportError:
                date = datetime.now(UTC).strftime("%Y-%m-%d")

        url = f"{TADO_API_BASE}/homes/{home_id}/meterReadings"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        payload = {"date": date, "reading": reading}

        try:
            async with self._session.post(url, headers=headers, json=payload) as resp:
                self._parse_ratelimit_headers(dict(resp.headers))

                if resp.status in (HTTPStatus.OK, HTTPStatus.CREATED):
                    _LOGGER.info("Added meter reading: %s on %s", reading, date)
                    return True

                _LOGGER.error("Failed to add meter reading: %s", resp.status)
                return False

        except aiohttp.ClientError:
            _LOGGER.exception("Network error adding meter reading")
            return False
        except Exception:
            _LOGGER.exception("Error adding meter reading")
            return False

    async def identify_device(self, device_serial: str) -> bool:
        """Make a device flash its LED to identify it.

        Args:
            device_serial: Device serial number

        Returns:
            True if successful, False otherwise
        """
        token = await self.get_access_token()
        if not token:
            _LOGGER.error("Failed to get access token")
            return False

        url = f"{API_ENDPOINT_DEVICES}/{device_serial}/identify"
        headers = {"Authorization": f"Bearer {token}"}

        try:
            async with self._session.post(url, headers=headers) as resp:
                if resp.status in (HTTPStatus.OK, HTTPStatus.NO_CONTENT):
                    _LOGGER.info("Identify command sent to device %s", device_serial)
                    return True

                _LOGGER.error("Failed to identify device: %s", resp.status)
                return False

        except aiohttp.ClientError:
            _LOGGER.exception("Network error identifying device")
            return False
        except Exception:
            _LOGGER.exception("Error identifying device")
            return False

    async def set_away_configuration(
        self,
        zone_id: str,
        mode: str,
        temperature: float | None = None,
        comfort_level: int = 50,
    ) -> bool:
        """Set away configuration for a zone.

        Args:
            zone_id: Zone ID
            mode: Away mode ('auto', 'manual', or 'off')
            temperature: Target temperature for manual mode
            comfort_level: Comfort level for auto mode (0-100)

        Returns:
            True if successful, False otherwise
        """
        config = await self._load_config()
        home_id = config.get("home_id")
        if not home_id:
            _LOGGER.error("No home_id configured")
            return False

        token = await self.get_access_token()
        if not token:
            return False

        url = f"{TADO_API_BASE}/homes/{home_id}/zones/{zone_id}/schedule/awayConfiguration"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

        # Build payload based on mode
        if mode == "auto":
            payload = {
                "type": "HEATING",
                "autoAdjust": True,
                "comfortLevel": comfort_level,
                "setting": {"type": "HEATING", "power": "OFF"},
            }
        elif mode == "manual" and temperature is not None:
            payload = {
                "type": "HEATING",
                "autoAdjust": False,
                "setting": {
                    "type": "HEATING",
                    "power": "ON",
                    "temperature": {"celsius": temperature},
                },
            }
        else:  # off
            payload = {
                "type": "HEATING",
                "autoAdjust": False,
                "setting": {"type": "HEATING", "power": "OFF"},
            }

        try:
            async with self._session.put(url, headers=headers, json=payload) as resp:
                self._parse_ratelimit_headers(dict(resp.headers))

                if resp.status in (HTTPStatus.OK, HTTPStatus.NO_CONTENT):
                    _LOGGER.info("Set away configuration for zone %s: %s", zone_id, mode)
                    return True

                _LOGGER.error("Failed to set away configuration: %s", resp.status)
                return False

        except aiohttp.ClientError:
            _LOGGER.exception("Network error setting away configuration")
            return False
        except Exception:
            _LOGGER.exception("Error setting away configuration")
            return False
