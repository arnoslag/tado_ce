"""Tado CE Hub Sensors — API status, home info, monitoring."""
from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import EntityCategory
from homeassistant.core import callback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DATA_DIR
from .device_manager import get_hub_device_info
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

    def __init__(self, coordinator: "TadoDataUpdateCoordinator") -> None:
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
    def update(self):
        """Update sensor state from coordinator data. Override in subclasses."""

class TadoHomeIdSensor(TadoHubSensor):

    """Sensor showing Tado Home ID."""

    def __init__(self, coordinator: "TadoDataUpdateCoordinator"):
        super().__init__(coordinator)
        self._attr_name = "[CE] Home ID"
        self.entity_id = "sensor.tado_ce_home_id"
        self._attr_unique_id = f"tado_ce_{coordinator.home_id}_home_id"
        self._attr_icon = "mdi:home"
        self._attr_entity_category = EntityCategory.DIAGNOSTIC


    @callback
    def update(self):
        try:
            # Use coordinator cached config data (async-loaded, no file I/O)
            coord_data = self.coordinator.data or {}
            config = coord_data.get("config")
            if config:
                self._attr_native_value = config.get("home_id")
                self._attr_available = self._attr_native_value is not None
            else:
                self._attr_available = False
        except Exception:
            self._attr_available = False


class TadoApiUsageSensor(TadoHubSensor):

    """Sensor for Tado API usage tracking."""

    def __init__(self, coordinator: "TadoDataUpdateCoordinator"):
        super().__init__(coordinator)
        self._attr_name = "[CE] API Usage"
        self.entity_id = "sensor.tado_ce_api_usage"
        self._attr_unique_id = f"tado_ce_{coordinator.home_id}_api_usage"
        self._attr_native_unit_of_measurement = "calls"
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._data = {}
        self._call_history = []

    @property
    def icon(self):
        status = self._data.get("status")
        if status == "rate_limited":
            return "mdi:api-off"
        elif status == "error":
            return "mdi:alert-circle"
        return "mdi:api"

    @property
    def extra_state_attributes(self):
        # Read test_mode directly from ratelimit.json (Single Source of Truth)
        test_mode = self._data.get("test_mode", False)

        attrs = {
            "limit": self._data.get("limit"),
            "remaining": self._data.get("remaining"),
            "percentage_used": self._data.get("percentage_used"),
            "last_updated": self._data.get("last_updated"),
            "status": self._data.get("status"),
            "test_mode": test_mode,  # Always show test_mode status
        }

        # Add descriptive test mode message if enabled
        if test_mode:
            attrs["test_mode_info"] = "Simulated 100-call API tier"
            # Add Test Mode cycle info
            test_mode_start = self._data.get("test_mode_start_time")
            test_mode_used = self._data.get("test_mode_used")
            if test_mode_start:
                attrs["test_mode_start_time"] = test_mode_start
            if test_mode_used is not None:
                attrs["test_mode_used"] = test_mode_used

        # Add call history if available
        if self._call_history:
            attrs["call_history"] = self._call_history

        return attrs


    @callback
    def update(self):
        try:
            # Use coordinator cached ratelimit data (async-loaded, no file I/O)
            self._data = (self.coordinator.data or {}).get("ratelimit")
            if self._data:
                used = self._data.get("used")
                if used is not None:
                    self._attr_native_value = int(used)
                    self._attr_available = True
                else:
                    self._attr_available = False
            else:
                self._attr_available = False

            # Load call history from tracker and convert to local timezone
            try:
                from datetime import datetime

                from homeassistant.util import dt as dt_util

                from .api_call_tracker import APICallTracker

                # Get retention days from per-entry config_manager
                retention_days = 14  # default
                try:
                    _ed = self.coordinator
                    retention_days = _ed.config_manager.get_api_history_retention_days()
                except (AttributeError, TypeError, KeyError):
                    pass

                # Get home_id for per-home file path
                home_id = self.coordinator.home_id

                tracker = APICallTracker(DATA_DIR, retention_days=retention_days, home_id=home_id)
                raw_history = tracker.get_recent_calls(limit=50)

                # Convert timestamps to local timezone for display
                self._call_history = []
                for call in raw_history:
                    call_copy = call.copy()
                    try:
                        # Parse ISO timestamp and convert to local
                        ts = datetime.fromisoformat(call["timestamp"])
                        if ts.tzinfo is None:
                            # Assume UTC if no timezone
                            ts = ts.replace(tzinfo=dt_util.UTC)
                        local_ts = dt_util.as_local(ts)
                        call_copy["timestamp"] = local_ts.strftime("%Y-%m-%d %H:%M:%S")
                    except Exception:
                        pass  # Keep original timestamp if conversion fails
                    self._call_history.append(call_copy)
            except FileNotFoundError:
                _LOGGER.debug("API call history file not found - first run or migration pending")
                self._call_history = []
            except PermissionError:
                _LOGGER.warning("Permission denied reading API call history file")
                self._call_history = []
            except json.JSONDecodeError as e:
                _LOGGER.error("Invalid JSON in API call history file: %s", e)
                self._call_history = []
            except Exception as e:
                _LOGGER.debug("Failed to load call history: %s", e)
                self._call_history = []

        except FileNotFoundError:
            _LOGGER.debug("Ratelimit file not found - first run or migration pending")
        except PermissionError:
            _LOGGER.error("Permission denied reading ratelimit file")
        except json.JSONDecodeError as e:
            _LOGGER.error("Invalid JSON in ratelimit file: %s", e)
        except Exception as e:
            _LOGGER.error("Unexpected error loading ratelimit data: %s", e, exc_info=True)

