"""Centralized Data Loader for Tado CE Integration.

This module provides thread-safe file loading helpers for all Tado CE components.
All file I/O is blocking and should be called via hass.async_add_executor_job().

v1.8.0: Added multi-home support with per-home data files.
v3.0.0 Phase 1: Class-based DataLoader replacing global _current_home_id.
  Each config entry (home) gets its own DataLoader instance with home_id-scoped
  file paths, eliminating shared global state (GAP-77).
  Module-level functions kept as thin wrappers for backward compatibility.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

from .const import DATA_DIR, get_data_file, get_legacy_file

_LOGGER = logging.getLogger(__name__)

# Global home_id cache (set during setup) — DEPRECATED in v3.0.0
# Kept for backward compat wrappers only. New code uses DataLoader instances.
_current_home_id: Optional[str] = None

# Module-level DataLoader instance for backward compat wrappers
_default_loader: Optional[DataLoader] = None

# Max outdoor temp readings (7 days at 30s poll interval)
MAX_OUTDOOR_TEMP_READINGS = 336


class DataLoader:
    """Per-entry data loader with home_id-scoped file paths.

    v3.0.0 Phase 1: Each config entry (home) gets its own DataLoader instance.
    All file paths are scoped to the home_id, ensuring two homes cannot
    read/write each other's data files (GAP-77, CP-4).

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

        v3.0.0: Always returns per-home path when home_id is set.
        No legacy fallback — the class-based loader always uses
        home_id-scoped paths to guarantee isolation (CP-4, GAP-77).
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
            _LOGGER.debug(f"{base_name}.json not found")
            return None
        except json.JSONDecodeError as e:
            _LOGGER.warning(f"Invalid JSON in {base_name}.json: {e}")
            return None
        except Exception as e:
            _LOGGER.error(f"Failed to load {base_name}.json: {e}")
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
                    _LOGGER.warning(f"Invalid overlay mode '{mode}', defaulting to TADO_MODE")
                    return "TADO_MODE"
                return mode
        except json.JSONDecodeError as e:
            _LOGGER.warning(f"Invalid JSON in overlay_mode.json: {e}")
            return "TADO_MODE"
        except Exception as e:
            _LOGGER.warning(f"Failed to load overlay mode: {e}")
            return "TADO_MODE"

    def save_overlay_mode(self, mode: str) -> bool:
        """Save overlay mode to storage.

        Args:
            mode: "TADO_MODE", "NEXT_TIME_BLOCK", "TIMER", or "MANUAL"

        Returns:
            True if saved successfully, False otherwise.
        """
        if mode not in ("TADO_MODE", "NEXT_TIME_BLOCK", "TIMER", "MANUAL"):
            _LOGGER.error(f"Invalid overlay mode: {mode}")
            return False
        file_path = DATA_DIR / "overlay_mode.json"
        try:
            file_path.parent.mkdir(parents=True, exist_ok=True)
            with open(file_path, 'w') as f:
                json.dump({"overlay_mode": mode}, f)
            _LOGGER.debug(f"Saved overlay mode: {mode}")
            return True
        except Exception as e:
            _LOGGER.error(f"Failed to save overlay mode: {e}")
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
            _LOGGER.error(f"Invalid timer duration: {duration}")
            return False
        file_path = DATA_DIR / "timer_duration.json"
        try:
            file_path.parent.mkdir(parents=True, exist_ok=True)
            with open(file_path, 'w') as f:
                json.dump({"timer_duration": duration}, f)
            _LOGGER.debug(f"Saved timer duration: {duration} minutes")
            return True
        except Exception as e:
            _LOGGER.error(f"Failed to save timer duration: {e}")
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
            _LOGGER.debug(f"Failed to load timer duration: {e}")
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
            _LOGGER.warning(f"Invalid JSON in outdoor_temp_history.json: {e}")
            return []
        except Exception as e:
            _LOGGER.debug(f"Failed to load outdoor_temp_history.json: {e}")
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
            _LOGGER.debug(f"Failed to save outdoor_temp_history.json: {e}")
            return False


# ============================================================
# Backward compatibility: Module-level functions (DEPRECATED)
# These delegate to _default_loader or use _current_home_id.
# New code should use DataLoader instances via EntryData.
# ============================================================


def set_current_home_id(home_id: str) -> None:
    """Set the current home_id and create default DataLoader.

    DEPRECATED: New code should create DataLoader instances directly.
    Called during integration setup for backward compat.
    """
    global _current_home_id, _default_loader
    _current_home_id = home_id
    _default_loader = DataLoader(home_id)
    _LOGGER.debug(f"Data loader home_id set to: {home_id}")


def get_current_home_id() -> Optional[str]:
    """Get the current home_id.

    DEPRECATED: New code should use DataLoader.home_id.
    """
    return _current_home_id


