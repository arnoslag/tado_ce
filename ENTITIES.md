# Tado CE — Entity Reference (v4.0.0-beta.7)

This document lists all 86 entity types in Tado CE, organised by function.

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

## Hub Sensors (17 entities)

### Friendly Names

| # | Function | CE? | v2.3.1 Name | v3.0 Name |
|---|----------|-----|-------------|-----------|
| 1 | Outdoor temperature | | Outside Temperature | Outside Temp |
| 2 | Solar radiation | | Solar Intensity | Solar Intensity |
| 3 | Weather condition | | Weather | Weather |
| 4 | Boiler flow temp | ✓ | Boiler Flow Temperature | Boiler Flow Temp |
| 5 | Home identifier | ✓ | Home ID | Home ID |
| 6 | API calls used | ✓ | API Usage | API Usage |
| 7 | API reset countdown | ✓ | API Reset | API Reset |
| 8 | Daily API limit | ✓ | API Limit | API Limit |
| 9 | API health | ✓ | API Status | API Status |
| 10 | Auth token health | ✓ | Token Status | Token Status |
| 11 | Zone count | ✓ | Zone Count | Zone Count |
| 12 | Last sync time | ✓ | Last Sync | Last Sync |
| 13 | Next sync time | ✓ | Next Sync | Next Sync |
| 14 | Polling interval | ✓ | Polling Interval | Polling Interval |
| 15 | API call history | ✓ | Call History | Call History |
| 16 | API call breakdown | ✓ | API Call Breakdown | API Breakdown |
| 17 | Home-wide insights | ✓ | Home Insights | Home Insights |

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

## Bridge API — Dynamic Discovery (up to 15 entities)

> Entities are dynamically discovered from the Bridge API response. Which entities appear depends on your wiring type (OpenTherm, eBUS, Relay). Entities marked 🟢 are enabled by default; entities marked 🔘 require manual enabling in the HA UI.

### Default Enabled (visible when Bridge API is configured)

| # | Function | CE? | Name | Platform | Wiring |
|---|----------|-----|------|----------|--------|
| 18 | Bridge API health | ✓ | Bridge Connected | `binary_sensor` | All |
| 19 | Boiler wiring state | ✓ | Bridge Wiring State | `sensor` | All |
| 20 | Boiler output temperature | ✓ | Bridge Boiler Output Temp | `sensor` | OpenTherm |
| 21 | Boiler flow temperature | ✓ | Bridge Boiler Flow Temp | `sensor` | eBUS |
| 22 | Max output temp control | ✓ | Boiler Max Output Temperature | `number` | OpenTherm |

### Default Disabled (user must manually enable)

| # | Function | CE? | Name | Platform | Wiring |
|---|----------|-----|------|----------|--------|
| 23 | Output temp timestamp | ✓ | Bridge Boiler Output Temp Time | `sensor` | OpenTherm |
| 24 | Flow temp timestamp | ✓ | Bridge Boiler Flow Temp Time | `sensor` | eBUS |
| 25 | Max output temperature (read-only) | ✓ | Bridge Boiler Max Output Temp | `sensor` | OpenTherm |
| 26 | Hot water zone present | ✓ | Bridge Hot Water Present | `sensor` | All |
| 27 | Bridge device type | ✓ | Bridge Device Type | `sensor` | All |
| 28 | Bridge device serial | ✓ | Bridge Device Serial | `sensor` | All |
| 29 | Therm interface type | ✓ | Bridge Therm Interface Type | `sensor` | All |
| 30 | Bridge device connected | ✓ | Bridge Device Connected | `sensor` | All |
| 31 | Bridge capabilities summary | ✓ | Bridge Capabilities | `sensor` | All |
| 32 | Bridge schema version | ✓ | Bridge Schema Version | `sensor` | All |

