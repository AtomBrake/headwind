"""Distances an old Strava import stored in millimetres. Strava's activities.csv has two 'Distance' columns, km then metres; csv.DictReader keeps
the second, and imports before the fork's `_csv_distance` (routes/import_rides.py) multiplied it by 1,000 as if it were km. That only reached
activities whose file gave no distance (a manual entry, a file that couldn't be read), so they're the ones with no track to say otherwise.
Upstream's own backfill (database.py, distanceBackfillDone) put right walks, runs and hikes over 500 km only; rides and the rest kept theirs."""
import json

MAX_AVG_MPS = 40        # 144 km/h over the whole activity: no sport here gets near it, and every stored-in-mm one is far beyond it


def fix(db):
    """Run once (Settings.mmDistancesDone): every activity faster than MAX_AVG_MPS over its time gets its distance divided by 1,000, unless its
    own distance stream agrees with it (a real track, however wrong; not this). An average speed of 0 is worked out again. Commits.
    Returns [(id, name, old metres, new metres)], or None when it has run before."""
    s = db.execute('SELECT mmDistancesDone FROM Settings WHERE id=1').fetchone()
    if not s or s['mmDistancesDone']:
        return None
    fixed = []
    for r in db.execute('SELECT id, name, distance, movingTime, averageSpeed, streams FROM Activity '
                        'WHERE distance > ? * COALESCE(NULLIF(elapsedTime, 0), NULLIF(movingTime, 0))', [MAX_AVG_MPS]).fetchall():
        try:
            dist = ((json.loads(r['streams'] or '{}') or {}).get('distance') or {}).get('data') or []
        except (TypeError, ValueError, AttributeError):
            dist = []
        if dist and isinstance(dist[-1], (int, float)) and abs(dist[-1] - r['distance']) <= 0.2 * r['distance']:
            continue
        new = r['distance'] / 1000
        avg = new / r['movingTime'] if not r['averageSpeed'] and r['movingTime'] else r['averageSpeed']
        db.execute("UPDATE Activity SET distance=?, averageSpeed=?, updatedAt=datetime('now') WHERE id=?", [new, avg, r['id']])
        fixed.append((r['id'], r['name'], r['distance'], new))
    db.execute('UPDATE Settings SET mmDistancesDone=1 WHERE id=1')
    db.commit()
    return fixed
