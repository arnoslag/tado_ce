# Changelog

All notable changes to Tado CE will be documented in this file.

## [3.0.3] - 2026-03-11

### Bug Fixes
- **Fixed Hub Sensors Showing Stale Data** ([#173](https://github.com/hiall-fyi/tado_ce/issues/173) - @driagi) — Hub sensors (API Limit, Reset Time, Status, Polling Interval, Next Sync) were stuck on initial values after each API sync. Now updates correctly in real-time.

### Improvements
- **Complete Entity Cleanup Coverage** — Disabling Weather or Mobile Device features now properly removes their entities and orphan devices. Previously these two feature toggles were missing from the cleanup system.
- **Improved Entity Cleanup Architecture** — Entity cleanup logic moved to a dedicated module, making it easier to maintain and extend for new entity types.
- **Code Quality** — Fixed all strict type-checking errors across the codebase.

## [3.0.2] - 2026-03-11

### Bug Fixes
- **Fixed Setup Hanging Indefinitely** ([#170](https://github.com/hiall-fyi/tado_ce/issues/170) - @driagi, @tigro7, @mpartington) — Integration could hang during setup for up to 80 minutes if you had API call history older than 14 days. Now starts up normally.
- **Fixed Preheat Triggering During Away Mode** ([#171](https://github.com/hiall-fyi/tado_ce/issues/171) - @thefern69) — Preheat recommendations and triggers were firing even when the home was in Away mode. Now correctly suppressed when not at home.
- **Fixed Hub Sensors Showing Wrong Polling Interval / Reset Time** ([#173](https://github.com/hiall-fyi/tado_ce/issues/173) - @driagi) — Three hub sensors were displaying default intervals instead of the actual adaptive polling values.
- **Fixed Blocking I/O Warning During Sensor Update** — Resolved a performance warning caused by synchronous file access during sensor updates.
- **Fixed Raw Values in Persistent Insights** — Home Insights were showing internal identifiers instead of human-readable names.

### Improvements
- **Preheat Cooling Prediction for Active Target** ([Discussion #163](https://github.com/hiall-fyi/tado_ce/discussions/163) - @thefern69) — Cooling rate prediction now also applies to the current setpoint, not just the next schedule change. Particularly useful for underfloor heating systems with high thermal inertia.
- **Cleaner Persistent Insights Display** — Insights now show grouped, emoji-prefixed lines (e.g., "🔴 High: Battery — Guest (1d 4h)") instead of raw data.
- **Removed Redundant Zone Name from Recommendations** — Per-zone recommendation attributes no longer repeat the zone name, since the entity already provides that context.

## [3.0.1] - 2026-03-10

### Bug Fixes
- **Removed `[CE]` Prefix from Entity Names** ([#167](https://github.com/hiall-fyi/tado_ce/issues/167) - @jeverley) — All entity names no longer include the `[CE]` prefix. Entity IDs are unchanged.
- **Fixed Duplicate Sensor Names in Multi-Device Zones** ([#167](https://github.com/hiall-fyi/tado_ce/issues/167) - @hapklaar) — Zones with multiple devices (e.g., sensor + 2 valves) now show device type in Battery/Connection sensor names to avoid duplicates.
- **Fixed Entities Going Unavailable Every 5 Minutes** ([#167](https://github.com/hiall-fyi/tado_ce/issues/167) - @hapklaar, @andyb2000) — Token refresh was triggering a full integration reload every poll cycle, briefly making entities unavailable. Now handles token rotation silently.
- **Synced Missing Translation Keys** — 3 translation keys added to all 7 language files.

## [3.0.0] - 2026-03-10

**Multi-Home Support, Actionable Insights Full Feature Set, Code Quality Platinum**

### Features
- **Multi-Home Support** ([#110](https://github.com/hiall-fyi/tado_ce/issues/110) - @robvol87, [#145](https://github.com/hiall-fyi/tado_ce/issues/145) - @Blankf) — Run multiple Tado accounts/homes in a single HA instance. Each home is fully isolated with its own data, API tracking, and configuration.
- **Insight Smarter Summary** — Home insights sensor produces action-based summaries (e.g., "Replace batteries: Guest, Lounge — Mold risk: Bedroom") instead of generic counts.
- **Insight Correlation** — Related insights within a zone are merged into a single action (e.g., mold risk + humidity trend + condensation → "humidity problem").
- **Insight History & Trending** — Persistent tracking of insight appearance/disappearance across HA restarts. Duration-aware messages and weekly digest attribute.
- **Insight Priority Escalation** — Auto-escalation based on persistence (e.g., battery low > 7 days → high priority, > 14 days → critical).
- **Insight Health Score** — Numeric 0-100 score reflecting overall home health, exposed as attribute on Home Insights sensor.
- **Preheat Cooling Rate Prediction** ([Discussion #163](https://github.com/hiall-fyi/tado_ce/discussions/163) - @thefern69) — Preheat Advisor considers cooling trends when room is above target, estimating when temperature will drop below target for proactive preheat.

### Improvements
- **Heating Rate Unit Corrected to °C/h** — Sensor unit and documentation now consistently use °C/h.
- **Lowered Timer Minimum to 1 Minute** ([#162](https://github.com/hiall-fyi/tado_ce/issues/162) - @joaomacp) — Climate and water heater timers now accept durations as low as 1 minute.
- **Multi-Language Translations** — Config flow and options UI available in 7 languages: English, German, Spanish, French, Italian, Dutch, and Portuguese.
- **Expanded Test Suite** — 3,238 tests with 99% code coverage. Strict type safety across all source files.

### Bug Fixes
- **Fixed Auth URL Showing 404 Page** ([#104](https://github.com/hiall-fyi/tado_ce/issues/104)) — Config flow authorization no longer shows a broken fallback URL.
- **Fixed Window Sensor Not Detecting Open Windows Without Auto-Assist** ([#157](https://github.com/hiall-fyi/tado_ce/issues/157) - @tanerpaca) — Window sensor now detects open windows even without Auto-Assist subscription.
- **Fixed Preheat Now Sensor Triggering a Day Early** ([#164](https://github.com/hiall-fyi/tado_ce/issues/164) - @thefern69) — Preheat sensor now uses complete datetime instead of time-only, preventing early triggers.

## [2.3.1] - 2026-02-26

### Bug Fixes
- **Fixed AC 'High' Fan Speed Reverting on Mitsubishi/Fujitsu Units** ([#142](https://github.com/hiall-fyi/tado_ce/issues/142) - @BirbByte) — Fan speed mapping now built dynamically from your AC's actual capabilities instead of using a static mapping that didn't work for all brands.
- **Fixed Blocking I/O Warning on Fresh Install** ([#127](https://github.com/hiall-fyi/tado_ce/issues/127) - @slflowfoon) — Resolved a startup warning on fresh installs where the data directory didn't exist yet.

### Improvements
- **AC Capabilities Live Reload** — After pressing "Refresh AC Capabilities", AC entities automatically reload without requiring HA restart.
- **AC Temperature Defaults from Capabilities** — Default temperature when switching modes now uses your AC's actual min/max range instead of hardcoded 24°C.
- **AC Optimistic State Improvements** — Fan and swing mode selections are preserved during update cycles, preventing UI flicker.

---

## [2.3.0] - 2026-02-25

### Features
- **21 New Insight Types** — Expanded actionable insights across 7 categories: zone efficiency, schedule & boiler, occupancy, weather, humidity, device health, and cross-zone analysis.

### Improvements
- **Enhanced `set_climate_timer` Service** ([#152](https://github.com/hiall-fyi/tado_ce/issues/152) - @mpartington) — `time_period` is now optional. Use `overlay: next_time_block` for "until next schedule change" or `overlay: manual` for indefinite. Backward compatible.

### Bug Fixes
- **Fixed Mold Risk Suggesting Lower Temperature** ([#147](https://github.com/hiall-fyi/tado_ce/issues/147) - @ChrisMarriott38) — Mold risk recommendation no longer suggests increasing heating when room is already warm enough. Now suggests ventilation/dehumidifier instead.
- **Fixed Hot Water Overlay Showing for Combi Boilers** ([#149](https://github.com/hiall-fyi/tado_ce/issues/149) - @ChrisMarriott38) — Overlay Mode and Timer Duration entities no longer incorrectly appear for combi boiler hot water zones.
- **Fixed Mobile Device Tracker Not Updating** ([#150](https://github.com/hiall-fyi/tado_ce/issues/150) - @driagi) — Device tracker entities were stuck on the state from last HA restart. Now polls every 30 seconds for real-time location updates.

---

## [2.2.3] - 2026-02-24

**Smart Day/Night Polling, AC Fan Fix & Climate Group Support**

### Bug Fixes
- **Fixed Adaptive Polling for Low-Quota Users** ([#144](https://github.com/hiall-fyi/tado_ce/issues/144) - @mkruiver) — Users with ≤100 remaining API calls now get smart day/night polling instead of getting stuck at 120-minute intervals.
- **Fixed Night Polling Using Wrong Interval** ([#141](https://github.com/hiall-fyi/tado_ce/issues/141) - @Xavinooo) — Day period quota calculation now correctly uses your custom night interval setting.
- **Fixed AC 'High' Fan Speed Reverting** ([#142](https://github.com/hiall-fyi/tado_ce/issues/142) - @BirbByte) — Fan level validation now checks against your AC's actual capabilities.

### Improvements
- **Climate Group Support** ([#139](https://github.com/hiall-fyi/tado_ce/discussions/139) - @merlinpimpim) — `set_climate_timer`, `set_water_heater_timer`, and `resume_schedule` services now support climate groups defined in `configuration.yaml`.

---

## [2.2.2] - 2026-02-23

### Bug Fixes
- **Fixed API Options Validation and Persistence** ([#134](https://github.com/hiall-fyi/tado_ce/issues/134) - @Xavinooo) — Fixed issues where API polling options couldn't be saved if only one interval was filled, and clearing a custom interval didn't persist.

---

## [2.2.1] - 2026-02-23

### Bug Fixes
- **Fixed Hot Water Config for Tank-Based Systems** ([#115](https://github.com/hiall-fyi/tado_ce/issues/115) - @jeverley) — Tank-based hot water users now correctly see Overlay Mode and Timer Duration entities.
- **Fixed API Options Not Saving** ([#134](https://github.com/hiall-fyi/tado_ce/issues/134) - @ChrisMarriott38, @Xavinooo) — Custom polling intervals now save correctly after Options flow changes.

---

## [2.2.0] - 2026-02-23

**Calibration Sensors & Actionable Insights**

### Features
- **Surface Temperature Sensor** ([#118](https://github.com/hiall-fyi/tado_ce/issues/118)) — New sensor showing calculated cold spot temperature for mold risk calibration with a laser thermometer.
- **Dew Point Sensor** ([#118](https://github.com/hiall-fyi/tado_ce/issues/118)) — New sensor for dehumidifier automation and condensation prevention.
- **Window Predicted Sensor** ([Discussion #112](https://github.com/hiall-fyi/tado_ce/discussions/112) - @tigro7) — Early open window detection using heating/cooling anomaly detection, providing warning before Tado's cloud detection (which takes 15-17 minutes).
- **Actionable Recommendations** ([Discussion #112](https://github.com/hiall-fyi/tado_ce/discussions/112) - @tigro7) — New `recommendation` attribute on environment, device, and hub sensors with specific, actionable guidance.
- **Home Insights Sensor** ([Discussion #112](https://github.com/hiall-fyi/tado_ce/discussions/112) - @tigro7) — Hub-level aggregation of insights from all zones with priority ranking.
- **Zone Insights Sensor** ([Discussion #112](https://github.com/hiall-fyi/tado_ce/discussions/112) - @tigro7) — Per-zone insights with dynamic icon based on highest priority.

### Improvements
- **User-Friendly Attribute Values** — Zone type, window type, and comfort model attributes now show human-readable names instead of internal codes.

### Bug Fixes
- **Fixed Heating Cycle Never Completing** ([#125](https://github.com/hiall-fyi/tado_ce/issues/125) - @BruceRobertson) — Long heating cycles (50+ minutes) now complete correctly.
- **Fixed API Call History Error on First Run** ([#127](https://github.com/hiall-fyi/tado_ce/issues/127) - @slflowfoon, [PR #132](https://github.com/hiall-fyi/tado_ce/pull/132) - @hacker4257) — First-run error when storage directory doesn't exist yet.
- **Fixed Hot Water Config for Tank-Based Systems** ([#115](https://github.com/hiall-fyi/tado_ce/issues/115) - @jeverley) — Tank-based hot water systems now correctly get Overlay Mode and Timer Duration entities.
- **Fixed Polling Override Issues** ([#126](https://github.com/hiall-fyi/tado_ce/issues/126) - @Xavinooo) — Custom night interval, day/night boundary detection, and config persistence all fixed.
- **Fixed AC Swing Mode for Mitsubishi Units** ([#128](https://github.com/hiall-fyi/tado_ce/issues/128) - @BirbByte) — AC units that don't support "OFF" as a swing value no longer get API errors.
- **Fixed Environment Sensor Cleanup** — All v2.2.0 sensors now correctly removed when the feature is toggled off.
- **Fixed Heating Anomaly False Positives** — Heating anomaly insight no longer fires on every poll cycle.

---

## [2.1.1] - 2026-02-19

### Bug Fixes
- **Fixed Test Mode Polling Using Wrong Reset Time** ([#120](https://github.com/hiall-fyi/tado_ce/issues/120), [#119](https://github.com/hiall-fyi/tado_ce/issues/119) - @ChrisMarriott38) — Test Mode polling intervals now calculate correctly.
- **Fixed Hot Water Zones Showing Heating-Only Entities** ([#115](https://github.com/hiall-fyi/tado_ce/issues/115) - @ChrisMarriott38) — Per-zone configuration entities (Surface Temp Offset, Min/Max Temp, etc.) no longer appear for hot water zones.

## [2.1.0] - 2026-02-18

**Per-Zone Configuration**

### Features
- **Per-Zone Overlay Mode** — Configure overlay termination per zone (Tado Mode, Timer, Manual).
- **Per-Zone Timer Duration** — Set custom timer duration per zone (15-180 minutes).
- **Per-Zone Thermal Analytics** ([#91](https://github.com/hiall-fyi/tado_ce/issues/91)) — Choose which zones have Thermal Analytics sensors. Zones that never call for heat can be deselected to keep UI clean.
- **Per-Zone Surface Temp Offset** ([#90](https://github.com/hiall-fyi/tado_ce/issues/90)) — Calibrate mold risk calculation per zone using a laser thermometer.

### Bug Fixes
- **Fixed Preheat Time Showing `unknown` After Restart** — Preheat Time sensors now display correctly after HA restart.
- **Fixed NEXT_TIME_BLOCK API Error** — Overlay termination now correctly maps to Tado API values.
- **Fixed Custom Polling Below 5 Minutes** ([#107](https://github.com/hiall-fyi/tado_ce/issues/107) - @jakeycrx) — Custom intervals of 1-4 minutes now work correctly when explicitly set.

### Improvements
- **Simplified Options UI** — Test Mode moved to Tado CE Exclusive section (4 sections instead of 5).

## [2.0.2] - 2026-02-14

**Presence Mode Select & Configurable Overlay Mode**

### ⚠️ Breaking Changes
- **Presence Mode Select** — `switch.tado_ce_away_mode` replaced by `select.tado_ce_presence_mode` ([Discussion #102](https://github.com/hiall-fyi/tado_ce/discussions/102) - @wyx087). Update automations from `switch.turn_on/turn_off` to `select.select_option`.

### Features
- **Presence Mode Select** — New 3-option select: Auto (resume geofencing), Home, Away.
- **Configurable Overlay Mode** ([#101](https://github.com/hiall-fyi/tado_ce/issues/101) - @leoogermenia) — Choose how long manual temperature changes last: Tado Mode (default), Next Time Block, or Manual (infinite).

### Bug Fixes
- **Fixed Custom Polling Below 5 Minutes** ([#107](https://github.com/hiall-fyi/tado_ce/issues/107) - @jakeycrx) — Custom intervals of 1-4 minutes now supported.
- **Fixed Polling Stuck at 120 Min in Uniform Mode** ([#99](https://github.com/hiall-fyi/tado_ce/issues/99) - @ChrisMarriott38) — Uniform mode (same day/night hours) now calculates intervals correctly.

## [2.0.1] - 2026-02-12

**Mold Risk Percentage, Hot Water Fix & Bootstrap Reserve**

### Features
- **Mold Risk Percentage Sensor** ([#90](https://github.com/hiall-fyi/tado_ce/issues/90)) — New sensor for historical tracking of mold risk.
- **Bootstrap Reserve Protection** ([#99](https://github.com/hiall-fyi/tado_ce/issues/99) - @ChrisMarriott38) — Reserves 3 API calls for auto-recovery.
- **Test Mode Full Simulation** — Fully simulates 100-call tier with independent 24h cycle.
- **Day/Night Aware Polling** — Night uses fixed 120-minute intervals; day uses adaptive intervals based on remaining quota.

### Bug Fixes
- **Fixed Climate Entities Unavailable After Upgrade** ([#100](https://github.com/hiall-fyi/tado_ce/issues/100) - @Claeysjens)
- **Fixed Hot Water UI Jumping Back** ([#98](https://github.com/hiall-fyi/tado_ce/issues/98) - @ChrisMarriott38) — Temperature changes no longer revert in the UI.
- **Fixed Quota Reserve Not Preventing API Limit** ([#99](https://github.com/hiall-fyi/tado_ce/issues/99) - @ChrisMarriott38)
- **Fixed Mold Risk Dew Point Calculation** ([#90](https://github.com/hiall-fyi/tado_ce/issues/90) - @ChrisMarriott38) — Now correctly uses room temperature.
- **Fixed Thermal Analytics Not Available for SU02 Zones** ([#91](https://github.com/hiall-fyi/tado_ce/issues/91) - @ChrisMarriott38) — Sensors now created for all zones with heating data, not just TRV zones.

## [2.0.0] - 2026-02-09

**Smart Polling, Mold Risk Enhancement & Thermal Analytics**

### Features
- **API Monitoring Sensors** ([#86](https://github.com/hiall-fyi/tado_ce/discussions/86), [#65](https://github.com/hiall-fyi/tado_ce/issues/65)) — New sensors: Next Sync, Last Sync, Polling Interval, Call History, API Breakdown.
- **Thermal Analytics** — New sensors for TRV zones: thermal inertia, average heating rate, preheat time, and more.
- **Adaptive Smart Polling** ([#89](https://github.com/hiall-fyi/tado_ce/issues/89) - @ChrisMarriott38) — Automatically adjusts polling frequency based on remaining API quota.
- **Quota Reserve Protection** ([#94](https://github.com/hiall-fyi/tado_ce/issues/94) - @ChrisMarriott38) — Pauses polling when quota is critically low.
- **Enhanced Mold Risk** ([#90](https://github.com/hiall-fyi/tado_ce/issues/90) - @ChrisMarriott38) — Surface temperature calculation with configurable window type.

### Bug Fixes
- Fixed hot water timer buttons not finding entity ([#93](https://github.com/hiall-fyi/tado_ce/issues/93) - @Fred224)
- Removed 'Tado CE' prefix from entity names

## [1.10.0] - 2026-02-05

### Bug Fixes
- **Fixed Climate Entity Flickering** ([#44](https://github.com/hiall-fyi/tado_ce/issues/44) - @hapklaar, @chinezbrun, @neonsp) — 3-layer defense strategy prevents stale data from overwriting user actions.

## [1.9.7] - 2026-02-04
- Fixed state flickering when rapidly changing modes ([#44](https://github.com/hiall-fyi/tado_ce/issues/44) - @chinezbrun)

## [1.9.6] - 2026-02-04
- Fixed hvac_action reverting to idle after state change ([#44](https://github.com/hiall-fyi/tado_ce/issues/44) - @hapklaar, @chinezbrun)

## [1.9.5] - 2026-02-02
- Fixed hvac_action not updating when setting temperature ([#44](https://github.com/hiall-fyi/tado_ce/issues/44) - @hapklaar, @chinezbrun)

## [1.9.4] - 2026-02-02

**Boost Buttons**

### Features
- **Boost Button** — Sets zone to 25°C for 30 minutes.
- **Smart Boost Button** — Intelligent boost with calculated duration.

### Bug Fixes
- Fixed hvac_action stuck on "Heating" after switching to Auto ([#44](https://github.com/hiall-fyi/tado_ce/issues/44) - @hapklaar)
- Fixed AC startup validation warnings ([#44](https://github.com/hiall-fyi/tado_ce/issues/44) - @neonsp)
- Fixed slow zone sensor updates ([#44](https://github.com/hiall-fyi/tado_ce/issues/44) - @chinezbrun)

## [1.9.3] - 2026-02-02
- Fixed slow state confirmation for Heating users ([#44](https://github.com/hiall-fyi/tado_ce/issues/44) - @hapklaar, @chinezbrun)
- Fixed AC DRY mode 422 error ([#79](https://github.com/hiall-fyi/tado_ce/issues/79) - @Fred224, @neonsp)

## [1.9.2] - 2026-02-01
- Fixed grey loading state issue ([#44](https://github.com/hiall-fyi/tado_ce/issues/44) - @chinezbrun)

## [1.9.1] - 2026-01-31
- Fixed device migration crash on startup ([#74](https://github.com/hiall-fyi/tado_ce/issues/74))

## [1.9.0] - 2026-01-31

**Smart Comfort Analytics + Environment Sensors**

### Features
- **Smart Comfort Analytics** — Heating/cooling rate, time to target, heating efficiency sensors.
- **Smart Comfort Insights** ([#33](https://github.com/hiall-fyi/tado_ce/discussions/33)) — Historical comparison, preheat advisor, smart comfort target.
- **Environment Sensors** ([#64](https://github.com/hiall-fyi/tado_ce/issues/64)) — Mold risk and comfort level per zone.
- **Schedule Sensors** — Next schedule time and temperature.

### Bug Fixes
- Fixed API reset detection for 100-call limit ([#54](https://github.com/hiall-fyi/tado_ce/issues/54))
- Fixed temperature offset for multi-TRV rooms ([#66](https://github.com/hiall-fyi/tado_ce/issues/66))
- Fixed device sensor assignment ([#56](https://github.com/hiall-fyi/tado_ce/issues/56))

## [1.8.3] - 2026-01-26
- Cached AC capabilities to save API calls ([#61](https://github.com/hiall-fyi/tado_ce/issues/61) - @neonsp)
- New: Refresh AC Capabilities button
- Fixed AC OFF→ON state feedback ([#44](https://github.com/hiall-fyi/tado_ce/issues/44) - @neonsp)

## [1.8.2] - 2026-01-26
- Enhanced AC optimistic updates ([#44](https://github.com/hiall-fyi/tado_ce/issues/44) - @neonsp)
- Fixed Resume All Schedules delay ([#44](https://github.com/hiall-fyi/tado_ce/issues/44) - @hapklaar)

## [1.8.1] - 2026-01-26
- Fixed AC optimistic updates not working ([#44](https://github.com/hiall-fyi/tado_ce/issues/44) - @neonsp)
- Fixed Resume All Schedules not refreshing ([#44](https://github.com/hiall-fyi/tado_ce/issues/44) - @hapklaar)

## [1.8.0] - 2026-01-26

**Schedule Calendar + Multi-Home Prep**

- New: Schedule Calendar — Per-zone calendar showing heating schedules
- New: Per-zone Refresh Schedule button
- New: API Reset sensor attributes ([#54](https://github.com/hiall-fyi/tado_ce/issues/54) - @ChrisMarriott38)
- Multi-home prep: Per-home data files

## [1.7.0] - 2026-01-26
- New: Optimistic state updates — Immediate UI feedback
- New: Optional homeState sync to save API calls
- Multi-home prep: unique_id migration

## [1.6.3] - 2026-01-25
- New: HA History Detection for accurate API reset time

## [1.6.2] - 2026-01-25
- Fixed API call history not recording
- Fixed timezone issues in various sensors

## [1.6.1] - 2026-01-25
- Fixed API Usage/Reset sensors showing 0
- Added configurable refresh debounce delay

## [1.6.0] - 2026-01-25
- Migrated to native async API (faster, no subprocess)
- Fixed cumulative migration bug
- Fixed `climate.set_temperature` ignoring `hvac_mode` parameter

## [1.5.5] - 2026-01-24
- Fixed AC Auto mode turning off AC
- Reduced API calls per state change

## [1.5.4] - 2026-01-24
- Fixed all AC control issues (modes, fan, swing)
- Added unified swing dropdown

## [1.5.3] - 2026-01-24
- Added Resume All Schedules button
- Fixed AC control 422 errors

## [1.5.2] - 2026-01-24
- Fixed token loss on HACS upgrade

## [1.5.1] - 2026-01-24
- Fixed OAuth flow errors for new users
- Added re-authenticate option in UI

## [1.5.0] - 2026-01-24

**Async Architecture Rewrite**

- Migrated to async API calls
- Added temperature offset service
- Full AC mode/fan/swing support
- Hot water temperature control

## [1.4.1] - 2026-01-23
- Fixed authentication broken after upgrade

## [1.4.0] - 2026-01-23
- New in-app OAuth setup (no SSH required)
- Home selection for multi-home accounts

## [1.2.1] - 2026-01-22
- Fixed duplicate hub cleanup race condition

## [1.2.0] - 2026-01-21

**Zone-Based Device Organization**

- Each zone now appears as separate device
- Optional weather sensors
- Customizable polling intervals
- 60-70% reduction in API calls

## [1.1.0] - 2026-01-19
- Added Away Mode switch
- Added preset mode support (Home/Away)

## [1.0.1] - 2026-01-18
- Fixed auto-fetch home ID

## [1.0.0] - 2026-01-17
- Initial release
