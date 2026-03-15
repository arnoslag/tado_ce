# Roadmap

Planned features and improvements for Tado CE.

For completed features, see [CHANGELOG.md](CHANGELOG.md).

---

## Up Next

**Flow Temperature Control** ([#187](https://github.com/hiall-fyi/tado_ce/issues/187), [#15](https://github.com/hiall-fyi/tado_ce/issues/15))

Control your boiler's max flow temperature directly from Home Assistant. Initially targeting V3/V3+ users with OpenTherm or eBUS connections via the Bridge API. Tado X support (Flow Temperature Optimization) will follow as part of broader Tado X compatibility work.

---

**Local API / HomeKit Hybrid** ([Discussion #29](https://github.com/hiall-fyi/tado_ce/discussions/29))

The goal: reduce or eliminate dependency on Tado's cloud API for day-to-day control.

1. **Phase 1** — Internal preparation to support multiple data sources (cloud, local, HomeKit) side by side. No user-facing changes.
2. **Phase 2** — Entity migration to the new architecture. No user-facing changes.
3. **Phase 3** — HomeKit local control for temperature, humidity, and HVAC mode. Cloud API still used for data not available locally (heating %, battery, schedules, hot water). Proof of concept already working — see [Discussion #29](https://github.com/hiall-fyi/tado_ce/discussions/29).
4. **Long-term** — Investigating fully local control via the 868MHz protocol between Bridge and TRVs. Requires specialized hardware and community help.

Target: Q3 2026

---

## Future Consideration

- **Call Priority System** — Different polling frequencies for different data types (e.g., zone states every 10 min, weather every 30 min).
- **Indoor Air Quality Score** ([#64](https://github.com/hiall-fyi/tado_ce/issues/64)) — Per-zone air quality and comfort visualization similar to the Tado app.
- **HACS Default Repository** — Apply for inclusion in the HACS default repository list.
