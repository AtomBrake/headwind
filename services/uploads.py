"""Every activity the phone, the Watch or Apple Health sends, through one door (POST /api/v1/activities; the older /rides and /workouts are the
same door with the kind decided for them).

An upload carries a client_id: the iPhone's or the Watch's recording UUID, Apple Health's `ah_<uuid>`, the Android app's. It's kept on the
activity (Activity.clientId, and in the row of a copy set aside or deleted), so the same upload sent again is found by it, whatever its sport,
and the phone can ask which of its ids the server has before reading a workout's route (known). An activity uploaded before 0.7.47 has no
clientId: it is found by the id it was given from its client_id (workouts.track_id, manual_activity.session_id), and gets its clientId then.

What it goes through depends on what it is: a ride with a track, the single-file import (best efforts, segments, PRs, the bike, Home Assistant);
another sport with a track, services/workouts (best times, foot segments, weather, calories); a session with no track, services/manual_activity.
Each ends in the same check for the same session from another source (services/duplicates.resolve)."""
import logging
import os
import re
import tempfile

from services.sports import canonical, is_ride

log = logging.getLogger(__name__)
MAX_KNOWN = 500                 # client ids asked about in one request
NOTHING_RECORDED = 'The recording has no distance and no time: nothing was recorded'
_TRKPT = re.compile(rb'<(?:[\w.-]+:)?trkpt\b[^>]*?(?:/>|>(.*?)</(?:[\w.-]+:)?trkpt\s*>)', re.S)
_TIME = re.compile(rb'<(?:[\w.-]+:)?time>\s*([^<]*?)\s*</(?:[\w.-]+:)?time>')


class Refused(Exception):
    """An upload that can't be stored, with the HTTP status the API answers with."""
    def __init__(self, message, status=422):
        super().__init__(message)
        self.status = status


def clean_id(client_id):
    if client_id is None:
        return None
    return str(client_id).strip()[:80] or None


def _old_ids(rider_id, client_id):
    """The ids an upload with this client_id was given before clientId was kept: as a track, or as a session with no track (ride or not)."""
    from services import manual_activity, workouts
    return [workouts.track_id(rider_id, client_id), manual_activity.session_id(rider_id, client_id, True),
            manual_activity.session_id(rider_id, client_id, False)]


def find(db, rider_id, client_id):
    """Where an upload with this client_id went: {'id': its own id, 'stands': the live activity that stands for it (its own, or the one it was
    set aside behind), or None when it's deleted}, or None when it was never sent."""
    from services import duplicates
    duplicates.ensure_schema(db)
    row = db.execute('SELECT id FROM Activity WHERE riderId=? AND clientId=?', [rider_id, client_id]).fetchone()
    if row:
        return {'id': row['id'], 'stands': row['id']}
    old = _old_ids(rider_id, client_id)
    marks = ','.join('?' * len(old))
    row = db.execute(f'SELECT id FROM Activity WHERE riderId=? AND id IN ({marks})', [rider_id, *old]).fetchone()
    if row:
        return {'id': row['id'], 'stands': row['id']}
    d = db.execute(f"""SELECT id, primaryId, status FROM ActivityDuplicate WHERE riderId=? AND status IN ('parked', 'deleted')
                       AND (id IN ({marks}) OR json_extract(rowJson, '$.clientId')=?) ORDER BY status='deleted' LIMIT 1""",
                   [rider_id, *old, client_id]).fetchone()
    if not d:
        return None
    live = d['status'] == 'parked' and db.execute('SELECT 1 FROM Activity WHERE id=?', [d['primaryId']]).fetchone()
    return {'id': d['id'], 'stands': d['primaryId'] if live else None}


