"""Tado CE service registration and handlers — custom HA service actions."""

from __future__ import annotations

import functools
import logging
from typing import TYPE_CHECKING, Any

from homeassistant.exceptions import HomeAssistantError
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.entity_platform import async_get_platforms
import voluptuous as vol

from . import ratelimit as _ratelimit
from .const import (
    DOMAIN,
    OPEN_WINDOW_DEFAULT_TEMP,
    OPEN_WINDOW_DEFAULT_TIMEOUT,
    SERVICE_ACTIVATE_OPEN_WINDOW,
    SERVICE_ADD_METER_READING,
    SERVICE_DEACTIVATE_OPEN_WINDOW,
    SERVICE_GET_TEMP_OFFSET,
    SERVICE_IDENTIFY_DEVICE,
    SERVICE_RESTORE_PREVIOUS_STATE,
    SERVICE_RESUME_SCHEDULE,
    SERVICE_SET_AWAY_CONFIG,
    SERVICE_SET_CLIMATE_TIMER,
    SERVICE_SET_OPEN_WINDOW_MODE,
    SERVICE_SET_TEMP_OFFSET,
    SERVICE_SET_WATER_HEATER_TIMER,
)
from .helpers import async_trigger_immediate_refresh, build_timer_termination, mask_serial

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant, ServiceCall

    from .coordinator import TadoDataUpdateCoordinator
    from .data_loader import DataLoader
    from .state_restore_manager import CapturedState

_LOGGER = logging.getLogger(__name__)

# Timer validation constants
TIMER_PARTS_COUNT = 3  # HH:MM:SS format
MAX_TIMER_HOURS = 24
MAX_TIMER_MINUTES = 59
MAX_TIMER_SECONDS = 59
MAX_TIMER_DURATION_MINUTES = 1440  # 24 hours in minutes

# Water heater temperature bounds (°C)
WATER_HEATER_MIN_TEMP = 30
WATER_HEATER_MAX_TEMP = 80
















def _raise_service_error(
    translation_key: str,
    **placeholders: object,
) -> None:
    """Raise a HomeAssistantError with the standard translation scheme.

    Keeps service handlers concise and ensures consistent translation
    domain. Use for user-facing service failures that should surface in
    the HA UI as an error toast.
    """
    raise HomeAssistantError(
        translation_domain=DOMAIN,
        translation_key=translation_key,
        translation_placeholders={k: str(v) for k, v in placeholders.items()},
    )


def _find_entity_by_id(
    hass: HomeAssistant,
    platform_domain: str,
    entity_id: str,
) -> object | None:
    """Find an entity instance by entity_id using entity platforms.

    Uses async_get_platforms (public HA API) instead of internal
    hass.data['entity_components'] dict.

    Args:
        hass: Home Assistant instance.
        platform_domain: Platform domain to search (e.g. 'climate', 'water_heater').
        entity_id: The entity_id to find.

    Returns:
        The entity instance, or None if not found.
    """
    for platform in async_get_platforms(hass, DOMAIN):
        if platform.domain == platform_domain:
            for ent in platform.entities.values():
                if ent.entity_id == entity_id:
                    return ent
    return None


def _get_zone_device_serial(zone_id: str, data_loader: DataLoader | None = None) -> str | None:
    """Get the first device serial for a zone.

    Args:
        zone_id: Zone ID to look up
        data_loader: DataLoader instance for per-entry file access

    Returns:
        Device serial number, or None if not found
    """
    try:
        if data_loader is None:
            return None
        zones_info = data_loader.load_zones_info_file()
        if not zones_info:
            return None

        for zone in zones_info:
            if str(zone.get("id")) == zone_id:
                # Tado API may return null for 'devices'; 'or []' handles None correctly
                for device in zone.get("devices") or []:
                    serial = device.get("shortSerialNo")
                    if serial:
                        return serial  # type: ignore[no-any-return]
        return None
    except (AttributeError, TypeError, KeyError, OSError) as e:
        # AttributeError/TypeError/KeyError: malformed zones_info structure.
        # OSError: load_zones_info_file disk read failure.
        _LOGGER.warning("Failed to get device serial for zone %s: %s", zone_id, e)
        return None


def _get_zone_device_serials(zone_id: str, data_loader: DataLoader | None = None) -> list[str]:
    """Get ALL device serials for a zone.

    Used for operations that need to apply to all devices in a zone
    (e.g., setting temperature offset on multiple TRVs).

    Args:
        zone_id: Zone ID to look up
        data_loader: DataLoader instance for per-entry file access

    Returns:
        List of device serial numbers (may be empty)
    """
    serials = []
    try:
        if data_loader is None:
            return []
        zones_info = data_loader.load_zones_info_file()
        if not zones_info:
            return []

        for zone in zones_info:
            if str(zone.get("id")) == zone_id:
                for device in zone.get("devices") or []:
                    serial = device.get("shortSerialNo")
                    if serial:
                        serials.append(serial)
                break
        return serials
    except (AttributeError, TypeError, KeyError, OSError) as e:
        # Narrow catch — see _get_zone_device_serial for rationale
        _LOGGER.warning("Failed to get device serials for zone %s: %s", zone_id, e)
        return []


