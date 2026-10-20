"""Importing a ride that is already saved (same id, e.g. a Strava export imported again). It used to be skipped outright, so a ride that first came in
broken (the 1000x distances, a GPX whose times couldn't be read) could never be repaired by importing again. Now the file is read anyway and
compared with the saved ride. Identical within rounding: skipped as before. Different: nothing is overwritten on the spot; the differences are kept
(ImportChange) and listed on the Import page, where the rider picks for each ride: keep the saved one, use the import, or fill in only what the
saved ride is missing. The rider's own edits (name, bike, notes, type, a dismissed flag) are never touched.

Reading every file again is most of an import's time (a FIT file is about half a second), so a file that can't give anything new is not read
(ImportSeen). Each one imported is remembered with a fingerprint of everything that decides what comes out of it: the file (the zip's CRC and
size), its row in a Strava export's activities.csv, the rider, and reader_version(), a hash of the code that reads files and compares them with
what's saved (READER_MODULES) and of the file libraries' versions. When all of that is the same and the activity is still saved, the import
skips it. A Headwind release that changes how files are read changes reader_version() by itself, so the next import reads every file again
and picks up what's new (0.7.9-beta's laps and pool lengths, say): nothing has to be remembered to bump."""
import hashlib
import importlib
import inspect
import json

# Activity columns an import can supply (calories handled separately, through the burn adjustment)
COLUMNS = ('distance', 'movingTime', 'elapsedTime', 'totalElevationGain', 'averageSpeed', 'maxSpeed', 'averageHeartrate', 'maxHeartrate',
           'averageWatts', 'maxWatts', 'averageCadence', 'startLat', 'startLng', 'streams', 'startDate', 'startDateLocal', 'rawData')
STREAM_NAMES = {'latlng': 'GPS', 'altitude': 'altitude', 'heartrate': 'heart rate', 'watts': 'power', 'cadence': 'cadence', 'velocity_smooth': 'speed',
                'distance': 'distance'}


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
    db.execute('''CREATE TABLE IF NOT EXISTS ImportProblem (
        rideId    TEXT PRIMARY KEY,
        riderId   INTEGER,
        rideName  TEXT,
        file      TEXT,                      -- the file the import couldn't read
        problem   TEXT NOT NULL,             -- what was saved instead, for the page
        foundAt   TEXT DEFAULT (datetime('now'))
    )''')
    db.execute('''CREATE TABLE IF NOT EXISTS ImportSeen (
        sourceKey   TEXT PRIMARY KEY,        -- 'strava:<activity id>' for an export's row, 'file:<crc>:<size>' for a file in a zip
        activityId  TEXT NOT NULL,           -- what it was saved as, or compared with
        fingerprint TEXT NOT NULL,           -- fingerprint(): the file, its activities.csv row, the rider, reader_version()
        seenAt      TEXT
    )''')


# The code that decides what an import makes of a file: reading it (parser, with best_efforts' sensor check and sports' water test), the export's
# own figures and crops (routes.import_rides), and the comparison with what's saved (reimport, with duplicates' time parsing), and the time
# zone an activity's local time is taken in (tz).
# tests/test_import_seen.py checks every module the parser imports is here.
READER_MODULES = ('services.parser', 'services.best_efforts', 'services.sports', 'services.reimport', 'services.duplicates', 'services.tz',
                  'services.sanity', 'routes.import_rides')       # sanity: its limits decide when a Strava export's climb replaces the file's
READER_LIBRARIES = ('fitparse', 'gpxpy', 'tzfpy')        # a FIT library that replaces fitparse goes here too; tzfpy: the local time where it happened
_reader_version = None


def reader_version():
    """A hash of READER_MODULES' source and READER_LIBRARIES' versions: it changes whenever a release changes how files are read. Where the
    source can't be read (the Windows build ships compiled code), Headwind's version stands in for it, so every release reads files again."""
    global _reader_version
    if _reader_version is None:
        h = hashlib.sha1()
        for name in READER_MODULES:
            try:
                src = inspect.getsource(importlib.import_module(name))
            except (OSError, TypeError):
                from version import __version__
                src = 'version ' + __version__
            h.update(name.encode() + b'\0' + src.encode() + b'\0')
        from importlib import metadata
        for lib in READER_LIBRARIES:
            try:
                h.update(f'{lib}={metadata.version(lib)}\0'.encode())
            except metadata.PackageNotFoundError:
                h.update(f'{lib}=none\0'.encode())
        _reader_version = h.hexdigest()[:16]
    return _reader_version


