# Changelog

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
