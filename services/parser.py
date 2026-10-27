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
    'ebike': 'EBikeRide', 'e-bike': 'EBikeRide', 'e_bike': 'EBikeRide', 'ebikeride': 'EBikeRide',     # the iPhone app's <type>ebike</type>
}


def _map_sport(s, sub=None):
    """A file's own name for its sport -> one of services/sports.SPORTS: the short names above (Strava's GPX numbers, the phone apps' types),
    else sports.from_type, which knows FIT's sports and sub-sports and GPX's and TCX's names, and makes anything it doesn't know 'Other'.
    A file that names no sport at all is taken as a ride by its caller, as it always was."""
    key = str(s).lower().strip()
    if key in _SPORT_MAP and not sub:
        return _SPORT_MAP[key]
    from services.sports import from_type
    return from_type(key, sub)


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


ALT_RANGE_M = (-450, 9000)      # lower than the Dead Sea's shore or higher than Everest's summit: a barometer gone wrong
ALT_JUMP = (200, 10)            # metres, within this many seconds: no one climbs or drops that fast (a broken Wahoo jumped 13 km in one)


def altitude_broken(streams):
    """True when the altitude stream can't be real (ALT_RANGE_M, ALT_JUMP): five rides from one Wahoo ELEMNT swung between -500 m and 12,600 m
    and claimed 9,293-41,539 m of climb. The biggest real days on the same export stay within 946-2,810 m, jumping 143 m at most over 170 s."""
    alt = (streams.get('altitude') or {}).get('data') or []
    t = (streams.get('time') or {}).get('data') or []
    vals = [a for a in alt if a is not None]
    if not vals:
        return False
    if min(vals) < ALT_RANGE_M[0] or max(vals) > ALT_RANGE_M[1]:
        return True
    if len(t) == len(alt):
        for i in range(1, len(alt)):
            if (alt[i] is not None and alt[i - 1] is not None and abs(alt[i] - alt[i - 1]) >= ALT_JUMP[0]
                    and t[i] - t[i - 1] <= ALT_JUMP[1]):
                return True
    return False


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


def _wrap_bare_trkpts(text):
    """A track whose <trkpt>s sit straight in <trk> (no <trkseg>) with them wrapped in one, so gpxpy finds them. Files with a <trkseg> are untouched."""
    if '<trkseg' in text:
        return text
    first, last = text.find('<trkpt'), text.rfind('</trkpt>')
    if first < 0 or last < first:
        return text
    last += len('</trkpt>')
    return text[:first] + '<trkseg>' + text[first:last] + '</trkseg>' + text[last:]


_RUNKEEPER_NAME = re.compile(r'(\d{1,2})/(\d{1,2})/(\d{2}|\d{4})\s+(\d{1,2}):(\d{2})\s*([ap]m)', re.I)


def runkeeper_shift(creator, track_name, start, lat, lng):
    """How far a RunKeeper GPX's clock is out, as a timedelta (None when it isn't, or can't be told). RunKeeper's files from 2011-2013 stamp
    every <time> whole hours out (-1 to +10, a different amount per file) with the minutes and seconds right, and name the track after the real
    start on the wall clock where it happened: "Running 7/26/11 6:20 pm" (M/D/YY h:mm am/pm). The shift is the whole-hour gap between that and
    the file's start in the zone of its first point; only a gap within 90 s of 1 to 14 whole hours counts."""
    from datetime import datetime, timedelta, timezone
    m = _RUNKEEPER_NAME.search(track_name or '')
    if 'runkeeper' not in (creator or '').lower() or not m or start is None:
        return None
    mo, d, y, h, mi, ampm = m.groups()
    try:
        wall = datetime(int(y) + (2000 if len(y) == 2 else 0), int(mo), int(d), int(h) % 12 + (12 if ampm.lower() == 'pm' else 0), int(mi))
    except ValueError:
        return None
    from services import tz
    file_wall = (start if start.tzinfo else start.replace(tzinfo=timezone.utc)).astimezone(tz.zone_at(lat, lng)).replace(tzinfo=None)
    gap = (wall - file_wall.replace(second=0, microsecond=0)).total_seconds()
    hours = round(gap / 3600)
    if not 1 <= abs(hours) <= 14 or abs(gap - hours * 3600) > 90:
        return None
    return timedelta(hours=hours)


