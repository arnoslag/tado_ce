# Changelog

All notable changes to Tado CE will be documented in this file.

## [4.0.0-beta.15] - 2026-05-11

### Features
- **Offset Sync Sensitivity is now configurable per zone** ([Discussion #219](https://github.com/hiall-fyi/tado_ce/discussions/219) - @Si-Hill) — You can now control how much the offset must change before writing to the TRV. Higher values mean fewer writes (better for battery life) but less precise temperature display in the Tado app. Adjust in **Settings → Tado CE → Configure → Zone Configuration → External Sensors → Offset Sync Sensitivity** (0.5–3.0°C, default 0.5°C). Only appears when Offset Sync mode is selected.

### Bug Fixes
- **Fixed `set_temperature_offset` service silently succeeding when every device rejected the write** — If all TRVs in a zone were offline or the write failed for every device, the service call still completed as "successful" and updated the HA cache. Automations reading back `offset_celsius` saw stale data and sync controllers were paused on a write that never landed. The service now raises an error visible in the HA UI when no devices accept the write.
- **Fixed target temperature briefly reverting to the old value after you change it** — When you set a new target on a climate card, the UI showed your new temperature instantly — but the next cloud poll (≤ 1 poll cycle later) could reset the display to the previous value before the API had finished propagating your change. The card now preserves your set temperature until the API confirms it.
- **Fixed timer service calls failing silently when every zone rejected the write** — `set_climate_timer` and `set_water_heater_timer` used to swallow per-zone failures and report overall success even when no timer was actually set. The services now raise an error when every zone fails and log a warning for partial failures so you can see what happened. Also covers the case where the entity layer catches a timeout or API error internally — those now propagate as failures instead of being silently reported as success.
- **Fixed Offset Sync being blocked for hours after restarting Home Assistant** ([#221](https://github.com/hiall-fyi/tado_ce/issues/221) - @simonotter) — If Home Assistant had been running for a while before a restart, Offset Sync could refuse to write any new offsets for as long as the previous uptime (e.g. 3 days of uptime → 3 days of no writes). The rate-limit timer is no longer persisted across restarts, so Offset Sync resumes normally after any reboot.
- **Fixed Smart Valve Control overwriting manual TRV adjustments made shortly after a Home Assistant restart** — After an HA restart, manually turning a TRV from the Tado app or on the device could be overwritten by Smart Valve Control within minutes. The manual-override grace-period timer is no longer persisted across restarts, so legitimate manual changes are detected correctly.
- **Fixed Offset Sync silently suppressing future corrections when the write queue was full** — If every device offset write was dropped due to a full queue, Offset Sync would still update its internal state as if the write had succeeded, leaving the TRV stuck on the old value until an external temperature change exceeded the threshold again. All state updates are now skipped when no write actually reaches the queue.
- **Fixed offset service call racing with Offset Sync** — Using the `set_temperature_offset` service while Offset Sync was active could briefly fight the service caller before the sync controller recognised the manual write. The sync controller is now notified before the refresh fires, so the pause window is in effect immediately.
- **Fixed Smart Valve Control not following external sensor switches** — Selecting a different external temperature sensor for a zone did not re-bind the real-time update subscription, so state changes on the new sensor were silently ignored until the next poll. The sensor subscription is now recreated on every sensor change.
- **Fixed Smart Valve Control continuing to run after its external sensor was removed** — Clearing the external sensor for a zone left the controller running but unable to do anything useful. Now the controller is automatically deactivated and a repair notification is raised so you know why the feature stopped working.
- **Fixed orphan sensor subscriptions from rapid Smart Valve Control mode changes** — Switching Smart Valve Control mode twice in quick succession (e.g. off → offset_sync → valve_target) could leave sensor subscriptions from the first mode alive until the integration reloaded. All controller lifecycle transitions are now serialized per zone.
- **Fixed climate entity temperature not updating to frost protection (5°C) after `set_hvac_mode: off`** ([#258](https://github.com/hiall-fyi/tado_ce/issues/258) - @Newreader) — After turning off a zone, the climate card kept showing the previous heat target (e.g. 23°C) while Tado was actually running frost protection at 5°C. Now shows 5°C to match what Tado has applied.
- **Fixed HomeKit overwriting frost protection temperature with stale target** ([#258](https://github.com/hiall-fyi/tado_ce/issues/258) - @apilone) — With HomeKit connected, the frost protection fix would briefly show 5°C then revert to the old target (e.g. 19.5°C) and oscillate. The HomeKit bridge reports the last heating target even when the zone is OFF — the integration now skips HomeKit target temperature and mode merging when the zone is in OFF mode.
- **Fixed zone flipping back to heating after turning off** — When a zone was off via the cloud, the HomeKit bridge could still push a stale "heating" state a few minutes later and flip the climate card back to HEAT even though the zone was actually off. The mode gate now matches the target temperature gate for OFF mode.
- **Fixed HomeKit overwriting temperature and mode after any local change** ([#253](https://github.com/hiall-fyi/tado_ce/issues/253) - @apilone) — After changing temperature or HVAC mode, the HomeKit bridge could push a stale cached value that overwrote your change within seconds. The integration now respects a 3-minute write protection window after any HomeKit write — during this window, the bridge's stale target temperature and mode are ignored until the cloud confirms the actual state.
- **Fixed cloud temperature/mode changes getting overwritten by HomeKit bridge** — If HomeKit was connected but a write went via the cloud API (e.g. HomeKit timed out), the bridge could push a stale value back within seconds, undoing your change. Cloud writes now trigger the same write protection window as HomeKit writes.
- **Fixed integration going unavailable if a storage file is corrupt** — If one of several auxiliary storage files (weather compensation, bridge health, HomeKit savings, window detection state, or the state-restore file) got corrupted after a crash or SD card issue, every entity would go unavailable until you manually deleted the file. The integration now logs a warning and continues with defaults, and the next successful save heals the file automatically.
- **Fixed Offset Sync and Smart Valve Control failing to recover from a manually-edited state file** — If the per-zone state file was hand-edited or left over from an older schema with a non-numeric value where a number was expected (e.g. a missing value became the literal string `null`), the affected controller could silently stop evaluating or crash on its next write. The load path now validates each numeric field and falls back to a clean state (Offset Sync re-reads the current offset from the API; Smart Valve Control resets to idle) if anything is malformed, with a warning in the log.
- **Fixed HomeKit event callbacks firing multiple times after a reconnect** — Each time the HomeKit bridge reconnected, the previous event callback was left alive instead of being torn down. After N reconnects, every bridge event triggered N+1 duplicate state updates — inflating write-counter metrics and causing redundant dispatcher signals. Reconnect now properly unsubscribes the old callback before installing a new one.
- **Fixed Offset Sync oscillating every 5 minutes** ([Discussion #219](https://github.com/hiall-fyi/tado_ce/discussions/219) - @Si-Hill) — After writing a device offset, the next evaluation would use a stale cached offset value for its calculation, producing a different result each cycle. The offset cache is now updated immediately after a successful write, so subsequent evaluations use the correct baseline.
- **Fixed Offset Sync writing offsets when heating is OFF (TRV motor noise)** ([Discussion #219](https://github.com/hiall-fyi/tado_ce/discussions/219) - @Si-Hill) — When the schedule was OFF or overnight, Offset Sync would still write device offsets whenever the external sensor changed. The TRV physically recalibrates its motor on every offset change, causing noise while the valve is closed. Offset Sync now only writes when the zone is actively heating.
- **Fixed heating cycle history being pruned too aggressively** — If you set the heating cycle history window to more than 7 days (e.g. 30 days), cycles older than 14 days were still being deleted. The cleanup now respects your configured window (keeps 2× your setting).
- **Fixed token refresh permanently invalidating your login on a single server error** — If Tado's servers returned a transient 401 during token refresh (server glitch, not a real auth failure), the integration would delete your refresh token and force you to re-authenticate. It now lets HA's built-in reauth flow handle it — if the token is truly invalid, you'll be prompted to log in again; if it was a glitch, the next refresh succeeds normally.
- **Fixed rate limit countdown showing wrong time after Tado sends a Retry-After header** — If Tado's API told you exactly how long to wait (via a "Retry-After" header), a subsequent successful request would accidentally clear that information. The countdown sensor now preserves the server's instruction until it's consumed.
- **Fixed Weather Compensation target getting permanently stuck on Unknown overnight** ([#249](https://github.com/hiall-fyi/tado_ce/issues/249) - @driagi) — If the gap between two evaluations exceeded 60 minutes — which happens naturally with the auto night-polling interval (120 minutes) or any custom interval ≥ 60 min — the engine would latch into "paused" forever, even though your outdoor temperature source was reporting fresh values the whole time. Once latched, the only way out was to reload the integration (which is why it tended to "fix itself" mid-morning when you interacted with HA). The culprit was a redundant "stale reading" guard that measured time between evaluations instead of staleness of the outdoor data; it's been removed since the existing grace-period already handles the case it was trying to cover. Weather Compensation now stays active across long night-polling gaps.

### Improvements

_Options Flow reorganisation_

- **General Settings reorganised by feature origin** — The toggles in **Settings → Tado CE → Configure → General Settings** are now grouped by what they actually do: **Tado Features** (Home Presence, Weather Data, Mobile Device Tracking, Schedule Calendar, Device Temperature Offsets — things Tado supports natively), **Hardware Connections** (Internet Bridge, HomeKit), **Smart Automations** (Smart Comfort, Thermal Analytics, Adaptive Preheat, Weather Compensation — enhancements Tado CE adds on top), and **Advanced** (Per-Zone Configuration). No toggles were removed or renamed — existing configurations continue to work unchanged.
- **Zone Configuration now flows from fundamentals to runtime overrides** — The per-zone settings form reorders sections to match how you actually think about a zone: **Temperature Limits** first, then **Heating System** (radiator vs UFH, Adaptive Preheat), then **External Sensors** (override Tado's built-in sensors, Smart Valve Control), then **Smart Features** (Smart Comfort mode, window detection), and finally **Manual Temperature Override**. Temperature Limits and Heating System are expanded by default; the rest start collapsed. The "Overlay" section is also renamed to "Manual Temperature Override" — same fields, clearer label. Existing entity IDs (`select.tado_ce_overlay_mode`, `select.tado_ce_overlay_timer_duration`) are unchanged so automations continue to work.
- **Smart Valve Control now surfaces the recommended mode in the UI** — The SVC mode selector now shows **Offset Sync (recommended)** before **Valve Target (advanced)**, matching the long-standing guidance that Offset Sync is the starting point for most setups. The inline description explains the difference clearly: Offset Sync quietly corrects the TRV's temperature reading and works alongside Tado's own algorithm; Valve Target directly overrides the TRV setpoint and is only needed when Offset Sync isn't enough. Clearing the external temperature sensor while SVC is active now shows an inline error pointing at the safer alternative (set SVC Mode to Off first) instead of silently deactivating the controller.
- **External sensor toggles renamed for clarity** — "Use External Temperature/Humidity Sensor" → **"Override Tado's Temperature/Humidity Sensor"**, with descriptions that explain turning off the toggle keeps your sensor selection saved, letting you pause without losing the configuration.
- **Smart Comfort, Weather Compensation, and Polling & API now guide you to a working starting point** — Enabling Smart Comfort for the first time now defaults the mode to **Light** instead of **None** (previously, enabling the feature left it doing nothing). Weather Compensation's Heating System preset dropdown now documents that it auto-sets slope + flow temperatures, and the affected fields note "auto-adjusted by heating system preset above" so values changing after a preset switch isn't surprising. Custom day/night polling interval fields now explicitly say "leave empty for auto" so reverting to automatic polling is obvious. Several other tuning descriptions (Smart Comfort Mode, window detection sensitivity, surface temperature offset) rewritten to explain what the field does in user-visible terms.
- **Hot Water Timer default moved to Polling & API** — The default duration for the `water_heater.turn_on` service was tucked away under Smart Comfort where it didn't belong. Now lives in **Advanced Settings → Polling & API** next to the other service defaults. The config key is unchanged — no reconfiguration needed. Resetting "Polling & API" now clears this field; resetting "Smart Comfort" no longer touches it.
- **Authentication flow has better guidance** — The manual token auth step (used when device authorization doesn't work) now includes explicit steps to find the refresh token in your browser's DevTools. The multi-home selector now explains that each home becomes its own integration entry.

_Data integrity & privacy_

- **Per-zone temperature limits are now clamped at save** — Values written via YAML import or direct Store edits that bypass the UI's number selector (min_temp, max_temp, surface_temp_offset, timer_duration, Offset Sync sensitivity) are now clamped to their valid ranges before being persisted. If min_temp and max_temp end up inverted (e.g. min=25, max=10 from a hand-edit), they are swapped so the saved config matches what the UI would have enforced. Defense in depth — the UI was already enforcing these limits, but hand-edits could slip past.
- **Heating anomaly durations and humidity trends now survive restarts** — The "heating anomaly for 3 days" and humidity rising / falling indicators on the Home Insights sensor used to reset to zero after every HA restart. They now persist across restarts, so your Home Insights dashboard shows continuous history.
- **Zone insight durations keep updating even if you disable the "Home Insights" sensor** — Duration tracking ("low battery for 3 days") used to silently stop if the home-level insights sensor was disabled in HA's entity registry. It now runs in the coordinator so all zone sensors keep showing accurate durations regardless.
- **Insight history survives zone renames** — Humidity trend and heating anomaly history is now tracked by internal zone ID instead of zone name. Renaming a zone in the Tado app no longer discards accumulated history.
- **Target temperature is preserved during the optimistic window** — After setting a new target on a climate card, the optimistic-state resolver now tracks the target alongside HVAC mode and action. The card keeps showing your new target until the API confirms it instead of briefly reverting to the old value on the next poll.
- **Device serial numbers are now masked in entity attributes** — Battery sensors, connection sensors, and device tracker entities previously exposed full device serial numbers in their state attributes. These are now truncated for privacy (same masking used in logs).
- **Adaptive Preheat and other zone-name lookups now work with non-ASCII zone names** — If your Tado zones have accented characters, dashes, or special characters in their names (e.g. "Büro", "Salle-à-manger"), Adaptive Preheat, water heater resume buttons, and thermal analytics would silently fail to find the matching entities. All zone-name-to-entity-ID conversions now use HA's standard method.

_Smart Valve Control & Offset Sync_

- **Warning when a device offset is set while Smart Valve Control is active** — The `set_temperature_offset` service call now logs a warning if the zone is using the valve_target Smart Valve mode with a non-zero offset. Smart Valve Control can't compensate correctly when the TRV's built-in sensor is offset-adjusted, so this flags the double-compensation condition clearly when it happens.
- **Offset Sync `valve_control_active` attribute now reflects actual runtime state** — The attribute used to always return `true` whenever a zone was configured for Offset Sync, even while the controller was paused after a manual offset write. It now correctly returns `false` during pause windows so dashboards show the real status.
- **Temperature offset service now validates range** — The `set_temperature_offset` service now rejects values outside ±10°C at the schema level instead of sending them to the API and waiting for rejection.

_HomeKit & auth resilience_

- **HomeKit now tracks heating/cooling state from the bridge** — A latent bug prevented the HomeKit bridge from reporting whether a zone was actively heating or idle. If you have HomeKit connected, the integration now receives real-time heating state changes from the bridge alongside temperature and humidity.
- **Token refreshes less often when your token is valid for longer** — The integration was refreshing your Tado access token every 5 minutes even though Tado issues them for roughly 10 minutes. It now reads the actual expiry time from Tado's response and only refreshes when the token is about to expire — roughly halving the number of auth calls.
- **Temperature changes survive a transient token rotation mid-request** — When Tado's auth servers rotate a session mid-request, the API returns a 401. Read requests already retried with a fresh token; writes (temperature / mode / schedule resume) now do too — a single server glitch no longer fails a user-initiated change.

_Performance & storage_

- **Reduced storage writes for insight history** — The insight history file was being written once per polling cycle (up to 2,880 writes/day with 30-second polling). Writes are now debounced to once per minute, reducing SD card wear on Home Assistant OS installs without any loss of data on shutdown.
- **API call history attributes are now capped to 10 entries** — The API usage, limit, and call history sensors used to expose up to 100 entries each in their attributes, which bloated the recorder database over time. Dashboards only show the most recent few anyway, so the attributes are now capped to 10 entries.
- **Preheat time sensor no longer has side effects when read** — The preheat time estimate sensor was computing its value inside a property getter, which could produce inconsistent readings if HA's recorder and frontend read it simultaneously. Computation is now done once per coordinator update.
- **Less CPU work per poll on homes with many zones** — Zone insights are now computed once per polling cycle by the coordinator and cached for every zone sensor + the home sensor to read, instead of each sensor collecting independently. The Home Insights sensor also caches its formatted attributes inside `update()` instead of rebuilding them on every dashboard template evaluation.

_Log output_

- **Log messages rewritten to be clearer** — Swept through the log output and rewrote messages that could confuse users reading their logs. Replaced internal terms ("backed-off", "bang-bang fallback", "optimistic state expired", "ROLLBACK") with plain-English equivalents that explain what happened and, where relevant, what the user can do. Affects Smart Valve Control, Offset Sync, climate, and water heater log output.
- **Smart Valve Control evaluation logging reduced** — The per-evaluation diagnostic log line has been moved from info to debug level, reducing log noise for users with many zones.
- **Offset Sync per-evaluation diagnostic log** — Added a debug log line per evaluation showing the key inputs: schedule power state, target, external sensor reading, TRV reading, current offset, desired offset, and minimum-change threshold. Makes it possible to verify the controller is evaluating as expected during any schedule block (e.g. the overnight 17°C block) without needing to enable more verbose logging.

## [4.0.0-beta.14] - 2026-05-07

### Features
- **Offset Sync — a new Smart Valve Control mode that corrects your TRV's temperature reading** ([#221](https://github.com/hiall-fyi/tado_ce/issues/221) - @simonotter) — Instead of adjusting the TRV's target temperature (what Valve Target mode does), Offset Sync writes a device temperature offset so the Tado app displays your external sensor's reading. With accurate temperature data, Tado's own modulation algorithm works correctly without needing external compensation. Choose between Off, Valve Target, and Offset Sync in **Settings → Tado CE → Configure → Zone Configuration → External Sensors → Smart Valve Control Mode**. The two active modes are mutually exclusive — you pick one per zone.

### Bug Fixes
- **Fixed Weather Compensation target showing "Unknown" after restarts and brief weather service outages** ([#249](https://github.com/hiall-fyi/tado_ce/issues/249) - @driagi) — If your outdoor temperature source was briefly unavailable (even for a single poll cycle during an HA restart), the Weather Compensation engine immediately paused and the flow temperature target went blank. It now holds the last known outdoor temperature for up to 30 minutes before pausing, so brief gaps no longer interrupt your heating curve.
- **Fixed Smart Valve Control showing excessive decimal places in the valve target attribute** ([pulse-card#45](https://github.com/hiall-fyi/pulse-card/issues/45) - @Si-Hill) — The `valve_target` attribute on your climate card could show values like `18.700000000000003°C` instead of `18.7°C`. This was a floating point arithmetic artifact from the offset calculation. Both Smart Valve Control and Offset Sync now round to 0.1°C precision (matching what Tado's API accepts).
- **Fixed Smart Valve Control overriding your schedule when it switches to OFF** ([#251](https://github.com/hiall-fyi/tado_ce/issues/251) - @Si-Hill) — If you had Smart Valve Control active on a zone and the Tado schedule switched to OFF (e.g. bedroom heating turns off at 8am), the controller kept heating the zone anyway. The Tado app showed "Frost protection" correctly, but HA showed the zone still heating at the old target. The controller now checks for schedule changes while active — it stops immediately when the schedule goes to OFF, and picks up the new target if the schedule changes to a different temperature.
- **Fixed Smart Valve Control crashing the integration on startup** ([#252](https://github.com/hiall-fyi/tado_ce/issues/252) - @wrowlands3) — If a zone with Smart Valve Control had its schedule set to OFF, the overlay data from Tado's API contained a null temperature value. The controller didn't handle that and crashed during startup, preventing the entire integration from loading. Fixed across all overlay reads.
- **Fixed HomeKit not updating target temperature or mode when changed in the Tado app** ([#253](https://github.com/hiall-fyi/tado_ce/issues/253) - @apilone) — If you changed the temperature or switched between heating/off in the Tado phone app, the climate card in HA wouldn't update for several minutes (until the next cloud API poll). The HomeKit bridge was receiving the changes instantly, but only the room temperature reading was being applied — the target temperature and mode were ignored. Now both update within seconds of the change.

### Improvements
- **Smart Valve Control now reports its state even when idle** ([pulse-card#45](https://github.com/hiall-fyi/pulse-card/issues/45) - @Si-Hill) — Zones with Smart Valve Control enabled now expose a `valve_control_enabled` attribute so your dashboard card can distinguish "SVC is on but not intervening" from "SVC is not configured". Pulse Card will use this to optionally show a subtle idle indicator.
- **Smart Valve Control logging is now visible without debug mode** — Initialization, evaluation summaries, and errors are now logged at info level so you can see what the controller is doing in **Settings → System → Logs** without enabling debug logging.
- **Your bridge serial number is now redacted from diagnostics** — If you share diagnostics for a bug report, your bridge serial is now hidden alongside other sensitive data. Previously it was exposed in the options dump.
- **Diagnostics downloads now redact additional sensitive fields** — Extra Tado API response fields are scrubbed from the diagnostics dump as defense-in-depth, so sharing a diagnostics bundle is safer by default.
- **Offset Sync zones now report their status to your dashboard card** — Offset Sync now publishes a status attribute so Pulse Card can show "offset sync active" instead of treating it as unconfigured.
- **Offset Sync reacts more smoothly to noisy external sensors** — Rapid bursts of sensor updates are now batched rather than triggering an evaluation on every single reading, reducing unnecessary processing on homes with chatty external sensors.
- **Offset data is now persisted after every write** — Previously persistence happened only when the controller deactivated, so a crash between writes could lose the most recent offset. Each write now schedules a save immediately (the zone config file still coalesces saves with a 5-second debounce for SD card wear, but no write goes un-scheduled).
- **Token refresh retries no longer discard your access token between attempts** — Fewer unnecessary re-authentications when Tado's servers are slow.

### Known Issues
- **"register_detection_callback() is deprecated" warning in logs** — If you have HomeKit enabled, you may see a deprecation warning from `habluetooth.wrappers` pointing at `homekit_client.py`. This comes from the `aiohomekit` library's internal BLE scanning code, not from Tado CE. It does not affect functionality — HomeKit works normally. The warning will disappear when `aiohomekit` releases an update. You can safely ignore it.

## [4.0.0-beta.13] - 2026-05-02

### Features
- **Integration now fires a `tado_ce_ready` event after startup** ([#246](https://github.com/hiall-fyi/tado_ce/issues/246) - @Newreader) — If you have automations that need to act on Tado CE entities right after HA starts, you can now trigger on the `tado_ce_ready` event instead of guessing timing with delays or `wait_template` chains. The event fires once all climate entities have real data from the API — temperature, offset, overlay mode, everything. The event payload includes `home_id`, `entry_id`, and `zone_count` for multi-home filtering.

### Bug Fixes
- **Fixed Smart Valve Control cloud writes silently failing every cycle** ([#221](https://github.com/hiall-fyi/tado_ce/issues/221) - @simonotter) — If you had Smart Valve Control enabled on a zone without HomeKit, the controller would try to adjust your TRV via the cloud API every 5 minutes but fail every time with "cloud write failed" in the logs. The API request was missing a required field, so Tado's servers rejected it. Your TRV was never actually adjusted despite the controller being active. Fixed — cloud writes now go through correctly.
- **Fixed setup failing with a misleading "Authorization failed" error when Tado's API is rate limiting** ([#246](https://github.com/hiall-fyi/tado_ce/issues/246) - @Newreader) — If Tado's servers returned HTTP 429 (Too Many Requests) during the initial setup or re-authentication, the config flow showed "Authorization failed" or "Failed to connect" — neither of which was true. The setup now retries automatically with backoff, and if the rate limit persists, shows a clear message telling you to wait a few minutes before trying again.
- **Fixed presence changes not reaching climate cards** ([Discussion #219](https://github.com/hiall-fyi/tado_ce/discussions/219) - @dragorex71) — When you changed presence to Away via the Tado CE Hub select (or a climate card's preset dropdown), the API call went through but the climate cards snapped back to "Home" within seconds. The integration was injecting the new state correctly, but the automatic refresh that fires right after was overwriting it with stale cached data. Both the Hub select and climate card preset paths now update the internal cache so the refresh reads the correct value.
- **Fixed presence mode showing different labels on the Hub select and climate cards** ([Discussion #219](https://github.com/hiall-fyi/tado_ce/discussions/219) - @dragorex71) — If you run HA in a non-English language, the Tado CE Hub presence select showed one translation (e.g. "Casa" / "Via" in Italian) while the climate card's preset mode showed a different one ("In casa" / "Fuori casa"). The presence labels now match what HA uses on climate cards across all 6 supported languages.

### Improvements
- **Smart Valve Control now warns when zone data is missing during evaluation** — Previously the controller silently skipped the evaluation. If you have SVC enabled and it appears idle, the log will now tell you why.
- **Diagnostics now redacts more Tado API PII fields** — Defense-in-depth for sharing diagnostics bundles — a wider set of sensitive fields is scrubbed from the dump.
- **Fewer spurious re-authentications during transient 403 retries** — When the Tado API throws a transient 403, the integration now retries with the existing access token instead of discarding it after every attempt, so a flaky response doesn't cost you an extra auth round-trip.

## [4.0.0-beta.12] - 2026-04-28

### Bug Fixes
- **Fixed overlay mode not being respected when changing HVAC mode** ([Discussion #219](https://github.com/hiall-fyi/tado_ce/discussions/219) - @mpartington) — If you set your overlay mode to "Manual" (or any non-default mode) and then used `climate.set_hvac_mode` to turn heating on or off, the override would still expire based on whatever Tado's servers remembered from the app. This happened because the HomeKit local write path doesn't carry overlay termination information — it just tells the TRV to turn on or off, and Tado's servers decide the rest. Now, when your overlay mode is anything other than "Tado Default", the integration skips the HomeKit path and uses the cloud API where the termination type is sent explicitly. Per-zone overlay mode settings in **Settings → Tado CE → Configure → zone → Overlay section** are now respected.
- **Fixed climate entities stuck at null temperature for up to 3 hours after HA restart** ([#246](https://github.com/hiall-fyi/tado_ce/issues/246) - @Newreader) — If an automation fired during startup and wrote to a climate entity before the first API sync completed, the entity would be marked as "fresh" with no data. The freshness check then blocked subsequent updates from populating the entity, leaving `current_temperature`, `heating_power`, and `offset_celsius` at null until the freshness expired. The freshness check now allows updates through when an entity has no data yet, regardless of the freshness timestamp.
- **Fixed "Invalid repairs platform" error on startup** ([#221](https://github.com/hiall-fyi/tado_ce/issues/221) - @simonotter) — HA was trying to register our repairs helper module as a repairs platform, which requires a specific interface we don't implement. Renamed the module so HA no longer auto-discovers it.
- **Reduced misleading "config file not found" warning on startup** ([#246](https://github.com/hiall-fyi/tado_ce/issues/246) - @Newreader) — A warning appeared in the logs on every HA restart saying the config file wasn't found and suggesting re-authentication. The config data is fetched on the first API sync a few seconds later, so the warning was harmless but confusing. Downgraded to debug level with a clearer message.

### Improvements
- **Smart Valve Control now logs what's happening during startup** ([#221](https://github.com/hiall-fyi/tado_ce/issues/221) - @simonotter) — If the controller can't start (missing zone data, no external sensor configured), you'll now see a clear warning in the logs explaining why. After initialization, an info-level summary shows how many controllers were activated.

## [4.0.0-beta.11] - 2026-04-27

### Bug Fixes
- **Fixed Smart Valve Control temperature escalation caused by feedback loop** — When Smart Valve Control was actively adjusting a zone, it would re-read the temperature overlay it had just written and treat it as the user's desired temperature. Each evaluation cycle compounded the error, causing the valve target to climb toward the zone's maximum temperature. The controller now captures your desired temperature when it starts adjusting and uses that stored value for all calculations, preventing the runaway escalation.
- **Fixed Smart Valve Control cloud writes ignoring your overlay mode setting** — When Smart Valve Control fell back to cloud writes (no HomeKit available), it always set the overlay to "Manual" mode regardless of your zone's overlay mode configuration. If you had "Next Time Block" or "Timer" mode configured, the override would persist indefinitely instead of expiring as expected. Cloud writes now respect your per-zone overlay mode setting.
- **Fixed Smart Valve Control backing off immediately after a HomeKit write** — After writing a temperature adjustment via HomeKit, the controller would check the cloud overlay data within seconds. Since HomeKit writes take up to 60 seconds to sync to Tado's cloud, the overlay still showed the old temperature, and the controller mistakenly thought you had manually changed it. There's now a 60-second grace period after each write before checking for manual overrides.
- **Fixed Smart Valve Control allowing valve targets above 30°C** — If a zone's maximum temperature was configured above 30°C (which shouldn't normally happen but could via manual config editing), the valve target could exceed 30°C. There's now a hard safety cap at 30°C regardless of zone configuration.
- **Fixed presence mode not syncing to climate entities when Home State Sync is disabled** ([Discussion #219](https://github.com/hiall-fyi/tado_ce/discussions/219) - @dragorex71) — When you changed presence to Away (from the Tado CE Hub select or a climate card's preset dropdown), the API call went through but the climate entities' `preset_mode` stayed on "home". This happened because the integration only fetched the home state from Tado's servers when Home State Sync was enabled. The integration now updates all climate entities and the presence select locally after a successful presence change, without needing an extra API call or the Home State Sync toggle.

### Improvements
- **Smart Valve Control now uses real-time TRV readings when HomeKit is connected** — Previously, the controller always used cloud-polled TRV temperatures, which could be 5–30 minutes stale depending on your polling interval. It now uses the same HomeKit real-time data that your climate entities show, so valve target calculations respond to temperature changes within seconds instead of waiting for the next cloud poll.

## [4.0.0-beta.10] - 2026-04-25

### Bug Fixes
- **Fixed bridge sensors (wiring state, boiler temperature, etc.) showing "unavailable" after HA restart** — The bridge API sensors rely on data from the bridge poll loop, but the poll loop started as a background task that raced with the sensor platform setup. If the first bridge fetch hadn't completed by the time sensors were created, they'd never get data and stay unavailable until the next full reload. The first bridge fetch now runs synchronously during startup so the data is ready before sensors are created.
- **Fixed translated placeholder names in 6 language files causing HA startup errors** — DeepL had translated placeholder names inside curly braces (e.g. `{zone_name}` became `{nome_zona}` in Italian, `{Dauer}` in German). HA requires placeholder names to match the English source exactly. Fixed across German, Spanish, French, Italian, Dutch, and Portuguese.
- **Fixed Smart Valve Control getting permanently stuck after a manual temperature change** ([#221](https://github.com/hiall-fyi/tado_ce/issues/221) - @simonotter, [Discussion #219](https://github.com/hiall-fyi/tado_ce/discussions/219) - @wrowlands3) — If you changed the temperature manually (from HA, the Tado app, or an automation) while Smart Valve Control was active, the controller would back off and wait for the next Tado schedule block change before resuming. But if your Tado schedule blocks were all set to OFF (common when using HA automations instead of Tado schedules), the controller would never detect a schedule change and stay backed off permanently. It now also watches for overlay changes — when your automation sets a new temperature or resumes the schedule, the controller picks up and starts adjusting again.
- **Fixed Smart Valve Control leaving a stale temperature override after HA crash** — If HA crashed or lost power while Smart Valve Control had an active temperature override on a zone, the override would persist on Tado's servers indefinitely. On restart, the zone could be stuck at whatever temperature the controller last wrote. The controller now detects and cleans up stale overrides from a previous session on startup.

### Improvements
- **Device and bridge serial numbers are now masked in logs** — All log messages that previously showed full serial numbers (bridge serial, TRV serials, HomeKit mapping) now show only the first 6 characters followed by "…". This prevents accidental exposure of bridge credentials when sharing debug logs — the bridge serial is printed on the device and the auth code is only 4 digits, so a full serial in a shared log could enable brute-force access.
- **Smart Valve Control now warns if your TRV has a temperature offset** ([#221](https://github.com/hiall-fyi/tado_ce/issues/221) - @simonotter) — If you enable Smart Valve Control on a zone where the TRV still has a non-zero temperature offset (from a previous automation or manual setting in the Tado app), the controller's compensation would stack on top of the existing offset, causing the room to overshoot. The controller now checks for this on startup and logs a warning telling you to reset the offset to zero.
- **Smart Valve Control now logs what it's doing in your normal logs** — State changes (activating, backing off, resuming), temperature writes, and schedule resumes now appear at info level instead of debug. You no longer need to enable debug logging to see whether the controller is working.
- **Selecting an external temperature sensor no longer requires toggling a separate switch first** ([#221](https://github.com/hiall-fyi/tado_ce/issues/221) - @simonotter) — Previously, configuring an external sensor for a zone required five steps across two separate toggles, and forgetting the first toggle would silently discard your sensor selection. The sensor picker now works on its own — select a sensor and it's saved. The toggle is only needed if you want to disable an already-configured sensor.

## [4.0.0-beta.9] - 2026-04-23

### Features
- **Smart Valve Control** ([Discussion #231](https://github.com/hiall-fyi/tado_ce/discussions/231) - @Si-Hill, @wrowlands3) — If you have an external temperature sensor configured for a heating zone, you can now let Tado CE automatically keep the valve open until your room actually reaches the target temperature. The TRV's built-in sensor sits on the radiator and reads high, so it shuts the valve while the room is still cold. Smart Valve Control compensates by adjusting the TRV target based on the gap between your external sensor and the desired temperature. Adjustments go through HomeKit when available (zero API cost), with cloud as fallback. The controller backs off when you manually change the temperature, and resumes on the next schedule block. If the external sensor goes offline, it automatically resumes the Tado schedule. Enable it per zone in **Settings → Tado CE → Configure → zone → External Sensors → Smart Valve Control**. See [FEATURES_GUIDE.md](FEATURES_GUIDE.md#-smart-valve-control) for details.

### Bug Fixes
- **Climate card now shows "off" when heating is off via schedule or Away mode** ([Discussion #219](https://github.com/hiall-fyi/tado_ce/discussions/219) - @dragorex71) — If your Tado schedule had a time block with heating off, or you set Away mode and your away schedule turns off heating, the climate card still showed "auto" instead of "off". It now shows "off" whenever the zone isn't heating, regardless of whether it was turned off manually, by the schedule, or by Away mode.

### Improvements
- **Custom polling interval now also keeps weather data fresh** — The beta.8 fix for custom polling overriding HomeKit cloud sync only applied to zone data. Weather data could still go stale if HomeKit was connected and your custom interval was shorter than the weather skip window. Both zone and weather data now refresh at your chosen rate.
- **Bridge credentials now have their own settings section** ([#240](https://github.com/hiall-fyi/tado_ce/issues/240) - @ChrisMarriott38) — If you have an Internet Bridge but don't use Weather Compensation, your bridge serial and auth code used to appear under a "Weather Compensation" heading. They now live in their own "Internet Bridge" section, and Weather Compensation tuning has its own separate section that only appears when both features are active. No settings are lost — this is purely a UI reorganisation.
- **HomeKit savings now tracked as standalone sensors** — Reads Saved and Writes Saved are now their own diagnostic sensor entities (disabled by default) instead of just attributes on the HomeKit Connected sensor. This means HA records their history, so you can add sparkline trends to your dashboard. Enable them in **Settings → Devices → Tado CE Hub → "X entities not shown"**.

## [4.0.0-beta.8] - 2026-04-19

### Bug Fixes
- **Fixed false HomeKit write failures triggering circuit breaker** — After a HomeKit temperature or mode change, the integration checks that Tado's cloud servers received the change. But the cloud can take 3–5 minutes to sync from the bridge, while the verification window was only 17 seconds. This caused every HomeKit write to be counted as a "failure" even though the bridge accepted it, eventually tripping the circuit breaker and forcing all writes through the slower cloud API. The verification now retries multiple times over a longer window before giving up, and cloud sync delays are no longer counted as write failures.
- **Fixed HomeKit savings counters not resetting after HA restart** — The "Reads Saved" and "Writes Saved" counters track how many API calls HomeKit local control has saved you. If HA restarted right around the time Tado's daily quota reset, the counters would keep climbing from the previous day instead of starting fresh. They now persist the data needed to detect the reset correctly across restarts.

### Improvements
- **Boiler flow temperature now updates every 60 seconds** ([#237](https://github.com/hiall-fyi/tado_ce/issues/237) - @ChrisMarriott38) — The boiler flow temperature sensor was tied to your cloud polling interval, so if you set polling to 30 minutes, flow temperature data went stale for 30 minutes too — even though the bridge API doesn't count toward your Tado API quota. It now polls the bridge independently every 60 seconds, giving you smooth flow temperature charts regardless of your cloud polling settings. Weather Compensation also benefits from fresher flow data.
- **Temperature sensors now display with consistent precision** — All temperature sensors (zone, outdoor, boiler flow, dew point, surface, weather compensation) now explicitly request one decimal place in the dashboard. Previously this relied on HA's default, which was usually correct but not guaranteed.
- **Custom polling interval now overrides HomeKit cloud sync** ([#239](https://github.com/hiall-fyi/tado_ce/issues/239) - @ChrisMarriott38) — If you set a custom day or night polling interval, all data (including humidity, heating power, and weather) now refreshes at that rate. Previously, HomeKit's Cloud Data Refresh setting (default 30 min) would override your custom interval for zone data, meaning humidity could lag behind even with 5-minute polling. Auto polling users are unaffected — the cloud sync interval still applies when no custom interval is set.

_Log output_

- **Cleaner HomeKit warnings** — Four HomeKit warning messages reworded to explain what you can do (e.g. "check bridge is reachable") instead of showing internal error details, and stack traces moved from warning to debug level so they don't clutter normal logs.
- **Jargon removed from warning messages** — A couple of internal terms that previously leaked into user-visible warnings have been replaced with plain English.

## [4.0.0-beta.7] - 2026-04-18

### Bug Fixes
- **Fixed custom polling interval stuck after being set** ([#234](https://github.com/hiall-fyi/tado_ce/issues/234) - @ChrisMarriott38) — Once you set a custom day or night polling interval, there was no way to clear it back to automatic through the UI. This was a side effect of the beta.6 fix for collapsed sections wiping values — the field now accepts `0` to mean "use automatic polling", and the description says so.

### Improvements
- **Humidity now always uses cloud data when available** — Previously, humidity readings could flip between HomeKit and cloud sources, but the bridge caches humidity values and returns stale readings that can drift 1–4% from the actual sensor. Humidity now always prefers the cloud API (which provides 0.1% precision with real-time updates), with HomeKit only as a fallback when the cloud is unavailable. Temperature still uses HomeKit first since it's accurate and real-time.
- **Test Mode removed** — The simulated 100-call API tier switch has been removed. With Custom Polling and HomeKit local control, there's no longer a need to simulate low-quota scenarios. If you had the Test Mode switch entity, it's automatically cleaned up on upgrade — no manual steps needed.

_Log output_

- **Cleaner, quieter logs** — Debug logging across polling, HomeKit, bridge, and state reconciliation has been significantly reduced. Repetitive per-poll messages are gone, HomeKit cache refreshes only log when values actually change, and data source tracking now only logs when a zone switches between cloud and HomeKit (instead of every single poll). Your logs stay readable even with debug enabled.
- **HomeKit writes now log at info level** — Temperature and mode changes through HomeKit (and fallbacks to cloud) now appear in your normal logs so you can see what's happening without enabling debug. Previously these were hidden at debug level.
- **Startup and shutdown now log a summary** — When the integration finishes loading, you'll see a single line showing zone count, HomeKit status, weather status, and polling interval. Shutdown also logs when it starts persisting state, so you know nothing was silently dropped.
- **Debug logs drastically slimmed down** — Removed ~130 lines of verbose debug logging from the polling module without losing any diagnostic value — the remaining single-line summaries contain the same information.
- **HomeKit event handler only logs when values actually change** — No more log spam on every sensor push when the value hasn't moved.
- **Bridge API logging consolidated** — Shorter, consistent log format so bridge-related log lines are easier to scan.

## [4.0.0-beta.6] - 2026-04-17

### Bug Fixes
- **Fixed settings silently wiping your bridge credentials when you change other options** ([#227](https://github.com/hiall-fyi/tado_ce/issues/227) - @ChrisMarriott38) — If you had Weather Compensation enabled and went to Advanced Settings to change something else (like the polling interval), saving the form would silently clear your bridge serial and auth key. Your boiler flow temperature and other bridge sensors would go unavailable until you re-entered the credentials. The settings form now correctly preserves your bridge credentials when you're not explicitly changing them.
- **Fixed settings silently wiping your outdoor temperature entity, custom polling intervals, and per-zone external sensors** — The same underlying issue affected three more places: your outdoor temperature entity selection (Smart Comfort), custom day/night polling intervals (Polling & API), and per-zone external temperature/humidity sensor selections (Zone Config) could all be silently cleared when saving settings with those sections collapsed. All four are fixed with the same approach — collapsed sections now preserve your existing values instead of treating missing fields as "user wants to clear this".
- **Fixed timer set via service call not updating the UI immediately** — When you set a heating or AC timer through the `set_climate_timer` service, the entity state wouldn't update until the next polling cycle (up to 30 minutes with HomeKit). It now triggers an immediate refresh, matching the behaviour of all other control actions.
- **Fixed API call counter resetting to zero on every HA restart** ([#224](https://github.com/hiall-fyi/tado_ce/issues/224) - @ChrisMarriott38) — A legacy code path was writing a config JSON file on every restart, which triggered a token rotation that reset Tado's per-token API counter. The redundant file write has been removed — your API usage history now persists correctly across restarts.

## [4.0.0-beta.5] - 2026-04-17

### Bug Fixes
- **Fixed HomeKit zone mapping corruption that could send one zone's data to the wrong place** ([#224](https://github.com/hiall-fyi/tado_ce/issues/224) - @ChrisMarriott38) — If the cloud API returned incomplete zone data during the initial HomeKit pairing, a device could be mapped to a non-existent zone (e.g. zone "0" instead of zone "10"). That zone would then fall back to slower cloud data while its HomeKit readings went nowhere. The mapping now rejects invalid zone IDs, validates cached mappings against your actual zones on every startup, and automatically rebuilds if anything looks wrong.
- **Fixed blocking I/O warning on startup when schedule data hasn't been fetched yet** ([Discussion #219](https://github.com/hiall-fyi/tado_ce/discussions/219) - @ChrisMarriott38) — If you restarted HA before the integration had fetched your zone schedules (common on first install), the smart comfort sensors would trigger a synchronous file read on the main thread, causing HA to log a blocking call warning. The data cache now remembers "file doesn't exist" so it doesn't keep trying to read from disk on every update cycle.

### Improvements
- **Faster and more reliable data storage** — All integration data (zone states, weather, rate limits, schedules, and more) now uses Home Assistant's built-in storage system instead of managing its own JSON files. This means faster startup, no more blocking file reads on the main thread, and your data is automatically saved when HA shuts down — nothing gets lost between restarts.
- **Seamless upgrade from any previous version** — Whether you're coming from v3.5.3 or any v4.0.0 beta, your existing data is automatically migrated to the new storage format on first startup. The old files are renamed (not deleted) so you can roll back if needed.
- **HomeKit pairing survives storage changes** — HomeKit pairing credentials and device mappings are now stored alongside all other integration data, instead of in separate files that could get out of sync.
- **HomeKit zone mapping now retries after first sync** — If your HomeKit bridge connects before the cloud has synced zone data (common on first install), the integration now automatically rebuilds the zone mapping after the first successful cloud sync instead of giving up.
- **Simpler shutdown** — The integration no longer needs to manually save a dozen files when HA stops. HA's storage system handles it automatically, reducing the chance of data loss during unexpected shutdowns.
- **Temperature and humidity sensors now show data freshness** — When HomeKit is connected, the temperature and humidity sensors now include `data_source` (showing "homekit" or "cloud") and `last_homekit_update` (showing when the bridge last sent data) attributes. This makes it easy to verify your sensors are receiving live data, even when humidity appears flat due to the 1% resolution of the HomeKit protocol.

## [4.0.0-beta.4] - 2026-04-16

### Bug Fixes
- **Fixed thermal analytics sensors showing nonsensical values when HomeKit is connected** — The Heating Acceleration and Approach Factor sensors could show extreme values (e.g. -20°C/h² instead of +5) because HomeKit and cloud data arriving within the same second created duplicate temperature readings. The thermal analyzer now deduplicates readings before analysis and rejects values outside sane bounds. Your actual heating behaviour (preheat timing, heating rate) was never affected — only these two diagnostic display sensors.

### Improvements
- **Window Predicted now reacts in real time when HomeKit is connected** — Previously, the predicted window-open sensor only checked for temperature drops at each polling interval (up to 30 minutes with HomeKit). It now responds to every temperature push from the bridge, so an open window can be detected within seconds instead of waiting for the next poll.
- **Heating rate and acceleration are now more accurate when HomeKit is connected** — Temperature readings from the bridge are now fed into heating cycle tracking as they arrive, so your Heating Rate and Thermal Inertia sensors are based on more frequent measurements instead of waiting for each cloud poll.
- **Actionable Insights now use the freshest data when HomeKit is connected** — Insights like mold risk, comfort level, humidity trends, and heating anomalies were using cloud data even when HomeKit had fresher readings available. They now use the same live data as the rest of the integration.
- **Weather compensation now has full temperature history from the first poll** — Previously, the outdoor temperature history was only loaded when the first weather data arrived, which could be delayed if HomeKit was connected. It's now loaded during startup so weather compensation calculations are accurate from the start.
- **Pending actions are now logged when HA restarts** — If you change a temperature or queue a device operation right before HA restarts, the log now tells you which actions were dropped instead of silently discarding them.
- **Diagnostics now include data flow health** — The diagnostics dump (Settings → Devices → Tado CE → Download Diagnostics) now includes a `data_flow_health` section showing last cloud fetch timestamps, HomeKit and Bridge connection status, and persistence state. Useful for troubleshooting data freshness issues.

### Documentation
- Added humidity resolution (1% via HomeKit vs 0.1% via cloud) to the Known Limitations in README and Features Guide.

## [4.0.0-beta.3] - 2026-04-15

### Bug Fixes
- **Fixed temperature and humidity sensors lagging behind when HomeKit is connected** ([#224](https://github.com/hiall-fyi/tado_ce/issues/224) - @ChrisMarriott38) — The temperature and humidity sensor entities were only reading from the cloud, even when HomeKit was providing fresher data from your bridge. This meant your history charts could show data up to 30 minutes old while the climate card showed the correct live value. These sensors now use the same "pick the freshest source" logic as the climate card — HomeKit data when available, cloud as fallback.
- **Fixed smart comfort sensors using stale data when HomeKit is connected** — The schedule deviation, next schedule temperature, preheat advisor, and smart comfort target sensors had the same issue as above. All four now use live HomeKit data when available.
- **Fixed window detection using stale data when HomeKit is connected** — The predicted window-open sensor was running its detection algorithm on cloud data that could be up to 30 minutes old, making it much less responsive to actual temperature drops from open windows. It now uses live HomeKit data, so window detection reacts in real-time.
- **Fixed insights, preheat decisions, and boost calculations using stale data when HomeKit is connected** — Zone insights (mold risk, comfort, humidity trends), adaptive preheat "already at target" checks, and smart boost current temperature reads all now use live HomeKit data when available.
- **Fixed climate card showing wrong target temperature after switching to Auto mode** ([Discussion #219](https://github.com/hiall-fyi/tado_ce/discussions/219) - @hapklaar) — After setting a manual temperature and then switching back to Auto, the climate card would keep showing the manual temperature instead of the scheduled one. It now reads the current schedule target so the card matches what Tado is actually doing.

### Improvements
- **HomeKit Connected sensor now shows "Never" instead of blank** — The `last_disconnected` attribute shows "Never" when the bridge hasn't disconnected since HA started, instead of showing a confusing blank value.

## [4.0.0-beta.2] - 2026-04-14

### Bug Fixes
- **Fixed heating controls getting permanently stuck after a HomeKit write** — If a temperature or mode change went through HomeKit but the Tado server never received it, the integration would keep showing "heating" indefinitely, blocking all further control attempts. Your HA dashboard would show the zone heating while the Tado app showed OFF, and no amount of retrying would fix it. The integration now detects when a local write isn't confirmed by Tado's servers, clears the stale state, and automatically switches to the cloud API for subsequent commands.
- **Fixed repeated commands being silently ignored** — After a HomeKit write that silently failed, the integration would skip your next command because it thought the zone was already in the requested state. For example, setting 20°C when the dashboard already showed 20°C (from the failed write) would do nothing. Commands are no longer skipped when the displayed state hasn't been confirmed by Tado's servers.
- **Fixed climate entity not updating after service calls** ([Discussion #219](https://github.com/hiall-fyi/tado_ce/discussions/219) - @jeverley) — When you called services like `set_open_window_mode`, `restore_previous_state`, `resume_schedule`, or `set_climate_timer`, the Tado app would update immediately but the HA entity state would stay stale until the next poll. All overlay-related services now trigger an immediate refresh so your entities reflect the change straight away.
- **Fixed entity attributes showing blank after writes in HomeKit mode** — When HomeKit was connected, entity attributes (target temperature, heating power, overlay type) could stay blank after a temperature or mode change until the next periodic cloud sync. Writes now always fetch fresh data from Tado's servers regardless of HomeKit connection status.

### Improvements
- **Real-time HomeKit data now updates your dashboard immediately** ([Discussion #219](https://github.com/hiall-fyi/tado_ce/discussions/219) - @jeverley, @ChrisMarriott38) — Previously, temperature and humidity from the HomeKit bridge only appeared on your dashboard at the polling interval (every 5–30 minutes), producing the same step pattern as cloud-only mode even though the bridge was pushing data in real-time. Now changes from the bridge appear on your dashboard within 2 seconds.
- **HomeKit writes are now verified against Tado's servers** — After every local write through HomeKit, the integration checks that Tado's servers actually received the change. If they didn't, future writes automatically switch to the cloud API until the local path recovers. This catches the scenario where HomeKit reports success but the command never reaches the Tado server.
- **More reliable HomeKit savings counters** — The "Reads saved today" and "Writes saved today" counters on the HomeKit Connected sensor now use the API quota reset time as a single source of truth, with a 24-hour fallback for edge cases where the reset signal is delayed. Counters also survive HA restarts instead of starting from zero.
- **Smarter API error handling** — The integration now handles different HTTP error codes more intelligently instead of treating them all the same:
  - Deleting an overlay that's already gone (HTTP 404) no longer shows as an error.
  - Tado API rejections (HTTP 422) are logged as warnings instead of errors, with the actual rejection reason from the API response so you can see what went wrong.
  - If Tado tells you to slow down (HTTP 429), the integration now reads the server's Retry-After header to know exactly when to try again, instead of guessing from historical data.
  - Server errors (500/502/503/504) are now retried automatically with backoff, the same way connection timeouts are handled. Previously a single server hiccup would fail the entire request.
  - If restoring a previous state fails (e.g. the captured temperature is no longer valid), the integration falls back to resuming the schedule instead of leaving the zone in a broken state.

## [4.0.0-beta.1] - 2026-04-12

**HomeKit Local Control**

### ⚠️ Breaking Changes
- **Connection sensors are now binary sensors** ([#160](https://github.com/hiall-fyi/tado_ce/issues/160) - @Thilas, @jeverley) — Device connection sensors (`sensor.tado_ce_*_connection`) have been converted to proper binary sensors (`binary_sensor.tado_ce_*_connection`) with the Connectivity device class. The migration happens automatically, but if you have automations or dashboard cards referencing the old `sensor.*_connection` entities, you'll need to update them to use the new `binary_sensor.*_connection` entities.
- **Hot water power sensor is now a binary sensor** ([#160](https://github.com/hiall-fyi/tado_ce/issues/160) - @jeverley) — The hot water power sensor (`sensor.tado_ce_*_power`) has been converted to a binary sensor (`binary_sensor.tado_ce_*_power`) with the Power device class. Same as above — automations referencing the old entity will need updating.

### Features
- **HomeKit local control for Tado Internet Bridge** — Pair your Tado bridge via HomeKit to control heating and AC directly on your local network. What you get:
  - **Faster controls** — Temperature and mode changes go through the bridge on your LAN instead of the Tado cloud, with a 3-second timeout so a slow bridge never freezes your UI.
  - **Real-time sensor updates** — Temperature and humidity push instantly via HomeKit events instead of waiting for the next cloud poll.
  - **Fewer API calls** — Cloud polling is reduced when HomeKit is connected. The integration tracks how many API calls HomeKit saves, and the counters survive HA restarts. You can configure how often to check the cloud for non-sensor data (default every 30 minutes) in **Settings → Tado CE → Configure → Advanced Settings → HomeKit**.
  - **Automatic fallback** — If HomeKit becomes unavailable, the integration seamlessly switches to the cloud API. After repeated failures it pauses HomeKit attempts for 5 minutes, then automatically tests recovery.
  - **Zero-config reconnect** — If the bridge connection drops, the integration reconnects in the background and restores real-time event subscriptions automatically.
  - Set up in **Settings → Tado CE → Configure → General Settings** (enable HomeKit) → follow the pairing flow.
- **HomeKit performance tracking** — The HomeKit Connected sensor now shows write attempts, successes, cloud fallbacks, and average response time as attributes. Check your HomeKit Connected entity's attributes to see how your local network is performing.
- **HomeKit unpair** — You can disconnect your HomeKit pairing from **Settings → Tado CE → Configure → Advanced Settings → HomeKit → Unpair** without removing the integration.

### Bug Fixes
- **Fixed empty Advanced Settings page** ([#220](https://github.com/hiall-fyi/tado_ce/issues/220) - @dragorex71) — The Advanced Settings page showed a blank form when no optional features were enabled. The Polling & API section now always appears regardless of which features you've turned on.
- **Fixed temperature offset showing raw Fahrenheit value** ([#221](https://github.com/hiall-fyi/tado_ce/issues/221) - @simonotter) — The `offset_celsius` attribute could show a nonsensical value (e.g. 75.9 instead of -0.1) if an automation read the offset and wrote it back, creating a feedback loop. The integration now reads back the actual offset from the device after every write, and rejects any value outside the valid ±10°C range on all paths — write, sync, and read.

### Improvements
- **Smarter polling when HomeKit is connected** — When HomeKit is providing live temperature and humidity data, the integration skips redundant cloud data fetches and stretches the polling interval further. Weather data is also fetched less often (every 30 minutes instead of every poll). This means fewer API calls and more headroom in your daily quota.
- **Cloud outages no longer make entities unavailable when HomeKit is connected** — If the Tado cloud is temporarily unreachable but HomeKit is still working, your entities stay available using local data instead of going unavailable.
- **Climate entities now show where their data comes from** — The `temperature_source` and `humidity_source` attributes now show `cloud`, `homekit`, or `external` instead of the old `tado` label, so you can tell at a glance which path your readings are taking. A new `last_write_source` attribute shows whether the most recent temperature or mode change went through HomeKit or the cloud.
- **Mobile Device Tracking moved to Polling & API** — The "Frequent Sync" toggle for mobile device tracking has moved from its own section into the Polling & API section in Advanced Settings, keeping all polling-related options in one place.
- **Cleaner logs** — Log messages now use plain language and routine messages are moved to debug level so your logs stay readable.

---

## [3.5.3] - 2026-04-08

### ⚠️ Prerequisites
- **Minimum Home Assistant version is now 2025.11** — Required by the smarter rate limit handling below. If you're on an older HA release, stay on v3.5.2 or upgrade HA first.

### Improvements
- **Overlay sensor now shows timer end time** ([#217](https://github.com/hiall-fyi/tado_ce/issues/217)) — When a Timer overlay is active, the `next_change` attribute now shows when the timer expires instead of the next schedule change. Two new attributes are also available: `overlay_expiry` (the exact end time) and `overlay_remaining_seconds` (countdown). Manual and Tado Mode overlays continue to show the next schedule change as before.
- **Smarter rate limit handling** — When the API quota is exhausted, the integration now tells HA exactly how long to wait before the next poll (using the known reset time) instead of using a fixed 15-minute retry. This means polling resumes faster after a quota reset.
- **Retry delay capped** — Exponential backoff delay is now capped at 30 seconds to prevent excessively long waits on repeated failures.
- **Device authorization polls less aggressively** — When signing in via device authorization, the integration now waits 5 seconds between polls instead of 2, matching the OAuth standard recommendation. You may notice the "waiting for browser authorization" step take a touch longer on fast networks, but it's less likely to hit rate limits on slow ones.

---

## [3.5.2] - 2026-04-06

### Bug Fixes
- **Fixed token refresh and API calls not retrying on DNS/network failures** ([#214](https://github.com/hiall-fyi/tado_ce/issues/214)) — If your DNS server briefly refused a query or the connection to Tado's servers timed out, the integration would give up immediately instead of retrying. This could leave all entities unavailable until the next poll cycle. Now token refresh and all API calls retry up to 3 times with exponential backoff on any transient network error (DNS failures, connection timeouts, connection resets), matching the existing 403 retry behaviour.

---

## [3.5.1] - 2026-04-06

**Reliability & Code Quality**

### Bug Fixes
- **Fixed stale insights sticking around after resolving** — The Home Insights sensor could show issues that had already resolved but were still within the reappearance grace period. For example, a mold risk warning that cleared would keep showing in the "persistent issues" list for up to an hour. Now only genuinely active issues appear.

### Improvements
- **More resilient API calls** — All API operations (temperature offsets, child lock, zone overlays, presence lock, schedules, meter readings, away configuration) now automatically retry when the Tado cloud returns a transient 403 error. Previously, only the main polling calls had retry logic — actions like changing temperature or toggling child lock would silently fail on a temporary CDN/WAF block. Now every cloud API call retries up to 3 times with exponential backoff before giving up.
- **Token refresh also retries on 403** — If the Tado login server returns a transient 403 during token refresh, the integration now retries instead of immediately failing. Real authentication errors (401, invalid_grant) are still handled instantly without retry.
- **Dangling async tasks fixed** — Background tasks in the write optimizer (action debouncer and refresh coalescer) now properly track their lifecycle and log exceptions instead of silently swallowing them. Cleanup on shutdown cancels all pending tasks.

_Performance & storage_

- **Faster polling** — Rate limit data is now read from memory instead of reading a file from disk on every poll cycle. Small wins compound on low-quota homes that poll frequently.

---

## [3.5.0] - 2026-04-02

**Redesigned Settings & Architecture Overhaul**

### Features
- **Redesigned Options Flow** — Settings are now split into four clear sections: General Settings (feature toggles), Advanced Settings (tuning parameters for enabled features only), Zone Configuration, and Reset to Defaults. You no longer need to scroll through 79 options on one page. First-time setup for Internet Bridge and Weather Compensation now guides you through credentials step by step. You can also reset settings back to defaults (per feature or everything at once) without losing your Tado account or bridge pairing.

### Bug Fixes
- **Fixed quota deadlock on clean install** ([#204](https://github.com/hiall-fyi/tado_ce/issues/204) - @Saughassy) — On a fresh install with stale rate limit data and no known reset time, the integration could get stuck permanently in "quota critically low" state. Now allows both polling and manual actions to bootstrap fresh data when no reset time is known.
- **Fixed temperature offset not updating after service call** ([#211](https://github.com/hiall-fyi/tado_ce/issues/211) - @mat01) — After calling `set_climate_temperature_offset`, the `offset_celsius` attribute kept showing the old value until the next HA restart. Automations that read-then-write offsets would oscillate. Now updates the local cache immediately so the new offset is reflected right away.

### Improvements

_Options Flow & descriptions_

- **Clearer Settings Descriptions** ([Discussion #131](https://github.com/hiall-fyi/tado_ce/discussions/131) - @Prodeguerriero) — All option descriptions in General Settings and Advanced Settings have been rewritten in plain language. Technical jargon like "rate calculation", "inertia end", and "setpoint deviation" has been replaced with descriptions that explain what each setting actually does for you. Mobile Device Tracking now clearly states that locations only update on HA restart unless you enable Frequent Sync. API cost info uses consistent "per poll" / "on restart" wording instead of the confusing "full sync" / "quick sync" distinction.
- **Removed Legacy Options Flow** — The old single-page "Global Settings" flow has been fully removed (code, strings, and all translations). If you see a stale UI after upgrading, clear your browser cache.

_Insights & comfort_

- **Smarter, Cleaner Insights** — Insights got a full overhaul. Recommendations now only appear when they're relevant to your actual settings (e.g. no geofencing alerts when you have geofencing off). The Home Insights summary focuses on the single most urgent action with a clear reason, instead of listing everything. Empty attributes no longer clutter the sensor. Persistent issues show escalated priority (a battery problem lasting 2 weeks shows as Critical, not Low). Zone-level sensors now include how long an issue has been active. The weekly digest is a simple trend comparison — new, resolved, up or down from last week.
- **More Accurate "Feels Like" Temperature** — The Heat Index calculation no longer has a small jump at the transition point (~27°C). Previously, a tiny humidity increase could briefly make the "feels like" temperature drop instead of rise. Now the transition is smooth.

_Performance & storage_

- **Faster Startup** — The insights engine loads only the modules it needs instead of pulling in the entire 3,000-line file on every restart.

_Data integrity_

- **More state now survives HA restarts** — Weather compensation settings, bridge health status, and window detection history are now persisted and restored across restarts instead of resetting to defaults or empty on startup.
- **Configuration now lives entirely in the HA config entry** — The separate `config_{home_id}.json` file is no longer written. Existing files are migrated automatically on upgrade — no action needed.
- **Config entry version bumped to v12 with automatic migration** — Upgrading from earlier v3.x releases migrates your data to the new format on first start.

---

## [3.4.1] - 2026-03-26

### Bug Fixes
- **Fixed crash on clean install** ([#204](https://github.com/hiall-fyi/tado_ce/issues/204) - @Saughassy) — On a fresh install, the integration could fail to start with a Python `TypeError` before rate limit data was fully populated — the adaptive polling calculator was dividing by fields that hadn't arrived yet. All rate limit fields are now treated as optional during first setup, so a clean install boots cleanly even before the first API response lands.

---

## [3.4.0] - 2026-03-23

### ⚠️ Prerequisites
- **Minimum supported upgrade path is now v3.0.0+** — All migration code for upgrading from v2.x has been removed. Users still on v2.x should upgrade to a v3.x release first before taking this update.

### Features
- **API Write Optimization** — All enabled by default. Three new settings under **Settings → Tado CE → Configure → Global Settings → Polling & API** to reduce unnecessary API calls:
  - **Smart Actions Debounce** — When you drag a temperature slider, only the final value is sent to the API instead of every intermediate position. Configurable window (0–10 seconds, default 3). Set to 0 to disable.
  - **Action Guard** — Skips API calls when the requested state already matches the current state (e.g. setting 22°C when it's already 22°C). Always active.
  - **Device Sync Queue** — Device-level operations (child lock, early start) are now queued and executed sequentially with a configurable delay (0.5–5 seconds, default 1), preventing race conditions from rapid toggling. Always active.
  - **Write Coalescing** — Multiple rapid state changes trigger a single coordinated refresh instead of one per change. Always active.
  - **Resume Guard** — Resuming a zone's schedule is skipped if the zone is already following its schedule. Always active.
- **Schedule Preview** — Heating and AC climate entities now show a `scheduled_target_temperature` attribute with the current schedule target, so you can see what temperature the zone would be at without an overlay.

### Bug Fixes
- **Fixed Hassfest Validation Failure** — The window detection mode selector was using title-case option keys (`Active`, `Passive`, `Auto`) which failed Home Assistant's Hassfest validation. Lowercased across all 7 languages. No user action needed — option labels in the UI are unchanged.

### Improvements
- **UFH Buffer Now Per-Zone** — Underfloor heating buffer is now configured per zone (via Zone Configuration) instead of a global setting. Zones with heating type set to Underfloor automatically get the buffer applied.
- **Atomic Writes for Zone Config & Outdoor Temp** — Zone configuration and outdoor temperature history files now use the same crash-safe tempfile-then-rename pattern as other data files, so an unexpected shutdown can't leave these files half-written.
- **Translation Sync** — Added missing Adaptive Preheat Mode selector translations across all 7 languages (German, Spanish, French, Italian, Dutch, Portuguese).

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

### Bug Fixes
- **Fixed Preheat Triggering During Away Mode** ([#171](https://github.com/hiall-fyi/tado_ce/issues/171) - @thefern69) — Preheat could still fire during the Home→Away transition due to a timing gap. Now properly checks presence before any heating action, including on startup.
- **Fixed Open Window Mode Duration** — The `set_open_window_mode` service was sending the duration as text instead of a number, which could cause the Tado API to reject the request. Now sends it correctly.

### Improvements

_Flow Temperature Control & Bridge_

- **Flow Temperature Control Settings** — Bridge credentials and weather compensation settings are now in one place instead of two separate menus, so there's less clicking around.
- **Fewer Bridge Entities by Default** — Only the most useful bridge entities are visible out of the box (Bridge Connected, Wiring State, Boiler Output Temperature, Boiler Flow Temperature). The rest are hidden and can be enabled manually if you need them.
- **Bridge Serial Validation** ([#187](https://github.com/hiall-fyi/tado_ce/issues/187) - @ChrisMarriott38) — The bridge serial field now checks that it starts with `IB` (v3+ bridge). V2 bridges (`GW` serial) aren't supported by the Bridge API. Weather Compensation still works without a bridge via cloud data.
- **Weather Compensation Blueprint Updated** ([#187](https://github.com/hiall-fyi/tado_ce/issues/187) - @driagi) — Blueprint tuned to reduce oscillation: larger step size (1.0°C), wider deadband (1.0°C), and 10-minute hold between adjustments.

_Window Detection_

- **Smoother Window Detection** — The Window Predicted sensor no longer flickers on/off rapidly. It now waits for several stable readings before clearing a detection (3 readings on Low sensitivity, 2 on Medium, 1 on High).
- **Window Detection Events** — HA events (`tado_ce_window_predicted` and `tado_ce_window_predicted_cleared`) now fire when a window is detected or cleared — useful for building your own automations.
- **Window Detection History** — The Window Predicted sensor now tracks when the last detection happened, how many times today, and which detection mode was used. Daily count resets at midnight.
- **Open Window Mode Saves State** — When `set_open_window_mode` activates, it now saves what the zone was doing first. After the window is closed, use `restore_previous_state` to go back to exactly where you were.

_Other_

- **Default Temperature on First Install** ([#182](https://github.com/hiall-fyi/tado_ce/issues/182) - @neonsp) — Climate entities now start with a sensible default (20°C heating, 24°C AC) instead of showing blank controls on first install.

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
- **Set Open Window Mode Service** ([#172](https://github.com/hiall-fyi/tado_ce/issues/172), [Discussion #184](https://github.com/hiall-fyi/tado_ce/discussions/184) - @driagi) — New `set_open_window_mode` service lets you trigger open window mode from your own contact sensors (Zigbee, Z-Wave, etc.) without waiting for Tado's built-in detection. Defaults to your zone's timeout setting or 15 minutes.

### Bug Fixes
- **Fixed Climate Card Blank After HA Restart** ([#182](https://github.com/hiall-fyi/tado_ce/issues/182) - @neonsp) — The climate card no longer shows a blank temperature after restarting HA. Your last target temperature is now restored automatically, so the controls work right away.
- **Fixed External Sensor Not Updating Instantly** ([#143](https://github.com/hiall-fyi/tado_ce/issues/143) - @BirbByte) — External temperature and humidity sensors (HomeKit, Zigbee, etc.) now update the climate card immediately when the value changes, instead of waiting for the next poll cycle.

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

### Bug Fixes
- **Fixed AC Max Temperature Capped at 25°C** ([#180](https://github.com/hiall-fyi/tado_ce/issues/180)) — AC zones that support up to 30°C were incorrectly limited to 25°C. Now uses your AC's actual temperature range unless you've set a custom override.

### Improvements
- **Zone Configuration Moved to Options Flow** — All per-zone settings (overlay mode, timer, temperature limits, offsets, heating type, etc.) are now in one place under Settings → Configure → Zone Configuration. No more config entities cluttering your dashboard.
- **Renamed "Tado Mode" → "Tado Default"** ([#176](https://github.com/hiall-fyi/tado_ce/issues/176)) — The overlay mode name now matches what Tado calls it.
- **Entity Categories Added** ([#178](https://github.com/hiall-fyi/tado_ce/issues/178)) — Configuration and diagnostic entities are now properly categorized, so they're organized correctly in the HA UI.
- **Smarter Full Sync** ([#141](https://github.com/hiall-fyi/tado_ce/issues/141) - @Xavinooo) — Full data sync now only runs on HA restart instead of every 6 hours, saving API calls.
- **Test Mode & Quota Reserve Skip Reload** — Toggling these settings no longer restarts the integration.
- **Health Score Formatting** — Home Insights health score now shows with emoji and label (e.g., "🟢 92 — Excellent") for quick reading.
- **Improved Translations** — All 6 non-English languages revised with more natural wording. Service names and descriptions now translated in all 7 languages.

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

### Bug Fixes
- **Fixed Auth URL Showing 404** ([#104](https://github.com/hiall-fyi/tado_ce/issues/104)) — The authorization link during setup no longer leads to a broken page.
- **Fixed Window Sensor Not Working Without Auto-Assist** ([#157](https://github.com/hiall-fyi/tado_ce/issues/157) - @tanerpaca) — Window sensor now detects open windows even without an Auto-Assist subscription.
- **Fixed Preheat Triggering a Day Early** ([#164](https://github.com/hiall-fyi/tado_ce/issues/164) - @thefern69) — Preheat sensor no longer fires a day before it should.
- **Fixed Heating Rate Unit** — Heating rate was showing inconsistent values depending on which internal path computed it — some sites reported °C/min, others °C/h. Standardised on °C/h everywhere and set the sensor's unit attribute accordingly.

### Improvements
- **Timer Minimum Lowered to 1 Minute** ([#162](https://github.com/hiall-fyi/tado_ce/issues/162) - @joaomacp) — Climate and water heater timers now accept durations as short as 1 minute (was 15).
- **7-Language Support** — Config flow and options UI now available in English, German, Spanish, French, Italian, Dutch, and Portuguese.

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

### Bug Fixes
- **Fixed Mold Risk Giving Wrong Advice** ([#147](https://github.com/hiall-fyi/tado_ce/issues/147) - @ChrisMarriott38) — Mold risk no longer suggests turning up the heating when the room is already warm enough. Now suggests ventilation or a dehumidifier instead.
- **Fixed Hot Water Overlay Showing for Combi Boilers** ([#149](https://github.com/hiall-fyi/tado_ce/issues/149) - @ChrisMarriott38) — Overlay Mode and Timer Duration entities no longer appear for combi boiler hot water zones where they don't apply.
- **Fixed Mobile Device Tracker Not Updating** ([#150](https://github.com/hiall-fyi/tado_ce/issues/150) - @driagi) — Device tracker was stuck on the state from last HA restart. Now updates every 30 seconds.

### Improvements
- **Flexible Climate Timer** ([#152](https://github.com/hiall-fyi/tado_ce/issues/152) - @mpartington) — `time_period` is now optional in the `set_climate_timer` service. Use `overlay: next_time_block` for "until next schedule change" or `overlay: manual` for indefinite.

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

### Bug Fixes
- **Fixed Long Heating Cycles Never Completing** ([#125](https://github.com/hiall-fyi/tado_ce/issues/125) - @BruceRobertson) — Heating cycles longer than 50 minutes now complete correctly.
- **Fixed First-Run Error** ([#127](https://github.com/hiall-fyi/tado_ce/issues/127) - @slflowfoon, [PR #132](https://github.com/hiall-fyi/tado_ce/pull/132) - @hacker4257) — Fixed an error on first install when the storage folder didn't exist yet.
- **Fixed Hot Water Settings Missing for Tank Systems** ([#115](https://github.com/hiall-fyi/tado_ce/issues/115) - @jeverley) — Tank-based hot water systems now correctly get Overlay Mode and Timer Duration controls.
- **Fixed Custom Polling Issues** ([#126](https://github.com/hiall-fyi/tado_ce/issues/126) - @Xavinooo) — Custom night interval, day/night detection, and settings persistence all fixed.
- **Fixed AC Swing Mode for Mitsubishi Units** ([#128](https://github.com/hiall-fyi/tado_ce/issues/128) - @BirbByte) — AC units that don't support "OFF" as a swing value no longer get API errors.
- **Fixed Environment Sensor Cleanup** — All sensors now correctly removed when the feature is toggled off.
- **Fixed Heating Anomaly False Alarms** — Heating anomaly insight no longer fires on every update.

### Improvements
- **Readable Attribute Values** — Zone type, window type, and comfort model attributes now show human-readable names instead of internal codes.

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
- **Fixed Climate Entities Unavailable After Upgrade** ([#100](https://github.com/hiall-fyi/tado_ce/issues/100) - @Claeysjens) — Climate entities could stay unavailable after upgrading from an earlier v2.x release because of a state migration gap. Now restores correctly on first load after upgrade.
- **Fixed Hot Water Temperature Jumping Back** ([#98](https://github.com/hiall-fyi/tado_ce/issues/98) - @ChrisMarriott38) — Temperature changes no longer revert in the UI.
- **Fixed Quota Reserve Not Preventing API Limit** ([#99](https://github.com/hiall-fyi/tado_ce/issues/99) - @ChrisMarriott38) — The quota reserve guard previously didn't block all API-spending paths, so the integration could still exceed the Tado daily limit when reserve was active. All API entry points now honour the reserve.
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
- **Fixed hot water timer buttons not finding the right entity** ([#93](https://github.com/hiall-fyi/tado_ce/issues/93) - @Fred224) — Timer button entity IDs were constructed from the zone name, but HA may add suffixes when the ID conflicts with another integration. Buttons now look up the water heater entity via the entity registry by unique ID, with name-based lookup as fallback.

### Improvements
- **Removed "Tado CE" prefix from entity names** — Hub sensors were prefixed with "Tado CE " (e.g. "Tado CE API Usage") which was redundant once every entity was grouped under the Tado CE Hub device. Prefix dropped — entity IDs unchanged so existing automations and dashboards keep working.

## [1.10.0] - 2026-02-05

### Bug Fixes
- **Fixed Climate Entity Flickering** ([#44](https://github.com/hiall-fyi/tado_ce/issues/44) - @hapklaar, @chinezbrun, @neonsp) — Climate entities no longer flicker or revert when you make changes. Multiple layers of protection prevent stale data from overwriting your actions.

## [1.9.7] - 2026-02-04

### Bug Fixes
- **Fixed state flickering when quickly changing modes** ([#44](https://github.com/hiall-fyi/tado_ce/issues/44) - @chinezbrun) — Rapid mode changes (e.g. Auto → Heat → Off within a few seconds) could leave the climate card flicking between states as the optimistic UI reconciled against delayed API responses. Optimistic state tracking now correctly holds the latest user intent until the API confirms it.

## [1.9.6] - 2026-02-04

### Bug Fixes
- **Fixed heating/cooling status reverting after a mode change** ([#44](https://github.com/hiall-fyi/tado_ce/issues/44) - @hapklaar, @chinezbrun) — After switching modes, the `hvac_action` attribute could briefly revert to the pre-change value on the next poll, making automations that react to heating/cooling state fire twice.

## [1.9.5] - 2026-02-02

### Bug Fixes
- **Fixed heating/cooling status not updating when setting temperature** ([#44](https://github.com/hiall-fyi/tado_ce/issues/44) - @hapklaar, @chinezbrun) — Changing the target temperature didn't update the `hvac_action` attribute until the next poll cycle, so automations tracking heating state missed the transition.

## [1.9.4] - 2026-02-02

**Boost Buttons**

### Features
- **Boost Button** — One tap to set any zone to 25°C for 30 minutes.
- **Smart Boost Button** — Intelligent boost that calculates the right duration automatically.

### Bug Fixes
- **Fixed heating status stuck on "Heating" after switching to Auto** ([#44](https://github.com/hiall-fyi/tado_ce/issues/44) - @hapklaar) — The climate card kept showing "heating" after switching from a manual target back to Auto, even when the zone was actually idle.
- **Fixed AC startup warnings** ([#44](https://github.com/hiall-fyi/tado_ce/issues/44) - @neonsp) — Spurious warnings on HA startup about missing AC capabilities resolved.
- **Fixed slow zone sensor updates** ([#44](https://github.com/hiall-fyi/tado_ce/issues/44) - @chinezbrun) — Zone sensors lagged behind climate card state by up to a poll cycle; now updated in lock-step.

## [1.9.3] - 2026-02-02

### Bug Fixes
- **Fixed slow state updates for heating users** ([#44](https://github.com/hiall-fyi/tado_ce/issues/44) - @hapklaar, @chinezbrun) — Heating-mode state changes took longer to reach HA than expected. Optimistic state updates now push the new state immediately while the API catches up.
- **Fixed AC DRY mode error** ([#79](https://github.com/hiall-fyi/tado_ce/issues/79) - @Fred224, @neonsp) — Setting the AC to DRY mode raised an API error on some AC models. Now correctly mapped.

## [1.9.2] - 2026-02-01

### Bug Fixes
- **Fixed grey loading state on climate card** ([#44](https://github.com/hiall-fyi/tado_ce/issues/44) - @chinezbrun) — The climate card showed a grey "loading" overlay for several seconds after any state change. Resolved by updating optimistic state synchronously instead of waiting for the async roundtrip.

## [1.9.1] - 2026-01-31

### Bug Fixes
- **Fixed crash on startup during device migration** ([#74](https://github.com/hiall-fyi/tado_ce/issues/74)) — Upgrading from an earlier 1.x release could crash at startup when the device migration path encountered a zone with no devices registered. Migration now handles empty device lists gracefully.

## [1.9.0] - 2026-01-31

**Smart Comfort Analytics + Environment Sensors**

### Features
- **Smart Comfort Analytics** — New sensors for heating/cooling rate, time to target, and heating efficiency.
- **Smart Comfort Insights** ([#33](https://github.com/hiall-fyi/tado_ce/discussions/33)) — Historical comparison, preheat advisor, and smart comfort target recommendations.
- **Environment Sensors** ([#64](https://github.com/hiall-fyi/tado_ce/issues/64)) — Mold risk and comfort level sensors for each zone.
- **Schedule Sensors** — Shows the next scheduled time and temperature for each zone.

### Bug Fixes
- **Fixed API reset detection for the 100-call limit** ([#54](https://github.com/hiall-fyi/tado_ce/issues/54)) — Users on the free 100-call API tier saw incorrect reset time estimates. The detection logic now reads the daily reset schedule correctly for low-quota accounts.
- **Fixed temperature offset for rooms with multiple TRVs** ([#66](https://github.com/hiall-fyi/tado_ce/issues/66)) — The temperature offset service only wrote to the first TRV in a zone; rooms with multiple radiator valves now get the offset applied to every TRV.
- **Fixed sensors being assigned to the wrong device** ([#56](https://github.com/hiall-fyi/tado_ce/issues/56)) — Some zone sensors appeared under the Hub device instead of the correct zone device. Device assignment now uses the zone's unique ID for lookup.

## [1.8.3] - 2026-01-26

### Features
- **Refresh AC Capabilities button** — New button on the Hub device to reload your AC unit's supported modes, fan speeds, and swing options without restarting HA. Useful if Tado's reported capabilities change or if you want to re-sync after connecting a new AC unit.

### Bug Fixes
- **Fixed AC not responding immediately after turning on** ([#44](https://github.com/hiall-fyi/tado_ce/issues/44) - @neonsp) — The first command after turning on an AC zone could take several seconds to register. Optimistic state now applies the command right away while the API catches up.

### Improvements
- **AC capabilities are now cached to save API calls** ([#61](https://github.com/hiall-fyi/tado_ce/issues/61) - @neonsp) — AC unit capabilities (supported modes, fan speeds, swing options) are only fetched when you first add the integration or manually refresh, instead of on every startup.

## [1.8.2] - 2026-01-26

### Bug Fixes
- **Fixed Resume All Schedules taking too long to respond** ([#44](https://github.com/hiall-fyi/tado_ce/issues/44) - @hapklaar) — The Resume All Schedules button could take several seconds to update the UI after pressing. Now refreshes immediately after the API confirms.

### Improvements
- **Smoother AC controls** ([#44](https://github.com/hiall-fyi/tado_ce/issues/44) - @neonsp) — Selections in AC mode, fan speed, and swing dropdowns no longer flicker during updates — optimistic state holds the new value until the API confirms.

## [1.8.1] - 2026-01-26

### Bug Fixes
- **Fixed AC instant feedback not working** ([#44](https://github.com/hiall-fyi/tado_ce/issues/44) - @neonsp) — AC mode and temperature changes didn't update the UI immediately, leaving users unsure whether the command had registered.
- **Fixed Resume All Schedules not refreshing the UI** ([#44](https://github.com/hiall-fyi/tado_ce/issues/44) - @hapklaar) — After pressing Resume All Schedules, the climate cards stayed on their overlay targets until the next poll. Now refresh immediately.

## [1.8.0] - 2026-01-26

**Schedule Calendar + Multi-Home Prep**

### Features
- **Schedule Calendar** — See your heating schedules as a calendar per zone, with each scheduled block appearing as a calendar event.
- **Per-zone Refresh Schedule button** — Trigger an on-demand schedule refresh for a specific zone without waiting for the next poll cycle.
- **API Reset sensor now shows extra details** ([#54](https://github.com/hiall-fyi/tado_ce/issues/54) - @ChrisMarriott38) — The API Reset sensor attributes now include next reset time, calls used this period, and detection method.

### Improvements
- **Multi-home preparation** — Data files are now stored per home (rather than globally) in preparation for the full multi-home support that lands in v3.0.0. No user action needed; existing single-home installs continue to work unchanged.

## [1.7.0] - 2026-01-26

### Features
- **Instant UI feedback** — Temperature changes, mode switches, and preset selections now show in the UI immediately instead of waiting for the next poll cycle to confirm. Optimistic state holds the new value until the API catches up.
- **Optional home state sync to save API calls** — Fetching Tado's cloud-side home presence state on every poll is now optional via a toggle in Options Flow. With it off, presence changes made on HA propagate to Tado without also polling for server-side changes you don't use.

### Improvements
- **Multi-home preparation — unique ID migration** — Entity unique IDs now include the home ID in preparation for the full multi-home support that lands in v3.0.0. Existing single-home installs are migrated automatically on first start; no user action needed.

## [1.6.3] - 2026-01-25

### Improvements
- **Uses HA history to detect API reset time more accurately** — The API reset time sensor now queries HA's history for past rate-limit sensor values to infer the actual reset window, rather than relying on fixed assumptions that could drift from Tado's real reset time.

## [1.6.2] - 2026-01-25

### Bug Fixes
- **Fixed API call history not being recorded** — API call counts were tracked in memory but not persisted, so the API usage sensor started from zero on every HA restart. Now correctly records history across restarts.
- **Fixed timezone issues in various sensors** — Sensors that displayed times (reset time, next sync, last sync) could show wrong values for users in non-UTC timezones. All time displays now honour HA's configured timezone.

## [1.6.1] - 2026-01-25

### Features
- **Configurable delay between rapid updates** — New Options Flow setting to adjust the debounce window for rapid state changes (e.g. slider drags). Prevents API spam when tuning temperatures quickly.

### Bug Fixes
- **Fixed API Usage and Reset sensors showing 0** — A regression in 1.6.0 left the API Usage and Reset sensors stuck on 0 regardless of actual quota state. Now reads the correct values on every poll.

## [1.6.0] - 2026-01-25

### Features
- **Faster API calls — migrated to native async** — The integration no longer spawns subprocesses to run Tado API calls. All HTTP requests now use HA's native aiohttp client, reducing per-call overhead from ~100ms to <10ms and eliminating the stability issues associated with subprocess-based calls.

### Bug Fixes
- **Fixed database migration issue from older versions** — Upgrading from pre-1.5 releases could fail mid-migration, leaving entities in an inconsistent state. Migration is now idempotent and can recover from partial prior runs.
- **Fixed `climate.set_temperature` ignoring the mode you selected** — Passing `hvac_mode` along with `temperature` to the service was being silently dropped — only the temperature was applied. Now both fields are honoured in the same call.

## [1.5.5] - 2026-01-24

### Bug Fixes
- **Fixed AC Auto mode accidentally turning off the AC** — Setting an AC zone to Auto mode could be misinterpreted by Tado's API as "off". The mode now maps to the correct API value so Auto stays Auto.

### Improvements
- **Reduced API calls when changing settings** — Rapid setting changes in the Options Flow no longer trigger multiple config reloads; changes are coalesced and applied once.

## [1.5.4] - 2026-01-24

### Features
- **Unified swing dropdown for AC** — Vertical and horizontal swing options are now combined into a single dropdown with Off/Vertical/Horizontal/Both, matching the official Tado integration's layout.

### Bug Fixes
- **Fixed all AC control issues (modes, fan speed, swing)** — A set of regressions from 1.5.3 affecting AC mode changes, fan speed selections, and swing mode updates are all resolved in this release.

## [1.5.3] - 2026-01-24

### Features
- **Resume All Schedules button** — New one-tap button on the Hub device that resumes the schedule on every zone at once, instead of clicking each zone's resume button individually.

### Bug Fixes
- **Fixed AC control errors** — Several AC mode and fan speed commands were failing with API errors due to incorrect parameter mapping. All AC commands now pass the correct API payload.

## [1.5.2] - 2026-01-24

### Bug Fixes
- **Fixed losing your login after a HACS upgrade** — A HACS upgrade could wipe the stored refresh token, forcing you to re-authenticate after every update. The token storage path now survives HACS upgrades.

## [1.5.1] - 2026-01-24

### Features
- **Re-authenticate option in the UI** — New menu option in the integration's overflow menu to trigger the re-auth flow without removing and re-adding the integration.

### Bug Fixes
- **Fixed login errors for new users** — First-time setup could fail on accounts that hadn't been used with the old official integration because of a stale token format assumption. New-account onboarding now works cleanly.

## [1.5.0] - 2026-01-24

**Async Architecture Rewrite**

### Features
- **Temperature offset service** — New `set_climate_temperature_offset` service lets you calibrate per-TRV temperature offsets from automations or scripts.
- **Full AC support — all modes, fan speeds, and swing options** — Previously AC zones were limited to basic mode/temperature. All modes (Cool/Heat/Auto/Dry/Fan), all fan speeds, and all swing options are now exposed as climate card controls.
- **Hot water temperature control** — Tank-based hot water zones now expose a water heater entity with temperature and mode control, matching what the Tado app offers.

### Improvements
- **Faster API calls with async architecture** — The integration's API layer has been rewritten using async I/O, eliminating subprocess overhead and improving per-call latency.

## [1.4.1] - 2026-01-23

### Bug Fixes
- **Fixed login broken after upgrading** — Upgrading from 1.3.x to 1.4.0 could leave your login in a broken state because the token storage format changed. The upgrade path now migrates existing tokens instead of invalidating them.

## [1.4.0] - 2026-01-23

### Features
- **In-app login** — New browser-based authentication flow built into the integration setup. No more SSH or terminal access needed to grab tokens — click a link, sign in, and you're done.
- **Home selection for accounts with multiple homes** — If your Tado account manages more than one home, setup now lets you pick which home this integration entry controls. Add the integration again to add another home.

## [1.2.1] - 2026-01-22

### Bug Fixes
- **Fixed a rare startup issue with duplicate hub cleanup** — Under specific upgrade paths, two Hub devices could end up registered for the same integration. Startup cleanup now correctly deduplicates without removing the wrong entity.

## [1.2.0] - 2026-01-21

**Zone-Based Device Organization**

### Features
- **Each zone now appears as its own device in HA** — Previously every sensor and control sat under a flat "Tado CE" device. Each zone is now its own device containing its climate entity, sensors, and switches, matching how HA users expect to browse by room.
- **Optional weather sensors** — Outdoor temperature, solar intensity, and weather state sensors can now be enabled per-installation via Options Flow.
- **Customizable polling intervals** — Options Flow exposes a polling interval setting so you can balance freshness against API quota.

### Improvements
- **60–70% fewer API calls** — The polling strategy now batches zone reads and defers non-essential endpoints to a longer interval, cutting total API calls dramatically for typical multi-zone installs.

## [1.1.0] - 2026-01-19

### Features
- **Away Mode switch** — New switch on the Hub device to toggle Tado's Away mode directly from HA.
- **Home/Away preset mode support** — Climate entities now expose the Home/Away preset modes, so dashboard climate cards include a presence selector.

## [1.0.1] - 2026-01-18

### Bug Fixes
- **Fixed auto-detection of your home ID** — For accounts with multiple homes, the integration sometimes picked the wrong home ID on setup. Home ID detection now matches the first home you logged in with via the Tado app.

## [1.0.0] - 2026-01-17

### Features
- **Initial release** — First public release of Tado CE as a fork of the official Tado integration with community-driven enhancements.
