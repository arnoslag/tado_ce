"""Tado CE Switch Platform — child lock and early start."""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .action_helpers import (
    check_bootstrap_reserve as _check_bootstrap_reserve,
)
from .action_helpers import (
    is_within_optimistic_window as _is_within_optimistic_window,
)
from .device_manager import get_hub_device_info, get_zone_device_info
from .entity_registry import ENTITY_REGISTRY, get_entity_category
from .helpers import async_trigger_immediate_refresh

if TYPE_CHECKING:
    from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

    from .coordinator import TadoConfigEntry, TadoDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: TadoConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Tado CE switches from a config entry."""
    _LOGGER.debug("Tado CE switch: Setting up...")
    coordinator = entry.runtime_data
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
                    switches.append(
                        TadoEarlyStartSwitch(
                            coordinator,
                            zone_id,
                            zone_name,
                            zone_type,
                            early_start.get("enabled", False),
                            home_id,
                        ),
                    )

            # Child Lock switches (per device)
            # Tado API may return null for 'devices'; 'or []' handles None correctly
            for device in zone.get("devices") or []:
                if "childLockEnabled" in device:
                    serial = device.get("shortSerialNo")
                    device_type = device.get("deviceType", "unknown")
                    switches.append(
                        TadoChildLockSwitch(  # type: ignore[arg-type]
                            coordinator,
                            zone_id,
                            serial,
                            zone_name,
                            zone_type,
                            device_type,
                            device.get("childLockEnabled", False),
                            zones_info,
                            home_id,
                        ),
                    )

    if switches:
        async_add_entities(switches, True)
        _LOGGER.info("Tado CE switches loaded: %s", len(switches))
    else:
        _LOGGER.debug("Tado CE: No switches found (device_controls_enabled may be OFF)")

    # Hub control toggles (always created)
    hub_switches: list[SwitchEntity] = [
        TadoHubToggleSwitch(
            coordinator, home_id, "switch_test_mode", "test_mode_enabled", "mdi:test-tube", "mdi:test-tube-off",
        ),
        TadoHubToggleSwitch(
            coordinator, home_id, "switch_quota_reserve", "quota_reserve_enabled", "mdi:shield-check", "mdi:shield-off",
        ),
    ]
    async_add_entities(hub_switches, True)



# TadoAwayModeSwitch class REMOVED
# Replaced by TadoPresenceModeSelect in select.py


class TadoEarlyStartSwitch(CoordinatorEntity["TadoDataUpdateCoordinator"], SwitchEntity):
    """TadoEarlyStartSwitch."""

    _attr_has_entity_name = True

    """Tado CE Early Start Switch Entity."""

    def __init__(
        self,
        coordinator: TadoDataUpdateCoordinator,
        zone_id: str,
        zone_name: str,
        zone_type: str,
        initial_state: bool,
        home_id: str,
    ) -> None:
        """Initialize."""
        super().__init__(coordinator)
        _meta = ENTITY_REGISTRY["switch_early_start"]
        self._zone_id = zone_id
        self._zone_name = zone_name
        self._zone_type = zone_type
        self._entry_id = coordinator.config_entry.entry_id

        self._attr_translation_key = _meta.translation_key
        self._attr_unique_id = f"tado_ce_{home_id}_{_meta.unique_id_suffix.format(zone_id=zone_id)}"
        self._attr_entity_category = get_entity_category(_meta)
        self._attr_icon = _meta.icon
        self._attr_is_on = initial_state
        self._attr_available = True
        self._attr_device_info = get_zone_device_info(zone_id, zone_name, zone_type, home_id)

        # Optimistic update tracking (parity with climate entities)
        self._optimistic_set_at: float | None = None

    def _is_within_optimistic_window(self) -> bool:
        """Check if we're within the optimistic update window."""
        return _is_within_optimistic_window(self.hass, self._optimistic_set_at, entry_id=self._entry_id)

    @property
    def icon(self) -> str | None:
        """Return icon based on state."""
        return "mdi:clock-fast" if self._attr_is_on else "mdi:clock-outline"

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
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

        if self._optimistic_set_at is not None:
            self._optimistic_set_at = None

        # Early start state is not in the cached files, so we keep the last known state

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on early start - async.

        Added optimistic tracking and proper rollback (parity with climate entities).
        Added bootstrap reserve check - blocks action when quota critically low.
        """
        await _check_bootstrap_reserve(self.hass, f"Early Start {self._zone_name}", entry_id=self._entry_id)

        old_is_on = self._attr_is_on

        # Optimistic update BEFORE API call
        self._attr_is_on = True
        self._optimistic_set_at = time.monotonic()
        self.async_write_ha_state()

        success = await self._async_set_early_start(True)
        if success:
            await async_trigger_immediate_refresh(self.hass, self.entity_id, "early_start_on")
        else:
            _LOGGER.warning("ROLLBACK: %s Early Start ON failed", self._zone_name)
            self._attr_is_on = old_is_on
            self._optimistic_set_at = None
            self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off early start - async.

        Added optimistic tracking and proper rollback (parity with climate entities).
        Added bootstrap reserve check - blocks action when quota critically low.
        """
        await _check_bootstrap_reserve(self.hass, f"Early Start {self._zone_name}", entry_id=self._entry_id)

        old_is_on = self._attr_is_on

        self._attr_is_on = False
        self._optimistic_set_at = time.monotonic()
        self.async_write_ha_state()

        success = await self._async_set_early_start(False)
        if success:
            await async_trigger_immediate_refresh(self.hass, self.entity_id, "early_start_off")
        else:
            _LOGGER.warning("ROLLBACK: %s Early Start OFF failed", self._zone_name)
            self._attr_is_on = old_is_on
            self._optimistic_set_at = None
            self.async_write_ha_state()

    async def _async_set_early_start(self, enabled: bool) -> bool:
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

    def __init__(
        self,
        coordinator: TadoDataUpdateCoordinator,
        zone_id: str,
        serial: str,
        zone_name: str,
        zone_type: str,
        device_type: str,
        initial_state: bool,
        zones_info: list[Any],
        home_id: str,
    ) -> None:
        """Initialize."""
        super().__init__(coordinator)
        _meta = ENTITY_REGISTRY["switch_child_lock"]
        self._zone_id = zone_id
        self._serial = serial
        self._zone_name = zone_name
        self._zone_type = zone_type
        self._device_type = device_type
        self._entry_id = coordinator.config_entry.entry_id

        self._attr_translation_key = _meta.translation_key
        self._attr_unique_id = f"tado_ce_{home_id}_{_meta.unique_id_suffix.format(serial=serial)}"
        self._attr_entity_category = get_entity_category(_meta)
        self._attr_icon = _meta.icon
        self._attr_is_on = initial_state
        self._attr_available = True
        self._attr_device_info = get_zone_device_info(zone_id, zone_name, zone_type, home_id)

        # Optimistic update tracking (parity with climate entities)
        self._optimistic_set_at: float | None = None

    def _is_within_optimistic_window(self) -> bool:
        """Check if we're within the optimistic update window."""
        return _is_within_optimistic_window(self.hass, self._optimistic_set_at, entry_id=self._entry_id)

    @property
    def icon(self) -> str | None:
        """Return icon based on state."""
        return "mdi:lock" if self._attr_is_on else "mdi:lock-open"

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
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
                self._zone_name,
                self._serial,
            )
            return

        if self._optimistic_set_at is not None:
            self._optimistic_set_at = None

        try:
            zones_info = (self.coordinator.data or {}).get("zones_info")

            if zones_info:
                for zone in zones_info:
                    for device in zone.get("devices") or []:
                        if device.get("shortSerialNo") == self._serial:
                            if "childLockEnabled" in device:
                                self._attr_is_on = device.get("childLockEnabled", False)
                                self._attr_available = True
                                return

            self._attr_available = False
        except Exception:
            self._attr_available = False

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on child lock - async.

        Added optimistic tracking and proper rollback (parity with climate entities).
        Added bootstrap reserve check - blocks action when quota critically low.
        """
        await _check_bootstrap_reserve(self.hass, f"Child Lock {self._zone_name}", entry_id=self._entry_id)

        old_is_on = self._attr_is_on

        # Optimistic update BEFORE API call
        self._attr_is_on = True
        self._optimistic_set_at = time.monotonic()
        self.async_write_ha_state()

        success = await self._async_set_child_lock(True)
        if success:
            await async_trigger_immediate_refresh(self.hass, self.entity_id, "child_lock_on")
        else:
            _LOGGER.warning("ROLLBACK: %s Child Lock (%s) ON failed", self._zone_name, self._serial)
            self._attr_is_on = old_is_on
            self._optimistic_set_at = None
            self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off child lock - async.

        Added optimistic tracking and proper rollback (parity with climate entities).
        Added bootstrap reserve check - blocks action when quota critically low.
        """
        await _check_bootstrap_reserve(self.hass, f"Child Lock {self._zone_name}", entry_id=self._entry_id)

        old_is_on = self._attr_is_on

        self._attr_is_on = False
        self._optimistic_set_at = time.monotonic()
        self.async_write_ha_state()

        success = await self._async_set_child_lock(False)
        if success:
            await async_trigger_immediate_refresh(self.hass, self.entity_id, "child_lock_off")
        else:
            _LOGGER.warning("ROLLBACK: %s Child Lock (%s) OFF failed", self._zone_name, self._serial)
            self._attr_is_on = old_is_on
            self._optimistic_set_at = None
            self.async_write_ha_state()

    async def _async_set_child_lock(self, enabled: bool) -> bool:
        """Set child lock state via centralized API client."""
        return await self.coordinator.api_client.set_child_lock(self._serial, enabled)


