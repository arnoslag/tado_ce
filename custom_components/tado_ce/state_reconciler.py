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
        # Track previous merge sources per zone for transition-only logging.
        # Key: "{zone_id}_{characteristic}" → source string.
        self._prev_sources: dict[str, str] = {}

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
        freshness_mode: str = "observed",
    ) -> tuple[float | int | None, bool]:
        """Get a fresh value from local provider.

        Args:
            zone_id: Zone identifier.
            getter: Method name on local_provider (e.g. "get_temperature").
            freshness_mode: Which cache timestamp to check against the
                staleness threshold. "observed" = last_observed_at (keeps
                stable readings valid). "changed" = last_changed_at
                (rejects cache entries that haven't seen a real value
                change within the threshold — needed for event-driven
                signals like target temperature and mode).

        Returns:
            (value, is_fresh) — is_fresh is False when value or the
            relevant timestamp is None, or its age exceeds the threshold.
        """
        if not self._local_provider or not self._local_provider.is_connected:
            return None, False
        method = getattr(self._local_provider, getter)
        result = method(zone_id)
        if not isinstance(result, tuple) or len(result) != 3:
            return None, False
        value, changed_at, observed_at = result
        if value is None:
            return None, False
        reference = changed_at if freshness_mode == "changed" else observed_at
        if reference is None:
            return None, False
        age = dt_util.utcnow() - reference
        if age >= HOMEKIT_STALENESS_THRESHOLD:
            return None, False
        return value, True

    def _log_source_transition(
        self,
        zone_id: str,
        characteristic: str,
        new_source: str,
        value: float | int | None,
    ) -> None:
        """Log only when the data source for a zone characteristic changes.

        Eliminates per-poll noise — only logs transitions like
        cloud→homekit or homekit→cloud.
        """
        key = f"{zone_id}_{characteristic}"
        prev_source = self._prev_sources.get(key)
        if prev_source != new_source:
            _LOGGER.debug(
                "Zone %s %s: source %s → %s (value=%s)",
                zone_id, characteristic,
                prev_source or "none", new_source, value,
            )
            self._prev_sources[key] = new_source

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
            self._log_source_transition(zone_id, "temp", "external", external_value)
            return external_value, "external"

        local_val, is_fresh = self._get_fresh_local_value(zone_id, "get_temperature")
        if is_fresh and local_val is not None:
            self._log_source_transition(zone_id, "temp", "homekit", local_val)
            return local_val, "homekit"

        self._log_source_transition(zone_id, "temp", "cloud", cloud_value)
        return cloud_value, "cloud"

    def merge_zone_humidity(
        self,
        zone_id: str,
        cloud_value: float | None,
        external_value: float | None = None,
    ) -> tuple[float | None, str]:
        """Return (merged_value, source_name).

        Priority: external > cloud > homekit.

        Cloud is preferred over HomeKit for humidity because the bridge
        caches humidity values and returns stale readings that can drift
        1-4% from the TRV's actual sensor. Cloud API provides 0.1%
        precision with real-time updates. HomeKit is kept as fallback
        for when cloud data is unavailable (e.g. cloud sync failed).
        Temperature uses HomeKit first (accurate, real-time push).
        """
        if external_value is not None:
            self._log_source_transition(zone_id, "humidity", "external", external_value)
            return external_value, "external"

        if cloud_value is not None:
            self._log_source_transition(zone_id, "humidity", "cloud", cloud_value)
            return cloud_value, "cloud"

        # Cloud unavailable — fall back to HomeKit (stale but better than nothing)
        local_val, is_fresh = self._get_fresh_local_value(zone_id, "get_humidity")
        if is_fresh and local_val is not None:
            self._log_source_transition(zone_id, "humidity", "homekit", local_val)
            return local_val, "homekit"

        self._log_source_transition(zone_id, "humidity", "cloud", None)
        return None, "cloud"

    def merge_zone_target_temperature(
        self,
        zone_id: str,
        cloud_value: float | None,
    ) -> tuple[float | None, str]:
        """Return (merged_value, source_name).

        Priority: homekit (if fresh AND no recent write) > cloud.
        During write protection window, the entity's optimistic value is
        authoritative — HomeKit bridge may still report stale target.
        """
        if not self.should_accept_cloud_value(zone_id):
            # Write protection active — trust optimistic/cloud value
            self._log_source_transition(zone_id, "target_temp", "cloud", cloud_value)
            return cloud_value, "cloud"

        local_val, is_fresh = self._get_fresh_local_value(
            zone_id, "get_target_temperature", freshness_mode="changed",
        )
        if is_fresh and local_val is not None:
            self._log_source_transition(zone_id, "target_temp", "homekit", local_val)
            return local_val, "homekit"

        self._log_source_transition(zone_id, "target_temp", "cloud", cloud_value)
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
            self._log_source_transition(zone_id, "hvac_state", "homekit", int(local_val))
            return int(local_val), "homekit"

        self._log_source_transition(zone_id, "hvac_state", "cloud", cloud_value)
        return cloud_value, "cloud"

    def merge_zone_target_heating_state(
        self,
        zone_id: str,
        cloud_value: int | None,
    ) -> tuple[int | None, str]:
        """Return (merged_value, source_name).

        Priority: homekit (if fresh AND no recent write) > cloud.
        During write protection window, the entity's optimistic value is
        authoritative — HomeKit bridge may still report stale mode.
        """
        if not self.should_accept_cloud_value(zone_id):
            self._log_source_transition(zone_id, "target_hvac", "cloud", cloud_value)
            return cloud_value, "cloud"

        local_val, is_fresh = self._get_fresh_local_value(
            zone_id, "get_target_heating_state", freshness_mode="changed",
        )
        if is_fresh and local_val is not None:
            self._log_source_transition(zone_id, "target_hvac", "homekit", int(local_val))
            return int(local_val), "homekit"

        self._log_source_transition(zone_id, "target_hvac", "cloud", cloud_value)
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
