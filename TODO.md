# TODO

Project-wide list of planned work. Tick items off as they land and note the version in CHANGELOG.md.

## Privacy

- [ ] **Privacy zones** — cut GPS points within X metres of home or work before they leave the instance. Apply to:
  - [ ] the friend feed (`routes/friends.py` `/api/feed`)
  - [ ] the route published to Home Assistant (MQTT attribute sensors)
  - [ ] heatmap exports
- [ ] **One token per friend** instead of the single shared feed token, so one person can be revoked on their own and each friend can be given a chosen subset: rides, segments, foods, or a date window.

## Users

- [ ] **Proper multi-user support, with roles.** Today there is one login (`services/credentials.py` `admin_login`: a single username and password from the environment or `.admin_login`), and the session is just `logged_in`. Other riders (`Rider` rows) are profiles that whoever is logged in can see and edit, and many routes assume the owner: about 26 queries pick `Rider WHERE isDefault=1`, including the phone API's `_rider()` (`routes/api_v1.py`), so every paired phone records as the owner.
  - [ ] A `User` table: username, password hash, role, the rider it belongs to, disabled flag. Move the existing admin login into it on upgrade, keeping the environment override for recovery. Sessions carry the user's ID, and changing a user's password or role ends that user's sessions (as `auth_version` does today).
  - [ ] Two roles. **Admin**: every rider, all Settings (Garmin, Home Assistant, MQTT, AI keys, backups, units default), users and invites, friends. **Standard user**: their own rider's rides, workouts, nutrition, gear, goals and their own preferences (units, AI personality), with no instance settings and no other riders' data unless an admin shares it.
  - [ ] Scope every page and API by the logged-in user's rider instead of `isDefault`, and check ownership on every write (ride delete, bulk edits, gear, nutrition entries). A test should log in as a standard user and get a 403 or 404 on another rider's ride, workout and nutrition URLs.
  - [ ] Phone pairing per user: `DeviceToken` gets a `userId`, so a paired phone records as its owner, not the instance owner.
  - [ ] Per-user connections where it makes sense: Garmin and Home Assistant are set once per instance now; each user needs their own Garmin account, or this stays admin-only, decided per feature.
  - [ ] Admin page: invite a user (one-time link), reset a password, change a role, disable a user. Keep at least one admin at all times.
- [ ] **Choose which riders' data friends can see.** The friend feed shares every local rider: `OWN_RIDERS_SQL` in `routes/friends.py` only leaves out riders synced from friends, so `/api/riders` lists, and `/api/feed` serves, every person on this instance to anyone with the feed token.
  - [ ] A per-rider "share with friends" choice, off by default for new riders. A standard user decides for their own rider, and an admin can't switch it on for someone else.
  - [ ] When a friend is linked (and when a new rider is added), show which riders will be visible and ask for confirmation before anything is served.
  - [ ] Combine this with **One token per friend** (Privacy, above), so the choice can be per friend: rider X to friend A only.
  - [ ] Tests: a rider who isn't shared is missing from `/api/riders`, and `/api/feed?rider=<name>` returns nothing for them.

## Security

From the project-wide security review, 2026-10-17.

