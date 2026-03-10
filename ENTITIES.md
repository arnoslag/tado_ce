# Tado CE — Entity Reference (v3.0.0)

This document lists all 75 entities in Tado CE, organised by function.

## How to Read This Document

**Two tables per section:**

1. **Friendly Names** — what you see in the HA UI
2. **Entity IDs** — what you use in automations and YAML

**Column guide:**

| Column | Meaning |
|--------|---------|
| CE? | `[CE]` = CE Exclusive (not in official Tado integration) |
| v2.3.1 Name | Friendly name in v2.3.1 |
| v3.0 Name | Friendly name in v3.0.0 (all users, immediate) |
| v2.3.1 entity_id | Entity ID in v2.3.1 (preserved for migrated users) |
| v3.0 entity_id (fresh) | Entity ID for fresh v3.0.0 installs |

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

## Hub Sensors (17 entities)

### Friendly Names

| # | Function | CE? | v2.3.1 Name | v3.0 Name |
|---|----------|-----|-------------|-----------|
| 1 | Outdoor temperature | | Outside Temperature | Outside Temp |
| 2 | Solar radiation | | Solar Intensity | Solar Intensity |
| 3 | Weather condition | | Weather | Weather |
| 4 | Boiler flow temp | ✓ | Boiler Flow Temperature | [CE] Boiler Flow Temp |
| 5 | Home identifier | ✓ | Home ID | [CE] Home ID |
| 6 | API calls used | ✓ | API Usage | [CE] API Usage |
| 7 | API reset countdown | ✓ | API Reset | [CE] API Reset |
| 8 | Daily API limit | ✓ | API Limit | [CE] API Limit |
| 9 | API health | ✓ | API Status | [CE] API Status |
| 10 | Auth token health | ✓ | Token Status | [CE] Token Status |
| 11 | Zone count | ✓ | Zone Count | [CE] Zone Count |
| 12 | Last sync time | ✓ | Last Sync | [CE] Last Sync |
| 13 | Next sync time | ✓ | Next Sync | [CE] Next Sync |
| 14 | Polling interval | ✓ | Polling Interval | [CE] Polling Interval |
| 15 | API call history | ✓ | Call History | [CE] Call History |
| 16 | API call breakdown | ✓ | API Call Breakdown | [CE] API Breakdown |
| 17 | Home-wide insights | ✓ | Home Insights | [CE] Home Insights |

### Entity IDs

| # | v2.3.1 entity_id | v3.0 entity_id (fresh) |
|---|-------------------|------------------------|
| 1 | `sensor.tado_ce_outside_temperature` | `sensor.tado_ce_hub_outside_temp` |
| 2 | `sensor.tado_ce_solar_intensity` | `sensor.tado_ce_hub_solar_intensity` |
| 3 | `sensor.tado_ce_weather_state` | `sensor.tado_ce_hub_weather` |
| 4 | `sensor.tado_ce_boiler_flow_temperature` | `sensor.tado_ce_hub_ce_boiler_flow_temp` |
| 5 | `sensor.tado_ce_home_id` | `sensor.tado_ce_hub_ce_home_id` |
| 6 | `sensor.tado_ce_api_usage` | `sensor.tado_ce_hub_ce_api_usage` |
| 7 | `sensor.tado_ce_api_reset` | `sensor.tado_ce_hub_ce_api_reset` |
| 8 | `sensor.tado_ce_api_limit` | `sensor.tado_ce_hub_ce_api_limit` |
| 9 | `sensor.tado_ce_api_status` | `sensor.tado_ce_hub_ce_api_status` |
| 10 | `sensor.tado_ce_token_status` | `sensor.tado_ce_hub_ce_token_status` |
| 11 | `sensor.tado_ce_zones_count` | `sensor.tado_ce_hub_ce_zone_count` |
| 12 | `sensor.tado_ce_last_sync` | `sensor.tado_ce_hub_ce_last_sync` |
| 13 | `sensor.tado_ce_next_sync` | `sensor.tado_ce_hub_ce_next_sync` |
| 14 | `sensor.tado_ce_polling_interval` | `sensor.tado_ce_hub_ce_polling_interval` |
| 15 | `sensor.tado_ce_call_history` | `sensor.tado_ce_hub_ce_call_history` |
| 16 | `sensor.tado_ce_api_call_breakdown` | `sensor.tado_ce_hub_ce_api_breakdown` |
| 17 | `sensor.tado_ce_home_insights` | `sensor.tado_ce_hub_ce_home_insights` |

---

## Hub Controls (5 entities)

### Friendly Names

