import logging
import hashlib
import io
import json
import re
from math import atan2, cos, radians, sin, sqrt

log = logging.getLogger(__name__)


def _utc_iso(dt):
    """A start time as an ISO string that says it is UTC. FIT timestamps are always UTC and GPX times are UTC by the spec, but fitparse (and gpxpy for
    a time without a 'Z') hand them back with no timezone, which the importer would then take for UK local time: an hour early all summer."""
    from datetime import timezone
    return (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).isoformat()


def _stable_id(start_dt, distance_m):
    key = f"{start_dt.isoformat()}:{int(distance_m)}"
    return 'imp_' + hashlib.sha1(key.encode()).hexdigest()[:14]


def estimate_ride_calories(distance_m, moving_s, weight_kg):
    """Fallback for a GPX ride with no device-recorded calories (e.g. a phone recording — GPX has no calorie
    field at all, unlike FIT). Compendium-of-Physical-Activities MET bands by average speed — same table as
    the Android app's live in-ride estimate (Live.kt Calories.rideKcal), kept identical so a ride shows the
    same number while recording and after it lands on the server. Not gradient-aware (a hilly ride burns more
    than a flat one at the same average speed) — good enough as a fallback, real device data is always used
    when a source (Garmin/FIT/a Strava export) actually provides it."""
    if not weight_kg or weight_kg <= 0 or not distance_m or not moving_s or moving_s <= 0:
        return None
    minutes = moving_s / 60.0
    kmh = (distance_m / 1000.0) / (moving_s / 3600.0)
    met = 4.0 if kmh < 16 else 6.8 if kmh < 19 else 8.0 if kmh < 22 else 10.0 if kmh < 26 else 12.0 if kmh < 30 else 15.8
    return round(met * 3.5 * weight_kg / 200.0 * minutes)


def _haversine(lat1, lon1, lat2, lon2):
    R = 6371000
    p1, p2 = radians(lat1), radians(lat2)
    dp = radians(lat2 - lat1)
    dl = radians(lon2 - lon1)
    a = sin(dp / 2) ** 2 + cos(p1) * cos(p2) * sin(dl / 2) ** 2
    return 2 * R * atan2(sqrt(a), sqrt(1 - a))


def _ext_value(extensions, local_name):
    for ext in (extensions or []):
        try:
            for el in ext.iter():
                tag = el.tag
                if isinstance(tag, str):
                    if '}' in tag:
                        tag = tag.rsplit('}', 1)[1]
                    if tag.lower() == local_name.lower() and el.text:
                        try:
                            return float(el.text)
                        except (TypeError, ValueError):
                            pass
        except Exception:
            log.debug('Reading an optional FIT/GPX extension failed', exc_info=True)
    return None


_SPORT_MAP = {
    '1': 'Ride', 'ride': 'Ride', 'cycling': 'Ride', 'bike': 'Ride', 'biking': 'Ride',
    '9': 'Run', 'run': 'Run', 'running': 'Run',
    'swim': 'Swim', 'swimming': 'Swim',
    'walk': 'Walk', 'walking': 'Walk',
    'hike': 'Hike', 'hiking': 'Hike',
    'vride': 'VirtualRide', 'virtual_ride': 'VirtualRide', 'virtualride': 'VirtualRide',
}


def _map_sport(s):
    return _SPORT_MAP.get(str(s).lower().strip(), 'Ride')


_MAX_PLAUSIBLE = {'speed': 30.0, 'hr': 250, 'watts': 2500, 'cadence': 250}   # m/s (108 km/h), bpm, W, rpm — beyond this is sensor/GPS noise


