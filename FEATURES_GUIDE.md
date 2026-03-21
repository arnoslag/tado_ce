# Tado CE Features Guide

Complete guide to all Tado CE exclusive features, configurations, and usage scenarios.

> **Entity ID note:** All automation examples use **v2.3.1 entity_ids** (preserved for migrated users).
> Fresh v3.0.0 installs get different entity_ids — see [ENTITIES.md](ENTITIES.md) for the mapping.

## 📑 Table of Contents

1. [Multi-Home Support](#-multi-home-support)
2. [API Management](#-api-management)
3. [Smart Polling](#-smart-polling)
4. [Thermal Analytics](#-thermal-analytics)
5. [Smart Comfort Analytics](#-smart-comfort-analytics)
6. [Enhanced Mold Risk Assessment](#-enhanced-mold-risk-assessment)
7. [Heating Cycle Detection](#-heating-cycle-detection)
8. [Enhanced Controls](#-enhanced-controls)
9. [Bridge API Integration](#-bridge-api-integration)
10. [Weather Compensation](#-weather-compensation)
11. [Optional Features](#-optional-features)
12. [Per-Zone Configuration](#-per-zone-configuration)
13. [Zone Features Toggles](#-zone-features-toggles)
14. [Configuration Scenarios](#-configuration-scenarios)
15. [Actionable Insights](#-actionable-insights)
16. [Troubleshooting](#-troubleshooting)

---

## 🏠 Multi-Home Support

**Available:** v3.0.0 | **Requirement:** Multiple Tado homes/accounts | **Automatic**

Run multiple Tado accounts or homes in a single Home Assistant instance with full data isolation.

### Overview

Each config entry is completely isolated — its own coordinator, API client, data loader, and cleanup. All per-entry state uses `ConfigEntry.runtime_data` instead of shared global state. A line-by-line audit across all 60 source files confirmed zero data isolation issues.

### How It Works

1. Add a second Tado CE integration via **Settings → Devices & Services → Add Integration → Tado CE**
2. Authenticate with a different Tado account (or same account, different home)
3. Each home gets its own set of entities, data files, and polling schedule

### Data Isolation

All data files include `{home_id}` suffix:
- `zones_{home_id}.json`, `ratelimit_{home_id}.json`, `config_{home_id}.json`, etc.
- Entity unique IDs include `{home_id}` prefix for collision avoidance
- Each home has independent API quota tracking and adaptive polling

### Migration from Single-Home

If upgrading from v2.3.1 (single home), migration runs automatically:
- Entity unique IDs updated to include `{home_id}` prefix (idempotent)
- Refresh token copied from `config.json` to `entry.data`
- Existing automations continue to work unchanged

---

## 📊 API Management

**Available:** v1.0.0+ | **Requirement:** None | **Always Enabled**

Real-time tracking of your Tado API usage, helping you avoid rate limiting and understand consumption patterns.

### Overview

Tado enforces API rate limits (100–20,000 calls/day depending on your plan). The official HA integration doesn't expose usage data. Tado CE solves this by:

- Reading rate limit data from Tado API response headers
- Auto-detecting your daily limit (100/1000/20000)
- Tracking reset time, call history, and per-endpoint breakdown
- Providing Test Mode to simulate low-quota scenarios

### Sensors

| Sensor | Friendly Name | Unit | Description |
|--------|--------------|------|-------------|
| `sensor.tado_ce_api_usage` | API Usage | calls | API calls used today |
| `sensor.tado_ce_api_limit` | API Limit | calls | Daily API call limit |
| `sensor.tado_ce_api_reset` | API Reset | timestamp | When your limit resets |
| `sensor.tado_ce_api_status` | API Status | text | API connection status |
| `sensor.tado_ce_token_status` | Token Status | text | Auth token health |
| `sensor.tado_ce_next_sync` | Next Sync | timestamp | Next scheduled API sync |
| `sensor.tado_ce_polling_interval` | Polling Interval | minutes | Current polling interval |
| `sensor.tado_ce_call_history` | Call History | count | API call history with statistics |
| `sensor.tado_ce_api_call_breakdown` | API Breakdown | text | Call breakdown by endpoint type |

### API Status States

| State | Meaning | When |
|-------|---------|------|
| `ok` | All good | Quota usage < 80% |
| `warning` | High usage | Quota usage > 80% |
| `rate_limited` | Quota exhausted | Remaining = 0 |
| `error` | Connection issue | Failed to read rate limit data |
| `unavailable` | Sensor not ready | During HA restart/reload |

### Configuration

**API History Retention:**
1. Go to Settings → Devices & Services → Tado CE → Configure
2. Set "API History Retention" (0–365 days, default: 14)
3. Set to 0 for unlimited retention

**Test Mode (v2.0.2+):**
1. Enable "Enable Test Mode" in Configure
2. Integration simulates a 100 call/day API tier
3. Each API call increments a simulated counter (capped at 100)
4. All API sensors show `test_mode: true` attribute
5. Quota Reserve, Bootstrap Reserve, and Adaptive Polling all use simulated values
6. When real API reset is detected, simulated counter resets to 0

### Usage Scenarios

#### Scenario 1: Monitor API Usage to Avoid Rate Limiting

```yaml
automation:
  - alias: "Alert: API Usage High"
    trigger:
      - platform: state
        entity_id: sensor.tado_ce_api_status
        to: "warning"
    action:
      - service: notify.mobile_app
        data:
          title: "⚠️ Tado API Usage High"
          message: >
            API status: {{ states('sensor.tado_ce_api_status') }}.
            Usage: {{ states('sensor.tado_ce_api_usage') }} / {{ states('sensor.tado_ce_api_limit') }}.
            Resets at {{ states('sensor.tado_ce_api_reset') }}.
```

#### Scenario 2: Dashboard Card

```yaml
type: entities
entities:
  - entity: sensor.tado_ce_api_usage
    name: "Calls Used Today"
  - entity: sensor.tado_ce_api_limit
    name: "Daily Limit"
  - entity: sensor.tado_ce_api_status
    name: "API Status"
  - entity: sensor.tado_ce_api_reset
    name: "Resets At"
```

---

## 🔄 Smart Polling

**Available:** v1.0.0+ | **Requirement:** None | **Always Enabled**

Automatically adjusts API polling frequency based on time of day, remaining quota, and configuration.

### Overview

Smart Polling includes multiple strategies:

- **Day/Night Polling** — more frequent during day, less at night
- **Adaptive Polling** — auto-adjusts based on remaining quota (minimum 5 min, max 120 min)
- **Quota Reserve Protection** — pauses polling when quota critically low (≤5%), auto-resumes after reset
- **Bootstrap Reserve** — hard limit of 3 API calls never used, reserved for auto-recovery after reset
- **Custom Intervals** — override with fixed intervals (1–1440 min)

### Configuration

**Day/Night Schedule:**

| Option | Default | Description |
|--------|---------|-------------|
| Day Start Hour | 7 | When "day" period starts (0–23) |
| Night Start Hour | 23 | When "night" period starts (0–23) |
| Custom Day Interval | Empty | Fixed interval during day (1–1440 min) |
| Custom Night Interval | Empty | Fixed interval during night (1–1440 min) |

**Optional Sensors (affect API usage):**

| Option | Default | API Calls Saved |
|--------|---------|-----------------|
| Enable Weather Sensors | Off | 1 call per sync |
| Enable Mobile Device Tracking | Off | 1 call per full sync (every 6h) |
| Enable Home State Sync | Off | Required for Away Mode |

### How It Works

**Adaptive Polling Formula:**
```
Interval = (Time Until Reset / Remaining Calls) / 0.90
Clamped to: 5 min (floor) – 120 min (ceiling)
```

**Day/Night Aware (v2.0.1):**
- Night period: Fixed 120 min interval to conserve quota
- Day period: Adaptive based on remaining quota after reserving night calls
- If Day Start == Night Start: always uses adaptive polling (24/7 mode)

**Quota Reserve (v2.0.0):**
- Pauses polling when remaining ≤5% or ≤5 calls
- Reserves quota for manual operations (set temperature, change mode)
- Auto-resumes when API reset time passes

**Bootstrap Reserve (v2.0.1):**
- Hard limit of 3 API calls never used, even for manual actions
- When triggered: persistent notification "API limit reached. Use the Tado app for emergency changes."
- Auto-dismisses when API reset detected

### Usage Scenarios

#### Scenario 1: Low Quota (100 calls/day) Day/Night Setup

```
Day Start: 7, Night Start: 23
Custom Day Interval: 30 min, Custom Night Interval: 120 min
Weather: Off, Mobile Tracking: Off

Expected: Day 32 syncs × 2 = 64, Night 4 × 2 = 8, Full sync 4 × 2 = 8 → ~80 calls/day
```

#### Scenario 2: High Quota (1000+) Adaptive

Leave custom intervals empty. Adaptive polling uses 5-minute minimum. Enable all optional sensors. Adaptive will override if quota drops critically low.

#### Scenario 3: Disable Optional Sensors to Save Calls

- Weather off: saves ~144 calls/day (at 10 min intervals)
- Mobile tracking off: saves ~4 calls/day
- Home State Sync off: saves 1 call/sync

---

## 🔥 Thermal Analytics

**Available:** v2.0.0+ | **Requirement:** Zones with heatingPower data (TRV or Smart Thermostat) | **Always Enabled**

Real-time analysis of heating system thermal performance based on complete heating cycles.

### Sensors

| Sensor | Friendly Name | Unit | Description |
|--------|--------------|------|-------------|
| `sensor.{zone}_thermal_inertia` | Thermal Inertia | minutes | Time constant for temperature changes |
| `sensor.{zone}_avg_heating_rate` | Heating Rate | °C/h | Average heating rate when heating ON |
| `sensor.{zone}_preheat_time` | Preheat Time | minutes | Estimated time to reach target |
| `sensor.{zone}_analysis_confidence` | Confidence | % | Confidence score for analysis |
| `sensor.{zone}_heating_acceleration` | Heat Accel | °C/h² | Rate of change of heating rate |
| `sensor.{zone}_approach_factor` | Approach Factor | %/hour | How quickly zone approaches target |

### Sensor Interpretation

**Thermal Inertia:**
- Low (10–30 min): Room heats/cools quickly — may indicate poor insulation or small room
- Medium (30–60 min): Typical for most rooms
- High (60+ min): Good insulation or large thermal mass

**Heating Rate:**
- Slow (<0.6°C/h): Possible radiator, boiler, or insulation issues
- Normal (0.6–1.8°C/h): Typical
- Fast (>1.8°C/h): Small room or oversized radiator

**Analysis Confidence:**
- <50%: Not enough data yet
- 50–80%: Reasonable confidence
- >80%: High confidence, reliable estimates

**Approach Factor:**
- <50%/h: Slow approach, multiple hours to target
- 50–100%/h: Normal, 1–2 hours
- >100%/h: Fast approach, less than 1 hour

### Configuration

**Global Toggle:** Options → Tado CE Exclusive → Thermal Analytics

**Per-Zone Control (v2.1.0+):** Options → Tado CE Exclusive → Thermal Analytics Zones
- Default: All zones with heatingPower data enabled
- Deselect zones that never call for heat (passive heating) to keep UI clean

**Supported Devices (v2.0.1+):** TRV (VA01, VA02, RU01, RU02), Smart Thermostat (SU02)

### Usage Scenarios

#### Scenario 1: Optimize Preheat Timing

```yaml
automation:
  - alias: "Bedroom Preheat"
    trigger:
      - platform: time
        at: "17:30:00"
    condition:
      - condition: numeric_state
        entity_id: sensor.bedroom_preheat_time
        above: 20
    action:
      - service: climate.set_temperature
        target:
          entity_id: climate.bedroom
        data:
          temperature: 21
```

Wait for `_analysis_confidence` > 80% before trusting preheat estimates.

#### Scenario 2: Detect Insulation Issues

**Indicators:**
- Low thermal inertia (<20 min) — heat escapes quickly
- Low heating rate (<0.6°C/h) — struggling to heat
- High approach factor (>150%/h) — temperature fluctuates rapidly

**Action:** Check for drafts, verify radiator valve, check boiler flow temperature.

#### Scenario 3: Compare Room Performance

| Room | Thermal Inertia | Heating Rate | Confidence | Status |
|------|----------------|--------------|------------|--------|
| Living Room | 45 min | 1.2°C/h | 95% | ✅ Normal |
| Bedroom | 35 min | 1.5°C/h | 90% | ✅ Good |
| Bathroom | 15 min | 0.6°C/h | 85% | ⚠️ Poor insulation |
| Kitchen | 60 min | 0.8°C/h | 80% | ✅ High thermal mass |

#### Scenario 4: Detect Radiator/Boiler Problems

Watch for sudden drops in heating rate or increases in preheat time. Check radiator valve, bleed radiators, check boiler flow temperature, verify TRV battery.

---

## 🧠 Smart Comfort Analytics

**Available:** v1.9.0+ | **Requirement:** None | **Opt-in Configuration**

Learns from heating patterns and provides predictive insights.

### Sensors

| Sensor | Friendly Name | Unit | Description |
|--------|--------------|------|-------------|
| `sensor.{zone}_historical_deviation` | Schedule Deviation | °C | Difference from 7-day average at same time |
| `sensor.{zone}_next_schedule_time` | Next Schedule | timestamp | When next schedule change occurs |
| `sensor.{zone}_next_schedule_temp` | Next Sched Temp | °C | Target for next schedule block |
| `sensor.{zone}_preheat_advisor` | Preheat Advisor | minutes | Recommended preheat start time |
| `sensor.{zone}_smart_comfort_target` | Comfort Target | °C | AI-recommended target temperature |

### Preheat Cooling Rate Prediction (v3.0.0)

The Preheat Advisor now considers cooling trends when the room is above the target temperature. Previously, if `current_temp >= target_temp`, it simply showed "Ready" — now it estimates when the temperature will drop below target and calculates a proactive preheat start time.

**How it works:**
1. `estimate_cooling_crossover()` calculates hours until temperature crosses below target using the current cooling rate
2. If a crossover is predicted, the advisor calculates when to start preheating to prevent undershoot
3. Heating rate data (from thermal analytics) is used to determine how long preheat needs

**Preheat Advisor attributes (when cooling prediction active):**

| Attribute | Description |
|-----------|-------------|
| `cooling_rate` | Current cooling rate in °C/h (negative value) |
| `predicted_crossover_time` | Estimated time when temp will drop below target |
| `is_cooling_prediction` | `true` when cooling prediction is active |
| `summary` | Human-readable explanation of the prediction |

### Adaptive Preheat Passive Mode (v3.3.0+)

Preheat now has three modes per zone, configured via **Options Flow → Zone Configuration**:

| Mode | Behavior |
|------|----------|
| Off | Preheat disabled for this zone |
| Active | Always triggers preheat before the next schedule change |
| Passive | Only triggers when the zone is following its schedule — skips preheat if you've set a manual override from HomeKit, the Tado app, etc. |

Existing users with preheat enabled are automatically migrated to Active mode. Passive mode is useful if you frequently override temperatures manually and don't want preheat fighting your changes.

### Configuration

1. Settings → Devices & Services → Tado CE → Configure
2. Enable "Smart Comfort Analytics"
3. Configure Smart Comfort Mode: None / Light / Moderate / Aggressive
4. Set Temperature History days (1–30)
5. Optionally set Outdoor Temperature Entity for weather compensation

### Usage Scenarios

#### Scenario 1: Detect Unusual Patterns

```yaml
automation:
  - alias: "Alert: Room Colder Than Usual"
    trigger:
      - platform: numeric_state
        entity_id: sensor.bedroom_historical_deviation
        below: -2.0
    action:
      - service: notify.mobile_app
        data:
          message: "Bedroom is 2°C colder than usual — check for open windows"
```

#### Scenario 2: Automatic Preheat

```yaml
automation:
  - alias: "Smart Preheat Before Schedule"
    trigger:
      - platform: template
        value_template: >
          {{ now().timestamp() >= 
             (state_attr('sensor.bedroom_next_schedule_time', 'timestamp') - 
              (states('sensor.bedroom_preheat_advisor') | int * 60)) }}
    action:
      - service: climate.set_temperature
        target:
          entity_id: climate.bedroom
        data:
          temperature: "{{ states('sensor.bedroom_next_schedule_temp') }}"
```

#### Scenario 3: Energy Optimization

```yaml
automation:
  - alias: "Reduce Heating When Warmer Than Usual"
    trigger:
      - platform: numeric_state
        entity_id: sensor.living_room_historical_deviation
        above: 1.0
    condition:
      - condition: state
        entity_id: climate.living_room
        state: "heat"
    action:
      - service: climate.set_temperature
        target:
          entity_id: climate.living_room
        data:
          temperature: >
            {{ state_attr('climate.living_room', 'temperature') - 0.5 }}
```

---

## 💧 Enhanced Mold Risk Assessment

**Available:** v2.0.0+ | **Requirement:** Outdoor temperature sensor | **Always Enabled**

Uses surface temperature calculation to accurately detect cold spots where mold can grow.

### Sensors

| Sensor | Friendly Name | Description |
|--------|--------------|-------------|
| `sensor.{zone}_mold_risk` | Mold Risk | Risk level: Low / Medium / High / Critical |
| `sensor.{zone}_mold_risk_percentage` | Mold Risk % | Numeric risk percentage |
| `sensor.{zone}_condensation_risk` | Condensation | Condensation risk (AC zones) |
| `sensor.{zone}_surface_temperature` | Surface Temp | Calculated surface temperature |
| `sensor.{zone}_dew_point` | Dew Point | Dew point temperature |
| `sensor.{zone}_comfort_level` | Comfort Level | Overall comfort assessment |

### Heat Index & Heat Risk (v3.3.0+)

The Comfort Level sensor now includes "feels like" temperature when it's warm (above 26.7°C), factoring in humidity using the NOAA/NWS Rothfusz regression. Risk levels appear in the sensor attributes and in comfort recommendations.

**Comfort Level extra attributes (when heat index is active):**

| Attribute | Description |
|-----------|-------------|
| `heat_index` | Calculated "feels like" temperature (°C) |
| `heat_risk_level` | NOAA risk level (see table below) |

**Heat Risk Levels:**

| Risk Level | Heat Index | Guidance |
|------------|-----------|----------|
| None | Below 26.7°C | No heat risk |
| Caution | 26.7–32°C | Fatigue possible with prolonged exposure |
| Extreme Caution | 32–39°C | Heat cramps and exhaustion possible |
| Danger | 39–51°C | Heat cramps/exhaustion likely, heatstroke possible |
| Extreme Danger | Above 51°C | Heatstroke highly likely |

When heat index is active, the comfort level calculation uses the "feels like" temperature instead of the raw air temperature for deviation and recommendation logic.

### Window Type Settings

| Window Type | U-Value (W/m²K) | Mold Risk |
|-------------|-----------------|-----------|
| Single Pane | 5.0 | ⚠️ High |
| Double Pane | 2.7 | ⚠️ Medium |
| Triple Pane | 1.0 | ✅ Low |
| Passive House | 0.8 | ✅ Very Low |

### Mold Risk Thresholds

| Risk Level | Surface RH | Action |
|------------|-----------|--------|
| Low | <60% | None — safe |
| Medium | 60–70% | Monitor, increase ventilation |
| High | 70–80% | Action needed, increase heating |
| Critical | >80% | Urgent — mold growth likely |

### Configuration

1. Settings → Devices & Services → Tado CE → Configure
2. Select "Window Type" (default: Double Pane)
3. Set "Outdoor Temperature Entity" (e.g., `weather.home`)

**Per-Zone Window Type (v2.1.0+):** Use Zone Config entity `select.{zone}_window_type` to set different window types per zone.

### Usage Scenarios

#### Scenario 1: Prevent Mold Growth

```yaml
automation:
  - alias: "Alert: High Mold Risk"
    trigger:
      - platform: numeric_state
        entity_id: sensor.bedroom_mold_risk_percentage
        above: 70
        for:
          minutes: 30
    action:
      - service: notify.mobile_app
        data:
          title: "⚠️ High Mold Risk in Bedroom"
          message: >
            Mold risk: {{ states('sensor.bedroom_mold_risk_percentage') }}%
            Surface temp: {{ state_attr('sensor.bedroom_mold_risk', 'surface_temperature') }}°C
            Action: Increase heating or ventilate
```

#### Scenario 2: Window Upgrade ROI

| Scenario | Indoor | Outdoor | Single Pane | Double Pane | Triple Pane |
|----------|--------|---------|-------------|-------------|-------------|
| Winter | 20°C | 0°C | 12.0°C (⚠️ 85% RH) | 15.4°C (⚠️ 72% RH) | 17.8°C (✅ 58% RH) |
| Cold Day | 20°C | 5°C | 14.5°C (⚠️ 78% RH) | 16.7°C (⚠️ 65% RH) | 18.5°C (✅ 55% RH) |
| Mild Day | 20°C | 10°C | 16.5°C (⚠️ 68% RH) | 17.8°C (✅ 58% RH) | 19.0°C (✅ 52% RH) |

### Passive Window Detection (v3.3.0+)

Detects open windows even when your heating or AC is off. Combines temperature drop speed, humidity changes, and indoor-outdoor temperature difference to tell the difference between a natural cooldown and an open window. Adjusts for your window type and is stricter in winter.

**How it differs from active detection:**

| Mode | When It Works | How It Detects |
|------|---------------|----------------|
| Active | Only when heating/cooling is running | Rapid temperature drop while HVAC is active |
| Passive | Anytime, even when HVAC is off | Temperature drop speed + humidity + outdoor differential |

### Window Detection Mode Per Zone (v3.3.0+)

Choose how each zone detects open windows. Configured via **Options Flow → Zone Configuration**.

| Mode | Behavior |
|------|----------|
| Active | Only detects when heating/cooling is running (original behavior) |
| Passive | Detects anytime, including when HVAC is off |
| Auto | Picks the best method automatically — uses active when HVAC is running, passive when it's off |

**Sensitivity presets (per zone):**

| Sensitivity | Min Readings | Temp Rate Threshold | Best For |
|-------------|-------------|---------------------|----------|
| Low | 4 readings | 0.4°C/min | Reducing false alarms in drafty rooms |
| Medium | 3 readings | 0.25°C/min | Most rooms (default) |
| High | 2 readings | 0.15°C/min | Rooms where you want fast detection |

### Window Detection Events (v3.3.0+)

HA events fire when a window is detected or cleared — useful for building your own automations:

| Event | When |
|-------|------|
| `tado_ce_window_predicted` | Window open detected |
| `tado_ce_window_predicted_cleared` | Detection cleared |

The Window Predicted sensor also tracks when the last detection happened, how many times today, and which detection mode was used. Daily count resets at midnight.

### Smoother Detection (v3.3.0+)

The Window Predicted sensor no longer flickers on/off rapidly. It waits for several stable readings before clearing a detection (3 readings on Low sensitivity, 2 on Medium, 1 on High).

---

## 🔄 Heating Cycle Detection

**Available:** v2.0.0+ | **Requirement:** Zones with heatingPower data | **Always Enabled**

Identifies complete heating cycles (heating ON → target reached → heating OFF) for accurate thermal analysis.

- Automatically detects complete heating cycles
- Minimum cycle: 10 minutes, maximum: 4 hours
- No configuration needed

**Monitor cycle health** via `sensor.{zone}_thermal_inertia` attributes:
- `cycle_count`: Total cycles analyzed
- `timeout_count`: Cycles that timed out
- Success rate >90% = heating system working well

---

## ⚡ Enhanced Controls

**Available:** v1.0.0+ | **Requirement:** None | **Always Enabled**

Improved responsiveness and convenience features for climate control.

### Features

#### 1. Immediate Refresh

Dashboard updates immediately after climate control actions. Configurable debounce delay (default: 15s, range: 1–60s).

#### 2. Boost & Smart Boost

| Button | Friendly Name | Description |
|--------|--------------|-------------|
| `button.{zone}_boost` | Boost | Quick boost: 25°C for 30 min (replicates Tado app feature) |
| `button.{zone}_smart_boost` | Smart Boost | Intelligent duration based on thermal analytics |

> ⬆ Boost replicates the Tado app's boost feature. HA official doesn't expose this.
> Smart Boost is CE exclusive — calculates optimal duration from thermal data.

#### 3. Climate Timer Service

```yaml
# Timer mode — boost for specific duration
service: tado_ce.set_climate_timer
target:
  entity_id: climate.living_room
data:
  temperature: 22
  time_period: 60

# Overlay mode (v2.3.0+) — until next schedule change
service: tado_ce.set_climate_timer
target:
  entity_id: climate.living_room
data:
  temperature: 22
  overlay: next_time_block

# Overlay mode — indefinite
service: tado_ce.set_climate_timer
target:
  entity_id: climate.living_room
data:
  temperature: 22
  overlay: manual
```

> v2.3.0: `time_period` is optional when `overlay` is specified. Supported: `next_time_block`, `manual`. Both Heating and AC zones.

#### 4. Enhanced Hot Water Timer

Control hot water with AUTO/HEAT/OFF modes. Timer duration configurable (1–1440 min, default: 60).

```yaml
service: tado_ce.set_water_heater_timer
target:
  entity_id: water_heater.hot_water
data:
  time_period: 60
```

#### 5. Temperature Offset

Calibrate device temperature readings (range: -10°C to +10°C).

```yaml
service: tado_ce.set_climate_temperature_offset
target:
  entity_id: climate.bedroom
data:
  offset: -0.5
```

Enable "Temperature Offset" in Configure to add `offset_celsius` attribute to climate entities.

#### 6. Climate Group Support (v2.2.3+)

Target climate groups with Tado CE custom services. Groups defined in `configuration.yaml` are automatically expanded.

```yaml
# Define group
group:
  tado_group:
    name: Tado TVR
    entities:
      - climate.bedroom
      - climate.living_room

# Use with Tado CE services
service: tado_ce.set_climate_timer
data:
  entity_id: group.tado_group
  temperature: 22
  time_period: "01:30:00"

# Resume schedule for all zones
service: tado_ce.resume_schedule
data:
  entity_id: group.tado_group
```

Supported services: `set_climate_timer`, `set_water_heater_timer`, `resume_schedule`.

#### 7. Open Window Services (v3.1.0+)

Three services for open window management, each serving a different purpose:

| Service | Purpose | When to Use |
|---------|---------|-------------|
| `tado_ce.activate_open_window` | Confirm Tado's own detection | Auto-Assist replacement — Tado has already detected an open window |
| `tado_ce.deactivate_open_window` | Cancel open window mode | Resume normal heating after window is closed |
| `tado_ce.set_open_window_mode` | Trigger from external sensors | Zigbee/Z-Wave contact sensors — no Tado detection needed |

**Set Open Window Mode** is the most useful for automations. It sets the zone to frost protection (5°C) with a timer:

```yaml
# Basic — uses zone's Open Window Detection timeout, or 15 min default
service: tado_ce.set_open_window_mode
target:
  entity_id: climate.bedroom

# Custom duration (seconds)
service: tado_ce.set_open_window_mode
target:
  entity_id: climate.bedroom
data:
  duration: 1800  # 30 minutes

# Indefinite — stays until manually resumed (v3.2.1+)
service: tado_ce.set_open_window_mode
target:
  entity_id: climate.bedroom
data:
  duration: 0
```

**Duration priority:** user-provided `duration` > zone's `openWindowDetection.timeoutInSeconds` > 15 min default.

**Automation example — contact sensor triggers open window mode:**

```yaml
automation:
  - alias: "Open Window — Bedroom"
    trigger:
      - platform: state
        entity_id: binary_sensor.bedroom_window_contact
        to: "on"
    action:
      - service: tado_ce.set_open_window_mode
        target:
          entity_id: climate.bedroom
        data:
          duration: 0  # indefinite until window closes

  - alias: "Close Window — Bedroom"
    trigger:
      - platform: state
        entity_id: binary_sensor.bedroom_window_contact
        to: "off"
    action:
      - service: tado_ce.deactivate_open_window
        target:
          entity_id: climate.bedroom
```

#### 8. Restore Previous State (v3.3.0+)

Puts a zone back to whatever it was doing before the last change. Works with heating, AC, and hot water.

State is saved automatically before any overlay action (timers, temperature changes, open window mode, preheat). If nothing was saved, it falls back to resuming the schedule. Saved state survives HA restarts and clears when you arrive home.

```yaml
# Restore a single zone
service: tado_ce.restore_previous_state
target:
  entity_id: climate.bedroom

# Restore multiple zones
service: tado_ce.restore_previous_state
target:
  entity_id:
    - climate.bedroom
    - climate.living_room
```

**Pairs well with open window mode:**

```yaml
automation:
  - alias: "Close Window — Restore State"
    trigger:
      - platform: state
        entity_id: binary_sensor.bedroom_window_contact
        to: "off"
    action:
      - service: tado_ce.restore_previous_state
        target:
          entity_id: climate.bedroom
```

---

## 🌉 Bridge API Integration

**Available:** v3.2.0+ | **Requirement:** Tado Internet Bridge with serial + auth key | **Opt-in Configuration**

Direct communication with your Tado Internet Bridge for boiler flow temperature monitoring and control. Independent from the cloud API — errors never affect main polling.

### Overview

The Bridge API uses the serial number and auth key printed on the bottom of your Internet Bridge to authenticate directly with `my.tado.com/api/v2/homeByBridge/{serial}/`. This is separate from the OAuth-based cloud API used for zone data.

### Entities

| Entity | Friendly Name | Type | Description |
|--------|--------------|------|-------------|
| `binary_sensor.tado_ce_{home_id}_bridge_connected` | Bridge Connected | Binary Sensor | Whether the Internet Bridge is reachable |
| `sensor.tado_ce_{home_id}_boiler_wiring_state` | Boiler Wiring State | Sensor | Bridge installation status (Ready / Installing / Failed) |
| `sensor.tado_ce_{home_id}_boiler_output_temperature` | Boiler Output Temperature | Sensor | Real-time boiler output temperature (°C) |
| `number.tado_ce_{home_id}_boiler_max_output_temperature` | Boiler Max Output Temperature | Number | Control max flow temperature (25–80°C, 0.5°C step) |

### Bridge Connected Sensor (v3.3.0+)

The Bridge Connected binary sensor shows whether your Internet Bridge is reachable. It tolerates brief hiccups — the bridge is only marked as disconnected after 3 consecutive failures, so a single timeout won't trigger a false alarm.

**Attributes:**

| Attribute | Description |
|-----------|-------------|
| `response_time` | Last successful response time |
| `failure_count` | Consecutive failure count |
| `last_successful_connection` | Timestamp of last successful connection |

### Wiring State Attributes

The Boiler Wiring State sensor includes extra state attributes from the Bridge API response:

| Attribute | Description |
|-----------|-------------|
| `bridge_connected` | Whether the bridge is online |
| `hot_water_zone_present` | Whether hot water zone is detected |
| `device_type` | Device wired to boiler (e.g. RU02) |
| `device_serial` | Serial number of the wired device |
| `therm_interface_type` | Connection type (OPENTHERM, eBUS, relay) |
| `device_connected` | Whether the wired device is connected |

### Configuration

1. Go to **Settings → Devices & Services → Tado CE → Configure → Global Settings → Flow Temperature Control**
2. Enable the **Internet Bridge** toggle
3. Enter your **Bridge Serial Number** (starts with `IB`, printed on the bottom of your Internet Bridge)
4. Enter your **Bridge Auth Key** (also printed on the bottom)
5. Save — credentials are validated automatically against the Bridge API

Turning off the Internet Bridge toggle automatically cleans up all bridge-related entities. V2 bridges (`GW` serial) aren't supported by the Bridge API.

### How It Works

- Bridge data is fetched during each coordinator update cycle alongside cloud API data
- Bridge API errors are isolated — they never affect cloud data or trigger reauth
- The `boiler.outputTemperature.celsius` field in the wiring state response provides real-time boiler output temperature
- Max output temperature control PUTs to `boilerMaxOutputTemperature` endpoint

### Bridge API vs Cloud API Boiler Sensors

| Sensor | Source | Requires |
|--------|--------|----------|
| Boiler Flow Temp | Cloud API (`activityDataPoints.boilerFlowTemperature`) | OpenTherm-connected boiler |
| Boiler Output Temperature | Bridge API (`boiler.outputTemperature.celsius`) | Bridge credentials |
| Boiler Max Output Temperature | Bridge API (`boilerMaxOutputTemperature`) | Bridge credentials |

Both can coexist — they read from different data sources.

### Usage Scenarios

#### Scenario 1: Monitor Boiler Output Temperature

```yaml
type: entities
entities:
  - entity: sensor.tado_ce_{home_id}_boiler_output_temperature
    name: "Boiler Output Temp"
  - entity: sensor.tado_ce_{home_id}_boiler_wiring_state
    name: "Bridge Status"
  - entity: number.tado_ce_{home_id}_boiler_max_output_temperature
    name: "Max Flow Temp"
```

#### Scenario 2: Weather-Compensated Flow Temperature

```yaml
automation:
  - alias: "Lower Flow Temp When Mild"
    trigger:
      - platform: numeric_state
        entity_id: sensor.tado_ce_hub_outside_temp
        above: 12
        for:
          hours: 2
    action:
      - service: number.set_value
        target:
          entity_id: number.tado_ce_{home_id}_boiler_max_output_temperature
        data:
          value: 45

  - alias: "Raise Flow Temp When Cold"
    trigger:
      - platform: numeric_state
        entity_id: sensor.tado_ce_hub_outside_temp
        below: 2
        for:
          hours: 1
    action:
      - service: number.set_value
        target:
          entity_id: number.tado_ce_{home_id}_boiler_max_output_temperature
        data:
          value: 65
```

---

## 🌡️ Weather Compensation

**Available:** v3.3.0+ | **Requirement:** Bridge API configured OR cloud outdoor temperature | **Opt-in Configuration**

Automatically adjusts your boiler's flow temperature based on outdoor temperature, so your heating runs more efficiently in mild weather and ramps up when it's cold.

### Overview

Weather compensation uses a heating curve to map outdoor temperature to a target boiler flow temperature. When it's mild outside, the boiler runs at a lower flow temperature (saving energy). When it's cold, the flow temperature increases to maintain comfort.

The engine runs every coordinator update cycle. A 10-minute hold between adjustments prevents oscillation, and outdoor temperature is smoothed (EMA or rolling average) to avoid reacting to brief fluctuations.

### Heating System Presets

| Preset | Max Flow Temp | Description |
|--------|---------------|-------------|
| Radiators Standard | 65°C | Traditional radiators |
| Radiators Low Temp | 55°C | Modern low-temperature radiators |
| Underfloor | 45°C | Underfloor heating systems |
| Custom | User-defined | Full control over all parameters |

Presets automatically calculate the slope from your min/max flow and design/shutoff temperatures, so the heating curve spans the full outdoor range without flat zones. Custom preset gives you full manual control over the slope.

### Configuration

1. Go to **Settings → Tado CE → Configure → Global Settings → Flow Temperature Control**
2. Enable the **Internet Bridge** toggle (or use cloud outdoor temperature)
3. Enable **Weather Compensation**
4. Select a **Heating System Preset** (or choose Custom for full control)
5. Save — the engine starts adjusting on the next update cycle

**Custom parameters (when preset = Custom):**

| Parameter | Default | Range | Description |
|-----------|---------|-------|-------------|
| Slope | 1.5 | 0.1–3.0 | Heating curve steepness |
| Design Outdoor Temp | -5°C | -30 to 10°C | Coldest expected outdoor temperature |
| Max Flow Temp | 65°C | 25–80°C | Maximum boiler flow temperature |
| Min Flow Temp | 25°C | 20–50°C | Minimum boiler flow temperature |
| Shutoff Temp | 18°C | 5–25°C | Outdoor temp above which heating stops |
| Smoothing Method | EMA | EMA / Rolling Avg | How outdoor temperature is smoothed |
| Smoothing Window | 60 min | 15–240 min | Smoothing time window |
| Room Compensation | Off | On/Off | Adjust flow temp based on room temperature |
| Room Compensation Factor | 3.0 | 1.0–5.0 | How strongly room temp affects flow temp |
| Step Size | 1.0°C | 0.5–5.0°C | Minimum change between adjustments |
| Hysteresis | 1.0°C | 0.5–5.0°C | Deadband to prevent oscillation |

### Sensors

| Entity | Name | Description |
|--------|------|-------------|
| `sensor.tado_ce_hub_ce_wc_target_flow_temp` | WC Target Flow Temp | Calculated target flow temperature |
| `sensor.tado_ce_hub_ce_wc_status` | WC Status | Engine status: active / paused / disabled |

**WC Target Flow Temp attributes:**

| Attribute | Description |
|-----------|-------------|
| `outdoor_temperature` | Smoothed outdoor temperature |
| `outdoor_temperature_raw` | Raw outdoor temperature reading |
| `heating_system_preset` | Active preset name |
| `room_compensation_offset` | Room feedback adjustment (°C) |
| `smoothing_method` | EMA or rolling_avg |
| `smoothing_window` | Smoothing window in minutes |

### How the Heating Curve Works

```
Target Flow Temp = Max Flow Temp - Slope × (Outdoor Temp - Design Outdoor Temp)
```

For presets, the slope is automatically calculated:
```
Auto Slope = (Max Flow - Min Flow) / (Shutoff Temp - Design Outdoor Temp)
```

This ensures the curve reaches exactly `min_flow_temp` at the shutoff temperature — no flat zones where outdoor changes have no effect.

Example with Radiators Standard (max 65°C, min 25°C, design -5°C, shutoff 18°C → auto-slope 1.74):
- Outdoor -5°C → Flow 65°C (full power)
- Outdoor 5°C → Flow 47.6°C
- Outdoor 10°C → Flow 38.9°C
- Outdoor 18°C+ → Heating off (shutoff)

### Usage Scenarios

#### Scenario 1: Standard Radiator Setup

Select "Radiators Standard" preset. The default curve works well for most homes with traditional radiators. Monitor `wc_target_flow_temp` for a few days to verify the curve matches your comfort needs.

#### Scenario 2: Underfloor Heating

Select "Underfloor" preset. The gentler slope (0.8) and lower max flow temp (45°C) protect UFH systems from overheating. If your floors feel cold in very cold weather, increase the slope slightly using Custom mode.

#### Scenario 3: Fine-Tuning with Room Compensation

Enable Room Compensation to let the engine adjust flow temperature based on actual room temperatures. If rooms are consistently too warm, the engine reduces flow temp. If rooms are cold, it increases. The compensation factor controls how aggressively it responds.

#### Scenario 4: Dashboard Card

```yaml
type: entities
entities:
  - entity: sensor.tado_ce_hub_ce_wc_target_flow_temp
    name: "Target Flow Temp"
  - entity: sensor.tado_ce_hub_ce_wc_status
    name: "WC Status"
  - entity: number.tado_ce_{home_id}_boiler_max_output_temperature
    name: "Current Max Flow Temp"
```

---

## 🔧 Optional Features

**Available:** Various versions | **Requirement:** Varies | **Opt-in Configuration**

### Schedule Calendar

Shows heating schedules as calendar events. Enable in Configure → "Schedule Calendar".

| Entity | Friendly Name |
|--------|--------------|
| `calendar.{zone}` | Schedule |

### Boiler Flow Temperature

Monitors OpenTherm boiler flow temperature. Auto-detected if available.

| Entity | Friendly Name |
|--------|--------------|
| `sensor.tado_ce_boiler_flow_temperature` | Boiler Flow Temp |

### Device Tracking

Tracks mobile device presence (home/away). Enable "Mobile Device Tracking" in Configure.

| Entity | Friendly Name |
|--------|--------------|
| `device_tracker.tado_ce_{device_name}` | {device_name} |

API usage: 1 call per full sync (every 6h). Enable "Sync Mobile Frequently" for every-poll updates.

### Home State Sync & Presence Mode

Syncs home/away presence state. Enable "Home/Away State Sync" in Configure.

| Entity | Friendly Name | Description |
|--------|--------------|-------------|
| `select.tado_ce_presence_mode` | Presence Mode | Control: auto / home / away |
| `binary_sensor.tado_ce_home` | Home | Read-only home/away status |

### Overlay Mode (v2.0.2)

Controls how long manual temperature changes last.

| Entity | Friendly Name |
|--------|--------------|
| `select.tado_ce_overlay_mode` | Overlay Mode |
| `select.tado_ce_overlay_timer_duration` | Overlay Timer |

**Options:**

| Option | Description |
|--------|-------------|
| Tado Mode | Follows per-device "Manual Control" settings in Tado app (default) |
| Next Time Block | Override lasts until next scheduled change |
| Manual | Infinite override until manually changed |

### Understanding Geofencing vs Presence Mode

Geofencing is a Tado account-level setting configured in the Tado app, not in this integration.

| Scenario | "Auto" Mode Behavior |
|----------|---------------------|
| Geofencing **enabled** | Tado auto-switches Home/Away based on mobile locations |
| Geofencing **disabled** | Stays in current state — no automatic switching |

**How Presence Lock Works:**
- **"home" or "away"**: Creates a presence lock that overrides geofencing
- **"auto"**: Deletes the presence lock. If geofencing enabled, Tado resumes automatic control. If disabled, state stays as-is.

### Multi-Language (v3.0.0)

Config flow and options UI available in 7 languages:

| Language | Code |
|----------|------|
| English | `en` |
| German | `de` |
| Spanish | `es` |
| French | `fr` |
| Italian | `it` |
| Dutch | `nl` |
| Portuguese | `pt` |

HA automatically selects the language based on your system locale. No configuration needed.

**Common Misconception (geofencing OFF):**
```
Home → Away → Auto = Back to Home?  ❌ WRONG
Home → Away → Auto = Stays Away     ✅ CORRECT
```

When geofencing is disabled, "Auto" just removes the lock — it doesn't change state. Use "Home"/"Away" directly, or use HA automations with other presence detection.

---

## 🏠 Per-Zone Configuration

**Available:** v2.1.0+ | **Requirement:** None | **Opt-in via Zone Features Toggle**

Customize settings for each individual zone instead of using global defaults.

### Configuration Entities

**Heating Zones:**

| Entity | Friendly Name | Type | Description |
|--------|--------------|------|-------------|
| `select.{zone}_heating_type` | Heat Emitter | Select | Radiator or Underfloor Heating |
| `number.{zone}_ufh_buffer` | UFH Buffer | Number | Extra preheat buffer for UFH (0–60 min) |

**All Climate Zones:**

| Entity | Friendly Name | Type | Description |
|--------|--------------|------|-------------|
| `switch.{zone}_adaptive_preheat` | Adaptive Preheat | Switch | Enable adaptive preheat |
| `select.{zone}_smart_comfort_mode` | Smart Comfort | Select | Weather compensation level |
| `select.{zone}_window_type` | Window Type | Select | Window insulation for mold risk |
| `select.{zone}_overlay_mode` | Overlay Mode | Select | How temperature changes behave |
| `select.{zone}_overlay_timer_duration` | Overlay Timer | Select | Timer duration |
| `number.{zone}_min_temp` | Min Temp | Number | Minimum temperature (5–25°C) |
| `number.{zone}_max_temp` | Max Temp | Number | Maximum temperature (15–30°C) |
| `number.{zone}_temp_offset` | Temp Offset | Number | Temperature calibration (-3.0 to +3.0°C) |
| `number.{zone}_surface_temp_offset` | Surface Offset | Number | Surface temp calibration |

### Zone Overlay Mode Options

| Option | Behavior |
|--------|----------|
| Tado Mode | Inherit from global setting (default) |
| Next Time Block | Revert at next schedule change |
| Timer | Revert after timer duration |
| Manual | Stay until manually changed |

### Use Cases

```yaml
# Living room: Manual control (stays until changed)
select.living_room_overlay_mode: Manual

# Bedroom: Timer (reverts after 30 min)
select.bedroom_overlay_mode: Timer

# Mark bathroom as UFH with 15 min buffer
select.bathroom_heating_type: Underfloor Heating
number.bathroom_ufh_buffer: 15

# Child's room: Limit max temp
number.childs_room_max_temp: 22
```

### Migration from Global Settings

When upgrading to v2.1.0:
- `ufh_zones` → per-zone `heating_type = UFH`
- `ufh_buffer_minutes` → per-zone `ufh_buffer`
- `adaptive_preheat_zones` → per-zone `adaptive_preheat = ON`
- Global `overlay_mode` remains as default; zones inherit unless overridden

---

## 🎛️ Zone Features Toggles

**Available:** v2.1.0+ | **Requirement:** None | **Options Flow Configuration**

Control which entity types are created, reducing clutter for users who don't need all features.

### Available Toggles

| Toggle | Entities Controlled | Default (New) | Default (Upgrade) |
|--------|---------------------|---------------|-------------------|
| Zone Diagnostics | Battery, connection, heating power sensors | OFF | ON |
| Device Controls | Child lock, early start switches | OFF | ON |
| Boost Buttons | Boost, Smart Boost buttons | OFF | ON |
| Environment Sensors | Mold risk, comfort level, condensation risk | OFF | ON |
| Thermal Analytics | Thermal inertia, heating rate, preheat time | OFF | ON |
| Zone Configuration | Per-zone config entities | OFF | ON |

**New installs:** All toggles OFF for minimal setup. Enable what you need.
**Upgrades:** All toggles ON to preserve existing entities and automations.

Configure: Settings → Devices & Services → Tado CE → Configure → "Zone Features" section.

---

## 🎯 Configuration Scenarios

### Scenario 1: Small Apartment (1–2 rooms, 100 calls/day)

```yaml
Adaptive Polling: Enabled (default)
Smart Comfort: Disabled (save quota)
Weather Sensors: Disabled
Mold Risk: Enabled (important for small spaces)
Window Type: Double Pane

Expected: ~80–120 calls/day, polling ~15–20 min
```

### Scenario 2: Large House (5+ rooms, 1000+ calls/day)

```yaml
Adaptive Polling: Enabled
Smart Comfort: Enabled
Weather Sensors: Enabled
Mold Risk: Enabled
Window Type: Per-zone (mix of double/triple)
Outdoor Temp: Weather integration

Expected: ~300–800 calls/day, polling ~5–10 min
```

### Scenario 3: Energy Optimization Focus

```yaml
Smart Comfort: Enabled (for preheat advisor)
Thermal Analytics: Monitor closely
Key sensors: _preheat_time, _historical_deviation, _avg_heating_rate
Automations: Preheat before schedule, reduce when warmer than usual
```

### Scenario 4: Mold Prevention Focus

```yaml
Mold Risk: Enabled
Window Type: Accurate setting per zone
Outdoor Temp: Required
Key sensors: _mold_risk, surface_temperature (attribute), _comfort_level
Automations: Alert when mold risk >70%, auto-ventilation
```

### Scenario 5: Low Quota (100 calls/day) Detailed

```yaml
Day Start: 7, Night Start: 23
Custom Day Interval: 30 min
Custom Night Interval: 120 min
Weather: Off, Mobile Tracking: Off, Home State Sync: Off
Smart Comfort: Off, Schedule Calendar: Off

Day (16h): 32 syncs × 2 = 64 calls
Night (8h): 4 syncs × 2 = 8 calls
Full sync (6h): 4 × 2 = 8 calls
Total: ~80 calls/day (20% buffer)
```

### Scenario 6: High Quota (1000+) All Features

```yaml
Custom Intervals: Empty (use adaptive)
All features: On
Sync Mobile Frequently: On
Smart Comfort Mode: Moderate
History Days: 30

Expected: ~576 calls/day at ~5 min intervals
```

### Scenario 7: Mixed Zone Types (Heating + AC)

| Feature | Heating Zones | AC Zones |
|---------|---------------|----------|
| Thermal Analytics | ✅ Available | ❌ No heatingPower data |
| Smart Comfort | ✅ Heating patterns | ✅ Cooling patterns |
| Condensation Risk | ❌ N/A | ✅ AC-specific |
| Weather Impact | Moderate | High (solar gain) |

### Scenario 8: OpenTherm Boiler

Auto-detected via `sensor.tado_ce_boiler_flow_temperature`. Monitor flow temp alongside zone heating rates to detect boiler issues.

```yaml
automation:
  - alias: "Alert: Low Boiler Flow Temperature"
    trigger:
      - platform: numeric_state
        entity_id: sensor.tado_ce_boiler_flow_temperature
        below: 45
        for:
          minutes: 30
    condition:
      - condition: template
        value_template: "{{ states('climate.living_room') == 'heat' }}"
    action:
      - service: notify.mobile_app
        data:
          title: "⚠️ Low Boiler Flow Temperature"
          message: "Flow temp: {{ states('sensor.tado_ce_boiler_flow_temperature') }}°C"
```

---

## 💡 Actionable Insights

**Available:** v2.2.0+ | **Requirement:** None | **Always Enabled**

Intelligent, context-aware recommendations across all zones for comfort, mold prevention, and energy optimization.

### v3.0.0 Insight Enhancements

#### Smarter Summary
Home insights sensor now produces action-based summaries instead of generic counts:
- Before: `"3 actions needed across 2 zones"`
- After: `"Replace batteries: Guest, Lounge — Mold risk: Bedroom"`

Top-priority insight drives summary text. Actions grouped by type across zones.

#### Correlation / Deduplication
Related insights within a zone are automatically merged into a single action:
- Mold risk + humidity trend + condensation → single "humidity problem" action
- Configurable correlation groups in `CORRELATION_GROUPS`
- Cross-zone insights excluded from correlation

#### History & Trending
Persistent tracking of insight appearance/disappearance (survives HA restarts):
- Stored in `.storage/tado_ce/insight_history_{home_id}.json`
- Duration-aware messages appended to recommendations ("persisting for 3 days")
- Weekly digest attribute with most frequent insight types and 7-day rolling window
- Auto-pruning of entries older than 30 days

#### Priority Escalation
Auto-escalation rules based on persistence duration:
- Battery low > 7 days → high, > 14 days → critical
- Mold risk > 3 days → high, > 7 days → critical
- Monotonic escalation (never downgrades). Capped at CRITICAL.
- Configurable via `ESCALATION_RULES`

#### Health Score
Numeric 0-100 score reflecting overall home health:
- Based on active insight count and severity
- Exposed as `insight_health_score` attribute on Home Insights sensor
- 100 = no active insights, lower = more/worse issues

### Home Insights Sensor

`sensor.tado_ce_home_insights` — hub-level aggregation:

- **State**: Total number of active insights (integer)
- **Attributes**: `critical_count`, `high_count`, `medium_count`, `low_count`, `top_priority`, `top_recommendation`, `zones_with_issues`, `cross_zone_insights`

### Zone Insights Sensor

`sensor.{zone}_insights` — per-zone insights:

- **State**: Number of active insights for this zone
- **Attributes**: `top_priority`, `top_recommendation`, `insight_types`, `recommendations`
- **Dynamic icon**: Changes based on highest priority

### Insight Types

**Zone-level insights:**

| Insight | Priority | Trigger |
|---------|----------|---------|
| Mold Risk | Critical/High/Medium | Dew point margin < 7°C |
| Comfort Level | High/Medium | Temperature outside 18–24°C |
| Window Predicted | High | Rapid temperature drop |
| Battery Low | Critical/Low | Device battery LOW/CRITICAL |
| Device Offline | High | Connection lost |
| Preheat Timing | Medium | Preheat time exceeds schedule gap |
| Schedule Deviation | Medium | Consistent deviation from schedule |
| Heating Anomaly | High | Power ≥80% but temp change <0.5°C for 60+ min |
| Condensation Risk | Medium/High/Critical | AC zone condensation detected |
| Overlay Duration | Medium/High | Manual override active too long |
| Frequent Override | Medium | Multiple manual overrides recently |
| Heating Off Cold Room | High | Heating off but room below comfort |
| Early Start Disabled | Low | Preheat feature not enabled |
| Poor Thermal Efficiency | Medium/High | Below expected threshold |
| Schedule Gap | Medium | Large gap leaving zone unheated |
| Boiler Flow Anomaly | High | Flow temp outside expected range |
| Humidity Trend | Medium | Sustained rising humidity |
| Device Limitation | Low | Hardware limitations affecting features |

**Home-level insights (in `sensor.tado_ce_home_insights` only):**

| Insight | Priority | Trigger |
|---------|----------|---------|
| Cross-Zone Mold | High | 3+ zones with Medium+ mold risk |
| Cross-Zone Windows | High | 2+ zones with window predicted open |
| Cross-Zone Condensation | High | Multiple zones with condensation |
| Cross-Zone Efficiency | Medium | Significant efficiency variation |
| Temperature Imbalance | Medium | Large temp difference between zones |
| Humidity Imbalance | Medium | Large humidity difference |
| Away Heating Active | High | Away mode but heating still active |
| Home All Off | Low | Everyone home but all heating off |
| Solar Gain | Low | Solar gain detected |
| Solar AC Load | Medium | Strong solar increasing AC load |
| Frost Risk | Critical | Outdoor temp near freezing |
| Heating Season Advisory | Low | Seasonal guidance |
| Geofencing Offline | High | Mobile device for geofencing offline |
| API Usage Spike | Medium/High | Unusual API call rate spike |
| API Quota Planning | Medium/High | Projected exhaustion <6h before reset |
| Weather Impact | Medium | Outdoor temp >5°C below 7-day average |

### Recommendation Attributes

These sensors include a `recommendation` attribute with actionable guidance:
- `sensor.{zone}_mold_risk` — specific humidity/temperature changes needed
- `sensor.{zone}_comfort_level` — context-aware (considers if HVAC is active)
- `sensor.{zone}_condensation_risk` — AC-specific prevention
- `sensor.{zone}_battery` — battery replacement reminders
- `sensor.{zone}_connection` — device troubleshooting
- `sensor.tado_ce_api_status` — quota management suggestions

Empty string when no action needed.

### Usage Scenarios

#### Scenario 1: Dashboard Overview

```yaml
type: entities
entities:
  - entity: sensor.tado_ce_home_insights
    name: "Active Insights"
  - type: attribute
    entity: sensor.tado_ce_home_insights
    attribute: top_priority
    name: "Top Priority"
  - type: attribute
    entity: sensor.tado_ce_home_insights
    attribute: top_recommendation
    name: "Top Action"
```

#### Scenario 2: Alert on Critical Insights

```yaml
automation:
  - alias: "Alert: Critical Home Insight"
    trigger:
      - platform: state
        entity_id: sensor.tado_ce_home_insights
        attribute: top_priority
        to: "critical"
    action:
      - service: notify.mobile_app
        data:
          title: "🚨 Critical Home Issue"
          message: >
            {{ state_attr('sensor.tado_ce_home_insights', 'top_recommendation') }}
```

---

## 🔧 Troubleshooting

### Thermal Analytics Shows "Unknown"

**Causes:** Zone doesn't report heatingPower, not enough cycles (need 3–5), heating always on (no complete cycles).

**Solution:** Check `sensor.{zone}_heating` exists, wait 2–3 days, verify `cycle_count` attribute > 0, ensure heating turns on/off regularly.

### Inaccurate Thermal Analytics Values

**Causes:** Low confidence (<50%), recent room changes, external heat sources.

**Solution:** Wait for confidence >80% (5–10 heating cycles). Avoid room changes during data collection.

### Heating Efficiency >200%

**Normal!** Means free heat from solar gain, cooking, appliances, or people. No action needed — consider reducing target to save energy.

### Mold Risk Always Shows "Room Temperature"

**Causes:** Outdoor temperature entity not configured, sensor unavailable, window type not set.

**Solution:** Configure outdoor temp entity, verify sensor works, set window type. Check `temperature_source` attribute — should show "surface_estimation".

### Adaptive Polling Too Slow

**Causes:** Low remaining quota, custom interval too high, many zones consuming quota.

**Solution:** Check `sensor.tado_ce_api_usage`, disable custom interval for pure adaptive, disable optional features, check if Test Mode is enabled.

### Smart Comfort Sensors Not Appearing

**Causes:** Not enabled, integration not restarted, not enough historical data.

**Solution:** Enable "Smart Comfort Analytics" in Configure, restart HA, wait 24–48 hours.

### API Rate Limit Exceeded

**Causes:** Too many manual actions, polling too short, too many optional features, multiple HA instances.

**Solution:** Increase polling intervals, disable optional features (Weather, Mobile Tracking), wait for reset (`sensor.tado_ce_api_reset`), ensure single HA instance.

### Schedule Calendar Not Showing Events

**Causes:** Not enabled, no schedules in Tado app, calendar integration not loaded.

**Solution:** Enable "Schedule Calendar", restart HA, verify schedules exist in Tado app.

### Boiler Flow Temperature Not Detected

**Causes:** Boiler not OpenTherm-compatible, Tado system doesn't support OpenTherm.

**Solution:** Verify boiler supports OpenTherm, check Tado app for flow temp data.

### Bridge API Sensors Showing "Unknown"

**Causes:** Wrong data path (fixed in v3.2.2), bridge credentials invalid, bridge offline.

**Solution:** Update to v3.2.2+, verify credentials in Configure → Bridge Configuration, check bridge is online. Enable debug logging:

```yaml
logger:
  default: info
  logs:
    custom_components.tado_ce.bridge_api: debug
    custom_components.tado_ce.sensor_bridge: debug
    custom_components.tado_ce.coordinator: debug
```

Look for `Bridge API full response` in logs to verify the API is returning data.

### Device Tracking Not Working

**Causes:** Not enabled, geo-tracking not enabled in Tado app, no mobile devices registered.

**Solution:** Enable "Mobile Device Tracking", enable geo-tracking in Tado app, wait for next full sync (6h).

### Temperature Offset Not Applying

**Causes:** Offset attribute not enabled, value out of range, service call failed.

**Solution:** Enable "Temperature Offset" in Configure, verify offset within range (-10 to +10°C), check HA logs.

### Preheat Advisor Shows 0 Minutes

**Causes:** Already at target, heating rate unknown, next schedule temp same as current.

**Solution:** Check current vs next schedule temp, wait for thermal analytics data (3–5 cycles), verify `_avg_heating_rate` has valid value.

---

## 📚 Related Documentation

- [ENTITIES.md](ENTITIES.md) — Complete entity reference (86 entities)
- [README.md](README.md) — Installation and setup
- [API_REFERENCE.md](API_REFERENCE.md) — Technical API details
- [ROADMAP.md](ROADMAP.md) — Planned features and ideas

---

**Last Updated:** v3.3.0 (2026-03-21)
