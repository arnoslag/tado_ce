"""Tado CE Data Loader — thread-safe, per-home file I/O for schedules and config.

Thread-safe, per-home file loading for all Tado CE components.
All file I/O is blocking and should be called via hass.async_add_executor_job().
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

from .const import DATA_DIR, OVERLAY_MODE_DEFAULT, TIMER_DURATION_DEFAULT, get_data_file

if TYPE_CHECKING:
    from pathlib import Path

_LOGGER = logging.getLogger(__name__)

# Max outdoor temp readings (7 days at 30s poll interval)
MAX_OUTDOOR_TEMP_READINGS = 336


class DataLoader:
    """Per-entry data loader with home_id-scoped file paths.

    Each config entry (home) gets its own DataLoader instance.
    All file paths are scoped to the home_id, ensuring two homes cannot
    read/write each other's data files.

    IMPORTANT: All public methods in this class perform blocking file I/O.
    They MUST be called via ``hass.async_add_executor_job()`` from async
    context to avoid blocking the event loop.

    Usage::

        loader = DataLoader(home_id="12345")
        zones = await hass.async_add_executor_job(loader.load_zones_file)
        await hass.async_add_executor_job(loader.save_overlay_mode, "TIMER")
    """

    def __init__(self, home_id: str) -> None:
        """Initialize DataLoader for a specific home.

        Args:
            home_id: Tado home ID for file path scoping.
        """
        self._home_id = home_id
        self._cache: dict[str, Any] = {}

    @property
    def home_id(self) -> str:
        """Return the home_id this loader is scoped to."""
        return self._home_id

    # --- Cache API ---

    def update_cache(self, base_name: str, data: dict[str, Any] | list[Any]) -> None:
        """Update in-memory cache entry after file write.

        Called by api_client after writing a JSON file to disk (write-through).

        Args:
            base_name: Base filename without extension (e.g. "zones").
            data: Parsed JSON data to cache.
        """
        self._cache[base_name] = data

    def get_cached(self, base_name: str) -> dict[str, Any] | list[Any] | None:
        """Get data from in-memory cache.

        Returns:
            Cached data, or None if not cached.
        """
        return self._cache.get(base_name)

    def clear_cache(self) -> None:
        """Clear all cached data."""
        self._cache.clear()

    def load_all_to_cache(self) -> None:
        """Bulk-load all data files into cache (blocking I/O).

        Called once during cold start via ``hass.async_add_executor_job()``.
        Reads all 11 data files in a single executor job instead of 11 separate ones.
        """
        file_names = [
            "zones",
            "config",
            "home_state",
            "ratelimit",
            "api_call_history",
            "zones_info",
            "weather",
            "mobile_devices",
            "offsets",
            "schedules",
            "ac_capabilities",
        ]
        for name in file_names:
            data = self._load_json(name)
            if data is not None:
                self._cache[name] = data

    def _get_file_path(self, base_name: str) -> Path:
        """Get file path scoped to this home_id."""
        return get_data_file(base_name, self._home_id)

    def _load_json(self, base_name: str) -> dict[str, Any] | list[Any] | None:
        """Load JSON data — cache-aside pattern.

        Returns cached data if available, otherwise reads from disk and
        populates the cache on success.

        Performs blocking file I/O on cache miss — call via
        ``hass.async_add_executor_job()`` when cache is cold.

        Args:
            base_name: Base filename without extension.

        Returns:
            Parsed JSON data, or None on error.
        """
        # Cache hit
        cached: dict[str, Any] | list[Any] | None = self._cache.get(base_name)
        if cached is not None:
            return cached

        # Cache miss — read from disk
        try:
            file_path = self._get_file_path(base_name)
            with file_path.open() as f:
                data = json.load(f)
                self._cache[base_name] = data  # Populate cache on read
                return data  # type: ignore[no-any-return]
        except FileNotFoundError:
            _LOGGER.debug("%s.json not found", base_name)
            return None
        except json.JSONDecodeError as e:
            _LOGGER.warning("Invalid JSON in %s.json: %s", base_name, e)
            return None
        except Exception:
            _LOGGER.exception("Failed to load %s.json", base_name)
            return None

    # === Load methods ===

    def load_zones_file(self) -> dict[str, Any] | None:
        """Load zones.json (zone states)."""
        return self._load_json("zones")  # type: ignore[return-value]

    def load_zones_info_file(self) -> list[Any] | None:
        """Load zones_info.json (zone metadata)."""
        return self._load_json("zones_info")  # type: ignore[return-value]

    def load_weather_file(self) -> dict[str, Any] | None:
        """Load weather.json."""
        return self._load_json("weather")  # type: ignore[return-value]

    def load_mobile_devices_file(self) -> list[Any] | None:
        """Load mobile_devices.json."""
        return self._load_json("mobile_devices")  # type: ignore[return-value]

    def load_config_file(self) -> dict[str, Any] | None:
        """Load config.json."""
        return self._load_json("config")  # type: ignore[return-value]

    def load_home_state_file(self) -> dict[str, Any] | None:
        """Load home_state.json."""
        return self._load_json("home_state")  # type: ignore[return-value]

    def load_ratelimit_file(self) -> dict[str, Any] | None:
        """Load ratelimit.json."""
        return self._load_json("ratelimit")  # type: ignore[return-value]

    def load_offsets_file(self) -> dict[str, Any] | None:
        """Load offsets.json (zone_id -> offset_celsius)."""
        return self._load_json("offsets")  # type: ignore[return-value]

    def load_ac_capabilities_file(self) -> dict[str, Any] | None:
        """Load ac_capabilities.json (zone_id -> capabilities)."""
        return self._load_json("ac_capabilities")  # type: ignore[return-value]

    def load_api_call_history_file(self) -> dict[str, Any] | None:
        """Load api_call_history.json."""
        return self._load_json("api_call_history")  # type: ignore[return-value]

    def load_schedules_file(self) -> dict[str, Any] | None:
        """Load schedules.json (zone heating schedules)."""
        return self._load_json("schedules")  # type: ignore[return-value]

    # === Convenience methods ===

    def get_zone_data(self, zone_id: str) -> dict[str, Any] | None:
        """Get state data for a specific zone."""
        zones_data = self.load_zones_file()
        if zones_data:
            zone_states = zones_data.get("zoneStates") or {}
            return zone_states.get(zone_id)
        return None

    def get_zone_schedule(self, zone_id: str) -> dict[str, Any] | None:
        """Get schedule data for a specific zone."""
        schedules = self.load_schedules_file()
        if schedules:
            return schedules.get(zone_id)
        return None

    # === Overlay mode (shared, not per-home) ===

    def load_overlay_mode(self) -> str:
        """Load overlay mode from storage.

        Performs blocking file I/O — call via ``hass.async_add_executor_job()``.

        Returns:
            "TADO_MODE", "NEXT_TIME_BLOCK", "TIMER", or "MANUAL".
            Defaults to "TADO_MODE" if file doesn't exist.
        """
        file_path = DATA_DIR / "overlay_mode.json"
        if not file_path.exists():
            return OVERLAY_MODE_DEFAULT
        try:
            with file_path.open() as f:
                data = json.load(f)
                mode = data.get("overlay_mode", OVERLAY_MODE_DEFAULT)
                if mode not in ("TADO_MODE", "NEXT_TIME_BLOCK", "TIMER", "MANUAL"):
                    _LOGGER.warning("Invalid overlay mode '%s', defaulting to TADO_MODE", mode)
                    return OVERLAY_MODE_DEFAULT
                return mode  # type: ignore[no-any-return]
        except json.JSONDecodeError as e:
            _LOGGER.warning("Invalid JSON in overlay_mode.json: %s", e)
            return OVERLAY_MODE_DEFAULT
        except Exception as e:
            _LOGGER.warning("Failed to load overlay mode: %s", e)
            return OVERLAY_MODE_DEFAULT

    def save_overlay_mode(self, mode: str) -> bool:
        """Save overlay mode to storage.

        Performs blocking file I/O — call via ``hass.async_add_executor_job()``.

        Args:
            mode: "TADO_MODE", "NEXT_TIME_BLOCK", "TIMER", or "MANUAL"

        Returns:
            True if saved successfully, False otherwise.
        """
        if mode not in ("TADO_MODE", "NEXT_TIME_BLOCK", "TIMER", "MANUAL"):
            _LOGGER.error("Invalid overlay mode: %s", mode)
            return False
        file_path = DATA_DIR / "overlay_mode.json"
        try:
            file_path.parent.mkdir(parents=True, exist_ok=True)
            data = {"overlay_mode": mode}
            with file_path.open("w") as f:
                json.dump(data, f)
            self._cache["overlay_mode"] = data
            _LOGGER.debug("Saved overlay mode: %s", mode)
            return True
        except Exception:
            _LOGGER.exception("Failed to save overlay mode")
            return False

    # === Timer duration ===

    def save_timer_duration(self, duration: int) -> bool:
        """Save timer duration to storage.

        Performs blocking file I/O — call via ``hass.async_add_executor_job()``.

        Args:
            duration: Duration in minutes (15-180)

        Returns:
            True if saved successfully, False otherwise.
        """
        if not isinstance(duration, int) or duration < 15 or duration > 180:
            _LOGGER.error("Invalid timer duration: %s", duration)
            return False
        file_path = DATA_DIR / "timer_duration.json"
        try:
            file_path.parent.mkdir(parents=True, exist_ok=True)
            data = {"timer_duration": duration}
            with file_path.open("w") as f:
                json.dump(data, f)
            self._cache["timer_duration"] = data
            _LOGGER.debug("Saved timer duration: %s minutes", duration)
            return True
        except Exception:
            _LOGGER.exception("Failed to save timer duration")
            return False

    def load_timer_duration(self) -> int:
        """Load timer duration from storage.

        Performs blocking file I/O — call via ``hass.async_add_executor_job()``.

        Returns:
            Duration in minutes (default TIMER_DURATION_DEFAULT if not set or error).
        """
        file_path = DATA_DIR / "timer_duration.json"
        try:
            if file_path.exists():
                with file_path.open() as f:
                    data = json.load(f)
                    return data.get("timer_duration", TIMER_DURATION_DEFAULT)  # type: ignore[no-any-return]
        except Exception as e:
            _LOGGER.debug("Failed to load timer duration: %s", e)
        return TIMER_DURATION_DEFAULT

    # === Outdoor temperature history ===

    def load_outdoor_temp_history(self) -> list[Any]:
        """Load outdoor temperature history from storage.

        Performs blocking file I/O — call via ``hass.async_add_executor_job()``.

        Returns:
            List of float temperature readings (most recent last), max 336 entries.
        """
        try:
            file_path = self._get_file_path("outdoor_temp_history")
            with file_path.open() as f:
                data = json.load(f)
                readings = data.get("readings", [])
                readings = [float(r) for r in readings if isinstance(r, (int, float))]
                return readings[-MAX_OUTDOOR_TEMP_READINGS:]
        except FileNotFoundError:
            _LOGGER.debug("outdoor_temp_history.json not found - starting fresh")
            return []
        except json.JSONDecodeError as e:
            _LOGGER.warning("Invalid JSON in outdoor_temp_history.json: %s", e)
            return []
        except Exception as e:
            _LOGGER.debug("Failed to load outdoor_temp_history.json: %s", e)
            return []

    def save_outdoor_temp_history(self, readings: list[Any]) -> bool:
        """Save outdoor temperature history to storage.

        Performs blocking file I/O — call via ``hass.async_add_executor_job()``.

        Args:
            readings: List of float temperature readings (most recent last).

        Returns:
            True if saved successfully, False otherwise.
        """
        try:
            import shutil
            import tempfile

            file_path = self._get_file_path("outdoor_temp_history")
            file_path.parent.mkdir(parents=True, exist_ok=True)
            trimmed = readings[-MAX_OUTDOOR_TEMP_READINGS:]
            data = {"readings": trimmed}
            with tempfile.NamedTemporaryFile(
                mode="w",
                dir=file_path.parent,
                delete=False,
                suffix=".tmp",
            ) as tmp:
                json.dump(data, tmp)
                temp_path = tmp.name
            shutil.move(temp_path, file_path)
            self._cache["outdoor_temp_history"] = data
            return True
        except Exception:
            _LOGGER.debug("Failed to save outdoor_temp_history.json")
            return False
