"""Tado CE Climate Platform — Supports Heating and AC zones.

Modules:
- climate.py: async_setup_entry (this file)
- climate_maps.py: HVAC mode maps, fan maps, get_zone_capabilities, build_fan_mapping
- climate_heating.py: TadoClimate (heating zones)
- climate_ac.py: TadoACClimate (AC zones)
"""
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .climate_ac import TadoACClimate
from .climate_heating import TadoClimate
from .climate_maps import get_zone_capabilities

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
):
    """Set up Tado CE climate from a config entry."""
    coordinator = entry.runtime_data
    data_loader = coordinator.data_loader
    home_id = coordinator.home_id
    zone_names = await hass.async_add_executor_job(data_loader.get_zone_names)
    zone_types = await hass.async_add_executor_job(data_loader.get_zone_types)
    zone_caps = await hass.async_add_executor_job(get_zone_capabilities, data_loader)

    climates = []
    try:
        zones_data = await hass.async_add_executor_job(data_loader.load_zones_file)
        if zones_data:
            # Use 'or {}' pattern for null safety
            zone_states = zones_data.get('zoneStates') or {}
            for zone_id, zone_data in zone_states.items():
                zone_type = zone_types.get(zone_id, 'HEATING')
                zone_name = zone_names.get(zone_id, f"Zone {zone_id}")
                caps = zone_caps.get(zone_id, {})

                if zone_type == 'HEATING':
                    climates.append(TadoClimate(coordinator, zone_id, zone_name, home_id))
                elif zone_type == 'AIR_CONDITIONING':
                    climates.append(TadoACClimate(coordinator, zone_id, zone_name, caps, home_id))
    except Exception as e:
        _LOGGER.error("Failed to load zones for climate: %s", e)

    async_add_entities(climates, True)
    _LOGGER.info("Tado CE climates loaded: %s", len(climates))
