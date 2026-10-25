import copy
import os
import threading
from collections import OrderedDict

from flask import Blueprint, abort, redirect, render_template, request, url_for, current_app

from database import get_db, query_db
from services.best_efforts import BRACKETS_MI

bp = Blueprint('riders', __name__)

_ALLOWED = {'png', 'jpg', 'jpeg', 'gif', 'webp', 'svg'}


_BADGES = OrderedDict()     # the last few results of _compute_badges, by everything they depend on (_badge_key)
_BADGES_KEEP = 16
_BADGES_LOCK = threading.Lock()   # page threads and the MQTT heartbeat share it


def _badge_key(rid, totals):
    """What a rider's badges depend on: the database, the rider, the totals passed in, the units they're worded in, and the version of the tables
    they are counted from (services/data_version.py). None when the version can't be read: then nothing is kept."""
    from services import data_version, units
    v = data_version.current(get_db())
    if v is None:
        return None
    return (current_app.config.get('DATABASE'), rid, tuple(totals[k] for k in ('rides', 'dist', 'elev')), units.current(), v)


def _compute_badges(rid, totals):
    """Every badge category for a rider, earned or not. Counting them takes about 80 queries over the rider's whole history, and the ride page
    wants them on every view (to show the badges that ride earned), so a result is kept until a ride, segment, effort or bike changes."""
    try:
        from services import sport_records
        sport_records.ensure(get_db(), rid)     # before the key: working out a new run's best times changes the version
    except Exception:
        pass
    try:
        key = _badge_key(rid, totals)
    except Exception:
        key = None
    with _BADGES_LOCK:
        hit = _BADGES.get(key) if key is not None else None
        if hit is not None:
            _BADGES.move_to_end(key)
    if hit is not None:
        return copy.deepcopy(hit)
    out = _count_badges(rid, totals)
    if key is not None:
        with _BADGES_LOCK:
            _BADGES[key] = copy.deepcopy(out)
            while len(_BADGES) > _BADGES_KEEP:
                _BADGES.popitem(last=False)
    return out


