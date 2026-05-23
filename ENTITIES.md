# Tado CE — Entity Reference (v4.0.0)

This document lists the entity types in Tado CE — roughly 90 distinct types in total, organised by function. The exact count depends on which features you've enabled and what your hardware exposes (Bridge API entities are dynamically discovered, AC zones expose different entities than heating zones, etc.).

> **v3.1.0 change:** Per-zone configuration (overlay mode, timer, min/max temp, temp offset, heating type, window type, sensitivity, external sensors, etc.) moved from 11 HA entities per zone to a centralised Options Flow menu. Zero config entities are created — settings live in **Settings → Tado CE → Configure → Zone Configuration**.

## How to Read This Document

**Two tables per section:**

1. **Friendly Names** — what you see in the HA UI
2. **Entity IDs** — what you use in automations and YAML

**Column guide:**

| Column | Meaning |
|--------|---------|
| CE? | ✓ = CE Exclusive (not in official Tado integration) |
| v2.3.1 Name | Friendly name in v2.3.1 |
| v3.0 Name | Friendly name in v3.0.0 (all users, immediate) |
| v4.0 Name | Friendly name in v4.0.0 (new entities only) |
| v2.3.1 entity_id | Entity ID in v2.3.1 (preserved for migrated users) |
| v3.0 entity_id (fresh) | Entity ID for fresh v3.0.0 installs |
| v4.0 entity_id (fresh) | Entity ID for fresh v4.0.0 installs (new entities only) |

**Markers:**

| Marker | Meaning |
|--------|---------|
| ✓ | CE Exclusive — not available in HA official Tado integration |
| ⬆ | Enhanced — Tado app feature that HA official lacks or CE implements better |

**Migration notes:**
- Upgrading from v2.3.1 → v3.0.0 **preserves your entity_ids** — automations won't break
- Friendly names change immediately for all users (code-driven via `strings.json`)
- Fresh installs get HA auto-generated entity_ids from device name + friendly name
- Multi-home fresh installs: HA auto-suffixes `_2`, `_3` etc. to avoid collision

**Device name → entity_id prefix mapping (fresh installs):**

| Device | Device Name | entity_id prefix |
|--------|------------|-----------------|
| Hub | Tado CE Hub | `{platform}.tado_ce_hub_` |
| Zone | {zone_name} (e.g. Lounge) | `{platform}.lounge_` |
| Schedule | Heating Schedule | `{platform}.heating_schedule_` |

**Zone examples use:** zone name = "Lounge", zone_id = 4, home_id = {home_id}

---

## Hub Sensors (19 entities)

### Friendly Names

| Function | CE? | v2.3.1 Name | v3.0 Name | v4.0 Name |
|----------|-----|-------------|-----------|-----------|
| Outdoor temperature | | Outside Temperature | Outside Temp | — |
| Solar radiation | | Solar Intensity | Solar Intensity | — |
| Weather condition | | Weather | Weather | — |
| Boiler flow temp | ✓ | Boiler Flow Temperature | Boiler Flow Temp | — |
| Home identifier | ✓ | Home ID | Home ID | — |
| API calls used | ✓ | API Usage | API Usage | — |
| API reset countdown | ✓ | API Reset | API Reset | — |
| Daily API limit | ✓ | API Limit | API Limit | — |
| API health | ✓ | API Status | API Status | — |
| Auth token health | ✓ | Token Status | Token Status | — |
| Zone count | ✓ | Zone Count | Zone Count | — |
| Last sync time | ✓ | Last Sync | Last Sync | — |
| Next sync time | ✓ | Next Sync | Next Sync | — |
| Polling interval | ✓ | Polling Interval | Polling Interval | — |
| API call history | ✓ | Call History | Call History | — |
| API call breakdown | ✓ | API Call Breakdown | API Breakdown | — |
| Home-wide insights | ✓ | Home Insights | Home Insights | — |
| HomeKit reads saved | ✓ | — | — | HomeKit Reads Saved |
| HomeKit writes saved | ✓ | — | — | HomeKit Writes Saved |