| # | Function | CE? | v2.3.1 Name | v3.0 Name |
|---|----------|-----|-------------|-----------|
| 18 | Resume all schedules | ✓ | Resume All Schedules | [CE] Resume All |
| 19 | Refresh AC cache | ✓ | Refresh AC Capabilities | [CE] Refresh AC |
| 20 | Presence mode | ✓ | Presence Mode | [CE] Presence Mode |
| 21 | Overlay mode | ✓ | Overlay Mode | [CE] Overlay Mode |
| 22 | Overlay timer duration | ✓ | Overlay Timer Duration | [CE] Overlay Timer |

### Entity IDs

| # | v2.3.1 entity_id | v3.0 entity_id (fresh) |
|---|-------------------|------------------------|
| 18 | `button.tado_ce_resume_all_schedules` | `button.tado_ce_hub_ce_resume_all` |
| 19 | `button.tado_ce_refresh_ac_capabilities` | `button.tado_ce_hub_ce_refresh_ac` |
| 20 | `select.tado_ce_presence_mode` | `select.tado_ce_hub_ce_presence_mode` |
| 21 | `select.tado_ce_overlay_mode` | `select.tado_ce_hub_ce_overlay_mode` |
| 22 | `select.tado_ce_overlay_timer_duration` | `select.tado_ce_hub_ce_overlay_timer` |

---

## Hub Binary Sensor (1 entity)

### Friendly Names

| # | Function | CE? | v2.3.1 Name | v3.0 Name |
|---|----------|-----|-------------|-----------|
| 23 | Home/Away status | ✓ | Home | [CE] Home |

### Entity IDs

| # | v2.3.1 entity_id | v3.0 entity_id (fresh) |
|---|-------------------|------------------------|
| 23 | `binary_sensor.tado_ce_home` | `binary_sensor.tado_ce_hub_ce_home` |

---

## Zone Sensors — Core (8 entities per zone)

### Friendly Names

| # | Function | CE? | v2.3.1 Name | v3.0 Name |
|---|----------|-----|-------------|-----------|
| 24 | Temperature | | Lounge Temperature | Lounge Temp |
| 25 | Humidity | | Lounge Humidity | Lounge Humidity |
| 26 | Heating power % | | Lounge Heating Power | Lounge Heating |
| 27 | AC power % | | Lounge AC Power | Lounge AC |
| 28 | Target temperature | ✓ | Lounge Target | Lounge [CE] Target |
| 29 | Overlay status | ✓ | Lounge Mode | Lounge [CE] Overlay |
| 30 | Hot water power | ✓ | Lounge Power | Lounge [CE] Power |
| 31 | Schedule deviation | ✓ | Lounge Historical Deviation | Lounge [CE] Schedule Deviation |

### Entity IDs

| # | v2.3.1 entity_id | v3.0 entity_id (fresh) |
|---|-------------------|------------------------|
| 24 | `sensor.lounge_temperature` | `sensor.lounge_temp` |
| 25 | `sensor.lounge_humidity` | `sensor.lounge_humidity` |
| 26 | `sensor.lounge_heating` | `sensor.lounge_heating` |
| 27 | `sensor.lounge_ac_power` | `sensor.lounge_ac` |
| 28 | `sensor.lounge_target` | `sensor.lounge_ce_target` |
| 29 | `sensor.lounge_mode` | `sensor.lounge_ce_overlay` |
| 30 | `sensor.lounge_power` | `sensor.lounge_ce_power` |
| 31 | `sensor.lounge_historical_deviation` | `sensor.lounge_ce_schedule_deviation` |

---

## Zone Sensors — Smart Comfort (4 entities per zone)

### Friendly Names

| # | Function | CE? | v2.3.1 Name | v3.0 Name |
|---|----------|-----|-------------|-----------|
| 32 | Next schedule time | ✓ | Lounge Next Schedule | Lounge [CE] Next Schedule |
| 33 | Next schedule temp | ✓ | Lounge Next Schedule Temp | Lounge [CE] Next Sched Temp |
| 34 | Preheat advisor | ✓ | Lounge Preheat Advisor | Lounge [CE] Preheat Advisor |
| 35 | Comfort target | ✓ | Lounge Smart Comfort Target | Lounge [CE] Comfort Target |

### Entity IDs

