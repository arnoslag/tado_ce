"""Tado CE Hub Sensors — API status, home info, monitoring."""

from __future__ import annotations

import contextlib
from datetime import UTC
import json
import logging
from typing import TYPE_CHECKING, Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.core import callback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .device_manager import get_hub_device_info
from .entity_registry import ENTITY_REGISTRY, get_entity_category
from .format_helpers import format_api_status as _format_api_status
from .insights import calculate_api_status_recommendation

if TYPE_CHECKING:
    from .coordinator import TadoDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)


class TadoHubSensor(CoordinatorEntity["TadoDataUpdateCoordinator"], SensorEntity):
    """Base class for Tado CE hub sensors.

    Provides common init (device_info, available, native_value)
    and the standard _handle_coordinator_update -> update() pattern.
    Subclasses only need to set sensor-specific attrs in __init__
    and implement update().
    """

    _attr_has_entity_name = True

    def __init__(self, coordinator: TadoDataUpdateCoordinator) -> None:
        """Initialize hub sensor with common attributes."""
        super().__init__(coordinator)
        self._attr_device_info = get_hub_device_info(coordinator.home_id)
        self._attr_available = False
        self._attr_native_value = None

    @callback
    def _handle_coordinator_update(self) -> None:
        self.update()
        self.async_write_ha_state()

    @callback
    def update(self) -> None:
        """Update sensor state from coordinator data. Override in subclasses."""


