"""What an activity's page shows for its sport (routes/rides.detail, templates/ride.html), worked out from what's stored: the streams, and the
device's laps and a pool swim's lengths (Activity.laps, services/parser.fit_laps).

- view(sport): which page an activity gets. 'ride'; 'foot' (walk, run, hike): pace, splits per mile or km, cadence in steps a minute;
  'swim': pace per 100 m, splits per 100 m, and a pool swim's lengths in sets; 'ski' (downhill): runs and lift time read off the altitude;
  'water' (paddle, surf, sail, row, windsurf): speed, no climbing; 'other'.
- splits(): one row per mile, km or 100 m, from the distance and time streams. The time is moving time, as Strava's splits are: a stop (or a
  pause the device skipped over) isn't in it.
- pace_series(): pace along the activity for the chart, for runs and walks that have no speed stream (most don't).
- pool(): a pool swim's lengths, grouped into sets at each rest.
- ski_runs(): each descent of at least SKI_MIN_DROP_M, and the climbs between them (the lifts)."""
import json

from services import sports, units

VIEWS = ('ride', 'foot', 'swim', 'ski', 'water', 'other')
_DOWNHILL = {'alpineski', 'ski', 'snowboard', 'downhillski', 'resortskiing', 'resortski'}     # 'Ski' is Garmin's, which a cross-country ski can be
SWIM_SPLIT_M = 100
SKI_MIN_DROP_M = 30          # a descent smaller than this is a dip on a run or a flat bit, not a run of its own
SKI_TURN_M = 15              # hysteresis: the altitude has to turn by this much before a run or a climb counts as over (GPS altitude wanders)
_MOVING_MPS = {'foot': 0.3, 'swim': 0.1}
_MIN_PACE_MPS = {'foot': 0.5, 'swim': 0.2}    # slower than this is standing about: left off the pace chart, which would otherwise be all spike


def view(sport):
    if sports.is_ride(sport):
        return 'ride'
    s = ''.join(c for c in (sport or '').lower() if c.isalpha())
    if sports.stat_group(sport) == 'foot':
        return 'foot'
    if 'swim' in s:
        return 'swim'
    if s in _DOWNHILL or 'alpine' in s or 'snowboard' in s:
        return 'ski'
    if sports.on_water(sport) or 'kite' in s:
        return 'water'
    return 'other'


def _data(streams, key):
    return ((streams or {}).get(key) or {}).get('data') or []


def splits(streams, view_, system=None):
    """[{n, dist_m, secs, mps, up_m, down_m, hr}] per mile or km on foot (per 100 m swimming), from the distance and time streams. The last split
    is the part left over, shown when it's at least a tenth of one. [] when the streams don't have both."""
    dist, time = _data(streams, 'distance'), _data(streams, 'time')
    n = min(len(dist), len(time))
    if n < 2:
        return []
    unit = SWIM_SPLIT_M if view_ == 'swim' else units.spec(system)['distM']
    alt, hr = _data(streams, 'altitude'), _data(streams, 'heartrate')
    floor = _MOVING_MPS.get(view_, 0.5)
    out, cur = [], None

    def fresh(start_m):
        return {'start': start_m, 'secs': 0.0, 'up': 0.0, 'down': 0.0, 'hr_sum': 0.0, 'hr_n': 0}

    prev = 0
    while prev < n and dist[prev] is None:
        prev += 1
    if prev >= n:
        return []
    cur = fresh(dist[prev])
    for i in range(prev + 1, n):
        d0, d1, t0, t1 = dist[prev], dist[i], time[prev], time[i]
        if d1 is None or t1 is None or t0 is None:
            continue
        dd, dt = d1 - d0, t1 - t0
        moving = dt if dt > 0 and dd / dt >= floor else 0      # a stop, or a gap the device paused over, isn't moving time
        cur['secs'] += moving
        if i < len(alt) and prev < len(alt) and alt[i] is not None and alt[prev] is not None:
            da = alt[i] - alt[prev]
            cur['up' if da > 0 else 'down'] += abs(da)
        if i < len(hr) and hr[i]:
            cur['hr_sum'] += hr[i]; cur['hr_n'] += 1
        while d1 - cur['start'] >= unit:                   # crossed a split line: the time for the metres past it goes to the next split
            carry = min(cur['secs'], moving * (d1 - cur['start'] - unit) / dd) if dd > 0 else 0
            cur['secs'] -= carry
            out.append(_split_row(len(out) + 1, unit, cur))
            cur = fresh(cur['start'] + unit)
            cur['secs'] = carry
        prev = i
    left = dist[prev] - cur['start'] if dist[prev] is not None else 0
    if left >= unit / 10:
        out.append(_split_row(len(out) + 1, left, cur))
    return out