def _windowed_max_speed(streams, window_s=10):
    """Max speed (m/s) for files with no speed stream (GPX): distance over >= window_s seconds, so a single GPS
    jump can't create a 90 mph "max". Distance comes from the stream or, failing that, from the GPS trace."""
    t = (streams.get('time') or {}).get('data') or []
    d = (streams.get('distance') or {}).get('data') or []
    if len(d) != len(t):
        ll = (streams.get('latlng') or {}).get('data') or []
        if len(ll) == len(t) and len(ll) > 1:
            d, acc = [0.0], 0.0
            for i in range(1, len(ll)):
                acc += _haversine(ll[i - 1][0], ll[i - 1][1], ll[i][0], ll[i][1])
                d.append(acc)
    if len(t) < 3 or len(d) != len(t):
        return None
    best, lo = 0.0, 0
    for hi in range(1, len(t)):
        while lo < hi - 1 and t[hi] - t[lo + 1] >= window_s:
            lo += 1
        dt = t[hi] - t[lo]
        if dt >= window_s:
            v = (d[hi] - d[lo]) / dt
            if v <= _MAX_PLAUSIBLE['speed']:      # a window containing a GPS jump is skipped, not allowed to set the max
                best = max(best, v)
    return best if best > 0 else None


def sensor_fault(streams):
    """True when the device's distance ran well ahead of the GPS (services/best_efforts.sensor_excess_m): an Edge's speed sensor that logged
    134 km/h for five minutes. The top speed is then no more than the GPS shows (extremes_from_streams), and the device's own is not used."""
    from services.best_efforts import SENSOR_FAULT_M, sensor_excess_m
    return sensor_excess_m(streams) > SENSOR_FAULT_M


def extremes_from_streams(streams):
    """Max speed / heart rate / power / cadence from the streams, ignoring impossible spikes. Missing -> absent keys."""
    out = {}
    def mx(key, cap):
        vals = [v for v in ((streams.get(key) or {}).get('data') or []) if v is not None and 0 < v <= cap]
        return max(vals) if vals else None
    spd = mx('velocity_smooth', _MAX_PLAUSIBLE['speed'])
    if sensor_fault(streams):                  # the speed sensor went wrong: no faster than the GPS shows (never faster: a noisy GPS overstates)
        gps = _windowed_max_speed({k: v for k, v in streams.items() if k in ('time', 'latlng')})
        spd = min(v for v in (spd, gps) if v is not None) if (spd is not None or gps is not None) else None
    if spd is None:
        spd = _windowed_max_speed(streams)
    for name, val in (('maxSpeed', spd), ('maxHeartrate', mx('heartrate', _MAX_PLAUSIBLE['hr'])),
                      ('maxWatts', mx('watts', _MAX_PLAUSIBLE['watts'])), ('maxCadence', mx('cadence', _MAX_PLAUSIBLE['cadence']))):
        if val is not None:
            out[name] = round(float(val), 3) if name == 'maxSpeed' else round(float(val), 1)
    return out


def _gain_smoothed(alts, threshold=3.0, window=7):
    """Total climb from a noisy altitude track (phone GPS altitude wanders by metres even when you stand still): smooth it, then only count a rise once it is
    at least `threshold` metres from the last low point."""
    if len(alts) < window:
        return 0.0
    h = window // 2
    sm = [sum(alts[max(0, i - h):i + h + 1]) / len(alts[max(0, i - h):i + h + 1]) for i in range(len(alts))]
    gain, low = 0.0, sm[0]
    for a in sm[1:]:
        if a - low >= threshold:
            gain += a - low
            low = a
        elif a < low:
            low = a
    return gain


def _declare_missing_prefixes(text):
    """Avinox writes <avinox:totalDistance> without ever declaring xmlns:avinox, which is not well-formed XML, so gpxpy rejects the whole file
    ("unbound prefix"). Declare any prefix that is used but never declared on the root <gpx> element; files that are already valid are untouched."""
    used = set(re.findall(r'</?([A-Za-z_][\w.-]*):[A-Za-z_]', text))
    used |= set(re.findall(r'\s([A-Za-z_][\w.-]*):[A-Za-z_][\w.-]*\s*=', text))
    declared = set(re.findall(r'xmlns:([A-Za-z_][\w.-]*)\s*=', text))
    missing = sorted(used - declared - {'xml', 'xmlns'})
    if not missing:
        return text
    decls = ''.join(f' xmlns:{p}="urn:undeclared:{p}"' for p in missing)
    return re.sub(r'<gpx(?=[\s>/])', lambda m: '<gpx' + decls, text, count=1)


