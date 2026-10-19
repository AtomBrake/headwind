"""Walks, runs and hikes recorded by the phone app, and the other activities that are not rides. They are Activity rows like every other
activity; what is a ride is services/sports.is_ride. A workout is handed around as a dict with `sport` (Activity's sportType), see COLS.

A workout arrives as a GPX file (the app records the track); we reuse the GPX parser, store our own row, estimate calories when the
phone gave none, and stay idempotent: the same `client_id` (a UUID the app makes per recording) can be re-sent any number of times.
"""
import hashlib
import json
import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from database import get_db, query_db
from services import tz
from services.sports import ON_FOOT as SPORTS, RIDE_SQL

log = logging.getLogger(__name__)
# A workout as the phone API and the Workouts page have always seen it (before 0.7 it had a table of its own, with `sport` for sportType)
COLS = ('id, riderId, sportType AS sport, name, startDate, startDateLocal, distance, movingTime, elapsedTime, totalElevationGain, averageSpeed, maxSpeed, '
        'averageHeartrate, calories, steps, startLat, startLng, streams, weatherSummary, source, createdAt, caloriesRaw, originId')
_ICON = {'Walk': '🚶', 'Run': '🏃', 'Hike': '🥾', 'Swim': '🏊', 'Surf': '🏄', 'Paddle': '🛶', 'Row': '🚣', 'Ski': '⛷️', 'Skate': '⛸️', 'Golf': '⛳', 'Climb': '🧗'}
MI = 1609.344


def estimate_calories(sport, distance_m, moving_s, gain_m, kg):
    """Gross kcal from the ACSM walking / running equations (the same "gross" meaning as a watch's activity calories, i.e. it
    includes resting burn; day_burn subtracts that). Returns None when there isn't enough to go on."""
    if sport not in SPORTS or not (distance_m and moving_s and kg and moving_s > 60):     # the equations are for walking / running only (not a swim)
        return None
    minutes = moving_s / 60.0
    speed = distance_m / minutes                       # metres per minute
    grade = min(0.15, max(0.0, (gain_m or 0) / distance_m))
    if sport == 'Run' and speed >= 134:                # running equation from ~5 mph
        vo2 = 0.2 * speed + 0.9 * speed * grade + 3.5
    else:                                              # walking (also slow jogging / hiking)
        vo2 = 0.1 * speed + 1.8 * speed * grade + 3.5
    return round(vo2 * kg / 1000.0 * 5.0 * minutes)


def _local(iso):
    dt = datetime.fromisoformat(iso)
    if dt.tzinfo is None:
        return dt.strftime('%Y-%m-%dT%H:%M:%S'), iso
    return dt.astimezone(tz.zone()).strftime('%Y-%m-%dT%H:%M:%S'), dt.astimezone(ZoneInfo('UTC')).strftime('%Y-%m-%dT%H:%M:%SZ')