class TadoHomeIdSensor(TadoHubSensor):
    """Sensor showing Tado Home ID."""

    def __init__(self, coordinator: TadoDataUpdateCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        _meta = ENTITY_REGISTRY["sensor_home_id"]
        self._attr_translation_key = _meta.translation_key
        self._attr_unique_id = f"tado_ce_{coordinator.home_id}_{_meta.unique_id_suffix}"
        self._attr_icon = _meta.icon
        self._attr_entity_category = get_entity_category(_meta)
        self._attr_entity_registry_enabled_default = _meta.enabled_default

    @callback
    def update(self) -> None:
        """Update sensor state from coordinator data."""
        try:
            # Use coordinator.home_id directly — always available, doesn't depend on config file
            home_id = self.coordinator.home_id
            if home_id:
                self._attr_native_value = home_id
                self._attr_available = True
            else:
                self._attr_available = False
        except Exception:
            self._attr_available = False


class TadoApiUsageSensor(TadoHubSensor):
    """Sensor for Tado API usage tracking."""

    def __init__(self, coordinator: TadoDataUpdateCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        _meta = ENTITY_REGISTRY["sensor_api_usage"]
        self._attr_translation_key = _meta.translation_key
        self._attr_unique_id = f"tado_ce_{coordinator.home_id}_{_meta.unique_id_suffix}"
        self._attr_native_unit_of_measurement = "calls"
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_entity_category = get_entity_category(_meta)
        self._data: dict[str, Any] = {}
        self._call_history: list[dict[str, Any]] = []

    @property
    def icon(self) -> str:
        """Return the icon for the sensor."""
        status = self._data.get("status")
        if status == "rate_limited":
            return "mdi:api-off"
        if status == "error":
            return "mdi:alert-circle"
        return "mdi:api"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra state attributes."""
        test_mode = self._data.get("test_mode", False)

        attrs = {
            "limit": self._data.get("limit"),
            "remaining": self._data.get("remaining"),
            "percentage_used": self._data.get("percentage_used"),
            "last_updated": self._data.get("last_updated"),
            "status": self._data.get("status"),
            "test_mode": test_mode,
        }

        if test_mode:
            attrs["test_mode_info"] = "Simulated 100-call API tier"
            test_mode_start = self._data.get("test_mode_start_time")
            test_mode_used = self._data.get("test_mode_used")
            if test_mode_start:
                attrs["test_mode_start_time"] = test_mode_start
            if test_mode_used is not None:
                attrs["test_mode_used"] = test_mode_used

        if self._call_history:
            attrs["call_history"] = self._call_history

        return attrs

    @callback
    def update(self) -> None:
        """Update sensor state from coordinator data."""
        try:
            self._data = (self.coordinator.data or {}).get("ratelimit") or {}
            if self._data:
                used = self._data.get("used")
                if used is not None:
                    self._attr_native_value = int(used)
                    self._attr_available = True
                else:
                    self._attr_available = False
            else:
                self._attr_available = False

            # Read call history from coordinator data (async-loaded by data_loader)
            # instead of instantiating APICallTracker which does blocking file I/O.
            try:
                from datetime import datetime

                from homeassistant.util import dt as dt_util

                history_data = (self.coordinator.data or {}).get("api_call_history")
                self._call_history = []

                if history_data and isinstance(history_data, dict):
                    all_calls: list[dict[str, Any]] = []
                    for date_calls in history_data.values():
                        if isinstance(date_calls, list):
                            all_calls.extend(date_calls)

                    all_calls.sort(key=lambda x: x.get("timestamp", ""), reverse=True)

                    for call in all_calls[:50]:
                        call_copy = call.copy()
                        try:
                            ts = datetime.fromisoformat(call["timestamp"])
                            if ts.tzinfo is None:
                                ts = ts.replace(tzinfo=dt_util.UTC)
                            local_ts = dt_util.as_local(ts)
                            call_copy["timestamp"] = local_ts.strftime("%Y-%m-%d %H:%M:%S")
                        except Exception:
                            _LOGGER.debug("Failed to convert timestamp for call history entry")
                        self._call_history.append(call_copy)
            except Exception as e:
                _LOGGER.debug("Failed to load call history: %s", e)
                self._call_history = []

        except FileNotFoundError:
            _LOGGER.debug("Ratelimit file not found - first run or migration pending")
        except PermissionError:
            _LOGGER.exception("Permission denied reading ratelimit file")
        except json.JSONDecodeError:
            _LOGGER.exception("Invalid JSON in ratelimit file")
        except Exception:
            _LOGGER.exception("Unexpected error loading ratelimit data")


class TadoApiResetSensor(TadoHubSensor):
    """Sensor showing API rate limit reset time."""

    def __init__(self, coordinator: TadoDataUpdateCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        _meta = ENTITY_REGISTRY["sensor_api_reset"]
        self._attr_translation_key = _meta.translation_key
        self._attr_unique_id = f"tado_ce_{coordinator.home_id}_{_meta.unique_id_suffix}"
        self._attr_icon = _meta.icon
        self._attr_device_class = SensorDeviceClass.TIMESTAMP
        self._attr_entity_category = get_entity_category(_meta)
        self._reset_human: str | None = None
        self._reset_seconds: int | None = None
        self._reset_at: str | None = None
        self._last_reset: str | None = None
        self._status: str | None = None
        self._next_poll: str | None = None
        self._current_interval: int | None = None
        self._test_mode: bool = False
        self._test_mode_start_time: str | None = None  # Test Mode cycle start

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra state attributes."""
        attrs = {
            "time_until_reset": self._reset_human,
            "reset_seconds": self._reset_seconds,
            "reset_at": self._reset_at,
            "last_reset": self._last_reset,  # When last reset happened
            "status": self._status,
            "next_poll": self._next_poll,
            "current_interval_minutes": self._current_interval,
            "test_mode": self._test_mode,
        }

        if self._test_mode:
            attrs["test_mode_info"] = "Simulated 24h cycle from enable time"
            if self._test_mode_start_time:
                attrs["test_mode_start_time"] = self._test_mode_start_time

        return attrs

    @callback
    def update(self) -> None:
        """Update sensor state from coordinator data."""
        try:
            from datetime import datetime, timedelta

            from homeassistant.util import dt as dt_util

            data = (self.coordinator.data or {}).get("ratelimit")
            if not data:
                return

            self._test_mode = data.get("test_mode", False)

            test_mode_start = data.get("test_mode_start_time")
            if test_mode_start and self._test_mode:
                try:
                    start_time = datetime.fromisoformat(
                        test_mode_start,
                    )
                    start_local = dt_util.as_local(start_time)
                    self._test_mode_start_time = start_local.strftime("%Y-%m-%d %H:%M:%S")
                except Exception:
                    self._test_mode_start_time = test_mode_start
            else:
                self._test_mode_start_time = None

            self._reset_human = data.get("reset_human")
            self._reset_seconds = data.get("reset_seconds")
            self._status = data.get("status", "unknown")

            reset_at = data.get("reset_at")
            if reset_at and reset_at != "unknown":
                try:
                    reset_time = datetime.fromisoformat(reset_at)
                    self._attr_native_value = reset_time
                    self._attr_available = True
                    reset_local = dt_util.as_local(reset_time)
                    self._reset_at = reset_local.strftime("%Y-%m-%d %H:%M:%S")
                except Exception as e:
                    _LOGGER.debug("Failed to parse reset_at: %s", e)
                    self._reset_at = None
            else:
                self._reset_at = None

            last_reset_utc = data.get("last_reset_utc")
            if last_reset_utc:
                try:
                    last_reset_time = datetime.fromisoformat(last_reset_utc)
                    last_reset_local = dt_util.as_local(last_reset_time)
                    self._last_reset = last_reset_local.strftime("%Y-%m-%d %H:%M:%S")
                except Exception as e:
                    _LOGGER.debug("Failed to parse last_reset_utc: %s", e)
                    self._last_reset = None
            else:
                self._last_reset = None

            try:
                from homeassistant.util import dt as dt_util

                last_updated = data.get("last_updated")
                if last_updated:
                    if last_updated.endswith(("Z", "00:00")) or "+" in last_updated:
                        last_sync = datetime.fromisoformat(last_updated)
                    else:
                        last_sync = datetime.fromisoformat(last_updated).replace(tzinfo=UTC)

                    from .polling import get_polling_interval

                    config_manager = self.coordinator.config_manager
                    if config_manager:
                        self._current_interval = get_polling_interval(config_manager, cached_ratelimit=data)

                        next_poll_time = last_sync + timedelta(minutes=self._current_interval)
                        next_poll_local = dt_util.as_local(next_poll_time)
                        self._next_poll = next_poll_local.strftime("%Y-%m-%d %H:%M:%S")
                    else:
                        self._next_poll = None
                        self._current_interval = None
                else:
                    self._next_poll = None
                    self._current_interval = None
            except Exception as e:
                _LOGGER.debug("Failed to calculate next poll time: %s", e)
                self._next_poll = None
                self._current_interval = None

        except Exception as e:
            _LOGGER.debug("Failed to update API reset sensor: %s", e)


class TadoApiLimitSensor(TadoHubSensor):
    """Sensor showing Tado API daily limit."""

    def __init__(self, coordinator: TadoDataUpdateCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        _meta = ENTITY_REGISTRY["sensor_api_limit"]
        self._attr_translation_key = _meta.translation_key
        self._attr_unique_id = f"tado_ce_{coordinator.home_id}_{_meta.unique_id_suffix}"
        self._attr_icon = _meta.icon
        self._attr_native_unit_of_measurement = "calls"
        self._attr_entity_category = get_entity_category(_meta)
        self._attr_extra_state_attributes: dict[str, Any] = {}
        self._test_mode: bool = False

    @callback
    def update(self) -> None:
        """Update sensor state from coordinator data."""
        try:
            data = (self.coordinator.data or {}).get("ratelimit")
            if data:
                self._attr_native_value = data.get("limit")
                self._attr_available = self._attr_native_value is not None
                self._test_mode = data.get("test_mode", False)
            else:
                self._test_mode = False

            extra_attrs: dict[str, Any] = {
                "test_mode": self._test_mode,
            }

            if self._test_mode and data:
                extra_attrs["test_mode_info"] = "Simulated 100-call limit"

            # Load recent API calls from history (last 100 calls only to avoid DB size issues)
            try:
                from datetime import datetime, timedelta

                from homeassistant.util import dt as dt_util

                history = (self.coordinator.data or {}).get("api_call_history")
                if history:
                    all_calls = []
                    for calls in history.values():
                        all_calls.extend(calls)

                    all_calls.sort(key=lambda x: x["timestamp"], reverse=True)
                    raw_recent_calls = all_calls[:100]

                    recent_calls = []
                    for call in raw_recent_calls:
                        call_copy = call.copy()
                        try:
                            ts = datetime.fromisoformat(call["timestamp"])
                            if ts.tzinfo is None:
                                ts = ts.replace(tzinfo=dt_util.UTC)
                            local_ts = dt_util.as_local(ts)
                            call_copy["timestamp"] = local_ts.strftime("%Y-%m-%d %H:%M:%S")
                        except Exception:
                            _LOGGER.debug("Failed to convert timestamp for recent call entry")
                        recent_calls.append(call_copy)

                    now = datetime.now(dt_util.UTC)
                    cutoff = now - timedelta(hours=24)
                    last_24h_count = sum(
                        1
                        for call in all_calls
                        if datetime.fromisoformat(call["timestamp"]).replace(tzinfo=dt_util.UTC) > cutoff
                    )

                    extra_attrs.update(
                        {
                            "recent_calls": recent_calls,
                            "recent_calls_count": len(recent_calls),
                            "last_24h_count": last_24h_count,
                            "total_calls_tracked": len(all_calls),
                        },
                    )
            except Exception as e:
                _LOGGER.debug("Failed to load API call history: %s", e)
                extra_attrs.update(
                    {
                        "recent_calls": [],
                        "recent_calls_count": 0,
                        "last_24h_count": 0,
                        "total_calls_tracked": 0,
                    },
                )

            self._attr_extra_state_attributes = extra_attrs
        except Exception:
            self._attr_available = False


class TadoApiStatusSensor(TadoHubSensor):
    """Sensor showing Tado API status."""

    def __init__(self, coordinator: TadoDataUpdateCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        _meta = ENTITY_REGISTRY["sensor_api_status"]
        self._attr_translation_key = _meta.translation_key
        self._attr_unique_id = f"tado_ce_{coordinator.home_id}_{_meta.unique_id_suffix}"
        self._attr_entity_category = get_entity_category(_meta)
        self._remaining_calls: int | None = None
        self._total_calls: int | None = None
        self._reset_time: str | None = None
        self._recommendation: str = ""

    @property
    def icon(self) -> str:
        """Return the icon for the sensor."""
        if self._attr_native_value == "ok":
            return "mdi:check-circle"
        if self._attr_native_value == "rate_limited":
            return "mdi:alert-circle"
        return "mdi:help-circle"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra state attributes."""
        return {
            "remaining_calls": self._remaining_calls,
            "total_calls": self._total_calls,
            "reset_time": self._reset_time,
            "recommendation": self._recommendation,
        }

    @callback
    def update(self) -> None:
        """Update sensor state from coordinator data."""
        try:
            data = (self.coordinator.data or {}).get("ratelimit")
            if data:
                self._attr_native_value = _format_api_status(data.get("status", "unknown"))
                self._remaining_calls = data.get("remaining")
                self._total_calls = data.get("limit")
                self._reset_time = data.get("reset_human")

                self._recommendation = calculate_api_status_recommendation(
                    remaining_calls=self._remaining_calls,
                    total_calls=self._total_calls,
                    reset_time_human=self._reset_time,
                    current_interval_minutes=None,  # Could get from config_manager if needed
                )
                self._attr_available = True
            else:
                self._attr_native_value = "unknown"
                self._attr_available = True
        except Exception:
            self._attr_native_value = "error"
            self._attr_available = True


class TadoTokenStatusSensor(TadoHubSensor):
    """Sensor showing Tado token status."""

    def __init__(self, coordinator: TadoDataUpdateCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        _meta = ENTITY_REGISTRY["sensor_token_status"]
        self._attr_translation_key = _meta.translation_key
        self._attr_unique_id = f"tado_ce_{coordinator.home_id}_{_meta.unique_id_suffix}"
        self._attr_entity_category = get_entity_category(_meta)
        self._attr_entity_registry_enabled_default = _meta.enabled_default

    @property
    def icon(self) -> str:
        """Return the icon for the sensor."""
        if self._attr_native_value == "valid":
            return "mdi:key"
        return "mdi:key-alert"

    @callback
    def update(self) -> None:
        """Update sensor state from coordinator data."""
        try:
            # Check api_client's injected refresh token (from ConfigEntry.data)
            # rather than config file which may have null refresh_token
            client = self.coordinator.api_client
            if client._injected_refresh_token or client._access_token:
                self._attr_native_value = "valid"
            else:
                self._attr_native_value = "missing"
            self._attr_available = True
        except Exception:
            self._attr_native_value = "error"
            self._attr_available = True


class TadoZoneCountSensor(TadoHubSensor):
    """Sensor showing number of Tado zones."""

    def __init__(self, coordinator: TadoDataUpdateCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        _meta = ENTITY_REGISTRY["sensor_zone_count"]
        self._attr_translation_key = _meta.translation_key
        self._attr_unique_id = f"tado_ce_{coordinator.home_id}_{_meta.unique_id_suffix}"
        self._attr_icon = _meta.icon
        self._attr_native_unit_of_measurement = "zones"
        self._attr_entity_category = get_entity_category(_meta)
        self._heating_zones = 0
        self._hot_water_zones = 0
        self._ac_zones = 0

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra state attributes."""
        return {
            "heating_zones": self._heating_zones,
            "hot_water_zones": self._hot_water_zones,
            "ac_zones": self._ac_zones,
        }

    @callback
    def update(self) -> None:
        """Update sensor state from coordinator data."""
        try:
            zones = (self.coordinator.data or {}).get("zones_info")
            if zones:
                self._attr_native_value = len(zones)
                self._heating_zones = len([z for z in zones if z.get("type") == "HEATING"])
                self._hot_water_zones = len([z for z in zones if z.get("type") == "HOT_WATER"])
                self._ac_zones = len([z for z in zones if z.get("type") == "AIR_CONDITIONING"])
                self._attr_available = True
            else:
                self._attr_available = False
        except Exception:
            self._attr_available = False


class TadoLastSyncSensor(TadoHubSensor):
    """Sensor showing last sync time."""

    def __init__(self, coordinator: TadoDataUpdateCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        _meta = ENTITY_REGISTRY["sensor_last_sync"]
        self._attr_translation_key = _meta.translation_key
        self._attr_unique_id = f"tado_ce_{coordinator.home_id}_{_meta.unique_id_suffix}"
        self._attr_icon = _meta.icon
        self._attr_device_class = SensorDeviceClass.TIMESTAMP
        self._attr_entity_category = get_entity_category(_meta)

    @callback
    def update(self) -> None:
        """Update sensor state from coordinator data."""
        try:
            data = (self.coordinator.data or {}).get("ratelimit")
            if data:
                last_updated = data.get("last_updated")
                if last_updated:
                    from datetime import datetime

                    if last_updated.endswith(("Z", "00:00")) or "+" in last_updated:
                        self._attr_native_value = datetime.fromisoformat(last_updated)
                    else:
                        self._attr_native_value = datetime.fromisoformat(last_updated).replace(tzinfo=UTC)
                    self._attr_available = True
                else:
                    self._attr_available = False
            else:
                self._attr_available = False
        except Exception:
            self._attr_available = False


# ============ API Monitoring Sensors ============


class TadoNextSyncSensor(TadoHubSensor):
    """Sensor showing next API sync time."""

    def __init__(self, coordinator: TadoDataUpdateCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        _meta = ENTITY_REGISTRY["sensor_next_sync"]
        self._attr_translation_key = _meta.translation_key
        self._attr_unique_id = f"tado_ce_{coordinator.home_id}_{_meta.unique_id_suffix}"
        self._attr_icon = _meta.icon
        self._attr_device_class = SensorDeviceClass.TIMESTAMP
        self._attr_entity_category = get_entity_category(_meta)
        self._countdown: str | None = None
        self._current_interval: int | None = None
        self._countdown_unsub: Any | None = None  # HA CALLBACK_TYPE

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra state attributes."""
        return {
            "countdown": self._countdown,
            "current_interval_minutes": self._current_interval,
        }

    async def async_added_to_hass(self) -> None:
        """Start periodic countdown refresh when added to HA."""
        await super().async_added_to_hass()

        from datetime import timedelta as td

        from homeassistant.helpers.event import async_track_time_interval

        @callback
        def _refresh_countdown(_now: Any) -> None:  # HA datetime arg
            """Recalculate countdown attribute periodically."""
            self._recalculate_countdown()
            self.async_write_ha_state()

        self._countdown_unsub = async_track_time_interval(
            self.hass, _refresh_countdown, td(seconds=30),
        )

    async def async_will_remove_from_hass(self) -> None:
        """Cancel periodic countdown refresh on removal."""
        if self._countdown_unsub:
            self._countdown_unsub()
            self._countdown_unsub = None
        await super().async_will_remove_from_hass()

    def _recalculate_countdown(self) -> None:
        """Recalculate countdown from current native_value."""
        from datetime import datetime

        native = self._attr_native_value
        if not isinstance(native, datetime):
            self._countdown = None
            return

        now = datetime.now(UTC)
        time_until = native - now
        if time_until.total_seconds() > 0:
            minutes = int(time_until.total_seconds() // 60)
            seconds = int(time_until.total_seconds() % 60)
            self._countdown = f"{minutes}m {seconds}s"
        else:
            self._countdown = "Overdue"

    @callback
    def update(self) -> None:
        """Update sensor state from coordinator data."""
        try:
            from datetime import datetime, timedelta

            data = (self.coordinator.data or {}).get("ratelimit")
            if not data:
                return

            last_updated = data.get("last_updated")
            if not last_updated:
                return

            if last_updated.endswith(("Z", "00:00")) or "+" in last_updated:
                last_sync = datetime.fromisoformat(last_updated)
            else:
                last_sync = datetime.fromisoformat(last_updated).replace(tzinfo=UTC)

            from .polling import get_polling_interval

            config_manager = self.coordinator.config_manager
            if config_manager:
                self._current_interval = get_polling_interval(config_manager, cached_ratelimit=data)

                next_sync_time = last_sync + timedelta(minutes=self._current_interval)
                self._attr_native_value = next_sync_time
                self._attr_available = True

                self._recalculate_countdown()
            else:
                self._current_interval = None
                self._countdown = None

        except Exception as e:
            _LOGGER.debug("Failed to update Next Sync sensor: %s", e)


class TadoPollingIntervalSensor(TadoHubSensor):
    """Sensor showing current polling interval."""

    def __init__(self, coordinator: TadoDataUpdateCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        _meta = ENTITY_REGISTRY["sensor_polling_interval"]
        self._attr_translation_key = _meta.translation_key
        self._attr_unique_id = f"tado_ce_{coordinator.home_id}_{_meta.unique_id_suffix}"
        self._attr_icon = _meta.icon
        self._attr_native_unit_of_measurement = "min"
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_entity_category = get_entity_category(_meta)
        self._attr_entity_registry_enabled_default = _meta.enabled_default
        self._source: str | None = None
        self._day_interval: int | None = None
        self._night_interval: int | None = None
        self._is_night_mode: bool | None = None
        self._test_mode: bool = False

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra state attributes."""
        return {
            "source": self._source,
            "day_interval": self._day_interval,
            "night_interval": self._night_interval,
            "is_night_mode": self._is_night_mode,
            "test_mode": self._test_mode,
        }

    @callback
    def update(self) -> None:
        """Update sensor state from coordinator data."""
        try:
            from .const import DEFAULT_DAY_INTERVAL, DEFAULT_NIGHT_INTERVAL
            from .polling import (
                _calculate_adaptive_interval,
                get_polling_interval,
            )

            config_manager = self.coordinator.config_manager
            if not config_manager:
                return

            ratelimit_data = (self.coordinator.data or {}).get("ratelimit")
            self._test_mode = ratelimit_data.get("test_mode", False) if ratelimit_data else False

            self._attr_native_value = get_polling_interval(config_manager, cached_ratelimit=ratelimit_data)
            self._attr_available = True

            # Get custom day/night intervals (None if not set by user)
            custom_day = config_manager.get_custom_day_interval()
            custom_night = config_manager.get_custom_night_interval()

            # For display, show effective intervals (with defaults)
            self._day_interval = custom_day or DEFAULT_DAY_INTERVAL
            self._night_interval = custom_night or DEFAULT_NIGHT_INTERVAL

            from homeassistant.util import dt as dt_util

            current_hour = dt_util.now().hour
            day_start = config_manager.get_day_start_hour()
            night_start = config_manager.get_night_start_hour()

            is_uniform_mode = day_start == night_start
            if is_uniform_mode:
                self._is_night_mode = False
            else:
                self._is_night_mode = not (day_start <= current_hour < night_start)

            adaptive_interval = None
            if ratelimit_data:
                with contextlib.suppress(Exception):
                    adaptive_interval = _calculate_adaptive_interval(ratelimit_data, config_manager)

            baseline_interval = self._night_interval if self._is_night_mode else self._day_interval

            # When no custom intervals set, we use pure adaptive (Day/Night aware)
            user_set_custom = custom_day is not None or custom_night is not None

            if user_set_custom:
                # User has custom intervals
                if adaptive_interval and adaptive_interval > baseline_interval:
                    self._source = "Adaptive (protecting quota)"
                elif custom_day and custom_night:
                    self._source = "Custom (Day/Night)"
                elif custom_day:
                    self._source = "Custom (Day only)"
                else:
                    self._source = "Custom (Night only)"
            # No custom intervals - using pure adaptive (Day/Night aware)
            elif adaptive_interval is not None:
                if is_uniform_mode:
                    self._source = "Adaptive (Uniform Mode)"
                elif self._is_night_mode:
                    self._source = "Adaptive (Night - fixed 120 min)"
                else:
                    self._source = "Adaptive (Day)"
            else:
                self._source = "Default (Day/Night)"

        except Exception as e:
            _LOGGER.debug("Failed to update Polling Interval sensor: %s", e)


class TadoApiHistorySensor(TadoHubSensor):
    """Sensor showing API call history."""

    def __init__(self, coordinator: TadoDataUpdateCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        _meta = ENTITY_REGISTRY["sensor_call_history"]
        self._attr_translation_key = _meta.translation_key
        self._attr_unique_id = f"tado_ce_{coordinator.home_id}_{_meta.unique_id_suffix}"
        self._attr_icon = _meta.icon
        self._attr_native_unit_of_measurement = "calls"
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_entity_category = get_entity_category(_meta)
        self._attr_entity_registry_enabled_default = _meta.enabled_default
        self._history: list[dict[str, Any]] = []
        self._history_period_days: int = 14
        self._oldest_call: str | None = None
        self._newest_call: str | None = None
        self._calls_per_hour: float | None = None
        self._calls_today: int | None = None
        self._most_called_endpoint: str | None = None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra state attributes."""
        return {
            "history": self._history,
            "history_period_days": self._history_period_days,
            "oldest_call": self._oldest_call,
            "newest_call": self._newest_call,
            "calls_per_hour": self._calls_per_hour,
            "calls_today": self._calls_today,
            "most_called_endpoint": self._most_called_endpoint,
        }

    @callback
    def update(self) -> None:
        """Update sensor state from coordinator data."""
        try:
            from datetime import datetime, timedelta

            from homeassistant.util import dt as dt_util

            try:
                _ed = self.coordinator
                self._history_period_days = _ed.config_manager.get_api_history_retention_days()
            except (AttributeError, TypeError, KeyError):
                self._history_period_days = 14

            history_data = (self.coordinator.data or {}).get("api_call_history")
            if not history_data:
                self._attr_available = True
                self._attr_native_value = 0
                self._history = []
                return

            all_calls = []
            for calls in history_data.values():
                all_calls.extend(calls)

            if not all_calls:
                self._attr_available = True
                self._attr_native_value = 0
                self._history = []
                return

            all_calls.sort(key=lambda x: x["timestamp"], reverse=True)

            self._attr_native_value = len(all_calls)
            self._attr_available = True

            recent_calls = []
            for call in all_calls[:100]:
                call_copy = call.copy()
                try:
                    ts = datetime.fromisoformat(call["timestamp"])
                    if ts.tzinfo is None:
                        ts = ts.replace(tzinfo=dt_util.UTC)
                    local_ts = dt_util.as_local(ts)
                    call_copy["timestamp"] = local_ts.strftime("%Y-%m-%d %H:%M:%S")
                except Exception:
                    _LOGGER.debug("Failed to convert timestamp for history call entry")
                recent_calls.append(call_copy)
            self._history = recent_calls

            try:
                oldest_ts = datetime.fromisoformat(all_calls[-1]["timestamp"])
                if oldest_ts.tzinfo is None:
                    oldest_ts = oldest_ts.replace(tzinfo=dt_util.UTC)
                self._oldest_call = dt_util.as_local(oldest_ts).strftime("%Y-%m-%d %H:%M:%S")

                newest_ts = datetime.fromisoformat(all_calls[0]["timestamp"])
                if newest_ts.tzinfo is None:
                    newest_ts = newest_ts.replace(tzinfo=dt_util.UTC)
                self._newest_call = dt_util.as_local(newest_ts).strftime("%Y-%m-%d %H:%M:%S")
            except Exception as e:
                _LOGGER.debug("Failed to parse oldest/newest timestamps: %s", e)
                self._oldest_call = None
                self._newest_call = None

            try:
                now = datetime.now(UTC)
                cutoff = now - timedelta(hours=24)
                last_24h_calls = [
                    c for c in all_calls if datetime.fromisoformat(c["timestamp"]).replace(tzinfo=UTC) > cutoff
                ]
                if last_24h_calls:
                    self._calls_per_hour = round(len(last_24h_calls) / 24, 1)
                else:
                    self._calls_per_hour = 0
            except Exception as e:
                _LOGGER.debug("Failed to calculate calls per hour: %s", e)
                self._calls_per_hour = None

            try:
                today_str = datetime.now(UTC).strftime("%Y-%m-%d")
                self._calls_today = len(history_data.get(today_str, []))
            except Exception as e:
                _LOGGER.debug("Failed to calculate calls today: %s", e)
                self._calls_today = None

            # Find most called endpoint
            try:
                endpoint_counts: dict[str, int] = {}
                for call in all_calls:
                    endpoint = call.get("type_name", "unknown")
                    endpoint_counts[endpoint] = endpoint_counts.get(endpoint, 0) + 1

                if endpoint_counts:
                    most_called = max(endpoint_counts.items(), key=lambda x: x[1])
                    self._most_called_endpoint = f"{most_called[0]} ({most_called[1]} calls)"
                else:
                    self._most_called_endpoint = None
            except Exception as e:
                _LOGGER.debug("Failed to find most called endpoint: %s", e)
                self._most_called_endpoint = None

        except Exception:
            _LOGGER.exception("Failed to update Call History sensor")


class TadoApiBreakdownSensor(TadoHubSensor):
    """Sensor showing API call breakdown by type."""

    def __init__(self, coordinator: TadoDataUpdateCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        _meta = ENTITY_REGISTRY["sensor_api_breakdown"]
        self._attr_translation_key = _meta.translation_key
        self._attr_unique_id = f"tado_ce_{coordinator.home_id}_{_meta.unique_id_suffix}"
        self._attr_icon = _meta.icon
        self._attr_entity_category = get_entity_category(_meta)
        self._attr_entity_registry_enabled_default = _meta.enabled_default
        self._breakdown_24h: dict[str, int] = {}
        self._breakdown_today: dict[str, int] = {}
        self._breakdown_total: dict[str, int] = {}
        self._top_3_types: list[dict[str, Any]] = []
        self._chart_data: list[dict[str, Any]] = []

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra state attributes."""
        return {
            "breakdown_24h": self._breakdown_24h,
            "breakdown_today": self._breakdown_today,
            "breakdown_total": self._breakdown_total,
            "top_3_types": self._top_3_types,
            "chart_data": self._chart_data,
        }

    @callback
    def update(self) -> None:
        """Update sensor state from coordinator data."""
        try:
            from datetime import datetime, timedelta

            history_data = (self.coordinator.data or {}).get("api_call_history")
            if not history_data:
                self._attr_available = True
                self._attr_native_value = "No data"
                self._breakdown_24h = {}
                self._breakdown_today = {}
                self._breakdown_total = {}
                self._top_3_types = []
                self._chart_data = []
                return

            all_calls = []
            for calls in history_data.values():
                all_calls.extend(calls)

            if not all_calls:
                self._attr_available = True
                self._attr_native_value = "No data"
                self._breakdown_24h = {}
                self._breakdown_today = {}
                self._breakdown_total = {}
                self._top_3_types = []
                self._chart_data = []
                return

            now = datetime.now(UTC)
            cutoff_24h = now - timedelta(hours=24)
            breakdown_24h: dict[str, int] = {}

            for call in all_calls:
                try:
                    ts = datetime.fromisoformat(call["timestamp"])
                    if ts.tzinfo is None:
                        ts = ts.replace(tzinfo=UTC)

                    if ts > cutoff_24h:
                        type_name = call.get("type_name", "unknown")
                        breakdown_24h[type_name] = breakdown_24h.get(type_name, 0) + 1
                except Exception:
                    _LOGGER.debug("Failed to parse timestamp in 24h breakdown")
                    continue

            self._breakdown_24h = breakdown_24h

            today_str = now.strftime("%Y-%m-%d")
            breakdown_today: dict[str, int] = {}
            today_calls = history_data.get(today_str, [])

            for call in today_calls:
                type_name = call.get("type_name", "unknown")
                breakdown_today[type_name] = breakdown_today.get(type_name, 0) + 1

            self._breakdown_today = breakdown_today

            # Calculate total breakdown (all history)
            breakdown_total: dict[str, int] = {}
            for call in all_calls:
                type_name = call.get("type_name", "unknown")
                breakdown_total[type_name] = breakdown_total.get(type_name, 0) + 1

            self._breakdown_total = breakdown_total

            # Find top 3 types (based on 24h data)
            if breakdown_24h:
                sorted_types = sorted(breakdown_24h.items(), key=lambda x: x[1], reverse=True)
                self._top_3_types = [{"type": type_name, "count": count} for type_name, count in sorted_types[:3]]

                self._attr_native_value = sorted_types[0][0]
            else:
                self._top_3_types = []
                self._attr_native_value = "No data"

            # Format chart data for visualization (24h data)
            self._chart_data = [
                {"type": type_name, "count": count}
                for type_name, count in sorted(breakdown_24h.items(), key=lambda x: x[1], reverse=True)
            ]

            self._attr_available = True

        except Exception:
            _LOGGER.exception("Failed to update API Call Breakdown sensor")