def parse_gpx(data: bytes, stopped_speed=None, smooth_gain=False):
    import gpxpy

    text = data.decode('utf-8', errors='replace')
    # Trailforks writes "2026-07-21T12:05:57z" — gpxpy only accepts an upper-case T/Z and silently drops every timestamp otherwise
    text = re.sub(r'<time>([^<]*)</time>', lambda m: '<time>' + m.group(1).strip().upper() + '</time>', text)
    text = _declare_missing_prefixes(text)
    gpx = gpxpy.parse(io.StringIO(text))

    points = []
    for track in gpx.tracks:
        for seg in track.segments:
            points.extend(seg.points)

    if not points:
        import logging; logging.getLogger(__name__).warning('parse_gpx: no track points found (route-only or empty file)')
        return None
    if points[0].time is None:
        if '<time>' in text.split('<trkpt', 1)[-1]:
            import logging; logging.getLogger(__name__).warning('parse_gpx: track has <time> tags gpxpy could not read (first: %s)',
                                                                re.search(r'<time>([^<]*)</time>', text.split('<trkpt', 1)[-1]).group(1))
        else:
            import logging; logging.getLogger(__name__).warning('parse_gpx: no timestamps in track — cannot import route-only files')
        return None

    start = points[0].time
    name = 'Imported Ride'
    sport_type = 'Ride'
    if gpx.tracks:
        t = gpx.tracks[0]
        name = t.name or gpx.name or name
        if t.type:
            sport_type = _map_sport(t.type)

    # stopped_speed: below this many m/s counts as standing still. gpxpy's default (1 m/s, 2.2 mph) is right for a bike but drops a stroll or a hill walk from the moving time
    moving_data = (gpx.tracks[0].get_moving_data(stopped_speed_threshold=stopped_speed) if stopped_speed else gpx.tracks[0].get_moving_data()) if gpx.tracks else None
    distance = moving_data.moving_distance if moving_data else 0
    moving_time = moving_data.moving_time if moving_data else 0
    uphill, _ = gpx.tracks[0].get_uphill_downhill() if gpx.tracks else (0, 0)
    if smooth_gain:
        uphill = _gain_smoothed([p.elevation for p in points if p.elevation is not None])

    if stopped_speed:
        # on foot: phone GPS often repeats a position for a second or two and then jumps, so single-second speeds flicker between 0 and double. Judge movement over a ~10 s window.
        timed_pts = [p for p in points if p.time is not None and p.latitude is not None]
        moving = 0.0
        for i in range(len(timed_pts) - 1):
            a, b = timed_pts[max(0, i - 5)], timed_pts[min(len(timed_pts) - 1, i + 5)]
            span = (b.time - a.time).total_seconds()
            if span > 0 and _haversine(a.latitude, a.longitude, b.latitude, b.longitude) / span >= stopped_speed:
                moving += max(0.0, min(30.0, (timed_pts[i + 1].time - timed_pts[i].time).total_seconds()))
        moving_time = moving

    rows, hr_s, pwr_s = [], [], []
    for pt in points:
        hr = _ext_value(pt.extensions, 'hr')
        cad = _ext_value(pt.extensions, 'cad') or _ext_value(pt.extensions, 'cadence')
        pwr = _ext_value(pt.extensions, 'power')
        if pwr is None:
            pwr = _ext_value(pt.extensions, 'powerinwatts')
        if pwr is None:
            pwr = _ext_value(pt.extensions, 'watts')
        rows.append({'time': pt.time,
                     'latlng': [pt.latitude, pt.longitude] if pt.latitude is not None and pt.longitude is not None else None,
                     'altitude': pt.elevation, 'heartrate': hr, 'cadence': cad, 'watts': pwr})
        if hr is not None:
            hr_s.append(int(hr))
        if pwr is not None:
            pwr_s.append(int(pwr))
    streams, _ = aligned_streams(rows, start)            # one value per point in every stream (distance measured along the track)
    latlng = (streams.get('latlng') or {}).get('data') or []

    avg_hr = (sum(hr_s) / len(hr_s)) if hr_s else None
    avg_pwr = (sum(pwr_s) / len(pwr_s)) if pwr_s else None
    extremes = extremes_from_streams(streams)
    avg_speed = (distance / moving_time) if moving_time > 0 else None

    timed = [p.time for p in points if p.time is not None]
    elapsed_s = (timed[-1] - timed[0]).total_seconds() if len(timed) > 1 else moving_time   # wall-clock, not moving time

    return {
        'id':                 _stable_id(start, distance),
        'name':               name,
        'sportType':          sport_type,
        'startDateLocal':     _utc_iso(start),
        'distance':           round(distance, 1),
        'movingTime':         int(moving_time),
        'elapsedTime':        int(elapsed_s),
        'totalElevationGain': round(uphill or 0, 1),
        'averageSpeed':       round(avg_speed, 4) if avg_speed else None,
        'averageHeartrate':   round(avg_hr, 1) if avg_hr else None,
        'averageWatts':       round(avg_pwr, 1) if avg_pwr else None,
        **extremes,
        'startLat':           latlng[0][0] if latlng else None,
        'startLng':           latlng[0][1] if latlng else None,
        'streams':            json.dumps(streams),
    }


