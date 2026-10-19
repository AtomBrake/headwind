"""Importing a ride that is already saved (same id, e.g. a Strava export imported again). It used to be skipped outright, so a ride that first came in
broken (the 1000x distances, a GPX whose times couldn't be read) could never be repaired by importing again. Now the file is read anyway and
compared with the saved ride. Identical within rounding: skipped as before. Different: nothing is overwritten on the spot; the differences are kept
(ImportChange) and listed on the Import page, where the rider picks for each ride: keep the saved one, use the import, or fill in only what the
saved ride is missing. The rider's own edits (name, bike, notes, type, a dismissed flag) are never touched."""
import json

# Activity columns an import can supply (calories handled separately, through the burn adjustment)
COLUMNS = ('distance', 'movingTime', 'elapsedTime', 'totalElevationGain', 'averageSpeed', 'maxSpeed', 'averageHeartrate', 'maxHeartrate',
           'averageWatts', 'maxWatts', 'averageCadence', 'startLat', 'startLng', 'streams', 'startDate', 'startDateLocal')
STREAM_NAMES = {'latlng': 'GPS', 'altitude': 'altitude', 'heartrate': 'heart rate', 'watts': 'power', 'cadence': 'cadence', 'velocity_smooth': 'speed'}


def ensure_schema(db):
    db.execute('''CREATE TABLE IF NOT EXISTS ImportChange (
        rideId    TEXT PRIMARY KEY,
        riderId   INTEGER,
        rideName  TEXT,
        source    TEXT,
        foundAt   TEXT DEFAULT (datetime('now')),
        diffs     TEXT NOT NULL,             -- [{label, old, new}] for the page
        act       TEXT NOT NULL              -- the imported ride, normalised (startDate / startDateLocal split as _insert stores them)
    )''')


def _empty(v):
    return v is None or v == 0 or (isinstance(v, str) and v.strip() in ('', '{}', 'null', '[]'))


def _streams(v):
    try:
        d = json.loads(v) if isinstance(v, str) else (v or {})
    except ValueError:
        return set()
    return {k for k, s in d.items() if isinstance(s, dict) and s.get('data')}


def _dur(secs):
    secs = int(secs or 0)
    h, r = divmod(secs, 3600)
    return f'{h}:{r // 60:02d}:{r % 60:02d}' if h else f'{r // 60}:{r % 60:02d}'


def _seconds_apart(a, b):
    from services.duplicates import instant
    ia, ib = instant(a), instant(b)
    return abs((ia - ib).total_seconds()) if ia and ib else None


def differences(saved, act):
    """[{label, old, new}] where the import has something different to offer (a value the file doesn't have is not a difference)."""
    from services import units
    out = []

    def num(col, label, tol_abs, tol_rel, fmt):
        new, old = act.get(col), saved[col]
        if _empty(new):
            return
        if _empty(old) or abs(float(new) - float(old)) > max(tol_abs, tol_rel * max(abs(float(old)), abs(float(new)))):
            out.append({'label': label, 'old': fmt(old) if not _empty(old) else '—', 'new': fmt(new)})
    num('distance', 'Distance', 50, 0.01, lambda v: units.fmt_dist(v, places=2))
    num('movingTime', 'Moving time', 60, 0.02, _dur)
    num('elapsedTime', 'Elapsed time', 60, 0.02, _dur)
    num('totalElevationGain', 'Climb', 10, 0.10, units.fmt_elev)
    if act.get('startDateLocal') and saved['startDateLocal']:
        apart = _seconds_apart(saved['startDateLocal'], act['startDateLocal'])
        if apart is not None and apart > 120:
            out.append({'label': 'Start', 'old': str(saved['startDateLocal'])[:16].replace('T', ' '), 'new': str(act['startDateLocal'])[:16].replace('T', ' ')})
    old_s, new_s = _streams(saved['streams']), _streams(act.get('streams'))
    if new_s - old_s:
        name = lambda s: ', '.join(STREAM_NAMES.get(k, k) for k in sorted(s) if k in STREAM_NAMES) or 'none'
        out.append({'label': 'Recorded data', 'old': name(old_s), 'new': name(new_s)})
    return out