> **Note:** Any additional unknown fields discovered from the Bridge API are automatically created as disabled diagnostic sensors. The `number` entity (#22) provides flow temperature control via the Bridge API.

---

## Hub Controls (5 entities)

### Friendly Names

| # | Function | CE? | v2.3.1 Name | v3.0 Name |
|---|----------|-----|-------------|-----------|
| 33 | Resume all schedules | ✓ | Resume All Schedules | Resume All |
| 34 | Refresh AC cache | ✓ | Refresh AC Capabilities | Refresh AC |
| 35 | Presence mode | ✓ | Presence Mode | Presence Mode |
| 36 | Overlay mode | ✓ | Overlay Mode | Overlay Mode |
| 37 | Overlay timer duration | ✓ | Overlay Timer Duration | Overlay Timer |

### Entity IDs

| # | v2.3.1 entity_id | v3.0 entity_id (fresh) |
|---|-------------------|------------------------|
| 33 | `button.tado_ce_resume_all_schedules` | `button.tado_ce_hub_ce_resume_all` |
| 34 | `button.tado_ce_refresh_ac_capabilities` | `button.tado_ce_hub_ce_refresh_ac` |
| 35 | `select.tado_ce_presence_mode` | `select.tado_ce_hub_ce_presence_mode` |
| 36 | `select.tado_ce_overlay_mode` | `select.tado_ce_hub_ce_overlay_mode` |
| 37 | `select.tado_ce_overlay_timer_duration` | `select.tado_ce_hub_ce_overlay_timer` |

---

## Hub Binary Sensors (2 entities, +1 optional)

### Friendly Names

| # | Function | CE? | v2.3.1 Name | v3.0 Name | v4.0 Name |
|---|----------|-----|-------------|-----------|-----------|
| 38 | Home/Away status | ✓ | Home | Home | Home |
| 84 | HomeKit connection status | ✓ | — | — | HomeKit Connected |

> HomeKit Connected (#84) only appears when HomeKit local control is enabled. Attributes include uptime, reconnect count, and mapped/unmapped zone counts.
>
> **Savings counters** (`reads_saved_today`, `writes_saved_today`) — survive HA restarts so your daily total stays accurate. Reset when your API quota resets.
>
> **Write performance metrics** (`write_attempts`, `write_successes`, `write_fallbacks`, `write_avg_latency_ms`) — reset on every HA restart, API quota reset, and HomeKit reconnect. These reflect current network conditions, not historical data. All zeros means no writes have happened since the last restart.

### Entity IDs

| # | v2.3.1 entity_id | v3.0 entity_id (fresh) | v4.0 entity_id (fresh) |
|---|-------------------|------------------------|------------------------|
| 38 | `binary_sensor.tado_ce_home` | `binary_sensor.tado_ce_hub_ce_home` | — |
| 84 | — | — | `binary_sensor.tado_ce_hub_ce_homekit_connected` |

---

## Hub Config Switches (2 entities)

### Friendly Names

| # | Function | CE? | v2.3.1 Name | v3.0 Name |
|---|----------|-----|-------------|-----------|
| 40 | Quota reserve toggle | ✓ | — | Quota Reserve |

### Entity IDs

| # | v2.3.1 entity_id | v3.0 entity_id (fresh) |
|---|-------------------|------------------------|
| 40 | — | `switch.tado_ce_hub_ce_quota_reserve` |

---

## Zone Sensors — Core (7 entities per zone)

### Friendly Names

| # | Function | CE? | v2.3.1 Name | v3.0 Name |
|---|----------|-----|-------------|-----------|
| 41 | Temperature | | Lounge Temperature | Lounge Temp |
| 42 | Humidity | | Lounge Humidity | Lounge Humidity |
| 43 | Heating power % | | Lounge Heating Power | Lounge Heating |
| 44 | AC power % | | Lounge AC Power | Lounge AC |
| 45 | Target temperature | ✓ | Lounge Target | Lounge Target |
| 46 | Overlay status | ✓ | Lounge Mode | Lounge Overlay |

> **Note:** Boiler Flow Temp (#4 in Hub Sensors) is defined in `sensor_zone.py` but attached to the hub device, not a zone device.

### Entity IDs

| # | v2.3.1 entity_id | v3.0 entity_id (fresh) |
|---|-------------------|------------------------|
| 41 | `sensor.lounge_temperature` | `sensor.lounge_temp` |
| 42 | `sensor.lounge_humidity` | `sensor.lounge_humidity` |
| 43 | `sensor.lounge_heating` | `sensor.lounge_heating` |
| 44 | `sensor.lounge_ac_power` | `sensor.lounge_ac` |
| 45 | `sensor.lounge_target` | `sensor.lounge_ce_target` |
| 46 | `sensor.lounge_mode` | `sensor.lounge_ce_overlay` |
| 47 | `sensor.lounge_power` | `sensor.lounge_ce_power` |

---

## Zone Sensors — Smart Comfort (5 entities per zone)

### Friendly Names

| # | Function | CE? | v2.3.1 Name | v3.0 Name |
|---|----------|-----|-------------|-----------|
| 48 | Schedule deviation | ✓ | Lounge Historical Deviation | Lounge Schedule Deviation |
| 49 | Next schedule time | ✓ | Lounge Next Schedule | Lounge Next Schedule |
| 50 | Next schedule temp | ✓ | Lounge Next Schedule Temp | Lounge Next Sched Temp |
| 51 | Preheat advisor | ✓ | Lounge Preheat Advisor | Lounge Preheat Advisor |
| 52 | Comfort target | ✓ | Lounge Smart Comfort Target | Lounge Comfort Target |

### Entity IDs

| # | v2.3.1 entity_id | v3.0 entity_id (fresh) |
|---|-------------------|------------------------|
| 48 | `sensor.lounge_historical_deviation` | `sensor.lounge_ce_schedule_deviation` |
| 49 | `sensor.lounge_next_schedule_time` | `sensor.lounge_ce_next_schedule` |
| 50 | `sensor.lounge_next_schedule_temp` | `sensor.lounge_ce_next_sched_temp` |
| 51 | `sensor.lounge_preheat_advisor` | `sensor.lounge_ce_preheat_advisor` |
| 52 | `sensor.lounge_smart_comfort_target` | `sensor.lounge_ce_comfort_target` |

---

## Zone Sensors — Environment (6 entities per zone)

### Friendly Names

| # | Function | CE? | v2.3.1 Name | v3.0 Name |
|---|----------|-----|-------------|-----------|
| 53 | Mold risk level | ✓ | Lounge Mold Risk | Lounge Mold Risk |
| 54 | Mold risk % | ✓ | Lounge Mold Risk Percentage | Lounge Mold Risk % |
| 55 | Condensation risk | ✓ | Lounge Condensation Risk | Lounge Condensation |
| 56 | Surface temperature | ✓ | Lounge Surface Temperature | Lounge Surface Temp |
| 57 | Dew point | ✓ | Lounge Dew Point | Lounge Dew Point |
| 58 | Comfort level | ✓ | Lounge Comfort Level | Lounge Comfort Level |

### Entity IDs

| # | v2.3.1 entity_id | v3.0 entity_id (fresh) |
|---|-------------------|------------------------|
| 53 | `sensor.lounge_mold_risk` | `sensor.lounge_ce_mold_risk` |
| 54 | `sensor.lounge_mold_risk_percentage` | `sensor.lounge_ce_mold_risk_pct` |
| 55 | `sensor.lounge_condensation_risk` | `sensor.lounge_ce_condensation` |
| 56 | `sensor.lounge_surface_temperature` | `sensor.lounge_ce_surface_temp` |
| 57 | `sensor.lounge_dew_point` | `sensor.lounge_ce_dew_point` |
| 58 | `sensor.lounge_comfort_level` | `sensor.lounge_ce_comfort_level` |

---

## Zone Sensors — Thermal Analytics (6 entities per heating zone)

### Friendly Names

| # | Function | CE? | v2.3.1 Name | v3.0 Name |
|---|----------|-----|-------------|-----------|
| 59 | Thermal inertia | ✓ | Lounge Thermal Inertia | Lounge Thermal Inertia |
| 60 | Heating rate | ✓ | Lounge Avg Heating Rate | Lounge Heating Rate |
| 61 | Preheat time | ✓ | Lounge Preheat Time | Lounge Preheat Time |
| 62 | Analysis confidence | ✓ | Lounge Analysis Confidence | Lounge Confidence |
| 63 | Heating acceleration | ✓ | Lounge Heating Acceleration | Lounge Heat Accel |
| 64 | Approach factor | ✓ | Lounge Approach Factor | Lounge Approach Factor |

### Entity IDs

| # | v2.3.1 entity_id | v3.0 entity_id (fresh) |
|---|-------------------|------------------------|
| 59 | `sensor.lounge_thermal_inertia` | `sensor.lounge_ce_thermal_inertia` |
| 60 | `sensor.lounge_avg_heating_rate` | `sensor.lounge_ce_heating_rate` |
| 61 | `sensor.lounge_preheat_time` | `sensor.lounge_ce_preheat_time` |
| 62 | `sensor.lounge_analysis_confidence` | `sensor.lounge_ce_confidence` |
| 63 | `sensor.lounge_heating_acceleration` | `sensor.lounge_ce_heat_accel` |
| 64 | `sensor.lounge_approach_factor` | `sensor.lounge_ce_approach_factor` |

---

## Zone Sensors — Insights (1 entity per zone)

### Friendly Names

| # | Function | CE? | v2.3.1 Name | v3.0 Name |
|---|----------|-----|-------------|-----------|
| 65 | Zone insights | ✓ | Lounge Insights | Lounge Insights |

### Entity IDs

| # | v2.3.1 entity_id | v3.0 entity_id (fresh) |
|---|-------------------|------------------------|
| 65 | `sensor.lounge_insights` | `sensor.lounge_ce_insights` |

---

## Zone Binary Sensors (3 entities per zone + 1 per HOT_WATER zone)

### Friendly Names

| # | Function | CE? | v2.3.1 Name | v3.0 Name |
|---|----------|-----|-------------|-----------|
| 66 | Open window detected | | Lounge Window | Lounge Window |
| 67 | Preheat trigger | ✓ | Lounge Preheat Now | Lounge Preheat Now |
| 68 | Window predicted | ✓ | Lounge Window Predicted | Lounge Window Predicted |
| 47 | Hot water power (on/off) | ✓ | — | Lounge Power |

### Entity IDs

| # | v2.3.1 entity_id | v3.0 entity_id (fresh) |
|---|-------------------|------------------------|
| 66 | `binary_sensor.lounge_open_window` | `binary_sensor.lounge_window` |
| 67 | `binary_sensor.lounge_preheat_now` | `binary_sensor.lounge_ce_preheat_now` |
| 68 | `binary_sensor.lounge_window_predicted` | `binary_sensor.lounge_ce_window_predicted` |
| 47 | `sensor.lounge_power` (migrated) | `binary_sensor.lounge_power` |

---

## Device Sensors (1 sensor + 1 binary sensor per device)

### Friendly Names

| # | Function | CE? | v2.3.1 Name | v3.0 Name |
|---|----------|-----|-------------|-----------|
| 69 | Battery status | | Lounge SU1234 Battery | Lounge Battery |
| 70 | Connection status (connected/disconnected) | | Lounge SU1234 Connection | Lounge Connection |

> Connection is now a `binary_sensor` with `CONNECTIVITY` device class.
> Battery remains a `sensor` (Tado reports NORMAL/LOW/CRITICAL — not boolean).

### Entity IDs

| # | v2.3.1 entity_id | v3.0 entity_id (fresh) |
|---|-------------------|------------------------|
| 69 | `sensor.lounge_su1234_battery` | `sensor.lounge_battery` |
| 70 | `sensor.lounge_su1234_connection` (migrated) | `binary_sensor.lounge_connection` |

---

## Climate / Water Heater (3 entities per zone)

### Friendly Names

| # | Function | CE? | v2.3.1 Name | v3.0 Name |
|---|----------|-----|-------------|-----------|
| 71 | Heating climate | | Lounge | Lounge |
| 72 | AC climate | | Lounge | Lounge |
| 73 | Water heater | | Lounge | Lounge |

### Entity IDs

| # | v2.3.1 entity_id | v3.0 entity_id (fresh) |
|---|-------------------|------------------------|
| 71 | `climate.lounge` | `climate.lounge` |
| 72 | `climate.lounge` | `climate.lounge` |
| 73 | `water_heater.lounge` | `water_heater.lounge` |

---

## Zone Switches (2 entities per zone)

### Friendly Names

| # | Function | CE? | v2.3.1 Name | v3.0 Name |
|---|----------|-----|-------------|-----------|
| 74 | Early start | ⬆ | Lounge Early Start | Lounge Early Start |
| 75 | Child lock | | Lounge SU1234 Child Lock | Lounge Child Lock |

> ⬆ HA official exposes early start as a read-only binary sensor.
> CE provides a controllable switch to toggle the Tado early start feature on/off.

### Entity IDs

| # | v2.3.1 entity_id | v3.0 entity_id (fresh) |
|---|-------------------|------------------------|
| 74 | `switch.lounge_early_start` | `switch.lounge_early_start` |
| 75 | `switch.lounge_su1234_child_lock` | `switch.lounge_child_lock` |

---

## Zone Buttons (4 entities per zone)

### Friendly Names

| # | Function | CE? | v2.3.1 Name | v3.0 Name |
|---|----------|-----|-------------|-----------|
| 76 | Timer buttons | ✓ | Lounge {dur}min Timer | Lounge {dur}min Timer |
| 77 | Refresh schedule | ✓ | Lounge Refresh Schedule | Lounge Refresh Schedule |
| 78 | Boost | ⬆ | Lounge Boost | Lounge Boost |
| 79 | Smart boost | ✓ | Lounge Smart Boost | Lounge Smart Boost |

> ⬆ Boost replicates the Tado app's boost feature (25°C for 30min).
> HA official Tado integration does not expose this. Smart Boost (#79) is CE exclusive
> — it uses thermal analytics to calculate optimal duration.

### Entity IDs

| # | v2.3.1 entity_id | v3.0 entity_id (fresh) |
|---|-------------------|------------------------|
| 76 | `button.lounge_timer_30min` | `button.lounge_ce_30min_timer` |
| 77 | `button.lounge_refresh_schedule` | `button.lounge_ce_refresh_schedule` |
| 78 | `button.lounge_boost` | `button.lounge_boost` |
| 79 | `button.lounge_smart_boost` | `button.lounge_ce_smart_boost` |

---

## Calendar (1 entity per zone)

### Friendly Names

| # | Function | CE? | v2.3.1 Name | v3.0 Name |
|---|----------|-----|-------------|-----------|
| 80 | Zone schedule | ✓ | Lounge | Lounge Schedule |

### Entity IDs

| # | v2.3.1 entity_id | v3.0 entity_id (fresh) |
|---|-------------------|------------------------|
| 80 | `calendar.lounge` | `calendar.heating_schedule_ce_schedule` |

---

## Zone Config (removed in v3.1.0)

> **v3.1.0:** All 11 per-zone configuration entities (heat emitter, UFH buffer, adaptive preheat, smart comfort, window type, overlay mode, overlay timer, min/max temp, temp offset, surface offset) have been replaced by the centralised Options Flow menu. Legacy entities are automatically cleaned up on upgrade. New settings (window predicted sensitivity, external temp/humidity sensor) are also managed via Options Flow — no entities created.

---

## Device Tracker (1 entity per mobile device, CE exclusive)

### Friendly Names

| # | Function | CE? | v2.3.1 Name | v3.0 Name |
|---|----------|-----|-------------|-----------|
| 81 | Mobile presence | ✓ | Tado CE {device_name} | {device_name} |

### Entity IDs

| # | v2.3.1 entity_id | v3.0 entity_id (fresh) |
|---|-------------------|------------------------|
| 81 | `device_tracker.tado_ce_{device_name}` | `device_tracker.tado_ce_hub_ce_{device_name}` |

---

## Weather Compensation Sensors (2 entities, CE exclusive)

> **v3.3.0:** Requires Bridge API configured and Weather Compensation enabled in **Settings → Tado CE → Configure → Global Settings → Flow Temperature Control**.

### Friendly Names

| # | Function | CE? | v3.3.0 Name |
|---|----------|-----|-------------|
| 82 | Target flow temperature | ✓ | WC Target Flow Temp |
| 83 | Compensation status | ✓ | WC Status |

### Entity IDs

| # | v3.3.0 entity_id (fresh) |
|---|--------------------------|
| 82 | `sensor.tado_ce_hub_ce_wc_target_flow_temp` |
| 83 | `sensor.tado_ce_hub_ce_wc_status` |

---

## Summary

| Category | Count | CE ✓ | Enhanced ⬆ | Standard |
|----------|-------|------|-----------|----------|
| Hub Sensors | 17 | 14 | 0 | 3 |
| Bridge API — Dynamic Discovery | up to 15 | 15 | 0 | 0 |
| Hub Controls | 5 | 5 | 0 | 0 |
| Hub Binary Sensors | 2 (+1 optional) | 2 | 0 | 0 |
| Hub Config Switches | 2 | 2 | 0 | 0 |
| Zone Sensors — Core | 7 /zone | 3 | 0 | 4 |
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
| **Total unique types** | **87** | **~69** | **4** | **~12** |