| # | v2.3.1 entity_id | v3.0 entity_id (fresh) |
|---|-------------------|------------------------|
| 32 | `sensor.lounge_next_schedule_time` | `sensor.lounge_ce_next_schedule` |
| 33 | `sensor.lounge_next_schedule_temp` | `sensor.lounge_ce_next_sched_temp` |
| 34 | `sensor.lounge_preheat_advisor` | `sensor.lounge_ce_preheat_advisor` |
| 35 | `sensor.lounge_smart_comfort_target` | `sensor.lounge_ce_comfort_target` |

---

## Zone Sensors — Environment (6 entities per zone)

### Friendly Names

| # | Function | CE? | v2.3.1 Name | v3.0 Name |
|---|----------|-----|-------------|-----------|
| 36 | Mold risk level | ✓ | Lounge Mold Risk | Lounge [CE] Mold Risk |
| 37 | Mold risk % | ✓ | Lounge Mold Risk Percentage | Lounge [CE] Mold Risk % |
| 38 | Condensation risk | ✓ | Lounge Condensation Risk | Lounge [CE] Condensation |
| 39 | Surface temperature | ✓ | Lounge Surface Temperature | Lounge [CE] Surface Temp |
| 40 | Dew point | ✓ | Lounge Dew Point | Lounge [CE] Dew Point |
| 41 | Comfort level | ✓ | Lounge Comfort Level | Lounge [CE] Comfort Level |

### Entity IDs

| # | v2.3.1 entity_id | v3.0 entity_id (fresh) |
|---|-------------------|------------------------|
| 36 | `sensor.lounge_mold_risk` | `sensor.lounge_ce_mold_risk` |
| 37 | `sensor.lounge_mold_risk_percentage` | `sensor.lounge_ce_mold_risk_pct` |
| 38 | `sensor.lounge_condensation_risk` | `sensor.lounge_ce_condensation` |
| 39 | `sensor.lounge_surface_temperature` | `sensor.lounge_ce_surface_temp` |
| 40 | `sensor.lounge_dew_point` | `sensor.lounge_ce_dew_point` |
| 41 | `sensor.lounge_comfort_level` | `sensor.lounge_ce_comfort_level` |

---

## Zone Sensors — Thermal Analytics (6 entities per heating zone)

### Friendly Names

| # | Function | CE? | v2.3.1 Name | v3.0 Name |
|---|----------|-----|-------------|-----------|
| 42 | Thermal inertia | ✓ | Lounge Thermal Inertia | Lounge [CE] Thermal Inertia |
| 43 | Heating rate | ✓ | Lounge Avg Heating Rate | Lounge [CE] Heating Rate |
| 44 | Preheat time | ✓ | Lounge Preheat Time | Lounge [CE] Preheat Time |
| 45 | Analysis confidence | ✓ | Lounge Analysis Confidence | Lounge [CE] Confidence |
| 46 | Heating acceleration | ✓ | Lounge Heating Acceleration | Lounge [CE] Heat Accel |
| 47 | Approach factor | ✓ | Lounge Approach Factor | Lounge [CE] Approach Factor |

### Entity IDs

| # | v2.3.1 entity_id | v3.0 entity_id (fresh) |
|---|-------------------|------------------------|
| 42 | `sensor.lounge_thermal_inertia` | `sensor.lounge_ce_thermal_inertia` |
| 43 | `sensor.lounge_avg_heating_rate` | `sensor.lounge_ce_heating_rate` |
| 44 | `sensor.lounge_preheat_time` | `sensor.lounge_ce_preheat_time` |
| 45 | `sensor.lounge_analysis_confidence` | `sensor.lounge_ce_confidence` |
| 46 | `sensor.lounge_heating_acceleration` | `sensor.lounge_ce_heat_accel` |
| 47 | `sensor.lounge_approach_factor` | `sensor.lounge_ce_approach_factor` |

---

## Zone Sensors — Insights (1 entity per zone)

### Friendly Names

| # | Function | CE? | v2.3.1 Name | v3.0 Name |
|---|----------|-----|-------------|-----------|
| 48 | Zone insights | ✓ | Lounge Insights | Lounge [CE] Insights |

### Entity IDs

| # | v2.3.1 entity_id | v3.0 entity_id (fresh) |
|---|-------------------|------------------------|
| 48 | `sensor.lounge_insights` | `sensor.lounge_ce_insights` |

---

## Zone Binary Sensors (3 entities per zone)

### Friendly Names

| # | Function | CE? | v2.3.1 Name | v3.0 Name |
|---|----------|-----|-------------|-----------|
| 49 | Open window detected | | Lounge Window | Lounge Window |
| 50 | Preheat trigger | ✓ | Lounge Preheat Now | Lounge [CE] Preheat Now |
| 51 | Window predicted | ✓ | Lounge Window Predicted | Lounge [CE] Window Predicted |

