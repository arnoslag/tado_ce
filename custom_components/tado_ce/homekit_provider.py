"""Tado CE HomeKit Local Provider — local data reads and writes via HomeKit."""

from __future__ import annotations

import asyncio
from datetime import datetime
import logging
from typing import TYPE_CHECKING, Any

from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.util import dt as dt_util

from .const import (
    CACHE_REFRESH_FAILURE_THRESHOLD,
    HOMEKIT_CACHE_REFRESH_SECONDS,
    HOMEKIT_WRITE_TIMEOUT_SECONDS,
    SIGNAL_HOMEKIT_UPDATE,
)
from .homekit_client import (
    CHAR_CURRENT_HEATING_STATE,
    CHAR_CURRENT_HUMIDITY,
    CHAR_CURRENT_TEMPERATURE,
    CHAR_TARGET_HEATING_STATE,
    CHAR_TARGET_TEMPERATURE,
    HomeKitClient,
)

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)


def _find_char_iid(
    accessories: list[dict[str, Any]],
    aid: int,
    char_type: str,
) -> int | None:
    """Find the iid of a characteristic by type for a given accessory.

    Args:
        accessories: List of accessory dicts from list_accessories_and_characteristics.
        aid: Accessory ID.
        char_type: Short-form characteristic type (e.g. "11" for Current Temperature).

    Returns:
        The iid if found, None otherwise.
    """
    for acc in accessories:
        if acc.get("aid") != aid:
            continue
        for svc in acc.get("services", []):
            for char in svc.get("characteristics", []):
                # aiohomekit normalizes types to full UUID: 0000XXXX-0000-1000-8000-0026BB765291
                raw_type = char.get("type", "")
                if "-" in raw_type:
                    ctype = raw_type.split("-")[0].lstrip("0").upper()
                else:
                    ctype = raw_type.upper().lstrip("0")
                if ctype == char_type.upper():
                    iid = char.get("iid")
                    return int(iid) if iid is not None else None
    return None


