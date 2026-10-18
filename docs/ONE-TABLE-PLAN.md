# One table for every activity: query audit

**Status:** release 1 done in 0.7.0-beta. Every statement below was changed as its category says, except that a sport change already became a label change (planned for release 2), so `services/convert.py` no longer moves rows. What release 2 still has to do is in the TODO entry.

Release 1 of **One table for every activity** (TODO.md, Multi-sport) moves `Workout` rows into `Activity`. This file sorts every SQL statement that touches `Activity` by what it needs then, so the change can be made file by file and checked off. Made 2026-10-18 at 0.6.6-beta. Line numbers drift as code changes: the function names are the stable reference.

**How the list was made.** Every string literal in the Python code (outside `tests/`) that matches `FROM`, `JOIN`, `INTO` or `UPDATE Activity` was extracted with its enclosing function, using Python's `ast`. That found 241 statements in 50 files. The earlier figure of 209 came from a grep that missed SQL spanning several lines. Statements that name the table through a variable are not in the tables; they are listed under **Not found by the search**.

## Two definitions release 1 needs

- **`Ride` view**: `Activity` rows whose sport is a ride. Use the test `services/gear.py` already has (`RIDE_SQL`: the sport contains "ride" or "cycl", ignoring case), so Strava's "Virtual Ride", "E-Bike Ride", "Gravel Ride" and "Mountain Bike Ride" count, and treat a NULL sport as a ride, as `_insert` in `routes/import_rides.py` does. `convert.RIDES` and `manual_activity.RIDE_SPORTS` (`Ride`, `VirtualRide`) are the sports Headwind writes itself; both should read from the one definition.
- **`Workout` view**: the other `Activity` rows, with `sportType` renamed to `sport`, so the ~42 places that read `Workout` keep working until release 2.

## What changes on screen

Release 1 is meant to change nothing except the duplicates, but two things will:
- **Ride totals drop.** Strava walks, runs, swims and gym sessions ("Workout", "Weight Training") sit in `Activity` today and count as rides on the dashboard, Data page, badges and Home Assistant. Through `Ride` they stop counting. That's correct, but say so in the changelog with a before and after.
- **The history list shows every sport** (decided 2026-10-18), with a choice of sports to leave out. That is `routes/dashboard.py` `dashboard` below.

## Summary

| Category | Statements | What to do |
|---|---:|---|
| Reads Workout too: fix in release 1 | 9 | Left as it is, it counts every workout twice. Either point this half at `Ride` or drop the Workout half (see each note). Release 2 makes each one `Activity` query. |
| Picks the table by kind: fix in release 1 | 8 | Use `Ride` for the ride branch; the workout branch reads the `Workout` view. Release 2 decides by sport family. |
| Ride-only read: use `Ride` | 83 | Point at `Ride`. Nothing changes on screen. |
| Every sport: stays on `Activity` | 8 | Keep on `Activity`: workouts are meant to be seen here. |
| By id: stays on `Activity` | 41 | Keep. The row is the one asked for, whatever its sport. |
| Through a ride-only table: stays on `Activity` | 13 | Keep. The other table already holds rides only. |
| Write: stays on `Activity` | 45 | Keep. |
| Scripts, demo, docstrings | 34 | Handle with the demo and scripts. |
| **Total** | **241** | |

### Reads Workout too: fix in release 1 (9)

| Where | Function | Statement | Note |
|---|---|---|---|
| `database.py:567` | `migrate_db` | `CREATE VIEW SegActivity AS SELECT id, name, riderId, startDateLocal, sportType, 'activity' AS kind FROM Act…` | `SegActivity` view: UNION of Activity and Workout. Once Workout is a view of Activity, every non-ride row appears twice. Not `Ride`: rewrite in release 1 as one SELECT from Activity, `kind` from the sport family |
| `routes/api_v1.py:115` | `tot` | `SELECT COUNT(*) n, SUM(distance) d, SUM(totalElevationGain) e, SUM(movingTime) t, SUM(calories) c FROM Acti…` | phone totals; workouts are added separately by `wk()` |
| `routes/api_v1.py:256` | `rides` | `SELECT 'ride' kind, CAST(id AS TEXT) id, name, sportType sport, startDateLocal, distance, movingTime, total…` | phone history: UNION ALL with Workout. Ride now; release 2 one SELECT |
| `routes/nutrition.py:1184` | `day_log` | `SELECT COALESCE(SUM(calories), 0) as total FROM Activity WHERE riderId=? AND date(startDateLocal)=? AND cal…` | Nutrition day burn: walks and runs are added separately by `workouts.calories_on` |
| `routes/nutrition.py:1685` | `week_log` | `SELECT COALESCE(SUM(calories),0) as total FROM Activity WHERE riderId=? AND date(startDateLocal)=?` | Nutrition day burn: walks and runs are added separately by `workouts.calories_on` |
| `services/goal_model.py:165` | `day_burn` | `SELECT calories, movingTime FROM Activity WHERE riderId=? AND date(startDateLocal)=? AND calories IS NOT NULL` | `goal_model.day_burn`: walks and runs are added separately by `workouts.net_calories_on` |
| `services/mqtt.py:306` | `_gather_nutrition` | `SELECT COALESCE(SUM(calories),0) as cal FROM Activity WHERE riderId=? AND date(startDateLocal)=? AND calori…` | Home Assistant nutrition burn: walks and runs are added separately by `workouts.calories_on` |
| `services/run_stats.py:73` | `_runs` | `SELECT id, name, startDateLocal d, distance, movingTime, totalElevationGain gain, averageHeartrate hr, stre…` | `run_stats._runs`: Activity runs + Workout runs. Once merged, Workout runs come back twice. Not `Ride` (that drops the runs): drop the Workout half |
| `services/segments.py:428` | `scan_all_activities` | `SELECT id, startDateLocal, streams, sportType FROM Activity WHERE streams IS NOT NULL AND streams NOT IN ('…` | segment rescan: also reads Workout runs straight after (`services/segments.py:431`). Not `Ride` (run segments need the runs): drop the Workout half |