def parse_fit(data: bytes):
    from fitparse import FitFile

    ff = FitFile(io.BytesIO(data))
    records = []
    session_msg = None

    for msg in ff.get_messages():
        if msg.name == 'record':
            records.append({f.name: f.value for f in msg})
        elif msg.name == 'session':
            session_msg = {f.name: f.value for f in msg}

    start = None
    if session_msg:
        start = session_msg.get('start_time')
    if not start and records:
        start = records[0].get('timestamp')
    if not start:
        return None

    s = session_msg or {}
    distance   = float(s.get('total_distance') or 0)
    # Some older devices report distance in mm. Only rescale when the per-record distance stream agrees it's off by 1000x —
    # a legitimate ultra-distance ride (>500 km) must not be silently shrunk.
    if distance > 500000:
        rec_dists = [r['distance'] for r in records if r.get('distance') is not None]
        last = float(rec_dists[-1]) if rec_dists else 0
        if last > 0 and abs(last - distance / 1000) / (distance / 1000) < 0.2:
            distance = distance / 1000
    moving_time = int(s.get('total_moving_time') or s.get('total_timer_time') or 0)
    elev_gain  = float(s.get('total_ascent') or 0)
    avg_hr     = s.get('avg_heart_rate')
    avg_watts  = s.get('avg_power')
    avg_speed  = s.get('avg_speed') if s.get('avg_speed') is not None else s.get('enhanced_avg_speed')
    avg_cad    = s.get('avg_cadence')
    calories   = s.get('total_calories')
    sport_type = _map_sport(s.get('sport', 'cycling'))

    points, hr_s = [], []
    for r in records:
        lat, lng = r.get('position_lat'), r.get('position_long')
        alt = r.get('altitude') if r.get('altitude') is not None else r.get('enhanced_altitude')   # newer devices write only enhanced_*
        spd = r.get('speed') if r.get('speed') is not None else r.get('enhanced_speed')
        num = lambda v: float(v) if isinstance(v, (int, float)) else None
        p = {'time': r.get('timestamp'),
             'latlng': [lat * 180 / 2 ** 31, lng * 180 / 2 ** 31] if lat is not None and lng is not None else None,
             'altitude': num(alt), 'heartrate': num(r.get('heart_rate')), 'watts': num(r.get('power')), 'cadence': num(r.get('cadence')),
             'velocity_smooth': num(spd), 'distance': num(r.get('distance'))}
        points.append(p)
        if p['heartrate'] is not None:
            hr_s.append(p['heartrate'])
    streams, _ = aligned_streams(points, start)          # one value per point in every stream: a record with no fix used to shift `time`
    latlng = (streams.get('latlng') or {}).get('data') or []
    device_moving = moving_time                          # the timer counts every stop when auto-pause is off: then the track's, as Strava does
    moving_time = pick_moving_time(moving_time, track_moving_time(streams), s.get('total_elapsed_time'), sport_type)
    if moving_time != device_moving:
        avg_speed = None                                 # the device's was distance over its own (wrong) time

    if avg_hr is None and hr_s:
        avg_hr = sum(hr_s) / len(hr_s)
    if avg_speed is None and distance and moving_time:
        avg_speed = distance / moving_time

    # Maxima: prefer what the device recorded for the whole session, else derive from the streams.
    extremes = extremes_from_streams(streams)
    dev_max = {'maxSpeed': s.get('enhanced_max_speed') if s.get('enhanced_max_speed') is not None else s.get('max_speed'),
               'maxHeartrate': s.get('max_heart_rate'), 'maxWatts': s.get('max_power'), 'maxCadence': s.get('max_cadence')}
    if sensor_fault(streams):
        dev_max.pop('maxSpeed')                          # the faulty sensor's: extremes_from_streams has the GPS's
    for k, v in dev_max.items():
        try:
            v = float(v)
        except (TypeError, ValueError):
            continue
        if 0 < v <= {'maxSpeed': 30.0, 'maxHeartrate': 250, 'maxWatts': 2500, 'maxCadence': 250}[k]:
            extremes[k] = round(v, 3) if k == 'maxSpeed' else round(v, 1)

    return {
        'id':                 _stable_id(start, distance),
        'name':               sport_type + ' Activity',
        'sportType':          sport_type,
        'startDateLocal':     _utc_iso(start),
        'distance':           round(distance, 1),
        'movingTime':         moving_time,
        'elapsedTime':        int(s.get('total_elapsed_time') or moving_time),
        'totalElevationGain': round(elev_gain, 1),
        'averageSpeed':       round(float(avg_speed), 4) if avg_speed else None,
        'averageHeartrate':   round(float(avg_hr), 1) if avg_hr else None,
        'averageWatts':       round(float(avg_watts), 1) if avg_watts else None,
        'averageCadence':     round(float(avg_cad), 1) if avg_cad else None,
        **extremes,
        'calories':           round(float(calories), 1) if calories else None,
        'startLat':           latlng[0][0] if latlng else None,
        'startLng':           latlng[0][1] if latlng else None,
        'streams':            json.dumps(streams),
    }


