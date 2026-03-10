"""Tado CE heating cycle storage — per-home persistence."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .heating_models import HeatingCycle

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)


class HeatingCycleStorage:
    """Persist heating cycles to disk with multi-home support and atomic writes."""

    def __init__(self, hass: HomeAssistant, home_id: str) -> None:
        """Initialize storage with home ID."""
        self._hass = hass
        self._home_id = home_id
        self._storage_path = Path(
            hass.config.path(
                f".storage/tado_ce/heating_cycle_history_{home_id}.json",
            ),
        )
        self._data: dict[str, Any] = {"version": "1.0", "zones": {}}

    async def async_load(self) -> None:
        """Load cycle data from disk with migration support."""
        try:
            # Try new path first (with home_id)
            path_exists = await self._hass.async_add_executor_job(
                self._storage_path.exists,
            )
            if path_exists:
                content = await self._hass.async_add_executor_job(
                    self._storage_path.read_text,
                )
                loaded_data = json.loads(content)
                self._data = self._migrate_data_format(loaded_data)
                _LOGGER.debug(
                    "Loaded heating cycle history for home %s: %d zones",
                    self._home_id,
                    len(self._data.get("zones", {})),
                )
            else:
                _LOGGER.debug("No existing heating cycle history found")

        except json.JSONDecodeError:
            _LOGGER.exception("Corrupted heating cycle storage file")
            # Rename corrupted file
            corrupted_path = self._storage_path.with_suffix(".corrupted")
            try:
                await self._hass.async_add_executor_job(
                    self._storage_path.rename,
                    corrupted_path,
                )
                _LOGGER.info("Renamed corrupted file to %s", corrupted_path)
            except FileNotFoundError:
                pass
            self._data = {"version": "1.0", "zones": {}}
        except OSError:
            _LOGGER.exception("Failed to load heating cycle storage")
            self._data = {"version": "1.0", "zones": {}}

    def _migrate_data_format(self, loaded_data: dict[str, Any]) -> dict[str, Any]:
        """Migrate old data format to new format.

        Old format: {"zone_id": [cycles], ...}
        New format: {"version": "1.0", "zones": {"zone_id": {"cycles": [...]}, ...}}
        """
        # Check if already new format
        if "version" in loaded_data and "zones" in loaded_data:
            return loaded_data

        # Migrate old format
        _LOGGER.info("Migrating heating cycle data from old format")
        new_data = {"version": "1.0", "zones": {}}

        for zone_id, cycles in loaded_data.items():
            if isinstance(cycles, list):
                new_data["zones"][zone_id] = {"cycles": cycles}  # type: ignore[index]
                _LOGGER.debug(
                    "Migrated zone %s with %d cycles",
                    zone_id,
                    len(cycles),
                )

        return new_data

    async def save_cycle(self, zone_id: str, cycle: HeatingCycle) -> None:
        """Save completed cycle for a zone."""
        if zone_id not in self._data["zones"]:
            self._data["zones"][zone_id] = {"cycles": []}

        self._data["zones"][zone_id]["cycles"].append(cycle.to_dict())

        _LOGGER.debug(
            "Saved cycle for zone %s: %s -> %s (completed=%s, interrupted=%s)",
            zone_id,
            cycle.start_time.isoformat(),
            cycle.end_time.isoformat() if cycle.end_time else "active",
            cycle.completed,
            cycle.interrupted,
        )

        # Cleanup old cycles (keep 2x rolling window)
        await self._cleanup_old_cycles(zone_id)

        # Save to disk (atomic write)
        await self._save_to_disk()

    async def get_cycles(
        self,
        zone_id: str,
        window_days: int = 7,
    ) -> list[HeatingCycle]:
        """Get cycles for a zone within rolling window."""
        if zone_id not in self._data["zones"]:
            return []

        cutoff = datetime.now(UTC) - timedelta(days=window_days)
        cycles = []

        for cycle_dict in self._data["zones"][zone_id]["cycles"]:
            cycle = HeatingCycle.from_dict(cycle_dict)
            # Only include completed, non-interrupted cycles within window
            if cycle.start_time >= cutoff and cycle.completed and not cycle.interrupted:
                cycles.append(cycle)

        return cycles

    async def get_active_cycles(self) -> dict[str, HeatingCycle]:
        """Get all active cycles (for resume after restart)."""
        active = {}
        for zone_id, zone_data in self._data["zones"].items():
            for cycle_dict in zone_data["cycles"]:
                cycle = HeatingCycle.from_dict(cycle_dict)
                if not cycle.completed and not cycle.interrupted:
                    active[zone_id] = cycle
                    break  # Only one active cycle per zone

        if active:
            _LOGGER.info("Found %d active cycles to resume", len(active))

        return active

    async def get_all_zone_ids(self) -> list[str]:
        """Get all zone IDs with stored cycle data."""
        return list(self._data["zones"].keys())

    async def _cleanup_old_cycles(self, zone_id: str) -> None:
        """Remove cycles older than 2x rolling window."""
        cutoff = datetime.now(UTC) - timedelta(days=14)  # 2x default window

        cycles = self._data["zones"][zone_id]["cycles"]
        original_count = len(cycles)

        self._data["zones"][zone_id]["cycles"] = [
            c for c in cycles if datetime.fromisoformat(c["start_time"]) >= cutoff
        ]

        removed_count = original_count - len(self._data["zones"][zone_id]["cycles"])
        if removed_count > 0:
            _LOGGER.debug(
                "Cleaned up %d old cycles for zone %s",
                removed_count,
                zone_id,
            )

    async def _save_to_disk(self) -> None:
        """Save cycle data to disk with atomic write."""
        try:
            await self._hass.async_add_executor_job(
                lambda: self._storage_path.parent.mkdir(parents=True, exist_ok=True),
            )

            # Write to temp file
            temp_path = self._storage_path.with_suffix(".tmp")
            content = json.dumps(self._data, indent=2)
            await self._hass.async_add_executor_job(
                temp_path.write_text,
                content,
            )

            # Atomic move
            await self._hass.async_add_executor_job(
                temp_path.replace,
                self._storage_path,
            )

            _LOGGER.debug("Saved heating cycle history to %s", self._storage_path)
        except OSError:
            _LOGGER.exception("Failed to save heating cycle history")
