# Multi-user support: plan

**Status:** made 2026-11-23 at 0.7.52-beta, decisions agreed the same day. A1 and A2 are built (`services/whose.py`); the rest is plan. It turns **Proper multi-user support, with roles** (TODO.md, P3 → Users) into releases that can each ship on their own. It also adds two things the TODO doesn't have: bringing another Headwind in as a rider, and an import folder for each user. Line numbers drift; function names are the stable reference.

## Where things are today

- **One login.** `services/credentials.admin_login` gives one username and password hash, from `.admin_login` or the environment. The session holds `logged_in` and `av` (`credentials.auth_version`), checked in `check_login` in `app.py`.
- **Riders are profiles, not people.** `Rider` rows are of three kinds: the owner (`isDefault=1`), other local riders (multi-rider mode, `services/rider_mode.py`), and friends' riders made by friend sync (`Friend.riderId`, read-only through `services/friend_rides.refuse`). Whoever is logged in can see and change every local rider.
- **"Whose data" is decided in many places.**
  - 33 queries pick `Rider WHERE isDefault=1`, in 26 files.
  - Six local helpers pick a rider their own way: `api_v1._rider`, `roughness._rider`, `nutrition._default_rider_id`, `gear._rider_id`, `goals._rider_id` and `dashboard._riders`.
  - `?rider=` / a form's `rider` is read in 10 route files.
- **Background work is the owner's.** Garmin sync (`services/garmin.py`, 3 places), MQTT (`services/mqtt.py`, 4), Home Assistant, live tracking, MQTT commands, the AI context and two start-up jobs in `app.py` all pick the owner.
- **Personal data sits in `Settings` (id=1).** Height, sex, birth date, activity factor, weight and step goals, every nutrition goal, holidays, `calorieAdjustPct`, `coachingGoals`, `coachPersonality`, `units`, `tempUnit`, `appearance`, `favouriteSports` and `timeZone` are all there, beside instance config (AI keys, MQTT, Home Assistant, map keys, `externalUrl`) and about 30 once-only repair flags. So today every local rider shares the owner's goals and preferences.
- **Garmin is one account per instance.**
  - The account: `Settings.garminEmail` and `garminPassword`, and about 20 more `garmin*` state columns (`garminSyncMode`, `garminLastOk`, `garminFailCount`, the history and weigh-in backfill cursors and so on). These are read in 15 files: `services/garmin.py` 32 times, `app.py` and `routes/garmin.py` 15 each.
  - The login: a single token file, `TOKEN_DIR/garmin_tokens.json` (`services/garmin.py`, `.garmin_tokens` or `HEADWIND_TOKEN_DIR`, a Docker volume).
  - The sync: two loops, `_garmin_heartbeat` and `_garmin_history` in `app.py`.
- **Some tables have no owner:** `GarminDaily` (primary key `date`), `SavedMeal`/`SavedMealItem`, and `PlannedRoute` in part.
- **Many writes go by row id only**, e.g. `DELETE FROM FoodLog WHERE id=?`. That's fine with one login. With two, it lets one user change another's rows by guessing ids (an IDOR).
- **312 routes** (`@bp.route`): nutrition 60, api_v1 45, gear 35, activities 25, friends 16 and the rest.
- **Phones:** `DeviceToken` has no owner. A token is made from a web session on the Phones page (`routes/phones.create`), so recording the user who made it needs no change in the iPhone app.
- **Backups:** `services/backup.py` makes and restores one zip of everything: `build`, `stage_upload`, `validate`, `prepare` (migrates a staged copy to the current schema) and `apply` (snapshots to `.pre-restore`, then swaps). A restore *replaces* `bike.db`, and nothing merges.
- **There's no import folder yet:** TODO's **Auto-import folder** (P3) describes one for a single rider.
- **Product promise:** the README's design principles say "One person per instance", and Beta status says "It is not a multi-user system". Both change at the end.

## The model

- **User**: someone who signs in. Each user has exactly one rider (`User.riderId UNIQUE`).
- **Rider without a user**: a profile an admin keeps, e.g. a child's. These stay possible, and admins see and edit them as today.
- **A friend's rider is never a user**, and stays read-only.
- **Two roles.** **Admin**: every local rider, instance settings, users, backups, Tasks. **Standard user**: their own rider's data, their own preferences and their own connections (Garmin, import folder), and nothing else unless shared.
- **One place answers "whose data is this request about?"** (`services/whose.py`, below). A route never picks a rider itself.

