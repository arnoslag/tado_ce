"""Tado CE Integration."""
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .config_manager import ConfigurationManager
from .const import (
    CONFIG_FILE,
    DATA_DIR,
    DOMAIN,
    SERVICE_ADD_METER_READING,
    SERVICE_GET_TEMP_OFFSET,
    SERVICE_IDENTIFY_DEVICE,
    SERVICE_RESUME_SCHEDULE,
    SERVICE_SET_AWAY_CONFIG,
    SERVICE_SET_CLIMATE_TIMER,
    SERVICE_SET_TEMP_OFFSET,
    SERVICE_SET_WATER_HEATER_TIMER,
)
from .coordinator import TadoDataUpdateCoordinator
from .data_loader import DataLoader
from .entry_data import EntryData
from .migration import (  # noqa: E402
    _migrate_to_per_zone_config,
    async_migrate_entry,  # noqa: F401
)
from .services import _async_register_services
from .zone_config_manager import ZoneConfigManager

_LOGGER = logging.getLogger(__name__)

BASE_PLATFORMS = [
    Platform.SENSOR, Platform.CLIMATE, Platform.BINARY_SENSOR,
    Platform.WATER_HEATER, Platform.DEVICE_TRACKER, Platform.SWITCH,
    Platform.BUTTON, Platform.SELECT, Platform.NUMBER,
]
CALENDAR_PLATFORM = Platform.CALENDAR