- [x] **Friends can pull other friends' rides** (medium). Fixed in 0.5.4-beta: `OWN_RIDERS_SQL` filter in `routes/friends.py`, covered by `tests/test_friend_feed.py`. `/api/feed?rider=<name>` (`routes/friends.py` `feed`) looks the name up in every `Rider` row, and `/api/riders` lists them all, including the riders created for synced friends. So anyone with our feed token can download, with full GPS and HR streams, the rides a third friend shared only with us. In both endpoints, leave out riders that belong to a friend (`id NOT IN (SELECT riderId FROM Friend WHERE riderId IS NOT NULL)`). The segment query in the same feed already filters on `friendId IS NULL`.
- [x] **Constant-time feed token check** (low). Fixed in 0.5.4-beta: all four feed endpoints use `_feed_token_ok()`. `feed` and `riders_list` compare the token with `!=`; use `_feed_token_ok()` (which uses `hmac.compare_digest`) in all three feed endpoints.
- [x] **Feed token in the query string** (low). Fixed in 0.5.4-beta: header only. The feed endpoints also accept `?token=`, which puts the token in proxy access logs. Friend instances already send the `X-Feed-Token` header, so drop the query-string option.
- [x] **Login lockout bypass without a reverse proxy** (low). Fixed in 0.5.4-beta: `services/trusted_proxy.py` honours forwarded headers only from loopback/private addresses or `TRUSTED_PROXIES`. `ProxyFix(x_for=1)` in `app.py` trusts `X-Forwarded-For` unconditionally, so on a directly exposed port each sign-in attempt can claim a new address and dodge the 8-per-5-minutes lockout. Make proxy trust opt-in (e.g. a `TRUSTED_PROXY` env setting), or key the lockout on the real socket address when no proxy is configured.
- [ ] **iOS: confirm the server before pairing from a link** (low). A `headwind://pair` link opened from outside the app pairs straight away when the app is unpaired (`ios/Headwind/Pairing/PairingView.swift`), and the "Pair with a different server?" alert (`ios/Headwind/App/HeadwindApp.swift`) names only the current server. Always show the new server's host before pairing, and tie each pending ride to the server it was recorded under, so `Session.unpair()` doesn't let old rides upload to a new server.

## Bugs

- [x] **MQTT heartbeat thread can die** — fixed in 0.5.4-beta: module-level `log` in `app.py`. (`app.py` `_mqtt_heartbeat`). Its gear-alert `except` handler calls `log.warning`, but `log` isn't defined there or at module level. If `gear.evaluate_alerts` raises, the resulting `NameError` kills the thread, which stops MQTT pushes, Home Assistant and weather sync, and goal auto-update until a restart. Add `log = logging.getLogger(__name__)` at module level.
- [x] **Old APK path default** — fixed in 0.5.4-beta: `headwind.apk` beside the database, or `HEADWIND_APK`. `routes/phones.py` defaults `APK_PATH` to `/home/rob/headwind-android/dist/headwind.apk`. Replace it with a path under the data directory, or require `HEADWIND_APK`.
- [x] **Units ignore the metric setting** — fixed in 0.5.9-beta. Every distance, climb, speed and pace now goes through `services/units.py`: the template filters in `app.py`, `window.UNITS` in `base.html` for page scripts, and the search forms' distance filters (`min_dist` / `max_dist`, old `min_mi` links still work). That covers the dashboard, ride, segment, rider, Data, AI, planner, Workouts and roughness pages, the "looks wrong" reasons (re-worded when the setting changes), gear alerts, workout notifications and badge wording. The AI coach is given the ride and its history in the rider's units. `tests/test_units.py` renders the main pages in metric and fails on any mile, mph or foot a reader would see.
  - [ ] **Home Assistant sensors** are still published in miles, mph and feet (`services/mqtt.py`, `services/live.py`). Changing a sensor's unit breaks its long-term statistics in HA, so it needs a plan: new sensor IDs, or a one-off migration. (HA can already show a sensor in other units from its own settings.)
  - [ ] **Best efforts and badges are defined in miles.** Best efforts are timed over 1, 5, 10 mi and so on, and shown converted ("16.1 km"). Badge limits are miles and mph and only their wording is converted ("25 miles" becomes "40 km"). Metric riders would want 5 / 10 / 20 / 40 / 100 km efforts and round-kilometre badges, which means recomputing the stored efforts.
  - [ ] **Weather is always metric** (°C, km/h wind and gusts), so an imperial rider sees km/h wind next to mph speeds. Follow the setting there too, or add a separate choice for temperature.
  - [ ] `RideMemory` stores miles, mph and feet. It's only read through the converters now, but storing metres and m/s like everything else would remove the special case.

