"""Bridge API health tracking for monitoring connectivity and response times."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime


@dataclass
class BridgeHealthState:
    """Track Bridge API health metrics."""

    consecutive_failures: int = 0
    last_successful_poll: datetime | None = None
    last_error: str | None = None
    last_response_time_ms: float | None = None
    is_connected: bool = False


class BridgeHealthTracker:
    """Track Bridge API health across coordinator polls."""

    def __init__(self, failure_threshold: int = 3) -> None:
        """Initialize the BridgeHealthTracker."""
        self._state = BridgeHealthState()
        self._failure_threshold = failure_threshold

    def record_success(self, response_time_ms: float) -> None:
        """Record a successful Bridge API poll."""
        self._state.consecutive_failures = 0
        self._state.last_successful_poll = datetime.now(UTC)
        self._state.last_error = None
        self._state.last_response_time_ms = response_time_ms
        self._state.is_connected = True

    def record_failure(self, error: str) -> None:
        """Record a failed Bridge API poll."""
        self._state.consecutive_failures += 1
        self._state.last_error = error
        if self._state.consecutive_failures >= self._failure_threshold:
            self._state.is_connected = False

    @property
    def state(self) -> BridgeHealthState:
        """Return current health state."""
        return self._state

    @property
    def failure_threshold(self) -> int:
        """Return the configured failure threshold."""
        return self._failure_threshold