def _expand_group_entity_ids(
    hass: HomeAssistant, entity_ids: list[Any], allowed_domains: list[Any] | None = None,
) -> list[Any]:
    """Expand group entity IDs to individual entity IDs.

    Args:
        hass: Home Assistant instance
        entity_ids: List of entity IDs (may include group.* entities)
        allowed_domains: Optional list of domains to filter (e.g., ["climate", "water_heater"])

    Returns:
        List of expanded entity IDs with groups replaced by their members
    """
    expanded_ids = []
    for entity_id in entity_ids:
        if entity_id.startswith("group."):
            # Get group members from state attributes
            group_state = hass.states.get(entity_id)
            if group_state and "entity_id" in group_state.attributes:
                group_members = group_state.attributes["entity_id"]
                # Filter by allowed domains if specified
                if allowed_domains:
                    group_members = [eid for eid in group_members if eid.split(".")[0] in allowed_domains]
                expanded_ids.extend(group_members)
                _LOGGER.debug("Expanded group %s to %s entities", entity_id, len(group_members))
            else:
                _LOGGER.warning("Group %s not found or has no members", entity_id)
        else:
            # Filter by allowed domains if specified
            if allowed_domains:
                domain = entity_id.split(".")[0]
                if domain not in allowed_domains:
                    _LOGGER.debug("Skipping %s - not in allowed domains %s", entity_id, allowed_domains)
                    continue
            expanded_ids.append(entity_id)
    return expanded_ids


def _resolve_coordinator(hass: HomeAssistant, entity_id: str) -> TadoDataUpdateCoordinator:
    """Resolve TadoDataUpdateCoordinator for a service call using the HA entity registry.

    Uses entry.runtime_data instead of hass.data[DOMAIN].

    Args:
        hass: Home Assistant instance
        entity_id: Entity ID to resolve (e.g., "climate.tado_ce_living_room")

    Returns:
        TadoDataUpdateCoordinator instance for the entity's config entry

    Raises:
        HomeAssistantError: If entity not found, not a Tado CE entity,
            or config entry not loaded
    """
    from homeassistant.helpers import entity_registry as er

    registry = er.async_get(hass)
    entity_entry = registry.async_get(entity_id)

    if entity_entry is None:
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="entity_not_found",
            translation_placeholders={"entity_id": entity_id},
        )

    if entity_entry.platform != DOMAIN:
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="entity_not_tado_ce",
            translation_placeholders={"entity_id": entity_id, "platform": entity_entry.platform},
        )

    config_entry_id = entity_entry.config_entry_id
    if config_entry_id is None:
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="entity_no_config_entry",
            translation_placeholders={"entity_id": entity_id},
        )

    config_entry = hass.config_entries.async_get_entry(config_entry_id)
    if config_entry is None or not hasattr(config_entry, "runtime_data") or config_entry.runtime_data is None:
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="entry_not_loaded",
            translation_placeholders={"entity_id": entity_id, "config_entry_id": config_entry_id},
        )

    coordinator = config_entry.runtime_data
    _LOGGER.debug(
        "Resolved %s -> entry=%s (home_id=%s)",
        entity_id,
        config_entry_id,
        coordinator.home_id,
    )
    return coordinator  # type: ignore[no-any-return]


def _resolve_coordinator_for_device(hass: HomeAssistant, device_serial: str) -> TadoDataUpdateCoordinator:
    """Resolve TadoDataUpdateCoordinator for a device serial using the HA device registry.

    Uses entry.runtime_data instead of hass.data[DOMAIN].

    Args:
        hass: Home Assistant instance
        device_serial: Device serial number (e.g., "VA1234567890")

    Returns:
        TadoDataUpdateCoordinator instance for the device's config entry

    Raises:
        HomeAssistantError: If device not found or config entry not loaded
    """
    from homeassistant.helpers import device_registry as dr

    device_registry = dr.async_get(hass)

    # Search for device by serial in identifiers
    for device in device_registry.devices.values():
        for domain, identifier in device.identifiers:
            if domain == DOMAIN and identifier == device_serial:
                # Found the device — get its config entry
                for config_entry_id in device.config_entries:
                    config_entry = hass.config_entries.async_get_entry(config_entry_id)
                    if (
                        config_entry is not None
                        and hasattr(config_entry, "runtime_data")
                        and config_entry.runtime_data is not None
                    ):
                        coordinator = config_entry.runtime_data
                        _LOGGER.debug(
                            "Resolved device %s -> entry=%s (home_id=%s)",
                            device_serial,
                            config_entry_id,
                            coordinator.home_id,
                        )
                        return coordinator  # type: ignore[no-any-return]

                raise HomeAssistantError(
                    translation_domain=DOMAIN,
                    translation_key="device_entry_not_loaded",
                    translation_placeholders={"device_serial": device_serial},
                )

    raise HomeAssistantError(
        translation_domain=DOMAIN,
        translation_key="device_not_found",
        translation_placeholders={"device_serial": device_serial},
    )


def _resolve_single_coordinator(hass: HomeAssistant) -> TadoDataUpdateCoordinator:
    """Resolve coordinator when there is exactly one Tado CE config entry.

    Uses entry.runtime_data instead of hass.data[DOMAIN].

    For home-level services (add_meter_reading) that don't have an entity_id
    or device_serial to route with. If only one entry exists, returns it.
    If multiple entries exist, raises an error asking the user to specify.

    Returns:
        TadoDataUpdateCoordinator instance for the single config entry

    Raises:
        HomeAssistantError: If no entries or multiple entries exist
    """
    entries = hass.config_entries.async_entries(DOMAIN)
    loaded = [e for e in entries if hasattr(e, "runtime_data") and e.runtime_data is not None]

    if len(loaded) == 0:
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="no_entries_loaded",
        )

    if len(loaded) == 1:
        coordinator = loaded[0].runtime_data
        _LOGGER.debug(
            "Single entry resolved (home_id=%s)",
            coordinator.home_id,
        )
        return coordinator  # type: ignore[no-any-return]

    # Multiple entries — list home_ids to help user
    home_ids = [e.runtime_data.home_id for e in loaded]
    raise HomeAssistantError(
        translation_domain=DOMAIN,
        translation_key="multiple_entries",
        translation_placeholders={"home_ids": ", ".join(home_ids)},
    )


