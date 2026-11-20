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


def _drop_dead_secrets(db):
    """Columns that held a secret nothing reads any more: upstream's Strava API tokens (services/vault.DEAD), and Settings.feedToken once
    services/feed_tokens.py has moved it to a FeedToken row. Emptied with secure_delete on, so their bytes go too, then dropped. feedToken
    stays while it still holds a value (encrypted with a key this server doesn't have: a restore from another server), so it isn't lost.
    An older Headwind adds feedToken back, empty, and never reads the Athlete ones. Commits when it drops something."""
    from services import vault
    gone = [(t, c) for t, cols in vault.DEAD.items() for c in vault.present(db, t, cols)]
    if vault.present(db, 'Settings', ['feedToken']):
        if not db.execute("SELECT 1 FROM Settings WHERE feedToken <> ''").fetchone():
            gone.append(('Settings', 'feedToken'))
    if not gone:
        return
    db.commit()
    with vault.secure_delete(db):
        for table, col in gone:
            db.execute(f'UPDATE {table} SET {col}=NULL')
            try:
                db.execute(f'ALTER TABLE {table} DROP COLUMN {col}')
            except sqlite3.OperationalError as e:       # SQLite before 3.35: left empty
                logging.getLogger(__name__).info('Left %s.%s empty, not dropped: %s', table, col, e)
        db.commit()
    db.execute('PRAGMA wal_checkpoint(TRUNCATE)')


