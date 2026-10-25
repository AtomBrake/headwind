from collections import defaultdict
from urllib.parse import urlencode

from flask import Blueprint, g, jsonify, render_template, request, url_for

from database import get_db, query_db
from services.best_efforts import BRACKETS_MI, scan_all_best_efforts
from services.sanity import SANE_SQL

bp = Blueprint('data', __name__)

MONTH_LABELS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
                'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

CLIMBING_BRACKETS_FT = [1000, 2000, 3000, 5000, 8000, 10000]
CLIMBING_BRACKETS_M  = [300, 600, 1000, 1500, 2500, 3000]

# length histogram: (label, low, high) in metres, by stat group (services/sports.stat_group) and the rider's units; seconds when the groups are mixed
HIST_BUCKETS = {
    ('foot', 'imperial'): [('0–2 mi', 0, 3219), ('2–4 mi', 3219, 6437), ('4–7 mi', 6437, 11265), ('7–13 mi', 11265, 20921), ('13–26 mi', 20921, 41843), ('26+ mi', 41843, 9_999_999)],
    ('foot', 'metric'):   [('0–3 km', 0, 3000), ('3–5 km', 3000, 5000), ('5–10 km', 5000, 10000), ('10–21 km', 10000, 21098), ('21–42 km', 21098, 42195), ('42+ km', 42195, 9_999_999)],
    'swim':               [('0–500 m', 0, 500), ('500 m–1 km', 500, 1000), ('1–2 km', 1000, 2000), ('2–3 km', 2000, 3000), ('3–5 km', 3000, 5000), ('5+ km', 5000, 9_999_999)],
    'imperial': [('0–5 mi', 0, 8047), ('5–10 mi', 8047, 16093), ('10–20 mi', 16093, 32187), ('20–30 mi', 32187, 48280), ('30–50 mi', 48280, 80467), ('50+ mi', 80467, 9_999_999)],
    'metric':   [('0–10 km', 0, 10000), ('10–20 km', 10000, 20000), ('20–40 km', 20000, 40000), ('40–60 km', 40000, 60000), ('60–100 km', 60000, 100000), ('100+ km', 100000, 9_999_999)],
}
DURATION_BUCKETS = [('0–30 min', 0, 1800), ('30–60 min', 1800, 3600), ('1–2 h', 3600, 7200), ('2–3 h', 7200, 10800), ('3–5 h', 10800, 18000), ('5+ h', 18000, 9_999_999)]

# the heatmap's colour steps, in metres: about 10, 20 and 30 miles in a day for rides, less on foot and in the water
HEAT_STEPS_M = {'ride': [16093, 32187, 48280], 'foot': [3219, 8047, 16093], 'swim': [1000, 2000, 3000]}

# m/s outside these is a corrupt row, not an activity: (lowest, highest) for speed, pace on foot and swim pace
SPEED_BOUNDS = {'speed': (1.0, 25), 'pace': (0.3, 7), 'swim': (0.2, 2.5)}


