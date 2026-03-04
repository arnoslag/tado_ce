"""Immediate Refresh Handler for Tado CE integration.

Handles immediate data refresh after user-initiated state changes.
Uses coordinator.async_request_refresh() instead of direct API sync + dispatcher.
Per-entry RefreshHandler stored on coordinator.refresh_handler.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from .coordinator import TadoDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)

# Entity types that should trigger immediate refresh
REFRESH_ENTITY_TYPES = {
    "climate",      # Temperature and HVAC mode changes
    "switch",       # Switch toggles
    "water_heater", # Hot water state changes
    "select"        # Presence mode changes
}

# Rate limiting thresholds
QUOTA_WARNING_THRESHOLD = 0.8  # 80% quota used
QUOTA_CRITICAL_THRESHOLD = 0.9  # 90% quota used
MIN_QUOTA_PERCENTAGE_FOR_REFRESH = 0.10  # Minimum 10% remaining to allow refresh


class RefreshHandler:
    """Handle immediate data refresh after user actions.

    Accepts coordinator instead of hass/entry_id.
    Uses coordinator.async_request_refresh() for data refresh — CoordinatorEntity
    handles entity update propagation automatically.
    """

    def __init__(self, coordinator: TadoDataUpdateCoordinator):
        """Initialize immediate refresh handler.

        Args:
            coordinator: TadoDataUpdateCoordinator instance for this config entry.
                         Provides hass, api_client, data_loader, config_manager access.
        """
        self._coordinator = coordinator
        self.hass = coordinator.hass
        # CRITICAL FIX: Per-entity rate limiting instead of global only
        self._last_refresh_per_entity: dict[str, datetime] = {}
        self._global_last_refresh: Optional[datetime] = None
        self._min_global_interval = 2  # Reduced from 10s to allow multi-zone updates
        self._min_per_entity_interval = 2  # Per-entity minimum (seconds)
        self._consecutive_failures = 0
        self._max_backoff_interval = 300  # Max 5 minutes backoff

        # Debounce mechanism for batch updates
        self._pending_refresh: bool = False
        self._pending_home_state_refresh: bool = False  # Track if home state refresh needed
        self._debounce_task: Optional[object] = None
        self._debounce_delay = 15.0  # Default 15 seconds (was 1s), configurable via options
    def _get_debounce_delay(self) -> float:
        """Get debounce delay from config or use default.

        Configurable via Options > Refresh Debounce Delay
        Direct coordinator.config_manager access.
        """
        try:
            return float(self._coordinator.config_manager.get_refresh_debounce_seconds())
        except Exception as e:
            _LOGGER.debug("Could not get debounce config, using default: %s", e)
        return self._debounce_delay

    async def _get_rate_limit_info(self) -> dict:
        """Get current rate limit information.

        Direct coordinator.data_loader access.

        Returns:
            Dictionary with rate limit info, or empty dict if unavailable
        """
        try:
            return await self.hass.async_add_executor_job(
                self._coordinator.data_loader.load_ratelimit_file
            ) or {}
        except Exception as e:
            _LOGGER.debug("Failed to read rate limit file: %s", e)
        return {}

    async def _check_quota_available(self) -> tuple[bool, str]:
        """Check if sufficient API quota is available.

        Returns:
            Tuple of (can_refresh, reason)
        """
        rl_info = await self._get_rate_limit_info()

        # If no rate limit info, allow refresh (fail open)
        if not rl_info:
            return True, "no_rate_limit_data"

        remaining = rl_info.get("remaining")
        limit = rl_info.get("limit")
        status = rl_info.get("status")

        # Check if rate limited
        if status == "rate_limited" or remaining == 0:
            return False, "rate_limited"

        # Check percentage thresholds (dynamic based on actual limit)
        if limit and remaining is not None:
            percentage_remaining = remaining / limit
            percentage_used = 1 - percentage_remaining

            # Skip refresh if less than 10% quota remaining
            if percentage_remaining < MIN_QUOTA_PERCENTAGE_FOR_REFRESH:
                return False, f"quota_too_low ({int(percentage_remaining * 100)}% remaining)"

            if percentage_used >= QUOTA_CRITICAL_THRESHOLD:
                return False, f"quota_critical ({int(percentage_used * 100)}% used)"

            if percentage_used >= QUOTA_WARNING_THRESHOLD:
                _LOGGER.warning(
                    "API quota warning: %s%% used (%s/%s remaining)",
                    int(percentage_used * 100), remaining, limit
                )

        return True, "ok"

    def _get_backoff_interval(self) -> int:
        """Calculate backoff interval based on consecutive failures.

        Returns:
            Backoff interval in seconds
        """
        if self._consecutive_failures == 0:
            return self._min_global_interval

        # Exponential backoff: 10s, 20s, 40s, 80s, 160s, 300s (max)
        backoff = self._min_global_interval * (2 ** self._consecutive_failures)
        return min(backoff, self._max_backoff_interval)

    def should_refresh(self, entity_id: str) -> bool:
        """Check if entity type should trigger immediate refresh.

        Args:
            entity_id: Entity ID (e.g., "climate.living_room")

        Returns:
            True if entity type should trigger refresh
        """
        domain = entity_id.split(".")[0]
        return domain in REFRESH_ENTITY_TYPES

    def can_refresh_now(self, entity_id: str) -> bool:
        """Check if refresh is allowed for this entity.

        CRITICAL FIX: Per-entity rate limiting allows multiple entities
        to refresh within the global interval, while still preventing
        API spam from a single entity.

        Args:
            entity_id: Entity ID requesting refresh

        Returns:
            True if refresh is allowed now
        """
        now = datetime.now()

        # Check global rate limit (prevents API spam)
        if self._global_last_refresh:
            global_elapsed = (now - self._global_last_refresh).total_seconds()
            required_global = self._get_backoff_interval()
            if global_elapsed < required_global:
                _LOGGER.debug(
                    "Global backoff active: %ss remaining (failures: %s)",
                    int(required_global - global_elapsed), self._consecutive_failures
                )
                return False

        # Check per-entity rate limit (allows multiple entities)
        if entity_id in self._last_refresh_per_entity:
            entity_elapsed = (now - self._last_refresh_per_entity[entity_id]).total_seconds()
            if entity_elapsed < self._min_per_entity_interval:
                _LOGGER.debug(
                    "Entity %s backoff active: %ss remaining",
                    entity_id, int(self._min_per_entity_interval - entity_elapsed)
                )
                return False

        return True

    async def trigger_refresh(
        self, entity_id: str, reason: str = "state_change",
        force: bool = False, skip_debounce: bool = False,
        include_home_state: bool = False,
    ):
        """Trigger immediate refresh for an entity.

        Uses debouncing to batch multiple rapid changes into a single refresh.

        Args:
            entity_id: Entity ID that triggered the refresh
            reason: Reason for refresh (for logging)
            force: If True, skip entity type check (for buttons like Resume All Schedules)
            skip_debounce: If True, execute refresh immediately without debounce delay
            include_home_state: If True, also fetch home state (for presence mode changes)
        """
        if not force and not self.should_refresh(entity_id):
            _LOGGER.debug("Entity %s does not trigger immediate refresh", entity_id)
            return

        # Check API quota before scheduling refresh
        can_refresh, quota_reason = await self._check_quota_available()
        if not can_refresh:
            _LOGGER.debug(
                "Skipping immediate refresh for %s: %s. Will rely on normal polling.",
                entity_id, quota_reason
            )
            return

        _LOGGER.debug("Scheduling debounced refresh for %s (reason: %s)", entity_id, reason)

        # Cancel existing debounce task if any
        if self._debounce_task is not None:
            self._debounce_task.cancel()
            self._debounce_task = None

        # Mark refresh as pending
        self._pending_refresh = True
        self._last_refresh_per_entity[entity_id] = datetime.now()

        # Track if home state refresh is needed
        self._pending_home_state_refresh = include_home_state

        # Schedule debounced refresh
        async def _debounced_refresh():
            # Skip debounce delay if requested (for buttons like Resume All Schedules)
            if not skip_debounce:
                delay = self._get_debounce_delay()
                await asyncio.sleep(delay)

            if not self._pending_refresh:
                return

            self._pending_refresh = False

            # Check global rate limit
            now = datetime.now()
            if self._global_last_refresh:
                global_elapsed = (now - self._global_last_refresh).total_seconds()
                required_global = self._get_backoff_interval()
                if global_elapsed < required_global:
                    _LOGGER.debug("Global backoff active: %ss remaining", int(required_global - global_elapsed))
                    return

            _LOGGER.info("Executing debounced refresh (triggered by: %s)", reason)

            try:
                # Use coordinator.async_request_refresh()
                # instead of direct API sync + file write + dispatcher signal.
                # CoordinatorEntity handles entity update propagation automatically.
                #
                # include_home_state: coordinator._async_update_data() already handles
                # home_state sync based on config_manager.get_home_state_sync_enabled().
                # For immediate presence changes, the coordinator's full sync covers it.
                await self._coordinator.async_request_refresh()

                self._global_last_refresh = datetime.now()

                if self._consecutive_failures > 0:
                    _LOGGER.info("Immediate refresh recovered after %s failures", self._consecutive_failures)
                    self._consecutive_failures = 0

                _LOGGER.debug("Immediate refresh completed via coordinator")

            except Exception as e:
                self._consecutive_failures += 1
                _LOGGER.error(
                    "Immediate refresh failed (attempt %s): %s. Next backoff: %ss",
                    self._consecutive_failures, e, self._get_backoff_interval()
                )

        self._debounce_task = asyncio.create_task(_debounced_refresh())