def known(db, rider_id, client_ids):
    """Which of these client ids the server has: live, set aside behind another recording, or deleted (an automatic sync mustn't bring a
    deleted one back). Those uploaded before clientId was kept are found by their old ids."""
    from services import duplicates
    duplicates.ensure_schema(db)
    ids = list(dict.fromkeys(c for c in map(clean_id, client_ids) if c))[:MAX_KNOWN]
    if not ids:
        return []
    marks = ','.join('?' * len(ids))
    have = {r[0] for r in db.execute(f'SELECT clientId FROM Activity WHERE riderId=? AND clientId IN ({marks})', [rider_id, *ids])}
    have |= {r[0] for r in db.execute(f"""SELECT json_extract(rowJson, '$.clientId') FROM ActivityDuplicate WHERE riderId=?
                                          AND status IN ('parked', 'deleted') AND json_extract(rowJson, '$.clientId') IN ({marks})""",
                                      [rider_id, *ids])}
    rest = [c for c in ids if c not in have]
    by_old = {o: c for c in rest for o in _old_ids(rider_id, c)}
    if by_old:
        marks = ','.join('?' * len(by_old))
        for r in db.execute(f"""SELECT id FROM Activity WHERE riderId=? AND id IN ({marks})
                                UNION SELECT id FROM ActivityDuplicate WHERE riderId=? AND status IN ('parked', 'deleted') AND id IN ({marks})""",
                            [rider_id, *by_old, rider_id, *by_old]):
            have.add(by_old[r[0]])
    return [c for c in ids if c in have]


def remember(db, act_id, client_id):
    """Keep the client_id on an activity uploaded before it was kept: the live row, or the row of a copy set aside or deleted. Does not commit."""
    if not db.execute('UPDATE Activity SET clientId=? WHERE id=? AND clientId IS NULL', [client_id, act_id]).rowcount:
        db.execute("""UPDATE ActivityDuplicate SET rowJson=json_set(rowJson, '$.clientId', ?)
                      WHERE id=? AND rowJson<>'{}' AND json_extract(rowJson, '$.clientId') IS NULL""", [client_id, act_id])


def _kind(db, act_id):
    row = db.execute('SELECT sportType FROM Activity WHERE id=?', [act_id]).fetchone()
    return 'ride' if row and is_ride(row['sportType']) else 'workout'


def _reply(db, act_id, created, via, duplicate=None, **extra):
    return {'status': 'created' if created else 'exists', 'created': created, 'kind': _kind(db, act_id), 'id': act_id, 'via': via,
            'duplicate': duplicate, **extra}


def receive(db, rider_id, client_id=None, source=None, gpx=None, filename=None, sport=None, kind=None, name=None, bike_id=None,
            calories=None, steps=None, session=None):
    """Store one upload, or find it if it was sent before. `gpx` is the recording's file (bytes); without one, `session` is the timed session's
    fields (manual_activity.create's: start, duration_s, distance_m, elev_m, calories, avg_hr, notes). `kind` 'ride' or 'workout' is decided for it by
    the older /rides and /workouts; otherwise the sport decides, or the file's own when none is given; `bike_id` is one of the rider's, already checked. Returns
    {status 'created'|'exists', created, kind, id (the activity that stands for it), via 'ride'|'track'|'session' (None when it was sent
    before), duplicate, ...}: created is False when it was here already or was set aside behind another recording of the same session.
    Raises Refused. Commits."""
    client_id = clean_id(client_id)
    sport = canonical(sport) if sport else None
    if client_id:
        had = find(db, rider_id, client_id)
        if had and had['stands']:                      # sent before: a retry after a lost reply, or a sync going over the same workouts again
            remember(db, had['id'], client_id)
            db.commit()
            return _reply(db, had['stands'], False, None)
    if gpx is None:
        return _session(db, rider_id, client_id, source, sport, name, bike_id, session or {})
    if _no_time(gpx):
        log.warning('Upload refused: its track is one moment (client_id=%s, source=%s)', client_id, source)
        raise Refused(NOTHING_RECORDED)
    ride = kind == 'ride' if kind else (is_ride(sport) if sport else _file_is_ride(gpx, filename))
    if ride:
        return _ride(db, rider_id, client_id, source, gpx, filename, bike_id)
    return _track(db, rider_id, client_id, source, gpx, sport, name, calories, steps)


def _no_time(data):
    """True when a GPX track's first and last timed points are at the same moment (one point, or one stale location sent over and over, as Apple
    Health has given a workout's route): stored, it would be an activity with no distance and no time. A scan of the <trkpt> times only, not a
    parse, as the ride and workout paths parse the file themselves. A FIT or gzipped file, a track with no times, or a time that can't be read
    is left to them: they refuse those with their own reason."""
    from services.parser import sniff
    if sniff(data) != 'gpx':
        return False
    first = last = None
    for m in _TRKPT.finditer(data):
        t = _TIME.search(m.group(1) or b'')
        if t and t.group(1):
            if first is None:
                first = t.group(1)
            last = t.group(1)
    if first is None:
        return False
    from gpxpy.gpxfield import parse_time
    try:
        a, b = (parse_time(s.decode('ascii').upper()) for s in (first, last))
    except Exception:
        return False
    return a == b


