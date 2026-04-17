"""Tado CE HomeKit Client — connection lifecycle, pairing, and reconnect."""

from __future__ import annotations

import asyncio
import logging
import random
from typing import TYPE_CHECKING, Any, Final

from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

if TYPE_CHECKING:
    from pathlib import Path

    from homeassistant.config_entries import ConfigFlowResult
    from homeassistant.core import HomeAssistant

    from .config_flow_options import TadoCEOptionsFlow

_LOGGER = logging.getLogger(__name__)

# Reconnection backoff schedule (seconds)
_BACKOFF_SCHEDULE: Final[tuple[float, ...]] = (5.0, 10.0, 30.0, 60.0, 300.0)

# HomeKit characteristic UUIDs (short form)
CHAR_CURRENT_TEMPERATURE: Final = "11"
CHAR_CURRENT_HUMIDITY: Final = "10"
CHAR_TARGET_TEMPERATURE: Final = "35"
CHAR_CURRENT_HEATING_STATE: Final = "0F"
CHAR_TARGET_HEATING_STATE: Final = "33"
CHAR_SERIAL_NUMBER: Final = "30"
CHAR_MODEL: Final = "21"

_STORE_VERSION = 1


class HomeKitClient:
    """Manage HomeKit connection to a Tado Internet Bridge.

    Wraps aiohomekit's Controller and IpPairing to provide:
    - Connect from stored pairing credentials
    - Disconnect gracefully
    - Two-step pairing flow (for config flow)
    - Unpair (remove pairing)
    - Auto-reconnect with exponential backoff
    """

    def __init__(
        self,
        hass: HomeAssistant,
        home_id: str,
        pairing_path: Path | None = None,
    ) -> None:
        """Initialize the HomeKit Client.

        Args:
            hass: Home Assistant instance.
            home_id: Tado home ID (for multi-home isolation).
            pairing_path: Deprecated — ignored. Pairing uses HA Store.
        """
        self._hass = hass
        self._home_id = home_id
        self._store: Store[dict[str, Any]] = Store(
            hass, _STORE_VERSION, f"tado_ce/homekit_pairing_{home_id}",
        )
        # Old JSON path for migration
        from .const import get_data_file

        self._old_pairing_path = get_data_file("homekit_pairing", home_id)
        self._controller: Any | None = None  # aiohomekit Controller
        self._pairing: Any | None = None  # aiohomekit IpPairing
        self._is_connected = False
        self._reconnect_task: asyncio.Task[None] | None = None
        self._closing = False

        # Zone mapping (set after pairing/connect)
        self._serial_to_zone: dict[str, str] = {}
        self._zone_to_aids: dict[str, list[int]] = {}

        # Connection stats
        self._last_connected: str | None = None
        self._last_disconnected: str | None = None
        self._reconnect_count = 0

        # Reconnect callbacks (e.g. re-subscribe events, reset circuit breaker)
        self._on_reconnect_callbacks: list[Any] = []

    @property
    def is_connected(self) -> bool:
        """Return True if HomeKit connection is active."""
        return self._is_connected

    @property
    def pairing(self) -> Any | None:
        """Return the underlying aiohomekit pairing object."""
        return self._pairing

    @property
    def connection_stats(self) -> dict[str, Any]:
        """Return connection statistics for the status sensor."""
        return {
            "last_connected": self._last_connected,
            "last_disconnected": self._last_disconnected,
            "reconnect_count": self._reconnect_count,
        }

    def set_zone_mapping(
        self,
        serial_to_zone: dict[str, str],
        zone_to_aids: dict[str, list[int]],
    ) -> None:
        """Set the serial-to-zone and zone-to-aids mappings."""
        self._serial_to_zone = serial_to_zone
        self._zone_to_aids = zone_to_aids

    def add_reconnect_callback(self, callback: Any) -> None:
        """Register an async callback to invoke after successful reconnect.

        Callbacks are awaited in order after `_reconnect_loop` succeeds.
        Typical use: re-subscribe HomeKit events, reset circuit breaker.
        """
        self._on_reconnect_callbacks.append(callback)

    def get_aids_for_zone(self, zone_id: str) -> list[int]:
        """Return accessory IDs for a given zone."""
        return self._zone_to_aids.get(zone_id, [])

    async def _ensure_controller(self) -> Any:
        """Lazily create the aiohomekit Controller."""
        if self._controller is None:
            from homeassistant.components.zeroconf import async_get_async_instance

            zeroconf = await async_get_async_instance(self._hass)

            # Import aiohomekit in executor — lark grammar loading does blocking file I/O
            def _create_controller() -> Any:
                from aiohomekit import Controller
                return Controller

            controller_cls = await self._hass.async_add_executor_job(_create_controller)
            self._controller = controller_cls(
                async_zeroconf_instance=zeroconf,
                char_cache={},
            )
            await self._controller.async_start()
        return self._controller

    async def async_connect(self) -> bool:
        """Connect using stored pairing credentials.

        Returns:
            True if connection succeeded, False otherwise.
        """
        pairing_data: dict[str, Any] | list[Any] | None = await self._store.async_load()
        if not pairing_data or not isinstance(pairing_data, dict):
            # Try migrating from old JSON file
            from .storage import async_migrate_json_to_store

            pairing_data = await async_migrate_json_to_store(
                self._hass, self._old_pairing_path, self._store,
                label="homekit_pairing",
            )
        if not pairing_data or not isinstance(pairing_data, dict):
            _LOGGER.debug("HomeKit: No pairing credentials found")
            return False

        try:
            controller = await self._ensure_controller()
            alias = f"tado_ce_{self._home_id}"
            self._pairing = controller.load_pairing(alias, pairing_data)
            if self._pairing is None:
                _LOGGER.warning("HomeKit: load_pairing returned None — credentials may be invalid")
                return False

            # Verify connection by listing accessories
            await self._pairing.list_accessories_and_characteristics()
            self._is_connected = True
            self._last_connected = dt_util.utcnow().isoformat()
            _LOGGER.info("HomeKit: Connected to bridge (home %s)", self._home_id)
            return True
        except Exception:
            _LOGGER.exception("HomeKit: Connection failed (home %s)", self._home_id)
            self._pairing = None
            self._is_connected = False
            return False

    async def async_disconnect(self) -> None:
        """Disconnect and clean up."""
        self._closing = True
        if self._reconnect_task and not self._reconnect_task.done():
            self._reconnect_task.cancel()
            try:
                await self._reconnect_task
            except asyncio.CancelledError:
                pass
            self._reconnect_task = None

        if self._pairing:
            try:
                await self._pairing.close()
            except Exception:
                _LOGGER.debug("HomeKit: Error during disconnect", exc_info=True)
            self._pairing = None

        self._is_connected = False
        self._last_disconnected = dt_util.utcnow().isoformat()
        _LOGGER.debug("HomeKit: Disconnected (home %s)", self._home_id)

    async def async_reconnect(self) -> None:
        """Reconnect with exponential backoff.

        Called when connection is lost. Runs in background.
        """
        if self._reconnect_task and not self._reconnect_task.done():
            return  # Already reconnecting
        self._reconnect_task = asyncio.create_task(self._reconnect_loop())

    async def _reconnect_loop(self) -> None:
        """Reconnect loop with exponential backoff and jitter."""
        self._is_connected = False
        self._last_disconnected = dt_util.utcnow().isoformat()
        backoff_idx = 0

        while not self._closing:
            max_delay = _BACKOFF_SCHEDULE[min(backoff_idx, len(_BACKOFF_SCHEDULE) - 1)]
            delay = random.uniform(0, max_delay)
            _LOGGER.debug(
                "HomeKit: Reconnect attempt %d in %.1fs (home %s)",
                backoff_idx + 1, delay, self._home_id,
            )
            await asyncio.sleep(delay)

            if self._closing:
                return

            try:
                success = await self.async_connect()
                if success:
                    self._reconnect_count += 1
                    _LOGGER.info(
                        "HomeKit: Reconnected after %d attempts (home %s)",
                        backoff_idx + 1, self._home_id,
                    )
                    # Invoke reconnect callbacks (re-subscribe events, reset circuit breaker)
                    for cb in self._on_reconnect_callbacks:
                        try:
                            await cb()
                        except Exception:
                            _LOGGER.debug("HomeKit: Reconnect callback failed", exc_info=True)
                    return
            except Exception:
                _LOGGER.debug("HomeKit: Reconnect attempt %d failed", backoff_idx + 1, exc_info=True)

            backoff_idx += 1

    async def async_pair(
        self,
        pin: str,
        bridge_hkid: str | None = None,
    ) -> dict[str, Any]:
        """Pair with a Tado bridge via two-step HomeKit flow.

        Args:
            pin: HomeKit PIN (format: XXX-XX-XXX).
            bridge_hkid: Bridge HomeKit Device ID. If None, discovers first available.

        Returns:
            Pairing data dict (to be stored).

        Raises:
            Exception: On pairing failure (wrong PIN, already paired, network error).
        """
        controller = await self._ensure_controller()

        if bridge_hkid is None:
            # Discover bridge — find first unpaired Tado device
            from aiohomekit.model.status_flags import StatusFlags

            async for discovery in controller.async_discover():
                if discovery.description.status_flags & StatusFlags.UNPAIRED:
                    bridge_hkid = discovery.description.id
                    _LOGGER.info("HomeKit: Found unpaired bridge: %s", bridge_hkid)
                    break

            if bridge_hkid is None:
                msg = "No unpaired HomeKit bridge found on the network"
                raise RuntimeError(msg)

        discovery = await controller.async_find(bridge_hkid)
        alias = f"tado_ce_{self._home_id}"
        finish_pairing = await discovery.async_start_pairing(alias)
        pairing = await finish_pairing(pin)

        # Store pairing credentials
        pairing_data = dict(pairing._pairing_data)
        await self._store.async_save(pairing_data)

        self._pairing = pairing
        self._is_connected = True
        self._last_connected = dt_util.utcnow().isoformat()
        _LOGGER.info("HomeKit: Pairing successful (home %s)", self._home_id)

        return pairing_data

    async def async_unpair(self) -> None:
        """Remove pairing and delete stored credentials."""
        if self._pairing:
            try:
                pairing_id = self._pairing._pairing_data.get("iOSPairingId", "")
                if pairing_id:
                    await self._pairing.remove_pairing(pairing_id)
                    _LOGGER.info("HomeKit: Removed pairing from bridge")
            except Exception:
                _LOGGER.warning("HomeKit: Failed to remove pairing from bridge", exc_info=True)
            finally:
                await self.async_disconnect()

        # Delete stored credentials
        await self._store.async_remove()
        _LOGGER.info("HomeKit: Deleted pairing credentials")

        # Delete device mapping
        from .homekit_mapping import remove_device_mapping

        await remove_device_mapping(self._hass, self._home_id)

    async def async_list_accessories(self) -> list[dict[str, Any]]:
        """List all accessories from the paired bridge.

        Returns:
            List of accessory dicts with services and characteristics.
        """
        if not self._pairing:
            return []
        try:
            result = await self._pairing.list_accessories_and_characteristics()
            if isinstance(result, list):
                _LOGGER.debug("HomeKit: Listed %d accessories", len(result))
                return result
            return []
        except Exception:
            _LOGGER.debug("HomeKit: Failed to list accessories", exc_info=True)
            return []


