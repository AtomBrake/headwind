import logging
import json
import re
from flask import Blueprint, abort, current_app, redirect, render_template, request, send_from_directory, url_for
from database import query_db, get_db
from services import sports
from routes.riders import _compute_badges
from services.ai import PERSONALITIES

log = logging.getLogger(__name__)

bp = Blueprint('rides', __name__)

_MW_KEYS = {
    'Weather Impact™': 'impact',
    'Headwind':         'headwind',
    'Longest Headwind': 'longest_headwind',
    'Air Speed':        'air_speed',
    'Temp':             'temp',
    'Precip':           'precip',
}

def _to_speed(text):
    """myWindsock writes speeds in m/s or km/h: show them in the rider's units."""
    from services import units
    text = re.sub(r'(\d+\.?\d*)\s*m/s',  lambda m: units.fmt_speed(float(m.group(1))), text)
    text = re.sub(r'(\d+\.?\d*)\s*km/h', lambda m: units.fmt_speed(float(m.group(1)) / 3.6), text)
    return text

def _parse_mywindsock(description):
    if not description or '-- myWindsock Report --' not in description:
        return None
    data = {}
    in_block = False
    for line in description.replace('\r\n', '\n').replace('\r', '\n').split('\n'):
        line = line.strip()
        if line == '-- myWindsock Report --':
            in_block = True
            continue
        if line == '-- END --':
            break
        if in_block and ':' in line:
            raw_key, _, value = line.partition(':')
            key = _MW_KEYS.get(raw_key.strip())
            if key:
                value = value.strip()
                if key in ('headwind', 'air_speed'):
                    value = _to_speed(value)
                data[key] = value
    return data or None

_SAMPLE = 300  # max chart points