DEFAULT_DAY_INTERVAL = 30
DEFAULT_NIGHT_INTERVAL = 120


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up the Tado CE component."""
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Tado CE from a config entry."""
    _LOGGER.info(
        "=== Tado CE Setup Start ===\n  Entry ID: %s\n  Entry version: %s\n  Entry data: %s",
        entry.entry_id, entry.version, entry.data
    )

    from .setup_entry_helpers import async_log_file_system_state
    await async_log_file_system_state(hass)

    # Check for duplicate entries and remove old ones
    from .migration import async_deduplicate_entries
    should_continue = await async_deduplicate_entries(hass, entry)
    if not should_continue:
        return False

    # Ensure data directory exists
    def _ensure_data_dir():
        try:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            _LOGGER.error("Failed to create DATA_DIR: %s", e)

    await hass.async_add_executor_job(_ensure_data_dir)

    config_manager = ConfigurationManager(entry, hass)
    _LOGGER.info("Configuration loaded: %s", config_manager.get_all_config())

    home_id = entry.data.get("home_id")
    hass.data.setdefault(DOMAIN, {})

    # Cancel old polling timer on reload
    old_entry_data = hass.data[DOMAIN].get(entry.entry_id)
    if old_entry_data and hasattr(old_entry_data, 'polling_cancel') and old_entry_data.polling_cancel:
        _LOGGER.warning("Tado CE: Entry %s already setup, cancelling old polling timer", entry.entry_id)
        old_entry_data.polling_cancel()

    data_loader = DataLoader(home_id or "default")
    entry_data = EntryData(
        home_id=home_id or "default",
        refresh_token=entry.data.get("refresh_token", ""),
        config_manager=config_manager,
        data_loader=data_loader,
    )

    zone_config_manager = ZoneConfigManager(hass, home_id or "default")
    await zone_config_manager.async_load()
    entry_data.zone_config_manager = zone_config_manager
    _LOGGER.info("Zone config manager initialized with %d zones", len(zone_config_manager.zones))

    await _migrate_to_per_zone_config(hass, entry, zone_config_manager, data_loader=data_loader)

    overlay_mode = await hass.async_add_executor_job(data_loader.load_overlay_mode)
    entry_data.overlay_mode = overlay_mode
    _LOGGER.debug("Tado CE: Overlay mode loaded: %s", overlay_mode)

    timer_duration = await hass.async_add_executor_job(data_loader.load_timer_duration)
    entry_data.timer_duration = timer_duration
    _LOGGER.debug("Tado CE: Timer duration loaded: %d minutes", timer_duration)

    # Create per-entry infrastructure (API tracker, client, timers, etc.)
    from .entry_lifecycle import async_create_entry_components
    await async_create_entry_components(hass, entry, entry_data, config_manager, home_id)

    # Check if config file exists
    config_exists = await hass.async_add_executor_job(CONFIG_FILE.exists)
    if not config_exists:
        _LOGGER.warning(
            "Tado CE config file not found. "
            "Use Settings > Devices & Services > Add Integration > Tado CE to authenticate."
        )

    # Initialize optional per-entry components (before coordinator creation)
    from .setup_entry_helpers import (
        async_init_adaptive_preheat,
        async_init_heating_cycle,
        async_init_smart_comfort,
    )

    await async_init_smart_comfort(hass, entry_data, config_manager, home_id)
    await async_init_heating_cycle(hass, entry_data, config_manager, home_id)
    await async_init_adaptive_preheat(hass, entry_data, config_manager)

    coordinator = TadoDataUpdateCoordinator(
        hass,
        entry,
        config_manager=config_manager,
        zone_config_manager=zone_config_manager,
        data_loader=data_loader,
        api_client=entry_data.api_client,
        api_tracker=entry_data.api_tracker,
        smart_comfort_manager=entry_data.smart_comfort_manager,
        heating_cycle_coordinator=entry_data.heating_cycle_coordinator,
        adaptive_preheat_manager=entry_data.adaptive_preheat_manager,
    )

    # Load overlay/timer cache into coordinator
    coordinator.overlay_mode = overlay_mode
    coordinator.timer_duration = timer_duration

    # First refresh
    await coordinator.async_config_entry_first_refresh()

    # Runtime fallback — detect old-format unique_ids
    if home_id:
        from .migration import detect_and_migrate_old_unique_ids
        detect_and_migrate_old_unique_ids(hass, entry, str(home_id))

    # Store coordinator as runtime_data (HA official pattern)
    entry.runtime_data = coordinator
    hass.data[DOMAIN][entry.entry_id] = entry_data  # backward compat during migration
    _LOGGER.info("Coordinator stored for entry %s (home_id=%s)", entry.entry_id, home_id)

    # Build platform list based on config
    platforms_to_load = list(BASE_PLATFORMS)
    if CALENDAR_PLATFORM and config_manager.get_schedule_calendar_enabled():
        platforms_to_load.append(CALENDAR_PLATFORM)
        _LOGGER.info("Tado CE: Schedule Calendar enabled")

    await hass.config_entries.async_forward_entry_setups(entry, platforms_to_load)

    # Register services
    await _async_register_services(hass)

    # Register update listener for options changes
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))

    _LOGGER.info("Tado CE: Integration loaded successfully")
    return True


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload config entry when options change."""
    _LOGGER.info("Tado CE: Options changed, reloading integration...")

    from .migration import (
        async_handle_test_mode_transition,
        cleanup_disabled_feature_entities,
    )

    try:
        cleanup_disabled_feature_entities(hass, entry)
    except Exception as e:
        _LOGGER.warning("Tado CE: Could not cleanup entities: %s", e)

    try:
        await async_handle_test_mode_transition(hass, entry)
    except Exception as e:
        _LOGGER.debug("Tado CE: Could not check Test Mode transition: %s", e)

    await hass.config_entries.async_reload(entry.entry_id)




async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    _LOGGER.info("Tado CE: Unloading entry %s...", entry.entry_id)

    coordinator = getattr(entry, 'runtime_data', None)
    entry_data = hass.data.get(DOMAIN, {}).get(entry.entry_id)

    # Clean up coordinator's RefreshHandler debounce task
    if coordinator and hasattr(coordinator, 'refresh_handler') and coordinator.refresh_handler:
        rh = coordinator.refresh_handler
        if rh._debounce_task is not None:
            rh._debounce_task.cancel()
            rh._debounce_task = None
            _LOGGER.debug("Cancelled pending debounce task")
        coordinator.refresh_handler = None
        _LOGGER.debug("Cleaned up coordinator RefreshHandler")

    # Per-entry cleanup (API client, timers, managers)
    from .entry_lifecycle import async_cleanup_entry_components
    await async_cleanup_entry_components(hass, entry_data)

    # --- Unload platforms ---

    config_manager = getattr(coordinator, 'config_manager', None) if coordinator else None
    if config_manager is None and entry_data is not None:
        config_manager = getattr(entry_data, 'config_manager', None)

    platforms_to_unload = list(BASE_PLATFORMS)
    if CALENDAR_PLATFORM and config_manager and config_manager.get_schedule_calendar_enabled():
        platforms_to_unload.append(CALENDAR_PLATFORM)

    unload_ok = await hass.config_entries.async_unload_platforms(entry, platforms_to_unload)

    # --- Clean up hass.data backward compat dict ---

    if unload_ok and DOMAIN in hass.data:
        hass.data[DOMAIN].pop(entry.entry_id, None)
        has_entries = any(
            isinstance(v, EntryData) for v in hass.data[DOMAIN].values()
        )
        if not has_entries:
            hass.data.pop(DOMAIN, None)
            _LOGGER.debug("Removed domain dict (last entry unloaded)")

    # --- Service lifecycle ---

    other_entries = [
        e for e in hass.config_entries.async_entries(DOMAIN)
        if e.entry_id != entry.entry_id
    ]
    if len(other_entries) == 0:
        for service_name in [
            SERVICE_SET_CLIMATE_TIMER, SERVICE_SET_WATER_HEATER_TIMER,
            SERVICE_RESUME_SCHEDULE, SERVICE_SET_TEMP_OFFSET,
            SERVICE_GET_TEMP_OFFSET, SERVICE_ADD_METER_READING,
            SERVICE_IDENTIFY_DEVICE, SERVICE_SET_AWAY_CONFIG,
        ]:
            if hass.services.has_service(DOMAIN, service_name):
                hass.services.async_remove(DOMAIN, service_name)
        _LOGGER.debug("Unregistered all services (last entry unloaded)")

    _LOGGER.info("Tado CE: Entry %s unloaded successfully", entry.entry_id)
    return unload_ok