def _build_setting_from_captured(
    captured: CapturedState,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Rebuild API setting and termination dicts from captured state.

    Returns a (setting, termination) tuple suitable for ``set_zone_overlay``.
    """
    setting: dict[str, Any] = {}

    if captured.entity_type in ("climate_heating", "climate_ac"):
        setting["type"] = (
            "HEATING" if captured.entity_type == "climate_heating" else "AIR_CONDITIONING"
        )
        setting["power"] = captured.power or "ON"
        if captured.entity_type == "climate_ac" and captured.hvac_mode is not None:
            setting["mode"] = captured.hvac_mode  # Raw API mode: COOL/HEAT/DRY/FAN
        if captured.temperature is not None:
            setting["temperature"] = {"celsius": captured.temperature}
        if captured.fan_mode is not None:  # AC only
            setting["fanLevel"] = captured.fan_mode
        if captured.swing_mode is not None:  # AC only
            setting["verticalSwing"] = captured.swing_mode
        if captured.horizontal_swing_mode is not None:  # AC only
            setting["horizontalSwing"] = captured.horizontal_swing_mode

    elif captured.entity_type == "water_heater":
        setting["type"] = "HOT_WATER"
        setting["power"] = captured.power or "ON"
        if captured.temperature is not None:
            setting["temperature"] = {"celsius": captured.temperature}

    # Termination: use captured termination or fall back to MANUAL
    termination: dict[str, Any] = captured.termination or {"type": "MANUAL"}

    return setting, termination


def _parse_time_period(time_period: Any) -> int:
    """Parse time_period to duration in minutes.

    Accepts timedelta or HH:MM:SS string format.
    Returns duration in minutes (1-1440).

    Raises ValueError on invalid input.
    """
    from datetime import timedelta

    if isinstance(time_period, timedelta):
        duration_minutes = int(time_period.total_seconds() / 60)
    else:
        time_parts = str(time_period).split(":")
        if len(time_parts) != TIMER_PARTS_COUNT:
            msg = f"Invalid time_period format: {time_period}. Expected HH:MM:SS"
            raise ValueError(msg)

        hours = int(time_parts[0])
        minutes = int(time_parts[1])
        seconds = int(time_parts[2])

        if not (0 <= hours <= MAX_TIMER_HOURS):
            msg = f"Hours must be 0-24, got {hours}"
            raise ValueError(msg)
        if not (0 <= minutes <= MAX_TIMER_MINUTES):
            msg = f"Minutes must be 0-59, got {minutes}"
            raise ValueError(msg)
        if not (0 <= seconds <= MAX_TIMER_SECONDS):
            msg = f"Seconds must be 0-59, got {seconds}"
            raise ValueError(msg)

        duration_minutes = hours * 60 + minutes + (seconds // 60)

    if duration_minutes < 1:
        msg = f"Duration must be at least 1 minute, got {duration_minutes}"
        raise ValueError(msg)
    if duration_minutes > MAX_TIMER_DURATION_MINUTES:
        msg = f"Duration must be at most 1440 minutes (24 hours), got {duration_minutes}"
        raise ValueError(msg)

    return duration_minutes


async def _check_bootstrap_reserve(hass: HomeAssistant, entity_ids: list[str]) -> TadoDataUpdateCoordinator | None:
    """Check bootstrap reserve for the first entity's coordinator. Returns coordinator."""
    if not entity_ids:
        return None
    try:
        _coord = _resolve_coordinator(hass, entity_ids[0])
        should_block, reason = await _ratelimit.async_check_bootstrap_reserve(hass, coordinator=_coord)
        if should_block:
            await _ratelimit.async_show_api_limit_notification(hass, reason)
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="api_quota_critically_low",
            )
        return _coord
    except HomeAssistantError:
        raise
    except Exception as err:
        # Advisory check — on failure the service proceeds without the
        # quota guard. Bump to WARNING so operators can see when the guard
        # fails; previously DEBUG made this invisible.
        _LOGGER.warning(
            "API quota reserve check failed — proceeding without the safety "
            "check for this call: %s", err,
        )
    return None


def _validate_timer_params(
    call: ServiceCall,
) -> tuple[float, int | None, str | None]:
    """Validate and parse set_climate_timer / set_water_heater_timer params.

    Returns (temperature, duration_minutes, overlay).
    """
    temperature = call.data.get("temperature")
    time_period = call.data.get("time_period")
    overlay = call.data.get("overlay")

    duration_minutes = None
    if time_period:
        try:
            duration_minutes = _parse_time_period(time_period)
            _LOGGER.info("Parsed time_period %s to %s minutes", time_period, duration_minutes)
        except (ValueError, AttributeError, TypeError) as e:
            error_msg = f"Failed to parse time_period: {e}"
            _LOGGER.exception(error_msg)
            raise vol.Invalid(error_msg) from e
    elif not overlay:
        error_msg = "Either time_period or overlay is required"
        _LOGGER.error(error_msg)
        raise vol.Invalid(error_msg)

    if temperature is None:
        error_msg = "temperature is required"
        _LOGGER.error(error_msg)
        raise vol.Invalid(error_msg)

    return temperature, duration_minutes, overlay


async def _execute_timer_on_entity(
    hass: HomeAssistant,
    coord: TadoDataUpdateCoordinator | None,
    entity_id: str,
    domain: str,
    temperature: float,
    duration_minutes: int | None,
    overlay: str | None,
) -> bool:
    """Execute async_set_timer on a single entity with state capture.

    Returns the bool from ``ent.async_set_timer`` — False means the API
    call failed (timeout / HTTP error swallowed by the entity). Returns
    False when entity lookup fails. Network errors and HomeAssistantError
    propagate — they affect the whole group call, not just this entity.
    """
    ent = _find_entity_by_id(hass, domain, entity_id)
    if not ent or not hasattr(ent, "async_set_timer"):
        return False
    zone_id = ent.zone_id  # type: ignore[attr-defined]
    entity_type = ent.entity_type  # type: ignore[attr-defined]
    if zone_id and coord:
        await coord.async_capture_state(zone_id, entity_type, "set_timer")
    success = await ent.async_set_timer(temperature, duration_minutes, overlay)
    if success:
        if duration_minutes:
            _LOGGER.info("Set timer for %s: %s°C for %smin", entity_id, temperature, duration_minutes)
        elif overlay:
            _LOGGER.info("Set timer for %s: %s°C with overlay=%s", entity_id, temperature, overlay)
    return bool(success)