### Entity IDs

| v2.3.1 entity_id | v3.0 entity_id (fresh) |
|-------------------|------------------------|
| `sensor.tado_ce_outside_temperature` | `sensor.tado_ce_hub_outside_temp` |
| `sensor.tado_ce_solar_intensity` | `sensor.tado_ce_hub_solar_intensity` |
| `sensor.tado_ce_weather_state` | `sensor.tado_ce_hub_weather` |
| `sensor.tado_ce_boiler_flow_temperature` | `sensor.tado_ce_hub_ce_boiler_flow_temp` |
| `sensor.tado_ce_home_id` | `sensor.tado_ce_hub_ce_home_id` |
| `sensor.tado_ce_api_usage` | `sensor.tado_ce_hub_ce_api_usage` |
| `sensor.tado_ce_api_reset` | `sensor.tado_ce_hub_ce_api_reset` |
| `sensor.tado_ce_api_limit` | `sensor.tado_ce_hub_ce_api_limit` |
| `sensor.tado_ce_api_status` | `sensor.tado_ce_hub_ce_api_status` |
| `sensor.tado_ce_token_status` | `sensor.tado_ce_hub_ce_token_status` |
| `sensor.tado_ce_zones_count` | `sensor.tado_ce_hub_ce_zone_count` |
| `sensor.tado_ce_last_sync` | `sensor.tado_ce_hub_ce_last_sync` |
| `sensor.tado_ce_next_sync` | `sensor.tado_ce_hub_ce_next_sync` |
| `sensor.tado_ce_polling_interval` | `sensor.tado_ce_hub_ce_polling_interval` |
| `sensor.tado_ce_call_history` | `sensor.tado_ce_hub_ce_call_history` |
| `sensor.tado_ce_api_call_breakdown` | `sensor.tado_ce_hub_ce_api_breakdown` |
| `sensor.tado_ce_home_insights` | `sensor.tado_ce_hub_ce_home_insights` |
| — | — | `sensor.tado_ce_hub_ce_homekit_reads_saved` |
| — | — | `sensor.tado_ce_hub_ce_homekit_writes_saved` |

---

## Bridge API — Dynamic Discovery (up to 15 entities)

> Entities are dynamically discovered from the Bridge API response. Which entities appear depends on your wiring type (OpenTherm, eBUS, Relay). Entities marked 🟢 are enabled by default; entities marked 🔘 require manual enabling in the HA UI.

### Default Enabled (visible when Bridge API is configured)

| Function | CE? | Name | Platform | Wiring |
|----------|-----|------|----------|--------|
| Bridge API health | ✓ | Bridge Connected | `binary_sensor` | All |
| Boiler wiring state | ✓ | Bridge Wiring State | `sensor` | All |
| Boiler output temperature | ✓ | Bridge Boiler Output Temp | `sensor` | OpenTherm |
| Boiler flow temperature | ✓ | Bridge Boiler Flow Temp | `sensor` | eBUS |
| Max output temp control | ✓ | Boiler Max Output Temperature | `number` | OpenTherm |

### Default Disabled (user must manually enable)

| Function | CE? | Name | Platform | Wiring |
|----------|-----|------|----------|--------|
| Output temp timestamp | ✓ | Bridge Boiler Output Temp Time | `sensor` | OpenTherm |
| Flow temp timestamp | ✓ | Bridge Boiler Flow Temp Time | `sensor` | eBUS |
| Max output temperature (read-only) | ✓ | Bridge Boiler Max Output Temp | `sensor` | OpenTherm |
| Hot water zone present | ✓ | Bridge Hot Water Present | `sensor` | All |
| Bridge device type | ✓ | Bridge Device Type | `sensor` | All |
| Bridge device serial | ✓ | Bridge Device Serial | `sensor` | All |
| Therm interface type | ✓ | Bridge Therm Interface Type | `sensor` | All |
| Bridge device connected | ✓ | Bridge Device Connected | `sensor` | All |
| Bridge capabilities summary | ✓ | Bridge Capabilities | `sensor` | All |
| Bridge schema version | ✓ | Bridge Schema Version | `sensor` | All |

