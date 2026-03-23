# Roadmap

Planned features and improvements for Tado CE.

For completed features, see [CHANGELOG.md](CHANGELOG.md).

---

## Up Next

**Local API / HomeKit Hybrid** ([Discussion #29](https://github.com/hiall-fyi/tado_ce/discussions/29))

The goal: reduce or eliminate dependency on Tado's cloud API for day-to-day control.

1. **Phase 1** — Internal preparation to support multiple data sources (cloud, local, HomeKit) side by side. No user-facing changes.
2. **Phase 2** — Entity migration to the new architecture. No user-facing changes.
3. **Phase 3** — HomeKit local control for temperature, humidity, and HVAC mode. Cloud API still used for data not available locally (heating %, battery, schedules, hot water). Proof of concept already working — see [Discussion #29](https://github.com/hiall-fyi/tado_ce/discussions/29).
4. **Long-term** — Investigating fully local control via the 868MHz protocol between Bridge and TRVs. Requires specialized hardware and community help.

Target: Q3 2026

---

## Future Consideration

- **Exponential Heating Curve** ([#187](https://github.com/hiall-fyi/tado_ce/issues/187) - @driagi)

Non-linear (exponential) heating curve option for weather compensation, using a building thermal sensitivity coefficient (`k` factor). Better models real-world heat loss in well-insulated vs poorly-insulated buildings compared to the current linear approach. Would sit alongside the existing linear presets as an "Expert" option under Custom. Deferred to next heating season for real-world validation.

- **Air Comfort System** ([#64](https://github.com/hiall-fyi/tado_ce/issues/64))

Per-zone indoor air quality monitoring inspired by the Tado app's Air Comfort feature. Two components:

1. **Air Freshness** — Per-zone freshness level (fresh/fair/stale) calculated from window opening history and AC activity. Uses existing open window detection and AC power data — zero extra API calls.
2. **Outdoor Air Quality** — Optional external AQI sensor input via Options Flow (same pattern as external temperature/humidity sensors). Users can connect any HA AQI integration (WAQI, OpenWeatherMap, etc.) without Tado CE calling third-party APIs.
- **Call Priority System** — Different polling frequencies for different data types (e.g., zone states every 10 min, weather every 30 min).
- **Quick Actions** — Home-level quick action system (one-tap heating/AC/hot water control). Lower priority — HA scripts and automations provide equivalent functionality.
- **HACS Default Repository** — Apply for inclusion in the HACS default repository list.