async def handle_set_climate_timer(hass: HomeAssistant, call: ServiceCall) -> None:
    """Handle set_climate_timer service call.

    Compatible with official Tado integration format:
    - entity_id (required)
    - temperature (required)
    - time_period (required) - Time Period format (e.g., "01:30:00")
    - overlay (optional)
    """
    entity_ids = call.data.get("entity_id", [])
    if isinstance(entity_ids, str):
        entity_ids = [entity_ids]
    entity_ids = _expand_group_entity_ids(hass, entity_ids, allowed_domains=["climate"])

    coord = await _check_bootstrap_reserve(hass, entity_ids)
    temperature, duration_minutes, overlay = _validate_timer_params(call)

    # Group partial-failure pattern: 0 succeed → raise, partial → warn.
    # Network errors propagate (affect the whole group, stop immediately).
    failures: list[tuple[str, str]] = []  # (entity_id, reason)
    success_count = 0
    total = 0
    for entity_id in entity_ids:
        if not hass.states.get(entity_id):
            continue
        total += 1
        try:
            if await _execute_timer_on_entity(
                hass, coord, entity_id, "climate", temperature, duration_minutes, overlay,
            ):
                success_count += 1
            else:
                # async_set_timer returned False — entity swallowed an API
                # timeout / error. Record as a failure so the group-level
                # raise surfaces it to the UI.
                failures.append((entity_id, "API call failed"))
        except (ValueError, TypeError, KeyError, AttributeError) as e:
            # Per-entity data error — don't abort the whole group
            _LOGGER.warning("Timer failed for %s: %s", entity_id, e)
            failures.append((entity_id, str(e)))
        # HomeAssistantError, aiohttp.ClientError, TimeoutError propagate

    if total > 0 and success_count == 0:
        _raise_service_error(
            "timer_set_failed_all",
            entity_count=total,
            reasons=", ".join(f"{eid}: {reason}" for eid, reason in failures[:3]),
        )
    elif failures:
        _LOGGER.warning(
            "Timer set for %s of %s zones; failed: %s",
            success_count, total, ", ".join(eid for eid, _ in failures),
        )


def _validate_water_heater_timer_params(
    call: ServiceCall,
) -> tuple[int, float | None]:
    """Validate set_water_heater_timer params. Returns (duration_minutes, temperature)."""
    time_period = call.data.get("time_period")
    temperature = call.data.get("temperature")

    if not time_period:
        error_msg = "time_period is required for set_water_heater_timer service"
        _LOGGER.error(error_msg)
        raise vol.Invalid(error_msg)

    try:
        duration_minutes = _parse_time_period(time_period)
        _LOGGER.info("Parsed time_period %s to %s minutes", time_period, duration_minutes)
    except (ValueError, AttributeError, TypeError) as e:
        error_msg = f"Failed to parse time_period: {e}"
        _LOGGER.exception(error_msg)
        raise vol.Invalid(error_msg) from e

    if temperature is not None:
        if not (WATER_HEATER_MIN_TEMP <= temperature <= WATER_HEATER_MAX_TEMP):
            error_msg = f"Temperature must be 30-80°C, got {temperature}"
            _LOGGER.error(error_msg)
            raise vol.Invalid(error_msg)

    return duration_minutes, temperature


async def handle_set_water_heater_timer(hass: HomeAssistant, call: ServiceCall) -> None:
    """Handle set_water_heater_timer service call."""
    entity_ids = call.data.get("entity_id", [])
    if isinstance(entity_ids, str):
        entity_ids = [entity_ids]
    entity_ids = _expand_group_entity_ids(hass, entity_ids, allowed_domains=["water_heater"])

    await _check_bootstrap_reserve(hass, entity_ids)
    duration_minutes, temperature = _validate_water_heater_timer_params(call)

    failures: list[tuple[str, str]] = []
    success_count = 0
    total = 0
    for entity_id in entity_ids:
        ent = _find_entity_by_id(hass, "water_heater", entity_id)
        if not ent or not hasattr(ent, "async_set_timer"):
            continue
        total += 1
        try:
            zone_id = ent.zone_id  # type: ignore[attr-defined]
            if zone_id:
                try:
                    wh_coord = _resolve_coordinator(hass, entity_id)
                    await wh_coord.async_capture_state(zone_id, "water_heater", "set_timer")
                except HomeAssistantError:
                    _LOGGER.debug("State capture skipped for %s", entity_id)
            success = await ent.async_set_timer(duration_minutes, temperature)
            if success:
                _LOGGER.info("Set timer for %s: %smin", entity_id, duration_minutes)
                success_count += 1
            else:
                # Entity swallowed a timeout / API error and returned False
                failures.append((entity_id, "API call failed"))
        except (ValueError, TypeError, KeyError, AttributeError) as e:
            _LOGGER.warning("Water heater timer failed for %s: %s", entity_id, e)
            failures.append((entity_id, str(e)))
        # HomeAssistantError / network errors propagate

    if total > 0 and success_count == 0:
        _raise_service_error(
            "timer_set_failed_all",
            entity_count=total,
            reasons=", ".join(f"{eid}: {reason}" for eid, reason in failures[:3]),
        )
    elif failures:
        _LOGGER.warning(
            "Water heater timer set for %s of %s; failed: %s",
            success_count, total, ", ".join(eid for eid, _ in failures),
        )


