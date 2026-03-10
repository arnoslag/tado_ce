# Roadmap

Feature requests and planned improvements for Tado CE.

For completed features, see [CHANGELOG.md](CHANGELOG.md).

---

## Up Next

**Local API / HomeKit Hybrid** ([Discussion #29](https://github.com/hiall-fyi/tado_ce/discussions/29)):

Multi-Home prerequisite is complete. The path to HomeKit local control:

1. **Data Source Abstraction Layer (Phase 1)** — Build a `DataSourceRouter` between entities and data sources (Cloud, HomeKit, future Local API/Matter). Cloud-only mode wraps existing data loading with zero behavior change. Pure refactor.
2. **Entity Migration (Phase 2)** — Migrate entities per-file to use the router instead of direct data loader calls. Each file independently tested. Pure refactor — no new features.
3. **HomeKit Local Control (Phase 3)** — Add HomeKit (HAP) as a data source. Local reads/writes for temperature, humidity, HVAC mode. Cloud API for data not available locally (heating %, battery, schedules, hot water). Proof of concept working — see Discussion #29 for details.
4. **Pure Local (Long-term research)** — Investigating 868MHz 6LoWPAN protocol between Bridge and TRVs for 100% local control. Requires specialized RF hardware and community help.

- **Target**: Q2 2026

---

## Future Consideration

**API Management:**
- **Call Priority System** — Configurable weighting for different call types (e.g., zoneStates every 10 min, weather every 30 min). Requires significant coordinator architecture changes. Low priority — current adaptive polling handles most use cases.
- **Event-Driven Full Sync** ([#141](https://github.com/hiall-fyi/tado_ce/issues/141) - @Xavinooo) — Remove 6-hour periodic full sync, make it event-driven (only on HA restart/reload). Zone info, offsets, and AC capabilities rarely change.

**Environment Sensors** ([#64](https://github.com/hiall-fyi/tado_ce/issues/64)):
- **Indoor Air Quality (IAQ)** — Air quality score per zone (requires additional sensors)
- **Air Comfort** — Similar to Tado app's comfort visualization

**Open Window Detection Enhancements** ([#135](https://github.com/hiall-fyi/tado_ce/issues/135) - @ChrisMarriott38):
- **Sensitivity Dropdown** — `select.{zone}_window_predicted_sensitivity` with Low/Medium/High options mapping to preset threshold combinations internally.
- **Cross-Zone Heating Detection** — Check if ANY zone is heating before triggering window predicted. Needs more real-world data; current per-zone approach avoids passive zone false positives.

**Hub Controls Migration:**
- **Quota Reserve Toggle** — Move `quota_reserve_enabled` from Config Options to Hub Controls for runtime toggle without reload.
- **Test Mode Toggle** — Move `test_mode_enabled` from Config Options to Hub Controls for easier debugging.
- **Benefit**: Allows automation control and faster toggling without entering Config Options. Waiting for community feedback.

**Per-Zone External Sensor Override** ([#106](https://github.com/hiall-fyi/tado_ce/issues/106), [#143](https://github.com/hiall-fyi/tado_ce/issues/143) - @BirbByte):
- Allow selecting any HA temperature sensor (HomeKit, Zigbee, etc.) per zone for faster updates. Under consideration.

**HA Official Pattern Alignment:**
- **`MINOR_VERSION` Support** (A16) — Use `MINOR_VERSION` for backwards-compatible schema changes. Add when a breaking config schema change is actually needed.

**Other:**
- Apply for HACS default repository inclusion
- Max Flow Temperature control (requires OpenTherm, [#15](https://github.com/hiall-fyi/tado_ce/issues/15))
- **Temperature Update Delay Investigation** ([#124](https://github.com/hiall-fyi/tado_ce/issues/124) - @hapklaar) — User reports ~2 hour update intervals and slow climate card updates. Awaiting debug logs.