def _sample(data, n=_SAMPLE):
    if not data:
        return []
    step = max(1, len(data) // n)
    return data[::step]


def _stream_series(streams, key, dist_key='distance', transform=None):
    from services import units
    raw  = (streams.get(key) or {}).get('data') or []
    dist = (streams.get(dist_key) or {}).get('data') or []
    if not raw:
        return None
    step = max(1, len(raw) // _SAMPLE)
    values = []
    labels = []
    for i in range(0, len(raw), step):
        v = raw[i]
        values.append(round(transform(v) if transform else v, 2))
        labels.append(round(units.dist(dist[i]), 2) if i < len(dist) else i)      # distance along the ride, in the rider's unit
    return {'values': values, 'labels': labels}


@bp.route('/<rid>')
def detail(rid):
    activity = query_db('''
        SELECT a.*, r.name AS riderName, r.avatarPath AS riderAvatar, r.isDefault AS riderIsDefault
        FROM Activity a
        LEFT JOIN Rider r ON r.id = a.riderId
        WHERE a.id=?
    ''', [rid], one=True)
    if not activity:
        abort(404)
    is_ride = sports.is_ride(activity['sportType'])
    is_workout = not is_ride                          # walks, runs, swims, ...: the same page, without what only a ride has
    if is_workout:
        activity = dict(activity, name=activity['name'] or activity['sportType'])

    streams = {}
    if activity['streams']:
        try:
            streams = json.loads(activity['streams'])
        except Exception:
            log.warning('Activity streams are not valid JSON', exc_info=True)

    # Prefer the raw latlng GPS stream — it's the same source the segment
    # matching algorithm uses, so segment snap coordinates are always consistent.
    # Fall back to the summary polyline for older activities without a stream.
    coords = (streams.get('latlng') or {}).get('data') or []
    if not coords and activity['summaryPolyline']:
        try:
            import polyline as pl
            coords = pl.decode(activity['summaryPolyline'])
        except Exception:
            log.warning('Activity summary polyline would not decode', exc_info=True)

    from services import units, activity_detail
    detail = activity_detail.for_activity(activity, streams)      # splits, pool lengths, ski runs, laps: what fits the sport
    view = detail['view']
    by_pace = view in ('foot', 'swim')                            # pace (faster at the top), not speed
    charts = {
        'elevation': _stream_series(streams, 'altitude', transform=lambda v: round(units.elev(v))) if sports.has_climbing(activity['sportType']) else None,
        'heartrate': _stream_series(streams, 'heartrate'),
        'power':     _stream_series(streams, 'watts'),
        'speed':     None if by_pace else _stream_series(streams, 'velocity_smooth', transform=lambda v: round(units.speed(v), 1)),
        'pace':      detail['pace'] if by_pace else None,
        'cadence':   _stream_series(streams, 'cadence', transform=(lambda v: v * 2) if view == 'foot' else None),   # a watch counts one foot: steps a minute are twice it
    }
    if not by_pace and not charts['speed']:
        charts['speed'] = activity_detail.speed_series(streams)     # no speed stream (a GPX): from the distance and time

    memory_count = get_db().execute(
        'SELECT COUNT(*) FROM RideMemory WHERE rideId != ?', [rid]
    ).fetchone()[0]

    # Other riders who rode on the same calendar day
    co_riders = query_db('''
        SELECT DISTINCT r.id, r.name, r.avatarPath
        FROM Ride a
        JOIN Rider r ON r.id = a.riderId
        WHERE date(a.startDateLocal) = date(?)
          AND a.riderId != ?
          AND a.riderId IS NOT NULL
    ''', [activity['startDateLocal'], activity['riderId'] or -1])

    seg_efforts = query_db('''
        SELECT e.*, s.name AS seg_name, s.id AS seg_id, s.distanceM
        FROM SegmentEffort e
        JOIN Segment s ON s.id = e.segmentId
        WHERE e.activityId = ?
        ORDER BY e.elapsedSecs ASC
    ''', [rid])

    # For each segment on this ride, get other riders' efforts on the SAME DAY
    seg_rivals = {}
    if seg_efforts:
        seg_ids = [e['seg_id'] for e in seg_efforts]
        placeholders = ','.join('?' * len(seg_ids))
        rivals = query_db(f'''
            SELECT e.segmentId, e.elapsedSecs, e.avgSpeedMps, e.isPR,
                   r.name AS rider_name, r.avatarPath AS rider_avatar, r.id AS rider_id
            FROM SegmentEffort e
            JOIN Activity a ON a.id = e.activityId
            JOIN Rider r ON r.id = a.riderId
            WHERE e.segmentId IN ({placeholders})
              AND date(a.startDateLocal) = date(?)
              AND a.riderId != ?
              AND a.riderId IS NOT NULL
        ''', seg_ids + [activity['startDateLocal'], activity['riderId'] or -1])
        for r in rivals:
            seg_rivals.setdefault(r['segmentId'], []).append(r)

    seg_trends = {}
    seg_class = sports.class_of(get_db(), activity['id'])      # bike / ebike / foot: an e-bike ride is compared with the last e-bike effort, and so on
    same_class = sports.class_sql(seg_class, 'a2.sportType', 'b2.kind')
    for e in seg_efforts:
        prev = query_db(f'''
            SELECT e2.elapsedSecs FROM SegmentEffort e2
            JOIN Activity a2 ON a2.id = e2.activityId
            LEFT JOIN Bike b2 ON b2.id = a2.bikeId
            WHERE e2.segmentId=? AND a2.riderId IS ? AND a2.startDateLocal < ? AND e2.activityId != ? AND {same_class}
            ORDER BY a2.startDateLocal DESC LIMIT 1
        ''', [e['seg_id'], activity['riderId'], activity['startDateLocal'], rid], one=True)
        if prev:
            delta = e['elapsedSecs'] - prev['elapsedSecs']
            seg_trends[e['seg_id']] = {'dir': 'up' if delta < 0 else ('down' if delta > 0 else 'flat'), 'delta': abs(delta)}

    # Trends for rival riders: compare each rival's today time vs their previous effort
    rival_trends = {}  # {rider_id: {seg_id: {dir, delta}}}
    for seg_id, rivals_list in seg_rivals.items():
        for rival in rivals_list:
            prev = query_db('''
                SELECT e2.elapsedSecs FROM SegmentEffort e2
                JOIN Activity a2 ON a2.id = e2.activityId
                WHERE e2.segmentId=? AND a2.riderId=? AND a2.startDateLocal < ?
                ORDER BY a2.startDateLocal DESC LIMIT 1
            ''', [seg_id, rival['rider_id'], activity['startDateLocal']], one=True)
            if prev:
                delta = rival['elapsedSecs'] - prev['elapsedSecs']
                rival_trends.setdefault(rival['rider_id'], {})[seg_id] = {
                    'dir': 'up' if delta < 0 else ('down' if delta > 0 else 'flat'),
                    'delta': abs(delta),
                }

    # Prev / Next: the rider's rides from a ride, the same sport from anything else (the run before this one)
    same = ('Ride', '1=1', []) if is_ride else ('Activity', 'sportType IS ?', [activity['sportType']])
    prev_ride = query_db(f'''
        SELECT id, name FROM {same[0]}
        WHERE startDateLocal < ? AND riderId IS ? AND {same[1]}
        ORDER BY startDateLocal DESC LIMIT 1
    ''', [activity['startDateLocal'], activity['riderId']] + same[2], one=True)

    next_ride = query_db(f'''
        SELECT id, name FROM {same[0]}
        WHERE startDateLocal > ? AND riderId IS ? AND {same[1]}
        ORDER BY startDateLocal ASC LIMIT 1
    ''', [activity['startDateLocal'], activity['riderId']] + same[2], one=True)

    alt_raw = (streams.get('altitude') or {}).get('data') or []

    elev_loss_m = 0
    for i in range(1, len(alt_raw)):
        d = alt_raw[i] - alt_raw[i - 1]
        if d < 0:
            elev_loss_m += -d

    sport = (activity['sportType'] or '').lower()
    from services import weather as _wx
    seg_family = sports.family_of(get_db(), activity['id'])     # ride / foot, or None: no segments (an indoor ride, a swim, ...)

    # Badges earned on this specific ride
    ride_badges = []
    if activity['riderId']:
        rtotals = query_db(
            'SELECT COUNT(*) as rides, SUM(distance) as dist, SUM(totalElevationGain) as elev '
            'FROM Ride WHERE riderId=?', [activity['riderId']], one=True)
        if rtotals:
            for cat in _compute_badges(activity['riderId'], rtotals):
                for b in cat['badges']:
                    if b.get('ride_id') and str(b['ride_id']) == str(rid):
                        ride_badges.append(b)

    from services import duplicates, gear as gear_svc
    gear_bikes = gear_svc.list_bikes(get_db(), activity['riderId']) if activity['riderId'] and is_ride else []
    from services import kit as kit_svc
    kit_items = kit_svc.choices_for(get_db(), activity) if not is_ride else []      # a run's shoes, a swim's wetsuit, ...
    dups = []
    for d in duplicates.parked_for(get_db(), rid):
        try:
            r = json.loads(d['rowJson'])
        except ValueError:
            continue
        dups.append({'id': d['id'], 'source': d['source'], 'reason': d['reason'], 'start': r.get('startDateLocal'), 'distance': r.get('distance'),
                     'moving': r.get('movingTime'), 'hr': r.get('averageHeartrate'), 'watts': r.get('averageWatts')})

    from services import sensors as _sensors
    phone_sensors = _sensors.for_ride(get_db(), str(activity['id']))
    from services import origin
    source_links = origin.links(get_db(), activity['id'], activity['originId'])
    from services import photos as _photos
    from services import garmin_changes
    from services import auto_analyse as _auto_analyse
    avg_mps = activity['averageSpeed'] or ((activity['distance'] or 0) / activity['movingTime'] if activity['movingTime'] else None)   # a phone walk stores none
    try:                                                # a Strava export's climb taken in place of the file's impossible one (import_rides._strava_climb_if_impossible)
        raw = json.loads(activity['rawData'] or '{}')
        file_climb = raw.get('fileClimb') if raw.get('fileClimb') is not None and activity['totalElevationGain'] == raw.get('stravaClimb') else None
    except (ValueError, TypeError, AttributeError):
        file_climb = None
    return render_template('ride.html', kit_items=kit_items, detail=detail, view=view, avg_mps=avg_mps, has_climbing=sports.has_climbing(activity['sportType']), source_links=source_links, photos=_photos.for_activity(get_db(), activity['id']), phone_sensors=phone_sensors, activity=activity, coords=coords, dups=dups, gear_bikes=gear_bikes, gear_error=request.args.get('error'), sports=list(sports.SPORTS),
                           file_climb=file_climb, garmin_change=garmin_changes.for_ride(get_db(), activity['id']),
                           charts=charts, has_memory=memory_count > 0, ai_pending=_auto_analyse.is_pending(activity['id']),
                           seg_efforts=seg_efforts, alt_raw=alt_raw,
                           co_riders=co_riders, seg_rivals=seg_rivals,
                           seg_trends=seg_trends, rival_trends=rival_trends,
                           elev_loss_m=elev_loss_m,
                           prev_ride=prev_ride, next_ride=next_ride,
                           is_ride=is_ride, seg_family=seg_family, seg_family_label=(sports.CLASS_LABELS['ebike'] if seg_class == 'ebike' else sports.FAMILY_LABELS.get(seg_family)), is_workout=is_workout,
                           wx_categories=list(_wx.CATEGORIES), wx_condition=_wx.bucket(activity['weatherCode'] if not is_workout else None),
                           wx_manual=(not is_workout and activity['weatherSource'] == 'manual'), wx_storm=(not is_workout and activity['weatherSource'] == 'storm'),
                           ride_badges=ride_badges,
                           personalities=PERSONALITIES,
                           current_personality=query_db('SELECT coachPersonality FROM Settings WHERE id=1', one=True) or {},
                           mywindsock=_parse_mywindsock(activity['description']))


@bp.route('/<rid>/scan', methods=['POST'])
def scan_segments(rid):
    from services.segments import scan_activity_against_segments, _refresh_prs
    db = get_db()
    activity = db.execute('SELECT id, startDateLocal, streams, sportType FROM Activity WHERE id=?', [rid]).fetchone()
    if not activity:
        return ('Not found', 404)
    segments = db.execute('SELECT * FROM Segment').fetchall()
    if not segments:
        return ('{"matched":0}', 200, {'Content-Type': 'application/json'})
    matched = scan_activity_against_segments(db, activity, segments)
    for seg in segments:
        _refresh_prs(db, seg['id'])
    db.commit()
    from flask import jsonify
    return jsonify(matched=matched)


@bp.route('/<rid>/weather', methods=['POST'])
def set_weather(rid):
    """Set a ride's weather condition by hand (Clear / Cloudy / Fog / Rain / Snow / Storm), or 'auto' to hand it back to the automatic lookup."""
    from services import weather
    from flask import jsonify
    label = (request.form.get('condition') or (request.get_json(silent=True) or {}).get('condition') or '').strip()
    if label not in ('auto', 'keep', 'notstorm') and label not in weather.CATEGORIES:
        return jsonify(error='unknown condition'), 400
    db = get_db()
    if not db.execute('SELECT 1 FROM Activity WHERE id=?', [rid]).fetchone():
        return jsonify(error='not found'), 404
    if label == 'notstorm':           # it was not a storm ride after all: back to the lookup's own condition, and never claimed again
        weather.set_condition(db, rid, None)
        row = db.execute('SELECT startLat, startLng, startDateLocal, streams FROM Activity WHERE id=?', [rid]).fetchone()
        lat, lng = weather.origin(row)
        w = weather.fetch_weather(lat, lng, row['startDateLocal'], row['streams']) if lat is not None else None
        if w:
            weather.save_weather(db, rid, w, claim=False)
        weather.set_condition(db, rid, 'keep')
    elif label == 'keep':
        weather.set_condition(db, rid, 'keep')
    elif label == 'auto':
        weather.set_condition(db, rid, None)
        row = db.execute('SELECT startLat, startLng, startDateLocal, streams FROM Activity WHERE id=?', [rid]).fetchone()
        lat, lng = weather.origin(row)
        w = weather.fetch_weather(lat, lng, row['startDateLocal'], row['streams']) if lat is not None else None
        if w:
            weather.save_weather(db, rid, w, claim=False)
        elif db.execute('SELECT weatherTempC FROM Activity WHERE id=?', [rid]).fetchone()[0] is None:      # nothing automatic to fall back on: forget the hand-picked word
            db.execute('UPDATE Activity SET weatherCode=NULL, weatherSummary=NULL WHERE id=?', [rid])
    else:
        weather.set_condition(db, rid, label)
    db.commit()
    row = db.execute('SELECT weatherCode, weatherSummary, weatherSource FROM Activity WHERE id=?', [rid]).fetchone()
    return jsonify(ok=True, condition=weather.bucket(row['weatherCode']), summary=row['weatherSummary'], manual=row['weatherSource'] == 'manual')


@bp.route('/<rid>/flag/dismiss', methods=['POST'])
def dismiss_flag(rid):
    """The rider says a flagged ride is right after all: clear the flag for good (it is counted in the analytics again)."""
    from services import sanity
    db = get_db()
    if not db.execute('SELECT 1 FROM Activity WHERE id=?', [rid]).fetchone():
        return ('Not found', 404)
    sanity.dismiss(db, rid)
    db.commit()
    return ('', 204)


@bp.route('/<rid>/climb/strava', methods=['POST'])
def use_strava_climb(rid):
    """A flagged ride from a Strava export takes Strava's climb in place of the file's (services/sanity.use_strava_climb)."""
    from flask import jsonify
    from services import sanity
    db = get_db()
    if not sanity.use_strava_climb(db, rid):
        return ('No climb from Strava for this ride', 404)
    db.commit()
    row = db.execute('SELECT flagReason FROM Activity WHERE id=?', [rid]).fetchone()
    return jsonify(ok=True, flagged=bool(row and row['flagReason']))


@bp.route('/<rid>/notes', methods=['POST'])
def save_notes(rid):
    notes = (request.form.get('notes') or '').strip() or None
    db = get_db()
    db.execute('UPDATE Activity SET notes=? WHERE id=?', [notes, rid])
    db.commit()
    return ('', 204)


@bp.route('/<rid>/commute', methods=['POST'])
def set_commute(rid):
    """Tick or untick 'Commute'. Unticking stores 0, not NULL, so importing a Strava export again doesn't tick it back."""
    db = get_db()
    n = db.execute('UPDATE Activity SET commute=? WHERE id=?', [1 if request.form.get('commute') == '1' else 0, rid]).rowcount
    db.commit()
    return ('', 204) if n else abort(404)


@bp.route('/photo/<name>')
def photo(name):
    from services import photos
    if not photos.valid_name(name):
        abort(404)
    return send_from_directory(photos.photo_dir(current_app.config['DATABASE']), name, max_age=86400)


@bp.route('/<rid>/photos', methods=['POST'])
def add_photos(rid):
    """Pictures picked on the activity page (field 'photos', up to photos.MAX_UPLOAD at once), each through photos.save. One that can't be read is
    named in the message and the rest are still added."""
    from flask import flash
    from services import photos
    db = get_db()
    if not db.execute('SELECT 1 FROM Activity WHERE id=?', [rid]).fetchone():
        abort(404)
    files = [f for f in request.files.getlist('photos') if f and f.filename][:photos.MAX_UPLOAD]
    pos, added, failed = photos.next_position(db, rid), 0, []
    for f in files:
        try:
            photos.save(db, rid, f.read(photos.MAX_BYTES + 1), current_app.config['DATABASE'], position=pos + added)
            added += 1
        except ValueError as e:
            heic = f.filename.lower().endswith(('.heic', '.heif'))
            failed.append(f"{f.filename}: {'HEIC pictures cannot be read yet; save it as a JPEG first' if heic else e}")
    db.commit()
    if added:
        flash(f"Added {added} photo{'' if added == 1 else 's'}.", 'success')
    if failed:
        flash('Not added: ' + '; '.join(failed) + '.', 'error')
    return redirect(url_for('rides.detail', rid=rid) + '#photosCard')


@bp.route('/<rid>/photos/<int:pid>/delete', methods=['POST'])
def delete_photo(rid, pid):
    from services import photos
    db = get_db()
    photos.delete(db, pid, rid, current_app.config['DATABASE'])
    db.commit()
    return redirect(url_for('rides.detail', rid=rid) + '#photosCard')


def gpx_for(activity):
    """(filename, GPX text) for a ride with a GPS track, or None. Point times are real UTC: the stored UTC start (startDate) when there is one,
    else the local start converted (stamping the local time with a 'Z' put every summer ride an hour out, and a re-import beside its original)."""
    from datetime import timedelta, timezone
    from services.duplicates import instant
    streams = {}
    if activity['streams']:
        try:
            streams = json.loads(activity['streams'])
        except Exception:
            log.warning('Activity streams are not valid JSON', exc_info=True)
    latlng     = (streams.get('latlng')    or {}).get('data') or []
    altitude   = (streams.get('altitude')  or {}).get('data') or []
    time_data  = (streams.get('time')      or {}).get('data') or []
    if not latlng:
        return None
    start_utc = activity['startDate'] if activity['startDate'] and str(activity['startDate']) != str(activity['startDateLocal']) else None
    start_dt = (instant(start_utc + ('' if 'Z' in str(start_utc) or '+' in str(start_utc)[10:] else 'Z')) if start_utc
                else instant(activity['startDateLocal']))
    if start_dt is None:
        from datetime import datetime
        start_dt = datetime.now(timezone.utc)
    start_dt = start_dt.astimezone(timezone.utc).replace(tzinfo=None)

    name_escaped = (activity['name'] or 'Ride').replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')

    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<gpx version="1.1" creator="Headwind" xmlns="http://www.topografix.com/GPX/1/1">',
        '  <trk>',
        f'    <name>{name_escaped}</name>',
        '    <trkseg>',
    ]

    for i, (lat, lng) in enumerate(latlng):
        ele = altitude[i]  if i < len(altitude)  else None
        t   = time_data[i] if i < len(time_data) else None
        lines.append(f'      <trkpt lat="{lat}" lon="{lng}">')
        if ele is not None:
            lines.append(f'        <ele>{ele:.1f}</ele>')
        if t is not None:
            lines.append(f'        <time>{(start_dt + timedelta(seconds=t)).strftime("%Y-%m-%dT%H:%M:%SZ")}</time>')
        lines.append('      </trkpt>')

    lines += ['    </trkseg>', '  </trk>', '</gpx>']

    safe = re.sub(r'[^\w\s-]', '', activity['name'] or 'ride').strip().replace(' ', '_')
    filename = f"{str(activity['startDateLocal'])[:10]}_{safe}.gpx"

    return filename, '\n'.join(lines)


@bp.route('/<rid>/gpx')
def export_gpx(rid):
    from flask import Response
    activity = query_db('SELECT * FROM Activity WHERE id=?', [rid], one=True)
    out = gpx_for(activity) if activity else None
    if not out:
        abort(404)
    filename, text = out
    return Response(text, mimetype='application/gpx+xml', headers={'Content-Disposition': f'attachment; filename="{filename}"'})


@bp.route('/<rid>/delete', methods=['POST'])
def delete(rid):
    from services import duplicates
    db = get_db()
    duplicates.delete_activity(db, rid)
    db.execute('DELETE FROM RideMemory WHERE rideId=?', [rid])
    db.commit()
    from services.ingest import after_ride_removed
    after_ride_removed()
    return redirect(url_for('dashboard.dashboard'))


def _bulk_ids():
    ids = request.form.getlist('id') or [i for i in (request.form.get('ids') or '').split(',') if i]
    return [i.strip() for i in ids if i.strip()]


def _safe_back(default='/dashboard'):
    back = request.form.get('back') or default
    return back if back.startswith('/') and not back.startswith('//') else default


@bp.route('/bulk', methods=['POST'])
def bulk():
    """An action on activities picked on a list (services/bulk.py). Reports what happened with a flash message and goes back to the list."""
    from flask import flash
    from services import bulk as _bulk
    action = request.form.get('action')
    ids = _bulk_ids()
    back = _safe_back()
    if not ids:
        return redirect(back)
    to_int = lambda v: int(v) if (v or '').isdigit() else None
    db = get_db()
    try:
        res = _bulk.apply(db, action, ids, sport=request.form.get('sport'), bike_id=to_int(request.form.get('bike')),
                          rider_id=to_int(request.form.get('rider')), name=request.form.get('name'),
                          commute=request.form.get('commute'), kit_id=to_int(request.form.get('kit')))
    except ValueError as e:
        db.rollback()
        flash(str(e), 'error')
        return redirect(back)
    db.commit()
    try:                                                # once for the whole batch, not per activity
        from services.mqtt import push_update, push_update_nutrition
        if 'ride' in res['kinds'] or action == 'delete':
            push_update(background=True)
        if 'workout' in res['kinds']:
            push_update_nutrition()
    except Exception:
        log.warning('Home Assistant update after a bulk edit failed', exc_info=True)
    verb = {'delete': 'Deleted', 'sport': 'Changed the type of', 'bike': 'Set the bike on', 'kit': 'Set the gear on', 'rider': 'Moved',
            'rename': 'Renamed', 'dismiss': 'Cleared the flag on', 'commute': 'Marked'}[action]
    n = res['done']
    msg = f"{verb} {n} activit{'y' if n == 1 else 'ies'}"
    if action == 'commute':
        msg += ' as a commute' if request.form.get('commute') == '1' else ' as not a commute'
    msg += '.'
    if res['skipped']:
        msg += f" {res['skipped']} could not be changed" + {'bike': ' (only rides have a bike)', 'dismiss': ' (only rides have a flag)',
                                                          'kit': ' (rides have a bike, not shoes)'}.get(action, '') + '.'
    flash(msg, 'success')
    return redirect(back)


@bp.route('/bulk/options')
def bulk_options():
    """What the selection bar's pickers offer: this instance's riders, and each one's bikes and kit."""
    from flask import jsonify
    from services import bulk as _bulk, convert, gear, kit
    db = get_db()
    riders = [dict(r) for r in _bulk.own_riders(db)]
    for r in riders:
        r['bikes'] = [{'id': b['id'], 'name': b['name']} for b in gear.list_bikes(db, r['id'])]
        r['kit'] = [{'id': k['id'], 'name': k['name']} for k in kit.list_kit(db, r['id'])]
    return jsonify({'riders': riders, 'sports': [{'value': s, 'label': sports.label(s)} for s in convert.SPORTS]})


@bp.route('/bulk/download', methods=['POST'])
def bulk_download():
    """The picked rides that have a GPS track, as one zip of GPX files."""
    import io
    import zipfile
    from flask import Response
    ids = _bulk_ids()[:5000]
    buf, names = io.BytesIO(), set()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as z:
        for act_id in ids:
            a = query_db('SELECT * FROM Activity WHERE id=?', [act_id], one=True)
            out = gpx_for(a) if a else None
            if not out:
                continue
            fname, text = out
            stem, n = fname[:-4], 2
            while fname in names:                       # two rides on one day with the same name
                fname, n = f'{stem}_{n}.gpx', n + 1
            names.add(fname)
            z.writestr(fname, text)
    if not names:
        from flask import flash
        flash('None of those have a GPS track to download.', 'error')
        return redirect(_safe_back())
    return Response(buf.getvalue(), mimetype='application/zip', headers={'Content-Disposition': 'attachment; filename="headwind-activities.zip"'})


@bp.route('/flagged/delete-blips', methods=['POST'])
def delete_blips():
    """Delete every flagged ride shorter than the sanity limit (an accidental start-stop) for one rider, each through the normal delete."""
    from services import duplicates, sanity
    from services.ingest import after_ride_removed
    db = get_db()
    rider = request.form.get('rider')
    rid = int(rider) if rider and rider.isdigit() else (query_db('SELECT id FROM Rider WHERE isDefault=1', one=True) or {'id': -1})['id']
    for act_id in sanity.blip_ids(db, rid):
        duplicates.delete_activity(db, act_id)
    db.commit()
    after_ride_removed()
    return redirect(url_for('dashboard.dashboard', rider=rider) if rider and rider.isdigit() else url_for('dashboard.dashboard'))


@bp.route('/<rid>/sport', methods=['POST'])
def change_sport(rid):
    """Change what this activity is (e.g. a walk that was recorded as a ride). A walk/run/hike leaves the rides list and appears under Workouts."""
    from services import convert
    db = get_db()
    try:
        res = convert.change_sport(db, 'ride', rid, request.form.get('sport'))
        db.commit()
    except ValueError as e:
        db.rollback()
        from urllib.parse import quote
        return redirect(url_for('rides.detail', rid=rid) + '?error=' + quote(str(e)))
    return redirect(url_for('workouts_ui.workouts_page') if res['kind'] == 'workout' else url_for('rides.detail', rid=res['id']))


@bp.route('/bulk-sport', methods=['POST'])
def bulk_sport():
    """Change the type of many activities at once (the results of a dashboard search): ids are comma-separated in `ids`. A walk/run/hike moves to Workouts,
    a ride moves back. Each one is converted by the same code as the single-activity dropdown; one that cannot be changed is skipped and counted."""
    from services import convert
    from urllib.parse import quote
    sport = request.form.get('sport')
    ids = [i for i in (request.form.get('ids') or '').split(',') if i][:5000]
    back = request.form.get('back') or '/dashboard'
    if not back.startswith('/') or back.startswith('//'):
        back = '/dashboard'
    if sport not in convert.SPORTS or not ids:
        return redirect(back)
    db = get_db()
    changed = skipped = 0
    for i in ids:
        try:
            res = convert.change_sport(db, None, i, sport)
            changed += 1 if res.get('changed') else 0
        except ValueError:
            skipped += 1
    db.commit()
    try:
        from services.mqtt import push_update, push_update_nutrition
        push_update(background=True); push_update_nutrition()
    except Exception:
        log.warning('Home Assistant update after a bulk change failed', exc_info=True)
    sep = '&' if '?' in back else '?'
    return redirect(back + sep + 'typed=' + quote(f'{changed}|{skipped}|{sport}'))


_DUP_SERIES = (('heartrate', 'Heart rate', 'bpm'), ('watts', 'Power', 'W'), ('cadence', 'Cadence', 'rpm'),
               ('velocity_smooth', 'Speed', None), ('altitude', 'Elevation', None))


def _recording(row, label, t0):
    """One recording (a live ride or a set-aside one) for the duplicate view: its numbers, GPS track and streams against minutes since `t0`."""
    from services import units
    from services.duplicates import start_instant, source_label
    row = dict(row)
    try:
        streams = json.loads(row.get('streams') or '{}') or {}
    except (ValueError, TypeError):
        streams = {}
    coords = (streams.get('latlng') or {}).get('data') or []
    if not coords and row.get('summaryPolyline'):
        try:
            import polyline as pl
            coords = pl.decode(row['summaryPolyline'])
        except Exception:
            log.warning('Activity summary polyline would not decode', exc_info=True)
    start = start_instant(row)
    offset = (start - t0).total_seconds() if start and t0 else 0
    times = (streams.get('time') or {}).get('data') or []
    conv = {'velocity_smooth': lambda v: units.speed(v), 'altitude': lambda v: units.elev(v)}
    series = {}
    for key, _, _ in _DUP_SERIES:
        raw = (streams.get(key) or {}).get('data') or []
        if not raw:
            continue
        step = max(1, len(raw) // _SAMPLE)
        series[key] = [{'x': round(((times[i] if i < len(times) else i) + offset) / 60, 2),
                        'y': round(conv[key](raw[i]), 1) if key in conv and raw[i] is not None else raw[i]} for i in range(0, len(raw), step)]
    return {'label': label, 'source': source_label(row), 'row': row, 'start': start, 'offset': offset, 'gps_points': len(coords),
            'coords': _sample(coords, 1500), 'series': series, 'streams': sorted(k for k in streams if k not in ('latlng',))}


@bp.route('/<rid>/duplicate')
@bp.route('/<rid>/duplicate/<dup_id>')
def view_duplicate(rid, dup_id=None):
    """A recording set aside as a duplicate of this ride: on its own, or (?compare=1) side by side with the one that was kept."""
    from services import duplicates
    from services.duplicates import start_instant
    db = get_db()
    parked = duplicates.parked_for(db, rid)
    d = next((p for p in parked if dup_id is None or str(p['id']) == str(dup_id)), None)
    main = db.execute('SELECT * FROM Activity WHERE id=?', [rid]).fetchone()
    if not d or not main:
        abort(404)
    other = json.loads(d['rowJson'] or '{}')
    compare = request.args.get('compare') == '1'
    starts = [s for s in (start_instant(r) for r in (dict(main), other)) if s]
    t0 = min(starts) if starts else None
    recs = [_recording(other, 'Set aside', t0)]
    if compare:
        recs.insert(0, _recording(main, 'Kept', t0))
    return render_template('ride_duplicate.html', activity=main, dup=d, others=[p['id'] for p in parked], recs=recs, compare=compare,
                           colours=['#fc4c02', '#3b82f6'][-len(recs):], series_meta=_DUP_SERIES)


@bp.route('/<rid>/duplicate/<dup_id>/<action>', methods=['POST'])
def resolve_duplicate(rid, dup_id, action):
    """The same ride recorded twice: use the other recording, keep both as separate rides, or discard the other one."""
    from services import duplicates
    db = get_db()
    d = db.execute("SELECT primaryId FROM ActivityDuplicate WHERE id=? AND status='parked'", [dup_id]).fetchone()
    if not d or str(d['primaryId']) != str(rid):
        abort(404)
    new_main = rid
    if action == 'swap':
        new_main = duplicates.swap(db, dup_id) or rid
    elif action == 'keep':
        duplicates.keep_both(db, dup_id)
    elif action == 'discard':
        duplicates.discard(db, dup_id)
    else:
        abort(400)
    db.commit()
    return redirect(url_for('rides.detail', rid=new_main))
