"""Tado CE Write Health Tracker — circuit breaker for HomeKit writes.

States:
- CLOSED: Normal operation, HomeKit writes attempted.
- OPEN: HomeKit writes skipped after consecutive failures.
- HALF_OPEN: One probe write attempted after cooldown period.
"""

from __future__ import annotations

import enum
import logging
import time

from .const import WRITE_CIRCUIT_OPEN_SECONDS, WRITE_FAILURE_THRESHOLD

_LOGGER = logging.getLogger(__name__)


class CircuitState(enum.Enum):
    """Circuit breaker states."""

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class WriteHealthTracker:
    """Track consecutive HomeKit write failures and implement circuit breaker."""

    def __init__(self) -> None:
        """Initialize the WriteHealthTracker."""
        self._consecutive_failures: int = 0
        self._circuit_opened_at: float | None = None  # time.monotonic() timestamp
        self._state: CircuitState = CircuitState.CLOSED

    @property
    def state(self) -> CircuitState:
        """Return current circuit breaker state, checking for OPEN → HALF_OPEN transition."""
        if self._state == CircuitState.OPEN and self._circuit_opened_at is not None:
            elapsed = time.monotonic() - self._circuit_opened_at
            if elapsed >= WRITE_CIRCUIT_OPEN_SECONDS:
                self._state = CircuitState.HALF_OPEN
        return self._state

    @property
    def consecutive_failures(self) -> int:
        """Return current consecutive failure count."""
        return self._consecutive_failures

    def should_try_homekit(self) -> bool:
        """Return True if HomeKit writes should be attempted."""
        return self.state in (CircuitState.CLOSED, CircuitState.HALF_OPEN)

    def record_success(self) -> None:
        """Record a successful HomeKit write."""
        self._consecutive_failures = 0
        self._circuit_opened_at = None
        self._state = CircuitState.CLOSED

    def record_failure(self) -> None:
        """Record a failed HomeKit write."""
        self._consecutive_failures += 1
        if self._state == CircuitState.HALF_OPEN:
            self._circuit_opened_at = time.monotonic()
            self._state = CircuitState.OPEN
            _LOGGER.debug(
                "WriteHealth: probe failed, re-opening circuit (failures=%d)",
                self._consecutive_failures,
            )
        elif self._consecutive_failures >= WRITE_FAILURE_THRESHOLD:
            self._circuit_opened_at = time.monotonic()
            self._state = CircuitState.OPEN
            _LOGGER.warning(
                "WriteHealth: circuit OPEN after %d consecutive failures",
                self._consecutive_failures,
            )

    def reset(self) -> None:
        """Reset tracker to initial state (e.g. on reconnect)."""
        self._consecutive_failures = 0
        self._circuit_opened_at = None
        self._state = CircuitState.CLOSED
