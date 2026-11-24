# Changelog

## [Unreleased]

### Added
- **The AI coach covers every sport, not just rides.** Runs, walks, hikes, swims, paddles, kitesurfs, ski days, strength, yoga and the rest get the coaching card on their page, in **Bulk Analysis** and in **Analyse New Activities**. Each is coached in its own terms: a run by pace and cadence in steps a minute, a swim by pace per 100 m, a ride by speed and power as before, and a strength, HIIT or yoga session by time and heart rate, with the coach told not to invent a distance or pace it hasn't got. Climbing is left out on the water and indoors. The personalities talk about the sport you did (Attenborough narrates a runner; Ted Lasso misunderstands swimming), and the default is now **Blunt Training Mate**.
- **The coach compares like with like.** A run's history, its comparable sessions, its monthly progress and its "similar run" comparisons are your other runs (trail and treadmill included), a swim's your swims, and so on; a ride's are your rides, as before. A run or a swim that set a best time over a standard distance (5 km, 400 m, ...) is told so, with the best it beat. Everything else you did in the 30 days before it is listed as other training, so a ride's notes know about the run and the gym session the day before, and a run's about the rides. Strength and yoga sessions are now in that list too.
- **Choose how far back the coach's progress by month goes.** Under **Coaching Goals** on the AI Coach page, **Progress by month** is **The last 6 months**, **The last 12 months**, **Since my comeback on…** a date of your choosing, or **Off**. It was fixed at January 2026 and always called a comeback. An install from before this keeps that until you change it; a new one starts on the last 6 months. The months now end at the activity's own, so an older activity analysed in Bulk Analysis gets the months before it, not the months up to today.
- **The coach follows up on what it said.** It's given its own verdicts on the last three activities of the same sport it analysed, a line each, so it can pick up a heart rate drift or a pacing question it raised last time, and say so if it now reads the trend differently.
- **Choose which sports are analysed as they arrive.** On the AI Coach page, **Analyse New Activities** has a list of sports to tick: **Every sport** (which takes in any you start later), groups such as Cycling and On foot, or single sports like Run, so a daily walk needn't cost an API call each time. If you had **Analyse new rides** on, it stays rides only (Cycling ticked) until you tick more. **Bulk Analysis** has a Sport menu to analyse one sport's history at a time.

### Fixed
- **The coach knows your whole history, not just what it has analysed.** Its history table, comparable sessions, 30-day summary, monthly progress and "similar ride" comparisons were read from the activities it had already analysed, so a rider with hundreds of runs, none analysed yet, got "No previous runs in memory yet". They now come from every earlier activity of the same sport you recorded. **Analyse with history** on an activity's page shows when there are earlier ones, not when something else has been analysed. A ride named "Ride Activity" with no power is no longer left out: that rule hid duplicates, which are now set aside on their own.
- **The 30-day summary's trends were back to front.** "Trending up" meant your distance, speed, power or heart rate had gone down over the 30 days, and the coach often noticed the label didn't match the numbers. It now reads them oldest to newest.
- **The coach no longer compares an activity with ones after it.** Analysing an older activity, in Bulk Analysis say, read your latest rides as its "history" and its 30 days of other training as the 30 days before today. Both now end on the activity's own day.
- **The coach's history is the rider's own.** The 30-day summary and the "similar ride" comparisons could include another rider's or a friend's rides on an instance with more than one.
- **An activity with nothing recorded isn't analysed.** An Apple Health workout with no distance and no moving time is skipped by the analysis of new activities and by Bulk Analysis, which also no longer counts a friend's activities.

### Changed
- **The AI Coach page counts every sport.** "Activities analysed" and "Memories" replace the ride counts. In Working Memory a dot's size is the activity's time and its colour its sport, each month shows its activities, hours and distance, and the speed trend is the rides' alone.

## [0.7.59-beta] - 2026-11-24

### Added
- **A map page on the Apple Watch while recording.** Swipe left past the figures while recording a ride, run, walk, hike or open water swim to see your track so far and where you are, turned the way you're going, with the distance and time (or the distance and pace on foot) over it. The Digital Crown zooms in and out, and the zoom stays as you left it. Timed sessions with no GPS, such as an indoor ride, a pool swim or strength, keep their two pages. With your wrist down or the screen in Always On, the map dims and stops following you until you raise your wrist, to save battery. Apps can't use the offline maps you download in Apple Maps, so away from your phone and any connection the map may be blank, but your track and position still show on it. The recording itself, what's saved and what's uploaded don't change.
- **Maintenance warnings can be turned off for one bike or one item of kit.** Untick **Maintenance warnings** when editing it, for a bike on a turbo trainer or shoes you'll wear out regardless. Its parts, or the item itself, then stay off the Gear page's Needs attention list and the dashboard, and send no notifications or Home Assistant alerts. Its card says "No warnings" instead of Due or Overdue, and its wear still shows on its own page. Before, the only way was to untick notifications on each of a bike's parts, which still left them on the due lists. Ticking it again sends any alert it missed.
- **An activity's charts can be drawn against time as well as distance.** A Distance / Time switch above the charts changes every chart at once, and the page remembers your choice next time. Against time, a stop where your device paused shows as a gap, where against distance it takes no room. The ticks along the bottom now fall on round figures (0, 5, 10 km; or 0:15, 0:30, 0:45), not on whatever point happened to be there (6.68, 13.61). Hovering a chart still marks the spot on the map, and the cursor on the map still shows on every chart, whichever way they're drawn. The tooltip gives both how far and how long at that point.

### Fixed
- **Charts for an activity with no distance are drawn against time.** A pool swim, a yoga or strength session, and a Zwift ride (whose files have no distance along the way) had charts numbered by sample along the bottom. They're now against time, without the switch.
- **A strength, yoga or HIIT session uploaded as a FIT file keeps its sport.** Garmin watches write these as "training" with the kind of session beside it, and Headwind read only the first part, so they came in as Other. Garmin sync wasn't affected.
- **A FIT file from a watch paired with a gym's machine keeps its sport.** An indoor bike comes in as an indoor ride, a treadmill as an indoor run and a rowing machine as a row, rather than Other.
- **Water skiing is no longer a ski day.** It came in as Ski, adding to your snow totals; it's now Other.
- **The Target box on the Goals page is labelled on one line.** "Target (km)" was split over three lines when adding a goal or starting a challenge.
- **Forms with several fields side by side use the card's full width.** Adding a goal put its four boxes in the left half of the card; the same happened on Settings, Activities, Gear and Nutrition wherever a form ended in a full-width row of buttons.

### Removed
- **The phone API's older paths are gone, and upstream's Android app no longer works with this server.** `POST /api/v1/rides` and `POST /api/v1/workouts`, `GET /api/v1/rides`, everything under `/api/v1/rides/<kind>/<id>` (photos, bike, sport, commute, duplicates, delete), and `GET` and `DELETE /api/v1/workouts` now answer 404. So do the old keys: `ride` and `workout` in an upload's reply, `kind` in `POST /api/v1/activities`' reply and in the activity list, `ride_id` when a duplicate is resolved, `rideId` and `rideName` in `/api/v1/perform`, and the ride-only totals in `/api/v1/overview` (`all`, `week`, `month`, `year`, `workouts`, `weekly` and `sports`), which `groups` and `weekly_all` replace. Everything is at `/api/v1/activities` and `/api/v1/activities/<id>`, as the iPhone and Watch app has used since 0.7.47. These paths were kept only for upstream's Android app, which this project doesn't ship and can't update: it can't upload, list or open activities on this server any more. An Android app of this project's own is planned.
- **The Android app download on the Phones page.** It offered upstream's sideloaded APK (`HEADWIND_APK`), which no longer works with this server. `/phones/app` and `/phones/app.apk` are gone.

### Changed
- **The iPhone and Watch app needs Headwind 0.7.47-beta or later.** It no longer knows the older paths: it refuses to pair with an older server, says so at the top of every tab when the one it's paired with is older, and holds its uploads and Apple Health sync until the server is updated. Update the server and the app together: the app installed before this one shows an error on its Overview tab against this server, because the ride totals it read are gone.
- **The About page describes every sport.** It was written when Headwind was a cycling app. It now covers runs, walks, swims and the rest, with the best times each sport has, the trophy case's categories, the Home Assistant sensors as they are, and AI coaching as the rides-only feature it is.
- **An activity with no sport is called "Activity", not "Ride".** It still counts with your rides in totals, segments and the Data page's records, as it always has.
- **Pages say "activity" where they meant any sport.** The Garmin settings (**Activities + health stats**, **Sync Activities**), the dashboard's Sync button, the setup wizard, the backup description, the Strava import's note, the calorie adjustment's note, the steps source note, the duplicate recording pages and their reasons, a segment with no efforts, and the Garmin and friends sync messages in the log. Wording that is about rides (a bike's rides, the riding badges, AI coaching, the ride weather charts, ride segments) still says ride.
- **Headwind points at its own project.** Bug reports and feature requests go to this project's Issues, with a form for each; LICENSE adds this project's copyright line beside the original's; the map tile requests name this project as their contact; and Home Assistant's device model reads Headwind instead of bike-flask (only the label changes, so your entities keep their ids). The README no longer describes upstream's Android app as part of this one.
- **The Roughness map's empty state** no longer sends you to the Android app: it says the map is drawn from a phone's motion sensors, which no current Headwind app records yet.
- **An upload from the phone with no `source`** is marked as the phone's, not the Android app's.
- **The README's AI coaching lines** now say it's for rides; they said every activity.

## [0.7.58-beta] - 2026-11-23

### Changed
- **The heatmap shows every sport, not only rides.** Runs, walks, hikes, swims, paddling, skiing and every other activity with a GPS track are now drawn alongside your rides. Before, "All Sports" meant every kind of ride, and nothing else could be picked. The Sport list now offers each sport you have a track for, the count under the filters says "activities", and the page is called Heatmap instead of Ride Heatmap. Zwift and other virtual runs are left out by default along with virtual rides, as before.

## [0.7.57-beta] - 2026-11-23

### Fixed
- **The Tasks page no longer takes 2 to 3 seconds to open while the heatmap tracks are worked out again.** After updating to 0.7.56, the background work that redraws every track kept the database locked for a second or more at a time. Each time the Tasks page opened, it waited for that lock so it could mark the start-up notice as read. The work now only takes the lock to save its results, and the page writes nothing once the notice has been read. On 3,400 activities the page opened in about 20 ms throughout.
- **Pages no longer wait behind an import, a segment scan or a best-efforts scan to save.** Several kinds of background work kept the database locked while they worked, so anything a page saved meanwhile had to wait. On 3,400 activities:
  - An import asked the weather service about each new activity while it held the lock. It now asks first. A save that waited up to 0.7 s waits at most 0.15 s, and the import takes as long as it did.
  - The best-efforts scan, the best efforts in kilometres and segment matching held the lock while they worked through each batch of 50 activities. They now work a batch out first and lock the database only to save it. A save waited up to 6 seconds during the best-efforts scan and up to 2.5 s during the others. It now waits a millisecond or less.
  - Setting a ride's weather back to automatic asked the weather service while the lock was held. It now asks first.

### Added
- **Progress bars on the Tasks page.** Working out the heatmap tracks again and the best efforts in kilometres after an update now each show as a job with a count and a bar ("1,450 of 3,425 done"). The weather for older activities and an import in progress have bars too. While a bar is moving, the page refreshes every 5 seconds instead of every 20.