### Picks the table by kind: fix in release 1 (8)

| Where | Function | Statement | Note |
|---|---|---|---|
| `routes/api_v1.py:272` | `preview` | `SELECT streams, summaryPolyline FROM Activity WHERE id=?` | phone preview / delete pick the table by `kind` |
| `routes/api_v1.py:334` | `ride_detail` | `SELECT * FROM Activity WHERE id=? AND riderId=?` | phone ride detail: `kind=ride` reads Activity, `kind=workout` reads Workout |
| `routes/api_v1.py:580` | `delete_ride` | `SELECT riderId FROM Activity WHERE id=?` | phone preview / delete pick the table by `kind` |
| `routes/kudos.py:24` | `_ensure_weather` | `SELECT * FROM Activity WHERE id=?` | AI kudos for one ride; a walk must keep getting a 404 |
| `routes/kudos.py:37` | `kudos` | `SELECT * FROM Activity WHERE id=?` | AI kudos for one ride; a walk must keep getting a 404 |
| `routes/rides.py:90` | `detail` | `SELECT a.*, r.name AS riderName, r.avatarPath AS riderAvatar, r.isDefault AS riderIsDefault FROM Activity a…` | ride page: falls back to `_workout_as_activity` when Activity has no such id. Reading Activity would show a walk as a ride (bike, power). Ride now; release 2 one SELECT |
| `services/bulk.py:9` | `_kind` | `SELECT 1 FROM Activity WHERE id=?` | bulk `_kind`: Activity means "ride". Decide by sport family instead |
| `services/convert.py:88` | `change_sport` | `SELECT * FROM Activity WHERE id=?` | `convert.change_sport(kind="ride")` reads Activity |

### Ride-only read: use `Ride` (83)