def parse_gpx(data: bytes, stopped_speed=None, smooth_gain=False):
    import gpxpy

    text = data.decode('utf-8', errors='replace')
    # Trailforks writes "2026-07-21T12:05:57z" — gpxpy only accepts an upper-case T/Z and silently drops every timestamp otherwise
    text = re.sub(r'<time>([^<]*)</time>', lambda m: '<time>' + m.group(1).strip().upper() + '</time>', text)
    # Strava's Android app (2014-16) wrote a UUID into <trk><number>, which GPX says is an integer, and gpxpy refuses the whole file for it;
    # it also put the points straight into <trk>, with no <trkseg>, where gpxpy doesn't look
    text = re.sub(r'<number>(?!\s*\d+\s*</number>)[^<]*</number>', '', text)
    text = _wrap_bare_trkpts(text)
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
    file_start = start
    shift = runkeeper_shift(gpx.creator, gpx.tracks[0].name if gpx.tracks else None, start, points[0].latitude, points[0].longitude)
    if shift:                                            # the streams count from the start, so only the start moves
        start = start + shift

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
        'id':                 _stable_id(file_start, distance),       # the file's own clock: the id it has always had
        'name':               name,
        'sportType':          sport_type,
        'startDateLocal':     _utc_iso(start),
        **({'clockShiftedFrom': _utc_iso(file_start)} if shift else {}),
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
    from fitparse.utils import FitEOFError

    if data.lstrip()[:2] == b'["':                       # a FIT saved as an escaped string in a Strava export (unescape_ruby_fit)
        data = unescape_ruby_fit(data)
    # The CRC isn't checked: a file that ends without it (a device that stopped mid-write) holds the whole ride all the same
    ff = FitFile(io.BytesIO(data), check_crc=False)
    records = []
    session_msg = None

    lap_msgs, length_msgs = [], []
    try:
        for msg in ff.get_messages():
            if msg.name == 'record':
                records.append({f.name: f.value for f in msg})
            elif msg.name == 'session':
                session_msg = {f.name: f.value for f in msg}
            elif msg.name == 'lap':
                lap_msgs.append({f.name: f.value for f in msg})
            elif msg.name == 'length':
                length_msgs.append({f.name: f.value for f in msg})
    except FitEOFError:
        if not records:                                  # junk from the start: not a FIT file at all
            raise
        log.warning('parse_fit: the file ends early, after %d records; keeping what came before', len(records))

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
    sport_type = _map_sport(s.get('sport', 'cycling'), s.get('sub_sport'))     # cycling + e_bike_mountain is an e-bike ride, + indoor_cycling indoors

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
    elapsed = s.get('total_elapsed_time')
    if not session_msg:                                  # a file that ended before its summary: what the track says
        distance = float(((streams.get('distance') or {}).get('data') or [0])[-1] or 0)
        elapsed = ((streams.get('time') or {}).get('data') or [0])[-1]
        alts = (streams.get('altitude') or {}).get('data') or []
        if alts:
            from gpxpy.geo import calculate_uphill_downhill
            elev_gain = calculate_uphill_downhill(alts)[0]
    device_moving = moving_time                         # the timer counts every stop when auto-pause is off: then the track's, as Strava does
    moving_time = pick_moving_time(moving_time, track_moving_time(streams), elapsed, sport_type)
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
        'elapsedTime':        int(elapsed or moving_time),
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
        'laps':               fit_laps(lap_msgs, length_msgs, s, start),
    }


def _num_or_none(v, places=1):
    try:
        v = float(v)
    except (TypeError, ValueError):
        return None
    return round(v, places)


