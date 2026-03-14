"""Tado CE Insight Sensors — home and zone actionable insights."""

from __future__ import annotations

from datetime import UTC, datetime
import logging
from typing import TYPE_CHECKING, Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.core import callback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .device_manager import get_hub_device_info, get_zone_device_info
from .entity_registry import ENTITY_REGISTRY, get_entity_category
from .format_helpers import (
    format_health_score as _format_health_score,
)
from .format_helpers import (
    format_insight_type as _format_insight_type,
)
from .format_helpers import (
    format_persistent_insights_grouped as _format_persistent_insights_grouped,
)
from .format_helpers import (
    format_priority as _format_priority,
)
from .format_helpers import (
    strip_zone_prefix as _strip_zone_prefix,
)
from .insights import Insight, aggregate_home_insights, calculate_insight_health_score
from .insights import build_weekly_digest as _build_weekly_digest
from .insights import correlate_insights as _correlate_insights
from .insights import escalate_priorities as _escalate_priorities
from .sensor_insight_collector import (
    collect_single_zone_insights,
    collect_zone_insights,
    get_cross_zone_insights,
    get_hub_insights,
)

if TYPE_CHECKING:
    from .coordinator import TadoDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)


class TadoHomeInsightsSensor(CoordinatorEntity["TadoDataUpdateCoordinator"], SensorEntity):
    """Represent a Tado home-level actionable insights sensor."""

    _attr_has_entity_name = True

    """Hub-level sensor aggregating actionable insights from all zones.

    Collects insights from zone sensors (mold risk, comfort,
    battery, connection, window predicted, preheat timing, schedule
    deviation, heating anomaly) and aggregates them into a single
    home-level summary with priority-based recommendations.

    Also includes cross-zone aggregation (mold risk, window predicted),
    hub-level insights (API quota planning, weather impact).

    State: Total number of active insights (integer)
    """

    def __init__(self, coordinator: TadoDataUpdateCoordinator) -> None:
        """Initialize the Home Insights Sensor."""
        super().__init__(coordinator)
        _meta = ENTITY_REGISTRY["sensor_home_insights"]
        self._attr_translation_key = _meta.translation_key
        self._attr_unique_id = f"tado_ce_{coordinator.home_id}_{_meta.unique_id_suffix}"
        self._attr_device_info = get_hub_device_info(coordinator.home_id)
        self._attr_entity_category = get_entity_category(_meta)
        self._attr_available = False
        self._attr_native_value = 0
        self._aggregated: dict[str, Any] = {}
        self._health_score: int = 100
        # Weekly digest cache — recompute only when date changes
        self._weekly_digest: str = ""
        self._weekly_digest_date: str = ""
        # Track per-zone heating anomaly start times for real duration measurement
        self._anomaly_start_times: dict[str, datetime] = {}
        # Per-zone humidity history for trend detection (in-memory only)
        self._humidity_histories: dict[str, list[Any]] = {}

    @property
    def icon(self) -> str | None:
        """Dynamic icon based on top priority."""
        top = self._aggregated.get("top_priority", "none")
        if top == "critical":
            return "mdi:alert-octagon"
        if top == "high":
            return "mdi:alert-circle"
        if top == "medium":
            return "mdi:alert"
        if top == "low":
            return "mdi:information"
        return "mdi:home-analytics"

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return extra state attributes."""
        raw_persistent = self.coordinator.insight_history.get_persistent_insights()
        return {
            "summary": self._aggregated.get("summary", ""),
            "actions_needed": self._aggregated.get("actions_needed", []),
            "zones_ok": self._aggregated.get("zones_ok", []),
            "top_priority": _format_priority(self._aggregated.get("top_priority", "none")),
            "top_recommendation": self._aggregated.get("top_recommendation", ""),
            "zones_with_issues": self._aggregated.get("zones_with_issues", []),
            "cross_zone_insights": self._aggregated.get("cross_zone_insights", []),
            "persistent_insights": _format_persistent_insights_grouped(raw_persistent),
            "insight_health_score": _format_health_score(self._health_score),
            "weekly_digest": self._weekly_digest,
        }

    @callback
    def _handle_coordinator_update(self) -> None:
        self.update()
        self.async_write_ha_state()

    @callback
    def update(self) -> None:
        """Update home insights by collecting and aggregating zone data."""
        try:
            zone_insights = collect_zone_insights(
                self.hass,
                self.coordinator,
                self._anomaly_start_times,
                self._humidity_histories,
            )

            cross_zone = get_cross_zone_insights(
                self.hass,
                self.coordinator,
                zone_insights,
            )

            hub = get_hub_insights(self.hass, self.coordinator)

            if hub:
                zone_insights["_hub"] = hub
            if cross_zone:
                zone_insights["_cross_zone"] = cross_zone

            all_insights = []
            for insights_list in zone_insights.values():
                all_insights.extend(insights_list)

            # Update insight history with current poll cycle
            now = datetime.now(UTC)
            self.coordinator.insight_history.update(all_insights, now)

            # Escalate priorities based on persistence duration
            history = self.coordinator.insight_history
            escalated = _escalate_priorities(all_insights, history, now)

            # Rebuild zone_insights with escalated insights (preserving zone grouping)
            idx = 0
            for zone_key in zone_insights:
                count = len(zone_insights[zone_key])
                zone_insights[zone_key] = escalated[idx : idx + count]
                idx += count

            # Append duration text for persistent insights (≥ 24h)
            for zone_key in zone_insights:
                for i, insight in enumerate(zone_insights[zone_key]):
                    dur = history.get_duration(insight.insight_type, insight.zone_name)
                    if dur is not None and dur.total_seconds() >= 86400:
                        days = int(dur.total_seconds() // 86400)
                        label = "1 day" if days == 1 else f"{days} days"
                        zone_insights[zone_key][i] = Insight(
                            priority=insight.priority,
                            recommendation=f"{insight.recommendation} (persisting for {label})",
                            insight_type=insight.insight_type,
                            zone_name=insight.zone_name,
                        )

            # Correlate related insights within each zone
            zone_insights = _correlate_insights(zone_insights)

            # Compute health score from escalated insights (before correlation)
            self._health_score = calculate_insight_health_score(escalated)

            # Update weekly digest (recompute only when date changes)
            today = now.strftime("%Y-%m-%d")
            if today != self._weekly_digest_date:
                self._weekly_digest = _build_weekly_digest(
                    self.coordinator.insight_history,
                    now,
                )
                self._weekly_digest_date = today

            self._aggregated = aggregate_home_insights(zone_insights)

            cross_recs = [i.recommendation for i in cross_zone if i.recommendation]
            self._aggregated["cross_zone_insights"] = cross_recs

            self._attr_native_value = len(self._aggregated.get("actions_needed", []))
            self._attr_available = True
        except Exception as e:
            _LOGGER.debug("Failed to update home insights: %s", e)
            self._attr_available = False


class TadoZoneInsightsSensor(CoordinatorEntity["TadoDataUpdateCoordinator"], SensorEntity):
    """Represent a Tado zone-level actionable insights sensor."""

    _attr_has_entity_name = True

    """Per-zone sensor showing actionable insights for a single zone.

    Collects insights specific to this zone (mold risk, comfort,
    battery, connection, window predicted, preheat timing, heating anomaly)
    and presents them as a zone-level summary.

    State: Number of active insights for this zone (integer)
    """

    def __init__(self, coordinator: TadoDataUpdateCoordinator, zone_id: str, zone_name: str, zone_type: str) -> None:
        """Initialize the Zone Insights Sensor."""
        super().__init__(coordinator)
        self._zone_id = zone_id
        self._zone_name = zone_name
        self._zone_type = zone_type
        _meta = ENTITY_REGISTRY["sensor_insights"]
        self._attr_translation_key = _meta.translation_key
        self._attr_unique_id = f"tado_ce_{coordinator.home_id}_{_meta.unique_id_suffix.format(zone_id=zone_id)}"
        self._attr_device_info = get_zone_device_info(zone_id, zone_name, zone_type, coordinator.home_id)
        self._attr_entity_category = get_entity_category(_meta)
        self._attr_available = False
        self._attr_native_value = 0
        self._insights: list[Any] = []
        # Use dict for anomaly tracking (consistent with Home sensor)
        self._anomaly_start_times: dict[str, datetime] = {}

    @property
    def icon(self) -> str | None:
        """Dynamic icon based on top priority."""
        if not self._insights:
            return "mdi:lightbulb-outline"
        top = max(self._insights, key=lambda i: i.priority.value)
        name = top.priority.name.lower()
        if name == "critical":
            return "mdi:alert-octagon"
        if name == "high":
            return "mdi:alert-circle"
        if name == "medium":
            return "mdi:alert"
        if name == "low":
            return "mdi:information"
        return "mdi:lightbulb-outline"

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return extra state attributes."""
        if not self._insights:
            return {
                "top_priority": "None",
                "top_recommendation": "",
                "insight_types": [],
                "recommendations": [],
            }
        top = max(self._insights, key=lambda i: i.priority.value)
        return {
            "top_priority": _format_priority(top.priority.name.lower()),
            "top_recommendation": _strip_zone_prefix(top.recommendation, self._zone_name),
            "insight_types": [_format_insight_type(i.insight_type) for i in self._insights],
            "recommendations": [_strip_zone_prefix(i.recommendation, self._zone_name) for i in self._insights],
        }

    @callback
    def _handle_coordinator_update(self) -> None:
        self.update()
        self.async_write_ha_state()

    @callback
    def update(self) -> None:
        """Collect insights for this zone using shared collector."""
        try:
            coord_data = self.coordinator.data or {}
            zones_data = coord_data.get("zones")
            if not zones_data:
                self._attr_available = False
                return

            zone_states = zones_data.get("zoneStates") or {}
            zone_data = zone_states.get(self._zone_id)
            if not zone_data:
                self._attr_available = False
                return

            zones_info = coord_data.get("zones_info")

            self._insights = collect_single_zone_insights(
                hass=self.hass,
                coordinator=self.coordinator,
                zone_id=self._zone_id,
                zone_name=self._zone_name,
                zone_data=zone_data,
                zones_info=zones_info,
                anomaly_start_times=self._anomaly_start_times,
            )
            self._attr_native_value = len(self._insights)
            self._attr_available = True
        except Exception as e:
            _LOGGER.debug("Failed to update zone insights for %s: %s", self._zone_name, e)
            self._attr_available = False