def cleanup_data_loader(hass=None) -> bool:
    """Clean up data loader state.

    DEPRECATED: New code should discard DataLoader instances in async_unload_entry.

    Args:
        hass: Home Assistant instance (unused, accepted for consistent singleton API)

    Returns:
        True if state was cleaned up
    """
    global _current_home_id, _default_loader
    _current_home_id = None
    _default_loader = None
    _LOGGER.debug("Cleaned up data loader home_id")
    return True


def _get_default_loader() -> DataLoader:
    """Get or create the default DataLoader for backward compat wrappers."""
    global _default_loader
    if _default_loader is None:
        _default_loader = DataLoader(_current_home_id or "")
    return _default_loader


def _get_file_path(base_name: str) -> Path:
    """DEPRECATED: Use DataLoader._get_file_path() instead."""
    return _get_default_loader()._get_file_path(base_name)


def load_zones_file() -> Optional[dict]:
    """DEPRECATED: Use DataLoader.load_zones_file() instead."""
    return _get_default_loader().load_zones_file()


def load_zones_info_file() -> Optional[list]:
    """DEPRECATED: Use DataLoader.load_zones_info_file() instead."""
    return _get_default_loader().load_zones_info_file()


def load_weather_file() -> Optional[dict]:
    """DEPRECATED: Use DataLoader.load_weather_file() instead."""
    return _get_default_loader().load_weather_file()


def load_mobile_devices_file() -> Optional[list]:
    """DEPRECATED: Use DataLoader.load_mobile_devices_file() instead."""
    return _get_default_loader().load_mobile_devices_file()


def load_config_file() -> Optional[dict]:
    """DEPRECATED: Use DataLoader.load_config_file() instead."""
    return _get_default_loader().load_config_file()


def load_home_state_file() -> Optional[dict]:
    """DEPRECATED: Use DataLoader.load_home_state_file() instead."""
    return _get_default_loader().load_home_state_file()


def load_ratelimit_file() -> Optional[dict]:
    """DEPRECATED: Use DataLoader.load_ratelimit_file() instead."""
    return _get_default_loader().load_ratelimit_file()


def load_offsets_file() -> Optional[dict]:
    """DEPRECATED: Use DataLoader.load_offsets_file() instead."""
    return _get_default_loader().load_offsets_file()


def load_ac_capabilities_file() -> Optional[dict]:
    """DEPRECATED: Use DataLoader.load_ac_capabilities_file() instead."""
    return _get_default_loader().load_ac_capabilities_file()


def load_api_call_history_file() -> Optional[dict]:
    """DEPRECATED: Use DataLoader.load_api_call_history_file() instead."""
    return _get_default_loader().load_api_call_history_file()


def load_schedules_file() -> Optional[dict]:
    """DEPRECATED: Use DataLoader.load_schedules_file() instead."""
    return _get_default_loader().load_schedules_file()


def get_zone_names() -> dict:
    """DEPRECATED: Use DataLoader.get_zone_names() instead."""
    return _get_default_loader().get_zone_names()


def get_zone_types() -> dict:
    """DEPRECATED: Use DataLoader.get_zone_types() instead."""
    return _get_default_loader().get_zone_types()


def get_zone_data(zone_id: str) -> Optional[dict]:
    """DEPRECATED: Use DataLoader.get_zone_data() instead."""
    return _get_default_loader().get_zone_data(zone_id)


def get_zone_schedule(zone_id: str) -> Optional[dict]:
    """DEPRECATED: Use DataLoader.get_zone_schedule() instead."""
    return _get_default_loader().get_zone_schedule(zone_id)


def load_overlay_mode() -> str:
    """DEPRECATED: Use DataLoader.load_overlay_mode() instead."""
    return _get_default_loader().load_overlay_mode()


def save_overlay_mode(mode: str) -> bool:
    """DEPRECATED: Use DataLoader.save_overlay_mode() instead."""
    return _get_default_loader().save_overlay_mode(mode)


def save_timer_duration(duration: int) -> bool:
    """DEPRECATED: Use DataLoader.save_timer_duration() instead."""
    return _get_default_loader().save_timer_duration(duration)


def load_timer_duration() -> int:
    """DEPRECATED: Use DataLoader.load_timer_duration() instead."""
    return _get_default_loader().load_timer_duration()


def load_outdoor_temp_history() -> list:
    """DEPRECATED: Use DataLoader.load_outdoor_temp_history() instead."""
    return _get_default_loader().load_outdoor_temp_history()


def save_outdoor_temp_history(readings: list) -> bool:
    """DEPRECATED: Use DataLoader.save_outdoor_temp_history() instead."""
    return _get_default_loader().save_outdoor_temp_history(readings)

