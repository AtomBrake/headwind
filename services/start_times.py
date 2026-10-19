"""One-off repair: rides imported from files (FIT, GPX, a Strava export) were saved with their UTC start time as if it were UK local time, so all summer
they sit an hour early. Besides the wrong time of day (and weather looked up for the wrong hour), the same ride from Garmin then didn't overlap its
imported twin, the duplicate check never matched them, and both counted in every total.

The signature of such a ride is startDate == startDateLocal: the import stored the naive time in both. Every path that knows the real local time
(Garmin, the phone app, a GPX with a 'Z') stores the UTC instant and the local time separately, and they differ all summer; in winter they are equal
but UTC is UK time then, so moving those changes nothing. Garmin, manual, converted and demo rides, and friends' synced rides, are left alone."""
import logging
from datetime import datetime, timezone
from services import tz

log = logging.getLogger(__name__)

_SKIP = ('garmin_%', 'man_%', 'conv_%', 'demo_%')


def fix_utc_starts(db):
    """Run once (Settings.utcStartFixDone). Moves each such ride's start to local time, keeps the UTC instant in startDate, and runs the duplicate
    check on every ride it moved, so the Garmin twin of an imported ride is found and the weaker copy is set aside (not deleted; it can be swapped
    back from the ride page). Commits. Returns {'moved', 'duplicates', 'ran'}."""
    from services import duplicates
    s = db.execute('SELECT utcStartFixDone FROM Settings WHERE id=1').fetchone()
    if not s or s['utcStartFixDone']:
        return {'moved': 0, 'duplicates': 0, 'ran': False}
    skip_sql = ' AND '.join('a.id NOT LIKE ?' for _ in _SKIP)
    rows = db.execute(f'''SELECT a.id, a.startDateLocal FROM Activity a
                          WHERE {skip_sql} AND a.riderId NOT IN (SELECT riderId FROM Friend WHERE riderId IS NOT NULL)
                            AND (a.startDate IS NULL OR substr(a.startDate, 1, 19) = substr(a.startDateLocal, 1, 19))''', list(_SKIP)).fetchall()
    moved = []
    for r in rows:
        try:
            utc = datetime.fromisoformat(str(r['startDateLocal'])[:19]).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        local = utc.astimezone(tz.zone()).strftime('%Y-%m-%dT%H:%M:%S')
        db.execute('UPDATE Activity SET startDate=?, startDateLocal=? WHERE id=?', [utc.strftime('%Y-%m-%dT%H:%M:%S'), local, r['id']])
        if local != str(r['startDateLocal'])[:19]:
            moved.append(r['id'])
    found = 0
    for act_id in moved:
        if db.execute('SELECT 1 FROM Activity WHERE id=?', [act_id]).fetchone():      # may have been set aside already as another's twin
            if duplicates.resolve(db, act_id):
                found += 1
    db.execute('UPDATE Settings SET utcStartFixDone=1 WHERE id=1')
    db.commit()
    if moved:
        log.info('Start times: moved %d imported ride(s) from UTC to local time; %d turned out to be a ride already here', len(moved), found)
    return {'moved': len(moved), 'duplicates': found, 'ran': True}


def recheck_away_starts(db):
    """Run once (Settings.awayStartRecheckDone). The duplicate check used to read Garmin's local start time in the home time zone, but it is the clock
    where the ride happened: on a trip abroad (a Vancouver walk with London as home) the Garmin copy sat hours away from its Strava or file twin, and
    both were kept. Matching now uses the stored UTC instant; this re-runs the check on every ride whose two start times disagree that way, so those
    twins are found and the weaker copy is set aside (not deleted; it can be swapped back from the ride page). Commits.
    Returns {'checked', 'duplicates', 'ran'}."""
    from services import duplicates
    s = db.execute('SELECT awayStartRecheckDone FROM Settings WHERE id=1').fetchone()
    if not s or s['awayStartRecheckDone']:
        return {'checked': 0, 'duplicates': 0, 'ran': False}
    rows = db.execute('''SELECT id, startDate, startDateLocal FROM Activity
                         WHERE startDate IS NOT NULL AND riderId NOT IN (SELECT riderId FROM Friend WHERE riderId IS NOT NULL)''').fetchall()
    away = [r['id'] for r in rows if duplicates.start_instant(r) != duplicates.instant(r['startDateLocal'])]
    found = 0
    for act_id in away:
        if db.execute('SELECT 1 FROM Activity WHERE id=?', [act_id]).fetchone():      # may have been set aside already as another's twin
            if duplicates.resolve(db, act_id):
                found += 1
    db.execute('UPDATE Settings SET awayStartRecheckDone=1 WHERE id=1')
    db.commit()
    if found:
        log.warning('Start times: %d ride(s) recorded away from the home time zone turned out to be a ride already here', found)
    return {'checked': len(away), 'duplicates': found, 'ran': True}