## Decisions (agreed 2026-11-23)

1. **Admins can see standard users' data**, through the rider picker as today. The invite page and the Users page say so plainly. They run the server and could read `bike.db` anyway.
2. **Local users are private from each other by default** (segment leaderboards, `seg_rivals` on the ride page, the heatmap's "whose", goals invitations). A later per-user switch can make a user "visible to others on this instance". Segment *definitions* stay shared and efforts stay per rider.
3. **Every personal preference is per user**: units, temperature unit, appearance, favourite sports, time zone, AI personality and coaching goals, and all the body, nutrition and goal figures. New users get the instance's values as their defaults. AI keys, map keys, MQTT, Home Assistant and the outside address stay instance-wide and admin-only.
4. **Garmin is per user from the start.** Each user connects their own Garmin account, and the sync runs for every connected account. The account refactor is done as groundwork in release A (A7), so it's in place before a second user can exist.
5. **Invite only**: a one-time link from the Users page, stored as a hash like `DeviceToken`, which expires after 7 days. There is no open sign-up.
6. **An existing local rider gets a login through an invite tied to that rider.** Nothing is copied or moved.
7. **Home Assistant entities (MQTT) are per user**, decided while building A1–A2. Each user can turn their own entities on or off, and every user who has them on gets their own set in Home Assistant (C7).
8. **Gear is the rider's own**, decided while building A1–A2. A standard user changes only their own bikes, kit and parts; an admin can add and change gear for the other local riders. A friend's rider never has gear here: from A on, the gear pages don't offer friends' riders and refuse one in `?rider=` or a form.

Still open, decided in the releases below:
- **Friends.** Each user has their own friends and their own feed codes (release G). Until then, Friends is admin-only.
- **What a merge brings over** (release E): a proposal is below.

## Releases

Each release passes the full test suite, adds its database changes as new `database.STEPS` (never edits to old ones), and gets a CHANGELOG entry. A and B change nothing on screen. User creation only ships in C, together with the checks that make it safe.

```
A groundwork ── B accounts ── C roles & scoping ── D exports ── E merge another Headwind ── G friends & AI per user
     └──────────── F import folders (any time after A; per user once C is in) ┘
```

### A. Groundwork (no visible change)

Large in line count but mechanical. It can go out as several small releases.

1. **`services/whose.py`**
   - `rider_id()`: in a request, the rider this request is about. In A that's the owner, and from C it's the signed-in user's.
   - `viewable(want)`: whether `?rider=N` may be shown and how (own / editable / read-only friend / no). In A it gives exactly today's answers.
   - Replace all 33 `isDefault=1` request-path queries and the six local helpers with these. `page_facts.ownerId` stays for "is this the owner" display logic only.
2. **Background work takes a rider id.** Garmin, MQTT, Home Assistant, live, `mqtt_commands`, `context` and the start-up jobs in `app.py` get the rider as an argument instead of looking it up. Their callers still pass the owner. Nothing outside a request may call `whose.rider_id()`: it raises there, so a missed caller fails loudly.
   - **As built:** what really belongs to the instance asks for the owner by name, `rider_mode.owner_rider_id()`, never `whose`: the Garmin loops and history backfill (until A7), the goal auto-update (until A4), the friend sync's challenge invitations, and the feed and foods feed a friend's Headwind reads (until G). MQTT and the Home Assistant import each have one resolver, `mqtt.sensor_rider()` and `homeassistant.import_rider()`, which callers ask once and hand down; C7 turns the first into the list of users with their entities on.
   - `tests/test_whose.py` fails if `isDefault=1`, or "the first rider by `isDefault DESC` … `LIMIT 1`", appears in `routes/` or `services/` outside `whose.py`, `rider_mode.py` and `page_facts.py`, or if a route other than `routes/friends.py` calls `owner_rider_id()`.
3. **Every endpoint declares its access.** Add an `@access('public' | 'any' | 'admin' | 'own')` decorator, or a table in `routes/__init__.py`, and use it to replace `_PUBLIC` in `app.py`. A test walks `app.url_map` and fails on any endpoint without a declaration. In A, `check_login` treats every signed-in session as allowed everywhere, so behaviour is unchanged. This turns the 312 routes into a checklist the test enforces, including routes added later.
4. **Personal settings move out of `Settings`.** Add a `RiderSettings` table (`riderId` primary key) with the columns from decision 3. A step copies the owner's values into it and gives each other local rider a copy too, which is what they see today. Readers go through `whose`: `page_facts`, `services/units.py`, `services/tz.py` (its `_cache` becomes per rider), `services/context.py`, `routes/nutrition.py`, `services/goals.py` and the rest (`units` alone is read in about 30 files). The old `Settings` columns are left in place for one release so a downgrade still works, then dropped.
5. **Owners for the ownerless tables.** `GarminDaily` becomes `(riderId, date)`. That's a table rebuild in a step with `keep_copy=True`, because older code reads it by `date`. `SavedMeal` and `PlannedRoute` get `riderId`, set to the owner on upgrade. `Segment`, `FoodOverride` and `FoodImage` stay shared.
6. **An ownership map.** One table in `services/whose.py` gives, for each table, what it belongs to:
   - its owner column (e.g. `Activity: riderId`), or its parent (e.g. `ActivityPhoto: Activity.activityId`, `Part: Bike.bikeId`, `ServiceLog: Part…`);
   - every column that refers to another table's id, which E's merge uses to renumber rows;
   - whether it's shared or instance-only.

   `owner_of(table, id)` and `require(table, id, write=True)` use it. They raise 404 for a row the caller may not see and 403 for one it may see but not change, replacing and extending `friend_rides.refuse`. In A, `require` only refuses friends' rows, as today. A test fails when a table in the schema is missing from the map. The access checks (C), the exports (D) and the merge (E) all read this one map, so they can't disagree.
7. **Garmin accounts** (decision 4).
   - **A `GarminAccount` table** (`riderId` primary key): email, password through `services/vault.py`, and every `garmin*` state column now in `Settings` (sync mode and hours, last OK and last error, fail count, sign-in needed, device sync, sweep, changes-before, activity sync date, the history and weigh-in backfill cursors and status). A step moves the owner's values in. The old columns stay for one release, then go.
   - **One token folder per account**: `TOKEN_DIR/<riderId>/garmin_tokens.json`. Start-up moves the existing file into the owner's folder. `TOKEN_DIR` stays the one Docker volume.
   - **`services/garmin.py` takes the account as an argument.** That covers `_client`, `sync_garmin`, `sync_garmin_activities`, the history and weigh-in pulls, `garmin_changes` and `garmin_failures`. The sync writes `GarminDaily`, `WeightLog` and activities for that account's rider.
   - **`_garmin_heartbeat` and `_garmin_history` go over every account.** One account at a time, never in parallel, spaced a few minutes apart, so several logins from one address don't look like abuse to Garmin. One account failing or needing sign-in never holds up the others.
   - **Every place that shows the Garmin state reads the account for the rider shown**: the Settings, Garmin, Tasks and dashboard pages. In A that's always the owner's, so nothing changes on screen.

### B. Accounts (no visible change)

1. **The `User` table:** `id`, `username` (unique, case-insensitive), `passwordHash`, `role`, `riderId` (unique), `disabledAt`, `authVersion` (an integer, raised on a password, role or disable change), `createdAt` and `lastLoginAt`. A step moves `.admin_login` into user 1, an admin tied to the owner rider. `password_hash` goes over as it is: werkzeug's `scrypt:…` string, which the comment in `credentials.py` already plans for.
2. **Recovery stays.** If `APP_USERNAME`/`APP_PASSWORD` in the environment change, they still win. They reset (or create) that admin user, as `admin_login`'s `env_sig` rule does today. The generated first-login password and the setup wizard make user 1.
3. **Sessions carry `uid` and `av` (the user's `authVersion`).** `check_login` loads the user into `g.user` and clears the session for a disabled user or a stale `av`. A session from before the upgrade (`logged_in` and a matching old `av`) becomes user 1's, so nobody is signed out by the upgrade.
4. **Bearer tokens get an owner.** `DeviceToken.userId`, set to user 1 on upgrade, and a Watch's token takes its parent phone's. `device_auth.verify` sets `g.user`, so `/api/v1/ping` and everything else answer for that user's rider. No change to the iPhone app.
5. **Settings → Password** becomes "your password" and raises that user's `authVersion`. This replaces `credentials.auth_version`.

### C. Roles and scoping (the main release)

1. **Switch it on.** `whose.rider_id()` returns `g.user.riderId`. `viewable` lets an admin see any local rider. For a standard user it allows their own rider only and gives 404 for any other `?rider=`.
   - The display checks that still read `Rider.isDefault` to mean "the rider shown is the request's own" compare with `whose.rider_id()` instead: `dashboard._rider_args`, `goals._back`, the Data page's alcohol recovery ("Garmin data is the owner's", per account after A7) and the `owner_rider_id` the templates get from `app.py`.
   - `activities.delete_blips` takes the form's rider without a check today; it goes through `whose.require` with the rest of C3.
2. **Enforce `@access`.**
   - Admin-only: Tasks, logs and diagnostics; backup and restore; Settings' instance sections; Home Assistant; MQTT; Riders management; Users; Friends (until G).
   - `own`: everything per rider, including the user's own Garmin connection and sync.
3. **Apply `whose.require` to every by-id route**: ride delete, bulk edits, photos, gear and parts, kit, nutrition entries, custom foods, recipes, saved meals, goals, challenges, planned routes, imports and re-import proposals. Work file by file in the order of the route counts above. The access test from A lists what's left.
4. **The Settings page splits.**
   - "Your settings" (everyone): preferences, password, Garmin (connect, sign-in with MFA, history choice, sync now, disconnect) and the import folder (F).
   - "This Headwind" (admins only): everything else.
   - On an admin's own pages, Garmin is their own account, like anyone else's. Through the rider picker, an admin also sees each user's Garmin state, read-only, and can disconnect an account.
5. **The Users page** (admin only):
   - Invite: a new rider, or one tied to an existing rider (decision 6).
   - Reset password: a one-time reset link, never an admin-typed password.
   - Change a role, disable, or delete. Deleting offers that user's export first, once D exists. Until then, deleting is disable only. Disabling also stops that user's Garmin sync and import folder.
   - At least one enabled admin at all times. This is enforced in the service, not just the page.
6. **The phone pairing page** lists the signed-in user's own phones. An admin also sees everyone's and can revoke any.
7. **Cross-user leaks outside routes.**
   - Context processors in `app.py`: the favourites, the Tasks badge (admin only) and the reimport badge (per rider).
   - The badge cache keyed on `data_version`: check it's keyed by rider.
   - **MQTT per user** (decision 7). A per-user switch in `RiderSettings`, on for the owner on upgrade. `mqtt.sensor_rider()` becomes the list of riders with it on: the heartbeat and the Settings button publish each one's set, and a push after a change goes to the rider whose data changed. Each user's entities are their own Home Assistant device. Proposed: the owner's keep today's ids and topics, so existing dashboards and automations keep working, and other users' get their own prefix, including their own water-button topic (`mqtt_commands`).
   - The Home Assistant import (weights and body figures read from HA) stays admin-only and goes into the owner's data (`homeassistant.import_rider()`).
   - Gear (decision 8): a standard user's `?rider=` or form rider on the gear pages is their own; `viewable`'s `local` is admin-only.
8. **README and CHANGELOG.** Rewrite "One person per instance" (e.g. "one household or club per instance, each person private by default") and the Beta status line, and document roles, invites, per-user Garmin and recovery.

**Tests for C** (the release isn't done without them):
- **The sweep.** Users A and B (standard) and an admin, with one of every owned object seeded for A. For every endpoint in `app.url_map` with an id in its path or form, B calls it with A's ids, GET and POST, and gets 403 or 404, and A's rows are unchanged afterwards. The test is generated from the URL map, so a new route is covered without anyone remembering to add it.
- B with a Bearer token gets the same results on `/api/v1/` and `/nutrition/api/`.
- A standard user gets 403 on every admin endpoint.
- The last admin can't be demoted, disabled or deleted.
- A password change or disable signs that user out everywhere, including other processes (it's in the database, not memory).
- **Garmin.** Two accounts each sync into their own rider (`GarminDaily`, `WeightLog`, activities). One account failing sign-in doesn't stop the other's sync. B can't connect, sync or disconnect A's account.
- The upgrade from 0.7.x keeps the signed-in session, the paired phones, the Garmin connection and every preference.

### D. Exports and backups by role

TODO.md already specifies this in detail: a user's own export, an admin's export of one user, the full backup and restore for admins only, background jobs, and tests. Build it as written, with one addition. A single user's export is the **same zip format as the full backup**, holding that one rider's rows (taken from A6's map) and their files, with a manifest saying so. That settles TODO's open question ("Decide what a single user's export is for"): the zip is the input for E's merge, and the GPX/CSV "Leaving Headwind" files can ride along in it.

### E. Bring another Headwind in as a rider (merge)

**What it's for:** people who run one Headwind each today (a couple, a club) can move onto one instance with logins. Admin-only, on the Users page: **Bring in another Headwind**.

1. **Input:** a full backup zip from any Headwind version, or a single-user export from D. It's staged and migrated to the current schema with the restore's own code (`backup.stage_upload`, `validate`, `prepare`), so an old instance can be brought in as it is. Nothing touches the live database yet.
2. **Choose who comes over.** The backup's local riders are listed, with its friends' riders shown but not offered. For each one, the admin picks:
   - **New rider**, with an optional invite (B/C), so the person gets a login for it; or
   - **An existing rider here**, for someone already on both instances. Their activities then go through the duplicate checks (`services/duplicates.py`), so copies are set aside for review rather than added twice; or
   - **Leave out.**

   **If this instance follows the incoming person as a friend** (a friend's rider made by friend sync), the merge offers to replace that friend's rider with the real one. The friend's synced copies and the `Friend` row go; their own data, with everything that was only on their instance, comes in.
3. **Preview first** (a dry run): for each rider, how many activities, photos, bikes, kit, weigh-ins, food entries, goals and so on will come in. It also shows how many activities will be set aside as duplicates, which segments will be matched to existing ones, and what is left behind (below). Nothing is written until the admin confirms.
4. **What comes over:**
   - Every row that rider owns, by A6's map, including the rows that hang off them.
   - Their `RiderSettings`.
   - Their files (avatar, activity photos, bike and kit pictures, food photos).
5. **What doesn't come over**, and the preview says so:
   - Instance settings: AI keys, MQTT, Home Assistant, map keys, the outside address.
   - Users and passwords. The person sets a new password from their invite.
   - Paired phones: the phone re-pairs with the new instance.
   - Feed codes the old instance gave out. Friends who followed the old instance need a new code.
   - Garmin's stored password and tokens. They're encrypted with the old instance's key, so the user signs in to Garmin again here. The sync history cursors do come over with `GarminAccount`, so the history isn't fetched again.
   - The old instance's friends. With G they come over as that user's `Friend` rows (address and code), and the next sync brings their activities back. Before G, they're listed so the user can add them again.
6. **New ids.** Every integer id the instance makes (bikes, kit, parts, goals, custom foods, segments and the rest) is given a new number. A6's map says which columns point at which table, so each reference is rewritten to the new numbers, in an order where parents go before children.
   - **Activity ids** are TEXT and come from Strava or Garmin. Two different people can't share one, so they're kept. If an id is already here for another rider (rare: a bad import), the incoming one gets a new id.
   - **File names** that hold an id (`bike_<id>_<hex>.jpg`) are renamed for the new number, and the column naming each file is rewritten.
   - **A segment** that matches one already here (same start, end and route, the test `services/segments.py` uses for families) keeps the one that's here, and the incoming efforts point at it.
7. **Safe to run.**
   - A background job (`services/jobs.py`) with progress, like the import.
   - The live database is snapshotted first, as a restore does (`.pre-restore`).
   - It writes in one transaction, so a failure leaves nothing half-merged. While it runs, the app shows a notice and other writes wait.
   - Afterwards, start-up's normal repairs run for the new rows (best efforts, segment matching where needed).
8. **Bringing the same backup in again** adds only what's new. A `MergeSource` table records each merge: a fingerprint of the backup's database, the source rider and the target rider, with each table's old id → new id. A later, newer backup of the same instance into the same rider then adds new rows instead of copies. This is how someone can keep using their old instance for a while and bring it in again before switching it off.
9. **Tests:**
   - Two throwaway instances, each with a rider who has activities, photos, a bike with parts and service logs, kit, weigh-ins, food entries, a custom food, a goal, a planned route, segment efforts and Garmin daily data, and with the same ids used on both sides. After the merge, every reference points at the right row (`PRAGMA foreign_key_check` plus a check of every reference in A6's map), and each rider's totals are what they were on their own instance.
   - Merging into an existing rider sets the same activities aside as duplicates, rather than adding them again.
   - Replacing a friend's rider removes the friend's copies and leaves no `Friend` row behind.
   - No secrets, users, phone tokens or feed codes come over.
   - Bringing the same backup in twice adds nothing the second time. A newer backup adds only its new activities.
   - A merge that fails partway leaves the database as it was before.
   - A standard user gets 403.

### F. Import folders per user

This replaces TODO's **Auto-import folder** with a version for each user. It can be built any time after A (with the owner as the only user), and becomes per user once C is in.

1. **Where the folders are.** The admin sets one root, with `HEADWIND_IMPORT_DIR` or in Settings → This Headwind, e.g. a Syncthing or Dropbox folder, or a NAS share mounted into the container. Each user gets their own subfolder under it, `<root>/<username>/`, made when the user is created. A user can't type a path.
   - **Why no typed paths:** a path a standard user could type would let them read any file the server can, `bike.db` and `.secret_key` included.
   - The admin can point a user at a different subfolder, but only one under the root. Every path is checked with `realpath` against the root, so symlinks and `..` can't leave it.
2. **What it reads:** the same files as `routes/import_rides.py` (`.fit`, `.gpx`, `.tcx`, `.gz`, zip). A Strava export zip dropped in is read as one, with that user's choices. Each file goes through `_process_single_file` for the folder's rider, so `services/duplicates.py` and `ingest.after_ride_added` still run.
3. **One background loop** polls every enabled user's folder, like `_mqtt_heartbeat` (inotify doesn't fire on network mounts).
   - The interval is set by the admin, every 5 minutes by default.
   - A file is read only once it has stopped growing, so half-synced files are left alone.
   - Each file is recorded by path, size and mtime (`ImportFolderFile`: `riderId`, `path`, `size`, `mtime`, `result`, `activityId`), so nothing is imported twice.
   - Afterwards the file moves to `imported/` or `failed/` inside the user's folder, or stays put if the user chooses "leave files where they are", for a folder a sync app also writes to.
4. **On the user's Import page:** the folder's path as the server sees it (to point their sync app at), on or off, the last scan, what was imported and any failures. Admins see every user's.
5. **Limits:** the same file-size and zip-entry limits as uploads (`services/limits.py`). A cap on files per scan stops a dump of 10,000 files from holding the write lock for long; the rest wait for the next scans.
6. **A disabled user's folder isn't scanned.** A merge (E) doesn't bring folder settings over.
7. **Tests:**
   - A file dropped in A's folder becomes A's activity, never B's.
   - A file still growing is left until it stops.
   - The same file is never imported twice, even after a restart.
   - A symlink or `..` out of the root is refused.
   - A standard user can't change their folder's path.
   - A failed file goes to `failed/` with its reason shown.
   - A disabled user's folder is skipped.

### G. Friends and AI per user

- **Friends per user.** `Friend.ownerRiderId` and `FeedToken.userId`. A standard user's code can share only their own rider, and the Friends page shows their own friends. This closes the TODO's "who may tick a rider" item. E's merge then carries a user's friends over.
- **AI.** Keys stay instance-wide. Admins get a per-user on/off switch, since the admin pays for the calls. Personality and coaching goals are already per rider from A.
- **Optional:** the "visible to others on this instance" switch from decision 2.

## Risks and how the plan handles them

- **A route that is missed in C leaks data.** The `@access` declaration test (A3) and the URL-map sweep (C tests) both fail on a route nobody looked at.
- **Background threads have no user.** `whose.rider_id()` raises outside a request (A2), so they must be given a rider. The Garmin loops and the folder loop go over accounts and folders explicitly.
- **`Settings` holds personal and instance data side by side.** It's split before any second user can exist (A4, A7), so nobody inherits the owner's goals, time zone or Garmin account.
- **Several Garmin logins from one address look like abuse to Garmin.** Accounts are synced one at a time and spaced out (A7). Each account's failure state is its own.
- **A merge renumbers rows and could leave references pointing at the wrong row.** Every reference comes from A6's map, which a test keeps complete. The merge test checks every reference afterwards, and a failure rolls the whole merge back.
- **An import folder could be used to read server files.** There are no user-typed paths, only subfolders of an admin-set root, and every path is checked with `realpath` (F1).
- **Upgrading signs people out, unpairs phones or loses Garmin.** B3, B4 and A7 carry the old session, the tokens and the Garmin connection over to user 1, and the migration test covers it.
- **Photos are served from `/static/`** (`rideimg/act_<12 hex>.jpg`, `bikeimg/`, `avatars/`) without a login check. The random names protect them only while nobody is shown another user's file names. After C a standard user never sees another rider's photo URLs, so this holds. Serving them through a checked route is a possible later hardening, not a blocker.