async def handle_resume_schedule(hass: HomeAssistant, call: ServiceCall) -> None:
    """Handle resume_schedule service call."""
    entity_ids = call.data.get("entity_id", [])
    if isinstance(entity_ids, str):
        entity_ids = [entity_ids]

    # Expand groups to individual entity IDs
    entity_ids = _expand_group_entity_ids(hass, entity_ids, allowed_domains=["climate", "water_heater"])

    for entity_id in entity_ids:
        # Resolve per-entry API client
        try:
            _coord = _resolve_coordinator(hass, entity_id)
        except HomeAssistantError:
            _LOGGER.exception("resume_schedule")
            continue

        should_block, reason = await _ratelimit.async_check_bootstrap_reserve(hass, coordinator=_coord)
        if should_block:
            await _ratelimit.async_show_api_limit_notification(hass, reason)
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="api_quota_critically_low",
            )

        domain = entity_id.split(".")[0]
        ent = _find_entity_by_id(hass, domain, entity_id)
        if ent:
            zone_id = ent.zone_id  # type: ignore[attr-defined]
            if zone_id:
                await _coord.api_client.delete_zone_overlay(zone_id)
                _LOGGER.info("Resumed schedule for %s", entity_id)
                await async_trigger_immediate_refresh(hass, entity_id, "resume_schedule")


async def handle_set_temp_offset(hass: HomeAssistant, call: ServiceCall) -> None:
    """Handle set_temperature_offset service call.

    Sets temperature offset for ALL devices in a zone (supports multi-TRV rooms).
    Per-entry API client and data_loader routing.
    """
    entity_id = call.data.get("entity_id")
    offset = call.data.get("offset")

    # Resolve per-entry data
    _coord = _resolve_coordinator(hass, entity_id)  # type: ignore[arg-type]

    should_block, reason = await _ratelimit.async_check_bootstrap_reserve(hass, coordinator=_coord)
    if should_block:
        await _ratelimit.async_show_api_limit_notification(hass, reason)
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="api_quota_critically_low",
        )

    # Get zone_id from entity and find ALL device serials
    ent = _find_entity_by_id(hass, "climate", entity_id)  # type: ignore[arg-type]
    if ent:
        zone_id = ent.zone_id  # type: ignore[attr-defined]
        if zone_id:
            # Find ALL device serials for this zone (multi-TRV support)
            # Use per-entry data_loader
            serials = await hass.async_add_executor_job(
                _get_zone_device_serials,
                zone_id,
                _coord.data_loader,
            )
            if serials:
                # Track per-device write success so we can distinguish
                # partial, total, and clean success cases.
                success_count = 0
                for serial in serials:
                    if await _coord.api_client.set_device_offset(serial, offset):  # type: ignore[arg-type]
                        success_count += 1

                if success_count == 0:
                    # Every write failed — do NOT update cache or notify
                    # the sync controller. The user must see the failure
                    # so they can retry or investigate.
                    _LOGGER.error(
                        "Set offset failed for all %s device(s) in %s",
                        len(serials), entity_id,
                    )
                    raise HomeAssistantError(
                        translation_domain=DOMAIN,
                        translation_key="offset_write_failed",
                        translation_placeholders={
                            "entity_id": str(entity_id),
                            "device_count": str(len(serials)),
                        },
                    )

                _LOGGER.info(
                    "Set offset %s°C for %s (%s/%s device(s))",
                    offset, entity_id, success_count, len(serials),
                )
                if success_count < len(serials):
                    _LOGGER.warning(
                        "Partial offset write for %s: %s of %s devices failed — "
                        "cache will reflect readback from first device",
                        entity_id, len(serials) - success_count, len(serials),
                    )

                # Read back the actual offset from the API (ground truth)
                # instead of caching the user-supplied value (#221).
                # This prevents automation feedback loops where offset_celsius
                # reflects the automation's last write rather than the device's
                # actual state.
                readback = await _coord.api_client.get_device_offset(serials[0])
                cache_value: float | None = readback if readback is not None else offset

                # Sanity check before caching (#221)
                from .const import is_valid_device_offset

                if not is_valid_device_offset(cache_value):
                    _LOGGER.warning(
                        "Offset readback for zone %s rejected: %s°C outside valid range",
                        zone_id, cache_value,
                    )
                else:
                    cached_offsets = _coord.data_loader.get_cached("offsets")
                    if cached_offsets is None:
                        cached_offsets = {}
                    cached_offsets[zone_id] = cache_value
                    _coord.data_loader.update_cache("offsets", cached_offsets)
                    await _coord.data_loader.async_update_store("offsets", cached_offsets)

                    if _coord.data and isinstance(_coord.data, dict):
                        _coord.data["offsets"] = cached_offsets

                    _LOGGER.debug("Updated offsets cache for zone %s: %s°C (readback)", zone_id, cache_value)

                # Notify offset sync controller BEFORE triggering refresh, so
                # the pause window is in effect when the refresh-triggered
                # evaluate runs. Otherwise the controller could fire an
                # evaluation against the freshly-cached value and write a
                # counter-correction that fights the service caller.
                if zone_id in _coord.offset_sync_controllers:
                    _coord.offset_sync_controllers[zone_id].on_external_offset_write()

                # Warn when Smart Valve Control (valve_target mode) is
                # running with a non-zero offset — offsets cause double
                # compensation because TRV sensorDataPoints.insideTemperature
                # is offset-adjusted, and SVC adds its own compensation on top.
                if (
                    zone_id in _coord.valve_controllers
                    and offset is not None
                    and abs(float(offset)) >= 0.1
                ):
                    _LOGGER.warning(
                        "Smart Valve Control is active for zone %s and the "
                        "device offset was just set to %.1f°C — this will "
                        "cause double compensation. Reset the offset to 0 "
                        "for accurate Smart Valve Control.",
                        zone_id, float(offset),
                    )

                # Trigger a coordinator refresh so entities pick up the change
                await _coord.async_request_refresh()
            else:
                _LOGGER.warning("No devices found for %s", entity_id)


