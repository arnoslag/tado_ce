# Tado CE — API Reference

How Tado CE interacts with the Tado API, including call types, data flow, and optimization tips.

> **Entity ID note:** All examples use **v2.3.1 entity_ids** (preserved for migrated users).
> Fresh v3.0.0 installs get different entity_ids — see [ENTITIES.md](ENTITIES.md) for the mapping.

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
| 8 | capabilities | Fetched once per AC zone, cached locally. Re-fetch via "Refresh AC Capabilities" button (also reloads fan mapping without HA restart) |

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

Bridge calls require the serial number and auth key from your Internet Bridge (configured in Flow Temperature Control settings).

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
- Weather Sensors and Home State Sync are low-cost (1 call each per sync)
- Smart Day/Night polling keeps you well within budget
- Typical usage with default settings: ~90–180 calls/day

### For Auto-Assist Users (20,000 calls/day)

Enable all features without concern. Even with 5-minute polling, ~576 calls/day (well under 20,000).

---

## Data Storage

Tado CE stores data in `/config/.storage/tado_ce/`. All per-home files include `{home_id}` suffix for multi-home isolation.

### Per-Home Data Files

| File | Contents |
|------|----------|
| `config_{home_id}.json` | OAuth tokens, home configuration |
| `ratelimit_{home_id}.json` | Current rate limit status, reset time |
| `zones_{home_id}.json` | Latest zone states snapshot |
| `zones_info_{home_id}.json` | Zone configuration (names, types, devices) |
| `weather_{home_id}.json` | Latest weather data |
| `home_state_{home_id}.json` | Home presence state |
| `mobile_devices_{home_id}.json` | Mobile device locations |
| `offsets_{home_id}.json` | Temperature offset data per zone |
| `ac_capabilities_{home_id}.json` | Cached AC zone capabilities |
| `schedules_{home_id}.json` | Cached heating schedules |
| `api_call_history_{home_id}.json` | Historical API calls for tracking |
| `heating_cycle_history_{home_id}.json` | Heating cycle detection history |
| `zone_config_{home_id}.json` | Per-zone configuration settings |
| `insight_history_{home_id}.json` | Insight appearance/disappearance tracking |
| `state_restore_{home_id}.json` | Captured zone states for restore_previous_state service |

### Legacy Files (pre-v3.0.0)

| File | Status |
|------|--------|
| `config.json` | Migrated to `config_{home_id}.json` |
| `zones.json` | Migrated to `zones_{home_id}.json` |
| `zones_info.json` | Migrated to `zones_info_{home_id}.json` |
| `ratelimit.json` | Migrated to `ratelimit_{home_id}.json` |
| `smart_comfort_cache_{home_id}.json` | Smart comfort temperature history per zone |
| `heating_cycle_history_{home_id}.json` | Still active — used by heating cycle coordinator |

Legacy files without `{home_id}` suffix are auto-migrated on first v3.0.0 startup.

These files persist across restarts and upgrades.

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
2. Check logs for file I/O errors
3. Verify `/config/.storage/tado_ce/` directory exists

---

## Related Documentation

- [ENTITIES.md](ENTITIES.md) — Complete entity reference (86 entities)
- [FEATURES_GUIDE.md](FEATURES_GUIDE.md) — Features, configuration, and usage scenarios
- [README.md](README.md) — Installation and setup
- [ROADMAP.md](ROADMAP.md) — Planned features and ideas

---

**Last Updated:** v3.4.0 (2026-03-23)