# Columns that can hold most of a megabyte, kept at the end of their table. SQLite stores a large row as a chain of overflow pages and reads its
# columns in order, so reading any column that comes after a large one means reading the whole chain: `source` or `bikeId` for every activity read
# every activity's GPS streams. A column added later with ALTER TABLE lands after these, and the next start moves it in front (heavy_last).
HEAVY_COLUMNS = {
    'Activity':    ['summaryPolyline', 'description', 'notes', 'aiKudos', 'rawData', 'laps'],
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
    # A trigger on another table that writes to this one (services/streams.py's) stops the rename too while the table is gone
    writers = [(n, s) for n, s in db.execute("SELECT name, sql FROM sqlite_master WHERE type='trigger' AND tbl_name<>? AND sql IS NOT NULL",
                                             [table]).fetchall() if f' {table} ' in f' {s} '.replace('(', ' ').replace('.', ' ')]
    db.execute('BEGIN IMMEDIATE')
    for name, _ in views:
        db.execute(f'DROP VIEW "{name}"')
    for name, _ in writers:
        db.execute(f'DROP TRIGGER "{name}"')
    db.execute(f'DROP TABLE {table}')
    db.execute(f'ALTER TABLE {new} RENAME TO {table}')
    for _, _, sql in others:
        db.execute(sql)
    for _, sql in triggers + writers:
        db.execute(sql)
    for _, sql in views:
        db.execute(sql)
    db.commit()
    db.execute('PRAGMA wal_checkpoint(TRUNCATE)')
    return moved


# Settings flags of the once-only start-up repairs in migrate_db, all set on a new database. Not garminHistoryDone or garminWeightsDone: those
# are downloads still to do. Step 1 sets those it made (_STEP_1_FLAGS, as they were then); a later one's step adds its column, and sets it done
# where there are no activities to repair.
_STEP_1_FLAGS = ('distanceBackfillDone', 'utcStartFixDone', 'awayStartRecheckDone', 'localZoneFixDone', 'workoutDupCheckDone', 'dupNameFixDone',
                 'segmentFamiliesDone', 'segmentBikesMergedDone', 'movingTimeFixDone', 'segmentMatchFixDone', 'sportEffortsDone',
                 'movingTimePausedDone', 'bestEffortsCleanDone', 'sensorTopSpeedDone', 'mmDistancesDone', 'stravaManualDone', 'sanityAllSportsDone',
                 'liveParkedFixDone', 'strandedParkedFixDone', 'segmentClimbFloorDone', 'ebikeSportDone', 'segmentStopsDone',
                 'segmentRouteDone', 'segmentLapsDone', 'dupMatchFixDone')
_REPAIR_FLAGS = _STEP_1_FLAGS + ('bestEffortsKmDone',)


# One row per effort: an activity that rides a segment twice (two laps of a trail centre's loop) has two, told apart by startSecs, the seconds
# into the activity's time stream where each starts (services/segments.match_segment_efforts). NULL on an effort kept from before laps counted.
_SEGMENT_EFFORT_SQL = '''
    CREATE TABLE IF NOT EXISTS {name} (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        segmentId    INTEGER NOT NULL REFERENCES Segment(id) ON DELETE CASCADE,
        activityId   TEXT NOT NULL,
        activityDate TEXT,
        elapsedSecs  INTEGER NOT NULL,
        avgSpeedMps  REAL,
        isPR         INTEGER DEFAULT 0,
        createdAt    TEXT DEFAULT (datetime('now')),
        approx       INTEGER DEFAULT 0,
        startSecs    INTEGER,
        UNIQUE(segmentId, activityId, startSecs)
    )
'''


def _efforts_per_lap(db):
    """SegmentEffort as it was before laps counted (UNIQUE(segmentId, activityId): one effort per activity, its fastest lap) rebuilt as
    _SEGMENT_EFFORT_SQL, rows and ids kept. Small (a row per effort), so one transaction. Its index and triggers are made again further on in
    migrate_db (idx_effort_activity, services/data_version.ensure_schema); services/segments.rematch_laps finds the other laps. Commits."""
    cols = 'id, segmentId, activityId, activityDate, elapsedSecs, avgSpeedMps, isPR, createdAt, approx'
    db.commit()
    db.execute('BEGIN IMMEDIATE')
    db.execute('DROP TABLE IF EXISTS SegmentEffort_new')
    db.execute(_SEGMENT_EFFORT_SQL.format(name='SegmentEffort_new'))
    db.execute(f'INSERT INTO SegmentEffort_new ({cols}) SELECT {cols} FROM SegmentEffort')
    db.execute('DROP TABLE SegmentEffort')
    db.execute('ALTER TABLE SegmentEffort_new RENAME TO SegmentEffort')
    db.commit()


def _step_1(db):
    """The tables of database.py, as every start made them before the steps were numbered (0.7.42): on a new database, everything; on any older
    one, upstream's 0.5 included, what's missing, found from what's there, with the moves between tables (walks and runs into Activity, one
    segment effort per lap). Commits as it goes, and is safe to run again after being stopped halfway."""
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

    db.execute(_SEGMENT_EFFORT_SQL.format(name='SegmentEffort'))

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
        ('laps',            'TEXT'),     # the device's laps and a pool swim's lengths, JSON (services/parser.fit_laps); NULL for one lap and no lengths
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
        ('mqttTls',          'INTEGER DEFAULT 0'),     # Settings → MQTT: connect over TLS (services/mqtt.connection)
        ('mqttCaFile',       'TEXT'),                  # the CA file for the broker's certificate, on this server; blank = the system's
        ('coachingGoals',    'TEXT'),
        ('coachPersonality', "TEXT DEFAULT 'default'"),
        ('aiAutoAnalyse',    'INTEGER DEFAULT 0'),     # analyse each new ride as it's imported (services/auto_analyse.py)
        ('garminEmail',      'TEXT'),
        ('garminPassword',   'TEXT'),      # no longer kept: only an older install's, until services/garmin._client swaps it for tokens
        ('garminSyncHours',  'REAL DEFAULT 0.5'),
        ('garminSignInNeeded',   'TEXT'),      # when Garmin stopped accepting the saved sign-in (services/garmin._client); NULL = fine
        ('friendSyncInterval',       'INTEGER DEFAULT 15'),
        ('garminActivitySyncDate',   'TEXT'),
        ('garminSyncMode',           "TEXT DEFAULT 'health'"),
        ('heightCm',             'REAL'),
        ('sex',                  'TEXT'),
        ('birthYear',            'INTEGER'),
        ('activityFactor',       'REAL'),
        ('lossLbPerWeek',        'REAL'),
        ('stepGoal',             'INTEGER'),
        ('stepsSource',          'TEXT'),        # 'garmin' / 'phone', NULL = automatic (services/steps.py)
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
        ('garminChangesBefore',  'TEXT'),      # the older block the daily check for changes in Garmin reads next ends here (services/garmin_changes.run)
        ('garminFailCount',      'INTEGER DEFAULT 0'),
        ('garminHistoryFrom',    'TEXT'),      # how far back to pull health history: NULL = not asked yet, 'all', 'none' or a YYYY-MM-DD
        ('garminHistoryCursor',  'TEXT'),      # oldest day the history backfill has covered so far
        ('garminHistoryDone',    'INTEGER DEFAULT 0'),
        ('garminHistoryStatus',  'TEXT'),
        ('garminHistoryRetryAt', 'TEXT'),      # after a rate limit or outage, don't try again before this (UTC ISO)
        ('utcStartFixDone',      'INTEGER DEFAULT 0'),
        ('awayStartRecheckDone', 'INTEGER DEFAULT 0'),
        ('localZoneFixDone',     'INTEGER DEFAULT 0'),   # local times taken where each activity happened, Garmin's zoneless times read as UTC, pieces of rides matched (services/start_times.fix_local_zones)
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
        ('mmDistancesDone',        'INTEGER DEFAULT 0'), # distances an old Strava import stored in mm, of every sport (services/mm_distances.fix)
        ('stravaManualDone',       'INTEGER DEFAULT 0'), # manual entries an old Strava import saved unmarked, marked and brought back (services/strava_manual.fix)
        ('liveParkedFixDone',      'INTEGER DEFAULT 0'), # activities both live and set aside as a copy (a Strava export before 0.7.11), decided again (services/duplicates.repair_live_parked)
        ('strandedParkedFixDone',  'INTEGER DEFAULT 0'), # copies left behind a deleted activity moved behind the live one of the same ride (services/duplicates.repair_stranded_parked)
        ('dupMatchFixDone',        'INTEGER DEFAULT 0'), # copies set aside checked against the one kept, every activity against the 0.7.41 matching rules (services/duplicates.recheck_matching)
        ('sanityAllSportsDone',    'INTEGER DEFAULT 0'), # every sport checked once against the "looks wrong" limits, heart rate included (services/sanity.scan_every_sport)
        ('segmentClimbFloorDone',  'INTEGER DEFAULT 0'), # steep segments matched again with a speed floor that drops on a climb (services/segments.rematch_climbs)
        ('segmentStopsDone',       'INTEGER DEFAULT 0'), # every segment matched again with stops left out of the speed floor and waits at the ends out of the time (services/segments.rematch_stops)
        ('segmentRouteDone',       'INTEGER DEFAULT 0'), # every segment matched again with efforts that must follow its shape (services/segments.rematch_routes)
        ('segmentLapsDone',        'INTEGER DEFAULT 0'), # every segment matched again with an effort for each lap, not one per activity (services/segments.rematch_laps)
        ('ebikeSportDone',         'INTEGER DEFAULT 0'), # rides on an e-bike made e-bike rides (services/gear.ebike_rides)
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
        ('appearance',           "TEXT DEFAULT 'auto'"),     # the web UI: auto (follows the device), light or dark (routes/settings.APPEARANCES)
        ('distanceBackfillDone', 'INTEGER DEFAULT 0'),
        ('nutritionWeightUnit',     "TEXT DEFAULT 'stlb'"),
        ('nutritionWeightEmaAlpha', 'REAL DEFAULT 0.1'),
        ('dietStartDate',           'TEXT'),
        ('weightMilestoneLines',    'INTEGER DEFAULT 1'),    # 0 = the weight graph hides its every-stone / every-5-kg lines
        ('calorieAdjustPct',       'REAL DEFAULT 0'),
        ('claudeKey',              'TEXT'),
        ('claudeModel',            'TEXT'),
        ('timeZone',               'TEXT'),     # IANA name; blank = the server's zone (services/tz.py)
        ('birthDate',              'TEXT'),     # YYYY-MM-DD; replaces birthYear for the age (services/goal_model.profile)
        ('birthDateGuessed',       'INTEGER DEFAULT 0'),    # 1 = filled in as 1 January from birthYear; the profile forms ask for the real date
        ('thunderforestKey',       'TEXT'),     # optional map keys (services/map_tiles.py), sealed by services/vault.py
        ('osMapsKey',              'TEXT'),
        ('externalUrl',            'TEXT'),     # the outside address (services/external_url.py); blank = APP_URL
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
    if 'startSecs' not in eff_cols:
        _efforts_per_lap(db)

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
            sourceDetail TEXT,
            createdAt TEXT DEFAULT (datetime('now')),
            UNIQUE(riderId, logDate)
        )
    ''')
    # Garmin's own sourceType for a 'garmin' row (MANUAL = typed into Garmin Connect, anything else a scale); NULL for other sources
    if 'sourceDetail' not in {r[1] for r in db.execute('PRAGMA table_info(WeightLog)').fetchall()}:
        db.execute('ALTER TABLE WeightLog ADD COLUMN sourceDetail TEXT')

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
    db.commit()

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
    # A token a phone made for its Apple Watch (services/device_auth.create_child) names the phone's; revoking the phone revokes it too
    if 'parentId' not in {r[1] for r in db.execute('PRAGMA table_info(DeviceToken)').fetchall()}:
        db.execute('ALTER TABLE DeviceToken ADD COLUMN parentId INTEGER')

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

    # A new database (no Settings row, no activities) has nothing older to repair: its row starts with every once-only repair done. Otherwise
    # each repair returns early for want of the row, and the second start runs them all against the first import, which needed none of them.
    # The wizard's upsert copes with the row being there; a restored backup brings its own.
    if not db.execute('SELECT 1 FROM Settings WHERE id=1').fetchone() and not db.execute('SELECT 1 FROM Activity LIMIT 1').fetchone():
        db.execute('INSERT INTO Settings (id) VALUES (1)')
        db.execute(f"UPDATE Settings SET {', '.join(f'{f}=1' for f in _STEP_1_FLAGS)} WHERE id=1")
        db.commit()
    if merged:
        from services import tasks as _tasks
        _tasks.ensure_schema(db)
        _tasks.record(db, 'startup:merge_workouts', 'Walks, runs and other workouts moved in with the rides',
                      f"{merged['moved']} moved into one table of activities"
                      + (f"; {merged['same_id']} already there under the same id (that copy kept)" if merged['same_id'] else '')
                      + (f". The whole database as it was is in {merged['copy']}" if merged['copy'] else ''))
        db.commit()


def _ensure_service_tables(db):
    """The tables each service keeps for itself, made or brought up to date by its own ensure_schema (as the services also do before using them).
    Every start, after the steps: a service's new column goes in its ensure_schema, as before. Does not commit."""
    from services import (best_efforts, duplicates, feed_tokens, garmin_changes, garmin_failures, gear, goals, jobs, kit, photos, reimport,
                          sport_fix, sport_guess, sport_records, strava_export, strava_gear, streams, tasks)
    for mod in (streams, sport_records, best_efforts, duplicates, gear, kit, strava_gear, photos, feed_tokens, tasks, garmin_failures, reimport,
                strava_export, sport_fix, sport_guess, garmin_changes, goals, jobs):
        mod.ensure_schema(db)


def _views_and_triggers(db):
    """The views and triggers made from code (services/sports.RIDE_SQL, the columns a friend's feed shares): made again whenever the code's differ
    from the database's. They hold no data, so this is every start, not a step. Does not commit."""
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
              'startLat', 'startLng', 'weatherTempC', 'weatherWindKph', 'weatherGustKph', 'weatherWindDir', 'weatherHumidity',
              'weatherRainMm', 'weatherCode', 'weatherSummary', 'weatherWindRel', 'steps', 'riderId')
    touch = (f"CREATE TRIGGER Activity_touch AFTER UPDATE OF {', '.join(shared)} ON Activity "
             f"WHEN NEW.updatedAt IS OLD.updatedAt AND ({' OR '.join(f'NEW.{c} IS NOT OLD.{c}' for c in shared)}) "
             "BEGIN UPDATE Activity SET updatedAt = strftime('%Y-%m-%d %H:%M:%f', 'now') WHERE id = NEW.id; END")
    cur = db.execute("SELECT sql FROM sqlite_master WHERE type='trigger' AND name='Activity_touch'").fetchone()
    if not cur or ' '.join((cur[0] or '').split()) != ' '.join(touch.split()):
        db.execute('DROP TRIGGER IF EXISTS Activity_touch')
        db.execute(touch)


def _every_start(db):
    """After the steps, at every start: the services' tables, the views and triggers, the large columns put last, the secrets nothing reads
    dropped, then the repairs, each once-only one guarded by its flag in Settings. (What a stopped process left running is closed by the worker as
    it starts, services/worker.py: a web server starting again mustn't fail the jobs the worker is running.) Commits."""
    _ensure_service_tables(db)
    _views_and_triggers(db)
    db.commit()
    # Every Activity column is there now: put the large ones last (heavy_last), then the track summaries and their triggers (services/tracks.py).
    rebuilt = {t: heavy_last(db, t, cols) for t, cols in HEAVY_COLUMNS.items()}
    from services.tracks import ensure_schema as _tracks_schema
    _tracks_schema(db)
    from services.data_version import ensure_schema as _data_version_schema
    _data_version_schema(db)
    _drop_dead_secrets(db)
    db.commit()

    # Start-up repairs below record what they did for the Tasks page (services/tasks.py)
    from services import tasks as _tasks
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
    from services import mm_distances as _mm_distances
    res = _mm_distances.fix(db)                 # before the duplicate checks below, which compare distances
    if res:
        from services import units as _units
        _tasks.record(db, 'startup:mm_distances_all', 'Distances stored in millimetres',
                      f"{len(res)} activit{'y' if len(res) == 1 else 'ies'} imported from a Strava export without a track had {'its' if len(res) == 1 else 'their'} "
                      "distance stored 1,000 times too long, and now have the real one: "
                      + '; '.join(f"{f[1] or f[0]} ({_units.fmt_dist(f[2], places=0)} → {_units.fmt_dist(f[3])})" for f in res[:5])
                      + ('…' if len(res) > 5 else '') + '.')
        db.commit()
    from services import strava_manual as _strava_manual
    res = _strava_manual.fix(db)                # also before the duplicate checks: a manual entry is never a recording, nor a whole with pieces
    if res and (res['marked'] or res['restored']):
        n, back = res['marked'], res['restored']
        _tasks.record(db, 'startup:strava_manual', 'Manual entries from Strava',
                      f"{n} activit{'y' if n == 1 else 'ies'} typed in on Strava (no track, and one duration for moving and elapsed time) "
                      f"now count as manual entries, which the duplicate check never takes for a recording of a ride"
                      + (f"; {len(back)} set aside as a copy of a ride {'is' if len(back) == 1 else 'are'} back as {'its' if len(back) == 1 else 'their'} own: "
                         + '; '.join(b[1] or b[0] for b in back[:5]) + ('…' if len(back) > 5 else '') if back else '') + '.')
        db.commit()

    # ── Strava's "Virtual Ride", "E-Bike Ride", "Weight Training", ... saved as Headwind's VirtualRide, EBikeRide, Strength, ...: one sport, not two ──
    from services import sport_fix as _sport_fix
    res = _sport_fix.fix_spellings(db)
    if res:
        from services.sports import label as _sport_label, canonical as _canonical
        n = sum(res.values())
        _tasks.record(db, 'startup:strava_spellings', "Strava's names for sports",
                      f"{n:,} activit{'y' if n == 1 else 'ies'} saved under Strava's name for a sport now {'has' if n == 1 else 'have'} Headwind's, "
                      "so each sport is listed and counted as one: "
                      + '; '.join(f"{c:,} {s} → {_canonical(s)} ({_sport_label(_canonical(s))})" for s, c in res.items()) + '.')
        db.commit()

    # ── Rides and runs in Zwift's made-up worlds saved as outdoor ones: indoor ones now; indoor activities' segment efforts gone ──
    res = _sport_fix.fix_misfiled(db)
    if res['moved'] or res['efforts']:
        from services.sports import label as _sport_label
        moved = res['moved']
        _tasks.record(db, 'startup:zwift_misfiled', 'Zwift activities saved as outdoor ones',
                      (f"{len(moved)} activit{'y' if len(moved) == 1 else 'ies'} starting in one of Zwift's made-up worlds (out at sea near the Solomon "
                       "Islands) had been saved as outdoor ones, and now count as indoor: their best times are the indoor ones', their start time "
                       "is on your clock, and they have no weather or segments: "
                       + '; '.join(f"{m[1] or m[0]} ({_sport_label(m[2])} → {_sport_label(m[3])})" for m in moved[:5])
                       + ('…' if len(moved) > 5 else '') + '. ' if moved else '')
                      + (f"{res['efforts']} segment effort{'s' if res['efforts'] != 1 else ''} on indoor rides and runs removed: Zwift's roads "
                         "aren't the segments' roads." if res['efforts'] else ''))
        db.commit()

    # ── Weather on virtual rides: looked up at the Zwift world's spot (Watopia is open sea near the Solomon Islands), never where the rider was ──
    from services.sports import virtual_sql as _virtual_sql
    n_wx = db.execute(f"""UPDATE Activity SET weatherTempC=NULL, weatherWindKph=NULL, weatherGustKph=NULL, weatherWindDir=NULL, weatherHumidity=NULL,
                                  weatherRainMm=NULL, weatherCode=NULL, weatherSummary=NULL, weatherWindRel=NULL, weatherSource=NULL
                          WHERE {_virtual_sql()} AND (weatherSummary IS NOT NULL OR weatherTempC IS NOT NULL)""").rowcount
    if n_wx:
        _tasks.record(db, 'startup:virtual_weather', 'Weather taken off Zwift activities',
                      f"{n_wx} indoor ride{'s' if n_wx != 1 else ''} or run{'s' if n_wx != 1 else ''} had the weather of the Zwift world's spot on the "
                      "globe (Watopia is out at sea near the Solomon Islands), not yours; it's gone, and indoor activities stay out of the weather analytics")
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
    from services.start_times import fix_local_zones
    res = fix_local_zones(db)
    if res.get('ran') and (res['moved'] or res['fragments'] or res['repointed']):
        n = res['moved']
        _tasks.record(db, 'startup:local_zones', 'Start times where each activity happened',
                      f"{n:,} activit{'y' if n == 1 else 'ies'} moved to the local time where {'it' if n == 1 else 'they'} started (a Garmin activity with no "
                      "time zone of its own had been read as home time, and every import used the home zone); their weather will be looked up again for "
                      f"the right hour. Every activity was then checked for duplicates again: {res['duplicates']} turned out to be an activity already here, and {res['fragments']} "
                      f"{'was a piece' if res['fragments'] == 1 else 'were pieces'} of a ride (a phone app with a speed sensor), so the weaker copy was "
                      f"set aside. {res['bikes']} ride{'s' if res['bikes'] != 1 else ''} put on {'their' if res['bikes'] != 1 else 'its'} Strava bike and "
                      f"{res['kit']} activit{'y' if res['kit'] == 1 else 'ies'} on {'their' if res['kit'] != 1 else 'its'} shoes"
                      + (f"; {res['repointed']} cop{'y' if res['repointed'] == 1 else 'ies'} set aside moved to the activity kept in the end" if res['repointed'] else '')
                      + '.')
        db.commit()
    from services.duplicates import recover_names
    res = recover_names(db)
    if res.get('ran') and res['checked']:
        _tasks.record(db, 'startup:dup_names', 'Names of merged activities',
                      f"{res['checked']} copies set aside checked; {res['renamed']} activit{'y' if res['renamed'] == 1 else 'ies'} "
                      "took back the name chosen on the copy" if res['renamed'] else f"{res['checked']} copies set aside checked; no names needed changing")
        db.commit()
    from services.duplicates import repair_live_parked
    res = repair_live_parked(db)
    if res['ran'] and (res['decided'] or res['apart'] or res['orphans'] or res['discarded']):
        n = len(res['decided'])
        names = {r[0]: r[1] for r in db.execute(f"SELECT id, name FROM Activity WHERE id IN ({','.join('?' * n)})", [k for k, _, _ in res['decided']])} if n else {}
        msg = ((f"{n} activit{'y was' if n == 1 else 'ies were'} saved twice: once as {'its' if n == 1 else 'their'} own and once set aside as a copy "
                "of another recording (a Strava export imported before 0.7.11), so the session counted twice in every total. Each pair was "
                "decided again as an import would, and the other recording set aside with its photos, commute and gear moved to the one kept: "
                + '; '.join(names.get(k) or k for k, _, _ in res['decided'][:5]) + ('…' if n > 5 else '') + '. ' if n else '')
               + (f"{len(res['apart'])} no longer match the recording they were set aside behind, and both are kept. " if res['apart'] else '')
               + (f"{res['orphans']} had been set aside behind an activity since deleted, and stay as their own. " if res['orphans'] else '')
               + (f"{res['discarded']} recording{'s' if res['discarded'] != 1 else ''} thrown away and imported again since "
                  f"{'are' if res['discarded'] != 1 else 'is'} no longer remembered as thrown away." if res['discarded'] else ''))
        _tasks.record(db, 'startup:live_parked', 'Activities counted twice', msg.strip())
        db.commit()
    from services.duplicates import repair_stranded_parked
    res = repair_stranded_parked(db)
    if res['ran'] and (res['moved'] or res['unmatched']):
        n, left = len(res['moved']), res['unmatched']
        msg = ((f"{n} recording{'s' if n != 1 else ''} set aside as a copy of an activity since deleted (most by deleting what was deleted in "
                f"Garmin) {'were' if n != 1 else 'was'} out of sight; each now sits behind the activity of the same session that's still here, "
                "where you can swap it in. " if n else '')
               + (f"{len(left)} match{'' if len(left) != 1 else 'es'} nothing still here and {'are' if len(left) != 1 else 'is'} left as "
                  f"{'they are' if len(left) != 1 else 'it is'}: " + '; '.join(f"{u[1] or u[0]}" for u in left[:5]) + ('…' if len(left) > 5 else '') + '.'
                  if left else ''))
        _tasks.record(db, 'startup:stranded_parked', 'Copies left behind deleted activities', msg.strip())
        db.commit()
    from services.duplicates import recheck_matching
    res = recheck_matching(db)
    if res['ran'] and (res['back'] or res['merged'] or res['empty']):
        nb, nm, ne = len(res['back']), len(res['merged']), res['empty']
        msg = ((f"{nb} recording{'s' if nb != 1 else ''} set aside as a copy of an activity {'they were' if nb != 1 else 'it was'} not the same as "
                f"(a Zwift race behind its warm-up, say) {'are' if nb != 1 else 'is'} back as {'their' if nb != 1 else 'its'} own: "
                + '; '.join(name or i for i, name in res['back'][:5]) + ('…' if nb > 5 else '') + '. ' if nb else '')
               + (f"{nm} more duplicate{'s' if nm != 1 else ''} found and the weaker copy set aside: recordings with nothing in them beside a real one, "
                  "two that started the same second, a start out by a time zone, or a long piece of a longer recording. " if nm else '')
               + (f"{ne} recording{'s' if ne != 1 else ''} with nothing in {'them' if ne != 1 else 'it'} and nothing beside {'them' if ne != 1 else 'it'} "
                  f"{'are' if ne != 1 else 'is'} listed under Activities that look wrong on the dashboard, to delete." if ne else ''))
        _tasks.record(db, 'startup:dup_matching', 'Duplicates checked again', msg.strip())
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
    from services.segments import rematch_climbs as _rematch_climbs
    res = _rematch_climbs(db)
    if res.get('found'):
        _tasks.record(db, 'startup:segment_climbs', 'Slow climbs matched',
                      f"{res['found']:,} new effort{'s' if res['found'] != 1 else ''} on {res['segments']} steep segment{'s' if res['segments'] != 1 else ''}: "
                      "a climb ridden or pushed up slowly now counts as long as it keeps climbing, where before a bike slower than a brisk walk "
                      "was turned away.")
        db.commit()
    from services.segments import rematch_routes as _rematch_routes
    res = _rematch_routes(db)
    if res.get('found') or res.get('removed') or res.get('shorter') or res.get('laps'):
        s_ = lambda n, one, many: f"{n:,} {one if n == 1 else many}"
        _tasks.record(db, 'startup:segment_routes', 'Segments follow their own line',
                      f"Every segment was matched again: {s_(res['removed'], 'effort', 'efforts')} that took another way between the same start and "
                      f"finish (a road round instead of the path, the other of two lines down a hill) {'was' if res['removed'] == 1 else 'were'} removed, "
                      f"{s_(res['found'], 'new effort', 'new efforts')} found, {s_(res['shorter'], 'time', 'times')} shorter, "
                      f"{s_(res['prs_moved'], 'segment PR', 'segment PRs')} changed. An effort now has to follow the segment's own line, not only "
                      "pass near its start, finish and a few points along it."
                      + (" A stop part way along a segment no longer turns the effort away, and counts in its time; a wait at the top before "
                         "setting off, or at the bottom after finishing, doesn't." if res['stops'] else '')
                      + (f" Every lap counts now, not only an activity's fastest: {s_(res['laps'], 'more lap', 'more laps')} found."
                         if res['laps'] else ''))
        db.commit()
    from services.segments import rematch_laps as _rematch_laps
    res = _rematch_laps(db)
    if res.get('laps') or res.get('found'):
        _tasks.record(db, 'startup:segment_laps', 'Every lap of a segment',
                      f"Every segment was matched again: {res['laps']:,} more lap{'s' if res['laps'] != 1 else ''} found, "
                      f"{res['found']:,} new effort{'s' if res['found'] != 1 else ''}, {res['prs_moved']} segment PR{'s' if res['prs_moved'] != 1 else ''} "
                      "changed. An activity that rides a segment more than once (laps of a trail centre's loop, a climb ridden twice) now has an "
                      "effort for each time round, as on Strava, where only the fastest was kept.")
        db.commit()
    from services.segments import rematch_stops as _rematch_stops
    res = _rematch_stops(db)
    if res.get('found') or res.get('shorter'):
        _tasks.record(db, 'startup:segment_stops', 'Segments with a stop on them',
                      f"Every segment was matched again: {res['found']:,} new effort{'s' if res['found'] != 1 else ''}, "
                      f"{res['shorter']:,} shorter time{'s' if res['shorter'] != 1 else ''}, {res['prs_moved']} segment PR{'s' if res['prs_moved'] != 1 else ''} changed. "
                      "A stop part way along a segment (waiting for a mate half way down a trail) no longer turns the effort away, even on the ride "
                      "the segment was made on; the stop still counts in its time. A wait at the top before setting off, or at the bottom after "
                      "finishing, no longer counts in it.")
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
    from services import sanity as _sanity              # after the repairs above: a flag set before one put the ride right is out of date
    res = _sanity.scan_every_sport(db)
    if res['ran'] and res['flagged']:
        n = len(res['flagged'])
        _tasks.record(db, 'startup:sanity_all_sports', 'Activities that look wrong',
                      f"Runs, walks, hikes and swims are now checked for what can't be real, and every sport for a heart rate no heart has and a "
                      f"moving time of seconds against a real distance. {n} activit{'y' if n == 1 else 'ies'} flagged, left out of the speed charts "
                      "until you look at them on the dashboard: " + '; '.join(f"{f[1] or f[0]} ({f[3]})" for f in res['flagged'][:5])
                      + ('…' if n > 5 else '') + '.')
        db.commit()
    future = [r for r in db.execute(f'SELECT id, name, startDateLocal, riderId IN (SELECT riderId FROM Friend WHERE riderId IS NOT NULL) AS friend '
                                    f'FROM Activity WHERE {_sanity.FUTURE_SQL} AND flagReason IS NULL AND COALESCE(flagDismissed, 0) = 0').fetchall()
              if _sanity.flag(db, r[0])]
    if future:                                          # saved before the check existed: every start, so one from any path is caught
        mine = [r for r in future if not r['friend']]
        n, nf = len(future), len(future) - len(mine)
        _tasks.record(db, 'startup:future_starts', 'Activities dated in the future',
                      f"{n} activit{'y starts' if n == 1 else 'ies start'} after today, from a device whose clock was wrong, and "
                      f"{'is' if n == 1 else 'are'} left out of the speed and weather analytics. "
                      + (f"Give {'it' if len(mine) == 1 else 'them'} the real date from the dashboard's list of activities that look wrong. " if mine else '')
                      + (f"{'It is' if nf == 1 else f'{nf} are'} a friend's, which only they can put right. " if nf else '')
                      + '; '.join(f"{r['name'] or '(no name)'} ({_sanity._day(str(r['startDateLocal'])[:10])})" for r in future[:5])
                      + ('…' if n > 5 else '.'))
    cleared = [r[1] for r in db.execute('SELECT id, name FROM Activity WHERE flagReason IS NOT NULL AND COALESCE(flagDismissed, 0) = 0').fetchall()
               if _sanity.flag(db, r[0]) is None]
    if cleared:
        _tasks.record(db, 'startup:stale_flags', 'Rides that no longer look wrong',
                      f"{len(cleared)} ride{'s' if len(cleared) != 1 else ''} flagged before a repair put {'them' if len(cleared) != 1 else 'it'} right "
                      f"{'are' if len(cleared) != 1 else 'is'} off the list: " + '; '.join(n or '(no name)' for n in cleared[:5]) + ('…' if len(cleared) > 5 else '') + '.')
    db.commit()
    from services.origin import backfill as _origin_backfill
    _origin_backfill(db)
    db.commit()

    # ── Rides on an e-bike are e-bike rides (once for those already here), then Garmin activities saved with another sport than Garmin's type ──
    from services.gear import ebike_rides as _ebike_rides
    res = _ebike_rides(db)
    if res['changed']:
        from services.sports import label as _sport_label
        ch = res['changed']
        _tasks.record(db, 'startup:ebike_sport', 'Rides on an e-bike',
                      f"{len(ch):,} ride{'s' if len(ch) != 1 else ''} on a bike of kind E-bike {'is' if len(ch) == 1 else 'are'} now "
                      f"{'an e-bike ride' if len(ch) == 1 else 'e-bike rides'}, so {'it shows' if len(ch) == 1 else 'they show'} and count{'s' if len(ch) == 1 else ''} "
                      f"as {'one' if len(ch) == 1 else 'such'} in the lists, the sport filter and the totals ({'its' if len(ch) == 1 else 'their'} segment times counted as e-bike ones already). "
                      "Put on a bike that isn't an e-bike, a ride goes back to what it was: "
                      + '; '.join(f"{c[1] or c[0]} on {str(c[3])[:10]} ({_sport_label(c[2])})" for c in ch[:5]) + ('…' if len(ch) > 5 else '') + '.')
        db.commit()
    from services.sport_fix import from_seen as _sport_from_seen
    res = _sport_from_seen(db)
    db.commit()
    if res:
        n = sum(res.values())
        _tasks.record(db, 'startup:garmin_sports', 'Garmin activities with another sport',
                      f"{n:,} Garmin activit{'y is' if n == 1 else 'ies are'} saved with another sport than the type Garmin lists for "
                      f"{'it' if n == 1 else 'them'} (e-bike or mountain bike rides saved as plain rides, say, before Headwind knew those types). "
                      "Nothing has changed: review them on the Activity types page (Settings, Garmin), linked from the dashboard.")
        db.commit()


def _step_2(db):
    """The streams out of Activity into ActivityStream, compressed (services/streams.py). Rows move _HEAVY_BATCH at a time, each batch one
    commit, so a start stopped halfway carries on from there. Then the column goes and, when the disk has room, the file is compacted."""
    log = logging.getLogger(__name__)
    import zlib
    db.execute('''CREATE TABLE IF NOT EXISTS ActivityStream (
        activityId TEXT PRIMARY KEY,
        format     INTEGER NOT NULL DEFAULT 1,
        data       BLOB NOT NULL
    )''')
    if 'streams' not in {r[1] for r in db.execute('PRAGMA table_info(Activity)')}:
        return
    # What reads the column goes first (made again from the code at every start, services/tracks.py and _views_and_triggers), and with it the
    # trigger that would move every activity's updatedAt on, and so send it to every friend again.
    for kind, name in db.execute("SELECT type, name FROM sqlite_master WHERE (type='trigger' AND name IN ('Activity_touch', 'ActivityTrack_update')) "
                                 "OR (type='trigger' AND name LIKE 'ActivityStream_touch%') OR (type='view' AND name IN ('Ride', 'SegActivity'))").fetchall():
        db.execute(f'DROP {kind.upper()} "{name}"')
    db.commit()
    total = db.execute('SELECT COUNT(*) FROM Activity WHERE streams IS NOT NULL').fetchone()[0]
    moved = 0
    while True:
        rows = db.execute('SELECT rowid, id, streams FROM Activity WHERE streams IS NOT NULL LIMIT ?', [_HEAVY_BATCH]).fetchall()
        if not rows:
            break
        for _, aid, text in rows:
            if text not in ('', 'null', '{}'):
                db.execute('INSERT OR REPLACE INTO ActivityStream (activityId, format, data) VALUES (?, 1, ?)',
                           [aid, zlib.compress(text.encode() if isinstance(text, str) else text, 6)])
        db.execute(f"UPDATE Activity SET streams=NULL WHERE rowid IN ({','.join('?' * len(rows))})", [r[0] for r in rows])
        db.commit()
        moved += len(rows)
        if moved % (_HEAVY_BATCH * 20) < _HEAVY_BATCH:
            log.warning('Streams moved to their own table: %d of %d activities', moved, total)
    try:
        db.execute('ALTER TABLE Activity DROP COLUMN streams')
    except sqlite3.OperationalError as e:               # SQLite before 3.35: renamed, so SELECT * has no `streams` of its own beside streams.sql()
        log.info('Activity.streams emptied and renamed streamsMoved, not dropped: %s', e)
        db.execute('ALTER TABLE Activity RENAME COLUMN streams TO streamsMoved')
    db.commit()
    _compact(db)


def _step_3(db):
    """Settings for favourite sports, the weather's °C or °F, and the flag for the best efforts in km. A database that ran a build from
    between 0.7.42 and the numbered steps has them already."""
    have = {r[1] for r in db.execute('PRAGMA table_info(Settings)').fetchall()}
    for col, defn in [
        ('bestEffortsKmDone',    'INTEGER DEFAULT 0'),       # every ride's best efforts in km as well as miles, once, in the background (services/best_efforts.fill_km)
        ('favouriteSports',      'TEXT'),                    # JSON list of services/favourites keys ('group:ride', 'sport:Run'): sidebar items
        ('tempUnit',             "TEXT DEFAULT 'C'"),        # the weather's temperature, C or F, apart from units: a UK rider rides in miles and °C
    ]:
        if col not in have:
            db.execute(f'ALTER TABLE Settings ADD COLUMN {col} {defn}')
    if 'bestEffortsKmDone' not in have and not db.execute('SELECT 1 FROM Activity LIMIT 1').fetchone():
        db.execute('UPDATE Settings SET bestEffortsKmDone=1')


def _step_4(db):
    """Routes that follow a line (services/planned_routes.py): PlannedRoute gets a track, where it came from, its rider, sport, distance and
    climb. A route made before this is the owner's, from the planner, with its distance measured now."""
    have = {r[1] for r in db.execute('PRAGMA table_info(PlannedRoute)').fetchall()}
    for col, defn in [
        ('riderId',       'INTEGER REFERENCES Rider(id)'),
        ('source',        "TEXT DEFAULT 'planner'"),     # planner, gpx, activity, strava
        ('sourceId',      'TEXT'),                       # the activity's id, for source 'activity'
        ('sportType',     'TEXT'),                       # from the file's <type> or the activity; NULL from the planner
        ('track',         'TEXT'),                       # JSON [[lat, lng, ele], ...], or NULL for a route of waypoints
        ('distance',      'REAL'),                       # metres
        ('elevationGain', 'REAL'),                       # metres, from the track's heights
    ]:
        if col not in have:
            db.execute(f'ALTER TABLE PlannedRoute ADD COLUMN {col} {defn}')
    db.execute('UPDATE PlannedRoute SET riderId=(SELECT id FROM Rider WHERE isDefault=1 ORDER BY id LIMIT 1) WHERE riderId IS NULL')
    import json
    from services.planned_routes import distance_m
    for rid, wps in db.execute('SELECT id, waypoints FROM PlannedRoute WHERE distance IS NULL').fetchall():
        try:
            d = round(distance_m(json.loads(wps or '[]')), 1)
        except (ValueError, TypeError, KeyError, IndexError):
            d = 0
        db.execute('UPDATE PlannedRoute SET distance=? WHERE id=?', [d, rid])


def _step_5(db):
    """The streams of copies set aside or in the bin (ActivityDuplicate.rowJson) and of imports waiting on the Import page (ImportChange.act)
    out of their JSON into a streams column of their own, compressed (services/streams.apart): 460 MB of proposals from one Strava export
    imported again. In SQL, _HEAVY_BATCH rows to a commit, so a start stopped halfway carries on from there. Then the file is compacted."""
    log = logging.getLogger(__name__)
    from services import streams
    streams.register(db)
    moved = 0
    for table, col in (('ActivityDuplicate', 'rowJson'), ('ImportChange', 'act')):
        have = {r[1] for r in db.execute(f'PRAGMA table_info({table})').fetchall()}
        if not have:                                    # made with the column by its ensure_schema
            continue
        if 'streams' not in have:
            db.execute(f'ALTER TABLE {table} ADD COLUMN streams BLOB')
        db.commit()
        total, last, done = db.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0], 0, 0
        while True:
            ids = [r[0] for r in db.execute(f'SELECT rowid FROM {table} WHERE rowid > ? ORDER BY rowid LIMIT ?', [last, _HEAVY_BATCH])]
            if not ids:
                break
            last = ids[-1]
            # json_extract gives a string's text (how a row's streams are kept) and an object's JSON alike
            moved += db.execute(f"""UPDATE {table} SET streams = COALESCE(streams_pack(json_extract({col}, '$.streams')), streams),
                                                       {col} = json_remove({col}, '$.streams')
                                    WHERE rowid IN ({','.join('?' * len(ids))}) AND json_valid({col})
                                      AND json_type({col}, '$.streams') IS NOT NULL""", ids).rowcount
            db.commit()
            done += len(ids)
            if done % (_HEAVY_BATCH * 20) < _HEAVY_BATCH:
                log.warning('%s: streams compressed, %d of %d rows', table, done, total)
    if moved:
        _compact(db)


def _compact(db):
    """VACUUM, giving the space freed inside the file back to the disk, when the disk has room for it: it writes the compacted database once to
    a temporary file and once through the WAL. Logged either way. Commits."""
    import shutil
    log = logging.getLogger(__name__)
    path = db.execute('PRAGMA database_list').fetchone()[2]
    if not path:
        return
    page = db.execute('PRAGMA page_size').fetchone()[0]
    used = (db.execute('PRAGMA page_count').fetchone()[0] - db.execute('PRAGMA freelist_count').fetchone()[0]) * page
    free = shutil.disk_usage(os.path.dirname(os.path.abspath(path))).free
    if free < 2 * used + 200 * 2**20:
        log.warning('The database was not compacted: %d MB free on the disk, %d MB needed. The space freed inside it is used again as it '
                    'grows.', free >> 20, (2 * used) >> 20)
        return
    before = os.path.getsize(path)
    db.commit()
    tmp = os.environ.get('SQLITE_TMPDIR')
    os.environ['SQLITE_TMPDIR'] = os.path.dirname(os.path.abspath(path))     # beside the database, not a container's /tmp or memory
    try:
        db.execute('PRAGMA temp_store = FILE')
        db.execute('VACUUM')
        db.execute('PRAGMA wal_checkpoint(TRUNCATE)')
    finally:
        db.execute('PRAGMA temp_store = MEMORY')
        if tmp is None:
            os.environ.pop('SQLITE_TMPDIR', None)
        else:
            os.environ['SQLITE_TMPDIR'] = tmp
    log.warning('Database compacted: %d MB to %d MB', before >> 20, os.path.getsize(path) >> 20)


# ── Numbered steps ───────────────────────────────────────────────
# PRAGMA user_version is the number of the last step a database has had. migrate_db runs the steps after it, in order, then _every_start.
# A new table or column of database.py, a rename, a move between tables, anything that changes what's stored for good: a new function at the
# end of STEPS, never an edit to an earlier one, which a database that has had it never runs again (tests/test_migrations.py checks). A step
# runs in one transaction, so one that fails leaves the database as it was; one that moves a lot of data may commit in batches instead, and
# must then carry on from wherever it stopped when it's run again. keep_copy: an older Headwind can't open the result, so the whole database
# is copied beside itself first, as <database>.pre-<version>. Docker runs them before Gunicorn starts (`python -m database migrate`, from
# docker-entrypoint.sh), so a long one isn't cut short by its worker timeout; create_app runs any still to do (the Windows app, `python app.py`).
STEPS = (
    # (function, keep_copy)
    (_step_1, False),
    (_step_2, True),         # an older Headwind reads Activity.streams
    (_step_3, False),
    (_step_4, False),
    (_step_5, True),         # an older Headwind puts a copy set aside back without its streams
)
LATEST = len(STEPS)


class SchemaTooNew(RuntimeError):
    """The database has had steps this version doesn't know: a newer Headwind has opened it."""


def schema_version(db):
    return db.execute('PRAGMA user_version').fetchone()[0]


def _keep_copy(db, n):
    """<database>.pre-<version>, a copy of the whole database before step n, unless there is one already (a second try keeps the first) or the
    disk hasn't room for it, which is logged. Returns its path or None."""
    import shutil
    from version import __version__
    log = logging.getLogger(__name__)
    path = db.execute('PRAGMA database_list').fetchone()[2]
    if not path:                                        # in memory
        return None
    copy = f'{path}.pre-{__version__}'
    if os.path.exists(copy):
        return copy
    need = sum(os.path.getsize(p) for p in (path, path + '-wal') if os.path.exists(p))
    free = shutil.disk_usage(os.path.dirname(os.path.abspath(path))).free
    if free < need + 200 * 2**20:
        log.warning('Step %d: no copy of the database kept first, as there is no room for one (%d MB free, %d MB needed). Going back to an '
                    'older Headwind will need a backup.', n, free >> 20, need >> 20)
        return None
    db.commit()
    part = f'{path}.copying-{__version__}'              # not .pre-*, so an unfinished copy is never taken for one (services/vault.seal_copies)
    out = sqlite3.connect(part)
    try:
        db.backup(out)
    finally:
        out.close()
    os.replace(part, copy)
    log.warning('Step %d: the database as it was is kept in %s', n, copy)
    return copy


def migrate_db():
    """Bring the database up to this version: the steps it hasn't had, then _every_start. Raises SchemaTooNew when a newer Headwind has opened it,
    rather than guess at what that one changed."""
    log = logging.getLogger(__name__)
    db = get_db()
    db.execute('PRAGMA journal_mode = WAL')     # kept in the database file, so once here (and on a restored backup) rather than per connection
    have = schema_version(db)
    if have > LATEST:
        from version import __version__
        raise SchemaTooNew(f'This database has been opened by a newer Headwind (it has had step {have} of its changes; Headwind {__version__} '
                           f'knows {LATEST}). Run the newer version, or restore a backup made before it.')
    new = not db.execute("SELECT 1 FROM sqlite_master WHERE type='table'").fetchone()     # nothing in it to keep a copy of
    for n in range(have + 1, LATEST + 1):
        step, keep_copy = STEPS[n - 1]
        if keep_copy and not new:
            _keep_copy(db, n)
        log.info('Database: step %d of %d, %s', n, LATEST, (step.__doc__ or step.__name__).split('\n')[0])
        db.commit()
        db.execute('BEGIN IMMEDIATE')
        step(db)
        db.execute(f'PRAGMA user_version = {n}')
        db.commit()
    _every_start(db)


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
        from services import streams, vault
        streams.register(g.db)                                                 # streams_json(), for services/streams.sql()
        g.db.row_factory = vault.row_factory(current_app.config['DATABASE'])   # sqlite3.Row, with the saved keys and passwords decrypted
        # The database is in WAL mode (set once, in migrate_db). With WAL, NORMAL can't corrupt the database: a power cut can only lose the last
        # commits, and it saves an fsync per commit (slow on an SD card). The sorts behind the badges and leaderboards use temporary tables, kept in memory; 8 MB of page cache per connection.
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


def main(argv):
    """`python -m database migrate`: run the steps and the start-up work against the configured database (DATABASE_URL), then exit. Docker runs
    it before Gunicorn starts (docker-entrypoint.sh). Exits 1, saying why, when the database is newer than this version."""
    import sys
    from flask import Flask
    from config import Config
    from services import logs
    if argv != ['migrate']:
        print('usage: python -m database migrate', file=sys.stderr)
        return 2
    app = Flask(__name__)
    app.config.from_object(Config)
    app.teardown_appcontext(close_db)
    logs.setup(app.config['DATABASE'])
    try:
        with app.app_context():
            migrate_db()
    except SchemaTooNew as e:
        logging.getLogger(__name__).error('%s', e)
        return 1
    return 0


if __name__ == '__main__':
    import sys
    import database                                     # the module the services import, not a second copy of it as __main__
    sys.exit(database.main(sys.argv[1:]))
