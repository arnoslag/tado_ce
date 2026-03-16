"""Tado CE second-order thermal dynamics analyzer — heating acceleration and approach behavior.

Heating acceleration and approach behavior analysis for improved preheat estimation.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .heating_models import HeatingCycle, TemperatureReading

_LOGGER = logging.getLogger(__name__)

# Thermal analysis thresholds
_MIN_READINGS_PER_HALF = 3
_MIN_RATE_THRESHOLD = 0.001


class ThermalAnalyzer:
    """Analyze second-order thermal dynamics from heating cycles.

    Second-order analysis provides:
    - Heating acceleration: How quickly the heating rate increases after heating starts
    - Approach factor: How much the heating rate decreases near the setpoint

    These metrics improve preheat estimation by accounting for:
    - System response time (acceleration)
    - Overshoot prediction (approach factor)
    """

    def __init__(self, min_cycles: int = 3) -> None:
        """Initialize analyzer.

        Args:
            min_cycles: Minimum completed cycles required for analysis
        """
        self._min_cycles = min_cycles

    def calculate_acceleration(
        self,
        cycles: list[HeatingCycle],
    ) -> float | None:
        """Calculate average heating acceleration.

        Acceleration = d(rate)/dt = (rate_end - rate_start) / duration

        Measures how quickly the heating rate increases after heating starts.
        Higher acceleration = faster response system.

        Args:
            cycles: List of completed heating cycles

        Returns:
            Average acceleration in °C/h², or None if insufficient data
        """
        # Filter to only valid heating cycles
        valid_cycles = [
            c
            for c in cycles
            if c.completed
            and c.start_temp is not None
            and c.start_temp < c.target_temp - 0.1  # At least 0.1°C heating needed
        ]

        if len(valid_cycles) < self._min_cycles:
            return None

        accelerations = []

        for cycle in valid_cycles:
            accel = self._calculate_cycle_acceleration(cycle)
            if accel is not None:
                accelerations.append(accel)

        if not accelerations:
            return None

        avg_acceleration = sum(accelerations) / len(accelerations)

        _LOGGER.debug(
            "Calculated acceleration from %d cycles: %.2f °C/h²",
            len(accelerations),
            avg_acceleration,
        )

        return round(avg_acceleration, 2)

    def _calculate_cycle_acceleration(
        self,
        cycle: HeatingCycle,
    ) -> float | None:
        """Calculate acceleration for a single cycle.

        We measure acceleration by comparing:
        - Initial heating rate (first 1/3 of cycle)
        - Final heating rate (last 1/3 of cycle, before reaching setpoint)

        Returns:
            Acceleration in °C/h², or None if cannot calculate
        """
        readings = cycle.temperature_readings

        if len(readings) < 6:
            return None

        # Split readings into thirds
        third = len(readings) // 3

        # Calculate initial rate (first third)
        initial_readings = readings[:third]
        initial_rate = self._calculate_rate_from_readings(initial_readings)

        # Calculate final rate (last third, but before setpoint)
        # Filter out readings that are at or above target
        final_readings = [r for r in readings[2 * third :] if r.temp < cycle.target_temp - 0.1]

        if len(final_readings) < 2:
            # Use all readings from last third if filtering removed too many
            final_readings = readings[2 * third :]

        final_rate = self._calculate_rate_from_readings(final_readings)

        if initial_rate is None or final_rate is None:
            return None

        # Calculate time span
        if not readings:
            return None

        duration_hours = (readings[-1].time - readings[0].time).total_seconds() / 3600

        if duration_hours < 0.1:  # Less than 6 minutes
            return None

        # Acceleration = (final_rate - initial_rate) / duration
        # Convert rates from °C/min to °C/h for consistency
        initial_rate_h = initial_rate * 60
        final_rate_h = final_rate * 60

        acceleration = (final_rate_h - initial_rate_h) / duration_hours

        return acceleration  # noqa: RET504 — readability: named result

    def _calculate_rate_from_readings(
        self,
        readings: list[TemperatureReading],
    ) -> float | None:
        """Calculate heating rate from a list of readings.

        Returns:
            Rate in °C/min, or None if cannot calculate
        """
        if len(readings) < 2:
            return None

        # Use linear regression for more stable rate calculation
        times = [(r.time - readings[0].time).total_seconds() / 60 for r in readings]
        temps = [r.temp for r in readings]

        n = len(readings)
        sum_t = sum(times)
        sum_temp = sum(temps)
        sum_t_temp = sum(t * temp for t, temp in zip(times, temps, strict=True))
        sum_t2 = sum(t * t for t in times)

        denominator = n * sum_t2 - sum_t * sum_t

        if abs(denominator) < 0.001:
            return None

        # Slope = rate in °C/min
        rate = (n * sum_t_temp - sum_t * sum_temp) / denominator

        return rate  # noqa: RET504 — readability: named result

    def calculate_approach_factor(
        self,
        cycles: list[HeatingCycle],
    ) -> float | None:
        """Calculate approach deceleration factor.

        Measures how much the heating rate decreases as temperature
        approaches the setpoint. Used to predict overshoot.

        Factor interpretation:
        - 1.0 (100%): No deceleration, will likely overshoot
        - 0.5 (50%): 50% deceleration, controlled approach
        - 0.0 (0%): Complete stop before setpoint (rare)

        Args:
            cycles: List of completed heating cycles

        Returns:
            Approach factor as percentage (0-100), or None if insufficient data
        """
        # Filter to only valid heating cycles
        valid_cycles = [
            c
            for c in cycles
            if c.completed
            and c.start_temp is not None
            and c.start_temp < c.target_temp - 0.1  # At least 0.1°C heating needed
        ]

        if len(valid_cycles) < self._min_cycles:
            return None

        factors = []

        for cycle in valid_cycles:
            factor = self._calculate_cycle_approach_factor(cycle)
            if factor is not None:
                factors.append(factor)

        if not factors:
            return None

        avg_factor = sum(factors) / len(factors)

        _LOGGER.debug(
            "Calculated approach factor from %d cycles: %.1f%%",
            len(factors),
            avg_factor * 100,
        )

        return round(avg_factor * 100, 1)

    def _calculate_cycle_approach_factor(
        self,
        cycle: HeatingCycle,
    ) -> float | None:
        """Calculate approach factor using hybrid industrial standard method.

        Primary method: Normalized Rate Ratio (first-half vs second-half average rate)
        - Robust to sensor noise and quantization effects
        - Uses temperature-based splitting, not time-based

        Validation: Exponential curve fitting (when data quality is high)
        - Validates primary result against thermal physics model

        Fallback: Point-based sampling (legacy method)
        - Used when primary method fails

        Returns:
            Factor between 0.0 and 2.0, or None if cannot calculate
            - < 1.0: Deceleration (normal, controlled approach)
            - = 1.0: Constant rate (no deceleration)
            - > 1.0: Acceleration (unusual, may overshoot)
        """
        readings = cycle.temperature_readings

        if len(readings) < 6 or cycle.start_temp is None:
            _LOGGER.debug(
                "Approach factor skip: insufficient readings (%d) or no start_temp",
                len(readings),
            )
            return None

        temp_delta = cycle.target_temp - cycle.start_temp

        if temp_delta < 0.5:  # Less than 0.5°C change
            _LOGGER.debug(
                "Approach factor skip: temp_delta %.2f°C < 0.5°C threshold",
                temp_delta,
            )
            return None

        # Primary method: Normalized Rate Ratio
        factor = self._calculate_approach_factor_rate_ratio(cycle, readings, temp_delta)

        if factor is not None:
            # Validation: If we have high quality data, validate with exponential fit
            if len(readings) >= 20:
                exp_factor = self._calculate_approach_factor_exponential(
                    cycle,
                    readings,
                    temp_delta,
                )
                if exp_factor is not None:
                    # If exponential validation differs significantly, log warning
                    diff = abs(factor - exp_factor)
                    if diff > 0.3:
                        _LOGGER.debug(
                            "Approach factor validation: rate_ratio=%.2f, exponential=%.2f, diff=%.2f",
                            factor,
                            exp_factor,
                            diff,
                        )
                        # Use weighted average when both methods work but differ
                        # Weight primary method more (70/30)
                        factor = factor * 0.7 + exp_factor * 0.3

            return factor

        # Fallback: Point-based sampling (legacy method)
        return self._calculate_approach_factor_point_based(cycle, readings, temp_delta)

    def _calculate_approach_factor_rate_ratio(
        self,
        cycle: HeatingCycle,
        readings: list[TemperatureReading],
        temp_delta: float,
    ) -> float | None:
        """Calculate approach factor using first-half vs second-half rate ratio.

        Industrial standard method: Compare average heating rate in first half
        of temperature rise vs second half. This is robust to sensor noise
        and quantization effects.

        Args:
            cycle: The heating cycle
            readings: Temperature readings
            temp_delta: Temperature difference (target - start)

        Returns:
            Factor between 0.0 and 2.0, or None if cannot calculate
        """
        # Find midpoint by temperature, not time
        mid_temp = cycle.start_temp + temp_delta * 0.5  # type: ignore[operator]

        # Split readings into first half and second half by temperature
        first_half = [r for r in readings if r.temp < mid_temp]
        second_half = [r for r in readings if r.temp >= mid_temp]

        if len(first_half) < _MIN_READINGS_PER_HALF or len(second_half) < _MIN_READINGS_PER_HALF:
            _LOGGER.debug(
                "Rate ratio skip: insufficient readings in halves (first=%d, second=%d)",
                len(first_half),
                len(second_half),
            )
            return None

        # Sort by time for rate calculation
        first_half = sorted(first_half, key=lambda r: r.time)
        second_half = sorted(second_half, key=lambda r: r.time)

        # Calculate average rate for each half
        rate_first = self._calculate_average_rate(first_half)
        rate_second = self._calculate_average_rate(second_half)

        if rate_first is None:
            _LOGGER.debug("Rate ratio skip: could not calculate first half rate")
            return None

        if rate_first <= _MIN_RATE_THRESHOLD:
            _LOGGER.debug(
                "Rate ratio skip: first half rate (%.6f) below threshold",
                rate_first,
            )
            return None

        if rate_second is None:
            rate_second = 0.0

        # Factor = rate_second / rate_first
        factor = rate_second / rate_first

        # Clamp to reasonable range
        factor = max(0.0, min(2.0, factor))

        _LOGGER.debug(
            "Rate ratio method: first_rate=%.4f, second_rate=%.4f, factor=%.2f",
            rate_first,
            rate_second,
            factor,
        )

        return factor

    def _calculate_average_rate(
        self,
        readings: list[TemperatureReading],
    ) -> float | None:
        """Calculate average heating rate over a set of readings.

        Uses total temperature change / total time for robustness.

        Args:
            readings: List of temperature readings (must be sorted by time)

        Returns:
            Rate in °C/min, or None if cannot calculate
        """
        if len(readings) < 2:
            return None

        # Total temperature change / total time
        temp_change = readings[-1].temp - readings[0].temp
        time_change = (readings[-1].time - readings[0].time).total_seconds() / 60

        if time_change <= 0:
            return None

        return temp_change / time_change

    def _calculate_approach_factor_exponential(
        self,
        cycle: HeatingCycle,
        readings: list[TemperatureReading],
        temp_delta: float,
    ) -> float | None:
        """Calculate approach factor using exponential curve fitting.

        Fits data to Newton's Law of Cooling: T(t) = T_target - (T_target - T_start) * exp(-t/τ)

        The approach factor is derived from the time constant τ:
        - Smaller τ = faster approach = higher factor
        - Larger τ = slower approach = lower factor

        Args:
            cycle: The heating cycle
            readings: Temperature readings (should have >= 20 readings)
            temp_delta: Temperature difference (target - start)

        Returns:
            Factor between 0.0 and 2.0, or None if cannot calculate
        """
        # Need sufficient data for curve fitting
        if len(readings) < 20:
            return None

        # Sort readings by time
        sorted_readings = sorted(readings, key=lambda r: r.time)

        # Prepare data for fitting
        base_time = sorted_readings[0].time
        times = [(r.time - base_time).total_seconds() / 60 for r in sorted_readings]  # minutes
        temps = [r.temp for r in sorted_readings]

        # Check for sufficient temperature variation
        temp_range = max(temps) - min(temps)
        if temp_range < 0.5:
            return None

        # Estimate time constant using linearization
        # For T(t) = T_target - A * exp(-t/τ), we can linearize:
        # ln(T_target - T) = ln(A) - t/τ
        # Slope = -1/τ

        target = cycle.target_temp

        # Filter readings that are below target (for valid log)
        valid_data = [
            (t, temp)
            for t, temp in zip(times, temps, strict=True)
            if temp < target - 0.1  # Need some margin
        ]

        if len(valid_data) < 10:
            return None

        # Calculate ln(target - temp) for linearization
        import math

        try:
            log_diffs = []
            log_times = []
            for t, temp in valid_data:
                diff = target - temp
                if diff > 0.05:  # Avoid log of very small numbers
                    log_diffs.append(math.log(diff))
                    log_times.append(t)

            if len(log_diffs) < 10:
                return None

            # Linear regression on log data
            n = len(log_diffs)
            sum_t = sum(log_times)
            sum_log = sum(log_diffs)
            sum_t_log = sum(t * log for t, log in zip(log_times, log_diffs, strict=True))
            sum_t2 = sum(t * t for t in log_times)

            denominator = n * sum_t2 - sum_t * sum_t
            if abs(denominator) < 0.001:
                return None

            slope = (n * sum_t_log - sum_t * sum_log) / denominator

            # slope = -1/τ, so τ = -1/slope
            if slope >= -0.001:  # slope should be negative for heating
                return None

            tau = -1.0 / slope  # time constant in minutes

            # Convert tau to approach factor
            # Expected tau for "normal" heating is roughly cycle_duration / 3
            cycle_duration = times[-1] - times[0]
            if cycle_duration <= 0:
                return None

            expected_tau = cycle_duration / 3

            # Factor = expected_tau / actual_tau
            # If actual tau < expected, heating is faster = higher factor
            # If actual tau > expected, heating is slower = lower factor
            if tau <= 0:
                return None

            factor = expected_tau / tau

            # Clamp to reasonable range
            factor = max(0.0, min(2.0, factor))

            _LOGGER.debug(
                "Exponential method: tau=%.1f min, expected_tau=%.1f min, factor=%.2f",
                tau,
                expected_tau,
                factor,
            )

            return factor

        except (ValueError, ZeroDivisionError) as e:
            _LOGGER.debug("Exponential method failed: %s", e)
            return None

    def _calculate_approach_factor_point_based(
        self,
        cycle: HeatingCycle,
        readings: list[TemperatureReading],
        temp_delta: float,
    ) -> float | None:
        """Calculate approach factor using point-based sampling (legacy fallback).

        Compare heating rate at 50% of temperature delta vs 90% of delta.

        Args:
            cycle: The heating cycle
            readings: Temperature readings
            temp_delta: Temperature difference (target - start)

        Returns:
            Factor between 0.0 and 2.0, or None if cannot calculate
        """
        # Find readings at ~50% and ~90% of temperature delta
        temp_50 = cycle.start_temp + temp_delta * 0.5  # type: ignore[operator]
        temp_90 = cycle.start_temp + temp_delta * 0.9  # type: ignore[operator]

        # Get readings around these temperatures
        readings_50 = self._get_readings_near_temp(readings, temp_50, tolerance=0.3)
        readings_90 = self._get_readings_near_temp(readings, temp_90, tolerance=0.3)

        if len(readings_50) < 2 or len(readings_90) < 2:
            _LOGGER.debug(
                "Point-based skip: insufficient readings at 50%% (%d) or 90%% (%d)",
                len(readings_50),
                len(readings_90),
            )
            return None

        rate_50 = self._calculate_rate_from_readings(readings_50)
        rate_90 = self._calculate_rate_from_readings(readings_90)

        if rate_50 is None or rate_90 is None:
            _LOGGER.debug(
                "Point-based skip: could not calculate rates (rate_50=%s, rate_90=%s)",
                rate_50,
                rate_90,
            )
            return None

        if abs(rate_50) < _MIN_RATE_THRESHOLD:
            _LOGGER.debug(
                "Point-based skip: rate_50 (%.6f) below threshold",
                rate_50,
            )
            return None

        if rate_50 <= 0:
            _LOGGER.debug(
                "Point-based skip: rate_50 (%.4f) is not positive",
                rate_50,
            )
            return None

        # Factor = rate_90 / rate_50
        factor = rate_90 / rate_50

        # Clamp to reasonable range
        factor = max(0.0, min(2.0, factor))

        _LOGGER.debug(
            "Point-based method: rate_50=%.4f, rate_90=%.4f, factor=%.2f",
            rate_50,
            rate_90,
            factor,
        )

        return factor

    def _get_readings_near_temp(
        self,
        readings: list[TemperatureReading],
        target_temp: float,
        tolerance: float = 0.3,
    ) -> list[TemperatureReading]:
        """Get readings near a target temperature."""
        return [r for r in readings if abs(r.temp - target_temp) <= tolerance]

    def estimate_overshoot(
        self,
        current_temp: float,
        target_temp: float,
        heating_rate: float,
        approach_factor: float,
    ) -> float:
        """Estimate temperature overshoot based on approach dynamics.

        Args:
            current_temp: Current temperature
            target_temp: Target temperature
            heating_rate: Current heating rate in °C/h
            approach_factor: Approach factor (0-100%)

        Returns:
            Estimated overshoot in °C
        """
        if heating_rate <= 0 or current_temp >= target_temp:
            return 0.0

        # Convert approach factor from percentage
        factor = approach_factor / 100.0

        # Higher factor = more overshoot
        # Base overshoot estimate: rate * thermal_lag_time
        # Thermal lag is typically 5-15 minutes for residential heating
        thermal_lag_hours = 0.15  # ~9 minutes

        base_overshoot = heating_rate * thermal_lag_hours

        # Adjust by approach factor
        # Factor 1.0 = full overshoot
        # Factor 0.5 = half overshoot
        adjusted_overshoot = base_overshoot * factor

        # Clamp to reasonable range
        return round(max(0.0, min(2.0, adjusted_overshoot)), 1)

    def get_improved_preheat_estimate(
        self,
        current_temp: float,
        target_temp: float,
        avg_heating_rate: float,
        inertia_time: float,
        acceleration: float | None = None,
        approach_factor: float | None = None,
    ) -> float | None:
        """Get improved preheat time estimate using second-order analysis.

        Args:
            current_temp: Current temperature
            target_temp: Target temperature
            avg_heating_rate: Average heating rate in °C/h
            inertia_time: Thermal inertia time in minutes
            acceleration: Heating acceleration in °C/h² (optional)
            approach_factor: Approach factor in % (optional)

        Returns:
            Estimated preheat time in minutes, or None if cannot calculate
        """
        if avg_heating_rate <= 0 or target_temp <= current_temp:
            return 0.0

        temp_delta = target_temp - current_temp

        # Base estimate: inertia + (delta / rate)
        # Convert rate from °C/h to °C/min
        rate_per_min = avg_heating_rate / 60
        heating_time = temp_delta / rate_per_min
        base_estimate = inertia_time + heating_time

        # Adjust for acceleration (if available)
        # Higher acceleration = faster warmup = less time needed
        if acceleration is not None and acceleration != 0:
            # Acceleration adjustment factor
            # Positive acceleration reduces time, negative increases it
            accel_adjustment = 1.0 - (acceleration / 100)  # Normalize
            accel_adjustment = max(0.8, min(1.2, accel_adjustment))
            base_estimate *= accel_adjustment

        # Adjust for approach factor (if available)
        # Lower approach factor = more deceleration = need to start earlier
        if approach_factor is not None:
            # Factor 100% = no adjustment
            # Factor 50% = add 10% more time
            factor_adjustment = 1.0 + (100 - approach_factor) / 500
            factor_adjustment = max(1.0, min(1.2, factor_adjustment))
            base_estimate *= factor_adjustment

        return round(base_estimate, 1)
