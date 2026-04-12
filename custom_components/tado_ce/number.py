"""Tado CE Number Platform — boiler max output temperature control."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from homeassistant.components.number import NumberDeviceClass, NumberEntity
from homeassistant.const import UnitOfTemperature
from homeassistant.core import callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .bridge_api import FLOW_TEMP_STEP, MAX_FLOW_TEMP, MIN_FLOW_TEMP
from .device_manager import get_hub_device_info
from .entity_registry import ENTITY_REGISTRY, get_entity_category
from .exceptions import TadoBridgeApiError

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

    from .coordinator import TadoConfigEntry, TadoDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: TadoConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Tado CE number entities from a config entry."""
    coordinator: TadoDataUpdateCoordinator = entry.runtime_data
    entities = []

    # Bridge number entity (optional — only when bridge credentials configured
    # AND the bridge response actually contains the temperature field)
    bridge_serial = entry.options.get("bridge_serial")
    bridge_auth_key = entry.options.get("bridge_auth_key")
    if bridge_serial and bridge_auth_key:
        bridge_data = coordinator.data.get("bridge")
        if isinstance(bridge_data, dict) and "boilerMaxOutputTemperatureInCelsius" in bridge_data:
            entities.append(TadoBoilerMaxOutputTemperatureNumber(coordinator))
            _LOGGER.info("Bridge credentials found with temperature field — creating bridge number entity")
        else:
            _LOGGER.debug(
                "Bridge credentials present but boilerMaxOutputTemperatureInCelsius not in response — "
                "skipping number entity",
            )

    async_add_entities(entities, True)


class TadoBoilerMaxOutputTemperatureNumber(
    CoordinatorEntity["TadoDataUpdateCoordinator"],
    NumberEntity,
):
    """Number entity for controlling boiler max output temperature.

    Uses optimistic update: value reflects the set value immediately,
    then syncs with the server on the next coordinator poll.
    """

    _attr_has_entity_name = True
    _attr_native_min_value = MIN_FLOW_TEMP
    _attr_native_max_value = MAX_FLOW_TEMP
    _attr_native_step = FLOW_TEMP_STEP
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_device_class = NumberDeviceClass.TEMPERATURE
    _attr_icon = "mdi:thermometer-water"

    def __init__(self, coordinator: TadoDataUpdateCoordinator) -> None:
        """Initialize the TadoBoilerMaxOutputTemperatureNumber."""
        super().__init__(coordinator)
        _meta = ENTITY_REGISTRY["number_boiler_max_output_temp"]
        self._attr_translation_key = _meta.translation_key
        self._attr_unique_id = f"tado_ce_{coordinator.home_id}_{_meta.unique_id_suffix}"
        if _meta.icon:
            self._attr_icon = _meta.icon
        self._attr_entity_category = get_entity_category(_meta)
        self._attr_device_info = get_hub_device_info(coordinator.home_id)
        self._attr_available = False
        self._attr_native_value: float | None = None

    async def async_set_native_value(self, value: float) -> None:
        """Set boiler max output temperature via Bridge API.

        Uses optimistic update: sets _attr_native_value immediately on
        success. The next coordinator poll will confirm or correct the
        value (server is source of truth).
        """
        client = self.coordinator.bridge_api_client
        if client is None:
            msg = "Bridge API client not available"
            raise HomeAssistantError(msg)
        try:
            await client.async_set_max_output_temperature(value)
        except TadoBridgeApiError as err:
            _LOGGER.exception("Failed to set boiler max output temperature")
            msg = "Failed to set boiler max output temperature"
            raise HomeAssistantError(msg) from err
        # Optimistic update — reflect new value immediately
        self._attr_native_value = round(value * 2) / 2
        self.async_write_ha_state()

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle coordinator data update."""
        bridge = self.coordinator.data.get("bridge")
        if not bridge:
            self._attr_available = False
            self.async_write_ha_state()
            return
        temp = bridge.get("boilerMaxOutputTemperatureInCelsius")
        if temp is not None:
            self._attr_native_value = float(temp)
            self._attr_available = True
        else:
            self._attr_available = False
        self.async_write_ha_state()