async def handle_add_meter_reading(hass: HomeAssistant, call: ServiceCall) -> None:
    """Handle add_meter_reading service call (fully async).

    Per-entry routing via _resolve_single_coordinator.
    """
    # Resolve entry — no entity_id, use single-entry implicit routing
    _coord = _resolve_single_coordinator(hass)

    should_block, reason = await _ratelimit.async_check_bootstrap_reserve(hass, coordinator=_coord)
    if should_block:
        await _ratelimit.async_show_api_limit_notification(hass, reason)
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="api_quota_critically_low",
        )

    reading = call.data.get("reading")
    date = call.data.get("date")

    success = await _coord.api_client.add_meter_reading(reading, date)  # type: ignore[arg-type]

    if not success:
        _LOGGER.error("Failed to add meter reading: %s", reading)


async def handle_identify_device(hass: HomeAssistant, call: ServiceCall) -> None:
    """Handle identify_device service call (fully async).

    Per-entry routing via _resolve_coordinator_for_device.
    """
    device_serial = call.data.get("device_serial")

    # Resolve entry via device registry lookup
    _coord = _resolve_coordinator_for_device(hass, device_serial)  # type: ignore[arg-type]

    should_block, reason = await _ratelimit.async_check_bootstrap_reserve(hass, coordinator=_coord)
    if should_block:
        await _ratelimit.async_show_api_limit_notification(hass, reason)
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="api_quota_critically_low",
        )

    success = await _coord.api_client.identify_device(device_serial)  # type: ignore[arg-type]

    if not success:
        _LOGGER.error("Failed to identify device: %s", mask_serial(device_serial or ""))


async def handle_set_away_config(hass: HomeAssistant, call: ServiceCall) -> None:
    """Handle set_away_configuration service call (fully async)."""
    entity_id = call.data.get("entity_id")
    mode = call.data.get("mode")
    temperature = call.data.get("temperature")
    comfort_level = call.data.get("comfort_level", 50)

    # Resolve per-entry data
    _coord = _resolve_coordinator(hass, entity_id)  # type: ignore[arg-type]

    should_block, reason = await _ratelimit.async_check_bootstrap_reserve(hass, coordinator=_coord)
    if should_block:
        await _ratelimit.async_show_api_limit_notification(hass, reason)
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="api_quota_critically_low",
        )

    # Get zone_id from entity
    ent = _find_entity_by_id(hass, "climate", entity_id)  # type: ignore[arg-type]
    if ent:
        zone_id = ent.zone_id  # type: ignore[attr-defined]
        if zone_id:
            success = await _coord.api_client.set_away_configuration(
                zone_id,
                mode,  # type: ignore[arg-type]
                temperature,
                comfort_level,
            )
            if success:
                await async_trigger_immediate_refresh(hass, entity_id, "set_away_config")  # type: ignore[arg-type]
            elif not success:
                _LOGGER.error("Failed to set away config for %s", entity_id)


async def handle_activate_open_window(hass: HomeAssistant, call: ServiceCall) -> None:
    """Handle activate_open_window service call.

    Activates open window mode on climate zones (same as tapping the icon in the Tado app).
    """
    entity_ids = call.data.get("entity_id", [])
    if isinstance(entity_ids, str):
        entity_ids = [entity_ids]

    # Expand groups to individual entity IDs
    entity_ids = _expand_group_entity_ids(hass, entity_ids, allowed_domains=["climate"])

    for entity_id in entity_ids:
        try:
            _coord = _resolve_coordinator(hass, entity_id)
        except HomeAssistantError:
            _LOGGER.exception("activate_open_window")
            continue

        should_block, reason = await _ratelimit.async_check_bootstrap_reserve(hass, coordinator=_coord)
        if should_block:
            await _ratelimit.async_show_api_limit_notification(hass, reason)
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="api_quota_critically_low",
            )

        ent = _find_entity_by_id(hass, "climate", entity_id)
        if ent:
            zone_id = ent.zone_id  # type: ignore[attr-defined]
            if zone_id:
                success = await _coord.api_client.activate_open_window(zone_id)
                if success:
                    _LOGGER.info("Activated open window for %s", entity_id)
                    await async_trigger_immediate_refresh(hass, entity_id, "activate_open_window")
                else:
                    _LOGGER.error("Failed to activate open window for %s", entity_id)


async def handle_deactivate_open_window(hass: HomeAssistant, call: ServiceCall) -> None:
    """Handle deactivate_open_window service call.

    Deactivates open window mode on climate zones, resuming normal heating/cooling.
    """
    entity_ids = call.data.get("entity_id", [])
    if isinstance(entity_ids, str):
        entity_ids = [entity_ids]

    # Expand groups to individual entity IDs
    entity_ids = _expand_group_entity_ids(hass, entity_ids, allowed_domains=["climate"])

    for entity_id in entity_ids:
        try:
            _coord = _resolve_coordinator(hass, entity_id)
        except HomeAssistantError:
            _LOGGER.exception("deactivate_open_window")
            continue

        should_block, reason = await _ratelimit.async_check_bootstrap_reserve(hass, coordinator=_coord)
        if should_block:
            await _ratelimit.async_show_api_limit_notification(hass, reason)
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="api_quota_critically_low",
            )

        ent = _find_entity_by_id(hass, "climate", entity_id)
        if ent:
            zone_id = ent.zone_id  # type: ignore[attr-defined]
            if zone_id:
                success = await _coord.api_client.deactivate_open_window(zone_id)
                if success:
                    _LOGGER.info("Deactivated open window for %s", entity_id)
                    await async_trigger_immediate_refresh(hass, entity_id, "deactivate_open_window")
                else:
                    _LOGGER.error("Failed to deactivate open window for %s", entity_id)


