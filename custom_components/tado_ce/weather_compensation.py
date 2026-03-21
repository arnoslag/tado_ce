"""Weather compensation (heating curve) engine for Tado CE.

Pure calculation module with no Home Assistant dependencies.
Automatically adjusts boiler max output (flow) temperature based on
outdoor temperature using a linear heating curve, with optional
EMA / rolling-average smoothing and indoor temperature feedback.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# Presets: (slope, max_flow, min_flow)
# ---------------------------------------------------------------------------

HEATING_PRESETS: dict[str, tuple[float, float, float]] = {
    "radiators_standard": (1.5, 65.0, 25.0),
    "radiators_low_temp": (1.2, 55.0, 25.0),
    "underfloor": (0.8, 45.0, 25.0),
    "custom": (1.5, 65.0, 25.0),
}

# Bridge API hard limits
_API_MIN_FLOW: float = 25.0
_API_MAX_FLOW: float = 80.0

# Minimum seconds between Bridge API adjustments (10 min)
_MIN_HOLD_SECONDS: float = 600.0

# Stale reading threshold in seconds (60 min)
_STALE_READING_SECONDS: float = 3600.0


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class WeatherCompensationConfig:
    """Configuration parameters for weather compensation."""

    enabled: bool = False
    heating_system_preset: str = "radiators_standard"
    slope: float = 1.5
    design_outdoor_temp: float = -5.0
    max_flow_temp: float = 65.0
    min_flow_temp: float = 25.0
    shutoff_temp: float = 18.0
    smoothing_method: str = "ema"
    smoothing_window_minutes: int = 60
    room_compensation_enabled: bool = False
    room_compensation_factor: float = 3.0
    step_size: float = 1.0
    hysteresis: float = 1.0


@dataclass
class WeatherCompensationState:
    """Mutable runtime state for weather compensation engine."""

    ema_outdoor_temp: float | None = None
    last_raw_outdoor_temp: float | None = None
    last_adjustment_time: float = 0.0
    last_sent_flow_temp: float | None = None
    last_outdoor_reading_time: float = 0.0
    status: str = "disabled"
    rolling_buffer: list[float] = field(default_factory=list)
    rolling_buffer_max_size: int = 0


@dataclass
class WeatherCompensationResult:
    """Result of a single weather compensation evaluation cycle."""

    target_flow_temp: float | None
    should_send: bool
    status: str
    smoothed_outdoor_temp: float | None
    raw_outdoor_temp: float | None
    smoothing_method: str
    smoothing_window: int
    room_compensation_offset: float
    heating_system_preset: str


# ---------------------------------------------------------------------------
# Pure calculation functions
# ---------------------------------------------------------------------------


def calculate_base_flow_temp(
    outdoor_temp: float,
    config: WeatherCompensationConfig,
) -> float:
    """Calculate base flow temperature from the linear heating curve.

    Formula: max_flow - slope × (outdoor_temp - design_outdoor_temp)

    Satisfies CP-1 (monotonicity) and CP-5 (design point).
    """
    return config.max_flow_temp - config.slope * (
        outdoor_temp - config.design_outdoor_temp
    )


def calculate_room_offset(
    indoor_temp: float,
    target_temp: float,
    compensation_factor: float,
) -> float:
    """Calculate room compensation offset.

    Positive when rooms are cold (boost), negative when warm (reduce).
    Satisfies CP-10 (symmetry): factor × (target - indoor).
    """
    return compensation_factor * (target_temp - indoor_temp)


def snap_to_step(value: float, step: float = 0.5) -> float:
    """Snap a value to the nearest step increment.

    Satisfies CP-3 (step precision): result is always a multiple of *step*.
    """
    return round(value / step) * step


def clamp_flow_temp(
    value: float,
    min_flow: float,
    max_flow: float,
) -> float:
    """Clamp flow temperature to user range AND Bridge API hard limits.

    Satisfies CP-2 (bounds): result always in
    [max(min_flow, 25.0), min(max_flow, 80.0)].
    """
    effective_min = max(min_flow, _API_MIN_FLOW)
    effective_max = min(max_flow, _API_MAX_FLOW)
    return max(effective_min, min(value, effective_max))


def update_ema(
    current: float | None,
    new_value: float,
    window_minutes: int,
    poll_interval_minutes: float,
) -> float:
    """Update exponential moving average.

    Alpha = 2 / (N + 1) where N = window_minutes / poll_interval_minutes.
    First call (current is None) seeds with *new_value*.
    Satisfies CP-9 (stability): converges to constant input.
    """
    if current is None:
        return new_value
    n = max(window_minutes / poll_interval_minutes, 1.0)
    alpha = 2.0 / (n + 1.0)
    return alpha * new_value + (1.0 - alpha) * current


def update_rolling_avg(
    buffer: list[float],
    new_value: float,
    max_size: int,
) -> float:
    """Update rolling (simple moving) average.

    Appends *new_value*, trims oldest when buffer exceeds *max_size*.
    Returns the mean of the buffer.
    Satisfies CP-9 (stability): full buffer of identical values → exact match.
    """
    buffer.append(new_value)
    if max_size > 0 and len(buffer) > max_size:
        del buffer[: len(buffer) - max_size]
    return sum(buffer) / len(buffer)


def smooth_outdoor_temp(
    config: WeatherCompensationConfig,
    state: WeatherCompensationState,
    raw_temp: float,
    poll_interval_minutes: float,
) -> float:
    """Dispatch to the configured smoothing method.

    Updates *state* in-place and returns the smoothed temperature.
    """
    method = config.smoothing_method

    if method == "ema":
        smoothed = update_ema(
            state.ema_outdoor_temp,
            raw_temp,
            config.smoothing_window_minutes,
            poll_interval_minutes,
        )
        state.ema_outdoor_temp = smoothed
        return smoothed

    if method == "rolling_average":
        if state.rolling_buffer_max_size == 0 and poll_interval_minutes > 0:
            state.rolling_buffer_max_size = max(
                int(config.smoothing_window_minutes / poll_interval_minutes), 1,
            )
        return update_rolling_avg(
            state.rolling_buffer,
            raw_temp,
            state.rolling_buffer_max_size,
        )

    # "none" — passthrough
    return raw_temp


def evaluate(
    config: WeatherCompensationConfig,
    state: WeatherCompensationState,
    outdoor_temp_raw: float | None,
    indoor_temp: float | None,
    target_temp: float | None,
    _current_flow_temp: float | None,
    now_mono: float,
    poll_interval_minutes: float,
) -> WeatherCompensationResult:
    """Run one weather compensation evaluation cycle.

    Mutates *state* in-place. Returns a result indicating the target
    flow temperature and whether the Bridge API should be called.

    Satisfies CP-4 (shutoff), CP-6 (idempotency), CP-7 (independence
    is enforced by the caller wrapping this in try/except).
    """
    base = WeatherCompensationResult(
        target_flow_temp=None,
        should_send=False,
        status="disabled",
        smoothed_outdoor_temp=None,
        raw_outdoor_temp=outdoor_temp_raw,
        smoothing_method=config.smoothing_method,
        smoothing_window=config.smoothing_window_minutes,
        room_compensation_offset=0.0,
        heating_system_preset=config.heating_system_preset,
    )

    if not config.enabled:
        state.status = "disabled"
        return base

    # --- Step 1: outdoor temp availability ---
    if outdoor_temp_raw is None:
        state.status = "paused"
        base.status = "paused"
        return base

    # --- Step 2: stale reading check ---
    if (
        state.last_outdoor_reading_time > 0
        and (now_mono - state.last_outdoor_reading_time) > _STALE_READING_SECONDS
    ):
        state.status = "paused"
        base.status = "paused"
        base.raw_outdoor_temp = outdoor_temp_raw
        return base

    state.last_raw_outdoor_temp = outdoor_temp_raw
    state.last_outdoor_reading_time = now_mono

    # --- Step 3: smooth outdoor temp ---
    smoothed = smooth_outdoor_temp(config, state, outdoor_temp_raw, poll_interval_minutes)
    base.smoothed_outdoor_temp = smoothed

    # --- Step 4: shutoff check (CP-4) ---
    step = config.step_size
    if smoothed >= config.shutoff_temp:
        target = clamp_flow_temp(
            snap_to_step(config.min_flow_temp, step),
            config.min_flow_temp,
            config.max_flow_temp,
        )
    else:
        # --- Step 5: heating curve + room compensation ---
        flow = calculate_base_flow_temp(smoothed, config)

        room_offset = 0.0
        if (
            config.room_compensation_enabled
            and indoor_temp is not None
            and target_temp is not None
        ):
            room_offset = calculate_room_offset(
                indoor_temp, target_temp, config.room_compensation_factor,
            )
        base.room_compensation_offset = room_offset

        target = clamp_flow_temp(
            snap_to_step(flow + room_offset, step),
            config.min_flow_temp,
            config.max_flow_temp,
        )

    base.target_flow_temp = target
    base.status = "active"
    state.status = "active"

    # --- Step 6: hold time check ---
    if (
        state.last_adjustment_time > 0
        and (now_mono - state.last_adjustment_time) < _MIN_HOLD_SECONDS
    ):
        return base

    # --- Step 7: idempotency check with hysteresis (CP-6) ---
    # Use <= so that a difference exactly equal to hysteresis does NOT
    # trigger a send.  This prevents boundary oscillation when step_size
    # equals hysteresis (both default to 1.0 °C).
    if (
        state.last_sent_flow_temp is not None
        and abs(target - state.last_sent_flow_temp) <= config.hysteresis
    ):
        return base

    # --- Should send ---
    base.should_send = True
    state.last_sent_flow_temp = target
    state.last_adjustment_time = now_mono
    return base
