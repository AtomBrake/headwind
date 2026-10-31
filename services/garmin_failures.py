"""Garmin activities the sync could not bring in (services/garmin.sync_garmin_activities), one row each, so one that keeps failing neither holds
the sync's cursor back for ever nor is downloaded on every run.

A download or a database write can fail for a while and then work: those are tried again after 25 minutes, then 1¾, 7 and 27 hours, and given
up on after TRIES. A file that wouldn't parse is tried once more. One given up on is skipped like an activity already here, until Headwind
is updated (a newer parser may read it: it is tried once more then) or the rider asks for it again on the Tasks page."""
from datetime import datetime, timedelta, timezone

TRIES = {'download': 5, 'insert': 5, 'parse': 2}
FIRST_WAIT = timedelta(minutes=25)      # just under the sync's half-hour interval, so the next run tries again


def ensure_schema(db):
    db.execute('''CREATE TABLE IF NOT EXISTS GarminFailure (
        activityId TEXT PRIMARY KEY,                 -- Garmin's id (Activity.id without 'garmin_')
        startDate  TEXT,                             -- its day, so a retry can move the sync's cursor back to it
        name       TEXT,
        kind       TEXT,                             -- download | parse | insert
        error      TEXT,
        tries      INTEGER NOT NULL DEFAULT 0,
        lastAt     TEXT,
        nextAt     TEXT,                             -- not before then (UTC ISO)
        gaveUp     INTEGER NOT NULL DEFAULT 0,
        version    TEXT                              -- the Headwind that gave up on it
    )''')


def _version():
    from version import __version__
    return __version__


def _iso(t):
    return t.isoformat(timespec='seconds')


def get(db, activity_id):
    return db.execute('SELECT * FROM GarminFailure WHERE activityId=?', [str(activity_id)]).fetchone()


def due(row, now=None):
    """May the sync try this one now?"""
    if row['gaveUp']:
        return row['version'] != _version()
    return not row['nextAt'] or row['nextAt'] <= _iso(now or datetime.now(timezone.utc))


def record(db, activity_id, kind, error, start_date=None, name=None, now=None):
    """Another failure. Returns True when the sync gives up on it (it then stops holding the cursor back). Does not commit."""
    now = now or datetime.now(timezone.utc)
    row = get(db, activity_id)
    if row and row['gaveUp']:
        tries, gave_up = row['tries'] + 1, True                 # the one more try after an update: given up on again
    else:
        tries = (row['tries'] if row else 0) + 1
        gave_up = tries >= TRIES.get(kind, 1)
    db.execute('''INSERT INTO GarminFailure (activityId, startDate, name, kind, error, tries, lastAt, nextAt, gaveUp, version)
                  VALUES (?,?,?,?,?,?,?,?,?,?)
                  ON CONFLICT(activityId) DO UPDATE SET startDate=excluded.startDate, name=excluded.name, kind=excluded.kind,
                      error=excluded.error, tries=excluded.tries, lastAt=excluded.lastAt, nextAt=excluded.nextAt, gaveUp=excluded.gaveUp,
                      version=excluded.version''',
               [str(activity_id), start_date, name, kind, str(error)[:300], tries, _iso(now),
                None if gave_up else _iso(now + FIRST_WAIT * 4 ** (tries - 1)), int(gave_up), _version() if gave_up else None])
    return gave_up


def clear(db, activity_id):
    db.execute('DELETE FROM GarminFailure WHERE activityId=?', [str(activity_id)])


def given_up(db):
    return [dict(r) for r in db.execute('SELECT * FROM GarminFailure WHERE gaveUp=1 ORDER BY startDate DESC')]


def rewind(db, cursor):
    """The sync's cursor, moved back to the day before the oldest activity that is due another try after an update, so the sync reaches it
    again (one given up on stopped holding the cursor). Does not commit."""
    rows = [r for r in db.execute('SELECT * FROM GarminFailure WHERE gaveUp=1 AND startDate IS NOT NULL') if due(r)]
    if not rows or not cursor:
        return cursor
    day = (datetime.fromisoformat(min(r['startDate'] for r in rows)) - timedelta(days=1)).date().isoformat()
    return min(cursor, day)


def retry_all(db):
    """The rider asked for every activity given up on to be tried again: forget them and move the cursor back to reach the oldest.
    Returns how many. Does not commit."""
    rows = given_up(db)
    if not rows:
        return 0
    days = [r['startDate'] for r in rows if r['startDate']]
    if days:
        day = (datetime.fromisoformat(min(days)) - timedelta(days=1)).date().isoformat()
        db.execute('UPDATE Settings SET garminActivitySyncDate=? WHERE id=1 AND garminActivitySyncDate > ?', [day, day])
    db.execute('DELETE FROM GarminFailure WHERE gaveUp=1')
    return len(rows)