def _resolve_open_window_timeout(
    coord: TadoDataUpdateCoordinator, zone_id: str, user_duration: int | None,
) -> int:
    """Resolve open window timeout: user param > zone setting > default."""
    if user_duration is not None:
        return user_duration
    zones_info = coord.data.get("zones_info") or []
    for zone in zones_info:
        if str(zone.get("id")) == zone_id:
            owd = zone.get("openWindowDetection") or {}
            timeout = owd.get("timeoutInSeconds")
            if timeout is not None:
                return int(timeout)
            break
    return OPEN_WINDOW_DEFAULT_TIMEOUT


def _build_open_window_overlay(
    zone_type: str, timeout: int,
) -> tuple[dict[str, Any], dict[str, Any], str]:
    """Build setting and termination for open window overlay. Returns (setting, termination, desc)."""
    setting: dict[str, str | dict[str, float]] = (
        {"type": "AIR_CONDITIONING", "power": "OFF"}
        if zone_type == "AIR_CONDITIONING"
        else {"type": "HEATING", "power": "ON", "temperature": {"celsius": OPEN_WINDOW_DEFAULT_TEMP}}
    )

    if timeout == 0:
        termination: dict[str, str | int] = build_timer_termination(overlay="manual")
        duration_desc = "indefinite"
    else:
        termination = build_timer_termination(duration_minutes=int(timeout) // 60)
        duration_desc = f"{int(timeout) // 60} min"

    return setting, termination, duration_desc


async def handle_set_open_window_mode(hass: HomeAssistant, call: ServiceCall) -> None:
    """Handle set_open_window_mode service call.

    Simulates open window mode using an overlay — sets zone to frost protection
    temperature with a timer.
    """
    entity_ids = call.data.get("entity_id", [])
    if isinstance(entity_ids, str):
        entity_ids = [entity_ids]
    entity_ids = _expand_group_entity_ids(hass, entity_ids, allowed_domains=["climate"])

    duration_seconds = call.data.get("duration")
    capture_state = call.data.get("capture_state", True)

    for entity_id in entity_ids:
        try:
            _coord = _resolve_coordinator(hass, entity_id)
        except HomeAssistantError:
            _LOGGER.exception("set_open_window_mode")
            continue

        should_block, reason = await _ratelimit.async_check_bootstrap_reserve(hass, coordinator=_coord)
        if should_block:
            await _ratelimit.async_show_api_limit_notification(hass, reason)
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="api_quota_critically_low",
            )

        ent = _find_entity_by_id(hass, "climate", entity_id)
        if not ent:
            continue
        zone_id = ent.zone_id  # type: ignore[attr-defined]
        if not zone_id:
            continue

        if capture_state:
            entity_type = ent.entity_type  # type: ignore[attr-defined]
            await _coord.async_capture_state(zone_id, entity_type, "set_open_window_mode")

        timeout = _resolve_open_window_timeout(_coord, zone_id, duration_seconds)
        zone_type = ent.zone_type  # type: ignore[attr-defined]
        setting, termination, duration_desc = _build_open_window_overlay(zone_type, timeout)

        success = await _coord.api_client.set_zone_overlay(zone_id, setting, termination)
        if success:
            _LOGGER.info("Set open window mode for %s (%s, %s°C)", entity_id, duration_desc, OPEN_WINDOW_DEFAULT_TEMP)
            await async_trigger_immediate_refresh(hass, entity_id, "set_open_window_mode")
        else:
            _LOGGER.error("Failed to set open window mode for %s", entity_id)


async def handle_get_temp_offset(hass: HomeAssistant, call: ServiceCall) -> None:
    """Handle get_temperature_offset service call.

    Fetches the current temperature offset for a climate entity on-demand.
    Returns the offset value via service response for use in automations.
    Per-entry API client and data_loader routing.
    """
    entity_id = call.data.get("entity_id")

    # Resolve per-entry data
    try:
        _coord = _resolve_coordinator(hass, entity_id)  # type: ignore[arg-type]
    except HomeAssistantError as e:
        _LOGGER.exception("get_temp_offset")
        return {"offset_celsius": None, "error": str(e)}  # type: ignore[return-value]

    # Get zone_id from entity
    ent = _find_entity_by_id(hass, "climate", entity_id)  # type: ignore[arg-type]
    if ent:
        zone_id = ent.zone_id  # type: ignore[attr-defined]
        if zone_id:
            # Find device serial for this zone
            # Use per-entry data_loader
            serial = await hass.async_add_executor_job(
                _get_zone_device_serial,
                zone_id,
                _coord.data_loader,
            )
            if serial:
                result = await _coord.api_client.get_device_offset(serial)
                if result is not None:
                    return {"offset_celsius": result}  # type: ignore[return-value]

        _LOGGER.error("Failed to get offset for %s", entity_id)
        return {"offset_celsius": None, "error": "Failed to fetch offset"}  # type: ignore[return-value]

    _LOGGER.error("Entity not found: %s", entity_id)
    return {"offset_celsius": None, "error": "Entity not found"}  # type: ignore[return-value]