class TadoApiResetSensor(TadoHubSensor):

    """Sensor showing API rate limit reset time."""

    def __init__(self, coordinator: "TadoDataUpdateCoordinator"):
        super().__init__(coordinator)
        self._attr_name = "[CE] API Reset"
        self.entity_id = "sensor.tado_ce_api_reset"
        self._attr_unique_id = f"tado_ce_{coordinator.home_id}_api_reset"
        self._attr_icon = "mdi:timer-refresh"
        self._attr_device_class = "timestamp"
        self._reset_human = None
        self._reset_seconds = None
        self._reset_at = None  # Actual reset time string
        self._last_reset = None  # Last reset time string
        self._status = None
        self._next_poll = None
        self._current_interval = None
        self._test_mode = False  # Test Mode indicator
        self._test_mode_start_time = None  # Test Mode cycle start

    @property
    def extra_state_attributes(self):
        attrs = {
            "time_until_reset": self._reset_human,
            "reset_seconds": self._reset_seconds,
            "reset_at": self._reset_at,  # When next reset will happen
            "last_reset": self._last_reset,  # When last reset happened
            "status": self._status,
            "next_poll": self._next_poll,
            "current_interval_minutes": self._current_interval,
            "test_mode": self._test_mode,  # Test Mode indicator
        }

        # Add Test Mode specific info
        if self._test_mode:
            attrs["test_mode_info"] = "Simulated 24h cycle from enable time"
            if self._test_mode_start_time:
                attrs["test_mode_start_time"] = self._test_mode_start_time

        return attrs


    @callback
    def update(self):
        try:
            from datetime import datetime, timedelta, timezone

            from homeassistant.util import dt as dt_util

            # Use coordinator cached ratelimit data (async-loaded, no file I/O)
            data = (self.coordinator.data or {}).get("ratelimit")
            if not data:
                return

            # Read test_mode from ratelimit.json (Single Source of Truth)
            self._test_mode = data.get("test_mode", False)

            # Read test_mode_start_time for display
            test_mode_start = data.get("test_mode_start_time")
            if test_mode_start and self._test_mode:
                try:
                    start_time = datetime.fromisoformat(
                        test_mode_start.replace('Z', '+00:00')
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

            # Format reset_at as local time string for attribute
            reset_at = data.get("reset_at")
            if reset_at and reset_at != "unknown":
                try:
                    reset_time = datetime.fromisoformat(reset_at.replace('Z', '+00:00'))
                    self._attr_native_value = reset_time
                    self._attr_available = True
                    # Format as local time for attribute
                    reset_local = dt_util.as_local(reset_time)
                    self._reset_at = reset_local.strftime("%Y-%m-%d %H:%M:%S")
                except Exception as e:
                    _LOGGER.debug("Failed to parse reset_at: %s", e)
                    self._reset_at = None
            else:
                self._reset_at = None

            # Format last_reset_utc as local time string for attribute
            last_reset_utc = data.get("last_reset_utc")
            if last_reset_utc:
                try:
                    last_reset_time = datetime.fromisoformat(last_reset_utc.replace('Z', '+00:00'))
                    last_reset_local = dt_util.as_local(last_reset_time)
                    self._last_reset = last_reset_local.strftime("%Y-%m-%d %H:%M:%S")
                except Exception as e:
                    _LOGGER.debug("Failed to parse last_reset_utc: %s", e)
                    self._last_reset = None
            else:
                self._last_reset = None

            # Calculate next poll time
            try:
                from homeassistant.util import dt as dt_util

                last_updated = data.get("last_updated")
                if last_updated:
                    # Robust timestamp parsing for different formats
                    # - "2026-01-25T12:00:00Z" (legacy tado_api.py)
                    # - "2026-01-25T12:00:00+00:00" (api_client.py)
                    # - "2026-01-25T12:00:00" (naive, assume UTC)
                    if last_updated.endswith('Z'):
                        last_sync = datetime.fromisoformat(last_updated.replace('Z', '+00:00'))
                    elif '+' in last_updated or last_updated.endswith('00:00'):
                        last_sync = datetime.fromisoformat(last_updated)
                    else:
                        # Naive datetime - assume UTC for backwards compatibility
                        last_sync = datetime.fromisoformat(last_updated).replace(tzinfo=timezone.utc)

                    # Get current polling interval from config
                    from . import get_polling_interval
                    config_manager = self.coordinator.config_manager
                    if config_manager:
                        self._current_interval = get_polling_interval(config_manager)

                        # Calculate next poll time and convert to local timezone
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

    def __init__(self, coordinator: "TadoDataUpdateCoordinator"):
        super().__init__(coordinator)
        self._attr_name = "[CE] API Limit"
        self.entity_id = "sensor.tado_ce_api_limit"
        self._attr_unique_id = f"tado_ce_{coordinator.home_id}_api_limit"
        self._attr_icon = "mdi:speedometer"
        self._attr_native_unit_of_measurement = "calls"
        self._attr_entity_category = EntityCategory.DIAGNOSTIC
        self._attr_extra_state_attributes = {}
        self._test_mode = False  # Test Mode indicator


    @callback
    def update(self):
        try:
            # Use coordinator cached ratelimit data (async-loaded, no file I/O)
            data = (self.coordinator.data or {}).get("ratelimit")
            if data:
                self._attr_native_value = data.get("limit")
                self._attr_available = self._attr_native_value is not None
                # Read test_mode from ratelimit.json
                self._test_mode = data.get("test_mode", False)
            else:
                self._test_mode = False

            # Build extra state attributes
            extra_attrs = {
                "test_mode": self._test_mode,  # Test Mode indicator
            }

            # Add Test Mode info if enabled
            if self._test_mode and data:
                extra_attrs["test_mode_info"] = "Simulated 100-call limit"

            # Load recent API calls from history (last 100 calls only to avoid DB size issues)
            try:
                from datetime import datetime, timedelta

                from homeassistant.util import dt as dt_util

                history = (self.coordinator.data or {}).get("api_call_history")
                if history:
                    # Flatten all calls from all dates
                    all_calls = []
                    for date_key, calls in history.items():
                        all_calls.extend(calls)

                    # Sort by timestamp (newest first) and take last 100
                    all_calls.sort(key=lambda x: x["timestamp"], reverse=True)
                    raw_recent_calls = all_calls[:100]

                    # Convert timestamps to local timezone for display
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
                            pass
                        recent_calls.append(call_copy)

                    # Count calls from last 24 hours for statistics
                    now = datetime.now(dt_util.UTC)
                    cutoff = now - timedelta(hours=24)
                    last_24h_count = sum(
                        1 for call in all_calls
                        if datetime.fromisoformat(call["timestamp"]).replace(tzinfo=dt_util.UTC) > cutoff
                    )

                    extra_attrs.update({
                        "recent_calls": recent_calls,
                        "recent_calls_count": len(recent_calls),
                        "last_24h_count": last_24h_count,
                        "total_calls_tracked": len(all_calls)
                    })
            except Exception as e:
                _LOGGER.debug("Failed to load API call history: %s", e)
                extra_attrs.update({
                    "recent_calls": [],
                    "recent_calls_count": 0,
                    "last_24h_count": 0,
                    "total_calls_tracked": 0
                })

            self._attr_extra_state_attributes = extra_attrs
        except Exception:
            self._attr_available = False

class TadoApiStatusSensor(TadoHubSensor):

    """Sensor showing Tado API status."""

    def __init__(self, coordinator: "TadoDataUpdateCoordinator"):
        super().__init__(coordinator)
        self._attr_name = "[CE] API Status"
        self.entity_id = "sensor.tado_ce_api_status"
        self._attr_unique_id = f"tado_ce_{coordinator.home_id}_api_status"
        self._remaining_calls: int | None = None
        self._total_calls: int | None = None
        self._reset_time: str | None = None
        self._recommendation: str = ""  # Actionable recommendation

    @property
    def icon(self):
        if self._attr_native_value == "ok":
            return "mdi:check-circle"
        elif self._attr_native_value == "rate_limited":
            return "mdi:alert-circle"
        return "mdi:help-circle"

    @property
    def extra_state_attributes(self):
        return {
            "remaining_calls": self._remaining_calls,
            "total_calls": self._total_calls,
            "reset_time": self._reset_time,
            "recommendation": self._recommendation,  # Actionable recommendation
        }


    @callback
    def update(self):
        try:
            # Use coordinator cached ratelimit data (async-loaded, no file I/O)
            data = (self.coordinator.data or {}).get("ratelimit")
            if data:
                self._attr_native_value = _format_api_status(data.get("status", "unknown"))
                self._remaining_calls = data.get("remaining")
                self._total_calls = data.get("limit")
                self._reset_time = data.get("reset_human")

                # Calculate SMART actionable recommendation
                self._recommendation = calculate_api_status_recommendation(
                    remaining_calls=self._remaining_calls,
                    total_calls=self._total_calls,
                    reset_time_human=self._reset_time,
                    current_interval_minutes=None  # Could get from config_manager if needed
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

    def __init__(self, coordinator: "TadoDataUpdateCoordinator"):
        super().__init__(coordinator)
        self._attr_name = "[CE] Token Status"
        self.entity_id = "sensor.tado_ce_token_status"
        self._attr_unique_id = f"tado_ce_{coordinator.home_id}_token_status"
        self._attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def icon(self):
        if self._attr_native_value == "valid":
            return "mdi:key"
        return "mdi:key-alert"


    @callback
    def update(self):
        try:
            # Use coordinator cached config data (async-loaded, no file I/O)
            coord_data = self.coordinator.data or {}
            config = coord_data.get("config")
            if config:
                if config.get("refresh_token"):
                    self._attr_native_value = "valid"
                else:
                    self._attr_native_value = "missing"
                self._attr_available = True
            else:
                self._attr_native_value = "missing"
                self._attr_available = True
        except Exception:
            self._attr_native_value = "error"
            self._attr_available = True

class TadoZoneCountSensor(TadoHubSensor):

    """Sensor showing number of Tado zones."""

    def __init__(self, coordinator: "TadoDataUpdateCoordinator"):
        super().__init__(coordinator)
        self._attr_name = "[CE] Zone Count"
        self.entity_id = "sensor.tado_ce_zone_count"
        self._attr_unique_id = f"tado_ce_{coordinator.home_id}_zone_count"
        self._attr_icon = "mdi:home-thermometer"
        self._attr_native_unit_of_measurement = "zones"
        self._attr_entity_category = EntityCategory.DIAGNOSTIC
        self._heating_zones = 0
        self._hot_water_zones = 0
        self._ac_zones = 0

    @property
    def extra_state_attributes(self):
        return {
            "heating_zones": self._heating_zones,
            "hot_water_zones": self._hot_water_zones,
            "ac_zones": self._ac_zones,
        }


    @callback
    def update(self):
        try:
            # Use coordinator cached zones_info data (async-loaded, no file I/O)
            zones = (self.coordinator.data or {}).get("zones_info")
            if zones:
                self._attr_native_value = len(zones)
                self._heating_zones = len([z for z in zones if z.get('type') == 'HEATING'])
                self._hot_water_zones = len([z for z in zones if z.get('type') == 'HOT_WATER'])
                self._ac_zones = len([z for z in zones if z.get('type') == 'AIR_CONDITIONING'])
                self._attr_available = True
            else:
                self._attr_available = False
        except Exception:
            self._attr_available = False

class TadoLastSyncSensor(TadoHubSensor):

    """Sensor showing last sync time."""

    def __init__(self, coordinator: "TadoDataUpdateCoordinator"):
        super().__init__(coordinator)
        self._attr_name = "[CE] Last Sync"
        self.entity_id = "sensor.tado_ce_last_sync"
        self._attr_unique_id = f"tado_ce_{coordinator.home_id}_last_sync"
        self._attr_icon = "mdi:sync"
        self._attr_device_class = SensorDeviceClass.TIMESTAMP
        self._attr_entity_category = EntityCategory.DIAGNOSTIC


    @callback
    def update(self):
        try:
            # Use coordinator cached ratelimit data (async-loaded, no file I/O)
            data = (self.coordinator.data or {}).get("ratelimit")
            if data:
                last_updated = data.get("last_updated")
                if last_updated:
                    from datetime import datetime, timezone
                    # Robust timestamp parsing for different formats
                    if last_updated.endswith('Z'):
                        self._attr_native_value = datetime.fromisoformat(last_updated.replace('Z', '+00:00'))
                    elif '+' in last_updated or last_updated.endswith('00:00'):
                        self._attr_native_value = datetime.fromisoformat(last_updated)
                    else:
                        # Naive datetime - assume UTC for backwards compatibility
                        self._attr_native_value = datetime.fromisoformat(last_updated).replace(tzinfo=timezone.utc)
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

    def __init__(self, coordinator: "TadoDataUpdateCoordinator"):
        super().__init__(coordinator)
        self._attr_name = "[CE] Next Sync"
        self.entity_id = "sensor.tado_ce_next_sync"
        self._attr_unique_id = f"tado_ce_{coordinator.home_id}_next_sync"
        self._attr_icon = "mdi:clock-outline"
        self._attr_device_class = SensorDeviceClass.TIMESTAMP
        self._attr_entity_category = EntityCategory.DIAGNOSTIC
        self._countdown = None
        self._current_interval = None

    @property
    def extra_state_attributes(self):
        return {
            "countdown": self._countdown,
            "current_interval_minutes": self._current_interval,
        }


    @callback
    def update(self):
        try:
            from datetime import datetime, timedelta, timezone

            # Use coordinator cached ratelimit data (async-loaded, no file I/O)
            data = (self.coordinator.data or {}).get("ratelimit")
            if not data:
                return

            last_updated = data.get("last_updated")
            if not last_updated:
                return

            # Parse last sync time
            if last_updated.endswith('Z'):
                last_sync = datetime.fromisoformat(last_updated.replace('Z', '+00:00'))
            elif '+' in last_updated or last_updated.endswith('00:00'):
                last_sync = datetime.fromisoformat(last_updated)
            else:
                last_sync = datetime.fromisoformat(last_updated).replace(tzinfo=timezone.utc)

            # Get current polling interval from config
            from . import get_polling_interval
            config_manager = self.coordinator.config_manager
            if config_manager:
                self._current_interval = get_polling_interval(config_manager)

                # Calculate next sync time
                next_sync_time = last_sync + timedelta(minutes=self._current_interval)
                self._attr_native_value = next_sync_time
                self._attr_available = True

                # Calculate countdown
                now = datetime.now(timezone.utc)
                time_until = next_sync_time - now
                if time_until.total_seconds() > 0:
                    minutes = int(time_until.total_seconds() // 60)
                    seconds = int(time_until.total_seconds() % 60)
                    self._countdown = f"{minutes}m {seconds}s"
                else:
                    self._countdown = "Overdue"
            else:
                self._current_interval = None
                self._countdown = None

        except Exception as e:
            _LOGGER.debug("Failed to update Next Sync sensor: %s", e)


class TadoPollingIntervalSensor(TadoHubSensor):

    """Sensor showing current polling interval."""

    def __init__(self, coordinator: "TadoDataUpdateCoordinator"):
        super().__init__(coordinator)
        self._attr_name = "[CE] Polling Interval"
        self.entity_id = "sensor.tado_ce_polling_interval"
        self._attr_unique_id = f"tado_ce_{coordinator.home_id}_polling_interval"
        self._attr_icon = "mdi:timer-outline"
        self._attr_native_unit_of_measurement = "min"
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_entity_category = EntityCategory.DIAGNOSTIC
        self._source = None
        self._day_interval = None
        self._night_interval = None
        self._is_night_mode = None
        self._test_mode = False  # Test Mode indicator

    @property
    def extra_state_attributes(self):
        return {
            "source": self._source,
            "day_interval": self._day_interval,
            "night_interval": self._night_interval,
            "is_night_mode": self._is_night_mode,
            "test_mode": self._test_mode,  # Test Mode indicator
        }


    @callback
    def update(self):
        try:
            from datetime import datetime

            from . import (
                DEFAULT_DAY_INTERVAL,
                DEFAULT_NIGHT_INTERVAL,
                _calculate_adaptive_interval,
                get_polling_interval,
            )

            config_manager = self.coordinator.config_manager
            if not config_manager:
                return

            # Use coordinator cached ratelimit data (async-loaded, no file I/O)
            ratelimit_data = (self.coordinator.data or {}).get("ratelimit")
            self._test_mode = ratelimit_data.get("test_mode", False) if ratelimit_data else False

            # Get current interval
            self._attr_native_value = get_polling_interval(config_manager)
            self._attr_available = True

            # Get custom day/night intervals (None if not set by user)
            custom_day = config_manager.get_custom_day_interval()
            custom_night = config_manager.get_custom_night_interval()

            # For display, show effective intervals (with defaults)
            self._day_interval = custom_day if custom_day else DEFAULT_DAY_INTERVAL
            self._night_interval = custom_night if custom_night else DEFAULT_NIGHT_INTERVAL

            # Check if currently in night mode based on config hours
            current_hour = datetime.now().hour
            day_start = config_manager.get_day_start_hour()
            night_start = config_manager.get_night_start_hour()

            # Handle Uniform Mode (day_start == night_start)
            is_uniform_mode = day_start == night_start
            if is_uniform_mode:
                self._is_night_mode = False  # Uniform Mode is always "Day"
            else:
                self._is_night_mode = not (day_start <= current_hour < night_start)

            # Determine source more accurately
            # Check if adaptive is overriding the baseline interval
            adaptive_interval = None
            if ratelimit_data:
                try:
                    adaptive_interval = _calculate_adaptive_interval(ratelimit_data, config_manager)
                except Exception:
                    pass

            baseline_interval = self._night_interval if self._is_night_mode else self._day_interval

            # Determine source based on what's actually being used
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
            else:
                # No custom intervals - using pure adaptive (Day/Night aware)
                if adaptive_interval is not None:
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

    def __init__(self, coordinator: "TadoDataUpdateCoordinator"):
        super().__init__(coordinator)
        self._attr_name = "[CE] Call History"
        self.entity_id = "sensor.tado_ce_call_history"
        self._attr_unique_id = f"tado_ce_{coordinator.home_id}_call_history"
        self._attr_icon = "mdi:history"
        self._attr_native_unit_of_measurement = "calls"
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_entity_category = EntityCategory.DIAGNOSTIC
        self._history = []
        self._history_period_days = 14
        self._oldest_call = None
        self._newest_call = None
        self._calls_per_hour = None
        self._calls_today = None
        self._most_called_endpoint = None

    @property
    def extra_state_attributes(self):
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
    def update(self):
        try:
            from datetime import datetime, timedelta, timezone

            from homeassistant.util import dt as dt_util

            # Get retention days from per-entry config_manager
            try:
                _ed = self.coordinator
                self._history_period_days = _ed.config_manager.get_api_history_retention_days()
            except (AttributeError, TypeError, KeyError):
                self._history_period_days = 14

            # Use coordinator cached api_call_history data (async-loaded, no file I/O)
            history_data = (self.coordinator.data or {}).get("api_call_history")
            if not history_data:
                self._attr_available = True
                self._attr_native_value = 0
                self._history = []
                return

            # Flatten all calls from all dates
            all_calls = []
            for date_key, calls in history_data.items():
                all_calls.extend(calls)

            if not all_calls:
                self._attr_available = True
                self._attr_native_value = 0
                self._history = []
                return

            # Sort by timestamp (newest first)
            all_calls.sort(key=lambda x: x["timestamp"], reverse=True)

            # Set state to total call count
            self._attr_native_value = len(all_calls)
            self._attr_available = True

            # Store recent calls (last 100) with local timezone conversion
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
                    pass
                recent_calls.append(call_copy)
            self._history = recent_calls

            # Calculate oldest/newest call timestamps
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

            # Calculate calls per hour (last 24h)
            try:
                now = datetime.now(timezone.utc)
                cutoff = now - timedelta(hours=24)
                last_24h_calls = [
                    c for c in all_calls
                    if datetime.fromisoformat(c["timestamp"]).replace(tzinfo=timezone.utc) > cutoff
                ]
                if last_24h_calls:
                    self._calls_per_hour = round(len(last_24h_calls) / 24, 1)
                else:
                    self._calls_per_hour = 0
            except Exception as e:
                _LOGGER.debug("Failed to calculate calls per hour: %s", e)
                self._calls_per_hour = None

            # Calculate calls today (UTC day)
            try:
                today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
                self._calls_today = len(history_data.get(today_str, []))
            except Exception as e:
                _LOGGER.debug("Failed to calculate calls today: %s", e)
                self._calls_today = None

            # Find most called endpoint
            try:
                endpoint_counts = {}
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

        except Exception as e:
            _LOGGER.error("Failed to update Call History sensor: %s", e)


class TadoApiBreakdownSensor(TadoHubSensor):

    """Sensor showing API call breakdown by type."""

    def __init__(self, coordinator: "TadoDataUpdateCoordinator"):
        super().__init__(coordinator)
        self._attr_name = "[CE] API Breakdown"
        self.entity_id = "sensor.tado_ce_api_call_breakdown"
        self._attr_unique_id = f"tado_ce_{coordinator.home_id}_api_breakdown"
        self._attr_icon = "mdi:chart-bar"
        self._attr_entity_category = EntityCategory.DIAGNOSTIC
        self._breakdown_24h = {}
        self._breakdown_today = {}
        self._breakdown_total = {}
        self._top_3_types = []
        self._chart_data = []

    @property
    def extra_state_attributes(self):
        return {
            "breakdown_24h": self._breakdown_24h,
            "breakdown_today": self._breakdown_today,
            "breakdown_total": self._breakdown_total,
            "top_3_types": self._top_3_types,
            "chart_data": self._chart_data,
        }


    @callback
    def update(self):
        try:
            from datetime import datetime, timedelta, timezone

            # Use coordinator cached api_call_history data (async-loaded, no file I/O)
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

            # Flatten all calls from all dates
            all_calls = []
            for date_key, calls in history_data.items():
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

            # Calculate breakdown for last 24 hours
            now = datetime.now(timezone.utc)
            cutoff_24h = now - timedelta(hours=24)
            breakdown_24h = {}

            for call in all_calls:
                try:
                    ts = datetime.fromisoformat(call["timestamp"])
                    if ts.tzinfo is None:
                        ts = ts.replace(tzinfo=timezone.utc)

                    if ts > cutoff_24h:
                        type_name = call.get("type_name", "unknown")
                        breakdown_24h[type_name] = breakdown_24h.get(type_name, 0) + 1
                except Exception:
                    continue

            self._breakdown_24h = breakdown_24h

            # Calculate breakdown for today (UTC day)
            today_str = now.strftime("%Y-%m-%d")
            breakdown_today = {}
            today_calls = history_data.get(today_str, [])

            for call in today_calls:
                type_name = call.get("type_name", "unknown")
                breakdown_today[type_name] = breakdown_today.get(type_name, 0) + 1

            self._breakdown_today = breakdown_today

            # Calculate total breakdown (all history)
            breakdown_total = {}
            for call in all_calls:
                type_name = call.get("type_name", "unknown")
                breakdown_total[type_name] = breakdown_total.get(type_name, 0) + 1

            self._breakdown_total = breakdown_total

            # Find top 3 types (based on 24h data)
            if breakdown_24h:
                sorted_types = sorted(breakdown_24h.items(), key=lambda x: x[1], reverse=True)
                self._top_3_types = [
                    {"type": type_name, "count": count}
                    for type_name, count in sorted_types[:3]
                ]

                # Set state to most called type
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

        except Exception as e:
            _LOGGER.error("Failed to update API Call Breakdown sensor: %s", e)

