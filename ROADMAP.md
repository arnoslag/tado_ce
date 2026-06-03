# Roadmap

Planned features and improvements for Tado CE.

For completed features, see [CHANGELOG.md](CHANGELOG.md).

---

## Up Next

**v4.1.0 beta cycle.** Foundation work on the persistence layer (re-pair-aware caches), adaptive polling rework (universal tier-aware reserve, round-robin drift refresh), HomeKit pairing reliability (named-exception detection + Repair issue), and State Restore atomicity. Each beta carries one architectural change so regressions are easy to attribute. A beta-tester recruitment thread will be posted in [GitHub Discussions](https://github.com/hiall-fyi/tado_ce/discussions) once the first architectural beta is ready to cut.

All AC writes (target temperature, HVAC mode, swing, fan, timers) currently go through the cloud — see the AC entry below for why HomeKit local control on Smart AC Control V3+ isn't on the active roadmap.

## Future Consideration

### AC

- **Smart AC Control V3+ standalone HomeKit pairing** ([Discussion #271](https://github.com/hiall-fyi/tado_ce/discussions/271) - @MacrosorcH) — Smart AC Control units are autonomous WiFi devices, each with its own 8-digit HomeKit code, paired separately from the Internet Bridge. Tado CE only handles the bridge pairing today, so AC zones use the cloud path for every operation regardless of HomeKit configuration. Adding standalone-unit support means a separate pairing flow per AC unit, multi-pairing controller management, and HAP HeaterCooler service handling on top of the existing Thermostat path (different characteristics, different state machine). Not actively planned — I don't have Smart AC Control hardware to develop or test against, and this class of feature can't be reliably built blind.

### Smart Valve Control

- **Automation-Friendly Temperature Override** ([#256](https://github.com/hiall-fyi/tado_ce/issues/256) - @apilone) — A new service that sets a zone's target temperature without triggering SVC back-off. Designed for holiday/calendar automations that override the Tado schedule — currently these are indistinguishable from manual changes, so SVC stops compensating exactly when you need it most. No timeline yet.

- **External Flow Temperature Sensor** ([#254](https://github.com/hiall-fyi/tado_ce/issues/254) - @apilone) — Let Weather Compensation read your boiler's actual flow temperature from any HA sensor entity (e.g. myVaillant, ebusd, OTGW) instead of requiring Tado's own OpenTherm bridge. Same "external sensor" pattern already used for room temperature and humidity — just a new config option pointing at your boiler integration's flow temp sensor. Would work for anyone whose boiler integration exposes flow temperature in HA. No timeline yet — post-GA.

- **Exponential Heating Curve** ([#187](https://github.com/hiall-fyi/tado_ce/issues/187) - @driagi) — Non-linear heating curve for weather compensation, using a building thermal sensitivity coefficient (`k` factor). Better models real-world heat loss in well-insulated vs poorly-insulated buildings compared to the current linear approach. Would sit alongside the existing linear presets as an "Expert" option. Deferred for real-world validation during the next heating season.

- **Air Comfort System** ([#64](https://github.com/hiall-fyi/tado_ce/issues/64)) — Per-zone indoor air quality monitoring inspired by the Tado app's Air Comfort feature. Two components: (1) Air Freshness — per-zone freshness level from window opening history and AC activity, zero extra API calls; (2) Outdoor Air Quality — optional external AQI sensor input via Options Flow, same pattern as external temperature/humidity sensors.

### Infrastructure

- **Local Only Mode** — A toggle that stops all cloud polling after initial setup, running purely off HomeKit bridge data. Technically feasible — the coordinator already skips cloud calls when HomeKit provides live data. Tradeoff: cloud-only data (schedules, battery, heating power, geofencing) would go stale. Could include a daily cloud check for diagnostics.

- **Periodic Full Sync** — Currently `zones_info`, `offsets`, `schedules`, and `ac_capabilities` only refresh on the first poll after restart. A periodic full sync (e.g. every 6 hours) would keep this data fresh without requiring a restart. Low priority — this data rarely changes.

### v5.0.0 — Legacy cleanup

A spring-clean release that drops backward-compat code accumulated through the v3.x and v4.x cycles. The cleanup is laser-focused on dead surface area, not behaviour change.

**Minimum supported upgrade path: v4.x.x.** Installs running v3.x or earlier should upgrade to v4.x first (any v4 release is fine), then to v5.0.0. v5.0.0 will not auto-migrate v3.x option keys, entity unique_ids, or storage layouts; the migration code that handled those upgrades will be removed. The v3 to v4 migration path stays open through every v4.x release, so there is no rush to upgrade in one jump.

Planned removals:

- **`weather_compensation` legacy option key migration** — pre-v4.0.0-beta.15 stored Smart Comfort presets under `weather_compensation`; the rename to `smart_comfort_mode` ships with a read-time fallback that has lived since beta.15. v5.0.0 replaces the read-time fallback with a one-shot startup migration that copies the value forward and removes the old key, so neither path needs to be carried in steady-state code.
- **`bridge_enrichment.LEGACY_UNIQUE_ID_MAP`** — backward-compat plumbing for an earlier entity unique_id rename. Carrying it costs extra registry lookups on every bridge enrichment cycle.
- **Entity naming drift cleanup** — Two slug points accumulated through the v3.x and v4.x cycles. Neither is user-blocking, but they read as polish gaps when listed side by side. Bundling them gives v5.0.0 a clean entity-naming baseline.
  - `calendar.heating_schedule_schedule` doubled slug — the calendar device is named "Heating Schedule" and the translation_key is `schedule`, so HA derives a doubled slug for fresh v3.0+ installs. v2.3.1-migrated users still see `calendar.lounge` and are unaffected. Either rename the device or the translation_key (the rename is the breaking-change part, and v5 already removes migration code, so this rides along).
  - `quota_reserve_enabled` / `weather_state` `unique_id_suffix` divergence from `translation_key` — internal-only inconsistency, no user-visible effect, but it costs an extra mental jump every time the registry is audited. Align suffix to translation_key.
- **Retire `API_REFERENCE.md`** — The doc currently mixes three things: an internal API call code taxonomy (codes 1-8) that users never see, write-optimisation and sync-type material that already lives in FEATURES_GUIDE, and three genuinely user-useful sections (rate-limit reset detection, per-tier polling guidance, and a short troubleshooting list). Fold the useful sections into FEATURES_GUIDE (Smart Polling already covers the same ground), drop the README and FEATURES_GUIDE links, and delete the file. v5.0.0 because it removes a doc users may have linked to externally; the move gives the redirect a clean version boundary.
- **Climate AC + Heating structural mirror** — `climate_ac.py` and `climate_heating.py` repeat the same setup shape (`async_added_to_hass`, `async_will_remove_from_hass`, zone-config listener wiring, temp-limit refresh) with only default temperature and log-prefix differences. Sharing a base class would save around 120 LOC. Gated on a full hardening-tests pass and a cross-module audit first — the two paths are intentionally cloned today and have absorbed several family-level bugs over the v4.x cycle, so the refactor needs solid scaffolding before it lands.

Anything else flagged in the v5 audit will be added here as it surfaces. No timeline yet.

### Long-Term Exploration

- **Fully Local Control** ([Discussion #29](https://github.com/hiall-fyi/tado_ce/discussions/29)) — Control via the 868MHz protocol between Bridge and TRVs, bypassing both cloud and HomeKit. Requires specialized hardware and community help.