def fingerprint(*parts):
    """What an import of one activity depends on, with reader_version(): the same fingerprint means reading it again can't find anything new."""
    h = hashlib.sha1(reader_version().encode())
    for p in parts:
        h.update(b'\0' + (p if isinstance(p, str) else json.dumps(p, sort_keys=True, default=str)).encode())
    return h.hexdigest()


def zip_fingerprint(zf, name):
    """The zip's own record of a file (CRC-32 and size), read from its directory: free, without opening the file. '' when it's not there."""
    try:
        info = zf.getinfo(name)
    except KeyError:
        return ''
    return f'{info.CRC:08x}:{info.file_size}'


def unchanged(db, source_key, fp):
    """True when this file was imported with this fingerprint and its activity is still saved, or still set aside as a duplicate of one that is
    (a deleted one isn't: a file you import yourself may bring it back): nothing to read."""
    return bool(db.execute("""SELECT 1 FROM ImportSeen s WHERE s.sourceKey=? AND s.fingerprint=?
                                AND (EXISTS (SELECT 1 FROM Activity a WHERE a.id = s.activityId)
                                     OR EXISTS (SELECT 1 FROM ActivityDuplicate d WHERE d.id = s.activityId AND d.status = 'parked'))""",
                           [source_key, fp]).fetchone())


def remember(db, source_key, act_id, fp):
    """Note that this file was read in full and compared with (or saved as) act_id. Does not commit."""
    db.execute("INSERT OR REPLACE INTO ImportSeen (sourceKey, activityId, fingerprint, seenAt) VALUES (?,?,?,datetime('now'))", [source_key, act_id, fp])


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


def _span(v):
    """Seconds from the first point of a track to the last, or None."""
    try:
        t = ((json.loads(v) if isinstance(v, str) else (v or {})).get('time') or {}).get('data') or []
    except (ValueError, AttributeError):
        return None
    return t[-1] - t[0] if len(t) > 1 else None


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
    old_span, new_span = _span(saved['streams']), _span(act.get('streams'))
    if old_span and new_span and abs(old_span - new_span) > 60:          # cropped on Strava (or the file holds more than was saved)
        out.append({'label': 'Track', 'old': _dur(old_span) + ' recorded', 'new': _dur(new_span) + ' recorded'})
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
    if act.get('laps') and _empty(saved['laps'] if 'laps' in saved.keys() else None):     # laps and pool lengths, read from files since 0.7.9:
        db.execute('UPDATE Activity SET laps=? WHERE id=?', [act['laps'], saved['id']])     # nothing the rider edits, so filled in, not offered
    diffs = differences(saved, act)
    if not diffs:
        return False
    keep = {k: act.get(k) for k in COLUMNS + ('calories', 'name', 'cropped') if act.get(k) is not None}
    db.execute('INSERT OR REPLACE INTO ImportChange (rideId, riderId, rideName, source, diffs, act) VALUES (?,?,?,?,?,?)',
               [saved['id'], saved['riderId'], saved['name'], source, json.dumps(diffs), json.dumps(keep)])
    return True


def pending(db):
    rows = db.execute('SELECT * FROM ImportChange ORDER BY foundAt DESC, rideId').fetchall()
    return [dict(r, diffs=json.loads(r['diffs'])) for r in rows]


def note_problem(db, ride_id, rider_id, ride_name, file, problem):
    """Remember that an import couldn't read an activity's file, for the Import page (problems). Does not commit."""
    db.execute('INSERT OR REPLACE INTO ImportProblem (rideId, riderId, rideName, file, problem) VALUES (?,?,?,?,?)',
               [ride_id, rider_id, ride_name, file, problem])


def problem_solved(db, ride_id):
    """The file was read this time. Does not commit."""
    db.execute('DELETE FROM ImportProblem WHERE rideId=?', [ride_id])


def problems(db):
    """Files the imports couldn't read, newest first, for activities that are still here."""
    return [dict(r) for r in db.execute('''SELECT p.* FROM ImportProblem p JOIN Activity a ON a.id = p.rideId
                                           ORDER BY p.foundAt DESC, p.rideId''').fetchall()]


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
        flat = col == 'totalElevationGain' and new == 0 and act.get('cropped')     # a crop on Strava that kept no climb: 0 is the figure
        if (_empty(new) and not flat) or (choice == 'fill' and not _empty(saved[col])):
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
    if sets.keys() & {'distance', 'movingTime', 'elapsedTime', 'startDate', 'startDateLocal', 'streams'}:
        duplicates.recheck_parked(db, ride_id)                       # a copy set aside behind it may not be the same ride any more
    return True
