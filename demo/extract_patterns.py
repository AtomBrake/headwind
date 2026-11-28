#!/usr/bin/env python3
"""Take the coordinate-free patterns of a real Headwind database, for the demo's generated data (demo/generate_demo_db.py).

    python3 demo/extract_patterns.py --source /path/to/bike.db --out ~/headwind-demo-build/patterns.json

What comes out is numbers only, per sport: how many activities a year, which months, weekdays and hours they start in, how far and how long they
go, how fast, how hard (heart rate, cadence, power) and how that changes with the gradient. No position, track, name, id, date, setting or token
is written. The streams are read with their positions dropped before anything looks at them, and the result is checked before it's saved:
it may hold only numbers and the sport and field names below.
The database is opened read-only.
"""
import argparse
import json
import math
import os
import sqlite3
import sys
from collections import Counter, defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from services import streams as _streams  # noqa: E402  (after the path)

# the source's sports that the demo's come from (demo/generate_demo_db.py SPORTS says which demo sport takes which)
SPORTS = ('Ride', 'EBikeRide', 'VirtualRide', 'Run', 'Walk', 'Hike', 'Stand Up Paddling', 'Kayaking', 'Swim', 'Workout', 'Yoga', 'Strength')
GRADE_BINS = list(range(-20, 21, 2))          # % gradient, the bin's centre
QS = [i / 20 for i in range(1, 20)]           # 5th to 95th percentile
STREAM_SAMPLE = 150                           # activities per sport whose streams are read, the newest first


def quantiles(values, qs=QS):
    v = sorted(x for x in values if x is not None and not (isinstance(x, float) and math.isnan(x)))
    if len(v) < 3:
        return None
    return [round(v[min(len(v) - 1, int(q * len(v)))], 3) for q in qs]