### Entity IDs

| # | v2.3.1 entity_id | v3.0 entity_id (fresh) |
|---|-------------------|------------------------|
| 49 | `binary_sensor.lounge_open_window` | `binary_sensor.lounge_window` |
| 50 | `binary_sensor.lounge_preheat_now` | `binary_sensor.lounge_ce_preheat_now` |
| 51 | `binary_sensor.lounge_window_predicted` | `binary_sensor.lounge_ce_window_predicted` |

---

## Device Sensors (2 entities per device)

### Friendly Names

| # | Function | CE? | v2.3.1 Name | v3.0 Name |
|---|----------|-----|-------------|-----------|
| 52 | Battery status | ⬆ | Lounge SU1234 Battery | Lounge Battery |
| 53 | Connection status | ⬆ | Lounge SU1234 Connection | Lounge Connection |

> ⬆ HA official exposes battery/connection as binary sensors (on/off).
> CE provides detailed sensor entities with state attributes (firmware, device type, recommendations).

### Entity IDs

| # | v2.3.1 entity_id | v3.0 entity_id (fresh) |
|---|-------------------|------------------------|
| 52 | `sensor.lounge_su1234_battery` | `sensor.lounge_battery` |
| 53 | `sensor.lounge_su1234_connection` | `sensor.lounge_connection` |

---

## Climate / Water Heater (3 entities per zone)

### Friendly Names

| # | Function | CE? | v2.3.1 Name | v3.0 Name |
|---|----------|-----|-------------|-----------|
| 54 | Heating climate | | Lounge | Lounge |
| 55 | AC climate | | Lounge | Lounge |
| 56 | Water heater | | Lounge | Lounge |

### Entity IDs

| # | v2.3.1 entity_id | v3.0 entity_id (fresh) |
|---|-------------------|------------------------|
| 54 | `climate.lounge` | `climate.lounge` |
| 55 | `climate.lounge` | `climate.lounge` |
| 56 | `water_heater.lounge` | `water_heater.lounge` |

---

## Zone Switches (2 entities per zone)

### Friendly Names

| # | Function | CE? | v2.3.1 Name | v3.0 Name |
|---|----------|-----|-------------|-----------|
| 57 | Early start | ⬆ | Lounge Early Start | Lounge Early Start |
| 58 | Child lock | | Lounge SU1234 Child Lock | Lounge Child Lock |

> ⬆ HA official exposes early start as a read-only binary sensor.
> CE provides a controllable switch to toggle the Tado early start feature on/off.

### Entity IDs

| # | v2.3.1 entity_id | v3.0 entity_id (fresh) |
|---|-------------------|------------------------|
| 57 | `switch.lounge_early_start` | `switch.lounge_early_start` |
| 58 | `switch.lounge_su1234_child_lock` | `switch.lounge_child_lock` |

---

## Zone Buttons (4 entities per zone)

### Friendly Names

| # | Function | CE? | v2.3.1 Name | v3.0 Name |
|---|----------|-----|-------------|-----------|
| 59 | Timer buttons | ✓ | Lounge {dur}min Timer | Lounge [CE] {dur}min Timer |
| 60 | Refresh schedule | ✓ | Lounge Refresh Schedule | Lounge [CE] Refresh Schedule |
| 61 | Boost | ⬆ | Lounge Boost | Lounge Boost |
| 62 | Smart boost | ✓ | Lounge Smart Boost | Lounge [CE] Smart Boost |

