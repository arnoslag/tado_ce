"""Optimistic state management helpers.

3-Layer Optimistic Defense Strategy:
  Layer 1: Coordinator-level freshness tracking (mark_entity_fresh)
  Layer 2: Sequence numbers (get_next_sequence) for ordering
  Layer 3: Expected state confirmation (compare API vs expected)

Functions:
  clear_optimistic_state(entity) — clears all optimistic tracking fields
  set_optimistic_state(entity, ...) — sets optimistic state for climate entities
  resolve_optimistic_vs_api(entity, ...) — Layer 2/3 comparison logic
"""
from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from homeassistant.components.climate import HVACAction, HVACMode

_LOGGER = logging.getLogger(__name__)

# All optimistic tracking fields across entity types.
# clear_optimistic_state() resets every field present on the entity to None.
_OPTIMISTIC_FIELDS = (
    # Climate entities (heating.py, ac.py)
    "_optimistic_state",
    "_optimistic_sequence",
    "_expected_hvac_mode",
    "_expected_hvac_action",
    # Water heater, select, switch entities
    "_optimistic_set_at",
    "_expected_operation",
    "_expected_temperature",
    "_expected_mode",
)


def clear_optimistic_state(entity: Any) -> None:
    """Clear all optimistic state tracking fields on an entity.

    Works for any entity type — only clears fields that exist on the entity.
    Replaces inline _clear_optimistic_state() in:
      - heating.py (clears _optimistic_state, _optimistic_sequence,
        _expected_hvac_mode, _expected_hvac_action)
      - ac.py (same as heating)
      - water_heater.py (clears _optimistic_set_at, _optimistic_sequence,
        _expected_operation, _expected_temperature)
      - select.py (clears _optimistic_set_at, _optimistic_sequence,
        _expected_mode)
    """
    for field in _OPTIMISTIC_FIELDS:
        if hasattr(entity, field):
            setattr(entity, field, None)


async def set_optimistic_state(
    entity: Any,
    hvac_mode: HVACMode,
    hvac_action: HVACAction,
    target_temp: float | None = None,
    extra_attrs: dict[str, Any] | None = None,
) -> None:
    """Set optimistic state with sequence number tracking (climate entities only).

    Replaces inline _set_optimistic_state() in heating.py and ac.py.
    AC passes extra_attrs={"fan_mode": ..., "swing_mode": ...} to preserve
    fan/swing during the optimistic window.

    Args:
        entity: Climate entity (must have .coordinator, .entity_id, ._zone_name)
        hvac_mode: The HVAC mode we expect API to confirm
        hvac_action: The HVAC action we expect API to confirm
        target_temp: Optional target temperature for optimistic state
        extra_attrs: Optional extra attributes to store (AC fan_mode/swing_mode)

    """
    # Layer 2: Get sequence number from coordinator
    entity._optimistic_sequence = entity.coordinator.get_next_sequence()

    # Build optimistic state dict
    state_dict: dict[str, Any] = {
        "target_temperature": target_temp,
        "hvac_mode": hvac_mode,
        "hvac_action": hvac_action,
        "timestamp": time.time(),
    }
    if extra_attrs:
        state_dict.update(extra_attrs)

    entity._optimistic_state = state_dict

    # Layer 3: Set expected state for confirmation checking
    entity._expected_hvac_mode = hvac_mode
    entity._expected_hvac_action = hvac_action

    # Layer 1: Mark entity as fresh in coordinator
    # MUST await to ensure freshness is set before async_write_ha_state()
    await entity.coordinator.mark_entity_fresh(entity.entity_id)

    _LOGGER.debug(
        "%s: Set optimistic state: mode=%s, action=%s, seq=%s",
        entity._zone_name, hvac_mode, hvac_action, entity._optimistic_sequence,
    )


def resolve_optimistic_vs_api(
    entity: Any,
    api_hvac_mode: HVACMode,
    api_hvac_action: HVACAction,
) -> bool:
    """Resolve whether to preserve optimistic state or accept API state.

    Implements Layer 2/3 of the 3-layer optimistic defense.
    Replaces the inline sequence-based comparison block in update() of
    heating.py and ac.py.

    Returns True if optimistic state should be preserved (API hasn't confirmed).
    Returns False if API confirmed or no optimistic state active.
    Side effect: calls clear_optimistic_state() when API confirms.

    Args:
        entity: Climate entity with _optimistic_sequence, _expected_hvac_mode,
                _expected_hvac_action fields
        api_hvac_mode: HVAC mode reported by API
        api_hvac_action: HVAC action reported by API

    Returns:
        True if optimistic state should be preserved, False otherwise

    """
    if entity._optimistic_sequence is None:
        return False

    # Check if API has confirmed our expected state
    if (
        api_hvac_mode == entity._expected_hvac_mode
        and api_hvac_action == entity._expected_hvac_action
    ):
        # API confirmed — clear optimistic state
        _LOGGER.debug(
            "%s: API confirmed optimistic state (mode=%s, action=%s), clearing",
            entity._zone_name, api_hvac_mode, api_hvac_action,
        )
        clear_optimistic_state(entity)
        return False

    # API hasn't caught up yet — preserve optimistic state
    _LOGGER.debug(
        "%s: Preserving optimistic state "
        "(expected mode=%s, action=%s; API shows mode=%s, action=%s)",
        entity._zone_name, entity._expected_hvac_mode,
        entity._expected_hvac_action, api_hvac_mode, api_hvac_action,
    )
    return True