def save_from_gpx(rider_id, data, sport=None, name=None, client_id=None, steps=None, source='android'):
    """Parse a GPX recording and store it. Returns (workout dict, created: bool) or raises ValueError with a readable reason."""
    from services.parser import parse_gpx
    try:
        act = parse_gpx(data, stopped_speed=0.2, smooth_gain=True)     # on foot: a slow stroll is still moving, and phone GPS altitude is noisy
    except Exception as e:                             # not XML / not GPX / truncated upload
        raise ValueError(f'that is not a readable GPX file ({type(e).__name__})')
    if not act or not act.get('startDateLocal'):
        raise ValueError('could not read a timed track from that GPX file')
    sport = sport if sport in SPORTS else (act.get('sportType') if act.get('sportType') in SPORTS else 'Walk')
    local, utc = _local(act['startDateLocal'])
    key = client_id or f"{local}|{round(act.get('distance') or 0)}"
    wid = 'wk_' + hashlib.sha1(f'{rider_id}|{key}'.encode()).hexdigest()[:16]
    existing = _get(wid)
    if existing:                                       # sent again (or since changed to another sport: it is still that recording)
        return existing, False
    kept = _kept_instead(wid)
    if kept:                                           # set aside as a copy of another recording: a retried upload gets that one back
        return kept, False
    from services import goal_model
    kg = goal_model.current_weight_kg(rider_id) or 70.0
    dist, secs, gain = act.get('distance') or 0, int(act.get('movingTime') or 0), act.get('totalElevationGain') or 0
    from services.calorie_adjust import pair as _kcal_pair
    kcal_raw, kcal = _kcal_pair(estimate_calories(sport, dist, secs, gain, kg))     # global burn adjustment, applied as the figure is made
    weather = None
    if act.get('startLat') is not None:
        try:
            from services.weather import fetch_weather
            w = fetch_weather(act['startLat'], act['startLng'], local, act.get('streams'))
            weather = (w or {}).get('summary') or (w or {}).get('weatherSummary')
        except Exception:
            log.warning('Weather for a workout failed', exc_info=True)
    db = get_db()
    db.execute('''INSERT INTO Activity (id, riderId, type, sportType, name, startDate, startDateLocal, distance, movingTime, elapsedTime,
                                        totalElevationGain, averageSpeed, averageHeartrate, calories, steps, startLat, startLng,
                                        streams, weatherSummary, source, caloriesRaw, rawData)
                  VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'{}')''',
               [wid, rider_id, sport, sport, (name or '').strip() or None, utc, local, dist, secs, int(act.get('elapsedTime') or secs), gain,
                act.get('averageSpeed'), act.get('averageHeartrate'), kcal, steps, act.get('startLat'), act.get('startLng'),
                act.get('streams') if isinstance(act.get('streams'), str) else json.dumps(act.get('streams') or {}), weather, source, kcal_raw])
    refresh_derived(db, wid)
    from services import duplicates
    dup = duplicates.resolve(db, wid)                  # the same session from Garmin, Strava or a file: keep the better recording
    try:
        from services import sensors
        sensors.attach_for_ride(db, (dup or {}).get('kept', wid))
    except Exception:
        log.warning('Attaching sensor data to a workout failed', exc_info=True)
    db.commit()
    if dup and dup['parked'] == wid:
        return _kept_instead(wid), False
    return _get(wid), True


def _get(act_id):
    """One activity shaped like a workout (COLS), whatever its sport, or None."""
    row = query_db(f'SELECT {COLS} FROM Activity WHERE id=?', [act_id], one=True)
    return dict(row) if row else None


def _kept_instead(wid):
    """The activity a set-aside recording was a copy of, shaped like a workout (sport, ...), or None."""
    d = query_db("SELECT primaryId FROM ActivityDuplicate WHERE id=? AND status='parked'", [wid], one=True)
    return _get(d['primaryId']) if d else None


def label(w):
    """'Morning walk' style label for a workout without a name of its own."""
    hour = int(str(w.get('startDateLocal') or 'T12')[11:13] or 12)
    return (w.get('name') or '').strip() or f"{'Morning' if hour < 12 else 'Afternoon' if hour < 17 else 'Evening'} {w['sport'].lower()}"


def summary(w, rider_name):
    """(title, message) for the push notification when a workout is saved."""
    from services import units
    dist = units.fmt_dist(w.get('distance'))
    secs = int(w.get('movingTime') or 0)
    h, r = divmod(secs, 3600)
    dur = f"{h}h {r // 60:02d}m" if h else f"{r // 60}m"
    title = f"{_ICON.get(w['sport'], '🏃')} {rider_name}: {label(w)} · {dist}"
    line1 = f"{dist} · {dur}"
    if secs and w.get('distance'):
        line1 += f" · {units.fmt_pace(w['distance'] / secs)}"
    lines = [line1]
    extras = []
    if w.get('totalElevationGain'):
        extras.append(f"⛰ {units.fmt_elev(w['totalElevationGain'])}")
    if w.get('calories'):
        extras.append(f"🔥 {round(w['calories']):,} kcal")
    if w.get('steps'):
        extras.append(f"👣 {w['steps']:,} steps")
    if extras:
        lines.append(' · '.join(extras))
    if w.get('averageHeartrate'):
        lines.append(f"❤️ {round(w['averageHeartrate'])} bpm")
    if w.get('weatherSummary'):
        lines.append(f"☁️ {w['weatherSummary']}")
    return title, '\n'.join(lines)