def _count_badges(rid, totals):
    total_rides   = totals['rides'] or 0
    total_dist_m  = totals['dist']  or 0
    total_elev_m  = totals['elev']  or 0
    total_dist_mi = total_dist_m / 1609.344
    total_elev_ft = total_elev_m * 3.28084
    everests      = total_elev_m / 8849

    def _nth_ride(n):
        row = query_db(
            'SELECT id, startDateLocal FROM Ride WHERE riderId=? ORDER BY startDateLocal LIMIT 1 OFFSET ?',
            [rid, n - 1], one=True)
        return (row['startDateLocal'][:10], row['id']) if row else (None, None)

    def _dist_milestone(threshold_mi):
        row = query_db('''
            SELECT id, startDateLocal FROM (
                SELECT id, startDateLocal,
                       SUM(distance) OVER (ORDER BY startDateLocal) as running
                FROM Ride WHERE riderId=?
            ) WHERE running >= ? LIMIT 1
        ''', [rid, threshold_mi * 1609.344], one=True)
        return (row['startDateLocal'][:10], row['id']) if row else (None, None)

    def _elev_milestone(threshold_m):
        row = query_db('''
            SELECT id, startDateLocal FROM (
                SELECT id, startDateLocal,
                       SUM(totalElevationGain) OVER (ORDER BY startDateLocal) as running
                FROM Ride WHERE riderId=?
            ) WHERE running >= ? LIMIT 1
        ''', [rid, threshold_m], one=True)
        return (row['startDateLocal'][:10], row['id']) if row else (None, None)

    def _first_ride(condition_sql, params=None):
        row = query_db(
            f'SELECT id, startDateLocal FROM Ride WHERE riderId=? AND {condition_sql} ORDER BY startDateLocal LIMIT 1',
            [rid] + (params or []), one=True)
        return (row['startDateLocal'][:10], row['id']) if row else (None, None)

    def _count_cond(cond, params=None):
        return query_db(
            f'SELECT COUNT(*) as n FROM Ride WHERE riderId=? AND {cond}',
            [rid] + (params or []), one=True)['n'] or 0

    def _nth_cond(n, cond, params=None):
        row = query_db(
            f'SELECT id, startDateLocal FROM Ride WHERE riderId=? AND {cond} ORDER BY startDateLocal LIMIT 1 OFFSET ?',
            [rid] + (params or []) + [n - 1], one=True)
        return (row['startDateLocal'][:10], row['id']) if row else (None, None)

    def _wc(n, cond, params=None):
        cnt = _count_cond(cond, params)
        d, i = _nth_cond(n, cond, params) if cnt >= n else (None, None)
        return {'earned': cnt >= n, 'earned_date': d, 'ride_id': i,
                'progress': cnt, 'target': n}

    headwind_count = _count_cond("weatherWindRel='headwind'")

    def _hw(n):
        d, i = _nth_cond(n, "weatherWindRel='headwind'") if headwind_count >= n else (None, None)
        return {'earned': headwind_count >= n, 'earned_date': d, 'ride_id': i,
                'progress': headwind_count, 'target': n}

    peak = query_db('''
        SELECT MAX(distance) as max_dist, MAX(totalElevationGain) as max_elev,
               MAX(averageSpeed) as max_speed, MAX(maxSpeed) as top_speed
        FROM Ride WHERE riderId=?
    ''', [rid], one=True)
    max_dist_mi   = (peak['max_dist']  or 0) / 1609.344
    max_elev_ft   = (peak['max_elev']  or 0) * 3.28084
    max_speed_mph = (peak['max_speed'] or 0) * 2.23694
    top_speed_mph = (peak['top_speed'] or 0) * 2.23694

    def _fts(mph):  # first ride hitting top speed threshold
        d, i = _first_ride('maxSpeed >= ?', [mph / 2.23694])
        return {'earned': top_speed_mph >= mph, 'earned_date': d, 'ride_id': i}

    wx = query_db('''
        SELECT MIN(weatherTempC) as min_temp FROM Ride
        WHERE riderId=? AND weatherTempC IS NOT NULL
    ''', [rid], one=True)
    min_temp = wx['min_temp'] if wx and wx['min_temp'] is not None else 999

    wx_coldest = query_db('''
        SELECT id, startDateLocal, weatherTempC FROM Ride
        WHERE riderId=? AND weatherTempC IS NOT NULL
        ORDER BY weatherTempC ASC LIMIT 1
    ''', [rid], one=True)
    wx_windiest = query_db('''
        SELECT id, startDateLocal, weatherWindKph, weatherGustKph FROM Ride
        WHERE riderId=? AND weatherWindKph IS NOT NULL
        ORDER BY COALESCE(weatherGustKph, weatherWindKph) DESC LIMIT 1
    ''', [rid], one=True)

    def _b(icon, name, desc, earned, earned_date=None, ride_id=None):
        return {'icon': icon, 'name': name, 'desc': desc,
                'earned': earned, 'earned_date': earned_date, 'ride_id': ride_id}

    def _rc(n):   # ride count helper
        d, i = _nth_ride(n) if total_rides >= n else (None, None)
        return {'earned': total_rides >= n, 'earned_date': d, 'ride_id': i,
                'progress': total_rides, 'target': n}
    def _dm(mi):  # distance milestone helper
        d, i = _dist_milestone(mi) if total_dist_mi >= mi else (None, None)
        return {'earned': total_dist_mi >= mi, 'earned_date': d, 'ride_id': i,
                'progress': round(units.dist(total_dist_mi * units.MI)), 'target': round(units.dist(mi * units.MI))}
    def _em(m):   # elevation milestone helper
        d, i = _elev_milestone(m) if everests >= m / 8849 else (None, None)
        ev_target = round(m / 8849, 1)
        return {'earned': everests >= m / 8849, 'earned_date': d, 'ride_id': i,
                'progress': round(everests, 2), 'target': ev_target}
    def _fr(cond, params=None):  # first ride matching condition — binary, no bar
        d, i = _first_ride(cond, params)
        return {'earned': bool(d), 'earned_date': d, 'ride_id': i}
    from services import units
    from services.sports import class_sql
    def _b(icon, name, desc, r):   # the limits are in miles / mph / feet; the wording follows the rider's units
        return {'icon': icon, 'name': units.localise(name), 'desc': units.localise(desc), **r}

    ride_count = [
        _b('🚴', 'First Pedal',     '1 ride',           _rc(1)),
        _b('🎯', 'Getting Started', '10 rides',         _rc(10)),
        _b('🔥', 'Regular Rider',   '50 rides',         _rc(50)),
        _b('💯', 'Centurion',       '100 rides',        _rc(100)),
        _b('⚡', 'Dedicated',       '250 rides',        _rc(250)),
        _b('🏆', 'Five Hundred',    '500 rides',        _rc(500)),
        _b('🌟', 'One Thousand',    '1,000 rides',      _rc(1000)),
        _b('💫', 'Two Thousand',    '2,000 rides',      _rc(2000)),
        _b('👑', 'Elite',           '3,000 rides',      _rc(3000)),
        _b('🔮', 'Five Thousand',   '5,000 rides',      _rc(5000)),
    ]
    distance = [
        _b('📍', 'Road Tripper',  '100 miles total',     _dm(100)),
        _b('🗺️',  'Explorer',     '500 miles total',     _dm(500)),
        _b('🌍', 'Globetrotter', '1,000 miles total',   _dm(1000)),
        _b('💫', 'Iron Legs',    '5,000 miles total',   _dm(5000)),
        _b('🌟', '10K Club',     '10,000 miles total',  _dm(10000)),
        _b('🚀', '25K Ultra',    '25,000 miles total',  _dm(25000)),
        _b('💎', '50K Legend',   '50,000 miles total',  _dm(50000)),
        _b('👑', '100K Elite',   '100,000 miles total', _dm(100000)),
    ]
    elevation = [
        _b('⛰️',  'Summit Seeker',   '1 Everest climbed',    _em(8849)),
        _b('🏔️',  'Peak Bagger',     '5 Everests climbed',   _em(44245)),
        _b('🌋', 'Altitude Junkie', '10 Everests climbed',  _em(88490)),
        _b('👑', 'Everest Master',  '25 Everests climbed',  _em(221225)),
        _b('💫', 'Cloud Walker',    '50 Everests climbed',  _em(442450)),
        _b('🌟', 'Stratosphere',    '100 Everests climbed', _em(884900)),
        _b('🚀', 'Beyond the Sky',  '150 Everests climbed', _em(1327350)),
        _b('🔮', 'Space Cowboy',    '200 Everests climbed', _em(1769800)),
    ]
    epic_rides = [
        # ── Single ride milestones ─────────────────────────────────
        _b('🌟', 'Quarter Century', '25 miles in one ride',  _fr('distance >= ?', [25  * 1609.344])),
        _b('💎', 'Half Century',    '50 miles in one ride',  _fr('distance >= ?', [50  * 1609.344])),
        _b('🔥', '75 Miler',        '75 miles in one ride',  _fr('distance >= ?', [75  * 1609.344])),
        _b('👑', 'Century Club',    '100 miles in one ride', _fr('distance >= ?', [100 * 1609.344])),
        # ── 25mi ride count ────────────────────────────────────────
        _b('🎯', '5 × 25mi',   '5 rides of 25+ miles',   _wc(5,   'distance >= ?', [25 * 1609.344])),
        _b('📍', '10 × 25mi',  '10 rides of 25+ miles',  _wc(10,  'distance >= ?', [25 * 1609.344])),
        _b('🗺️',  '25 × 25mi',  '25 rides of 25+ miles',  _wc(25,  'distance >= ?', [25 * 1609.344])),
        _b('💫', '50 × 25mi',  '50 rides of 25+ miles',  _wc(50,  'distance >= ?', [25 * 1609.344])),
        _b('🌟', '100 × 25mi', '100 rides of 25+ miles', _wc(100, 'distance >= ?', [25 * 1609.344])),
        # ── 50mi ride count ────────────────────────────────────────
        _b('⭐', '5 × 50mi',   '5 rides of 50+ miles',   _wc(5,  'distance >= ?', [50 * 1609.344])),
        _b('🔥', '10 × 50mi',  '10 rides of 50+ miles',  _wc(10, 'distance >= ?', [50 * 1609.344])),
        _b('💪', '25 × 50mi',  '25 rides of 50+ miles',  _wc(25, 'distance >= ?', [50 * 1609.344])),
        _b('👑', '50 × 50mi',  '50 rides of 50+ miles',  _wc(50, 'distance >= ?', [50 * 1609.344])),
        # ── Century count ──────────────────────────────────────────
        _b('🏆', '3 × Century',  '3 rides of 100+ miles',  _wc(3,  'distance >= ?', [100 * 1609.344])),
        _b('💎', '10 × Century', '10 rides of 100+ miles', _wc(10, 'distance >= ?', [100 * 1609.344])),
    ]
    speed = [
        _b('🐢', 'Rolling',        '8 mph avg on a ride',  _fr('averageSpeed >= ?', [8  / 2.23694])),
        _b('🚲', 'Cruising',       '10 mph avg on a ride', _fr('averageSpeed >= ?', [10 / 2.23694])),
        _b('🏃', 'Getting There',  '12 mph avg on a ride', _fr('averageSpeed >= ?', [12 / 2.23694])),
        _b('💨', 'Building Speed', '14 mph avg on a ride', _fr('averageSpeed >= ?', [14 / 2.23694])),
        _b('⚡', 'Respectable',    '16 mph avg on a ride', _fr('averageSpeed >= ?', [16 / 2.23694])),
        _b('🔥', 'Quick',          '18 mph avg on a ride', _fr('averageSpeed >= ?', [18 / 2.23694])),
        _b('🚀', 'Speed Merchant', '20 mph avg on a ride', _fr('averageSpeed >= ?', [20 / 2.23694])),
        _b('💫', 'Rocket',         '22 mph avg on a ride', _fr('averageSpeed >= ?', [22 / 2.23694])),
        _b('🌟', 'Flying',         '24 mph avg on a ride', _fr('averageSpeed >= ?', [24 / 2.23694])),
        _b('👑', 'Supersonic',     '25 mph avg on a ride', _fr('averageSpeed >= ?', [25 / 2.23694])),
        _b('💨', 'Quick Descent',  '30 mph top speed',     _fts(30)),
        _b('⚡', 'Bullet',         '40 mph top speed',     _fts(40)),
        _b('🚀', 'Missile',        '50 mph top speed',     _fts(50)),
    ]
    climbing = [
        # ── Big elevation days ────────────────────────────────────
        _b('🏔️', 'Hills Exist',   'Ride with 500ft+ elevation',    _fr('totalElevationGain >= ?', [500  / 3.28084])),
        _b('⛰️',  'Proper Climb',  'Ride with 1,000ft+ elevation',  _fr('totalElevationGain >= ?', [1000 / 3.28084])),
        _b('🌋', 'Mountain Day', 'Ride with 2,000ft+ elevation',  _fr('totalElevationGain >= ?', [2000 / 3.28084])),
        _b('💪', 'Epic Climb',   'Ride with 3,000ft+ elevation',  _fr('totalElevationGain >= ?', [3000 / 3.28084])),
        _b('🏆', 'Alpine',       'Ride with 5,000ft+ elevation',  _fr('totalElevationGain >= ?', [5000 / 3.28084])),
        _b('👑', 'Gran Fondo',   'Ride with 7,500ft+ elevation',  _fr('totalElevationGain >= ?', [7500 / 3.28084])),
        _b('🌟', 'Everest Day',  'Ride with 10,000ft+ elevation', _fr('totalElevationGain >= ?', [10000 / 3.28084])),
        # ── Hilly regulars ────────────────────────────────────────
        _b('🎯', 'Hill Regular', '10 rides with 1,000ft+ elevation',  _wc(10,  'totalElevationGain >= ?', [1000 / 3.28084])),
        _b('💦', 'Hill Addict',  '100 rides with 1,000ft+ elevation', _wc(100, 'totalElevationGain >= ?', [1000 / 3.28084])),
        _b('🦵', 'King of Hills', '500 rides with 1,000ft+ elevation', _wc(500, 'totalElevationGain >= ?', [1000 / 3.28084])),
        # ── Speed on hilly rides (≥2% avg gradient, ≥5mi) ────────
        _b('🐢', 'Up the Hill',      '8mph avg on a hilly ride (≥2% gradient)',  _fr('averageSpeed >= ? AND distance >= 8047 AND CAST(totalElevationGain AS FLOAT)/distance*100 >= 2', [8  / 2.23694])),
        _b('🚵', 'Grinder',          '10mph avg on a hilly ride (≥2% gradient)', _fr('averageSpeed >= ? AND distance >= 8047 AND CAST(totalElevationGain AS FLOAT)/distance*100 >= 2', [10 / 2.23694])),
        _b('💪', 'Hill Chaser',      '12mph avg on a hilly ride (≥2% gradient)', _fr('averageSpeed >= ? AND distance >= 8047 AND CAST(totalElevationGain AS FLOAT)/distance*100 >= 2', [12 / 2.23694])),
        _b('🔥', 'Gradient Burner',  '15mph avg on a hilly ride (≥2% gradient)', _fr('averageSpeed >= ? AND distance >= 8047 AND CAST(totalElevationGain AS FLOAT)/distance*100 >= 2', [15 / 2.23694])),
        _b('⚡', 'Gradient King',    '18mph avg on a hilly ride (≥2% gradient)', _fr('averageSpeed >= ? AND distance >= 8047 AND CAST(totalElevationGain AS FLOAT)/distance*100 >= 2', [18 / 2.23694])),
    ]
    weather = [
        # ── Winter ───────────────────────────────────────────────
        _b('❄️',  'Ice Breaker',    'Ride when temp ≤ 5°C',        _fr('weatherTempC <= 5')),
        _b('🧊', 'Cold Shoulder',  '10 rides when temp ≤ 5°C',    _wc(10,   'weatherTempC <= 5')),
        _b('🌨️',  'Winter Warrior', '50 rides when temp ≤ 5°C',    _wc(50,   'weatherTempC <= 5')),
        _b('🏔️',  'Frozen',         '100 rides when temp ≤ 5°C',   _wc(100,  'weatherTempC <= 5')),
        _b('👑', 'Polar Explorer', '500 rides when temp ≤ 5°C',   _wc(500,  'weatherTempC <= 5')),
        _b('🌟', 'Arctic',         '1,000 rides when temp ≤ 5°C', _wc(1000, 'weatherTempC <= 5')),
        _b('🥶', 'Freeze Warrior', 'Ride when temp ≤ 0°C',        _fr('weatherTempC <= 0')),
        _b('🧊', 'Sub-Zero Club',  '10 rides when temp ≤ 0°C',    _wc(10,  'weatherTempC <= 0')),
        _b('❄️',  'Ice Machine',    '50 rides when temp ≤ 0°C',    _wc(50,  'weatherTempC <= 0')),
        _b('💀', 'Hypothermia?',   '100 rides when temp ≤ 0°C',   _wc(100, 'weatherTempC <= 0')),
        _b('🌨️',  'Deep Freeze',    'Ride when temp ≤ −5°C',       _fr('weatherTempC <= -5')),
        _b('☃️',  'Record Low',
           f'Your coldest ride: {wx_coldest["weatherTempC"]:.1f}°C' if wx_coldest else 'No temp data yet',
           {'earned': bool(wx_coldest),
            'earned_date': wx_coldest['startDateLocal'][:10] if wx_coldest else None,
            'ride_id': wx_coldest['id'] if wx_coldest else None}),
        # ── Summer ───────────────────────────────────────────────
        _b('☀️',  'Sun Seeker',     'Ride when temp ≥ 25°C',       _fr('weatherTempC >= 25')),
        _b('😎', 'Summer Cyclist', '5 rides when temp ≥ 25°C',    _wc(5,  'weatherTempC >= 25')),
        _b('🌞', 'Heat Seeker',    '10 rides when temp ≥ 25°C',    _wc(10,  'weatherTempC >= 25')),
        _b('😎', 'Sun Addict',     '50 rides when temp ≥ 25°C',   _wc(50,  'weatherTempC >= 25')),
        _b('☀️',  'Heatwave Hero',  '100 rides when temp ≥ 25°C',  _wc(100, 'weatherTempC >= 25')),
        _b('🔥', 'Heatwave',       'Ride when temp ≥ 30°C',       _fr('weatherTempC >= 30')),
        _b('🌡️',  'Mad Dog',        'Ride when temp ≥ 35°C',       _fr('weatherTempC >= 35')),
        # ── Rain ─────────────────────────────────────────────────
        _b('🌧️',  'First Drops',    'Ride in the rain',            _fr('(weatherCode BETWEEN 51 AND 67 OR weatherCode BETWEEN 80 AND 82)')),
        _b('☔', 'Rain Regular',   '10 rides in rain',            _wc(10,  '(weatherCode BETWEEN 51 AND 67 OR weatherCode BETWEEN 80 AND 82)')),
        _b('🌊', 'Soggy Cyclist',  '50 rides in rain',            _wc(50,  '(weatherCode BETWEEN 51 AND 67 OR weatherCode BETWEEN 80 AND 82)')),
        _b('💦', 'Waterproof',     '100 rides in rain',           _wc(100, '(weatherCode BETWEEN 51 AND 67 OR weatherCode BETWEEN 80 AND 82)')),
        _b('🌧️',  'British Summer', '500 rides in rain',           _wc(500, '(weatherCode BETWEEN 51 AND 67 OR weatherCode BETWEEN 80 AND 82)')),
        # ── Storm ────────────────────────────────────────────────
        _b('⛈️',  'Storm Chaser',   'Ride during a thunderstorm',  _fr('weatherCode >= 95')),
        _b('🌩️',  'Lightning Rod',  '5 rides in a storm',          _wc(5,  'weatherCode >= 95')),
        _b('🌪️',  'Storm Season',   '10 rides in a storm',         _wc(10, 'weatherCode >= 95')),
        # ── Wind ─────────────────────────────────────────────────
        _b('🌬️',  'Headwind Hero',  'Ride into a 30+ kph headwind', _fr("weatherWindRel='headwind' AND weatherWindKph >= 30")),
        _b('💪', 'Into the Wind',  '10 headwind rides',            _hw(10)),
        _b('😤', 'Wind Warrior',   '50 headwind rides',            _hw(50)),
        _b('⚡', 'Gale Force',     '100 headwind rides',           _hw(100)),
        _b('👑', 'Against the Elements', '1,000 headwind rides',   _hw(1000)),
        _b('💨',  'Record Gale',
           f'Your windiest ride: {round(wx_windiest["weatherGustKph"] or wx_windiest["weatherWindKph"])} kph' if wx_windiest else 'No wind data yet',
           {'earned': bool(wx_windiest),
            'earned_date': wx_windiest['startDateLocal'][:10] if wx_windiest else None,
            'ride_id': wx_windiest['id'] if wx_windiest else None}),
    ]
    def _segment_badges(cls, names):
        """One class's segment badges (services/sports.CLASSES), counted over its family's segments and the rider's efforts of that class on them:
        pedal and e-bike rides share the ride segments but each has its own efforts, PRs and badges; walks, runs and hikes share the foot ones."""
        fam = 'foot' if cls == 'foot' else 'ride'
        keep, keep2 = class_sql(cls), class_sql(cls, 'a2.sportType', 'b2.kind')
        on = ("FROM SegmentEffort e JOIN Segment s ON s.id = e.segmentId AND COALESCE(s.sport, 'ride') = ? JOIN Activity a ON a.id = e.activityId "
              f"LEFT JOIN Bike b ON b.id = a.bikeId WHERE a.riderId = ? AND {keep}")
        args = [fam, rid]
        efforts = query_db(f'SELECT COUNT(*) AS n {on}', args, one=True)['n'] or 0
        prs = query_db(f'SELECT COUNT(*) AS n {on} AND e.isPR = 1', args, one=True)['n'] or 0
        defined = query_db("SELECT COUNT(*) AS n FROM Segment WHERE COALESCE(sport, 'ride') = ?", [fam], one=True)['n'] or 0
        repeats = query_db(f'SELECT MAX(cnt) AS m FROM (SELECT COUNT(*) AS cnt {on} GROUP BY e.segmentId)', args, one=True)['m'] or 0
        fastest = query_db(f'SELECT MAX(e.avgSpeedMps) AS v {on}', args, one=True)['v'] or 0

        def first(extra='', extra_args=(), offset=0):
            row = query_db(f'SELECT a.id, a.startDateLocal {on} {extra} ORDER BY a.startDateLocal LIMIT 1 OFFSET ?', args + list(extra_args) + [offset], one=True)
            return (row['startDateLocal'][:10], row['id']) if row else (None, None)

        def count(n):
            d, i = first(offset=n - 1) if efforts >= n else (None, None)
            return {'earned': efforts >= n, 'earned_date': d, 'ride_id': i, 'progress': efforts, 'target': n}

        def repeat(n):
            d, i = (first('AND e.segmentId IN (SELECT e2.segmentId FROM SegmentEffort e2 JOIN Activity a2 ON a2.id = e2.activityId '
                          f'LEFT JOIN Bike b2 ON b2.id = a2.bikeId WHERE a2.riderId = ? AND {keep2} '
                          'GROUP BY e2.segmentId HAVING COUNT(*) >= ?)', [rid, n], offset=n - 1) if repeats >= n else (None, None))
            return {'earned': repeats >= n, 'earned_date': d, 'ride_id': i, 'progress': repeats, 'target': n}

        def quick(mps):
            d, i = first('AND e.avgSpeedMps >= ?', [mps]) if fastest >= mps else (None, None)
            return {'earned': fastest >= mps, 'earned_date': d, 'ride_id': i}

        n = names
        how = n.get('how', '')
        return ([_b(icon, name, f"{k:,} {n['effort']}{'s' if k != 1 else ''}", count(k)) for (icon, name), k in zip(n['counts'], (1, 10, 50, 100, 250, 500))]
                + [_b('🥇', n['first_pr'], f"Set your first {n['noun']} PR{how}", {'earned': prs >= 1, 'earned_date': None, 'ride_id': None, 'progress': prs, 'target': 1}),
                   _b('👑', n['king'], f"Hold every {n['noun']} PR{how} ({defined} segment{'s' if defined != 1 else ''})",
                      {'earned': defined > 0 and prs >= defined, 'earned_date': None, 'ride_id': None, 'progress': prs, 'target': defined or 1})]
                + [_b(icon, name, f"{n['verb']} the same {n['noun']} {k}+ times{how}", repeat(k)) for (icon, name), k in zip(n['repeats'], (10, 25, 50))]
                + [_b(icon, name, desc, quick(mps)) for icon, name, desc, mps in n['fast']])

    # Pedal rides keep the names and limits the Segments badges always had. E-bike rides race on the same segments for their own PRs, with higher
    # limits; on foot it is pace, not speed.
    _pace = lambda secs_per_mi: units.MI / secs_per_mi
    seg_ride = _segment_badges('bike', {
        'effort': 'segment effort', 'noun': 'segment', 'verb': 'Ride', 'first_pr': 'First PR', 'king': 'King of the Road',
        'counts': [('📐', 'First Effort'), ('🔄', '10 Efforts'), ('💪', '50 Efforts'), ('💯', '100 Efforts'), ('⚡', '250 Efforts'), ('🏆', '500 Efforts')],
        'repeats': [('🔁', 'Creature of Habit'), ('😤', 'Obsessed'), ('🏠', 'Local Legend')],
        'fast': [('💨', 'Segment Flyer', '20 mph avg on a segment', 20 / 2.23694), ('🚀', 'Segment Rocket', '25 mph avg on a segment', 25 / 2.23694),
                 ('💫', 'Segment Missile', '30 mph avg on a segment', 30 / 2.23694), ('👑', 'Flying Machine', '35 mph avg on a segment', 35 / 2.23694)],
    })
    seg_eride = _segment_badges('ebike', {
        'effort': 'e-bike segment effort', 'noun': 'segment', 'how': ' on an e-bike', 'verb': 'Ride', 'first_pr': 'First E-Bike PR', 'king': 'King of the E-Road',
        'counts': [('🔌', 'Plugged In'), ('🔋', '10 E-Efforts'), ('🔋', '50 E-Efforts'), ('⚡', '100 E-Efforts'), ('⚡', '250 E-Efforts'), ('🏆', '500 E-Efforts')],
        'repeats': [('🔁', 'Daily Charge'), ('😤', 'Battery Obsessed'), ('🏠', 'E-Local Legend')],
        'fast': [('💨', 'Turbo Mode', '25 mph avg on a segment (e-bike)', 25 / 2.23694), ('🚀', 'Boost', '30 mph avg on a segment (e-bike)', 30 / 2.23694),
                 ('💫', 'Overdrive', '35 mph avg on a segment (e-bike)', 35 / 2.23694), ('👑', 'Ludicrous Mode', '40 mph avg on a segment (e-bike)', 40 / 2.23694)],
    })
    seg_foot = _segment_badges('foot', {
        'effort': 'foot segment effort', 'noun': 'foot segment', 'verb': 'Walk or run', 'first_pr': 'First Foot PR', 'king': 'King of the Trail',
        'counts': [('👟', 'First Steps'), ('🔄', '10 Foot Efforts'), ('💪', '50 Foot Efforts'), ('💯', '100 Foot Efforts'), ('⚡', '250 Foot Efforts'),
                   ('🏆', '500 Foot Efforts')],
        'repeats': [('🔁', 'Familiar Path'), ('😤', 'Well Trodden'), ('🏠', 'Local Legend on Foot')],
        'fast': [(icon, name, f'{units.fmt_pace(_pace(secs))} avg on a foot segment', _pace(secs))
                 for icon, name, secs in (('🏃', 'Jogger', 600), ('💨', 'Runner', 480), ('🚀', 'Swift', 420), ('👑', 'Flying Feet', 360))],
    })

    return [
        {'name': 'Ride Count',   'badges': ride_count},
        {'name': 'Distance',     'badges': distance},
        {'name': 'Elevation',    'badges': elevation},
        {'name': 'Epic Rides',   'badges': epic_rides},
        {'name': 'Speed',        'badges': speed},
        {'name': 'Climbing',     'badges': climbing},
        {'name': 'Weather',      'badges': weather},
        {'name': 'Segments',            'badges': seg_ride},
        {'name': 'E-Bike Segments',     'badges': seg_eride},
        {'name': 'Segments on Foot',    'badges': seg_foot},
    ] + _sport_badges(rid, _b)