ACTIVITY_EXTENSIONS = ('.gpx', '.fit', '.tcx', '.gpx.gz', '.fit.gz', '.tcx.gz')


def parse_activity_file(name, data: bytes):
    """Parse an activity file by its extension (data already gunzipped). None if the name isn't a .gpx / .fit / .tcx (optionally .gz)."""
    n = name.lower()
    if n.endswith('.gz'):
        n = n[:-3]
    if n.endswith('.gpx'):
        return parse_gpx(data)
    if n.endswith('.fit'):
        return parse_fit(data)
    if n.endswith('.tcx'):
        return parse_tcx(data)
    return None


def _tag(el):
    return el.tag.rsplit('}', 1)[-1] if isinstance(el.tag, str) else ''


def _num(el):
    try:
        return float(el.text) if el is not None and el.text else None
    except ValueError:
        return None


def _tcx_time(s):
    from datetime import datetime
    try:
        return datetime.fromisoformat((s or '').strip().upper().replace('Z', '+00:00'))
    except ValueError:
        return None


def _carried(vals):
    """A stream with gaps (a sensor that dropped out for a few points) as one value per point: the last reading is carried forward, and the first one
    back over any leading gap. Segments, best efforts and the charts all index every stream by the same point."""
    first = next(v for v in vals if v is not None)
    out, last = [], first
    for v in vals:
        last = v if v is not None else last
        out.append(last)
    return out


MOVING_MPS = 0.3        # track_moving_time: slower than this between two points is stopped (on a real export, within 1% of Strava's moving times)


PAUSED_SLACK = (1.1, 60)    # a device's moving time this much over the track's (x 1.1, + 60 s) counted stopped time: auto-pause was off


def pick_moving_time(device, on_track, elapsed=0, sport=None):
    """The moving time to keep: the device's, unless the track says it's wrong, as Strava works it out from the track itself. Wrong is under half
    the track's (a flat battery or a restart wrote a lap timer of seconds for a whole ride) or well over it (auto-pause off: an uplift day at a
    bike park, standing in the queue, comes out at 7 hours moving instead of 2). Not "well over" on the water: a slow swim, a snorkel or waiting
    for a wave is under MOVING_MPS and would look stopped."""
    from services.sports import on_water
    device, on_track = int(device or 0), int(on_track or 0)
    paused = device > on_track * PAUSED_SLACK[0] + PAUSED_SLACK[1] and not on_water(sport)
    if on_track and (not device or device < on_track / 2 or paused):
        return on_track
    return device or int(elapsed or 0)


