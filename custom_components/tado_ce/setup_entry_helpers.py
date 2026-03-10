"""Tado CE setup entry helpers — optional per-entry component initialization."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from .adaptive_preheat import AdaptivePreheatManager
    from .api_client import TadoApiClient
    from .config_manager import ConfigurationManager
    from .data_loader import DataLoader
    from .heating_coordinator import HeatingCycleCoordinator
    from .smart_comfort import SmartComfortManager

_LOGGER = logging.getLogger(__name__)


async def async_log_file_system_state(hass: HomeAssistant) -> None:
    """Log file system state for debugging (run in executor to avoid blocking I/O)."""
    from .const import CONFIG_FILE, DATA_DIR, ZONES_FILE, ZONES_INFO_FILE

    def _check() -> dict[str, Any]:
        """Check file system state."""
        return {
            "data_dir_exists": DATA_DIR.exists(),
            "config_file_exists": CONFIG_FILE.exists(),
            "zones_file_exists": ZONES_FILE.exists(),
            "zones_info_file_exists": ZONES_INFO_FILE.exists(),
        }

    fs_state = await hass.async_add_executor_job(_check)
    _LOGGER.info(
        "=== Setup File System State ===\n"
        "  DATA_DIR: %s (exists: %s)\n  CONFIG_FILE: %s (exists: %s)\n"
        "  ZONES_FILE: %s (exists: %s)\n  ZONES_INFO_FILE: %s (exists: %s)",
        DATA_DIR,
        fs_state["data_dir_exists"],
        CONFIG_FILE,
        fs_state["config_file_exists"],
        ZONES_FILE,
        fs_state["zones_file_exists"],
        ZONES_INFO_FILE,
        fs_state["zones_info_file_exists"],
    )


async def async_init_smart_comfort(
    hass: HomeAssistant,
    data_loader: DataLoader,
    config_manager: ConfigurationManager,
    home_id: str | None,
) -> SmartComfortManager | None:
    """Initialize Smart Comfort Manager if enabled.

    Returns the manager instance, or None if disabled.
    """
    if not config_manager.get_smart_comfort_enabled():
        return None

    from .smart_comfort import (
        SmartComfortManager,
        async_load_baseline_from_statistics,
        async_load_history_from_recorder,
    )

    history_days = config_manager.get_smart_comfort_history_days()
    smart_comfort_manager = SmartComfortManager(
        hass=hass,
        home_id=home_id or "",
        history_days=history_days,
    )
    smart_comfort_manager.enable()

    # Configure weather compensation
    outdoor_temp_entity = config_manager.get_outdoor_temp_entity()
    weather_compensation = config_manager.get_weather_compensation()
    use_feels_like = config_manager.get_use_feels_like()

    if outdoor_temp_entity:
        smart_comfort_manager.configure_weather(
            outdoor_temp_entity=outdoor_temp_entity,
            weather_compensation=weather_compensation,
            use_feels_like=use_feels_like,
        )

    # 3-Tier Loading Strategy
    # Tier 1: Load from cache file (fastest, 2h detailed data)
    cache_readings = await hass.async_add_executor_job(smart_comfort_manager.load_from_file)

    # Get zones_info for entity ID mapping
    zones_info = await hass.async_add_executor_job(data_loader.load_zones_info_file)

    if zones_info:
        entity_to_zone_id = {
            zone.get("name", "").lower().replace(" ", "_"): str(zone.get("id"))
            for zone in zones_info
            if zone.get("name") and zone.get("id")
        }

        climate_entity_ids = [f"climate.{entity_name}" for entity_name in entity_to_zone_id]

        # Tier 2: Load from recorder history (24h detailed states)
        recorder_readings = 0
        if climate_entity_ids:
            recorder_readings = await async_load_history_from_recorder(
                hass,
                smart_comfort_manager,
                climate_entity_ids,
                entity_to_zone_id,
            )

        # Tier 3: Load baseline rates from long-term statistics (7 days hourly)
        zone_sensor_mapping = {
            str(zone.get("id")): f"sensor.{zone.get('name', '').lower().replace(' ', '_')}_temperature"
            for zone in zones_info
            if zone.get("name") and zone.get("id")
        }
        baseline_stats = await async_load_baseline_from_statistics(
            hass,
            smart_comfort_manager,
            zone_sensor_mapping,
        )

        _LOGGER.info(
            "Tado CE: Smart Comfort 3-tier loading complete - cache=%s, recorder=%s, baseline_zones=%s",
            cache_readings,
            recorder_readings,
            len(baseline_stats),
        )

    _LOGGER.info("Tado CE: Smart Comfort Analytics enabled")
    return smart_comfort_manager


async def async_init_heating_cycle(
    hass: HomeAssistant,
    config_manager: ConfigurationManager,
    home_id: str | None,
) -> HeatingCycleCoordinator | None:
    """Initialize Heating Cycle Coordinator.

    Always enabled for HEATING zones.
    Returns the coordinator instance, or None if no home_id.
    """
    if not home_id:
        return None

    try:
        from .heating_coordinator import HeatingCycleCoordinator
        from .heating_models import HeatingCycleConfig

        heating_cycle_config = HeatingCycleConfig(
            enabled=True,
            rolling_window_days=config_manager.get_heating_cycle_history_days(),
            inertia_threshold_celsius=config_manager.get_heating_cycle_inertia_threshold(),
            min_cycles=config_manager.get_heating_cycle_min_cycles(),
        )

        _LOGGER.info(
            "Tado CE: Heating Cycle Config - min_cycles=%d, history_days=%d, inertia_threshold=%.2f",
            heating_cycle_config.min_cycles,
            heating_cycle_config.rolling_window_days,
            heating_cycle_config.inertia_threshold_celsius,
        )

        heating_cycle_coordinator = HeatingCycleCoordinator(
            hass,
            home_id,
            heating_cycle_config,
        )
        await heating_cycle_coordinator.async_setup()

        _LOGGER.info("Tado CE: Heating Cycle Analysis initialized")
        return heating_cycle_coordinator
    except Exception:
        _LOGGER.exception("Tado CE: Failed to initialize Heating Cycle Analysis")
        return None


async def async_init_adaptive_preheat(
    hass: HomeAssistant,
    config_manager: ConfigurationManager,
    *,
    api_client: TadoApiClient | None,
    data_loader: DataLoader | None,
) -> AdaptivePreheatManager | None:
    """Initialize Adaptive Preheat Manager if enabled.

    Returns the manager instance, or None if disabled.
    """
    if not config_manager.get_adaptive_preheat_enabled():
        return None

    try:
        from .adaptive_preheat import AdaptivePreheatManager

        apm = AdaptivePreheatManager(
            hass,
            config_manager,
            api_client=api_client,
            data_loader=data_loader,
        )
        await apm.async_setup()
        _LOGGER.info("Tado CE: Adaptive Preheat enabled")
        return apm
    except Exception:
        _LOGGER.exception("Tado CE: Failed to initialize Adaptive Preheat")
        return None
