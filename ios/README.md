# Headwind for iPhone and Apple Watch

A native SwiftUI companion for a Headwind server. It uses the same phone API and pairing as the Android app
(`routes/api_v1.py`, `routes/phones.py`), so the server needs no changes.

| Tab | Shows | Endpoint |
|---|---|---|
| Today | Calories ring (eaten / goal / burned), macros, water, steps, weight trend, food diary by meal, today's other activities with their own icons | `GET /api/v1/today` |
| Record | Map (or a clock for a timed sport), live stats, start / pause / finish any sport the phone records, on a chosen bike; share a live tracking link; list of recordings, their upload status, bike and waiting photos (add, remove, reorder) | `POST /api/v1/activities` (older servers: `/rides`, `/workouts`), `/activities/<id>/bike`, `/activities/<id>/photos`, `/live`, `/live/share` |
| Activities | Every activity of every sport, paged, searchable and filtered by sport, and by whose (Me, a friend, Everyone); each with its map (a Zwift ride's over its Zwift world), stats, charts and photos (add, delete, reorder, caption), and delete. A friend's is read-only | `GET /api/v1/activities` (`?rider=`), `/friends`, `/activities/<id>`, `/photos/<name>`, `/zwift/<slug>.png`, `/activities/<id>/photos…` (older servers, whose `/ping` says `api` below 3: `/rides`, `/rides/<kind>/<id>…`) |
| Overview | A card per sport group for week / month / year / all time (the week and month as the server counts them: the past 7 and 28 days, or calendar ones, with their dates), a 12-week chart of one sport by distance or every sport by time, latest recovery (Garmin's or Apple Health's) | `GET /api/v1/overview` |
| Settings | Paired server, rider, units, Bluetooth sensors (pair, forget, battery, wheel size), whether recordings share a live tracking link and the contacts the server emails it to, Apple Health (what to send, how far back), friends (make a QR code for a friend with what they may see; add a friend by scanning or pasting their code), unpair | `GET /api/v1/ping`, `/contacts`, `POST /api/v1/health/days`, `GET`/`DELETE /api/v1/health`, `POST /api/v1/friends/tokens`, `/friends/probe`, `/friends` |

**Apple Watch:** recording only. Start, pause and end any sport on the wrist with heart rate, calories and, where it has them, GPS,
speed or pace, distance, climbing, power and cadence, and a map of the track so far. On Apple Watch Ultra the Action button starts and pauses it.

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
  the bike (the server's default to begin with; the last choice is remembered). Both are fixed once recording. Every
  recording uploads to `/api/v1/activities` with its sport, a ride with its `bike_id`; to a server older than that (its
  `/api/v1/ping` says `api` 1) rides go to `/api/v1/rides` and the rest to `/api/v1/workouts`. On foot the live
  stats show pace, and the Watch records the matching Apple Health workout. A ride's bike can be changed later from its
  menu under Recordings, before or after upload.
- **iPhone:** GPS keeps recording with the screen locked. While recording, the phone reports its position to
  `/api/v1/live` every 15 s for Home Assistant, as the Android app does. Every post carries the recording's id
  (`recording`), given at Start and kept in the journal; the upload sends the same id as its `client_id`.
- **Live tracking link (iPhone):** "Share live location" on the Record screen (its default is in Settings) asks the server
  for a link at Start (`POST /api/v1/live/share`), or mid-recording with the track so far thinned as the server thins it
  (a point every 10 s or 25 m, at most 5,000), and opens the share sheet with it. While the link runs the phone posts every
  `send_every_s` (5 s) instead of 15, in the background too. The idle post at Finish or Discard ends it; it then works for an
  hour, and stays on the Record screen until then to send again, copy or stop (**Stop sharing**: `DELETE /api/v1/live/share`).
  A 409 (no outside https address) shows the server's reason with a button to its Settings page, and the recording goes on
  without the link. `Headwind/Record/LiveShareController.swift`, `Shared/LiveShare.swift`.
- **Contacts for the live link:** Settings → Live tracking link → **Contacts to email it to** lists the people the server
  emails each new link to (`GET/POST /api/v1/contacts`, `PATCH/DELETE /api/v1/contacts/<id>`; the same list as Settings on
  the web), each with a switch. The reply to `POST /api/v1/live/share` names them (`contacts`: `sending`, `sent` or `failed`
  with why), and the phone asks `GET /api/v1/live/share?recording=` every 3 s for up to a minute until none is left sending;
  the Record screen's link card says "Sent to Sam and Alex." When someone is getting it, Start doesn't open the share sheet:
  **Send** is there for anyone else. `Headwind/Settings/ContactsView.swift`.
- **Live posts from the Watch:** with "Share live location" on at Start (its default comes from the phone's Settings) and a
  token of its own, a Watch recording with GPS posts `/api/v1/live` itself every 30 s with its recording's id, and idle when
  it ends: through the phone's connection when it's near, over Wi-Fi or cellular when not. With its first post it asks for
  the link (`POST /api/v1/live/share`, tried again with each post while there's no signal) and, having no share sheet, hands
  it to the phone (`transferUserInfo`, `LiveLinkMessage`), which shows a notification ("Your live link is ready"; permission is
  asked when sharing is switched on in Settings) whose tap opens the share sheet, and keeps the link on the Record screen. At
  the end it tells the phone, which shows the link as finished. The phone posts nothing itself for a recording the Watch
  makes. The server emails the link to the contacts itself, so it gets out with the phone left at home: the Watch's controls
  page says who it went to, asking until the server has finished, then hands the phone the link once more with how it went
  (`LiveLinkMessage.recipients`). `HeadwindWatch/WorkoutManager.swift`, `Headwind/Record/LiveLinkNotifier.swift`.
- **Watch:** runs as a HealthKit workout of the chosen sport, which keeps the app running with the wrist down and supplies heart
  rate. The finished ride is saved to Apple Health with its route, and sent to the iPhone as GPX with heart rate
  on every point. The phone uploads it with its own pairing, so the Watch never needs pairing. Riding without the
  phone is fine: the system queues the transfer until the two are back in range.
- **Watch without the phone:** the phone gives the Watch a token of its own (`POST /api/v1/devices/watch`, listed under
  the phone on the Phones page and revoked with it). If the phone hasn't taken a finished ride within 45 s, the Watch
  uploads it itself over Wi-Fi or cellular, backing off on failure to spare the battery, and cancels the queued transfer
  once it's on the server. The upload goes through a background `URLSession`, queued when the ride is saved to start when
  the 45 s are up, so it goes even if the app has been suspended (wrist down, another app opened). Every recording carries the Watch's id for it, sent as its `client_id` either way, so the server
  keeps one copy.
- **The Watch's pages while recording:** swipe between the controls (End, Pause, the live link), the figures, and for a sport with
  GPS a map: the track so far (a `MapPolyline`) and where you are (`UserAnnotation`), with distance and time over it (distance and
  pace on foot). The page moves the camera to each fix itself, at the zoom the Digital Crown left, turned to the direction of travel
  from GPS: MapKit's own follow mode would put the zoom back every time it started following again, and the compass would point
  where the wrist does and keep the compass running. Timed-only sessions (an indoor ride, a
  treadmill run, a pool swim, strength) have the first two. The track is the recording's own fixes thinned as they arrive
  (`Shared/MapTrack.swift`): a fix is drawn only when leaving it out would bend the line more than 3 m, the tolerance doubling
  whenever more than 2,000 points are kept, so a long day redraws as quickly as a short one; the GPX and the journal still keep
  every fix. Each stretch between pauses is its own line. With the wrist down, in Always On, or on another page, the map rests:
  dimmed, held where it was and not redrawn, until the wrist comes up. MapKit in an app doesn't use the offline maps downloaded in
  Apple Maps, so with no phone and no connection the Watch may have no tiles beyond what it has cached: the track and your position
  still draw, on MapKit's empty grid. `HeadwindWatch/MapPage.swift`; the line layer (`TrackLines`) is there for a route to be drawn
  under the track.
- **Action button (Apple Watch Ultra):** Settings → Action Button → Workout → Headwind, then pick the sport under First
  Press. The press starts it (the system opens the app and it starts the workout session); a press during it pauses or
  resumes; the Action and side buttons together pause and resume too. `HeadwindWatch/WorkoutIntents.swift`.
- **Power and cadence:** a power meter or cadence sensor paired in the Watch's Bluetooth settings feeds the workout
  (watchOS 10), and is recorded on every point (`<power>` and `gpxtpx:cad` in the GPX, which the server's parser reads).
  The screen shows power as a 3 s average, as head units do; the GPX keeps every reading as it came.
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
  when the app is next opened. The server ignores duplicates, so a retry can't create a second copy. Each recording
  uploads only to the server the phone was paired with when it was made: after pairing with another server, one still
  waiting says so under Recordings, and its menu offers to upload it to the new server instead.
- **Photos:** add them from the library or the camera to a recording (Photos in its menu under Recordings) before or after
  it's uploaded, or to any activity under Activities. They're redrawn as a JPEG of at most 1600 px on the phone (iPhone
  pictures are HEIC, which the server can't read), wait with the recording until it's on the server, and never hold it up.
  PhotosPicker needs no photo-library permission: only the pictures picked are shared; the camera asks for the camera
  permission the QR scanner already uses. On an activity each photo has its own tile while it uploads (tap a failed one to
  try again); Select deletes several at once and drags them into a new order (the first is the cover); the full-size photo
  has its caption, Edit caption and Delete. Deleting asks first. A recording's waiting photos can be removed and reordered,
  and go up in that order. `Headwind/Activities/ActivityPhotos.swift`, `Headwind/Record/PendingPhotosView.swift`.
- **Crash safety:** every GPS point is written to a journal file as it arrives (a timed session notes its progress every
  30 s). If the app is killed mid-ride, it offers to save the unfinished ride the next time it opens.
- **Pauses** start a new GPX track segment, so the gap isn't counted as distance or drawn as a straight line.

## Apple Health

Settings → Apple Health on the phone. Each kind of data is switched on by itself, and HealthKit asks for that one when it is
(or **Allow all** switches every one on, asking for them in one Health sheet):
steps, resting heart rate, HRV, sleep, weight, body fat, active and resting calories, and workouts from other apps. Headwind
only reads, and sends what it reads to your own server (`POST /api/v1/health/days`, one figure per day and metric, safe to
send twice). Observer queries with background delivery wake the app when there's something new; it also sends whenever it
comes to the foreground. The first time it goes back as far as you choose (30 days to 3 years). Coming to the foreground, it
asks HealthKit again for anything switched on that HealthKit has no answer for (Health's permissions were reset, say), then
looks through that history again, since HealthKit hides what it may not share rather than saying so.

- Steps, calories and HRV are HealthKit's daily statistics, so the iPhone's and Watch's samples are counted once.
- Sleep is every asleep stage from every source, overlaps counted once, dated to the morning the night ends. Its deep, core and
  REM sleep, time awake and time in bed come from one source per night, the Watch's where it recorded the night, else the one with
  the most staged sleep; a night that's only "asleep" (an iPhone alone, an older Watch) has none.
- Garmin's figure wins for a day it has one. Apple's HRV is SDNN through the day, Garmin's RMSSD overnight: they're kept
  apart, and the Overview says which it shows. Apple has no sleep score or body battery.
- A weigh-in never replaces a manual or Garmin one for the same day.
- Workouts from other apps go up as Headwind's recordings do (with their route and heart rate, or timed without a route),
  with `ah_<uuid>` as their client id. A route under a minute or 100 m long counts as none: some apps save one stale
  location with a workout, and the workout goes up timed with Health's duration, distance, calories and heart rate instead. Before reading a batch's routes and heart rate, the phone asks the server which of
  those ids it has (`POST /api/v1/activities/known`) and leaves them out, so a look back through years of workouts sends only
  the new ones. One deleted on the server counts as had, so a sync doesn't bring it back. Headwind's own (the Watch saves every workout to Health) are left out, and so are
  sports Headwind doesn't have (an elliptical, say). A workout deleted in Health isn't deleted on the server: the server's
  copy may be the one it kept of several. Settings shows what the last look found, by app, and what became of each. It
  warns when the server refuses one, and when a look through all your history finds no other app's workouts: HealthKit
  hides data it isn't allowed to share without saying so, so that usually means Workouts is off for Headwind in the
  Health app.
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

What's planned for the apps (food logging, widgets, smart-trainer control, following a route on the iPhone and Watch) is in
[TODO.md](../TODO.md) under **iPhone and Watch** in each priority tier.

## Requirements

- Xcode 16 or newer (the project uses folder-synchronised groups)
- iOS 17 or newer on the phone; watchOS 10 or newer on the Watch
- A Headwind server reachable over **https://**, the same requirement as the Android app (the main README's
  [Putting it on the internet safely](../README.md#putting-it-on-the-internet-safely) has a Cloudflare Tunnel compose file
  and a Caddyfile)

## Run it

1. Open `ios/Headwind.xcodeproj` in Xcode.
2. **Simulator:** choose an iPhone simulator and press Run.
3. **Your own iPhone:** add your Apple ID in Xcode → *Settings* → *Accounts* (a free Apple ID works), then create
   `ios/Config/Signing.local.xcconfig` containing your Team ID, which that Accounts pane and developer.apple.com
   show:

   ```
   DEVELOPMENT_TEAM = ABCDE12345
   ```

   `Config/Signing.xcconfig` reads it for every target, and git ignores it. Don't pick the Team in
   *Signing & Capabilities* instead: Xcode writes it into `project.pbxproj`, which would put your team in a commit.
   If Xcode complains about the bundle identifier, change it to something unique to you. Plug the phone in and turn on
   Developer Mode when iOS asks. Builds signed with a free Apple ID expire after 7 days; a paid developer account
   lasts a year and allows TestFlight.
4. **Apple Watch:** the same team signs the **HeadwindWatch** target. The Watch app is embedded in the iPhone
   app, so installing on the phone offers it on the paired Watch (Watch app → *Available Apps*), or run the
   **HeadwindWatch** scheme with the Watch selected. It needs the HealthKit capability, which Xcode adds from
   `Config/HeadwindWatch.entitlements`. The iPhone target needs it too, with background delivery, for Apple Health
   (`Config/Headwind.entitlements`).

## Versions

Both apps show their version: the iPhone in **Settings**, the Watch at the bottom of its start screen, as `0.1.1 (2)`
(the version, then the build number). It lives in `Config/Version.xcconfig`, shared by every target, since the Watch
app has to match the iPhone app it's inside. Bump it before every build that goes onto a phone or Watch, so you can tell
which build a device is running:

```sh
python3 ios/scripts/bump_version.py          # 0.1.1 -> 0.1.2
```

The parts move the way the server's do:

- **patch** (`0.1.1` → `0.1.2`), the default: every build put on a device, whether it fixes something or adds something.
- **minor** (`bump_version.py minor`, `0.1.7` → `0.2.0`): the app needs a newer server than the last version did, or it
  changes what it keeps on the device (the recording journal, the upload queue) so that going back a version would lose
  or misread it.
- **major** (`bump_version.py major`, `0.x` → `1.0.0`): the app leaves beta.

The build number goes up by one with every bump. `bump_version.py --show` prints both without changing them. Builds in
the simulator and test runs don't need a bump.

## Pairing

On the server, open **Phones**, name the phone and press **Create token**. Then either:

- tap **Scan QR code** in the app,
- point the iPhone's Camera app at the QR code. The app registers the `headwind://` scheme, so iOS offers to open it, or
- paste the `headwind://pair?...` link shown under the QR code into *Enter details manually*.

A link opened from outside the app (the Camera app, a web page, a message) never pairs by itself: the app names the
server it points to and asks first, and when it would replace the current pairing it names both.

A friend's QR code holds a `headwind://friend?c=hwfc_…` link instead. Opened from the Camera app, it goes to *Add a friend*
rather than pairing; on a phone that isn't paired yet, it waits until it is.

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
uploads to (by the server's `api`), the Watch's ids, the Watch map's thinned track (corners and turns kept, under 2,000 points
after six hours), Apple Health's sleep merging, and the Bluetooth sensors: GATT parsing, counters wrapping, 3 s power,
combining sensors, distance by sensor and a timed session's samples. The decoding tests use JSON captured from a real
server in `HeadwindTests/Fixtures/`. If an endpoint's shape changes, refresh those files and the tests show what
the app no longer understands.

The UI tests run against a live server and skip themselves otherwise. `RecordRideUITests` simulates GPS, records a
ride and waits for the server to accept it. `LiveShareUITests` starts a run with "Share live location" on: a server with an
https outside address gives the share sheet and then **Stop sharing**; a local one refuses, and the test checks the reason
is shown and the recording goes on. Grant location first:

```sh
xcrun simctl privacy <device> grant location io.github.atombrake.headwind
TEST_RUNNER_HW_SERVER=http://localhost:5001 TEST_RUNNER_HW_TOKEN=hw_... xcodebuild test ... -parallel-testing-enabled NO
```

The **HeadwindWatch** scheme's UI tests record a ride and a run on a Watch simulator, checking the map page after the figures
(the crown zooming it, and it coming back after the app has been in the background), and a strength session, which has no map
page. Give the Watch a moving location first, with turns so the map has something to draw:
`xcrun simctl location <watch> start --speed=8 51.4545,-2.5879 51.4581,-2.5879 51.4581,-2.5836 51.4545,-2.5836 51.4545,-2.5879`.
On a simulator that has never granted Headwind Health access, the test pages through the Health sheet itself (Review, each
switch, Next, Continue, Full History, Done), which takes about 30 s the first time.

## Layout

```
ios/
  Headwind.xcodeproj
  Config/                  Info.plists (URL scheme, background modes), the Watch's HealthKit entitlements, signing and
                           the apps' version (Version.xcconfig)
  scripts/                 bump_version.py
  Shared/                  compiled into both apps: sports, ride tracker, the map's thinned track, GPX writer, crash journal, ride summary, units,
                           API client and pairing, upload routing, Bluetooth sensor parsing and readings
  Headwind/
    App/                   entry point, root view, tabs
    Core/                  API client, models, Keychain, session, shared views
    Pairing/  Today/  Overview/  Settings/
    Friends/               share codes: make one for a friend as a QR code, add a friend from theirs
    Activities/            every activity from the server, and one in detail with its photos
    Health/                Apple Health reader (HealthSync)
    Record/                iPhone recorder, recordings store and upload queue, Watch link, Record tab
    Sensors/               Bluetooth sensors: CoreBluetooth manager and the Sensors screen
  HeadwindWatch/           Watch app: HealthKit workout + GPS recorder, iPhone link and direct upload, Action button intents, screens
                           (the recording's map page in MapPage.swift)
  HeadwindTests/           Swift Testing unit tests
  HeadwindUITests/         end-to-end iPhone tests against a live server
  HeadwindWatchUITests/    end-to-end Watch recording test
```