def track_moving_time(streams):
    """Seconds spent moving, from the time and distance streams (distance measured along latlng when there's no distance stream), or 0."""
    t = (streams.get('time') or {}).get('data') or []
    d = (streams.get('distance') or {}).get('data') or []
    if len(d) != len(t):
        ll = (streams.get('latlng') or {}).get('data') or []
        if len(ll) != len(t):
            return 0
        d, acc = [0.0], 0.0
        for a, b in zip(ll, ll[1:]):
            acc += _haversine(a[0], a[1], b[0], b[1])
            d.append(acc)
    moving = 0
    for i in range(1, len(t)):
        dt = t[i] - t[i - 1]
        if dt > 0 and (d[i] - d[i - 1]) / dt >= MOVING_MPS:
            moving += dt
    return moving


_STREAM_KEYS = (('latlng', None), ('altitude', 1), ('heartrate', 0), ('cadence', 0), ('watts', 0), ('velocity_smooth', 3), ('distance', 1))


def aligned_streams(points, start):
    """Streams with one value per kept point in every one of them, so latlng[i], time[i], heartrate[i], ... are the same moment: segments, best
    efforts, roughness and the charts all index them so. `points`: dicts with 'time' (a datetime) and any of the _STREAM_KEYS. A point with no
    time, or a repeated or backwards one, is dropped, and so (when the track has any GPS) is one with no position: a device that writes a record
    before its first fix, or more records than fixes, used to make `time` longer than `latlng`, so every time read against a position was off.
    A channel's gaps are filled (_carried). With no distance channel, it is measured along the track. Returns (streams, the kept points)."""
    timed, prev = [], None
    has_gps = any(p.get('latlng') for p in points)
    for p in points:
        if p.get('time') is not None and (prev is None or p['time'] > prev) and (p.get('latlng') or not has_gps):
            timed.append(p)
            prev = p['time']
    if not timed:
        return {}, []
    streams = {'time': {'data': [int((p['time'] - start).total_seconds()) for p in timed]}}
    for key, nd in _STREAM_KEYS:
        vals = [p.get(key) for p in timed]
        if any(v is not None for v in vals):
            vals = _carried(vals)
            streams[key] = {'data': vals if nd is None else [round(v, nd) if nd else int(v) for v in vals]}
    if 'distance' not in streams and 'latlng' in streams:
        ll, acc, dist = streams['latlng']['data'], 0.0, [0.0]
        for a, b in zip(ll, ll[1:]):
            acc += _haversine(a[0], a[1], b[0], b[1])
            dist.append(round(acc, 1))
        streams['distance'] = {'data': dist}
    return streams, timed


CROP_SLACK_S = 5          # a window this close to the whole recording is not a crop (Strava's start and the file's differ by a second or so)


