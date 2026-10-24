# Changelog

## [0.7.18-beta] - 2026-10-24

### Changed
- **Only sports you have gear for count as having none.** The Gear page's note and the "No gear" list on the Activities page used to count every activity with no shoes or kit, so swims, yoga or weight training showed up even with no gear to put them on. Now a sport counts only once a pair of shoes or other gear (not retired) is its default or has been on one of its activities. Rides still count once you have a bike.

## [0.7.17-beta] - 2026-10-24

Dependency: `cryptography` 42.0 or later (`pip install -r requirements.txt` outside Docker). At the first start, a key file, `.secrets_key`, is made beside the database, and the keys and passwords saved in the database are encrypted with it.

### Added
- **Whose rides the heatmap shows.** A new Whose choice on the heatmap shows **Mine**, one friend's rides, or **Everyone together**. Friends' rides used to be mixed into yours with no way to tell them apart; the heatmap now opens on yours alone. Each person keeps their own colour, yours the usual orange, and Everyone together has a key with each person's ride count. Picking someone zooms the map to their rides. The choice only appears once a friend (or another rider on your instance) has rides with a map.
- **A list of the activities with no gear.** The note on the Gear page counts every ride with no bike and every other activity with no shoes or kit, says how many of each type, and links to them on the Activities page, a month at a time. Each row there has a bike or kit picker, so they can be sorted out one by one. The Gear choice in the Activities search also finds one bike's rides or one pair of shoes' activities. On the gear calendar, the rides on the days you pick are listed under it, each with its own bike, so a day with two rides on two bikes can be split.

### Changed
- **Saved keys and passwords are encrypted.** The AI keys, the Home Assistant token, the MQTT password, friends' feed tokens and the Garmin sign-in are encrypted in the database, with the key in `.secrets_key` beside it. A copy of `bike.db` or a backup, shared for troubleshooting say, gives none of them away. Backups leave the key out: restoring on the same server keeps everything, while a restore on another server says which to enter again, or to copy `.secrets_key` across and restart.
- **Activities look the same on every list.** The dashboard, Activities, Workouts, bike, kit and rider pages draw each activity the same way: sport, name, date, distance, time, speed or pace for the sport, and the climb. Forms share one layout, with any error at the top.

### Fixed
- **The heatmap export ignored the sport filter**, and always drew every sport. It now draws what the map shows. Changing the sport no longer clears the highlighted date range and map type.

## [0.7.16-beta] - 2026-10-24

### Added
- **Full re-sync with Garmin.** A new Full re-sync button in Settings → Garmin Connect (with activity sync on) checks every Garmin activity in Headwind against all of your Garmin Connect history at once, not just the last 90 days and a little older each day. Anything deleted, renamed, given another sport or cropped in Garmin is listed on the Import page for review, as with the daily check, and nothing changes until you choose. When Garmin's count of your activities matches its list, the oldest ones are checked too, and a big clear-out counts as deletions rather than a broken list. If none of your activities are in Garmin's list (signed in to another account, say), nothing is flagged.

## [0.7.15-beta] - 2026-10-24

Migration, at the first start: `Settings` gains `garminChangesBefore`, `aiAutoAnalyse` and `appearance`, `WeightLog` gains `sourceDetail`, and there are new `GarminSeen` and `GarminChange` tables.

### Added
- **Activities deleted or changed in Garmin Connect are flagged for review.** A deletion, rename, change of sport or crop in Garmin used to never reach Headwind, because the sync only reads new activities. Once a day (with activity sync on) Headwind compares the last 90 days in Garmin, and a little further back each day, with what it imported. Each change is listed on the Import page and the activity's page, and nothing changes until you choose: delete it here too or keep it; use Garmin's name or sport or keep yours; a cropped recording is offered like a re-import (keep, replace or fill in). A name or sport you changed in Headwind is never overwritten or flagged. A listing that fails, or one missing most activities at once (another account, say), flags nothing. Activities imported before this version are compared from their first check on.
- **New rides can be analysed by the AI coach as they arrive.** A new "Analyse New Rides" setting on the AI page writes the coaching notes for each new ride from Garmin, the phone app or an import, with the coach personality you last chose. It's off by default and can only be turned on once an AI provider is set up. Only rides from the last 3 days are analysed, so importing your history doesn't run up a bill; use Bulk Analysis for older rides. While a ride is being analysed its page shows "Analysing…". A failed analysis shows on the Tasks page and isn't retried, and the ride keeps its Analyse button. With ntfy set up, you get a notification when the analysis is ready.
- **A Weight page.** The weight graph is now Health → Weight in the sidebar (it was only reachable from the Nutrition day view), and under the graph a table lists the period's weigh-ins, newest first: weight, that day's trend, the change since the previous weigh-in and where it came from.
- **Light mode.** Settings → Display Preferences has a new Appearance choice: Auto (the default) follows each device's light or dark setting and switches with it, at sunset say, while Light and Dark apply everywhere. Charts and maps change colour with the page, with no reload.

### Changed
- **One look across the app.** Pages were styled one by one, so the same thing looked different from page to page. Buttons, tables, helper text, empty lists and colours now come from one set of shared styles. Small buttons work on every page (they did nothing outside Gear), only a page's main action is orange, and a selected option (a sport, a period) is highlighted rather than orange. Every table has the same headings and spacing, with numbers right-aligned.
- **The way back is in the page title.** A page that sits under another shows it before its title, Gear › Stumpjumper, as a link, in place of the "← Back" buttons.
- **The same words for the same thing.** Bikes are **Retired** and **Brought back** like other gear (they were Archived and Restored). A form says **Add** when it makes something and **Save** when it changes it. Delete warnings say what goes and what stays.
- **Garmin weigh-ins count as scale readings**, unless Garmin says they were typed into Garmin Connect. This decides the dots on the weight graph, the "scale" tag on the Nutrition day and the Home Assistant weight chart.
- **Times like "last used" and "last synced"** show as a date and time in your time zone, not a raw UTC timestamp.
- **Python 3.14.** The Docker image and the Windows build are now built on Python 3.14. Running Headwind outside Docker still works on Python 3.12 or later.

### Fixed
- **An activity page with no map grew taller and taller.** On an indoor ride, a watch recording without GPS or a pool swim, the charts stretched every time the window changed size until the page couldn't be used. Without a map beside them, the charts now have a fixed height and sit side by side.

## [0.7.14-beta] - 2026-10-20

The release of 0.7.13-beta, which never got a Docker image: its build stopped installing `garminconnect` 0.3.19, which needs Python 3.12. Nothing else changed since 0.7.13-beta; read its notes below for the upgrade.

### Changed
- **Python 3.12.** The Docker image and the Windows build are now built on Python 3.12, and running Headwind outside Docker needs Python 3.12 or later.

## [0.7.13-beta] - 2026-10-20

Migration, at the first start: `Settings` gains `garminSignInNeeded`, and there's a new `StravaExport` table. Dependency: `garminconnect` must now be 0.3.19 or later, which needs Python 3.12 or later (`pip install -r requirements.txt` outside Docker).

