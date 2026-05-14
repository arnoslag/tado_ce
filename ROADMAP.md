# Roadmap

Planned features and improvements for Tado CE.

For completed features, see [CHANGELOG.md](CHANGELOG.md).

---

## Up Next

**v4.0.0 GA Release**

v4.0.0-beta.16 is in final testing. Headline features shipped during
the beta cycle: HomeKit local control, Smart Valve Control (Offset
Sync + Valve Target modes), Weather Compensation, multi-home support,
actionable insights, and a redesigned Options Flow. See
[CHANGELOG.md](CHANGELOG.md) for the full release history.

- Monitor beta.16 feedback from the community
- **Target: GA release May 2026** if no blockers surface

## Future Consideration

### Smart Valve Control

- **Automation-Friendly Temperature Override** ([#256](https://github.com/hiall-fyi/tado_ce/issues/256) - @apilone) — A new service that sets a zone's target temperature without triggering SVC back-off. Designed for holiday/calendar automations that override the Tado schedule — currently these are indistinguishable from manual changes, so SVC stops compensating exactly when you need it most. No timeline yet.

- **External Flow Temperature Sensor** ([#254](https://github.com/hiall-fyi/tado_ce/issues/254) - @apilone) — Let Weather Compensation read your boiler's actual flow temperature from any HA sensor entity (e.g. myVaillant, ebusd, OTGW) instead of requiring Tado's own OpenTherm bridge. Same "external sensor" pattern already used for room temperature and humidity — just a new config option pointing at your boiler integration's flow temp sensor. Would work for anyone whose boiler integration exposes flow temperature in HA. No timeline yet — post-GA.

- **Exponential Heating Curve** ([#187](https://github.com/hiall-fyi/tado_ce/issues/187) - @driagi) — Non-linear heating curve for weather compensation, using a building thermal sensitivity coefficient (`k` factor). Better models real-world heat loss in well-insulated vs poorly-insulated buildings compared to the current linear approach. Would sit alongside the existing linear presets as an "Expert" option. Deferred for real-world validation during the next heating season.

- **Air Comfort System** ([#64](https://github.com/hiall-fyi/tado_ce/issues/64)) — Per-zone indoor air quality monitoring inspired by the Tado app's Air Comfort feature. Two components: (1) Air Freshness — per-zone freshness level from window opening history and AC activity, zero extra API calls; (2) Outdoor Air Quality — optional external AQI sensor input via Options Flow, same pattern as external temperature/humidity sensors.

### Infrastructure

- **Local Only Mode** — A toggle that stops all cloud polling after initial setup, running purely off HomeKit bridge data. Technically feasible — the coordinator already skips cloud calls when HomeKit provides live data. Tradeoff: cloud-only data (schedules, battery, heating power, geofencing) would go stale. Could include a daily cloud check for diagnostics.

- **Periodic Full Sync** — Currently `zones_info`, `offsets`, `schedules`, and `ac_capabilities` only refresh on the first poll after restart. A periodic full sync (e.g. every 6 hours) would keep this data fresh without requiring a restart. Low priority — this data rarely changes.

- **HACS Default Repository** — Apply for inclusion in the HACS default repository list.

### Long-Term Exploration

- **Fully Local Control** ([Discussion #29](https://github.com/hiall-fyi/tado_ce/discussions/29)) — Control via the 868MHz protocol between Bridge and TRVs, bypassing both cloud and HomeKit. Requires specialized hardware and community help.