| Where | Function | Statement | Note |
|---|---|---|---|
| `app.py:148` | `_garmin_heartbeat` | `SELECT a.id, a.startDate, a.elapsedTime, a.streams FROM Activity a JOIN Rider r ON r.id = a.riderId WHERE r…` | fills missing heart rate from Garmin for the owner's rides |
| `routes/ai_page.py:97` | `index` | `SELECT COUNT(*) FROM Activity` | AI kudos: the coach is rides only |
| `routes/ai_page.py:98` | `index` | `SELECT COUNT(*) FROM Activity WHERE aiKudos IS NOT NULL AND aiKudos != ''` | AI kudos: the coach is rides only |
| `routes/ai_page.py:141` | `generate` | `SELECT * FROM Activity {…} ORDER BY startDateLocal ASC` | AI kudos: the coach is rides only |
| `routes/ai_page.py:189` | `count` | `SELECT COUNT(*) FROM Activity {…}` | AI kudos: the coach is rides only |
| `routes/api_v1.py:128` | `overview` | `SELECT DISTINCT sportType FROM Activity WHERE riderId=? AND sportType IS NOT NULL ORDER BY sportType` | phone overview: ride sports (workout sports come from Workout separately) |
| `routes/api_v1.py:162` | `perform` | `SELECT id, name, totalElevationGain, date(startDateLocal) as d FROM Activity WHERE riderId=? AND totalEleva…` | phone Performance: top climbs, segment summary |
| `routes/api_v1.py:169` | `perform` | `SELECT s.id, s.name, s.distanceM, s.elevationGainM, COUNT(e.id) AS effort_count, MIN(e.elapsedSecs) AS best…` | phone Performance: top climbs, segment summary |
| `routes/dashboard.py:22` | `_weekly_data` | `SELECT SUM(distance) as total, SUM(totalElevationGain) as elev, SUM(calories) as cals FROM Activity WHERE r…` | Performance chart weekly totals |
| `routes/dashboard.py:150` | `dashboard` | `SELECT COUNT(*) as rides, SUM(a.distance) as dist, SUM(a.totalElevationGain) as elev, SUM(a.movingTime) as …` | dashboard totals: rides only until **Every sport in the dashboard and stats** |
| `routes/dashboard.py:196` | `dashboard` | `SELECT id, date(startDateLocal) as d, averageSpeed, name FROM Activity WHERE riderId=? AND strftime('%Y', s…` | dashboard speed line |
| `routes/data.py:37` | `index` | `SELECT DISTINCT sportType FROM Activity WHERE riderId=? AND sportType IS NOT NULL ORDER BY sportType` | Data page (rides; its sport filter narrows within rides) |
| `routes/data.py:51` | `index` | `SELECT date(startDateLocal) as d, averageSpeed FROM Activity {…} ORDER BY startDateLocal` | Data page (rides; its sport filter narrows within rides) |
| `routes/data.py:70` | `index` | `SELECT strftime('%Y-%m', startDateLocal) as ym, SUM(distance) as dist FROM Activity {…} GROUP BY ym ORDER B…` | Data page (rides; its sport filter narrows within rides) |
| `routes/data.py:84` | `index` | `SELECT strftime('%Y', startDateLocal) as yr, CAST(strftime('%m', startDateLocal) AS INTEGER) as mo, SUM(dis…` | Data page (rides; its sport filter narrows within rides) |
| `routes/data.py:104` | `index` | `SELECT COUNT(*) as n FROM Activity {…}` | Data page (rides; its sport filter narrows within rides) |
| `routes/data.py:117` | `index` | `SELECT CAST(strftime('%w', startDateLocal) AS INTEGER) as dow, COUNT(*) as n FROM Activity {…} GROUP BY dow` | Data page (rides; its sport filter narrows within rides) |
| `routes/data.py:132` | `index` | `SELECT date(startDateLocal) as d, calories FROM Activity {…} ORDER BY startDateLocal` | Data page (rides; its sport filter narrows within rides) |
| `routes/data.py:151` | `index` | `SELECT date(startDateLocal) as d, SUM(distance) as dist FROM Activity {…} GROUP BY d` | Data page (rides; its sport filter narrows within rides) |
| `routes/data.py:192` | `index` | `SELECT id, name, totalElevationGain, startDateLocal, strftime('%Y', startDateLocal) as yr, strftime('%Y-%m'…` | Data page (rides; its sport filter narrows within rides) |
| `routes/data.py:234` | `index` | `SELECT id, averageSpeed, weatherTempC, weatherWindKph, weatherWindRel, weatherCode, strftime('%m', startDat…` | Data page (rides; its sport filter narrows within rides) |
| `routes/data.py:278` | `index` | `SELECT averageSpeed, weatherCode FROM Activity {…}` | Data page (rides; its sport filter narrows within rides) |
| `routes/friends.py:117` | `generate` | `SELECT id, name, type, sportType, startDate, startDateLocal, distance, movingTime, elapsedTime, totalElevat…` | friend feed export: friends' instances store what they get as rides. Rides only until the feed carries a sport family |
| `routes/friends.py:473` | `_do_ride_sync` | `SELECT id, startDateLocal, streams FROM Activity WHERE riderId=? AND streams IS NOT NULL AND streams NOT IN…` | friend sync re-scans the friend's rides for segments and best efforts |
| `routes/friends.py:495` | `_do_ride_sync` | `SELECT id, startDateLocal, streams FROM Activity WHERE riderId=? AND streams IS NOT NULL AND streams NOT IN…` | friend sync re-scans the friend's rides for segments and best efforts |
| `routes/garmin_page.py:22` | `index` | `SELECT DISTINCT date(startDateLocal) as d FROM Activity WHERE date(startDateLocal) >= date('now', ? \|\| ' …` | Garmin page chart: markers on days with a ride |
| `routes/heatmap.py:16` | `index` | `SELECT MIN(date(startDateLocal)) as min_d, MAX(date(startDateLocal)) as max_d FROM Activity WHERE streams I…` | heatmap (later: every sport) |
| `routes/heatmap.py:21` | `index` | `SELECT DISTINCT sportType FROM Activity WHERE sportType IS NOT NULL AND streams IS NOT NULL AND streams != …` | heatmap (later: every sport) |
| `routes/heatmap.py:95` | `data` | `SELECT streams FROM Activity {…}` | heatmap (later: every sport) |
| `routes/riders.py:23` | `_nth_ride` | `SELECT id, startDateLocal FROM Activity WHERE riderId=? ORDER BY startDateLocal LIMIT 1 OFFSET ?` | badges: cycling milestones |
| `routes/riders.py:28` | `_dist_milestone` | `SELECT id, startDateLocal FROM ( SELECT id, startDateLocal, SUM(distance) OVER (ORDER BY startDateLocal) as…` | badges: cycling milestones |
| `routes/riders.py:38` | `_elev_milestone` | `SELECT id, startDateLocal FROM ( SELECT id, startDateLocal, SUM(totalElevationGain) OVER (ORDER BY startDat…` | badges: cycling milestones |
| `routes/riders.py:49` | `_first_ride` | `SELECT id, startDateLocal FROM Activity WHERE riderId=? AND {…} ORDER BY startDateLocal LIMIT 1` | badges: cycling milestones |
| `routes/riders.py:54` | `_compute_badges` | `SELECT COUNT(*) as n FROM SegmentEffort e JOIN Activity a ON a.id=e.activityId WHERE a.riderId=?` | badges: cycling milestones |
| `routes/riders.py:59` | `_compute_badges` | `SELECT COUNT(*) as n FROM SegmentEffort e JOIN Activity a ON a.id=e.activityId WHERE a.riderId=? AND e.isPR=1` | badges: cycling milestones |
| `routes/riders.py:66` | `_compute_badges` | `SELECT MAX(cnt) as m FROM ( SELECT COUNT(*) as cnt FROM SegmentEffort e JOIN Activity a ON a.id=e.activityI…` | badges: cycling milestones |
| `routes/riders.py:74` | `_compute_badges` | `SELECT MAX(e.avgSpeedMps) as v FROM SegmentEffort e JOIN Activity a ON a.id=e.activityId WHERE a.riderId=?` | badges: cycling milestones |
| `routes/riders.py:81` | `_nth_effort` | `SELECT a.id, a.startDateLocal FROM SegmentEffort e JOIN Activity a ON a.id=e.activityId WHERE a.riderId=? O…` | badges: cycling milestones |
| `routes/riders.py:89` | `_first_effort_speed` | `SELECT a.id, a.startDateLocal FROM SegmentEffort e JOIN Activity a ON a.id=e.activityId WHERE a.riderId=? A…` | badges: cycling milestones |
| `routes/riders.py:99` | `_count_cond` | `SELECT COUNT(*) as n FROM Activity WHERE riderId=? AND {…}` | badges: cycling milestones |
| `routes/riders.py:104` | `_nth_cond` | `SELECT id, startDateLocal FROM Activity WHERE riderId=? AND {…} ORDER BY startDateLocal LIMIT 1 OFFSET ?` | badges: cycling milestones |
| `routes/riders.py:122` | `_first_repeat` | `SELECT a.id, a.startDateLocal FROM SegmentEffort e JOIN Activity a ON a.id=e.activityId WHERE a.riderId=? A…` | badges: cycling milestones |
| `routes/riders.py:135` | `_compute_badges` | `SELECT MAX(distance) as max_dist, MAX(totalElevationGain) as max_elev, MAX(averageSpeed) as max_speed, MAX(…` | badges: cycling milestones |
| `routes/riders.py:149` | `_compute_badges` | `SELECT MIN(weatherTempC) as min_temp FROM Activity WHERE riderId=? AND weatherTempC IS NOT NULL` | badges: cycling milestones |
| `routes/riders.py:155` | `_compute_badges` | `SELECT id, startDateLocal, weatherTempC FROM Activity WHERE riderId=? AND weatherTempC IS NOT NULL ORDER BY…` | badges: cycling milestones |
| `routes/riders.py:160` | `_compute_badges` | `SELECT id, startDateLocal, weatherWindKph, weatherGustKph FROM Activity WHERE riderId=? AND weatherWindKph …` | badges: cycling milestones |
| `routes/riders.py:381` | `index` | `SELECT r.*, COUNT(a.id) AS ride_count, SUM(a.distance) AS total_dist FROM Rider r LEFT JOIN Activity a ON a…` | Riders page: ride count and distance, rider totals, recent rides |
| `routes/riders.py:400` | `detail` | `SELECT COUNT(*) as rides, SUM(distance) as dist, SUM(totalElevationGain) as elev, SUM(movingTime) as secs, …` | Riders page: ride count and distance, rider totals, recent rides |
| `routes/riders.py:406` | `detail` | `SELECT id, name, sportType, startDateLocal, distance, movingTime, totalElevationGain, averageSpeed FROM Act…` | Riders page: ride count and distance, rider totals, recent rides |
| `routes/riders.py:412` | `detail` | `SELECT s.name AS seg_name, s.id AS seg_id, e.elapsedSecs, e.activityDate, e.avgSpeedMps FROM SegmentEffort …` | rider page segment PRs |
| `routes/rides.py:135` | `detail` | `SELECT DISTINCT r.id, r.name, r.avatarPath FROM Activity a JOIN Rider r ON r.id = a.riderId WHERE date(a.st…` | ride page: who else rode that day |
| `routes/rides.py:200` | `detail` | `SELECT id, name FROM Activity WHERE startDateLocal < ? AND riderId IS ? ORDER BY startDateLocal DESC LIMIT 1` | ride page previous / next ride (later: every activity) |
| `routes/rides.py:206` | `detail` | `SELECT id, name FROM Activity WHERE startDateLocal > ? AND riderId IS ? ORDER BY startDateLocal ASC LIMIT 1` | ride page previous / next ride (later: every activity) |
| `routes/rides.py:229` | `detail` | `SELECT COUNT(*) as rides, SUM(distance) as dist, SUM(totalElevationGain) as elev FROM Activity WHERE riderId=?` | ride page: rider totals |
| `routes/settings.py:270` | `<module>` | `FROM Activity WHERE weatherSummary IS NULL AND startDateLocal IS NOT NULL AND (startLat IS NOT NULL OR stre…` | Settings: count of rides without weather (goes with `services/weather.py:304`) |
| `routes/sync.py:49` | `sync` | `SELECT a.id, a.startDate, a.elapsedTime, a.streams FROM Activity a JOIN Rider r ON r.id = a.riderId WHERE r…` | fills missing heart rate (as `app.py:148`) |
| `services/best_efforts.py:104` | `scan_all_best_efforts` | `SELECT id, startDateLocal, streams FROM Activity WHERE streams IS NOT NULL AND streams NOT IN ('null', '{}')` | best-effort rescan: BestEffort is for rides (runs have RunEffort) |
| `services/context.py:366` | `_build_badge_context` | `SELECT COUNT(*) as rides, SUM(distance) as dist, SUM(totalElevationGain) as elev FROM Activity WHERE riderId=?` | AI badge context |
| `services/gear.py:244` | `assign_rides` | `FROM Activity a WHERE a.riderId=? AND {…} AND {…}` | gear: already filters with `RIDE_SQL`; switch to Ride for one definition |
| `services/gear.py:249` | `assign_rides` | `SELECT a.bikeId, COUNT(*) FROM Activity a WHERE a.riderId=? AND {…} AND {…}{…}{…} GROUP BY a.bikeId` | gear: already filters with `RIDE_SQL`; switch to Ride for one definition |
| `services/gear.py:260` | `calendar_month` | `SELECT substr(a.startDateLocal,1,10) d, a.bikeId b, COUNT(*) n FROM Activity a WHERE a.riderId=? AND {…} AN…` | gear: already filters with `RIDE_SQL`; switch to Ride for one definition |
| `services/gear.py:275` | `ride_span` | `SELECT MIN(substr(a.startDateLocal,1,10)), MAX(substr(a.startDateLocal,1,10)), SUM(a.bikeId IS NULL), COUNT…` | gear: already filters with `RIDE_SQL`; switch to Ride for one definition |
| `services/gear.py:276` | `ride_span` | `SELECT MIN(substr(a.startDateLocal,1,10)) FROM Activity a WHERE a.riderId=? AND {…} AND a.bikeId IS NULL` | gear: already filters with `RIDE_SQL`; switch to Ride for one definition |
| `services/max_stats.py:21` | `backfill` | `SELECT id, streams, averageSpeed, maxSpeed, maxHeartrate, maxWatts, weatherWindDir, weatherWindKph, weather…` | top speed and max-stat backfills (ride streams) |
| `services/max_stats.py:58` | `fix_spiky_max_speed` | `SELECT id, streams FROM Activity WHERE maxSpeed > ?` | top speed and max-stat backfills (ride streams) |
| `services/mqtt.py:460` | `_ride_route_payloads` | `SELECT id, name, startDateLocal, distance, movingTime, streams FROM Activity WHERE riderId=? ORDER BY start…` | Home Assistant last-ride route and segments |
| `services/mqtt.py:472` | `_ride_route_payloads` | `SELECT e2.elapsedSecs secs, a2.startDateLocal d FROM SegmentEffort e2 JOIN Activity a2 ON a2.id=e2.activity…` | Home Assistant last-ride route and segments |
| `services/mqtt.py:486` | `_ride_route_payloads` | `SELECT s.id, s.name, s.distanceM, MIN(x.secs) best, COUNT(x.secs) tries, MAX(x.d) last FROM Segment s LEFT …` | Home Assistant last-ride route and segments |
| `services/mqtt.py:570` | `_history_payloads` | `SELECT CAST(strftime('%m', startDateLocal) AS INTEGER) m, COUNT(*) n, SUM(distance) d, SUM(movingTime) t, S…` | Home Assistant ride totals and history sensors |
| `services/mqtt.py:591` | `_history_payloads` | `SELECT strftime('%Y', startDateLocal) y, COUNT(*) n, SUM(distance) d, SUM(movingTime) t, SUM(totalElevation…` | Home Assistant ride totals and history sensors |
| `services/mqtt.py:615` | `_history_payloads` | `SELECT date(startDateLocal, '-' \|\| ((CAST(strftime('%w', startDateLocal) AS INTEGER) + 6) % 7) \|\| ' day…` | Home Assistant ride totals and history sensors |
| `services/mqtt.py:786` | `_gather_stats` | `SELECT COUNT(*) as rides, SUM(distance) as dist, SUM(totalElevationGain) as elev, SUM(movingTime) as secs, …` | Home Assistant ride totals and history sensors |
| `services/mqtt.py:791` | `_gather_stats` | `SELECT name, sportType, startDateLocal, distance, movingTime, totalElevationGain, averageSpeed, averageHear…` | Home Assistant ride totals and history sensors |
| `services/mqtt.py:812` | `_gather_stats` | `SELECT COUNT(*) as rides, SUM(distance) as dist, SUM(totalElevationGain) as elev FROM Activity WHERE riderId=?` | Home Assistant ride totals and history sensors |
| `services/mqtt.py:941` | `push_update` | `SELECT COUNT(*) AS n, SUM(distance) AS d FROM Activity WHERE riderId=? AND strftime('%Y', startDateLocal)=?` | Home Assistant ride totals and history sensors |
| `services/sanity.py:74` | `scan_all` | `SELECT id FROM Activity WHERE flagDismissed IS NULL OR flagDismissed = 0` | sanity checks are tuned for rides |
| `services/sanity.py:89` | `flagged` | `SELECT id, name, startDateLocal, distance, averageSpeed, flagReason FROM Activity WHERE riderId=? AND flagR…` | sanity checks are tuned for rides |
| `services/storms.py:44` | `storm_rides` | `SELECT id, name, startDateLocal, distance, averageSpeed, weatherWindKph, weatherGustKph, weatherCode, weath…` | storm rides |
| `services/storms.py:81` | `claim_all` | `SELECT id FROM Activity WHERE riderId=? AND weatherGustKph IS NOT NULL` | storm rides |
| `services/storms.py:92` | `reassess` | `SELECT id, startLat, startLng, startDateLocal, streams, weatherGustKph FROM Activity WHERE riderId=? AND we…` | storm rides |
| `services/storms.py:107` | `violent_unnamed` | `SELECT id, name, startDateLocal, distance, weatherWindKph, weatherGustKph, weatherCode, weatherSource FROM …` | storm rides |
| `services/weather.py:304` | `backfill_missing` | `SELECT id, startLat, startLng, startDateLocal, streams FROM Activity WHERE weatherSummary IS NULL AND start…` | weather backfill and fog check (rides) |
| `services/weather.py:341` | `fog_candidates` | `SELECT id, name, startDateLocal, weatherHumidity, weatherWindKph, weatherTempC FROM Activity WHERE riderId=…` | weather backfill and fog check (rides) |