@bp.route('/data')
def index():
    all_riders   = query_db('SELECT * FROM Rider ORDER BY isDefault DESC, name')
    owner        = next((r for r in all_riders if r['isDefault']), all_riders[0] if all_riders else None)
    try:
        rid = int(request.args.get('rider') or owner['id'])
    except (TypeError, ValueError):
        rid = owner['id'] if owner else None
    active_rider = query_db('SELECT * FROM Rider WHERE id=?', [rid], one=True) or owner
    rider_args   = [] if not active_rider or active_rider['isDefault'] else [('rider', active_rider['id'])]

    from services import units
    from services.sport_filter import SportFilter, speed_sql
    sf = SportFilter(get_db(), rid, request.args)
    fclause, fparams = sf.sql()
    act_where, act_params = f"riderId=? AND {fclause}", [rid] + fparams       # on Activity: every sport the filter leaves in
    dist_mode = bool(sf.group)        # the sports left in share a distance (services/sports.stat_group); otherwise the charts count time

    # ── Speed (or pace) over time ────────────────────────────────
    # Only for sports that share one: a walk's pace on a line of ride speeds means nothing. The bounds leave out a few corrupt rows (a 3 s moving
    # time against a real distance, from the original 2014/15 Strava import) whose speed otherwise blows out the chart's autoscale.
    speed_labels, speed_values = [], []
    if sf.group:
        lo, hi = SPEED_BOUNDS[sf.style]
        for r in query_db(f"SELECT date(startDateLocal) as d, {speed_sql()} AS mps FROM Activity "
                          f"WHERE {act_where} AND {SANE_SQL} AND {speed_sql()} >= ? AND {speed_sql()} < ? ORDER BY startDateLocal",
                          act_params + [lo, hi]):
            speed_labels.append(r['d'])
            speed_values.append(round(units.speed(r['mps']), 1) if sf.style == 'speed' else
                                round((100 if sf.style == 'swim' else units.spec()['distM']) / r['mps']))      # seconds per mile / km, or per 100 m
    window = 20
    speed_rolling = []
    for i, v in enumerate(speed_values):
        chunk = speed_values[max(0, i - window + 1): i + 1]
        speed_rolling.append(round(sum(chunk) / len(chunk), 2))

    def amount(dist, secs):
        """A month's or a day's total: distance in the rider's unit, or hours when the sports left in don't share a distance."""
        return round(units.dist(dist), 1) if dist_mode else round((secs or 0) / 3600, 1)

    # ── Monthly distance (or time) ───────────────────────────────
    monthly_rows = query_db(
        f"SELECT strftime('%Y-%m', startDateLocal) as ym, SUM(distance) as dist, SUM(movingTime) as secs "
        f"FROM Activity WHERE {act_where} GROUP BY ym ORDER BY ym",
        act_params
    )
    monthly_labels = [r['ym'] for r in monthly_rows]
    monthly_values = [amount(r['dist'], r['secs']) for r in monthly_rows]

    # ── Year-on-year ─────────────────────────────────────────────
    yoy_rows = query_db(
        f"SELECT strftime('%Y', startDateLocal) as yr, "
        f"CAST(strftime('%m', startDateLocal) AS INTEGER) as mo, "
        f"SUM(distance) as dist, SUM(movingTime) as secs FROM Activity WHERE {act_where} GROUP BY yr, mo ORDER BY yr, mo",
        act_params
    )
    year_data = defaultdict(lambda: [0] * 12)
    for r in yoy_rows:
        year_data[r['yr']][int(r['mo']) - 1] = amount(r['dist'], r['secs'])
    year_on_year = {y: year_data[y] for y in sorted(year_data)}

    # ── Length histogram: by distance for one group, by time for several ──
    system = units.spec()['system']
    if dist_mode:
        hist_buckets, hist_col = HIST_BUCKETS.get((sf.group, system)) or HIST_BUCKETS.get(sf.group) or HIST_BUCKETS[system], 'distance'
    else:
        hist_buckets, hist_col = DURATION_BUCKETS, 'movingTime'
    lengths = [r[0] or 0 for r in query_db(f"SELECT {hist_col} FROM Activity WHERE {act_where}", act_params)]
    hist_labels = [label for label, _, _ in hist_buckets]
    hist_values = [sum(1 for v in lengths if lo <= v < hi) for _, lo, hi in hist_buckets]

    # ── Day of week ───────────────────────────────────────────────
    dow_rows = query_db(
        f"SELECT CAST(strftime('%w', startDateLocal) AS INTEGER) as dow, COUNT(*) as n "
        f"FROM Activity WHERE {act_where} GROUP BY dow",
        act_params
    )
    dow_map    = {r['dow']: r['n'] for r in dow_rows}
    dow_labels = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']
    dow_values = [dow_map.get(i, 0) for i in range(7)]

    # ── Calories over time ────────────────────────────────────────
    cal_rows = query_db(
        f"SELECT date(startDateLocal) as d, calories "
        f"FROM Activity WHERE {act_where} AND calories > 0 ORDER BY startDateLocal",
        act_params
    )
    cal_labels = [r['d'] for r in cal_rows]
    cal_values = [int(r['calories']) for r in cal_rows]
    cal_window = 20
    cal_rolling = []
    for i in range(len(cal_values)):
        chunk = cal_values[max(0, i - cal_window + 1): i + 1]
        cal_rolling.append(round(sum(chunk) / len(chunk), 1))

    # ── Heatmap (every day with an activity) ─────────────────────
    heatmap_rows = query_db(
        f"SELECT date(startDateLocal) as d, SUM(distance) as dist, SUM(movingTime) as secs "
        f"FROM Activity WHERE {act_where} GROUP BY d",
        act_params
    )
    if dist_mode:
        heatmap = {r['d']: round(units.dist(r['dist']), 1) for r in heatmap_rows}
        heat_steps = [round(units.dist(m), 1) for m in HEAT_STEPS_M.get(sf.group, HEAT_STEPS_M['ride'])]
        heat_unit = units.spec()['dist']
    else:
        heatmap = {r['d']: round((r['secs'] or 0) / 60) or 1 for r in heatmap_rows}       # minutes; a day with an activity but no time still shows
        heat_steps, heat_unit = [30, 60, 120], 'min'

    # ── Best efforts: rides (services/best_efforts), runs and swims (services/sport_records) ──
    # BestEffort holds a row for anything with a track (skis, walks, ...), so the ride table reads the Ride view: a ski run is not a ride's best 5 miles.
    achievements = []
    if sf.has_rides:
        ride_rows = query_db(f'''SELECT e.distanceMi AS dist, e.activityDate, e.elapsedSecs, e.avgSpeedMps, e.activityId, a.name
                                FROM BestEffort e JOIN Ride a ON a.id = e.activityId
                                WHERE a.riderId=? AND {sf.sql('a.sportType')[0]} ORDER BY e.distanceMi, e.elapsedSecs''', [rid] + fparams)
        achievements.append(_achievements('ride', 'Achievements', 'Ride', 'Avg Speed', 'speed',
                                          [(str(d), units.fmt_dist(d * units.MI, places=0 if system != 'metric' else 1)) for d in BRACKETS_MI],
                                          [dict(r, key=str(int(r['dist']))) for r in ride_rows], scan=True))
    from services import sport_records
    for k, group, title, noun in (('run', 'foot', 'Run best times', 'Run'), ('swim', 'swim', 'Swim best times', 'Swim')):
        if group not in sf.groups:
            continue
        sport_records.ensure(get_db(), rid)
        rows = sport_records.efforts(get_db(), rid, k, sf.sql('a.sportType')[0], fparams)
        if not rows:
            continue
        style = 'pace' if k == 'run' else 'swim'
        achievements.append(_achievements(k, title, noun, 'Pace', style, [(f'{d:g}', label) for d, label in sport_records.DISTANCES[k]],
                                          [dict(r, key=f"{r['distanceM']:g}", avgSpeedMps=r['distanceM'] / r['elapsedSecs']) for r in rows]))
    has_efforts = any(a['rows'] for a in achievements if a['key'] == 'ride')

    # ── Records: each sport's biggest single activities ───────────
    sport_records_by = _sport_records(query_db(
        f"SELECT id, name, sportType, startDateLocal, distance, movingTime, totalElevationGain, {speed_sql()} AS mps "
        f"FROM Activity WHERE {act_where} AND {SANE_SQL}", act_params))

    # ── Climbing records ──────────────────────────────────────────
    metric = units.spec()['system'] == 'metric'
    climb_brackets = CLIMBING_BRACKETS_M if metric else CLIMBING_BRACKETS_FT      # in the rider's unit
    climbing_rows = query_db('''
        SELECT id, name, totalElevationGain, startDateLocal,
               strftime('%Y', startDateLocal) as yr,
               strftime('%Y-%m', startDateLocal) as ym
        FROM Ride
        WHERE riderId=? AND totalElevationGain > 0 AND {ride_clause}
        ORDER BY yr, totalElevationGain DESC
    '''.format(ride_clause=fclause if sf.has_rides else '0'), [rid] + (fparams if sf.has_rides else []))

    climbing_by_year  = defaultdict(lambda: defaultdict(lambda: None))
    climbing_by_month = defaultdict(lambda: defaultdict(lambda: None))
    for r in climbing_rows:
        ft = units.elev(r['totalElevationGain'])      # feet or metres, matching the brackets
        yr, ym = r['yr'], r['ym']
        for b in climb_brackets:
            if ft >= b:
                if climbing_by_year[yr][b] is None:
                    climbing_by_year[yr][b] = {
                        'ft':     round(ft),
                        'ride':   r['name'],
                        'rideId': r['id'],
                        'date':   str(r['startDateLocal'])[:10],
                    }
                if climbing_by_month[ym][b] is None:
                    climbing_by_month[ym][b] = {
                        'ft':     round(ft),
                        'ride':   r['name'],
                        'rideId': r['id'],
                        'date':   str(r['startDateLocal'])[:10],
                    }

    climbing_by_year  = {yr: {str(b): v for b, v in bmap.items() if v} for yr, bmap in climbing_by_year.items()}
    climbing_by_month = {ym: {str(b): v for b, v in bmap.items() if v} for ym, bmap in climbing_by_month.items()}

    # ── Weather performance ───────────────────────────────────────
    # real rides only: a few corrupt old imports (a 3 s moving time against a real distance, or a 0.005-mile blip) give speeds of 2,500 mph or 0.01 mph that blow out the axes
    wx_where = "WHERE riderId=? AND " + SANE_SQL + " AND averageSpeed >= 1.0 AND averageSpeed < 20 AND distance >= 1000 AND weatherTempC IS NOT NULL AND weatherWindKph IS NOT NULL"
    wx_where += f" AND {fclause if sf.has_rides else '0'}"
    wx_params = [rid] + (fparams if sf.has_rides else [])
    weather_scatter = query_db(
        f'''SELECT id, averageSpeed, weatherTempC, weatherWindKph, weatherWindRel, weatherCode,
                  strftime('%m', startDateLocal) as mo
           FROM Ride
           {wx_where}
           ORDER BY startDateLocal''',
        wx_params
    )

    wx_temp_x, wx_temp_y, wx_temp_season, wx_temp_ids = [], [], [], []
    wx_wind_x, wx_wind_y, wx_wind_rel, wx_wind_ids    = [], [], [], []
    wx_cond_buckets = {'Clear': [], 'Cloudy': [], 'Fog': [], 'Rain': [], 'Snow': [], 'Storm': []}

    from services.weather import bucket as _wmo_bucket

    def _season(mo):
        m = int(mo)
        if m in (12, 1, 2):  return 'Winter'
        if m in (3, 4, 5):   return 'Spring'
        if m in (6, 7, 8):   return 'Summer'
        return 'Autumn'

    for r in weather_scatter:
        mph = round(units.speed(r['averageSpeed']), 1)       # in the rider's units, despite the name
        mo  = r['mo'] or '01'

        wx_temp_x.append(round(float(r['weatherTempC']), 1))
        wx_temp_y.append(mph)
        wx_temp_season.append(_season(mo))
        wx_temp_ids.append(r['id'])

        # wind in the same unit as the ride speed
        wind_mph = round(units.speed(float(r['weatherWindKph'] or 0) / 3.6), 1)
        wx_wind_x.append(wind_mph)
        wx_wind_y.append(mph)
        wx_wind_rel.append(r['weatherWindRel'] or 'calm')
        wx_wind_ids.append(r['id'])


    # condition chart: every ride with a condition counts, including ones whose temperature or wind is missing (hand-picked conditions often are)
    cond_where = "WHERE riderId=? AND " + SANE_SQL + " AND averageSpeed >= 1.0 AND averageSpeed < 20 AND distance >= 1000 AND weatherCode IS NOT NULL"
    cond_where += f" AND {fclause if sf.has_rides else '0'}"
    cond_params = [rid] + (fparams if sf.has_rides else [])
    for r in query_db(f'SELECT averageSpeed, weatherCode FROM Ride {cond_where}', cond_params):
        b = _wmo_bucket(r['weatherCode'])
        if b:
            wx_cond_buckets[b].append(round(units.speed(r['averageSpeed']), 1))

    from services.weather import fog_candidates
    wx_fog = fog_candidates(get_db(), rid, (fclause, fparams)) if sf.has_rides else []
    from services import alcohol as _alcohol
    alcohol_recovery = _alcohol.recovery_comparison(get_db(), rid) if (active_rider and active_rider['isDefault']) else None      # Garmin data is the owner's
    from services import storms as _storms
    wx_storm = (_storms.storm_rides(get_db(), rid) + _storms.violent_unnamed(get_db(), rid)) if sf.has_rides else []
    from datetime import datetime as _dt
    from services.dates import day_month_year
    for f in wx_fog:
        f['date'] = day_month_year(_dt.fromisoformat(str(f['startDateLocal'])[:19]))
    for r_ in wx_storm:
        r_['date_txt'] = day_month_year(_dt.fromisoformat(r_['date']))
    wx_cond_labels = list(wx_cond_buckets.keys())
    wx_cond_avgs   = [round(sum(v) / len(v), 2) if v else 0 for v in wx_cond_buckets.values()]
    wx_cond_counts = [len(v) for v in wx_cond_buckets.values()]

    return render_template('data.html',
        speed_labels=speed_labels,
        speed_values=speed_values,
        speed_rolling=speed_rolling,
        monthly_labels=monthly_labels,
        monthly_values=monthly_values,
        year_on_year=year_on_year,
        month_labels=MONTH_LABELS,
        hist_labels=hist_labels,
        hist_values=hist_values,
        dow_labels=dow_labels,
        dow_values=dow_values,
        cal_labels=cal_labels,
        cal_values=cal_values,
        cal_rolling=cal_rolling,
        heatmap=heatmap,
        heat_steps=heat_steps,
        heat_unit=heat_unit,
        dist_mode=dist_mode,
        rides_only_note=sf.has_rides and len(sf.groups) > 1,      # the records and weather sections count the rides in the selection only
        achievements=achievements,
        has_efforts=has_efforts,
        sport_records=sport_records_by,
        climbing_by_year=climbing_by_year,
        climbing_by_month=climbing_by_month,
        climbing_brackets=climb_brackets,
        wx_temp_x=wx_temp_x,
        wx_temp_y=wx_temp_y,
        wx_temp_season=wx_temp_season,
        wx_temp_ids=wx_temp_ids,
        wx_wind_x=wx_wind_x,
        wx_wind_y=wx_wind_y,
        wx_wind_rel=wx_wind_rel,
        wx_wind_ids=wx_wind_ids,
        wx_cond_labels=wx_cond_labels,
        wx_cond_avgs=wx_cond_avgs,
        wx_cond_counts=wx_cond_counts,
        wx_fog=wx_fog,
        alcohol_recovery=alcohol_recovery,
        wx_storm=wx_storm,
        all_riders=all_riders,
        active_rider=active_rider,
        sf=sf,
        sport_links=[(label, icon, url_for('data.index') + '?' + urlencode(rider_args + sf.args(skip)), active) for label, icon, skip, active in sf.shortcuts()],
    )


