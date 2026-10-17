# TODO

Project-wide list of planned work. Tick items off as they land and note the version in CHANGELOG.md.

## Privacy

- [ ] **Privacy zones** — cut GPS points within X metres of home or work before they leave the instance. Apply to:
  - [ ] the friend feed (`routes/friends.py` `/api/feed`)
  - [ ] the route published to Home Assistant (MQTT attribute sensors)
  - [ ] heatmap exports
- [ ] **One token per friend** instead of the single shared feed token, so one person can be revoked on their own and each friend can be given a chosen subset: rides, segments, foods, or a date window.

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

## Training and analysis

- [ ] **Training metrics** — FTP, power and HR zones, power curve, NP/IF/TSS, and fitness/fatigue/form (CTL/ATL/TSB). The inputs are already stored (`weightedAvgWatts`, streams, Garmin HRV), and the `sufferScore` column exists but is never filled in.
- [ ] **Laps and intervals** — show the laps recorded in FIT files, and auto-detect interval efforts.
- [ ] **Matched rides** — "this commute vs your last 20". The AI coach already gets similar past rides as context; surface that comparison in the UI.
- [ ] **Distance and climbing goals** (weekly or yearly), plus **friend challenges** built on the peer-to-peer sync.

## Routes

- [ ] **Road routing in the planner** — `routes/route_builder.py` only measures straight-line (haversine) distance between waypoints. Use a self-hosted BRouter (cycling profiles, runs on a Pi).
- [ ] **Send routes to Garmin** as courses.
- [ ] **Trailforks trail routing** for off-road routes.

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
- [ ] **TCX import.**
- [ ] **Fuller exports** — FIT/TCX and a full JSON/CSV dump (only GPX export exists today).

## Social

- [ ] **Ride photos**, with EXIF location stripped.
- [ ] **Peer-to-peer kudos and comments** between linked instances. (The existing `routes/kudos.py` is the AI coach, not social kudos.)
- [ ] *Longer term:* **ActivityPub federation**, so Headwind can talk to the Fediverse, not only to other Headwinds.

## Housekeeping

- [ ] **Configurable time zone** — `Europe/London` is hard-coded in 21 places (nutrition, MQTT, run stats, goal model, duplicates), so users elsewhere get the wrong "today". Make it a setting (defaulting to the server's local zone) and read it from one helper. This includes the MQTT water command (`services/mqtt_commands.py`), which logs water against the London date, so entries land on the wrong day near midnight elsewhere.
