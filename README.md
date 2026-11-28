<div align="center">

# Headwind

**Your rides and runs. Your food. Your hardware. Your friends.**

Self-hosted training analytics for cycling, running, swimming and every other sport, plus nutrition and body tracking — no cloud, no subscription, no one else touching your data.

## 👉 [**Try the live demo**](https://headwind-demo.atombrake.info)

Press **Enter the demo**: no sign-up, no password. A made-up athlete's two years of rides, walks, runs, hikes, swims and paddles in four national parks, on generated tracks, with a friend, bikes, food and sleep. Play with anything; it resets every night.

[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Status: beta](https://img.shields.io/badge/status-beta-orange.svg)](CHANGELOG.md)
[![Docker](https://img.shields.io/badge/docker-amd64%20%7C%20arm64-2496ED.svg?logo=docker&logoColor=white)](https://github.com/AtomBrake/headwind/pkgs/container/headwind)

Built on [lordmaa's original Headwind](https://github.com/lordmaa/headwind), and now a separate project going its own way: see [Where Headwind came from](#where-headwind-came-from). Found a bug or want something added? [Open an issue](../../issues).

<img src="docs/promo/headwind-hero.jpg" alt="Headwind: your rides, your data. A self-hosted cycling archive." width="900">



</div>

---

## Contents

- [What is Headwind?](#what-is-headwind)
- [Where Headwind came from](#where-headwind-came-from)
- [Beta status — read this first](#beta-status--read-this-first)
- [Bugs, ideas and feature requests](#bugs-ideas-and-feature-requests)
- [A quick tour](#a-quick-tour)
- [Every page and feature](#every-page-and-feature)
- [Features](#features)
- [Install](#install) — [Docker](#docker-recommended) · [Raspberry Pi](#raspberry-pi) · [Windows](#windows-experimental) · [From source](#from-source)
- [First run: the setup wizard](#first-run-the-setup-wizard)
- [Configuration](#configuration) — [Turning features off](#turning-features-off)
- [Integrations](#integrations) — Garmin · Home Assistant / MQTT · AI coaching · Friends · Notifications
- [Nutrition in depth](#nutrition-in-depth)
- [Putting it on the internet safely](#putting-it-on-the-internet-safely) — [Cloudflare Tunnel (recommended)](#recommended-cloudflare-tunnel) · [other proxies](#other-reverse-proxies)
- [Backups, updates and your data](#backups-updates-and-your-data)
- [Privacy](#privacy)
- [Security notes](#security-notes)
- [The iPhone and Apple Watch app](#the-iphone-and-apple-watch-app)
- [Troubleshooting](#troubleshooting)
- [How it works](#how-it-works) — stack, layout, data model
- [Known limitations and roadmap](#known-limitations-and-roadmap)
- [Development](#development)
- [Acknowledgements and licence](#acknowledgements-and-licence)

---

## What is Headwind?

Headwind is a single self-hosted web app that brings together the things most athletes spread across four or five services. It started as a cycling app, and rides are still its deepest part, but runs, walks, hikes, swims, ski days, paddles, strength sessions and the rest are first-class activities too.

- **Activity analytics** — import from Garmin Connect, FIT/GPX/TCX files or a Strava export; see maps, streams, weather, wind, splits, laps, best times and records for each sport, segments, comparisons with the other times you've done the same route, goals, saved routes, and a GPS heatmap of everywhere you've been.
- **Gear and maintenance** — bikes, shoes and other kit with photos, a default for each kind of activity (changeable per activity), a calendar to say which bike rode which rides, and mileage on the parts that wear out (chains, cassettes, tyres, bar tape, sealant...) with service log and "due" alerts.
- **Nutrition and body tracking** — a fast food diary with barcode scanning, per-meal "recent foods", saved meals, hydration, weight trend and calorie goals that account for your training.
- **Coaching and automation** — optional AI analysis of your rides, runs, swims and every other sport with your own key (or local Ollama), on demand or as each one arrives; Home Assistant sensors over MQTT; push notifications.
- **A social layer without a central server** — link your instance to a friend's directly to share activities, segment leaderboards, the heatmap and challenges.

It runs on a Raspberry Pi, a NAS, a spare PC or a VPS. Your data lives in one SQLite file you can copy, back up and inspect. It only talks to services you explicitly configure (plus a few public data APIs listed [below](#privacy)).

**Design principles**

| | |
|---|---|
| **Yours** | One folder of data. Export any ride as GPX, back up everything as one zip, no lock-in. |
| **Quiet** | No account, no analytics, no ads, and nothing sent back to the developer. |
| **One person per instance** | Your stats, your PRs, your coaching. To track someone else, they run their own Headwind and you link them as a friend. |
| **Honest** | It's a beta; this README lists what's rough. The AI coach is deliberately blunt rather than flattering. |

---

## Where Headwind came from

Headwind was created by [lordmaa](https://github.com/lordmaa), who wrote the original app ([lordmaa/headwind](https://github.com/lordmaa/headwind)) and released it under the MIT licence. Thank you for building it and sharing it openly: none of this would exist without it.

This repository began as a fork of it in October 2026, from the original's 0.5.3-beta, and is now a separate project going in a different direction: every sport rather than cycling first, an iPhone and Apple Watch app, more ways to import your history, and a lot of fixes along the way. The two no longer share code, and each is maintained on its own, so please report problems with this version **here**, not on the original. The original has since been rewritten (its 0.8 onwards). If you run the original, its 0.5 or the rewrite, and want to try this one, see [Moving from the original Headwind](#moving-from-the-original-headwind), which lists the releases tested and what comes across.

---

## Beta status — read this first

Headwind is a real, working application used daily by its maintainer. The first public release (0.1.0-beta) went through a security and reliability review (restore safety, login hardening, injection fixes, Garmin sync reliability, resource limits), and every release since is listed in the [CHANGELOG](CHANGELOG.md), with any migration it runs at the first start. It is still a beta:

- **Expect rough edges.** Report them — [open an issue](../../issues).
- **Shared admin login.** There is one login for the whole instance. It is not a multi-user system: for several people, run a Headwind each (one container per person) and link them as friends. Don't give the login to people you don't trust with your data.
- **Back up before you upgrade** and before you import years of history.
- **The iPhone and Apple Watch app isn't on the App Store** — build it yourself with Xcode (see [ios/README.md](ios/README.md)). It hasn't yet been tried on every device it supports.
- **The arm64 (Raspberry Pi) image and the Windows build are new** and have had little real-world testing.
- **Don't expose it to the internet without HTTPS** — see [Putting it on the internet safely](#putting-it-on-the-internet-safely).

---

## Bugs, ideas and feature requests

Please [open an issue](../../issues) for anything: a bug, something confusing, a sport or a device that isn't handled well, an import that went wrong, or a feature you'd like. Small requests are welcome too, and so are "this works but it's annoying". Headwind grows from what people ask for.

**New issue** offers a form for a bug and one for a feature request, which ask for what's below. For a bug, it helps to include the version (**Settings → This server**, beside **Check for update**), how you run it (Docker, Raspberry Pi, Windows or from source), what you did and what you expected. The **Tasks** page has a **Download diagnostics** button for the logs; look through it before attaching it, as it can hold activity names and places.

---

## A quick tour

> All images: demo data — a fictional rider "Alex" riding real roads around Hathersage, Castleton, Edale and Bakewell. They were taken before the 0.7 releases, so some pages now look a little different (one shared style across the app, light mode, every sport) and newer pages such as Activities, Goals and Tasks aren't pictured yet.

<img src="docs/promo/riding-analytics.jpg" alt="Built around the riding: every ride, and everywhere you've ridden" width="900">

### Dashboard
Lifetime totals, a 12-week performance chart you can flip between distance, elevation, speed and calories, your goals, and your recent activities with a sport filter.

<img src="docs/screenshots/dashboard.jpg" alt="Dashboard" width="900">

### Activity detail
A map with a picker for its type (satellite, grey, topographic, cycling) and switches for direction arrows, distance markers and wind arrows; hovering a chart marks the spot on the map, and the cursor on the map's track shows on every chart. Elevation + heart-rate, speed or pace, power and cadence charts, drawn against distance or against time (a Distance / Time switch above them, remembered between visits; against time a stop shows as a gap, and an activity with no distance, such as a pool swim or an indoor session, is always against time), weather at the start (temperature, wind speed/direction and a headwind / tailwind / crosswind call computed from your route bearing), and effort comparison. Each page fits its sport: pace and splits for runs, sets and SWOLF for a pool swim, each run of a ski day, laps from your device. **Same route** ranks this activity against every other time you've done the same start, finish and roads, the same way round, and a Zwift ride or run is drawn over its Zwift world's map alone, with no weather (it wasn't done outside).

<img src="docs/screenshots/ride-detail.jpg" alt="Ride detail" width="900">

### Heatmap
Everywhere you've been, filterable by date range and sport, on any of the map types, with HD export (3440×1440). Each track follows the roads you took to within 10 m (5 m in the HD export), keeping its bends and roundabouts while a straight road takes only a few points, so the page stays quick with years of activities. Click or tap a track to see which activity it is and open it (the pointer turns into a hand over one); where tracks overlap, such as a regular commute, you get a list of all of them, newest first. Show your own activities, one friend's, or everyone's together, each in their own colour; Zwift rides and runs are left out unless you include them, and drawn over their Zwift world's map.

<img src="docs/screenshots/heatmap.jpg" alt="Heatmap" width="900">

### Segments and leaderboards
Draw a segment on any ride; Headwind scans your whole history, ranks every effort, charts your trend, rates the difficulty and tracks PRs. A steep climb counts however slowly it's ridden or pushed up, as long as it keeps climbing. A stop part way along counts in the effort's time, as on Strava, but doesn't stop it counting; a wait at the top before setting off, or at the bottom after finishing, isn't in the time. An effort has to follow the segment's own line: another way between the same start and finish, such as a road round a steep path or the other of two trails down a hill, isn't the segment. Every lap counts: an activity that rides a segment more than once has an effort for each time round, marked lap 1, lap 2, ... on the activity and on the leaderboard. Linked friends' segments and efforts appear on the same leaderboard.

<img src="docs/screenshots/segment-leaderboard.jpg" alt="Segment leaderboard" width="900">

### Analytics
Speed (or pace) over time, monthly distance, year-on-year, length distribution, day-of-week, weather scatter charts, best times and records for each sport — all filterable by sport.

<img src="docs/screenshots/analytics.jpg" alt="Analytics" width="900">

<img src="docs/promo/performance-context.jpg" alt="The stuff around the ride matters too: recovery, bodyweight and nutrition beside your cycling data" width="900">

### Nutrition
A diary built for speed: barcode scan, per-meal recent foods, saved meals, hydration, macro rings, and calorie goals that include what you burn training.

<img src="docs/screenshots/nutrition-day.jpg" alt="Nutrition diary" width="900">

### Smaller (or bigger) portions
Saved a meal but ate less? Scale the whole meal in one tap — weight and every macro together — or open any item and change its weight.

<img src="docs/screenshots/nutrition-meal-portion.jpg" alt="Meal portion scaling" width="900">

### Change the weight, macros follow
Edit the weight of any logged item and calories, protein, carbs, fat and fibre scale in proportion. Entries with no recorded weight get a baseline from the first weight you type.

<img src="docs/screenshots/nutrition-weight-edit.jpg" alt="Editing a food's weight" width="900">

### Weight trend
Daily weigh-ins with a smoothed trend line, rate of change, and progress against your goal. The chart stays readable from a week to years of daily readings, with a line at every stone (or 5 kg) lost that you can switch off. Hover over the chart, or tap it on a phone, to see a day's weigh-in, trend, change and source.

<img src="docs/screenshots/weight-trend.jpg" alt="Weight trend" width="900">

### Goals and challenges
Set a distance, climbing, time or activity-count goal per week, month or year, for every sport or the ones you tick ("3 activities a week, rides or runs"), and see whether you're ahead of an even pace on the Goals page and the dashboard. You have only the goals you set. On the **Challenges** page, race linked friends over set dates; each instance works out the standings from the activities it syncs.

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
<summary><b>Riding</b> (12 screens)</summary>

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

**GPS heatmap of everywhere you've ridden, run, walked or swum, filterable by date range and sport.**

<img src="docs/screenshots/heatmap.jpg" alt="GPS heatmap of everywhere you've ridden, run, walked or swum, filterable by date range and sport." width="800">

**The same heatmap on satellite imagery (also Dark, Light, topographic and cycling maps, with HD export).**

<img src="docs/screenshots/heatmap-satellite.jpg" alt="The same heatmap on satellite imagery (also Dark, Light, topographic and cycling maps, with HD export)." width="800">

**Analytics: best efforts, climbing records, speed trend, monthly distance, distribution, weather scatters, and more.**

<img src="docs/screenshots/analytics.jpg" alt="Analytics: best efforts, climbing records, speed trend, monthly distance, distribution, weather scatters, and more." width="800">

**Profile and trophy case: lifetime stats, segment PRs, best efforts and badges.**

<img src="docs/screenshots/profile.jpg" alt="Profile and trophy case: lifetime stats, segment PRs, best efforts and badges." width="800">

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

**AI Coach: your coaching goals, and bulk analysis of activities by date range.**

<img src="docs/screenshots/ai-coach.jpg" alt="AI Coach: your coaching goals, and bulk analysis of activities by date range." width="800">

**Settings, in four sections: You (display, features, profile and goals, calorie burn), Connections (Garmin Connect, Home Assistant, AI provider, maps), Sharing (outside address, contacts for live links, email) and This server (login, backup and restore). The screenshot is from before the regroup.**

<img src="docs/screenshots/settings.jpg" alt="Settings: display, features, profile, Garmin Connect, Home Assistant, AI provider, maps, outside address, email, login, backup and restore." width="800">

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
<summary><b>The setup wizard</b> (6 screens)</summary>

**Step 1: your name (or restore from a backup).**

<img src="docs/screenshots/wizard-1-name.jpg" alt="Step 1: your name (or restore from a backup)." width="800">

**Step 2: units.**

<img src="docs/screenshots/wizard-2-units.jpg" alt="Step 2: units." width="800">

**Step 4: Garmin Connect (optional, MFA-capable).**

<img src="docs/screenshots/wizard-3-garmin.jpg" alt="Step 4: Garmin Connect (optional, MFA-capable)." width="800">

**Step 5: Home Assistant (optional).**

<img src="docs/screenshots/wizard-4-home-assistant.jpg" alt="Step 5: Home Assistant (optional)." width="800">

**Choosing a health entity from Home Assistant.**

<img src="docs/screenshots/wizard-4b-ha-entity-picker.jpg" alt="Choosing a health entity from Home Assistant." width="800">

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
- **Every sport** — road, mountain bike, gravel, e-bike and indoor (Zwift) rides; runs, trail runs, indoor (treadmill and Zwift) runs, walks and hikes; pool and open-water swims; ski and snowboard days; paddles, surfs, kitesurfs, wing foils and sails; strength, yoga and anything else with no distance. Distances only ever add up within a kind, so a run never changes your ride stats. A ride on a bike you've set up as an e-bike is an e-bike ride, whatever the file or Garmin called it (a default bike given automatically doesn't count), and goes back to what it was if you move it to another bike.
- **Garmin Connect sync** — activities of every type *and* daily recovery data; MFA-capable connect flow in the browser (no command line); incremental sync that re-scans the last day so a second same-day activity is never missed and failed downloads are retried. Activities deleted or changed in Garmin later are flagged for review (see [Garmin Connect](#garmin-connect)).
- **File import** — `.fit`, `.gpx`, `.tcx` (and gzipped variants), or a **Strava data-export zip**, with a live progress bar. The **Import** page has the upload at the top and, under **To review**, everything an import or the Garmin check found that waits for you to decide, with how many and a link to each list. A file keeps its own sport. When it says "Biking" (as Strava writes into every TCX, a run's too) or names none, and its pace is a runner's or a walker's, Headwind asks on the activity, the dashboard and the **Import** page whether it was a run or walk; nothing changes until you answer. Strava's names for sports Headwind has its own name for ("Virtual Ride", "E-Bike Ride", "Mountain Bike Ride", ...) are saved under Headwind's, so an indoor ride from Strava and one from Garmin are the same sport in every list and filter. Strava's Weight Training and Crossfit count as Strength, and its High Intensity Interval Training as HIIT. A FIT file's strength, yoga and HIIT sessions keep their sport, and so do sessions on a gym's bike, treadmill or rowing machine (an indoor ride, an indoor run, a row). From a Strava export Headwind also takes Strava's own distance and moving time, your bikes and shoes, photos, commutes and segments, the routes you made on Strava if you tick **Routes** (onto the **Routes** page, with their heights; importing again adds no copies), and keeps the export so you can **Import again** later without uploading it. When an update brings fixes that only reach activities already here through a re-import, the Import page says what they are and asks you to import the export again (or upload it, if it wasn't kept). It also lists the activities an older Headwind stored with their GPS and times out of step, which segments leave out: Garmin's are read again by the Garmin check, a friend's are put right on their Headwind, and the rest need their files imported again.
- **Duplicates** — the same activity from Garmin, Strava, a file and the phone is kept once, however it arrived (including a watch's indoor ride and its Zwift copy, a phone's partial recording of a ride, a recording with nothing in it beside a real one, and a copy whose start a time zone mistake put hours out). The better recording is kept, unless its distance or time can't be right and the other's can: then the other is. Importing an activity you already have again offers to repair it from the file. Deleting an activity moves the recordings set aside behind it to another recording of the same session if there is one; otherwise one deleted in Garmin brings its other recording back as its own, and one you delete takes them into **Recently deleted** with it (and back out, if you restore it). When the two recordings are on different gear (a Garmin ride on your default bike, its Strava copy naming the bike you rode), the activity, the dashboard and **Gear → Gear to check** say so, so you can pick the right one. When they say different sports (a Garmin ride saved as a plain ride, its Strava copy an e-bike ride), the activity, the dashboard and the **Import** page say so: take the other recording's sport or keep the one it has, for one activity or for every activity with the same difference at once. The activity links to the recording set aside, on its own or side by side with the one kept: their numbers, tracks on one map and charts against the same clock, where hovering a chart marks each recording's spot on the map and the cursor on a track shows that minute on the charts.
- **Start times where each activity happened** — the time zone comes from where it started, so a run abroad shows local time. Your home time zone is set in Settings.
- **Activities page** — every activity in one list, with search, a sport filter and a **Select** bar to edit many at once (delete, change type, set the gear, mark as commutes, rename, download as GPX). **More filters** pick activities with or without power, heart rate, cadence or a GPS track, indoors or out, and by where they came from (Garmin, Strava, a file, the phone app, typed in), and list them by date, distance, moving time, climbing or speed, a page at a time. Every filter is in the address, so a filtered list can be bookmarked or linked. A rider's profile links to their list.
- **Favourite sports** — pick them under **Settings → Display** and each gets its own item under Activities in the sidebar: Cycling (every kind of ride), On foot, Swimming, or one sport such as Run on its own. A kind of ride you first record later joins Cycling by itself. **+ Add an activity by hand** at the top adds a ride, walk, run or hike you didn't record; if a recording of it arrives later, the recording is kept and the typed-in one put aside. The **Activities** link at the top of an activity goes back to the list as you left it, with its search and filters, even after paging through with Prev and Next.
- **Recently deleted** — a deleted activity of any sport is kept whole for 30 days, listed under **Recently deleted** at the bottom of the **Import** page with its date, name, sport and distance. **Restore** puts it back as it was: notes, photos, gear, commute, the AI's analysis, and its segment and best times worked out again (a bike or shoes deleted meanwhile are replaced by your default; if another recording of the same session came in meanwhile, the better of the two is kept and the other set aside). **Delete now** doesn't wait. After 30 days only its id is kept, and its photo files are deleted. Either way no Garmin sync or Strava export imported again brings it back; uploading its file yourself does. Backups include it, photos and all.
- **Commutes** and **photos** on any activity. Give a photo a caption and drag the photos into order on the activity page; the first is the cover.
- **GPX export** of any activity.
- **Phone and watch recording** — the iPhone and Apple Watch app records every sport and uploads it (see [The iPhone and Apple Watch app](#the-iphone-and-apple-watch-app)).
- **Upload endpoint** — `POST /import/api/upload-ride` with an `X-Upload-Token` header (set `RIDE_UPLOAD_TOKEN`) lets a script, a Pi attached to a bike computer, or an automation push GPX files in.

### Activity pages and analytics
- Map, speed/elevation/heart-rate/power/cadence streams, wind overlay, co-rider badges. Hovering a chart marks the spot on the map, and the map's cursor on the track shows on the charts.
- **Map types** — every map (activities, segments, heatmap) has a picker: Esri satellite, satellite + labels, dark, light and topographic, OpenTopoMap (contours, paths and tracks) and CyclOSM (surfaces, MTB trail grades), with Waymarked Trails' mountain bike and cycle routes over any of them. Thunderforest's OpenCycleMap and Outdoors, and Ordnance Survey's Outdoor map of Great Britain, join it once you save your own free key under **Settings → Maps**. On an activity, direction arrows, distance markers every mile or km (fewer when zoomed out) and the wind arrows each have their own switch. Each kind of map remembers your choice in the browser.
- **Pages that fit the sport** — pace and splits per mile or km on foot; pace per 100 m, sets, strokes and SWOLF for swims; each run of a ski day with vertical descent; no climb on the water; laps from your device for any sport.
- **Same route** — the other times you've done this activity's route (same start, finish and roads, same way round, same kind of activity), ranked by moving time, compared with the last 20 and charted. The AI coach gets the same comparison.
- **Zwift rides and runs** are matched to one of Zwift's worlds and drawn over its map alone, with no satellite map around it, on the activity page (in the iPhone app too) and when comparing its recordings. A ride or run that starts in one of Zwift's made-up worlds (Watopia, Makuri Islands, France, Crit City) counts as a Zwift one whatever its file called it, and Garmin's virtual and treadmill runs come in as indoor runs. Indoor rides and runs have no segments.
- Weather at the start of every activity from Open-Meteo (free, no key), including a backfill for history: each sync fills in a few older activities, and **Fetch now** under **Weather for older activities** on the **Tasks** page does the rest at once. The wind is in mph or km/h, as your speeds are, and the temperature in °C or °F, a choice of its own under **Settings → Display**. Zwift rides and runs get none: a Zwift world's spot on the globe isn't where you were.
- Analytics: speed or pace trend with rolling average, monthly distance, year-on-year, distribution, day-of-week, weather scatters; metric/imperial; sport filter.
- **Best times** — fastest 5/10/20/30/50/75/100 miles on a ride (5/10/20/40/50/100/160 km when your units are metric), 1 km to the marathon on foot, 100 m to 3.8 km in the water, with year/month filters, plus **records by sport** (longest, longest time, most climbing, fastest). Indoor rides and runs (Zwift, a turbo trainer, a treadmill) have best-time tables of their own and never count towards your outdoor ones.
- **Trophy case** — badges for riding (counts, distance, elevation, epic rides, speed, climbing, weather, segments), running, walking and hiking, swimming, other sports and all sports together, each linking back to the activity that earned it. Indoor rides and runs count for the badges that count activities or time, not for distance, climbing, speed, weather or segments. With metric units the limits are round figures (40 km in one ride, 150 m of climbing) and count as such.
- **Goals** — distance, climbing, time or number of activities, every week, month or year, on the Goals page and the dashboard. Each counts the sports you tick: every sport, Cycling, On foot, Swimming or single sports like Run, as many as you like; a distance goal needs sports whose distances add up (rides, or runs and walks). Your weekly goal of a number of activities is also what Home Assistant's weekly activity sensor counts. With calendar weeks and months a goal is measured against an even pace; with the past 7 and 28 days it's what you've done in them (see **This week and this month** below).
- **This week and this month** — under **Settings → Display**, each rider picks how they're counted: **Past 7 and 28 days** (today and the 6 or 27 days before it, so a Monday or the 1st never starts you from nothing) or **Calendar weeks and months** (the week starts on the day you choose, the month on the 1st). The dashboard's weekly bars, goals and their history, the phone app's Overview, the alcohol units and the Home Assistant sensors all follow it, and say which they mean ("Past 7 days" or "This week"). The year is the calendar year either way. The Nutrition week diary, the badge for three kinds of training in one week, the Analytics calendar and the gear calendar are calendar weeks from your chosen day whichever you pick. New installs start on the past 7 and 28 days; an existing one keeps calendar weeks from Monday until you change it.
- **Activities that look wrong** — anything that can't be real is flagged on the dashboard and its own page, and left out of the speed and weather charts until you keep it or delete it: a ride at 2,500 mph, a walk at 20 km/h, a run faster than any record, a swim with nothing recorded, a moving time of seconds against a real distance, a heart rate below 30 or above 230 bpm, or a start date in the future from a device whose clock was wrong (every sport). The limits are loose: hard but real days pass. Where it can, the flag offers a fix: Strava's climb in place of a file's impossible one, the elapsed time when a file's broken timestamps made the moving time seconds, or the real date for one dated in the future. To deal with many at once, the dashboard's card has its own **Select**: pick rows, or every one with the same reason, then say they're right, fix them or delete them. Only your own riders' activities are flagged for you: a friend's are theirs to fix on their own Headwind.
- **Recovery** — resting HR, HRV, sleep (stacked by deep, light and REM sleep and time awake, with sleep efficiency), steps, stress and body battery with 30/60/90-day charts: from Garmin, or from Apple Health through the iPhone app on days Garmin has none (Apple Health has no body battery, sleep score or stress, so a chart or Daily Log column with nothing in it is left out). Steps come from one source, chosen on the **Steps** page (Garmin, the phone, or automatic), never the highest of several: a phone counts pedalling as steps.
- Tables sort by clicking a column heading.

### Segments
- Define a segment by clicking start and end on an activity's map; Headwind **retroactively scans** every activity of that kind in the background, and the segment's page shows the efforts when it's done.
- Per-effort history, PRs, trend chart, difficulty rating, rolling average. Each lap of a segment on one activity is an effort of its own, as on Strava.
- If a segment's stored route shape is missing, Headwind rebuilds it from the activity it was drawn on (or a matching effort) — and says "route shape unavailable" instead of drawing a misleading straight line.
- Segments are shared both ways with linked friends.
- **Ride segments and on-foot segments.** Rides (bike and e-bike) only match ride segments; runs, walks and hikes only match on-foot segments, which show pace. The Segments page has a tab for each, a segment can be switched between them from its own page, and ride leaderboards filter **All / Bike / E-bike** so e-bike efforts never take a pedal PR.

### Routes
- The **Routes** page draws every route you've saved on one map, light lines that grow brighter where they overlap, so you can see at a glance where your routes go. Point at a line to pick it out, and click it to open that route (where several overlap, you choose from a list). The map fits to where most of your routes are; **Fit the map to them all** takes in any far away.
- Under the map, the table of routes (any sport, with distance, climb, where each came from and when it was added) sorts on any column and filters by part of a name, sport, where it came from, distance, and **Only in the map's view**. The map shows only the routes the filters leave, pointing at a row picks its route out on the map, and the filters and sort stay in the address, so a bookmark keeps them.
- Each route has a page of its own: the route on a map from start to finish with its elevation profile (hovering the profile marks the spot on the map), the **segments** it takes in from end to end, the same way round, in the order it reaches them, with your best time and how many times you've done each (drawn on the map too), and **Done before**: your activities that followed it (the same start, finish and roads, either way round) with the quickest, your typical moving time and a chart of every time, and the longer ones that took in all of it on the way. Only activities of the route's own kind count (any ride for a ride, walks, runs and hikes alike on foot); a route with no sport takes anything done outdoors.
- Routes come from **GPX files** (several at once), the routes you made on **Strava** (read from your Strava export: the one Headwind kept when you imported it, or a zip you upload there, of which only the routes are read), your **Garmin Connect courses** (with Garmin connected: you choose which from a list; a course deleted on Garmin stays here), or one of your **activities** (**Save as route** in its **⋯** menu).
- Rename a route or download it as a GPX file with its own heights on its page, change its sport there or in the table, or delete it from either. A route with the same points as one already here isn't saved again, whatever either is called, so importing the same file, export or courses twice makes no copies.
- Routes can't be edited yet.

### A live tracking link (iPhone app)
Switch on **Share live location** on the Record screen (or make it the default in Settings) and the phone makes a link when you start, or when you switch it on mid-recording, and opens the share sheet to send it by Messages, WhatsApp or mail. It opens in any browser with no account and shows where you are, your track so far, distance, time, speed or pace and the phone's battery, but nothing within 300 m of where you started or inside your [privacy zones](#privacy-zones). Anyone with the link can see where you are. It ends an hour after you finish, or at once with **Stop sharing** (on the phone's Record screen, on the Watch's controls page for a link the Watch started, or on the server's **Phones** page, which lists the running and recent links, for one sent by mistake when the phone isn't to hand), and stays on the Record screen until then to send again or copy. Your server needs an https **Outside address**; without one, the app says why and records without the link. The Watch has the same switch on its start screen: it sends where you are every 30 s, through the phone or over Wi-Fi or cellular, and makes the link itself. As the Watch can't send it, your iPhone shows a notification saying the link is ready, and tapping it opens the share sheet; the link also waits on the Record screen.

When you're following one of your saved routes, the link can follow it too: the page shows how far you've come along the route, how far is left, and when you should finish, at your recent moving speed or pace so stops don't count. Off the route, it says so and keeps the last figures. The route's line is drawn on the page only if you choose to show it, since it says where you're going; the distance to go and the finish time show either way. The line is cut around both its ends and inside your privacy zones, and your own position isn't shown near the route's finish either. The server side of this is built; the apps can name the route once they can follow one (see the TODO).

On the iPhone, the recording also shows on the Lock Screen and in the Dynamic Island as a Live Activity: the time, distance, speed or pace and heart rate, and whether your live link is being shared.

Headwind can also email each new link itself to people you choose beforehand: add them under **Contacts for live links** in Settings (or in the app's Settings) and give it a mail server under **Settings → Email**. They get it with nobody tapping anything, from the Watch on its own too, and the phone and the Watch say who it was sent to.

### Running in Home Assistant
- Best times for 1 km, 1 mile, 3 km, 5 km, 10 km, 15 km, half and full marathon, worked out from the GPS of your recorded runs (the fastest stretch of that distance inside any one run; indoor runs count in the totals but not the best times), plus pace, weekly/monthly/yearly totals, 12 weeks of distance, recent runs and the latest route, are shown in Home Assistant on a **Running** tab (see `docs/ha`). Every other sport has its own totals sensors too.

### Nutrition and body
- Barcode scanner (phone camera) and text search, backed by **Open Food Facts** — no API key.
- Meals: Breakfast, Lunch, Dinner, Snacks, **Ride fuel** and **Recovery**.
- **Recent foods per meal** — pick *Add* on a meal and see what you most often (and most recently) log for that meal.
- **Saved meals** and **recipes**, **Go-Tos** (favourites), **My Foods** (your own foods, per-100 g).
- Edit any entry's weight and the macros rescale; scale a whole meal with one tap.
- Calorie and macro goals, with an estimated daily burn that includes your activities and a fixed weekly allowance for exercise (**Typical exercise**, for the sports you tick, with a figure offered from their last 8 weeks); weekly view; "copy yesterday".
- Hydration logging with a daily goal.
- Weight tracking with a smoothed (EMA) trend, goal weight and projected finish, on its own **Weight** page under Health with a table of weigh-ins (Garmin weigh-ins count as scale readings). Lines at every stone or 5 kg lost can be switched off.
- Optional **AI food-photo estimate** and **screenshot import** (e.g. from another food app) with your own key.
- Installable as a PWA on a phone.

### Gear and maintenance
- **Bikes** with photos, type, brand/model/year and any mileage from before Headwind.
- **Shoes and other gear** — shoes, wetsuits, skis, boards, boats — with a photo, distance and time added up from their activities, and a replace-at distance (700 km to start with for shoes) with nudges at 90%, 100% and 125%. Shoes in a Strava export come in with their activities.
- **Defaults for new activities** — a default bike for commutes, mountain bike, gravel, e-bike and indoor rides (and any other kind you've ridden) beside one for every other ride, and default shoes or kit for each sport. Every new activity lands on its default (Garmin sync, file import, phone recording, typed-in activity), and **Apply to past activities** brings older ones in line. Matching a Strava bike brings in the sports Strava had it as the default for.
- **Assign by calendar** — click days or set a range ("everything from 1 March to today"), choose the bike and see exactly how many rides change before you apply. A gear picker on every activity changes just that one, and the Activities page lists the activities with no gear (only for sports you have gear for). An activity recorded twice whose two recordings are on different bikes or shoes is listed under **Gear to check**, to use the other recording's gear or keep the one it has, one at a time or all at once.
- **A card for each item on the Gear page** — its photo, distance, wear, activities, time, and when it was first and last used.
- **One page for every piece of gear** — odometer, activities, distance, time, climbing, speed or pace, a breakdown by sport, first and last used, longest activity, distance by year and the 10 most recent activities. **Retire** keeps its history, and retired gear can still be picked for an old activity.
- **Replaceable parts** — chain, cassette, chainrings, tyres, tubeless sealant, brake pads/rotors/fluid, cables, bar tape, headset and wheel bearings, bottom bracket, cleats, suspension service or your own, each with editable *check* and *replace* intervals by distance and/or days.
- **Service log** — replaced, serviced, inspected, cleaned...; replacing a part retires it (keeping its lifetime) and fits a fresh one.
- **Alerts** — soon / due / overdue, once each, via ntfy and Home Assistant push; a dashboard card shows what needs attention. Untick **Maintenance warnings** on a bike or an item of kit (a turbo bike, beach shoes) to leave it out of the alerts and the due lists; its wear still shows on its page.
- Mileage is always **computed from your rides**, so fixing a ride's bike fixes every part. Photos are included in backups. See [docs/GEAR.md](docs/GEAR.md).

### Social (peer-to-peer)
- Add a friend's Headwind with the code they made for you: paste it on the Friends page, or scan their QR code with the iPhone app. Their activities (rides, runs, walks, any sport), segments and shared foods sync directly into your database. No central server. In the iPhone app, the **Whose** menu on the Activities tab shows one friend's activities, or everyone's together, to look at but not change.
- **One code per friend**, made on the Friends page or in the iPhone app, each choosing what it shares (activities, segments, foods), whose activities when the instance has more than one rider (a new code shares only the main rider's unless you tick others, and a rider added later isn't shared until you tick them on a code), and the date range (all, past 6 months, past month, from today, or your own dates), so you can cut one person off without touching the others. A code holds your address and that friend's feed token; a Headwind that doesn't read codes can still be given the address and token separately.
- A friend's activities are shown, never changed, on your instance. The rider buttons on the dashboard and the Activities page show one friend's activities, or with **Friends** every friend's together, newest first with each one's avatar. The heatmap shows yours, one friend's or everyone's together.
- **What your friends have been doing:** the Friends page lists each friend with their latest activity, and their name opens their activity list. After a sync that brought new activities it says what came in ("Sam: 1 new ride, Hill reps, 20 Oct"), adding up over several syncs until you dismiss it. A friend's first sync brings their history, so it says nothing.
- **Challenges** — a race over set dates, on a page of its own, sent to the friends you invite: the most distance, climbing, time or activities, or the first to a target. Each instance works out the standings from the activities it can see, and the dashboard shows where you stand in the ones under way.
- Auto-sync every 15 minutes by default (off / 15 / 30 / 60 / 120). Only new or changed activities are fetched, and edits and deletions reach your friends at their next sync. **Sync** on the Friends page runs in the background (a first sync can take minutes): you can leave the page, and the result shows on the Tasks page.
- Works over LAN, VPN or the public internet (use HTTPS).

### Automation and coaching
- **AI coaching** (optional, every sport): GPT models, **Claude**, or a local **Ollama** model. Each activity is coached in its own terms: a ride by speed and power, a run by pace and cadence, a swim by pace per 100 m, a strength or yoga session by time and heart rate. The prompt includes the activity's stats, weather, same-route comparisons, similar past activities of the same kind (a mountain bike ride against your mountain bike rides, a Zwift ride against your indoor rides, a trail run against your trail runs: their speeds don't compare), segment comparisons, best times against the same kind, your other training in the 30 days before it (other kinds of ride or run included, as load), and recovery. Ten personalities (including a refreshingly rude one) and your own coaching goals. **Analyse New Activities** writes the notes for each new activity of the sports you pick as it arrives.
- **Home Assistant / MQTT**: ride, every-sport, recovery, nutrition, hydration and weight sensors with auto-discovery; notifications; dashboards.
- **Notifications** — activity-synced alerts through Home Assistant's companion app (an ntfy hook exists in the code but has no settings screen yet).

### Running it
- **Tasks page** — in two sections. **Background work**: the Garmin sync, health history, friend sync, the MQTT link, imports in progress, the weather for older activities (with **Fetch now**), the one-off work an update starts in the background (such as working out the heatmap tracks again), with a progress bar for each long job (also shown at the top of every page while it runs), the Garmin activities the sync gave up on (with **Try again**), the recent runs, and the one-off repairs an update runs and what each changed. **When something goes wrong**: the Logs card, which searches the log (an activity named in a line links to it), and the diagnostics and troubleshooting copy to send to whoever is helping.
- **Light, dark or auto** — follows each device's setting by default; charts and maps change with the page.
- Works on a phone: the layout and each page's top-bar actions fit a small screen.

---

## Install

### Docker (recommended)

You need Docker with the Compose plugin. No clone required:

```bash
mkdir headwind && cd headwind
curl -O https://raw.githubusercontent.com/AtomBrake/headwind/main/docker-compose.yml
curl -O https://raw.githubusercontent.com/AtomBrake/headwind/main/.env.example

docker compose up -d
```

Open **http://localhost:5001**. On the first start Headwind generates a random signing key and an admin password and prints it **once** in the logs:

```bash
docker logs headwind 2>&1 | grep -A3 "generated one"
```

Sign in with `admin` and that password, then choose your own (at least 10 characters) in the setup wizard or under **Settings**; the generated one stops working then. Headwind keeps only a hash of the password, so it can't show it to you again. To choose your own credentials instead, copy `.env.example` to `.env` and set `SECRET_KEY`, `APP_USERNAME` and `APP_PASSWORD` *before* the first `docker compose up`.

Data lives in `./data` (database, avatars, food photos, the saved login) and `./garmin_tokens`, next to your `docker-compose.yml`, so it survives restarts and upgrades.

**It runs as a user, not root.** The app runs as `headwind` (uid and gid 1000), so on a Linux host the files in `./data` and `./garmin_tokens` belong to uid 1000. Folders made by an older image belong to root: at each start, before giving up root, the container hands over whatever isn't the user's yet (only those files, so later starts are quick). If it can't, for example because a folder is mounted read-only, or it's on NFS that maps root to nobody, it says so in the log and carries on as root, as older images did. To choose the user yourself, give the folders to that user first and set `user: "1000:1000"` (or your own ids) in the Compose file, or pass `--user` to `docker run`. The container then changes no ownership.

**Health check.** The image checks `/login` every 30 seconds, and `docker ps` shows `healthy` once it answers. The first start on a new version brings the database up to date before the web server starts, which can take minutes on a big one, so the container shows `starting` for up to 10 minutes before a failed check counts. A database a newer Headwind has opened is refused, with the reason in `docker logs`, rather than changed.

To reach it from outside your home, at an HTTPS address, add a Cloudflare Tunnel: see [Putting it on the internet safely](#recommended-cloudflare-tunnel).

Images are published for **amd64 and arm64** on the GitHub Container Registry as [`ghcr.io/atombrake/headwind`](https://github.com/AtomBrake/headwind/pkgs/container/headwind). The `beta` tag follows the newest release, and each release also has a tag of its own version, to stay on one. There's no `latest` tag until a release comes out of beta.

### Moving from the original Headwind

If you run the original Headwind with Docker (its image is `lordmerchant99/headwind`, or one you built from its source), back up your `./data` folder, then change the `image:` line in your `docker-compose.yml` to `ghcr.io/atombrake/headwind:beta` and run:

```bash
docker compose pull && docker compose up -d
```

Keep `./data` and `./garmin_tokens` where they are. Headwind brings the database up to date at its first start, which can take a few minutes on a big one (see the health check above), and the **Tasks** page then lists what it brought over and put right on the way.

**Tested:** moving from the original's 0.5.3-beta, and from 0.9.1-beta, its newest release. Its 0.8 onwards are a rewrite of their own; 0.8.0 and 0.9.0 weren't tried separately, and a release newer than 0.9.1 hasn't been tried yet, so keep the backup, and [open an issue](../../issues) if it goes wrong.

**What comes across:** every activity, with its map and its recorded data (heart rate, power, cadence and so on), bikes with their parts and service log, weigh-ins, food and drink, nutrition and weight goals, coaching goals and your settings. Photos on an activity come across too. A fault you logged on an activity (a puncture, a snapped chain) goes into that activity's notes, as there's no list of faults here; one on a bike is also in its service log, as it was.

**What looks different afterwards**, because this Headwind puts right what the original saved wrongly:
- An imported activity starts at the local time where it began. The original showed its UTC time, an hour or more out in summer or abroad.
- An activity from a Strava export with no track has its real distance. The original saved some 1,000 times too long ("This ride looks wrong").
- An activity recorded with auto-pause off has a moving time that leaves out the stops.

**What doesn't come across**, as this Headwind doesn't have it: where a photo was placed on the map, the verdict on each weigh-in, the food diary summaries, the weight milestone, the automatic trim of the calorie goal, and the usual portion remembered for each food. They stay in the database as they were.

**To do by hand afterwards:**
- If you imported a Strava export into the original's rewrite, the **Import** page asks you to import it again (from 0.5.3, nothing asks, but it's worth doing too). Activities already here are matched, not doubled, and the page lists what reads better now for you to accept, such as a track the original couldn't read. It also brings in the export's bikes and shoes, and its photos.
- The original's Android app doesn't work with this Headwind, which has an iPhone and Apple Watch app of its own.

### Raspberry Pi

The same Docker instructions work on a Raspberry Pi 4/5 (64-bit OS). The arm64 image is new — if something misbehaves, please report it. Tips:

- Keep `./data` on an SSD or good SD card; SQLite is happiest on reliable storage.
- Expect the first Garmin history sync and weather backfill to take longer than on a PC.
- Running **Watchtower** will keep the image current automatically — convenient, but updates then happen without you watching.

### Portainer

Deploy as a stack using the Compose file from this repo and set `SECRET_KEY`, `APP_USERNAME` and `APP_PASSWORD` under **Environment variables**.

### Windows (experimental)

Download `Headwind-windows-x64.zip` from the [Releases](../../releases) page, extract it somewhere writable (not *Program Files*), and run `Headwind\Headwind.exe`. It runs as a desktop app: a tray icon (bottom right, near the clock — you may need to click the ^ arrow) and Headwind opens in its own app-style window. A dialog shows your first sign-in.

Tray menu (right-click, or double-click to open): **Open Headwind**, **Show sign-in details** (the generated password, until you choose your own or Headwind quits), **Reset sign-in password** (if you've forgotten yours: a new random one, shown once), **Open data folder** (`%LOCALAPPDATA%\Headwind`), **Start with Windows**, **Quit Headwind**. Closing the window does *not* stop it (it keeps syncing); use Quit.

- Your data survives updates — replace the extracted folder.
- It listens on this PC only by default. For a phone on your network set `HEADWIND_HOST=0.0.0.0` before launching.
- The build is **unsigned**: SmartScreen will say "unknown publisher" (More info → Run anyway) and some antivirus tools flag PyInstaller apps. If that worries you, use Docker or run from source.
- Build it yourself: `pip install -r requirements.txt waitress pyinstaller` then `python scripts\build_windows.py dist`.

### From source

```bash
git clone https://github.com/AtomBrake/headwind.git
cd headwind
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python3 app.py          # http://localhost:5001
```

`python3 app.py` is for development: it listens on all interfaces. `HEADWIND_DEBUG=1` turns on Flask's debugger, which runs code for anyone who reaches it, so then it listens on `127.0.0.1` only (and says so in the log). For anything long-lived use Docker (gunicorn) or put it behind a proper service manager.

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
3. **Outside address** — the https address you reach Headwind on from outside the house (a [Cloudflare Tunnel](#recommended-cloudflare-tunnel) or another reverse proxy). The phone app pairs with it, friends' Headwinds sync from it and notification links open it. **Check** loads it from your browser. It starts with `APP_URL` when that's https; skip it if Headwind isn't reachable from outside yet.
4. **Garmin Connect** — optional. Enter your Garmin email and password; if Garmin asks for an MFA code you'll be prompted in the browser. The password is used only to sign in and isn't kept: Headwind keeps the sign-in tokens Garmin gives it, which renew themselves.
5. **Home Assistant** — optional. Connect to HA with a long-lived token, map health entities and pick a weather entity.
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
| `APP_PASSWORD` | generated | Login password. If blank or a known placeholder, a random one is generated and printed once in the logs. A password changed in **Settings** is kept (as a hash, in `.admin_login`) across container recreation until you edit this value: then this one wins, which is the way back in if you forget yours. Headwind never writes it to `.env`. |
| `APP_URL` | `http://localhost:5001` | The address others (and your phone) reach this instance at, used until one is saved under **Settings → Outside address**, which is the easier place to set it: no restart, and the setup wizard asks for it. |
| `DATABASE_URL` | `/data/bike.db` (Docker) | Path to the SQLite database. |
| `HEADWIND_MULTI_RIDER` | *(unset)* | `1` enables the advanced multi-rider mode (several local riders on one instance). |
| `RIDE_UPLOAD_TOKEN` | *(unset)* | Enables `POST /import/api/upload-ride` (authenticated by the `X-Upload-Token` header). Disabled when unset. |
| `SESSION_COOKIE_SECURE` | `false` | Set to `true` when serving over HTTPS so the login cookie is never sent over plain HTTP. |
| `TRUSTED_PROXIES` | private addresses | Where a reverse proxy may connect from for Headwind to believe its `X-Forwarded-*` headers: comma-separated addresses or networks (e.g. `203.0.113.7` or `10.8.0.0/24`), or `none`. Unset, any loopback or private address is trusted (a proxy on the same machine, LAN or Docker network, or a local tunnel), and the first forwarded request from a private address that isn't loopback is noted once in the log. Set it if your proxy reaches Headwind from a public address, or to your proxy's address to close the gap described under [Other reverse proxies](#other-reverse-proxies). |
| `HEADWIND_MQTT_PREFIX` / `HEADWIND_MQTT_NAME` | *(defaults)* | Give a second instance on the same MQTT broker its own entity prefix and device name so they don't collide. |
| `HEADWIND_MQTT_NUTRITION` | `1` | `0` publishes only the ride sensors, not nutrition. |
| `HEADWIND_ENV` | `./.env` | Point an instance at a different env file (useful for running two instances from one code folder). |
| `WEB_WORKERS` | `2` | How many processes serve pages in Docker, each with 8 threads, so a slow page doesn't hold up the rest. Each takes about 120 MB of memory: `1` suits a machine short of it. The background work runs in a process of its own whatever this is. |
| `PORT` | `5001` | Port for `python3 app.py`. |
| `HEADWIND_DEBUG` | *(unset)* | `1` turns on Flask's debug mode for `python3 app.py`, listening on `127.0.0.1` only. |
| `LOG_LEVEL` | `INFO` | How much goes in the log. `DEBUG` adds every page load and every call to Strava, Garmin, the weather, food lookup and the AI; use it while chasing a fault. |
| `LOG_DIR` | `logs` beside the database (`./data/logs` in Docker) | Where the log files go (`headwind.log`, rotated at 5 MB, 5 kept). `off` keeps the log on the console only. |
| `LOG_FORMAT` | text | `json` writes one JSON object per line, for a log collector. |
| `LOG_CONSOLE_LEVEL` | same as `LOG_LEVEL` | Keep the console quieter than the log file (the Windows build sets `WARNING`). |

Windows-build only: `HEADWIND_HOST`, `HEADWIND_DATA`, `HEADWIND_NO_TRAY`.

### Settings inside the app

The Garmin sign-in, the MQTT broker, Home Assistant URL/token and mappings, AI provider/key/model, the optional map keys, the **outside address** (what phones pair with, friends sync from and notification links open), coaching personality and goals, display units, home time zone, how this week and this month are counted, appearance (Auto, Light or Dark), which features are on ([Turning features off](#turning-features-off)), your login details, backups and the **calorie burn adjustment** (a percentage taken off every burn estimate as it is pulled in, kept reversible; see the changelog) are all configured under **Settings** — not in `.env`. The page is in four sections, with links to each at the top: **You** (display, features, profile and goals, calorie burn), **Connections** (Garmin Connect, Home Assistant, AI provider, maps), **Sharing** (outside address, privacy zones, contacts for live links, email) and **This server** (login, backup and restore, the version). Calorie and macro goals live under **Nutrition → Goals**, and friend-sync is under **Friends → Auto-Sync**.

### Turning features off

Not everyone wants the food diary or the bike maintenance. **Settings → Features** turns off the parts you don't use:

| Switch | What goes |
|---|---|
| **Health** | Nutrition, Steps, Weight and Recovery together, and the Health heading in the sidebar. It overrides the four below without changing them, so turning Health back on brings back the same choices. |
| &nbsp;&nbsp;**Nutrition** | The food diary, water and the calorie goals, and the profile card in Settings that the goals are worked out from. |
| &nbsp;&nbsp;**Steps** | The Steps page. With Steps off and Nutrition on, the calorie goals count your exercise allowance only, not your step goal. |
| &nbsp;&nbsp;**Weight** | The Weight page and its backfill page. Nutrition still takes weigh-ins for its goals while it's on. |
| &nbsp;&nbsp;**Recovery** | The Recovery page, the dashboard's **Recovery Today** card, and the AI coach's recovery notes. |
| **Gear** | Bikes, shoes and other kit, and picking them on an activity. Activities keep the bike they had. |
| &nbsp;&nbsp;**Gear maintenance** | The parts, wear and service log on a bike, kit's replace-at distance, the dashboard's due list and the alerts. Bikes, kit and their distances stay. |
| **Segments** | Segments and leaderboards, an activity's efforts, and segments in the AI coach's notes. |
| **Routes** | Saved routes, and **Save as route** on an activity. |
| **Heatmap** | The heatmap. |
| **Goals** | Your weekly, monthly and yearly goals, and their card on the dashboard. |
| **Challenges** | The Challenges page and the races on the dashboard's Goals card. Your friends' races still keep you in them while it's off, so they're up to date when you turn it back on. Turned off for you if you'd turned Goals off before it had a switch of its own. |
| **AI coach** | The coaching notes on an activity, and the analysis of new activities as they arrive. |
| **Friends** | The Friends page and friends' activities, the automatic sync, and the feed your friends' Headwinds read from yours (they get an error until it's back on). |
| **Live tracking** | Starting live tracking links from the phone, and the contacts they're emailed to. A link already running carries on until it ends. |
| **Roughness**, **Route planner** | The road roughness map and the route planner (not in the sidebar yet, but at `/roughness` and `/planner`). |

A feature you turn off leaves the sidebar and the dashboard, and its pages say it's turned off in Settings. Its work in the background stops too: the Garmin sync stops reading the daily health figures once Recovery, Steps and Nutrition are all off, and the weigh-ins once Weight and Nutrition are; the part alerts, the AI coach's analysis of new activities and the friends' sync stop; and its Home Assistant entities are removed. Nothing is deleted. Turn a feature back on and its data, pages and entities are back as they were.

Each rider has their own switches. **Save, and start new riders with these** also makes them what a rider added later starts with. The phone apps can read what's off from `GET /api/v1/ping` (`features_off`), and the API endpoints of a feature that's off answer `403` with `feature_off` naming it.

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
| `/data/.secret_key`, `/data/.admin_login` | The generated session key, and the login: username, a scrypt hash of the password, and a scrypt hash of the environment's credentials it was saved under (mode 600). |
| `/data/prepared-downloads/` | A backup or a copy for troubleshooting while it's waiting to be downloaded (a day at most). Emptied at every start. Not in backups. |
| `/data/.secrets_key` | The key those saved secrets, and the Garmin token file, are encrypted with (mode 600). Not in backups unless you tick **Include the secrets key**: otherwise keep a copy to move to another server with them. |
| `/app/.garmin_tokens/` | Garmin login tokens (so MFA isn't needed every sync), encrypted with `.secrets_key`: a copy of this folder without the data folder doesn't sign anyone in. |

---

## Integrations

### Garmin Connect
- Connect in the wizard or **Settings → Garmin Connect**. MFA is handled in the browser.
- Two things sync: **activities** (downloaded as FIT, deduplicated by Garmin activity id and start time) and **daily health** (resting HR, HRV, sleep and its stages, body battery, steps, weigh-ins).
- Every activity type comes in: mountain bike, gravel and e-bike rides keep their kind; strength, yoga and HIIT come in as their own sports, and pilates, breathwork and the like as Other workouts with no track. Activities typed into Garmin Connect come in from Garmin's activity list, marked as typed in (the activity page says so), so a real recording of the same session is kept over them. The daily Garmin check marks ones an older version brought in, and gives Garmin's distance and time to any saved with neither. **Settings → Garmin Connect → Check activity types with Garmin** puts right activities an older version saved with the wrong sport, and Headwind lists them by itself when it starts, from the type Garmin last gave each one (the dashboard says when there are some to review). Another name for the same sport isn't listed: a Strava "Stand Up Paddling" or "Nordic Ski" is already Garmin's paddle or ski.
- An activity you cropped in Garmin Connect comes in cropped. Garmin keeps the whole recording in the file it hands out, so Headwind cuts the track to the part Garmin kept and takes Garmin's distance, moving time, climb and calories. One that came in whole before this was put right is found once by the daily check (below) and offered on the **Import** page with the other re-imports.
- The activity cursor re-scans the most recent day and never advances past a failed download, so activities aren't silently skipped.
- Your Garmin password isn't stored. Headwind keeps Garmin's sign-in tokens in `garmin_tokens` (readable only by Headwind's user, and encrypted with the key beside the database) and they renew themselves. If Garmin ever stops accepting them (you changed your Garmin password, or signed out of all devices), syncing stops and Settings and the Tasks page ask you to **Sign in again**. **Sign out** deletes the tokens.
- Signing in to a different Garmin account replaces the tokens of the old one.
- **Courses**: **From Garmin** on the **Routes** page lists the courses you made in Garmin Connect, with their sport, distance, climb and the date you made them, and marks the ones already here. Tick the ones you want (there's a search box and **Select all shown**) and they come in as routes with their heights and sport. That runs in the background, with its progress on the page; courses already here are never brought in twice.
- An activity deleted, renamed, given another sport or cropped in Garmin Connect after it came in isn't changed here on its own. Once a day, with activity sync on, Headwind compares the last 90 days in Garmin (and a little further back each day) with what it imported, and lists what changed on the **Import** page and the activity's own page: keep it as it is here, or take Garmin's (delete it here too, use Garmin's name or sport). A cropped one is offered with the other re-imports. **Check now** on the Import page runs it straight away. The same check reads again, from Garmin, any activity an older Headwind stored with its GPS and times out of step, so segments can time it again and another copy of it is found.
- **Full re-sync** (Settings → Garmin Connect) checks everything against all of your Garmin history at once. It also lists any Garmin activity that isn't here under "In Garmin, not here", to bring in or leave out, and the ones you deleted here under "Deleted here, still in Garmin", with **Bring back** (one still in Recently deleted comes back as it was here, not as Garmin has it). Each name opens the activity on Garmin Connect, to check it before deciding.
- Upgrading from a version that stored the password: the next sync swaps it for tokens and deletes it from the database.

### Home Assistant / MQTT
- Enter your broker in **Settings → Home Assistant**, under **Sensors out, over MQTT**. Headwind publishes retained **auto-discovery** config, so sensors appear in Home Assistant without YAML.
- The week sensors (`week_activities`, `week_ride_distance_mi` and the rest) count the week the way the rider chose under **Settings → Display**, and their names say which ("Activities Past 7 Days" or "Activities This Week"). Their entity ids never change, so automations keep working when the setting does.
- **TLS:** tick **Use TLS** so the broker's username and password don't cross the network as they are (brokers usually take TLS on port 8883, which the port changes to). A broker with a self-signed certificate needs the CA certificate that signed it: give its path on the server (with Docker, put it in the data volume, e.g. `/data/mqtt-ca.crt`); blank uses the system's. **Test connection** says when the certificate can't be verified. The publisher and the listener for Home Assistant's water button both use it.
- Sensors cover lifetime ride totals, last-ride details, recovery metrics, calories eaten / remaining, macros, hydration and weight. State is published on events plus a periodic heartbeat.
- Distances, climbs and speeds are published in mi, ft and mph whatever the units setting, so their ids and history never change, but each says it's a distance or a speed: to see one in km, m or km/h, pick the unit in the entity's settings in Home Assistant.
- Every sensor that's a number has a unit (counts too: rides, activities, badges, steps) or is marked as a measurement, so Home Assistant draws its history as a line graph and keeps long-term statistics for it. Text sensors, like the last activity's name, stay text. A reading Headwind doesn't have shows as unknown.
- **One publisher per broker:** two Headwinds on one broker must use different `HEADWIND_MQTT_PREFIX` values, or they'll overwrite each other's sensors.
- A separate connection (**Settings → Home Assistant → Health data in**) lets Headwind read HA entities (e.g. weight from a smart scale, a weather entity) via a long-lived token.
- The latest ride's route and the segments it crossed, and your run stats (best times, totals, weekly distance, latest run and its route), are published as attribute sensors too, so a dashboard can draw a map and a segment table. The example dashboard in [`docs/ha`](docs/ha) has Today, Body, Running and Riding tabs.
- Example Home Assistant dashboard and automation builders live in [`docs/ha`](docs/ha).

### AI coaching
- In **Settings → AI Provider** choose OpenAI or Claude (paste your key, pick a model) **or** a local **Ollama** (URL + model). Nothing is sent anywhere until you do.
- Pick a coaching personality and add your own goals; the model is also given recent history and the other times you've done the same route, so it can say whether you're improving.
- Every sport can be coached. A run is compared with your other runs, a swim with your swims, and so on: every earlier one you recorded, whether or not the coach has analysed it, so the first analysis already knows your history. Everything else you did in the 30 days before it is listed as other training, so a hard run the day before explains tired legs on a ride.
- **Progress by month**, under **Coaching Goals** on the AI Coach page: the coach is shown each month's average speed or pace, power and heart rate for the sport, up to the activity's month, to read the overall trend. Choose **The last 6 months** (the default), **The last 12 months**, **Since my comeback on…** a date, which also tells it to judge you against the rebuild rather than your old best, or **Off**.
- The coach also sees its own verdicts on the last three activities of the same sport it analysed, a line each, so it can follow up on something it raised (a heart rate drift, a pacing question) rather than start from scratch.
- **Analyse New Activities** (on the AI Coach page, off by default) writes the notes for each new activity from Garmin, the phone or an import as it arrives, for the sports you tick there: **Every sport**, groups such as Cycling or On foot, or single sports, so daily walks needn't each cost an API call. Only activities from the last 3 days are analysed, so importing your history doesn't run up a bill. **Bulk Analysis** can be limited to one sport the same way.
- Costs are whatever your provider charges; Headwind sends ride summaries, not raw GPS.
- The same key powers the optional food-photo estimate and screenshot import in the nutrition tracker.

### Friends (peer-to-peer)
1. On each instance open **Friends**, enter the other person's name, choose what they see and press **Create Code** (or, in the iPhone app, Settings → **Share with a friend**). It shows a QR code and a code starting `hwfc_`, once. Send it privately: anyone with it can read what it shares.
2. The other person scans the QR code with the Headwind iPhone app (Settings → **Add a friend**, or the Camera app), or pastes the code into **Friends → Add a Friend**, then picks the rider to follow.
   The code carries your address: **Settings → Outside address** when it's https, otherwise the address your browser used. If that's a home-network address the page warns you, since a friend's server can't reach it; set the outside address first.
3. Their activities and segments sync into your database; segments you both have appear on shared leaderboards, and their activities can be shown on the heatmap. Nothing inside your [privacy zones](#privacy-zones) is sent.
4. To race, start a **challenge** on the **Challenges** page and invite them; it reaches them on the feed.

If a friend moves their Headwind to a new address or sends you a new token, press **Edit** by their name on **Friends**, then paste the new code they made you, or change the address or token. The new connection is tried before it's saved, and their activities, segments and challenges stay.

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

1. **Use HTTPS.** Always. The recommended way is a [Cloudflare Tunnel](#recommended-cloudflare-tunnel), below.
2. **Set `SESSION_COOKIE_SECURE=true`** once you're on HTTPS.
3. **Use a strong password** (the generated one is fine; your own must be at least 10 characters) — never `admin/admin`.
4. **Don't forward a port on your router.** A tunnel doesn't need one.
5. Remember the **phone app only talks to HTTPS** servers.

If only you need to reach it, a VPN (Tailscale or WireGuard) is fine too. Friends' sync, though, needs an address their servers can reach, so it won't work over a VPN.

### Recommended: Cloudflare Tunnel

A [Cloudflare Tunnel](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/) puts Headwind at an HTTPS address such as `https://headwind.example.com` without opening a port on your router. A small `cloudflared` container makes an outbound connection to Cloudflare, and Cloudflare sends your visitors down it. HTTPS certificates are handled for you, your home IP address isn't published, and it works behind CGNAT. It's free; you need a domain whose DNS is on Cloudflare (a free Cloudflare account is enough).

**1. Create the tunnel.** In the [Cloudflare dashboard](https://dash.cloudflare.com) open **Zero Trust → Networks → Tunnels** and choose **Create a tunnel → Cloudflared**. Give it a name (e.g. `headwind`). On the install step choose **Docker**. The command shown ends `--token eyJ…`: copy that token. You don't need to run the command, because the compose file below runs `cloudflared` for you.

**2. Add a public hostname** for the tunnel (Cloudflare's menus may call it a *published application route*):

| Field | Value |
|---|---|
| Subdomain | `headwind` (or any name you like) |
| Domain | your domain, e.g. `example.com` |
| Service type | `HTTP` |
| URL | `headwind:5001` |

`headwind:5001` is the Headwind container's name and port on the Docker network that both containers share. Cloudflare creates the DNS record for you.

**3. Put the token and address in `.env`** next to `docker-compose.yml`:

```bash
TUNNEL_TOKEN=eyJ...the token from step 1...
APP_URL=https://headwind.example.com
```

The token lets anyone run your tunnel, so keep `.env` private and don't commit it anywhere.

**4. Use a compose file that runs both containers.** Replace `docker-compose.yml` with this:

```yaml
services:
  headwind:
    image: ghcr.io/atombrake/headwind:beta
    container_name: headwind
    # No "ports:" here. cloudflared reaches Headwind over the Docker network, so the tunnel is the only way in.
    volumes:
      - ./data:/data
      - ./garmin_tokens:/app/.garmin_tokens
    environment:
      - DATABASE_URL=/data/bike.db
      - SECRET_KEY=${SECRET_KEY:-}
      - APP_USERNAME=${APP_USERNAME:-admin}
      - APP_PASSWORD=${APP_PASSWORD:-}
      - APP_URL=${APP_URL}                # https://headwind.example.com, from .env
      - SESSION_COOKIE_SECURE=${SESSION_COOKIE_SECURE:-true}   # the login cookie only travels over HTTPS
      - TZ=${TZ:-}
      - LOG_LEVEL=${LOG_LEVEL:-}
    restart: unless-stopped

  cloudflared:
    image: cloudflare/cloudflared:latest
    container_name: headwind-cloudflared
    command: tunnel --no-autoupdate run
    environment:
      - TUNNEL_TOKEN=${TUNNEL_TOKEN}      # from .env
    depends_on:
      - headwind
    restart: unless-stopped
```

**5. Start it:**

```bash
docker compose up -d
docker logs headwind-cloudflared    # look for "Registered tunnel connection"
```

Open `https://headwind.example.com` and sign in. In the dashboard the tunnel should now show as **Healthy**.

Things to know:

- **Sign-in throttling still sees each visitor's own address.** `cloudflared` connects to Headwind from a private Docker address, which Headwind trusts by default, and passes the visitor's address in `X-Forwarded-For`. Leave `TRUSTED_PROXIES` unset.
- **Uploads through Cloudflare are limited to 100 MB** on the free plan, and a Strava export zip is often bigger. To import one, open the port on your home network for a while: add `ports: ["5001:5001"]` to the `headwind` service, put `SESSION_COOKIE_SECURE=false` in `.env` (or the login cookie won't be sent over plain HTTP), run `docker compose up -d`, and import at `http://<server-ip>:5001`. Then undo both changes and run `docker compose up -d` again.
- **Cloudflare Access** (Zero Trust's sign-in page) can add a second login in front of Headwind, but the phone app and friends' sync can't get past it. If you turn it on, those stop working.
- To pair the phone app, set **Settings → Outside address** to the `https://` address, because the pairing QR code is built from it. If the address changes later, the iPhone app offers to move to the new one the next time it opens.

### Other reverse proxies

Any HTTPS reverse proxy works: [Caddy](https://caddyserver.com), nginx, Tailscale Serve. A minimal Caddyfile:

```
headwind.example.com {
    reverse_proxy localhost:5001
}
```

Behind a proxy Headwind trusts one `X-Forwarded-*` hop, but only from a loopback or private address (or the ones in `TRUSTED_PROXIES`), so a client reaching port 5001 directly can't fake its address to get round the sign-in lockout. Make sure your proxy sets those headers, and keep port 5001 unreachable from outside anyway.

Where a direct client can still arrive from a private address (Docker Desktop on Mac or Windows, Docker's userland proxy, a port published on your LAN), it can claim a new address on each attempt and dodge the per-address lockout (8 failures in 5 minutes). A second limit covers that: 30 failures from all addresses together in 5 minutes closes sign-in to everyone until they age out, whatever the headers say. Signed-in browsers and paired phones carry on as normal. If your proxy runs on the same machine as Headwind, `TRUSTED_PROXIES=127.0.0.1,::1` closes the gap completely; if it runs in another container, set its Docker network instead (e.g. `TRUSTED_PROXIES=172.18.0.0/16`, from `docker network inspect`). While `TRUSTED_PROXIES` is unset, the log says once when it believed forwarded headers from a private address that isn't loopback, naming the address.

---

## Backups, updates and your data

- **Backup:** **Settings → Backup & Restore → Make backup** makes one zip: the database, rider avatars, food photos, gear photos and activity photos. It's made in the background, so a big database can't time out behind a reverse proxy: the card says how far it's got (the database copied, then files *n* of *N*), and you can leave the page. When it's ready, a notice at the top of whatever page is open links to the download (`headwind-backup-<date>.zip`), and ntfy says so too when it's set up. The zip is kept beside the database for a day, or until the next one is made, then deleted; the Settings card says how big the last one was. It deliberately excludes the Garmin token files, the kept Strava export, earlier backups, your generated login/key files and `.env`. The keys and passwords saved in Settings (AI, maps, MQTT, Home Assistant, friends' feed tokens, the Garmin email) stay encrypted in it, and the key to them (`.secrets_key`) is left out, so a backup shared by mistake doesn't give them away. Tick **Include the secrets key** to put it in (the file is then named `headwind-backup-with-secrets-<date>.zip`), so a restore on another server keeps them; anyone else with that zip can read them too. The rest of your data (rides with GPS, health, food) is in it as it is, so store it accordingly.
- **Restore:** **Settings → Backup & Restore → Restore** (or from the setup wizard on a fresh install). The uploaded database is checked for integrity, migrated and smoke-tested **before** anything live is touched; your current database is kept as `bike.db.pre-restore`; the swap itself is atomic. A backup this version can't use is rejected with "Nothing was changed". Restored on another server, the backup's saved keys and passwords can't be read: Headwind lists which to enter again. To keep them, restore a backup made with **Include the secrets key** (they're encrypted again with the new server's own key), or copy `.secrets_key` from beside the old database to beside the new one and restart.
- **Copies made before an upgrade or a restore** (`bike.db.pre-0.7.0`, `bike.db.pre-<version>`, `bike.db.pre-restore`) stay beside the database. Their saved keys and passwords are encrypted at start, as the database's are, so restoring one on the same server keeps them; going back to an older Headwind with one means entering them again.
- **Updating (Docker):** `docker compose pull && docker compose up -d`. The database is brought up to date at start-up, before the web server answers. Take a backup first on a beta. **Going back** to an older version after an upgrade needs a backup made before it (or the `bike.db.pre-<version>` copy kept before a change an older version can't read): an older Headwind won't open a database a newer one has changed.
- **Upgrading from an older compose file that used the placeholder `changeme` login:** the placeholder is no longer accepted — a random login is generated; read it from `docker logs`.
- **Moving to a new host:** copy `./data` and `./garmin_tokens`, or restore a backup and sign in to Garmin again.

---

## Privacy

**What leaves your machine** — only to services you configure or the public APIs below:

| Service | What for | What's sent |
|---|---|---|
| Garmin Connect | Activity/health sync | Your login (to Garmin), requests for your own data |
| Open-Meteo | Weather, elevation | Ride start coordinates + time |
| Open Food Facts | Food search/barcodes | The barcode or search text |
| Zwift's CDN (`cdn.zwift.com`) | A Zwift world's map, fetched by the server the first time it's drawn | A request for the map image |
| Map tile hosts: Esri, OpenTopoMap, CyclOSM (OpenStreetMap France), Waymarked Trails, and Thunderforest or Ordnance Survey if you save a key | Map tiles in your browser, for the map type you pick; the heatmap's HD export fetches the screen's tiles through the server (Thunderforest's straight from your browser) | Normal tile requests (your browser's IP, or the server's for an export); your Thunderforest or OS key with theirs |
| GitHub (`api.github.com`) | **Check for update** under Settings, only when you press it | A request for this project's release tags |
| Your AI provider (if configured) | Coaching, photo estimates | Activity summaries / the image you submit |
| Your MQTT broker / Home Assistant (if configured) | Automation | Sensor values / notifications |
| Linked friends (if configured) | P2P sync | Activities and segments you've chosen to share, and challenges you send |

**Nothing else.** Headwind sends no usage data, install pings or analytics anywhere, to its developers or anyone else.

### Privacy zones

**Settings → Sharing → Privacy zones** keeps places such as home or work out of what you share. Click the map where the zone goes, paste its latitude and longitude, or pick one of the places your activities most often start from, then choose its size, 200 m to 1.6 km. Inside a zone nothing is sent:

- to friends' Headwinds: your activities' positions, and the heart rate, power and the rest recorded there, are taken out, the start point becomes the first one outside, and a segment that starts or ends in a zone isn't shared;
- on a live tracking link (its track, your position, and the route it follows);
- to Home Assistant, in the latest ride's and run's tracks;
- in the heatmap's HD image.

Your own pages still show every track whole. A zone hides at least the size you chose all round the place, and more on one side, moved a random way when you make it, so the cut ends of many tracks don't draw a circle round your door. Adding, resizing or removing a zone sends the activities near it to friends again, cut the new way. The copy for troubleshooting (Tasks page) leaves your zones out, and with GPS left in, cuts them out of everything it keeps: the tracks and the readings taken inside, start points, laps, planned routes, segments that go inside, and the other copies of an activity.

---

## Security notes

The first public release, 0.1.0-beta, shipped after a dedicated review. In short:

- **No default credentials** — placeholder logins are rejected; a random key and password are generated per install.
- **Login throttling** (8 failures from one address, or 30 from all addresses together, in 5 minutes), **session revocation** when the password changes, **cross-site request blocking**, open-redirect fix.
- **Restore** is hardened (no path-chosen uploads, archive allow-list and size limits, integrity check, atomic swap).
- **Stored-content injection** (ride/friend/segment names, friend-supplied route shapes) is escaped or validated; avatars that aren't decodable images are rejected.
- **Resource limits** on imports, archives and peer feeds; peer redirects restricted to the same host.

Since then:

- **Saved secrets are encrypted** — the AI keys, Home Assistant token, MQTT password, friends' feed tokens and the Garmin sign-in are encrypted in the database with a key kept beside it (`.secrets_key`), and never sent back to the Settings page.
- **The Garmin password isn't kept** — only the sign-in tokens Garmin gives back.
- **The login password is stored as a hash** (scrypt, in `.admin_login`) and never written to `.env`; new passwords need at least 10 characters. A password saved in plain text by an older version is hashed at the next start, and browsers signed in then stay signed in.
- **Feed tokens are per friend**, each sharing only the riders ticked for it, sent in a header only and compared in constant time; `X-Forwarded-*` headers are only believed from a trusted proxy.
- **A friend's activities can't be changed** on your instance.
- **Phone tokens not used for 90 days** are flagged on **Phones**, with a button to revoke them.
- **MQTT can use TLS**, with your own CA certificate for a self-signed broker.
- **Pictures over 50 megapixels are refused** before they're decoded (activity, gear, avatar and food photos), so one upload can't take half a gigabyte of memory.
- **Only Headwind's own script files run** — the Content-Security-Policy allows scripts from the server's own files and nothing inline, so text that slipped into a page unescaped still couldn't run as script. Pages can't be framed by other sites (`frame-ancestors 'none'`).

Known limits: one shared admin login; in the advanced multi-rider mode phone devices aren't scoped per rider. See [Known limitations](#known-limitations-and-roadmap). To report a vulnerability, please [open a private security advisory](../../security/advisories/new) on GitHub rather than a public issue.

---

## The iPhone and Apple Watch app

A native SwiftUI app in [`ios/`](ios/README.md), paired with your server through the phone API (`/api/v1`). It isn't on the App Store: build it onto your own iPhone with Xcode (a free Apple ID works, though its builds expire after 7 days). [ios/README.md](ios/README.md) has the steps.

- **Record any sport** on the iPhone or the Watch: rides on the bike you pick, runs, walks and hikes, swims on the Watch, and timed sessions (indoor rides, treadmill runs, strength, HIIT, yoga). The phone reads Bluetooth heart rate straps, power meters, speed and cadence sensors and smart trainers; the Watch uses the sensors paired in its own settings. Recordings go through the normal import (best times, segments, weather), and the phone shares its position with Home Assistant while recording.
- **A live tracking link** to send when you start recording, stopped from the phone, the Watch or the server's Phones page (see [A live tracking link](#a-live-tracking-link-iphone-app)).
- **On the Lock Screen and in the Dynamic Island:** a recording on the iPhone shows its time, distance, speed or pace and heart rate there, and whether its live link is being shared.
- **A map on the Watch:** while recording anything with GPS, a third page after the figures shows your track so far and where you are, turned the way you're going, with distance and time (or pace on foot) over it. The Digital Crown zooms it.
- **The Watch on its own:** with the phone out of range it uploads over Wi-Fi or cellular, with a token of its own listed under the phone on **Phones** and revoked with it. On Apple Watch Ultra the Action button starts and pauses a workout.
- **Today, Activities and Overview:** the food diary and calories, every activity with its map, charts and photos (add, caption, reorder, delete), and totals for each sport.
- **Apple Health:** steps, resting heart rate, HRV, sleep, weight, body fat, calories and other apps' workouts, each switched on by itself. A workout already on the server, or deleted there, isn't read or sent again. A workout whose route is only a stale location (some apps save one) goes up timed, with Apple Health's own time, distance, calories and heart rate. If an older app sends that route anyway, the server refuses it rather than store an empty activity. Garmin's figure wins on a day it has one (steps follow the source chosen on the **Steps** page), a weigh-in never replaces a manual or Garmin one, and Apple's HRV (SDNN through the day) is kept apart from Garmin's (RMSSD overnight). **Remove Apple Health data from Headwind** deletes it from the server.
- **Friends:** make a share code as a QR code, or add a friend by scanning theirs.

It **requires HTTPS**, and a server new enough for it: an app from this release on refuses to pair with a Headwind older than 0.7.47-beta, and says so if the one it's paired with is. Upstream's Android app doesn't work with this server: the older phone paths it used are gone. Pair it from **Phones**: name the phone, press **Create token**, then scan the QR code in the app or with the iPhone's Camera. A token works until it's revoked: **Phones** shows when each was last used, flags those not used for 90 days, and revokes them with one button (a phone counts as used while its Watch is, and its Watch's token goes with it).

---

## Troubleshooting

| Problem | Try |
|---|---|
| **Can't sign in / forgot the password** | A generated one that's still in use: `docker logs headwind 2>&1 \| grep -A3 "generated one"`. Otherwise Headwind keeps only a hash, so set a new `APP_PASSWORD` in `.env` (one it hasn't seen before) and recreate the container: that one then works, and you can choose another under **Settings**. On Windows, use **Reset sign-in password** in the tray menu. After 8 wrong tries from one address, or 30 from everywhere, sign-in waits 5 minutes. |
| **"Too many attempts"** | The login locks for a few minutes after 8 failures. Wait, or restart the container. |
| **Port 5001 is in use** | Change the left side of `ports` in `docker-compose.yml`, e.g. `"5002:5001"`. |
| **Garmin asks you to sign in again after every restart** | The `garmin_tokens` folder must be a persistent volume; check it's mounted and writable. |
| **Garmin sync finds nothing** | Make sure activity sync is enabled in Settings → Garmin and the account matches the one you connected. Failed rides are retried on the next sync. |
| **Phone app can't pair** | It needs an **HTTPS** address. Put Headwind behind a [Cloudflare Tunnel](#recommended-cloudflare-tunnel) or another TLS proxy and save that address under **Settings → Outside address**. |
| **Home Assistant sensors missing** | Check the MQTT broker settings, that discovery is enabled in HA, and that no other Headwind uses the same `HEADWIND_MQTT_PREFIX`. |
| **Map is blank** | Your browser needs to reach the map tile hosts listed under [Privacy](#privacy). The map and chart libraries come from Headwind itself. |
| **Windows SmartScreen warning** | The build is unsigned. More info → Run anyway, or use Docker. |
| **Restore says "not compatible"** | The backup's database couldn't be migrated, or is from a newer Headwind. Nothing was changed — your current data is intact. |
| **Reporting a bug** | **Tasks → Download diagnostics** gives one zip to attach: the recent logs, the version, settings without passwords, keys or addresses, and row counts. When someone helping needs your data itself, **Tasks → Make a copy for troubleshooting** makes the database without saved keys, passwords, tokens, addresses, your friends' data or photos, and without GPS or the streams if you tick them (with GPS left in, the places inside your [privacy zones](#privacy-zones) are cut out of it); the page lists what's still in it. It's made in the background (a minute or so on a big database; you can leave the page) and offered on the Tasks page for a day, or until you delete it or make another. An error page shows a reference such as `3f9c2a1b`, and so does a message when a sync, an AI analysis, a friend's address or a restore fails for a reason other than something you can fix; quote it, and the matching log lines carry `[3f9c2a1b]`. The log file is `./data/logs/headwind.log`. Set `LOG_LEVEL=DEBUG` in `.env` and recreate the container for more detail. |
| **Want to start over** | Stop the container and move `./data` aside (don't delete it until you're sure). |

---

## How it works

**Stack** — Python 3.14 / Flask, SQLite (WAL), Jinja templates, vanilla JavaScript, Chart.js, Leaflet. Two gunicorn workers (`WEB_WORKERS`) with several threads each serve the pages, sharing nothing but the database; the background work (imports, backups, the Garmin and friend syncs, MQTT, AI analyses: whatever a page starts, and the timed loops) runs in a worker process beside it, which Gunicorn starts. Shipped as a multi-arch Docker image. Windows build: PyInstaller + waitress + pystray.

**Layout**

```
app.py              application factory, auth guard, the timed background loops
config.py           environment + settings loading
database.py         schema: numbered steps (STEPS, PRAGMA user_version), then the start-up checks and repairs
routes/             one blueprint per area (activities, segments, nutrition, friends, settings, setup, api_v1 …)
services/           Garmin, parsing, segments, best efforts, AI, MQTT, backup, credentials, limits …;
                    worker.py + jobs.py: the background worker and its queue
gunicorn.conf.py    starts the background worker beside Gunicorn
templates/ static/  UI; static/vendor holds Chart.js, Leaflet and the barcode scanner (scripts/vendor.py)
scripts/            smoke tests, Windows build, helpers
tests/              unit tests
docs/               Home Assistant builders, screenshots, notes
```

**Data model (SQLite)** — `Activity` (every sport; `Ride` is a view of the rides in it), `ActivityStream` (each activity's GPS/HR/power streams, compressed), `ActivityTrack` (track summaries for the heatmap and segment matching), `ActivityPhoto`, `ActivityDuplicate` (recordings set aside and Recently deleted, their streams compressed), `BestEffort` + `SportEffort` (best times), `Segment` + `SegmentEffort`, `Bike` + `Part` + `ServiceLog` + `BikeDefault` and `Kit` + `KitDefault` (Gear), `Goal`, `Challenge` (+ members, invites), `FoodLog`, `HydrationLog`, `WeightLog`, `SavedMeal(+Item)`, `FoodFavourite`, `CustomFood`/`FoodOverride`, `Friend` + `FeedToken` (+ imported riders/segments/shared foods), `GarminDaily`, `GarminChange`/`GarminMissing`/`GarminFailure` (Garmin review lists), `StravaExport` + `StravaBike`/`StravaKit` (Strava imports), `ImportChange`/`ImportProblem` (Import page review lists; an import's streams compressed), `TaskLog`, `Settings`, `Rider`. Schema changes are numbered steps (`database.STEPS`), applied before the server starts; restoring an older backup migrates it first.

---

## Known limitations and roadmap

**Known limitations**
- One shared admin login. For several people, run a Headwind each.
- Phone-API tokens aren't scoped per rider (only matters in the advanced multi-rider mode).
- The arm64 image and Windows build are new and lightly tested; the Windows build is unsigned.
- Strava's live API is closed to new apps, so Strava is import-only (export zip).
- Some background jobs (large imports, bulk AI) run in-process and can be slow on small hardware.
- Dependencies aren't yet pinned to an exact lock file.

**Roadmap (no promises)**
- Per-device scopes.
- Signed Windows build and an installer.
- A proper job queue for imports and bulk AI.
- More analytics and a deeper recovery view.

---

## Development

The same on Windows, macOS and Linux, with [uv](https://docs.astral.sh/uv/). It reads `.python-version` (3.14, as in the Docker image and CI) and fetches that Python if the machine doesn't have it:

```bash
uv venv && uv pip install -r requirements-dev.txt   # once, and again after requirements*.txt change
uv run python -m pytest tests -q -n auto            # unit tests, spread across every core
```

Without uv: make a Python 3.14 virtual environment, `pip install -r requirements-dev.txt` in it, then `python -m pytest tests -q -n auto`. CI runs the tests on Linux, Windows and macOS. Text opened without `encoding=` fails a test on all three (`pytest.ini`), because Windows would otherwise read it as cp1252.

```bash
# End-to-end smoke tests — throwaway instance only (they write data):
d=$(mktemp -d); printf "DATABASE_URL=$d/t.db\nSECRET_KEY=x\nAPP_USERNAME=t\nAPP_PASSWORD=t\n" > $d/env
HEADWIND_ENV=$d/env PYTHONPATH=. python3 scripts/smoke_setup_wizard.py
```

Other smoke scripts: `smoke_client_ops`, `smoke_api_v1`, `smoke_recipes_sync`, `smoke_ride_upload`, `smoke_single_rider`.

- Schema changes are numbered steps: a new function at the end of `database.STEPS`, never an edit to an earlier one (a database that has had a step never runs it again; `tests/test_migrations.py` checks). A service's own tables stay in its `ensure_schema`, which runs at every start. Docker runs the steps before Gunicorn (`python -m database migrate`).
- Dates are UK format everywhere ("15 May 2026", from `services/dates.py`: never `strftime('%-d')`, which Windows rejects); the UI uses CSS custom properties (no hard-coded colours).
- **Dependencies:** `requirements.txt` lists what the app needs, loosely (`>=`). The Docker image installs the exact versions and hashes in `requirements.lock`, so a rebuild gets the same packages. The lock is made with pip-tools inside the image's base image (Linux; amd64 and arm64 resolve the same, and the hashes cover every platform's wheels). After changing `requirements.txt`, or to take newer versions, refresh it:
  ```bash
  docker run --rm -v "$PWD":/src -w /src python:3.14-slim sh -c "pip install -q pip-tools && pip-compile --upgrade --generate-hashes --allow-unsafe --strip-extras --output-file=requirements.lock requirements.txt"
  ```
  Leave out `--upgrade` to keep the current pins and only add what `requirements.txt` changed. CI runs `pip-audit` against the lock on every push. The Windows build has a lock of its own, `requirements-windows.lock`, from `requirements.txt` and `requirements-windows-build.txt` (PyInstaller), because pip-compile leaves out the Windows-only packages when it runs on Linux. Make it by running the **Windows lock** workflow from the Actions tab (tick **upgrade** for newer versions) and committing the file it uploads. Until that file is in the repo, the Windows build installs loosely.
- Contributions are welcome — open an issue first for anything big. Please include a test or a smoke check with behaviour changes.

---

## Acknowledgements and licence

Headwind began as [lordmaa's original Headwind](https://github.com/lordmaa/headwind); see [Where Headwind came from](#where-headwind-came-from). It stands on a lot of generous open data and software: [Open Food Facts](https://openfoodfacts.org), [Open-Meteo](https://open-meteo.com), [OpenStreetMap](https://www.openstreetmap.org) contributors, [Esri](https://www.esri.com) imagery, [OpenTopoMap](https://opentopomap.org), [CyclOSM](https://www.cyclosm.org), [Waymarked Trails](https://waymarkedtrails.org), [Leaflet](https://leafletjs.com), [Chart.js](https://www.chartjs.org), [Flask](https://flask.palletsprojects.com), [garminconnect](https://github.com/cyberjunky/python-garminconnect), [fitparse](https://github.com/dtcooper/python-fitparse), [gpxpy](https://github.com/tkrajina/gpxpy), [paho-mqtt](https://github.com/eclipse/paho.mqtt.python) and [Home Assistant](https://www.home-assistant.io).

Released under the [MIT licence](LICENSE), which keeps the original's copyright notice alongside this project's.

## Public demo
**[Try it at headwind-demo.atombrake.info](https://headwind-demo.atombrake.info).** Demo mode (`HEADWIND_DEMO=1`) runs a Headwind anyone can try: every page and action is shut unless it's been checked as safe to show, it connects to nothing on the network around it, visitors press **Enter the demo** to sign in, and the data resets every night. Its data is a made-up athlete's two years in four national parks, on tracks drawn by a routing engine, so no real track is in it; only coordinate-free patterns (how often, how far, how fast and how hard) come from a real database, and an audit refuses to publish anything else of it. [demo/README.md](demo/README.md) says how to build it and run it behind a Cloudflare tunnel.
