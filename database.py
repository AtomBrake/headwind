import logging
import os
import sqlite3
from flask import current_app, g


def _merge_workouts(db):
    """Once, on an install from before 0.7.0: copy every Workout row into Activity (its sport into type and sportType) and drop the old table.
    An id in both tables is one recording (ids come from the source, or from a hash of it), so the Activity row stays. The copy and the drop are one
    transaction, so a crash halfway leaves the old table as it was. Before anything changes, the whole database is copied to <database>.pre-0.7.0
    (0.6 can't open a merged database, so going back means restoring that file). Commits.
    Returns {'moved', 'same_id', 'copy'} or None when there is nothing to merge."""
    if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='Workout'").fetchone():
        return None
    copy = None
    path = db.execute('PRAGMA database_list').fetchone()[2]
    if path:                                            # '' for an in-memory database
        copy = path + '.pre-0.7.0'
        if not os.path.exists(copy):                    # a second attempt after a crash keeps the first, untouched, copy
            db.commit()
            out = sqlite3.connect(copy)
            try:
                db.backup(out)
            finally:
                out.close()
    wcols = [r[1] for r in db.execute('PRAGMA table_info(Workout)').fetchall()]
    acols = {r[1] for r in db.execute('PRAGMA table_info(Activity)').fetchall()}
    same = [c for c in wcols if c in acols]
    cols = same + ['type', 'sportType', 'rawData', 'updatedAt']
    sel = [f'w.{c}' for c in same] + ['w.sport', 'w.sport', "'{}'", "COALESCE(w.createdAt, datetime('now'))" if 'createdAt' in wcols else "datetime('now')"]
    same_id = db.execute('SELECT COUNT(*) FROM Workout w JOIN Activity a ON a.id = w.id').fetchone()[0]
    moved = db.execute(f"INSERT OR IGNORE INTO Activity ({', '.join(cols)}) SELECT {', '.join(sel)} FROM Workout w").rowcount
    db.execute('DROP VIEW IF EXISTS SegActivity')       # 0.6's reads the Workout table; migrate_db makes it again from Activity
    db.execute('DROP TABLE Workout')
    db.commit()
    return {'moved': moved, 'same_id': same_id, 'copy': copy}


def _drop_merge_leftovers(db):
    """What 0.7.0 kept while the code moved over to one table: the Workout view and the old table, renamed WorkoutPreMerge (the whole database as it
    was is still in <database>.pre-0.7.0). Returns the backup tables dropped. Does not commit."""
    left = db.execute("SELECT type, name FROM sqlite_master WHERE (type='view' AND name='Workout') OR (type='table' AND name LIKE 'WorkoutPreMerge%')").fetchall()
    for kind, name in left:                             # looked up first, so a start-up with nothing to drop writes nothing
        db.execute(f'DROP {kind.upper()} "{name}"')
    return [name for kind, name in left if kind == 'table']


# Columns that can hold most of a megabyte, kept at the end of their table. SQLite stores a large row as a chain of overflow pages and reads its
# columns in order, so reading any column that comes after a large one means reading the whole chain: `source` or `bikeId` for every activity read
# every activity's GPS streams. A column added later with ALTER TABLE lands after these, and the next start moves it in front (heavy_last).
HEAVY_COLUMNS = {
    'Activity':    ['summaryPolyline', 'description', 'notes', 'aiKudos', 'rawData', 'streams'],
    'GarminDaily': ['hrStream', 'bodyBatteryStream'],
}
_HEAVY_BATCH = 50       # rows moved per commit: a big activity's streams are ~1 MB


def _coldef(col, fks, one_pk):
    _, name, typ, notnull, dflt, pk = col
    s = f'"{name}" {typ}'.rstrip()
    if pk and one_pk:
        s += ' PRIMARY KEY'
    if notnull:
        s += ' NOT NULL'
    if dflt is not None:
        s += f' DEFAULT ({dflt})'
    if name in fks:
        s += f' REFERENCES {fks[name][0]}({fks[name][1]})'
    return s


def heavy_last(db, table, heavy):
    """Rebuild `table` with the `heavy` columns (in that order) after every other one, when they aren't already. Rows move to <table>_new
    _HEAVY_BATCH at a time, each batch one commit (the copy and the delete together), so a start-up stopped halfway carries on from there next
    time and the file never holds two copies: the pages a batch frees take the next one. The swap at the end (drop the empty old table, rename,
    indexes, triggers, the views over it) is one transaction. Returns the rows moved, or None when nothing needed doing. Commits."""
    new = f'{table}_new'
    cols = db.execute(f'PRAGMA table_info({table})').fetchall()
    if not cols:
        return None
    names = [c[1] for c in cols]
    heavy = [h for h in heavy if h in names]
    resuming = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", [new]).fetchone()
    if not resuming and names[len(names) - len(heavy):] == heavy:
        return None
    if not resuming:
        fks = {r[3]: (r[2], r[4]) for r in db.execute(f'PRAGMA foreign_key_list({table})')}
        order = [c for c in cols if c[1] not in heavy] + [c for h in heavy for c in cols if c[1] == h]
        pk = [c[1] for c in sorted((c for c in cols if c[5]), key=lambda c: c[5])]
        defs = [_coldef(c, fks, len(pk) == 1) for c in order] + ([f"PRIMARY KEY ({', '.join(pk)})"] if len(pk) > 1 else [])
        db.execute(f"CREATE TABLE {new} ({', '.join(defs)})")
        db.commit()
    keep = [c[1] for c in db.execute(f'PRAGMA table_info({new})').fetchall()]
    keep = ', '.join(f'"{c}"' for c in keep if c in names)
    # Triggers on the old table would fire on every row moved (services/tracks.py drops a track summary on delete); its ensure_schema makes them
    # again on the new table. Kept with the indexes and views, put back at the swap.
    triggers = db.execute("SELECT name, sql FROM sqlite_master WHERE type='trigger' AND tbl_name=?", [table]).fetchall()
    for name, _ in triggers:
        db.execute(f'DROP TRIGGER "{name}"')
    db.commit()
    log = logging.getLogger(__name__)
    moved, total = 0, db.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]
    while True:
        ids = [r[0] for r in db.execute(f'SELECT rowid FROM {table} ORDER BY rowid LIMIT ?', [_HEAVY_BATCH])]
        if not ids:
            break
        marks = ','.join('?' * len(ids))
        db.execute(f'INSERT INTO {new} (rowid, {keep}) SELECT rowid, {keep} FROM {table} WHERE rowid IN ({marks})', ids)
        db.execute(f'DELETE FROM {table} WHERE rowid IN ({marks})', ids)
        db.commit()
        moved += len(ids)
        if moved % (_HEAVY_BATCH * 20) < _HEAVY_BATCH:
            log.warning('%s: large columns moved to the end of the row, %d of %d rows', table, moved, total)
    others = db.execute("SELECT type, name, sql FROM sqlite_master WHERE type IN ('index', 'trigger') AND tbl_name=? AND sql IS NOT NULL",
                        [table]).fetchall()
    views = db.execute("SELECT name, sql FROM sqlite_master WHERE type='view'").fetchall()   # any of them can read the table
    db.execute('BEGIN IMMEDIATE')
    for name, _ in views:
        db.execute(f'DROP VIEW "{name}"')
    db.execute(f'DROP TABLE {table}')
    db.execute(f'ALTER TABLE {new} RENAME TO {table}')
    for _, _, sql in others:
        db.execute(sql)
    for _, sql in triggers:
        db.execute(sql)
    for _, sql in views:
        db.execute(sql)
    db.commit()
    db.execute('PRAGMA wal_checkpoint(TRUNCATE)')
    return moved


