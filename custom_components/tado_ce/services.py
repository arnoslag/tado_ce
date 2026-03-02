"""Tado CE service registration and handlers.

Extracted from __init__.py to reduce file size.
All service handlers for set_climate_timer, set_water_heater_timer,
resume_schedule, set_temperature_offset, get_temperature_offset,
add_meter_reading, identify_device, set_away_configuration.
"""
import logging

import voluptuous as vol

from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
import homeassistant.helpers.config_validation as cv

from .const import (
    DOMAIN,
    SERVICE_SET_CLIMATE_TIMER,
    SERVICE_SET_WATER_HEATER_TIMER,
    SERVICE_RESUME_SCHEDULE,
    SERVICE_SET_TEMP_OFFSET,
    SERVICE_GET_TEMP_OFFSET,
    SERVICE_ADD_METER_READING,
    SERVICE_IDENTIFY_DEVICE,
    SERVICE_SET_AWAY_CONFIG,
)

_LOGGER = logging.getLogger(__name__)


def _get_device_serial_for_zone(zone_id: str, data_loader=None) -> str | None:
    """Get the first device serial for a zone.

    Args:
        zone_id: Zone ID to look up
        data_loader: DataLoader instance for per-entry file access (v3.0.0 GAP-73)

    Returns:
        Device serial number, or None if not found
    """
    try:
        if data_loader is not None:
            zones_info = data_loader.load_zones_info_file()
        else:
            from .data_loader import load_zones_info_file
            zones_info = load_zones_info_file()
        if not zones_info:
            return None

        for zone in zones_info:
            if str(zone.get('id')) == zone_id:
                for device in zone.get('devices', []):
                    serial = device.get('shortSerialNo')
                    if serial:
                        return serial
        return None
    except Exception as e:
        _LOGGER.error(f"Failed to get device serial for zone {zone_id}: {e}")
        return None


def _get_device_serials_for_zone(zone_id: str, data_loader=None) -> list[str]:
    """Get ALL device serials for a zone.

    Used for operations that need to apply to all devices in a zone
    (e.g., setting temperature offset on multiple TRVs).

    Args:
        zone_id: Zone ID to look up
        data_loader: DataLoader instance for per-entry file access (v3.0.0 GAP-73)

    Returns:
        List of device serial numbers (may be empty)
    """
    serials = []
    try:
        if data_loader is not None:
            zones_info = data_loader.load_zones_info_file()
        else:
            from .data_loader import load_zones_info_file
            zones_info = load_zones_info_file()
        if not zones_info:
            return []

        for zone in zones_info:
            if str(zone.get('id')) == zone_id:
                for device in zone.get('devices', []):
                    serial = device.get('shortSerialNo')
                    if serial:
                        serials.append(serial)
                break
        return serials
    except Exception as e:
        _LOGGER.error(f"Failed to get device serials for zone {zone_id}: {e}")
        return []


