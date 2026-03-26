# Changelog

All notable changes to Tado CE will be documented in this file.

## [3.4.1] - 2026-03-26

### Bug Fixes
- **Fixed crash on clean install** ([#204](https://github.com/hiall-fyi/tado_ce/issues/204) - @Saughassy) — The integration failed to start with "unsupported operand type(s) for //: 'NoneType' and 'int'" when rate limit data had missing values. Now handles missing rate limit fields gracefully during first setup.

---

## [3.4.0] - 2026-03-23

### Features
- **API Write Optimization** — All enabled by default. Three new settings under **Settings → Tado CE → Configure → Global Settings → Polling & API** to reduce unnecessary API calls:
  - **Smart Actions Debounce** — When you drag a temperature slider, only the final value is sent to the API instead of every intermediate position. Configurable window (0–10 seconds, default 3). Set to 0 to disable.
  - **Action Guard** — Skips API calls when the requested state already matches the current state (e.g. setting 22°C when it's already 22°C). Always active.
  - **Device Sync Queue** — Device-level operations (child lock, early start) are now queued and executed sequentially with a configurable delay (0.5–5 seconds, default 1), preventing race conditions from rapid toggling. Always active.
  - **Write Coalescing** — Multiple rapid state changes trigger a single coordinated refresh instead of one per change. Always active.
  - **Resume Guard** — Resuming a zone's schedule is skipped if the zone is already following its schedule. Always active.
- **Schedule Preview** — Heating and AC climate entities now show a `scheduled_target_temperature` attribute with the current schedule target, so you can see what temperature the zone would be at without an overlay.

### Improvements
- **UFH Buffer Now Per-Zone** — Underfloor heating buffer is now configured per zone (via Zone Configuration) instead of a global setting. Zones with `heating_type: ufh` automatically get the buffer applied.
- **Atomic Writes for Zone Config & Outdoor Temp** — Zone configuration and outdoor temperature history files now use the same crash-safe tempfile-then-rename pattern as other data files.
- **Dropped v2.x Migration Code** — All migration code for upgrading from v2.x has been removed. The minimum supported upgrade path is now v3.0.0+. Users on v2.x should upgrade to v3.x first.
- **Translation Sync** — Added missing `adaptive_preheat_mode` selector translations across all 7 languages.
- **Codebase Cleanup** — Removed unused `thermal_storage.py` (511 lines) and `zone_config.py` stub. Removed hardcoded default zone names from constants.

### Bug Fixes
- **Fixed Hassfest Validation Failure** — Window detection mode selector options (`Active`, `Passive`, `Auto`) used Title Case keys which Hassfest requires to be lowercase. Now uses `active`, `passive`, `auto` across `strings.json` and all translation files.

## [3.3.1] - 2026-03-21

### Improvements
- **Smarter Weather Compensation Curve** ([#187](https://github.com/hiall-fyi/tado_ce/issues/187) - @driagi) — Preset heating curves (Radiators Standard, Radiators Low Temp, Underfloor) now automatically calculate the slope from your min/max flow and design/shutoff temperatures. Previously, a fixed slope could cause the flow temperature to hit the minimum floor well before the shutoff temperature, creating a flat zone where outdoor changes had no effect. Now the curve modulates smoothly across the entire outdoor range. Custom preset still gives you full manual control.

## [3.3.0] - 2026-03-21

### Features
- **Weather Compensation** ([#187](https://github.com/hiall-fyi/tado_ce/issues/187) - @driagi) — Automatically adjusts your boiler's flow temperature based on outdoor temperature. Pick from three presets (Radiators Standard, Radiators Low Temp, Underfloor) or create a custom heating curve. Includes smoothing, room feedback, and a 10-minute hold between adjustments to prevent oscillation. Configured via **Settings → Tado CE → Configure → Global Settings → Flow Temperature Control**.
- **Enable Internet Bridge Toggle** — Simple on/off toggle at the top of Flow Temperature Control. Turn it off and all bridge-related entities are automatically removed — no need to manually clear credentials.
- **Adaptive Preheat Passive Mode** ([#171](https://github.com/hiall-fyi/tado_ce/issues/171) - @thefern69) — Preheat now has three modes per zone: Off, Active (always triggers), and Passive (only triggers when the zone is following its schedule — skips preheat if you've set a manual override from HomeKit, the Tado app, etc.). Existing users with preheat enabled are automatically migrated to Active. Configured via **Options Flow → Zone Configuration**.
- **Restore Previous State** — New `tado_ce.restore_previous_state` service that puts a zone back to whatever it was doing before the last change. Works with heating, AC, and hot water. State is saved automatically before any overlay action (timers, temperature changes, open window mode, preheat). If nothing was saved, it falls back to resuming the schedule. Saved state survives HA restarts and clears when you arrive home.
- **Passive Window Detection** — Detects open windows even when your heating or AC is off. Combines temperature drop speed, humidity changes, and indoor-outdoor temperature difference to tell the difference between a natural cooldown and an open window. Adjusts for your window type and is stricter in winter.
- **Window Detection Mode Per Zone** — Choose how each zone detects open windows: Active (only when heating/cooling is running), Passive (works anytime), or Auto (picks the best method automatically). Configured via **Options Flow → Zone Configuration**.
- **Heat Index & Heat Risk** — The Comfort Level sensor now shows "feels like" temperature when it's warm (above 26.7°C), factoring in humidity. Risk levels (Caution, Extreme Caution, Danger, Extreme Danger) appear in the sensor attributes and in comfort recommendations.
- **Bridge Connected Sensor** — New binary sensor that shows whether your Internet Bridge is reachable. Includes health info like response time, failure count, and last successful connection as attributes.
- **Bridge Health Tracking** — The bridge connection sensor tolerates brief hiccups — it only marks the bridge as disconnected after 3 consecutive failures, so a single timeout won't trigger a false alarm.

### Improvements
- **Flow Temperature Control Settings** — Bridge credentials and weather compensation settings are now in one place instead of two separate menus, so there's less clicking around.
- **Fewer Bridge Entities by Default** — Only the most useful bridge entities are visible out of the box (Bridge Connected, Wiring State, Boiler Output Temperature, Boiler Flow Temperature). The rest are hidden and can be enabled manually if you need them.
- **Bridge Serial Validation** ([#187](https://github.com/hiall-fyi/tado_ce/issues/187) - @ChrisMarriott38) — The bridge serial field now checks that it starts with `IB` (v3+ bridge). V2 bridges (`GW` serial) aren't supported by the Bridge API. Weather Compensation still works without a bridge via cloud data.
- **Default Temperature on First Install** ([#182](https://github.com/hiall-fyi/tado_ce/issues/182) - @neonsp) — Climate entities now start with a sensible default (20°C heating, 24°C AC) instead of showing blank controls on first install.
- **Weather Compensation Blueprint Updated** ([#187](https://github.com/hiall-fyi/tado_ce/issues/187) - @driagi) — Blueprint tuned to reduce oscillation: larger step size (1.0°C), wider deadband (1.0°C), and 10-minute hold between adjustments.
- **Smoother Window Detection** — The Window Predicted sensor no longer flickers on/off rapidly. It now waits for several stable readings before clearing a detection (3 readings on Low sensitivity, 2 on Medium, 1 on High).
- **Window Detection Events** — HA events (`tado_ce_window_predicted` and `tado_ce_window_predicted_cleared`) now fire when a window is detected or cleared — useful for building your own automations.
- **Window Detection History** — The Window Predicted sensor now tracks when the last detection happened, how many times today, and which detection mode was used. Daily count resets at midnight.
- **Open Window Mode Saves State** — When `set_open_window_mode` activates, it now saves what the zone was doing first. After the window is closed, use `restore_previous_state` to go back to exactly where you were.

### Bug Fixes
- **Fixed Preheat Triggering During Away Mode** ([#171](https://github.com/hiall-fyi/tado_ce/issues/171) - @thefern69) — Preheat could still fire during the Home→Away transition due to a timing gap. Now properly checks presence before any heating action, including on startup.
- **Fixed Open Window Mode Duration** — The `set_open_window_mode` service was sending the duration as text instead of a number, which could cause the Tado API to reject the request. Now sends it correctly.

## [3.2.2] - 2026-03-16

### Bug Fixes
- **Fixed Boiler Output Temperature Sensor Showing Wrong Value** ([#187](https://github.com/hiall-fyi/tado_ce/issues/187) - @driagi) — The boiler output temperature sensor was reading from the wrong data field, so it never showed the actual temperature. Now displays the correct real-time value. Also fixed the Wiring State sensor's extra attributes.

## [3.2.1] - 2026-03-16

### Features
- **Indefinite Open Window Mode** ([Discussion #184](https://github.com/hiall-fyi/tado_ce/discussions/184) - @jeverley) — The `set_open_window_mode` service now supports `duration: 0` to keep the window mode active until you manually resume. Great for contact sensor automations where you want full control.

### Bug Fixes
- **Fixed Bridge Sensor Showing "Unknown"** ([#187](https://github.com/hiall-fyi/tado_ce/issues/187) - @driagi) — Bridge API sensors were stuck on "Unknown" even when the bridge was connected. Now shows boiler temperature data correctly. Added better logging for troubleshooting.

## [3.2.0] - 2026-03-16

**Bridge API Integration — Flow Temperature Control**

### Features
- **Bridge API Integration** — Connect to your Tado Internet Bridge for direct boiler monitoring. Enter your bridge serial and auth key in Settings, and you'll get sensors for boiler wiring state, output temperature, and a control to set the max output temperature (25–80°C). Bridge data is fetched separately from the cloud, so bridge issues never affect your other sensors.
- **Bridge Entity Cleanup** — Remove your bridge credentials and all bridge-related entities are automatically cleaned up.

### Bug Fixes
- **Fixed Climate Card Blank After HA Restart** ([#182](https://github.com/hiall-fyi/tado_ce/issues/182) - @neonsp) — The climate card no longer shows a blank temperature after restarting HA. Your last target temperature is now restored automatically, so the controls work right away.
- **Fixed External Sensor Not Updating Instantly** ([#143](https://github.com/hiall-fyi/tado_ce/issues/143) - @BirbByte) — External temperature and humidity sensors (HomeKit, Zigbee, etc.) now update the climate card immediately when the value changes, instead of waiting for the next poll cycle.
- **Set Open Window Mode Service** ([#172](https://github.com/hiall-fyi/tado_ce/issues/172), [Discussion #184](https://github.com/hiall-fyi/tado_ce/discussions/184) - @driagi) — New `set_open_window_mode` service lets you trigger open window mode from your own contact sensors (Zigbee, Z-Wave, etc.) without waiting for Tado's built-in detection. Defaults to your zone's timeout setting or 15 minutes.

## [3.1.1] - 2026-03-15

**Manual Token Auth, Climate Card Fix & Smart AC Mode**

### Features
- **Manual Token Authentication** ([#185](https://github.com/hiall-fyi/tado_ce/issues/185)) — New fallback login method for when Tado's authorization server is down. You can now paste a refresh token from the Tado web app as an alternative way to sign in.

### Bug Fixes
- **Fixed Climate Card Unusable When Zone is OFF** ([#182](https://github.com/hiall-fyi/tado_ce/issues/182)) — When a heating zone is off, the climate card now keeps the last temperature showing so the slider and controls still work.

### Improvements
- **Updated Global Settings Description** ([Discussion #76](https://github.com/hiall-fyi/tado_ce/discussions/76)) — The setup instructions now match the current toggle-based settings layout.
- **AC Picks the Right Mode Automatically** ([#182](https://github.com/hiall-fyi/tado_ce/issues/182) - @neonsp) — When you turn on an AC zone by setting a temperature, it now picks HEAT or COOL based on whether the target is above or below the current temperature.

## [3.1.0] - 2026-03-14

**Options Flow Zone Configuration, Open Window Services, External Sensor Override & Entity Registry**

### Features
- **Open Window Services** ([#172](https://github.com/hiall-fyi/tado_ce/issues/172) - @driagi) — New `activate_open_window` and `deactivate_open_window` services let you trigger open window mode from your own window sensors (e.g., Zigbee contact sensors) instead of waiting 15+ minutes for Tado to detect it. A free Auto-Assist replacement via HA automations.
- **External Temperature & Humidity Sensors** ([#106](https://github.com/hiall-fyi/tado_ce/issues/106), [#143](https://github.com/hiall-fyi/tado_ce/issues/143) - @BirbByte) — Use any HA sensor (HomeKit, Zigbee, etc.) instead of Tado's built-in sensor for each zone. Configured in Zone Configuration.
- **Window Predicted Sensitivity** ([#135](https://github.com/hiall-fyi/tado_ce/issues/135) - @ChrisMarriott38) — Adjust how sensitive the open window prediction is per zone (Low, Medium, or High) to reduce false alarms.
- **Hub Control Switches** — New Test Mode and Quota Reserve switches on the hub device. Toggle them from your dashboard without going into Settings.
- **Options Flow Menu** — Settings are now organized into Global Settings and Zone Configuration sections for easier navigation.

### Improvements
- **Zone Configuration Moved to Options Flow** — All per-zone settings (overlay mode, timer, temperature limits, offsets, heating type, etc.) are now in one place under Settings → Configure → Zone Configuration. No more config entities cluttering your dashboard.
- **Renamed "Tado Mode" → "Tado Default"** ([#176](https://github.com/hiall-fyi/tado_ce/issues/176)) — The overlay mode name now matches what Tado calls it.
- **Entity Categories Added** ([#178](https://github.com/hiall-fyi/tado_ce/issues/178)) — Configuration and diagnostic entities are now properly categorized, so they're organized correctly in the HA UI.
- **Smarter Full Sync** ([#141](https://github.com/hiall-fyi/tado_ce/issues/141) - @Xavinooo) — Full data sync now only runs on HA restart instead of every 6 hours, saving API calls.
- **Test Mode & Quota Reserve Skip Reload** — Toggling these settings no longer restarts the integration.
- **Health Score Formatting** — Home Insights health score now shows with emoji and label (e.g., "🟢 92 — Excellent") for quick reading.
- **Improved Translations** — All 6 non-English languages revised with more natural wording. Service names and descriptions now translated in all 7 languages.

### Bug Fixes
- **Fixed AC Max Temperature Capped at 25°C** ([#180](https://github.com/hiall-fyi/tado_ce/issues/180)) — AC zones that support up to 30°C were incorrectly limited to 25°C. Now uses your AC's actual temperature range unless you've set a custom override.

## [3.0.4] - 2026-03-12

### Bug Fixes
- **Fixed API Reset Time Estimate Off by Hours** ([#173](https://github.com/hiall-fyi/tado_ce/issues/173) - @driagi) — The estimated API reset time was off by about 6 hours. Now calculates more accurately using your actual day/night schedule.
- **Fixed API Reset History Detection** ([#173](https://github.com/hiall-fyi/tado_ce/issues/173)) — History-based reset detection was silently failing. Added logging to help troubleshoot.
- **Fixed Smart Comfort Description** — The options flow description was listing the wrong sensors. Now correctly describes what's included.

### Improvements
- **Better Entity Cleanup** — Removing entities is now more accurate and won't accidentally remove the wrong ones.

## [3.0.3] - 2026-03-11

### Bug Fixes
- **Fixed Hub Sensors Stuck on Old Values** ([#173](https://github.com/hiall-fyi/tado_ce/issues/173) - @driagi) — Hub sensors (API Limit, Reset Time, Status, Polling Interval, Next Sync) were not updating after each sync. Now refreshes in real-time.

### Improvements
- **Better Feature Toggle Cleanup** — Disabling Weather or Mobile Device features now properly removes their entities and leftover devices.
- **Code Quality** — Fixed all strict type-checking issues across the codebase.

## [3.0.2] - 2026-03-11

### Bug Fixes
- **Fixed Setup Hanging for Minutes** ([#170](https://github.com/hiall-fyi/tado_ce/issues/170) - @driagi, @tigro7, @mpartington) — The integration could hang during setup for up to 80 minutes if you had old API call history. Now starts up normally.
- **Fixed Preheat Firing During Away Mode** ([#171](https://github.com/hiall-fyi/tado_ce/issues/171) - @thefern69) — Preheat was still triggering even when nobody was home. Now correctly pauses when you're away.
- **Fixed Hub Sensors Showing Wrong Values** ([#173](https://github.com/hiall-fyi/tado_ce/issues/173) - @driagi) — Polling interval and reset time sensors were showing defaults instead of actual values.
- **Fixed Performance Warning During Sensor Update** — Resolved a warning caused by slow file access during sensor updates.
- **Fixed Raw Values in Insights** — Home Insights were showing internal codes instead of readable names.

### Improvements
- **Smarter Preheat for Active Heating** ([Discussion #163](https://github.com/hiall-fyi/tado_ce/discussions/163) - @thefern69) — Preheat now also considers cooling trends for the current temperature target, not just the next schedule change. Especially helpful for underfloor heating.
- **Cleaner Insights Display** — Insights now show grouped, emoji-prefixed lines for easier reading.
- **Shorter Recommendations** — Per-zone recommendations no longer repeat the zone name.

## [3.0.1] - 2026-03-10

### Bug Fixes
- **Removed `[CE]` Prefix from Entity Names** ([#167](https://github.com/hiall-fyi/tado_ce/issues/167) - @jeverley) — Entity names no longer include the `[CE]` prefix. Entity IDs are unchanged.
- **Fixed Duplicate Sensor Names** ([#167](https://github.com/hiall-fyi/tado_ce/issues/167) - @hapklaar) — Zones with multiple devices (e.g., a sensor and two valves) now include the device type in battery and connection sensor names to avoid duplicates.
- **Fixed Entities Going Unavailable Every 5 Minutes** ([#167](https://github.com/hiall-fyi/tado_ce/issues/167) - @hapklaar, @andyb2000) — Token refresh was accidentally restarting the integration every poll cycle, briefly making all entities unavailable. Now handles token updates silently.
- **Fixed Missing Translations** — 3 translation keys added to all 7 language files.

## [3.0.0] - 2026-03-10

**Multi-Home Support & Actionable Insights**

### Features
- **Multi-Home Support** ([#110](https://github.com/hiall-fyi/tado_ce/issues/110) - @robvol87, [#145](https://github.com/hiall-fyi/tado_ce/issues/145) - @Blankf) — Run multiple Tado accounts or homes in a single HA instance. Each home is fully isolated with its own data and settings.
- **Smarter Insight Summaries** — Home insights now show action-based summaries (e.g., "Replace batteries: Guest, Lounge — Mold risk: Bedroom") instead of generic counts.
- **Related Insights Merged** — Related issues in a zone are combined into a single action item (e.g., mold risk + high humidity + condensation → "humidity problem").
- **Insight History & Trending** — Insights are tracked across HA restarts with duration-aware messages and a weekly digest.
- **Insight Priority Escalation** — Issues that persist automatically escalate in priority (e.g., low battery for over 7 days becomes high priority).
- **Home Health Score** — A 0-100 score reflecting your overall home health, shown on the Home Insights sensor.
- **Preheat Cooling Rate Prediction** ([Discussion #163](https://github.com/hiall-fyi/tado_ce/discussions/163) - @thefern69) — Preheat now considers cooling trends when the room is above target, estimating when it will drop below target for proactive heating.

### Improvements
- **Heating Rate Unit Fixed** — Sensor now correctly shows °C/h.
- **Timer Minimum Lowered to 1 Minute** ([#162](https://github.com/hiall-fyi/tado_ce/issues/162) - @joaomacp) — Climate and water heater timers now accept durations as short as 1 minute.
- **7-Language Support** — Config flow and options UI available in English, German, Spanish, French, Italian, Dutch, and Portuguese.

### Bug Fixes
- **Fixed Auth URL Showing 404** ([#104](https://github.com/hiall-fyi/tado_ce/issues/104)) — The authorization link during setup no longer leads to a broken page.
- **Fixed Window Sensor Not Working Without Auto-Assist** ([#157](https://github.com/hiall-fyi/tado_ce/issues/157) - @tanerpaca) — Window sensor now detects open windows even without an Auto-Assist subscription.
- **Fixed Preheat Triggering a Day Early** ([#164](https://github.com/hiall-fyi/tado_ce/issues/164) - @thefern69) — Preheat sensor no longer fires a day before it should.

## [2.3.1] - 2026-02-26

### Bug Fixes
- **Fixed AC Fan Speed Reverting on Some Brands** ([#142](https://github.com/hiall-fyi/tado_ce/issues/142) - @BirbByte) — Setting "High" fan speed on Mitsubishi/Fujitsu units would revert back. Fan speed options are now built from your AC's actual capabilities.
- **Fixed Startup Warning on Fresh Install** ([#127](https://github.com/hiall-fyi/tado_ce/issues/127) - @slflowfoon) — Resolved a warning that appeared on first install when the data folder didn't exist yet.

### Improvements
- **AC Capabilities Live Reload** — After pressing "Refresh AC Capabilities", AC entities update automatically without restarting HA.
- **Smarter AC Temperature Defaults** — Default temperature when switching modes now uses your AC's actual range instead of a fixed value.
- **Smoother AC Controls** — Fan and swing mode selections no longer flicker during updates.

---

## [2.3.0] - 2026-02-25

### Features
- **21 New Insight Types** — More actionable insights across zone efficiency, schedule, occupancy, weather, humidity, device health, and cross-zone analysis.

### Improvements
- **Flexible Climate Timer** ([#152](https://github.com/hiall-fyi/tado_ce/issues/152) - @mpartington) — `time_period` is now optional in the `set_climate_timer` service. Use `overlay: next_time_block` for "until next schedule change" or `overlay: manual` for indefinite.

### Bug Fixes
- **Fixed Mold Risk Giving Wrong Advice** ([#147](https://github.com/hiall-fyi/tado_ce/issues/147) - @ChrisMarriott38) — Mold risk no longer suggests turning up the heating when the room is already warm enough. Now suggests ventilation or a dehumidifier instead.
- **Fixed Hot Water Overlay Showing for Combi Boilers** ([#149](https://github.com/hiall-fyi/tado_ce/issues/149) - @ChrisMarriott38) — Overlay Mode and Timer Duration entities no longer appear for combi boiler hot water zones where they don't apply.
- **Fixed Mobile Device Tracker Not Updating** ([#150](https://github.com/hiall-fyi/tado_ce/issues/150) - @driagi) — Device tracker was stuck on the state from last HA restart. Now updates every 30 seconds.

---

## [2.2.3] - 2026-02-24

**Smart Day/Night Polling, AC Fan Fix & Climate Group Support**

### Bug Fixes
- **Fixed Polling Stuck at 120 Minutes for Low-Quota Users** ([#144](https://github.com/hiall-fyi/tado_ce/issues/144) - @mkruiver) — Users with few API calls left now get smart day/night polling instead of being stuck on very slow intervals.
- **Fixed Night Polling Using Wrong Interval** ([#141](https://github.com/hiall-fyi/tado_ce/issues/141) - @Xavinooo) — Day period quota now correctly accounts for your custom night interval setting.
- **Fixed AC Fan Speed Reverting** ([#142](https://github.com/hiall-fyi/tado_ce/issues/142) - @BirbByte) — Fan speed validation now checks against your AC's actual supported levels.

### Improvements
- **Climate Group Support** ([#139](https://github.com/hiall-fyi/tado_ce/discussions/139) - @merlinpimpim) — `set_climate_timer`, `set_water_heater_timer`, and `resume_schedule` services now work with climate groups defined in `configuration.yaml`.

---

## [2.2.2] - 2026-02-23

### Bug Fixes
- **Fixed API Polling Options Not Saving** ([#134](https://github.com/hiall-fyi/tado_ce/issues/134) - @Xavinooo) — Custom polling intervals now save correctly even when only one field is filled, and clearing a custom interval properly persists.

---

## [2.2.1] - 2026-02-23

### Bug Fixes
- **Fixed Hot Water Settings Missing for Tank Systems** ([#115](https://github.com/hiall-fyi/tado_ce/issues/115) - @jeverley) — Tank-based hot water users now correctly see Overlay Mode and Timer Duration controls.
- **Fixed Custom Polling Intervals Not Saving** ([#134](https://github.com/hiall-fyi/tado_ce/issues/134) - @ChrisMarriott38, @Xavinooo) — Custom polling intervals now save correctly after changing options.

---

## [2.2.0] - 2026-02-23

**Calibration Sensors & Actionable Insights**

### Features
- **Surface Temperature Sensor** ([#118](https://github.com/hiall-fyi/tado_ce/issues/118)) — Shows the calculated cold spot temperature in each zone, so you can calibrate mold risk with a laser thermometer.
- **Dew Point Sensor** ([#118](https://github.com/hiall-fyi/tado_ce/issues/118)) — Useful for dehumidifier automations and condensation prevention.
- **Window Predicted Sensor** ([Discussion #112](https://github.com/hiall-fyi/tado_ce/discussions/112) - @tigro7) — Detects open windows early by spotting unusual temperature drops, giving you a heads-up minutes before Tado's cloud detection kicks in.
- **Actionable Recommendations** ([Discussion #112](https://github.com/hiall-fyi/tado_ce/discussions/112) - @tigro7) — Environment, device, and hub sensors now include a `recommendation` attribute with specific advice.
- **Home Insights Sensor** ([Discussion #112](https://github.com/hiall-fyi/tado_ce/discussions/112) - @tigro7) — A hub-level sensor that aggregates insights from all zones with priority ranking.
- **Zone Insights Sensor** ([Discussion #112](https://github.com/hiall-fyi/tado_ce/discussions/112) - @tigro7) — Per-zone insights with an icon that changes based on the highest priority issue.

### Improvements
- **Readable Attribute Values** — Zone type, window type, and comfort model attributes now show human-readable names instead of internal codes.

### Bug Fixes
- **Fixed Long Heating Cycles Never Completing** ([#125](https://github.com/hiall-fyi/tado_ce/issues/125) - @BruceRobertson) — Heating cycles longer than 50 minutes now complete correctly.
- **Fixed First-Run Error** ([#127](https://github.com/hiall-fyi/tado_ce/issues/127) - @slflowfoon, [PR #132](https://github.com/hiall-fyi/tado_ce/pull/132) - @hacker4257) — Fixed an error on first install when the storage folder didn't exist yet.
- **Fixed Hot Water Settings Missing for Tank Systems** ([#115](https://github.com/hiall-fyi/tado_ce/issues/115) - @jeverley) — Tank-based hot water systems now correctly get Overlay Mode and Timer Duration controls.
- **Fixed Custom Polling Issues** ([#126](https://github.com/hiall-fyi/tado_ce/issues/126) - @Xavinooo) — Custom night interval, day/night detection, and settings persistence all fixed.
- **Fixed AC Swing Mode for Mitsubishi Units** ([#128](https://github.com/hiall-fyi/tado_ce/issues/128) - @BirbByte) — AC units that don't support "OFF" as a swing value no longer get API errors.
- **Fixed Environment Sensor Cleanup** — All sensors now correctly removed when the feature is toggled off.
- **Fixed Heating Anomaly False Alarms** — Heating anomaly insight no longer fires on every update.

---

## [2.1.1] - 2026-02-19

### Bug Fixes
- **Fixed Test Mode Using Wrong Reset Time** ([#120](https://github.com/hiall-fyi/tado_ce/issues/120), [#119](https://github.com/hiall-fyi/tado_ce/issues/119) - @ChrisMarriott38) — Test Mode polling intervals now calculate correctly.
- **Fixed Hot Water Zones Showing Wrong Entities** ([#115](https://github.com/hiall-fyi/tado_ce/issues/115) - @ChrisMarriott38) — Per-zone configuration controls (Surface Temp Offset, Min/Max Temp, etc.) no longer appear for hot water zones where they don't apply.

## [2.1.0] - 2026-02-18

**Per-Zone Configuration**

### Features
- **Per-Zone Overlay Mode** — Choose how long manual temperature changes last, separately for each zone (Tado Default, Timer, or Manual).
- **Per-Zone Timer Duration** — Set a custom timer duration per zone (15–180 minutes).
- **Per-Zone Thermal Analytics** ([#91](https://github.com/hiall-fyi/tado_ce/issues/91)) — Choose which zones have Thermal Analytics sensors. Zones that never call for heat can be turned off to keep your UI clean.
- **Per-Zone Surface Temp Offset** ([#90](https://github.com/hiall-fyi/tado_ce/issues/90)) — Calibrate mold risk calculation per zone using a laser thermometer reading.

### Bug Fixes
- **Fixed Preheat Time Showing `unknown` After Restart** — Preheat Time sensors now display correctly after HA restart.
- **Fixed Overlay Mode API Error** — Overlay termination now correctly maps to the Tado API.
- **Fixed Custom Polling Below 5 Minutes** ([#107](https://github.com/hiall-fyi/tado_ce/issues/107) - @jakeycrx) — Custom intervals of 1–4 minutes now work correctly.

### Improvements
- **Simplified Options UI** — Test Mode moved into the Tado CE Exclusive section for a cleaner layout.

## [2.0.2] - 2026-02-14

**Presence Mode Select & Configurable Overlay Mode**

### ⚠️ Breaking Changes
- **Presence Mode Select** — `switch.tado_ce_away_mode` has been replaced by `select.tado_ce_presence_mode` ([Discussion #102](https://github.com/hiall-fyi/tado_ce/discussions/102) - @wyx087). Update your automations from `switch.turn_on/turn_off` to `select.select_option`.

### Features
- **Presence Mode Select** — New 3-option select: Auto (resume geofencing), Home, or Away.
- **Configurable Overlay Mode** ([#101](https://github.com/hiall-fyi/tado_ce/issues/101) - @leoogermenia) — Choose how long manual temperature changes last: Tado Default, Next Time Block, or Manual (indefinite).

### Bug Fixes
- **Fixed Custom Polling Below 5 Minutes** ([#107](https://github.com/hiall-fyi/tado_ce/issues/107) - @jakeycrx) — Custom intervals of 1–4 minutes now work.
- **Fixed Polling Stuck at 120 Minutes** ([#99](https://github.com/hiall-fyi/tado_ce/issues/99) - @ChrisMarriott38) — Polling now calculates correctly when day and night hours are the same.

## [2.0.1] - 2026-02-12

**Mold Risk Percentage, Hot Water Fix & Bootstrap Reserve**

### Features
- **Mold Risk Percentage Sensor** ([#90](https://github.com/hiall-fyi/tado_ce/issues/90)) — New sensor for tracking mold risk over time in HA history.
- **Bootstrap Reserve Protection** ([#99](https://github.com/hiall-fyi/tado_ce/issues/99) - @ChrisMarriott38) — Reserves 3 API calls so the integration can always recover after a restart.
- **Test Mode** — Fully simulates the 100-call API tier with its own 24-hour cycle for testing.
- **Day/Night Aware Polling** — Uses fixed 120-minute intervals at night and adaptive intervals during the day based on remaining quota.

### Bug Fixes
- **Fixed Climate Entities Unavailable After Upgrade** ([#100](https://github.com/hiall-fyi/tado_ce/issues/100) - @Claeysjens)
- **Fixed Hot Water Temperature Jumping Back** ([#98](https://github.com/hiall-fyi/tado_ce/issues/98) - @ChrisMarriott38) — Temperature changes no longer revert in the UI.
- **Fixed Quota Reserve Not Preventing API Limit** ([#99](https://github.com/hiall-fyi/tado_ce/issues/99) - @ChrisMarriott38)
- **Fixed Mold Risk Calculation** ([#90](https://github.com/hiall-fyi/tado_ce/issues/90) - @ChrisMarriott38) — Now correctly uses room temperature for dew point calculation.
- **Fixed Thermal Analytics Missing for Some Zones** ([#91](https://github.com/hiall-fyi/tado_ce/issues/91) - @ChrisMarriott38) — Sensors now appear for all zones with heating data, not just TRV zones.

## [2.0.0] - 2026-02-09

**Smart Polling, Mold Risk Enhancement & Thermal Analytics**

### Features
- **API Monitoring Sensors** ([#86](https://github.com/hiall-fyi/tado_ce/discussions/86), [#65](https://github.com/hiall-fyi/tado_ce/issues/65)) — New sensors showing next sync time, last sync, polling interval, call history, and API breakdown.
- **Thermal Analytics** — New sensors for heating zones: thermal inertia, average heating rate, preheat time, and more.
- **Adaptive Smart Polling** ([#89](https://github.com/hiall-fyi/tado_ce/issues/89) - @ChrisMarriott38) — Polling frequency automatically adjusts based on your remaining API quota.
- **Quota Reserve Protection** ([#94](https://github.com/hiall-fyi/tado_ce/issues/94) - @ChrisMarriott38) — Pauses polling when your API quota is critically low to prevent hitting the limit.
- **Enhanced Mold Risk** ([#90](https://github.com/hiall-fyi/tado_ce/issues/90) - @ChrisMarriott38) — Surface temperature calculation with configurable window type for more accurate mold risk assessment.

### Bug Fixes
- Fixed hot water timer buttons not finding the right entity ([#93](https://github.com/hiall-fyi/tado_ce/issues/93) - @Fred224)
- Removed 'Tado CE' prefix from entity names

## [1.10.0] - 2026-02-05

### Bug Fixes
- **Fixed Climate Entity Flickering** ([#44](https://github.com/hiall-fyi/tado_ce/issues/44) - @hapklaar, @chinezbrun, @neonsp) — Climate entities no longer flicker or revert when you make changes. Multiple layers of protection prevent stale data from overwriting your actions.

## [1.9.7] - 2026-02-04
- Fixed state flickering when quickly changing modes ([#44](https://github.com/hiall-fyi/tado_ce/issues/44) - @chinezbrun)

## [1.9.6] - 2026-02-04
- Fixed heating/cooling status reverting after a mode change ([#44](https://github.com/hiall-fyi/tado_ce/issues/44) - @hapklaar, @chinezbrun)

## [1.9.5] - 2026-02-02
- Fixed heating/cooling status not updating when setting temperature ([#44](https://github.com/hiall-fyi/tado_ce/issues/44) - @hapklaar, @chinezbrun)

## [1.9.4] - 2026-02-02

**Boost Buttons**

### Features
- **Boost Button** — One tap to set any zone to 25°C for 30 minutes.
- **Smart Boost Button** — Intelligent boost that calculates the right duration automatically.

### Bug Fixes
- Fixed heating status stuck on "Heating" after switching to Auto ([#44](https://github.com/hiall-fyi/tado_ce/issues/44) - @hapklaar)
- Fixed AC startup warnings ([#44](https://github.com/hiall-fyi/tado_ce/issues/44) - @neonsp)
- Fixed slow zone sensor updates ([#44](https://github.com/hiall-fyi/tado_ce/issues/44) - @chinezbrun)

## [1.9.3] - 2026-02-02
- Fixed slow state updates for heating users ([#44](https://github.com/hiall-fyi/tado_ce/issues/44) - @hapklaar, @chinezbrun)
- Fixed AC DRY mode error ([#79](https://github.com/hiall-fyi/tado_ce/issues/79) - @Fred224, @neonsp)

## [1.9.2] - 2026-02-01
- Fixed grey loading state on climate card ([#44](https://github.com/hiall-fyi/tado_ce/issues/44) - @chinezbrun)

## [1.9.1] - 2026-01-31
- Fixed crash on startup during device migration ([#74](https://github.com/hiall-fyi/tado_ce/issues/74))

## [1.9.0] - 2026-01-31

**Smart Comfort Analytics + Environment Sensors**

### Features
- **Smart Comfort Analytics** — New sensors for heating/cooling rate, time to target, and heating efficiency.
- **Smart Comfort Insights** ([#33](https://github.com/hiall-fyi/tado_ce/discussions/33)) — Historical comparison, preheat advisor, and smart comfort target recommendations.
- **Environment Sensors** ([#64](https://github.com/hiall-fyi/tado_ce/issues/64)) — Mold risk and comfort level sensors for each zone.
- **Schedule Sensors** — Shows the next scheduled time and temperature for each zone.

### Bug Fixes
- Fixed API reset detection for the 100-call limit ([#54](https://github.com/hiall-fyi/tado_ce/issues/54))
- Fixed temperature offset for rooms with multiple TRVs ([#66](https://github.com/hiall-fyi/tado_ce/issues/66))
- Fixed sensors being assigned to the wrong device ([#56](https://github.com/hiall-fyi/tado_ce/issues/56))

## [1.8.3] - 2026-01-26
- AC capabilities are now cached to save API calls ([#61](https://github.com/hiall-fyi/tado_ce/issues/61) - @neonsp)
- New: Refresh AC Capabilities button to reload without restarting HA
- Fixed AC not responding immediately after turning on ([#44](https://github.com/hiall-fyi/tado_ce/issues/44) - @neonsp)

## [1.8.2] - 2026-01-26
- Smoother AC controls — selections no longer flicker during updates ([#44](https://github.com/hiall-fyi/tado_ce/issues/44) - @neonsp)
- Fixed Resume All Schedules taking too long to respond ([#44](https://github.com/hiall-fyi/tado_ce/issues/44) - @hapklaar)

## [1.8.1] - 2026-01-26
- Fixed AC instant feedback not working ([#44](https://github.com/hiall-fyi/tado_ce/issues/44) - @neonsp)
- Fixed Resume All Schedules not refreshing the UI ([#44](https://github.com/hiall-fyi/tado_ce/issues/44) - @hapklaar)

## [1.8.0] - 2026-01-26

**Schedule Calendar + Multi-Home Prep**

- New: Schedule Calendar — See your heating schedules as a calendar per zone
- New: Per-zone Refresh Schedule button
- New: API Reset sensor now shows extra details ([#54](https://github.com/hiall-fyi/tado_ce/issues/54) - @ChrisMarriott38)
- Multi-home preparation: data files are now stored per home

## [1.7.0] - 2026-01-26
- New: Instant UI feedback — changes show immediately without waiting for the next poll
- New: Optional home state sync to save API calls
- Multi-home preparation: unique ID migration

## [1.6.3] - 2026-01-25
- New: Uses HA history to detect API reset time more accurately

## [1.6.2] - 2026-01-25
- Fixed API call history not being recorded
- Fixed timezone issues in various sensors

## [1.6.1] - 2026-01-25
- Fixed API Usage and Reset sensors showing 0
- Added configurable delay between rapid updates

## [1.6.0] - 2026-01-25
- Faster API calls — migrated to native async (no more subprocess)
- Fixed database migration issue from older versions
- Fixed `climate.set_temperature` ignoring the mode you selected

## [1.5.5] - 2026-01-24
- Fixed AC Auto mode accidentally turning off the AC
- Reduced API calls when changing settings

## [1.5.4] - 2026-01-24
- Fixed all AC control issues (modes, fan speed, swing)
- Added unified swing dropdown for AC

## [1.5.3] - 2026-01-24
- New: Resume All Schedules button — one tap to reset all zones
- Fixed AC control errors

## [1.5.2] - 2026-01-24
- Fixed losing your login after a HACS upgrade

## [1.5.1] - 2026-01-24
- Fixed login errors for new users
- Added re-authenticate option in the UI

## [1.5.0] - 2026-01-24

**Async Architecture Rewrite**

- Faster API calls with async architecture
- New: Temperature offset service
- Full AC support — all modes, fan speeds, and swing options
- Hot water temperature control

## [1.4.1] - 2026-01-23
- Fixed login broken after upgrading

## [1.4.0] - 2026-01-23
- New: In-app login — no SSH or terminal needed
- Home selection for accounts with multiple homes

## [1.2.1] - 2026-01-22
- Fixed a rare startup issue with duplicate hub cleanup

## [1.2.0] - 2026-01-21

**Zone-Based Device Organization**

- Each zone now appears as its own device in HA
- Optional weather sensors
- Customizable polling intervals
- 60–70% fewer API calls

## [1.1.0] - 2026-01-19
- New: Away Mode switch
- New: Home/Away preset mode support

## [1.0.1] - 2026-01-18
- Fixed auto-detection of your home ID

## [1.0.0] - 2026-01-17
- Initial release
