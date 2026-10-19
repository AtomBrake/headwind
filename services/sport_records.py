"""Best times over standard distances for runs and swims, the way services/best_efforts does them for rides: the quickest stretch of each distance
anywhere in the activity, by a sliding window over its distance and time streams. Kept per activity in SportEffort so pages and Home Assistant only
read them.

An activity is looked at once. Its rows carry the kind they were worked out for ('run' or 'swim'), and an activity that has none for its kind (new,
or its sport changed) is worked out the next time anything reads them (ensure). A row with distance 0 means "looked: too short for any distance".
Walks and hikes have no best times: a walk's quickest kilometre says little. Their records, and every other sport's, are the single-activity ones
on the Data page (longest, longest time, most climbing, fastest)."""
import json
import logging

from services.best_efforts import CEILING_MPS, effort_series, fastest

log = logging.getLogger(__name__)

RUN_DISTANCES = [(1000.0, '1 km'), (1609.344, '1 mile'), (3000.0, '3 km'), (5000.0, '5 km'), (10000.0, '10 km'),
                 (15000.0, '15 km'), (21097.5, 'Half marathon'), (42195.0, 'Marathon')]
SWIM_DISTANCES = [(100.0, '100 m'), (200.0, '200 m'), (400.0, '400 m'), (750.0, '750 m'), (1000.0, '1 km'), (1500.0, '1500 m'),
                  (1609.344, '1 mile'), (2000.0, '2 km'), (3800.0, '3.8 km')]
DISTANCES = {'run': RUN_DISTANCES, 'swim': SWIM_DISTANCES}
LABELS = {'run': 'Runs', 'swim': 'Swims'}
_RUNS = ('run', 'trailrun', 'virtualrun')               # services/sports._squash of Run, Trail Run, Virtual Run


def _squash(sport):
    return ''.join(c for c in (sport or '').lower() if c.isalpha())


def kind(sport):
    """'run', 'swim' or None (no best times)."""
    s = _squash(sport)
    if s in _RUNS:
        return 'run'
    if 'swim' in s:
        return 'swim'
    return None


def kind_sql(col='sportType'):
    """kind() for a query: 'run', 'swim' or NULL."""
    s = f"replace(replace(replace(lower(COALESCE({col}, '')), ' ', ''), '-', ''), '_', '')"
    runs = ', '.join(f"'{r}'" for r in _RUNS)
    return f"(CASE WHEN {s} IN ({runs}) THEN 'run' WHEN {s} LIKE '%swim%' THEN 'swim' END)"


def ensure_schema(db):
    """SportEffort replaces RunEffort, which held runs only (it was a cache: every run is worked out again). Does not commit."""
    db.execute('''CREATE TABLE IF NOT EXISTS SportEffort (
        activityId   TEXT NOT NULL,
        activityDate TEXT,
        kind         TEXT NOT NULL,              -- run | swim
        distanceM    REAL NOT NULL,              -- 0: looked, too short for any distance
        elapsedSecs  INTEGER NOT NULL,
        PRIMARY KEY (activityId, kind, distanceM)
    )''')
    db.execute('CREATE INDEX IF NOT EXISTS idx_sporteffort_kind ON SportEffort(kind, distanceM, elapsedSecs)')
    db.execute('DROP TABLE IF EXISTS RunEffort')


def compute(streams_json, k):
    """[(distance_m, best_elapsed_secs)] for every one of kind k's distances the activity is long enough to contain. Stretches that can't be real
    (the device's distance far ahead of the GPS, or faster than a runner or swimmer can go) are left out: services/best_efforts.effort_series."""
    try:
        streams = json.loads(streams_json or '{}')
    except Exception:
        return []
    d, t = effort_series(streams, CEILING_MPS[k])
    if not d:
        return []
    out = []
    for target, _label in DISTANCES[k]:
        best = fastest(d, t, target)
        if best is None:
            if d[-1] - d[0] < target:
                break
            continue
        out.append((target, int(best)))
    return out


def index(db, act_id, act_date, sport, streams_json):
    """Work out one activity's best times again (replacing any it had). An activity of no kind just loses its rows. Does not commit."""
    db.execute('DELETE FROM SportEffort WHERE activityId=?', [act_id])
    k = kind(sport)
    if not k:
        return 0
    day = str(act_date or '')[:10]
    rows = compute(streams_json, k) or [(0.0, 0)]
    db.executemany('INSERT OR REPLACE INTO SportEffort (activityId, activityDate, kind, distanceM, elapsedSecs) VALUES (?,?,?,?,?)',
                   [(act_id, day, k, dist, secs) for dist, secs in rows])
    return len(rows)


def forget(db, act_id):
    """Does not commit."""
    db.execute('DELETE FROM SportEffort WHERE activityId=?', [act_id])


def ensure(db, rider_id=None):
    """Work out the best times of every run and swim that has none for its kind yet, then commit. Cheap when there's nothing to do: one query."""
    k = kind_sql('a.sportType')
    sql = (f"SELECT a.id, a.startDateLocal, a.sportType FROM Activity a WHERE {k} IS NOT NULL"
           + (' AND a.riderId=?' if rider_id is not None else '')
           + f" AND NOT EXISTS (SELECT 1 FROM SportEffort e WHERE e.activityId = a.id AND e.kind = {k})")
    todo = db.execute(sql, [rider_id] if rider_id is not None else []).fetchall()
    for row in todo:
        streams = db.execute('SELECT streams FROM Activity WHERE id=?', [row[0]]).fetchone()[0]
        index(db, row[0], row[1], row[2], streams)
    if todo:
        db.commit()
    return len(todo)


def efforts(db, rider_id, k, where='1=1', params=()):
    """Every best time of kind k for the rider's activities of that kind, quickest first within each distance:
    [{distanceM, elapsedSecs, activityId, activityDate, name}]. `where` narrows the activities (on alias a)."""
    return db.execute(f'''SELECT e.distanceM, e.elapsedSecs, e.activityId, e.activityDate, a.name, a.sportType
                          FROM SportEffort e JOIN Activity a ON a.id = e.activityId
                          WHERE a.riderId=? AND e.kind=? AND e.distanceM > 0 AND {kind_sql('a.sportType')} = ? AND {where}
                          ORDER BY e.distanceM, e.elapsedSecs, e.activityDate''', [rider_id, k, k, *params]).fetchall()


def bests(db, rider_id, k, where='1=1', params=()):
    """{distanceM: the quickest effort's row} for kind k."""
    out = {}
    for r in efforts(db, rider_id, k, where, params):
        out.setdefault(r['distanceM'], r)
    return out