def crop(act, start, seconds):
    """The activity cut down to the window Strava keeps after a crop: from `start` (an aware datetime) for `seconds`. A Strava export's file is
    the recording as it was uploaded, and activities.csv the activity as it is now, so the crop is the window between them. Returns a new act
    with the streams cut and starting at 0, and what is read off the track (start position, maxima, average heart rate, power and cadence)
    worked out again from what's left; distance, moving time, climb and calories are the caller's (Strava's own figures). The act as it was
    when the window is the whole recording, or would leave nothing."""
    from datetime import datetime
    try:
        streams = json.loads(act.get('streams') or '{}')
        file_start = datetime.fromisoformat(act['startDateLocal'])
        if file_start.tzinfo is None:
            from datetime import timezone
            file_start = file_start.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError, KeyError):
        return act
    t = (streams.get('time') or {}).get('data') or []
    if not t or not seconds:
        return act
    off = (start - file_start).total_seconds()
    if off <= CROP_SLACK_S and t[-1] <= off + seconds + CROP_SLACK_S:
        return act                                         # the whole recording
    if off < -CROP_SLACK_S or off + seconds > t[-1] + CROP_SLACK_S:
        return act                                         # a window that doesn't fit inside the recording is a clock that's out (an hour, a time
                                                           # zone), not a crop: cutting by it would lose part of the ride
    keep = [i for i, x in enumerate(t) if off - 1 <= x <= off + seconds + 1]
    if len(keep) < 2:
        return act
    lo, hi = keep[0], keep[-1] + 1
    out_streams = {}
    for key, st in streams.items():
        data = (st or {}).get('data') if isinstance(st, dict) else None
        if not isinstance(data, list) or len(data) != len(t):
            continue                                       # a channel out of step with time can't be cut by it
        cut = data[lo:hi]
        if key == 'time':
            cut = [max(0, int(round(x - off))) for x in cut]
        elif key == 'distance' and cut and cut[0] is not None:
            base = cut[0]
            cut = [round(x - base, 1) if x is not None else None for x in cut]
        out_streams[key] = {**st, 'data': cut}
    new = {k: v for k, v in act.items() if k not in ('maxSpeed', 'maxHeartrate', 'maxWatts', 'maxCadence')}
    new['streams'] = json.dumps(out_streams)
    new['elapsedTime'] = int(seconds)
    new.update(extremes_from_streams(out_streams))
    ll = [p for p in (out_streams.get('latlng') or {}).get('data') or [] if p and p[0] is not None]
    new['startLat'], new['startLng'] = (ll[0][0], ll[0][1]) if ll else (act.get('startLat'), act.get('startLng'))
    for col, key, keep_v in (('averageHeartrate', 'heartrate', lambda v: v > 0), ('averageWatts', 'watts', lambda v: v >= 0),
                             ('averageCadence', 'cadence', lambda v: v > 0)):
        vals = [v for v in (out_streams.get(key) or {}).get('data') or [] if v is not None and keep_v(v)]
        new[col] = round(sum(vals) / len(vals), 1) if vals else None
    alts = [a for a in (out_streams.get('altitude') or {}).get('data') or [] if a is not None]
    from gpxpy.geo import calculate_uphill_downhill
    new['totalElevationGain'] = round(calculate_uphill_downhill(alts)[0], 1) if alts else None
    new['calories'] = None                                 # the whole recording's
    new['cropped'] = True
    return new


