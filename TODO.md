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

- [x] **Friends can pull other friends' rides** (medium). Fixed: `OWN_RIDERS_SQL` filter in `routes/friends.py`, covered by `tests/test_friend_feed.py`. `/api/feed?rider=<name>` (`routes/friends.py` `feed`) looks the name up in every `Rider` row, and `/api/riders` lists them all, including the riders created for synced friends. So anyone with our feed token can download, with full GPS and HR streams, the rides a third friend shared only with us. In both endpoints, leave out riders that belong to a friend (`id NOT IN (SELECT riderId FROM Friend WHERE riderId IS NOT NULL)`). The segment query in the same feed already filters on `friendId IS NULL`.
- [ ] **Constant-time feed token check** (low). `feed` and `riders_list` compare the token with `!=`; use `_feed_token_ok()` (which uses `hmac.compare_digest`) in all three feed endpoints.
- [ ] **Feed token in the query string** (low). The feed endpoints also accept `?token=`, which puts the token in proxy access logs. Friend instances already send the `X-Feed-Token` header, so drop the query-string option.
- [ ] **Login lockout bypass without a reverse proxy** (low). `ProxyFix(x_for=1)` in `app.py` trusts `X-Forwarded-For` unconditionally, so on a directly exposed port each sign-in attempt can claim a new address and dodge the 8-per-5-minutes lockout. Make proxy trust opt-in (e.g. a `TRUSTED_PROXY` env setting), or key the lockout on the real socket address when no proxy is configured.
- [ ] **iOS: confirm the server before pairing from a link** (low). A `headwind://pair` link opened from outside the app pairs straight away when the app is unpaired (`ios/Headwind/Pairing/PairingView.swift`), and the "Pair with a different server?" alert (`ios/Headwind/App/HeadwindApp.swift`) names only the current server. Always show the new server's host before pairing, and tie each pending ride to the server it was recorded under, so `Session.unpair()` doesn't let old rides upload to a new server.

## Bugs

- [x] **MQTT heartbeat thread can die** — fixed: module-level `log` in `app.py`. (`app.py` `_mqtt_heartbeat`). Its gear-alert `except` handler calls `log.warning`, but `log` isn't defined there or at module level. If `gear.evaluate_alerts` raises, the resulting `NameError` kills the thread, which stops MQTT pushes, Home Assistant and weather sync, and goal auto-update until a restart. Add `log = logging.getLogger(__name__)` at module level.
- [ ] **Old APK path default** — `routes/phones.py` defaults `APK_PATH` to `/home/rob/headwind-android/dist/headwind.apk`. Replace it with a path under the data directory, or require `HEADWIND_APK`.

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

- [ ] **Watched import folder** (Dropbox, Syncthing or a NAS directory), covering Wahoo, Hammerhead, Zwift and Coros through their auto-export features without needing their APIs.
- [ ] **TCX import.**
- [ ] **Fuller exports** — FIT/TCX and a full JSON/CSV dump (only GPX export exists today).

## Social

- [ ] **Ride photos**, with EXIF location stripped.
- [ ] **Peer-to-peer kudos and comments** between linked instances. (The existing `routes/kudos.py` is the AI coach, not social kudos.)
- [ ] *Longer term:* **ActivityPub federation**, so Headwind can talk to the Fediverse, not only to other Headwinds.

## Housekeeping

- [ ] **Configurable time zone** — `Europe/London` is hard-coded in 21 places (nutrition, MQTT, run stats, goal model, duplicates), so users elsewhere get the wrong "today". Make it a setting (defaulting to the server's local zone) and read it from one helper. This includes the MQTT water command (`services/mqtt_commands.py`), which logs water against the London date, so entries land on the wrong day near midnight elsewhere.