### Every sport: stays on `Activity` (8)

| Where | Function | Statement | Note |
|---|---|---|---|
| `routes/dashboard.py:158` | `dashboard` | `SELECT a.id, a.name, a.sportType, a.startDateLocal, a.distance, a.movingTime, a.totalElevationGain, a.avera…` | dashboard history: every activity (decided 2026-10-18), with sports to leave out. Delete the runs-only merge from Workout below it |
| `routes/dashboard.py:208` | `dashboard` | `SELECT DISTINCT sportType FROM Activity WHERE riderId=? AND sportType IS NOT NULL ORDER BY sportType` | sport list for the history filter: every sport present. Drop the Workout "Run" append |
| `routes/route_builder.py:75` | `index` | `SELECT AVG(startLat) as lat, AVG(startLng) as lng FROM Activity WHERE startLat IS NOT NULL AND startLng IS …` | route builder map centre: any activity's start is fine |
| `services/context.py:300` | `_build_other_training_context` | `SELECT name, sportType, startDateLocal, distance, movingTime, totalElevationGain FROM Activity WHERE riderI…` | AI "Other training": every non-ride. Today it misses the Workout table altogether, so the merge fixes it |
| `services/duplicates.py:149` | `find_duplicates` | `SELECT * FROM Activity WHERE riderId=? AND id<>? AND substr(startDateLocal,1,10) BETWEEN ? AND ?` | duplicate check: every sport, which is what fixes the Garmin run + Strava run pairs |
| `services/sport_fix.py:31` | `scan` | `SELECT id, name, startDateLocal, distance, sportType FROM Activity WHERE riderId=? AND id LIKE 'garmin\_%' …` | sport check: must see Garmin rows of every sport |
| `services/start_times.py:26` | `fix_utc_starts` | `SELECT a.id, a.startDateLocal FROM Activity a WHERE {…} AND a.riderId NOT IN (SELECT riderId FROM Friend WH…` | one-off start-time repairs: every activity |
| `services/start_times.py:61` | `recheck_away_starts` | `SELECT id, startDate, startDateLocal FROM Activity WHERE startDate IS NOT NULL AND riderId NOT IN (SELECT r…` | one-off start-time repairs: every activity |

