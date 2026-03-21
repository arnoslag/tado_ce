"""Manage state capture and restoration for zone overlays.

Follows the existing manager pattern (SmartComfortManager, AdaptivePreheatManager):
a coordinator-owned manager class that encapsulates all state capture/restore logic.

Design doc: .kiro/specs/state-restoration-enhancement/design.md
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from .config_manager import ConfigurationManager
    from .coordinator import TadoDataUpdateCoordinator
    from .data_loader import DataLoader

_LOGGER = logging.getLogger(__name__)

# Stale state threshold — purge captured states older than this on load
_STALE_THRESHOLD = timedelta(hours=24)

# Storage base name (added to PER_HOME_FILES in const.py)
_STORAGE_BASE_NAME = "state_restore"


@dataclass
class CapturedState:
    """Represent a captured zone state before an overlay operation."""

    zone_id: str
    entity_type: str  # "climate_heating", "climate_ac", "water_heater"
    temperature: float | None = None
    hvac_mode: str | None = None  # HVACMode value as string
    power: str | None = None  # "ON" / "OFF"
    overlay_type: str | None = None  # "MANUAL" / "TIMER" / "TADO_MODE" / None (schedule)
    termination: dict[str, Any] | None = None  # Full termination dict from API
    fan_mode: str | None = None  # AC only — raw API fanLevel value
    swing_mode: str | None = None  # AC only — raw API verticalSwing value
    horizontal_swing_mode: str | None = None  # AC only — raw API horizontalSwing value
    captured_at: str = ""  # ISO 8601 timestamp
    source: str = ""  # What triggered capture: "set_open_window_mode", "set_timer", etc.


def _state_to_dict(state: CapturedState) -> dict[str, Any]:
    """Serialise CapturedState to a JSON-compatible dict."""
    return {
        "zone_id": state.zone_id,
        "entity_type": state.entity_type,
        "temperature": state.temperature,
        "hvac_mode": state.hvac_mode,
        "power": state.power,
        "overlay_type": state.overlay_type,
        "termination": state.termination,
        "fan_mode": state.fan_mode,
        "swing_mode": state.swing_mode,
        "horizontal_swing_mode": state.horizontal_swing_mode,
        "captured_at": state.captured_at,
        "source": state.source,
    }


def _state_from_dict(data: dict[str, Any]) -> CapturedState:
    """Deserialise a dict into a CapturedState."""
    return CapturedState(
        zone_id=data.get("zone_id", ""),
        entity_type=data.get("entity_type", ""),
        temperature=data.get("temperature"),
        hvac_mode=data.get("hvac_mode"),
        power=data.get("power"),
        overlay_type=data.get("overlay_type"),
        termination=data.get("termination"),
        fan_mode=data.get("fan_mode"),
        swing_mode=data.get("swing_mode"),
        horizontal_swing_mode=data.get("horizontal_swing_mode"),
        captured_at=data.get("captured_at", ""),
        source=data.get("source", ""),
    )


def _make_store_key(zone_id: str, entity_type: str) -> str:
    """Build storage key from zone_id and entity_type."""
    return f"{zone_id}:{entity_type}"


class StateRestoreManager:
    """Manage state capture and restoration for zone overlays."""

    def __init__(
        self,
        hass: HomeAssistant,
        config_manager: ConfigurationManager,
        data_loader: DataLoader,
    ) -> None:
        """Initialize the StateRestoreManager."""
        self._hass = hass
        self._config_manager = config_manager
        self._data_loader = data_loader
        self._coordinator: TadoDataUpdateCoordinator | None = None
        self._store: dict[str, CapturedState] = {}
        self._lock = asyncio.Lock()
        # Timer expiry detection: zone_id -> had_overlay in previous poll
        self._previous_overlay_states: dict[str, bool] = {}

    def set_coordinator(self, coordinator: TadoDataUpdateCoordinator) -> None:
        """Set coordinator back-reference (resolves chicken-and-egg dependency)."""
        self._coordinator = coordinator

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def async_setup(self) -> None:
        """Load persisted state from disk and purge stale entries."""
        raw = await self._hass.async_add_executor_job(
            self._data_loader._load_json, _STORAGE_BASE_NAME,
        )
        if not raw or not isinstance(raw, dict):
            _LOGGER.debug("State Restore: No persisted state found")
            return

        now = datetime.now(UTC)
        loaded = 0
        purged = 0
        for key, entry in raw.items():
            if not isinstance(entry, dict):
                continue
            state = _state_from_dict(entry)
            # Purge entries older than 24 hours
            if state.captured_at:
                try:
                    captured_dt = datetime.fromisoformat(state.captured_at)
                    if now - captured_dt > _STALE_THRESHOLD:
                        purged += 1
                        continue
                except (ValueError, TypeError):
                    pass  # Keep entries with unparseable timestamps
            self._store[key] = state
            loaded += 1

        if loaded or purged:
            _LOGGER.info(
                "State Restore: Loaded %d captured state(s), purged %d stale",
                loaded, purged,
            )
        # Persist after purge so stale entries are removed from disk
        if purged:
            await self._async_persist()

    async def async_shutdown(self) -> None:
        """Persist state to disk on HA shutdown / config entry unload."""
        await self._async_persist()
        _LOGGER.debug("State Restore: Shutdown — state persisted")

    # ------------------------------------------------------------------
    # Core operations
    # ------------------------------------------------------------------

    async def capture(
        self,
        zone_id: str,
        entity_type: str,
        source: str,
    ) -> bool:
        """Capture current zone state before overlay operation.

        Returns True if state was captured, False if existing capture preserved
        (overwrite rule: preserve original pre-overlay state).
        """
        key = _make_store_key(zone_id, entity_type)

        async with self._lock:
            # Overwrite rule (EC2): preserve existing capture
            if key in self._store:
                _LOGGER.debug(
                    "State Restore: Existing capture preserved for %s (source=%s)",
                    key, self._store[key].source,
                )
                return False

            if not self._coordinator:
                _LOGGER.warning("State Restore: No coordinator — cannot capture for %s", key)
                return False

            coord_data = self._coordinator.data or {}
            zone_states = (coord_data.get("zones") or {}).get("zoneStates") or {}
            zone_data = zone_states.get(zone_id) or zone_states.get(str(zone_id))

            if not zone_data:
                _LOGGER.debug("State Restore: No zone data for zone %s", zone_id)
                return False

            state = self._extract_state(zone_id, entity_type, zone_data, source)
            self._store[key] = state
            await self._async_persist()

            _LOGGER.debug(
                "State Restore: Captured %s — temp=%s, power=%s, overlay=%s, source=%s",
                key, state.temperature, state.power, state.overlay_type, source,
            )
            return True

    async def restore(
        self,
        zone_id: str,
        entity_type: str,
    ) -> CapturedState | None:
        """Consume and return captured state for restoration."""
        key = _make_store_key(zone_id, entity_type)

        async with self._lock:
            state = self._store.pop(key, None)
            if state:
                await self._async_persist()
                _LOGGER.debug("State Restore: Restored (consumed) %s", key)
            return state

    def get_captured(
        self,
        zone_id: str,
        entity_type: str,
    ) -> CapturedState | None:
        """Peek at captured state without consuming (for diagnostics/events)."""
        key = _make_store_key(zone_id, entity_type)
        return self._store.get(key)

    async def clear(self, zone_id: str, entity_type: str) -> None:
        """Explicitly clear a captured state."""
        key = _make_store_key(zone_id, entity_type)
        async with self._lock:
            if self._store.pop(key, None):
                await self._async_persist()
                _LOGGER.debug("State Restore: Cleared %s", key)

    async def clear_zone(self, zone_id: str) -> None:
        """Clear all captured states for a zone (all entity types)."""
        prefix = f"{zone_id}:"
        async with self._lock:
            keys_to_remove = [k for k in self._store if k.startswith(prefix)]
            if keys_to_remove:
                for k in keys_to_remove:
                    del self._store[k]
                await self._async_persist()
                _LOGGER.debug("State Restore: Cleared zone %s (%d entries)", zone_id, len(keys_to_remove))

    async def clear_all(self) -> None:
        """Clear all captured states (e.g. on Away → Home transition)."""
        async with self._lock:
            if self._store:
                count = len(self._store)
                self._store.clear()
                await self._async_persist()
                _LOGGER.info("State Restore: Cleared all %d captured state(s)", count)


    def get_diagnostics_summary(self) -> list[dict[str, str]]:
        """Return privacy-safe summary of captured states for diagnostics."""
        return [
            {
                "zone_id": state.zone_id,
                "entity_type": state.entity_type,
                "captured_at": state.captured_at,
                "source": state.source,
            }
            for state in self._store.values()
        ]


    # ------------------------------------------------------------------
    # Timer expiry detection (called from coordinator poll cycle)
    # ------------------------------------------------------------------

    def on_poll_update(self, coordinator_data: dict[str, Any]) -> None:
        """Detect timer expiration and fire restoration events.

        Called from coordinator._async_update_data after each poll.
        Compares overlay states between polls to detect overlay disappearance.
        """
        zone_states = (coordinator_data.get("zones") or {}).get("zoneStates") or {}

        for key, captured in list(self._store.items()):
            zone_id = captured.zone_id
            zone_data = zone_states.get(zone_id) or zone_states.get(str(zone_id))

            has_overlay = bool(zone_data and zone_data.get("overlay"))
            had_overlay = self._previous_overlay_states.get(zone_id, False)

            # Overlay disappeared → timer expired or API-side removal
            if had_overlay and not has_overlay and key in self._store:
                _LOGGER.info(
                    "State Restore: Overlay disappeared for zone %s — firing restoration event",
                    zone_id,
                )
                self._fire_restoration_event(captured, zone_data)
                # Schedule transition reset: clear captured state after event
                # (done outside lock since on_poll_update is sync)
                self._store.pop(key, None)
                self._hass.async_create_task(self._async_persist())

        # Update previous overlay states for next poll cycle
        for zone_id_str in zone_states:
            zd = zone_states[zone_id_str]
            self._previous_overlay_states[zone_id_str] = bool(zd and zd.get("overlay"))

    def _fire_restoration_event(
        self,
        captured: CapturedState,
        zone_data: dict[str, Any] | None,
    ) -> None:
        """Fire tado_ce_state_restoration_available event."""
        zone_name = ""
        if zone_data:
            zone_name = zone_data.get("name", "")

        self._hass.bus.async_fire(
            "tado_ce_state_restoration_available",
            {
                "zone_id": captured.zone_id,
                "zone_name": zone_name,
                "entity_type": captured.entity_type,
                "captured_temperature": captured.temperature,
                "captured_hvac_mode": captured.hvac_mode,
                "source": captured.source,
            },
        )

    # ------------------------------------------------------------------
    # State extraction from coordinator zone data
    # ------------------------------------------------------------------

    def _extract_state(
        self,
        zone_id: str,
        entity_type: str,
        zone_data: dict[str, Any],
        source: str,
    ) -> CapturedState:
        """Extract current zone state into a CapturedState."""
        setting = zone_data.get("setting") or {}
        overlay = zone_data.get("overlay")
        overlay_type = zone_data.get("overlayType")  # "MANUAL" / "TIMER" / "TADO_MODE" / None

        power = setting.get("power")
        temperature = (setting.get("temperature") or {}).get("celsius")

        # Termination info from overlay
        termination: dict[str, Any] | None = None
        if overlay and isinstance(overlay, dict):
            termination = overlay.get("termination")

        # HVAC mode (climate entities only)
        hvac_mode: str | None = None
        if entity_type in ("climate_heating", "climate_ac"):
            if entity_type == "climate_ac":
                hvac_mode = setting.get("mode")  # COOL / HEAT / DRY / FAN / AUTO
            elif power == "ON":
                # Heating: derive from power + overlay
                hvac_mode = "heat" if overlay_type == "MANUAL" else "auto"
            elif overlay_type == "MANUAL":
                hvac_mode = "off"
            else:
                hvac_mode = "auto"

        # AC-specific: fan and swing
        fan_mode: str | None = None
        swing_mode: str | None = None
        horizontal_swing_mode: str | None = None
        if entity_type == "climate_ac":
            fan_mode = setting.get("fanLevel") or setting.get("fanSpeed")
            swing_mode = setting.get("verticalSwing")
            horizontal_swing_mode = setting.get("horizontalSwing")

        return CapturedState(
            zone_id=zone_id,
            entity_type=entity_type,
            temperature=temperature,
            hvac_mode=hvac_mode,
            power=power,
            overlay_type=overlay_type,
            termination=termination,
            fan_mode=fan_mode,
            swing_mode=swing_mode,
            horizontal_swing_mode=horizontal_swing_mode,
            captured_at=datetime.now(UTC).isoformat(),
            source=source,
        )

    # ------------------------------------------------------------------
    # Persistence helpers
    # ------------------------------------------------------------------

    async def _async_persist(self) -> None:
        """Persist current store to disk via DataLoader."""
        data = {key: _state_to_dict(state) for key, state in self._store.items()}
        try:
            await self._hass.async_add_executor_job(self._save_to_disk, data)
        except Exception:
            _LOGGER.exception("State Restore: Failed to persist state")

    def _save_to_disk(self, data: dict[str, Any]) -> None:
        """Write state data to JSON file (blocking I/O)."""
        import json

        from .const import get_data_file

        home_id = self._data_loader.home_id
        file_path = get_data_file(_STORAGE_BASE_NAME, home_id)
        try:
            file_path.parent.mkdir(parents=True, exist_ok=True)
            with file_path.open("w") as f:
                json.dump(data, f, indent=2)
            self._data_loader.update_cache(_STORAGE_BASE_NAME, data)
        except Exception:
            _LOGGER.exception("State Restore: Failed to write %s", file_path)
