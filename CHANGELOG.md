# Changelog

## [0.5.9-beta] - 2026-10-18

Migration: a new `SportFix` table, four new `Settings` columns (`utcStartFixDone`, `garminWeights*`), and one-off repairs of top speeds and imported rides' start times at start-up (all automatic). No Android change.

### Fixed
- **Garmin weight history could have gaps.** The health-history download asked for weigh-ins 28 days at a time, but when that request failed (anything other than Garmin asking it to slow down) it moved on anyway, so that stretch's weigh-ins were never asked for again. It now waits and retries the stretch. Weigh-ins are also fetched on their own, a year per request, across the history range you chose. This runs once on every install, so earlier gaps fill in, and again whenever you change the range or the Garmin account. A weight typed in Headwind or from Home Assistant is never replaced. Progress shows under the history status in Settings → Garmin Connect. `services/garmin.backfill_weigh_ins`, `tests/test_garmin_sync.py`.
- **Rides imported from Strava or from files were counted twice** when Garmin also had them, e.g. a Zwift ride that reaches both. Imported start times were an hour early all summer: FIT files and Strava's `activities.csv` give the start in UTC, and the import took it for UK local time. So the imported copy didn't overlap its Garmin twin, the duplicate check never matched them, and both counted in every total, chart and badge. Imports now read those times as UTC. At start-up, rides already saved this way move to the right local time once, and each one is checked again for a twin. The weaker copy (normally the import, since the Garmin recording has heart rate) is set aside, not deleted, and can be swapped back from the ride page. Weather for those rides was looked up for the wrong hour and isn't refetched. `services/start_times.py`, `services/parser._utc_iso`, `tests/test_start_times.py`.
- **Swims, surf sessions and other sports were saved as rides.** The Garmin sync turned every activity type it didn't recognise into a ride: lap and open-water swimming, surfing, paddling, skiing, golf, and trail and treadmill runs. They counted in the ride totals, charts and Home Assistant sensors, and were flagged as rides that look wrong ("Pool Swimming · only 140 m long"). Runs, walks and hikes it did recognise were still kept with the rides instead of in Workouts. The sync now saves rides as rides, indoor cycling as an indoor ride, and everything else in Workouts under its own sport (Run, Walk, Hike, Swim, Surf, Paddle, Row, Ski, Skate, Golf, Climb or Other), keeping the watch's calories. `services/garmin.garmin_sport`, `tests/test_garmin_sports.py`.
- **Activities already saved with the wrong sport** can be put right from Settings → Garmin Connect → "Check activity types with Garmin" (also linked from the "Rides that look wrong" card). It asks Garmin for the real type of each Garmin ride (100 per call) and lists the wrong ones grouped by sport, all ticked. Apply moves them, and the ones you untick are left alone and not suggested again. A moved activity is remembered, so a re-sync can't bring it back as a ride. `services/sport_fix.py`, `GET /garmin/sports`.
- **Mountain bike rides with a top speed of 86-137 mph.** The Garmin sync took the single highest reading in the speed recording, so one GPS jump became the ride's top speed and the ride was flagged and left out of the speed and weather charts. It now uses the parser's top speed, which ignores anything above 108 km/h. Rides already saved are recomputed from their own speed and GPS data at start-up, and re-checked, so a ride flagged only for that drops off the list. `services/max_stats.fix_spiky_max_speed`.
- **A Garmin workout you deleted could come back** on a full re-sync. Deleting one is now remembered, as it is for rides. `services/workouts.delete`.
- **The links on the "Rides that look wrong" card** used the browser's default blue.