### By id: stays on `Activity` (41)

| Where | Function | Statement | Note |
|---|---|---|---|
| `database.py:722` | `migrate_db` | `SELECT 1 FROM Activity LIMIT 1` | is the database empty |
| `routes/friends.py:467` | `_do_ride_sync` | `SELECT id, startDateLocal, streams FROM Activity WHERE id IN ({}) AND streams IS NOT NULL AND streams NOT I…` |  |
| `routes/gear.py:277` | `ride_bike` | `SELECT riderId FROM Activity WHERE id=?` |  |
| `routes/import_rides.py:302` | `_process_single_file` | `SELECT * FROM Activity WHERE id=?` | import: the id just imported |
| `routes/import_rides.py:323` | `_process_single_file` | `SELECT * FROM Activity WHERE id=?` | import: the id just imported |
| `routes/import_rides.py:378` | `_process_strava_export` | `SELECT id FROM Activity WHERE id = ?` | import: the id just imported |
| `routes/import_rides.py:535` | `_offer_change` | `SELECT * FROM Activity WHERE id=?` | import: the id just imported |
| `routes/rides.py:272` | `scan_segments` | `SELECT id, startDateLocal, streams, sportType FROM Activity WHERE id=?` | segment scan: falls back to Workout, but the row has the sport either way |
| `routes/rides.py:296` | `set_weather` | `SELECT 1 FROM Activity WHERE id=?` | by id on the ride page |
| `routes/rides.py:300` | `set_weather` | `SELECT startLat, startLng, startDateLocal, streams FROM Activity WHERE id=?` | by id on the ride page |
| `routes/rides.py:310` | `set_weather` | `SELECT startLat, startLng, startDateLocal, streams FROM Activity WHERE id=?` | by id on the ride page |
| `routes/rides.py:315` | `set_weather` | `SELECT weatherTempC FROM Activity WHERE id=?` | by id on the ride page |
| `routes/rides.py:320` | `set_weather` | `SELECT weatherCode, weatherSummary, weatherSource FROM Activity WHERE id=?` | by id on the ride page |
| `routes/rides.py:329` | `dismiss_flag` | `SELECT 1 FROM Activity WHERE id=?` | by id on the ride page |
| `routes/rides.py:400` | `export_gpx` | `SELECT * FROM Activity WHERE id=?` | by id on the ride page |
| `routes/rides.py:490` | `bulk_download` | `SELECT * FROM Activity WHERE id=?` | by id on the ride page |
| `routes/rides.py:614` | `view_duplicate` | `SELECT * FROM Activity WHERE id=?` | by id on the ride page |
| `routes/segments.py:191` | `detail` | `SELECT streams FROM Activity WHERE id=?` | segment source track (falls back to Workout) |
| `services/backup.py:106` | `<module>` | `SELECT id, riderId, startDateLocal, distance, streams FROM Activity LIMIT 1` | backup check: the table exists and has columns |
| `services/bulk.py:54` | `apply` | `SELECT sportType FROM Activity WHERE id=?` |  |
| `services/duplicates.py:167` | `rebuild_derived` | `SELECT * FROM Activity WHERE id=?` |  |
| `services/duplicates.py:183` | `park` | `SELECT * FROM Activity WHERE id=?` |  |
| `services/duplicates.py:187` | `park` | `SELECT * FROM Activity WHERE id=?` |  |
| `services/duplicates.py:207` | `resolve` | `SELECT * FROM Activity WHERE id=?` |  |
| `services/duplicates.py:222` | `resolve` | `SELECT * FROM Activity WHERE id=?` |  |
| `services/duplicates.py:232` | `exists_anywhere` | `SELECT 1 FROM Activity WHERE id=? UNION SELECT 1 FROM ActivityDuplicate WHERE id=? AND status<>'deleted'` |  |
| `services/duplicates.py:250` | `delete_activity` | `SELECT id, riderId FROM Activity WHERE id=?` |  |
| `services/duplicates.py:294` | `swap` | `SELECT 1 FROM Activity WHERE id=?` |  |
| `services/gear.py:198` | `set_ride_bike` | `SELECT id, riderId, sportType FROM Activity WHERE id=?` | gear: checks the sport itself |
| `services/gear.py:211` | `stamp_new_ride` | `SELECT id, riderId, sportType, bikeId FROM Activity WHERE id=?` | gear: checks the sport itself |
| `services/gear.py:290` | `on_ride_added` | `SELECT bikeId, riderId FROM Activity WHERE id=?` | gear: checks the sport itself |
| `services/reimport.py:102` | `resolve` | `SELECT * FROM Activity WHERE id=?` |  |
| `services/sanity.py:63` | `flag` | `SELECT id, sportType, distance, movingTime, elapsedTime, averageSpeed, maxSpeed, totalElevationGain, calori…` |  |
| `services/segments.py:37` | `_activity_family` | `SELECT sportType FROM Activity WHERE id=?` |  |
| `services/segments.py:142` | `recover_polyline` | `SELECT streams FROM Activity WHERE id=?` |  |
| `services/segments.py:450` | `scan_new_ride` | `SELECT id, startDateLocal, streams, sportType FROM Activity WHERE id=?` |  |
| `services/start_times.py:41` | `fix_utc_starts` | `SELECT 1 FROM Activity WHERE id=?` |  |
| `services/start_times.py:66` | `recheck_away_starts` | `SELECT 1 FROM Activity WHERE id=?` |  |
| `services/storms.py:68` | `claim` | `SELECT startDateLocal, weatherGustKph, weatherSource FROM Activity WHERE id=?` |  |
| `services/weather.py:244` | `save_weather` | `SELECT weatherSource, weatherCode, weatherSummary FROM Activity WHERE id=?` |  |
| `services/weather.py:283` | `set_condition` | `SELECT id, weatherSummary, weatherCode, weatherSource FROM Activity WHERE id=?` |  |