### Changed
- **Segment matching and the best-efforts scan run in the background.** Creating a segment, changing its sport, **Rescan all activities** on the Segments page and the best-efforts scan on the Data page now come straight back. On a few thousand activities the page waited up to 25 seconds. The work goes to the background worker, and the Tasks page shows how far it has got, as does the indicator at the top of every page. A new segment's page says its efforts are being found, then shows them when they're ready. During a rescan, every segment keeps its efforts until it has been matched again.
- **Newer libraries.** The image and the Windows app install the AI coach's libraries at their latest versions (anthropic 2.13, openai 3.58), and the image is built with the current releases of Docker's build tools.

## [0.7.56-beta] - 2026-11-23

### Fixed
- **Heatmap tracks follow the roads.** Each track on the heatmap was cut down to about 50 points taken at even intervals through the recording, a point every 360 m on a typical ride and every kilometre or more on a long one, so bends, roundabouts and winding lanes were drawn as straight lines. Tracks now keep every point needed to stay within 10 m of where you went, and a straight road takes only a few. The HD export keeps them within 5 m. The download is about three and a half times the size, about 2 MB compressed for 2,000 activities. Existing activities' tracks are worked out again in the background on the first start after updating, which takes about a minute for a few thousand activities.
- **"Same route" finds more of your repeated routes.** It compared the same cut-down tracks, which often left out an activity's last point, so two rides that finished in the same place could fail the check that they did. It now compares points spread evenly along each route.

### Changed
- **The Docker Compose file installs this project's own image,** `ghcr.io/atombrake/headwind:beta`, now that Headwind is developed separately from the project it started from. The README credits the original.

## [0.7.55-beta] - 2026-11-23

### Fixed
- **Saving a setting no longer waits for Home Assistant.** With MQTT set up, saving Settings, the feature switches or anything else that changes a sensor made the page wait while Headwind worked out every sensor and sent the ones that changed, often 3 to 4 seconds. The update now goes to the background worker and the page comes straight back. Home Assistant gets the change a moment later. The same goes for deleting, restoring and bulk-editing activities, logging food and water, matching Strava bikes, and the phone app's uploads and deletes. Several changes in a row make one update. The worker also keeps one record of what Home Assistant was last sent, so it sends only what changed. Each web process kept its own record and started with an empty one, so its first update after a restart sent all 126 sensors again.

## [0.7.54-beta] - 2026-11-23

### Added
- **Turn off the features you don't use.** A new **Features** section in Settings has a switch for each part of Headwind someone might not want: **Health** (and under it **Nutrition**, **Steps**, **Weight** and **Recovery**, each on its own), **Gear** (and under it **Gear maintenance**), **Segments**, **Routes**, **Heatmap**, **Goals**, **AI coach**, **Friends**, **Live tracking**, **Roughness** and the **Route planner**. A feature turned off leaves the sidebar and the dashboard, its pages say it's turned off in Settings with a link back, and its work in the background stops: the Garmin sync stops reading the daily health figures once Recovery, Steps and Nutrition are all off, and the weigh-ins once Weight and Nutrition are; the part and kit alerts, the AI coach's analysis of new rides, the friends' automatic sync and Home Assistant's water button stop; and its Home Assistant entities are removed. Nothing is deleted, so turning it back on brings everything back. Turning **Health** off turns its four parts off without changing them, so turning it on again brings back the same choices; **Gear** does the same for **Gear maintenance**, which takes away the parts, the service log, kit's replace-at distance and the due list but keeps the bikes and shoes and their distances. Some follow from others: with Steps off the calorie goals count rides only, and the AI coach leaves out recovery, steps and segments when they're off. Each rider has their own switches, and **Save, and start new riders with these** sets what a rider added later starts with. For the apps, `GET /api/v1/ping` lists what's off as `features_off`, the endpoints of a feature that's off answer `403` with `feature_off` naming it, and `/today`, `/overview`, `/perform` and `/sync/nutrition` leave out what's off. The iPhone and Watch apps don't follow the switches yet.
- **Count this week and this month as the past 7 and 28 days, or as calendar weeks and months.** A new choice under **Settings → Display**, kept for each rider. **Past 7 and 28 days** counts today and the 6 or 27 days before it, so on a Monday "this week" is no longer just today, and on the 1st "this month" is no longer just today. **Calendar weeks and months** starts the week on the day you pick under **Week starts on** (Monday to Sunday) and the month on the 1st. The year is the calendar year either way. Everything that adds up a week or a month follows it, through one shared piece of code, so they all give the same numbers:
  - The dashboard's 12 weekly bars. With the past 7 days the last bar is the past 7 days, and each bar's label gives its dates.
  - Goals, and the history under each one. A weekly goal counts the past 7 days, a monthly one the past 28 ("every 28 days"), and the bars under it are the 7- and 28-day blocks before that. With the past 7 and 28 days there's no even pace to be ahead of, so the tick on the bar is gone and a goal not yet reached says **Not yet**.
  - `GET /api/v1/overview`, which now also sends what each period is (its label, first and last day), and the run stats.
  - The alcohol units on the Nutrition page, which already counted the 7 days ending on the day: with calendar weeks they're the calendar week so far.
  - The Home Assistant week sensors and the run, training and activity-trend charts. The names say which ("Activities Past 7 Days" or "Activities This Week") and change when you change the setting. The entity ids stay the same, so automations keep working.

  The Nutrition week diary, the **All-Rounder** badge (three kinds of training in one week), the Analytics calendar and day-of-week chart, and the gear calendar stay calendar weeks, starting on the day you chose. New installs start on the past 7 and 28 days. An existing one keeps calendar weeks from Monday, as before, until you change it.
- **The iPhone app's Overview says what the server counts as the week and the month.** The picker says "7 days" and "28 days", or "Week" and "Month", and the line under it gives the period and its dates ("Past 7 days · 17–23 Nov"). Needs the updated iPhone app. An older app still shows the right numbers, labelled Week and Month.

### Changed
- **Settings, Import and Tasks are grouped into sections.** Each page had grown one card at a time into a long list. Each now has headed sections with links to them at the top:
  - **Settings**: **You** (Display, Features, Profile & goals, Calorie burn adjustment), **Connections** (Garmin Connect, Home Assistant, AI Provider, Maps), **Sharing** (Outside address, Contacts for live links, Email) and **This server** (Login details, Backup & Restore, the version). Home Assistant's two cards are one: **Health data in** and **Sensors out, over MQTT**. Display Preferences is now **Display**, as the rest of Headwind already called it. The Setup Guide card is gone: its Garmin and Home Assistant notes moved into those cards, and its list of environment variables was out of date (the README's Configuration section has them all).
  - **Import**: **Import** (the upload, and the kept Strava export beside it), then **To review**, which says how many things wait for you to decide and links to each list, short ones first, and **Recently deleted** at the end.
  - **Tasks**: **Background work** (the jobs, recent runs and start-up repairs) and **When something goes wrong** (the logs, then the diagnostics and the copy for troubleshooting).
- **Weather for older activities is on the Tasks page.** The Weather Backfill card has moved from Settings to the Tasks page's jobs, which says how many activities still have no weather, offers **Fetch now**, and follows it while it runs. It no longer counts rides in a virtual world, which never get weather: with any of those, the old card started the backfill again every two seconds without end.
- **Home Assistant draws every Headwind number as a graph.** Sensors that count things, like **Activities This Week**, **Badges Earned**, **Total Rides** and **Total Activities**, had no unit, so Home Assistant showed their history as a coloured bar of values. They now have units (rides, activities, badges, laps, steps, and ms for HRV), and every sensor that's a number is marked as a measurement, so each draws a line graph and keeps long-term statistics, as the speed and distance sensors already did. Sleep score, stress and Everests climbed graph without a unit. A missing reading, like the last ride's power when it had no power meter, is now sent in the form Home Assistant reads as unknown, which stops an error in its log for each one. The values themselves and the entity ids are unchanged, so dashboards keep working.
- **The pointer turns into a hand over a track on the heatmap.** Tracks can be clicked to open their activity since the last release, but nothing showed it: now the pointer changes over a track, as over a link, and goes back to the grab hand off one, so you can see where a click will find something.

### Fixed
- **A friend's dashboard no longer asks you to fix their activities.** Picking a friend's rider showed their **Activities that look wrong** card, with **It's right**, the fixes and **Delete all blips**, though you can't change a friend's activities here; they're fixed on their own Headwind. The card is gone from a friend's dashboard, along with the other things to sort out there (gear due, activities recorded on different gear or as different sports, uploads that look like runs). Your own dashboard is unchanged.

## [0.7.53-beta] - 2026-11-23

### Added
- **Click a track on the heatmap to open its activity.** Click or tap a line and a popup shows the activity's name, date, sport and distance, linking to its page. Where tracks overlap, as a regular commute's do, it lists every one under the click, newest first, and pointing at one in the list picks it out on the map. The tracks you picked are drawn over the rest while the popup is open. With everyone's activities shown together, each says whose it is, and a friend's opens on its own page too.
- **Your live tracking link is emailed to contacts you choose beforehand.** Add the people who should get it under **Contacts for live links** in Settings, or in the iPhone app under Settings → Live tracking link → **Contacts to email it to**, and tick **Send my live links** for each. When a link starts, your server emails it to them itself, so it gets out from the Watch on its own, or when nobody stops to tap Send. The email says it's from you, what you're doing, and that the link stops working an hour after you finish. Each link is sent once: asking for the same link again doesn't send it again. The mail goes out in the background, so a slow mail server doesn't hold up the phone. The iPhone's Record screen and the Watch say who it was sent to ("Sent to Sam and Alex."), and who it couldn't be sent to and why. When someone is getting the link, the iPhone no longer opens the share sheet at Start; **Send** is still there for anyone else. Needs the updated iPhone and Watch apps to show who it went to; the email goes out with older apps too.
- **Email settings.** A new **Email** card in Settings takes the mail server Headwind sends through (your email provider's SMTP settings, or a relay on your network): server, security, port, user name, password and the address to send from, with **Send a test email**. The password is kept encrypted like the other saved passwords. The troubleshooting copy leaves out the mail server, the contacts and who each link was sent to.

### Changed
- **The gear pages no longer offer a friend's rider.** With several riders on one Headwind, the rider picker on Gear, Kit and parts listed friends' riders too, and you could add a bike or shoes to one. A friend's gear is on their own Headwind, so the picker now lists only the riders who live here, and a link naming a friend's rider shows your own gear.

### Fixed
- **An activity dated in the future no longer goes to your friends.** A device whose clock was reset can save an activity more than a day ahead, like the Avinox unit's 2106 dates. Your friends were sent it, and until then it sat at the top of their Friends page and their list of your activities. Now it stays off your feed until you give it its real date with **When did it really start?**. It then goes out as new. A friend who already has it loses it at their next sync. **It's right** doesn't share it, because a start that hasn't happened can't be right. The activity's page and the dashboard's list of activities that look wrong both say friends won't see it until its date is fixed. An activity that's only ahead of the clock here, like one recorded this evening in New Zealand, is shared as before: only a start more than a day ahead is held back.
- **A friend's activity dated in the future no longer tops your lists.** A friend on an older version can still send one. It's no longer their newest activity or a new one on the Friends page, and it's left out of the lists of their activities on the web and in the iPhone app. It still opens on its own page.
- **Windows: deleting a backup while it is still downloading no longer shows an error page.** Windows won't remove a file that's still open, so **Delete** on the backup card (and on a troubleshooting copy) failed while a download of it was running, and starting a new backup during one failed too. The file is now left until the next start, when it's removed. If the file was locked at start-up, the background jobs didn't start either.

## [0.7.52-beta] - 2026-11-22

### Added
- **Share a live tracking link from the iPhone.** Switch on **Share live location** on the Record screen, or make it the default in Settings → Live tracking link. When you start a recording with GPS (or switch it on mid-recording), the phone asks your server for a link and opens the share sheet to send it by Messages, WhatsApp or mail. The link opens in any browser, with no account, and shows where you are, your track so far, distance, time, speed or pace and the phone's battery, but nothing within 300 m of where you started. Anyone with the link can see where you are. While it's shared the phone sends where you are every 5 s instead of 15, with the screen locked too. The link ends an hour after you finish, or at once with **Stop sharing**, and until then it stays on the Record screen to send again or copy. Your server needs an https **Outside address**: without one the app shows the reason and a button to Settings on the server, and the recording carries on without the link. Needs the updated iPhone app.
- **Share a live tracking link from the Watch.** Switch on **Share live location** on the Watch's start screen (it starts from the phone's setting). A recording with GPS sends where you are every 30 s, through the phone when it's near and over Wi-Fi or cellular when it isn't, and the Watch makes the link itself. The Watch can't send it, so your iPhone shows a notification, "Your live link is ready", and tapping it opens the share sheet. The link also waits on the iPhone's Record screen, with **Send**, **Copy** and **Stop sharing**, and shows as finished when the Watch recording ends. The iPhone asks to show notifications when you switch sharing on in Settings. Needs the updated Watch app, and the Watch's own token (made by the iPhone app).