def _sport_badges(rid, _b):
    """The badge categories for the sports other than riding, each shown once the rider has done that sport: Running, Walking & Hiking, Swimming,
    Other Sports (a few for each), and All Sports once they do more than one kind. Counted in Python from one pass over the rider's activities and
    their run and swim best times (services/sport_records), so they add two queries, not one per badge."""
    from services import sport_records, sports, units
    from services.run_stats import MIN_RUN_M, MIN_RUN_S
    acts = [dict(r) for r in query_db('SELECT id, startDateLocal, sportType, distance, movingTime, totalElevationGain FROM Activity '
                                      'WHERE riderId=? ORDER BY startDateLocal, id', [rid])]
    for a in acts:
        a['group'] = sports.stat_group(a['sportType'])
        a['day'] = str(a['startDateLocal'] or '')[:10]
    runs = [a for a in acts if sport_records.kind(a['sportType']) == 'run' and (a['distance'] or 0) >= MIN_RUN_M and (a['movingTime'] or 0) >= MIN_RUN_S]
    walks = [a for a in acts if a['group'] == 'foot' and sport_records.kind(a['sportType']) != 'run']
    swims = [a for a in acts if a['group'] == 'swim']
    times = query_db(f'''SELECT e.kind, e.distanceM, e.elapsedSecs, a.id, a.startDateLocal FROM SportEffort e JOIN Activity a ON a.id = e.activityId
                         WHERE a.riderId=? AND e.distanceM > 0 AND {sport_records.kind_sql('a.sportType')} = e.kind ORDER BY a.startDateLocal''', [rid])

    def at(a):
        return (a['day'], a['id']) if a else (None, None)

    def count(lst, n):
        d, i = at(lst[n - 1]) if len(lst) >= n else (None, None)
        return {'earned': len(lst) >= n, 'earned_date': d, 'ride_id': i, 'progress': len(lst), 'target': n}

    def single(lst, col, value):
        hit = next((a for a in lst if (a[col] or 0) >= value), None)
        d, i = at(hit)
        return {'earned': bool(hit), 'earned_date': d, 'ride_id': i}

    def total(lst, metres, unit_m=units.MI):
        """Distance added up to `metres`; the bar counts in miles / km (unit_m: metres per step, 1000 for swims)."""
        run = 0
        for a in lst:
            run += a['distance'] or 0
            if run >= metres:
                return {'earned': True, 'earned_date': a['day'], 'ride_id': a['id']}
        step = unit_m if unit_m != units.MI else units.spec()['distM']
        return {'earned': False, 'earned_date': None, 'ride_id': None, 'progress': round(run / step), 'target': round(metres / step)}

    def under(k, dist, secs):
        hit = next((t for t in times if t['kind'] == k and t['distanceM'] == dist and t['elapsedSecs'] < secs), None)
        return {'earned': bool(hit), 'earned_date': str(hit['startDateLocal'])[:10] if hit else None, 'ride_id': hit['id'] if hit else None}

    finished = 0.99           # a race the GPS measured a touch short still counts as finished
    cats = []
    if runs:
        cats.append({'name': 'Running', 'badges': [
            *[_b(icon, name, f"{n:,} run{'s' if n != 1 else ''}", count(runs, n)) for icon, name, n in (
                ('👟', 'First Run', 1), ('🎯', 'Getting Going', 10), ('🔥', 'Regular Runner', 50), ('💯', 'Century of Runs', 100),
                ('⚡', 'Dedicated Runner', 250), ('🏆', 'Five Hundred Runs', 500))],
            *[_b(icon, name, f'{label} in one run', single(runs, 'distance', m * finished)) for icon, name, label, m in (
                ('🏅', '5K Finisher', '5 km', 5000), ('🎽', '10K Finisher', '10 km', 10000), ('🥈', 'Half Marathoner', 'A half marathon', 21097.5),
                ('🥇', 'Marathoner', 'A marathon', 42195), ('🦄', 'Ultra Runner', '50 km', 50000))],
            *[_b(icon, name, f'{mi:,} miles run in total', total(runs, mi * units.MI)) for icon, name, mi in (
                ('📍', 'Hundred Miler', 100), ('🗺️', 'Long Haul Runner', 500), ('🌍', 'Thousand Mile Club', 1000), ('🚀', 'Road Warrior', 2500))],
            *[_b(icon, name, desc, under('run', m, secs)) for icon, name, desc, m, secs in (
                ('🐢', '5K Under 30', '5 km in under 30:00', 5000, 1800), ('🏃', '5K Under 25', '5 km in under 25:00', 5000, 1500),
                ('💨', '5K Under 20', '5 km in under 20:00', 5000, 1200), ('⏱️', '10K Under the Hour', '10 km in under 1:00:00', 10000, 3600),
                ('⚡', '10K Under 50', '10 km in under 50:00', 10000, 3000), ('🔥', 'Sub-2 Half', 'A half marathon in under 2:00:00', 21097.5, 7200),
                ('👑', 'Sub-4 Marathon', 'A marathon in under 4:00:00', 42195, 14400))],
        ]})
    if walks:
        cats.append({'name': 'Walking & Hiking', 'badges': [
            *[_b(icon, name, f"{n:,} walk{'s' if n != 1 else ''} or hike{'s' if n != 1 else ''}", count(walks, n)) for icon, name, n in (
                ('🚶', 'Out for a Walk', 1), ('🌳', 'Stroller', 10), ('🥾', 'Rambler', 50), ('🧭', 'Wanderer', 100), ('🏕️', 'Trekker', 250),
                ('🗺️', 'Pathfinder', 500))],
            *[_b(icon, name, f'{mi} miles in one walk or hike', single(walks, 'distance', mi * units.MI)) for icon, name, mi in (
                ('📍', 'Long Walk', 5), ('🌄', 'Big Day Out', 10), ('💪', 'Long Haul', 20), ('🏆', 'Marathon Walker', 26))],
            *[_b(icon, name, f'{ft:,}ft+ on one walk or hike', single(walks, 'totalElevationGain', ft / units.FT_PER_M)) for icon, name, ft in (
                ('⛰️', 'Hill Walker', 1000), ('🏔️', 'Fell Walker', 2000), ('🧗', 'Mountaineer', 3000), ('👑', 'High Peaks', 5000))],
            *[_b(icon, name, f'{mi:,} miles walked in total', total(walks, mi * units.MI)) for icon, name, mi in (
                ('👣', 'Hundred Mile Walker', 100), ('🌍', 'Long Walk Home', 500), ('💎', 'Thousand Mile Walker', 1000))],
        ]})
    if swims:
        cats.append({'name': 'Swimming', 'badges': [
            *[_b(icon, name, f"{n:,} swim{'s' if n != 1 else ''}", count(swims, n)) for icon, name, n in (
                ('💧', 'First Dip', 1), ('🏊', 'Regular Swimmer', 10), ('🐸', 'Water Baby', 25), ('🐟', 'Fish', 50), ('🐬', 'Dolphin', 100))],
            *[_b(icon, name, f'{label} in one swim', single(swims, 'distance', m * finished)) for icon, name, label, m in (
                ('🎯', 'Kilometre Swim', '1 km', 1000), ('🏅', 'Olympic Distance', '1,500 m', 1500), ('🥇', 'Iron Distance', '3.8 km', 3800),
                ('🌊', 'Long Distance', '5 km', 5000), ('👑', 'Marathon Swim', '10 km', 10000))],
            *[_b(icon, name, desc, total(swims, km * 1000, 1000)) for icon, name, desc, km in (
                ('📏', 'Ten K in the Water', '10 km swum in total', 10), ('⛴️', 'Channel Crosser', 'The English Channel (34 km) swum in total', 34),
                ('🌍', 'Hundred K Swimmer', '100 km swum in total', 100), ('🐋', 'Open Ocean', '250 km swum in total', 250))],
            *[_b(icon, name, desc, under('swim', m, secs)) for icon, name, desc, m, secs in (
                ('🐢', 'Steady Stroke', '400 m in under 10:00', 400, 600), ('🏊', 'Smooth Stroke', '400 m in under 8:00', 400, 480),
                ('💨', 'Quick Stroke', '400 m in under 7:00', 400, 420), ('⚡', 'Fast Kilometre', '1 km in under 20:00', 1000, 1200),
                ('🔥', 'Olympic Pace', '1,500 m in under 30:00', 1500, 1800))],
        ]})
    others = {}
    for a in acts:
        if a['group'] not in ('ride', 'foot', 'swim'):
            others.setdefault(sports.label(a['sportType']), []).append(a)
    if others:
        cats.append({'name': 'Other Sports', 'badges': [
            _b(sports.icon(sport), name.format(sport=sport), f"{n:,} session{'s' if n != 1 else ''}", count(lst, n))
            for sport, lst in sorted(others.items()) for name, n in (('First {sport}', 1), ('{sport} Regular', 10), ('{sport} Devotee', 50))]})

    groups = {a['group'] for a in acts}
    if len(groups) > 1:
        def first_day(test):
            """The first day whose activities pass test(set of stat groups), and the activity that made it pass."""
            seen, day = set(), None
            for a in acts:
                if a['day'] != day:
                    seen, day = set(), a['day']
                seen.add(a['group'])
                if test(seen):
                    return {'earned': True, 'earned_date': a['day'], 'ride_id': a['id']}
            return {'earned': False, 'earned_date': None, 'ride_id': None}

        def first_week(n):
            seen, week, best = set(), None, 0
            from datetime import date, timedelta
            for a in acts:
                try:
                    d = date.fromisoformat(a['day'])
                except ValueError:
                    continue
                w = d - timedelta(days=d.weekday())
                if w != week:
                    seen, week = set(), w
                seen.add(a['group'])
                best = max(best, len(seen))
                if len(seen) >= n:
                    return {'earned': True, 'earned_date': a['day'], 'ride_id': a['id'], 'progress': n, 'target': n}
            return {'earned': False, 'earned_date': None, 'ride_id': None, 'progress': best, 'target': n}

        def kinds(n):
            seen = set()
            for a in acts:
                seen.add(a['group'])
                if len(seen) >= n:
                    return {'earned': True, 'earned_date': a['day'], 'ride_id': a['id']}
            return {'earned': False, 'earned_date': None, 'ride_id': None, 'progress': len(seen), 'target': n}

        def hours(h):
            run = 0
            for a in acts:
                run += a['movingTime'] or 0
                if run >= h * 3600:
                    return {'earned': True, 'earned_date': a['day'], 'ride_id': a['id']}
            return {'earned': False, 'earned_date': None, 'ride_id': None, 'progress': round(run / 3600), 'target': h}

        cats.append({'name': 'All Sports', 'badges': [
            _b('🔀', 'Double Day', 'Two kinds of training on the same day', first_day(lambda g: len(g) >= 2)),
            _b('🧱', 'Brick', 'A ride and a run (or walk) on the same day', first_day(lambda g: {'ride', 'foot'} <= g)),
            _b('🔱', 'Triathlete', 'A swim, a ride and a run on the same day', first_day(lambda g: {'swim', 'ride', 'foot'} <= g)),
            _b('🗓️', 'All-Rounder', 'Three kinds of training in one week', first_week(3)),
            _b('🧭', 'Explorer', '5 different kinds of training', kinds(5)),
            _b('🃏', 'Jack of All Trades', '10 different kinds of training', kinds(10)),
            *[_b(icon, name, f'{h:,} hours of training, every sport', hours(h)) for icon, name, h in (
                ('⏱️', 'Hundred Hours', 100), ('⌛', 'Five Hundred Hours', 500), ('🏆', 'Thousand Hours', 1000), ('💎', 'Devotion', 2500),
                ('👑', 'Lifer', 5000))],
        ]})
    return cats


