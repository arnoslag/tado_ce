# Tado CE — API Reference

How Tado CE interacts with the Tado API, including call types, data flow, and optimization tips.

---

## API Call Types

Tado CE tracks all API calls with a code system:

| Code | Type | Description | Configurable |
|------|------|-------------|--------------|
| 1 | zoneStates | Current state of all zones (temperature, humidity, heating status, overlay) | No (required) |
| 2 | weather | Outdoor weather data (temperature, solar intensity, weather state) | Yes |
| 3 | zones | Zone configuration (names, types, devices) | No (required) |
| 4 | mobileDevices | Geofencing device locations | Yes |
| 5 | overlay | Manual overrides (set/delete temperature or mode changes) | N/A (action-triggered) |
| 6 | presenceLock | Home/Away mode lock status | N/A (action-triggered) |
| 7 | homeState | Home presence state (home/away) | Yes |
| 8 | capabilities | AC zone capabilities (modes, fan levels, swing options) | Auto-cached |

### Required Calls (Cannot Be Disabled)

| Code | Type | Why Required |
|------|------|--------------|
| 1 | zoneStates | Core data — temperature, humidity, heating status for all zones |
| 3 | zones | Zone configuration, needed at startup to identify devices |

### Configurable Calls

Toggle in Settings → Devices & Services → Tado CE → Configure:

| Code | Type | Option | API Savings |
|------|------|--------|-------------|
| 2 | weather | Enable Weather Sensors | 1 call per sync |
| 4 | mobileDevices | Enable Mobile Device Tracking | 1 call per full sync |
| 7 | homeState | Enable Home State Sync | 1 call per quick sync |

### Auto-Cached Calls

| Code | Type | Behavior |
|------|------|----------|
| 8 | capabilities | Fetched per AC zone and cached locally. Refreshed automatically when a zone is added or removed, or when a controller re-pair / hardware swap changes a zone's device serial or firmware. The "Refresh AC Capabilities" button forces a refresh for the rare same-serial same-firmware re-pair. The climate entity rebuilds its mode list and fan mapping on refresh without an HA restart |

### Action-Triggered Calls

| Code | Type | When Triggered |
|------|------|----------------|
| 5 | overlay | When you change temperature/mode via Tado CE services |
| 6 | presenceLock | When you change Presence Mode (Home/Away/Auto) |

Not polling calls — only happen when you take an action.

### Write Optimization (v3.4.0+)

Action-triggered calls (Code 5) are automatically optimized to reduce unnecessary API usage:

| Optimization | What It Does | Default |
|-------------|--------------|---------|
| Smart Actions Debounce | Waits for slider to stop moving before sending the final value | 3s window |
| Action Guard | Skips the call if requested state matches current state | Always on |
| Device Sync Queue | Queues device operations (child lock, early start) sequentially | 1s delay |
| Write Coalescing | Batches multiple rapid writes into a single coordinator refresh | 2s window |
| Resume Guard | Skips `resume_schedule` if zone has no active overlay | Always on |

These optimizations are transparent — they don't change what you see in the UI, only how efficiently calls reach the Tado API. See [FEATURES_GUIDE.md](FEATURES_GUIDE.md#-api-write-optimization) for full details.

### Bridge API Calls (v3.2.0+)

Bridge API calls are separate from the cloud API — they use a different endpoint (`my.tado.com/api/v2/homeByBridge/{serial}/`) and don't count toward your daily API quota. Bridge data is fetched during each coordinator update cycle alongside cloud data, but errors are isolated and never affect cloud polling.

| Call | Description | When |
|------|-------------|------|
| Wiring state | Bridge installation status, boiler output temp | Every sync (if bridge configured) |
| Max output temp | Read/write boiler max flow temperature | Every sync + on user action |

Bridge calls require the serial number and auth key from your Internet Bridge (configured under **Settings → Tado CE → Configure → General Settings → Hardware Connections → Internet Bridge**).

---

## What is "Overlay"?

An **overlay** is Tado's term for a manual override on top of the schedule.

| Type | Behavior |
|------|----------|
| MANUAL | Stays until you cancel it |
| TIMER | Reverts after X minutes |
| TADO_MODE | Reverts at next schedule change (Next Block) |

**How overlay relates to API calls:**
- Code 5 tracks **write** operations only (`set_zone_overlay`, `delete_zone_overlay`)
- Overlay **status** (whether a zone has an override) comes from Code 1 (zoneStates), not a separate call
- Climate changes via HomeKit or other systems don't trigger Code 5 through Tado CE

---

## Sync Types

Two sync types balance data freshness with API efficiency:

### Quick Sync

Runs frequently (based on polling interval):
- zoneStates (Code 1) — always
- homeState (Code 7) — if enabled

Typical: 1–2 calls per quick sync.

### Full Sync

Runs on HA restart (v3.1.0+, previously every 6 hours). Everything from quick sync plus:
- zones (Code 3)
- weather (Code 2) — if enabled
- mobileDevices (Code 4) — if enabled

Typical: 2–5 calls per full sync (depending on options).

---

## Call History

API calls are recorded in `sensor.tado_ce_call_history` attributes:

```yaml
call_history:
  - "2026-03-08 10:30:15 - Code 1 (zoneStates)"
  - "2026-03-08 10:30:16 - Code 7 (homeState)"
```

**Viewing:** Developer Tools → States → search `sensor.tado_ce_call_history` → expand Attributes.