> **Note:** Any additional unknown fields discovered from the Bridge API are automatically created as disabled diagnostic sensors. The `number` entity (#22) provides flow temperature control via the Bridge API.

---

## Hub Controls (5 entities)

### Friendly Names

| Function | CE? | v2.3.1 Name | v3.0 Name |
|----------|-----|-------------|-----------|
| Resume all schedules | ✓ | Resume All Schedules | Resume All |
| Refresh AC cache | ✓ | Refresh AC Capabilities | Refresh AC |
| Presence mode | ✓ | Presence Mode | Presence Mode |
| Overlay mode | ✓ | Overlay Mode | Overlay Mode |
| Overlay timer duration | ✓ | Overlay Timer Duration | Overlay Timer |

### Entity IDs

| v2.3.1 entity_id | v3.0 entity_id (fresh) |
|-------------------|------------------------|
| `button.tado_ce_resume_all_schedules` | `button.tado_ce_hub_ce_resume_all` |
| `button.tado_ce_refresh_ac_capabilities` | `button.tado_ce_hub_ce_refresh_ac` |
| `select.tado_ce_presence_mode` | `select.tado_ce_hub_ce_presence_mode` |
| `select.tado_ce_overlay_mode` | `select.tado_ce_hub_ce_overlay_mode` |
| `select.tado_ce_overlay_timer_duration` | `select.tado_ce_hub_ce_overlay_timer` |

---

## Hub Binary Sensors (1 always + 2 optional)

### Friendly Names

| Function | CE? | v2.3.1 Name | v3.0 Name | v4.0 Name |
|----------|-----|-------------|-----------|-----------|
| Home/Away status | ✓ | Home | Home | Home |
| HomeKit connection status | ✓ | — | — | HomeKit Connected |

> Three hub-level binary sensors exist: Home/Away (always), HomeKit Connected (when HomeKit local control is enabled), and Bridge Connected (when the Internet Bridge is configured). Bridge Connected is documented separately under §Bridge API — Dynamic Discovery because its attributes depend on the bridge's wiring type. HomeKit Connected attributes include uptime, reconnect count, and mapped/unmapped zone counts.
>
> **Savings counters** — HomeKit Reads Saved (#18) and Writes Saved (#19) are standalone diagnostic sensors (disabled by default). They track how many API calls HomeKit local control has saved you today. Enable them in **Settings → Devices → Tado CE Hub → "X entities not shown"**. Counters survive HA restarts and reset when your API quota resets.
>
> **Write performance metrics** (`write_attempts`, `write_successes`, `write_fallbacks`, `write_avg_latency_ms`) — attributes on the HomeKit Connected sensor. Reset on every HA restart, API quota reset, and HomeKit reconnect. These reflect current network conditions, not historical data. All zeros means no writes have happened since the last restart.

### Entity IDs

| v2.3.1 entity_id | v3.0 entity_id (fresh) | v4.0 entity_id (fresh) |
|-------------------|------------------------|------------------------|
| `binary_sensor.tado_ce_home` | `binary_sensor.tado_ce_hub_ce_home` | — |
| — | — | `binary_sensor.tado_ce_hub_ce_homekit_connected` |

---

## Hub Config Switches (2 entities)

### Friendly Names

| Function | CE? | v2.3.1 Name | v3.0 Name |
|----------|-----|-------------|-----------|
| Quota reserve toggle | ✓ | — | Quota Reserve |

### Entity IDs

| v2.3.1 entity_id | v3.0 entity_id (fresh) |
|-------------------|------------------------|
| — | `switch.tado_ce_hub_ce_quota_reserve` |

---

## Zone Sensors — Core (6 entities per zone)

### Friendly Names

| Function | CE? | v2.3.1 Name | v3.0 Name |
|----------|-----|-------------|-----------|
| Temperature | | Lounge Temperature | Lounge Temp |
| Humidity | | Lounge Humidity | Lounge Humidity |
| Heating power % | | Lounge Heating Power | Lounge Heating |
| AC power % | | Lounge AC Power | Lounge AC |
| Target temperature | ✓ | Lounge Target | Lounge Target |
| Overlay status | ✓ | Lounge Mode | Lounge Overlay |

> **Note:** Boiler Flow Temp (Hub Sensors section) is defined in `sensor_zone.py` but attached to the hub device, not a zone device. Hot water power was a sensor in v2.x; it migrated to a binary sensor in v4.0.0 and now lives under §Zone Binary Sensors.

### Entity IDs

| v2.3.1 entity_id | v3.0 entity_id (fresh) |
|-------------------|------------------------|
| `sensor.lounge_temperature` | `sensor.lounge_temp` |
| `sensor.lounge_humidity` | `sensor.lounge_humidity` |
| `sensor.lounge_heating` | `sensor.lounge_heating` |
| `sensor.lounge_ac_power` | `sensor.lounge_ac` |
| `sensor.lounge_target` | `sensor.lounge_ce_target` |
| `sensor.lounge_mode` | `sensor.lounge_ce_overlay` |

---

## Zone Sensors — Smart Comfort (5 entities per zone)

### Friendly Names

| Function | CE? | v2.3.1 Name | v3.0 Name |
|----------|-----|-------------|-----------|
| Schedule deviation | ✓ | Lounge Historical Deviation | Lounge Schedule Deviation |
| Next schedule time | ✓ | Lounge Next Schedule | Lounge Next Schedule |
| Next schedule temp | ✓ | Lounge Next Schedule Temp | Lounge Next Sched Temp |
| Preheat advisor | ✓ | Lounge Preheat Advisor | Lounge Preheat Advisor |
| Comfort target | ✓ | Lounge Smart Comfort Target | Lounge Comfort Target |

### Entity IDs

| v2.3.1 entity_id | v3.0 entity_id (fresh) |
|-------------------|------------------------|
| `sensor.lounge_historical_deviation` | `sensor.lounge_ce_schedule_deviation` |
| `sensor.lounge_next_schedule_time` | `sensor.lounge_ce_next_schedule` |
| `sensor.lounge_next_schedule_temp` | `sensor.lounge_ce_next_sched_temp` |
| `sensor.lounge_preheat_advisor` | `sensor.lounge_ce_preheat_advisor` |
| `sensor.lounge_smart_comfort_target` | `sensor.lounge_ce_comfort_target` |

---

## Zone Sensors — Environment (6 entities per zone)

### Friendly Names

| Function | CE? | v2.3.1 Name | v3.0 Name |
|----------|-----|-------------|-----------|
| Mold risk level | ✓ | Lounge Mold Risk | Lounge Mold Risk |
| Mold risk % | ✓ | Lounge Mold Risk Percentage | Lounge Mold Risk % |
| Condensation risk | ✓ | Lounge Condensation Risk | Lounge Condensation |
| Surface temperature | ✓ | Lounge Surface Temperature | Lounge Surface Temp |
| Dew point | ✓ | Lounge Dew Point | Lounge Dew Point |
| Comfort level | ✓ | Lounge Comfort Level | Lounge Comfort Level |

### Entity IDs

| v2.3.1 entity_id | v3.0 entity_id (fresh) |
|-------------------|------------------------|
| `sensor.lounge_mold_risk` | `sensor.lounge_ce_mold_risk` |
| `sensor.lounge_mold_risk_percentage` | `sensor.lounge_ce_mold_risk_pct` |
| `sensor.lounge_condensation_risk` | `sensor.lounge_ce_condensation` |
| `sensor.lounge_surface_temperature` | `sensor.lounge_ce_surface_temp` |
| `sensor.lounge_dew_point` | `sensor.lounge_ce_dew_point` |
| `sensor.lounge_comfort_level` | `sensor.lounge_ce_comfort_level` |

---

## Zone Sensors — Thermal Analytics (6 entities per heating zone)

### Friendly Names

| Function | CE? | v2.3.1 Name | v3.0 Name |
|----------|-----|-------------|-----------|
| Thermal inertia | ✓ | Lounge Thermal Inertia | Lounge Thermal Inertia |
| Heating rate | ✓ | Lounge Avg Heating Rate | Lounge Heating Rate |
| Preheat time | ✓ | Lounge Preheat Time | Lounge Preheat Time |
| Analysis confidence | ✓ | Lounge Analysis Confidence | Lounge Confidence |
| Heating acceleration | ✓ | Lounge Heating Acceleration | Lounge Heat Accel |
| Approach factor | ✓ | Lounge Approach Factor | Lounge Approach Factor |

### Entity IDs

| v2.3.1 entity_id | v3.0 entity_id (fresh) |
|-------------------|------------------------|
| `sensor.lounge_thermal_inertia` | `sensor.lounge_ce_thermal_inertia` |
| `sensor.lounge_avg_heating_rate` | `sensor.lounge_ce_heating_rate` |
| `sensor.lounge_preheat_time` | `sensor.lounge_ce_preheat_time` |
| `sensor.lounge_analysis_confidence` | `sensor.lounge_ce_confidence` |
| `sensor.lounge_heating_acceleration` | `sensor.lounge_ce_heat_accel` |
| `sensor.lounge_approach_factor` | `sensor.lounge_ce_approach_factor` |

---

## Zone Sensors — Insights (1 entity per zone)

### Friendly Names

| Function | CE? | v2.3.1 Name | v3.0 Name |
|----------|-----|-------------|-----------|
| Zone insights | ✓ | Lounge Insights | Lounge Insights |

### Entity IDs

| v2.3.1 entity_id | v3.0 entity_id (fresh) |
|-------------------|------------------------|
| `sensor.lounge_insights` | `sensor.lounge_ce_insights` |

---

## Zone Binary Sensors (3 entities per zone + 1 per HOT_WATER zone)

### Friendly Names

| Function | CE? | v2.3.1 Name | v3.0 Name |
|----------|-----|-------------|-----------|
| Open window detected | | Lounge Window | Lounge Window |
| Preheat trigger | ✓ | Lounge Preheat Now | Lounge Preheat Now |
| Window predicted | ✓ | Lounge Window Predicted | Lounge Window Predicted |
| Hot water power (on/off) | ✓ | — | Lounge Power |

### Entity IDs

| v2.3.1 entity_id | v3.0 entity_id (fresh) |
|-------------------|------------------------|
| `binary_sensor.lounge_open_window` | `binary_sensor.lounge_window` |
| `binary_sensor.lounge_preheat_now` | `binary_sensor.lounge_ce_preheat_now` |
| `binary_sensor.lounge_window_predicted` | `binary_sensor.lounge_ce_window_predicted` |
| `sensor.lounge_power` (migrated) | `binary_sensor.lounge_power` |

---

## Device Sensors (1 sensor + 1 binary sensor per device)

### Friendly Names

| Function | CE? | v2.3.1 Name | v3.0 Name |
|----------|-----|-------------|-----------|
| Battery status | | Lounge SU1234 Battery | Lounge Battery |
| Connection status (connected/disconnected) | | Lounge SU1234 Connection | Lounge Connection |

> Connection is now a `binary_sensor` with `CONNECTIVITY` device class.
> Battery remains a `sensor` (Tado reports NORMAL/LOW/CRITICAL — not boolean).

### Entity IDs

| v2.3.1 entity_id | v3.0 entity_id (fresh) |
|-------------------|------------------------|
| `sensor.lounge_su1234_battery` | `sensor.lounge_battery` |
| `sensor.lounge_su1234_connection` (migrated) | `binary_sensor.lounge_connection` |

---

## Climate / Water Heater (3 entities per zone)

### Friendly Names

| Function | CE? | v2.3.1 Name | v3.0 Name |
|----------|-----|-------------|-----------|
| Heating climate | | Lounge | Lounge |
| AC climate | | Lounge | Lounge |
| Water heater | | Lounge | Lounge |

### Entity IDs

| v2.3.1 entity_id | v3.0 entity_id (fresh) |
|-------------------|------------------------|
| `climate.lounge` | `climate.lounge` |
| `climate.lounge` | `climate.lounge` |
| `water_heater.lounge` | `water_heater.lounge` |

### Smart Valve Control Attributes (heating zones only)

Smart Valve Control and Offset Sync (both v4.0.0+) don't create dedicated entities — they expose state via attributes on each heating zone's climate entity. Dashboards (e.g. Pulse Card) can read these attributes directly.

| Attribute | Present when | Value |
|-----------|--------------|-------|
| `valve_control_enabled` | Valve Target mode is configured | `true` |
| `valve_control_active` | SVC configured | `true` when controller is actively compensating; `false` when paused after a manual write or deactivated |
| `valve_control_backed_off` | Valve Target mode + BACKED_OFF state | `true` while the controller has yielded to a manual override (cleared on the next schedule block change) |
| `valve_control_mode` | Offset Sync configured | `"offset_sync"` |
| `valve_target` | Valve Target mode + currently writing | Current TRV target temperature (°C, rounded to 0.1) |
| `desired_target` | Valve Target mode + ACTIVE state | User's intended target temperature captured at IDLE→ACTIVE transition (°C) |
| `offset_celsius` | Device offset feature enabled | Current device offset in °C (populated after Offset Sync confirms a write, or when `set_temperature_offset` service is used) |
| `offset_clamped` (v4.0.0+) | `offset_celsius` present and Offset Sync has written at least once | `true` if the last write had to be clamped at Tado's ±10°C limit, `false` otherwise |
| `offset_clamp_direction` (v4.0.0+) | Same as `offset_clamped` | `"none"` / `"hit_max"` / `"hit_min"` — which bound was hit |

Configure SVC per zone under **Settings → Tado CE → Configure → Zone Configuration → External Sensors → Smart Valve Control Mode**.

> **Reading the clamp attributes:** when `offset_clamped: true` appears, the physical temperature gap between your external sensor and the TRV exceeded Tado's ±10°C device-offset limit. The `offset_celsius` value you see is the clamp boundary, not the full correction required. Check for draughts around the TRV, a cold external wall behind it, or an external sensor placed in a warmer pocket than the TRV itself.

---

## Zone Switches (2 entities per zone)

### Friendly Names

| Function | CE? | v2.3.1 Name | v3.0 Name |
|----------|-----|-------------|-----------|
| Early start | ⬆ | Lounge Early Start | Lounge Early Start |
| Child lock | | Lounge SU1234 Child Lock | Lounge Child Lock |

> ⬆ HA official exposes early start as a read-only binary sensor.
> CE provides a controllable switch to toggle the Tado early start feature on/off.

### Entity IDs

| v2.3.1 entity_id | v3.0 entity_id (fresh) |
|-------------------|------------------------|
| `switch.lounge_early_start` | `switch.lounge_early_start` |
| `switch.lounge_su1234_child_lock` | `switch.lounge_child_lock` |

---

## Zone Buttons (4 entities per zone)

### Friendly Names

| Function | CE? | v2.3.1 Name | v3.0 Name |
|----------|-----|-------------|-----------|
| Timer buttons | ✓ | Lounge {dur}min Timer | Lounge {dur}min Timer |
| Refresh schedule | ✓ | Lounge Refresh Schedule | Lounge Refresh Schedule |
| Boost | ⬆ | Lounge Boost | Lounge Boost |
| Smart boost | ✓ | Lounge Smart Boost | Lounge Smart Boost |

> ⬆ Boost replicates the Tado app's boost feature (25°C for 30min).
> HA official Tado integration does not expose this. Smart Boost (#79) is CE exclusive
> — it uses thermal analytics to calculate optimal duration.

### Entity IDs

| v2.3.1 entity_id | v3.0 entity_id (fresh) |
|-------------------|------------------------|
| `button.lounge_timer_30min` | `button.lounge_ce_30min_timer` |
| `button.lounge_refresh_schedule` | `button.lounge_ce_refresh_schedule` |
| `button.lounge_boost` | `button.lounge_boost` |
| `button.lounge_smart_boost` | `button.lounge_ce_smart_boost` |

---

## Calendar (1 entity per zone)

### Friendly Names

| Function | CE? | v2.3.1 Name | v3.0 Name |
|----------|-----|-------------|-----------|
| Zone schedule | ✓ | Lounge | Lounge Schedule |

### Entity IDs

| v2.3.1 entity_id | v3.0 entity_id (fresh) |
|-------------------|------------------------|
| `calendar.lounge` | `calendar.heating_schedule_ce_schedule` |

---

## Zone Config (removed in v3.1.0)

> **v3.1.0:** All 11 per-zone configuration entities (heat emitter, UFH buffer, adaptive preheat, smart comfort, window type, overlay mode, overlay timer, min/max temp, temp offset, surface offset) have been replaced by the centralised Options Flow menu. Legacy entities are automatically cleaned up on upgrade. New settings (window predicted sensitivity, external temp/humidity sensor) are also managed via Options Flow — no entities created.

---

## Device Tracker (1 entity per mobile device, CE exclusive)

### Friendly Names

| Function | CE? | v2.3.1 Name | v3.0 Name |
|----------|-----|-------------|-----------|
| Mobile presence | ✓ | Tado CE {device_name} | {device_name} |

### Entity IDs

| v2.3.1 entity_id | v3.0 entity_id (fresh) |
|-------------------|------------------------|
| `device_tracker.tado_ce_{device_name}` | `device_tracker.tado_ce_hub_ce_{device_name}` |

---

## Weather Compensation Sensors (2 entities, CE exclusive)

> **v3.3.0:** Requires Bridge API configured and Weather Compensation enabled in **Settings → Tado CE → Configure → Global Settings → Flow Temperature Control**.

### Friendly Names

| Function | CE? | v3.3.0 Name |
|----------|-----|-------------|
| Target flow temperature | ✓ | WC Target Flow Temp |
| Compensation status | ✓ | WC Status |

### Entity IDs

| v3.3.0 entity_id (fresh) |
|--------------------------|
| `sensor.tado_ce_hub_ce_wc_target_flow_temp` |
| `sensor.tado_ce_hub_ce_wc_status` |

---

## Summary

| Category | Count | CE ✓ | Enhanced ⬆ | Standard |
|----------|-------|------|-----------|----------|
| Hub Sensors | 19 | 16 | 0 | 3 |
| Bridge API — Dynamic Discovery | up to 15 | 15 | 0 | 0 |
| Hub Controls | 5 | 5 | 0 | 0 |
| Hub Binary Sensors | 1 always + 2 optional | 3 | 0 | 0 |
| Hub Config Switches | 2 | 2 | 0 | 0 |
| Zone Sensors — Core | 6 /zone | 2 | 0 | 4 |
| Zone Sensors — Smart Comfort | 5 /zone | 5 | 0 | 0 |
| Zone Sensors — Environment | 6 /zone | 6 | 0 | 0 |
| Zone Sensors — Thermal Analytics | 6 /zone | 6 | 0 | 0 |
| Zone Sensors — Insights | 1 /zone | 1 | 0 | 0 |
| Zone Binary Sensors | 3 /zone (+1 per HOT_WATER) | 2 | 0 | 1 |
| Device Sensors | 1 sensor + 1 binary /device | 0 | 0 | 2 |
| Climate / Water Heater | 3 /zone | 0 | 0 | 3 |
| Zone Switches | 2 /zone | 0 | 1 | 1 |
| Zone Buttons | 4 /zone | 2 | 1 | 0 |
| Calendar | 1 /zone | 1 | 0 | 0 |
| Zone Config | ~~11 /zone~~ 0 (Options Flow) | — | — | — |
| Device Tracker | 1 /device | 1 | 0 | 0 |
| Weather Compensation | 2 | 2 | 0 | 0 |
| **Total unique types** | **~90** | **~70** | **4** | **~12** |
