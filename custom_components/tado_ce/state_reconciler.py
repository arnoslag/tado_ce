"""Tado CE State Reconciler — merge local and cloud data sources."""

from __future__ import annotations

from datetime import timedelta
import logging
from typing import TYPE_CHECKING, Any, Final

from homeassistant.util import dt as dt_util

from .const import HOMEKIT_STALENESS_THRESHOLD

if TYPE_CHECKING:
    from .homekit_provider import HomeKitLocalProvider

_LOGGER = logging.getLogger(__name__)

# Re-export for backward compatibility (used in tests)
LOCAL_STALENESS_THRESHOLD = HOMEKIT_STALENESS_THRESHOLD

# After a local write, ignore conflicting cloud values for this duration
WRITE_PROTECTION_WINDOW: Final[timedelta] = timedelta(minutes=3)


class StateReconciler:
    """Merge local HomeKit data with cloud API data."""

    def __init__(self) -> None:
        """Initialize the StateReconciler."""
        self._local_provider: HomeKitLocalProvider | None = None
        self._write_timestamps: dict[str, Any] = {}

    @property
    def local_provider(self) -> HomeKitLocalProvider | None:
        """Return the current local provider."""
        return self._local_provider

    @local_provider.setter
    def local_provider(self, provider: HomeKitLocalProvider | None) -> None:
        """Set the local provider."""
        self._local_provider = provider

    def record_local_write(self, zone_id: str) -> None:
        """Record that a local write was made (for write protection window)."""
        self._write_timestamps[zone_id] = dt_util.utcnow()

    def _get_fresh_local_value(
        self,
        zone_id: str,
        getter: str,
    ) -> tuple[float | int | None, bool]:
        """Get a fresh value from local provider.

        Args:
            zone_id: Zone identifier.
            getter: Method name on local_provider (e.g. "get_temperature").

        Returns:
            (value, is_fresh) — value is None if unavailable or stale.
        """
        if not self._local_provider or not self._local_provider.is_connected:
            _LOGGER.debug(
                "Zone %s %s: HomeKit not available (provider=%s, connected=%s)",
                zone_id, getter,
                self._local_provider is not None,
                self._local_provider.is_connected if self._local_provider else False,
            )
            return None, False
        method = getattr(self._local_provider, getter)
        value, timestamp = method(zone_id)
        if value is None or timestamp is None:
            _LOGGER.debug(
                "Zone %s %s: HomeKit cache empty (value=%s, ts=%s)",
                zone_id, getter, value, timestamp,
            )
            return None, False
        age = dt_util.utcnow() - timestamp
        if age >= HOMEKIT_STALENESS_THRESHOLD:
            _LOGGER.debug(
                "Zone %s %s: HomeKit cache STALE (value=%s, age=%.1fs, threshold=%.0fs)",
                zone_id, getter, value, age.total_seconds(),
                HOMEKIT_STALENESS_THRESHOLD.total_seconds(),
            )
            return None, False
        _LOGGER.debug(
            "Zone %s %s: HomeKit cache fresh (value=%s, age=%.1fs)",
            zone_id, getter, value, age.total_seconds(),
        )
        return value, True

    def merge_zone_temperature(
        self,
        zone_id: str,
        cloud_value: float | None,
        external_value: float | None = None,
    ) -> tuple[float | None, str]:
        """Return (merged_value, source_name).

        Priority: external > homekit (if fresh) > cloud.
        """
        if external_value is not None:
            _LOGGER.debug("Zone %s temp: external=%.1f → using external", zone_id, external_value)
            return external_value, "external"

        local_val, is_fresh = self._get_fresh_local_value(zone_id, "get_temperature")
        if is_fresh and local_val is not None:
            _LOGGER.debug(
                "Zone %s temp: cloud=%s, homekit=%s → using homekit",
                zone_id, cloud_value, local_val,
            )
            return local_val, "homekit"

        _LOGGER.debug(
            "Zone %s temp: cloud=%s, homekit not fresh → using cloud",
            zone_id, cloud_value,
        )
        return cloud_value, "cloud"

    def merge_zone_humidity(
        self,
        zone_id: str,
        cloud_value: float | None,
        external_value: float | None = None,
    ) -> tuple[float | None, str]:
        """Return (merged_value, source_name).

        Priority: external > homekit (if fresh) > cloud.
        """
        if external_value is not None:
            _LOGGER.debug("Zone %s humidity: external=%s → using external", zone_id, external_value)
            return external_value, "external"

        local_val, is_fresh = self._get_fresh_local_value(zone_id, "get_humidity")
        if is_fresh and local_val is not None:
            _LOGGER.debug(
                "Zone %s humidity: cloud=%s, homekit=%s → using homekit",
                zone_id, cloud_value, local_val,
            )
            return local_val, "homekit"

        _LOGGER.debug(
            "Zone %s humidity: cloud=%s, homekit not fresh → using cloud",
            zone_id, cloud_value,
        )
        return cloud_value, "cloud"

    def merge_zone_target_temperature(
        self,
        zone_id: str,
        cloud_value: float | None,
    ) -> tuple[float | None, str]:
        """Return (merged_value, source_name).

        Priority: homekit (if fresh) > cloud. No external sensor for target temp.
        """
        local_val, is_fresh = self._get_fresh_local_value(zone_id, "get_target_temperature")
        if is_fresh and local_val is not None:
            return local_val, "homekit"

        return cloud_value, "cloud"

    def merge_zone_hvac_state(
        self,
        zone_id: str,
        cloud_value: int | None,
    ) -> tuple[int | None, str]:
        """Return (merged_value, source_name).

        Priority: homekit (if fresh) > cloud. 0=Off, 1=Heat, 2=Cool.
        """
        local_val, is_fresh = self._get_fresh_local_value(zone_id, "get_hvac_state")
        if is_fresh and local_val is not None:
            return int(local_val), "homekit"

        return cloud_value, "cloud"

    def should_accept_cloud_value(self, zone_id: str) -> bool:
        """Check if cloud value should overwrite local cache.

        Returns False if a local write is still within the protection window.
        """
        last_write = self._write_timestamps.get(zone_id)
        if last_write is None:
            return True
        age = dt_util.utcnow() - last_write
        if age >= WRITE_PROTECTION_WINDOW:
            del self._write_timestamps[zone_id]
            return True
        _LOGGER.debug(
            "Write protection active for zone %s (%.0fs remaining)",
            zone_id,
            (WRITE_PROTECTION_WINDOW - age).total_seconds(),
        )
        return False
