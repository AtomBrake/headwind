# Headwind for iPhone and Apple Watch

A native SwiftUI companion for a Headwind server. It uses the same phone API and pairing as the Android app
(`routes/api_v1.py`, `routes/phones.py`), so the server needs no changes.

| Tab | Shows | Endpoint |
|---|---|---|
| Today | Calories ring (eaten / goal / burned), macros, water, steps, weight trend, food diary by meal, today's walks and runs | `GET /api/v1/today` |
| Record | Map, live stats, start / pause / finish a ride, e-bike ride, run, walk or hike, on a chosen bike; list of recordings, their upload status and bike | `POST /api/v1/rides`, `POST /api/v1/workouts`, `POST /api/v1/rides/ride/<id>/bike`, `POST /api/v1/live` |
| Overview | Riding totals for week / month / year / all time, 12-week distance chart, latest recovery (resting HR, HRV, sleep, body battery) | `GET /api/v1/overview` |
| Settings | Paired server, rider, units, unpair (the ping also brings the rider's bikes) | `GET /api/v1/ping` |

**Apple Watch:** recording only. Start, pause and end a ride, run, walk or hike on the wrist with GPS, heart rate,
speed or pace, distance and climbing.

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
- **Uploads:** every ride is saved on the phone first, then uploaded as GPX through the server's normal import
  (best efforts, segment matching, weather). Failed uploads, e.g. when offline, retry when the app is next opened.
  The server ignores duplicates, so a retry can't create a second copy.
- **Crash safety:** every GPS point is written to a journal file as it arrives. If the app is killed mid-ride, it
  offers to save the unfinished ride the next time it opens.
- **Pauses** start a new GPX track segment, so the gap isn't counted as distance or drawn as a straight line.

Planned next:

1. Food logging with barcode scan
2. Widgets
3. **Full code review: security, functionality and efficiency.**

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
   `Config/HeadwindWatch.entitlements`.

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
rejection, climbing, pauses, GPX output and journal recovery. The decoding tests use JSON captured from a real
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
  Shared/                  compiled into both apps: ride tracker, GPX writer, crash journal, ride summary, units
  Headwind/
    App/                   entry point, root view, tabs
    Core/                  API client, models, Keychain, session, shared views
    Pairing/  Today/  Overview/  Settings/
    Record/                iPhone recorder, recordings store and upload queue, Watch link, Record tab
  HeadwindWatch/           Watch app: HealthKit workout + GPS recorder, iPhone link, screens
  HeadwindTests/           Swift Testing unit tests
  HeadwindUITests/         end-to-end iPhone tests against a live server
  HeadwindWatchUITests/    end-to-end Watch recording test
```
