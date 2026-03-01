"""Zone configuration manager - handles per-zone settings storage and entities.

v2.1.0: Per-zone configuration for heating type, overlay mode, temp limits, etc.
"""
import json
import logging
from pathlib import Path
from typing import Any, Callable, Optional

from homeassistant.core import HomeAssistant

from .const import DATA_DIR, DEFAULT_ZONE_CONFIG, WINDOW_U_VALUES

_LOGGER = logging.getLogger(__name__)


class ZoneConfigManager:
    """Manage per-zone configuration.
    
    Stores zone-specific settings in .storage/tado_ce/zone_config_{home_id}.json
    and provides listener pattern for config changes.
    """
    
    def __init__(self, hass: HomeAssistant, home_id: str):
        """Initialize zone config manager.
        
        Args:
            hass: Home Assistant instance
            home_id: Tado home ID for multi-home support
        """
        self._hass = hass
        self._home_id = home_id
        self._config_file = DATA_DIR / f"zone_config_{home_id}.json"
        self._config: dict[str, dict] = {}
        self._listeners: list[Callable[[str, str, Any], None]] = []
    
    async def async_load(self) -> None:
        """Load zone configuration from storage.
        
        Uses executor_job to avoid blocking I/O.
        """
        def _load() -> dict:
            if self._config_file.exists():
                try:
                    with open(self._config_file, 'r') as f:
                        data = json.load(f)
                        return data.get("zones", {})
                except (json.JSONDecodeError, IOError) as e:
                    _LOGGER.error(f"Failed to load zone config: {e}")
                    return {}
            return {}
        
        self._config = await self._hass.async_add_executor_job(_load)
        _LOGGER.debug(f"Loaded zone config for {len(self._config)} zones")

    async def async_save(self) -> None:
        """Save zone configuration to storage.
        
        Uses executor_job to avoid blocking I/O.
        Creates parent directory if needed.
        """
        def _save() -> None:
            try:
                self._config_file.parent.mkdir(parents=True, exist_ok=True)
                with open(self._config_file, 'w') as f:
                    json.dump({"version": 1, "zones": self._config}, f, indent=2)
            except IOError as e:
                _LOGGER.error(f"Failed to save zone config: {e}")
        
        await self._hass.async_add_executor_job(_save)
        _LOGGER.debug(f"Saved zone config for {len(self._config)} zones")
    
    def get_zone_config(self, zone_id: str) -> dict:
        """Get configuration for a zone, with defaults.
        
        Args:
            zone_id: Zone ID as string
            
        Returns:
            Zone config dict merged with defaults
        """
        zone_config = self._config.get(str(zone_id), {})
        # Merge with defaults (zone config overrides defaults)
        return {**DEFAULT_ZONE_CONFIG, **zone_config}
    
    def get_zone_value(self, zone_id: str, key: str, default: Any = None) -> Any:
        """Get a specific configuration value for a zone.
        
        Args:
            zone_id: Zone ID as string
            key: Configuration key
            default: Default value if not set (uses DEFAULT_ZONE_CONFIG if None)
            
        Returns:
            Configuration value
        """
        config = self.get_zone_config(str(zone_id))
        if default is None:
            return config.get(key, DEFAULT_ZONE_CONFIG.get(key))
        return config.get(key, default)
    
    async def async_set_zone_value(self, zone_id: str, key: str, value: Any) -> None:
        """Set a configuration value for a zone.
        
        Args:
            zone_id: Zone ID as string
            key: Configuration key
            value: Value to set
        """
        zone_id = str(zone_id)
        if zone_id not in self._config:
            self._config[zone_id] = {}
        
        old_value = self._config[zone_id].get(key)
        self._config[zone_id][key] = value
        
        await self.async_save()
        
        # Notify listeners if value changed
        if old_value != value:
            for listener in self._listeners:
                try:
                    listener(zone_id, key, value)
                except Exception as e:
                    _LOGGER.error(f"Error in zone config listener: {e}")
    
    def add_listener(self, callback: Callable[[str, str, Any], None]) -> Callable[[], None]:
        """Add a listener for config changes.
        
        Args:
            callback: Function(zone_id, key, value) called on changes
            
        Returns:
            Function to remove the listener
        """
        self._listeners.append(callback)
        
        def _remove_listener():
            """Remove listener with race condition protection."""
            try:
                self._listeners.remove(callback)
            except ValueError:
                pass  # Already removed
        
        return _remove_listener
    
    def get_window_u_value(self, zone_id: str) -> float:
        """Get window U-value for a zone based on window type.
        
        Args:
            zone_id: Zone ID as string
            
        Returns:
            U-value in W/m²K
        """
        window_type = self.get_zone_value(zone_id, "window_type", "double_pane")
        return WINDOW_U_VALUES.get(window_type, 2.7)
    
    def get_surface_temp_offset(self, zone_id: str) -> float:
        """Get surface temperature offset for mold risk calibration.
        
        v2.1.0: Allows users to calibrate mold risk calculation based on
        laser thermometer measurements of actual cold spots.
        
        Args:
            zone_id: Zone ID as string
            
        Returns:
            Offset in °C (negative = colder surface, positive = warmer)
        """
        return self.get_zone_value(zone_id, "surface_temp_offset", 0.0)
    
    def get_effective_target_temp(self, zone_id: str, target_temp: float) -> float:
        """Get effective target temperature with offset applied.
        
        Args:
            zone_id: Zone ID as string
            target_temp: Original target temperature
            
        Returns:
            Target temperature with offset applied
        """
        offset = self.get_zone_value(zone_id, "temp_offset", 0.0)
        return target_temp + offset
    
    @property
    def zones(self) -> dict[str, dict]:
        """Get all zone configurations."""
        return self._config.copy()