async def handle_restore_previous_state(hass: HomeAssistant, call: ServiceCall) -> None:
    """Handle restore_previous_state service call.

    Restore a zone to its state before the last overlay operation.
    Falls back to resume_schedule if no captured state exists.
    """
    entity_ids = call.data.get("entity_id", [])
    if isinstance(entity_ids, str):
        entity_ids = [entity_ids]

    # Expand groups to individual entity IDs
    entity_ids = _expand_group_entity_ids(hass, entity_ids, allowed_domains=["climate", "water_heater"])

    for entity_id in entity_ids:
        try:
            _coord = _resolve_coordinator(hass, entity_id)
        except HomeAssistantError:
            _LOGGER.exception("State Restore: failed to resolve coordinator for %s", entity_id)
            continue

        # Resolve entity to get zone_id and entity_type
        domain = entity_id.split(".")[0]
        ent = _find_entity_by_id(hass, domain, entity_id)
        if ent is None:
            _LOGGER.warning("State Restore: entity not found: %s", entity_id)
            continue

        zone_id = ent.zone_id  # type: ignore[attr-defined]
        entity_type = ent.entity_type  # type: ignore[attr-defined]
        if not zone_id or not entity_type:
            _LOGGER.warning(
                "State Restore: missing zone_id or entity_type for %s",
                entity_id,
            )
            continue

        # Consume captured state (null-safe — returns None when sr_manager unavailable)
        captured = await _coord.async_restore_state(zone_id, entity_type)

        if captured is None:
            # Fallback: resume schedule (delete overlay)
            await _coord.api_client.delete_zone_overlay(zone_id)
            _LOGGER.info("State Restore: no captured state for %s, resumed schedule", entity_id)
            await async_trigger_immediate_refresh(hass, entity_id, "restore_previous_state")
            continue

        if captured.overlay_type is None:
            # Was on schedule — resume schedule
            await _coord.api_client.delete_zone_overlay(zone_id)
            _LOGGER.info("State Restore: restored schedule for %s", entity_id)
            await async_trigger_immediate_refresh(hass, entity_id, "restore_previous_state")
        else:
            # Was on overlay — rebuild and re-apply
            setting, termination = _build_setting_from_captured(captured)
            await _coord.api_client.set_zone_overlay(zone_id, setting, termination)
            _LOGGER.info(
                "State Restore: restored overlay for %s (type=%s, temp=%s)",
                entity_id,
                captured.overlay_type,
                captured.temperature,
            )
            await async_trigger_immediate_refresh(hass, entity_id, "restore_previous_state")


async def _async_register_services(hass: HomeAssistant) -> None:
    """Register Tado CE services."""
    # Check if services are already registered (avoid duplicate registration)
    if hass.services.has_service(DOMAIN, SERVICE_SET_CLIMATE_TIMER):
        _LOGGER.debug("Tado CE services already registered, skipping")
        return

    # Register services
    # Use cv.entity_ids + handler expansion to support climate groups
    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_CLIMATE_TIMER,
        functools.partial(handle_set_climate_timer, hass),
        schema=vol.Schema(
            {
                vol.Required("entity_id"): cv.entity_ids,
                vol.Required("temperature"): vol.All(vol.Coerce(float), vol.Range(min=5, max=30)),
                vol.Optional("time_period"): cv.time_period,
                vol.Optional("overlay"): cv.string,
            },
        ),
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_WATER_HEATER_TIMER,
        functools.partial(handle_set_water_heater_timer, hass),
        schema=vol.Schema(
            {
                vol.Required("entity_id"): cv.entity_ids,
                vol.Required("time_period"): cv.time_period,
                vol.Optional("temperature"): vol.Coerce(float),
            },
        ),
    )

    # Use cv.entity_ids + handler expansion to support groups
    hass.services.async_register(
        DOMAIN,
        SERVICE_RESUME_SCHEDULE,
        functools.partial(handle_resume_schedule, hass),
        schema=vol.Schema(
            {
                vol.Required("entity_id"): cv.entity_ids,
            },
        ),
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_TEMP_OFFSET,
        functools.partial(handle_set_temp_offset, hass),
        schema=vol.Schema(
            {
                vol.Required("entity_id"): cv.entity_id,
                vol.Required("offset"): vol.All(vol.Coerce(float), vol.Range(min=-10.0, max=10.0)),
            },
        ),
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_ADD_METER_READING,
        functools.partial(handle_add_meter_reading, hass),
        schema=vol.Schema(
            {
                vol.Required("reading"): vol.Coerce(int),
                vol.Optional("date"): cv.string,
            },
        ),
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_IDENTIFY_DEVICE,
        functools.partial(handle_identify_device, hass),
        schema=vol.Schema(
            {
                vol.Required("device_serial"): cv.string,
            },
        ),
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_AWAY_CONFIG,
        functools.partial(handle_set_away_config, hass),
        schema=vol.Schema(
            {
                vol.Required("entity_id"): cv.entity_id,
                vol.Required("mode"): cv.string,
                vol.Optional("temperature"): vol.Coerce(float),
                vol.Optional("comfort_level"): vol.Coerce(int),
            },
        ),
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_ACTIVATE_OPEN_WINDOW,
        functools.partial(handle_activate_open_window, hass),
        schema=vol.Schema(
            {
                vol.Required("entity_id"): cv.entity_ids,
            },
        ),
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_DEACTIVATE_OPEN_WINDOW,
        functools.partial(handle_deactivate_open_window, hass),
        schema=vol.Schema(
            {
                vol.Required("entity_id"): cv.entity_ids,
            },
        ),
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_OPEN_WINDOW_MODE,
        functools.partial(handle_set_open_window_mode, hass),
        schema=vol.Schema(
            {
                vol.Required("entity_id"): cv.entity_ids,
                vol.Optional("duration"): vol.All(
                    vol.Coerce(int), vol.Any(0, vol.Range(min=60, max=3600)),
                ),
                vol.Optional("capture_state", default=True): cv.boolean,
            },
        ),
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_GET_TEMP_OFFSET,
        functools.partial(handle_get_temp_offset, hass),
        schema=vol.Schema(
            {
                vol.Required("entity_id"): cv.entity_id,
            },
        ),
        supports_response=True,  # type: ignore[arg-type]
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_RESTORE_PREVIOUS_STATE,
        functools.partial(handle_restore_previous_state, hass),
        schema=vol.Schema(
            {
                vol.Required("entity_id"): cv.entity_ids,
            },
        ),
    )

    _LOGGER.info("Tado CE: Services registered")