def parse_tcx(data: bytes):
    """Garmin Training Center XML (.tcx): older Garmins (the Edge 705), TrainerRoad and Strava's own exports. Laps hold the device's totals
    (timer time, distance, calories, maxima); trackpoints hold time, position, altitude, distance, heart rate, cadence, and speed / power / run
    cadence in the ActivityExtension. Only the first <Activity> is read. Unlike GPX/FIT, every stream gets one value per kept point."""
    import xml.etree.ElementTree as ET
    from gpxpy.geo import calculate_uphill_downhill

    data = data.lstrip().removeprefix(b'\xef\xbb\xbf').lstrip()     # Strava's TCX files start with spaces before <?xml, which XML forbids
    root = ET.fromstring(data)
    activity = next((el for el in root.iter() if _tag(el) == 'Activity'), None)
    if activity is None:
        return None
    sport_type = _map_sport(activity.get('Sport', 'Biking'))

    laps = [el for el in activity if _tag(el) == 'Lap']
    lap_time = lap_dist = calories = 0.0
    dev_max = {'maxSpeed': None, 'maxHeartrate': None}
    points = []
    for lap in laps:
        for el in lap:
            name = _tag(el)
            if name == 'TotalTimeSeconds':
                lap_time += _num(el) or 0
            elif name == 'DistanceMeters':
                lap_dist += _num(el) or 0
            elif name == 'Calories':
                calories += _num(el) or 0
            elif name in ('MaximumSpeed', 'MaximumHeartRateBpm'):
                key = 'maxSpeed' if name == 'MaximumSpeed' else 'maxHeartrate'
                v = _num(el) if key == 'maxSpeed' else _num(next((c for c in el if _tag(c) == 'Value'), None))
                if v is not None:
                    dev_max[key] = max(dev_max[key] or 0, v)
        for tp in lap.iter():
            if _tag(tp) != 'Trackpoint':
                continue
            p = {}
            for el in tp:
                name = _tag(el)
                if name == 'Time':
                    p['time'] = _tcx_time(el.text)
                elif name == 'Position':
                    ll = {_tag(c): _num(c) for c in el}
                    if ll.get('LatitudeDegrees') is not None and ll.get('LongitudeDegrees') is not None:
                        p['latlng'] = [ll['LatitudeDegrees'], ll['LongitudeDegrees']]
                elif name == 'AltitudeMeters':
                    p['altitude'] = _num(el)
                elif name == 'DistanceMeters':
                    p['distance'] = _num(el)
                elif name == 'HeartRateBpm':
                    p['heartrate'] = _num(next((c for c in el if _tag(c) == 'Value'), None))
                elif name == 'Cadence':
                    p['cadence'] = _num(el)
                elif name == 'Extensions':
                    for c in el.iter():
                        ext = _tag(c)
                        if ext == 'Speed':
                            p['velocity_smooth'] = _num(c)
                        elif ext == 'Watts':
                            p['watts'] = _num(c)
                        elif ext == 'RunCadence' and p.get('cadence') is None:
                            p['cadence'] = _num(c)
            if p.get('time'):
                points.append(p)

    if not points:
        return None
    times = [p['time'] for p in points]
    first_lap = _tcx_time(laps[0].get('StartTime')) if laps else None
    start = min(first_lap or times[0], times[0])
    elapsed_s = (max(times) - start).total_seconds()

    streams, timed = aligned_streams(points, start)     # drops repeated or backwards timestamps, and (outdoors) the points with no position

    track_dist = ((streams.get('distance') or {}).get('data') or [0])[-1]
    distance = lap_dist if lap_dist >= track_dist / 2 else track_dist      # an Edge 25 wrote a 100 km ride's lap as 42 m; its trackpoints were right
    on_track = track_moving_time(streams)
    # A Garmin whose battery went flat (or that restarted) can write a lap timer of a few seconds for a whole ride: 9 s for 11 km, so 2,766 mph;
    # one with auto-pause off counts every stop. Strava works moving time out from the track; so do we when the device's is far off it.
    moving_time = pick_moving_time(lap_time, on_track, elapsed_s, sport_type)
    alts = (streams.get('altitude') or {}).get('data') or []
    raw = lambda key, keep=lambda v: True: [p[key] for p in timed if p.get(key) is not None and keep(p[key])]
    hr, watts, cad = raw('heartrate'), raw('watts'), raw('cadence', lambda v: v > 0)     # Garmin's average cadence leaves out coasting

    extremes = extremes_from_streams(streams)
    if sensor_fault(streams):
        dev_max.pop('maxSpeed', None)                    # the faulty sensor's: extremes_from_streams has the GPS's
    for k, v in dev_max.items():
        if v and 0 < v <= {'maxSpeed': _MAX_PLAUSIBLE['speed'], 'maxHeartrate': _MAX_PLAUSIBLE['hr']}[k]:
            extremes[k] = round(v, 3) if k == 'maxSpeed' else round(v, 1)
    latlng = (streams.get('latlng') or {}).get('data') or []

    return {
        'id':                 _stable_id(start, distance),
        'name':               sport_type + ' Activity',
        'sportType':          sport_type,
        'startDateLocal':     _utc_iso(start),
        'distance':           round(distance, 1),
        'movingTime':         moving_time,
        'elapsedTime':        int(elapsed_s),
        'totalElevationGain': round(calculate_uphill_downhill(alts)[0] if alts else 0, 1),     # gpxpy's, as GPX rides get: within 1% of Strava's median on Edge 705 files
        'averageSpeed':       round(distance / moving_time, 4) if distance and moving_time else None,
        'averageHeartrate':   round(sum(hr) / len(hr), 1) if hr else None,
        'averageWatts':       round(sum(watts) / len(watts), 1) if watts else None,
        'averageCadence':     round(sum(cad) / len(cad), 1) if cad else None,
        **extremes,
        'calories':           round(calories, 1) if calories else None,
        'startLat':           latlng[0][0] if latlng else None,
        'startLng':           latlng[0][1] if latlng else None,
        'streams':            json.dumps(streams),
    }