def fit_laps(lap_msgs, length_msgs, session, start):
    """The device's laps, and a pool swim's lengths, as JSON for Activity.laps (services/activity_detail reads it), or None when there's only the
    one lap and no lengths. Times are seconds from the start of the activity, so a crop can shift them (crop_laps). A length is a pool length
    swum ('active': strokes, stroke type) or a rest at the wall ('active' false)."""
    def offset(m):
        t = m.get('start_time') or m.get('timestamp')
        try:
            return max(0, int(round((t - start).total_seconds())))
        except (TypeError, AttributeError):
            return None
    laps = []
    for m in lap_msgs:
        mps = m.get('enhanced_avg_speed') if m.get('enhanced_avg_speed') is not None else m.get('avg_speed')
        lap = {'t': offset(m), 'secs': _num_or_none(m.get('total_timer_time') or m.get('total_elapsed_time')), 'dist': _num_or_none(m.get('total_distance')),
               'mps': _num_or_none(mps, 3), 'hr': _num_or_none(m.get('avg_heart_rate'), 0), 'maxHr': _num_or_none(m.get('max_heart_rate'), 0),
               'cad': _num_or_none(m.get('avg_cadence'), 0), 'watts': _num_or_none(m.get('avg_power'), 0),
               'up': _num_or_none(m.get('total_ascent'), 0), 'down': _num_or_none(m.get('total_descent'), 0),
               'strokes': _num_or_none(m.get('total_strokes'), 0), 'stroke': m.get('swim_stroke') if isinstance(m.get('swim_stroke'), str) else None}
        laps.append({k: v for k, v in lap.items() if v is not None})
    lengths = []
    for m in length_msgs:
        active = m.get('length_type') != 'idle'
        ln = {'t': offset(m), 'secs': _num_or_none(m.get('total_timer_time') or m.get('total_elapsed_time')), 'active': active}
        if active:
            ln.update({'strokes': _num_or_none(m.get('total_strokes'), 0), 'cad': _num_or_none(m.get('avg_swimming_cadence'), 0),
                       'stroke': m.get('swim_stroke') if isinstance(m.get('swim_stroke'), str) else None})
        lengths.append({k: v for k, v in ln.items() if v is not None})
    pool_m = _num_or_none(session.get('pool_length'), 2)  # metres, whichever way the swimmer counts: a 25 yd pool is 22.86
    if len(laps) < 2 and not lengths:
        return None
    out = {'laps': laps if len(laps) > 1 else []}
    if lengths:
        out['lengths'] = lengths
        out['pool_m'] = pool_m
        out['pool_unit'] = 'yd' if session.get('pool_length_unit') == 'statute' else 'm'
    return json.dumps(out)


def crop_laps(laps_json, off, seconds):
    """Activity.laps cut to a crop's window (crop): the laps and lengths that start inside it, their times shifted to its start."""
    try:
        d = json.loads(laps_json) if laps_json else None
    except ValueError:
        return None
    if not d:
        return None
    def keep(items):
        return [dict(x, t=int(x['t'] - off)) for x in items or [] if x.get('t') is not None and off - 1 <= x['t'] <= off + seconds]
    d['laps'] = keep(d.get('laps'))
    if d.get('lengths'):
        d['lengths'] = keep(d['lengths'])
    if len(d['laps']) < 2 and not d.get('lengths'):
        return None
    return json.dumps(d)


ACTIVITY_EXTENSIONS = ('.gpx', '.fit', '.tcx', '.gpx.gz', '.fit.gz', '.tcx.gz')


def sniff(data: bytes):
    """'fit', 'gpx', 'tcx' or None, from what a file holds rather than its name: Strava's exports have FIT files named .bin."""
    if len(data) >= 12 and data[8:12] == b'.FIT':
        return 'fit'
    head = data[:2048].lstrip().removeprefix(b'\xef\xbb\xbf').lstrip()
    if head.startswith(b'<'):
        if b'<gpx' in head:
            return 'gpx'
        if b'<TrainingCenterDatabase' in head:
            return 'tcx'
    return None


def parse_activity_file(name, data: bytes, strava_export=False):
    """Parse an activity file (data already gunzipped) by its extension: .gpx / .fit / .tcx, optionally .gz. strava_export: a file named in a
    Strava export's activities.csv, which may also be a recording from Strava's own app (.json: parse_strava_app_json) or a FIT file under
    another name (.bin), told by its contents (sniff). None when it's none of these. A ride or run that starts in one of Zwift's made-up worlds
    is a Zwift one, whatever the file calls it (services/zwift.indoor_sport)."""
    n = name.lower()
    if n.endswith('.gz'):
        n = n[:-3]
    if n.endswith('.json'):
        act = parse_strava_app_json(data) if strava_export else None
    else:
        kind = next((k for k in ('gpx', 'fit', 'tcx') if n.endswith('.' + k)), None) or (sniff(data) if strava_export else None)
        act = {'gpx': parse_gpx, 'fit': parse_fit, 'tcx': parse_tcx}[kind](data) if kind else None
    if act:
        from services.zwift import indoor_sport
        act['sportType'] = indoor_sport(act.get('sportType'), act.get('startLat'), act.get('startLng'))
    return act