def _avatar_dir():
    return os.environ.get('AVATAR_DIR') or os.path.join(current_app.root_path, 'static', 'avatars')


@bp.route('/riders')
def index():
    from services.rider_mode import multi_rider, owner_rider_id
    if not multi_rider() and owner_rider_id():       # one person per instance: this page is just your profile
        return redirect(url_for('riders.detail', rid=owner_rider_id()))
    riders = query_db('''
        SELECT r.*,
               COUNT(a.id) AS ride_count,
               SUM(a.distance) AS total_dist
        FROM Rider r
        LEFT JOIN Ride a ON a.riderId = r.id
        GROUP BY r.id
        ORDER BY r.isDefault DESC, r.name ASC
    ''')
    return render_template('riders.html', riders=riders)


@bp.route('/riders/<int:rid>')
def detail(rid):
    rider = query_db('SELECT * FROM Rider WHERE id=?', [rid], one=True)
    if not rider:
        abort(404)

    totals = query_db(
        'SELECT COUNT(*) as rides, SUM(distance) as dist, '
        'SUM(totalElevationGain) as elev, SUM(movingTime) as secs, '
        'SUM(calories) as cals FROM Ride WHERE riderId=?',
        [rid], one=True,
    )

    recent = query_db('''
        SELECT id, name, sportType, startDateLocal, distance, movingTime,
               totalElevationGain, averageSpeed
        FROM Ride WHERE riderId=? ORDER BY startDateLocal DESC LIMIT 20
    ''', [rid])

    seg_prs = query_db('''
        SELECT s.name AS seg_name, s.id AS seg_id,
               e.elapsedSecs, e.activityDate, e.avgSpeedMps
        FROM SegmentEffort e
        JOIN Ride a ON a.id = e.activityId
        JOIN Segment s ON s.id = e.segmentId
        WHERE a.riderId=? AND e.isPR=1
        ORDER BY s.name
    ''', [rid])

    effort_rows = query_db('''
        SELECT e.distanceMi, e.elapsedSecs, e.avgSpeedMps, e.activityDate,
               a.name AS rideName, e.activityId
        FROM BestEffort e
        JOIN Ride a ON a.id = e.activityId
        WHERE a.riderId=?
        ORDER BY e.distanceMi, e.elapsedSecs ASC
    ''', [rid])      # the Ride view: BestEffort has rows for anything with a track, and a ski run is not a ride's best 5 miles

    best_by_dist = {}
    for e in effort_rows:
        d = int(e['distanceMi'])
        if d not in best_by_dist:
            best_by_dist[d] = e

    badges = _compute_badges(rid, totals)        # works out any run and swim best times still missing (services/sport_records.ensure)
    from services import sport_records
    sport_bests = []                                # [(heading, [(distance label, effort row, m/s)])] for runs and swims
    for k in ('run', 'swim'):
        got = sport_records.bests(get_db(), rid, k)
        rows = [(label, got[d], d / got[d]['elapsedSecs']) for d, label in sport_records.DISTANCES[k] if d in got]
        if rows:
            sport_bests.append((sport_records.LABELS[k], k, rows))

    from services import gear as gear_svc
    rider_bikes = gear_svc.list_bikes(get_db(), rid)
    return render_template('rider.html', rider=rider, totals=totals, rider_bikes=rider_bikes,
                           recent=recent, seg_prs=seg_prs,
                           best_by_dist=best_by_dist, brackets=BRACKETS_MI, sport_bests=sport_bests,
                           badges=badges)