class TadoHubToggleSwitch(CoordinatorEntity["TadoDataUpdateCoordinator"], SwitchEntity):
    """Handle a hub-level config toggle (Test Mode / Quota Reserve)."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: TadoDataUpdateCoordinator,
        home_id: str,
        registry_key: str,
        option_key: str,
        icon_on: str,
        icon_off: str,
    ) -> None:
        """Initialize the TadoHubToggleSwitch."""
        super().__init__(coordinator)
        _meta = ENTITY_REGISTRY[registry_key]
        self._option_key = option_key
        self._icon_on = icon_on
        self._icon_off = icon_off

        self._attr_translation_key = _meta.translation_key
        self._attr_unique_id = f"tado_ce_{home_id}_{_meta.unique_id_suffix}"
        self._attr_device_info = get_hub_device_info(home_id)
        self._attr_entity_category = get_entity_category(_meta)
        self._attr_is_on = self._read_option()

    def _read_option(self) -> bool:
        """Read current option value from config entry."""
        entry = self.coordinator.config_entry
        result = entry.options.get(self._option_key, self._attr_is_on)
        return bool(result)

    @property
    def icon(self) -> str | None:
        """Return icon based on state."""
        return self._icon_on if self._attr_is_on else self._icon_off

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle coordinator data update."""
        self._attr_is_on = self._read_option()
        self.async_write_ha_state()

    async def async_turn_on(self, **kwargs: Any) -> None:  # noqa: ANN401 — HA interface
        """Turn on the toggle."""
        await self._async_set_option(True)

    async def async_turn_off(self, **kwargs: Any) -> None:  # noqa: ANN401 — HA interface
        """Turn off the toggle."""
        await self._async_set_option(False)

    async def _async_set_option(self, value: bool) -> None:
        """Persist option to config entry and update state.

        These options are read in real-time by config_manager, so the
        change takes effect immediately without an integration reload.
        For test_mode_enabled transitions, we also trigger an API refresh
        to get real rate limit data when exiting test mode.
        """
        entry = self.coordinator.config_entry
        new_options = {**entry.options, self._option_key: value}
        self.hass.config_entries.async_update_entry(entry, options=new_options)
        self._attr_is_on = value
        self.async_write_ha_state()
        _LOGGER.info("Tado CE: %s set to %s", self._option_key, value)

        # Handle test mode transition (disable → need API refresh for real data)
        if self._option_key == "test_mode_enabled":
            from .migration import async_handle_test_mode_transition

            try:
                await async_handle_test_mode_transition(self.hass, entry)
            except Exception as exc:
                _LOGGER.debug("Tado CE: Test mode transition handling: %s", exc)
