# Roadmap

Planned features and improvements for Tado CE.

For completed features, see [CHANGELOG.md](CHANGELOG.md).

---

## Up Next

**HomeKit Local Control — GA Release**

v4.0.0-beta.3 extended HomeKit data to all sensor entities (temperature, humidity, smart comfort, window detection, insights, preheat decisions) and fixed the Auto mode target temperature display. Beta.2 shipped the core architecture (real-time entity updates, direct HomeKit reads, write verification, circuit breaker). Currently in beta testing with community testers. Next steps:

- Monitor beta.3 feedback — sensor charts should now be smooth, Auto mode target temp correct
- Investigate intermittent write flip-back reported by @hapklaar (needs reproduction logs)
- Investigate weather compensation bridge API failure on some setups
- Ship v4.0.0 stable once confidence is high

---

## Future Consideration

- **Exponential Heating Curve** ([#187](https://github.com/hiall-fyi/tado_ce/issues/187) - @driagi)

Non-linear (exponential) heating curve option for weather compensation, using a building thermal sensitivity coefficient (`k` factor). Better models real-world heat loss in well-insulated vs poorly-insulated buildings compared to the current linear approach. Would sit alongside the existing linear presets as an "Expert" option under Custom. Deferred to next heating season for real-world validation.

- **Air Comfort System** ([#64](https://github.com/hiall-fyi/tado_ce/issues/64))

Per-zone indoor air quality monitoring inspired by the Tado app's Air Comfort feature. Two components:

1. **Air Freshness** — Per-zone freshness level (fresh/fair/stale) calculated from window opening history and AC activity. Uses existing open window detection and AC power data — zero extra API calls.
2. **Outdoor Air Quality** — Optional external AQI sensor input via Options Flow (same pattern as external temperature/humidity sensors). Users can connect any HA AQI integration (WAQI, OpenWeatherMap, etc.) without Tado CE calling third-party APIs.

- **Fully Local Control** ([Discussion #29](https://github.com/hiall-fyi/tado_ce/discussions/29)) — Investigating control via the 868MHz protocol between Bridge and TRVs, bypassing both cloud and HomeKit. Requires specialized hardware and community help. Long-term exploration.
- **Call Priority System** — Different polling frequencies for different data types (e.g., zone states every 10 min, weather every 30 min). Partially addressed by HomeKit polling optimization — cloud-only data already fetches less often when HomeKit is connected.
- **Quick Actions** — Home-level quick action system (one-tap heating/AC/hot water control). Lower priority — HA scripts and automations provide equivalent functionality.
- **HACS Default Repository** — Apply for inclusion in the HACS default repository list.
