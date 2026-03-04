"""Tado CE Switch Platform (Child Lock + Early Start).

Extends CoordinatorEntity for automatic update subscription.
"""
import logging
import time
from datetime import timedelta
from typing import TYPE_CHECKING

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .action_helpers import (
    check_bootstrap_reserve as _check_bootstrap_reserve,
)
from .action_helpers import (
    is_within_optimistic_window as _is_within_optimistic_window,
)
from .const import API_ENDPOINT_DEVICES
from .device_manager import get_zone_device_info
from .helpers import async_trigger_immediate_refresh

if TYPE_CHECKING:
    from .coordinator import TadoDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)
SCAN_INTERVAL = timedelta(seconds=30)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Tado CE switches from a config entry."""
    _LOGGER.debug("Tado CE switch: Setting up...")
    coordinator: TadoDataUpdateCoordinator = entry.runtime_data
    data_loader = coordinator.data_loader
    home_id = coordinator.home_id
    zones_info = await hass.async_add_executor_job(data_loader.load_zones_info_file)

    # Get config manager for feature toggles
    config_manager = coordinator.config_manager

    switches = []

    # Away Mode switch removed - replaced by select.tado_ce_presence_mode

    # Device controls (Early Start, Child Lock) controlled by feature toggle
    if config_manager.get_device_controls_enabled() and zones_info:
        for zone in zones_info:
            zone_id = str(zone.get("id"))
            zone_name = zone.get("name", f"Zone {zone.get('id')}")
            zone_type = zone.get("type")

            # Early Start switch (for heating zones that support it)
            if zone_type == "HEATING":
                early_start = zone.get("earlyStart") or {}
                if early_start.get("supported", True):  # Default to supported
                    switches.append(TadoEarlyStartSwitch(
                        coordinator, zone_id, zone_name, zone_type, early_start.get("enabled", False), home_id,
                    ))

            # Child Lock switches (per device)
            for device in zone.get("devices", []):
                if "childLockEnabled" in device:
                    serial = device.get("shortSerialNo")
                    device_type = device.get("deviceType", "unknown")
                    switches.append(TadoChildLockSwitch(
                        coordinator, zone_id, serial, zone_name, zone_type,
                        device_type, device.get("childLockEnabled", False),
                        zones_info, home_id,
                    ))

    if switches:
        async_add_entities(switches, True)  # noqa: FBT003
        _LOGGER.info("Tado CE switches loaded: %s", len(switches))
    else:
        _LOGGER.debug("Tado CE: No switches found (device_controls_enabled may be OFF)")

    # Zone configuration switch entities (per-zone settings)
    from .zone_config import async_setup_zone_config_switch  # noqa: PLC0415
    await async_setup_zone_config_switch(hass, entry, async_add_entities)


# TadoAwayModeSwitch class REMOVED
# Replaced by TadoPresenceModeSelect in select.py


class TadoEarlyStartSwitch(CoordinatorEntity["TadoDataUpdateCoordinator"], SwitchEntity):
    """TadoEarlyStartSwitch."""

    _attr_has_entity_name = True


    """Tado CE Early Start Switch Entity."""

    def __init__(self, coordinator: "TadoDataUpdateCoordinator", zone_id: str, zone_name: str, zone_type: str, initial_state: bool, home_id: str) -> None:  # noqa: E501, FBT001, PLR0913
        """Initialize."""
        super().__init__(coordinator)
        self._zone_id = zone_id
        self._zone_name = zone_name
        self._zone_type = zone_type
        # Convenience alias — used by action_helpers that still accept entry_id
        self._entry_id = coordinator.config_entry.entry_id

        self._attr_name = "[CE] Early Start"
        # Use zone_id for unique_id to maintain entity_id stability across zone name changes
        self._attr_unique_id = f"tado_ce_{home_id}_zone_{zone_id}_early_start"
        self._attr_icon = "mdi:clock-fast"
        self._attr_is_on = initial_state
        self._attr_available = True
        # Use zone device info instead of hub device info
        self._attr_device_info = get_zone_device_info(zone_id, zone_name, zone_type, home_id)

        # Optimistic update tracking (parity with climate entities)
        self._optimistic_set_at: float | None = None

    # ========== Helper Methods ==========

    def _is_within_optimistic_window(self) -> bool:
        """Check if we're within the optimistic update window."""
        return _is_within_optimistic_window(self.hass, self._optimistic_set_at, entry_id=self._entry_id)

    # ========== End Helper Methods ==========

    @property
    def icon(self) -> None:
        """Return icon based on state."""
        return "mdi:clock-fast" if self._attr_is_on else "mdi:clock-outline"

    @property
    def extra_state_attributes(self) -> None:
        """Return extra state attributes."""
        return {
            "zone_id": self._zone_id,
            "zone": self._zone_name,
            "description": "Pre-heats the room to reach target temperature on time",
        }

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle coordinator data update.

        CoordinatorEntity calls this automatically.
        """
        self.update()
        self.async_write_ha_state()

    @callback
    def update(self) -> None:
        """Update early start state from API.

        Added optimistic window protection (parity with climate entities).
        Early start state is not in the cached files, so we keep the last known state.
        It will be updated when user toggles it.
        """
        # Preserve optimistic state if within window
        if self._is_within_optimistic_window():
            _LOGGER.debug("%s Early Start: Preserving optimistic state (within window)", self._zone_name)
            return

        # Window expired, clear optimistic tracking
        if self._optimistic_set_at is not None:
            self._optimistic_set_at = None

        # Early start state is not in the cached files, so we keep the last known state

    async def async_turn_on(self, **kwargs) -> None:  # noqa: ANN003, ARG002
        """Turn on early start - async.

        Added optimistic tracking and proper rollback (parity with climate entities).
        Added bootstrap reserve check - blocks action when quota critically low.
        """
        # Bootstrap Reserve - block action when quota critically low
        await _check_bootstrap_reserve(self.hass, f"Early Start {self._zone_name}", entry_id=self._entry_id)

        # Store previous state for rollback
        old_is_on = self._attr_is_on

        # Optimistic update BEFORE API call
        self._attr_is_on = True
        self._optimistic_set_at = time.time()
        self.async_write_ha_state()

        success = await self._async_set_early_start(True)  # noqa: FBT003
        if success:
            await async_trigger_immediate_refresh(self.hass, self.entity_id, "early_start_on")
        else:
            _LOGGER.warning("ROLLBACK: %s Early Start ON failed", self._zone_name)
            self._attr_is_on = old_is_on
            self._optimistic_set_at = None
            self.async_write_ha_state()

    async def async_turn_off(self, **kwargs) -> None:  # noqa: ANN003, ARG002
        """Turn off early start - async.

        Added optimistic tracking and proper rollback (parity with climate entities).
        Added bootstrap reserve check - blocks action when quota critically low.
        """
        # Bootstrap Reserve - block action when quota critically low
        await _check_bootstrap_reserve(self.hass, f"Early Start {self._zone_name}", entry_id=self._entry_id)

        # Store previous state for rollback
        old_is_on = self._attr_is_on

        # Optimistic update BEFORE API call
        self._attr_is_on = False
        self._optimistic_set_at = time.time()
        self.async_write_ha_state()

        success = await self._async_set_early_start(False)  # noqa: FBT003
        if success:
            await async_trigger_immediate_refresh(self.hass, self.entity_id, "early_start_off")
        else:
            _LOGGER.warning("ROLLBACK: %s Early Start OFF failed", self._zone_name)
            self._attr_is_on = old_is_on
            self._optimistic_set_at = None
            self.async_write_ha_state()


    async def _async_set_early_start(self, enabled: bool) -> bool:  # noqa: FBT001
        """Set early start state via async API."""
        client = self.coordinator.api_client

        # Early start uses a different endpoint format
        endpoint = f"zones/{self._zone_id}/earlyStart"
        result = await client.api_call(endpoint, method="PUT", data={"enabled": enabled})

        if result is not None:
            state_str = "enabled" if enabled else "disabled"
            _LOGGER.info("Early Start %s for %s", state_str, self._zone_name)
            self._attr_is_on = enabled
            self.async_write_ha_state()
            return True

        _LOGGER.error("Failed to set early start for %s", self._zone_name)
        return False


class TadoChildLockSwitch(CoordinatorEntity["TadoDataUpdateCoordinator"], SwitchEntity):
    """TadoChildLockSwitch."""

    _attr_has_entity_name = True


    """Tado CE Child Lock Switch Entity."""

    def __init__(  # noqa: PLR0913
        self, coordinator: "TadoDataUpdateCoordinator", zone_id: str, serial: str,
        zone_name: str, zone_type: str, device_type: str,
        initial_state: bool, zones_info: list, home_id: str,  # noqa: ARG002, FBT001
    ) -> None:
        """Initialize."""
        super().__init__(coordinator)
        self._zone_id = zone_id
        self._serial = serial
        self._zone_name = zone_name
        self._zone_type = zone_type
        self._device_type = device_type
        # Convenience alias — used by action_helpers that still accept entry_id
        self._entry_id = coordinator.config_entry.entry_id

        self._attr_name = "Child Lock"
        self._attr_unique_id = f"tado_ce_{home_id}_device_{serial}_child_lock"
        self._attr_icon = "mdi:lock"
        self._attr_is_on = initial_state
        self._attr_available = True
        # Use zone device info instead of hub device info
        self._attr_device_info = get_zone_device_info(zone_id, zone_name, zone_type, home_id)

        # Optimistic update tracking (parity with climate entities)
        self._optimistic_set_at: float | None = None

    # ========== Helper Methods ==========

    def _is_within_optimistic_window(self) -> bool:
        """Check if we're within the optimistic update window."""
        return _is_within_optimistic_window(self.hass, self._optimistic_set_at, entry_id=self._entry_id)

    # ========== End Helper Methods ==========

    @property
    def icon(self) -> None:
        """Return icon based on state."""
        return "mdi:lock" if self._attr_is_on else "mdi:lock-open"

    @property
    def extra_state_attributes(self) -> None:
        """Return extra state attributes."""
        return {
            "serial": self._serial,
            "device_type": self._device_type,
            "zone": self._zone_name,
        }

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle coordinator data update.

        CoordinatorEntity calls this automatically.
        """
        self.update()
        self.async_write_ha_state()

    @callback
    def update(self) -> None:
        """Update child lock state from JSON file.

        Added optimistic window protection (parity with climate entities).
        """
        # Preserve optimistic state if within window
        if self._is_within_optimistic_window():
            _LOGGER.debug(
                "%s Child Lock (%s): Preserving optimistic state (within window)",
                self._zone_name, self._serial,
            )
            return

        # Window expired, clear optimistic tracking
        if self._optimistic_set_at is not None:
            self._optimistic_set_at = None

        try:
            # Use coordinator cached zones_info data (async-loaded, no file I/O)
            zones_info = (self.coordinator.data or {}).get("zones_info")

            if zones_info:
                for zone in zones_info:
                    for device in zone.get("devices", []):
                        if device.get("shortSerialNo") == self._serial:  # noqa: SIM102
                            if "childLockEnabled" in device:
                                self._attr_is_on = device.get("childLockEnabled", False)
                                self._attr_available = True
                                return

            self._attr_available = False
        except Exception:  # noqa: BLE001
            self._attr_available = False

    async def async_turn_on(self, **kwargs) -> None:  # noqa: ANN003, ARG002
        """Turn on child lock - async.

        Added optimistic tracking and proper rollback (parity with climate entities).
        Added bootstrap reserve check - blocks action when quota critically low.
        """
        # Bootstrap Reserve - block action when quota critically low
        await _check_bootstrap_reserve(self.hass, f"Child Lock {self._zone_name}", entry_id=self._entry_id)

        # Store previous state for rollback
        old_is_on = self._attr_is_on

        # Optimistic update BEFORE API call
        self._attr_is_on = True
        self._optimistic_set_at = time.time()
        self.async_write_ha_state()

        success = await self._async_set_child_lock(True)  # noqa: FBT003
        if success:
            await async_trigger_immediate_refresh(self.hass, self.entity_id, "child_lock_on")
        else:
            _LOGGER.warning("ROLLBACK: %s Child Lock (%s) ON failed", self._zone_name, self._serial)
            self._attr_is_on = old_is_on
            self._optimistic_set_at = None
            self.async_write_ha_state()

    async def async_turn_off(self, **kwargs) -> None:  # noqa: ANN003, ARG002
        """Turn off child lock - async.

        Added optimistic tracking and proper rollback (parity with climate entities).
        Added bootstrap reserve check - blocks action when quota critically low.
        """
        # Bootstrap Reserve - block action when quota critically low
        await _check_bootstrap_reserve(self.hass, f"Child Lock {self._zone_name}", entry_id=self._entry_id)

        # Store previous state for rollback
        old_is_on = self._attr_is_on

        # Optimistic update BEFORE API call
        self._attr_is_on = False
        self._optimistic_set_at = time.time()
        self.async_write_ha_state()

        success = await self._async_set_child_lock(False)  # noqa: FBT003
        if success:
            await async_trigger_immediate_refresh(self.hass, self.entity_id, "child_lock_off")
        else:
            _LOGGER.warning("ROLLBACK: %s Child Lock (%s) OFF failed", self._zone_name, self._serial)
            self._attr_is_on = old_is_on
            self._optimistic_set_at = None
            self.async_write_ha_state()


    async def _async_set_child_lock(self, enabled: bool) -> bool:  # noqa: FBT001
        """Set child lock state via async API."""
        import aiohttp  # noqa: PLC0415
        from homeassistant.helpers.aiohttp_client import async_get_clientsession  # noqa: PLC0415

        client = self.coordinator.api_client
        token = await client.get_access_token()

        if not token:
            _LOGGER.error("Failed to get access token")
            return False

        # Child lock uses device endpoint (not home endpoint)
        url = f"{API_ENDPOINT_DEVICES}/{self._serial}/childLock"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

        session = async_get_clientsession(self.hass)

        try:
            async with session.put(
                url, headers=headers, json={"childLockEnabled": enabled},
            ) as resp:
                if resp.status in (200, 204):
                    state_str = "enabled" if enabled else "disabled"
                    _LOGGER.info("Child lock %s for %s (%s)", state_str, self._zone_name, self._serial)
                    self._attr_is_on = enabled
                    self.async_write_ha_state()
                    return True

                _LOGGER.error("Failed to set child lock: %s", resp.status)
                return False

        except aiohttp.ClientError as e:
            _LOGGER.exception("Network error while setting child lock: %s", e)  # noqa: TRY401
            return False
        except Exception as e:
            _LOGGER.exception("Unexpected error while setting child lock: %s", e)  # noqa: TRY401
            return False