def _hms(secs):
    secs = int(secs or 0)
    h, m, sec = secs // 3600, secs % 3600 // 60, secs % 60
    return f'{h}:{m:02d}:{sec:02d}' if h else f'{m}:{sec:02d}'


def _achievements(key, title, noun, rate_label, style, distances, rows, scan=False):
    """One best-times table for the Data page: {key, title, noun, rate_label, distances [(key, label)], by_year, by_month, rows, scan}. by_year and
    by_month hold the quickest effort at each distance in that year or month: {period: {distance key: {secs, time, rate, ride, rideId, date}}}.
    `rate` is worded; `mps` is the number behind it.
    `rows` are sorted quickest first within each distance."""
    from services import units
    by_year, by_month = defaultdict(dict), defaultdict(dict)
    for e in rows:
        day = str(e['activityDate'])
        rec = {'secs': e['elapsedSecs'], 'time': _hms(e['elapsedSecs']), 'rate': units.fmt_rate(e['avgSpeedMps'], style) if e['avgSpeedMps'] else '—',
               'mps': e['avgSpeedMps'], 'ride': e['name'] or noun, 'rideId': e['activityId'], 'date': day[:10]}
        by_year[day[:4]].setdefault(e['key'], rec)
        by_month[day[:7]].setdefault(e['key'], rec)
    return {'key': key, 'title': title, 'noun': noun, 'rate_label': rate_label, 'style': style, 'distances': distances, 'by_year': dict(by_year),
            'by_month': dict(by_month), 'rows': len(rows), 'scan': scan}