> ⬆ Boost replicates the Tado app's boost feature (25°C for 30min).
> HA official Tado integration does not expose this. Smart Boost (#62) is CE exclusive
> — it uses thermal analytics to calculate optimal duration.

### Entity IDs

| # | v2.3.1 entity_id | v3.0 entity_id (fresh) |
|---|-------------------|------------------------|
| 59 | `button.lounge_timer_30min` | `button.lounge_ce_30min_timer` |
| 60 | `button.lounge_refresh_schedule` | `button.lounge_ce_refresh_schedule` |
| 61 | `button.lounge_boost` | `button.lounge_boost` |
| 62 | `button.lounge_smart_boost` | `button.lounge_ce_smart_boost` |

---

## Calendar (1 entity per zone)

### Friendly Names

| # | Function | CE? | v2.3.1 Name | v3.0 Name |
|---|----------|-----|-------------|-----------|
| 63 | Zone schedule | ✓ | Lounge | Lounge [CE] Schedule |

### Entity IDs

| # | v2.3.1 entity_id | v3.0 entity_id (fresh) |
|---|-------------------|------------------------|
| 63 | `calendar.lounge` | `calendar.heating_schedule_ce_schedule` |

---

## Zone Config (11 entities per zone, all CE exclusive)

### Friendly Names

| # | Function | CE? | v2.3.1 Name | v3.0 Name |
|---|----------|-----|-------------|-----------|
| 64 | Heat emitter type | ✓ | Heat Emitter Type | [CE] Heat Emitter |
| 65 | UFH buffer | ✓ | UFH Buffer | [CE] UFH Buffer |
| 66 | Adaptive preheat | ✓ | Adaptive Preheat | [CE] Adaptive Preheat |
| 67 | Smart comfort mode | ✓ | Smart Comfort | [CE] Smart Comfort |
| 68 | Window type | ✓ | Window Type | [CE] Window Type |
| 69 | Zone overlay mode | ✓ | Overlay Mode | [CE] Overlay Mode |
| 70 | Zone overlay timer | ✓ | Overlay Timer Duration | [CE] Overlay Timer |
| 71 | Min temperature | ✓ | Min Temp | [CE] Min Temp |
| 72 | Max temperature | ✓ | Max Temp | [CE] Max Temp |
| 73 | Temp offset | ✓ | Temp Offset | [CE] Temp Offset |
| 74 | Surface temp offset | ✓ | Surface Temp Offset | [CE] Surface Offset |

### Entity IDs

| # | v2.3.1 entity_id | v3.0 entity_id (fresh) |
|---|-------------------|------------------------|
| 64 | `select.lounge_heating_type` | `select.lounge_ce_heat_emitter` |
| 65 | `number.lounge_ufh_buffer` | `number.lounge_ce_ufh_buffer` |
| 66 | `switch.lounge_adaptive_preheat` | `switch.lounge_ce_adaptive_preheat` |
| 67 | `select.lounge_smart_comfort_mode` | `select.lounge_ce_smart_comfort` |
| 68 | `select.lounge_window_type` | `select.lounge_ce_window_type` |
| 69 | `select.lounge_overlay_mode` | `select.lounge_ce_overlay_mode` |
| 70 | `select.lounge_overlay_timer_duration` | `select.lounge_ce_overlay_timer` |
| 71 | `number.lounge_min_temp` | `number.lounge_ce_min_temp` |
| 72 | `number.lounge_max_temp` | `number.lounge_ce_max_temp` |
| 73 | `number.lounge_temp_offset` | `number.lounge_ce_temp_offset` |
| 74 | `number.lounge_surface_temp_offset` | `number.lounge_ce_surface_offset` |

---

## Device Tracker (1 entity per mobile device, CE exclusive)

### Friendly Names

| # | Function | CE? | v2.3.1 Name | v3.0 Name |
|---|----------|-----|-------------|-----------|
| 75 | Mobile presence | ✓ | Tado CE {device_name} | [CE] {device_name} |

### Entity IDs

| # | v2.3.1 entity_id | v3.0 entity_id (fresh) |
|---|-------------------|------------------------|
| 75 | `device_tracker.tado_ce_{device_name}` | `device_tracker.tado_ce_hub_ce_{device_name}` |

---

## Summary

| Category | Count | CE ✓ | Enhanced ⬆ | Standard |
|----------|-------|------|-----------|----------|
| Hub Sensors | 17 | 14 | 0 | 3 |
| Hub Controls | 5 | 5 | 0 | 0 |
| Hub Binary Sensor | 1 | 1 | 0 | 0 |
| Zone Sensors — Core | 8 /zone | 4 | 0 | 4 |
| Zone Sensors — Smart Comfort | 4 /zone | 4 | 0 | 0 |
| Zone Sensors — Environment | 6 /zone | 6 | 0 | 0 |
| Zone Sensors — Thermal Analytics | 6 /zone | 6 | 0 | 0 |
| Zone Sensors — Insights | 1 /zone | 1 | 0 | 0 |
| Zone Binary Sensors | 3 /zone | 2 | 0 | 1 |
| Device Sensors | 2 /device | 0 | 2 | 0 |
| Climate / Water Heater | 3 /zone | 0 | 0 | 3 |
| Zone Switches | 2 /zone | 0 | 1 | 1 |
| Zone Buttons | 4 /zone | 2 | 1 | 0 |
| Calendar | 1 /zone | 1 | 0 | 0 |
| Zone Config | 11 /zone | 11 | 0 | 0 |
| Device Tracker | 1 /device | 1 | 0 | 0 |
| **Total unique types** | **75** | **~57** | **4** | **~12** |