**Retention:** Configure via Options → Polling & API → "API History Retention" (default: 14 days, 0 = forever).

---

## Rate Limit Headers

Tado CE reads rate limit information from API response headers:

| Header | Description |
|--------|-------------|
| `X-RateLimit-Limit` | Your daily limit (100/1000/20000) |
| `X-RateLimit-Remaining` | Calls remaining today |
| `X-RateLimit-Reset` | Reset time (often inaccurate from Tado) |

### Reset Time Detection

Tado CE uses multiple strategies since the API's `X-RateLimit-Reset` header often points to midnight UTC (incorrect):

1. **Detected Reset** — when remaining increases significantly, record the time
2. **HA History** — check sensor history for usage drops
3. **Extrapolation** — calculate from usage rate and call history
4. **First Call Mode** — fallback using historical first-call times

---

## Optimizing API Usage

### For HomeKit Users

- Disable Weather Sensors (unless using Smart Comfort)
- Disable Mobile Device Tracking (unless using device trackers)
- Disable Home State Sync (unless using Tado geofencing)

Climate changes via HomeKit don't trigger Code 5 (overlay) calls through Tado CE.

### For 100 Calls/Day Limit

With all optional syncs disabled:
- Quick sync: 1 call (zoneStates only)
- Full sync: 2 calls (zoneStates + zones)

Maximum headroom for manual actions and automations.

### For 1000 Calls/Day Limit

Enable features as needed:
- Weather Sensors and Home State Sync are low-cost, and each refreshes on its own floor (weather every 30 min, presence every 5 min by default — configurable in Advanced Settings → Polling & API) rather than on the zone-state cadence
- The adaptive polling floor is a flat 5 min, so a healthy-quota moment can't drop you to 1-min polling
- Typical usage with default settings: ~90–180 calls/day

### For Auto-Assist Users (20,000 calls/day)

Enable all features without concern. The adaptive floor is a flat 5 min, the same as every other plan: a bigger quota doesn't buy a faster automatic cadence because zone temperature doesn't change any faster. With weather and presence on their own slower floors, you stay well under 20,000. If you want faster presence or mobile refresh, dial the intervals down in Advanced Settings → Polling & API — on a 20,000-call plan, 1 minute costs around 1,440 calls per device per day and gives tighter geofencing latency for automations. If you want faster zone polling than 5 min, set a custom interval and it's honoured as-is.

### How often each data type refreshes

The polling interval governs zone temperature and mode only. Slow-changing data refreshes on its own floor so a fast cadence doesn't burn quota re-reading it: weather every 30 min (configurable 15–120 min), presence and mobile-device locations every 5 min (configurable 1–60 min), device firmware/battery/connection hourly (paid) or every 4 h (free). These floors are set in Advanced Settings → Polling & API. When HomeKit local control is connected, the configured floors widen further to your Cloud Data Refresh dial. Full table in [FEATURES_GUIDE → Smart Polling](FEATURES_GUIDE.md#-smart-polling).

---

## Data Storage

Since v4.0.0, Tado CE stores all runtime data through Home Assistant's built-in Store system (under `/config/.storage/`). You don't need to interact with these files directly — HA manages serialisation, atomic writes, and shutdown flush.

### Store Categories

Two categories of Store, both keyed per home (multi-home isolation):

| Category | Save Mode | Examples |
|----------|-----------|----------|
| API data | Immediate (write-through on every API response) | `zones`, `config`, `home_state`, `ratelimit`, `zones_info`, `weather`, `mobile_devices`, `offsets`, `schedules`, `ac_capabilities`, `ac_capabilities_fp` |
| Auxiliary | Debounced (coalesced saves, typically 5–30s) | `zone_config`, `wc_state`, `bridge_health`, `outdoor_temp_history`, `window_detection`, `smart_comfort_cache`, `overlay_mode`, `timer_duration`, `homekit_savings`, `insight_runtime_state` |

### Upgrade Behaviour

- **From v3.5.3**: existing JSON files under `/config/.storage/tado_ce/` are migrated to HA Store on first start of v4.0.0. Old files are renamed (not deleted) so you can roll back.
- **From pre-v3.0.0**: first upgrade to v3.0.0 migrates flat-named files (e.g. `config.json`) to per-home files (e.g. `config_{home_id}.json`). Then the v4.0.0 migration picks those up into Store.
- **Restore-related state** (e.g. `state_restore`, HomeKit pairing data, heating cycle history) is also stored through HA Store, so it survives restarts and upgrades automatically.

---

## Troubleshooting

### High API Usage

1. Check `sensor.tado_ce_call_history` attributes for unexpected calls
2. Disable optional syncs you don't need
3. Increase polling intervals via custom day/night settings

### Missing Data

1. Check if the relevant sync option is enabled
2. Check logs for API errors
3. Verify you haven't hit your rate limit

### Call History Not Recording

1. Ensure API History Retention > 0
2. Check logs for Store save errors
3. Try reloading the integration to re-initialise the Store

---

## Related Documentation

- [ENTITIES.md](ENTITIES.md) — Complete entity reference
- [FEATURES_GUIDE.md](FEATURES_GUIDE.md) — Features, configuration, and usage scenarios
- [README.md](README.md) — Installation and setup
- [ROADMAP.md](ROADMAP.md) — Planned features and ideas

---

**Last Updated:** v4.0.2 (2026-06-07)