def migrate_db():
    db = get_db()

    # ── Create all tables first ──────────────────────────────────────
    db.execute('''
        CREATE TABLE IF NOT EXISTS Rider (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            name       TEXT NOT NULL,
            avatarPath TEXT,
            isDefault  INTEGER DEFAULT 0,
            haDevice   TEXT
        )
    ''')

    db.execute('''
        CREATE TABLE IF NOT EXISTS Activity (
            id                  TEXT PRIMARY KEY,
            name                TEXT,
            type                TEXT,
            sportType           TEXT,
            startDate           TEXT,
            startDateLocal      TEXT,
            timezone            TEXT,
            distance            REAL,
            movingTime          INTEGER,
            elapsedTime         INTEGER,
            totalElevationGain  REAL,
            averageSpeed        REAL,
            maxSpeed            REAL,
            averageHeartrate    REAL,
            maxHeartrate        REAL,
            averageWatts        REAL,
            maxWatts            REAL,
            weightedAvgWatts    REAL,
            kilojoules          REAL,
            averageCadence      REAL,
            calories            REAL,
            sufferScore         REAL,
            startLat            REAL,
            startLng            REAL,
            city                TEXT,
            country             TEXT,
            summaryPolyline     TEXT,
            kudosCount          INTEGER,
            streams             TEXT,
            rawData             TEXT,
            description         TEXT,
            notes               TEXT,
            riderId             INTEGER REFERENCES Rider(id),
            weatherTempC        REAL,
            weatherWindKph      REAL,
            weatherGustKph      REAL,
            weatherWindDir      INTEGER,
            weatherHumidity     INTEGER,
            weatherRainMm       REAL,
            weatherCode         INTEGER,
            weatherSummary      TEXT,
            weatherWindRel      TEXT,
            aiKudos             TEXT,
            createdAt           TEXT DEFAULT (datetime('now')),
            updatedAt           TEXT DEFAULT (datetime('now'))
        )
    ''')

    db.execute('''
        CREATE TABLE IF NOT EXISTS Settings (
            id               INTEGER PRIMARY KEY,
            aiProvider       TEXT,
            openaiKey        TEXT,
            openaiModel      TEXT,
            ollamaUrl        TEXT,
            ollamaModel      TEXT,
            ntfyUrl          TEXT,
            webhookSubId     TEXT,
            mqttHost         TEXT,
            mqttPort         INTEGER DEFAULT 1883,
            mqttUser         TEXT,
            mqttPassword     TEXT,
            coachingGoals    TEXT,
            coachPersonality TEXT DEFAULT 'default',
            garminEmail      TEXT,
            garminPassword   TEXT,
            garminSyncHours  REAL DEFAULT 0.5
        )
    ''')

    db.execute('''
        CREATE TABLE IF NOT EXISTS GarminDaily (
            date         TEXT PRIMARY KEY,
            restingHR    INTEGER,
            hrv          INTEGER,
            hrvBalanced  INTEGER DEFAULT 0,
            sleepHours   REAL,
            sleepScore   INTEGER,
            bodyBattery  INTEGER,
            steps        INTEGER,
            stressScore  INTEGER
        )
    ''')

    db.execute('''
        CREATE TABLE IF NOT EXISTS Segment (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            name             TEXT NOT NULL,
            startLat         REAL NOT NULL,
            startLng         REAL NOT NULL,
            endLat           REAL NOT NULL,
            endLng           REAL NOT NULL,
            distanceM        REAL,
            elevationGainM   REAL,
            sourceActivityId TEXT,
            polyline         TEXT,
            createdAt        TEXT DEFAULT (datetime('now'))
        )
    ''')

    db.execute('''
        CREATE TABLE IF NOT EXISTS SegmentEffort (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            segmentId    INTEGER NOT NULL REFERENCES Segment(id) ON DELETE CASCADE,
            activityId   TEXT NOT NULL,
            activityDate TEXT,
            elapsedSecs  INTEGER NOT NULL,
            avgSpeedMps  REAL,
            isPR         INTEGER DEFAULT 0,
            createdAt    TEXT DEFAULT (datetime('now')),
            UNIQUE(segmentId, activityId)
        )
    ''')

    db.execute('''
        CREATE TABLE IF NOT EXISTS RideMemory (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            rideId      TEXT UNIQUE NOT NULL,
            rideDate    TEXT,
            rideName    TEXT,
            distanceMi  REAL,
            movingTime  INTEGER,
            elevationFt REAL,
            avgSpeedMph REAL,
            avgPower    REAL,
            normPower   REAL,
            avgHR       REAL,
            calories    REAL,
            userNotes   TEXT,
            aiSummary   TEXT,
            tags        TEXT,
            createdAt   TEXT DEFAULT (datetime('now')),
            updatedAt   TEXT DEFAULT (datetime('now'))
        )
    ''')

    db.execute('''
        CREATE TABLE IF NOT EXISTS Athlete (
            id           INTEGER PRIMARY KEY,
            firstname    TEXT,
            lastname     TEXT,
            profile      TEXT,
            accessToken  TEXT,
            refreshToken TEXT,
            expiresAt    INTEGER
        )
    ''')

    db.execute('''
        CREATE TABLE IF NOT EXISTS BestEffort (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            activityId   TEXT NOT NULL,
            activityDate TEXT NOT NULL,
            distanceMi   REAL NOT NULL,
            elapsedSecs  INTEGER NOT NULL,
            avgSpeedMps  REAL,
            UNIQUE(activityId, distanceMi)
        )
    ''')

    db.execute('''
        CREATE TABLE IF NOT EXISTS FoodLog (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            riderId    INTEGER REFERENCES Rider(id),
            logDate    TEXT NOT NULL,
            barcode    TEXT,
            foodName   TEXT NOT NULL,
            calories   REAL,
            protein    REAL,
            carbs      REAL,
            fat        REAL,
            servingG   REAL,
            quantity   REAL DEFAULT 1,
            createdAt  TEXT DEFAULT (datetime('now'))
        )
    ''')

    db.execute('''
        CREATE TABLE IF NOT EXISTS HydrationLog (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            riderId   INTEGER REFERENCES Rider(id),
            logDate   TEXT NOT NULL,
            ml        INTEGER NOT NULL,
            createdAt TEXT DEFAULT (datetime('now'))
        )
    ''')

    db.commit()

    # ── Backfill columns added after initial release ─────────────────
    # (Safe to run on old DBs that predate the CREATE TABLE above)

    rider_cols = {r[1] for r in db.execute('PRAGMA table_info(Rider)').fetchall()}
    if 'haDevice' not in rider_cols:
        db.execute('ALTER TABLE Rider ADD COLUMN haDevice TEXT')

    act_cols = {r[1] for r in db.execute('PRAGMA table_info(Activity)').fetchall()}
    for col, defn in [
        ('riderId',         'INTEGER REFERENCES Rider(id)'),
        ('description',     'TEXT'),
        ('notes',           'TEXT'),
        ('weatherTempC',    'REAL'),
        ('weatherWindKph',  'REAL'),
        ('weatherGustKph',  'REAL'),
        ('weatherWindDir',  'INTEGER'),
        ('weatherHumidity', 'INTEGER'),
        ('weatherRainMm',   'REAL'),
        ('weatherCode',     'INTEGER'),
        ('weatherSummary',  'TEXT'),
        ('weatherWindRel',  'TEXT'),
        ('weatherSource',   'TEXT'),
        ('flagReason',      'TEXT'),
        ('flagDismissed',   'INTEGER'),
        ('aiKudos',         'TEXT'),
        ('aiKudosAt',       'TEXT'),
        ('caloriesRaw',     'REAL'),
        ('originId',        'TEXT'),     # a ride that was a workout: the id it first came in with (services/origin.py)
        ('steps',           'INTEGER'),  # walks, runs, hikes: from the phone or watch
        ('source',          'TEXT'),     # how a walk, run, ... arrived: 'android', 'garmin', 'manual', 'converted', ... (was Workout.source)
        ('commute',         'INTEGER'),  # 1 a commute, 0 the rider said it isn't, NULL never said (a Strava import may then tick it)
        ('srcUpdatedAt',    'TEXT'),     # a friend's ride: their updatedAt for it once matched here, '' until then, NULL from before 0.7.6 (routes/friends.py)
    ]:
        if col not in act_cols:
            db.execute(f'ALTER TABLE Activity ADD COLUMN {col} {defn}')

    if 'riderId' in act_cols and 'riderId' not in act_cols:
        default = db.execute('SELECT id FROM Rider WHERE isDefault=1 LIMIT 1').fetchone()
        if default:
            db.execute('UPDATE Activity SET riderId=? WHERE riderId IS NULL', [default[0]])

    settings_cols = {r[1] for r in db.execute('PRAGMA table_info(Settings)').fetchall()}
    for col, defn in [
        ('ntfyUrl',          'TEXT'),
        ('webhookSubId',     'TEXT'),
        ('mqttHost',         'TEXT'),
        ('mqttPort',         'INTEGER DEFAULT 1883'),
        ('mqttUser',         'TEXT'),
        ('mqttPassword',     'TEXT'),
        ('coachingGoals',    'TEXT'),
        ('coachPersonality', "TEXT DEFAULT 'default'"),
        ('garminEmail',      'TEXT'),
        ('garminPassword',   'TEXT'),
        ('garminSyncHours',  'REAL DEFAULT 0.5'),
        ('feedToken',                'TEXT'),
        ('friendSyncInterval',       'INTEGER DEFAULT 15'),
        ('garminActivitySyncDate',   'TEXT'),
        ('garminSyncMode',           "TEXT DEFAULT 'health'"),
        ('heightCm',             'REAL'),
        ('sex',                  'TEXT'),
        ('birthYear',            'INTEGER'),
        ('activityFactor',       'REAL'),
        ('lossLbPerWeek',        'REAL'),
        ('stepGoal',             'INTEGER'),
        ('goalAuto',             'INTEGER DEFAULT 0'),
        ('goalAutoLast',         'TEXT'),
        ('rideKcalWeek',         'REAL'),
        ('rideGoalWeek',         'INTEGER'),
        ('goalWeightKg',         'REAL'),
        ('holidayStart',         'TEXT'),
        ('holidayEnd',           'TEXT'),
        ('garminLastOk',         'TEXT'),
        ('garminLastError',      'TEXT'),
        ('garminDeviceSync',     'TEXT'),
        ('garminSweepAt',        'TEXT'),      # when the Garmin sync last read all its recent days (services/garmin.health_days)
        ('garminFailCount',      'INTEGER DEFAULT 0'),
        ('garminHistoryFrom',    'TEXT'),      # how far back to pull health history: NULL = not asked yet, 'all', 'none' or a YYYY-MM-DD
        ('garminHistoryCursor',  'TEXT'),      # oldest day the history backfill has covered so far
        ('garminHistoryDone',    'INTEGER DEFAULT 0'),
        ('garminHistoryStatus',  'TEXT'),
        ('garminHistoryRetryAt', 'TEXT'),      # after a rate limit or outage, don't try again before this (UTC ISO)
        ('utcStartFixDone',      'INTEGER DEFAULT 0'),
        ('awayStartRecheckDone', 'INTEGER DEFAULT 0'),
        ('workoutDupCheckDone',  'INTEGER DEFAULT 0'),   # walks, runs, ... checked once for duplicates after the merge (services/duplicates.recheck_workouts)   # duplicates re-checked on the UTC instant for rides recorded abroad (services/start_times.py)
        ('dupNameFixDone',       'INTEGER DEFAULT 0'),   # merged activities given back the name chosen on the copy set aside (services/duplicates.recover_names)
        ('segmentFamiliesDone',  'INTEGER DEFAULT 0'),   # segments split into ride / on foot, efforts and PRs picked again (services/segments.regroup)
        ('segmentBikesMergedDone', 'INTEGER DEFAULT 0'), # 0.7.3's e-bike segments merged into the ride ones, PRs per pedal / e-bike (services/segments.merge_bikes)
        ('movingTimeFixDone',      'INTEGER DEFAULT 0'), # moving times a broken lap timer made a few seconds, taken from the track (services/moving_time.repair)
        ('segmentMatchFixDone',    'INTEGER DEFAULT 0'), # 0.7.7's matching fixes: loops cut again, tracks realigned, every segment matched again (services/segments.repair_matching)
        ('sportEffortsDone',       'INTEGER DEFAULT 0'), # best times worked out for every run and swim already saved (services/sport_records.ensure)
        ('movingTimePausedDone',   'INTEGER DEFAULT 0'), # moving times that counted the stops (auto-pause off) taken from the track (services/moving_time.repair_paused)
        ('bestEffortsCleanDone',   'INTEGER DEFAULT 0'), # best times worked out again without GPS jumps and speed-sensor faults (services/best_efforts.rescan_clean)
        ('sensorTopSpeedDone',     'INTEGER DEFAULT 0'), # top speeds from the GPS where the speed sensor went wrong (services/max_stats.fix_sensor_top_speed)
        ('garminWeightsDone',    'INTEGER DEFAULT 0'),   # weigh-in history fetched on its own (services/garmin.backfill_weigh_ins)
        ('garminWeightsRetryAt', 'TEXT'),
        ('garminWeightsStatus',  'TEXT'),   # imported rides' UTC start times moved to local time (services/start_times.py)
        ('haUrl',                'TEXT'),
        ('haToken',              'TEXT'),
        ('haEntityMap',          'TEXT'),
        ('haSyncMinutes',        'INTEGER'),
        ('haLastSync',           'TEXT'),
        ('haLastResult',         'TEXT'),
        ('haWeatherEntity',      'TEXT'),
        ('haWeatherCondition',   'TEXT'),
        ('haWeatherTempC',       'REAL'),
        ('haWeatherUpdatedAt',   'TEXT'),
        ('installId',            'TEXT'),
        ('telemetryOptOut',      'INTEGER DEFAULT 0'),
        ('telemetryPingedAt',    'TEXT'),
        ('nutritionCalGoal',     'INTEGER'),
        ('nutritionProteinGoal', 'INTEGER'),
        ('nutritionCarbGoal',    'INTEGER'),
        ('nutritionFatGoal',     'INTEGER'),
        ('nutritionSugarGoal',   'INTEGER'),
        ('nutritionAlcoholWeekGoal', 'REAL'),
        ('nutritionWaterGoalMl', 'INTEGER DEFAULT 2500'),
        ('nutritionBmrKcal',     'INTEGER'),
        ('units',                "TEXT DEFAULT 'imperial'"),
        ('distanceBackfillDone', 'INTEGER DEFAULT 0'),
        ('nutritionWeightUnit',     "TEXT DEFAULT 'stlb'"),
        ('nutritionWeightEmaAlpha', 'REAL DEFAULT 0.1'),
        ('dietStartDate',           'TEXT'),
        ('calorieAdjustPct',       'REAL DEFAULT 0'),
        ('claudeKey',              'TEXT'),
        ('claudeModel',            'TEXT'),
        ('timeZone',               'TEXT'),     # IANA name; blank = the server's zone (services/tz.py)
        ('birthDate',              'TEXT'),     # YYYY-MM-DD; replaces birthYear for the age (services/goal_model.profile)
        ('birthDateGuessed',       'INTEGER DEFAULT 0'),    # 1 = filled in as 1 January from birthYear; the profile forms ask for the real date
    ]:
        if col not in settings_cols:
            db.execute(f'ALTER TABLE Settings ADD COLUMN {col} {defn}')
    if 'timeZone' not in settings_cols:                 # an install from before the setting: keep the zone it has always used
        db.execute("UPDATE Settings SET timeZone='Europe/London' WHERE id=1")
    if 'birthDate' not in settings_cols:                # only the year was known: 1 January of it, until the real date is entered
        db.execute("UPDATE Settings SET birthDate=printf('%04d-01-01', birthYear), birthDateGuessed=1 WHERE birthYear BETWEEN 1900 AND 2100")

    db.execute('''
        CREATE TABLE IF NOT EXISTS Friend (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            name        TEXT NOT NULL,
            url         TEXT NOT NULL,
            token       TEXT,
            riderId     INTEGER REFERENCES Rider(id),
            lastSynced  TEXT,
            createdAt   TEXT DEFAULT (datetime('now'))
        )
    ''')

    garmin_cols = {r[1] for r in db.execute('PRAGMA table_info(GarminDaily)').fetchall()}
    for col, defn in [
        ('steps',              'INTEGER'),
        ('stressScore',        'INTEGER'),
        ('hrStream',           'TEXT'),
        ('bodyBatteryStream',  'TEXT'),
        ('totalCalories',  'INTEGER'),
        ('activeCalories', 'INTEGER'),
        ('totalCaloriesRaw',  'REAL'),
        ('activeCaloriesRaw', 'REAL'),
    ]:
        if col not in garmin_cols:
            db.execute(f'ALTER TABLE GarminDaily ADD COLUMN {col} {defn}')

    seg_cols = {r[1] for r in db.execute('PRAGMA table_info(Segment)').fetchall()}
    for col, defn in [
        ('polyline',       'TEXT'),
        ('elevationGainM', 'REAL'),
        ('friendId',       'INTEGER REFERENCES Friend(id)'),
        ('sourceSegId',    'INTEGER'),
        ('matchPending',   'INTEGER'),   # a friend's segment that is new or moved and not matched yet (routes/friends.py)
    ]:
        if col not in seg_cols:
            db.execute(f'ALTER TABLE Segment ADD COLUMN {col} {defn}')

    eff_cols = {r[1] for r in db.execute('PRAGMA table_info(SegmentEffort)').fetchall()}
    if 'approx' not in eff_cols:        # 1 = close-but-not-exact match (time estimated); see services/segments.match_segment_close
        db.execute('ALTER TABLE SegmentEffort ADD COLUMN approx INTEGER DEFAULT 0')

    friend_cols = {r[1] for r in db.execute('PRAGMA table_info(Friend)').fetchall()}
    if 'riderName' not in friend_cols:
        db.execute('ALTER TABLE Friend ADD COLUMN riderName TEXT')
    if 'lastFoodSync' not in friend_cols:
        db.execute('ALTER TABLE Friend ADD COLUMN lastFoodSync TEXT')

    db.execute('''
        CREATE TABLE IF NOT EXISTS PlannedRoute (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            name      TEXT NOT NULL,
            waypoints TEXT NOT NULL,
            createdAt TEXT DEFAULT (datetime('now'))
        )
    ''')

    db.execute('''
        CREATE TABLE IF NOT EXISTS FoodOverride (
            barcode     TEXT PRIMARY KEY,
            name        TEXT NOT NULL,
            brand       TEXT,
            kcal100g    REAL,
            protein100g REAL,
            carbs100g   REAL,
            fat100g     REAL,
            servingG    REAL,
            updatedAt   TEXT DEFAULT (datetime('now'))
        )
    ''')

    db.execute('''
        CREATE TABLE IF NOT EXISTS SavedMeal (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            name      TEXT NOT NULL,
            createdAt TEXT DEFAULT (datetime('now'))
        )
    ''')

    db.execute('''
        CREATE TABLE IF NOT EXISTS SavedMealItem (
            id       INTEGER PRIMARY KEY AUTOINCREMENT,
            mealId   INTEGER NOT NULL REFERENCES SavedMeal(id) ON DELETE CASCADE,
            foodName TEXT NOT NULL,
            calories REAL,
            protein  REAL,
            carbs    REAL,
            fat      REAL,
            servingG REAL,
            barcode  TEXT
        )
    ''')

    food_log_cols = {r[1] for r in db.execute('PRAGMA table_info(FoodLog)').fetchall()}
    for col, defn in [
        ('mealType',        "TEXT DEFAULT 'uncategorised'"),
        ('source',          "TEXT DEFAULT 'manual'"),
        ('brand',           'TEXT'),
        ('imageUrl',        'TEXT'),
        ('nutriScoreGrade', 'TEXT'),
        ('fibre',           'REAL'),
        ('sugar',           'REAL'),
        ('alcoholUnits',    'REAL'),
    ]:
        if col not in food_log_cols:
            db.execute(f'ALTER TABLE FoodLog ADD COLUMN {col} {defn}')

    food_override_cols = {r[1] for r in db.execute('PRAGMA table_info(FoodOverride)').fetchall()}
    for col, defn in [
        ('imageUrl',        'TEXT'),
        ('nutriScoreGrade', 'TEXT'),
        ('fibre100g',       'REAL'),
    ]:
        if col not in food_override_cols:
            db.execute(f'ALTER TABLE FoodOverride ADD COLUMN {col} {defn}')

    cf_cols = {r[1] for r in db.execute('PRAGMA table_info(CustomFood)').fetchall()}
    if cf_cols and 'fibre100g' not in cf_cols:      # (cf_cols empty = brand-new DB; the table is created below with the column)
        db.execute('ALTER TABLE CustomFood ADD COLUMN fibre100g REAL')
    fc_cols = {r[1] for r in db.execute('PRAGMA table_info(FoodCache)').fetchall()}
    if fc_cols and 'fibre100g' not in fc_cols:
        db.execute('ALTER TABLE FoodCache ADD COLUMN fibre100g REAL')

    saved_meal_item_cols = {r[1] for r in db.execute('PRAGMA table_info(SavedMealItem)').fetchall()}
    if saved_meal_item_cols and 'fibre' not in saved_meal_item_cols:
        db.execute('ALTER TABLE SavedMealItem ADD COLUMN fibre REAL')
    if saved_meal_item_cols and 'sugar' not in saved_meal_item_cols:
        db.execute('ALTER TABLE SavedMealItem ADD COLUMN sugar REAL')

    db.execute('''
        CREATE TABLE IF NOT EXISTS WeightLog (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            riderId   INTEGER REFERENCES Rider(id),
            logDate   TEXT NOT NULL,
            weightKg  REAL NOT NULL,
            source    TEXT DEFAULT 'manual',
            createdAt TEXT DEFAULT (datetime('now')),
            UNIQUE(riderId, logDate)
        )
    ''')

    db.execute('''
        CREATE TABLE IF NOT EXISTS FoodFavourite (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            riderId   INTEGER REFERENCES Rider(id),
            barcode   TEXT,
            foodName  TEXT NOT NULL,
            brand     TEXT,
            calories  REAL,
            protein   REAL,
            carbs     REAL,
            fat       REAL,
            servingG  REAL,
            imageUrl  TEXT,
            createdAt TEXT DEFAULT (datetime('now'))
        )
    ''')

    db.execute('''
        CREATE TABLE IF NOT EXISTS CustomFood (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            riderId   INTEGER REFERENCES Rider(id),
            name      TEXT NOT NULL,
            brand     TEXT,
            calories  REAL,
            protein   REAL,
            carbs     REAL,
            fat       REAL,
            servingG  REAL,
            imageUrl  TEXT,
            createdAt TEXT DEFAULT (datetime('now'))
        )
    ''')

    db.execute('''
        CREATE TABLE IF NOT EXISTS RecipeBook (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            riderId   INTEGER REFERENCES Rider(id),
            name      TEXT NOT NULL,
            nameKey   TEXT NOT NULL,
            calories  REAL NOT NULL,
            protein   REAL,
            carbs     REAL,
            fat       REAL,
            createdAt TEXT DEFAULT (datetime('now')),
            updatedAt TEXT DEFAULT (datetime('now'))
        )
    ''')
    db.execute('CREATE UNIQUE INDEX IF NOT EXISTS idx_recipebook_key ON RecipeBook(riderId, nameKey)')

    db.execute('''
        CREATE TABLE IF NOT EXISTS BodyMetric (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            riderId   INTEGER REFERENCES Rider(id),
            logDate   TEXT NOT NULL,
            metric    TEXT NOT NULL,
            value     REAL NOT NULL,
            unit      TEXT,
            source    TEXT DEFAULT 'homeassistant',
            updatedAt TEXT DEFAULT (datetime('now')),
            UNIQUE(riderId, logDate, metric)
        )
    ''')

    db.execute('''
        CREATE TABLE IF NOT EXISTS FoodImage (
            nameKey   TEXT PRIMARY KEY,
            name      TEXT NOT NULL,
            imageUrl  TEXT NOT NULL,
            updatedAt TEXT DEFAULT (datetime('now'))
        )
    ''')

    # Every activity, of every sport, is a row in Activity. Walks, runs, swims, ... used to have a table of their own (Workout); _merge_workouts
    # moves an old install's rows across once. Ride is a view of the rides in Activity (services/sports.RIDE_SQL): about 80 queries read rides only.
    if 'sport' not in {r[1] for r in db.execute('PRAGMA table_info(Segment)').fetchall()}:
        db.execute("ALTER TABLE Segment ADD COLUMN sport TEXT DEFAULT 'ride'")
    merged = _merge_workouts(db)
    dropped = _drop_merge_leftovers(db)
    if dropped:
        import logging
        logging.getLogger(__name__).warning('One table for every activity: dropped the Workout view and %s (kept by 0.7.0)', ', '.join(dropped))
    from services.sports import RIDE_SQL
    views = {
        'Ride': f'CREATE VIEW Ride AS SELECT * FROM Activity WHERE {RIDE_SQL}',
        # segment leaderboards: no streams (heavy), only what they need (bikeId: pedal or e-bike, services/sports.segment_class)
        'SegActivity': f'''CREATE VIEW SegActivity AS SELECT id, name, riderId, startDateLocal, sportType, bikeId,
            CASE WHEN {RIDE_SQL} THEN 'activity' ELSE 'workout' END AS kind FROM Activity''',
    }
    for name, sql in views.items():
        cur = db.execute("SELECT sql FROM sqlite_master WHERE type='view' AND name=?", [name]).fetchone()
        if not cur or ' '.join((cur[0] or '').split()) != ' '.join(sql.split()):      # only write when missing or changed, so start-up never takes a write lock needlessly
            db.execute(f'DROP VIEW IF EXISTS {name}')
            db.execute(sql)
    # A change to anything a friend's feed shares moves updatedAt on, so the feed's manifest tells friends which rides to fetch again
    # (routes/friends.py). Only a value that really changed: SQLite fires UPDATE OF for a column that was only rewritten. One that sets
    # updatedAt itself is left alone. Not calories: the calorie setting (services/calorie_adjust) rewrites every activity's, and that would
    # send every friend every ride again.
    shared = ('name', 'type', 'sportType', 'startDate', 'startDateLocal', 'distance', 'movingTime', 'elapsedTime', 'totalElevationGain',
              'averageSpeed', 'maxSpeed', 'averageHeartrate', 'maxHeartrate', 'averageWatts', 'weightedAvgWatts', 'averageCadence',
              'startLat', 'startLng', 'streams', 'weatherTempC', 'weatherWindKph', 'weatherGustKph', 'weatherWindDir', 'weatherHumidity',
              'weatherRainMm', 'weatherCode', 'weatherSummary', 'weatherWindRel', 'steps', 'riderId')
    touch = (f"CREATE TRIGGER Activity_touch AFTER UPDATE OF {', '.join(shared)} ON Activity "
             f"WHEN NEW.updatedAt IS OLD.updatedAt AND ({' OR '.join(f'NEW.{c} IS NOT OLD.{c}' for c in shared)}) "
             "BEGIN UPDATE Activity SET updatedAt = strftime('%Y-%m-%d %H:%M:%f', 'now') WHERE id = NEW.id; END")
    cur = db.execute("SELECT sql FROM sqlite_master WHERE type='trigger' AND name='Activity_touch'").fetchone()
    if not cur or ' '.join((cur[0] or '').split()) != ' '.join(touch.split()):
        db.execute('DROP TRIGGER IF EXISTS Activity_touch')
        db.execute(touch)
    db.execute('CREATE INDEX IF NOT EXISTS idx_activity_rider_date ON Activity(riderId, startDateLocal)')
    # SegmentEffort's own index starts with segmentId, so an activity's efforts (re-matching or deleting it, its page) scanned the whole table;
    # the food and water logs are read by rider and day and had no index at all.
    db.execute('CREATE INDEX IF NOT EXISTS idx_effort_activity ON SegmentEffort(activityId)')
    db.execute('CREATE INDEX IF NOT EXISTS idx_foodlog_rider_date ON FoodLog(riderId, logDate)')
    db.execute('CREATE INDEX IF NOT EXISTS idx_hydration_rider_date ON HydrationLog(riderId, logDate)')
    # Phone sensor recordings kept beside rides (see services/sensors.py): one row per recording, attached to the overlapping ride by time.
    db.execute('''
        CREATE TABLE IF NOT EXISTS RideSensor (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            riderId     INTEGER NOT NULL,
            clientId    TEXT NOT NULL UNIQUE,
            startUtc    TEXT NOT NULL,
            endUtc      TEXT NOT NULL,
            data        TEXT NOT NULL,
            summary     TEXT,
            device      TEXT,
            mount       TEXT,
            sensorsOnly INTEGER DEFAULT 0,
            rideKind    TEXT,
            rideId      TEXT,
            createdAt   TEXT DEFAULT (datetime('now'))
        )
    ''')
    db.execute('CREATE INDEX IF NOT EXISTS idx_ridesensor_ride ON RideSensor(rideId)')
    from services.sport_records import ensure_schema as _sport_records_schema      # run and swim best times (was RunEffort, runs only)
    _sport_records_schema(db)

    from services.duplicates import ensure_schema as _dup_schema
    _dup_schema(db)
    from services.gear import ensure_schema as _gear_schema
    _gear_schema(db)
    from services.strava_gear import ensure_schema as _strava_gear_schema
    _strava_gear_schema(db)
    from services.photos import ensure_schema as _photos_schema
    _photos_schema(db)
    db.commit()
    # Every Activity column is there now: put the large ones last (heavy_last), then the track summaries and their triggers (services/tracks.py).
    rebuilt = {t: heavy_last(db, t, cols) for t, cols in HEAVY_COLUMNS.items()}
    from services.tracks import ensure_schema as _tracks_schema
    _tracks_schema(db)
    from services.data_version import ensure_schema as _data_version_schema
    _data_version_schema(db)
    from services.feed_tokens import ensure_schema as _feed_tokens_schema
    _feed_tokens_schema(db)

    # One row per paired phone/app. Only a SHA-256 of the token is stored; the token itself is shown once at pairing time.
    db.execute('''
        CREATE TABLE IF NOT EXISTS DeviceToken (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            name       TEXT NOT NULL,
            tokenHash  TEXT NOT NULL UNIQUE,
            createdAt  TEXT DEFAULT (datetime('now')),
            lastUsedAt TEXT,
            revokedAt  TEXT
        )
    ''')

    # Phone-generated ids for queued offline writes, so a retried food/water log is applied once (see routes/nutrition.py log_food / add_water)
    db.execute('''
        CREATE TABLE IF NOT EXISTS ClientOp (
            clientId  TEXT PRIMARY KEY,
            kind      TEXT NOT NULL,
            entryId   INTEGER,
            createdAt TEXT DEFAULT (datetime('now'))
        )
    ''')

    # Foods friends' instances shared with us (their corrected products + barcode-less custom foods); see services/shared_foods.py
    db.execute('''
        CREATE TABLE IF NOT EXISTS SharedFood (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            friendId     INTEGER NOT NULL,
            origin       TEXT,
            kind         TEXT NOT NULL,
            key          TEXT NOT NULL,
            barcode      TEXT,
            name         TEXT NOT NULL,
            brand        TEXT,
            kcal100g     REAL, protein100g REAL, carbs100g REAL, fat100g REAL, fibre100g REAL,
            servingG     REAL,
            imageUrl     TEXT,
            nutriScoreGrade TEXT,
            srcUpdatedAt TEXT,
            syncedAt     TEXT,
            UNIQUE (friendId, kind, key)
        )
    ''')
    db.execute('CREATE INDEX IF NOT EXISTS idx_sharedfood_barcode ON SharedFood(barcode)')

    db.execute('''
        CREATE TABLE IF NOT EXISTS FoodCache (
            key             TEXT PRIMARY KEY,
            barcode         TEXT,
            name            TEXT NOT NULL,
            brand           TEXT,
            searchText      TEXT NOT NULL,
            kcal100g        REAL NOT NULL,
            protein100g     REAL,
            carbs100g       REAL,
            fat100g         REAL,
            sugars100g      REAL,
            fibre100g       REAL,
            servingG        REAL,
            imageUrl        TEXT,
            nutriScoreGrade TEXT,
            useCount        INTEGER DEFAULT 0,
            lastUsed        TEXT,
            fetchedAt       TEXT DEFAULT (datetime('now'))
        )
    ''')

    db.commit()

    # A brand-new DB gets these tables from the CREATE statements above, which predate some later columns, and the column checks
    # earlier in this function ran before the tables existed. Add anything still missing now that every table is there.
    for table, col, defn in (('CustomFood', 'fibre100g', 'REAL'), ('SavedMealItem', 'fibre', 'REAL'), ('FoodCache', 'fibre100g', 'REAL'), ('FoodCache', 'abv', 'REAL')):
        have = {r[1] for r in db.execute(f'PRAGMA table_info({table})').fetchall()}
        if have and col not in have:
            db.execute(f'ALTER TABLE {table} ADD COLUMN {col} {defn}')
    db.commit()

    # Start-up repairs below record what they did for the Tasks page (services/tasks.py)
    from services import tasks as _tasks, garmin_failures as _garmin_failures
    _tasks.ensure_schema(db)
    _garmin_failures.ensure_schema(db)
    _tasks.close_orphans(db)
    db.commit()
    if rebuilt.get('Activity'):
        _tasks.record(db, 'startup:heavy_last', 'Activities stored for faster pages',
                      f"{rebuilt['Activity']:,} activit{'y' if rebuilt['Activity'] == 1 else 'ies'} rewritten with their GPS data at the end of the row, "
                      "so lists and totals no longer read it")
        db.commit()

    # ── Backfill corrupted distance data (mm vs m) ──────────────────
    settings = db.execute("SELECT distanceBackfillDone FROM Settings WHERE id=1").fetchone()
    if not settings or not settings[0]:
        n_mm = db.execute("""
            UPDATE Activity SET distance = distance / 1000
            WHERE distance > 500000
              AND (lower(sportType) LIKE '%walk%'
                OR lower(sportType) LIKE '%hike%'
                OR lower(sportType) LIKE '%run%')
        """).rowcount
        db.execute("UPDATE Settings SET distanceBackfillDone=1 WHERE id=1")
        if settings and n_mm:
            _tasks.record(db, 'startup:mm_distances', 'Walk, run and hike distances stored in mm', f'{n_mm} divided by 1,000')
        db.commit()

    # ── Top speeds that are one GPS spike (old Garmin syncs): recomputed from the ride's streams, then re-checked ──
    from services.max_stats import fix_spiky_max_speed
    n_spiky = fix_spiky_max_speed(db)
    if n_spiky:
        _tasks.record(db, 'startup:spiky_top_speeds', 'Top speeds that were a GPS spike',
                      f"{n_spiky} ride{'s' if n_spiky != 1 else ''} recomputed from their own GPS and speed data, and re-checked")
        db.commit()
    from services.start_times import fix_utc_starts
    res = fix_utc_starts(db)
    if res.get('ran') and (res['moved'] or db.execute('SELECT 1 FROM Activity LIMIT 1').fetchone()):     # a new, empty install has nothing to report
        _tasks.record(db, 'startup:utc_starts', 'Start times of imported rides',
                      f"{res['moved']} ride{'s' if res['moved'] != 1 else ''} moved from UTC to UK time; "
                      f"{res['duplicates']} turned out to be a ride already here (the weaker copy was set aside)" if res['moved'] else 'Nothing needed moving')
        db.commit()
    if merged:
        _tasks.record(db, 'startup:merge_workouts', 'Walks, runs and other workouts moved in with the rides',
                      f"{merged['moved']} moved into one table of activities"
                      + (f"; {merged['same_id']} already there under the same id (that copy kept)" if merged['same_id'] else '')
                      + (f". The whole database as it was is in {merged['copy']}" if merged['copy'] else ''))
        db.commit()
    from services.duplicates import recheck_workouts
    res = recheck_workouts(db)
    if res.get('ran') and res['checked']:
        _tasks.record(db, 'startup:workout_duplicates', 'Duplicates of walks, runs and other workouts',
                      f"{res['checked']} checked; {res['duplicates']} turned out to be an activity already here (the weaker copy was set aside)")
        db.commit()
    from services.start_times import recheck_away_starts
    res = recheck_away_starts(db)
    if res.get('ran') and res['checked']:
        _tasks.record(db, 'startup:away_starts', 'Duplicates of activities recorded in another time zone',
                      f"{res['checked']} checked again on their real start time; "
                      f"{res['duplicates']} turned out to be a ride already here (the weaker copy was set aside)")
        db.commit()
    from services.duplicates import recover_names
    res = recover_names(db)
    if res.get('ran') and res['checked']:
        _tasks.record(db, 'startup:dup_names', 'Names of merged activities',
                      f"{res['checked']} copies set aside checked; {res['renamed']} activit{'y' if res['renamed'] == 1 else 'ies'} "
                      "took back the name chosen on the copy" if res['renamed'] else f"{res['checked']} copies set aside checked; no names needed changing")
        db.commit()
    from services.segments import regroup as _regroup_segments
    res = _regroup_segments(db)
    if res.get('ran') and db.execute('SELECT 1 FROM Segment LIMIT 1').fetchone():
        _tasks.record(db, 'startup:segment_families', 'Segments split into ride and on foot',
                      f"{res['removed']} effort{'s' if res['removed'] != 1 else ''} by walks, hikes and indoor rides left the ride segments; "
                      f"{res['foot']} new effort{'s' if res['foot'] != 1 else ''} on foot segments from {res['scanned']} walks, runs and hikes; "
                      f"{res['prs_moved']} segment PR{'s' if res['prs_moved'] != 1 else ''} changed")
        db.commit()
    from services.segments import merge_bikes as _merge_bikes
    res = _merge_bikes(db)
    if res.get('ran') and db.execute('SELECT 1 FROM Segment LIMIT 1').fetchone():
        _tasks.record(db, 'startup:segment_bikes', 'Bike and e-bike rides share segments',
                      f"{res['merged']} e-bike segment{'s' if res['merged'] != 1 else ''} became ride segment{'s' if res['merged'] != 1 else ''}; "
                      f"{res['found']} new effort{'s' if res['found'] != 1 else ''} from {res['scanned']} ride{'s' if res['scanned'] != 1 else ''}; "
                      f"{res['prs_moved']} segment PR{'s' if res['prs_moved'] != 1 else ''} changed (pedal and e-bike PRs are kept apart)")
        db.commit()
    from services import moving_time as _moving_time
    res = _moving_time.repair(db)
    if res.get('fixed'):
        n = len(res['fixed'])
        _tasks.record(db, 'startup:moving_time', 'Moving times put right',
                      f"{n} activit{'y' if n == 1 else 'ies'} whose device recorded a moving time of seconds for the whole ride (a Garmin that went flat "
                      "or restarted) now take it from the track, as Strava does: "
                      + '; '.join(f"{f[1] or f[0]} ({f[2]} s → {f[3] // 60} min)" for f in res['fixed'][:5]) + ('…' if n > 5 else '') + '.')
        db.commit()
    from services.segments import repair_matching as _repair_matching
    res = _repair_matching(db)
    if res.get('ran') and db.execute('SELECT 1 FROM Segment LIMIT 1').fetchone():
        _tasks.record(db, 'startup:segment_matching', 'Segment times checked again',
                      f"Every segment was matched again with the impossible-time fixes: {res['before']:,} efforts before, {res['after']:,} now; "
                      f"{res['prs_moved']} segment PR{'s' if res['prs_moved'] != 1 else ''} changed. "
                      f"{res['loops']} loop segment{'s' if res['loops'] != 1 else ''} cut again from the ride{'s' if res['loops'] != 1 else ''} "
                      f"{'they were' if res['loops'] != 1 else 'it was'} made on. {res['realigned']} track{'s' if res['realigned'] != 1 else ''} "
                      "whose GPS and times were out of step put right"
                      + (f"; {res['misaligned']} more can't be put right here, and their segment times are left out until they're imported "
                         "again from their files (the same Strava export or file: they're repaired as they come in)" if res['misaligned'] else '') + '.')
        db.commit()
    res = _moving_time.repair_paused(db)
    if res.get('fixed'):
        n, saved_h = len(res['fixed']), sum(f[2] - f[3] for f in res['fixed']) / 3600
        _tasks.record(db, 'startup:moving_time_paused', 'Moving times without the stops',
                      f"{n} activit{'y' if n == 1 else 'ies'} recorded with auto-pause off counted every stop as moving; they now take the moving time "
                      f"from the track, as Strava does ({saved_h:,.0f} hours in all, so average speeds go up): "
                      + '; '.join(f"{f[1] or f[0]} ({f[2] // 60} → {f[3] // 60} min)" for f in sorted(res['fixed'], key=lambda f: f[3] - f[2])[:5])
                      + ('…' if n > 5 else '') + '.')
        db.commit()
    from services.max_stats import fix_sensor_top_speed as _fix_sensor_top_speed
    res = _fix_sensor_top_speed(db)
    if res:
        from services import units as _units
        _tasks.record(db, 'startup:sensor_top_speed', 'Top speeds from a faulty speed sensor',
                      f"{len(res)} activit{'y' if len(res) == 1 else 'ies'} whose speed sensor logged far more distance than the GPS shows now take "
                      "their top speed from the GPS: " + '; '.join(f"{f[1] or f[0]} ({_units.fmt_speed(f[2])} → {_units.fmt_speed(f[3])})"
                                  for f in sorted(res, key=lambda f: f[3] - f[2])[:5])
                      + ('…' if len(res) > 5 else '') + '.')
        db.commit()
    from services.best_efforts import rescan_clean as _rescan_clean
    res = _rescan_clean(db)
    if res.get('ran') and res['scanned']:
        from services import units as _units
        moved = '; '.join(f"{_units.localise(f'{mi:g} miles')}: {_mmss(old)} → {_mmss(new)}" for mi, old, new in res['changed'][:7])
        _tasks.record(db, 'startup:best_efforts_clean', 'Best times without GPS jumps',
                      f"Best times worked out again for {res['scanned']:,} rides, and for every run and swim, leaving out the stretches that can't be "
                      "real (faster than 108 km/h on a bike, or the speed sensor's distance far ahead of the GPS). "
                      + (f"Ride records that changed: {moved}." if moved else 'No ride record changed.'))
        db.commit()
    from services import sport_records as _sport_records
    done = db.execute('SELECT sportEffortsDone FROM Settings WHERE id=1').fetchone()
    n_efforts = _sport_records.ensure(db)              # every start: anything that came in without its best times; the first time, every run and swim
    if done is not None and not done[0]:
        db.execute('UPDATE Settings SET sportEffortsDone=1 WHERE id=1')
        if n_efforts:
            _tasks.record(db, 'startup:sport_efforts', 'Best times for runs and swims',
                          f"Worked out for {n_efforts} run{'s' if n_efforts != 1 else ''} and swim{'s' if n_efforts != 1 else ''}: "
                          "1 km to the marathon on foot, 100 m to 3.8 km in the water. They're on the Data page and your profile.")
        db.commit()
    from services.reimport import ensure_schema as _reimport_schema
    _reimport_schema(db)
    from services.sport_fix import ensure_schema as _sport_fix_schema
    _sport_fix_schema(db)
    from services.origin import backfill as _origin_backfill
    _origin_backfill(db)
    db.commit()


def _mmss(secs):
    if not secs:
        return '—'
    h, m, sec = secs // 3600, secs % 3600 // 60, secs % 60
    return f'{h}:{m:02d}:{sec:02d}' if h else f'{m}:{sec:02d}'


def get_db():
    if 'db' not in g:
        g.db = sqlite3.connect(
            current_app.config['DATABASE'],
            detect_types=sqlite3.PARSE_DECLTYPES,
            timeout=60,
        )
        g.db.row_factory = sqlite3.Row
        g.db.execute('PRAGMA journal_mode = WAL')
        # With WAL, NORMAL can't corrupt the database: a power cut can only lose the last commits, and it saves an fsync per commit (slow on
        # an SD card). The sorts behind the badges and leaderboards use temporary tables, kept in memory; 8 MB of page cache per connection.
        g.db.execute('PRAGMA synchronous = NORMAL')
        g.db.execute('PRAGMA temp_store = MEMORY')
        g.db.execute('PRAGMA cache_size = -8000')
    return g.db


def close_db(e=None):
    db = g.pop('db', None)
    if db is not None:
        db.close()


def query_db(query, args=(), one=False):
    cur = get_db().execute(query, args)
    rv = cur.fetchall()
    return (rv[0] if rv else None) if one else rv
