"""Data models for heating cycle analysis."""
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from .models import HeatingCycleReading

# Backward compat alias — existing code may import TemperatureReading from here
TemperatureReading = HeatingCycleReading


@dataclass
class HeatingCycle:
    """Represents a complete heating cycle."""

    zone_id: str
    start_time: datetime  # UTC
    end_time: Optional[datetime]  # UTC, None if active
    start_temp: Optional[float]  # Set on first temperature update
    target_temp: float
    first_rise_time: Optional[datetime]  # UTC, when temp first increased by threshold
    first_rise_temp: Optional[float]
    temperature_readings: list[TemperatureReading]  # Limited to 100 readings max
    completed: bool
    interrupted: bool
    interrupt_reason: Optional[str]


    def to_dict(self) -> dict:
        """Serialize to dictionary for JSON storage."""
        return {
            "zone_id": self.zone_id,
            "start_time": self.start_time.isoformat(),
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "start_temp": self.start_temp,
            "target_temp": self.target_temp,
            "first_rise_time": self.first_rise_time.isoformat() if self.first_rise_time else None,
            "first_rise_temp": self.first_rise_temp,
            "temperature_readings": [r.to_dict() for r in self.temperature_readings],
            "completed": self.completed,
            "interrupted": self.interrupted,
            "interrupt_reason": self.interrupt_reason,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "HeatingCycle":
        """Deserialize from dictionary."""
        return cls(
            zone_id=data["zone_id"],
            start_time=datetime.fromisoformat(data["start_time"]),
            end_time=datetime.fromisoformat(data["end_time"]) if data["end_time"] else None,
            start_temp=data["start_temp"],
            target_temp=data["target_temp"],
            first_rise_time=datetime.fromisoformat(data["first_rise_time"]) if data["first_rise_time"] else None,
            first_rise_temp=data["first_rise_temp"],
            temperature_readings=[TemperatureReading.from_dict(r) for r in data["temperature_readings"]],
            completed=data["completed"],
            interrupted=data["interrupted"],
            interrupt_reason=data["interrupt_reason"],
        )


@dataclass
class HeatingCycleConfig:
    """Configuration for heating cycle analysis."""

    enabled: bool = True
    rolling_window_days: int = 7
    inertia_threshold_celsius: float = 0.1
    min_cycles: int = 3

    def validate(self) -> None:
        """Validate configuration values."""
        if not 1 <= self.rolling_window_days <= 30:
            raise ValueError("rolling_window_days must be between 1 and 30")
        if not 0.05 <= self.inertia_threshold_celsius <= 0.5:
            raise ValueError("inertia_threshold_celsius must be between 0.05 and 0.5")
        if not 1 <= self.min_cycles <= 10:
            raise ValueError("min_cycles must be between 1 and 10")