def _file_is_ride(data, filename):
    from services.parser import parse_activity_file
    try:
        act = parse_activity_file((filename or 'upload.gpx').lower(), data)
    except Exception:
        return False                                   # the workout path says why it can't be read
    return bool(act) and is_ride(act.get('sportType'))


def _ride(db, rider_id, client_id, source, data, filename, bike_id):
    """A ride with a track, through the web's single-file import."""
    import json
    from routes.import_rides import _process_single_file
    from services.parser import ACTIVITY_EXTENSIONS
    name = filename if (filename or '').lower().endswith(ACTIVITY_EXTENSIONS) else 'upload.gpx'
    with tempfile.NamedTemporaryFile(delete=False, suffix='.gpx') as tmp:
        tmp.write(data)
    done = {}
    try:
        for ev in _process_single_file(tmp.name, name, rider_id, bike_id=bike_id, client_id=client_id):
            payload = json.loads(ev[len('data: '):]) if ev.startswith('data: ') else {}
            if payload.get('error'):
                raise Refused(payload['error'])
            if payload.get('complete'):
                done = payload
    finally:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass
    if done.get('errors') or not (done.get('activity') or {}).get('id'):
        raise Refused('could not parse that recording', 500)
    act_id = str(done['activity']['id'])
    if done.get('imported'):                           # recorded on a phone, not a file imported on the web (the list's source filter)
        db.execute(r"UPDATE Activity SET source=? WHERE id=? AND source IS NULL AND id LIKE 'imp\_%' ESCAPE '\'",
                   [source if source in ('android', 'ios') else 'phone', act_id])
    elif client_id:                                    # this ride was here already (sent before clientId was kept, or from a file)
        remember(db, act_id, client_id)
    dup = done.get('duplicate')
    stands = (dup or {}).get('kept') or _standing(db, act_id)
    db.commit()
    extra = {'sport_guess': done['sport_guess']} if done.get('sport_guess') else {}
    return _reply(db, stands, bool(done.get('imported')), 'ride', dup, activity=dict(done['activity'], id=stands), **extra)


def _standing(db, act_id):
    """The live activity standing for this id: itself, or the one it was set aside behind."""
    if db.execute('SELECT 1 FROM Activity WHERE id=?', [act_id]).fetchone():
        return act_id
    d = db.execute("SELECT primaryId FROM ActivityDuplicate WHERE id=? AND status='parked'", [act_id]).fetchone()
    return d['primaryId'] if d else act_id


def _track(db, rider_id, client_id, source, data, sport, name, calories, steps):
    """Any other sport with a track (services/workouts.save_from_gpx)."""
    from services import workouts
    try:
        w, created = workouts.save_from_gpx(rider_id, data, sport=sport, name=(name or '')[:80] or None, client_id=client_id, steps=steps,
                                            source=source if source in ('android', 'ios') else 'android', calories=calories)
    except ValueError as e:
        raise Refused(str(e))
    if not created and client_id:                      # sent before clientId was kept: its id is the one its client_id gives
        remember(db, workouts.track_id(rider_id, client_id), client_id)
        db.commit()
    return _reply(db, w['id'], created, 'track', workout=w)


def _session(db, rider_id, client_id, source, sport, name, bike_id, s):
    """A session with no track (services/manual_activity.create): typed in, or timed on the phone or the Watch."""
    from services import manual_activity
    try:
        res = manual_activity.create(db, rider_id, sport, s.get('start'), s.get('duration_s'), s.get('distance_m'), s.get('elev_m'),
                                     s.get('calories'), name, s.get('notes'), client_id, source=source or 'manual', avg_hr=s.get('avg_hr'))
    except ValueError as e:
        raise Refused(str(e), 400)
    if res['created'] and res['kind'] == 'ride' and bike_id:     # an indoor ride on the bike chosen on the phone
        from services import gear
        gear.set_ride_bike(db, res['id'], bike_id)
    elif not res['created'] and client_id:
        remember(db, res['id'], client_id)
    db.commit()
    return _reply(db, _standing(db, res['id']), res['created'], 'session', res.get('duplicate'))