def median(values):
    v = sorted(values)
    return v[len(v) // 2] if v else None


def windows(st, step_m=50.0):
    """(grade %, speed m/s, hr, cadence, watts) over stretches of about step_m metres of moving, from one activity's streams (positions already gone)."""
    t = (st.get('time') or {}).get('data') or []
    d = (st.get('distance') or {}).get('data') or []
    a = (st.get('altitude') or {}).get('data') or []
    n = min(len(t), len(d))
    if n < 30:
        return
    extra = {k: (st.get(k) or {}).get('data') or [] for k in ('heartrate', 'cadence', 'watts')}
    i = 0
    while i < n - 1:
        j = i + 1
        while j < n - 1 and (d[j] or 0) - (d[i] or 0) < step_m:
            j += 1
        dd, dt = (d[j] or 0) - (d[i] or 0), (t[j] or 0) - (t[i] or 0)
        if dd >= step_m * 0.6 and 0 < dt < 600:
            sp = dd / dt
            grade = ((a[j] - a[i]) / dd * 100) if len(a) > j and a[i] is not None and a[j] is not None else None
            vals = {}
            for k, arr in extra.items():
                seg = [x for x in arr[i:j + 1] if x]
                vals[k] = sum(seg) / len(seg) if seg else None
            yield grade, sp, vals['heartrate'], vals['cadence'], vals['watts']
        i = j


def sport_patterns(src, sport, owner):
    rows = src.execute('SELECT startDateLocal, distance, movingTime, elapsedTime, totalElevationGain, averageHeartrate, maxHeartrate, averageCadence, '
                       'averageWatts, calories FROM Activity WHERE sportType=? AND riderId=? AND startDateLocal IS NOT NULL', [sport, owner]).fetchall()
    if not rows:
        return None
    years, months, weekdays, hours = Counter(), Counter(), Counter(), Counter()
    from datetime import datetime
    for r in rows:
        try:
            dt = datetime.fromisoformat(str(r['startDateLocal'])[:19])
        except ValueError:
            continue
        years[str(dt.year)] += 1
        months[dt.month] += 1
        weekdays[dt.weekday()] += 1
        hours[dt.hour] += 1
    km = lambda r: (r['distance'] or 0) / 1000
    p = {
        'count_by_year': dict(sorted(years.items())),
        'month_weights': [months.get(m, 0) for m in range(1, 13)],
        'weekday_weights': [weekdays.get(w, 0) for w in range(7)],
        'hour_weights': [hours.get(h, 0) for h in range(24)],
        'distance_km_q': quantiles([km(r) for r in rows if km(r) > 0.2]),
        'moving_min_q': quantiles([r['movingTime'] / 60 for r in rows if r['movingTime']]),
        'elapsed_over_moving_q': quantiles([r['elapsedTime'] / r['movingTime'] for r in rows if r['movingTime'] and r['elapsedTime'] and r['elapsedTime'] >= r['movingTime']]),
        'climb_m_per_km_q': quantiles([r['totalElevationGain'] / km(r) for r in rows if km(r) > 1 and r['totalElevationGain'] is not None]),
        'avg_hr_q': quantiles([r['averageHeartrate'] for r in rows if r['averageHeartrate']]),
        'max_hr_q': quantiles([r['maxHeartrate'] for r in rows if r['maxHeartrate']]),
        'avg_cadence_q': quantiles([r['averageCadence'] for r in rows if r['averageCadence']]),
        'avg_watts_q': quantiles([r['averageWatts'] for r in rows if r['averageWatts']]),
        'kcal_per_hour_q': quantiles([r['calories'] / (r['movingTime'] / 3600) for r in rows if r['calories'] and r['movingTime'] and r['movingTime'] > 300]),
        'with_hr': round(sum(1 for r in rows if r['averageHeartrate']) / len(rows), 3),
    }
    # how speed, heart rate, cadence and power go with the gradient, from the newest activities' streams
    bins = defaultdict(lambda: {'speed': [], 'hr': [], 'cadence': [], 'watts': []})
    act_speed, act_hr = [], []
    read = 0
    for r in src.execute(f'SELECT {_streams.sql()} FROM Activity WHERE sportType=? AND riderId=? AND {_streams.has_sql()} ORDER BY startDateLocal DESC LIMIT ?',
                         [sport, owner, STREAM_SAMPLE]):
        try:
            st = json.loads(r['streams'] or '{}')
        except ValueError:
            continue
        st.pop('latlng', None)                                   # never looked at
        read += 1
        sp_all = []
        for grade, sp, hr, cad, w in windows(st):
            if sp < 0.4:
                continue
            sp_all.append(sp)
            if grade is None or abs(grade) > 21:
                continue
            b = bins[min(GRADE_BINS, key=lambda c: abs(c - grade))]
            b['speed'].append(sp)
            for k, v in (('hr', hr), ('cadence', cad), ('watts', w)):
                if v:
                    b[k].append(v)
        if sp_all:
            act_speed.append(median(sp_all))
        hr_all = [x for x in ((st.get('heartrate') or {}).get('data') or []) if x]
        if hr_all:
            act_hr.append(sum(hr_all) / len(hr_all))
    p['streams_read'] = read
    p['by_grade'] = {str(g): {k: (round(median(v), 2) if len(v) >= 20 else None) for k, v in bins[g].items()} | {'n': len(bins[g]['speed'])}
                     for g in GRADE_BINS if bins[g]['speed']}
    # each activity's pace against the sport's typical one: some days are easy, some hard
    mid_sp, mid_hr = median(act_speed), median(act_hr)
    p['day_speed_ratio_q'] = quantiles([s / mid_sp for s in act_speed]) if mid_sp else None
    p['day_hr_offset_q'] = quantiles([h - mid_hr for h in act_hr]) if mid_hr else None
    return p


def check(obj, path='$'):
    """Only numbers, null and the known names: anything else (a string that isn't a field or sport name) fails the extract."""
    allowed = set(SPORTS) | {'n', 'speed', 'hr', 'cadence', 'watts'}
    if isinstance(obj, dict):
        for k, v in obj.items():
            if not (k in allowed or k.lstrip('-').isdigit() or k.replace('_', '').isalpha() and k.islower()):
                raise SystemExit(f'refusing to save: unexpected key {k!r} at {path}')
            check(v, f'{path}.{k}')
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            check(v, f'{path}[{i}]')
    elif not (obj is None or isinstance(obj, (int, float))):
        raise SystemExit(f'refusing to save: a {type(obj).__name__} at {path}')


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--source', required=True, help='a real Headwind database (opened read-only)')
    ap.add_argument('--out', required=True, help='where the patterns go (keep it out of the repo)')
    args = ap.parse_args()
    src = sqlite3.connect(f'file:{os.path.abspath(args.source)}?mode=ro', uri=True, timeout=60)
    src.row_factory = sqlite3.Row
    _streams.register(src)
    owner = src.execute('SELECT id FROM Rider WHERE isDefault=1 ORDER BY id LIMIT 1').fetchone()[0]          # the owner's own, not a friend's
    out = {'version': 1, 'sports': {}}
    for sport in SPORTS:
        p = sport_patterns(src, sport, owner)
        if p:
            out['sports'][sport] = p
            print(f'{sport:18} {sum(p["count_by_year"].values()):5} activities, streams of {p["streams_read"]} read')
    check(out)
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, 'w', encoding='utf-8') as fh:
        json.dump(out, fh, indent=1)
    print(f'wrote {args.out}')


if __name__ == '__main__':
    main()