**Your Garmin password is no longer kept.** Headwind signs in to Garmin once and keeps only the sign-in tokens Garmin gives it, which renew themselves. On an upgrade, the stored password is used once more if the tokens need it, then deleted from the database. If your Garmin account uses 2-step verification and the tokens had already stopped working, Settings and the Tasks page ask you to sign in again.

### Changed
- **Garmin sign-in without a stored password.** Connect (Settings → Garmin Connect, or the setup wizard) sends the password to Garmin for that sign-in only; the email is saved once Garmin accepts it. If Garmin stops accepting the tokens (you changed your Garmin password, or signed out everywhere), syncing stops and the Garmin card and the Tasks page say **Sign in again**; a later sync that works clears it. **Sign out** deletes the tokens. Signing in to another account replaces the old tokens only once the new sign-in works.
- **The Strava export is kept, so it can be imported again without uploading it.** After an import, the export is kept beside the database (`strava_exports/`, the latest per rider, left out of backups). The Import page offers **Import again** and **Delete**, and says when this version reads exports differently from the one that last read it. A tick box on the upload skips keeping it.

### Fixed
- **Saved secrets were in the Settings page's source.** The page carried the Garmin password, the OpenAI key and the MQTT password in hidden fields, and filled the password and key boxes with the saved values. They're gone: the boxes are empty, and leaving one blank keeps what's saved. Saving Settings no longer changes the Garmin email or password.
- **Start-up repairs replaced Strava's moving times.** The moving-time repairs now leave alone a moving time that is still the one a Strava export gave. On an install that was already hit, importing the export again offers Strava's figures back on the Import page.
- **Backups could hold the Garmin password** (an install from before this version that hasn't synced since): the backup zip leaves it out.

## [0.7.12-beta] - 2026-10-20

Migration, at the first start: `Settings` gains `mmDistancesDone` and `stravaManualDone`, and there's a new `ImportProblem` table. On a database with activities from older Strava imports, two one-off repairs run (below; seconds, listed on the Tasks page). A brand-new install now starts with every one-off repair already done. Importing an export or a zip again reads every file once more, because how files are read has changed. No Android or iOS change.

**Upgrading from the original Headwind (lordmaa/headwind) works.** Found upgrading a friend's 0.5.3-beta database (three riders, 3,831 activities), and checked against a fresh import of the same athlete's Strava export.

### Changed
- **Duplicates come out the same however the activities arrived.** When two copies of a ride score the same, the longer one is kept, then the one with the more detailed track, then the one uploaded first. Before, it was whichever had been saved first, so an upgraded database and a fresh import could keep different copies.
- **Taking an import's figures can bring back a ride set aside as a duplicate.** When you use an import's times or distance on the Import page, the copies set aside behind that activity are checked again, and any that is no longer the same ride comes back as its own activity. A ride whose device was left running (trimmed on Strava, but not in the file) had held the next ride inside it. Copies you set aside yourself stay set aside.
- **A manual entry is never taken for a recording.** A Strava activity typed in by hand (no file in the export) is a top-up for distance the device missed, so it is never the "whole ride" a recording is a piece of: a 2.5 km entry "lasting" 15 hours had swallowed that evening's 24 km ride. Importing the export again brings back a manual entry set aside wrongly. A database from an older import is repaired at the first start (below).
- **When a file's climb can't be real, a Strava export takes Strava's**, and drops the file's altitude so no profile or segment climb is read from it. Flagged rides from a Strava export offer "Use Strava's climb" on the dashboard.
- **Strava's "Water Sport" is on the water**: no climb in totals or lists, and no stops cut from its moving time. The sport picker offers every sport.
- **The import summary says what it couldn't do**: copies set aside as duplicates (with links), files it couldn't read (also kept on the Import page), and photos missing from Strava's zip.

### Fixed
- **Distances 1,000 times too long from Strava imports.** `activities.csv` has two "Distance" columns, km then metres, and older imports read the metres as km for activities with no track (a manual entry, or a file that couldn't be read): a 46 km ride saved as 45,970 km. The original Headwind's own repair only covered walks, runs and hikes over 500 km. A one-off repair divides every activity averaging over 144 km/h by 1,000, unless its own track agrees with the distance, and works out its average speed again.
- **Manual entries from older Strava imports weren't marked.** A one-off repair marks a Strava activity with no track, a distance, one duration for moving and elapsed time, and not a virtual ride, as typed in, and brings back any set aside behind a ride it isn't a copy of. On two real exports it found every manual entry with a distance and nothing else. If it ever guesses wrong, importing the activity's file clears the mark.
- **Start-up failed on a database with more than one rider**, once: working out best times again compared a time with "none" when two riders had a record at the same distance.
- **Activity files the import gave up on are read**: a FIT named `.bin` that ends without its checksum, a FIT saved as an escaped string, a recording from Strava's own app (`.json`), and GPX files with an id in `<number>` and no track segment. These had come in from `activities.csv` alone, with no track.
- **A new install ran every one-off repair at its second start**, against the first import, which needed none of them. Two of them replaced the moving times a Strava export had just given. Importing the export again offers Strava's back on the Import page.

## [0.7.11-beta] - 2026-10-20

Migration, at the first start: `Settings` gains `localZoneFixDone`, and a one-off repair runs (below; a few seconds on a few thousand activities, listed on the Tasks page). New dependency: `tzfpy` (an offline time-zone lookup, about 3 MB). Importing an export or a zip again reads every file once more, because how files are read has changed. No Android or iOS change.

### Changed
- **An activity's local time is the time where it happened.** Every import used to give it the clock of the home time zone, so a run in Sydney or a ski day in the Alps showed UK time. Now the time zone comes from where the activity started: Strava exports, files, the phone app, and the Garmin sync. Zwift and other virtual rides stay on the home clock, and so does anything with no position or typed in by hand. The start-up repair moves the local time of the activities you already have. Their weather is looked up again for the right hour (a few at every sync, or all at once with Settings → Weather), unless you picked the weather yourself or a named storm claimed it.
- **A piece of a ride is a duplicate of it.** A phone app paired with a speed sensor recorded bits of rides (no GPS, 0 m or only the wheel's distance). A ride that starts during another one, has at least half of itself inside it (the app often ran on for a few minutes after the ride's own device was stopped) and lasts at most half as long now pairs with it. When both have GPS tracks they must be in the same place at the same moments. The whole ride is kept if the piece has no GPS or is well short of its distance. Otherwise the better recording wins, as for any duplicate.
- **A watch's indoor ride and its Zwift copy are one ride.** Each makes up its own distance (Zwift's was 15–25% more than the watch's), so two virtual rides now pair when they start within 10 minutes of each other and last within 20% as long, whatever distances they give. The Zwift (or other app) recording, the one with the route, is always kept over the watch's, unless it has no distance; the bike moves to it. A Zwift ride inside a longer watch session (a warm-up, then a race) is kept too, and the watch session is set aside.
- **Setting a copy aside keeps its shoes too**, as it already kept the bike. Copies set aside under one that is itself set aside later now follow it to the activity kept, so their Strava bike or shoes still reach it.
- **A copy with elevation ranks a little higher** when picking which of two copies to keep.

### Fixed
- **Garmin activities without a time zone were an hour early all summer, and kept twice.** For old uploads and phone-app activities, Garmin gives the UTC time as the local time too. Headwind read that as UK time, so in summer the Garmin copy sat an hour before its Strava copy, both were kept, and the Garmin one counted as a ride with no bike. Those times now count as UTC, in the sync and in the start-up repair. The repair then checks every activity for duplicates again (pairs that came in before the duplicate check, or by a path that missed it, were never compared), sets the weaker copy aside, and puts the Strava bikes and shoes on what has none.
- **RunKeeper files from 2011–2013 had the wrong hour.** Their timestamps are whole hours out (a different amount per file). The real start is in the track's name ("Running 7/26/11 6:20 pm"), and the import now uses it. Copies already saved with the wrong time (Strava's, which came from the same file, or a Garmin re-upload of it) move to the right time when you import the export again, and then meet the copies that had it right.
- **Importing an export again could bring back a copy set aside as a duplicate**, and with it undo a "use the other recording" choice. A copy set aside or thrown away now stays that way. Its photos and commute tick go on the activity kept in its place.

## [0.7.10-beta] - 2026-10-20

Migration, at the first start: a new `ImportSeen` table. No Android or iOS change.

### Changed
- **Importing the same export again is quick.** Reading the files is nearly all of an import's time (half a second for a FIT file), so Headwind now remembers each file it imported, by the zip's own checksum, its row in `activities.csv`, and the version of the code that reads files. Next time, an activity whose file and row are the same, read by the same code, isn't read again: on the test data, 200 activities went from 38 s to under a tenth of a second. Photos, commute ticks and shoes are still added. A release that changes how files are read (as 0.7.9-beta did, for laps) reads every file again by itself, so importing the same zip after an upgrade still picks up what's new. The first import after this upgrade reads everything once, as before. Zips of activity files get the same, by each file's contents.

### Fixed
- **A file of any sport but a ride, run, swim, walk or hike came in as a ride** when uploaded on its own or in a zip of files: a ski day, a paddle, a windsurf, yoga. Now the file's own sport is used, as the Garmin sync reads Garmin's: a FIT file's indoor and e-bike rides keep what they are, a Strava GPX of an e-MTB ride is an e-bike ride, and a sport Headwind doesn't know is Other, never a ride. A Strava export import was never affected (it takes the sport from activities.csv). Activities uploaded as files before keep their sport; change it on the activity page.

## [0.7.9-beta] - 2026-10-19

Migration, at the first start: `Activity` gains `laps` and `kitId` (so it is rebuilt once with the GPS streams last, as in 0.7.6-beta: a few seconds on a few thousand activities), and there are new tables `Kit`, `KitDefault`, `KitAlert` and `StravaKit`. No Android or iOS change.

**A page for every sport, shoes, and all your activities in one list.**

### Added
- **Activities in the sidebar.** One list of every activity, rides and the rest together, newest first, with the dashboard's search, sport filter and Select bar. The dashboard's "View all" goes there.
- **Activity pages that fit the sport.**
  - Runs, walks and hikes: pace instead of speed, a pace chart, splits per mile or km (moving time, climb and heart rate for each, the fastest marked), cadence in steps a minute.
  - Swims: pace per 100 m. A pool swim recorded on a watch shows its sets (the lengths between rests, with stroke, pace, strokes a length, SWOLF and the rest after), the pool length and an average SWOLF. An open-water swim gets splits per 100 m.
  - Downhill ski and snowboard days: each run (vertical, distance, moving time, average and top speed), with time skiing against time going up, and vertical descent instead of the lifts' climb.
  - Paddles, surfs, sails and the rest on the water: no climb (the GPS bobbing about).
  - Yoga, weights and anything else with no distance: no distance, speed or climb cards.
  - The laps your device recorded, for any sport, when there are two or more.
  - A ride, or anything else, with no speed stream (a GPX from Strava) gets a speed chart worked out from its track.
  - Notes on every activity, not only rides. Prev and Next go through the same sport (the run before this one).
- **Laps and pool lengths are read from FIT files.** For activities imported before, import the file or your Strava export again: they're filled in without asking.
- **Shoes and other gear.** Gear has a "Shoes and other gear" section beside the bikes: shoes, wetsuits, skis, boards, boats. Each has its distance and time (added up from its activities), a replace-at distance (700 km to start with for shoes) with a nudge at 90%, 100% and 125% in the same alerts as bike parts, and can be the default for a sport: a new run, walk or hike lands on its default pair. Retire a pair to keep its history. Pick the gear on an activity's page, or for many at once with "Gear…" in the Select bar.
- **Shoes from a Strava export.** Importing your export makes an item for each pair your walks, runs and hikes name, puts those activities on it, makes shoes.csv's default sports their defaults, and brings in pairs last worn over a year ago as retired.

### Changed
- A ride's Distance card no longer shows a pace underneath.

### Fixed
- **Rides that no longer look wrong come off the list.** A start-up repair that put a ride right (a moving time from the track, a top speed from the GPS) left the "looks wrong" flag set before it; every flagged ride is checked again after the repairs, and those cleared are listed on the Tasks page.

## [0.7.8-beta] - 2026-10-19

No migration, and no Android or iOS change.

### Fixed
- **A paused recording was taken for a crop.** Strava leaves paused time (a bike park's uplifts, a device stopped mid-ride) out of its elapsed time, so 0.7.7-beta's Strava export import offered to cut such a ride down to part of itself: a BPW day from 30.5 km to 22.9. Now a ride is only cut when that brings its track to Strava's distance, and more so than leaving out the track's jumps across the pauses does; a later start on Strava is always a crop. If you imported your Strava export again on 0.7.7-beta and haven't yet applied the differences on the Import page, import it again before you do.

## [0.7.7-beta] - 2026-10-19

Migration, at the first start: a new `SportEffort` table replaces `RunEffort` (a cache: every run is worked out again), `TaskLog` gains `logId`, and `Settings` gains `segmentMatchFixDone`, `movingTimeFixDone`, `sportEffortsDone`, `movingTimePausedDone`, `bestEffortsCleanDone` and `sensorTopSpeedDone`, one for each start-up repair below. The repairs run once and are listed on the Tasks page; on a database of 3,400 activities they took about 25 seconds in all. No Android or iOS change.

**Every sport in the stats, and figures that match Strava's.** Runs and swims get best times, badges and Home Assistant sensors of their own. Moving times that counted every stop, best times from GPS jumps or a faulty speed sensor, and segment times that couldn't be right are put right. A Strava export import now takes Strava's own distance, moving time and crops.

### Added
- **Run and swim best times.** 1 km to the marathon for runs (trail and virtual runs too), 100 m to 3.8 km for swims, on the Data page and your profile beside the ride ones. They're worked out on import, and once at the first start for everything already saved.
- **Records by sport** on the Data page: each sport's longest, longest time, most climbing and fastest, all time or by year.
- **Badges for every sport:** Running, Walking & Hiking, Swimming, Other Sports and All Sports (two kinds of training in a day, a triathlon day, 100 to 5,000 hours). Each category shows once you've done that sport.
- **Home Assistant sensors for every sport:** total activities and training time, this week's activities, time, calories and distance (rides, on foot and swims apart), and your last activity of any sport. `nutrition_training_weekly` holds 12 weeks of it for a chart. The ride sensors are unchanged.
- **Logs.** Headwind keeps a log file (`logs/headwind.log` beside the database, `/data/logs` in Docker), set with `LOG_LEVEL`. The Tasks page shows it, with a filter and a search, and every line carries the id of the request or background run it came from. An error page quotes its id. **Tasks → Download diagnostics** zips the logs with the version and settings, secrets left out.
- **A segment can be switched between ride and on foot** from its own page.

### Changed
- **Strava export import uses Strava's own figures.** Distance and moving time come from the export's `activities.csv`, not the file: they carry the "correct distance" and crops you made on Strava, and a ski day's distance without the lifts. **A ride cropped on Strava is cropped here too:** the track is cut to the part Strava kept, and the climb and top speed are Strava's. To bring activities you've already imported into line, import the export again: the differences wait on the Import page ("Track" for a crop), where "Use the import for all" applies them.
- **Moving time without the stops.** A device with auto-pause off counted every stop as moving, so a bike park day came in at 7 hours instead of 2. FIT and TCX imports now take the moving time from the track when the device's is well over it, as Strava does, and activities already saved are put right once (on the test data: 934 activities, 5,009 hours in all down to 4,284, against Strava's 4,304). Not swims, surfs and paddles, where slow swimming or waiting for a wave looks stopped. Average speeds go up to match.
- **Best times leave out what can't be real:** a stretch where the device's distance ran far ahead of the GPS (a speed sensor gone wrong), or faster than 108 km/h on a bike, 10 m/s on foot or 2.5 m/s in the water. Every best time is worked out again once.
- **Segment matching** no longer gives impossible times: loops and short segments are timed properly, a road beside a trail no longer counts as the trail, and efforts over a sane speed are dropped. Every segment is matched again once, so segment PRs and leaderboard places can move.
- The Ride Count badges say "rides", which is what they count.

### Fixed
- **A ski run, a walk or a run could be a ride's best time.** Ride achievements and your profile's Best Efforts counted every sport with a track; they count rides only now.
- **A faulty speed sensor's top speed.** Where the device's distance ran far ahead of the GPS, the top speed is now no more than the GPS shows (one ride: 107.5 km/h down to 49).
- **Tracks whose GPS and times were out of step** (a device that writes records before its first fix) are lined up again, and importing the file again repairs one that can't be.
- **A Garmin that went flat could give a moving time of seconds** for a whole ride (2,766 mph); it's taken from the track now.

## [0.7.6-beta] - 2026-10-19

Migration, at the first start: `Activity` gains `srcUpdatedAt` (so it is rebuilt once more with the GPS streams last, as in 0.7.5-beta: a few seconds on a few thousand activities), `Segment` gains `matchPending`, `Settings` gains `garminSweepAt`, and there is a new `GarminFailure` table. A new trigger, `Activity_touch`, moves an activity's `updatedAt` on whenever something a friend can see changes. No Android or iOS change. Friends on 0.7.5-beta or older still sync both ways, the old way (below).

**Friend sync and the Garmin sync do far less work.** A friend sync with nothing new used to match every one of your activities against every segment the friend shares, on every sync: 11 to 15 minutes each half hour for a friend with 24 segments and 1,300 activities. It now takes no time at all. The Garmin sync used to make about 100 calls to Garmin every half hour; most runs now make a handful.

### Added
- **Friends see every sport.** The friend feed shares all of a rider's activities (rides, runs, walks, swims and the rest) with their step counts, not just rides. The token's "Rides" choice is now "Activities". A friend's run races on their foot segments. A friend on this version fetches the runs and walks they're missing at their next sync; one on an older version gets those that started since its last sync.
- **Garmin activities typed into Garmin Connect** come in from Garmin's activity list (distance, times, climb, heart rate, power, calories), and an activity uploaded to Garmin as a GPX or TCX file is read with its track. Both used to be skipped.
- **Tasks: "Garmin activities not imported"** lists the activities the Garmin sync gave up on and why, with a Try again button.

### Changed
- **Friend sync fetches only what is new or changed.** The friend's instance sends a list of every activity it shares with when each last changed, and only the ones missing here or changed there are fetched, 100 at a time. A friend's segment is matched against your history only when it is new or has moved, and then only against the activities that pass near it. PRs are picked again only on the segments that changed.
- **The Garmin sync reads only the health days that can have changed.** It checks when the watch last uploaded: no upload since the last sync, no days read; otherwise the days since the upload before. All of the last 14 days are still read once a day. It logs in once per run instead of up to four times, and backfills a ride's missing heart rate only after a new upload. A run where Garmin answers none of the calls counts as failed, so those days are read again.
- **A Garmin activity that keeps failing is given up on.** A failed download or save is tried again after 25 minutes, then 1¾, 7 and 27 hours; a file that won't parse is tried once more. One given up on no longer holds the sync back or gets downloaded on every run, and is tried once more after each Headwind update. `services/garmin_failures.py`.

### Fixed
- **A friend's late upload never arrived.** Friend sync asked for activities that started after the day of the last sync, so one recorded earlier and uploaded later was missed for good.
- **Edits and deletions never reached friends.** A renamed, re-typed or deleted activity now changes or goes on their instance at their next sync, and so do activities that a narrowed token no longer shares. Revoking a token still leaves what they already have.
- **An interrupted friend sync lost activities.** A sync that broke part way still counted as done, and the older activities it hadn't reached were never asked for again. It only counts as done once everything has arrived, and segments and activities stored by a sync that stopped before matching them are matched next time.
- **A Garmin activity that reached Garmin late could be missed**, when a newer one from another device had already moved the sync on. The sync looks through the 100 newest activities each time, which it already downloads.
- **A moved friend segment kept its old efforts.** It is now matched again from scratch, against every rider's activities.

`routes/friends.py`, `services/garmin.py`, `services/garmin_failures.py`, `services/tasks.py`, `routes/tasks.py`, `app.py`, `database.py`, `templates/friends.html`, `tests/test_friend_sync_segments.py`, `tests/test_garmin_sync.py`.

## [0.7.5-beta] - 2026-10-18

Migration, at the first start: `Activity` (and `GarminDaily`) are rebuilt once with the GPS streams and raw data as their last columns (below). On a big database this takes a while, in batches, and a start that's stopped or times out carries on where it left off; on a Pi with years of history it can take more than one start. Afterwards each activity's track summary for the heatmap and segment matching (`ActivityTrack`) is made in the background. New: `Activity.commute`, and the `ActivityPhoto`, `ActivityTrack`, `DataVersion`, `StravaBike` and `StravaGear` tables; indexes on `SegmentEffort(activityId)`, `FoodLog(riderId, logDate)` and `HydrationLog(riderId, logDate)`. Photos are kept in `rideimg/` beside the database, and backups carry them. No Android change; the iPhone app's sport and bike choice (on the `ios-app` branch) needs this version.

**Much faster pages on a large history.** SQLite reads a row's columns in order, so reading anything stored after an activity's GPS streams (its bike, weather, source…) read the whole track: the badges did that about 80 times for every ride page. Measured on a synthetic 1.4 GB history: ride page 10.4 s → 0.02 s, rider page 10.4 s → 0.007 s, heatmap data 8.9 s → 0.006 s, Analytics 0.86 s → 0.035 s, the dashboard 3.4 MB of HTML → 92 KB, a new segment 36 s → 1–3 s and a full segment rescan 771 s → 24 s, with the same efforts, PRs and heatmap tracks as before.

### Added
- **TCX import.** `.tcx` and `.tcx.gz` files from older Garmins, TrainerRoad and Strava exports are read: as a single file, in a zip, or inside a Strava export, whose TCX rides used to arrive with no track (no map, heatmap, charts, best efforts or segments). Distance, time, calories and maxima come from the device's laps; heart rate, cadence, speed and power from the track. Checked against 465 real files. A file a Strava import can't read is now logged rather than passed over. `services/parser.parse_tcx`, `tests/test_tcx.py`.
- **Bikes from a Strava export.** The import records which bike rode each ride, for new and already saved rides, and a ride that names a Strava bike no longer gets the default bike. **Gear → Strava bikes** matches each Strava bike to one of yours, adds it as a new bike or leaves it out; a bike with the same name is matched straight away, and matches are remembered for the next export. `services/strava_gear.py`, `templates/gear_strava.html`, `tests/test_strava_gear.py`.
- **Photos, commutes and segments from a Strava export** (import it again to fill in rides already saved). Photos are saved as upright JPEGs with no EXIF, at up to 1600 px plus a thumbnail, never twice. The commute tick comes in too, but never re-ticks a ride you unticked. When asked, the segments you made on Strava are added, each cut from a ride along it. `services/photos.py`, `segments.import_strava`, `tests/test_strava_extras.py`.
- **Add photos to any activity** from its page (up to 20 at once). Off in the demo.
- **Commutes.** A Commute tick box on every activity, "Commute…" in the bulk-edit bar, and a "Commutes / Not commutes" picker beside the sport filter on the dashboard and Analytics.
- **Phone API for the iPhone app's sport and bike choice.** `/api/v1/ping` lists the rider's bikes that aren't archived (id, name, kind, which is the default). `POST /api/v1/rides` takes an optional `bike_id`: the ride goes on that bike instead of the default, and one that isn't the rider's or is archived falls back to the default rather than refusing the ride. `POST /api/v1/rides/ride/<id>/bike` (`{bike_id: id or null}`) changes a ride's bike, picking its PRs again when it moves between a pedal bike and an e-bike. A GPX of type `ebike` imports as an e-bike ride. `POST /api/v1/workouts` takes `source=ios`, so walks from the iPhone aren't labelled Android. Also `commute` in the ride detail and `POST /api/v1/rides/<kind>/<id>/commute`. `tests/test_phone_sport_bike.py`.

### Changed
- The dashboard's history draws only the open month; other months load when opened.
- The badges are worked out once and kept until a ride, segment, effort or bike changes.
- The heatmap serves track summaries made once in the background, instead of sampling every track on each load.
- Segment matching only reads tracks that pass near both ends of a segment, and parses each track once.

### Fixed
- **A Strava segment could miss the ride it was made on.** Its shape was cut from the shortest stretch from near its start to near its end; on a ride that first skirted both ends on a shorter line, that was the wrong shape. The pass closest to both ends is taken now.

## [0.7.4-beta] - 2026-10-18

Migration, at the first start: 0.7.3's e-bike segments become ride segments (`Segment.sport` is `ride` or `foot` again), and ride segment PRs are picked again (below). `Settings` gains `segmentBikesMergedDone`; the `SegActivity` view gains `bikeId`. No Android or iOS change. A friend on 0.7.3 who sends e-bike segments has them saved as ride segments.

**Ride segment PRs can change.** Pedal and e-bike rides now share the ride segments, and each rider keeps two PRs on each: one pedal, one e-bike. At the first start, pedal rides are matched against the segments that were e-bike segments, e-bike rides against the ones that were always ride segments, and every ride segment's PRs are picked again. So e-bike rides appear on pedal riders' segments (and the other way round), a segment can show a pedal PR and an e-bike PR for the same rider, and the E-Bike Segments badges count every ride segment. The Tasks page says how many segments merged, how many efforts were found and how many PRs changed.

### Changed
- **Bike and e-bike rides share segments.** The Segments page has two tabs again, Ride and On foot, and a segment made on an e-bike ride is a ride segment. An e-bike ride still never takes a pedal PR: pedal and e-bike PRs are kept apart.
- **Ride leaderboards filter All / Bike / E-bike.** On the Segments list the filter sets the KOM, the best time, the effort count and the PR date. On a segment's page it sets the leaderboard, the PR and average figures and the time trend, with the number of efforts of each kind on the buttons. E-bike efforts carry ⚡ in the "All" leaderboard. Bookmarks to the old e-bike tab (`/segments?sport=eride`) open the Ride tab filtered to e-bikes.
- **The E-Bike Segments badges count e-bike efforts on the ride segments**, and "King of the E-Road" means holding the e-bike PR on every ride segment. The Segments badges still count pedal efforts only.
- **Comparisons stay within the kind of bike.** A ride's "faster / slower than last time" on its segments, and Home Assistant's best time, rank and tries for the last ride, compare e-bike rides with e-bike efforts and pedal rides with pedal ones.

`services/sports.py` (`segment_family`, `segment_class`, `class_of`, `ebike_sql`, `class_sql`), `services/segments.py` (`_refresh_prs`, `reclassed`, `merge_bikes`), `services/gear.py`, `services/convert.py`, `services/mqtt._ride_route_payloads`, `routes/segments.py`, `routes/rides.detail`, `routes/riders._compute_badges`, `routes/friends.py`, `database.py`, `templates/segments.html`, `templates/segment.html`, `tests/test_segment_families.py`, `tests/test_segments_close.py`.

**The dashboard's headline numbers change.** They used to count rides only. They now count every sport, so with walks, runs or swims in the history the top row shows time, calories and climbing, and each kind's distance sits underneath on its own. "Only rides" gives the old numbers back.

### Added
- **A sport filter on the dashboard and the Analytics (Data) page.** The sport chips that 0.7.1 put on the dashboard list now sit at the top of both pages and set everything: the totals, the Performance chart, the activity history and every chart on the Data page. Every sport is in to start with; untick one to leave it out, or use "Only rides", "Only on foot" or "Only swims". The dashboard's links keep the choice: to the Data page, from the week bars, and the month and year "List" links. Old links with `?sport=Run` still work.
- **No more mixed distances.** Distances only add up within a kind: rides (indoor and e-bike too), on foot (walks, runs and hikes), swims, and each other sport on its own. When the sports left in are of several kinds, the dashboard shows time, calories and climbing, and each kind's distance on its own (each opens that kind alone). The Performance chart's bars stack by kind for time, calories and climbing. On the Data page, monthly, year-on-year and the heatmap count hours or minutes, and the histogram groups by duration. The history tree shows time instead of distance.
- **Speed for rides, pace on foot and per 100 m for swims** in the dashboard's lists and on both pages' charts. A pace chart puts faster at the top. The Performance chart's Speed tab becomes Pace on foot and in the water, and a walk or run saved without an average speed gets one from its distance and moving time.
- **Charts that fit the sport.** On foot, the Data page's histogram goes 0–2 mi up to marathon length (0–3 km to 42+ km); for swims, 0–500 m up to 5+ km. The heatmap's colour steps are smaller on foot and in the water.

### Changed
- **The records and weather sections say "rides only"** when other sports are in the filter, and leave out the rides you untick. They are hidden when no ride is left in. Personal records per sport come later.
- The Data page is called Analytics, as in the menu, and its charts say "per activity" rather than "per ride".

### Fixed
- **The Data page drew no charts at all until "Compute Achievements" had been run.** The achievements script stopped the page's scripts when there were no efforts yet.

The phone app's weekly bars stay rides only. `services/sport_filter.py` (new), `services/sports.py` (`stat_group`, `rate_style`), `services/units.py` (`fmt_swim_pace`, `fmt_rate`), `services/weather.fog_candidates`, `routes/dashboard.py`, `routes/data.py`, `templates/_sport_filter.html` (new), `templates/dashboard.html`, `templates/data.html`, `templates/base.html` (`UNITS.toPace`), `tests/test_sport_filter.py`.

## [0.7.3-beta] - 2026-10-18

Migration, at the first start: run segments become **foot** segments (`Segment.sport` is now `ride`, `eride` or `foot`), and segment efforts and PRs are sorted out once (below). `Settings` gains `segmentFamiliesDone`. No Android or iOS change. A friend still on 0.7.2 or older keeps working: they see your foot segments as run segments and your e-bike segments as ride segments.

**Segment PRs and leaderboard places can move.** At the first start, efforts on ride segments by walks, hikes, e-bike rides, indoor rides, swims and anything else that isn't a pedal ride are removed. Walks, runs and hikes are matched against the foot segments, and every segment's PRs are picked again. So a pedal ride can take back a PR an e-bike ride or a walk held, a walk or hike can appear on a foot segment's leaderboard, and segment badges can change. The Tasks page says how many efforts moved and how many PRs changed.

### Added
- **Segments by sport: ride, e-bike and on foot.** The Segments page has three tabs, and an activity is only matched against segments of its own kind. Walks, runs and hikes share foot segments: one leaderboard and one PR each, with the sport's icon beside every effort, and pace instead of speed. Indoor rides, swims, paddles, skis and the rest have no segments, so their pages don't offer "Create Segment". A segment made on an activity takes that activity's kind, so one made on a walk is a foot segment.
- **E-bike rides are told apart from pedal rides.** A ride is an e-bike ride when Strava says so ("E-Bike Ride", "E-Mountain Bike Ride"), when Garmin says so, or when it was ridden on a bike whose kind is E-bike (Gear). Changing a ride's bike, a bike's kind, or deleting an e-bike moves those rides between ride and e-bike segments straight away. So does changing the type between Ride, Indoor ride and the new E-bike ride.
- **Garmin e-bike rides keep their type.** The Garmin sync used to save `e_bike_mountain` and `e_bike_fitness` as a plain Ride; they are now E-bike rides. For rides already synced, run the check on **Garmin → Activity types**: it now proposes E-bike ride for them.
- **Segment badges for each kind.** E-bike segments and segments on foot get their own sets beside the existing Segments badges: effort counts, first PR, holding every PR, repeats, and speed (25 to 40 mph on an e-bike) or pace (10:00 to 6:00 /mi on foot). The existing Segments badges now count pedal rides on ride segments only. More badges also means the trophy-case totals (the AI coach, the Home Assistant badge sensor) go up.

### Fixed
- **"King of the Road" couldn't be earned once a run segment existed.** It compared the PRs you hold with every segment, run segments included. Each set now counts its own segments.
- **E-bike rides took pedal PRs and topped pedal leaderboards.**
- **Walks and hikes counted as rides on segments.** A full rescan matched them against ride segments, and walks never matched run segments. They now go on foot segments only. The slowest speed that counts on foot is lower (0.5 m/s, was 1.2), so walks and steep hikes match.
- **"Create Segment" on a walk made a ride segment.**
- **Home Assistant's ride segments list follows the last ride's kind**, so after an e-bike ride it lists the e-bike segments.

`services/sports.py` (`segment_family`, `family_of`, `FAMILIES`, `label`), `services/segments.py` (`rescan_activity`, `regroup`), `services/gear.py`, `services/garmin.garmin_sport`, `services/convert.py`, `services/workouts.refresh_derived`, `routes/segments.py`, `routes/riders._compute_badges`, `routes/friends.py`, `tests/test_segment_families.py`, `tests/test_run_segments.py`.

## [0.7.2-beta] - 2026-10-18

No migration. No Android or iOS change.

### Fixed
- **0.7.1-beta wouldn't start on a large install ("database or disk is full").** The one-time name check for merged activities sorted every copy set aside, each a whole activity with its GPS track, in a single query. SQLite's temporary space for that sort filled the disk, and the start failed again on every restart. The check now sorts only the ids and reads one copy at a time. Nothing had been changed when it failed, so it simply runs on the next start. `services/duplicates.recover_names`, `tests/test_duplicates.py`.

## [0.7.1-beta] - 2026-10-18

Migration, at the first start: the `Workout` view and the `WorkoutPreMerge` table that 0.7.0 kept are dropped. Nothing reads them any more, and the way back is still the whole-database copy `bike.db.pre-0.7.0` made by 0.7.0. An install coming straight from 0.6 is merged as before, then drops its old `Workout` table in the same step as the copy, so there is no `WorkoutPreMerge` (the `.pre-0.7.0` copy is still made first). `Settings` gains `dupNameFixDone`, for the one-time name check below. No Android or iOS change: the phone API keeps its shape.

This finishes **One table for every activity** (release 2 in `docs/ONE-TABLE-PLAN.md`). It is mostly cleanup: nothing adds a rides half and a workouts half any more, and every "is this a ride?" question goes to `services/sports.py`.

### Fixed
- **A merged activity lost the name you gave it.** When two recordings of one activity were merged, the one kept took its own name even when that was made up (Garmin's "London Cycling") and the copy set aside had a name someone chose ("Box Hill loop"). A chosen name now wins over a made-up one (Strava's "Morning Ride", Garmin's place and sport, "Imported Ride"), and any name wins over none; between two chosen or two made-up names the kept recording's stays. At the first start, activities merged before this get the chosen name back from the copy set aside, once. A name you've given since the merge stays, and friends' activities are left alone. The count is on the Tasks page. `services/duplicates.recover_names`, `tests/test_duplicates.py`.
- **Re-sending a phone walk that had since been changed to a ride failed.** The upload looked for the walk among the workouts only, didn't find it, and tried to save it again under the same id. It now finds the activity, whatever its sport, and answers "exists".
- **Changing a workout to a ride on the Workouts page showed an error page.** The change was saved, but the page that should then open the ride failed. It opens the ride now.
- **Opening an activity in the phone app after its type changed on the web said "not found".** The app asks for `/rides/ride/<id>` or `/rides/workout/<id>`, and the server only looked in the half the app named. The server now uses the activity's own sport, so a stale kind still opens it, changes its type and deletes it. The answer carries the real kind.
- **GPX files from Avinox e-bikes wouldn't import.** They use an `avinox:` tag for the ride totals without declaring it, which isn't valid XML, so the whole file was rejected ("unbound prefix"). The importer now declares any such tag name itself before reading the file. Valid files are read exactly as before. (`services/parser._declare_missing_prefixes`, `tests/test_gpx_namespaces.py`)

### Changed
- **Choosing sports on the dashboard's Activities list.** The "Leave out" column is now one wrapping row of sport chips, all ticked to start with: untick one to drop it from the list ("Tick all" puts them back). The URL still lists only the sports left out, so a sport you take up later shows without changing a bookmark. The old column stacked every sport down the middle of the page.
- **One definition of a ride.** The gear module, the activity-type change, the typed-in activity form, the Garmin sync, the ride sanity checks, AI kudos, the ride page and the AI coach's "Other training" each had their own test of whether a sport is a ride. They now all use `services/sports.is_ride`, the same rule the `Ride` view is built from. In practice this changes nothing, except for an activity with no sport at all: like everywhere else, it now counts as a ride for the bike calendar, the default bike and the "looks wrong" checks, and "Cyclocross"-style sports get AI kudos.
- **The day's calorie burn is one query over every sport** (Nutrition page, the calorie goal, Home Assistant), not rides plus workouts added together. The figures are the same.
- **The phone's totals and history are one query each.** The `kind` in the answers comes from the sport, not from which half a row was found in.

`services/sports.py` (`RIDES`, `ON_FOOT`, `WORKOUTS`, `SPORTS`, `kind`, `kind_of`, `KIND_SQL`), `services/goal_model.activity_calories`, `database._drop_merge_leftovers`, `routes/api_v1.py`, `routes/rides.py`, `services/workouts.py`, `services/bulk.py`, `services/sensors.py`, `services/gear.py`, `tests/test_one_table.py`.

## [0.7.0-beta] - 2026-10-18

Migration, one way: walks, runs, swims and every other workout move into `Activity`, the table rides are in, at the first start. Before anything changes, the whole database is copied to `bike.db.pre-0.7.0` beside it; the old `Workout` table is also kept, untouched, as `WorkoutPreMerge`. 0.6 can't open the merged database, so going back means restoring that copy. `Activity` gains `steps` and `source`; `Ride` and `Workout` become views of it; `Settings` gains `workoutDupCheckDone`. No Android or iOS change: the phone API keeps its shape.

### Added
- **The Activities list on the dashboard shows every sport.** Walks, hikes, swims and the rest sit beside rides and runs, and "Leave out" ticks drop any sport from the list. The choice is kept in the URL, so a list can be bookmarked. A walk with no name of its own gets one ("Afternoon walk"), as on the Workouts page.

### Fixed
- **A Garmin run or walk and its Strava copy were both kept.** Garmin saved it as a workout and the Strava export as a ride, and the duplicate check only compared rides. Every sport is now one table, so the check sees every activity. At start-up each walk, run and other workout is checked once; the weaker copy (normally Strava's) is set aside, not deleted, and the count is on the Tasks page. New ones are checked as they arrive from Garmin, the phone or a typed-in entry. A phone upload of a recording that was set aside gets the kept one back instead of saving it again.
- **Strava walks, runs, swims and gym sessions counted as rides.** A Strava export stored every activity type as a ride, so they added to the ride totals, the Performance chart, the Data page, badges and the Home Assistant sensors. These now read rides only, so **ride totals drop** by whatever those were. They appear on the Workouts page instead, and still count once in the day's calorie burn.
- **Deleting a rider left their workouts behind.** They go with the rider now, with their run best times.
- **The AI coach's "Other training" missed phone and Garmin workouts.** It read only the non-ride activities that had been saved as rides.

### Changed
- **Changing an activity's type keeps its id.** A walk recorded as a ride used to be moved to the other table under a new id (the old id kept as a tombstone, the original Garmin or Strava id in `originId`). It is now the same row with a new sport: what only a ride has (best efforts, ride segments, the bike) goes, calories are estimated again, and links and bookmarks keep working. The phone API still returns the id.

`services/sports.py` (what counts as a ride), `database._merge_workouts`, `services/duplicates.recheck_workouts`, `services/convert.py`, `routes/dashboard.py`, `docs/ONE-TABLE-PLAN.md`, `tests/test_one_table.py`.

## [0.6.6-beta] - 2026-10-18

Migration: one `Settings` column (`awayStartRecheckDone`), added automatically at startup, and a one-time duplicate recheck (below). No Android change.

### Fixed
- **Activities recorded away from your home time zone were kept twice** when Garmin and Strava (or a file) both had them, e.g. a walk in Vancouver with London as home. Garmin gives the local time where the activity happened, and the duplicate check read it in the home time zone. So the Garmin copy sat 8 hours away from its Strava twin and never overlapped it. Matching now uses the UTC start time that every source already stores. At start-up, rides whose two start times disagree this way are checked once more for a twin. The weaker copy (normally the Strava or file one) is set aside, not deleted, and can be swapped back from the ride page. The result is on the Tasks page. The side-by-side view of two recordings lines them up on the same instant too. Runs and walks that Garmin saved as workouts are still not compared with a Strava copy saved as a ride; that needs the two tables merged. `services/duplicates.start_instant`, `services/start_times.recheck_away_starts`, `tests/test_duplicates.py`, `tests/test_start_times.py`, `tests/test_garmin_sync.py`.

## [0.6.5-beta] - 2026-10-18

No migration. No Android change.

### Fixed
- **The default rider picture was a broken image in Docker.** A new rider gets `custard_cream.svg` as their picture until they upload a photo, but the Docker image replaces `static/avatars` with a link to the `/data` volume (so uploaded photos survive upgrades), which also removed the bundled picture. Desktop installs that keep photos in `AVATAR_DIR` had the same problem. The picture now ships in `static/img` and is copied into the avatar folder at startup if it's missing. Uploaded photos were never affected.

## [0.6.4-beta] - 2026-10-18

No migration. No Android change.

### Added
- **Quick date ranges for feed tokens.** When you make or edit a friend's token, "All rides", "Past 6 months", "Past month" and "From today" fill in the dates. The end date is left open, so new rides keep reaching them.

### Changed
- **A tidier Friends page.** Every field has its label above it and the forms line up. Edit opens a row under the token, replacing a popup whose date fields spilled out of it. On a phone, tokens and friends are shown as small cards instead of squashed tables.
- **Placeholder text is dimmed everywhere**, so example text like "e.g. Sam" no longer looks like something already typed. Empty date fields are dimmed too, since Safari shows today's date in them.

### Fixed
- **A friend sync slowed down or broke everything else that saves data.** It held the database's write lock for up to a minute at a time: it saved only every 50 rides, and its segment scans and PR refresh took a long time. Creating a feed token during a sync took about a minute, and other saves could fail with "database is locked". The sync now saves after each ride and each segment, so other saves wait milliseconds. Only one sync per friend runs at once; a second one is refused with "Already syncing" instead of competing with the first. `tests/test_friend_feed.py`.

## [0.6.3-beta] - 2026-10-18

Migration: three `Settings` columns (`timeZone`, `birthDate`, `birthDateGuessed`), added automatically at startup. Existing installs are set to Europe/London so their "today" doesn't move, and an age saved before becomes 1 January of that birth year. `docker-compose.yml` now passes `TZ` through. No Android change: an age sent by an older client is still accepted.

### Added
- **Set your home time zone.** Settings → Display Preferences has a time zone. Leave it blank to use the server's zone (`$TZ`, then `/etc/localtime`). Everything that used to assume Europe/London now reads it, including the MQTT water command, which logged water against the London date. `services/tz.py`, `tests/test_tz_birth_date.py`.

### Changed
- **Date of birth instead of age.** The profile forms ask for a date of birth, so your age goes up on your birthday instead of being up to a year out. If you'd only entered an age before, the forms ask for the full date until you enter it.
- **The ride page links to both Garmin and Strava** when the same ride was imported from each. Before, only the recording kept as the main one got a button. `services/origin.py`.

### Fixed
- **"Fetch history" in Settings → Garmin Connect did nothing.** The range dropdown had the same id as the button's function, and inside the Garmin form the button's click found the dropdown instead of the function, so no request was sent. The dropdown is now `garminHistoryRange`, here and in the setup wizard.

## [0.6.2-beta] - 2026-10-18

Migration: an `originId` column on `Activity` and `Workout`, added automatically at startup. Workouts already changed from rides get theirs filled in once. No Android change.

### Added
- **Open an activity on Garmin or Strava.** A ride or workout that came from the Garmin sync or a Strava export now has a **Garmin ↗** or **Strava ↗** button at the top of its page, which opens it on Garmin Connect or Strava. It still works after you change the activity between a ride and a workout (for example with the activity type check), which gives it a new id: the id it came in with is now kept in `originId`. `services/origin.py`, `tests/test_garmin_sports.py`.

### Fixed
- **The activity type check stopped when you left the page, and never showed on the Tasks page.** "Check with Garmin" ran inside the page request, so the result was lost if you browsed away, and nothing recorded that it was running. It now runs in the background: the Tasks page shows it running, then its result or error, and the Activity types page shows that it's running, updates itself when it's done, and then shows the last result. `routes/garmin.sports_check`, `tests/test_tasks.py`.

## [0.6.1-beta] - 2026-10-18

Migration: a new `FeedToken` table and two `Settings` columns (`claudeKey`, `claudeModel`), added automatically at startup. The old shared feed token moves into the new table. New Python dependency: `anthropic` (included in the Docker image). No Android change.

### Added
- **Claude as an AI provider.** Settings → AI Provider now offers Claude next to OpenAI and Ollama: paste an Anthropic API key and pick Claude Opus 5.5 (the default), Sonnet 5.5 or Haiku 5.5. It does the ride coaching and reads food-diary screenshots, recipe screenshots and meal photos. "Test AI" works with it, and the "add a key" messages now name whichever provider you chose. All AI calls now go through one helper, `services.ai.Chat`, which talks to each provider in its own format. `tests/test_ai_providers.py`.
- **One feed token per friend.** The Friends page used to have a single token for everyone, so you couldn't cut off one person without updating all of them. Now you make a token for each friend and choose what it shares: rides, segments, foods, and optionally only rides between two dates. You can change that later, or revoke one friend's token without affecting anyone else. Each token shows when it was last used. A token is shown once when you make it and only a hash is kept, like phone pairing. If a token stops sharing foods, the friend's copy of your foods is cleared on their next sync. Rides they already pulled stay on their instance. `services/feed_tokens.py`, `tests/test_feed_tokens.py`.

### Changed
- **Your existing feed token keeps working** as one token named "Shared token (everyone, from before per-friend tokens)" that shares everything, so friends already linked keep syncing. Give each of them their own token, have them update it on their Friends page, then revoke the shared one. A new **Token** button on each connected instance lets you paste the new token a friend gives you, keeping their rides (before, the only way was to remove the friend, which deleted their rides). The token is no longer shown on the page, and the Regenerate button is gone. Revoke it and make a new one instead.

## [0.6.0-beta] - 2026-10-18

Migration: new `TaskLog` and `ImportChange` tables, added automatically at startup. No Android change.

### Added
- **Select and edit many activities at once.** "Select" on the dashboard's activity history and search results, the Workouts page and a rider's page. Click rows to pick them (shift-click for a range, All / None), then use the bar at the bottom: delete, change type, set the bike, move to another rider, rename, mark flagged rides as right, or download them as a zip of GPX files. Rides and workouts can be mixed. Each action goes through the same code as a single activity, so deleted rides stay deleted on the next sync and segment PRs are re-picked, and Home Assistant is updated once at the end. `services/bulk.py`, `POST /rides/bulk`, `tests/test_bulk.py`.
- **A Tasks page** (sidebar) showing what Headwind does in the background:
  - the Garmin sync (last run, or the error it keeps failing on), with "Sync now";
  - the Garmin health and weight history, with "Try now" while one waits after a rate limit;
  - friend sync, the Home Assistant / MQTT link, and an import in progress;
  - the start-up repairs an update runs, and what each one changed;
  - the latest runs.

  After an update's repairs have run, every page shows a notice until you open the page. `services/tasks.py`, `routes/tasks.py`, `tests/test_tasks.py`.
- **Re-importing a ride that's already saved repairs it, if you want.** Importing a Strava export, zip or file again used to skip every ride it already had, so one that came in broken stayed broken. Now each one is compared with the saved ride. If they're the same, it's skipped as before. If they differ, it's listed on the Import page with the saved and file values side by side, and you choose: **Use import** (the file's values wherever it has one), **Fill in gaps** (only what the saved ride is missing, e.g. a GPS track), or **Keep saved**, for each ride or all at once. Names, bikes, notes, the activity type and a ride you marked as right are never changed, and best efforts, segments and the sanity check are redone for any ride that changes. `services/reimport.py`, `tests/test_reimport.py`.

### Fixed
- **GPX exports were an hour out all summer.** Track times were the local start time labelled as UTC. They now use the stored UTC start, so an exported ride re-imports on top of its original. `routes/rides.gpx_for`.

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