# the fastest average only counts an activity this long (metres), so a 200 m GPS blip isn't anyone's quickest run
RECORD_MIN_M = {'speed': 1000, 'pace': 1000, 'swim': 100}


def _sport_records(rows):
    """Each sport's biggest single activities, all time and per year: {'all' | 'YYYY': [{sport, icon, dist, time, climb, fast}]}, sports in the
    usual order (rides, on foot, swims, the rest). Each record is {v (worded), n (the number: metres, seconds, m/s), id, name, date}, or None when the sport has nothing to show (a yoga
    session has no distance)."""
    from services import sports, units
    best = defaultdict(dict)        # (period, sport) -> {what: (value, row)}

    def keep(period, sport, what, value, r):
        cur = best[(period, sport)].get(what)
        if value and (cur is None or value > cur[0]):
            best[(period, sport)][what] = (value, r)

    for r in rows:
        sport = sports.label(r['sportType'] or None)
        style = sports.rate_style(r['sportType'] or 'Ride')
        lo, hi = SPEED_BOUNDS[style]
        for period in ('all', str(r['startDateLocal'])[:4]):
            keep(period, sport, 'dist', r['distance'] or 0, r)
            keep(period, sport, 'time', r['movingTime'] or 0, r)
            if sports.has_climbing(r['sportType']):
                keep(period, sport, 'climb', r['totalElevationGain'] or 0, r)
            if r['mps'] and lo <= r['mps'] < hi and (r['distance'] or 0) >= RECORD_MIN_M[style]:
                keep(period, sport, 'fast', r['mps'], r)

    def worded(what, value, sport_type):
        group = sports.stat_group(sport_type or 'Ride')
        if what == 'dist':
            return f'{value:,.0f} m' if group == 'swim' else units.fmt_dist(value)
        if what == 'time':
            return _hms(value)
        if what == 'climb':
            return units.fmt_elev(value)
        return units.fmt_rate(value, sports.rate_style(sport_type or 'Ride'))

    out = defaultdict(list)
    for (period, sport), recs in best.items():
        any_row = next(iter(recs.values()))[1]
        entry = {'sport': sport, 'icon': sports.icon(any_row['sportType'] or 'Ride'),
                 'order': (sports.stat_order(sports.stat_group(any_row['sportType'] or 'Ride')), sport)}
        for what in ('dist', 'time', 'climb', 'fast'):
            v = recs.get(what)
            entry[what] = {'v': worded(what, v[0], v[1]['sportType']), 'n': v[0], 'id': v[1]['id'], 'name': v[1]['name'] or sport,
                           'date': str(v[1]['startDateLocal'])[:10]} if v else None
        out[period].append(entry)
    for period in out:
        out[period].sort(key=lambda e: e.pop('order'))
    return dict(out)


@bp.route('/data/scan-efforts', methods=['POST'])
def scan_efforts():
    db = get_db()
    n = scan_all_best_efforts(db)
    return jsonify({'ok': True, 'scanned': n})