@bp.route('/riders/<int:rid>/avatar', methods=['POST'])
def upload_avatar(rid):
    import logging
    log = logging.getLogger(__name__)

    rider = query_db('SELECT * FROM Rider WHERE id=?', [rid], one=True)
    if not rider:
        abort(404)

    f = request.files.get('avatar')
    log.warning('Avatar upload rid=%s filename=%r size=%s',
                rid, f.filename if f else None,
                f.content_length if f else None)

    if not f or not f.filename:
        log.warning('Avatar upload aborted: no file or empty filename')
        return redirect(url_for('riders.detail', rid=rid))

    data = f.read()
    if not data:
        log.warning('Avatar upload aborted: file is empty filename=%r mime=%r', f.filename, f.mimetype)
        return redirect(url_for('riders.detail', rid=rid))

    # Detect type from magic bytes — works regardless of extension or MIME type
    if data[:8] == b'\x89PNG\r\n\x1a\n':
        ext = 'png'
    elif data[:3] == b'\xff\xd8\xff':
        ext = 'jpg'
    elif data[:6] in (b'GIF87a', b'GIF89a'):
        ext = 'gif'
    elif data[:4] == b'RIFF' and data[8:12] == b'WEBP':
        ext = 'webp'
    elif b'<svg' in data[:256] or b'<?xml' in data[:64]:
        ext = 'svg'
    else:
        # Fall back to filename extension, then MIME type
        ext = f.filename.rsplit('.', 1)[-1].lower() if '.' in f.filename else ''
        if ext not in _ALLOWED:
            _mime_map = {'image/jpeg': 'jpg', 'image/jpg': 'jpg', 'image/png': 'png',
                         'image/gif': 'gif', 'image/webp': 'webp'}
            ext = _mime_map.get(f.mimetype or '', 'jpg')

    avatar_dir = _avatar_dir()
    os.makedirs(avatar_dir, exist_ok=True)

    # Resize to max 256x256 and save as JPEG regardless of source format
    try:
        from PIL import Image
        import io
        img = Image.open(io.BytesIO(data)).convert('RGB')
        img.thumbnail((256, 256), Image.LANCZOS)
        filename = f'rider_{rid}.jpg'
        save_path = os.path.join(avatar_dir, filename)
        img.save(save_path, 'JPEG', quality=88)
    except Exception as e:
        # Never store the raw upload: an unparseable image may be active content (SVG/HTML) served same-origin
        log.warning('Avatar rejected, not a decodable image: %s', e)
        return redirect(url_for('riders.detail', rid=rid))

    log.info('Avatar saved to %s', save_path)

    db = get_db()
    db.execute('UPDATE Rider SET avatarPath=? WHERE id=?', [filename, rid])
    db.commit()
    log.warning('Avatar DB updated: rid=%s avatarPath=%s', rid, filename)
    return redirect(url_for('riders.detail', rid=rid))


