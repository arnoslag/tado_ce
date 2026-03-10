"""Tado CE Number Platform — zone configuration numbers."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

    from .coordinator import TadoConfigEntry

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: TadoConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Tado CE number entities from a config entry."""
    _LOGGER.debug("Tado CE number: Setting up...")

    # Zone configuration number entities (per-zone settings)
    from .zone_config import async_setup_zone_config_number

    await async_setup_zone_config_number(hass, entry, async_add_entities)