# ---------------------------------------------------------------------------
# Config flow pairing steps (delegated from config_flow_options.py)
# ---------------------------------------------------------------------------


async def async_step_homekit_pairing(
    flow: TadoCEOptionsFlow,
    user_input: dict[str, Any] | None = None,
) -> ConfigFlowResult:
    """Handle HomeKit pairing sub-step.

    First call: show PIN form.
    Second call (with PIN): attempt pairing, build mapping, save.
    """
    from homeassistant.helpers.selector import TextSelector, TextSelectorConfig, TextSelectorType
    import voluptuous as vol

    errors: dict[str, str] = {}

    if user_input is not None:
        pin = user_input.get("homekit_pin", "").strip()
        if pin:
            try:
                from .homekit_mapping import build_serial_mapping, save_device_mapping

                home_id = flow.config_entry.data.get("home_id") or "default"
                client = HomeKitClient(flow.hass, home_id)

                await client.async_pair(pin)

                # Build serial-to-zone mapping
                accessories = await client.async_list_accessories()
                zones_info = flow.config_entry.runtime_data.data.get("zones_info") or []
                mapping = build_serial_mapping(accessories, zones_info)
                await save_device_mapping(flow.hass, home_id, mapping)

                await client.async_disconnect()

                _LOGGER.info("HomeKit: Pairing and mapping complete")

                # Save pending options
                if flow._pending_general_options:
                    return flow.async_create_entry(title="", data=flow._pending_general_options)
                return await flow.async_step_init()

            except Exception as err:
                err_str = str(err).lower()
                if "authentication" in err_str or "pin" in err_str:
                    errors["homekit_pin"] = "homekit_wrong_pin"
                elif "already paired" in err_str or "max peers" in err_str or "unavailable" in err_str:
                    errors["homekit_pin"] = "homekit_already_paired"
                elif "not found" in err_str:
                    errors["homekit_pin"] = "homekit_network_error"
                elif "timeout" in err_str:
                    errors["homekit_pin"] = "homekit_timeout"
                else:
                    errors["homekit_pin"] = "homekit_pairing_failed"
                _LOGGER.warning("HomeKit pairing failed: %s", err)
        else:
            # Empty PIN — cancel pairing, revert homekit_enabled
            if flow._pending_general_options:
                flow._pending_general_options["homekit_enabled"] = False
                return flow.async_create_entry(title="", data=flow._pending_general_options)
            return await flow.async_step_init()

    return flow.async_show_form(
        step_id="homekit_pairing",
        data_schema=vol.Schema(
            {
                vol.Required("homekit_pin"): TextSelector(
                    TextSelectorConfig(type=TextSelectorType.TEXT),
                ),
            },
        ),
        errors=errors,
    )


