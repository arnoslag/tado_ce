# Tado CE - Custom Integration for Home Assistant

<div align="center">

<!-- Platform Badges -->
![Home Assistant](https://img.shields.io/badge/Home%20Assistant-2025.11%2B-blue?style=for-the-badge&logo=home-assistant) ![Python](https://img.shields.io/badge/Python-3.13%2B-blue?style=for-the-badge&logo=python&logoColor=white) ![Tado](https://img.shields.io/badge/Tado-V2%2FV3%2FV3%2B-orange?style=for-the-badge) ![HACS](https://img.shields.io/badge/HACS-Custom-orange.svg?style=for-the-badge)

<!-- Status Badges -->
![Version](https://img.shields.io/badge/Version-3.5.3-purple?style=for-the-badge) ![License](https://img.shields.io/badge/License-AGPL--3.0-blue?style=for-the-badge) ![Maintained](https://img.shields.io/badge/Maintained-Yes-green.svg?style=for-the-badge) ![Coverage](https://img.shields.io/badge/Coverage-98%25-brightgreen?style=for-the-badge)

<!-- Community Badges -->
![GitHub stars](https://img.shields.io/github/stars/hiall-fyi/tado_ce?style=for-the-badge&logo=github) ![GitHub forks](https://img.shields.io/github/forks/hiall-fyi/tado_ce?style=for-the-badge&logo=github) ![GitHub issues](https://img.shields.io/github/issues/hiall-fyi/tado_ce?style=for-the-badge&logo=github) ![GitHub Release Date](https://img.shields.io/github/release-date/hiall-fyi/tado_ce?style=for-the-badge&logo=github)

<!-- Support -->
[![Buy Me A Coffee](https://img.shields.io/badge/Support-Buy%20Me%20A%20Coffee-FFDD00?style=for-the-badge&logo=buy-me-a-coffee&logoColor=black)](https://buymeacoffee.com/hiallfyi)

**⭐ Community-driven Tado integration with advanced analytics, smart automation, and features you won't find anywhere else.**

**Built by the community, for the community — join thousands of users taking control of their smart climate.**

[Quick Start](#-quick-start) • [Features](#-features) • [Configuration](#-configuration-options) • [Troubleshooting](#-troubleshooting) • [Discussions](https://github.com/hiall-fyi/tado_ce/discussions)

</div>

---

## Why Tado CE?

Tado CE was born from the community's response to Tado's 2025 API rate limits (100-20,000 calls/day depending on plan). The official Home Assistant integration doesn't show your actual API usage, leaving users unaware until they get blocked.

**What started as a community solution has grown into the most advanced Tado integration available** — actionable insights that tell you what's wrong and what to do about it, thermal analytics that learn how your rooms heat, preheat advisors that prevent temperature drops before they happen, mold risk monitoring, multi-home support, and enhanced controls the official integration doesn't offer.

**Join thousands of users who've taken control of their smart climate with Tado CE.**

---

## Quick Start

**Prerequisites:** Home Assistant 2025.11+ and a Tado account with V2/V3/V3+ devices.

### 1. Install via HACS

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=hiall-fyi&repository=tado_ce&category=integration)

1. Click the button above (or add `https://github.com/hiall-fyi/tado_ce` as a custom repository in HACS)
2. Install "Tado CE" from HACS
3. Restart Home Assistant

<details>
<summary>Manual Installation</summary>

```bash
cp -r tado_ce /config/custom_components/
```
</details>

### 2. Add Integration & Authenticate

1. Go to **Settings > Devices & Services > Add Integration**
2. Search for **Tado CE** and click **Submit**
3. Click the authorization link shown, or visit the URL displayed and enter the code
4. Authorize in your browser, then click **Submit**
5. If you have multiple homes, select which one to use

That's it! No SSH required.

### 3. Verify Success

Check **Settings > System > Logs** for:

```
Tado CE: Integration loading...
Tado CE: Polling interval set to 30m (day)
Tado CE full sync SUCCESS
Tado CE: Integration loaded successfully
```

### 4. Configure Options

Click the **gear icon** on the integration card to customize features, polling schedule, and Smart Comfort settings.

---

## Features

Full climate, AC, and hot water control with timer support, geofencing, presence detection, weather data, and more.

**Tado CE Exclusive:**

Tado CE provides comprehensive smart climate control with features developed by and for the community:

- **Multi-Home Support** — Multiple Tado accounts/homes in a single HA instance with full data isolation
- **Actionable Insights** — Per-zone and home-wide intelligent recommendations with priority escalation, correlation/deduplication, history tracking, health score, and 21+ insight types across 7 categories
- **API Management** — Real-time rate limit tracking, reset time detection, call history, test mode, sync monitoring
- **Smart Polling** — Adaptive real-time polling based on remaining API quota, custom intervals, monitoring sensors
- **API Write Optimization** — Smart debounce, redundant call skipping, device operation queuing, write coalescing, and schedule resume guard to reduce unnecessary API calls
- **Environment Monitoring** — Mold risk assessment, comfort level tracking, condensation risk (AC)
- **Smart Comfort** — Historical patterns, preheat advisor with cooling rate prediction, schedule sensors, AI recommendations
- **Thermal Analytics** — Heating rate analysis, preheat estimates, thermal inertia, confidence scoring
- **Weather Compensation** — Automatic boiler flow temperature adjustment based on outdoor temperature with preset heating curves
- **Enhanced Controls** — Smart boost, hot water timer (min 1 min), immediate refresh, temperature offset, restore previous state
- **Per-Zone Configuration** — Individual overlay modes, temperature limits, UFH settings per zone
- **Zone Features Toggles** — Control which entity types are created for a minimal or full setup
- **Multi-Language** — Config flow and options UI in 7 languages (English, German, Spanish, French, Italian, Dutch, Portuguese)
- **Optional Features** — Schedule calendar, boiler flow temperature, device tracking, home state sync

**Every feature requested, tested, and refined by real users like you.**

See [FEATURES_GUIDE.md](FEATURES_GUIDE.md) for detailed documentation, configuration instructions, and usage scenarios for all features.

---

## Configuration Options

Access via **Settings > Devices & Services > Tado CE > gear icon**.

Settings are organised into four sections:

- **General Settings** — Feature toggles (Weather, Mobile Tracking, Smart Comfort, Schedule Calendar, Zone Features, Bridge, Weather Compensation)
- **Advanced Settings** — Tuning parameters for enabled features only (polling intervals, debounce windows, comfort modes, heating curves)
- **Zone Configuration** — Per-zone overlay mode, temperature limits, heating type, external sensors, window detection, preheat mode
- **Reset to Defaults** — Reset settings per feature or everything at once, without losing your Tado account or bridge pairing

See [FEATURES_GUIDE.md](FEATURES_GUIDE.md) for detailed configuration guides and usage scenarios based on your setup (low quota, high quota, mixed zones, OpenTherm boiler, etc.).

**Note**: Changes take effect immediately without restart.

---

## Entities

Quick overview of entities created by Tado CE (86 entity types — see [ENTITIES.md](ENTITIES.md) for full reference):

- **Hub**: API usage/reset/sync sensors, weather sensors, home insights, presence mode, overlay mode, resume all button
- **Per Zone**: Climate control, temperature/humidity, heating power, overlay status, battery, connection
- **Environment**: Mold risk, comfort level, surface temperature, dew point, condensation risk (AC)
- **Actionable Insights**: Per-zone insights + home-wide aggregation with correlation, history tracking, priority escalation, and health score
- **Smart Comfort**: Heating/cooling rates, time-to-target, preheat advisor (with cooling rate prediction), schedule sensors (opt-in)
- **Thermal Analytics**: Thermal inertia, heating rate, preheat time, confidence scoring (heating zones)
- **Hot Water**: Water heater with AUTO/HEAT/OFF modes, timer buttons (min 1 min)
- **Weather Compensation**: Target flow temperature, compensation status (when bridge configured)
- **Switches**: Child lock, early start per zone
- **Zone Features Toggles**: Control which entity types are created for a minimal or full setup

---

## Services

| Service | Description |
|---------|-------------|
| `set_climate_timer` | Set heating/cooling with timer (min 1 min), until next schedule (`overlay: next_time_block`), or indefinitely (`overlay: manual`). `time_period` optional when `overlay` specified |
| `set_water_heater_timer` | Turn on hot water with timer (min 1 min) |
| `resume_schedule` | Delete overlay, return to schedule |
| `set_climate_temperature_offset` | Calibrate device temperature (-10 to +10°C) |
| `get_temperature_offset` | Fetch current offset (Tado CE exclusive) |
| `set_open_window_mode` | Trigger open window mode from external sensors (Zigbee, Z-Wave) with optional duration |
| `restore_previous_state` | Restore zone to whatever it was doing before the last change |
| `identify_device` | Flash device LED |
| `set_away_configuration` | Configure away temperature |
| `add_meter_reading` | Add Energy IQ reading (supports historical dates) |

All services available in **Developer Tools > Services** with full parameter documentation.

---

## Smart Polling

**v2.0.0**: Adaptive Smart Polling with Quota Reserve Protection - real-time interval calculation based on remaining API quota.

### The Design Philosophy

- **Real-time Adaptive**: Calculates interval before each sync based on remaining quota, distributes remaining calls over remaining time, self-healing for any usage pattern
- **Universal**: Works for ANY quota tier (100, 1000, 20000) - no hardcoded tiers or special cases
- **Simple & Predictable**: Easy to understand, transparent through debug logging

### What This Means For You

| Quota | Typical Interval | Daily Utilization |
|-------|------------------|-------------------|
| 100 | ~16 min | ~90 calls (90%) |
| 1000 | ~8 min | ~180 calls |
| 20000 | 5 min (minimum) | Prevents excessive polling |

**Self-healing**: If you make manual API calls, it automatically slows down. End of day uses remaining quota efficiently.

### Safety Mechanisms

- **Minimum interval**: 5 min (prevents excessive polling even with high quotas)
- **Maximum interval**: 120 min (ensures reasonable update frequency)
- **Safety buffer**: 10% reserve for manual operations
- **Low quota protection**: Automatically slows down when quota is low
- **Quota Reserve Protection**: Pauses polling when quota critically low (≤5% or ≤5 calls), reserves quota for manual operations (set temperature, etc.), automatically resumes after API reset

### Optional Features Impact

- **Weather sensors**: Automatically accounts for extra API call
- **Mobile device tracking**: Automatically adjusts for additional calls
- **Smart Comfort**: No impact (local computation only)

### Custom Intervals

Override adaptive polling with fixed intervals in **Settings > Devices & Services > Tado CE > Configure > Polling Schedule**:
- Custom Day Interval (7am-11pm default)
- Custom Night Interval (11pm-7am default)

### Monitoring

New sensors let you monitor polling behavior:
- `sensor.tado_ce_polling_interval` - Current interval with source
- `sensor.tado_ce_next_sync` - Next sync time with countdown
- `sensor.tado_ce_call_history` - API call statistics

---

## Supported Devices

| Device | Type | Support |
|--------|------|---------|
| Smart Thermostat V2 | HEATING | Full (community verified) |
| Smart Thermostat V3/V3+ | HEATING | Full |
| Smart Radiator Thermostat (SRT/VA02) | HEATING | Full |
| Smart AC Control V3/V3+ | AIR_CONDITIONING | Full |
| Wireless Temperature Sensor | HEATING | Full |
| Internet Bridge V3 | Infrastructure | N/A |
| **Tado X Series** | Matter/Thread | Not Supported |

Tado X devices use Matter over Thread - use the [Home Assistant Matter integration](https://community.home-assistant.io/t/using-tado-smart-thermostat-x-through-matter/736576) instead.

---

## Limitations

| Limitation | Description |
|------------|-------------|
| Cloud-Only | All control goes through Tado's cloud servers |
| No GPS | Device trackers only show home/not_home status |
| Rotating Tokens | If token expires, re-authentication required |
| No Schedule Management | Use Tado app for schedule changes |
| No Historical Data | Would consume too many API calls |

---

## Uninstall

1. Go to **Settings > Devices & Services > Tado CE**
2. Click the **three-dot menu** (⋮) and select **Delete**
3. Restart Home Assistant
4. If installed via HACS: open **HACS > Integrations**, find Tado CE, click the three-dot menu and **Remove**
5. If installed manually: delete the `custom_components/tado_ce/` folder
6. Restart Home Assistant again

---

## Troubleshooting

<details>
<summary><strong>Token refresh failed / Re-authentication required</strong></summary>

1. Go to **Settings > Devices & Services > Tado CE**
2. Click **Configure** or look for re-authentication prompt
3. Follow the device authorization flow (link + code)

</details>

<details>
<summary><strong>No device tracker entities</strong></summary>

Device trackers only appear for mobile devices with geo tracking enabled in the Tado app.

</details>

<details>
<summary><strong>Enable debug logging</strong></summary>

Add to `configuration.yaml`:

```yaml
logger:
  default: info
  logs:
    custom_components.tado_ce: debug
```

Restart Home Assistant and check **Settings > System > Logs**.

</details>

For other issues, check logs at **Settings > System > Logs** (filter by "tado_ce") or [open an issue on GitHub](https://github.com/hiall-fyi/tado_ce/issues).

<details>
<summary><strong>Bridge API sensors showing "Unknown"</strong></summary>

Wrong data path (fixed in v3.2.2), bridge credentials invalid, or bridge offline.

**Solution:**
1. Update to **v3.2.2+**
2. Verify credentials in **Configure → Bridge Configuration**
3. Check bridge is online
4. Enable debug logging:

```yaml
logger:
  default: info
  logs:
    custom_components.tado_ce.bridge_api: debug
    custom_components.tado_ce.sensor_bridge: debug
```

Look for `Bridge API full response` in logs to verify the API is returning data.

</details>

---

## Documentation

| Document | Description |
|----------|-------------|
| [FEATURES_GUIDE.md](FEATURES_GUIDE.md) | Complete guide to all features, sensors, configuration, and usage scenarios |
| [ENTITIES.md](ENTITIES.md) | Complete list of all sensors, switches, and controls |
| [API_REFERENCE.md](API_REFERENCE.md) | API call types, optimization tips, troubleshooting |
| [ROADMAP.md](ROADMAP.md) | Planned features, ideas, and known limitations |
| [CREDITS.md](CREDITS.md) | Community contributors and supporters |
| [CHANGELOG.md](CHANGELOG.md) | Version history and release notes |

## External Resources

- [Tado API Rate Limit Announcement](https://community.home-assistant.io/t/tado-rate-limiting-api-calls/928751)
- [Official Tado Integration](https://www.home-assistant.io/integrations/tado/)
- [Tado API Documentation (Community)](https://github.com/kritsel/tado-openapispec-v2)

---

## License

**GNU Affero General Public License v3.0 (AGPL-3.0)**

Free to use, modify, and distribute. Modifications must be open source under AGPL-3.0 with attribution.

**Original Author:** Joe Yiu ([@hiall-fyi](https://github.com/hiall-fyi))

See [LICENSE](LICENSE) for full details.

---

## Contributing

**Join the community that's shaping the future of smart climate control!**

Contributions welcome! Every feature in Tado CE started as a community idea.

1. Fork the repository
2. Create feature branch (`git checkout -b feature/AmazingFeature`)
3. Commit changes (`git commit -m 'Add AmazingFeature'`)
4. Push to branch (`git push origin feature/AmazingFeature`)
5. Open a Pull Request

**Your ideas matter** — check out our [Discussions](https://github.com/hiall-fyi/tado_ce/discussions) to share feature requests, ask questions, or help other users.

---

<div align="center">

[![Star History Chart](https://api.star-history.com/svg?repos=hiall-fyi/tado_ce&type=Date)](https://star-history.com/#hiall-fyi/tado_ce&Date)

</div>

---

<details>
<summary><strong>Disclaimer</strong></summary>

This project is not affiliated with, endorsed by, or connected to tado GmbH or Home Assistant. tado and the tado logo are registered trademarks of tado GmbH. Home Assistant is a trademark of Nabu Casa, Inc.

This integration is provided "as is" without warranty. Use at your own risk.

</details>
