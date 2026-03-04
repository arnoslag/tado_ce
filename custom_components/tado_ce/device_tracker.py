"""Tado CE Device Tracker (Presence Detection)."""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import TYPE_CHECKING

from homeassistant.components.device_tracker import SourceType
from homeassistant.components.device_tracker.config_entry import TrackerEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .device_manager import get_hub_device_info

if TYPE_CHECKING:
    from .coordinator import TadoDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)
SCAN_INTERVAL = timedelta(seconds=30)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
):
    """Set up Tado CE device trackers from a config entry."""
    coordinator: TadoDataUpdateCoordinator = entry.runtime_data
    data_loader = coordinator.data_loader
    home_id = coordinator.home_id
    _LOGGER.debug("Tado CE device_tracker: Setting up...")
    mobile_devices = await hass.async_add_executor_job(data_loader.load_mobile_devices_file)

    trackers = []

    if mobile_devices:
        for device in mobile_devices:
            device_id = device.get('id')
            device_name = device.get('name', f"Device {device_id}")
            settings = device.get('settings') or {}

            # Only create tracker if geo tracking is enabled
            if settings.get('geoTrackingEnabled', False):
                trackers.append(TadoDeviceTracker(coordinator, device_id, device_name, device, home_id))
            else:
                _LOGGER.debug("Skipping %s - geoTrackingEnabled is False", device_name)

    if trackers:
        async_add_entities(trackers, True)
        _LOGGER.info("Tado CE device trackers loaded: %s", len(trackers))
    else:
        _LOGGER.debug("Tado CE: No devices with geo tracking enabled")


class TadoDeviceTracker(TrackerEntity):
    _attr_has_entity_name = True

    """Tado CE Device Tracker Entity."""

    def __init__(self, coordinator: TadoDataUpdateCoordinator, device_id: int, device_name: str, device_data: dict, home_id: str):
        self._coordinator = coordinator
        self._device_id = device_id
        self._device_name = device_name
        self._device_data = device_data

        self._attr_name = f"[CE] {device_name}"
        self._attr_unique_id = f"tado_ce_{home_id}_device_{device_id}"
        self._attr_available = False
        # Use hub device info for global entities
        self._attr_device_info = get_hub_device_info(home_id)

        self._is_home = None
        self._location = None
        self._bearing = None
        self._relative_distance = None

    @property
    def should_poll(self) -> bool:
        """Enable polling to read updated mobile device data from JSON file.

        TrackerEntity defaults should_poll=False (designed for push-based
        integrations). Our file-based architecture requires polling so
        update() is called every SCAN_INTERVAL to re-read the JSON file.
        """
        return True

    @property
    def source_type(self) -> SourceType:
        return SourceType.GPS

    @property
    def is_connected(self) -> bool:
        return self._is_home is not None

    @property
    def location_name(self) -> str | None:
        if self._is_home is True:
            return "home"
        elif self._is_home is False:
            return "not_home"
        return None

    @property
    def extra_state_attributes(self):
        metadata = self._device_data.get('deviceMetadata') or {}
        return {
            "device_id": self._device_id,
            "platform": metadata.get('platform'),
            "os_version": metadata.get('osVersion'),
            "model": metadata.get('model'),
            "bearing": self._bearing,
            "relative_distance": self._relative_distance,
        }

    @callback
    def update(self):
        """Update device tracker state from JSON file."""
        try:
            devices = (self._coordinator.data or {}).get("mobile_devices")

            if devices:
                for device in devices:
                    if device.get('id') == self._device_id:
                        self._device_data = device
                        location = device.get('location')

                        if location:
                            self._is_home = location.get('atHome')
                            self._bearing = (location.get('bearingFromHome') or {}).get('degrees')
                            self._relative_distance = location.get('relativeDistanceFromHomeFence')
                        else:
                            # No location data - device might not have geo tracking
                            self._is_home = None

                        self._attr_available = True
                        return

            self._attr_available = False
        except Exception:
            self._attr_available = False
