# Release Credits

Community contributors who helped shape Tado CE through bug reports, feature requests, testing, and feedback.

---

## v3.0.3

**[@driagi](https://github.com/driagi)** - [Issue #173](https://github.com/hiall-fyi/tado_ce/issues/173)
- Reported hub sensors showing stale data after API sync (API Limit stuck at 5000, Status in error)

---

## v3.0.2

**[@driagi](https://github.com/driagi)** - [Issue #170](https://github.com/hiall-fyi/tado_ce/issues/170), [Issue #173](https://github.com/hiall-fyi/tado_ce/issues/173)
- Reported setup deadlock — integration hangs indefinitely on startup
- Reported hub sensors showing wrong polling interval and API reset time

**[@tigro7](https://github.com/tigro7)** - [Issue #170](https://github.com/hiall-fyi/tado_ce/issues/170)
- Confirmed deadlock issue, provided additional context

**[@mpartington](https://github.com/mpartington)** - [Issue #170](https://github.com/hiall-fyi/tado_ce/issues/170)
- Confirmed deadlock issue affecting users with existing call history data

**[@thefern69](https://github.com/thefern69)** - [Issue #171](https://github.com/hiall-fyi/tado_ce/issues/171), [Discussion #163](https://github.com/hiall-fyi/tado_ce/discussions/163)
- Reported preheat triggering during Away mode
- Requested cooling rate prediction for active target (underfloor heating use case)

---

## v3.0.1

**[@jeverley](https://github.com/jeverley)** - [Issue #167](https://github.com/hiall-fyi/tado_ce/issues/167)
- Reported `[CE]` prefix in entity names after v3.0.0 upgrade

**[@hapklaar](https://github.com/hapklaar)** - [Issue #167](https://github.com/hiall-fyi/tado_ce/issues/167)
- Reported duplicate sensor names in multi-device zones
- Reported entities going unavailable every 5 minutes (token refresh triggering reload)

**[@andyb2000](https://github.com/andyb2000)** - [Issue #167](https://github.com/hiall-fyi/tado_ce/issues/167)
- Confirmed entities going unavailable issue

---

## v3.0.0

**[@robvol87](https://github.com/robvol87)** - [Issue #110](https://github.com/hiall-fyi/tado_ce/issues/110)
- Requested multi-home support

**[@Blankf](https://github.com/Blankf)** - [Issue #145](https://github.com/hiall-fyi/tado_ce/issues/145)
- Requested multi-home support (second account)

**[@thefern69](https://github.com/thefern69)** - [Discussion #163](https://github.com/hiall-fyi/tado_ce/discussions/163), [Issue #164](https://github.com/hiall-fyi/tado_ce/issues/164)
- Requested preheat cooling rate prediction
- Reported preheat sensor triggering a day early

**[@joaomacp](https://github.com/joaomacp)** - [Issue #162](https://github.com/hiall-fyi/tado_ce/issues/162)
- Requested lowering timer minimum to 1 minute

**[@tanerpaca](https://github.com/tanerpaca)** - [Issue #157](https://github.com/hiall-fyi/tado_ce/issues/157)
- Reported window sensor not detecting open windows without Auto-Assist

---

## v2.3.1

**[@BirbByte](https://github.com/BirbByte)** - [Issue #142](https://github.com/hiall-fyi/tado_ce/issues/142)
- Reported AC 'High' fan speed reverting on Mitsubishi/Fujitsu units

**[@slflowfoon](https://github.com/slflowfoon)** - [Issue #127](https://github.com/hiall-fyi/tado_ce/issues/127)
- Reported blocking I/O warning on fresh install

---

## v2.3.0

**[@mpartington](https://github.com/mpartington)** - [Issue #152](https://github.com/hiall-fyi/tado_ce/issues/152)
- Requested enhanced `set_climate_timer` service with optional `time_period`

**[@ChrisMarriott38](https://github.com/ChrisMarriott38)** - [Issue #147](https://github.com/hiall-fyi/tado_ce/issues/147), [Issue #149](https://github.com/hiall-fyi/tado_ce/issues/149)
- Reported mold risk suggesting lower temperature when room is warm
- Reported hot water overlay showing for combi boilers

**[@driagi](https://github.com/driagi)** - [Issue #150](https://github.com/hiall-fyi/tado_ce/issues/150)
- Reported mobile device tracker not updating

---

## v2.2.3

**[@mkruiver](https://github.com/mkruiver)** - [Issue #144](https://github.com/hiall-fyi/tado_ce/issues/144)
- Reported adaptive polling stuck at 120 min for low-quota users

**[@Xavinooo](https://github.com/Xavinooo)** - [Issue #141](https://github.com/hiall-fyi/tado_ce/issues/141)
- Reported night polling using wrong interval

**[@BirbByte](https://github.com/BirbByte)** - [Issue #142](https://github.com/hiall-fyi/tado_ce/issues/142)
- Reported AC 'High' fan speed reverting

**[@merlinpimpim](https://github.com/merlinpimpim)** - [Discussion #139](https://github.com/hiall-fyi/tado_ce/discussions/139)
- Requested climate group support

---

## v2.2.2

**[@Xavinooo](https://github.com/Xavinooo)** - [Issue #134](https://github.com/hiall-fyi/tado_ce/issues/134)
- Reported API options validation and persistence issues

---

## v2.2.1

**[@jeverley](https://github.com/jeverley)** - [Issue #115](https://github.com/hiall-fyi/tado_ce/issues/115)
- Reported hot water config not working for tank-based systems

**[@ChrisMarriott38](https://github.com/ChrisMarriott38)** - [Issue #134](https://github.com/hiall-fyi/tado_ce/issues/134)
- Reported API options not saving

**[@Xavinooo](https://github.com/Xavinooo)** - [Issue #134](https://github.com/hiall-fyi/tado_ce/issues/134)
- Confirmed API options not saving

---

## v2.2.0

**[@tigro7](https://github.com/tigro7)** - [Discussion #112](https://github.com/hiall-fyi/tado_ce/discussions/112)
- Proposed window predicted sensor, actionable recommendations, home/zone insights

**[@BruceRobertson](https://github.com/BruceRobertson)** - [Issue #125](https://github.com/hiall-fyi/tado_ce/issues/125)
- Reported heating cycle never completing for long cycles

**[@slflowfoon](https://github.com/slflowfoon)** - [Issue #127](https://github.com/hiall-fyi/tado_ce/issues/127)
- Reported API call history error on first run

**[@hacker4257](https://github.com/hacker4257)** - [PR #132](https://github.com/hiall-fyi/tado_ce/pull/132)
- Contributed fix for API call history directory creation

**[@jeverley](https://github.com/jeverley)** - [Issue #115](https://github.com/hiall-fyi/tado_ce/issues/115)
- Reported hot water config for tank-based systems

**[@Xavinooo](https://github.com/Xavinooo)** - [Issue #126](https://github.com/hiall-fyi/tado_ce/issues/126)
- Reported polling override issues

**[@BirbByte](https://github.com/BirbByte)** - [Issue #128](https://github.com/hiall-fyi/tado_ce/issues/128)
- Reported AC swing mode issue for Mitsubishi units

---

## v2.1.1

**[@ChrisMarriott38](https://github.com/ChrisMarriott38)** - [Issue #120](https://github.com/hiall-fyi/tado_ce/issues/120), [Issue #119](https://github.com/hiall-fyi/tado_ce/issues/119)
- Reported Test Mode polling using wrong reset time
- Reported hot water zones showing heating-only entities

---

## v2.1.0

**[@ChrisMarriott38](https://github.com/ChrisMarriott38)** - [Issue #90](https://github.com/hiall-fyi/tado_ce/issues/90), [Issue #91](https://github.com/hiall-fyi/tado_ce/issues/91)
- Inspired per-zone surface temp offset for mold risk calibration
- Requested per-zone thermal analytics selection

**[@jakeycrx](https://github.com/jakeycrx)** - [Issue #107](https://github.com/hiall-fyi/tado_ce/issues/107)
- Reported custom polling interval below 5 minutes not working

---

## v2.0.2

**[@wyx087](https://github.com/wyx087)** - [Discussion #102](https://github.com/hiall-fyi/tado_ce/discussions/102)
- Proposed Presence Mode Select to replace Away Mode switch

**[@leoogermenia](https://github.com/leoogermenia)** - [Issue #101](https://github.com/hiall-fyi/tado_ce/issues/101)
- Requested configurable overlay mode

**[@jakeycrx](https://github.com/jakeycrx)** - [Issue #107](https://github.com/hiall-fyi/tado_ce/issues/107)
- Reported custom polling interval below 5 minutes not working

**[@ChrisMarriott38](https://github.com/ChrisMarriott38)** - [Issue #99](https://github.com/hiall-fyi/tado_ce/issues/99)
- Reported polling stuck at 120 min in Uniform Mode

---

## v2.0.1

**[@Claeysjens](https://github.com/Claeysjens)** - [Issue #100](https://github.com/hiall-fyi/tado_ce/issues/100)
- Reported climate entities unavailable after upgrade

**[@ChrisMarriott38](https://github.com/ChrisMarriott38)** - [Issue #90](https://github.com/hiall-fyi/tado_ce/issues/90), [Issue #91](https://github.com/hiall-fyi/tado_ce/issues/91), [Issue #98](https://github.com/hiall-fyi/tado_ce/issues/98), [Issue #99](https://github.com/hiall-fyi/tado_ce/issues/99)
- Reported mold risk dew point calculation issue
- Reported thermal analytics not available for SU02 zones
- Reported hot water UI jumping back after temperature change
- Reported quota reserve not preventing API limit exceeded

---

## v2.0.0

**[@ChrisMarriott38](https://github.com/ChrisMarriott38)** - [Issue #89](https://github.com/hiall-fyi/tado_ce/issues/89), [Issue #90](https://github.com/hiall-fyi/tado_ce/issues/90), [Issue #94](https://github.com/hiall-fyi/tado_ce/issues/94)
- Inspired adaptive smart polling based on remaining quota
- Proposed enhanced mold risk with surface temperature calculation
- Requested quota reserve protection

**[@Fred224](https://github.com/Fred224)** - [Issue #93](https://github.com/hiall-fyi/tado_ce/issues/93)
- Reported hot water timer buttons not finding entity

---

## v1.10.0

**[@hapklaar](https://github.com/hapklaar)**, **[@chinezbrun](https://github.com/chinezbrun)**, **[@neonsp](https://github.com/neonsp)** - [Issue #44](https://github.com/hiall-fyi/tado_ce/issues/44)
- Extensive testing and feedback on climate entity flickering

---

## v1.9.x

**[@hapklaar](https://github.com/hapklaar)** - [Issue #44](https://github.com/hiall-fyi/tado_ce/issues/44)
- Reported hvac_action stuck on "Heating", Resume All Schedules delay, grey loading state

**[@chinezbrun](https://github.com/chinezbrun)** - [Issue #44](https://github.com/hiall-fyi/tado_ce/issues/44)
- Reported grey loading state, slow state confirmation, heating power sensor delay

**[@neonsp](https://github.com/neonsp)** - [Issue #44](https://github.com/hiall-fyi/tado_ce/issues/44)
- Reported AC startup validation warnings, AC optimistic update issues

**[@Fred224](https://github.com/Fred224)** - [Issue #79](https://github.com/hiall-fyi/tado_ce/issues/79)
- Reported AC DRY mode 422 error

**[@thefern69](https://github.com/thefern69)** - [Issue #74](https://github.com/hiall-fyi/tado_ce/issues/74), [Discussion #33](https://github.com/hiall-fyi/tado_ce/discussions/33)
- Reported device migration crash on startup
- Proposed room-aware early start / preheat concept

**[@ChrisMarriott38](https://github.com/ChrisMarriott38)** - [Issue #54](https://github.com/hiall-fyi/tado_ce/issues/54), [Issue #56](https://github.com/hiall-fyi/tado_ce/issues/56), [Issue #64](https://github.com/hiall-fyi/tado_ce/issues/64)
- Reported API reset detection issue with 100-call limit
- Reported device sensors assigned to wrong zone
- Proposed mold risk indicator and environment monitoring

**[@neonsp](https://github.com/neonsp)** - [Issue #61](https://github.com/hiall-fyi/tado_ce/issues/61)
- Reported AC capabilities consuming unnecessary API calls

**[@colinada](https://github.com/colinada)** - [Issue #66](https://github.com/hiall-fyi/tado_ce/issues/66)
- Reported temperature offset only applying to first TRV in multi-TRV rooms

---

## v1.8.x

**[@neonsp](https://github.com/neonsp)** - [Issue #44](https://github.com/hiall-fyi/tado_ce/issues/44), [Issue #61](https://github.com/hiall-fyi/tado_ce/issues/61)
- Reported AC OFF→ON state feedback issues, AC capabilities caching suggestion

**[@hapklaar](https://github.com/hapklaar)** - [Issue #44](https://github.com/hiall-fyi/tado_ce/issues/44), [Discussion #39](https://github.com/hiall-fyi/tado_ce/discussions/39)
- Reported Resume All Schedules delay, requested Resume All Schedules button

**[@ChrisMarriott38](https://github.com/ChrisMarriott38)** - [Issue #54](https://github.com/hiall-fyi/tado_ce/issues/54), [Issue #55](https://github.com/hiall-fyi/tado_ce/issues/55)
- Requested API Reset sensor attributes, suggested Home State Sync default OFF

---

## v1.7.0

**[@neonsp](https://github.com/neonsp)** - [Issue #44](https://github.com/hiall-fyi/tado_ce/issues/44), [Issue #31](https://github.com/hiall-fyi/tado_ce/issues/31)
- Reported UI not updating immediately after state changes
- Requested optional homeState sync to save API calls

---

## v1.6.0

**[@neonsp](https://github.com/neonsp)** - [Issue #31](https://github.com/hiall-fyi/tado_ce/issues/31)
- Reported `climate.set_temperature` ignoring `hvac_mode` parameter

**[@hapklaar](https://github.com/hapklaar)** - [Issue #44](https://github.com/hiall-fyi/tado_ce/issues/44)
- Reported climate entities not updating consistently

---

## v1.5.x

**[@neonsp](https://github.com/neonsp)** - [Issue #31](https://github.com/hiall-fyi/tado_ce/issues/31)
- Comprehensive AC testing — identified all 6 AC issues, provided API response data
- Reported AC Auto mode turning off AC, suggested API call optimization

**[@hapklaar](https://github.com/hapklaar)** - [Discussion #39](https://github.com/hiall-fyi/tado_ce/discussions/39), [Issue #34](https://github.com/hiall-fyi/tado_ce/issues/34)
- Requested Resume All Schedules button
- Reported token loss after HACS upgrade

**[@jeverley](https://github.com/jeverley)** - [Issue #34](https://github.com/hiall-fyi/tado_ce/issues/34)
- Reported token loss after HACS upgrade, requested re-authenticate option

**[@wrowlands3](https://github.com/wrowlands3)** - [Issue #34](https://github.com/hiall-fyi/tado_ce/issues/34)
- Confirmed token loss issue

**[@mkruiver](https://github.com/mkruiver)** - [Issue #36](https://github.com/hiall-fyi/tado_ce/issues/36)
- Reported OAuth flow error for new users

**[@harryvandervossen](https://github.com/harryvandervossen)** - [Discussion #35](https://github.com/hiall-fyi/tado_ce/discussions/35)
- Provided detailed OAuth flow feedback

**[@pisolofin](https://github.com/pisolofin)** - [Issue #24](https://github.com/hiall-fyi/tado_ce/issues/24)
- Requested `get_temperature_offset` service

**[@ohipe](https://github.com/ohipe)** - [Issue #25](https://github.com/hiall-fyi/tado_ce/issues/25)
- Requested optional `offset_celsius` attribute

**[@beltrao](https://github.com/beltrao)** - [Issue #28](https://github.com/hiall-fyi/tado_ce/issues/28)
- Requested frequent mobile device sync option

**[@hapklaar](https://github.com/hapklaar)** - [Issue #26](https://github.com/hiall-fyi/tado_ce/issues/26)
- Reported authentication broken after upgrade

**[@mjsarfatti](https://github.com/mjsarfatti)** - [Issue #26](https://github.com/hiall-fyi/tado_ce/issues/26)
- Confirmed authentication broken after upgrade

---

## v1.4.0

**[@ChrisMarriott38](https://github.com/ChrisMarriott38)** - [Issue #15](https://github.com/hiall-fyi/tado_ce/issues/15), [Issue #16](https://github.com/hiall-fyi/tado_ce/issues/16), [Issue #17](https://github.com/hiall-fyi/tado_ce/issues/17)
- Reported boiler flow temperature issues, API reset time confusion, options UI issues

**[@jeverley](https://github.com/jeverley)** - [Issue #22](https://github.com/hiall-fyi/tado_ce/issues/22)
- Reported climate preset mode stuck on Away

**[@hapklaar](https://github.com/hapklaar)**
- Volunteered for OpenTherm testing

---

## v1.2.x

**[@marcovn](https://github.com/marcovn)** - [Issue #10](https://github.com/hiall-fyi/tado_ce/issues/10), [Issue #11](https://github.com/hiall-fyi/tado_ce/issues/11)
- Reported duplicate hub issue, confusing entity names for multi-device zones

**[@ChrisMarriott38](https://github.com/ChrisMarriott38)** - [Issue #4](https://github.com/hiall-fyi/tado_ce/issues/4), [Issue #10](https://github.com/hiall-fyi/tado_ce/issues/10)
- Extensive feature requests and testing — boiler flow temp, weather sensors, API tracking, polling intervals, test mode
- Confirmed duplicate hub cleanup issue

**[@wrowlands3](https://github.com/wrowlands3)** - [Issue #4](https://github.com/hiall-fyi/tado_ce/issues/4)
- Requested zone-based device organization, improved entity naming

**[@donnie-darko](https://github.com/donnie-darko)** - [Issue #4](https://github.com/hiall-fyi/tado_ce/issues/4)
- Requested `set_water_heater_timer` service, shared solar water heater use case

**[@StreborStrebor](https://github.com/StreborStrebor)** - [Issue #4](https://github.com/hiall-fyi/tado_ce/issues/4)
- Requested immediate refresh after user actions, AC fan/swing mode controls

**[@hapklaar](https://github.com/hapklaar)** - [Issue #2](https://github.com/hiall-fyi/tado_ce/issues/2), [Issue #5](https://github.com/hiall-fyi/tado_ce/issues/5), [Issue #10](https://github.com/hiall-fyi/tado_ce/issues/10)
- Suggested humidity attribute, preset mode support, reported away mode toggle issue
- Generous Buy Me a Coffee supporter! ☕

**[@LorDHarA](https://github.com/LorDHarA)** - [Issue #1](https://github.com/hiall-fyi/tado_ce/issues/1)
- First bug report — identified 403 auth error for new users

**[@MJWMJW2](https://github.com/MJWMJW2)** - [Issue #3](https://github.com/hiall-fyi/tado_ce/issues/3)
- Requested Away Mode switch

**[@ctcampbell](https://github.com/ctcampbell)** - [Issue #6](https://github.com/hiall-fyi/tado_ce/issues/6)
- Requested proper AUTO/HEAT/OFF operation modes for hot water

**[@greavous1138](https://github.com/greavous1138)** - [Issue #7](https://github.com/hiall-fyi/tado_ce/issues/7)
- Reported `duration` parameter not working, requested boost button

**[@thefern69](https://github.com/thefern69)** - [Issue #9](https://github.com/hiall-fyi/tado_ce/issues/9)
- Provided Docker installation instructions

---

## 🌟 Special Thanks

**[@wyx087](https://github.com/wyx087)** - [Discussion #21](https://github.com/hiall-fyi/tado_ce/discussions/21)
- Verified Tado V2 hardware compatibility

**All community members** who tested, reported issues, shared use cases, and supported the project. You make Tado CE better every release.

---

**Made with ❤️ by the Tado CE community**
