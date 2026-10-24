# Gear: bikes, parts, service, shoes and other gear

Track which bike rode which ride, what is fitted to each bike, how far every chain, tyre and cassette has gone, and get a nudge when something is due.
Everything is computed from your rides, so correcting a ride's bike corrects all the mileage. It lives in **Gear** in the sidebar.

## 1. Add your bikes
**Gear > + Add bike.** Name, type, brand, model, year, an optional photo, and any mileage the bike already had before you started using Headwind.
The first bike you add becomes your **default**: every new ride (Garmin sync, a file you import, a phone recording, an activity you type in) is put on it automatically.

With more than one bike, give each kind of ride its own: **Defaults for new activities** at the bottom of the Gear page has a line for commutes,
mountain bike, gravel, e-bike and indoor rides (and any other kind you've ridden), and one for every other ride. Or tick them in a bike's form
under "Default for new rides". A commute goes on the commute bike whatever its sport; otherwise a ride takes the bike for its kind, else the one
for every other ride. Retired bikes are skipped. Garmin's mountain biking and gravel types come in as mountain bike and gravel rides; rides an
older sync saved as plain rides can be given their kind back with "Check activity types with Garmin" in Settings. A Strava bike's default sport types
(bikes.csv) become its defaults when you match it, where you have none yet.

Changing a default only affects rides that arrive afterwards. Ticking **Commute** or changing a ride's sport later picks its bike again, as long
as the bike was given by a default; one you chose yourself (or the phone, or a Strava export, named) stays. To bring older rides in line, the
defaults card lists how many would move and **Apply to past activities** moves them: rides with no bike or still on the bike a default gave
them, and, if you tick it, rides on another bike too (rides from before Headwind kept track can't be told apart from ones you picked by hand).
Rides whose Strava bike you haven't matched yet wait for the match.

Photos are resized to a JPEG and stored beside your database (`bikeimg/`), so they are included in backups and survive upgrades.

## 2. Say which bike rode the older rides
You will have years of rides with no bike. **Gear > Assign rides** opens a calendar:

* click days to pick them, shift-click to pick a stretch, or set a **From / To** range (tick "all the way to today" for an open end);
* quick buttons: **From picked day to today**, This month, This year, **All unassigned rides**;
* pick the bike, and decide whether rides that already have a bike are left alone (the default);
* Headwind shows exactly how many rides will change *before* you press Apply.

Days with rides that still have no bike are outlined in orange, and each ride day carries a colour stripe for the bike(s) it was on. The picked days' rides are listed under the calendar, each with its own bike picker, so a day with a road ride and a mountain-bike ride can be split. Walks, runs and hikes are never touched.

To go through them one by one instead, click the count in the Gear page's "activities have no gear" note, or one of the types after it (rides, runs, walks, ...). It opens the Activities page filtered to them (the **Gear** filter in the search form, "No gear"), a month at a time like the rest of the history, with a row of types and their counts above it to show one sport alone. Each row has a picker at the end: a bike for a ride, shoes or other gear for anything else. Only sports you have gear for are counted: runs once a pair of shoes is the default for runs or has been on one, but never yoga or a swim you've no gear for. An activity leaves the list as soon as it has some. The same filter lists a bike's rides or a pair of shoes' activities.

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

* Tick the sports it's the **default** for (runs, walks, hikes, ..., and commutes): each new activity of those sports is put on it, as a new ride is put on its bike. A sport has one default; ticking it on another item moves it there. They're on the Gear page's defaults card too, and follow the same rules as bikes: a commute first, a change of sport or commute picks again unless you chose the gear yourself, and **Apply to past activities** brings older ones in line.
* Its distance and time are added up from its activities, so moving an activity to other shoes corrects both pairs.
* At 90%, 100% and 125% of its replace-at distance you get the same nudge as a bike part, once each, and it shows under "Needs attention" and on the dashboard.
* **Retire** a pair when it's done: it keeps its history and the date, stops being a default and stops nudging. It can still be picked for an activity, listed last and marked retired, so an old run can be put in the shoes it was done in. Retired bikes are the same.
* Its page is laid out like a bike's: a photo, its figures, distance by year and by sport, **Assign activities to it** by date for the sports you tick, and the recent ones with "See all". Only a bike has parts and a service log.
* On an activity's page the **Gear** dropdown changes that activity; on the Activities page, **Select** then **Gear…** changes many. Rides keep their bike and never take kit.

Importing a **Strava export** makes an item for each pair of shoes your walks, runs and hikes name in it, and puts those activities on it. Pairs last worn more than a year ago come in retired.

## Data and backups
Gear adds tables `Bike`, `Part`, `ServiceLog`, `PartAlert` and `BikeDefault`, a `bikeId` and `bikeAuto` on rides and a `defaultBikeId` on riders; shoes and other gear add `Kit`, `KitDefault`, `KitAlert` and `StravaKit`, and a `kitId` and `kitAuto` on activities (`*Auto`: the gear a default gave it). They are created automatically on upgrade (nothing is dropped).
Bike and kit photos live in `<data folder>/bikeimg/`: `/data/bikeimg/` in Docker, `%LOCALAPPDATA%\Headwind\bikeimg\` for the Windows build. Settings > Backup includes them and Restore brings them back.

## Not in v1 (planned)
The phone app does not have a Gear screen yet (a bike picker on ride detail is next). Components cannot yet be moved between bikes (log a replacement on the new bike instead).