async def async_step_homekit_unpair(
    flow: TadoCEOptionsFlow,
    user_input: dict[str, Any] | None = None,
) -> ConfigFlowResult:
    """Handle HomeKit unpairing sub-step.

    First call: show confirmation.
    Second call: unpair and delete credentials.
    """
    import voluptuous as vol

    if user_input is not None:
        try:
            home_id = flow.config_entry.data.get("home_id") or "default"
            client = HomeKitClient(flow.hass, home_id)

            # Try to connect first so we can remove pairing from bridge
            await client.async_connect()
            await client.async_unpair()

            _LOGGER.info("HomeKit: Unpaired successfully")
        except Exception:
            _LOGGER.warning("HomeKit: Unpair encountered errors", exc_info=True)

        # Disable homekit_enabled in options and schedule entity cleanup
        new_options = dict(flow.config_entry.options)
        new_options["homekit_enabled"] = False

        # Set cleanup flag so entities get removed on reload
        coordinator = flow.config_entry.runtime_data
        if coordinator and hasattr(coordinator, "_pending_cleanup"):
            coordinator._pending_cleanup.setdefault(flow.config_entry.entry_id, {})["_cleanup_homekit"] = True

        return flow.async_create_entry(title="", data=new_options)

    return flow.async_show_form(
        step_id="homekit_unpair",
        data_schema=vol.Schema({}),
    )
