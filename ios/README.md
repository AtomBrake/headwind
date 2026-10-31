# Headwind for iPhone and Apple Watch

A native SwiftUI companion for a Headwind server. It uses the same phone API and pairing as the Android app
(`routes/api_v1.py`, `routes/phones.py`), so the server needs no changes.

| Tab | Shows | Endpoint |
|---|---|---|
| Today | Calories ring (eaten / goal / burned), macros, water, steps, weight trend, food diary by meal, today's other activities with their own icons | `GET /api/v1/today` |
| Record | Map (or a clock for a timed sport), live stats, start / pause / finish any sport the phone records, on a chosen bike; list of recordings, their upload status, bike and waiting photos | `POST /api/v1/rides`, `/workouts`, `/activities`, `/rides/ride/<id>/bike`, `/rides/<kind>/<id>/photos`, `/live` |
| Activities | Every activity of every sport, paged, searchable and filtered by sport; each with its map, stats, charts and photos (add, delete), and delete | `GET /api/v1/rides`, `/rides/<kind>/<id>`, `/photos/<name>` |
| Overview | A card per sport group for week / month / year / all time, a 12-week chart of one sport by distance or every sport by time, latest recovery (Garmin's or Apple Health's) | `GET /api/v1/overview` |
| Settings | Paired server, rider, units, Bluetooth sensors (pair, forget, battery, wheel size), Apple Health (what to send, how far back), unpair | `GET /api/v1/ping`, `POST /api/v1/health/days`, `GET`/`DELETE /api/v1/health` |

**Apple Watch:** recording only. Start, pause and end any sport on the wrist with heart rate, calories and, where it has them, GPS,
speed or pace, distance, climbing, power and cadence. On Apple Watch Ultra the Action button starts and pauses it.

## Sports

| Sport | Records | iPhone | Watch | Goes to |
|---|---|---|---|---|
| Ride, E-bike ride | GPS track | ✓ | ✓ | `/rides`, with its bike |
| Run, Walk, Hike | GPS track | ✓ | ✓ | `/workouts` |
| Open water swim | GPS track | | ✓ (water lock) | `/workouts` as a Swim |
| Indoor ride | Time (Watch: heart rate, calories, a paired speed sensor's distance; iPhone: its Bluetooth sensors' heart rate, power, cadence and a trainer's or wheel sensor's distance) | ✓ | ✓ | `/activities` as VirtualRide, with its bike |
| Treadmill run | Time (Watch: distance from its steps) | ✓ | ✓ | `/activities` as VirtualRun |
| Pool swim | Time, lengths (pool length chosen on the Watch) | | ✓ (water lock) | `/activities` as a Swim |
| Strength, HIIT, Yoga | Time (Watch: heart rate, calories) | ✓ | ✓ | `/activities` |

On the phone a timed sport is a stopwatch: no GPS, so no battery spent on it, plus whatever its Bluetooth sensors measure. A session must last a
minute to be kept.

## Recording rides

- **Sport and bike:** pick Ride, E-bike ride, Run, Walk or Hike before Start, on the phone or the Watch, and for rides
  the bike (the server's default to begin with; the last choice is remembered). Both are fixed once recording. Rides
  upload to `/api/v1/rides` with `bike_id`; on foot they go to `/api/v1/workouts` with their sport. On foot the live
  stats show pace, and the Watch records the matching Apple Health workout. A ride's bike can be changed later from its
  menu under Recordings, before or after upload.
- **iPhone:** GPS keeps recording with the screen locked. While recording, the phone reports its position to
  `/api/v1/live` every 15 s for Home Assistant, as the Android app does.
- **Watch:** runs as a HealthKit workout of the chosen sport, which keeps the app running with the wrist down and supplies heart
  rate. The finished ride is saved to Apple Health with its route, and sent to the iPhone as GPX with heart rate
  on every point. The phone uploads it with its own pairing, so the Watch never needs pairing. Riding without the
  phone is fine: the system queues the transfer until the two are back in range.
- **Watch without the phone:** the phone gives the Watch a token of its own (`POST /api/v1/devices/watch`, listed under
  the phone on the Phones page and revoked with it). If the phone hasn't taken a finished ride within 45 s, the Watch
  uploads it itself over Wi-Fi or cellular, backing off on failure to spare the battery, and cancels the queued transfer
  once it's on the server. Every recording carries the Watch's id for it, sent as its `client_id` either way, so the server
  keeps one copy.
- **Action button (Apple Watch Ultra):** Settings → Action Button → Workout → Headwind, then pick the sport under First
  Press. The press starts it (the system opens the app and it starts the workout session); a press during it pauses or
  resumes; the Action and side buttons together pause and resume too. `HeadwindWatch/WorkoutIntents.swift`.
- **Power and cadence:** a power meter or cadence sensor paired in the Watch's Bluetooth settings feeds the workout
  (watchOS 10), and is recorded on every point (`<power>` and `gpxtpx:cad` in the GPX, which the server's parser reads).
- **Bluetooth sensors on the iPhone:** for riding without the Watch. Pair them on the Sensors screen (Settings → Sensors, or
  the sensor button on the Record tab): heart rate straps, power meters, speed and cadence sensors and smart trainers (Bluetooth
  FTMS), Bluetooth LE only. Each shows its connection, battery and live reading; paired ones are remembered on this phone and
  connect while the Record tab is open and while recording, reconnecting by themselves if one drops. Heart rate, power (as a 3 s
  average) and cadence go on every GPS point and in the GPX; a run takes only heart rate. A timed session takes a sample every
  second, journalled, and an indoor ride takes its distance from the trainer, or from a wheel sensor and the wheel's size (2105 mm
  unless set on the Sensors screen). Bluetooth is asked for only when the Sensors screen first opens. `Headwind/Sensors/`, with the
  GATT parsing in `Shared/GATT.swift` and `Shared/SensorReadings.swift`. Not yet: a timed session's power and cadence on the server
  (`/activities` takes average heart rate only), and controlling a smart trainer.
- **Uploads:** every ride is saved on the phone first, then uploaded as GPX through the server's normal import
  (best efforts, segment matching, weather); a timed session as its summary. Failed uploads, e.g. when offline, retry
  when the app is next opened. The server ignores duplicates, so a retry can't create a second copy.
- **Photos:** add them to a recording (its menu under Recordings) before or after it's uploaded, or to any activity under
  Activities. They're redrawn as a JPEG of at most 1600 px on the phone (iPhone pictures are HEIC, which the server can't
  read), wait with the recording until it's on the server, and never hold it up. PhotosPicker needs no photo-library
  permission: only the pictures picked are shared.