### Changed
- **The iPhone and Watch apps' version goes up with every build, and the Watch shows it.** It was 0.1.0 on every build, so it couldn't tell you which one a device had. This build is 0.1.1 (2): the version, then the build number. The iPhone shows it in Settings, and the Watch at the bottom of its start screen. `ios/README.md` (Versions) says when each part goes up.
- **Each recording from the iPhone or the Watch has its id from the start.** The id goes with every live reading and, as before, with the upload, so a live link takes only its own recording's readings. A recording recovered after a crash keeps its id, and saving or discarding it ends any link it had.

### Removed
- **The install ping.** The setup wizard no longer has the step that sent a random install id and the version number to the original developer's server, and Headwind sends nothing of the kind. The wizard has six steps now. A database that had the ping loses its install id and the record of whether it was sent at the next start. `TELEMETRY` in `.env` does nothing any more and can be taken out.
- **The Buy Me a Coffee card at the top of Settings, and the README's links to it.** They went to the original developer's page.

## [0.7.51-beta] - 2026-11-22

### Added
- **A Routes page.** **Routes** in the sidebar lists every route you've saved, for any sport, with its distance, climb, sport and where it came from. Click one to see it on the map with its elevation profile. Bring routes in with **Import GPX** (several files at once), **From Strava** (the routes you made on Strava, read from the export Headwind kept when you imported it, or from an export you upload there, of which only the routes are read) and **From Garmin** (your Garmin Connect courses, when Garmin is connected; it runs in the background and skips courses already here). **Save as route** on an activity now opens its route here. In each row you can rename a route, change its sport, download it as a GPX file or delete it. Routes can't be edited yet. A route with the same points as one already here is no longer saved again under another name, so a route you've renamed doesn't come back as a copy when you import the same export again.
- **Deal with many "Activities that look wrong" at once.** The dashboard's card has its own **Select** button. Pick rows on it, or pick every row with the same reason in one click (**Pick by reason**: "No distance and no time (34)", "Under 160 m (2)"), then use the bar at the bottom: **It's right**, **Delete**, and **Use Strava's climb** or **Use the elapsed time** when a picked row can take that fix. A fix goes on the rows it fits; the message after says how many it couldn't change. Picking on the card doesn't pick anything in the activity list below it, even when the same activity is in both. **Delete all blips** now also takes activities with no distance and no time, such as the empty uploads from Apple Health, along with rides under 160 m and recordings with nothing in them.

### Fixed
- **It's right on the Select bar clears the flag on a run, walk or swim too.** It used to skip anything but a ride and say "only rides have a flag", though runs, walks and swims get flagged as well.
- **Settings → Activity types no longer says "0 have the wrong sport" above a list of them without explaining why.** That count is from the last time you pressed **Check with Garmin**. Each time Headwind starts, it can add more to the list, going by the type each activity had at its last sync. When it has done that since your last check, the page now says so under the count and suggests checking with Garmin again.
- **The server refuses a phone upload whose track has no distance and no time.** Older iPhone apps and the Android app can still send Apple Health's stale-location route (see 0.7.50-beta): one location repeated at a single moment. It became an empty activity under "Activities that look wrong". Now the server stores nothing and answers that nothing was recorded. The iPhone counts it under "refused by the server" in Settings → Apple Health. Once the app is updated, it can send the same workout again as a timed session. Files you import on the web and Strava exports are unchanged.

## [0.7.50-beta] - 2026-11-21

### Fixed
- **Activity types you changed in Garmin stay off Settings → Activity types after a restart.** 0.7.49-beta covered a re-sync, but not **Check with Garmin**. That check read each activity's current type from Garmin and found nothing wrong, so the list emptied, but it didn't keep that type. The check Headwind runs at each start went by the type from the last sync, which for older activities was still the type from when they came in (walking for a walk you made hiking in Garmin), and listed them all again. **Check with Garmin** now keeps the types it reads. Press it once after updating and the list stays clear.
- **Workouts from Apple Health no longer arrive empty.** Some apps save one stale location with a workout, repeated at a single moment, and the iPhone sent it as the workout's route. The server read it as an activity with no distance and no time, listed under "Activities that look wrong" as "nothing was recorded". The iPhone now sends a workout whose route covers under a minute or 100 m as a timed session, with Apple Health's own duration, distance, calories and average heart rate. A workout sent with no route now carries Apple Health's average heart rate too. Needs the updated iPhone app. Activities already sent this way stay as they are; they're often copies of a workout that Strava or Garmin Connect saved to Apple Health, so check for the original before deleting them.

## [0.7.49-beta] - 2026-11-20

### Fixed
- **An activity type you changed in Garmin no longer comes back on Activity types after every restart.** When you changed an activity's type in Garmin Connect to the sport Headwind already had (walking made hiking, rowing made canoeing), a re-sync saw nothing to offer, but kept the type Garmin had when the activity first came in. Each start then listed it again on Settings → Activity types, to be changed back to the old type. A re-sync now takes Garmin's new type, and the activity drops off the list. Run **Full re-sync** once after updating to catch older activities.

## [0.7.48-beta] - 2026-11-20

### Added
- **Every friend's activities in one list.** The rider buttons on the dashboard and the Activities page have a **Friends** choice once two friends have synced: their activities together, newest first, each row with its rider's avatar. Search, the more filters, the sport filter, the totals and the weekly chart work over them all together, as for one rider. Nothing on it can be changed here, as with any friend's activity: it has no **Select** bar, gear filter, **Change the type of all results** or **Add an activity by hand**. Another rider who lives on this instance isn't a friend and is never listed under Friends. Before, a friend's activities showed one friend at a time.

## [0.7.47-beta] - 2026-11-20