def _expand_group_entity_ids(hass: HomeAssistant, entity_ids: list, allowed_domains: list = None) -> list:
    """Expand group entity IDs to individual entity IDs.

    v2.2.3: Added to support climate groups in custom services (#139).

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
                    group_members = [
                        eid for eid in group_members
                        if eid.split(".")[0] in allowed_domains
                    ]
                expanded_ids.extend(group_members)
                _LOGGER.debug(f"Expanded group {entity_id} to {len(group_members)} entities")
            else:
                _LOGGER.warning(f"Group {entity_id} not found or has no members")
        else:
            # Filter by allowed domains if specified
            if allowed_domains:
                domain = entity_id.split(".")[0]
                if domain not in allowed_domains:
                    _LOGGER.debug(f"Skipping {entity_id} - not in allowed domains {allowed_domains}")
                    continue
            expanded_ids.append(entity_id)
    return expanded_ids


def _resolve_entry_data(hass: HomeAssistant, entity_id: str):
    """Resolve EntryData for a service call using the HA entity registry.

    Looks up the entity in the HA entity registry to find its config_entry_id,
    then returns the corresponding EntryData from hass.data[DOMAIN].

    Args:
        hass: Home Assistant instance
        entity_id: Entity ID to resolve (e.g., "climate.tado_ce_living_room")

    Returns:
        EntryData instance for the entity's config entry

    Raises:
        HomeAssistantError: If entity not found, not a Tado CE entity,
            or config entry not loaded
    """
    from homeassistant.helpers import entity_registry as er
    from .entry_data import EntryData

    registry = er.async_get(hass)
    entity_entry = registry.async_get(entity_id)

    if entity_entry is None:
        raise HomeAssistantError(
            f"Entity {entity_id} not found in entity registry"
        )

    if entity_entry.platform != DOMAIN:
        raise HomeAssistantError(
            f"Entity {entity_id} is not a Tado CE entity (platform={entity_entry.platform})"
        )

    config_entry_id = entity_entry.config_entry_id
    if config_entry_id is None:
        raise HomeAssistantError(
            f"Entity {entity_id} has no config entry association"
        )

    domain_data = hass.data.get(DOMAIN, {})
    entry_data = domain_data.get(config_entry_id)

    if entry_data is None:
        raise HomeAssistantError(
            f"No Tado CE entry loaded for {entity_id} (config_entry_id={config_entry_id})"
        )

    _LOGGER.debug(
        "Resolved %s -> entry=%s (home_id=%s)",
        entity_id, config_entry_id, entry_data.home_id,
    )
    return entry_data


def _resolve_entry_data_for_device(hass: HomeAssistant, device_serial: str):
    """Resolve EntryData for a device serial using the HA device registry.

    For home-level services like identify_device that take a device_serial
    instead of entity_id. Looks up the device in the HA device registry
    to find its config_entry_id.

    Args:
        hass: Home Assistant instance
        device_serial: Device serial number (e.g., "VA1234567890")

    Returns:
        EntryData instance for the device's config entry

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
                    domain_data = hass.data.get(DOMAIN, {})
                    entry_data = domain_data.get(config_entry_id)
                    if entry_data is not None:
                        _LOGGER.debug(
                            "Resolved device %s -> entry=%s (home_id=%s)",
                            device_serial, config_entry_id, entry_data.home_id,
                        )
                        return entry_data

                raise HomeAssistantError(
                    f"Device {device_serial} found but its config entry is not loaded"
                )

    raise HomeAssistantError(
        f"Device {device_serial} not found in device registry. "
        "Check the serial number is correct."
    )


def _resolve_single_entry_data(hass: HomeAssistant):
    """Resolve EntryData when there is exactly one Tado CE config entry.

    For home-level services (add_meter_reading) that don't have an entity_id
    or device_serial to route with. If only one entry exists, returns it.
    If multiple entries exist, raises an error asking the user to specify.

    Returns:
        EntryData instance for the single config entry

    Raises:
        HomeAssistantError: If no entries or multiple entries exist
    """
    domain_data = hass.data.get(DOMAIN, {})

    # Filter to only EntryData instances (domain_data may contain other keys)
    from .entry_data import EntryData
    entries = {k: v for k, v in domain_data.items() if isinstance(v, EntryData)}

    if len(entries) == 0:
        raise HomeAssistantError("No Tado CE entries are loaded")

    if len(entries) == 1:
        entry_data = next(iter(entries.values()))
        _LOGGER.debug(
            "Single entry resolved (home_id=%s)", entry_data.home_id,
        )
        return entry_data

    # Multiple entries — list home_ids to help user
    home_ids = [ed.home_id for ed in entries.values()]
    raise HomeAssistantError(
        f"Multiple Tado homes configured ({', '.join(home_ids)}). "
        "Please use a service that targets a specific entity to route to the correct home."
    )


