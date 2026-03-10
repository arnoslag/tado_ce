# Roadmap

Feature requests and planned improvements for Tado CE.

For completed features, see [CHANGELOG.md](CHANGELOG.md).

---

## ✅ Recently Completed

**Multi-Home Support** ([#110](https://github.com/hiall-fyi/tado_ce/issues/110) - @robvol87, [#145](https://github.com/hiall-fyi/tado_ce/issues/145) - @Blankf):

Multiple Tado accounts/homes in a single HA instance. Completed incrementally from v1.7.0 through v2.3.1:

- Per-home data files (`zones_{home_id}.json`, `ratelimit_{home_id}.json`, etc.) — v1.7.0
- Per-home unique_id (`tado_ce_{home_id}`) for config entries — v1.7.0
- Home selection in config flow — v1.3.0
- Per-home ZoneConfigManager and APICallTracker — v2.0.0
- `ConfigEntry.runtime_data` for all per-entry state (no `hass.data[DOMAIN]` flat dict) — v2.0.0+
- Per-entry client instances, coordinator, and cleanup — v2.0.0+
- Full code audit confirmed zero data isolation issues across all 61 source files

**Actionable Insights — Full Feature Set:**

All four planned improvements now implemented:

- Smarter Summary — Action-based home summary replaces generic counts. Top-priority insight drives summary text (e.g., "Replace batteries: Guest, Lounge — Mold risk: Bedroom")
- Insight Correlation / Deduplication — Related insights (mold risk + humidity trend + condensation) merged into single "humidity problem" action per zone. Configurable correlation groups
- Insight History & Trending — Persistent tracking in `.storage/tado_ce/insight_history_{home_id}.json`. Duration-aware messages ("persisting for 3 days"). Weekly digest with most frequent insight types
- Priority Escalation — Auto-escalation rules based on persistence duration (e.g., battery low > 7 days → critical, mold risk > 3 days → high). Monotonic escalation capped at CRITICAL

**Code Quality — Platinum Quality Scale:**

- mypy strict mode — zero errors across 61 source files
- ruff comprehensive linting (`--select=ALL` baseline) — zero errors with 12 rule groups enabled
- Bare `except Exception:` audit — all instances now log errors
- Module-level docstring standardisation — all 61 files
- Unnecessary comment cleanup — 22 comments removed across 12 files

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

**Predictive Preheat — Cooling Rate Awareness** ([Discussion #163](https://github.com/hiall-fyi/tado_ce/discussions/163) - @thefern69):
- Preheat Advisor currently shows "Ready" when `current_temp >= target_temp`, ignoring temperature trend
- Enhancement: estimate cooling rate from recent readings, extrapolate when temperature will cross target, and trigger preheat proactively accounting for thermal inertia
- Building blocks already exist (HeatingCycleCoordinator temperature readings, ThermalAnalyzer second-order analysis)
- Requires: cooling rate estimation step before the "Ready" early-return in `TadoPreheatAdvisorSensor`

**Other:**
- Apply for HACS default repository inclusion
- Max Flow Temperature control (requires OpenTherm, [#15](https://github.com/hiall-fyi/tado_ce/issues/15))
- **Temperature Update Delay Investigation** ([#124](https://github.com/hiall-fyi/tado_ce/issues/124) - @hapklaar) — User reports ~2 hour update intervals and slow climate card updates. Awaiting debug logs.