def _out_of_step(streams):
    """Streams whose GPS and time have different lengths (stored before 0.7.7: services/parser.aligned_streams), or None if unreadable."""
    try:
        d = json.loads(streams) if isinstance(streams, str) else (streams or {})
    except ValueError:
        return None
    ll, tm = (d.get('latlng') or {}).get('data') or [], (d.get('time') or {}).get('data') or []
    return bool(ll and tm and len(ll) != len(tm))


def propose(db, saved, act, source):
    """Compare an import with the ride already saved under its id. Returns True if it differs (and is now waiting on the Import page). Does not commit.
    Saved streams whose GPS and time are out of step are replaced by the file's straight away, when the file's are in step: that's a repair, not a
    choice, and the rider's own edits are never in the streams. The ride is matched against the segments again."""
    if _out_of_step(saved['streams']) and _out_of_step(act.get('streams')) is False:
        db.execute('UPDATE Activity SET streams=? WHERE id=?', [act['streams'], saved['id']])
        from services.segments import rescan_activity
        rescan_activity(db, saved['id'])
        saved = {**dict(saved), 'streams': act['streams']}
    diffs = differences(saved, act)
    if not diffs:
        return False
    keep = {k: act.get(k) for k in COLUMNS + ('calories', 'name') if act.get(k) is not None}
    db.execute('INSERT OR REPLACE INTO ImportChange (rideId, riderId, rideName, source, diffs, act) VALUES (?,?,?,?,?,?)',
               [saved['id'], saved['riderId'], saved['name'], source, json.dumps(diffs), json.dumps(keep)])
    return True


def pending(db):
    rows = db.execute('SELECT * FROM ImportChange ORDER BY foundAt DESC, rideId').fetchall()
    return [dict(r, diffs=json.loads(r['diffs'])) for r in rows]


def resolve(db, ride_id, choice):
    """choice: 'keep' (the saved ride stays as it is), 'replace' (the import's values wherever it has one), 'fill' (only where the saved ride has
    nothing). Re-checks the ride and rebuilds its best efforts and segment efforts when anything changed. Returns True if the ride changed.
    Raises ValueError for an unknown choice. Does not commit."""
    if choice not in ('keep', 'replace', 'fill'):
        raise ValueError('choose keep, replace or fill')
    row = db.execute('SELECT * FROM ImportChange WHERE rideId=?', [ride_id]).fetchone()
    if not row:
        return False
    db.execute('DELETE FROM ImportChange WHERE rideId=?', [ride_id])
    saved = db.execute('SELECT * FROM Activity WHERE id=?', [ride_id]).fetchone()
    if choice == 'keep' or not saved:
        return False
    act = json.loads(row['act'])
    sets = {}
    for col in COLUMNS:
        new = act.get(col)
        if _empty(new) or (choice == 'fill' and not _empty(saved[col])):
            continue
        sets[col] = new
    if choice == 'fill' and not _empty(saved['streams']) and not _empty(act.get('streams')):     # add the streams the saved ride lacks, keep its own
        try:
            have = json.loads(saved['streams'])
            extra = {k: v for k, v in json.loads(act['streams']).items() if k not in have}
            if extra:
                sets['streams'] = json.dumps({**have, **extra})
        except ValueError:
            pass
    if not _empty(act.get('distance')) and not _empty(act.get('movingTime')) and ('distance' in sets or 'movingTime' in sets) and _empty(act.get('averageSpeed')):
        sets['averageSpeed'] = float(sets.get('distance', saved['distance'])) / float(sets.get('movingTime', saved['movingTime']))
    if not _empty(act.get('calories')) and (choice == 'replace' or _empty(saved['calories'])):
        from services.calorie_adjust import pair
        sets['caloriesRaw'], sets['calories'] = pair(act['calories'])
    if not sets:
        return False
    db.execute(f"UPDATE Activity SET {', '.join(f'{k}=?' for k in sets)}, updatedAt=datetime('now') WHERE id=?", [*sets.values(), ride_id])
    from services import duplicates, sanity
    sanity.flag(db, ride_id)                                         # a dismissed flag stays dismissed
    duplicates.rebuild_derived(db, ride_id)                          # best efforts, segment efforts, PRs
    return True
