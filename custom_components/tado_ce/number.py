"""Tado CE Number Platform.

Number entities for zone configuration (min/max temp, timer duration, etc.)
"""
import logging
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

_LOGGER = logging.getLogger(__name__)
SCAN_INTERVAL = timedelta(seconds=30)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Tado CE number entities from a config entry."""
    _LOGGER.debug("Tado CE number: Setting up...")

    # Zone configuration number entities (per-zone settings)
    from .zone_config import async_setup_zone_config_number
    await async_setup_zone_config_number(hass, entry, async_add_entities)