def recent(rider_id, days=30):
    since = (tz.today() - timedelta(days=days)).isoformat()
    rows = query_db(f'''SELECT id, sportType AS sport, name, startDateLocal, distance, movingTime, totalElevationGain, calories, steps, weatherSummary, source
                        FROM Activity WHERE riderId=? AND NOT {RIDE_SQL} AND date(startDateLocal)>=? ORDER BY startDateLocal DESC''', [rider_id, since])
    return [dict(r) for r in rows]


def search(rider_id, q='', date_from='', date_to='', min_m=None, max_m=None, sport=''):
    """The complete workout history (no 90-day cut-off), newest first, with the same filters as the activity list on the dashboard (distances in metres)."""
    where, args = ['riderId=?', f'NOT {RIDE_SQL}'], [rider_id]
    if q:
        where.append("COALESCE(name, sportType) LIKE ?"); args.append(f'%{q}%')
    if date_from:
        where.append('date(startDateLocal) >= ?'); args.append(date_from)
    if date_to:
        where.append('date(startDateLocal) <= ?'); args.append(date_to)
    for val, op in ((min_m, '>='), (max_m, '<=')):
        if val is not None:
            where.append(f'distance {op} ?'); args.append(val)
    if sport:
        where.append('sportType = ?'); args.append(sport)
    return query_db(f'''SELECT id, sportType AS sport, name, startDateLocal, distance, movingTime, totalElevationGain, averageSpeed, calories, steps, weatherSummary, source
                        FROM Activity WHERE {' AND '.join(where)} ORDER BY startDateLocal DESC''', args)


def forget(db, wid):
    """A workout is going away: drop its best-time cache and any segment efforts, and re-pick each affected segment's PRs. Does not commit."""
    from services.segments import _refresh_prs
    seg_ids = [r[0] for r in db.execute('SELECT DISTINCT segmentId FROM SegmentEffort WHERE activityId=?', [wid]).fetchall()]
    db.execute('DELETE FROM SegmentEffort WHERE activityId=?', [wid])
    db.execute('DELETE FROM SportEffort WHERE activityId=?', [wid])
    db.execute('UPDATE RideSensor SET rideKind=NULL, rideId=NULL WHERE rideId=?', [wid])
    for sid in seg_ids:
        _refresh_prs(db, sid)


def delete(db, wid, rider_id):
    """Delete one of this rider's workouts with everything derived from it. One that came from Garmin is remembered (only its id), so the next sync
    does not bring it back. Returns True if it existed. Does not commit."""
    if not db.execute(f'SELECT 1 FROM Activity WHERE id=? AND riderId=? AND NOT {RIDE_SQL}', [wid, rider_id]).fetchone():
        return False
    forget(db, wid)
    db.execute('DELETE FROM Activity WHERE id=?', [wid])
    from flask import current_app
    from services import photos
    photos.delete_for(db, [wid], current_app.config['DATABASE'])
    if str(wid).startswith('garmin_'):
        from services import duplicates
        duplicates.tombstone(db, wid, rider_id)
    return True


def refresh_derived(db, wid):
    """(Re)build everything derived from one workout: best times (runs and swims) and foot-segment efforts (walks, runs and hikes). Safe to call
    after any change. Does not commit."""
    from services import sport_records
    from services.segments import scan_activity_against_segments, _refresh_prs
    from services.sports import segment_family
    forget(db, wid)
    w = db.execute('SELECT id, sportType AS sport, startDateLocal, streams FROM Activity WHERE id=?', [wid]).fetchone()
    if not w or not w['streams']:
        return
    sport_records.index(db, wid, w['startDateLocal'], w['sport'], w['streams'])
    if segment_family(w['sport']) != 'foot':
        return
    try:
        segs = db.execute("SELECT * FROM Segment WHERE sport='foot'").fetchall()
        if segs and scan_activity_against_segments(db, {'id': wid, 'startDateLocal': w['startDateLocal'], 'streams': w['streams'], 'sportType': w['sport']}, segs):
            for s in segs:
                _refresh_prs(db, s['id'])
    except Exception:
        log.warning('Segment scan of a run failed: its segment efforts are missing', exc_info=True)