- **Imperial units showed up all over the app with metric chosen.** Many pages, charts and messages converted to miles, feet and mph by hand. Everything now goes through one module (`services/units.py`) and follows the Settings choice:
  - the dashboard's Performance chart and distance filters;
  - the ride page's charts, pace, segment builder and effort speeds;
  - segment and rider pages, including best efforts;
  - every Data page chart, table and the calendar heatmap (the wind chart's axis also said "kph" while its numbers were mph);
  - the AI page, the route planner, Workouts filters and the roughness note;
  - the "looks wrong" reasons (re-worded when you switch units), gear alerts, workout notifications and badge wording.

  The AI coach is now given the ride and its history in your units, instead of in miles. Not yet converted: the Home Assistant sensors, and best-effort distances and badge limits, which are still defined in miles (see TODO). `tests/test_units.py`.

### Added
- **"Delete all blips"** on the "Rides that look wrong" card: one click, with a confirmation, deletes every flagged ride shorter than 160 m (an accidental start and stop). `POST /rides/flagged/delete-blips`.

## [0.5.8-beta] - 2026-10-18

No migration. No Android change.

### Added
- **A clickable dashboard.** Click a weekly bar in the Performance chart to list that week's activities, or a point on the speed line to open that ride. The lifetime tiles and fun stats lead to the full history or the matching Data page section, the weather chip to the weather analysis, and the recovery numbers to Recovery. Each year and month in the history has a "List" link and each day heading is a link, all to that period's activities. Activity rows are now real links, so they can be opened in a new tab or reached with the keyboard. Viewing another rider's dashboard keeps that rider on every link. `routes/dashboard.py`, `templates/dashboard.html`, `tests/test_dashboard_links.py`.

### Fixed
- **Home Assistant kept a deleted ride in its totals** until the next ride arrived, when the ride was deleted on the web (deleting from the phone was fine). The sensors are now re-published straight after the delete. The web pages were never affected: they work their numbers out on every load. `services/ingest.after_ride_removed`.
- **Hovering over a row in an activity table didn't highlight it**, because of a broken rule in the stylesheet. `static/css/style.css`.

## [0.5.7-beta] - 2026-10-17

No migration. No Android change.

### Fixed
- **Some Strava-imported rides were 1,000 times too long** (e.g. a 28.6-mile ride shown as 28,558 miles, and flagged by the sanity check). When a ride's own file couldn't be read (a TCX file, or one of the Trailforks GPX files fixed in 0.5.6-beta), the import fell back to the distance in Strava's `activities.csv`. That file has two `Distance` columns, kilometres then metres, and only the metres one was being read, then multiplied by 1,000 as if it were kilometres. Both columns are now kept and the metres one is used. Rides already imported this way keep their wrong distance: delete them and import the Strava export again (a re-import skips rides it already has). `routes/import_rides.py`, `tests/test_strava_csv.py`.

## [0.5.6-beta] - 2026-10-17

No migration. No Android change.

### Fixed
- **A big import stopped if you left the Import page.** The import ran in the background, but once about 200 rides had been processed with nobody watching, it waited forever for the page to read its progress. It now runs to the end whatever the browser does. Coming back to the Import page picks up the progress where it is, or shows the result if it finished while you were away. `routes/import_rides.py`, `tests/test_import_background.py`.
- **Trailforks GPX rides were rejected as routes.** Trailforks writes timestamps with a lower-case `z` (`2026-07-21T12:05:57z`), which the GPX reader silently ignored, so the ride looked like a route with no times. Timestamps are now read whatever their case, and a file whose `<time>` tags can't be read is logged as such rather than as route-only. `services/parser.parse_gpx`, `tests/test_gpx_times.py`.

### Added
- **Import progress on every page.** While an import runs, the top bar shows "Importing 142 / 800" with a progress line, and links to the Import page. When it finishes, it shows how many rides were imported (or the error) until you dismiss it. `GET /import/progress`.

## [0.5.5-beta] - 2026-10-17

Migration: five new `Settings.garminHistory*` columns, added automatically at startup. No Android change.

### Added
- **Garmin health history on first connect.** When Garmin is connected (setup wizard or Settings), Headwind asks how much past health data to fetch: all of it (the default), 5 / 2 / 1 years, 6 / 3 months, or just the last two weeks. Sleep, HRV, resting HR, body battery, stress, steps and weigh-ins then download in the background. Each 28-day stretch starts with one step-count request, so only days with data get the full set of calls, and days already stored are skipped. "All" stops after about a year with no data, or at 2005. It keeps its place across restarts, Garmin rate limits and outages, and progress shows in Settings. Existing installs are asked once on the Settings page, and switching Garmin accounts asks again. `services/garmin.backfill_history`, `tests/test_garmin_sync.py`.
- **Weight from Garmin Connect.** The Garmin sync now pulls weigh-ins from a Garmin Index scale, or typed into Garmin Connect, into the weight log, so the Nutrition weight trend fills itself in. It keeps the last weigh-in of each day. A weight you typed in Headwind, or one from Home Assistant, is never replaced. `services/garmin._sync_weigh_ins`, `tests/test_garmin_sync.py`.

## [0.5.4-beta] - 2026-10-17

Security and bug fixes from a project-wide review. No migration. No Android change.

**Check before upgrading:** if your reverse proxy reaches Headwind from a *public* address (not the same machine, LAN, Docker network or a local tunnel), set `TRUSTED_PROXIES` to that address, or Headwind will stop believing its `X-Forwarded-*` headers. If you pointed anything at the friend feed with `?token=` in the URL, send the `X-Feed-Token` header instead. Headwind's own friend sync already does.

### Security
- **A friend could pull rides another friend shared only with you.** `/api/riders` listed the riders created by syncing a friend, and `/api/feed?rider=<name>` served their rides, with full GPS and heart-rate streams, to anyone holding your feed token. Both now offer only the riders who live on this instance. `tests/test_friend_feed.py`.
- **The sign-in lockout could be dodged on a directly exposed port.** Headwind believed `X-Forwarded-For` from any client, so each attempt could claim a new address. Forwarded headers are now honoured only from a loopback or private address, or from the addresses in the new `TRUSTED_PROXIES` setting (`none` turns them off). `services/trusted_proxy.py`.
- **The friend feed token is header-only and compared in constant time.** `?token=` in the URL is no longer accepted, because it ends up in proxy access logs. All four feed endpoints now share one check.

### Fixed
- **The MQTT heartbeat thread could die** if a gear-alert sweep failed, stopping MQTT, Home Assistant, weather sync and goal updates until a restart.
- **The Android APK default pointed at a developer's home folder.** Headwind now looks for `headwind.apk` (and an optional `version.txt`) beside the database, or wherever `HEADWIND_APK` points, and the Phones → App page says where to put it.

## [0.5.3-beta] - 2026-10-12

Migration: one new column, `SegmentEffort.approx`, added automatically at startup. No Android change.

### Added
- **Close-match segment efforts.** A ride that clearly rode a segment but was not *perfectly* on it now counts. It must follow the stored shape in the right order, within 75 m, for at least 85% of its length, without looping or wandering, at a believable speed. The time is estimated from the part followed and scaled to the whole segment, so these efforts show a `≈` on the segment and ride pages and **never take a personal best** (exact matches only). Direction, a different road and part-rides are still rejected. Where a ride matched both ways the estimate was within 1% of the exact time. Rescan from the Segments page to pick them up. `services/segments.match_segment_close`, `tests/test_segments_close.py`.

### Fixed
- **Creating a segment dropped the editor below the phone-sensor card**, so the map was off screen while placing the start and end markers. The panel now sits directly under the map.

## [0.5.2-beta] - 2026-10-11

No migration. Android 0.21.2-beta goes with this.

### Fixed
- **A drink added from search or a scan got no alcohol units** when Open Food Facts had no strength for it. A scanned Jack Daniel's, for example, came back with 220 kcal per 100 g and nothing else, so 100 ml logged 0 units. The food card now recognises a drink by its name (whisky, gin, vodka, lager, ale, cider, wine, prosecco and well-known brands) and shows a **Strength (% ABV)** field with a typical strength pre-filled for you to confirm, working out the units live (100 ml at 40% is 4 units). A strength you confirm is remembered with that product, so the next search, scan or phone-app log of it needs no typing (the server also derives and remembers the strength from the units a phone sends). Editing a logged drink shows the strength it implies. Not guessed, on purpose: sauces and food flavoured with a drink (Jack Daniel's BBQ sauce, rum raisin ice cream, ginger biscuits), alcohol-free versions (0.0, 0%), and ready-to-drink mixes and seltzers, where the spirit's own 40% would be about eight times too high (those still show the field, empty). `services/alcohol.recognise`.