- [x] **Long-term stats after a delete** — investigated in 0.5.8-beta: the web pages were already right, but Home Assistant wasn't. The dashboard's Performance chart looked the same after the 1000x-too-long Strava rides from 0.5.7-beta were deleted. Every web page and phone endpoint works its numbers out from `Activity` on each load, and a test that deletes rides and re-reads the dashboard, Data page, rider page, heatmap, `/api/v1/overview`, `/perform` and `/rides` saw every one change at once (`tests/test_dashboard_links.py`). The chart only covers the last 12 weeks, and the speed line only this year, so deleting older rides doesn't move it.
  - [x] The web delete (`delete` in `routes/rides.py`) didn't re-publish the Home Assistant sensors, so their totals stayed wrong until the next ride. It now calls `after_ride_removed` in `services/ingest.py`. Deleting a rider or friend doesn't need it: the sensors only cover the owner, who can't be deleted.
  - [ ] If it happens again, note which rides, where they were deleted from (web or phone) and which page still showed them. The browser's back button can show a page from before the delete.

### iOS and watchOS app

From two code reviews of `ios/`, 2026-10-17. Most severe first. The iOS code lives on the `ios-app` branch until it's merged.

- [x] **Returning to Record mid-ride turns off background location** (`ios/Headwind/Record/RecordView.swift` `onAppear`). Fixed on `ios-app` (`eee4dc0`): `warmUp()` does nothing unless the recorder is idle. `onAppear` always calls `recorder.warmUp()`, which runs `feed.start(background: false)` and sets `allowsBackgroundLocationUpdates = false` even while recording. Start a ride, switch to Today, come back to Record, lock the phone: GPS stops and the rest of the ride is lost. Skip the warm-up (or keep background on) while a ride is recording.
- [x] **A failed save loses the ride** (`ios/Headwind/Record/RecordView.swift` `save()`). Fixed on `ios-app` (`eee4dc0`): `finish(into:)` / `saveRecovered(into:)` end recording and clear the journal only after `RideStore.add` succeeds. `recorder.finish()` / `takeRecovered()` clear the crash journal and end recording before `RideStore.add` writes the GPX. If that write throws `.storage` (disk full, unwritable Recordings dir), the alert shows but the GPX exists only in memory and is dropped. Write the GPX first and clear the journal only once it's on disk.
- [x] **Losing the pairing mid-ride hides the Record controls** (`ios/Headwind/App/HeadwindApp.swift` `RootView`). Fixed on `ios-app` (`eee4dc0`): `RootView` keeps `RecordView` up while recording, and `/live` posts bypass `Session.call`, so a 401 doesn't unpair. `RootView` swaps `MainTabs` for `PairingView` whenever `pairing` is nil. A 401 from the best-effort `/live` post (`Session.call` calls `unpair()`), or accepting "Pair with a different server", leaves GPS recording in the background with no Pause or Finish button. Keep the Record screen reachable while a ride is in progress, and don't unpair on a 401 from `/live`.
- [x] **Starting a ride wipes an unsaved recovered ride** (`ios/Headwind/Record/PhoneRideRecorder.swift` `start()`; same in `ios/HeadwindWatch/WorkoutManager.swift` `start`). Fixed on `ios-app` (`eee4dc0`): the phone saves, and the Watch sends, a waiting recovered ride first and won't start if that fails; the Watch also keeps its journal when it can't queue a ride. `journal.begin()` deletes the journal that still holds the recovered ride shown in the "Unfinished ride" banner. If the app is then killed during the new ride, the earlier one is gone for good. Require Save or Discard first, or move the old journal aside.
- [x] **Watch rides can vanish in transfer** (`ios/Headwind/Record/WatchBridge.swift` `didReceive file`). Fixed on `ios-app` (`eee4dc0`): received rides are held in Application Support (`WatchInbox`) until the RideStore takes them, retried on launch, and a failed hold sets `lastError`. If moving the file fails or the metadata doesn't parse, the method returns silently. The transfer still counts as successful, so the Watch deletes its outbox copy and neither device keeps the ride, with no `lastError`. If `adopt()` later fails the file is also left in `temporaryDirectory`, which the system can purge. Copy into Application Support synchronously, surface the error, and keep the file on failure.
- [x] **Watch stuck on "Saving ride…" / GPS left on** (`ios/HeadwindWatch/WorkoutManager.swift`). Fixed on ios-app: a failed session is ended and the ride finished; `finishWorkout` stops GPS and the clock itself and runs once per session. Finishing depends entirely on the HK session reaching `.ended`. `didFailWithError` only sets the error, so a failed session (e.g. another workout app takes over) leaves `end()` in `.saving` for ever. If the system ends the session itself while recording, `finishWorkout` runs without `location.stopUpdatingLocation()`. Finish (and stop location) on failure as well as on `.ended`.
- [ ] **"Pair with a different server" unpairs before checking the new link** (`ios/Headwind/App/HeadwindApp.swift`). The button calls `session.unpair()` before the link is validated, contradicting `Session.pair`'s "only then stores it". A stale or mistyped link deletes the working pairing from the Keychain and then fails. Validate the new server first and only then replace the pairing. (Related to the Security item above about confirming the server before pairing.)
- [x] **Orphaned HKWorkoutSession if `beginCollection` throws** (`ios/HeadwindWatch/WorkoutManager.swift` `start`). Fixed on ios-app: the catch ends the session; callbacks from a stale session are ignored. The catch calls `reset()`, which drops the session reference without `session.end()` after `startActivity` has already run. The workout indicator stays on, the app keeps running in the background, and the next Start can fail. End the session in the catch path.
- [x] **Watch context sent before WCSession activation is dropped** (`ios/Headwind/Record/WatchBridge.swift` `updateWatch`). Fixed on `ios-app` (`7a0d8b2`): the latest context is kept and sent from `activationDidCompleteWith` and `sessionWatchStateDidChange`. `updateWatch` returns early unless the session is activated, and `activationDidCompleteWith` is empty. The units/paired context sent at launch is lost, and if `refreshInfo` returns an unchanged `PingInfo` it's never re-sent, so the Watch shows metric units and `phonePaired = true` regardless. Remember the latest context and send it from `activationDidCompleteWith`.
- [x] **Rides added during an upload wait for the next foreground** (`ios/Headwind/Record/RideStore.swift` `uploadPending`). Fixed on `ios-app` (`7a0d8b2`): a call made mid-upload sets `uploadAgain`, and the running pass loops until no untried pending rides are left. A call made while `uploading` is true returns immediately, and the running loop works from a snapshot. A Watch ride arriving mid-upload stays "Waiting to upload" until the app is next opened, despite the comment promising a retry when another ride finishes. Set a "run again" flag and loop until no new pending rides appear.
- [x] **Background upload task has no expiration handler** (`ios/Headwind/Record/RideStore.swift` `uploadPending`). Fixed on `ios-app` (`7a0d8b2`): the handler cancels the upload, puts the ride in flight back to pending and ends the task. `beginBackgroundTask` is called without one. Several rides at up to 120 s each can outlast the background time, and iOS kills the app when a task expires without being ended. Add a handler that cancels the loop and ends the task.
- [x] **Watch retries failed transfers in a tight loop** (`ios/HeadwindWatch/PhoneLink.swift` `didFinish`). Fixed on `ios-app` (`7a0d8b2`): retries back off from 15 s to 30 min; permanent `WCError`s stop retrying and show on the summary, with the ride kept in the outbox and resent on the next launch. Every failed transfer goes straight back to `transferFile` with no backoff and no check for permanent errors (e.g. the iPhone app isn't installed). It drains the battery and leaves "Sending to iPhone…" up for good. Back off, and stop on non-transient errors.
- [ ] **Recovered rides skip the two-point check** (`ios/Headwind/Record/PhoneRideRecorder.swift` `takeRecovered`; `ios/HeadwindWatch/WorkoutManager.swift` `saveRecovered`). Unlike `finish()` / `finishWorkout()`, they don't require `tracker.pointCount >= 2`. A one-point GPX gets stored, the server returns 422 "Could not parse activity", and it's retried on every foreground. Apply the same check (and treat 422 as permanent).
- [ ] **Finishing a ride stops the map on the Record screen** (`ios/Headwind/Record/PhoneRideRecorder.swift` `endRecording()`). It always calls `feed.stop()`, so after Finish or Discard on the still-visible Record tab, the map stops following and after 10 s the label says "Waiting for GPS…" until the tab is left and reopened. Drop back to the foreground warm-up feed instead of stopping it.
- [ ] **Watch says "Sent to iPhone" when nothing was sent** (`ios/HeadwindWatch/HeadwindWatchApp.swift` summary). The green check shows whenever `waitingToSend == 0`, including when the ride was too short to send or `phone.send` threw `.storage`. Track whether a send actually happened.
- [ ] **Today shows yesterday's date west of UTC** (`ios/Headwind/Today/TodayView.swift`). The server's local date string is parsed as UTC midnight, then checked with `isDateInToday` in local time. In New York, `2026-10-17` becomes the evening of 16 October and the title reads "Friday 16 October" instead of "Today". Parse it with the local calendar/time zone (or compare date strings).

## iOS and watchOS app

- [ ] **Upload rides straight from the Watch** over cellular or Wi-Fi when the iPhone isn't around. Recording and saving to Apple Health already work without the phone, but the ride only reaches Headwind through the phone: `PhoneLink` queues it with `WCSession.transferFile`, and the phone uploads it when the two are next in range. Fix the two Watch-link bugs above first (the retry loop with no backoff in `PhoneLink`, and the context `WatchBridge` drops before activation), since this builds on the same path.
  - [ ] **Credentials on the Watch:** the phone sends the server URL and a token over WatchConnectivity, and the Watch keeps them in its Keychain. Give the Watch its own pairing, created from the phone, rather than a copy of the phone's token, so it can be revoked on its own from the server's Phones page.
  - [ ] **Direct upload:** after a ride, `POST /api/v1/rides` from a background `URLSession` (watchOS runs it over cellular or known Wi-Fi), still queuing the `transferFile` as the fallback.
  - [ ] **No double upload:** the server already ignores duplicates, so a ride arriving both ways is harmless, but cancel the queued transfer once the direct upload succeeds so the phone doesn't upload it again.
  - [ ] **Battery:** back off between retries, because cellular on the Watch is expensive.

- [ ] **Apple Health as a steps source** — read the day's step count from HealthKit on the iPhone and send it to the server, so riders without a Garmin still get steps on Today, MQTT and the step goal. The Watch app already writes workouts to Apple Health (`ios/HeadwindWatch/WorkoutManager.swift`, on `ios-app`), but nothing reads steps back.
  - [ ] Ask for HealthKit read access to `stepCount` and sum the day with an `HKStatisticsQuery` (`.cumulativeSum`), which de-duplicates iPhone and Watch samples.
  - [ ] Post it as a `BodyMetric` (e.g. `steps_health`) and add that to `STEP_METRICS` in `services/mqtt.py`, so `_best_steps_for` takes the highest of Garmin, phone, Watch, manual and Apple Health.
  - [ ] Keep it fresh with an `HKObserverQuery` and background delivery, plus a send on foreground, and backfill the last few days on first connect.

## AI

- [ ] **Claude as an AI source** — add `claude` to `aiProvider` alongside `openai` and `ollama` (Settings page in `routes/settings.py`, key and model columns on `Settings`).
  - [ ] `services/ai.py` `_get_client_and_model` returns an OpenAI client for every provider, and callers (`services/food_vision.py` included) use `client.chat.completions.create`. Either use Anthropic's OpenAI-compatible endpoint, or wrap the Anthropic SDK behind one small `chat()` helper that all callers go through.
  - [ ] Check the food-screenshot and recipe readers still work, since they send images.
  - [ ] Store the API key with the others, and update the "add an OpenAI key in Settings" errors to name whichever provider is missing.

## Dashboard and activity lists

- [x] **Clickable dashboard** — done in 0.5.8-beta, apart from the other lists. Most of the home page is read-only: the stat tiles, the fun stats, the Performance chart, the recovery numbers and the weather. Make nearly everything a way into the data behind it.
  - [x] Performance chart: clicking a weekly bar (distance, elevation, calories) opens the activity list for that week, `/dashboard?from=<Monday>&to=<Sunday>`, which the search form already supports. A point on the speed line opens that ride, so `year_speed` in `routes/dashboard.py` needs to send each ride's ID. Use Chart.js `onClick`, with a pointer cursor on hover.
  - [x] Lifetime tiles (Activities, Total Distance, Total Elevation, Total Time) and the fun stats go to the full history (`#ride-history`), or to the Data page section that breaks them down.
  - [x] Recovery Today values open `/recovery`. The weather chip opens the weather analysis on the Data page.
  - [x] Year, month and day headings in the Activities history open the list filtered to that period.
  - [x] Turn the `onclick="location.href=..."` rows on the dashboard into real `<a>` links, so middle-click, open in new tab and keyboard focus work.
  - [ ] The same for the lists that copy the pattern: `templates/rider.html`, `workouts.html` and `setup.html`.
- [ ] **Select and edit many activities at once.** The only bulk action today is "Change the type of all N results" (`/rides/bulk-sport` in `routes/rides.py`), which only appears after a search and always takes every result.
  - [ ] Add a select mode to the activity lists (dashboard history and search results, Workouts, a rider's page): a checkbox on each row, select all / none, shift-click for a range, and a bar that stays in view showing how many are picked.
  - [ ] Actions on the picked activities: delete, change type (`convert.change_sport`, as `bulk-sport` does), set the bike (`set_ride_bike` in `services/gear.py`), change the rider, rename, dismiss sanity flags, and download them as a zip.
  - [ ] Delete each ride through `duplicates.delete_activity` so tombstones, segment PRs and best efforts stay right. Ask for confirmation with the count, and commit once.
  - [ ] Keep the 5,000 cap from `bulk-sport`, and refresh the Home Assistant sensors once at the end rather than for every ride.

## Training and analysis

- [ ] **Training metrics** — FTP, power and HR zones, power curve, NP/IF/TSS, and fitness/fatigue/form (CTL/ATL/TSB). The inputs are already stored (`weightedAvgWatts`, streams, Garmin HRV), and the `sufferScore` column exists but is never filled in.
- [ ] **Laps and intervals** — show the laps recorded in FIT files, and auto-detect interval efforts.
- [ ] **Matched rides** — "this commute vs your last 20". The AI coach already gets similar past rides as context; surface that comparison in the UI.
- [ ] **Distance and climbing goals** (weekly or yearly), plus **friend challenges** built on the peer-to-peer sync.

## Routes

- [ ] **Road routing in the planner** — `routes/route_builder.py` only measures straight-line (haversine) distance between waypoints. Use a self-hosted BRouter (cycling profiles, runs on a Pi).
- [ ] **Send routes to Garmin** as courses.
- [ ] **Trailforks trail routing** for off-road routes.
- [ ] **More map types, including off-road ones** — every map uses Esri tiles only: dark, light, satellite and satellite + labels. None show trails, contours or surface.
  - [ ] Move the map-type list into one shared script. `TILE_DEFS` is copied into `heatmap.html` and `route_builder.html`, and `ride.html`, `segment.html` and `roughness.html` each hard-code their own layers. Remember the chosen type per viewer.
  - [ ] Keyless additions: **OpenTopoMap** (contours, paths, tracks), **CyclOSM** (cycling-focused: surfaces, MTB trail grades, bike shops) and **Esri World Topo**. Add **Waymarked Trails MTB / cycling** as an overlay that can sit on top of any base map.
  - [ ] Optional ones that need an API key, entered in Settings and stored with `services/credentials.py`: **Thunderforest** OpenCycleMap / Outdoors, and **OS Maps** (Ordnance Survey leisure maps for Great Britain, with bridleways and rights of way).
  - [ ] Follow each provider's usage policy (attribution, a proper user agent through the tile proxy, no bulk downloading). Check the free tiers allow this use.
  - [ ] Support the new types in the heatmap HD export. `routes/heatmap.py` `tile_proxy` only proxies Esri layers, and each layer's maximum zoom differs.
- [ ] **Zwift maps** — a Zwift ride's GPS track is drawn on the normal map tiles, and nothing treats virtual rides differently (`templates/ride.html`, `heatmap.html`). Worlds that copy a real place (London, Richmond, Innsbruck, New York, Yorkshire, Paris) land roughly in the right spot. Watopia, Makuri Islands and the other made-up worlds sit on open sea near the Solomon Islands, so the ride is a line over the ocean.
  - [ ] Work out the Zwift world from the track's bounding box (each world has a fixed box). Fall back to the normal map for anything that doesn't match, e.g. another virtual platform.
  - [ ] Show the ride over that world's map, as an image overlay fitted to the world's box. Check whether Zwift's map images (or the community ones, e.g. from ZwiftMap or zwifthacks) may be used, and with what credit.
  - [ ] Keep virtual rides off the heatmap by default, with a switch to show them, so Watopia doesn't add a patch of ocean to it.
  - [ ] Show the world (and the route, where it can be found) on the ride page, and let the ride list filter by world.
- [ ] **Clickable heatmap** — click a track on the heatmap to go straight to that ride's page (`/rides/<id>`).
  - [ ] `/heatmap/data` (`routes/heatmap.py`) selects only `streams` and returns bare point lists, so send each track's ride ID, name and date with it.
  - [ ] In `templates/heatmap.html` the polylines are `interactive: false`. Make them clickable, with a wider invisible hit line so thin tracks are easy to tap on a phone.
  - [ ] Where tracks overlap (a regular commute can stack dozens), show a popup listing every ride under the click (name, date, distance), newest first, each linking to its page, instead of picking one.
  - [ ] Optionally highlight the hovered or picked track over the others.

## Import and export

- [ ] **Auto-import folder** — watch a folder (Dropbox, Syncthing or a NAS directory) and import any ride added to it. This covers Wahoo, Hammerhead, Zwift and Coros through their auto-export features, with no need for their APIs.
  - [ ] Folder path (and the rider it imports for) set in Settings or with a `HEADWIND_IMPORT_DIR` env setting. Poll from a background thread like `_mqtt_heartbeat` rather than relying on inotify, which doesn't fire on network mounts.
  - [ ] Accept the same files as `routes/import_rides.py` (`.fit`, `.gpx`, `.gz`, zip) and reuse `_process_single_file` / `_insert`, so `services/duplicates.py` and `services/ingest.py` `after_ride_added` still run.
  - [ ] Wait until a file has stopped growing before reading it, so half-synced files aren't picked up.
  - [ ] Remember files already seen (path + size + mtime) so nothing is imported twice, and move each file to `imported/` or `failed/` afterwards.
  - [ ] Show the last scan, the import count and any errors on the Import page.
- [ ] **Segment export and import as a file** — export all segments to one file that can be shared (email, chat, a forum post) and imported on another instance, so segments can be shared without linking instances.
  - [ ] Reuse the friend feed's segment fields (`routes/friends.py` `feed`: name, start/end, distance, elevation, polyline, sport) and its import checks (`clean_polyline`, `valid_coord`). Export only our own segments (`friendId IS NULL`).
  - [ ] Skip segments that are already there on import (same start, end and sport), and scan existing rides against the new ones, as the friend sync does for imported segments.
  - [ ] Optionally offer GPX too, one track per segment, for use in other apps.
  - [ ] **Publish to GitHub and subscribe**, so subscribers stay up to date as the sharer adds, removes and edits segments.
    - [ ] Publishing: push the same file to a GitHub repo (or gist) whenever our segments change, using a token stored with `services/credentials.py`. Give each segment a stable ID in the file so edits and removals can be told apart from new segments.
    - [ ] Subscribing: needs only the file's public URL, no GitHub account. Poll it from a background thread like `_mqtt_heartbeat`, using ETag / `If-None-Match` so unchanged files cost nothing.
    - [ ] Keep track of where each subscribed segment came from (a source table plus a source segment ID, like `friendId` / `sourceSegId` for friends). Apply adds, edits (re-scan rides when the shape changes) and removals (delete the segment and its efforts). Subscribed segments are read-only locally, and unsubscribing removes them.
    - [ ] Treat the file as untrusted: run the same checks as the file import, cap the size and segment count, and keep the current segments if a fetch fails or the file doesn't parse.
- [x] **Pull weight from Garmin Connect** — weigh-ins from a Garmin Index scale (or entered in Garmin Connect) land in `WeightLog`, so the Nutrition weight trend fills itself in. `sync_garmin` in `services/garmin.py` already pulls daily metrics into `GarminDaily`; add the weigh-ins to the same sync.
  - [x] Fetch the weigh-ins for the sync window (garminconnect `get_weigh_ins` / `get_body_composition`) and convert grams to kg.
  - [x] Upsert into `WeightLog` with `source='garmin'`, one row per day (the table is `UNIQUE(riderId, logDate)`). Take the day's last weigh-in, and never overwrite a manual entry, the way `routes/nutrition.py` asks before replacing one.
- [ ] **Re-import rides that changed** — today a ride whose ID is already in the database is skipped outright (`_process_strava_export` in `routes/import_rides.py`), so a ride that first came in broken can't be repaired by importing again. Found when 11 Strava rides came in 1000x too long: 10 Trailforks GPX files whose lower-case `z` timestamps failed to parse (fixed in `fb101a2`) and a TCX file, all of which fell back to a CSV distance read in the wrong units.
  - [ ] When the ID matches, parse the file anyway and compare it with the saved ride: distance, moving and elapsed time, climb, start time, and whether it has a GPS track and streams.
  - [ ] Identical, or within rounding: skip as now.
  - [ ] Different: don't overwrite on the spot. Collect the differences and, once the import finishes, list them on the Import page with old and new values side by side. For each one (or all at once) offer: keep the saved ride, replace it with the import, or fill in only what's missing (e.g. add the GPS track but keep a renamed title).
  - [ ] Never lose the rider's own edits (name, description, bike, a dismissed sanity flag) on replace, and re-run `services/sanity.py`, the segment scan and `after_ride_added` for any ride that changes.
  - [ ] Works for the generic zip and single-file imports too, not only Strava exports.
- [ ] **TCX import.**
- [ ] **Fuller exports** — FIT/TCX and a full JSON/CSV dump (only GPX export exists today).

## Social

- [ ] **Ride photos**, with EXIF location stripped.
- [ ] **Peer-to-peer kudos and comments** between linked instances. (The existing `routes/kudos.py` is the AI coach, not social kudos.)
- [ ] *Longer term:* **ActivityPub federation**, so Headwind can talk to the Fediverse, not only to other Headwinds.

## Housekeeping

- [ ] **Date of birth instead of age** — the Settings and Nutrition profile forms (`pfAge` in `templates/settings.html`, `sgAge` in `templates/nutrition.html`) ask for an age. `routes/nutrition.py` `goal-profile` stores it as `Settings.birthYear` (this year minus the age), and `services/goal_model.py` `profile()` turns it back into this year minus `birthYear`. So the age used for BMR can be a year out, depending on when the birthday falls.
  - [ ] Add a `birthDate` column to `Settings`. Fill it from `birthYear` for existing installs (1 January of that year), then ask for the real date.
  - [ ] Swap both age fields for a date input, and send and validate `birth_date` in `goal-profile`.
  - [ ] Work out the current age in `profile()` from the date of birth, allowing for whether this year's birthday has passed, so it goes up on the birthday.

- [ ] **Configurable time zone** — `Europe/London` is hard-coded in 21 places (nutrition, MQTT, run stats, goal model, duplicates), so users elsewhere get the wrong "today". Make it a setting (defaulting to the server's local zone) and read it from one helper. This includes the MQTT water command (`services/mqtt_commands.py`), which logs water against the London date, so entries land on the wrong day near midnight elsewhere.
