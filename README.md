# Tado CE - Custom Integration for Home Assistant

<div align="center">

<!-- Platform Badges -->
![Home Assistant](https://img.shields.io/badge/Home%20Assistant-2025.11%2B-blue?style=for-the-badge&logo=home-assistant) ![Python](https://img.shields.io/badge/Python-3.13%2B-blue?style=for-the-badge&logo=python&logoColor=white) ![Tado](https://img.shields.io/badge/Tado-V2%2FV3%2FV3%2B-orange?style=for-the-badge) ![HACS](https://img.shields.io/badge/HACS-Custom-orange.svg?style=for-the-badge)

<!-- Status Badges -->
![Version](https://img.shields.io/badge/Version-4.0.0--beta.10-purple?style=for-the-badge) ![License](https://img.shields.io/badge/License-AGPL--3.0-blue?style=for-the-badge) ![Maintained](https://img.shields.io/badge/Maintained-Yes-green.svg?style=for-the-badge) ![Coverage](https://img.shields.io/badge/Coverage-98%25-brightgreen?style=for-the-badge)

<!-- Community Badges -->
![GitHub stars](https://img.shields.io/github/stars/hiall-fyi/tado_ce?style=for-the-badge&logo=github) ![GitHub forks](https://img.shields.io/github/forks/hiall-fyi/tado_ce?style=for-the-badge&logo=github) ![GitHub issues](https://img.shields.io/github/issues/hiall-fyi/tado_ce?style=for-the-badge&logo=github) ![GitHub Release Date](https://img.shields.io/github/release-date/hiall-fyi/tado_ce?style=for-the-badge&logo=github)

<!-- Support -->
[![Buy Me A Coffee](https://img.shields.io/badge/Support-Buy%20Me%20A%20Coffee-FFDD00?style=for-the-badge&logo=buy-me-a-coffee&logoColor=black)](https://buymeacoffee.com/hiallfyi)

**⭐ Community-driven Tado integration with local control, smart analytics, and features you won't find anywhere else.**

**Built by the community, for the community — join thousands of users taking control of their smart climate.**

[Quick Start](#-quick-start) • [Features](#-features) • [Configuration](#-configuration-options) • [Troubleshooting](#-troubleshooting) • [Discussions](https://github.com/hiall-fyi/tado_ce/discussions)

</div>

---

## Why Tado CE?

Tado CE turns your Tado system into a truly local smart climate platform. By pairing your Tado Internet Bridge via HomeKit, temperature and humidity updates arrive in real time over your local network — no cloud round-trip needed. Your heating keeps working even when Tado's servers are down, and local commands don't count against your API quota.

In real-world testing with 9 heating zones, HomeKit local control reduced daily API usage by over 80% (from ~394 calls/day to under 80) while delivering fresher data — temperature changes appear in about 1 second instead of waiting up to 5 minutes for the next cloud poll. During a simulated cloud outage, all 9 zones continued reporting live data with zero interruption.

If Tado ever drops the API limit to 100 calls/day, HomeKit users barely notice — temperatures stay real-time and you've got plenty of API budget left for cloud-only data like schedules and geofencing. Without HomeKit, 100 calls means your dashboard shows temperatures that could be 15–20 minutes old.

Beyond local control, Tado CE provides actionable insights that tell you what's wrong and what to do about it, thermal analytics that learn how your rooms heat, preheat advisors that prevent temperature drops before they happen, mold risk monitoring, multi-home support, and enhanced controls the official integration doesn't offer.

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

- **Local Control (HomeKit)** — Pair your v3+ bridge via HomeKit for local temperature reads and writes over your LAN. Your heating keeps working when Tado's cloud is down, local commands don't count against your API quota, and temperature updates arrive in ~1 second instead of waiting for the next cloud poll. Everything falls back to cloud automatically if the local connection drops.
- **Multi-Home Support** — Multiple Tado accounts/homes in a single HA instance with full data isolation
- **Actionable Insights** — Per-zone and home-wide intelligent recommendations with priority escalation, correlation/deduplication, history tracking, health score, and 21+ insight types across 7 categories
- **API Management** — Real-time rate limit tracking, reset time detection, call history, sync monitoring
- **Smart Polling** — Adaptive real-time polling based on remaining API quota, custom intervals, monitoring sensors
- **API Write Optimization** — Smart debounce, redundant call skipping, device operation queuing, write coalescing, and schedule resume guard to reduce unnecessary API calls
- **Environment Monitoring** — Mold risk assessment, comfort level tracking, condensation risk (AC)
- **Smart Comfort** — Historical patterns, preheat advisor with cooling rate prediction, schedule sensors, AI recommendations
- **Thermal Analytics** — Heating rate analysis, preheat estimates, thermal inertia, confidence scoring
- **Weather Compensation** — Automatic boiler flow temperature adjustment based on outdoor temperature with preset heating curves
- **Enhanced Controls** — Smart boost, hot water timer (min 1 min), immediate refresh, temperature offset, restore previous state
- **Smart Valve Control** — Per-zone proportional TRV offset using external sensors. Automatically adjusts the TRV target so the room reaches your desired temperature, writing via HomeKit (zero API cost) with cloud fallback. Backs off on manual changes, resumes on next schedule block.
- **Per-Zone Configuration** — Individual overlay modes, temperature limits, UFH settings, Smart Valve Control per zone
- **Zone Features Toggles** — Control which entity types are created for a minimal or full setup
- **Multi-Language** — Config flow and options UI in 7 languages (English, German, Spanish, French, Italian, Dutch, Portuguese)
- **Optional Features** — Schedule calendar, boiler flow temperature, device tracking, home state sync

**Every feature requested, tested, and refined by real users like you.**

See [FEATURES_GUIDE.md](FEATURES_GUIDE.md) for detailed documentation, configuration instructions, and usage scenarios for all features.

---

## Configuration Options

Access via **Settings > Devices & Services > Tado CE > gear icon**.

Settings are organised into four sections:

- **General Settings** — Feature toggles (Weather, Mobile Tracking, Smart Comfort, Schedule Calendar, Zone Features, Bridge, Weather Compensation, Local Control)
- **Advanced Settings** — Tuning parameters for enabled features only (polling intervals, debounce windows, comfort modes, heating curves, HomeKit cloud sync frequency)
- **Zone Configuration** — Per-zone overlay mode, temperature limits, heating type, external sensors, window detection, preheat mode, Smart Valve Control
- **Reset to Defaults** — Reset settings per feature or everything at once, without losing your Tado account or bridge pairing

See [FEATURES_GUIDE.md](FEATURES_GUIDE.md) for detailed configuration guides and usage scenarios based on your setup (low quota, high quota, mixed zones, OpenTherm boiler, etc.).

**Note**: Changes take effect immediately without restart.

---

## Entities

Quick overview of entities created by Tado CE (88 entity types — see [ENTITIES.md](ENTITIES.md) for full reference):

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

10 services for climate control, hot water timers, open window mode, temperature offsets, and more. All available in **Developer Tools > Services** with full parameter documentation.

See [FEATURES_GUIDE.md](FEATURES_GUIDE.md) for service details and usage examples.

---

## Smart Polling

Tado CE automatically adjusts how often it checks the cloud based on your remaining API quota. Works for any quota tier (100, 1000, 20,000) — no configuration needed. With HomeKit connected, cloud polling drops further since temperature and humidity come locally.

You can override with custom day/night intervals in **Configure > Advanced Settings > Polling & API**.

See [FEATURES_GUIDE.md](FEATURES_GUIDE.md) for polling details, quota tiers, and monitoring sensors.

---

## Supported Devices

| Device | Type | Support | HomeKit Local |
|--------|------|---------|---------------|
| Smart Thermostat V2 | HEATING | Full (community verified) | ❌ (V2 bridge) |
| Smart Thermostat V3/V3+ | HEATING | Full | ✅ |
| Smart Radiator Thermostat (SRT/VA02) | HEATING | Full | ✅ |
| Smart AC Control V3/V3+ | AIR_CONDITIONING | Full | ✅ (temp only) |
| Wireless Temperature Sensor | HEATING | Full | ❌ (not a HomeKit accessory) |
| Internet Bridge V3+ | Infrastructure | N/A | Required for local control |
| **Tado X Series** | Matter/Thread | Not Supported | — |

Tado X devices use Matter over Thread - use the [Home Assistant Matter integration](https://community.home-assistant.io/t/using-tado-smart-thermostat-x-through-matter/736576) instead.

---

## Limitations

See [Known Limitations](FEATURES_GUIDE.md#known-limitations) in the Features Guide.

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