_RUBY_ESCAPES = {ord('e'): 0x1b, ord('f'): 0x0c, ord('n'): 0x0a, ord('t'): 0x09, ord('r'): 0x0d, ord('v'): 0x0b, ord('b'): 0x08, ord('a'): 0x07,
                 ord('s'): 0x20, ord('0'): 0x00, ord('"'): 0x22, ord('\\'): 0x5c, ord('#'): 0x23}


def unescape_ruby_fit(data: bytes):
    """A FIT file that Strava's export holds as a JSON array, ["<the file as a Ruby string literal>", true]: \\xNN for most bytes, Ruby's
    one-letter escapes (\\e \\f \\n \\t \\r \\v \\b \\a \\s \\0), and \\" \\\\ \\#. Python's unicode_escape gets it wrong (it has no \\e or \\#).
    Returns the file's bytes; ValueError when it isn't one."""
    m = re.match(rb'\s*\[\s*"', data)
    if not m:
        raise ValueError('not an escaped FIT file')
    out, i, n = bytearray(), m.end(), len(data)
    while i < n:
        c = data[i]
        if c == 0x22:                                    # the closing quote
            return bytes(out)
        if c != 0x5c:
            out.append(c)
            i += 1
            continue
        e = data[i + 1] if i + 1 < n else None
        if e == ord('x'):
            out.append(int(data[i + 2:i + 4], 16))
            i += 4
        elif e in _RUBY_ESCAPES:
            out.append(_RUBY_ESCAPES[e])
            i += 2
        else:
            raise ValueError(f'unknown escape at byte {i}')
    raise ValueError('escaped FIT file has no end')


def parse_strava_app_json(data: bytes):
    """A recording from Strava's own phone app, as a Strava export keeps it (activities/<n>.json, from about 2020): a JSON array whose first item
    is a JSON string of {metadata, data}. metadata has the activity type, name, start, timer (moving) and elapsed time; data is a list of
    series {fields, values}: the track (time in epoch seconds, latlng, elevation, speed, distance, ...) and the pauses (time, pause_type:
    0 / 2 paused by hand / automatically, 1 / 3 going again). Returns the same act dict as parse_gpx, or None."""
    from datetime import datetime, timezone
    try:
        outer = json.loads(data)
        doc = outer[0] if isinstance(outer, list) and outer else outer
        doc = json.loads(doc) if isinstance(doc, str) else doc
        meta, series = doc.get('metadata') or {}, doc.get('data') or []
    except (ValueError, TypeError, AttributeError, KeyError, IndexError):
        return None
    track = pauses = None
    for s in series:
        f = s.get('fields') or []
        if 'time' in f and 'latlng' in f and track is None:
            track = s
        elif f == ['time', 'pause_type']:
            pauses = s
    if not track or not track.get('values'):
        return None
    idx = {k: i for i, k in enumerate(track['fields'])}
    get = lambda row, k: row[idx[k]] if k in idx and idx[k] < len(row) else None
    points, seen_alt = [], False
    for row in track['values']:
        t, ll, alt = get(row, 'time'), get(row, 'latlng'), get(row, 'elevation')
        if t is None:
            continue
        seen_alt = seen_alt or bool(alt)
        points.append({'time': datetime.fromtimestamp(float(t), timezone.utc),
                       'latlng': [float(ll[0]), float(ll[1])] if isinstance(ll, list) and len(ll) == 2 else None,
                       'altitude': float(alt) if alt is not None and seen_alt else None,     # 0 until the phone has a height
                       'velocity_smooth': get(row, 'speed'), 'distance': get(row, 'distance')})
    if len(points) < 2:
        return None
    try:
        start = datetime.fromisoformat(str(meta.get('start_date')).replace('Z', '+00:00'))
        start = start if start.tzinfo else start.replace(tzinfo=timezone.utc)
    except ValueError:
        start = points[0]['time']
    start = min(start, points[0]['time'])
    streams, _ = aligned_streams(points, start)
    t_end = (streams.get('time') or {}).get('data', [0])[-1]
    elapsed = int(meta.get('elapsed_time') or t_end)
    moving = int(meta.get('timer_time') or 0)
    if not moving and pauses:                            # the time between each pause and going again, left out
        paused, since = 0.0, None
        for t, kind in pauses.get('values') or []:
            if kind in (0, 2) and since is None:
                since = t
            elif kind in (1, 3) and since is not None:
                paused, since = paused + t - since, None
        if since is not None:
            paused += max(0.0, points[-1]['time'].timestamp() - since)
        moving = max(0, int(round(t_end - paused)))
    moving = moving or track_moving_time(streams)
    distance = float(((streams.get('distance') or {}).get('data') or [0])[-1] or 0)
    latlng = (streams.get('latlng') or {}).get('data') or []
    sport = _map_sport(meta['activity_type']) if meta.get('activity_type') else 'Ride'
    return {
        'id':                 _stable_id(start, distance),
        'name':               (meta.get('activity_name') or '').strip() or sport + ' Activity',
        'sportType':          sport,
        'startDateLocal':     _utc_iso(start),
        'distance':           round(distance, 1),
        'movingTime':         moving,
        'elapsedTime':        elapsed,
        # Unknown: a phone's GPS height wanders (1,354 m climbed on a ride Strava, which corrects it from the ground, makes 501 m), and the
        # export these come in always has Strava's figure in activities.csv, which the import takes when the file has none
        'totalElevationGain': None,
        'averageSpeed':       round(distance / moving, 4) if distance and moving else None,
        **extremes_from_streams(streams),
        'startLat':           latlng[0][0] if latlng else None,
        'startLng':           latlng[0][1] if latlng else None,
        'streams':            json.dumps(streams),
    }


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
CROP_EXPLAINS = 0.5       # an end crop must take away at least half the difference between the track's distance and Strava's