- **Crash safety:** every GPS point is written to a journal file as it arrives (a timed session notes its progress every
  30 s). If the app is killed mid-ride, it offers to save the unfinished ride the next time it opens.
- **Pauses** start a new GPX track segment, so the gap isn't counted as distance or drawn as a straight line.

## Apple Health

Settings → Apple Health on the phone. Each kind of data is switched on by itself, and HealthKit asks for that one when it is:
steps, resting heart rate, HRV, sleep, weight, body fat, active and resting calories, and workouts from other apps. Headwind
only reads, and sends what it reads to your own server (`POST /api/v1/health/days`, one figure per day and metric, safe to
send twice). Observer queries with background delivery wake the app when there's something new; it also sends whenever it
comes to the foreground. The first time it goes back as far as you choose (30 days to 3 years).

- Steps, calories and HRV are HealthKit's daily statistics, so the iPhone's and Watch's samples are counted once.
- Sleep is every asleep stage from every source, overlaps counted once, dated to the morning the night ends.
- Garmin's figure wins for a day it has one. Apple's HRV is SDNN through the day, Garmin's RMSSD overnight: they're kept
  apart, and the Overview says which it shows. Apple has no sleep score or body battery.
- A weigh-in never replaces a manual or Garmin one for the same day.
- Workouts from other apps go up as Headwind's recordings do (with their route and heart rate, or timed without a route),
  with `ah_<uuid>` as their client id. Headwind's own (the Watch saves every workout to Health) are left out, and so are
  sports Headwind doesn't have (an elliptical, say). A workout deleted in Health isn't deleted on the server: the server's
  copy may be the one it kept of several.
- **Remove Apple Health data from Headwind** deletes the daily figures and weigh-ins on the server and stops sending.

## iPhone Duo and other screen sizes

The app follows the size class, never the screen's size, so it works on the iPhone Duo's outer (compact) and inner
(regular width) screens, in either orientation, and re-flows as it's folded or opened:

- Today and Overview lay their cards out in as many columns as fit (`CardColumns`).
- Record puts the controls beside the map instead of over it.
- Activities is a `NavigationSplitView`: the list beside the open activity.
- On iOS 18 the tabs are `.sidebarAdaptable`, so the system can place them where it suits the screen.

All recording state lives in objects made at launch (`PhoneRideRecorder`, `RideStore`, `WatchBridge`), not in the views, so a
fold or rotation mid-ride loses nothing. The fold-specific APIs Apple has shown (reserved regions, ArrangementView) are in the
iOS 27.1 SDK only; the app uses only what Xcode 16 and iOS 17 have, and the system's own containers keep clear of the fold.

Planned next:

1. Food logging with barcode scan
2. Widgets
3. Smart trainers on the iPhone: an indoor ride uploaded as a file with its power, cadence and distance, then ERG, resistance and
   gradient simulation through Fitness Machine control

Later:

- **Example docker-compose file for running the server behind HTTPS.** The phone apps only pair over https://. The
  current `docker-compose.yml` serves plain http on port 5001, so an example with a reverse proxy that handles
  certificates (e.g. Caddy) would make the server ready to pair out of the box.

- **Trailforks integration.** Search and import trails. Trailforks' API needs an approved app key from Trailforks.
- **Route planner.** Import Trailforks trails and build a route that links them. The server already has a planner
  at `/planner` (`routes/route_builder.py`) that saves routes and exports GPX, so the phone would extend that
  rather than start from scratch.
