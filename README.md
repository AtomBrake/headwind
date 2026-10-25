<div align="center">

# Headwind

**Your rides and runs. Your food. Your hardware. Your friends.**

Self-hosted training analytics for cycling, running, swimming and every other sport, plus nutrition and body tracking — no cloud, no subscription, no one else touching your data.

## 👉 [**TRY THE LIVE DEMO: headwindtest.smerchants.co.uk**](https://headwindtest.smerchants.co.uk)

**Login: `test` / `test`**. A fictional rider, thousands of real routes (home area removed), made-up food diary. Play with anything; it resets every night.

[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Status: beta](https://img.shields.io/badge/status-beta-orange.svg)](CHANGELOG.md)
[![Docker](https://img.shields.io/badge/docker-amd64%20%7C%20arm64-2496ED.svg?logo=docker&logoColor=white)](https://hub.docker.com/r/lordmerchant99/headwind)
[![Buy Me A Coffee](https://img.shields.io/badge/Buy%20Me%20A%20Coffee-Support-FFDD00?logo=buy-me-a-coffee&logoColor=black)](https://buymeacoffee.com/lordmerchant)

<img src="docs/promo/headwind-hero.jpg" alt="Headwind: your rides, your data. A self-hosted cycling archive." width="900">



</div>

---

## Contents

- [What is Headwind?](#what-is-headwind)
- [Beta status — read this first](#beta-status--read-this-first)
- [A quick tour](#a-quick-tour)
- [Every page and feature](#every-page-and-feature)
- [Features](#features)
- [Install](#install) — [Docker](#docker-recommended) · [Raspberry Pi](#raspberry-pi) · [Windows](#windows-experimental) · [From source](#from-source)
- [First run: the setup wizard](#first-run-the-setup-wizard)
- [Configuration](#configuration)
- [Integrations](#integrations) — Garmin · Home Assistant / MQTT · AI coaching · Friends · Notifications
- [Nutrition in depth](#nutrition-in-depth)
- [Putting it on the internet safely](#putting-it-on-the-internet-safely)
- [Backups, updates and your data](#backups-updates-and-your-data)
- [Privacy and telemetry](#privacy-and-telemetry)
- [Security notes](#security-notes)
- [The Android app](#the-android-app)
- [Troubleshooting](#troubleshooting)
- [How it works](#how-it-works) — stack, layout, data model
- [Known limitations and roadmap](#known-limitations-and-roadmap)
- [Development](#development)
- [Acknowledgements and licence](#acknowledgements-and-licence)

---

## What is Headwind?

Headwind is a single self-hosted web app that brings together the things most athletes spread across four or five services. It started as a cycling app, and rides are still its deepest part, but runs, walks, hikes, swims, ski days, paddles, strength sessions and the rest are first-class activities too.

- **Activity analytics** — import from Garmin Connect, FIT/GPX/TCX files or a Strava export; see maps, streams, weather, wind, splits, laps, best times and records for each sport, segments, comparisons with the other times you've done the same route, goals, and a GPS heatmap of everywhere you've been.
- **Gear and maintenance** — bikes, shoes and other kit with photos, a default for each kind of activity (changeable per activity), a calendar to say which bike rode which rides, and mileage on the parts that wear out (chains, cassettes, tyres, bar tape, sealant...) with service log and "due" alerts.
- **Nutrition and body tracking** — a fast food diary with barcode scanning, per-meal "recent foods", saved meals, hydration, weight trend and calorie goals that account for your training.
- **Coaching and automation** — optional AI analysis with your own key (or local Ollama), on demand or as each activity arrives; Home Assistant sensors over MQTT; push notifications.
- **A social layer without a central server** — link your instance to a friend's directly to share activities, segment leaderboards, the heatmap and challenges.

It runs on a Raspberry Pi, a NAS, a spare PC or a VPS. Your data lives in one SQLite file you can copy, back up and inspect. It only talks to services you explicitly configure (plus a few public data APIs listed [below](#privacy-and-telemetry)).

**Design principles**

| | |
|---|---|
| **Yours** | One folder of data. Export any ride as GPX, back up everything as one zip, no lock-in. |
| **Quiet** | No account, no analytics, no ads. A single optional, anonymous install ping — fully disclosed, one-time, opt-out. |
| **One person per instance** | Your stats, your PRs, your coaching. To track someone else, they run their own Headwind and you link them as a friend. |
| **Honest** | It's a beta; this README lists what's rough. The AI coach is deliberately blunt rather than flattering. |

---

## Beta status — read this first

Headwind is a real, working application used daily by its author. The first public release (0.1.0-beta) went through a security and reliability review (restore safety, login hardening, injection fixes, Garmin sync reliability, resource limits), and every release since is listed in the [CHANGELOG](CHANGELOG.md), with any migration it runs at the first start. It is still a beta:

- **Expect rough edges.** Report them — [open an issue](../../issues).
- **Shared admin login.** There is one login for the whole instance. It is not a multi-user system. Don't give the login to people you don't trust with your data.
- **Back up before you upgrade** and before you import years of history.
- **The Android companion app is a work in progress** and not publicly released yet.
- **The arm64 (Raspberry Pi) image and the Windows build are new** and have had little real-world testing.
- **Don't expose it to the internet without HTTPS** — see [Putting it on the internet safely](#putting-it-on-the-internet-safely).

---

## A quick tour

> All images: demo data — a fictional rider "Alex" riding real roads around Hathersage, Castleton, Edale and Bakewell. They were taken before the 0.7 releases, so some pages now look a little different (one shared style across the app, light mode, every sport) and newer pages such as Activities, Goals and Tasks aren't pictured yet.

<img src="docs/promo/riding-analytics.jpg" alt="Built around the riding: every ride, and everywhere you've ridden" width="900">

### Dashboard
Lifetime totals, a 12-week performance chart you can flip between distance, elevation, speed and calories, your goals, and your recent activities with a sport filter.

<img src="docs/screenshots/dashboard.jpg" alt="Dashboard" width="900">

### Activity detail
Satellite map, elevation + heart-rate and cadence charts, weather at the start (temperature, wind speed/direction and a headwind / tailwind / crosswind call computed from your route bearing), and effort comparison. Each page fits its sport: pace and splits for runs, sets and SWOLF for a pool swim, each run of a ski day, laps from your device. **Same route** ranks this activity against every other time you've done the same start, finish and roads, the same way round, and a Zwift ride is drawn over its Zwift world.

<img src="docs/screenshots/ride-detail.jpg" alt="Ride detail" width="900">

### Heatmap
Everywhere you've been, filterable by date range and sport, with HD export (3440×1440). Show your own activities, one friend's, or everyone's together, each in their own colour; Zwift rides are left out unless you include them, and drawn over their Zwift world's map.

<img src="docs/screenshots/heatmap.jpg" alt="Heatmap" width="900">

### Segments and leaderboards
Draw a segment on any ride; Headwind scans your whole history, ranks every effort, charts your trend, rates the difficulty and tracks PRs. Linked friends' segments and efforts appear on the same leaderboard.

<img src="docs/screenshots/segment-leaderboard.jpg" alt="Segment leaderboard" width="900">

### Analytics
Speed (or pace) over time, monthly distance, year-on-year, length distribution, day-of-week, weather scatter charts, best times and records for each sport — all filterable by sport.

<img src="docs/screenshots/analytics.jpg" alt="Analytics" width="900">

<img src="docs/promo/performance-context.jpg" alt="The stuff around the ride matters too: recovery, bodyweight and nutrition beside your cycling data" width="900">

### Nutrition
A diary built for speed: barcode scan, per-meal recent foods, saved meals, hydration, macro rings, and calorie goals that include what you burned riding.

<img src="docs/screenshots/nutrition-day.jpg" alt="Nutrition diary" width="900">

### Smaller (or bigger) portions
Saved a meal but ate less? Scale the whole meal in one tap — weight and every macro together — or open any item and change its weight.

<img src="docs/screenshots/nutrition-meal-portion.jpg" alt="Meal portion scaling" width="900">

### Change the weight, macros follow
Edit the weight of any logged item and calories, protein, carbs, fat and fibre scale in proportion. Entries with no recorded weight get a baseline from the first weight you type.

<img src="docs/screenshots/nutrition-weight-edit.jpg" alt="Editing a food's weight" width="900">

### Weight trend
Daily weigh-ins with a smoothed trend line, rate of change, and progress against your goal. The chart stays readable from a week to years of daily readings, with a line at every stone (or 5 kg) lost that you can switch off.

<img src="docs/screenshots/weight-trend.jpg" alt="Weight trend" width="900">

### Route planner
Plan a route on the map, see distance and the elevation profile, and export it as GPX.

<img src="docs/screenshots/route-planner.jpg" alt="Route planner" width="900">

### Goals and challenges
Set a distance, climbing, time or activity-count goal for a sport, per week, month or year, and see whether you're ahead of an even pace on the Goals page and the dashboard. Challenge linked friends to a race over set dates; each instance works out the standings from the activities it syncs.

### Gear: bikes, shoes, parts and service
Add your bikes, shoes and other kit (with photos) and give each kind of activity a default — road, mountain bike, gravel, e-bike, indoor, commutes, runs — so every new activity lands on the right one. The calendar assigns older activities by date or range, and each bike tracks the mileage on its replaceable parts with a service log and alerts. Full guide: [docs/GEAR.md](docs/GEAR.md).

<img src="docs/screenshots/gear-overview.jpg" alt="Gear: your bikes, with what needs attention" width="900">

<details>
<summary>More: a bike's parts and service log, the assign-by-calendar screen and the per-ride bike picker</summary>

<img src="docs/screenshots/gear-bike.jpg" alt="A bike: odometer, stats, parts with wear bars and the service log" width="900">

<img src="docs/screenshots/gear-bike-assign.jpg" alt="Assign a date range of rides to a bike from the bike's own page" width="900">

<img src="docs/screenshots/gear-assign.jpg" alt="Assign rides to bikes by picking days or a date range on a calendar, with a preview of what will change" width="900">

<img src="docs/screenshots/gear-ride-bike.jpg" alt="The bike picker at the top of a ride" width="900">

</details>

<details>
<summary>More: the segments list</summary>

<img src="docs/screenshots/segments.jpg" alt="Segments list" width="900">

</details>

---

## Every page and feature

All 68 screens below use the same synthetic demo data (a fictional rider on real roads). Open a group to browse it.

<details>
<summary><b>Riding</b> (13 screens)</summary>

**Dashboard: lifetime totals, a 12-week performance chart (distance, elevation, speed, calories) and your recent rides.**

<img src="docs/screenshots/dashboard.jpg" alt="Dashboard: lifetime totals, a 12-week performance chart (distance, elevation, speed, calories) and your recent rides." width="800">

**Ride detail: satellite map, elevation and heart-rate charts, cadence, weather at the start and a headwind/tailwind/crosswind call.**

<img src="docs/screenshots/ride-detail.jpg" alt="Ride detail: satellite map, elevation and heart-rate charts, cadence, weather at the start and a headwind/tailwind/crosswind call." width="800">

**A full ride page with the AI coach's analysis, segment efforts and ride notes.**

<img src="docs/screenshots/ride-detail-ai.jpg" alt="A full ride page with the AI coach's analysis, segment efforts and ride notes." width="800">

**Creating a segment: slide the start and finish markers along the ride, then name it.**

<img src="docs/screenshots/ride-create-segment.jpg" alt="Creating a segment: slide the start and finish markers along the ride, then name it." width="800">

**Segments list with efforts and difficulty.**

<img src="docs/screenshots/segments.jpg" alt="Segments list with efforts and difficulty." width="800">

**Segment leaderboard: every effort ranked, your trend over time, and linked friends' efforts on the same board.**

<img src="docs/screenshots/segment-leaderboard.jpg" alt="Segment leaderboard: every effort ranked, your trend over time, and linked friends' efforts on the same board." width="800">

**GPS heatmap of everywhere you've ridden, filterable by date range and sport.**

<img src="docs/screenshots/heatmap.jpg" alt="GPS heatmap of everywhere you've ridden, filterable by date range and sport." width="800">

**The same heatmap on satellite imagery (also Dark, Light and Satellite + labels, with HD export).**

<img src="docs/screenshots/heatmap-satellite.jpg" alt="The same heatmap on satellite imagery (also Dark, Light and Satellite + labels, with HD export)." width="800">

**Analytics: best efforts, climbing records, speed trend, monthly distance, distribution, weather scatters, and more.**

<img src="docs/screenshots/analytics.jpg" alt="Analytics: best efforts, climbing records, speed trend, monthly distance, distribution, weather scatters, and more." width="800">

**Profile and trophy case: lifetime stats, segment PRs, best efforts and badges.**

<img src="docs/screenshots/profile.jpg" alt="Profile and trophy case: lifetime stats, segment PRs, best efforts and badges." width="800">

**Route planner with a saved route loaded: distance, waypoints and GPX export.**

<img src="docs/screenshots/route-planner.jpg" alt="Route planner with a saved route loaded: distance, waypoints and GPX export." width="800">

**Workouts: every activity that isn't a ride, with search and a sport filter. Distances only add up within a kind, so they never change your ride stats.**

<img src="docs/screenshots/workouts.jpg" alt="Workouts: every activity that isn't a ride, with search and a sport filter." width="800">

**Import: drop in .fit / .gpx / .tcx files or a full Strava export zip.**

<img src="docs/screenshots/import.jpg" alt="Import: drop in .fit / .gpx / .tcx files or a full Strava export zip." width="800">

</details>

<details>
<summary><b>Gear</b> (7 screens)</summary>

**Gear: your bikes with photos, odometers and what needs attention (overdue / due / soon).**

<img src="docs/screenshots/gear-overview.jpg" alt="Gear: your bikes with photos, odometers and what needs attention." width="800">

**A bike: odometer, stats, a distance-by-year chart, every part with replace/check wear bars, and the service log.**

<img src="docs/screenshots/gear-bike.jpg" alt="A bike: odometer, stats, distance by year, parts with wear bars and the service log." width="800">

**On each bike's page: pick a date range and every ride in it goes on that bike (with a live count first).**

<img src="docs/screenshots/gear-bike-assign.jpg" alt="Assign a date range of rides to a bike from the bike's own page." width="800">

**Assign rides to bikes: pick days or a date range on the calendar, choose the bike, see exactly how many rides will change, apply.**

<img src="docs/screenshots/gear-assign.jpg" alt="Assign rides to bikes by calendar with a live preview." width="800">

**Every ride has a Bike picker at the top (new rides get your default bike).**

<img src="docs/screenshots/gear-ride-bike.jpg" alt="The Bike picker on a ride." width="800">

<p><img src="docs/screenshots/m-gear.jpg" alt="Gear on a phone." width="200" title="Gear on a phone."> <img src="docs/screenshots/m-gear-assign.jpg" alt="Assign rides on a phone." width="200" title="Assign rides on a phone."></p>

</details>

<details>
<summary><b>Health and recovery</b> (4 screens)</summary>

**Recovery from Garmin: resting heart rate, body battery, sleep, steps and stress, with 30/60/90-day views.**

<img src="docs/screenshots/recovery.jpg" alt="Recovery from Garmin: resting heart rate, body battery, sleep, steps and stress, with 30/60/90-day views." width="800">

**Steps with a daily goal; log a day by hand if you have no tracker.**

<img src="docs/screenshots/steps.jpg" alt="Steps with a daily goal; log a day by hand if you have no tracker." width="800">

**Weight trend: daily weigh-ins, a smoothed line and your rate of change.**

<img src="docs/screenshots/weight-trend.jpg" alt="Weight trend: daily weigh-ins, a smoothed line and your rate of change." width="800">

**Backfill past weigh-ins in bulk.**

<img src="docs/screenshots/weight-backfill.jpg" alt="Backfill past weigh-ins in bulk." width="800">

</details>

<details>
<summary><b>Nutrition</b> (19 screens)</summary>

**The diary: calories and macro rings, meals, hydration and your weight.**

<img src="docs/screenshots/nutrition-day.jpg" alt="The diary: calories and macro rings, meals, hydration and your weight." width="800">

**"View Nutrition": the day's totals against your goals, by meal, with a macro split.**

<img src="docs/screenshots/nutrition-meal-sheet-day.jpg" alt=""View Nutrition": the day's totals against your goals, by meal, with a macro split." width="800">

**Add food: this meal's recent and most-logged foods first, one tap to log.**

<img src="docs/screenshots/nutrition-find-food-recent.jpg" alt="Add food: this meal's recent and most-logged foods first, one tap to log." width="800">

**Search Open Food Facts by name (barcode scanning is next to it).**

<img src="docs/screenshots/nutrition-search-results.jpg" alt="Search Open Food Facts by name (barcode scanning is next to it)." width="800">

**Go-Tos: your favourites.**

<img src="docs/screenshots/nutrition-find-food-gotos.jpg" alt="Go-Tos: your favourites." width="800">

**Recipes and saved meals, loggable at ½×, 1×, 1½× or 2×.**

<img src="docs/screenshots/nutrition-find-food-recipes.jpg" alt="Recipes and saved meals, loggable at ½×, 1×, 1½× or 2×." width="800">

**My Foods: your own foods, per 100 g.**

<img src="docs/screenshots/nutrition-find-food-myfoods.jpg" alt="My Foods: your own foods, per 100 g." width="800">

**Change a food's weight and the calories and macros follow.**

<img src="docs/screenshots/nutrition-weight-edit.jpg" alt="Change a food's weight and the calories and macros follow." width="800">

**"Smaller or bigger portion?": scale every item in a meal at once.**

<img src="docs/screenshots/nutrition-meal-portion.jpg" alt=""Smaller or bigger portion?": scale every item in a meal at once." width="800">

**Manual entry for anything without a barcode.**

<img src="docs/screenshots/nutrition-manual-entry.jpg" alt="Manual entry for anything without a barcode." width="800">

**Daily goals, weight unit, diet start date and goal weight.**

<img src="docs/screenshots/nutrition-goals.jpg" alt="Daily goals, weight unit, diet start date and goal weight." width="800">

**Copy yesterday: a whole day or just one meal.**

<img src="docs/screenshots/nutrition-copy-day.jpg" alt="Copy yesterday: a whole day or just one meal." width="800">

**Weigh in.**

<img src="docs/screenshots/nutrition-weigh-in.jpg" alt="Weigh in." width="800">

**AI food-photo estimate (needs your own AI key).**

<img src="docs/screenshots/nutrition-photo-estimate.jpg" alt="AI food-photo estimate (needs your own AI key)." width="800">

**Import a food diary or recipe from screenshots of another app (needs your own AI key).**

<img src="docs/screenshots/nutrition-screenshot-import.jpg" alt="Import a food diary or recipe from screenshots of another app (needs your own AI key)." width="800">

**Build a meal or recipe from ingredients.**

<img src="docs/screenshots/nutrition-recipe-builder.jpg" alt="Build a meal or recipe from ingredients." width="800">

**Save what you've logged as a reusable meal.**

<img src="docs/screenshots/nutrition-save-as-meal.jpg" alt="Save what you've logged as a reusable meal." width="800">

**Create your own food.**

<img src="docs/screenshots/nutrition-my-food-editor.jpg" alt="Create your own food." width="800">

**Weekly summary: eaten, burned, net and macros per day.**

<img src="docs/screenshots/nutrition-week.jpg" alt="Weekly summary: eaten, burned, net and macros per day." width="800">

</details>

<details>
<summary><b>Social, coaching and settings</b> (7 screens)</summary>

**Friends: your feed token, add a friend by URL + token, and auto-sync.**

<img src="docs/screenshots/friends.jpg" alt="Friends: your feed token, add a friend by URL + token, and auto-sync." width="800">

**AI Coach: your coaching goals, and bulk analysis of rides by date range.**

<img src="docs/screenshots/ai-coach.jpg" alt="AI Coach: your coaching goals, and bulk analysis of rides by date range." width="800">

**Settings: units, login details, AI provider, Garmin Connect, weather backfill, backup and restore.**

<img src="docs/screenshots/settings.jpg" alt="Settings: units, login details, AI provider, Garmin Connect, weather backfill, backup and restore." width="800">

**Home Assistant: connect with a long-lived token and import health readings.**

<img src="docs/screenshots/settings-home-assistant.jpg" alt="Home Assistant: connect with a long-lived token and import health readings." width="800">

**Pair a phone with a QR code and a per-device token (HTTPS required).**

<img src="docs/screenshots/phones-pairing.jpg" alt="Pair a phone with a QR code and a per-device token (HTTPS required)." width="800">

**About: what's in the app.**

<img src="docs/screenshots/about.jpg" alt="About: what's in the app." width="800">

**Sign in.**

<img src="docs/screenshots/login.jpg" alt="Sign in." width="800">

</details>

<details>
<summary><b>The setup wizard</b> (7 screens)</summary>

**Step 1: your name (or restore from a backup).**

<img src="docs/screenshots/wizard-1-name.jpg" alt="Step 1: your name (or restore from a backup)." width="800">

**Step 2: units.**

<img src="docs/screenshots/wizard-2-units.jpg" alt="Step 2: units." width="800">

**Step 3: Garmin Connect (optional, MFA-capable).**

<img src="docs/screenshots/wizard-3-garmin.jpg" alt="Step 3: Garmin Connect (optional, MFA-capable)." width="800">

**Step 4: Home Assistant (optional).**

<img src="docs/screenshots/wizard-4-home-assistant.jpg" alt="Step 4: Home Assistant (optional)." width="800">

**Choosing a health entity from Home Assistant.**

<img src="docs/screenshots/wizard-4b-ha-entity-picker.jpg" alt="Choosing a health entity from Home Assistant." width="800">

**Step 5: the one-time anonymous install ping, with a permanent opt-out.**

<img src="docs/screenshots/wizard-5-telemetry.jpg" alt="Step 5: the one-time anonymous install ping, with a permanent opt-out." width="800">

**Step 6: done.**

<img src="docs/screenshots/wizard-6-done.jpg" alt="Step 6: done." width="800">

</details>

<details>
<summary><b>On your phone (the nutrition tracker installs as a PWA)</b> (11 screens)</summary>

<p><img src="docs/screenshots/m-dashboard.jpg" alt="Dashboard." width="200" title="Dashboard."> <img src="docs/screenshots/m-ride-detail.jpg" alt="Ride detail." width="200" title="Ride detail."> <img src="docs/screenshots/m-heatmap.jpg" alt="Heatmap." width="200" title="Heatmap."> <img src="docs/screenshots/m-segment-leaderboard.jpg" alt="Segment leaderboard." width="200" title="Segment leaderboard."> <img src="docs/screenshots/m-recovery.jpg" alt="Recovery." width="200" title="Recovery."> <img src="docs/screenshots/m-nutrition-day.jpg" alt="Diary." width="200" title="Diary."> <img src="docs/screenshots/m-nutrition-add-food.jpg" alt="Add food: recent first." width="200" title="Add food: recent first."> <img src="docs/screenshots/m-nutrition-meal-portion.jpg" alt="Meal portion scaling." width="200" title="Meal portion scaling."> <img src="docs/screenshots/m-nutrition-food-detail.jpg" alt="Weight edit with macros following." width="200" title="Weight edit with macros following."> <img src="docs/screenshots/m-weight-trend.jpg" alt="Weight trend." width="200" title="Weight trend."> <img src="docs/screenshots/m-settings.jpg" alt="Settings." width="200" title="Settings."></p>

</details>

---

## Features

### Activities and import
- **Every sport** — road, mountain bike, gravel, e-bike and indoor (Zwift) rides; runs, trail runs, walks and hikes; pool and open-water swims; ski and snowboard days; paddles, surfs and sails; strength, yoga and anything else with no distance. Distances only ever add up within a kind, so a run never changes your ride stats.
- **Garmin Connect sync** — activities of every type *and* daily recovery data; MFA-capable connect flow in the browser (no command line); incremental sync that re-scans the last day so a second same-day activity is never missed and failed downloads are retried. Activities deleted or changed in Garmin later are flagged for review (see [Garmin Connect](#garmin-connect)).
- **File import** — `.fit`, `.gpx`, `.tcx` (and gzipped variants), or a **Strava data-export zip**, with a live progress bar. A file keeps its own sport. From a Strava export Headwind also takes Strava's own distance and moving time, your bikes and shoes, photos, commutes and segments, and keeps the export so you can **Import again** later without uploading it. When an update brings fixes that only reach activities already here through a re-import, the Import page says what they are and asks you to import the export again (or upload it, if it wasn't kept).
- **Duplicates** — the same activity from Garmin, Strava, a file and the phone is kept once, however it arrived (including a watch's indoor ride and its Zwift copy, and a phone's partial recording of a ride). Importing an activity you already have again offers to repair it from the file. Deleting an activity moves the recordings set aside behind it to another recording of the same session if there is one; otherwise one deleted in Garmin brings its other recording back as its own, and one you delete takes them with it.
- **Start times where each activity happened** — the time zone comes from where it started, so a run abroad shows local time. Your home time zone is set in Settings.
- **Activities page** — every activity in one list, with search, a sport filter and a **Select** bar to edit many at once (delete, change type, set the gear, mark as commutes, rename, download as GPX).
- **Commutes** and **photos** on any activity.
- **GPX export** of any activity.
- **Phone recording** — the Android app records rides and workouts and uploads them (work in progress; see [The Android app](#the-android-app)).
- **Upload endpoint** — `POST /import/api/upload-ride` with an `X-Upload-Token` header (set `RIDE_UPLOAD_TOKEN`) lets a script, a Pi attached to a bike computer, or an automation push GPX files in.

### Activity pages and analytics
- Satellite map, speed/elevation/heart-rate/power/cadence streams, wind overlay, co-rider badges.
- **Pages that fit the sport** — pace and splits per mile or km on foot; pace per 100 m, sets, strokes and SWOLF for swims; each run of a ski day with vertical descent; no climb on the water; laps from your device for any sport.
- **Same route** — the other times you've done this activity's route (same start, finish and roads, same way round, same kind of activity), ranked by moving time, compared with the last 20 and charted. The AI coach gets the same comparison.
- **Zwift rides** are matched to one of Zwift's worlds and drawn over its map.
- Weather at the start of every activity from Open-Meteo (free, no key), including a backfill for history.
- Analytics: speed or pace trend with rolling average, monthly distance, year-on-year, distribution, day-of-week, weather scatters; metric/imperial; sport filter.
- **Best times** — fastest 5/10/20/30/50/100 miles on a ride, 1 km to the marathon on foot, 100 m to 3.8 km in the water, with year/month filters, plus **records by sport** (longest, longest time, most climbing, fastest).
- **Trophy case** — badges for riding (counts, distance, elevation, epic rides, speed, climbing, weather, segments), running, walking and hiking, swimming, other sports and all sports together, each linking back to the activity that earned it.
- **Goals** — distance, climbing, time or number of activities for a sport, every week, month or year, measured against an even pace, on the Goals page and the dashboard.
- **Activities that look wrong** — anything that can't be real is flagged on the dashboard and its own page, and left out of the speed and weather charts until you keep it or delete it: a ride at 2,500 mph, a walk at 20 km/h, a run faster than any record, a swim with nothing recorded, a moving time of seconds against a real distance, or a heart rate below 30 or above 230 bpm (every sport). The limits are loose: hard but real days pass. Where it can, the flag offers a fix: Strava's climb in place of a file's impossible one, or the elapsed time when a file's broken timestamps made the moving time seconds.
- **Recovery** (Garmin) — resting HR, HRV, sleep score and body battery with 30/60/90-day charts.
- Tables sort by clicking a column heading.

### Segments
- Define a segment by clicking start and end on an activity's map; Headwind **retroactively scans** every activity of that kind.
- Per-effort history, PRs, trend chart, difficulty rating, rolling average.
- If a segment's stored route shape is missing, Headwind rebuilds it from the activity it was drawn on (or a matching effort) — and says "route shape unavailable" instead of drawing a misleading straight line.
- Segments are shared both ways with linked friends.
- **Ride segments and on-foot segments.** Rides (bike and e-bike) only match ride segments; runs, walks and hikes only match on-foot segments, which show pace. The Segments page has a tab for each, a segment can be switched between them from its own page, and ride leaderboards filter **All / Bike / E-bike** so e-bike efforts never take a pedal PR.

### Phone sensors and live rides (Android app 0.18+)
- The Android app can record the phone's motion sensors (shake, tilt, barometer) once a second and upload them as a **sidecar** that Headwind attaches to the ride it overlaps in time, so you can ride with a Garmin Edge as the main recorder and still get roughness, tilt and a barometric climb on the ride page ("Sensors only" mode), or record them with a phone-recorded ride.
- **Share live with Home Assistant** streams position, speed and sensor readings every few seconds to Headwind, which publishes them as Live Ride sensors and a device tracker, so the example dashboard's **Live** tab can show the ride as it happens.

### Running in Home Assistant
- Best times for 1 km, 1 mile, 3 km, 5 km, 10 km, 15 km, half and full marathon, worked out from the GPS of your recorded runs (the fastest stretch of that distance inside any one run), plus pace, weekly/monthly/yearly totals, 12 weeks of distance, recent runs and the latest route, are shown in Home Assistant on a **Running** tab (see `docs/ha`). Every other sport has its own totals sensors too.

### Nutrition and body
- Barcode scanner (phone camera) and text search, backed by **Open Food Facts** — no API key.
- Meals: Breakfast, Lunch, Dinner, Snacks, **Ride fuel** and **Recovery**.
- **Recent foods per meal** — pick *Add* on a meal and see what you most often (and most recently) log for that meal.
- **Saved meals** and **recipes**, **Go-Tos** (favourites), **My Foods** (your own foods, per-100 g).
- Edit any entry's weight and the macros rescale; scale a whole meal with one tap.
- Calorie and macro goals, with an estimated daily burn that includes your rides; weekly view; "copy yesterday".
- Hydration logging with a daily goal.
- Weight tracking with a smoothed (EMA) trend, goal weight and projected finish, on its own **Weight** page under Health with a table of weigh-ins (Garmin weigh-ins count as scale readings). Lines at every stone or 5 kg lost can be switched off.
- Optional **AI food-photo estimate** and **screenshot import** (e.g. from another food app) with your own key.
- Installable as a PWA on iOS/Android.

### Gear and maintenance
- **Bikes** with photos, type, brand/model/year and any mileage from before Headwind.
- **Shoes and other gear** — shoes, wetsuits, skis, boards, boats — with a photo, distance and time added up from their activities, and a replace-at distance (700 km to start with for shoes) with nudges at 90%, 100% and 125%. Shoes in a Strava export come in with their activities.
- **Defaults for new activities** — a default bike for commutes, mountain bike, gravel, e-bike and indoor rides (and any other kind you've ridden) beside one for every other ride, and default shoes or kit for each sport. Every new activity lands on its default (Garmin sync, file import, phone recording, typed-in activity), and **Apply to past activities** brings older ones in line. Matching a Strava bike brings in the sports Strava had it as the default for.
- **Assign by calendar** — click days or set a range ("everything from 1 March to today"), choose the bike and see exactly how many rides change before you apply. A gear picker on every activity changes just that one, and the Activities page lists the activities with no gear (only for sports you have gear for).
- **One page for every piece of gear** — odometer, activities, distance, time, climbing, speed or pace, a breakdown by sport, first and last used, longest activity, distance by year and the 10 most recent activities. **Retire** keeps its history, and retired gear can still be picked for an old activity.
- **Replaceable parts** — chain, cassette, chainrings, tyres, tubeless sealant, brake pads/rotors/fluid, cables, bar tape, headset and wheel bearings, bottom bracket, cleats, suspension service or your own, each with editable *check* and *replace* intervals by distance and/or days.
- **Service log** — replaced, serviced, inspected, cleaned...; replacing a part retires it (keeping its lifetime) and fits a fresh one.
- **Alerts** — soon / due / overdue, once each, via ntfy and Home Assistant push; a dashboard card shows what needs attention.
- Mileage is always **computed from your rides**, so fixing a ride's bike fixes every part. Photos are included in backups. See [docs/GEAR.md](docs/GEAR.md).

### Social (peer-to-peer)
- Add a friend's Headwind by URL + feed token; their activities (rides, runs, walks, any sport), segments and shared foods sync directly into your database. No central server.
- **One feed token per friend**, each with its own date range (all, past 6 months, past month, from today), so you can cut one person off without touching the others.
- A friend's activities are shown, never changed, on your instance. The heatmap shows yours, one friend's or everyone's together.
- **Challenges** — a race over set dates, sent to the friends you invite.
- Auto-sync every 15 minutes by default (off / 15 / 30 / 60 / 120). Only new or changed activities are fetched, and edits and deletions reach your friends at their next sync.
- Works over LAN, VPN or the public internet (use HTTPS).

### Automation and coaching
- **AI coaching** (optional): GPT models, **Claude**, or a local **Ollama** model; the prompt includes activity stats, weather, same-route comparisons, similar past activities, segment comparisons, other training and recovery. Ten personalities (including a refreshingly rude one) and your own coaching goals. **Analyse New Rides** writes the notes for each new activity as it arrives.
- **Home Assistant / MQTT**: ride, every-sport, recovery, nutrition, hydration and weight sensors with auto-discovery; notifications; dashboards.
- **Notifications** — activity-synced alerts through Home Assistant's companion app (an ntfy hook exists in the code but has no settings screen yet).

### Running it
- **Tasks page** — what Headwind is doing in the background: the Garmin sync, health history, friend sync, the MQTT link, imports in progress, the one-off repairs an update runs and what each changed, and the Garmin activities it gave up on, with Try again.
- **Light, dark or auto** — follows each device's setting by default; charts and maps change with the page.
- Works on a phone: the layout and each page's top-bar actions fit a small screen.

---

## Install

### Docker (recommended)

You need Docker with the Compose plugin. No clone required:

```bash
mkdir headwind && cd headwind
curl -O https://raw.githubusercontent.com/lordmaa/headwind/main/docker-compose.yml
curl -O https://raw.githubusercontent.com/lordmaa/headwind/main/.env.example

docker compose up -d
```

Open **http://localhost:5001**. On the first start Headwind generates a random signing key and an admin password and prints it **once** in the logs:

```bash
docker logs headwind 2>&1 | grep -A3 "generated one"
```

Sign in with `admin` and that password, then change it under **Settings**. To choose your own credentials instead, copy `.env.example` to `.env` and set `SECRET_KEY`, `APP_USERNAME` and `APP_PASSWORD` *before* the first `docker compose up`.

Data lives in `./data` (database, avatars, food photos, generated login) and `./garmin_tokens`, next to your `docker-compose.yml`, so it survives restarts and upgrades.

Images are published for **amd64 and arm64** on Docker Hub: `lordmerchant99/headwind` (tags: `latest`, `0.1.0-beta`).

### Raspberry Pi

The same Docker instructions work on a Raspberry Pi 4/5 (64-bit OS). The arm64 image is new — if something misbehaves, please report it. Tips:

- Keep `./data` on an SSD or good SD card; SQLite is happiest on reliable storage.
- Expect the first Garmin history sync and weather backfill to take longer than on a PC.
- Running **Watchtower** will keep the image current automatically — convenient, but updates then happen without you watching.

### Portainer

Deploy as a stack using the Compose file from this repo and set `SECRET_KEY`, `APP_USERNAME` and `APP_PASSWORD` under **Environment variables**.

### Windows (experimental)

Download `Headwind-windows-x64.zip` from the [Releases](../../releases) page, extract it somewhere writable (not *Program Files*), and run `Headwind\Headwind.exe`. It runs as a desktop app: a tray icon (bottom right, near the clock — you may need to click the ^ arrow) and Headwind opens in its own app-style window. A dialog shows your first sign-in.

Tray menu (right-click, or double-click to open): **Open Headwind**, **Show sign-in details**, **Open data folder** (`%LOCALAPPDATA%\Headwind`), **Start with Windows**, **Quit Headwind**. Closing the window does *not* stop it (it keeps syncing); use Quit.

- Your data survives updates — replace the extracted folder.
- It listens on this PC only by default. For a phone on your network set `HEADWIND_HOST=0.0.0.0` before launching.
- The build is **unsigned**: SmartScreen will say "unknown publisher" (More info → Run anyway) and some antivirus tools flag PyInstaller apps. If that worries you, use Docker or run from source.
- Build it yourself: `pip install -r requirements.txt waitress pyinstaller` then `python scripts\build_windows.py dist`.

### From source

```bash
git clone https://github.com/lordmaa/headwind.git
cd headwind
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python3 app.py          # http://localhost:5001
```

`python3 app.py` is for development: it listens on all interfaces. Set `HEADWIND_DEBUG=1` for Flask's debugger **only on a machine nobody else can reach**. For anything long-lived use Docker (gunicorn) or put it behind a proper service manager.

To build the Docker image yourself:

```bash
docker compose -f docker-compose.dev.yml up --build
# multi-arch:
docker buildx build --platform linux/amd64,linux/arm64 -t yourname/headwind:dev --push .
```

---

## First run: the setup wizard

A new install walks you through six short steps. Everything except step 1 is skippable and can be changed later in **Settings**.

1. **Your name** — Headwind tracks one person. (Restoring from a backup is also offered here.)
2. **Units** — imperial (mi, mph, ft, st/lb) or metric.
3. **Garmin Connect** — optional. Enter your Garmin email and password; if Garmin asks for an MFA code you'll be prompted in the browser. The password is used only to sign in and isn't kept: Headwind keeps the sign-in tokens Garmin gives it, which renew themselves.
4. **Home Assistant** — optional. Connect to HA with a long-lived token, map health entities and pick a weather entity.
5. **Telemetry** — the exact text of the one-time anonymous ping is shown with a permanent opt-out.
6. **Done** — you land on the dashboard.

No Garmin? Go to **Import** and drop in `.fit` / `.gpx` / `.tcx` files or a Strava export zip.

---

## Configuration

### Environment variables

Set these in a `.env` file next to `docker-compose.yml` (Compose reads it automatically) or in your service environment.

| Variable | Default | What it does |
|---|---|---|
| `SECRET_KEY` | generated | Session signing key. If blank or a known placeholder, a random one is generated and stored in the data folder. |
| `APP_USERNAME` | `admin` | Login username. |
| `APP_PASSWORD` | generated | Login password. If blank or a known placeholder, a random one is generated and printed once in the logs. A password changed in **Settings** persists across container recreation unless you later edit this value. |
| `APP_URL` | `http://localhost:5001` | The URL others (and your phone) reach this instance at — used in notification links and the phone pairing QR code. |
| `DATABASE_URL` | `/data/bike.db` (Docker) | Path to the SQLite database. |
| `TELEMETRY` | *(unset)* | Set to `off` to skip the telemetry question and never send the install ping. |
| `HEADWIND_MULTI_RIDER` | *(unset)* | `1` enables the advanced multi-rider mode (several local riders on one instance). |
| `RIDE_UPLOAD_TOKEN` | *(unset)* | Enables `POST /import/api/upload-ride` (authenticated by the `X-Upload-Token` header). Disabled when unset. |
| `SESSION_COOKIE_SECURE` | `false` | Set to `true` when serving over HTTPS so the login cookie is never sent over plain HTTP. |
| `TRUSTED_PROXIES` | private addresses | Where a reverse proxy may connect from for Headwind to believe its `X-Forwarded-*` headers: comma-separated addresses or networks (e.g. `203.0.113.7` or `10.8.0.0/24`), or `none`. Unset, any loopback or private address is trusted (a proxy on the same machine, LAN or Docker network, or a local tunnel). Set it if your proxy reaches Headwind from a public address. |
| `HEADWIND_APK` | `headwind.apk` in the data folder | The Android APK offered on **Phones → App**. A `version.txt` beside it is shown on that page. |
| `HEADWIND_MQTT_PREFIX` / `HEADWIND_MQTT_NAME` | *(defaults)* | Give a second instance on the same MQTT broker its own entity prefix and device name so they don't collide. |
| `HEADWIND_MQTT_NUTRITION` | `1` | `0` publishes only the ride sensors, not nutrition. |
| `HEADWIND_ENV` | `./.env` | Point an instance at a different env file (useful for running two instances from one code folder). |
| `PORT` | `5001` | Port for `python3 app.py`. |
| `HEADWIND_DEBUG` | *(unset)* | `1` turns on Flask's debug mode for `python3 app.py` (never on a reachable machine). |
| `LOG_LEVEL` | `INFO` | How much goes in the log. `DEBUG` adds every page load and every call to Strava, Garmin, the weather, food lookup and the AI; use it while chasing a fault. |
| `LOG_DIR` | `logs` beside the database (`./data/logs` in Docker) | Where the log files go (`headwind.log`, rotated at 5 MB, 5 kept). `off` keeps the log on the console only. |
| `LOG_FORMAT` | text | `json` writes one JSON object per line, for a log collector. |
| `LOG_CONSOLE_LEVEL` | same as `LOG_LEVEL` | Keep the console quieter than the log file (the Windows build sets `WARNING`). |

Windows-build only: `HEADWIND_HOST`, `HEADWIND_DATA`, `HEADWIND_NO_TRAY`.

### Settings inside the app

The Garmin sign-in, the MQTT broker, Home Assistant URL/token and mappings, AI provider/key/model, coaching personality and goals, display units, home time zone, appearance (Auto, Light or Dark), your login details, backups and the **calorie burn adjustment** (a percentage taken off every burn estimate as it is pulled in, kept reversible; see the changelog) are all configured under **Settings** — not in `.env`. Calorie and macro goals live under **Nutrition → Goals**, and friend-sync is under **Friends → Auto-Sync**.

### Data and volumes

| Path (in the container) | Contents |
|---|---|
| `/data/bike.db` | The SQLite database (WAL mode) — rides, food, weight, settings. Keys, passwords and tokens you enter (AI, MQTT, Home Assistant, friends' feed tokens, the Garmin email) are stored encrypted. |
| `/data/avatars/` | Profile photos. |
| `/data/foodimg/` | Food photos fetched or uploaded. |
| `/data/bikeimg/` | Bike, shoe and other gear photos. |
| `/data/rideimg/` | Photos added to activities (or brought in from a Strava export). |
| `/data/strava_exports/` | The latest Strava export imported, per rider, kept for **Import again**. Not in backups. |
| `/data/logs/` | `headwind.log` and its rotated copies. |
| `/data/.secret_key`, `/data/.admin_login` | The generated session key and login (mode 600). |
| `/data/.secrets_key` | The key those saved secrets are encrypted with (mode 600). Not in backups: keep a copy to move to another server with them. |
| `/app/.garmin_tokens/` | Garmin login tokens (so MFA isn't needed every sync). |

---

## Integrations

### Garmin Connect
- Connect in the wizard or **Settings → Garmin Connect**. MFA is handled in the browser.
- Two things sync: **activities** (downloaded as FIT, deduplicated by Garmin activity id and start time) and **daily health** (resting HR, HRV, sleep, body battery, steps, weigh-ins).
- Every activity type comes in: mountain bike, gravel and e-bike rides keep their kind, and strength, yoga, pilates and the like are saved as Other workouts with no track. Activities typed into Garmin Connect come in from Garmin's activity list. **Settings → Garmin Connect → Check activity types with Garmin** puts right activities an older version saved with the wrong sport.
- An activity you cropped in Garmin Connect comes in cropped. Garmin keeps the whole recording in the file it hands out, so Headwind cuts the track to the part Garmin kept and takes Garmin's distance, moving time, climb and calories. One that came in whole before this was put right is found once by the daily check (below) and offered on the **Import** page with the other re-imports.
- The activity cursor re-scans the most recent day and never advances past a failed download, so rides aren't silently skipped.
- Your Garmin password isn't stored. Headwind keeps Garmin's sign-in tokens in `garmin_tokens` (readable only by Headwind's user) and they renew themselves. If Garmin ever stops accepting them (you changed your Garmin password, or signed out of all devices), syncing stops and Settings and the Tasks page ask you to **Sign in again**. **Sign out** deletes the tokens.
- Signing in to a different Garmin account replaces the tokens of the old one.
- An activity deleted, renamed, given another sport or cropped in Garmin Connect after it came in isn't changed here on its own. Once a day, with activity sync on, Headwind compares the last 90 days in Garmin (and a little further back each day) with what it imported, and lists what changed on the **Import** page and the activity's own page: keep it as it is here, or take Garmin's (delete it here too, use Garmin's name or sport). A cropped one is offered with the other re-imports. **Check now** on the Import page runs it straight away.
- **Full re-sync** (Settings → Garmin Connect) checks everything against all of your Garmin history at once. It also lists any Garmin activity that isn't here under "In Garmin, not here", to bring in or leave out, and the ones you deleted here under "Deleted here, still in Garmin", with **Bring back**.
- Upgrading from a version that stored the password: the next sync swaps it for tokens and deletes it from the database.

### Home Assistant / MQTT
- Enter your broker in **Settings → Home Assistant — MQTT**. Headwind publishes retained **auto-discovery** config, so sensors appear in Home Assistant without YAML.
- Sensors cover lifetime ride totals, last-ride details, recovery metrics, calories eaten / remaining, macros, hydration and weight. State is published on events plus a periodic heartbeat.
- **One publisher per broker:** two Headwinds on one broker must use different `HEADWIND_MQTT_PREFIX` values, or they'll overwrite each other's sensors.
- A separate connection (**Settings → Home Assistant — import health data**) lets Headwind read HA entities (e.g. weight from a smart scale, a weather entity) via a long-lived token.
- The latest ride's route and the segments it crossed, and your run stats (best times, totals, weekly distance, latest run and its route), are published as attribute sensors too, so a dashboard can draw a map and a segment table. The example dashboard in [`docs/ha`](docs/ha) has Today, Body, Running and Riding tabs.
- Example Home Assistant dashboard and automation builders live in [`docs/ha`](docs/ha).

### AI coaching
- In **Settings → AI Provider** choose OpenAI or Claude (paste your key, pick a model) **or** a local **Ollama** (URL + model). Nothing is sent anywhere until you do.
- Pick a coaching personality and add your own goals; the model is also given recent history and the other times you've done the same route, so it can say whether you're improving.
- **Analyse New Rides** (on the AI Coach page, off by default) writes the notes for each new activity from Garmin, the phone or an import as it arrives. Only activities from the last 3 days are analysed, so importing your history doesn't run up a bill.
- Costs are whatever your provider charges; Headwind sends ride summaries, not raw GPS.
- The same key powers the optional food-photo estimate and screenshot import in the nutrition tracker.

### Friends (peer-to-peer)
1. On each instance open **Friends** and make a feed token for the other person (one per friend, with the date range it shares).
2. On your instance add a friend: enter their URL and **Their Feed Token**, then pick the rider to follow.
3. Their activities and segments sync into your database; segments you both have appear on shared leaderboards, and their activities can be shown on the heatmap.
4. To race, start a **challenge** on the Goals page and invite them; it reaches them on the feed.

Sync is pull-based, over HTTP(S). Peer URLs must be `http://` or `https://`; redirects to a different host are refused so a peer can't bounce your token elsewhere. Use HTTPS over the internet.

### Notifications
When a new ride syncs, Headwind can notify you through **Home Assistant** (companion-app notification with a link to the ride). There is also an [ntfy](https://ntfy.sh) hook in `services/notify.py`, but it has no field in the Settings screen yet — treat it as a developer feature for now.

---

## Nutrition in depth

- **Logging fast:** *Add* on a meal shows that meal's recent and frequent foods first — one tap to re-log, or open one to change the weight. Barcode scan and search are right there too.
- **Weights and portions:** every entry stores a weight. Change it and the macros scale proportionally; entries with no recorded weight take the first weight you type as their baseline. On any meal, **Smaller or bigger portion?** (½, ¾, 1¼, 1½, 2×) scales everything in the meal.
- **Saved meals / recipes:** save what you've logged as a meal, or build a recipe from ingredients; log it later at any scale.
- **Your own foods:** override a wrong Open Food Facts entry per barcode (fix the macros once, keep the fix), or add custom foods.
- **Goals:** set a target (e.g. a weekly loss rate) and Headwind works out a daily calorie goal from your profile, steps and rides; it adjusts for ride days. An estimated daily burn is shown alongside what you've eaten.
- **Weight:** log by stone/lb or kg; a smoothed trend line separates real change from daily noise; backfill historic weights in bulk.
- **Hydration** with a daily goal and one-tap +150/+250/+500 ml.
- **Sharing foods:** foods you create can be shared with linked friends (only your own corrections and custom foods — never your diary).

---

## Putting it on the internet safely

Headwind has a login, throttling and cross-site protections, but it is a **single shared admin account guarding years of health and location data**. If you expose it:

1. **Use HTTPS.** Always. Put it behind a reverse proxy or tunnel — e.g. [Caddy](https://caddyserver.com), nginx, Cloudflare Tunnel or Tailscale Serve.
2. **Set `SESSION_COOKIE_SECURE=true`** once you're on HTTPS.
3. **Use a strong password** (the generated one is fine) — never `admin/admin`.
4. Prefer **a VPN** (Tailscale/WireGuard) over opening it to the world if you can.
5. Remember the **phone app only talks to HTTPS** servers.

A minimal Caddyfile:

```
headwind.example.com {
    reverse_proxy localhost:5001
}
```

Behind a proxy Headwind trusts one `X-Forwarded-*` hop, but only from a loopback or private address (or the ones in `TRUSTED_PROXIES`), so a client reaching port 5001 directly can't fake its address to get round the sign-in lockout. Make sure your proxy sets those headers, and keep port 5001 unreachable from outside anyway.

---

## Backups, updates and your data

- **Backup:** **Settings → Backup & Restore → Download** gives one zip: the database, rider avatars, food photos, gear photos and activity photos. It deliberately excludes the Garmin token files, the kept Strava export, your generated login/key files and `.env`. The keys and passwords saved in Settings (AI, MQTT, Home Assistant, friends' feed tokens, the Garmin email) stay encrypted in it, and the key to them (`.secrets_key`) is left out, so a backup shared by mistake doesn't give them away. The rest of your data (rides with GPS, health, food) is in it as it is, so store it accordingly.
- **Restore:** **Settings → Backup & Restore → Restore** (or from the setup wizard on a fresh install). The uploaded database is checked for integrity, migrated and smoke-tested **before** anything live is touched; your current database is kept as `bike.db.pre-restore`; the swap itself is atomic. A backup this version can't use is rejected with "Nothing was changed". Restored on another server, the backup's saved keys and passwords can't be read: Headwind lists which to enter again. To keep them, copy `.secrets_key` from beside the old database to beside the new one and restart.
- **Updating (Docker):** `docker compose pull && docker compose up -d`. Migrations run automatically at start-up. Take a backup first on a beta.
- **Upgrading from an older compose file that used the placeholder `changeme` login:** the placeholder is no longer accepted — a random login is generated; read it from `docker logs`.
- **Moving to a new host:** copy `./data` and `./garmin_tokens`, or restore a backup and sign in to Garmin again.

---

## Privacy and telemetry

**What leaves your machine** — only to services you configure or the public APIs below:

| Service | What for | What's sent |
|---|---|---|
| Garmin Connect | Activity/health sync | Your login (to Garmin), requests for your own data |
| Open-Meteo | Weather, elevation | Ride start coordinates + time |
| Open Food Facts | Food search/barcodes | The barcode or search text |
| Zwift's CDN (`cdn.zwift.com`) | A Zwift world's map, fetched by the server the first time it's drawn | A request for the map image |
| Esri / map tile hosts | Map tiles in your browser | Normal tile requests (your browser's IP) |
| CDNs (unpkg, jsDelivr) | Chart/map libraries in your browser | Normal asset requests |
| Your AI provider (if configured) | Coaching, photo estimates | Ride summaries / the image you submit |
| Your MQTT broker / Home Assistant (if configured) | Automation | Sensor values / notifications |
| Linked friends (if configured) | P2P sync | Activities and segments you've chosen to share, and challenges you send |

**Telemetry (the one exception).** At the end of setup, Headwind can send **one single, one-time, anonymous ping** — a random install id and the version number, nothing else — so the author has a rough idea how many instances exist. No rides, food, weight, location or any personal data is ever sent. The collector does not store IP addresses. The wizard shows this text and a permanent opt-out; you can also set `TELEMETRY=off` in your `.env` to skip the question entirely. The code is [`services/telemetry.py`](services/telemetry.py) — read it rather than take our word for it.

---

## Security notes

The first public release, 0.1.0-beta, shipped after a dedicated review. In short:

- **No default credentials** — placeholder logins are rejected; a random key and password are generated per install.
- **Login throttling** (8 failures / 5 minutes), **session revocation** when the password changes, **cross-site request blocking**, open-redirect fix.
- **Restore** is hardened (no path-chosen uploads, archive allow-list and size limits, integrity check, atomic swap).
- **Stored-content injection** (ride/friend/segment names, friend-supplied route shapes) is escaped or validated; avatars that aren't decodable images are rejected.
- **Resource limits** on imports, archives and peer feeds; peer redirects restricted to the same host.

Since then:

- **Saved secrets are encrypted** — the AI keys, Home Assistant token, MQTT password, friends' feed tokens and the Garmin sign-in are encrypted in the database with a key kept beside it (`.secrets_key`), and never sent back to the Settings page.
- **The Garmin password isn't kept** — only the sign-in tokens Garmin gives back.
- **Feed tokens are per friend**, sent in a header only and compared in constant time; `X-Forwarded-*` headers are only believed from a trusted proxy.
- **A friend's activities can't be changed** on your instance.

Known limits: one shared admin login; the login password is stored in plaintext in your data folder / `.env`; in the advanced multi-rider mode phone devices aren't scoped per rider. See [Known limitations](#known-limitations-and-roadmap). To report a vulnerability, please open a private security advisory on GitHub rather than a public issue.

---

## The Android app

A native Kotlin/Jetpack Compose companion — nutrition logging with barcode scan, ride recording, widgets and Health Connect — exists but is **a work in progress and not publicly released**. It pairs with your server via a QR code (**Phones** page) and a per-device token, and **requires HTTPS**. Until it's released, everything works from the browser, and the nutrition tracker installs as a PWA.

---

## Troubleshooting

| Problem | Try |
|---|---|
| **Can't sign in / forgot the generated password** | `docker logs headwind 2>&1 \| grep -A3 "generated one"`. The login is also stored in `./data/.admin_login`. To set your own, put `APP_PASSWORD` in `.env` and recreate the container. |
| **"Too many attempts"** | The login locks for a few minutes after 8 failures. Wait, or restart the container. |
| **Port 5001 is in use** | Change the left side of `ports` in `docker-compose.yml`, e.g. `"5002:5001"`. |
| **Garmin asks you to sign in again after every restart** | The `garmin_tokens` folder must be a persistent volume; check it's mounted and writable. |
| **Garmin sync finds nothing** | Make sure activity sync is enabled in Settings → Garmin and the account matches the one you connected. Failed rides are retried on the next sync. |
| **Phone app can't pair** | It needs an **HTTPS** address. Put Headwind behind a TLS proxy/tunnel and set `APP_URL` to that address. |
| **Home Assistant sensors missing** | Check the MQTT broker settings, that discovery is enabled in HA, and that no other Headwind uses the same `HEADWIND_MQTT_PREFIX`. |
| **Map is blank** | Your browser needs to reach the tile and CDN hosts listed under [Privacy](#privacy-and-telemetry). |
| **Windows SmartScreen warning** | The build is unsigned. More info → Run anyway, or use Docker. |
| **Restore says "not compatible"** | The backup's database couldn't be migrated. Nothing was changed — your current data is intact. |
| **Reporting a bug** | **Tasks → Download diagnostics** gives one zip to attach: the recent logs, the version, settings without passwords, keys or addresses, and row counts. An error page shows a reference such as `3f9c2a1b`; quote it, and the matching log lines carry `[3f9c2a1b]`. The log file is `./data/logs/headwind.log`. Set `LOG_LEVEL=DEBUG` in `.env` and recreate the container for more detail. |
| **Want to start over** | Stop the container and move `./data` aside (don't delete it until you're sure). |

---

## How it works

**Stack** — Python 3.14 / Flask, SQLite (WAL), Jinja templates, vanilla JavaScript, Chart.js, Leaflet. One gunicorn worker with several threads (background jobs — Garmin sync, MQTT, friend sync — must not be duplicated), shipped as a multi-arch Docker image. Windows build: PyInstaller + waitress + pystray.

**Layout**

```
app.py              application factory, auth guard, background jobs
config.py           environment + settings loading
database.py         schema + forward-only migrations (never drops tables)
routes/             one blueprint per area (rides, segments, nutrition, friends, settings, setup, api_v1 …)
services/           Garmin, parsing, segments, best efforts, AI, MQTT, backup, credentials, limits …
templates/ static/  UI
scripts/            smoke tests, Windows build, helpers
tests/              unit tests
docs/               Home Assistant builders, screenshots, notes
```

**Data model (SQLite)** — `Activity` (every sport, with GPS/HR/power streams last; `Ride` and `Workout` are views of it), `ActivityTrack` (track summaries for the heatmap and segment matching), `ActivityPhoto`, `ActivityDuplicate`, `BestEffort` + `SportEffort` (best times), `Segment` + `SegmentEffort`, `Bike` + `Part` + `ServiceLog` + `BikeDefault` and `Kit` + `KitDefault` (Gear), `Goal`, `Challenge` (+ members, invites), `FoodLog`, `HydrationLog`, `WeightLog`, `SavedMeal(+Item)`, `FoodFavourite`, `CustomFood`/`FoodOverride`, `Friend` + `FeedToken` (+ imported riders/segments/shared foods), `GarminDaily`, `GarminChange`/`GarminMissing`/`GarminFailure` (Garmin review lists), `StravaExport` + `StravaBike`/`StravaKit` (Strava imports), `ImportChange`/`ImportProblem` (Import page review lists), `TaskLog`, `Settings`, `Rider`. Schema changes are applied at start-up by `migrate_db()`; restoring an older backup migrates it first.

---

## Known limitations and roadmap

**Known limitations**
- One shared admin login; the login password is stored in plaintext in the data folder / `.env`.
- Phone-API tokens aren't scoped per rider (only matters in the advanced multi-rider mode).
- The arm64 image and Windows build are new and lightly tested; the Windows build is unsigned.
- Strava's live API is closed to new apps, so Strava is import-only (export zip).
- Some background jobs (large imports, bulk AI) run in-process and can be slow on small hardware.
- Dependencies aren't yet pinned to an exact lock file.

**Roadmap (no promises)**
- Public Android release; per-device scopes.
- Password hashing and optional multi-user.
- Signed Windows build and an installer.
- A proper job queue for imports and bulk AI.
- More analytics and a deeper recovery view.

---

## Development

```bash
pip install -r requirements-dev.txt
python3 -m pytest tests -q                    # unit tests

# End-to-end smoke tests — throwaway instance only (they write data):
d=$(mktemp -d); printf "DATABASE_URL=$d/t.db\nSECRET_KEY=x\nAPP_USERNAME=t\nAPP_PASSWORD=t\n" > $d/env
HEADWIND_ENV=$d/env PYTHONPATH=. python3 scripts/smoke_setup_wizard.py
```

Other smoke scripts: `smoke_client_ops`, `smoke_api_v1`, `smoke_recipes_sync`, `smoke_ride_upload`, `smoke_single_rider`.

- Schema changes go through `migrate_db()` — add columns/tables, never drop/recreate.
- Dates are UK format everywhere (`%-d %b %Y`); the UI uses CSS custom properties (no hard-coded colours).
- Contributions are welcome — open an issue first for anything big. Please include a test or a smoke check with behaviour changes.

---

## Acknowledgements and licence

Headwind stands on a lot of generous open data and software: [Open Food Facts](https://openfoodfacts.org), [Open-Meteo](https://open-meteo.com), [OpenStreetMap](https://www.openstreetmap.org) contributors, [Esri](https://www.esri.com) imagery, [Leaflet](https://leafletjs.com), [Chart.js](https://www.chartjs.org), [Flask](https://flask.palletsprojects.com), [garminconnect](https://github.com/cyberjunky/python-garminconnect), [fitparse](https://github.com/dtcooper/python-fitparse), [gpxpy](https://github.com/tkrajina/gpxpy), [paho-mqtt](https://github.com/eclipse/paho.mqtt.python) and [Home Assistant](https://www.home-assistant.io).

Released under the [MIT licence](LICENSE). If Headwind is useful to you, [a coffee](https://buymeacoffee.com/lordmerchant) is always appreciated.

## Public demo
A locked-down read-mostly demo mode (`HEADWIND_DEMO=1`) with anonymised data is described in [demo/README.md](demo/README.md).