### Through a ride-only table: stays on `Activity` (13)

| Where | Function | Statement | Note |
|---|---|---|---|
| `routes/api_v1.py:150` | `perform` | `SELECT e.elapsedSecs, e.avgSpeedMps, e.activityId, e.activityDate, a.name as rideName FROM BestEffort e JOI…` | BestEffort holds rides only (as long as `services/best_efforts.py:104` reads Ride) |
| `routes/data.py:158` | `index` | `SELECT e.distanceMi, e.activityDate, e.elapsedSecs, e.avgSpeedMps, e.activityId, a.name as rideName FROM Be…` | BestEffort |
| `routes/gear.py:127` | `bike` | `SELECT id, name, startDateLocal, distance, movingTime, totalElevationGain FROM Activity WHERE bikeId=? ORDE…` | by bikeId: only rides have a bike |
| `routes/riders.py:422` | `detail` | `SELECT e.distanceMi, e.elapsedSecs, e.avgSpeedMps, e.activityDate, a.name AS rideName, e.activityId FROM Be…` | BestEffort |
| `routes/rides.py:157` | `detail` | `SELECT e.segmentId, e.elapsedSecs, e.avgSpeedMps, e.isPR, r.name AS rider_name, r.avatarPath AS rider_avata…` | segment efforts on the ride page, already limited to that ride's segments |
| `routes/rides.py:173` | `detail` | `SELECT e2.elapsedSecs FROM SegmentEffort e2 JOIN Activity a2 ON a2.id = e2.activityId WHERE e2.segmentId=? …` | segment efforts on the ride page, already limited to that ride's segments |
| `routes/rides.py:187` | `detail` | `SELECT e2.elapsedSecs FROM SegmentEffort e2 JOIN Activity a2 ON a2.id = e2.activityId WHERE e2.segmentId=? …` | segment efforts on the ride page, already limited to that ride's segments |
| `services/context.py:390` | `_build_comeback_progress` | `SELECT strftime('%Y-%m', rideDate) as ym, COUNT(*) as rides, AVG(distanceMi) as avg_dist, AVG(avgSpeedMph) …` | RideMemory (rides only) |
| `services/context.py:457` | `build_context` | `SELECT * FROM RideMemory WHERE rideId != ? AND rideId IN (SELECT id FROM Activity WHERE riderId IS ?) AND d…` | RideMemory (rides only) |
| `services/context.py:466` | `build_context` | `SELECT * FROM RideMemory WHERE rideId != ? AND rideId IN (SELECT id FROM Activity WHERE riderId IS ?) AND d…` | RideMemory (rides only) |
| `services/gear.py:168` | `distance_on` | `SELECT COALESCE(SUM(distance),0) FROM Activity WHERE bikeId=?` | by bikeId |
| `services/gear.py:181` | `bike_stats` | `SELECT COUNT(*) n, COALESCE(SUM(distance),0) dist, COALESCE(SUM(movingTime),0) moving, COALESCE(SUM(totalEl…` | by bikeId |
| `services/gear.py:184` | `bike_stats` | `SELECT substr(startDateLocal,1,4) y, COUNT(*) n, SUM(distance) d, SUM(totalElevationGain) g FROM Activity W…` | by bikeId |

