"""Tado CE migration — config entry version migration and device cleanup."""

from __future__ import annotations

import json
import logging
import re
from typing import TYPE_CHECKING, Any

from .const import CONFIG_FILE, DATA_DIR, DOMAIN

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

    from .data_loader import DataLoader
    from .zone_config_manager import ZoneConfigManager

_LOGGER = logging.getLogger(__name__)

# Module-level set to track duplicate cleanup operations (prevents re-running)
_duplicate_cleanup_done: set[str] = set()


async def async_migrate_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Migrate old entry to new version.

    Uses cumulative `< X` pattern so users jumping multiple versions
    run ALL migrations. Earliest supported upgrade path: v2.3.1+.
    """
    # Store initial version for logging (version may change during migration)
    # Handle None version (can happen if previous migration failed mid-way)
    initial_version = config_entry.version
    if initial_version is None:
        _LOGGER.warning(
            "Config entry version is None (possibly from failed migration). "
            "Treating as version 1 to run all migrations.",
        )
        initial_version = 1

    _LOGGER.info(
        "=== Tado CE Migration Start ===\n"
        "  Current version: %s\n  Target version: 11\n"
        "  Entry ID: %s\n  Entry data: %s",
        initial_version,
        config_entry.entry_id,
        config_entry.data,
    )

    # Log file system state for debugging (run in executor to avoid blocking I/O)
    def _log_fs_state() -> dict[str, Any]:
        """Gather file system state synchronously."""
        state: dict[str, Any] = {
            "data_dir_exists": DATA_DIR.exists(),
            "config_file_exists": CONFIG_FILE.exists(),
            "data_dir_files": [],
        }
        if state["data_dir_exists"]:
            try:
                state["data_dir_files"] = [f.name for f in DATA_DIR.glob("*.json")]
            except Exception as e:
                state["data_dir_error"] = str(e)
        return state

    fs_state = await hass.async_add_executor_job(_log_fs_state)
    _LOGGER.info(
        "=== File System State ===\n"
        "  DATA_DIR exists: %s\n  DATA_DIR path: %s\n"
        "  CONFIG_FILE exists: %s\n  CONFIG_FILE path: %s",
        fs_state["data_dir_exists"],
        DATA_DIR,
        fs_state["config_file_exists"],
        CONFIG_FILE,
    )
    if fs_state.get("data_dir_files"):
        _LOGGER.info("  DATA_DIR files: %s", fs_state["data_dir_files"])
    if fs_state.get("data_dir_error"):
        _LOGGER.warning("  Could not list DATA_DIR files: %s", fs_state["data_dir_error"])

    # Cumulative migration using `< X` pattern
    # This ensures users jumping multiple versions run ALL migrations
    # Removed all migration steps prior to v10 (v2.3.1).
    # Earliest supported upgrade path: v2.3.1 (config entry version = 10).
    # Users on older versions must upgrade to v2.3.1 first, then to v3.0.0.

    if initial_version < 11:
        # Version 10 -> 11 (v3.0.0): All v2.3.1 → v3.0.0 migrations in one step:
        #   1. Migrate entity unique_ids to include {home_id}
        #   2. Copy refresh_token from config file to entry.data
        _LOGGER.info("=== Migration: v10 -> v11 (v2.3.1 -> v3.0.0) ===")

        home_id = config_entry.data.get("home_id")

        if not home_id:

            def _read_home_id_from_config() -> str | None:
                """Read home_id from config.json synchronously."""
                if CONFIG_FILE.exists():
                    try:
                        with CONFIG_FILE.open() as f:
                            config = json.load(f)
                        return config.get("home_id")  # type: ignore[no-any-return]
                    except Exception as e:
                        _LOGGER.warning("  Could not read home_id from config.json: %s", e)
                return None

            home_id = await hass.async_add_executor_job(_read_home_id_from_config)
            if home_id:
                _LOGGER.info("  Got home_id from config.json: %s", home_id)

        # Step 1: Entity unique_id migration
        _LOGGER.info("  Step 1: Migrating entity unique_ids to v3.0.0 format")
        if home_id:
            from .data_loader import DataLoader

            migration_loader = DataLoader(str(home_id))

            migrated_count = _migrate_entity_unique_ids(hass, config_entry, str(home_id), data_loader=migration_loader)
            _LOGGER.info("  Migrated %s entity unique_ids", migrated_count)
        else:
            _LOGGER.warning(
                "  Could not determine home_id for entity UID migration. "
                "Entity unique_ids will be migrated on next restart after re-authentication.",
            )

        # Step 2: Copy refresh_token from config file to entry.data
        _LOGGER.info("  Step 2: Storing refresh_token in entry.data")
        if "refresh_token" not in config_entry.data or not config_entry.data.get("refresh_token"):
            from .const import get_data_file

            def _read_refresh_token() -> str | None:
                """Read refresh_token from config files synchronously."""
                for config_path in [get_data_file("config", home_id), CONFIG_FILE]:
                    if config_path and config_path.exists():
                        try:
                            with config_path.open() as f:
                                cfg = json.load(f)
                            t = cfg.get("refresh_token")
                            if t:
                                return (t, config_path.name)  # type: ignore[return-value]
                        except Exception as e:
                            _LOGGER.debug("  Could not read %s: %s", config_path, e)
                return (None, None)  # type: ignore[return-value]

            token, source_name = await hass.async_add_executor_job(_read_refresh_token)  # type: ignore[misc]
            if token:
                _LOGGER.info("  Got refresh_token from %s", source_name)
                new_data = {**config_entry.data, "refresh_token": token}
                hass.config_entries.async_update_entry(config_entry, data=new_data)
                _LOGGER.info("  Stored refresh_token in entry.data")
            else:
                _LOGGER.warning("  No refresh_token found in config files — will be set on next re-auth")
        else:
            _LOGGER.info("  entry.data already has refresh_token, skipping")

        _LOGGER.info("Migration v10 -> v11 complete")

    # Update to final version (only once, at the end)
    target_version = 11
    if initial_version < target_version:
        hass.config_entries.async_update_entry(config_entry, version=target_version)

        def _final_fs_state() -> tuple[bool, bool]:
            """Check final file system state synchronously."""
            return CONFIG_FILE.exists(), DATA_DIR.exists()

        cfg_exists, data_exists = await hass.async_add_executor_job(_final_fs_state)
        _LOGGER.info(
            "=== Migration Complete ===\n"
            "  Initial version: %s\n  Final version: %s\n"
            "  CONFIG_FILE exists: %s\n  DATA_DIR exists: %s",
            initial_version,
            target_version,
            cfg_exists,
            data_exists,
        )
    else:
        _LOGGER.info("Config entry already at version %s, no migration needed", target_version)

    return True


async def _migrate_to_per_zone_config(
    hass: HomeAssistant,
    entry: ConfigEntry,
    zone_config_manager: ZoneConfigManager,
    data_loader: DataLoader | None = None,
) -> None:
    """Migrate global settings to per-zone configuration.

    Called on first startup after upgrade. Migrates:
    - ufh_zones → per-zone heating_type = "ufh"
    - ufh_buffer_minutes → per-zone ufh_buffer_minutes
    - adaptive_preheat_zones → per-zone adaptive_preheat = True
    - smart_comfort_mode → per-zone (inherit global)
    - mold_risk_window_type → per-zone window_type
    - overlay_mode → per-zone (inherit global)
    """
    options = entry.options

    # Check if already migrated
    if options.get("_per_zone_migrated"):
        _LOGGER.debug("Per-zone migration already completed, skipping")
        return

    # Check if there are any global settings to migrate
    has_settings_to_migrate = any(
        [
            options.get("ufh_zones"),
            options.get("adaptive_preheat_zones"),
            options.get("smart_comfort_mode"),
            options.get("mold_risk_window_type"),
        ],
    )

    if not has_settings_to_migrate:
        _LOGGER.debug("No global settings to migrate to per-zone config")
        # Mark as migrated anyway to prevent future checks
        new_options = {**options, "_per_zone_migrated": True}
        hass.config_entries.async_update_entry(entry, options=new_options)
        return

    if data_loader is None:
        _LOGGER.warning("No data_loader available, skipping per-zone migration")
        return

    _LOGGER.info("=== Per-Zone Configuration Migration ===")

    zones_info = await hass.async_add_executor_job(data_loader.load_zones_info_file)

    if not zones_info:
        _LOGGER.warning("No zones info available, skipping per-zone migration")
        return

    # Get global settings
    ufh_zones = options.get("ufh_zones", [])
    ufh_buffer = options.get("ufh_buffer_minutes", 30)
    adaptive_preheat_zones = options.get("adaptive_preheat_zones", [])
    smart_comfort_mode = options.get("smart_comfort_mode", "none")
    window_type = options.get("mold_risk_window_type", "double_pane")

    # Get overlay mode from cache or file (already UPPERCASE)
    overlay_mode = await hass.async_add_executor_job(data_loader.load_overlay_mode)

    # overlay_mode is already UPPERCASE from data_loader — use directly
    overlay_mode_internal = overlay_mode

    migrated_count = 0

    # Apply to each zone
    for zone in zones_info:
        zone_id = str(zone.get("id"))
        zone_type = zone.get("type")
        zone_name = zone.get("name", f"Zone {zone_id}")

        config_updates = {}

        # Heating type (Heating only)
        if zone_type == "HEATING":
            if zone_id in ufh_zones:
                config_updates["heating_type"] = "ufh"
                config_updates["ufh_buffer_minutes"] = ufh_buffer
                _LOGGER.debug("  Zone %s: UFH with %smin buffer", zone_name, ufh_buffer)
            else:
                config_updates["heating_type"] = "radiator"

        # Adaptive preheat (Heating + AC)
        if zone_id in adaptive_preheat_zones:
            config_updates["adaptive_preheat"] = True  # type: ignore[assignment]
            _LOGGER.debug("  Zone %s: Adaptive preheat enabled", zone_name)

        # Smart comfort mode (inherit global)
        if smart_comfort_mode != "none":
            config_updates["smart_comfort_mode"] = smart_comfort_mode

        # Window type (inherit global)
        config_updates["window_type"] = window_type

        # Overlay mode (inherit global)
        config_updates["overlay_mode"] = overlay_mode_internal

        # Save zone config
        for key, value in config_updates.items():
            await zone_config_manager.async_set_zone_value(zone_id, key, value)

        if config_updates:
            migrated_count += 1

    # Mark as migrated
    new_options = {**options, "_per_zone_migrated": True}
    hass.config_entries.async_update_entry(entry, options=new_options)

    _LOGGER.info("Per-zone migration complete: %s zones configured", migrated_count)


# ===========================================================================
# Entity unique_id migration map
# Maps v2.x unique_id patterns to v3.0 patterns (includes {home_id})
# 31 specific renames + generic {home_id} insertion rule for the rest
# ===========================================================================

# Specific renames: entries where the descriptor also changes (not just {home_id} insertion)
# Format: (v2.x_suffix, v3.0_suffix_template)
# The v3.0 template uses {hid} for home_id, {zid} for zone_id, {serial} for device serial
# Timer buttons use {zone_name} in v2.x — handled separately via zone_name→zone_id lookup
_UID_RENAME_MAP = {
    # Hub sensors — shortened descriptors
    "outside_temperature": "{hid}_outside_temp",
    "boiler_flow_temperature": "{hid}_boiler_flow_temp",
    "api_call_breakdown": "{hid}_api_breakdown",
    # Hub controls — shortened descriptors
    "resume_all_schedules": "{hid}_resume_all",
    "refresh_ac_capabilities": "{hid}_refresh_ac",
    "overlay_timer_duration": "{hid}_overlay_timer",
}

# Zone-level renames: v2.x pattern "zone_{zid}_{old}" → v3.0 "{hid}_zone_{zid}_{new}"
_UID_ZONE_RENAME_MAP = {
    "temperature": "temp",
    "ac_power": "ac",
    "mode": "overlay",
    "historical_deviation": "schedule_deviation",
    "next_schedule_time": "next_schedule",
    "next_schedule_temp": "next_sched_temp",
    "smart_comfort_target": "comfort_target",
    "mold_risk_percentage": "mold_risk_pct",
    "condensation_risk": "condensation",
    "surface_temperature": "surface_temp",
    "avg_heating_rate": "heating_rate",
    "analysis_confidence": "confidence",
    "heating_acceleration": "heat_accel",
    # Zone config descriptor renames
    "heating_type": "heat_emitter",
    "smart_comfort_mode": "smart_comfort",
    "timer_duration": "overlay_timer",
    "surface_temp_offset": "surface_offset",
}

# Zone buttons that need "zone_" segment added (v2.x: tado_ce_{zid}_X → v3.0: tado_ce_{hid}_zone_{zid}_X)
_UID_ZONE_BUTTON_ADD_SEGMENT = {"refresh_schedule", "boost", "smart_boost"}

# Calendar: tado_ce_schedule_{zid} → tado_ce_{hid}_zone_{zid}_schedule (reordered)
# Device sensors: tado_ce_{serial}_X → tado_ce_{hid}_device_{serial}_X (added device_ segment)
# Timer buttons: tado_ce_{zone_name}_timer_{dur}min → tado_ce_{hid}_zone_{zid}_timer_{dur}min


def _migrate_entity_unique_ids(
    hass: HomeAssistant, config_entry: ConfigEntry, home_id: str, data_loader: DataLoader | None = None,
) -> int:
    """Migrate v2.x entity unique_ids to v3.0 format (with {home_id}).

    One-time cumulative migration. Idempotent — safe to run multiple times.

    Strategy:
    1. For each entity in the registry belonging to this config_entry:
       a. If unique_id already contains home_id → skip (already migrated)
       b. Try specific rename map first (descriptor changes)
       c. Fall back to generic rule: insert {home_id} after "tado_ce_"

    Returns:
        Number of entities migrated
    """
    from homeassistant.helpers import entity_registry as er

    entity_registry = er.async_get(hass)

    # Build zone_name → zone_id mapping for timer button migration
    zones_info = data_loader.load_zones_info_file() if data_loader is not None else None
    zone_name_to_id = {}
    if zones_info:
        for zone in zones_info:
            zname = zone.get("name", "")
            zid = str(zone.get("id", ""))
            if zname and zid:
                # v2.x timer buttons use lowercased zone_name with spaces replaced by underscores
                zone_name_to_id[zname.lower().replace(" ", "_")] = zid

    migrated = 0
    prefix = "tado_ce_"
    hid = str(home_id)
    already_migrated_prefix = f"tado_ce_{hid}_"

    for entity_id, entity_entry in list(entity_registry.entities.items()):
        if entity_entry.config_entry_id != config_entry.entry_id:
            continue

        old_uid = entity_entry.unique_id or ""
        if not old_uid.startswith(prefix):
            continue

        # Skip if already migrated (contains home_id)
        if old_uid.startswith(already_migrated_prefix):
            continue

        new_uid = None
        rest = old_uid[len(prefix) :]  # everything after "tado_ce_"

        # --- 1. Hub-level specific renames ---
        if rest in _UID_RENAME_MAP:
            new_uid = f"{prefix}{_UID_RENAME_MAP[rest].format(hid=hid)}"

        # --- 2. Calendar: schedule_{zid} → {hid}_zone_{zid}_schedule ---
        elif rest.startswith("schedule_"):
            zid = rest[len("schedule_") :]
            if zid.isdigit():
                new_uid = f"{prefix}{hid}_zone_{zid}_schedule"

        # --- 3. Zone-level entities: zone_{zid}_{descriptor} ---
        elif rest.startswith("zone_"):
            m = re.match(r"^zone_(\d+)_(.+)$", rest)
            if m:
                zid, descriptor = m.group(1), m.group(2)
                if descriptor in _UID_ZONE_RENAME_MAP:
                    new_uid = f"{prefix}{hid}_zone_{zid}_{_UID_ZONE_RENAME_MAP[descriptor]}"
                else:
                    # Generic: just insert {hid}
                    new_uid = f"{prefix}{hid}_zone_{zid}_{descriptor}"

        # --- 4. Zone buttons without zone_ prefix: {zid}_X ---
        elif not rest.startswith("zone_"):
            # Check for zone buttons: {zid}_refresh_schedule, {zid}_boost, {zid}_smart_boost
            for btn_suffix in _UID_ZONE_BUTTON_ADD_SEGMENT:
                if rest.endswith(f"_{btn_suffix}"):
                    zid_part = rest[: -(len(btn_suffix) + 1)]
                    if zid_part.isdigit():
                        new_uid = f"{prefix}{hid}_zone_{zid_part}_{btn_suffix}"
                        break

            # Timer buttons: {zone_name}_timer_{dur}min
            if new_uid is None:
                tm = re.match(r"^(.+)_timer_(\d+)min$", rest)
                if tm:
                    zname_slug = tm.group(1)
                    dur = tm.group(2)
                    zid = zone_name_to_id.get(zname_slug)  # type: ignore[assignment]
                    if zid:
                        new_uid = f"{prefix}{hid}_zone_{zid}_timer_{dur}min"
                    else:
                        _LOGGER.warning(
                            "  Timer button migration: could not resolve zone_name '%s' to zone_id for %s",
                            zname_slug,
                            old_uid,
                        )

            # Device sensors/switches: {serial}_battery, {serial}_connection, {serial}_child_lock
            if new_uid is None:
                for dev_suffix in ("_battery", "_connection", "_child_lock"):
                    if rest.endswith(dev_suffix):
                        serial = rest[: -(len(dev_suffix))]
                        if serial and not serial.isdigit():
                            # Serial numbers are alphanumeric, not pure digits (digits = zone_id)
                            new_uid = f"{prefix}{hid}_device_{serial}{dev_suffix}"
                            break

        # --- 5. Generic fallback: insert {hid} after tado_ce_ ---
        if new_uid is None:
            new_uid = f"{prefix}{hid}_{rest}"

        # Apply migration
        if new_uid != old_uid:
            try:
                entity_registry.async_update_entity(
                    entity_id,
                    new_unique_id=new_uid,
                )
                migrated += 1
                _LOGGER.debug("  Migrated UID: %s -> %s", old_uid, new_uid)
            except Exception as e:
                _LOGGER.warning("  Failed to migrate %s: %s", old_uid, e)

    return migrated


def cleanup_duplicate_devices(hass: HomeAssistant, home_id: str) -> None:
    """Cleanup duplicate hub and zone devices after identifier migration.

    Handles the device registry layer (identifiers), which is separate from
    entity unique_id migration. Covers:
      tado_ce_hub → tado_ce_hub_{home_id},
      tado_ce_zone_{id} → tado_ce_{home_id}_zone_{id}.
    All async_update_entity calls are wrapped in try/except.

    If migration failed or was interrupted, we might have both old and new
    device identifiers. This function merges duplicates by keeping the device
    with more entities.

    Args:
        hass: Home Assistant instance
        home_id: The home ID for this config entry
    """
    from homeassistant.helpers import device_registry as dr
    from homeassistant.helpers import entity_registry as er

    device_registry = dr.async_get(hass)
    entity_registry = er.async_get(hass)

    def count_device_entities(device_id: str) -> int:
        """Count entities linked to a device."""
        return len([e for e in entity_registry.entities.values() if e.device_id == device_id])

    # --- Hub device cleanup ---
    old_hub_identifier = "tado_ce_hub"
    new_hub_identifier = f"tado_ce_hub_{home_id}"

    old_hub = device_registry.async_get_device(identifiers={(DOMAIN, old_hub_identifier)})
    new_hub = device_registry.async_get_device(identifiers={(DOMAIN, new_hub_identifier)})

    if old_hub and new_hub:
        # Both exist - need to merge safely to preserve entity links
        old_entity_count = count_device_entities(old_hub.id)
        new_entity_count = count_device_entities(new_hub.id)

        _LOGGER.warning(
            "Found duplicate hub devices: %s (%s entities) and %s (%s entities). Merging...",
            old_hub_identifier,
            old_entity_count,
            new_hub_identifier,
            new_entity_count,
        )

        if old_entity_count >= new_entity_count:
            # Keep old (has more or equal entities)
            for entity in list(entity_registry.entities.values()):
                if entity.device_id == new_hub.id:
                    try:
                        entity_registry.async_update_entity(entity.entity_id, device_id=old_hub.id)
                    except Exception as e:
                        _LOGGER.warning("Could not move entity %s to old hub: %s", entity.entity_id, e)

            try:
                device_registry.async_remove_device(new_hub.id)
                _LOGGER.info("Removed empty new hub device: %s", new_hub_identifier)
            except Exception as e:
                _LOGGER.warning("Could not remove new hub device: %s", e)

            device_registry.async_update_device(old_hub.id, new_identifiers={(DOMAIN, new_hub_identifier)})
            _LOGGER.info("Kept old hub (%s entities), updated identifier to %s", old_entity_count, new_hub_identifier)
        else:
            # Keep new (has more entities)
            for entity in list(entity_registry.entities.values()):
                if entity.device_id == old_hub.id:
                    try:
                        entity_registry.async_update_entity(entity.entity_id, device_id=new_hub.id)
                    except Exception as e:
                        _LOGGER.warning("Could not move entity %s to new hub: %s", entity.entity_id, e)

            try:
                device_registry.async_remove_device(old_hub.id)
                _LOGGER.info("Removed empty old hub device: %s", old_hub_identifier)
            except Exception as e:
                _LOGGER.warning("Could not remove old hub device: %s", e)

            _LOGGER.info("Kept new hub (%s entities)", new_entity_count)
    elif old_hub and not new_hub:
        # Only old exists - migration didn't run, update it now
        _LOGGER.info(
            "Found old hub device without new one. Migrating: %s -> %s",
            old_hub_identifier,
            new_hub_identifier,
        )
        device_registry.async_update_device(
            old_hub.id,
            new_identifiers={(DOMAIN, new_hub_identifier)},
        )

    # --- Zone device cleanup ---
    zone_pattern = re.compile(r"tado_ce_zone_(\d+)")

    for device in list(device_registry.devices.values()):
        for id_tuple in device.identifiers:
            if len(id_tuple) != 2:
                continue
            domain, identifier = id_tuple
            if domain == DOMAIN:
                match = zone_pattern.match(identifier)
                if match:
                    zone_id = match.group(1)
                    new_zone_identifier = f"tado_ce_{home_id}_zone_{zone_id}"

                    new_zone = device_registry.async_get_device(identifiers={(DOMAIN, new_zone_identifier)})

                    if new_zone:
                        # Both exist - keep the one with more entities
                        old_count = count_device_entities(device.id)
                        new_count = count_device_entities(new_zone.id)

                        _LOGGER.warning(
                            "Found duplicate zone devices: %s (%s entities) and %s (%s entities). Merging...",
                            identifier,
                            old_count,
                            new_zone_identifier,
                            new_count,
                        )

                        if old_count >= new_count:
                            for entity in list(entity_registry.entities.values()):
                                if entity.device_id == new_zone.id:
                                    try:
                                        entity_registry.async_update_entity(entity.entity_id, device_id=device.id)
                                    except Exception as e:
                                        _LOGGER.warning("Could not move entity %s: %s", entity.entity_id, e)
                            try:
                                device_registry.async_remove_device(new_zone.id)
                            except Exception as e:
                                _LOGGER.warning("Could not remove new zone device: %s", e)
                            device_registry.async_update_device(
                                device.id,
                                new_identifiers={(DOMAIN, new_zone_identifier)},
                            )
                            _LOGGER.info(
                                "Kept old zone (%s entities), updated to %s",
                                old_count,
                                new_zone_identifier,
                            )
                        else:
                            for entity in list(entity_registry.entities.values()):
                                if entity.device_id == device.id:
                                    try:
                                        entity_registry.async_update_entity(entity.entity_id, device_id=new_zone.id)
                                    except Exception as e:
                                        _LOGGER.warning("Could not move entity %s: %s", entity.entity_id, e)
                            try:
                                device_registry.async_remove_device(device.id)
                            except Exception as e:
                                _LOGGER.warning("Could not remove old zone device: %s", e)
                            _LOGGER.info("Kept new zone (%s entities)", new_count)
                    else:
                        # Only old exists - migrate it
                        _LOGGER.info("Migrating zone device: %s -> %s", identifier, new_zone_identifier)
                        device_registry.async_update_device(device.id, new_identifiers={(DOMAIN, new_zone_identifier)})


async def async_handle_test_mode_transition(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> None:
    """Check if Test Mode was just disabled and refresh rate limit data.

    When Test Mode is disabled, triggers an API call to refresh rate limit
    data with real values instead of relying on backup.
    """
    import json

    from .const import get_data_file

    home_id = entry.data.get("home_id")
    ratelimit_path = get_data_file("ratelimit", home_id)

    prev_test_mode = False
    path_exists = await hass.async_add_executor_job(ratelimit_path.exists)
    if path_exists:
        content = await hass.async_add_executor_job(ratelimit_path.read_text)
        ratelimit_data = json.loads(content)
        prev_test_mode = ratelimit_data.get("test_mode", False)

    new_test_mode = entry.options.get("test_mode_enabled", False)
    _LOGGER.debug("Test Mode transition check: prev=%s, new=%s", prev_test_mode, new_test_mode)

    if prev_test_mode and not new_test_mode:
        _LOGGER.info("Tado CE: Test Mode disabled - triggering API refresh for real rate limit data")

        entry_data = getattr(entry, "runtime_data", None)
        client = entry_data.api_client if entry_data else None

        if client is None:
            _LOGGER.warning("No API client available for entry %s", entry.entry_id)
        else:
            try:
                await client.get_me()
                _LOGGER.info("Tado CE: API refresh completed - rate limit data updated with real values")
            except Exception as e:
                _LOGGER.warning("Tado CE: API refresh failed (will use backup): %s", e)


async def async_deduplicate_entries(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> bool:
    """Check for and remove duplicate config entries.

    Groups by unique_id — multi-home entries with different unique_ids
    are NOT duplicates.

    Returns True if this entry should continue setup, False if it's a duplicate
    that should abort.
    """
    from collections import defaultdict

    all_entries = hass.config_entries.async_entries(DOMAIN)

    # Group entries by unique_id
    entries_by_uid: dict[str | None, list[Any]] = defaultdict(list)
    for e in all_entries:
        entries_by_uid[e.unique_id].append(e)

    # Find the group that THIS entry belongs to
    my_group = entries_by_uid.get(entry.unique_id, [entry])

    if len(my_group) > 1:
        _LOGGER.warning(
            "Found %d entries with same unique_id '%s' - checking for duplicates",
            len(my_group),
            entry.unique_id,
        )
        _LOGGER.info("  Entries in group: %s", [(e.entry_id, e.version) for e in my_group])

        # Sort by version (descending), then by entry_id for deterministic ordering
        entries_by_version = sorted(
            my_group,
            key=lambda e: (getattr(e, "version", 0), e.entry_id),
            reverse=True,
        )

        keeper_entry_id = entries_by_version[0].entry_id
        _LOGGER.info("  Keeper entry: %s", keeper_entry_id)

        # If current entry is NOT the one to keep, abort this setup
        if entry.entry_id != keeper_entry_id:
            _LOGGER.warning(
                "Current entry %s (version %s) is duplicate of unique_id '%s'. "
                "Aborting setup - will be removed by keeper entry.",
                entry.entry_id,
                entry.version,
                entry.unique_id,
            )
            return False

        # Current entry IS the keeper - remove all others in this group
        cleanup_key = f"duplicate_cleanup_{keeper_entry_id}"
        if cleanup_key not in _duplicate_cleanup_done:
            _duplicate_cleanup_done.add(cleanup_key)

            _LOGGER.info(
                "Entry %s is keeper for unique_id '%s' - removing %d duplicates",
                keeper_entry_id,
                entry.unique_id,
                len(entries_by_version) - 1,
            )

            for old_entry in entries_by_version[1:]:
                _LOGGER.warning(
                    "Removing duplicate entry %s (version %s, unique_id '%s')",
                    old_entry.entry_id,
                    getattr(old_entry, "version", "unknown"),
                    old_entry.unique_id,
                )
                try:
                    await hass.config_entries.async_remove(old_entry.entry_id)
                    _LOGGER.info("Successfully removed duplicate entry %s", old_entry.entry_id)
                except Exception as e:
                    _LOGGER.exception("Failed to remove duplicate entry %s", old_entry.entry_id)

            _LOGGER.info(
                "Duplicate cleanup complete for unique_id '%s'. Keeper: %s",
                entry.unique_id,
                keeper_entry_id,
            )
    elif len(all_entries) > 1:
        _LOGGER.info(
            "Found %d Tado CE entries with %d distinct unique_ids — multi-home setup, no duplicates",
            len(all_entries),
            len(entries_by_uid),
        )

    return True


def detect_and_migrate_old_unique_ids(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    home_id: str,
) -> int:
    """Runtime fallback: detect entities with old-format unique_ids.

    Called from async_setup_entry() BEFORE platform forwarding.
    If Phase 0b migration was skipped (e.g., user restored a backup without
    running migration), entities may still have old-format unique_ids that
    lack {home_id}. This causes silent collisions in multi-home setups.

    Strategy:
    1. Scan all entities for this config_entry
    2. If any unique_id starts with "tado_ce_" but NOT "tado_ce_{home_id}_",
       it's an old-format unique_id
    3. Trigger _migrate_entity_unique_ids() retroactively
    4. Log clearly what happened

    Returns:
        Number of entities migrated (0 if all already migrated)
    """
    from homeassistant.helpers import entity_registry as er

    entity_registry = er.async_get(hass)
    prefix = "tado_ce_"
    migrated_prefix = f"tado_ce_{home_id}_"

    # Count old-format entities for this config entry
    old_format_count = 0
    for entity_entry in entity_registry.entities.values():
        if entity_entry.config_entry_id != config_entry.entry_id:
            continue
        uid = entity_entry.unique_id or ""
        if uid.startswith(prefix) and not uid.startswith(migrated_prefix):
            old_format_count += 1

    if old_format_count == 0:
        return 0

    _LOGGER.warning(
        "Found %d entities with old-format unique_ids (missing home_id) "
        "for config entry %s (home_id=%s). Running retroactive migration...",
        old_format_count,
        config_entry.entry_id,
        home_id,
    )

    from .data_loader import DataLoader

    migration_loader = DataLoader(str(home_id))
    migrated = _migrate_entity_unique_ids(
        hass,
        config_entry,
        str(home_id),
        data_loader=migration_loader,
    )

    if migrated > 0:
        _LOGGER.warning(
            "Retroactively migrated %d entity unique_ids to v3.0 format "
            "(home_id=%s). This entry may have skipped migration.",
            migrated,
            home_id,
        )
    else:
        _LOGGER.error(
            "Found %d old-format entities but migration migrated 0. "
            "Some entities may have unique_id conflicts. Check entity registry "
            "for duplicates. home_id=%s, entry=%s",
            old_format_count,
            home_id,
            config_entry.entry_id,
        )

    return migrated