@bp.route('/riders/<int:rid>/edit', methods=['POST'])
def edit(rid):
    name      = (request.form.get('name')     or '').strip()
    ha_device = (request.form.get('haDevice') or '').strip()
    db = get_db()
    if name:
        db.execute('UPDATE Rider SET name=?, haDevice=? WHERE id=?', [name, ha_device or None, rid])
    else:
        db.execute('UPDATE Rider SET haDevice=? WHERE id=?', [ha_device or None, rid])
    db.commit()
    return redirect(url_for('riders.detail', rid=rid))


@bp.route('/riders/<int:rid>/delete', methods=['POST'])
def delete(rid):
    db  = get_db()
    rider = db.execute('SELECT isDefault FROM Rider WHERE id=?', [rid]).fetchone()
    if not rider:
        abort(404)
    if rider['isDefault']:
        abort(400)  # never delete the owner

    # Only this rider's efforts go; other riders' efforts on the same segments stay, and PRs are recomputed
    from services.segments import _refresh_prs
    seg_ids = [r[0] for r in db.execute(
        'SELECT DISTINCT e.segmentId FROM SegmentEffort e JOIN Activity a ON a.id=e.activityId WHERE a.riderId=?', [rid])]
    db.execute('DELETE FROM SegmentEffort WHERE activityId IN (SELECT id FROM Activity WHERE riderId=?)', [rid])
    db.execute('DELETE FROM BestEffort WHERE activityId IN '
               '(SELECT id FROM Activity WHERE riderId=?)', [rid])
    db.execute('DELETE FROM RideMemory WHERE rideId IN '
               '(SELECT id FROM Activity WHERE riderId=?)', [rid])
    db.execute('DELETE FROM SportEffort WHERE activityId IN '
               '(SELECT id FROM Activity WHERE riderId=?)', [rid])          # their run and swim best times
    from services import photos
    photos.delete_for(db, [r[0] for r in db.execute('SELECT id FROM Activity WHERE riderId=?', [rid])], current_app.config['DATABASE'])
    from services import strava_export
    strava_export.forget(db, current_app.config['DATABASE'], rid)                 # their Strava export kept for Import again
    strava_export.forget_read(db, rid)
    from services import goals
    goals.forget_rider(db, rid)
    db.execute('DELETE FROM Activity WHERE riderId=?', [rid])
    db.execute('DELETE FROM Rider WHERE id=?', [rid])
    for sid in seg_ids:
        _refresh_prs(db, sid)
    db.commit()
    return redirect(url_for('riders.index'))


@bp.route('/riders/create', methods=['POST'])
def create():
    from services.rider_mode import multi_rider
    if not multi_rider():
        abort(403)    # one person per instance; set HEADWIND_MULTI_RIDER=1 for the advanced multi-rider mode
    name = (request.form.get('name') or '').strip() or 'New Rider'
    db = get_db()
    db.execute('INSERT INTO Rider (name, isDefault) VALUES (?, 0)', [name])
    db.commit()
    new_id = db.execute('SELECT last_insert_rowid()').fetchone()[0]
    return redirect(url_for('riders.detail', rid=new_id))