### Write: stays on `Activity` (45)

| Where | Function | Statement | Note |
|---|---|---|---|
| `app.py:176` | `_garmin_heartbeat` | `UPDATE Activity SET averageHeartrate=?, maxHeartrate=?, streams=? WHERE id=?` |  |
| `database.py:245` | `migrate_db` | `UPDATE Activity SET riderId=? WHERE riderId IS NULL` |  |
| `database.py:701` | `migrate_db` | `UPDATE Activity SET distance = distance / 1000 WHERE distance > 500000 AND (lower(sportType) LIKE '%walk%' …` |  |
| `routes/ai_page.py:167` | `generate` | `UPDATE Activity SET aiKudos=?, aiKudosAt=datetime('now') WHERE id=?` |  |
| `routes/friends.py:260` | `delete` | `DELETE FROM SegmentEffort WHERE activityId IN (SELECT id FROM Activity WHERE riderId=?)` | removing a friend removes everything of theirs: all sports |
| `routes/friends.py:262` | `delete` | `DELETE FROM BestEffort WHERE activityId IN (SELECT id FROM Activity WHERE riderId=?)` | removing a friend removes everything of theirs: all sports |
| `routes/friends.py:263` | `delete` | `DELETE FROM RideMemory WHERE rideId IN (SELECT id FROM Activity WHERE riderId=?)` | removing a friend removes everything of theirs: all sports |
| `routes/friends.py:264` | `delete` | `DELETE FROM Activity WHERE riderId=?` | removing a friend removes everything of theirs: all sports |
| `routes/friends.py:404` | `_do_ride_sync` | `INSERT INTO Activity ( id, name, type, sportType, startDate, startDateLocal, distance, movingTime, elapsedT…` |  |
| `routes/import_rides.py:563` | `_insert` | `INSERT OR IGNORE INTO Activity (id, name, type, sportType, startDate, startDateLocal, distance, movingTime,…` |  |
| `routes/kudos.py:54` | `kudos` | `UPDATE Activity SET aiKudos=?, aiKudosAt=datetime('now') WHERE id=?` |  |
| `routes/riders.py:540` | `delete` | `SELECT DISTINCT e.segmentId FROM SegmentEffort e JOIN Activity a ON a.id=e.activityId WHERE a.riderId=?` | deleting a rider: all sports. Today it never touches Workout, so a deleted rider's workouts are left behind; after the merge they go too |
| `routes/riders.py:541` | `delete` | `DELETE FROM SegmentEffort WHERE activityId IN (SELECT id FROM Activity WHERE riderId=?)` | deleting a rider: all sports. Today it never touches Workout, so a deleted rider's workouts are left behind; after the merge they go too |
| `routes/riders.py:542` | `delete` | `DELETE FROM BestEffort WHERE activityId IN (SELECT id FROM Activity WHERE riderId=?)` | deleting a rider: all sports. Today it never touches Workout, so a deleted rider's workouts are left behind; after the merge they go too |
| `routes/riders.py:544` | `delete` | `DELETE FROM RideMemory WHERE rideId IN (SELECT id FROM Activity WHERE riderId=?)` | deleting a rider: all sports. Today it never touches Workout, so a deleted rider's workouts are left behind; after the merge they go too |
| `routes/riders.py:546` | `delete` | `DELETE FROM Activity WHERE riderId=?` | deleting a rider: all sports. Today it never touches Workout, so a deleted rider's workouts are left behind; after the merge they go too |
| `routes/rides.py:316` | `set_weather` | `UPDATE Activity SET weatherCode=NULL, weatherSummary=NULL WHERE id=?` |  |
| `routes/rides.py:340` | `save_notes` | `UPDATE Activity SET notes=? WHERE id=?` |  |
| `routes/sync.py:76` | `sync` | `UPDATE Activity SET averageHeartrate=?, maxHeartrate=?, streams=? WHERE id=?` |  |
| `services/bulk.py:81` | `_move_to_rider` | `UPDATE Activity SET riderId=?, bikeId=NULL WHERE id=?` | bulk "move to rider": all sports. (Its `UPDATE Workout` must go) |
| `services/calorie_adjust.py:58` | `reapply_all` | `UPDATE Activity SET caloriesRaw=calories WHERE caloriesRaw IS NULL AND calories IS NOT NULL AND id NOT LIKE…` | burn adjustment: all sports. (Its two `UPDATE Workout` must go, or every workout is adjusted twice) |
| `services/calorie_adjust.py:62` | `reapply_all` | `UPDATE Activity SET calories=ROUND(caloriesRaw*?,1) WHERE caloriesRaw IS NOT NULL` | burn adjustment: all sports. (Its two `UPDATE Workout` must go, or every workout is adjusted twice) |
| `services/convert.py:69` | `_workout_to_ride` | `INSERT OR REPLACE INTO Activity (id, name, type, sportType, startDate, startDateLocal, distance, movingTime…` |  |
| `services/convert.py:94` | `change_sport` | `UPDATE Activity SET sportType=?, type=? WHERE id=?` |  |
| `services/duplicates.py:191` | `park` | `UPDATE Activity SET {…}=? WHERE id=?` |  |
| `services/duplicates.py:195` | `park` | `DELETE FROM Activity WHERE id=?` |  |
| `services/duplicates.py:254` | `delete_activity` | `DELETE FROM Activity WHERE id=?` |  |
| `services/duplicates.py:270` | `_insert_row` | `INSERT OR REPLACE INTO Activity ({…}) VALUES ({…})` |  |
| `services/garmin.py:761` | `sync_garmin_activities` | `INSERT INTO Activity ( id, name, type, sportType, startDate, startDateLocal, distance, movingTime, elapsedT…` |  |
| `services/gear.py:158` | `delete_bike` | `UPDATE Activity SET bikeId=NULL WHERE bikeId=?` |  |
| `services/gear.py:205` | `set_ride_bike` | `UPDATE Activity SET bikeId=? WHERE id=?` |  |
| `services/gear.py:216` | `stamp_new_ride` | `UPDATE Activity SET bikeId=? WHERE id=?` |  |
| `services/gear.py:252` | `assign_rides` | `UPDATE Activity SET bikeId=? WHERE id IN (SELECT a.id {…}{…}{…})` |  |
| `services/manual_activity.py:89` | `create` | `INSERT INTO Activity (id, name, type, sportType, startDate, startDateLocal, distance, movingTime, elapsedTi…` |  |
| `services/max_stats.py:47` | `backfill` | `UPDATE Activity SET {…} WHERE id=?` |  |
| `services/max_stats.py:65` | `fix_spiky_max_speed` | `UPDATE Activity SET maxSpeed=? WHERE id=?` |  |
| `services/reimport.py:127` | `resolve` | `UPDATE Activity SET {…}, updatedAt=datetime('now') WHERE id=?` |  |
| `services/sanity.py:67` | `flag` | `UPDATE Activity SET flagReason=? WHERE id=?` |  |
| `services/sanity.py:83` | `dismiss` | `UPDATE Activity SET flagDismissed=1, flagReason=NULL WHERE id=?` |  |
| `services/start_times.py:36` | `fix_utc_starts` | `UPDATE Activity SET startDate=?, startDateLocal=? WHERE id=?` |  |
| `services/weather.py:249` | `save_weather` | `UPDATE Activity SET weatherTempC=?, weatherWindKph=?, weatherGustKph=?, weatherWindDir=?, weatherHumidity=?…` |  |
| `services/weather.py:287` | `set_condition` | `UPDATE Activity SET weatherSource='manual' WHERE id=? AND weatherCode IS NOT NULL` |  |
| `services/weather.py:291` | `set_condition` | `UPDATE Activity SET weatherCode=?, weatherSummary=?, weatherSource=? WHERE id=?` |  |
| `services/weather.py:293` | `set_condition` | `UPDATE Activity SET weatherSource=NULL WHERE id=?` |  |
| `services/weather.py:325` | `backfill_missing` | `UPDATE Activity SET startLat=?, startLng=? WHERE id=? AND startLat IS NULL` |  |