PAUSE_S = 300             # no point for this long: the recording was paused (an uplift at a bike park), and the track jumps across it


def _track_m(streams, lo=0, hi=None, skip_pauses=False):
    """Metres along the track between two points: along the GPS when there is one in step with time, else the distance channel's.
    skip_pauses leaves out the straight-line jump across each pause, which Strava doesn't count either."""
    t = (streams.get('time') or {}).get('data') or []
    ll = (streams.get('latlng') or {}).get('data') or []
    hi = len(t) if hi is None else hi
    if len(ll) == len(t) and len(t) > 1:
        return sum(_haversine(ll[i - 1][0], ll[i - 1][1], ll[i][0], ll[i][1]) for i in range(max(lo, 1), hi)
                   if ll[i - 1] and ll[i] and ll[i - 1][0] is not None and ll[i][0] is not None
                   and i > lo and not (skip_pauses and t[i] - t[i - 1] >= PAUSE_S))
    d = (streams.get('distance') or {}).get('data') or []
    vals = [v for v in d[lo:hi] if v is not None] if len(d) == len(t) else []
    return vals[-1] - vals[0] if len(vals) > 1 else None


def crop(act, start, seconds, strava_m=None):
    """The activity cut down to the window Strava keeps after a crop: from `start` (an aware datetime) for `seconds`. A Strava export's file is
    the recording as it was uploaded, and activities.csv the activity as it is now, so the crop is the window between them. Returns a new act
    with the streams cut and starting at 0, and what is read off the track (start position, maxima, average heart rate, power and cadence)
    worked out again from what's left; distance, moving time, climb and calories are the caller's (Strava's own figures). The act as it was
    when the window is the whole recording, or would leave nothing.

    Strava leaves a paused recording's pauses out of its elapsed time (the uplifts at a bike park, a device stopped for an hour mid-ride), so a
    window that ends early is not always a crop; one that starts late is (a pause never moves the start). Given Strava's distance (`strava_m`),
    an end crop is only made when it takes away at least half the difference between the track's distance and Strava's, and comes closer to
    it than leaving out the jumps across the pauses does: a crop does (7 hours, 23.8 km -> 0.6 km, Strava's 0.61); pauses don't (a 24 km ride
    matching Strava's would lose half its track; a bike park day, 38.8 km with the uplifts' jumps, 30.3 without them, Strava's 30.5, would be
    cut to 22.9)."""
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
    if strava_m and off <= CROP_SLACK_S:              # a later start is a crop for certain; an earlier end may be pauses Strava doesn't count
        whole, cut, unpaused = _track_m(streams), _track_m(streams, lo, hi), _track_m(streams, skip_pauses=True)
        if whole is not None and cut is not None and (abs(cut - strava_m) > CROP_EXPLAINS * abs(whole - strava_m)
                                                      or (unpaused is not None and abs(unpaused - strava_m) <= abs(cut - strava_m))):
            return act
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
    new['laps'] = crop_laps(act.get('laps'), off, seconds)
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
