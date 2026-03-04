"""Climate platform helpers — HVAC mode maps, fan maps, zone capabilities."""
import logging

from homeassistant.components.climate.const import (
    FAN_AUTO,
    FAN_HIGH,
    FAN_LOW,
    FAN_MEDIUM,
    HVACMode,
)

_LOGGER = logging.getLogger(__name__)

# Tado AC modes mapping
TADO_TO_HA_HVAC_MODE = {
    "COOL": HVACMode.COOL,
    "HEAT": HVACMode.HEAT,
    "DRY": HVACMode.DRY,
    "FAN": HVACMode.FAN_ONLY,
    "AUTO": HVACMode.HEAT_COOL,
}

HA_TO_TADO_HVAC_MODE = {v: k for k, v in TADO_TO_HA_HVAC_MODE.items()}

# Fan level mapping - Tado uses SILENT, LEVEL1-5, AUTO
# Map to HA's limited fan modes (auto, low, medium, high)
TADO_TO_HA_FAN = {
    "AUTO": FAN_AUTO,
    "SILENT": FAN_LOW,
    "LEVEL1": FAN_LOW,
    "LEVEL2": FAN_LOW,
    "LEVEL3": FAN_MEDIUM,
    "LEVEL4": FAN_HIGH,
    "LEVEL5": FAN_HIGH,
    # Legacy mappings
    "HIGH": FAN_HIGH,
    "MIDDLE": FAN_MEDIUM,
    "LOW": FAN_LOW,
}

HA_TO_TADO_FAN = {
    FAN_AUTO: "AUTO",
    FAN_LOW: "LEVEL1",
    FAN_MEDIUM: "LEVEL3",
    FAN_HIGH: "LEVEL5",
}


def get_zone_capabilities(data_loader):
    """Load zone capabilities (for AC zones).

    First tries to load from ac_capabilities.json (fetched from dedicated API endpoint).
    Falls back to zones_info.json for basic capabilities.
    """
    ac_caps = data_loader.load_ac_capabilities_file() or {}
    zones_info = data_loader.load_zones_info_file()

    if not zones_info:
        return {}

    caps = {}
    for z in zones_info:
        zone_id = str(z.get('id'))
        zone_type = z.get('type')

        if zone_type == 'AIR_CONDITIONING' and zone_id in ac_caps:
            # Use detailed AC capabilities from dedicated API
            caps[zone_id] = {
                'type': zone_type,
                'ac_capabilities': ac_caps[zone_id],
            }
        else:
            # Fallback to basic capabilities from zones_info
            # Use 'or {}' pattern for null safety
            caps[zone_id] = {
                'type': zone_type,
                'capabilities': z.get('capabilities') or {},
            }
    return caps


def build_fan_mapping(fan_levels: set) -> tuple[dict, dict]:
    """Build bidirectional fan level mapping from actual AC capabilities.

    Dynamic mapping to fix #142 (Mitsubishi/Fujitsu HIGH fan speed).

    Different AC brands use different fan level names:
      - Mitsubishi/Fujitsu: ONE, TWO, THREE, FOUR, AUTO
      - Newer Tado:         LEVEL1, LEVEL2, LEVEL3, LEVEL4, LEVEL5, AUTO
      - Legacy:             LOW, MIDDLE, HIGH, AUTO
      - Silent variants:    SILENT, ONE, TWO, THREE, FOUR, AUTO

    Strategy:
      1. AUTO always maps to FAN_AUTO
      2. SILENT always maps to FAN_LOW (quietest)
      3. Remaining levels sorted and divided evenly into low/medium/high buckets
      4. ha→tado picks the HIGHEST tado level in each bucket (best match for user intent)

    Returns:
        (tado_to_ha, ha_to_tado) mapping dicts
    """
    TADO_FAN_ORDER = [
        "SILENT",
        "LOW", "LEVEL1", "ONE",
        "MIDDLE", "LEVEL2", "TWO",
        "LEVEL3", "THREE",
        "LEVEL4", "FOUR",
        "HIGH", "LEVEL5",
    ]

    tado_to_ha = {}
    ha_to_tado = {}

    # AUTO always maps to FAN_AUTO
    if "AUTO" in fan_levels:
        tado_to_ha["AUTO"] = FAN_AUTO
        ha_to_tado[FAN_AUTO] = "AUTO"

    # SILENT is always the quietest → FAN_LOW
    if "SILENT" in fan_levels:
        tado_to_ha["SILENT"] = FAN_LOW

    # Sort remaining non-AUTO, non-SILENT levels by known order
    other_levels = sorted(
        [f for f in fan_levels if f not in ("AUTO", "SILENT")],
        key=lambda x: TADO_FAN_ORDER.index(x) if x in TADO_FAN_ORDER else 99
    )

    n = len(other_levels)
    if n == 0:
        if "SILENT" in fan_levels:
            ha_to_tado[FAN_LOW] = "SILENT"
        return tado_to_ha, ha_to_tado

    # Divide into 3 buckets: low / medium / high
    # n=1 → [low]
    # n=2 → [low, high]
    # n=3 → [low, medium, high]
    # n=4 → [low, low, medium, high]
    # n=5 → [low, low, medium, high, high]
    low_end = max(1, n // 3)
    high_start = n - max(1, n // 3)

    for i, level in enumerate(other_levels):
        if i < low_end:
            ha_mode = FAN_LOW
        elif i >= high_start:
            ha_mode = FAN_HIGH
        else:
            ha_mode = FAN_MEDIUM
        tado_to_ha[level] = ha_mode

    # ha→tado: pick the HIGHEST tado level in each bucket
    for ha_mode in [FAN_LOW, FAN_MEDIUM, FAN_HIGH]:
        candidates = [lvl for lvl, ha in tado_to_ha.items() if ha == ha_mode and lvl not in ("AUTO", "SILENT")]
        if candidates:
            ha_to_tado[ha_mode] = candidates[-1]

    # Fallback: if FAN_LOW not mapped yet, use SILENT
    if FAN_LOW not in ha_to_tado and "SILENT" in fan_levels:
        ha_to_tado[FAN_LOW] = "SILENT"

    return tado_to_ha, ha_to_tado