### Scripts, demo, docstrings (34)

`backfill_weather.py` (1), `demo/build_demo_db.py` (6), `export_demo_rides.py` (1), `scripts/resolve_existing_duplicates.py` (3), `scripts/smoke_api_v1.py` (2), `scripts/smoke_duplicates_manual.py` (5), `scripts/smoke_gear.py` (11), `scripts/smoke_ride_upload.py` (3), `services/ingest.py` (1), `services/workouts.py` (1).

## Not found by the search

These name the table through a variable, so the search couldn't see them. All of them choose between `Activity` and `Workout` by `kind`:
- `routes/api_v1.py:532` (`change_sport` route): reads `riderId` from the table for `kind`.
- `services/bulk.py:61` (`apply`, rename): `UPDATE` on the table for `kind`.
- `services/sensors.py:187` (`_candidates`) and `:225`: read both tables to match a phone sensor recording to an activity. Once merged, every workout is a candidate twice; read `Activity` once.
- `services/sensors.py:248`: reads `startDate` from the table for `rideKind`.

## Writes to `Workout`

A view can't be written to, so each of these moves to `Activity` in release 1. There are more than the 5 the TODO entry first named: 12 statements in 8 files, plus `services/bulk.py:61` above.
- `services/workouts.py:73` (`save_from_gpx`, insert) and `:179` (`delete`)
- `services/garmin.py:609` (`_save_workout`)
- `services/manual_activity.py:76` (`create`)
- `services/convert.py:46`, `:104`, `:111` (`_ride_to_workout`, `change_sport`)
- `services/bulk.py:79` (`_move_to_rider`)
- `services/calorie_adjust.py:59`, `:63` (`reapply_all`). These must be removed, not moved: the `Activity` updates beside them would already cover workouts, so moving them adjusts every workout twice.
- `services/origin.py:53` (`backfill`)
- `demo/build_demo_db.py:311`

