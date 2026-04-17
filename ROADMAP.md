# Roadmap

Planned features and improvements for Tado CE.

For completed features, see [CHANGELOG.md](CHANGELOG.md).

---

## Up Next

**HomeKit Local Control — GA Release**

v4.0.0-beta.5 unified the persistence layer (all data now uses HA Store), added data freshness attributes to temperature and humidity sensors, and documented the HomeKit humidity resolution tradeoff. Beta.4 fixed thermal analytics with HomeKit and added real-time window detection. Currently in final beta testing. Next steps:
- Monitor beta.5 feedback — data storage migration, sensor attributes
- Investigate any remaining issues reported by community testers
- Target: GA release in May 2026 if no blockers found

## Future Consideration

- **Exponential Heating Curve** ([#187](https://github.com/hiall-fyi/tado_ce/issues/187) - @driagi)

Non-linear (exponential) heating curve option for weather compensation, using a building thermal sensitivity coefficient (`k` factor). Better models real-world heat loss in well-insulated vs poorly-insulated buildings compared to the current linear approach. Would sit alongside the existing linear presets as an "Expert" option under Custom. Deferred to next heating season for real-world validation.

- **Air Comfort System** ([#64](https://github.com/hiall-fyi/tado_ce/issues/64))

Per-zone indoor air quality monitoring inspired by the Tado app's Air Comfort feature. Two components:

1. **Air Freshness** — Per-zone freshness level (fresh/fair/stale) calculated from window opening history and AC activity. Uses existing open window detection and AC power data — zero extra API calls.
2. **Outdoor Air Quality** — Optional external AQI sensor input via Options Flow (same pattern as external temperature/humidity sensors). Users can connect any HA AQI integration (WAQI, OpenWeatherMap, etc.) without Tado CE calling third-party APIs.

- **Local Only Mode** ([#227](https://github.com/hiall-fyi/tado_ce/issues/227) - @ChrisMarriott38) — A "Local Only" toggle that stops all cloud polling after initial setup, running purely off HomeKit bridge data. Technically feasible — the coordinator already skips cloud calls when HomeKit provides live data, and cloud sync failures are handled gracefully. Tradeoff: cloud-only data (schedules, battery, heating power, geofencing) would go stale. Could include a daily cloud check for diagnostics. Requires HomeKit to be enabled and connected.
- **Fully Local Control** ([Discussion #29](https://github.com/hiall-fyi/tado_ce/discussions/29)) — Investigating control via the 868MHz protocol between Bridge and TRVs, bypassing both cloud and HomeKit. Requires specialized hardware and community help. Long-term exploration.
- **Call Priority System** — Different polling frequencies for different data types (e.g., zone states every 10 min, weather every 30 min). Partially addressed by HomeKit polling optimization — cloud-only data already fetches less often when HomeKit is connected.
- **Quick Actions** — Home-level quick action system (one-tap heating/AC/hot water control). Lower priority — HA scripts and automations provide equivalent functionality.
- **HACS Default Repository** — Apply for inclusion in the HACS default repository list.