async def _async_register_services(hass: HomeAssistant):
    """Register Tado CE services."""
    # Lazy imports to avoid circular dependencies
    from . import async_check_bootstrap_reserve, async_show_api_limit_notification

    # Check if services are already registered (avoid duplicate registration)
    if hass.services.has_service(DOMAIN, SERVICE_SET_CLIMATE_TIMER):
        _LOGGER.debug("Tado CE services already registered, skipping")
        return

    async def handle_set_climate_timer(call: ServiceCall):
        """Handle set_climate_timer service call.

        Compatible with official Tado integration format:
        - entity_id (required)
        - temperature (required)
        - time_period (required) - Time Period format (e.g., "01:30:00")
        - overlay (optional)

        v2.0.1: Added bootstrap reserve check - blocks action when quota critically low.
        v3.0.0: Per-entry bootstrap reserve check (GAP-75).
        """
        entity_ids = call.data.get("entity_id", [])
        if isinstance(entity_ids, str):
            entity_ids = [entity_ids]

        # v2.2.3: Expand groups to individual entity IDs (#139)
        entity_ids = _expand_group_entity_ids(hass, entity_ids, allowed_domains=["climate"])

        # v3.0.0: Per-entry bootstrap reserve check — check first entity's entry
        if entity_ids:
            try:
                _ed = _resolve_entry_data(hass, entity_ids[0])
                should_block, reason = await async_check_bootstrap_reserve(hass, entry_data=_ed)
                if should_block:
                    await async_show_api_limit_notification(hass, reason)
                    raise HomeAssistantError(
                        "API quota critically low - action blocked to preserve bootstrap reserve. "
                        "Please wait for API reset."
                    )
            except HomeAssistantError:
                raise
            except Exception:
                pass  # If resolve fails, let the entity call handle the error

        temperature = call.data.get("temperature")
        time_period = call.data.get("time_period")
        overlay = call.data.get("overlay")

        # v2.3.0: time_period is optional when overlay is specified (#152 - @mpartington)
        # Validate: must have either time_period or overlay
        duration_minutes = None
        if time_period:
            # Convert time_period to minutes with validation
            try:
                from datetime import timedelta

                # Home Assistant cv.time_period returns timedelta
                if isinstance(time_period, timedelta):
                    duration_minutes = int(time_period.total_seconds() / 60)
                else:
                    # Fallback: parse string format HH:MM:SS
                    time_parts = str(time_period).split(":")
                    if len(time_parts) != 3:
                        raise ValueError(f"Invalid time_period format: {time_period}. Expected HH:MM:SS")

                    hours = int(time_parts[0])
                    minutes = int(time_parts[1])
                    seconds = int(time_parts[2])

                    # Validate ranges
                    if not (0 <= hours <= 24):
                        raise ValueError(f"Hours must be 0-24, got {hours}")
                    if not (0 <= minutes <= 59):
                        raise ValueError(f"Minutes must be 0-59, got {minutes}")
                    if not (0 <= seconds <= 59):
                        raise ValueError(f"Seconds must be 0-59, got {seconds}")

                    duration_minutes = hours * 60 + minutes + (seconds // 60)

                # Validate final duration (5-1440 minutes)
                if duration_minutes < 5:
                    raise ValueError(f"Duration must be at least 5 minutes, got {duration_minutes}")
                if duration_minutes > 1440:
                    raise ValueError(f"Duration must be at most 1440 minutes (24 hours), got {duration_minutes}")

                _LOGGER.info(f"Parsed time_period {time_period} to {duration_minutes} minutes")

            except (ValueError, AttributeError, TypeError) as e:
                error_msg = f"Failed to parse time_period: {e}"
                _LOGGER.error(error_msg)
                raise vol.Invalid(error_msg)
        elif not overlay:
            error_msg = "Either time_period or overlay is required for set_climate_timer service"
            _LOGGER.error(error_msg)
            raise vol.Invalid(error_msg)

        # Validate temperature if provided
        if temperature is None:
            error_msg = "temperature is required for set_climate_timer service"
            _LOGGER.error(error_msg)
            raise vol.Invalid(error_msg)

        for entity_id in entity_ids:
            entity = hass.states.get(entity_id)
            if entity:
                # Get the climate entity and call async_set_timer
                climate_entity = hass.data.get("entity_components", {}).get("climate")
                if climate_entity:
                    for ent in climate_entity.entities:
                        if ent.entity_id == entity_id and hasattr(ent, 'async_set_timer'):
                            try:
                                await ent.async_set_timer(temperature, duration_minutes, overlay)
                                if duration_minutes:
                                    _LOGGER.info(f"Set timer for {entity_id}: {temperature}°C for {duration_minutes}min")
                                elif overlay:
                                    _LOGGER.info(f"Set timer for {entity_id}: {temperature}°C with overlay={overlay}")
                            except Exception as e:
                                error_msg = f"Failed to set timer for {entity_id}: {e}"
                                _LOGGER.error(error_msg)
                                # Continue to next entity instead of failing completely
                            break

    async def handle_set_water_heater_timer(call: ServiceCall):
        """Handle set_water_heater_timer service call.

        v2.0.1: Added bootstrap reserve check - blocks action when quota critically low.
        v3.0.0: Per-entry bootstrap reserve check (GAP-75).
        """
        entity_ids = call.data.get("entity_id", [])
        if isinstance(entity_ids, str):
            entity_ids = [entity_ids]

        # v2.2.3: Expand groups to individual entity IDs (#139)
        entity_ids = _expand_group_entity_ids(hass, entity_ids, allowed_domains=["water_heater"])

        # v3.0.0: Per-entry bootstrap reserve check
        if entity_ids:
            try:
                _ed = _resolve_entry_data(hass, entity_ids[0])
                should_block, reason = await async_check_bootstrap_reserve(hass, entry_data=_ed)
                if should_block:
                    await async_show_api_limit_notification(hass, reason)
                    raise HomeAssistantError(
                        "API quota critically low - action blocked to preserve bootstrap reserve. "
                        "Please wait for API reset."
                    )
            except HomeAssistantError:
                raise
            except Exception:
                pass

        time_period = call.data.get("time_period")
        temperature = call.data.get("temperature")

        # CRITICAL FIX: Validate time_period
        if not time_period:
            error_msg = "time_period is required for set_water_heater_timer service"
            _LOGGER.error(error_msg)
            raise vol.Invalid(error_msg)

        # Convert time_period to minutes with validation
        try:
            from datetime import timedelta

            # Home Assistant cv.time_period returns timedelta
            if isinstance(time_period, timedelta):
                duration_minutes = int(time_period.total_seconds() / 60)
            else:
                # Fallback: parse string format HH:MM:SS
                time_parts = str(time_period).split(":")
                if len(time_parts) != 3:
                    raise ValueError(f"Invalid time_period format: {time_period}. Expected HH:MM:SS")

                hours = int(time_parts[0])
                minutes = int(time_parts[1])
                seconds = int(time_parts[2])

                # Validate ranges
                if not (0 <= hours <= 24):
                    raise ValueError(f"Hours must be 0-24, got {hours}")
                if not (0 <= minutes <= 59):
                    raise ValueError(f"Minutes must be 0-59, got {minutes}")
                if not (0 <= seconds <= 59):
                    raise ValueError(f"Seconds must be 0-59, got {seconds}")

                duration_minutes = hours * 60 + minutes + (seconds // 60)

            # Validate final duration (5-1440 minutes)
            if duration_minutes < 5:
                raise ValueError(f"Duration must be at least 5 minutes, got {duration_minutes}")
            if duration_minutes > 1440:
                raise ValueError(f"Duration must be at most 1440 minutes (24 hours), got {duration_minutes}")

            _LOGGER.info(f"Parsed time_period {time_period} to {duration_minutes} minutes")

        except (ValueError, AttributeError, TypeError) as e:
            error_msg = f"Failed to parse time_period: {e}"
            _LOGGER.error(error_msg)
            raise vol.Invalid(error_msg)

        # Validate temperature if provided
        if temperature is not None:
            if not (30 <= temperature <= 80):
                error_msg = f"Temperature must be 30-80°C, got {temperature}"
                _LOGGER.error(error_msg)
                raise vol.Invalid(error_msg)

        # Call water heater entities
        for entity_id in entity_ids:
            water_heater_component = hass.data.get("entity_components", {}).get("water_heater")
            if water_heater_component:
                for ent in water_heater_component.entities:
                    if ent.entity_id == entity_id and hasattr(ent, 'async_set_timer'):
                        try:
                            await ent.async_set_timer(duration_minutes, temperature)
                            _LOGGER.info(f"Set timer for {entity_id}: {duration_minutes}min")
                        except Exception as e:
                            error_msg = f"Failed to set timer for {entity_id}: {e}"
                            _LOGGER.error(error_msg)
                            # Continue to next entity instead of failing completely
                        break

    async def handle_resume_schedule(call: ServiceCall):
        """Handle resume_schedule service call.

        v2.0.1: Added bootstrap reserve check - blocks action when quota critically low.
        v2.2.3: Added group expansion support (#139).
        v3.0.0: Per-entry API client routing (GAP-75).
        """
        entity_ids = call.data.get("entity_id", [])
        if isinstance(entity_ids, str):
            entity_ids = [entity_ids]

        # v2.2.3: Expand groups to individual entity IDs (#139)
        entity_ids = _expand_group_entity_ids(hass, entity_ids, allowed_domains=["climate", "water_heater"])

        for entity_id in entity_ids:
            # v3.0.0: Resolve per-entry API client
            try:
                _ed = _resolve_entry_data(hass, entity_id)
            except HomeAssistantError as e:
                _LOGGER.error(f"resume_schedule: {e}")
                continue

            # Per-entry bootstrap reserve check
            should_block, reason = await async_check_bootstrap_reserve(hass, entry_data=_ed)
            if should_block:
                await async_show_api_limit_notification(hass, reason)
                raise HomeAssistantError(
                    "API quota critically low - action blocked to preserve bootstrap reserve. "
                    "Please wait for API reset."
                )

            domain = entity_id.split(".")[0]
            component = hass.data.get("entity_components", {}).get(domain)
            if component:
                for ent in component.entities:
                    if ent.entity_id == entity_id:
                        zone_id = getattr(ent, '_zone_id', None)
                        if zone_id:
                            await _ed.api_client.delete_zone_overlay(zone_id)
                            _LOGGER.info(f"Resumed schedule for {entity_id}")
                        break

    async def handle_set_temp_offset(call: ServiceCall):
        """Handle set_temperature_offset service call.

        Sets temperature offset for ALL devices in a zone (supports multi-TRV rooms).
        v2.0.1: Added bootstrap reserve check - blocks action when quota critically low.
        v3.0.0: Per-entry API client and data_loader routing (GAP-73, GAP-75).
        """
        entity_id = call.data.get("entity_id")
        offset = call.data.get("offset")

        # v3.0.0: Resolve per-entry data
        _ed = _resolve_entry_data(hass, entity_id)

        # Per-entry bootstrap reserve check
        should_block, reason = await async_check_bootstrap_reserve(hass, entry_data=_ed)
        if should_block:
            await async_show_api_limit_notification(hass, reason)
            raise HomeAssistantError(
                "API quota critically low - action blocked to preserve bootstrap reserve. "
                "Please wait for API reset."
            )

        # Get zone_id from entity and find ALL device serials
        climate_component = hass.data.get("entity_components", {}).get("climate")
        if climate_component:
            for ent in climate_component.entities:
                if ent.entity_id == entity_id:
                    zone_id = getattr(ent, '_zone_id', None)
                    if zone_id:
                        # Find ALL device serials for this zone (multi-TRV support)
                        # v3.0.0: Use per-entry data_loader (GAP-73)
                        serials = await hass.async_add_executor_job(
                            _get_device_serials_for_zone, zone_id, _ed.data_loader
                        )
                        if serials:
                            for serial in serials:
                                await _ed.api_client.set_device_offset(serial, offset)
                            _LOGGER.info(f"Set offset {offset}°C for {entity_id} ({len(serials)} device(s))")
                        else:
                            _LOGGER.warning(f"No devices found for {entity_id}")
                    break

    async def handle_add_meter_reading(call: ServiceCall):
        """Handle add_meter_reading service call (fully async).

        v2.0.1: Added bootstrap reserve check - blocks action when quota critically low.
        v3.0.0: Per-entry routing via _resolve_single_entry_data (GAP-74c).
        """
        # v3.0.0: Resolve entry — no entity_id, use single-entry implicit routing
        _ed = _resolve_single_entry_data(hass)

        # Per-entry bootstrap reserve check
        should_block, reason = await async_check_bootstrap_reserve(hass, entry_data=_ed)
        if should_block:
            await async_show_api_limit_notification(hass, reason)
            raise HomeAssistantError(
                "API quota critically low - action blocked to preserve bootstrap reserve. "
                "Please wait for API reset."
            )

        reading = call.data.get("reading")
        date = call.data.get("date")

        success = await _ed.api_client.add_meter_reading(reading, date)

        if not success:
            _LOGGER.error(f"Failed to add meter reading: {reading}")

    async def handle_identify_device(call: ServiceCall):
        """Handle identify_device service call (fully async).

        v2.0.1: Added bootstrap reserve check - blocks action when quota critically low.
        v3.0.0: Per-entry routing via _resolve_entry_data_for_device (GAP-74b).
        """
        device_serial = call.data.get("device_serial")

        # v3.0.0: Resolve entry via device registry lookup
        _ed = _resolve_entry_data_for_device(hass, device_serial)

        # Per-entry bootstrap reserve check
        should_block, reason = await async_check_bootstrap_reserve(hass, entry_data=_ed)
        if should_block:
            await async_show_api_limit_notification(hass, reason)
            raise HomeAssistantError(
                "API quota critically low - action blocked to preserve bootstrap reserve. "
                "Please wait for API reset."
            )

        success = await _ed.api_client.identify_device(device_serial)

        if not success:
            _LOGGER.error(f"Failed to identify device: {device_serial}")

    async def handle_set_away_config(call: ServiceCall):
        """Handle set_away_configuration service call (fully async).

        v2.0.1: Added bootstrap reserve check - blocks action when quota critically low.
        v3.0.0: Per-entry API client routing (GAP-75).
        """
        entity_id = call.data.get("entity_id")
        mode = call.data.get("mode")
        temperature = call.data.get("temperature")
        comfort_level = call.data.get("comfort_level", 50)

        # v3.0.0: Resolve per-entry data
        _ed = _resolve_entry_data(hass, entity_id)

        # Per-entry bootstrap reserve check
        should_block, reason = await async_check_bootstrap_reserve(hass, entry_data=_ed)
        if should_block:
            await async_show_api_limit_notification(hass, reason)
            raise HomeAssistantError(
                "API quota critically low - action blocked to preserve bootstrap reserve. "
                "Please wait for API reset."
            )

        # Get zone_id from entity
        climate_component = hass.data.get("entity_components", {}).get("climate")
        if climate_component:
            for ent in climate_component.entities:
                if ent.entity_id == entity_id:
                    zone_id = getattr(ent, '_zone_id', None)
                    if zone_id:
                        success = await _ed.api_client.set_away_configuration(
                            zone_id, mode, temperature, comfort_level
                        )
                        if not success:
                            _LOGGER.error(f"Failed to set away config for {entity_id}")
                    break

    async def handle_get_temp_offset(call: ServiceCall):
        """Handle get_temperature_offset service call.

        Fetches the current temperature offset for a climate entity on-demand.
        Returns the offset value via service response for use in automations.
        v3.0.0: Per-entry API client and data_loader routing (GAP-73, GAP-75).
        """
        entity_id = call.data.get("entity_id")

        # v3.0.0: Resolve per-entry data
        try:
            _ed = _resolve_entry_data(hass, entity_id)
        except HomeAssistantError as e:
            _LOGGER.error(f"get_temp_offset: {e}")
            return {"offset_celsius": None, "error": str(e)}

        # Get zone_id from entity
        climate_component = hass.data.get("entity_components", {}).get("climate")
        if climate_component:
            for ent in climate_component.entities:
                if ent.entity_id == entity_id:
                    zone_id = getattr(ent, '_zone_id', None)
                    if zone_id:
                        # Find device serial for this zone
                        # v3.0.0: Use per-entry data_loader (GAP-73)
                        serial = await hass.async_add_executor_job(
                            _get_device_serial_for_zone, zone_id, _ed.data_loader
                        )
                        if serial:
                            result = await _ed.api_client.get_device_offset(serial)
                            if result is not None:
                                return {"offset_celsius": result}

                    _LOGGER.error(f"Failed to get offset for {entity_id}")
                    return {"offset_celsius": None, "error": "Failed to fetch offset"}

        _LOGGER.error(f"Entity not found: {entity_id}")
        return {"offset_celsius": None, "error": "Entity not found"}

    # Register services
    # v2.2.3: Use cv.entity_ids + handler expansion to support climate groups (#139)
    hass.services.async_register(
        DOMAIN, SERVICE_SET_CLIMATE_TIMER, handle_set_climate_timer,
        schema=vol.Schema({
            vol.Required("entity_id"): cv.entity_ids,
            vol.Required("temperature"): vol.Coerce(float),
            vol.Optional("time_period"): cv.time_period,
            vol.Optional("overlay"): cv.string,
        })
    )

    hass.services.async_register(
        DOMAIN, SERVICE_SET_WATER_HEATER_TIMER, handle_set_water_heater_timer,
        schema=vol.Schema({
            vol.Required("entity_id"): cv.entity_ids,
            vol.Required("time_period"): cv.time_period,
            vol.Optional("temperature"): vol.Coerce(float),
        })
    )

    # v2.2.3: Use cv.entity_ids + handler expansion to support groups (#139)
    hass.services.async_register(
        DOMAIN, SERVICE_RESUME_SCHEDULE, handle_resume_schedule,
        schema=vol.Schema({
            vol.Required("entity_id"): cv.entity_ids,
        })
    )

    hass.services.async_register(
        DOMAIN, SERVICE_SET_TEMP_OFFSET, handle_set_temp_offset,
        schema=vol.Schema({
            vol.Required("entity_id"): cv.entity_id,
            vol.Required("offset"): vol.Coerce(float),
        })
    )

    hass.services.async_register(
        DOMAIN, SERVICE_ADD_METER_READING, handle_add_meter_reading,
        schema=vol.Schema({
            vol.Required("reading"): vol.Coerce(int),
            vol.Optional("date"): cv.string,
        })
    )

    hass.services.async_register(
        DOMAIN, SERVICE_IDENTIFY_DEVICE, handle_identify_device,
        schema=vol.Schema({
            vol.Required("device_serial"): cv.string,
        })
    )

    hass.services.async_register(
        DOMAIN, SERVICE_SET_AWAY_CONFIG, handle_set_away_config,
        schema=vol.Schema({
            vol.Required("entity_id"): cv.entity_id,
            vol.Required("mode"): cv.string,
            vol.Optional("temperature"): vol.Coerce(float),
            vol.Optional("comfort_level"): vol.Coerce(int),
        })
    )

    hass.services.async_register(
        DOMAIN, SERVICE_GET_TEMP_OFFSET, handle_get_temp_offset,
        schema=vol.Schema({
            vol.Required("entity_id"): cv.entity_id,
        }),
        supports_response=True,
    )

    _LOGGER.info("Tado CE: Services registered")
