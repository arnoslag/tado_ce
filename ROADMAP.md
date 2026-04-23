# Roadmap

Planned features and improvements for Tado CE.

For completed features, see [CHANGELOG.md](CHANGELOG.md).

---

## Up Next

**HomeKit Local Control — GA Release**

v4.0.0-beta.9 is the latest beta — nine releases since beta.1 introduced HomeKit local control. The beta cycle has addressed humidity source accuracy, cleaned up verbose logging, removed Test Mode, fixed multiple settings and data persistence issues, improved HomeKit write verification, and added Smart Valve Control for TRV offset compensation using external sensors. Currently in final testing. Next steps:
- Monitor beta.9 feedback
- Target: GA release in May 2026 if no blockers found

## Future Consideration

- **Exponential Heating Curve** ([#187](https://github.com/hiall-fyi/tado_ce/issues/187) - @driagi)

Non-linear (exponential) heating curve option for weather compensation, using a building thermal sensitivity coefficient (`k` factor). Better models real-world heat loss in well-insulated vs poorly-insulated buildings compared to the current linear approach. Would sit alongside the existing linear presets as an "Expert" option under Custom. Deferred to next heating season for real-world validation.

- **Air Comfort System** ([#64](https://github.com/hiall-fyi/tado_ce/issues/64))

Per-zone indoor air quality monitoring inspired by the Tado app's Air Comfort feature. Two components:

1. **Air Freshness** — Per-zone freshness level (fresh/fair/stale) calculated from window opening history and AC activity. Uses existing open window detection and AC power data — zero extra API calls.
2. **Outdoor Air Quality** — Optional external AQI sensor input via Options Flow (same pattern as external temperature/humidity sensors). Users can connect any HA AQI integration (WAQI, OpenWeatherMap, etc.) without Tado CE calling third-party APIs.

- **Local Only Mode** — A "Local Only" toggle that stops all cloud polling after initial setup, running purely off HomeKit bridge data. Technically feasible — the coordinator already skips cloud calls when HomeKit provides live data, and cloud sync failures are handled gracefully. Tradeoff: cloud-only data (schedules, battery, heating power, geofencing) would go stale. Could include a daily cloud check for diagnostics. Requires HomeKit to be enabled and connected.

- ~~**Smart Valve Control**~~ ✅ **Shipped in v4.0.0-beta.9** — Per-zone proportional TRV offset using external sensors. See [FEATURES_GUIDE.md](FEATURES_GUIDE.md#-smart-valve-control) for details.

- **Fully Local Control** ([Discussion #29](https://github.com/hiall-fyi/tado_ce/discussions/29)) — Investigating control via the 868MHz protocol between Bridge and TRVs, bypassing both cloud and HomeKit. Requires specialized hardware and community help. Long-term exploration.
- **Call Priority System** — Different polling frequencies for different data types (e.g., zone states every 10 min, weather every 30 min). Largely addressed by HomeKit polling optimization — cloud-only data already fetches less often when HomeKit is connected, and weather has its own reduced frequency. Remaining gap: per-endpoint configurable intervals for non-HomeKit users.
- **Periodic Full Sync** — Currently `zones_info`, `offsets`, `schedules`, and `ac_capabilities` only refresh on the first poll after restart. A periodic full sync (e.g. every 6 hours) would keep this data fresh without requiring a restart. Low priority — this data rarely changes, and most users on HomeKit have even less need for frequent cloud syncs. Revisit after 4.0.0 GA once HomeKit adoption is clearer.
- **Quick Actions** — Home-level quick action system (one-tap heating/AC/hot water control). Lower priority — HA scripts and automations provide equivalent functionality.
- **HACS Default Repository** — Apply for inclusion in the HACS default repository list.
