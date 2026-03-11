# Roadmap

Planned features and improvements for Tado CE.

For completed features, see [CHANGELOG.md](CHANGELOG.md).

---

## v3.1.0

**Open Window Detection:**
- **Activate/Deactivate Open Window Services** ([#172](https://github.com/hiall-fyi/tado_ce/issues/172) - @driagi) — Instantly trigger open window mode from external window sensors (e.g., Zigbee contact sensors) instead of waiting 15+ minutes for Tado's built-in detection. Also enables free Auto-Assist replacement via HA automations.
- **Window Predicted Sensitivity** ([#135](https://github.com/hiall-fyi/tado_ce/issues/135) - @ChrisMarriott38) — Per-zone Low/Medium/High sensitivity dropdown to tune false positive rate for the Window Predicted sensor.

**API Management:**
- **Smarter Full Sync** ([#141](https://github.com/hiall-fyi/tado_ce/issues/141) - @Xavinooo) — Full data sync only on HA restart/reload instead of every 6 hours. Saves API calls, especially for 100-call quota users.

**Hub Controls:**
- **Quota Reserve Toggle** — Enable/disable quota reserve protection without entering Config Options.
- **Test Mode Toggle** — Enable/disable test mode without entering Config Options. Both can be controlled via automations.

---

## Up Next

**Local API / HomeKit Hybrid** ([Discussion #29](https://github.com/hiall-fyi/tado_ce/discussions/29))

The goal: reduce or eliminate dependency on Tado's cloud API for day-to-day control.

1. **Phase 1** — Internal preparation to support multiple data sources (cloud, local, HomeKit) side by side. No user-facing changes.
2. **Phase 2** — Entity migration to the new architecture. No user-facing changes.
3. **Phase 3** — HomeKit local control for temperature, humidity, and HVAC mode. Cloud API still used for data not available locally (heating %, battery, schedules, hot water). Proof of concept already working — see [Discussion #29](https://github.com/hiall-fyi/tado_ce/discussions/29).
4. **Long-term** — Investigating fully local control via the 868MHz protocol between Bridge and TRVs. Requires specialized hardware and community help.

Target: Q2 2026

---

## Future Consideration

- **Call Priority System** — Different polling frequencies for different data types (e.g., zone states every 10 min, weather every 30 min).
- **Indoor Air Quality Score** ([#64](https://github.com/hiall-fyi/tado_ce/issues/64)) — Per-zone air quality and comfort visualization similar to the Tado app.
- **Cross-Zone Window Detection** ([#135](https://github.com/hiall-fyi/tado_ce/issues/135) - @ChrisMarriott38) — Check if any zone is heating before triggering window predicted, reducing false positives in passive zones.
- **External Temperature Sensor Override** ([#106](https://github.com/hiall-fyi/tado_ce/issues/106), [#143](https://github.com/hiall-fyi/tado_ce/issues/143) - @BirbByte) — Use any HA temperature sensor (HomeKit, Zigbee, etc.) per zone for faster updates.
- **HACS Default Repository** — Apply for inclusion in the HACS default repository list.
- **Max Flow Temperature Control** ([#15](https://github.com/hiall-fyi/tado_ce/issues/15)) — Requires OpenTherm support.
- **Temperature Update Delay Investigation** ([#124](https://github.com/hiall-fyi/tado_ce/issues/124) - @hapklaar) — Investigating reports of slow climate card updates. Awaiting debug logs.