class HomeKitLocalProvider:
    """Provide local data from a HomeKit-paired Tado bridge.

    Each method returns (value, timestamp) tuples so the StateReconciler
    can check freshness. Returns (None, None) when data is unavailable.
    """

    def __init__(self, client: HomeKitClient, hass: HomeAssistant, home_id: str) -> None:
        """Initialize the HomeKit Local Provider."""
        self._client = client
        self._hass = hass
        self._home_id = home_id
        # Cache: zone_id → {char_type: (value, timestamp)}
        self._cache: dict[str, dict[str, tuple[Any, datetime]]] = {}
        # Accessory list cache (refreshed on connect)
        self._accessories: list[dict[str, Any]] = []
        # Event subscription cleanup
        self._unsub_dispatcher: Any | None = None
        # Event map: (aid, iid) → (zone_id, char_type)
        self._event_map: dict[tuple[int, int], tuple[str, str]] = {}
        # Periodic cache refresh task
        self._cache_refresh_task: asyncio.Task[None] | None = None

    @property
    def is_connected(self) -> bool:
        """Return True if the underlying HomeKit connection is active."""
        return self._client.is_connected

    async def async_refresh_accessories(self) -> None:
        """Refresh the cached accessory list."""
        self._accessories = await self._client.async_list_accessories()

    def update_cache(
        self,
        zone_id: str,
        char_type: str,
        value: Any,
    ) -> None:
        """Update the local cache for a zone characteristic.

        Called by event subscription callbacks when bridge pushes updates.
        """
        if zone_id not in self._cache:
            self._cache[zone_id] = {}
        self._cache[zone_id][char_type] = (value, dt_util.utcnow())

    def get_temperature(self, zone_id: str) -> tuple[float | None, datetime | None]:
        """Get current temperature for a zone.

        Returns:
            (celsius, timestamp) or (None, None) if unavailable.
        """
        entry = self._cache.get(zone_id, {}).get(CHAR_CURRENT_TEMPERATURE)
        if entry is None:
            return None, None
        return entry

    def get_humidity(self, zone_id: str) -> tuple[float | None, datetime | None]:
        """Get current humidity for a zone.

        Returns:
            (percentage, timestamp) or (None, None) if unavailable.
        """
        entry = self._cache.get(zone_id, {}).get(CHAR_CURRENT_HUMIDITY)
        if entry is None:
            return None, None
        return entry

    def get_target_temperature(self, zone_id: str) -> tuple[float | None, datetime | None]:
        """Get target temperature for a zone.

        Returns:
            (celsius, timestamp) or (None, None) if unavailable.
        """
        entry = self._cache.get(zone_id, {}).get(CHAR_TARGET_TEMPERATURE)
        if entry is None:
            return None, None
        return entry

    def get_hvac_state(self, zone_id: str) -> tuple[int | None, datetime | None]:
        """Get current HVAC state for a zone.

        Returns:
            (state_int, timestamp) or (None, None) if unavailable.
            State: 0=Off, 1=Heat, 2=Cool.
        """
        entry = self._cache.get(zone_id, {}).get(CHAR_CURRENT_HEATING_STATE)
        if entry is None:
            return None, None
        return entry

    def get_target_heating_state(self, zone_id: str) -> tuple[int | None, datetime | None]:
        """Get target heating/cooling state for a zone.

        Returns:
            (state_int, timestamp) or (None, None) if unavailable.
            State: 0=Off, 1=Heat, 2=Cool, 3=Auto.
        """
        entry = self._cache.get(zone_id, {}).get(CHAR_TARGET_HEATING_STATE)
        if entry is None:
            return None, None
        return entry

    async def set_temperature(self, zone_id: str, temperature: float) -> bool:
        """Set target temperature for a zone via HomeKit.

        Args:
            zone_id: Tado zone ID.
            temperature: Target temperature in Celsius (5-25, step 0.1).

        Returns:
            True if write succeeded, False otherwise.
        """
        if not self._client.is_connected or not self._client.pairing:
            return False

        aids = self._client.get_aids_for_zone(zone_id)
        if not aids:
            _LOGGER.debug("HomeKit: No accessory mapped for zone %s", zone_id)
            return False

        aid = aids[0]
        iid = _find_char_iid(self._accessories, aid, CHAR_TARGET_TEMPERATURE)
        if iid is None:
            _LOGGER.debug("HomeKit: Target temperature characteristic not found for aid %d", aid)
            return False

        try:
            async with asyncio.timeout(HOMEKIT_WRITE_TIMEOUT_SECONDS):
                result = await self._client.pairing.put_characteristics([(aid, iid, temperature)])
            if not result:  # Empty dict = success
                self.update_cache(zone_id, CHAR_TARGET_TEMPERATURE, temperature)
                _LOGGER.info("HomeKit: Set zone %s temperature to %.1f°C via local bridge", zone_id, temperature)
                return True
            _LOGGER.warning("HomeKit: Set temperature failed for zone %s: %s", zone_id, result)
            return False
        except TimeoutError:
            _LOGGER.warning("HomeKit: set_temperature timed out for zone %s", zone_id)
            return False
        except Exception:
            _LOGGER.debug("HomeKit: Set temperature exception for zone %s", zone_id, exc_info=True)
            return False

    async def set_hvac_mode(self, zone_id: str, mode: int) -> bool:
        """Set HVAC mode for a zone via HomeKit.

        Args:
            zone_id: Tado zone ID.
            mode: Target heating/cooling state (0=Off, 1=Heat, 2=Cool, 3=Auto).

        Returns:
            True if write succeeded, False otherwise.
        """
        if not self._client.is_connected or not self._client.pairing:
            return False

        aids = self._client.get_aids_for_zone(zone_id)
        if not aids:
            _LOGGER.debug("HomeKit: No accessory mapped for zone %s", zone_id)
            return False

        aid = aids[0]
        iid = _find_char_iid(self._accessories, aid, CHAR_TARGET_HEATING_STATE)
        if iid is None:
            _LOGGER.debug("HomeKit: Target heating state characteristic not found for aid %d", aid)
            return False

        try:
            async with asyncio.timeout(HOMEKIT_WRITE_TIMEOUT_SECONDS):
                result = await self._client.pairing.put_characteristics([(aid, iid, mode)])
            if not result:
                self.update_cache(zone_id, CHAR_TARGET_HEATING_STATE, mode)
                _LOGGER.info("HomeKit: Set zone %s HVAC mode to %d via local bridge", zone_id, mode)
                return True
            _LOGGER.warning("HomeKit: Set HVAC mode failed for zone %s: %s", zone_id, result)
            return False
        except TimeoutError:
            _LOGGER.warning("HomeKit: set_hvac_mode timed out for zone %s", zone_id)
            return False
        except Exception:
            _LOGGER.debug("HomeKit: Set HVAC mode exception for zone %s", zone_id, exc_info=True)
            return False

    async def async_subscribe_events(self) -> None:
        """Subscribe to characteristic events for all mapped zones.

        Subscribes to temperature, humidity, target temp, and HVAC state
        events for each mapped accessory. Updates are pushed by the bridge
        and handled by _on_event_callback.
        """
        if not self._client.is_connected or not self._client.pairing:
            _LOGGER.debug("HomeKit: Cannot subscribe — not connected")
            return

        if not self._accessories:
            await self.async_refresh_accessories()

        # Build subscription list: (aid, iid) for all interesting characteristics
        subscribe_chars: list[tuple[int, int]] = []
        char_types = (
            CHAR_CURRENT_TEMPERATURE,
            CHAR_CURRENT_HUMIDITY,
            CHAR_TARGET_TEMPERATURE,
            CHAR_CURRENT_HEATING_STATE,
            CHAR_TARGET_HEATING_STATE,
        )

        for zone_id, aids in self._client._zone_to_aids.items():
            for aid in aids:
                for char_type in char_types:
                    iid = _find_char_iid(self._accessories, aid, char_type)
                    if iid is not None:
                        subscribe_chars.append((aid, iid))

        if not subscribe_chars:
            _LOGGER.debug("HomeKit: No characteristics to subscribe to")
            return

        # Build reverse lookup: (aid, iid) → (zone_id, char_type)
        self._event_map = {}
        for zone_id, aids in self._client._zone_to_aids.items():
            for aid in aids:
                for char_type in char_types:
                    iid = _find_char_iid(self._accessories, aid, char_type)
                    if iid is not None:
                        self._event_map[(aid, iid)] = (zone_id, char_type)

        # Subscribe to events
        await self._client.pairing.subscribe(subscribe_chars)
        self._unsub_dispatcher = self._client.pairing.dispatcher_connect(
            self._on_event_callback,
        )
        _LOGGER.info(
            "HomeKit: Subscribed to %d characteristics across %d zones",
            len(subscribe_chars),
            len(self._client._zone_to_aids),
        )

        # Start periodic cache refresh to prevent staleness
        if self._cache_refresh_task is not None:
            self._cache_refresh_task.cancel()
        self._cache_refresh_task = asyncio.create_task(
            self._periodic_cache_refresh(),
        )

    def _on_event_callback(self, event_data: dict[tuple[int, int], dict[str, Any]]) -> None:
        """Handle characteristic event updates from the bridge.

        Args:
            event_data: Dict mapping (aid, iid) to {"value": ...}.
        """
        updated_zones: set[str] = set()
        for key, data in event_data.items():
            mapping = self._event_map.get(key)
            if mapping is None:
                continue
            zone_id, char_type = mapping
            value = data.get("value")
            if value is not None:
                # Only log when value actually changed
                old_entry = self._cache.get(zone_id, {}).get(char_type)
                old_value = old_entry[0] if old_entry else None
                self.update_cache(zone_id, char_type, value)
                updated_zones.add(zone_id)
                if value != old_value:
                    _LOGGER.debug(
                        "HomeKit event: zone %s char %s changed %s → %s",
                        zone_id, char_type, old_value, value,
                    )
        # Fire dispatcher signal once per updated zone
        signal = SIGNAL_HOMEKIT_UPDATE.format(home_id=self._home_id)
        for zone_id in updated_zones:
            async_dispatcher_send(self._hass, signal, zone_id)

    async def _periodic_cache_refresh(self) -> None:
        """Periodically poll all subscribed characteristics to keep cache fresh.

        HomeKit bridge only pushes events on value change. When temperature
        is stable, cache timestamps go stale (>5 min) and StateReconciler
        falls back to cloud. This poll refreshes timestamps even when values
        haven't changed.

        Tracks consecutive failures and triggers reconnect after threshold.
        """
        consecutive_failures = 0
        first_refresh = True
        while True:
            await asyncio.sleep(HOMEKIT_CACHE_REFRESH_SECONDS)
            if not self._client.is_connected or not self._client.pairing:
                continue
            try:
                chars_to_read = list(self._event_map.keys())
                if not chars_to_read:
                    continue
                result = await self._client.pairing.get_characteristics(chars_to_read)
                updated_zones: set[str] = set()
                changes_found = 0
                for key, data in result.items():
                    mapping = self._event_map.get(key)
                    if mapping is None:
                        continue
                    zone_id, char_type = mapping
                    value = data.get("value")
                    if value is not None:
                        old_entry = self._cache.get(zone_id, {}).get(char_type)
                        old_value = old_entry[0] if old_entry else None
                        self.update_cache(zone_id, char_type, value)
                        updated_zones.add(zone_id)
                        if value != old_value:
                            changes_found += 1
                            _LOGGER.debug(
                                "HomeKit cache refresh: zone %s char %s changed %s → %s",
                                zone_id, char_type, old_value, value,
                            )
                consecutive_failures = 0
                # Fire dispatcher signal per refreshed zone
                signal = SIGNAL_HOMEKIT_UPDATE.format(home_id=self._home_id)
                for zone_id in updated_zones:
                    async_dispatcher_send(self._hass, signal, zone_id)
                # Only log on first refresh or when values changed
                if first_refresh:
                    _LOGGER.debug(
                        "HomeKit: First cache refresh — %d characteristics polled",
                        len(chars_to_read),
                    )
                    first_refresh = False
                elif changes_found > 0:
                    _LOGGER.debug(
                        "HomeKit: Cache refresh — %d value(s) changed",
                        changes_found,
                    )
            except Exception:
                consecutive_failures += 1
                if consecutive_failures >= CACHE_REFRESH_FAILURE_THRESHOLD:
                    _LOGGER.warning(
                        "HomeKit: %d consecutive cache refresh failures, triggering reconnect",
                        consecutive_failures,
                    )
                    await self._client.async_reconnect()
                    consecutive_failures = 0
                else:
                    _LOGGER.debug(
                        "HomeKit: Cache refresh failed (%d/%d)",
                        consecutive_failures,
                        CACHE_REFRESH_FAILURE_THRESHOLD,
                    )

    def unsubscribe_events(self) -> None:
        """Unsubscribe from characteristic events and stop cache refresh."""
        if self._cache_refresh_task is not None:
            self._cache_refresh_task.cancel()
            self._cache_refresh_task = None
        if self._unsub_dispatcher:
            self._unsub_dispatcher()
            self._unsub_dispatcher = None
            _LOGGER.debug("HomeKit: Unsubscribed from events")
