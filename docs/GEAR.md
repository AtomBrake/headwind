# Gear: bikes, parts, service, shoes and other gear

Track which bike rode which ride, what is fitted to each bike, how far every chain, tyre and cassette has gone, and get a nudge when something is due.
Everything is computed from your rides, so correcting a ride's bike corrects all the mileage. It lives in **Gear** in the sidebar.

## 1. Add your bikes
**Gear > + Add bike.** Name, type, brand, model, year, an optional photo, and any mileage the bike already had before you started using Headwind.
The first bike you add becomes your **default**: every new ride (Garmin sync, a file you import, a phone recording, an activity you type in) is put on it automatically.
Change the default any time on the Gear page, a bike's page, or your rider page. Changing it only affects rides that arrive afterwards, never history.

Photos are resized to a JPEG and stored beside your database (`bikeimg/`), so they are included in backups and survive upgrades.

## 2. Say which bike rode the older rides
You will have years of rides with no bike. **Gear > Assign rides** opens a calendar:

* click days to pick them, shift-click to pick a stretch, or set a **From / To** range (tick "all the way to today" for an open end);
* quick buttons: **From picked day to today**, This month, This year, **All unassigned rides**;
* pick the bike, and decide whether rides that already have a bike are left alone (the default);
* Headwind shows exactly how many rides will change *before* you press Apply.

Days with rides that still have no bike are outlined in orange, and each ride day carries a colour stripe for the bike(s) it was on. The picked days' rides are listed under the calendar, each with its own bike picker, so a day with a road ride and a mountain-bike ride can be split. Walks, runs and hikes are never touched.

To go through them one by one instead, click the count in the Gear page's "activities have no gear" note, or one of the types after it (rides, runs, walks, ...). It opens the Activities page filtered to them (the **Gear** filter in the search form, "No gear"), a month at a time like the rest of the history, with a row of types and their counts above it to show one sport alone. Each row has a picker at the end: a bike for a ride, shoes or other gear for anything else. An activity leaves the list as soon as it has some. The same filter lists a bike's rides or a pair of shoes' activities.

On any single ride, the **Bike** dropdown at the top of the ride page changes just that ride.

## 3. Track the parts that wear out
Open a bike and use **+ Add a part**. Pick from the list (chain, cassette, chainrings, tyres, tubeless sealant, brake pads and rotors, brake fluid, cables, bar tape,
headset and wheel bearings, bottom bracket, cleats, suspension service...) or "Other part". Each part starts with sensible default intervals which you can change:

| Interval | Meaning |
|---|---|
| **Replace every** (miles/km and/or days) | when it should be swapped |
| **Check every** (miles/km and/or days) | when to look at it, measure it, lube it or top it up |

Use distance, days, or both (whichever comes first). Sealant and bar tape are good "days" parts; a chain is a distance part.
If a part was already worn when you fitted it (a second-hand wheelset, say) enter how much under "already worn when fitted".

A part's mileage is the distance of the rides on that bike since the day you fitted it, so it is always up to date and always consistent with your assignments.

## 4. Log the work
**Service log > + Log some work:** replaced, serviced, inspected, cleaned, adjusted, topped up. Logging an inspection or service restarts that part's **check** clock.
Logging **Replaced** retires the old part (its lifetime stays in "Retired parts") and, if you leave "Fit a new one" ticked, fits a fresh one with the same intervals.

## 5. Alerts
A part is **soon** at 90% of an interval, **due** at 100% and **overdue** at 125%. You see this as coloured bars on the bike page, a "Needs attention" list on the Gear page and a card on the dashboard.
You are also notified (ntfy, and a Home Assistant push if MQTT is set up) once for each level, never repeatedly: the alert resets when you check or replace the part.
Turn alerts off per part. Time-based parts are re-checked about hourly, so sealant becomes due even if you do not ride.

## 6. Shoes and other gear
Below the bikes, **Shoes and other gear** keeps everything else an activity is done in or on: shoes, a wetsuit, skis, a board, a boat. **Gear > + Add shoes or gear**:
name, type, brand, model, when you bought it, any distance it had before Headwind, and a **replace at** distance (700 km to start with for shoes; blank for never).

* Tick the sports it's the **default** for (runs, walks, hikes, ...): each new activity of those sports is put on it, as a new ride is put on the default bike. A sport has one default; ticking it on another item moves it there.
* Its distance and time are added up from its activities, so moving an activity to other shoes corrects both pairs.
* At 90%, 100% and 125% of its replace-at distance you get the same nudge as a bike part, once each, and it shows under "Needs attention" and on the dashboard.
* **Retire** a pair when it's done: it keeps its history, stops being a default and stops nudging.
* On an activity's page the **Gear** dropdown changes that activity; on the Activities page, **Select** then **Gear…** changes many. Rides keep their bike and never take kit.

Importing a **Strava export** makes an item for each pair of shoes your walks, runs and hikes name in it, and puts those activities on it. Pairs last worn more than a year ago come in retired.

## Data and backups
Gear adds tables `Bike`, `Part`, `ServiceLog` and `PartAlert`, a `bikeId` on rides and a `defaultBikeId` on riders; shoes and other gear add `Kit`, `KitDefault`, `KitAlert` and `StravaKit`, and a `kitId` on activities. They are created automatically on upgrade (nothing is dropped).
Bike photos live in `<data folder>/bikeimg/`: `/data/bikeimg/` in Docker, `%LOCALAPPDATA%\Headwind\bikeimg\` for the Windows build. Settings > Backup includes them and Restore brings them back.

## Not in v1 (planned)
The phone app does not have a Gear screen yet (a bike picker on ride detail is next). Components cannot yet be moved between bikes (log a replacement on the new bike instead).
