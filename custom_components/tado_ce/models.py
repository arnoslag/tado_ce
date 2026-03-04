"""Unified data models for Tado CE.

Consolidates the three separate TemperatureReading dataclasses that
existed across heating_models.py, insights.py, and
smart_comfort.py into distinctly-named classes.
"""
from __future__ import annotations

from dataclasses import dataclass, fields
from datetime import datetime
from typing import Optional, get_type_hints


class _SerializableMixin:
    """Mixin for dataclasses with datetime fields — provides to_dict/from_dict."""

    def to_dict(self) -> dict:
        """Serialize to dictionary for JSON storage."""
        d = {}
        for f in fields(self):
            v = getattr(self, f.name)
            d[f.name] = v.isoformat() if isinstance(v, datetime) else v
        return d

    @classmethod
    def from_dict(cls, data: dict):
        """Deserialize from dictionary."""
        hints = get_type_hints(cls)
        kwargs = {}
        for f in fields(cls):
            v = data.get(f.name)
            if v is not None and hints.get(f.name) is datetime:
                v = datetime.fromisoformat(v)
            if v is not None:
                kwargs[f.name] = v
        return cls(**kwargs)


@dataclass
class HeatingCycleReading(_SerializableMixin):
    """Single temperature measurement during a heating cycle.

    Migrated from heating_models.py TemperatureReading.
    """

    time: datetime  # UTC
    temp: float


@dataclass
class InsightTemperatureReading:
    """A temperature reading with timestamp for insights.

    Migrated from insights.py TemperatureReading.
    """

    temperature: float
    humidity: Optional[float]
    timestamp: datetime


@dataclass
class SmartComfortReading(_SerializableMixin):
    """A single temperature reading with heating context.

    Migrated from smart_comfort.py TemperatureReading.
    """

    timestamp: datetime
    temperature: float
    is_heating: bool  # True if HVAC is actively heating/cooling
    target_temperature: Optional[float] = None
