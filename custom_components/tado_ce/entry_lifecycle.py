"""Tado CE entry lifecycle — per-entry component creation and cleanup."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from .helpers import mask_serial_dict

if TYPE_CHECKING:
    from collections.abc import Callable

    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

    from .config_manager import ConfigurationManager
    from .coordinator import TadoDataUpdateCoordinator
    from .data_loader import DataLoader

_LOGGER = logging.getLogger(__name__)


async def async_create_entry_components(
    hass: HomeAssistant,
    entry: ConfigEntry,
    config_manager: ConfigurationManager,
    home_id: str | None,
    data_loader: DataLoader | None = None,
) -> dict[str, Any]:
    """Create per-entry infrastructure components.

    Creates: API tracker, API client, freshness cleanup timer,
    refresh handler, and runs device cleanup.

    Returns a dict with created components for coordinator construction.
    """
    from homeassistant.helpers.aiohttp_client import async_get_clientsession

    from .api_call_tracker import APICallTracker
    from .api_client import TadoApiClient
    from .const import DATA_DIR
    # Create per-entry API call tracker
    retention_days = config_manager.get_api_history_retention_days()
    api_tracker = APICallTracker(
        hass, DATA_DIR, retention_days=retention_days, home_id=home_id, config_manager=config_manager,
    )
    await api_tracker.async_init()
    _LOGGER.debug("Tado CE: Per-entry API call tracker created")

    # Create per-entry API client
    session = async_get_clientsession(hass)
    api_client = TadoApiClient(
        session,
        hass,
        home_id=home_id,
        refresh_token=entry.data.get("refresh_token", ""),
        config_manager=config_manager,
        api_tracker=api_tracker,
        data_loader=data_loader,
        config_entry=entry,
    )
    _LOGGER.debug("Tado CE: Per-entry API client created")

    # Load version early to avoid race conditions in device_manager
    from .device_manager import load_version

    await hass.async_add_executor_job(load_version)

    # Create HomeKit client if enabled
    homekit_client = None
    if config_manager.get_homekit_enabled():
        from .homekit_client import HomeKitClient

        homekit_client = HomeKitClient(hass, home_id or "default")
        connected = await homekit_client.async_connect()
        if connected:
            _LOGGER.info("Tado CE: HomeKit connected to bridge")
            from .homekit_mapping import (
                build_serial_mapping,
                load_device_mapping,
                save_device_mapping,
                validate_mapping,
            )

            mapping = await load_device_mapping(hass, home_id or "default")
            serial_to_zone = mapping.get("serial_to_zone", {}) if mapping else {}

            # Validate cached mapping against cloud zone IDs
            if serial_to_zone and mapping:
                # Load zones_info for validation
                if data_loader:
                    zi_for_validation = await hass.async_add_executor_job(data_loader.load_zones_info_file)
                else:
                    zi_for_validation = None
                from .const import get_climate_zone_ids

                valid_ids = get_climate_zone_ids(zi_for_validation or []) if zi_for_validation else None
                if not validate_mapping(mapping, valid_zone_ids=valid_ids):
                    _LOGGER.info("Tado CE: HomeKit cached mapping invalid — rebuilding")
                    serial_to_zone = {}  # Force rebuild below

            # Rebuild mapping if empty or invalid
            if not serial_to_zone:
                _LOGGER.info("Tado CE: HomeKit mapping empty — rebuilding from accessories + cloud zones")
                accessories = await homekit_client.async_list_accessories()
                # Load zones_info from disk (coordinator not created yet)
                if data_loader:
                    zones_info = await hass.async_add_executor_job(data_loader.load_zones_info_file)
                else:
                    zones_info = []
                if accessories and zones_info:
                    mapping = build_serial_mapping(accessories, zones_info)
                    await save_device_mapping(hass, home_id or "default", mapping)
                    serial_to_zone = mapping.get("serial_to_zone", {})

            if serial_to_zone:
                homekit_client.set_zone_mapping(
                    mapping.get("serial_to_zone", {}),  # type: ignore[union-attr]
                    mapping.get("zone_to_aids", {}),  # type: ignore[union-attr]
                )
                _LOGGER.info("Tado CE: HomeKit zone mapping loaded (%d zones)", len(serial_to_zone))
                _LOGGER.debug(
                    "HomeKit: Mapping detail — serial_to_zone=%s, zone_to_aids=%s",
                    mask_serial_dict(mapping.get("serial_to_zone", {})),  # type: ignore[union-attr]
                    mapping.get("zone_to_aids", {}),  # type: ignore[union-attr]
                )

                # Log mapped vs unmapped climate zones for diagnostics
                from .const import get_climate_zone_ids

                if data_loader:
                    zi = await hass.async_add_executor_job(data_loader.load_zones_info_file)
                else:
                    zi = zones_info if "zones_info" in dir() else []
                all_climate_ids = get_climate_zone_ids(zi or [])
                mapped_ids = set(serial_to_zone.values())
                unmapped = all_climate_ids - mapped_ids
                if unmapped:
                    _LOGGER.info("HomeKit: Zones without local mapping (using cloud): %s", unmapped)
            else:
                _LOGGER.warning("Tado CE: HomeKit connected but no zone mapping — scheduling deferred rebuild")

                # Schedule one-shot retry after first coordinator refresh
                async def _deferred_homekit_rebuild(
                    coord: TadoDataUpdateCoordinator,
                    _hk_client: Any = homekit_client,
                    _hass: HomeAssistant = hass,
                    _home_id: str | None = home_id,
                ) -> None:
                    """Rebuild HomeKit mapping after first successful coordinator poll."""
                    from .homekit_mapping import build_serial_mapping, save_device_mapping

                    zi = coord.data.get("zones_info") or []
                    if not zi:
                        _LOGGER.warning("HomeKit: Deferred rebuild failed — still no zones_info")
                        return
                    accs = await _hk_client.async_list_accessories()
                    if not accs:
                        _LOGGER.warning("HomeKit: Deferred rebuild failed — no accessories")
                        return
                    new_mapping = build_serial_mapping(accs, zi)
                    s2z = new_mapping.get("serial_to_zone", {})
                    if not s2z:
                        _LOGGER.warning("HomeKit: Deferred rebuild produced empty mapping — local data unavailable")
                        return
                    _hk_client.set_zone_mapping(
                        new_mapping.get("serial_to_zone", {}),
                        new_mapping.get("zone_to_aids", {}),
                    )
                    await save_device_mapping(_hass, _home_id or "default", new_mapping)
                    _LOGGER.info("HomeKit: Deferred rebuild succeeded — %d zones mapped", len(s2z))

                return {
                    "api_tracker": api_tracker,
                    "api_client": api_client,
                    "homekit_client": homekit_client,
                    "_deferred_homekit_rebuild": _deferred_homekit_rebuild,
                }
        else:
            _LOGGER.warning("Tado CE: HomeKit connection failed, using cloud only")

    return {
        "api_tracker": api_tracker,
        "api_client": api_client,
        "homekit_client": homekit_client,
    }


async def async_cleanup_entry_components(
    hass: HomeAssistant,
    coordinator: TadoDataUpdateCoordinator | None,
) -> None:
    """Clean up per-entry infrastructure components.

    Cancels timers and cleans up managers using coordinator attributes.
    """
    if coordinator is None:
        return

    def _attr(field: str) -> Any:
        """Get field from coordinator, or None if missing."""
        return getattr(coordinator, field, None)

    # --- Cancel per-entry timers ---

    cancel_func: Callable[[], None] | None = _attr("_freshness_cleanup_cancel")
    if cancel_func:
        cancel_func()
        _LOGGER.debug("Cancelled freshness cleanup timer")

    cancel_func = _attr("_heating_cycle_timeout_cancel")
    if cancel_func:
        cancel_func()
        _LOGGER.debug("Cancelled heating cycle timeout timer")

    # --- Clean up per-entry managers ---

    ac = _attr("api_client")
    if ac is not None:
        ac._access_token = None
        ac._token_expiry = None
        coordinator.api_client = None  # type: ignore[assignment]
        _LOGGER.debug("Cleaned up per-entry TadoApiClient")

    # Save data before cleanup
    # Note: smart_comfort_cache and bridge_health use HA Store debounced save,
    # which auto-flushes on HA shutdown. Explicit saves here handle integration
    # reload (where EVENT_HOMEASSISTANT_FINAL_WRITE does not fire).
    scm = _attr("smart_comfort_manager")
    if scm is not None:
        scm.save_to_file()
        coordinator.smart_comfort_manager = None
        _LOGGER.debug("Cleaned up per-entry SmartComfortManager")

    apm = _attr("adaptive_preheat_manager")
    if apm is not None:
        await apm.async_unload()
        coordinator.adaptive_preheat_manager = None
        _LOGGER.debug("Cleaned up per-entry AdaptivePreheatManager")

    if _attr("data_loader") is not None:
        coordinator.data_loader = None  # type: ignore[assignment]
        _LOGGER.debug("Cleaned up per-entry DataLoader")

    # Clean up HomeKit client
    hkc = _attr("homekit_client")
    if hkc is not None:
        from .homekit_client import HomeKitClient

        # Unsubscribe events and stop cache refresh before disconnecting
        provider = _attr("homekit_provider")
        if provider is not None and hasattr(provider, "unsubscribe_events"):
            provider.unsubscribe_events()

        if isinstance(hkc, HomeKitClient):
            await hkc.async_disconnect()
        coordinator.homekit_client = None
        coordinator.homekit_provider = None
        coordinator.state_reconciler = None
        _LOGGER.debug("Cleaned up HomeKit client")