def _split_row(n, dist_m, cur):
    secs = cur['secs']
    return {'n': n, 'dist_m': round(dist_m, 1), 'secs': round(secs), 'mps': dist_m / secs if secs > 0 else None,
            'up_m': round(cur['up'], 1), 'down_m': round(cur['down'], 1), 'hr': round(cur['hr_sum'] / cur['hr_n']) if cur['hr_n'] else None}


def pace_series(streams, view_, system=None, window_s=30, points=300):
    """{'values': seconds per mile / km (per 100 m swimming), 'labels': distance along it} for the pace chart, from a speed averaged over about
    window_s seconds. None for a gap (standing still). None when the streams have no distance and time."""
    dist, time = _data(streams, 'distance'), _data(streams, 'time')
    n = min(len(dist), len(time))
    if n < 2:
        return None
    unit = SWIM_SPLIT_M if view_ == 'swim' else units.spec(system)['distM']
    slow = _MIN_PACE_MPS.get(view_, 0.5)
    step = max(1, n // points)
    values, labels, j = [], [], 0
    for i in range(0, n, step):
        if dist[i] is None or time[i] is None:
            continue
        while j < i and (time[j] is None or dist[j] is None or time[i] - time[j] > window_s):
            j += 1
        dt = time[i] - time[j] if j < i else 0
        mps = (dist[i] - dist[j]) / dt if dt > 0 else None
        values.append(round(unit / mps) if mps and mps >= slow else None)
        labels.append(round(units.dist(dist[i], system), 2))
    return {'values': values, 'labels': labels} if any(v for v in values) else None


def speed_series(streams, system=None, window_s=10, points=300):
    """{'values': speed in mph or km/h, 'labels': distance along it} from the distance and time streams, for an activity with no speed stream
    (a GPX from Strava has none). None without distance and time."""
    dist, time = _data(streams, 'distance'), _data(streams, 'time')
    n = min(len(dist), len(time))
    if n < 2:
        return None
    step = max(1, n // points)
    values, labels, j = [], [], 0
    for i in range(0, n, step):
        if dist[i] is None or time[i] is None:
            continue
        while j < i and (time[j] is None or dist[j] is None or time[i] - time[j] > window_s):
            j += 1
        dt = time[i] - time[j] if j < i else 0
        values.append(round(units.speed((dist[i] - dist[j]) / dt, system), 1) if dt > 0 else 0)
        labels.append(round(units.dist(dist[i], system), 2))
    return {'values': values, 'labels': labels} if any(values) else None


def load_laps(laps_json):
    try:
        d = json.loads(laps_json) if laps_json else None
    except ValueError:
        return None
    return d if isinstance(d, dict) else None


STROKES = {'freestyle': 'Freestyle', 'backstroke': 'Backstroke', 'breaststroke': 'Breaststroke', 'butterfly': 'Butterfly', 'drill': 'Drill',
           'mixed': 'Mixed', 'im': 'IM'}


def pool(laps):
    """A pool swim's lengths: {'pool_m', 'pool_unit', 'lengths', 'secs', 'rest_secs', 'strokes', 'swolf', 'by_stroke': [(stroke, lengths)],
    'sets': [{n, lengths, dist_m, secs, mps, stroke, strokes_per_length, swolf, rest_after}]}. A set is the lengths swum between two rests.
    SWOLF is a length's seconds plus its strokes (lower is better). None without lengths."""
    lengths = (laps or {}).get('lengths') or []
    pool_m = (laps or {}).get('pool_m')
    active = [x for x in lengths if x.get('active')]
    if not active or not pool_m:
        return None
    sets, cur = [], []
    def close(rest):
        if cur:
            secs = sum(x.get('secs') or 0 for x in cur)
            with_strokes = [x for x in cur if x.get('strokes')]
            kinds = {x.get('stroke') for x in cur if x.get('stroke')}
            spl = sum(x['strokes'] for x in with_strokes) / len(with_strokes) if with_strokes else None
            sets.append({'n': len(sets) + 1, 'lengths': len(cur), 'dist_m': len(cur) * pool_m, 'secs': round(secs),
                         'mps': len(cur) * pool_m / secs if secs else None,
                         'stroke': STROKES.get(kinds.pop(), None) if len(kinds) == 1 else ('Mixed' if kinds else None),
                         'strokes_per_length': round(spl, 1) if spl else None,
                         'swolf': round(secs / len(cur) + spl) if spl else None, 'rest_after': round(rest) if rest else 0})
    for x in lengths:
        if x.get('active'):
            cur.append(x)
        else:
            close(x.get('secs') or 0)
            cur = []
    close(0)
    by = {}
    for x in active:
        k = STROKES.get(x.get('stroke'), 'Unknown')
        by[k] = by.get(k, 0) + 1
    secs = sum(x.get('secs') or 0 for x in active)
    with_strokes = [x for x in active if x.get('strokes')]
    strokes = sum(x['strokes'] for x in with_strokes)
    return {'pool_m': pool_m, 'pool_unit': laps.get('pool_unit') or 'm', 'lengths': len(active), 'dist_m': len(active) * pool_m,
            'secs': round(secs), 'rest_secs': round(sum(x.get('secs') or 0 for x in lengths if not x.get('active'))),
            'strokes': int(strokes) if strokes else None,
            'swolf': round(sum((x.get('secs') or 0) + x['strokes'] for x in with_strokes) / len(with_strokes)) if with_strokes else None,
            'by_stroke': sorted(by.items(), key=lambda kv: -kv[1]), 'sets': sets}


def device_laps(laps):
    """The device's laps (two or more), as stored: [{n, t, secs, dist, mps, hr, maxHr, cad, watts, up, down, strokes, stroke}]."""
    rows = (laps or {}).get('laps') or []
    if len(rows) < 2:
        return []
    out = []
    for i, x in enumerate(rows):
        mps = x.get('mps') or (x['dist'] / x['secs'] if x.get('dist') and x.get('secs') else None)
        out.append(dict(x, n=i + 1, mps=mps, stroke=STROKES.get(x.get('stroke'), x.get('stroke'))))
    return out


def _auto_laps(laps, unit_m):
    """True when every lap but the last is the split distance, within 1%: a device's auto-lap, not laps pressed by hand."""
    return all(abs((x.get('dist') or 0) - unit_m) <= unit_m / 100 for x in laps[:-1])


def _smooth(vals, half=5):
    """A running mean over 2*half+1 points, skipping gaps: GPS altitude jitters by metres from one second to the next."""
    out, n = [], len(vals)
    for i in range(n):
        w = [v for v in vals[max(0, i - half):i + half + 1] if v is not None]
        out.append(sum(w) / len(w) if w else None)
    return out


def _moving_secs(time, dist, lo, hi, floor=1.0):
    total = 0
    for i in range(lo + 1, hi + 1):
        if None in (time[i], time[i - 1], dist[i], dist[i - 1]):
            continue
        dt = time[i] - time[i - 1]
        if dt > 0 and (dist[i] - dist[i - 1]) / dt >= floor:
            total += dt
    return total


def ski_runs(streams):
    """A downhill ski day split into runs and the climbs between them: {'runs': [{n, t, secs (moving), drop_m, dist_m, top_mps, mps}], 'run_secs',
    'lift_secs', 'drop_m', 'longest_m', 'top_mps'}. A run is a descent of at least SKI_MIN_DROP_M; the altitude has to turn by SKI_TURN_M before a
    run or a climb ends, so a short rise mid-run doesn't split it. None without altitude and time, or with no run."""
    alt, time, dist = _data(streams, 'altitude'), _data(streams, 'time'), _data(streams, 'distance')
    n = min(len(alt), len(time))
    if n < 10:
        return None
    vel = _data(streams, 'velocity_smooth')
    a = _smooth(alt[:n])
    idx = [i for i in range(n) if a[i] is not None and time[i] is not None]
    if len(idx) < 10:
        return None
    # Turning points of the altitude, with hysteresis: a zig-zag through the highs and lows.
    turns, direction = [idx[0]], 0
    hi = lo = ext = idx[0]
    for i in idx[1:]:
        if direction == 0:                                           # not yet moving either way: wait for the first turn of SKI_TURN_M
            hi = i if a[i] > a[hi] else hi
            lo = i if a[i] < a[lo] else lo
            if a[hi] - a[i] >= SKI_TURN_M:
                direction, ext = -1, i
                if hi != idx[0]:
                    turns.append(hi)
            elif a[i] - a[lo] >= SKI_TURN_M:
                direction, ext = 1, i
                if lo != idx[0]:
                    turns.append(lo)
        elif direction > 0:                                          # climbing: ext is the highest point so far
            if a[i] > a[ext]:
                ext = i
            elif a[ext] - a[i] >= SKI_TURN_M:
                turns.append(ext)
                direction, ext = -1, i
        else:                                                        # descending: ext is the lowest point so far
            if a[i] < a[ext]:
                ext = i
            elif a[i] - a[ext] >= SKI_TURN_M:
                turns.append(ext)
                direction, ext = 1, i
    if ext != turns[-1]:
        turns.append(ext)
    runs, lift_secs = [], 0
    for lo, hi in zip(turns, turns[1:]):
        secs = time[hi] - time[lo]
        drop = a[lo] - a[hi]
        if drop >= SKI_MIN_DROP_M:
            d = (dist[hi] - dist[lo]) if hi < len(dist) and lo < len(dist) and dist[hi] is not None and dist[lo] is not None else None
            top = max((v for v in vel[lo:hi + 1] if v is not None), default=None) if vel else None
            moving = _moving_secs(time, dist, lo, hi) if d else secs      # a stop on the way down (a lunch, a fall, waiting for friends) isn't skiing
            runs.append({'n': len(runs) + 1, 't': time[lo], 'secs': moving, 'drop_m': round(drop), 'dist_m': d,
                         'top_mps': top, 'mps': d / moving if d and moving else None})
        elif drop < 0:
            lift_secs += secs
    if not runs:
        return None
    return {'runs': runs, 'run_secs': sum(r['secs'] for r in runs), 'lift_secs': lift_secs, 'drop_m': sum(r['drop_m'] for r in runs),
            'longest_m': max((r['dist_m'] or 0) for r in runs), 'top_mps': max((r['top_mps'] or 0) for r in runs) or None}


def for_activity(activity, streams, system=None):
    """Everything the activity page adds for the sport: {'view', 'splits', 'best_split', 'pace', 'pool', 'laps', 'ski'}."""
    v = view(activity['sportType'])
    laps = load_laps(activity['laps'] if 'laps' in activity.keys() else None)
    out = {'view': v, 'splits': [], 'pace': None, 'pool': None, 'laps': device_laps(laps), 'ski': None}
    if v == 'foot':
        out['splits'] = splits(streams, v, system)
        out['pace'] = pace_series(streams, v, system)
    elif v == 'swim':
        out['pool'] = pool(laps)
        if not out['pool']:                                   # open water: splits off the GPS (a pool swim's are its sets)
            out['splits'] = splits(streams, v, system)
        out['pace'] = pace_series(streams, v, system)
    elif v == 'ski':
        out['ski'] = ski_runs(streams)
    if out['splits'] and out['laps'] and _auto_laps(out['laps'], out['splits'][0]['dist_m']):
        out['laps'] = []                                      # the watch's lap every km (or mile) says what the splits already do
    whole = [x for x in out['splits'] if x['mps'] and out['splits'] and x['dist_m'] >= out['splits'][0]['dist_m']]
    out['best_split'] = max(whole, key=lambda x: x['mps']) if len(whole) > 1 else None     # the fastest whole mile or km
    return out
