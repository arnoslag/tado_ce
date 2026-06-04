# Roadmap

Planned features and improvements for Tado CE.

For completed features, see [CHANGELOG.md](CHANGELOG.md).

---

## Up Next

**v4.1.0 beta cycle.** Architectural foundation work first, doc + observability polish second, with one focused theme per beta cut so regressions are easy to attribute. Beta-tester recruitment thread is live at [Discussion #285](https://github.com/hiall-fyi/tado_ce/discussions/285).

| Beta | Theme | Notes |
|---|---|---|
| beta.3 | Adaptive polling rework (universal tier-aware reserve) | Replaces the `100`-call assumption baked into the drift-refresh gate, calendar low-quota check, and polling-interval switch. Bundles two error-handling improvements: a revoked or rotated token will trigger reauth instead of falling through to cache, and a rate-limit response with an explicit retry window will be honoured instead of using the configured polling interval. |
| beta.4 | Drift refresh round-robin | Advance through climate zones one per cycle instead of all every cycle. Same total drift coverage, no burst pattern. Closes [#277](https://github.com/hiall-fyi/tado_ce/issues/277). |
| beta.5 | HomeKit pairing reliability | `aiohomekit` named-exception detection plus a Repair issue when the bridge issues a new HomeKit Setup ID after factory reset. Stops the silent-retry loop. |
| beta.6 | Doc maturity batch | New "Settings configured in the Tado app, not Tado CE" section in FEATURES_GUIDE (covers hysteresis / Acceptance Range / Minimum On/Off Time / Smart Schedule preheating-level / open-window-detection mode and similar Tado-app-only knobs). Plus a `Computed by:` line on every FEATURES_GUIDE feature section to clarify whether the value is computed by Tado server or by Tado CE. |
| beta.7 | Skills detection + Air Comfort prep | Read `/api/homes/{home_id}/skills` once per session to detect Auto-Assist enablement. Surface as a hub diagnostic sensor and use the signal to disambiguate Tado CE's predicted features from Tado server's paid equivalents in docs and Repair issues. Air Comfort ([#64](https://github.com/hiall-fyi/tado_ce/issues/64)) schema design lands alongside. |
| beta.8 | Air Comfort feature ([#64](https://github.com/hiall-fyi/tado_ce/issues/64)) | Per-zone Air Freshness from window-opening history and AC activity (zero extra API calls). Optional Outdoor Air Quality external-sensor input via Options Flow, same pattern as external temperature / humidity. |
| beta.9 | Hysteresis attribute investigation + legacy REST audit | Investigate whether per-zone hysteresis / minimum-on-off settings are readable on the legacy REST surface and surface them as climate attributes if so. Plus an internal endpoint catalogue cataloguing every endpoint Tado CE depends on, classifying each by criticality, and documenting graceful-degradation behaviour — bridges into the v5 cleanup work. |
| GA | Polish + final review | Final FEATURES_GUIDE editing pass, full quality-check sweep, release announcement. |

Cadence is themes-not-dates. Each beta lands when its work is clean and stable.

All AC writes (target temperature, HVAC mode, swing, fan, timers) currently go through the cloud. See the AC entry below for why HomeKit local control on Smart AC Control V3+ isn't on the active roadmap.

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
- **Climate AC + Heating structural mirror** — `climate_ac.py` and `climate_heating.py` repeat the same setup shape (`async_added_to_hass`, `async_will_remove_from_hass`, zone-config listener wiring, temp-limit refresh) with only default temperature and log-prefix differences. Sharing a base class would save around 120 LOC. Gated on a thorough test-suite review and a cross-file consistency check first — the two paths are intentionally cloned today and have absorbed several recurring shape-similar bugs over the v4.x cycle, so the refactor needs solid scaffolding before it lands.
- **Four feature toggles that have no UI surface** — `zone_diagnostics_enabled`, `device_controls_enabled`, `boost_buttons_enabled`, `environment_sensors_enabled` are stored as config keys but no Options Flow row, no `strings.json` entry, and no selector lets you actually flip them. They sit at the default `True` on every install. Net cost is around 130 LOC carried for a runtime path that nobody can trigger, same shape as Test Mode (retired in v4.0.0-beta.7). Drop the toggles. If anyone later surfaces a real need to disable one of these, it will land in v5.x as a normal feature flag rather than as an inherited dead toggle.
- **AC swing legacy mode migration shim** — `climate_ac._migrate_legacy_swing_mode` has carried a deprecation warning since v4.1.0-beta.1 stating "removed in v4.2". If v4.2 ships before v5.0.0 the shim retires there; otherwise it rides along with v5 cleanup, slightly later than the original promise. Track in the v5 punch list either way.
- **`entity_cleanup.py` v3.x branches** — eighteen `legacy_suffixes=` lists carry v3.x `unique_id` shapes for entities that have since been renamed or moved. Once v5.0.0 ships with the minimum-upgrade-from-v4.x rule in force, every v3.x branch in those lists is unreachable and can drop. Roughly 150 LOC depending on how many lists go fully empty after the cull.

Anything else flagged in the v5 audit will be added here as it surfaces. No timeline yet.

### Long-Term Exploration

- **Fully Local Control** ([Discussion #29](https://github.com/hiall-fyi/tado_ce/discussions/29)) — Control via the 868MHz protocol between Bridge and TRVs, bypassing both cloud and HomeKit. Requires specialized hardware and community help.
