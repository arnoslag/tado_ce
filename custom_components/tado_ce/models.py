"""Unified data models for Tado CE.

Consolidates the three separate TemperatureReading dataclasses that
existed across heating_models.py, insights.py, and
smart_comfort.py into distinctly-named classes.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass
class HeatingCycleReading:
    """Single temperature measurement during a heating cycle.

    Migrated from heating_models.py TemperatureReading.
    """

    time: datetime  # UTC
    temp: float

    def to_dict(self) -> dict:
        """Serialize to dictionary for JSON storage."""
        return {
            "time": self.time.isoformat(),
            "temp": self.temp,
        }

    @classmethod
    def from_dict(cls, data: dict) -> HeatingCycleReading:
        """Deserialize from dictionary."""
        return cls(
            time=datetime.fromisoformat(data["time"]),
            temp=data["temp"],
        )


@dataclass
class InsightTemperatureReading:
    """A temperature reading with timestamp for insights.

    Migrated from insights.py TemperatureReading.
    """

    temperature: float
    humidity: Optional[float]
    timestamp: datetime


@dataclass
class SmartComfortReading:
    """A single temperature reading with heating context.

    Migrated from smart_comfort.py TemperatureReading.
    """

    timestamp: datetime
    temperature: float
    is_heating: bool  # True if HVAC is actively heating/cooling
    target_temperature: Optional[float] = None

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "timestamp": self.timestamp.isoformat(),
            "temperature": self.temperature,
            "is_heating": self.is_heating,
            "target_temperature": self.target_temperature,
        }

    @classmethod
    def from_dict(cls, data: dict) -> SmartComfortReading:
        """Create from dictionary."""
        return cls(
            timestamp=datetime.fromisoformat(data["timestamp"]),
            temperature=data["temperature"],
            is_heating=data["is_heating"],
            target_temperature=data.get("target_temperature"),
        )
