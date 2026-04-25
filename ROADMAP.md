# Roadmap

Planned features and improvements for Tado CE.

For completed features, see [CHANGELOG.md](CHANGELOG.md).

---

## Up Next

**HomeKit Local Control — GA Release**

v4.0.0-beta.10 is the latest beta — ten releases since beta.1 introduced HomeKit local control. The beta cycle has addressed humidity source accuracy, cleaned up verbose logging, removed Test Mode, fixed multiple settings and data persistence issues, improved HomeKit write verification, added Smart Valve Control for TRV offset compensation using external sensors, and hardened SVC for edge cases (all-OFF schedules, crash recovery, device offset warnings). Currently in final testing. Next steps:
- Monitor beta.10 feedback, particularly Smart Valve Control with real-world setups
- Target: GA release in May 2026 if no blockers found

## Future Consideration

### Next Heating Season

- **Exponential Heating Curve** ([#187](https://github.com/hiall-fyi/tado_ce/issues/187) - @driagi) — Non-linear heating curve for weather compensation, using a building thermal sensitivity coefficient (`k` factor). Better models real-world heat loss in well-insulated vs poorly-insulated buildings compared to the current linear approach. Would sit alongside the existing linear presets as an "Expert" option. Deferred for real-world validation during the next heating season.

- **Air Comfort System** ([#64](https://github.com/hiall-fyi/tado_ce/issues/64)) — Per-zone indoor air quality monitoring inspired by the Tado app's Air Comfort feature. Two components: (1) Air Freshness — per-zone freshness level from window opening history and AC activity, zero extra API calls; (2) Outdoor Air Quality — optional external AQI sensor input via Options Flow, same pattern as external temperature/humidity sensors.

### Infrastructure

- **Local Only Mode** — A toggle that stops all cloud polling after initial setup, running purely off HomeKit bridge data. Technically feasible — the coordinator already skips cloud calls when HomeKit provides live data. Tradeoff: cloud-only data (schedules, battery, heating power, geofencing) would go stale. Could include a daily cloud check for diagnostics.

- **Periodic Full Sync** — Currently `zones_info`, `offsets`, `schedules`, and `ac_capabilities` only refresh on the first poll after restart. A periodic full sync (e.g. every 6 hours) would keep this data fresh without requiring a restart. Low priority — this data rarely changes.

- **HACS Default Repository** — Apply for inclusion in the HACS default repository list.

### Long-Term Exploration

- **Fully Local Control** ([Discussion #29](https://github.com/hiall-fyi/tado_ce/discussions/29)) — Control via the 868MHz protocol between Bridge and TRVs, bypassing both cloud and HomeKit. Requires specialized hardware and community help.
