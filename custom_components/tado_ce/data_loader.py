"""Centralized Data Loader for Tado CE Integration.

Thread-safe file loading helpers for all Tado CE components.
All file I/O is blocking and should be called via hass.async_add_executor_job().

Each config entry (home) gets its own DataLoader instance with home_id-scoped
file paths, eliminating shared global state.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

from .const import DATA_DIR, get_data_file

_LOGGER = logging.getLogger(__name__)

# Max outdoor temp readings (7 days at 30s poll interval)
MAX_OUTDOOR_TEMP_READINGS = 336


class DataLoader:
    """Per-entry data loader with home_id-scoped file paths.

    Each config entry (home) gets its own DataLoader instance.
    All file paths are scoped to the home_id, ensuring two homes cannot
    read/write each other's data files.

    Usage:
        loader = DataLoader(home_id="12345")
        zones = loader.load_zones_file()
        loader.save_overlay_mode("TIMER")
    """

    def __init__(self, home_id: str) -> None:
        """Initialize DataLoader for a specific home.

        Args:
            home_id: Tado home ID for file path scoping.
        """
        self._home_id = home_id

    @property
    def home_id(self) -> str:
        """Return the home_id this loader is scoped to."""
        return self._home_id

    def _get_file_path(self, base_name: str) -> Path:
        """Get file path scoped to this home_id.

        Always returns per-home path when home_id is set.
        No legacy fallback — the class-based loader always uses
        home_id-scoped paths to guarantee isolation.
        Legacy fallback is only in the module-level backward compat wrappers.
        """
        return get_data_file(base_name, self._home_id)

    def _load_json(self, base_name: str) -> Optional[dict | list]:
        """Generic JSON file loader with error handling.

        Args:
            base_name: Base filename without extension.

        Returns:
            Parsed JSON data, or None on error.
        """
        try:
            file_path = self._get_file_path(base_name)
            with open(file_path) as f:
                return json.load(f)
        except FileNotFoundError:
            _LOGGER.debug("%s.json not found", base_name)
            return None
        except json.JSONDecodeError as e:
            _LOGGER.warning("Invalid JSON in %s.json: %s", base_name, e)
            return None
        except Exception as e:
            _LOGGER.error("Failed to load %s.json: %s", base_name, e)
            return None

    # === Load methods ===

    def load_zones_file(self) -> Optional[dict]:
        """Load zones.json (zone states)."""
        return self._load_json("zones")

    def load_zones_info_file(self) -> Optional[list]:
        """Load zones_info.json (zone metadata)."""
        return self._load_json("zones_info")

    def load_weather_file(self) -> Optional[dict]:
        """Load weather.json."""
        return self._load_json("weather")

    def load_mobile_devices_file(self) -> Optional[list]:
        """Load mobile_devices.json."""
        return self._load_json("mobile_devices")

    def load_config_file(self) -> Optional[dict]:
        """Load config.json."""
        return self._load_json("config")

    def load_home_state_file(self) -> Optional[dict]:
        """Load home_state.json."""
        return self._load_json("home_state")

    def load_ratelimit_file(self) -> Optional[dict]:
        """Load ratelimit.json."""
        return self._load_json("ratelimit")

    def load_offsets_file(self) -> Optional[dict]:
        """Load offsets.json (zone_id -> offset_celsius)."""
        return self._load_json("offsets")

    def load_ac_capabilities_file(self) -> Optional[dict]:
        """Load ac_capabilities.json (zone_id -> capabilities)."""
        return self._load_json("ac_capabilities")

    def load_api_call_history_file(self) -> Optional[dict]:
        """Load api_call_history.json."""
        return self._load_json("api_call_history")

    def load_schedules_file(self) -> Optional[dict]:
        """Load schedules.json (zone heating schedules)."""
        return self._load_json("schedules")

    # === Convenience methods ===

    def get_zone_names(self) -> dict:
        """Get zone ID to name mapping."""
        from .const import DEFAULT_ZONE_NAMES
        zones_info = self.load_zones_info_file()
        if zones_info:
            return {str(z.get('id')): z.get('name', f"Zone {z.get('id')}") for z in zones_info}
        return DEFAULT_ZONE_NAMES

    def get_zone_types(self) -> dict:
        """Get zone ID to type mapping."""
        zones_info = self.load_zones_info_file()
        if zones_info:
            return {str(z.get('id')): z.get('type', 'HEATING') for z in zones_info}
        return {}

    def get_zone_data(self, zone_id: str) -> Optional[dict]:
        """Get state data for a specific zone."""
        zones_data = self.load_zones_file()
        if zones_data:
            zone_states = zones_data.get('zoneStates') or {}
            return zone_states.get(zone_id)
        return None

    def get_zone_schedule(self, zone_id: str) -> Optional[dict]:
        """Get schedule data for a specific zone."""
        schedules = self.load_schedules_file()
        if schedules:
            return schedules.get(zone_id)
        return None

    # === Overlay mode (shared, not per-home) ===

    def load_overlay_mode(self) -> str:
        """Load overlay mode from storage.

        Returns:
            "TADO_MODE", "NEXT_TIME_BLOCK", "TIMER", or "MANUAL".
            Defaults to "TADO_MODE" if file doesn't exist.
        """
        file_path = DATA_DIR / "overlay_mode.json"
        if not file_path.exists():
            return "TADO_MODE"
        try:
            with open(file_path, 'r') as f:
                data = json.load(f)
                mode = data.get("overlay_mode", "TADO_MODE")
                if mode not in ("TADO_MODE", "NEXT_TIME_BLOCK", "TIMER", "MANUAL"):
                    _LOGGER.warning("Invalid overlay mode '%s', defaulting to TADO_MODE", mode)
                    return "TADO_MODE"
                return mode
        except json.JSONDecodeError as e:
            _LOGGER.warning("Invalid JSON in overlay_mode.json: %s", e)
            return "TADO_MODE"
        except Exception as e:
            _LOGGER.warning("Failed to load overlay mode: %s", e)
            return "TADO_MODE"

    def save_overlay_mode(self, mode: str) -> bool:
        """Save overlay mode to storage.

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
            with open(file_path, 'w') as f:
                json.dump({"overlay_mode": mode}, f)
            _LOGGER.debug("Saved overlay mode: %s", mode)
            return True
        except Exception as e:
            _LOGGER.error("Failed to save overlay mode: %s", e)
            return False

    # === Timer duration ===

    def save_timer_duration(self, duration: int) -> bool:
        """Save timer duration to storage.

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
            with open(file_path, 'w') as f:
                json.dump({"timer_duration": duration}, f)
            _LOGGER.debug("Saved timer duration: %s minutes", duration)
            return True
        except Exception as e:
            _LOGGER.error("Failed to save timer duration: %s", e)
            return False

    def load_timer_duration(self) -> int:
        """Load timer duration from storage.

        Returns:
            Duration in minutes (default 60 if not set or error).
        """
        file_path = DATA_DIR / "timer_duration.json"
        try:
            if file_path.exists():
                with open(file_path, 'r') as f:
                    data = json.load(f)
                    return data.get("timer_duration", 60)
        except Exception as e:
            _LOGGER.debug("Failed to load timer duration: %s", e)
        return 60

    # === Outdoor temperature history ===

    def load_outdoor_temp_history(self) -> list:
        """Load outdoor temperature history from storage.

        Returns:
            List of float temperature readings (most recent last), max 336 entries.
        """
        try:
            file_path = self._get_file_path("outdoor_temp_history")
            with open(file_path) as f:
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

    def save_outdoor_temp_history(self, readings: list) -> bool:
        """Save outdoor temperature history to storage.

        Args:
            readings: List of float temperature readings (most recent last).

        Returns:
            True if saved successfully, False otherwise.
        """
        try:
            file_path = self._get_file_path("outdoor_temp_history")
            file_path.parent.mkdir(parents=True, exist_ok=True)
            trimmed = readings[-MAX_OUTDOOR_TEMP_READINGS:]
            with open(file_path, 'w') as f:
                json.dump({"readings": trimmed}, f)
            return True
        except Exception as e:
            _LOGGER.debug("Failed to save outdoor_temp_history.json: %s", e)
            return False