- **Segments from Trailforks trails.** Turn an imported trail into a Headwind segment, so rides are matched against it
  and appear on its leaderboard like any other segment (`services/segments.py`).
- **Follow a route on the watch,** with a map, the route line, your position and off-route alerts. This builds on
  the watch recording app in step 2.

## Requirements

- Xcode 16 or newer (the project uses folder-synchronised groups)
- iOS 17 or newer on the phone; watchOS 10 or newer on the Watch
- A Headwind server reachable over **https://**, the same requirement as the Android app

## Run it

1. Open `ios/Headwind.xcodeproj` in Xcode.
2. **Simulator:** choose an iPhone simulator and press Run.
3. **Your own iPhone:** plug it in, select the **Headwind** target → *Signing & Capabilities*, choose your Team
   (a free Apple ID works) and, if Xcode complains, change the bundle identifier to something unique to you.
   Turn on Developer Mode on the phone when iOS asks. Builds signed with a free Apple ID expire after 7 days;
   a paid developer account lasts a year and allows TestFlight.
4. **Apple Watch:** also choose your Team for the **HeadwindWatch** target. The Watch app is embedded in the iPhone
   app, so installing on the phone offers it on the paired Watch (Watch app → *Available Apps*), or run the
   **HeadwindWatch** scheme with the Watch selected. It needs the HealthKit capability, which Xcode adds from
   `Config/HeadwindWatch.entitlements`. The iPhone target needs it too, with background delivery, for Apple Health
   (`Config/Headwind.entitlements`).

## Pairing

On the server, open **Phones**, name the phone and press **Create token**. Then either:

- tap **Scan QR code** in the app,
- point the iPhone's Camera app at the QR code. The app registers the `headwind://` scheme, so iOS offers to open it, or
- paste the `headwind://pair?...` link shown under the QR code into *Enter details manually*.

The token is stored in the Keychain. If the server revokes it, the next request gets a 401 and the app returns to the
pairing screen and says why.

## Development against a local server

Debug builds also accept plain `http://localhost` (or `127.0.0.1`), so the simulator can talk to a dev server on the
same Mac. Release builds are https-only. The Phones page refuses non-https addresses, so mint a token from a shell:

```sh
python -c "from app import create_app; from services import device_auth
app = create_app()
with app.app_context(): print(device_auth.create('Simulator')[0])"
```

Then pair with server `http://localhost:5001` and that token.

## Tests

```sh
xcodebuild test -project ios/Headwind.xcodeproj -scheme Headwind -destination 'platform=iOS Simulator,name=iPhone 17'
```

The unit tests cover pairing links, decoding, formatting, and the recording maths: distance, moving time, GPS-jump
rejection, climbing, pauses, GPX output (with power and cadence), journal recovery (timed sessions too), where each sport
uploads to, the Watch's ids, Apple Health's sleep merging, and the Bluetooth sensors: GATT parsing, counters wrapping, 3 s power,
combining sensors, distance by sensor and a timed session's samples. The decoding tests use JSON captured from a real
server in `HeadwindTests/Fixtures/`. If an endpoint's shape changes, refresh those files and the tests show what
the app no longer understands.

The UI tests run against a live server and skip themselves otherwise. `RecordRideUITests` simulates GPS, records a
ride and waits for the server to accept it. Grant location first:

```sh
xcrun simctl privacy <device> grant location io.github.atombrake.headwind
TEST_RUNNER_HW_SERVER=http://localhost:5001 TEST_RUNNER_HW_TOKEN=hw_... xcodebuild test ... -parallel-testing-enabled NO
```

The **HeadwindWatch** scheme's UI test records a ride on a Watch simulator. Give the Watch a moving location first:
`xcrun simctl location <watch> start --speed=8 51.4545,-2.5879 51.4745,-2.5879`.

## Layout

```
ios/
  Headwind.xcodeproj
  Config/                  Info.plists (URL scheme, background modes) and the Watch's HealthKit entitlements
  Shared/                  compiled into both apps: sports, ride tracker, GPX writer, crash journal, ride summary, units,
                           API client and pairing, upload routing, Bluetooth sensor parsing and readings
  Headwind/
    App/                   entry point, root view, tabs
    Core/                  API client, models, Keychain, session, shared views
    Pairing/  Today/  Overview/  Settings/
    Activities/            every activity from the server, and one in detail with its photos
    Health/                Apple Health reader (HealthSync)
    Record/                iPhone recorder, recordings store and upload queue, Watch link, Record tab
    Sensors/               Bluetooth sensors: CoreBluetooth manager and the Sensors screen
  HeadwindWatch/           Watch app: HealthKit workout + GPS recorder, iPhone link and direct upload, Action button intents, screens
  HeadwindTests/           Swift Testing unit tests
  HeadwindUITests/         end-to-end iPhone tests against a live server
  HeadwindWatchUITests/    end-to-end Watch recording test
```