### Added
- **Apple Health sends only the workouts your server doesn't have.** Before this, the iPhone read every other app's workout again on a full look (the first sync, choosing to go further back, Health's permission granted again), with its route and heart rate, and uploaded it for the server to recognise. Over three years that took minutes. Now the phone asks the server which it has before reading their routes, and sends only the rest. Workouts already sent before this update are recognised too. Settings → Apple Health counts them as "already on the server". Needs the updated iPhone app.

### Changed
- **One upload path for everything from the iPhone and the Watch.** Rides, other sports with a GPS track and sessions with none now go through the same door on the server, and each keeps the phone's id for it. A ride sent again is found by that id as well as by its content, and every sport gets the same duplicate check against Garmin, Strava and file imports. The older apps' upload paths still work and answer as before.
- **Two processes serve pages in Docker.** Before this there was one, so a page that reads a lot (the dashboard, a long activity list) held up every other page behind Python's one lock per process. Now there are two, each with 8 threads, and what they need to share is in the database: a live ride's last reading (one per rider), failed sign-ins, and a Garmin sign-in waiting for its MFA code, which now runs in the background worker. `WEB_WORKERS` in `.env` sets how many; each takes about 120 MB, so `1` suits a machine short of memory.
- **Activity pages are at `/activities/<id>`.** They were at `/rides/<id>` from when only rides had pages. Links to the old address still work: bookmarks, friends' links, Home Assistant notifications already sent, and a page left open from before. The database's own names for the AI coach's notes, the phone's sensor recordings and the activities waiting on the Import and Garmin pages say activity now too. The first start after updating renames them in under a second, after keeping a copy of the database as it was (`bike.db.pre-<version>`) if there isn't one already, since an older Headwind can't read the new names. The phone apps' older addresses (`/api/v1/rides`) still work: see the next item.
- **The phone API says activities, not rides.** Every activity of every sport is at `/api/v1/activities/<id>`, with its photos, bike, sport, commute and duplicates under it, and `GET /api/v1/activities` lists them, with no `ride`/`workout` kind in the path or the answer. `/api/v1/ping` says `api` 3 for them. Best times and biggest climbs in `/api/v1/perform` name theirs as `activityId` and `activityName`. The older `/api/v1/rides` paths and the `rideId` and `rideName` keys stay, answering as before, until the Android app moves. The updated iPhone app uses the new paths and keeps using the older ones on a server that doesn't have them yet.

### Fixed
- **Download GPX on every sport's page.** The activity page offered it only on rides, though any activity with a GPS track exports, as it already did from a list's Download. A track with no name is named after its sport, not "Ride".
- **A workout you deleted no longer comes back from Apple Health.** A full look through Apple Health uploaded it again; the phone now leaves out workouts deleted on the server. Uploading a recording yourself still brings it back.
- **A typed-in or timed session that turned out to be a copy of another recording says so.** The phone was told it was new and shown the copy's id; it's now told it was already on the server, with the id of the activity that was kept, as a recording with a track already was.
- **A live ride is marked idle whichever process heard from the phone last.** The 90-second check that marks a ride idle when the phone stops sending now runs in the background worker, from the saved reading, rather than on a timer in the process that took the last reading.
- **The sign-in lockout counts every attempt, and survives a restart.** Failed sign-ins are kept in the database, so 8 failures from one address (and 30 from all) are counted across every process serving pages, and a restart no longer resets the count.
- **Two processes starting at once no longer both run a start-up repair.** Every process checks the database when it starts, and each once-only repair checks its flag first. Two processes starting together could both find it unset and both run it. They now take turns.

## [0.7.46-beta] - 2026-11-20

### Added
- **Routes from GPX files, activities and your Strava export.** Before this, the route planner (`/planner`, still out of the sidebar until it's finished) could only make a route from waypoints clicked on the map. **Import GPX** in its Saved routes panel makes a route from each file you choose, several at once. It reads a file's track, or failing that its route points, which is what the planner's own export writes. A file with no points, or one that isn't GPX, is listed with the reason. **Save as route** in an activity's **⋯** menu makes a route from the activity's own GPS points, for any sport with a GPS track except Zwift. Tick **Routes** on the Import page with a Strava export to bring in the routes you made on Strava, each with its sport (routes you starred from other people aren't in the export). A route made like this keeps the line it follows, with its heights. The planner draws it as one line with its distance, climb and elevation profile, and hovering the profile marks the spot on the map. **Export GPX** writes the route's own heights instead of looking them up, and **Edit as a copy** turns the line into waypoints at most a few metres off it, to drag and save as a new route, so the original stays. A route with the same name and points isn't saved twice, so importing a Strava export again, or choosing a GPX file again, adds no copies (Strava's export often lists a route more than once). Routes now belong to a rider: a route saved from an activity goes to that activity's rider, and every other route to you. Routes made before this update are yours too, and deleting a rider deletes their routes.
- **Sleep stages on Recovery.** The Sleep chart stacks each night's deep, light and REM sleep, with time awake on top, and the Daily Log has **Deep / REM** and **Efficiency** (time asleep as a share of time in bed) columns. The AI coach's recovery notes get them too. They come from Garmin, from the next sync on (nights already synced keep their total only), or from Apple Health through the iPhone app, which needs no new permission. Apple Health stages come from one source per night, the Watch's where it recorded the night, since two sources' stages for the same minutes disagree. A night recorded only as "asleep" (an iPhone alone or an older Watch) has its hours and no stages, and is drawn as one bar as before.
- **Each friend's latest activity on the Friends page, and what a sync brought.** The friends list now comes first, as **Your Friends**, with a **Latest activity** column (the sport, a link to it, its date and distance), and a friend's name opens their activity list. Before, a friend's new activities only showed once you picked their rider on the dashboard or the Activities page. After a sync that brought new activities the page says so ("Sam: 1 new ride, Hill reps, 20 Nov", or "3 new runs, the latest …" with a link to all of them), adding up several syncs until you dismiss it. A friend's first sync brings their history and says nothing, and an edited activity isn't new.

### Changed
- **Pages are smaller, and only Headwind's own script files run.** The pages' JavaScript moved out of the pages into files under `static/js`, which the browser keeps between visits instead of fetching again with every page: the Nutrition page went from about 200 KB to 77 KB (15 KB compressed). With nothing inline left, the Content-Security-Policy no longer allows inline scripts (`'unsafe-inline'`), so if some text ever slipped into a page unescaped, it still couldn't run as script.
- **A smaller database when activities are merged or imports wait on the Import page.** The recordings set aside behind merged activities, the activities in **Recently deleted** and the imports waiting for you to choose on the Import page kept their GPS and other recorded data uncompressed: on one test install, importing a Strava export again left 480 MB of it. It's compressed now, as an activity's own is, and two test databases shrank by half (690 MB to 350 MB, 890 MB to 420 MB). The Import page also no longer reads all of it to load. The first start after updating compresses what's there, in under a minute on those, after keeping a copy of the database as it was (`bike.db.pre-<version>`).
- **Roughness and the route planner are out of the sidebar until they're finished.** Their pages are still at `/roughness` and `/planner`.

### Fixed
- **The warnings when changing an activity's type say what happens.** They still said rides "move to Workouts", a page that's been part of Activities for a while. They now say that a ride that becomes another sport loses its bike and ride segment times, and its calories are worked out again. The activity page's warning also decided what's a ride from Walk, Run and Hike, so changing a ride to a swim gave no warning and a walk to a swim a wrong one. The calorie setting's **Apply to history** message always said 0 walks and runs.

## [0.7.45-beta] - 2026-11-20

### Fixed
- **The dashboard loads much faster with many merged activities.** Its counts of merged activities whose two recordings disagree about the gear or sport read every copy set aside in full, streams and all, on each load: with a few thousand copies, that was over 600 MB, and several seconds for the first load after a restart. They now read only an index. The first start after updating builds it once.

## [0.7.44-beta] - 2026-11-20

### Added
- **The map and charts are linked when comparing two recordings.** On an activity's **Compare side by side** page, hovering a chart puts a dot on the map where each recording was at that minute, in its own colour, and the cursor on either track shows that minute on every chart, as on the activity page.
- **The phone sensor charts are linked to the map too.** On an activity with a phone's sensor recording, hovering the roughness, barometric altitude or cadence chart marks the spot on the map, and the cursor on the track shows on those charts as it does on the others.

### Fixed
- **Times under the segment sliders.** Making a segment from an activity now shows how far into it each end is ("12m in"), as it was always meant to.
- **The Import page no longer lists an activity that differs from its file once that activity has been deleted** or set aside behind another recording. Before, it was shown without a date or sport, and its link went to a page that wasn't found.

## [0.7.43-beta] - 2026-11-20

### Added
- **Favourite sports in the sidebar.** Under **Settings → Display**, tick the sports you do most, and each gets its own item under Activities in the sidebar, opening the list with only that sport. A favourite can be Cycling (every kind of ride: road, indoor, e-bike, mountain bike, gravel), On foot (runs, walks and hikes), Swimming, or one sport on its own, such as Run without the walks. The list it opens says what it keeps, not what it leaves out, so a kind of ride you first record next year shows up under Cycling by itself. The item is highlighted while that's the only filter on. The **Only rides** / **Only on foot** links work the same way now. The iPhone app gets the favourites from `GET /api/v1/ping` (`favourite_sports`), in the form its activity list already filters by.
- **More filters and an order for the activity lists.** Under **More filters** on the dashboard and the Activities page: with or without power, heart rate, cadence or a GPS track, indoors or outdoors, and where it came from (Garmin, Strava, a file, the phone app, typed in). **Order** lists them by date (newest or oldest first), distance, moving time, climbing or speed. With any of these on, the list is one list a hundred at a time, with **Next** and **Previous**, rather than the years and months. Every filter is in the page's address, so a filtered list can be bookmarked or linked, and the links on the page keep it. A rider's profile has an **All activities** link to their list. A ride recorded on the phone now says so, so the phone app filter finds it.
- **Captions and order for an activity's photos.** On the activity page, type a caption under a photo (it saves when you leave the box), and drag the photos into order, or use the ‹ › arrows on a phone. The first photo is the activity's cover. The iPhone app could already do both.
- **Best efforts in kilometres.** With metric units, the ride best efforts on your profile and the Data page are your fastest 5, 10, 20, 40, 50, 100 and 160 km, not 5 to 100 miles converted to 8.0, 16.1 and 32.2 km. Both sets are kept, so switching units is instant. Rides already here get theirs once, in the background, after the update (the Tasks page shows it). The phone app's best efforts stay in miles.
- **°C or °F for the weather.** Under **Settings → Display**, apart from the units, since many riders who ride in miles still say 9°C. The wind and gusts now follow the units, so an imperial rider sees mph next to mph speeds rather than km/h. The activity page, the Data page's weather charts, storm and fog lists, and the weather badges follow both.

### Changed
- **Re-imported activities that differ are easier to read.** On the Import page, each activity the file now reads differently is one compact line: its date, name and sport, then what differs, as `saved → in the file`. Before, each one had its own table with columns stretched across the page, and only a name to tell it by. **Fill in gaps** is offered only where the saved activity is missing something the file has, and says what it would add (heart rate, calories, the recorded track). **Fill in all gaps** fills those and leaves the rest for you to choose. Before, it settled every one, even where it had nothing to add. **Use import** is now **Use the file's**.

- **Metric riders' badges count against round figures.** Badges are written in miles, and a metric rider saw them converted: "40 km in one ride", earned only at 40.2 km. Now the limits are the round numbers the badge shows (40 km in one ride, 150 m of climbing, 1,600 km in total, whole km/h for speeds), and that's what counts. Imperial riders' badges haven't changed.
- **The loss target is in kg a week when weights are shown in kg**, under **Settings → Profile & goals** and on **Nutrition → Goals**, from 0.25 to 1.1 kg. It's still kept in lb, so nothing saved changes, and the plan under the form names the rate in the same unit. **Show weights as** now says it's a choice of its own, apart from the units.
- **Height is in cm first with metric units**, with feet and inches as the alternative. Typing either fills in the other, so the one you changed is the one saved. Before, the feet and inches always won, so a new height typed in cm was ignored.
- **Strava's Weight Training, Crossfit and High Intensity Interval Training are Strength and HIIT.** They were saved under Strava's names, so they had a distance, no estimated calories and a sport filter entry of their own. Those already saved are renamed at the next start, with any gear defaults set for them.
- **Home Assistant can show the distance and speed sensors in metric.** They're still published in mi, ft and mph, so their ids and history stay as they are, but each now says it's a distance or a speed, so Home Assistant offers km, m and km/h in the entity's settings.
- **Maps and charts no longer come from another site.** Chart.js, Leaflet and the barcode scanner were fetched from jsDelivr and unpkg by every page that drew a map, a chart or scanned food, so those two sites saw each visit. Headwind now serves them itself, from `static/vendor`. Map tiles still come from the map you pick. `scripts/vendor.py` fetches a new version, checked against npm's checksum.
- **Pages load faster.** Headwind's own scripts, styles and libraries are kept by the browser for a year and fetched again only when they change, and pages, their data and those files are sent compressed: the Analytics page goes from 800 KB to 165 KB, an activity's page to a third of its size.
- **The database is brought up to date before the web server starts.** Each change to how Headwind stores things is now a numbered step, and the database records the last one it has had, so each runs once, in order. In Docker they run before Gunicorn starts, so a long one on a big database is no longer cut short by the web server's 5-minute limit and started again on the next start. A database a newer Headwind has opened is refused, saying so, instead of being changed by an older one that can't know what the newer one did; a backup from a newer version is refused in the same way. Before a step an older version can't read, the database is kept beside itself as `bike.db.pre-<version>`. Everything before this release is step 1, so nothing changes for an existing database. The repairs and checks at every start are unchanged.
- **The database is about half the size.** Each activity's recording, point by point (GPS, heart rate, power, ...), was three quarters of the database, stored as plain text in the activities table, so every read of an activity carried most of a megabyte. It's now kept in a table of its own, compressed to about a quarter of the size. On a history of 3,400 activities the database went from 1.25 GB to 690 MB, and the move took 35 seconds at the first start. Before it, the database is copied beside itself as `bike.db.pre-<version>` (an older Headwind can't read the new one), and afterwards the file is compacted when the disk has room. Delete the copy once you're happy. Nothing about an activity changes, and friends aren't sent your activities again because of it.
- **Background work runs in a process of its own.** Imports, backups and the copy for troubleshooting, the Garmin and Home Assistant syncs, the Garmin history, MQTT commands, the friends' syncs (automatic or from the Friends page), the weather for older activities, the Garmin activity type and changes checks, and the AI coach's analyses used to run inside the web server, sharing its one process with every page. They now run in a background worker beside it, so a long import's or sync's parsing and matching no longer slow pages down. In Docker, Gunicorn starts the worker and starts it again if it stops; the Windows app runs it inside itself. Work a page starts is queued in the database and run once, and a run cut short by a restart is shown as stopped rather than running for ever. The Tasks page says if the worker isn't running.
- **Imports, Garmin's activity sync and the AI batch no longer tie up the server.** An import, Settings' **Sync activities** and the AI page's batch analysis used to do the work inside the page's own connection, holding one of the server's few threads for as long as the import, Garmin or the AI took. Now the upload is saved and the work runs in the background worker, and the page follows it, so it carries on if you leave the page, as an import already did. One import runs at a time: starting a second while one runs says so, where before both ran at once and fought over the database.
- **A finished backup or copy for troubleshooting survives a restart.** It's offered for a day, as before, but a restart no longer deletes it. An import or a file being made when Headwind restarts is shown as stopped by the restart, in the indicator at the top of the page as well as on the Tasks page. And the Friends page's **Sync** button says how a friend's last sync went after a restart, the automatic one included.

### Fixed
- **Garmin's HIIT, yoga and strength sessions saved as Other are offered their sport.** An older sync saved these as rides, and the type check of the time could only make them Other. The start-up check of Garmin's types missed them, because changing a ride into a workout back then gave it a new id. It now finds them through the Garmin id they came from, and offers Garmin's sport for each one that has no sport in particular. A sport you picked yourself is never offered over. On a real history that was 91 HIIT sessions and 6 kitesurfs. And applying a change to an activity that was already a workout (a Garmin yoga session saved as Other) failed with "that ride was not found"; it now works.
- **A list of only yoga or strength shows its time, not a distance.** Filtered to a sport with no distance, the dashboard and the Data page showed its distance and speed, both zero. They now show time, calories and climbing, as for a mix of sports, and the activity rows leave out "0.0 mi".
- **Runs uploaded from Strava's files are no longer taken for rides without a word.** Strava writes "Biking" into the TCX file of every activity it exports, a run's too, and many GPX files (Strava's, RunKeeper's, Trailforks') name no sport at all, so a run uploaded on its own came in as a ride. A Strava export was never affected, since it takes the sport from activities.csv. Now, when a file says "Biking" or nothing and its track moved like a run or a walk, Headwind still saves it as the file says, then asks: **Was this a run?** on the activity, with **Use Run** or **Ride is right**, and the upload's result, the dashboard and the Import page say so too. The Import page lists every upload waiting for an answer, to change or keep one at a time or all at once. Uploads from the phone, the upload endpoint and a zip of files are asked about the same way. Pace decides it, not cadence: a runner's cadence is counted per foot, so it looks like pedalling, and Strava's run files have none. Tried on two real Strava exports, it asked about all 161 runs and walks saved as rides, and about 14 of 1,154 real rides, slow ones, which take one click to keep. A file with a power meter, or one that names its sport, is never asked about.
- **A Full re-sync no longer locks everything else out.** It saved its first change, then held it open while it read the rest of Garmin's list, downloading files as it went, so anything else that saved, from a duplicate's **Use this recording** to opening the Tasks page, waited a minute and failed with "database is locked" until it finished. It now saves before each download. The regular Garmin sync did the same thing on a smaller scale: up to 20 downloads, and each day's health figures, behind one save. It now saves each activity and each day as it goes, and gets an activity's weather before saving it. Matching every activity against the segments again, scanning for best efforts, and importing from Home Assistant also save as they go now, so none of them hold everything else up while they run.

## [0.7.42-beta] - 2026-11-19

### Changed
- **Activities in the log are links.** On the Tasks page's Logs card, an activity's id in a line (a duplicate set aside, the one kept, a repair that moved it) opens that activity, or the view of the copy set aside, with its name in the tooltip. A number that isn't an activity here, or a copy since discarded, stays plain text.
- **The Import page uses the width of the screen.** On a wide screen the upload card sits on the left and what's waiting for you (a kept Strava export, files that couldn't be read, activities left out of segments, Garmin sports to review) on the right, with the longer lists under both, as wide as the two. Before, every card was stacked down a narrow column, and one or two ran right across the screen. A narrower screen still shows one column.

## [0.7.41-beta] - 2026-11-19

### Added
- **Friends' activities in the iPhone app.** The Activities tab has a **Whose** menu, next to the sport filter, once a friend has synced: Me, one friend, or Everyone together by date, with each friend's rows named under Everyone. A friend's activity opens with its map, stats and charts, says whose it is and when it was synced, and has no Delete and no photo editing, as on the web. The app keeps the choice. For the app, `GET /api/v1/friends` lists the friends synced here, and `GET /api/v1/rides` takes `rider` (a friend's rider id, or `all`). Another rider who lives on this instance is never listed there, and every change to a friend's activity is still refused.
- **Set the outside address in Settings.** **Settings → Outside address** is the https address you reach Headwind on from outside the house. The phone apps pair with it, a friend's code carries it, and notification links open it. Until now it was only the `APP_URL` environment variable, which meant editing the env file and restarting. The setup wizard asks for it as a new step 3, with the browser's address as a hint, and the Done step says when it was skipped. **Check** loads the address from your browser, because a server often can't reach its own public address. An install with an https `APP_URL` keeps using it until an address is saved. **Phones → Pair a phone** no longer has an address box of its own: it shows the saved address with a link to change it, and won't make a token without an https one. The Friends page says where its codes connect, and its feed URL uses the same address. For the apps, `GET /api/v1/ping` returns it as `server_url`. When that isn't the address the iPhone app paired with (Headwind moved, or the phone paired over the home network), the app offers to move. It moves only once the new address accepts the phone's token, and its recordings and Watch go with it.

### Changed
- **The Workouts page is gone: the Activities page shows all of it.** Since every sport went into one table, Workouts was the Activities list with the rides left out, and its notes still described it as before 0.7. **+ Add an activity by hand** is now at the top of the Activities page, and adds to the rider whose list it is. The page's header now includes calories. A walk's or run's page links back to Activities, and deletes and changes type the same way a ride's does. An old link to `/workouts` opens the Activities list with the rides left out, keeping its search and dates. The "workout saved" notification links to the activity. In demo mode, activities added by hand can no longer be deleted there, as with rides.

### Security
- **Choose whose activities each friend sees.** A friend's code used to share every rider on this instance. Now each code shares only the riders ticked for it, under **Whose activities** on the Friends page, when it's made and with **Edit** after. A new code shares just the main rider unless you tick others, a rider added later is shared with nobody until you tick them (Headwind says so when you add one), and the panel showing a new code says whose activities it shares. A rider a code doesn't share is missing from the rider list a friend's Headwind sees, and their feed is empty. Unticking a rider takes their activities off the friend's instance at the next sync. Codes made before this keep sharing every rider they shared, so nothing changes for friends already linked until you untick someone. The iPhone app's codes share the main rider, as before.
- **The saved login no longer gives the environment's password away.** `.admin_login` records which `APP_USERNAME`/`APP_PASSWORD` it was saved under, so editing `.env` still wins over a password changed in Settings. That record was a quick, unsalted hash, which someone with a copy of the data folder could work back to the password. Now it's a salted scrypt hash, as the password's is. The old one is replaced at the first start.
- **A note in the log when a private address is trusted as a proxy.** With `TRUSTED_PROXIES` unset, Headwind believes `X-Forwarded-For` from any private address, so on a LAN or under Docker Desktop a client could claim a new address on each sign-in attempt (the 30-in-5-minutes limit for everyone still holds). Nothing changes by default, but the log now says once which private address it believed, and how to set `TRUSTED_PROXIES` to your proxy's address or network.
- **The Windows build can install exact versions.** A new **Windows lock** workflow makes `requirements-windows.lock` (hashes included) on Windows, where the Windows-only packages resolve. Once that file is committed, the Windows build installs from it with `--require-hashes`, and CI audits it with `pip-audit`. `waitress` is now listed in `requirements.txt` for Windows, and PyInstaller in `requirements-windows-build.txt`.

### Fixed
- **A copy with impossible figures no longer wins over one that's right.** When the same activity came in twice, the better recording (a Garmin's, with heart rate) was kept whatever its figures said. So a walk whose Garmin GPS jumped about kept 31.2 km at an average of 33 km/h, and Strava's 1.7 km was set aside. Now a copy whose distance, time, average speed, climb or start can't be right loses to one whose figures are fine, whatever recorded it. A single top-speed spike, or a heart-rate or calorie fault, doesn't count against a copy, since its distance is still right. A flag you've dismissed ("it is right") doesn't either. Activities already merged keep the copy they have: swap in the other from the activity's page.
- **A Strava crop that keeps the end of a recording is made.** Strava's export holds the recording as it was uploaded, and Headwind cuts it to the part Strava kept. When the crop kept everything from a later start to the end, and the device's session ran on a little past its last record (half a minute on a ski day), the crop was taken for a clock that was out. The whole recording was then kept under the crop's later start: its track sat minutes late, and it never matched the watch's own copy. Now the crop is made. **Import again** puts an activity imported before this right: it's offered on the Import page like any other change.
- **Recovery's Daily Log leaves out columns with nothing in them.** A rider on Apple Health alone saw three columns of dashes: Apple Health has no sleep score, Body Battery or stress. A column with no value on any day in the range is now left out, as the charts already were. A day with only an HRV reading is listed now too; before, it was left out of the log. The iPhone app's Recovery card shows only the figures the day has.
- **Zwift races hidden behind their warm-ups come back.** When a watch session held a Zwift warm-up and a race, and the race had been set aside as a copy of the session, keeping the warm-up over the session moved the race behind the warm-up with it, though they aren't the same ride. Now a copy that moves to another recording is checked against it first, and comes back as its own activity when it doesn't match. A Zwift recording that lasts more than half the watch session it's in is now matched to the session too, and kept over it.
- **Activities typed into Garmin Connect are kept as typed in, and one saved empty gets Garmin's figures.** Garmin has no file for an activity typed into Garmin Connect, so Headwind makes it from Garmin's list, but it was saved like a recording. When the same session was also recorded (on Strava, say), the duplicate check could keep the typed-in copy over the real one. Now it's saved as typed in, and the activity page says "typed in" beside the date, for these and for Strava's manual entries. The daily Garmin check marks the ones an older version brought in. One that was saved with no distance and no time takes Garmin's: a swim from 2016 had come in as 0 m in 0 s, though Garmin says 500 m in 40 minutes. Once for each, a typed-in activity whose distance or time differs from Garmin's, more or less, is offered on the Import page. **Full re-sync** on the Settings page does them all at once. An activity with no track no longer offers **Download GPX**, which led to a "not found" page. One with no climb shows none rather than 0 m. And the box for a copy set aside says "activity" rather than "ride" for other sports.
- **More duplicates are found, with no change to the ones already found.** On a real history this set aside 23 more:
  - **Recordings with nothing in them** (a ride, run, walk or swim with no distance, speed, heart rate, power or GPS track, as some Garmin uploads are) are set aside behind the real activity they overlap, however long they last. An empty recording that overlaps nothing is listed under **Activities that look wrong** on the dashboard, where **Delete all blips** now takes these too.
  - **Two recordings that start the same second** are one activity, however far apart their distances are: GPS drift, or a ski app that counts the lifts.
  - **A start out by a time zone or a clock mistake.** A recording whose start is a whole number of quarter hours from another's, with the same distance, length and GPS track, is the same activity (RunKeeper runs on Strava, hours out from their Garmin copies). The one kept takes the start of whichever copy knows its time zone. Two Garmin recordings never match this way, so the same commute ridden twice in a day at the same pace stays two rides.
  - **A second recording longer than half the activity** (a second Garmin recording of most of a day's ride, say) is a piece of it when it lies wholly inside it, is the same sport, and both GPS tracks agree.
  - **A track stored with more times than positions.** Before 0.7.7, Headwind kept a time for each moment a device had no GPS fix, so the track's times and positions no longer line up, and it couldn't be compared with another copy at all. Now each position is compared at its likely moment wherever that's known to within a minute. A few records out, it's matched like any other. Where the fix was lost for minutes (in a lift), the daily Garmin check reads the file again, as it already did for segments, and once the track is put right the activity is checked for duplicates again. Four of the Alpe d'Huez ski days whose ski app's copy was kept beside the watch's are one activity each now.

  At the first start after updating, every copy set aside is checked against the activity it sits behind, and every activity is checked for duplicates again. This took under half a minute on 3,600 activities. The Tasks page lists what came back and how many more duplicates were found. As always, a copy set aside isn't deleted: you can swap it in or keep both from the activity's page.

## [0.7.40-beta] - 2026-11-19

### Fixed
- **Activities with GPS and times out of step are put right, or pointed out.** A Headwind before 0.7.7 (and the original project) kept a time for every second a device recorded, but a position only when it had a GPS fix. So on an activity that lost the signal, or took a while to find it, the times along the track are off, and segments leave it out altogether. Only reading the file again puts it right. Now the daily Garmin check does that for Garmin's: it downloads the activity's file again and puts the track right, so segments count it again. **Full re-sync** on the Settings page does them all at once, where the daily check works back through your history a block at a time. The **Import** page lists the ones left out of segments and says how each gets put right: Garmin's by that check, a friend's on their own Headwind (they come back with the next sync), and the rest by importing their files again. Anything else in a file read again that differs from what's saved waits on the Import page for you to decide, as before. At the first start after updating, the map summaries of every activity are made again, which takes a minute or so on a long history.

## [0.7.39-beta] - 2026-11-19

### Fixed
- **Every lap of a segment counts.** An activity that rode a segment more than once (laps of a trail centre's loop, a climb ridden twice) kept only its fastest time there, so six laps over three rides showed as three efforts at most. Now each time round is an effort of its own, as on Strava: the leaderboard lists them all and the PR is the best of any lap. The activity page marks them lap 1, lap 2, ..., and each lap's trend is against the effort before it (lap 2 against lap 1). A friend's time on the same day is their best lap. An approximate (≈) lap, ridden a little off the line, counts too. At the first start after updating, every segment is matched again, and the Tasks page says how many more laps were found. On a real mountain-biking history: 141.

## [0.7.38-beta] - 2026-11-19

### Added
- **Kitesurf and Wingfoil are sports of their own.** Pick either in **Change the type** on an activity or in the Activities page's **Select** bar, and set default gear for it. A Garmin kiteboarding activity or a FIT or GPX file of a kitesurf comes in as Kitesurf; before, Garmin's came in as Other and a file's as Surf. A Garmin or file wing foil session comes in as Wingfoil, where it was Other. Kitesurfs from a Strava export were already kept as Kitesurf, but couldn't be picked. Like the other water sports, neither has a climb, and each one's distance adds up on its own. Garmin kiteboarding and wing foil activities already saved as Other are offered their sport on the **Import** page, to apply or keep; a kitesurf saved as Surf from a file, or from a Garmin sync before 0.7, is changed by hand.

### Fixed
- **An effort has to follow the segment's own line.** A ride only had to pass near a segment's start and finish and four points along it, within 60 m, so another way between the same ends counted: a road round instead of a steep path, or the other of two trails down a hill that split and join again. Two segments drawn on such trails got the same efforts, each taking the faster of the ride's runs down either. Now a ride that strays more than 40 m from the segment's line for more than 60 m isn't on it, and neither is a ride that runs nearer the line of another segment with the same start and finish, where the two lines go their own ways. GPS drift and a single stray point still count. Approximate (≈) efforts are checked the same way. At the first start after updating, every segment is matched again, and the Tasks page says how many efforts were removed. Some PRs can change: on real data, a few had been set on the other way.

## [0.7.37-beta] - 2026-11-19

### Changed
- **A day's steps come from one source.** Each day took the highest count from Garmin, the phone, Apple Health and a watch, and a phone counts pedalling as steps, so on a ride day the phone's count won, thousands of steps too high. Now the **Steps** page has **Count steps from**: Automatic (Garmin when it has given steps on 5 of the last 14 days, otherwise the phone), Garmin, or Phone (Apple Health, the Android app, or a watch through Home Assistant). If the chosen source has nothing for a day, the day has no steps; another source's count isn't used instead. A number you enter on the Steps page is still the count for its day. The Home Assistant sensors, the recovery charts and the phone apps all use the same count.
- **Check for update looks at this project's releases.** It asked Docker Hub when the original project's old image was last pushed, which said nothing about the version you run. Now it compares your version with the newest release on GitHub and names it when there's a newer one.

### Fixed
- **A live recording on the phone goes idle in Home Assistant when the phone stops sending.** The timer that marks it idle couldn't read the MQTT settings from its own thread, so the ride stayed "riding" in Home Assistant.
- **Activities from a Garmin sync send the new-activity notification,** as an uploaded file does, for activities from the last 3 days. Older ones filled in by the sync, and a copy of an activity already here, don't.
- **An activity that fails half-way through a zip import leaves nothing behind.** What it had saved before the error was kept along with the next activity, without its duplicate check or best times.

These four came from looking through the original project's 0.8 and 0.9 releases.

- **A segment matches the ride it was made on, stops and all.** An effort slower than 2 m/s (4.5 mph) over a segment was turned away as a false match, and that counted the stops: five minutes waiting for a mate half way down a 200 m trail made it far too slow. So segments drawn on a mountain-bike ride with stops on its descents didn't match that ride, nor any other ride that stopped on them. Now the slowest speed that counts is taken over the time spent moving. The effort's time is still the whole elapsed time from start to finish, stops included, as on Strava. A ride that leaves the segment and comes back is still turned away, because the detour is moving time. A wait at the top before setting off, or at the bottom after finishing, used to count in the time when the rider stood within reach of the marker; now the effort starts when they move off and ends when they arrive. At the first start after updating, every segment is matched again, and the Tasks page says how many efforts were found and how many times got shorter. Some PRs can change.

## [0.7.36-beta] - 2026-11-01

### Added
- **Activities recorded twice with different sports are pointed out.** When Garmin and Strava both have an activity and say different sports (a Garmin ride saved as a plain ride while Strava says it was on an e-bike, Strava's indoor ride kept as Garmin's `cycling`, Strava's yoga kept as Garmin's Other), Headwind kept one and its sport without a word. Now the activity's page says "Strava says E-bike ride, Garmin says Ride", with a button to take the other sport or keep the one it has. The Import page lists them all, grouped by kind of difference, to settle a whole group at once, and the dashboard says when there are some. Nothing changes until you choose. Strava's spelling of a sport Headwind has its own name for doesn't count as a difference, nor does a copy that only says Other or Workout.

### Changed
- **A ride on an e-bike is an e-bike ride.** Before, only segments counted it as one, so a ride on an e-bike still showed and counted as a plain Ride. Now a ride put on a bike whose type is E-bike (by hand, on the phone, from a Strava export, with Assign rides) becomes an e-bike ride, and so do a bike's rides when its type is changed to E-bike. Most head units don't mark an e-bike in their files, so the bike is often the only way to tell. A default bike a ride was given automatically doesn't count. Moved to another bike, a ride goes back to the sport it had, unless you've changed its sport yourself since. At the first start after updating, rides already on an e-bike become e-bike rides, and the Tasks page lists them.
- **Garmin activities saved with the wrong sport are found by themselves.** "Check activity types with Garmin" only ran when someone pressed it, so e-bike rides saved as plain rides before 0.7.3 stayed that way. Headwind now makes the same check at every start, from the type Garmin gave each activity the last time it was synced, without asking Garmin. The dashboard and the Import page say when there are some to review on the Activity types page. Nothing changes until you apply them.

### Fixed
- **Activities dated in the future are caught.** A device whose clock was reset can save a ride years ahead: an Avinox unit set back to 1970 gives dates in February 2106. Any activity starting more than a day after now, whether it came from a file, Garmin, the phone or a friend, now goes on the list of activities that look wrong and is left out of the speed and weather charts. On its page, **When did it really start?** takes the real date and time. The track, laps and charts move with it, its weather is looked up again for the right hour, and it's checked again for duplicates, because on the right day it may be a copy of another activity. Importing the file again doesn't offer the wrong date back. A friend's activity is only flagged, since only they can change it. At the first start after updating, those already saved are flagged, and the Tasks page lists them.
- **Slow climbs match their segments.** A ride slower than 2 m/s (4.5 mph) over a segment was always turned away as a false match, so a steep climb pushed or crawled up never counted, not even on the ride the segment was drawn on. On a climb, the slowest speed that counts now depends on how steep it is: an effort counts if it climbs at least 200 m an hour, so a 10% climb at walking pace is an effort. A flat segment with a café stop in the middle still isn't. At the first start after updating, the steep segments are matched again, and the Tasks page says how many efforts were found.

## [0.7.35-beta] - 2026-11-01

### Changed
- **Backups are made in the background.** **Make backup** under **Settings → Backup & Restore** returns at once, and the backup is made while you carry on. The card and the Tasks page say how far it's got, and when it's ready a notice at the top of whatever page is open offers the download (ntfy says so too, when it's set up). It's kept for a day, or until the next one is made. It's also much quicker: photos are stored as they are, not compressed again. Before, the page sat waiting until the whole zip was made, and a reverse proxy's timeout could cut it off.
- **The top bar shows every background job,** not only imports: a backup or a copy for troubleshooting shows there too.
- **Syncing with a friend runs in the background,** as a row on the Tasks page, so a long first sync no longer holds the Friends page.
- **Faster pages and imports.** Every page makes fewer database queries, and the duplicate check during an import or sync no longer reads every nearby activity's recorded data, about three times quicker. Deleting a friend re-checks only the segments their activities were on.

## [0.7.34-beta] - 2026-11-01

### Added
- **A bin for deleted activities.** Deleting an activity of any sport now keeps it whole, photos included, for 30 days. It's listed under **Recently deleted** on the Import page, with **Restore** and **Delete now**. Restoring it brings back its segment times, best efforts, gear and Home Assistant totals, and any copies set aside behind it come back with it. After 30 days only its id is kept, so a Garmin sync or a Strava export imported again doesn't bring it back.
- **MQTT over TLS.** **Settings → MQTT** has **Use TLS** (port 8883) and an optional CA file, used by every sensor, the live ride and the water button. **Test connection** checks the certificate.
- **Unused phone tokens are flagged.** The Phones page marks phones not seen for 90 days and revokes them, each with its Watch, with one button. Nothing is revoked without asking.
- **Weight chart detail.** Hover or tap a day on the weight chart to see its weigh-in, trend, change and where it came from.

### Security
- **The admin password is stored as a hash.** The saved sign-in now holds a salted scrypt hash, not the password itself. It's converted at the first start, and browsers already signed in stay signed in. Changing the password in Settings no longer writes it into `.env`; setting `APP_PASSWORD` in the environment still works to get back in. Going back to an older version afterwards: it can't read the hash, so it signs in with `APP_PASSWORD`. With none set, it makes a new password (shown in the logs) and overwrites the saved sign-in, so the password you chose in Settings is lost, even after upgrading again. With `APP_PASSWORD` set, the saved sign-in is left alone and works again once you upgrade.
- **New passwords need at least 10 characters,** in Settings and in the setup wizard.
- **Sign-in locks for everyone after 30 failures in 5 minutes,** beside the existing 8 per address, so changing the forwarded address no longer gets round the lockout.
- **The Docker image runs as a user, not root.** Headwind now runs as `headwind` (uid and gid 1000). At start the container hands the data folder and the Garmin token folder to that user, then gives up root. Nothing to do when updating. On a Linux host the files in `./data` and `./garmin_tokens` will belong to uid 1000 afterwards. If they can't be handed over (a read-only mount, NFS), Headwind says so in the log and runs as root as before. Going back to an older image still works. Running the container with `--user` works too, once the folders belong to that user.
- **The image's Python packages are pinned** to exact versions and hashes (`requirements.lock`), so the same release builds the same packages every time, and CI checks them for known vulnerabilities.
- **Request size limits before signing in:** 1 MB for anyone not signed in, 64 MB for the phone app, and the large limits only for the Strava export import and backup restores.
- **A Content Security Policy** allows scripts only from this server and the exact Chart.js, Leaflet and html5-qrcode versions the pages use.
- **Errors show a short message with a log id,** not the exception text, which could carry file paths and internals. That includes friend syncs.
- **Pictures over 50 megapixels are refused** with a clear message, so one upload can't take half a gigabyte to decode.
- **Every HTML escaper escapes quotes,** and the default-bike buttons on the Gear pages no longer send you back to the Referer.
- **Friend feed tokens are hidden in the logs,** as phone tokens already were.
- **Debug mode listens on this computer only** (`HEADWIND_DEBUG=1`), with a warning in the log.

### Changed
- **A health check.** `docker ps` shows the container `healthy` once `/login` answers. A first start on a new version shows `starting` while the database is migrated.

### Fixed
- **A generated password that can't be saved** (a read-only data folder) is kept for as long as the server runs, instead of changing on every request and signing everyone out.
- **Activity lists open on the newest month with activities.** On the 1st of a month, before anything was recorded, every month was collapsed.
- **Recovery on a phone:** today's heart-rate and Body Battery charts stack instead of each taking half the screen.
- **The setup wizard's restore errors** no longer end in a server error.

## [0.7.33-beta] - 2026-10-31

### Added
- **More map types, on every map.** The activity, segment, heatmap, route planner, road roughness and duplicate-check maps share one picker (the layers button in the map's corner): Esri satellite, satellite + labels, dark, light and topographic, OpenTopoMap (contours, paths and tracks) and CyclOSM (surfaces, mountain bike trail grades), with Waymarked Trails' mountain bike and cycle routes over any of them. Each kind of map remembers your choice in the browser. The heatmap's HD export draws whichever you've picked.
- **Thunderforest and Ordnance Survey maps with your own key.** Save a free key under **Settings → Maps** and OpenCycleMap and Thunderforest Outdoors, or OS Outdoor (Great Britain), join the picker. Keys are encrypted like the other saved keys. Only OS's free zoom levels are used; closer in, they're enlarged.
- **Direction arrows and distance markers on an activity's map.** Chevrons along the track show which way it went, and a marker every mile or km (every 2, 5 or 10 when zoomed out) shows how far along it is. Each has a switch in the picker, and so do the wind arrows.
- **Charts and the map follow each other.** Hovering the elevation, speed, pace, heart rate, power or cadence chart marks the spot on the map, and moving along the track on the map shows that spot on every chart.

## [0.7.32-beta] - 2026-10-31

### Added
- **Garmin activities that aren't here link to Garmin Connect.** On the import page, each name under "In Garmin, not here" and "Deleted here, still in Garmin" opens that activity on Garmin Connect, to check it before bringing it in or back.

## [0.7.31-beta] - 2026-10-31

### Added
- **A backup that keeps your saved keys on another server.** Tick **Include the secrets key** under **Settings → Backup & Restore** and the zip (`headwind-backup-with-secrets.zip`) carries the key your saved passwords and API keys are encrypted with. Restoring it on another server, from Settings or the setup wizard, keeps them, encrypted again with that server's own key. Anyone else who gets that zip can read them too, so keep it safe; a backup without the tick still leaves the key out.
- **A copy of the database that's safe to share for troubleshooting.** **Tasks → Make a copy for troubleshooting** gives a zip without any password, key or token, without addresses (Home Assistant, MQTT, Ollama, ntfy, friends' servers), without friends' names, activities, segments or foods, and without photos or avatars. Optionally without GPS too, or without the recorded streams altogether. It's made in the background: the page says when it's ready to download, and it's deleted after a day.
- **iPhone: a pairing link asks before it pairs.** A `headwind://pair` link opened from outside the app now asks "Pair with <server>?" first, as switching servers already did, and switching says how many recordings will wait for the current server.

### Security
- **The Garmin sign-in tokens are encrypted** with the same key as the other saved secrets, so a copy of the token folder on its own signs nobody in. The next sync encrypts the file it finds.
- **Old copies of the database are encrypted too.** The copies Headwind keeps beside the database before an upgrade or a restore (`bike.db.pre-0.7.0`, `bike.db.pre-restore` and the like) have their plain passwords and tokens encrypted at every start, and the ones nothing uses any more emptied.
- **Unused secret columns are gone.** The Strava API tokens from before Headwind (read by nothing) and the old shared friend feed token (moved to a per-friend token since 0.6.1) are emptied and their columns dropped at the first start. An older version started on this database adds the feed token column back, empty.

### Fixed
- **iPhone: a recording uploads to the server it was made for.** After pairing with another server, recordings made before the switch went to the new one. Each now keeps its server, and its upload, photos and bike change go only there; one waiting for another server says so under Recordings, with **Upload to <server> instead** in its menu. Recordings from before this update go to whichever server they upload to next.

## [0.7.30-beta] - 2026-10-31

### Added
- **Connect a friend with a code or a QR code.** On the Friends page, enter a friend's name, choose what they see (activities, segments, foods, and which dates) and press **Create Code**: you get a QR code and a code starting `hwfc_`, holding your address and a token of their own, shown once. They scan the QR with the Headwind iPhone app, or paste the code into **Friends → Add a Friend**, then pick the rider to follow, with no address and token to copy by hand. The page says which address the code holds and warns when it's one only your home network can reach (set `APP_URL` to your https address). A Headwind that doesn't read codes yet can still be sent the address and token.
- **Friends in the iPhone app.** Settings → **Share with a friend** makes a code and QR code from the phone, with the same choices, for the address the phone is paired with. Settings → **Add a friend** adds one from their code: scanned, pasted, or opened from the Camera app.

## [0.7.29-beta] - 2026-10-31

### Added
- **Allow all for Apple Health.** One switch at the top of the app's Apple Health settings turns every kind of data on, asked for in one Health sheet; the separate switches stay for choosing some. A server too old for Apple Health now says so, instead of "HTTP 404".

### Fixed
- **The iPhone app draws a Zwift ride over its Zwift world.** The activity page put the track on Apple's map, so a Watopia ride sat out at sea near the Solomon Islands. It's now drawn over the world's own map alone, as on the web, opened on the track: pinch to zoom, drag to look around, double-tap to fit the track again.
- **The Recovery page shows Apple Health's days.** It read Garmin alone, so a rider whose iPhone sends Apple Health saw "No Garmin data yet". It now takes Garmin's figure for a day that has one and Apple Health's otherwise, says where the figures came from, hides the Body Battery and Stress cards when there are none, and marks Apple's HRV as SDNN (not comparable with Garmin's overnight figure).
- **Steps lists Apple Health as a source.** A day's steps from Apple Health showed no source in the breakdown; it's now listed beside Manual, Phone, Watch and Garmin.

## [0.7.28-beta] - 2026-10-31

### Added
- **The iPhone and Apple Watch app records every sport.** Besides rides, runs, walks and hikes: open-water swims with GPS, and timed sessions with no track (an indoor ride, a treadmill run, a pool swim, strength, HIIT and yoga). On the Watch each is the matching Apple Health workout, with heart rate and calories, the pool's length for counting lengths, and water lock for swims. The iPhone records everything but swims.
- **Strength, HIIT and Yoga are sports.** Each has its own totals (they never add to a ride's or a run's), and Garmin's strength_training and hiit, Strava's "Weight Training" and "Crossfit", and Apple's strength, core, HIIT and yoga workouts come in as them. A strength or yoga session needs no distance, and gets an estimate of its calories when it has none.
- **Apple Health as a health source, from the iPhone app.** Switch on any of steps, resting heart rate, HRV, sleep, weight, body fat and calories in the app's Settings, and choose how far back to send. For riders without a Garmin, or days without one: Garmin's figure wins for a day it has. Apple's HRV (SDNN through the day) is kept apart from Garmin's overnight figure and labelled as such. Workouts from other apps (Apple's Workout app, Peloton) can come in too, with their route and heart rate. **Remove** in the app deletes the daily figures and weigh-ins it sent from the server.
- **Activities on the phone.** A new tab lists every activity of every sport, with search and a sport filter, and opens each with its map, the numbers that suit its sport, its charts and its photos.
- **Photos from the phone.** Add photos to an activity in the app, or to a recording before it's uploaded (they wait on the phone and go up after it). They're shrunk to 1600 px JPEGs on the phone, so iPhone HEIC pictures work.
- **Manage an activity's photos in the app.** Take one with the camera as well as picking from the library, and watch each upload on its own tile (a failed one can be tried again). Delete asks first, and several can be selected and deleted at once. Drag photos into a new order (the first is the activity's cover) and give each a caption. A recording's photos still waiting on the phone can be removed and put in order too, and go up in that order.
- **The Overview shows every sport.** A card per sport (rides, on foot, swims, and each other sport you do) for the week, month, year and all time, and a 12-week chart of one sport by distance or every sport by time.
- **iPhone Duo.** The app turns with the phone and spreads out on the open screen: cards side by side, the Record map beside its controls, Activities beside the one that's open. Folding or unfolding mid-ride loses nothing.
- **The Action button on Apple Watch Ultra.** Choose Headwind under Settings > Action Button > Workout and the button starts the workout you pick there; a press during it pauses or resumes, as does pressing it with the side button.
- **The Watch uploads by itself.** When the iPhone isn't with it, a ride goes straight to the server over Wi-Fi or cellular, with a token of the Watch's own (listed on the Phones page under the phone, and revoked with it). With the phone nearby it still goes through the phone.
- **Power and cadence from the Watch.** A power meter or cadence sensor paired with the Watch is recorded on every point and shown during the ride.

### Security
- **A friend's server could run script on your Friends page.** The name its feed sent replaced the one you gave the friend on every sync, and went into the **Token** button's prompt unescaped for JavaScript, so a quote in it ran code as you when you clicked it. The friend keeps the name you typed when adding them, and no name goes into an inline script any more (the Goals page's delete and leave confirmations too).
- **A product or photo title could run script in the nutrition photo picker.** Open Food Facts names (anyone can edit them) and Wikimedia file titles went into a `title="…"` with their quotes left as they were. They're escaped now, as are route names in the route builder.

### Fixed
- **Security headers on every install, not only the public demo.** Pages can no longer be framed by another site (clickjacking), the browser won't guess file types, and full URLs aren't sent to other sites. A small Content-Security-Policy forbids framing, `<base>` and plugins. Over HTTPS (directly, or through a trusted proxy that says so) Headwind also sends HSTS for a year, so browsers stop trying plain HTTP; a plain-HTTP LAN install doesn't get it.
- **A session timed on a phone abroad kept the server's clock.** The time zone it was sent with was cut off, so a 6.30 pm session in New York was saved as 6.30 pm in London.
- **The phone API refuses an upload bigger than the app ever sends** (64 MB) instead of the 2 GB the web's Strava export import allows.
- **Faster lists in the app.** The activity list no longer reads each activity's whole track for its thumbnail, and the Perform tab finds every segment's fastest time in one query.

## [0.7.27-beta] - 2026-10-27

### Added
- **Gear to check: activities recorded twice on different gear.** When the same activity came in twice (a Garmin ride and its Strava copy, say) and both recordings had a bike or shoes, the one kept stayed on its own without a word, often the default bike while the Strava copy named the bike you rode. Now the activity says so, the dashboard shows how many there are, and **Gear → Gear to check** lists them: use the other recording's gear or keep the one it has, one at a time or all at once. A default the other recording was only given doesn't count; the bike or shoes its Strava export names do, once matched to yours.

### Fixed
- **"Use that recording instead" keeps the activity's bike.** Swapping in the other recording lost the bike, kit, commute tick, notes and photos the activity had. They now stay with it.

## [0.7.26-beta] - 2026-10-27

### Fixed
- **An activity's link back to the list keeps your filters.** The Activities (or Workouts) link at the top of an activity went to the bare list, dropping the search, dates, distances, sports and gear. It now goes back to the list as you left it, even after stepping through with Prev and Next.
- **"Indoor ride" no longer shows twice in the sport filter.** Strava's export and the Garmin sync spell some sports differently (Strava's "Virtual Ride" against Garmin's), so a rider with both saw each spelling listed. Strava's names are now saved as Headwind's, by the Strava export import and by a friend's sync, and activities already saved under Strava's names are renamed at start-up, as the Tasks page says.
- **Comparing a Zwift ride's recordings draws them over its world's map.** The compare page drew satellite tiles, so the two tracks sat out at sea near the Solomon Islands. It now draws them over the Zwift world's map alone, as the ride page does.

## [0.7.25-beta] - 2026-10-27

### Added
- **Zwift runs and treadmill runs.** A run on a treadmill or in Zwift is an **Indoor run**, however it arrives: from Garmin (its virtual and treadmill runs), a FIT file, a GPX, a Strava export, or typed in by hand. Like a Zwift ride, it has no weather, stays on your home clock, is drawn over its Zwift world's map, is left off the heatmap unless you include it, and has no segments. It gets your running shoes unless you give indoor runs a default of their own.
- **Indoor best times of their own.** Zwift rides, turbo sessions, Zwift runs and treadmill runs no longer count towards your best times: the Data page and your profile show them in **Indoor ride** and **Indoor run** tables beside the outdoor ones. They don't show on the phone's Perform tab either, and the AI coach compares an indoor ride only with your other indoor rides.
- **Indoor rides and runs no longer earn badges for distance, climbing, speed or weather.** A Zwift century, Alpe du Zwift or a treadmill 10K still counts as a ride or run, and towards your hours and days of training, but not towards the miles, Everests, 5K times, top speeds or cold-weather rides, which are for the road. On the profile, a badge already earned with help from indoor miles moves to the outdoor activity that earns it now.
- **The weight chart's milestone lines can be switched off.** A **milestone lines** box under the chart hides the line at every stone (or 5 kg) lost, and the choice is remembered.

### Fixed
- **Zwift rides have no weather.** Watopia and Zwift's other made-up worlds sit on open sea near the Solomon Islands, so a Zwift ride got that spot's tropical weather (a Watopia ride on a cold evening came out at 25°C). Zwift rides now get none, the weather already on them is cleared at start-up, and they stay out of the weather analytics. A Zwift ride's map is its world's map alone, with no satellite map under it.
- **Zwift rides and runs saved as outdoor ones are put right.** A ride or run that starts in one of Zwift's made-up worlds (Watopia, Makuri Islands, France, Crit City) is a Zwift one, whatever its file called it. Those already saved as outdoor ones become indoor ones at start-up: they lose the weather of the open sea near the Solomon Islands, and a start time taken from the Solomon Islands' clock (11 hours ahead of London) goes back to yours. Segment efforts on indoor rides and runs are removed too, since Strava's Zwift runs were matched against your segments on foot.
- **The weight chart reads well over long spans.** Over years of daily weigh-ins the month letters ran into each other and the dots buried the trend line. Now the dates along the bottom are days, months or years to suit the span, the dots shrink and fade behind the trend line when they're packed in, and the weights up the side are round numbers (whole kilos, or stones and quarter stones).

## [0.7.24-beta] - 2026-10-25

### Fixed
- **Activities cropped in Garmin Connect come in cropped.** Garmin keeps the whole recording in the file it hands out, so an activity cropped there came in whole: a walk cropped to 1.7 km came in as 31 km, the drive home included. Now the track is cut to the part Garmin kept, and the distance, moving time, climb and calories are Garmin's. Activities that already came in whole are found once by the daily Garmin check (or straight away by **Full re-sync** in Settings → Garmin Connect) and offered on the Import page with the other re-imports.

## [0.7.23-beta] - 2026-10-25

### Added
- **Asked to import the Strava export again when an update needs it.** Some fixes only reach activities already here when the export is imported again, and nothing used to say so outside a note on the kept export's card. Now a release that brings such a fix lists it, and the Import page shows each rider who imported their export before it what's changed, with **Import again** (or, if the export wasn't kept, where to download it from Strava). The Import menu item carries a badge until then. **Not now** hides it until a later release adds to the list. Riders who imported an export before this version are asked too, from the first release that lists a fix.

### Fixed
- **An activity whose moving time is seconds because of broken timestamps can be put right.** A file whose times bunch at the start and end (an 11.8 km run "moving" for 9 seconds of 70 minutes) was flagged as looking wrong, with no fix but keeping or deleting it. Where the elapsed time makes it believable, the dashboard's "looks wrong" list and the activity's page now offer **Use the elapsed time**, and the activity's page then shows the file's moving time.

## [0.7.22-beta] - 2026-10-25

### Added
- **"Looks wrong" checks for every sport.** Runs, walks, hikes and swims are flagged when they can't be real (a walk at 20 km/h, a run faster than any record, a swim with nothing recorded), and every sport when its heart rate is below 30 or above 230 bpm, or its moving time is seconds against a real distance. Flagged activities of every sport are listed on the dashboard and left out of the speed charts until you keep or delete them. Every activity is checked once when you upgrade.

### Fixed
- **Activities counted twice.** A Strava export imported before 0.7.11 could save again an activity already set aside as a copy of another recording, so the session counted twice in every total. On upgrade each pair is decided again as an import would, and the other recording is set aside, with its photos, commute and gear moved to the one kept.
- **Deleting an activity no longer loses the recordings set aside behind it.** One that's another recording of the same session moves behind that one; otherwise an activity deleted in Garmin brings its other recording back as its own, and one you delete takes them with it. On upgrade, copies an earlier delete left out of sight move behind the activity of the same session that's still here.
- **Ride best times count rides only.** The phone app's Perform tab could name a walk as your fastest 5 or 10 miles on a ride, and the AI coach compared a ride's best times with walks and with other riders' rides.

## [0.7.21-beta] - 2026-10-25

### Changed
- **A lighter Docker image**, about a third smaller (710 MB to 454 MB). The C compiler used to install the packages, the tests and the docs are no longer in it.
- Running the tests from a copy of the code now needs `pip install -r requirements-dev.txt`; pytest is no longer in `requirements.txt`.

## [0.7.20-beta] - 2026-10-25

### Added
- **Same-route comparisons.** An activity's page shows the other times you've done it: the same start, finish and roads, the same way round, the same kind of activity. It ranks this one by moving time, compares it with the last 20 and charts every time. The AI coach gets the same comparison.
- **Goals.** Distance, climbing, time or number of activities for a sport, every week, month or year, measured against an even pace, on a new Goals page and on the dashboard.
- **Challenges with friends.** A race over set dates, sent on the friends feed to the friends you invite. Each instance works out the standings from the activities it syncs.
- **Zwift rides drawn over their Zwift world.** A virtual ride is matched to one of Zwift's 12 worlds and drawn over that world's map on its page, with a switch to hide it. The heatmap leaves virtual rides out by default, with Include and Only Zwift, draws the worlds' maps under their tracks (in the HD export too) and has a button for each world.
- **Tables sort by clicking a column heading**, and a second click turns the order round. The choice stays in the link. Segments and leaderboards, a ride's splits, sets, laps and segments, segment PRs, records, a bike's parts and service log, the nutrition week and Friends all sort.
- **Full re-sync finds what's missing from Garmin.** Activities of a type the sync used to skip are brought in. Any other Garmin activity that isn't here is listed on the Import page under "In Garmin, not here", to bring in or leave out. Garmin activities you deleted here are listed under "Deleted here, still in Garmin", with Bring back.

### Changed
- **Garmin imports every activity type.** Strength training, yoga, pilates, gym equipment, breathwork and the like used to be dropped; now they're saved, as Other workouts with no track until they become sports of their own.
- **Segment names open the segment** on the Segments page; the View button and the ride page's arrow are gone.

## [0.7.19-beta] - 2026-10-25

### Added
- **A default bike for each kind of ride, and for commutes.** A new "Defaults for new activities" card on the Gear page has a line for commutes, mountain bike, gravel, e-bike and indoor rides (and any other kind you've ridden) beside your default bike, which now covers every other ride. A bike's form has the same choices under "Default for new rides". A commute goes on the commute bike whatever its sport; otherwise a ride takes the bike for its kind. Shoes and other gear can have a commute default too. Ticking Commute or changing an activity's sport later picks its gear again, unless you chose it yourself (or the phone, or a Strava export, named it).
- **Apply your defaults to past activities.** The defaults card says how many older activities would get different gear and moves them: those with none, or still on what a default gave them, and, if you tick it, those on other gear too. Rides whose Strava bike you haven't matched yet wait for the match.
- **Strava bikes bring their default sports.** Matching a Strava bike makes it your default for the kinds of ride Strava had it as the default for, where you have none yet.

### Changed
- **One gear page for bikes and shoes.** A bike's page and a pair of shoes' page (and their forms, and their cards on the Gear page) are now the same, with the parts and service log on bikes only. Shoes and other gear gain a photo, distance by year, assigning activities by date for the sports you tick, and speed or pace. Bikes gain a breakdown by sport, first and last used, and their most worn part with a bar at the top. Both say Retire with the date, and list the 10 most recent activities with "See all".
- **Garmin keeps mountain bike and gravel rides.** They used to arrive as plain rides; now they come in as mountain bike and gravel rides, which can be typed in and picked in "change the type" too. Rides an older sync saved as plain rides are offered their kind back by "Check activity types with Garmin" in Settings.
- **A friend's activity is shown, never changed here.** Its page says whose it is and when it was synced, and keeps only the map, charts, segments, splits and GPX. Every change to one is refused, and the selection bar skips them and says how many were a friend's.
- **Retired gear can still be picked for an activity**, listed last and marked retired, so an old activity can be put on what it was done on. A ride on a retired bike no longer shows "No bike chosen".
- **Top-bar actions fit on a phone.** The ride page keeps ‹ and › and puts Download GPX, Open on Strava and Delete in a ⋯ menu; other pages' actions wrap under the title.

### Fixed
- A GPX file whose type is GravelRide was saved as "Other", not a ride.
- Charts on the ride page and a segment's time trend were squashed into their cards; they're now drawn at the size they're shown.
- Each hourly friend sync said the same rides were new; it now counts only the new or changed ones ("Nothing new" when there are none).

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