## [0.5.1-beta] - 2026-10-11

No migration, nothing to configure; your saved sugar reference is kept. Android 0.21.1-beta goes with this.

### Fixed
- **The Nutrition page layout broke** after the Alcohol ring was added (one `</div>` too many closed the ring grid early, pushing the rest of the page out of shape on some widths). The six rings now sit in one grid: three across on a phone or tablet, six on a wide screen.

### Changed
- **Sugar is total sugar, and is treated as a reference, not a limit.** `FoodLog.sugar` has always been *total* sugars (the label's "of which sugars", per 100 g from Open Food Facts scaled by the portion, or from an earlier log of the same food, or typed by hand), which includes the natural sugars in fruit and milk. UK guidance (about 30 g a day) is for *free* sugars, so a red "over the limit" ring was misleading. The ring is now *Total sugar*, stays its own colour past the number and shows a muted "above reference", the goals field is *Total sugar reference (g)* with a note, and a one-line explanation sits under the rings. Home Assistant gets the same: the Total sugar ring is never red and reads "above / below your reference". The default stays 50 g and is not changed to 30 (that would be wrong for total sugars). Protein, carb and fat targets are untouched. The alcohol ring keeps its red because the weekly alcohol guideline is a real limit. Entity ids are unchanged, so existing Home Assistant history and dashboards keep working.
- The goals API now also returns `sugar_basis: "total"`.

### Not done, on purpose: free / added sugar
Open Food Facts does carry an `added-sugars_100g` field, but it cannot be trusted: in a sample of products from a real diary it was missing on some, zero on strawberry jam (about 62 g total), and larger than the total sugars on others (43.11 g added against 2.3 g total; 52.75 g against 49.7 g). Headwind does not store it and does not estimate added sugar from total sugar. If a reliable source appears (a verified branded-food database, or labels that declare "includes added sugars"), the clean design is a separate nullable `FoodLog.addedSugar` column and per-100g field alongside the existing total, shown as its own gauge against the 30 g free-sugar guidance; existing records would simply have no value.

## [0.5.0-beta] - 2026-10-11

Upgrading is automatic (`FoodLog.alcoholUnits`, `FoodCache.abv`, `Settings.nutritionAlcoholWeekGoal`). Android 0.21.0-beta goes with this.

### Added
- **Alcohol units.** A *Drink* button on the Nutrition page opens presets (pint of lager, ale or cider, half, bottle, can, small / medium / large wine, prosecco, single and double spirit) or a size (ml) and strength (% ABV) with a count; it works out units (one UK unit is 10 ml of pure alcohol) and the calories from the alcohol, and logs them. Scanned or searched drinks that declare a strength in the food database get their units from it (the strength is cached with the product). A violet *Alcohol (week)* ring shows the last seven days against a weekly limit (14 units, the UK guideline, editable under Goals), turning red past it, with today's units under it; meal headers and entries show units; copying a day keeps them. The day endpoint returns an `alcohol` summary (today, week, goal, drinking days), and `/api/v1/sync/nutrition` carries each entry's units to the phone.
- **Home Assistant:** `Nutrition Alcohol Today / Week / Remaining / Goal` sensors and an *Alcohol (week)* ring on the example dashboard.
- **Alcohol and recovery** (Analytics): once there are 5 or more days with 2+ units logged, the morning-after resting heart rate, heart-rate variability and sleep from Garmin are compared with the morning after a dry day (a day only counts as dry if food was logged), with a note that this shows what happens, not why. `services/alcohol.py`.

## [0.4.1-beta] - 2026-10-11

Upgrading is automatic. Android 0.20.1-beta goes with this (it needs this server to show sugar).

### Added
- **Profile & goals card in Settings.** The stats the smart goals work from (sex, age, height, weight now, goal weight, loss target, steps goal, and whether weights show as stone and lb or kg) were hidden inside a collapsed section of the Nutrition page's Goals pop-up, so new users could not find them. They now have their own card under Settings, with a note of what is still missing and the calculated goals, and the Nutrition page shows a nudge to finish the profile until the plan has what it needs. `GET /nutrition/api/profile`.
- **Change an activity's type from a dropdown, everywhere.** The type control was buried in the ride-only Bike card, so a walk or run page had none. Every activity page now has an *Activity type* card (Ride, Indoor ride, Walk, Run, Hike) that confirms and converts, moving the activity between rides and Workouts as needed. On the dashboard, a filtered search offers *Change the type of all N results* for fixing a batch at once (`POST /rides/bulk-sport`).

### Fixed
- **Sugar never reached the phone.** `/api/v1/sync/nutrition` did not include each entry's sugar, so the app showed 0. It now does.

## [0.4.0-beta] - 2026-10-11

Upgrading is automatic (new columns: `Activity.weatherSource / flagReason / flagDismissed`, `FoodLog.sugar`, `SavedMealItem.sugar`, `Settings.nutritionSugarGoal`, plus the roughness and sensor tables from 0.3). Phone app: Android 0.20.0-beta goes with this.

### Added (nutrition)
- **Sugar tracking.** Every food entry now carries sugars (g). It is filled in automatically from the food database's per-100g value (or an earlier log of the same food) and can be typed in the add / edit dialogs. A sugar *limit* (default 50 g, editable under Goals) is shown on the Nutrition page.
- **Macro ring gauges.** The Nutrition page shows protein, carbs, fat, fibre and sugar as filling rings (full = goal reached; the sugar ring turns red past its limit), like the phone app, and each meal's header shows its protein / carbs / fat / fibre / sugar next to its calories.
- **Home Assistant:** sugar sensors (`Nutrition Sugar`, `Sugar Remaining`, `Sugar Goal`, and one per meal), a Sugar ring and per-meal sugar line on the example dashboard, and a sugar trend chart; a 30-day sugar history for the chart.

### Added (weather and storms)
- **Named storms.** A reference table of the 84 UK and Ireland named storms 2015-2026 (Met Office archive). A ride on a named-storm day counts as **Storm** only when the weather at the ride's own place and hour had gusts of 50 km/h or more (a name alone is not proof it reached you); that outranks the lookup's own condition. Rides on a storm day with 40-49 km/h gusts or calm weather, and rides with violent wind (75 km/h+) on an unnamed day, are listed on the Analytics page to confirm with one tap, and every claim can be taken back. New rides are claimed as their weather is saved. `services/storms.py`.


### Fixed
- **Walks and runs: moving time, climb and calories were wrong.** The GPX parser's "stopped" threshold (1 m/s, right for a bike) counted a stroll as standing still, so a 2 h walk became 71 min and the walking equation was fed a 5.5 mph pace. On foot, movement is now judged over a 10 s window (phone GPS repeats positions) with a 0.2 m/s threshold, and climb ignores GPS altitude noise (a recovered walk dropped from 243 m to 92 m).
- **Snow never appeared in the weather-by-condition analytics.** The grouping tested "rain" before "snow", so every snow ride was counted as Rain (the Rain badges had the same problem). Snow (codes 71-77, 85-86) is now its own group, and the chart also counts rides that have a condition but no temperature or wind.
- **Weather backfill skipped almost every old ride.** It only handled rides with a stored start point, but older imports kept just the GPS track (about 95% of the rides on a long-running instance). It now uses the first track point (and fills in the start point), the sync tops up a few old rides each time so history fills in by itself, and a ride the weather service has no data for no longer blocks the queue.
- **Wind arrows on the ride map were hard to see** once the route was drawn in roughness colours: they are now bigger, outlined and drawn on top. The route is no longer coloured by roughness for phone-in-the-pocket recordings (that mostly measures the rider).
- **Roughness map tiles could fail to load** after a filter had shown nothing (the hidden map had zero size). It now re-measures itself, and uses the same satellite imagery and place names as the ride map.
- **Segments are matched automatically on every import path.** Rides arriving through the Garmin sync and the bulk file imports were never scanned against segments (only the single-file import was), so efforts and PRs only appeared after pressing the scan button by hand. They are now scanned as the ride lands (after duplicate resolution, so the surviving recording is the one scanned).

### Added
- **Junk-ride safety rails.** Every new ride (any import path) is checked against generous limits (average over 45 mph, top speed over 80 mph, under 160 m long, a 3-second moving time against a real distance, a climb that does not fit the distance, over 72 hours, over 15,000 kcal). A ride that breaks one is flagged, never deleted: a banner on its page and a card on the dashboard give the reason, with *It's right, keep it* or *Delete*. Flagged rides are left out of the speed and weather analytics until dismissed; a dismissed ride is never flagged again. `services/sanity.py`, `services/ingest.py` (one place for what every new ride gets: sanity check and segment scan).
- **Runs on the dashboard.** Runs now appear in the dashboard's activity list and search (with a RUN tag and a Run filter), alongside rides; ride totals and charts stay ride-only.
- **Workouts is a full history.** The page no longer stops at 90 days: totals, search and filters, and the same year / month / day tree as the dashboard.
- **Analytics are compact and readable:** fixed-height charts (they no longer grow taller on wide screens), junk speeds left out of the weather charts, ride counts shown on the condition chart, and the heatmap shows one band per year (a strip of weeks for long spans) so 14 years fit.
- **Possible fog rides.** Weather models almost never report fog, so rides that started damp and still (97%+ humidity, light wind, no rain) are listed under the condition chart to confirm or reject.
- **Live-ride entities are announced when the server starts** (idle), so the Live card can be added to a dashboard before the first ride is streamed.
- **Rebuild an activity from a sensor recording.** If a phone was left in sensors-only mode and never sent the walk, run or hike itself, `sensors.rebuild_activity` builds it from the recording's own GPS track (the sensor data then attaches to it, and it is idempotent).
- **Set a ride's weather by hand.** The ride page has a *Conditions* dropdown (Clear, Cloudy, Fog, Rain, Snow, Storm, or Automatic) for rides where the lookup is missing or wrong. A chosen condition is kept through every later backfill (only temperature and wind are refreshed around it) and feeds the analytics; *Automatic* hands the ride back to the lookup. New column `Activity.weatherSource`.
- **Estimated cadence from a phone in the pocket** (Android 0.19). Sidecars gain a `cad` column (rpm, from the leg's rhythm in the accelerometer). The ride page's Phone sensors card shows average cadence, time coasting and a cadence chart. Older sidecars without the column keep working.
- **Road roughness map** (new *Roughness* page). The phone's shake readings from sensor recordings that have GPS are laid onto the road: each reading is eased towards a steady 18 mph (square-root scaling: a real ride showed shake grows much slower than linearly with speed), readings on climbs steeper than 6% are dropped (pedalling and rocking the bike swamp the road), averaged into
  about 20 m cells, and rides over the same road average out. Coloured smooth to roughest by percentile of your own roads, with a legend, a period filter (all / 90 days / 30 days), a "roughest spots" list that
  zooms to each one, and phone-in-the-pocket recordings left out unless you tick the box (a pocket mostly measures the rider). `GET /roughness/data` returns the cells. On the ride page the route is also drawn
  coloured by roughness. See `services/roughness.py`.

## [0.3.0-beta] - 2026-10-11

Upgrading is automatic (one new table, `RideSensor`). Nothing changes unless a phone running Headwind Android 0.18 or later sends sensor data.

### Added
- **Phone sensor recordings ("sidecars").** `POST /api/v1/sensors` accepts what a phone's motion sensors saw during a ride: one row per second with roughness (RMS shake), peak shock, gyro, tilt, barometer
  and, if the phone had them, GPS. The sidecar is kept separately from the ride and **attached to whichever ride overlaps it in time**, whichever of the two arrives first (a Garmin Edge ride that syncs
  hours later still picks it up), so the duplicate-recording rule never has to choose between a Garmin and a phone. Idempotent per `client_id`. A phone-recorded ride or run can carry its own.
  Headline numbers are worked out on the server: average and 95th-percentile roughness, biggest shock, maximum tilt, barometric climb, hard-braking events and the three roughest stretches.
  The ride page shows a **Phone sensors** card (roughness and barometric altitude against time, with the stats), `GET /api/v1/rides/<kind>/<id>` returns a `sensors` block, and deleting the ride keeps the
  sidecar for the next ride that overlaps it. Table `RideSensor`.
- **Live ride in Home Assistant.** `POST /api/v1/live` takes the phone's position, speed, distance, elapsed time, elevation, roughness, tilt, pressure and battery every few seconds while it records, and
  publishes them over MQTT (the server stays the only publisher): sensors `Live Ride Status / Sport / Speed / Distance / Elapsed / Elevation / Roughness / Lean / Pressure / Phone Battery` and a
  `Live Ride Position` device tracker whose attributes carry the position, so the HA map card can follow the ride. A final `idle` ends it, and if the phone just stops talking the ride goes idle after
  90 seconds. Discovery config is retained. See `services/live.py`.
- **Example dashboard: Live tab** (`docs/ha/build_dashboard.py`), added only when the Live Ride sensors exist: elapsed, speed, distance, elevation, roughness, lean and pressure while riding, a map card
  with a trail that appears only during a ride, and last-hour graphs. If your Home Assistant also has `sensor.live_ride_distance_home` and `sensor.live_ride_eta_home` (two template sensors, see
  `docs/ha/README.md`) it shows how far from home you are and a rough ETA.

### Fixed
- Start-up no longer rewrites the `SegActivity` view every time (it only does when it is missing or changed), so a start-up, a helper script or a backup running alongside a live instance can no longer hit "database is locked" there.

## [0.2.0-beta] - 2026-10-10

Upgrading is automatic: new columns and tables are added on start-up and nothing is dropped. Existing data is not changed unless you press
*Apply to history* on the calorie setting below.

### Added
- **Calorie burn adjustment** (Settings → *Calorie burn adjustment*). Burn figures from watches and formulas tend to read high, so you can take a
  percentage (0–50%) off every burn estimate **as it is pulled in**: Garmin/FIT/Strava-export rides, phone GPX rides, walks and runs, and Garmin's
  daily totals. Everything downstream (dashboards, MQTT/Home Assistant, the API, the phone app) then carries the corrected number. The original is
  kept alongside (`caloriesRaw`, and `totalCaloriesRaw`/`activeCaloriesRaw` on `GarminDaily`), so it is reversible: *Save and apply to history*
  re-works your own stored rides, walks/runs and Garmin totals from the originals, and can be re-run with a different percentage. Never touched:
  food calories, numbers you type in yourself, and rides received from friends (their own instance applies its own setting). Default is 0 (off).
  `/api/v1/today` now includes `calorie_adjust_pct` so the phone app applies the same figure to its live estimate.
- **Running: stats from your recorded runs.** Best times for 1 km, 1 mile, 3 km, 5 km, 10 km, 15 km, half and full marathon (the fastest stretch of
  that distance inside any one run, from the GPS, so a 10 km run also gives a 5 km time), pace, totals for this week/month/year/all time, 12 weeks of
  distance, recent runs, longest run, fastest pace and the latest route. Recordings under 400 m or 2 minutes are ignored. Runs come from the phone app
  (Workouts) or from a Garmin. Best times are cached per run in the new `RunEffort` table. Published to Home Assistant as
  `Nutrition Run Stats`, `Nutrition Run Route` and `Nutrition Run Segments` sensors.
- **Run segments.** Segments now have a sport: **ride** or **run**. Runs only match run segments and rides only match ride segments (a walk or hike
  has none), with a slower minimum speed for runs. Create a run segment from a run's page: phone-recorded runs and walks now open the same page as a
  ride (map, elevation, segments table, *Create Segment*), linked from each row on **Workouts**. The **Segments** page has *Ride segments* / *Run
  segments* tabs, and run segments show **pace per mile** instead of mph. Efforts and PRs work across runs from the phone and from a Garmin, a new run
  is matched as soon as it arrives, deleting a run or changing its type removes/recreates its efforts and re-picks the PRs, and run segments are shared
  with linked friends (older peers without the field treat everything as a ride). New `Segment.sport` column and a `SegActivity` view over rides and
  workouts for leaderboard queries.
- **Home Assistant: route map and segments.** New `Nutrition Ride Route` / `Nutrition Ride Segments` sensors carry the latest ride's track (thinned to
  fit an attribute) and the segments it crossed, with your time, rank, gap to your best and comparison with last time. The example dashboard
  (`docs/ha/build_dashboard.py`) gets a **map card** (route over map tiles, segments overlaid, PRs in gold) and a **segments card** on the Riding tab,
  and a new **Running** tab: latest run and map, best times, totals, weekly distance, recent runs and run segments. Gaps are shown as minutes and seconds.
- The example dashboard's **cycling outlook** card (next few hours and tomorrow) appears only if your Home Assistant has `sensor.cycling_conditions` and
  `sensor.cycling_verdict`; `docs/ha/deploy.py` now checks, so a standard install is not asked for entities it does not have.

### Changed
- Segment leaderboards, the Segments list and segment pages read activities through the new `SegActivity` view, so a segment's efforts can come from
  either a ride or a phone-recorded run. Ride behaviour is unchanged.
- Weight pace: when the short window reads flat or gaining only because of a holiday spike but the 12-week trend is a real loss, the 12-week pace is used.

### Added (earlier, same release)
- **Change an activity's type** (e.g. a walk that was recorded as a ride): a Type picker on the ride page and on each Workouts row, and in the phone app. Moving between rides and walks/runs/hikes moves the activity and re-estimates its calories for the new sport.
- **Gear: assign a date range from a bike's own page** (the full calendar is still there, and opens with the bike pre-selected).
- **Gear: bikes, parts and service** (new sidebar item, guide in `docs/GEAR.md`). Add bikes with photos and a default bike per rider (new rides get it automatically, whichever way they arrive),
  assign older rides by **calendar** (click days, shift-click, or a from/to range such as "everything from 1 March to today", with a preview of exactly what will change), and pick the bike on any
  ride from a dropdown. Per-bike odometer and stats. Track **replaceable parts** (chain, cassette, chainrings, tyres, tubeless sealant, brake pads/rotors/fluid, cables, bar tape, headset and wheel
  bearings, bottom bracket, cleats, suspension service, or your own) with editable check/replace intervals by distance and/or days, a **service log** (replacing a part retires it and fits a fresh one),
  and soon/due/overdue **alerts** (ntfy + Home Assistant push, once per level, plus a dashboard card). Mileage is computed from your rides, so correcting a ride's bike corrects every part.
  New tables `Bike`, `Part`, `ServiceLog`, `PartAlert`; `Activity.bikeId`, `Rider.defaultBikeId`. Bike photos live in `bikeimg/` beside the database and are part of backup/restore.
- **The same ride recorded twice is now handled.** If a ride arrives from two devices (say the phone app AND a Garmin), Headwind keeps the better
  recording (Garmin device > heart rate > power > cadence > GPS detail) and parks the other. Nothing is deleted: the ride page shows an
  "also recorded by another device" card with *Use that recording instead*, *They are different rides - keep both* and *Delete the other
  recording*. Parked rides live in `ActivityDuplicate`, so every existing stat, chart and sensor still sees exactly one ride. Matching is on
  the real UTC instant plus time overlap and distance (within 15%), never on local-time strings. Notes you typed on the parked ride are
  copied to the kept one. Existing history can be checked with `python3 scripts/resolve_existing_duplicates.py` (dry run by default).
- **Add an activity by hand** (Workouts page, and the phone app): a ride you forgot to record, a turbo session, a walk without GPS. Rides land in
  `Activity` (no map), walks/runs/hikes in `Workout`. If a real recording of the same ride turns up later it wins and the typed-in copy is parked.
- **Delete from the Workouts page** (and from the phone app, for rides and workouts). A deleted ride is remembered so a Garmin re-sync does not
  bring it back; uploading the file yourself can.

### Changed
- Phone/GPX recordings now store the UTC instant in `startDate` and the home-timezone local time in `startDateLocal` (they used to store the UTC
  time as "local", an hour out in summer, which is how the duplicate above went unnoticed). Old rows are untouched; the duplicate script can
  fix chosen ones with `--ids`.
- The Garmin sync no longer skips its copy of a ride just because a phone/file copy exists; it keeps whichever recording is better.

### Fixed
- **Max speed on imported rides was the average speed.** Imports (FIT/GPX files, Strava export, phone uploads) now store the real max
  speed, and also max heart rate and max power. Existing rides can be repaired with `python3 scripts/backfill_max_stats.py` (dry run by
  default; `--apply` to write; only rows showing the old bug are touched).
- **FIT files from newer devices** that write only `enhanced_altitude` / `enhanced_speed` no longer lose elevation and speed.
- **GPX power** (heart-rate-style extension tags) is now read.
- **Headwind/tailwind on loop rides.** The label used one start-to-finish bearing, which is meaningless for a loop. It is now judged over
  the whole route; loops that get both are labelled "Mixed". Existing labels are left as they were (`--rewind-wind` on the backfill
  script re-labels them, which can change badge counts).

## [0.1.0-beta] - 2026-10-03

First public beta of Headwind — a self-hosted cycling, nutrition and body-tracking server. An Android companion app is in development (work in progress, not yet released).
The project history was reset for this release; earlier internal version numbers (1.x) no longer apply.

### Highlights
- Ride import (FIT/GPX/Strava export zip), Garmin Connect sync (MFA-capable), analytics, heatmaps, custom segments,
  best efforts, badges, route planning.
- Nutrition: food logging (Open Food Facts, custom foods, recipes, saved meals), hydration, weight trends and goals.
- Optional: AI coaching (your own OpenAI-compatible key or local Ollama), Home Assistant / MQTT sensors, P2P friend feeds.
- Phone API (paired per-device tokens) used by the Android app, which is still a work in progress.

### Security notes
- **No default login.** If `SECRET_KEY` / `APP_PASSWORD` are unset (or still placeholders), a random signing key and admin
  password are generated on first start and stored in your data directory; the password is printed once in the logs
  (`docker logs headwind`). Set your own in `.env` if you prefer.
- Backup restore migrates and smoke-tests the uploaded database before touching live data, then swaps it in atomically; uploads can't choose file paths. Backups contain the credentials you configured in Settings — keep them private.
- A password changed in Settings now persists across container recreation (unless you later edit the credentials in `.env`).
- Login throttling, session invalidation on password change, cross-site request blocking, input size limits.
- One optional, consent-gated, anonymous install ping (random id + version only) — opt out in the setup wizard or with
  `TELEMETRY=off`.

### Platforms
- Docker (amd64 + arm64) and an experimental Windows build (`Headwind-windows-x64.zip`, see the README).

### One person per instance
- New installs track one person (the setup wizard asks for one name; the Riders page becomes a profile). A second person runs their own instance and links as a friend. `HEADWIND_MULTI_RIDER=1` (or an install that already had several local riders) keeps the multi-rider UI.

### Known limitations (beta)
- One shared admin login; in the advanced multi-rider mode phone tokens are not scoped per rider.
- Admin password is stored in plaintext in your data directory / `.env` (file mode 600 for generated ones).
- The Android app is a work in progress — expect rough edges and no public release yet.
- The arm64 (Raspberry Pi) image is new and has had little real-world testing. The Windows build is experimental and unsigned.
