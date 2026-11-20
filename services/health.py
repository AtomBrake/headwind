"""Apple Health as a source of daily health data, beside Garmin: steps, resting heart rate, HRV, sleep, weight, body fat and the day's calories,
sent by the iPhone app (POST /api/v1/health/days) for riders without a Garmin, or with one that isn't worn every day.

Where it's stored (decided 2026-10-25): BodyMetric rows with source 'apple_health', one per day and metric, and weigh-ins in WeightLog. GarminDaily has
the date as its only key, with no rider and no source, so it can't hold a second source. Readers go through the helpers here, which take Garmin's figure
for a day when it has one and Apple Health's otherwise:

  latest_recovery(rid)     the Overview's recovery card: the latest day either source has
  recovery_days(rid, ...)  the AI's recovery block, for a few days up to a ride
  device_burn(rid, day)    the day's total calories from a device: Garmin's total, else Apple's active + resting

Apple's HRV is SDNN from spot readings through the day; Garmin's is overnight RMSSD. The numbers aren't comparable, so Apple's is kept as its own metric,
said to be Apple's ('hrv_kind': 'sdnn') and never compared with Garmin's baseline (GarminDaily.hrvBalanced). Apple has no sleep score or body battery:
those stay empty. Sleep stages come from the same source as the night's hours, never Garmin's total with Apple's stages.

Sending the same day twice is harmless: a metric is replaced, never added to. A manual or Garmin weigh-in, or a body fat from Home Assistant, is never
overwritten by Apple Health's for the same day."""
from datetime import date, timedelta

from database import query_db
from services import tz

SOURCE = 'apple_health'
MAX_ITEMS = 5000                       # one request: a year of every metric, or a backfill sent in batches

# The app's name for a metric -> (BodyMetric metric, unit, lowest, highest). Anything outside the range is a broken reading, and is refused.
METRICS = {
    'steps':       ('steps_health', 'count', 0, 200_000),
    'resting_hr':  ('resting_hr_apple', 'bpm', 20, 200),
    'hrv_sdnn':    ('hrv_sdnn_apple', 'ms', 1, 500),
    'sleep_hours': ('sleep_apple', 'h', 0, 24),
    # A night's stages, from one source (the Watch where there is one), and its time in bed: asleep and awake, gaps between left out
    'sleep_deep':   ('sleep_deep_apple', 'h', 0, 24),
    'sleep_rem':    ('sleep_rem_apple', 'h', 0, 24),
    'sleep_core':   ('sleep_core_apple', 'h', 0, 24),
    'sleep_awake':  ('sleep_awake_apple', 'h', 0, 24),
    'sleep_in_bed': ('sleep_in_bed_apple', 'h', 0, 24),
    'active_kcal': ('active_kcal_apple', 'kcal', 0, 20_000),
    'basal_kcal':  ('basal_kcal_apple', 'kcal', 0, 10_000),
    'body_fat':    ('body_fat', '%', 1, 75),
}
WEIGHT = ('weight_kg', 20, 400)        # into WeightLog, not BodyMetric
SHARED = {'body_fat'}                  # metrics another source also writes: Apple's only fills a day that has none


_GARMIN = ('date, restingHR, hrv, hrvBalanced, sleepHours, sleepScore, bodyBattery, steps, stressScore, '
           'sleepDeep, sleepRem, sleepLight, sleepAwake')


def _day(v):
    try:
        d = date.fromisoformat(str(v)[:10])
    except ValueError:
        return None
    return d if date(2000, 1, 1) <= d <= tz.today() + timedelta(days=1) else None


def save_days(db, rider_id, items):
    """Store a batch of {date, metric, value}. Returns {'saved': n, 'skipped': n, 'errors': [first few reasons]}; raises ValueError when the batch
    itself isn't a list of up to MAX_ITEMS. Doesn't commit."""
    if not isinstance(items, list):
        raise ValueError('days must be a list of {date, metric, value}')
    if len(items) > MAX_ITEMS:
        raise ValueError(f'send at most {MAX_ITEMS} at a time')
    saved = skipped = 0
    errors = []

    def bad(why):
        nonlocal skipped
        skipped += 1
        if len(errors) < 5:
            errors.append(why)

    for it in items:
        if not isinstance(it, dict):
            bad('each item must be an object'); continue
        d, name, value = _day(it.get('date')), it.get('metric'), it.get('value')
        if d is None:
            bad(f'bad date {str(it.get("date"))[:20]!r}'); continue
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            bad(f'{name}: value must be a number'); continue
        if name == WEIGHT[0]:
            if not WEIGHT[1] <= value <= WEIGHT[2]:
                bad(f'{name} out of range'); continue
            # A manual or Garmin weigh-in for the day wins; Apple's own is replaced.
            cur = db.execute('UPDATE WeightLog SET weightKg=? WHERE riderId=? AND logDate=? AND source=?',
                             [round(value, 2), rider_id, d.isoformat(), SOURCE]).rowcount
            if not cur:
                cur = db.execute('INSERT OR IGNORE INTO WeightLog (riderId, logDate, weightKg, source) VALUES (?,?,?,?)',
                                 [rider_id, d.isoformat(), round(value, 2), SOURCE]).rowcount
            saved += 1 if cur else 0
            skipped += 0 if cur else 1
            continue
        spec = METRICS.get(name)
        if not spec:
            bad(f'unknown metric {str(name)[:30]!r}'); continue
        metric, unit, lo, hi = spec
        if not lo <= value <= hi:
            bad(f'{name} out of range'); continue
        only_ours = ' WHERE BodyMetric.source = excluded.source' if name in SHARED else ''
        n = db.execute(f'''INSERT INTO BodyMetric (riderId, logDate, metric, value, unit, source, updatedAt) VALUES (?,?,?,?,?,?, datetime('now'))
                           ON CONFLICT(riderId, logDate, metric) DO UPDATE SET value=excluded.value, unit=excluded.unit, source=excluded.source,
                           updatedAt=excluded.updatedAt{only_ours}''',
                       [rider_id, d.isoformat(), metric, float(value), unit, SOURCE]).rowcount
        saved += 1 if n else 0
        skipped += 0 if n else 1
    return {'saved': saved, 'skipped': skipped, 'errors': errors}


def _apple(rid, since, until=None):
    """{date: {metric: value}} of Apple Health's recovery metrics between two dates (inclusive)."""
    names = [METRICS[k][0] for k in ('resting_hr', 'hrv_sdnn', 'sleep_hours', 'steps', 'sleep_deep', 'sleep_rem', 'sleep_core', 'sleep_awake', 'sleep_in_bed')]
    q = f"SELECT logDate, metric, value FROM BodyMetric WHERE riderId=? AND source=? AND metric IN ({','.join('?' * len(names))}) AND logDate>=?"
    a = [rid, SOURCE, *names, since]
    if until:
        q += ' AND logDate<=?'; a.append(until)
    out = {}
    for r in query_db(q, a):
        out.setdefault(r['logDate'], {})[r['metric']] = r['value']
    return out


def _merge(day, garmin, apple, steps_source='garmin'):
    """One day's recovery from Garmin's row and Apple's metrics: Garmin's figure where it has one, except steps, which come from steps_source alone
    ('garmin' or 'phone', services/steps.py). hrv_kind says whose HRV it is, and source whose figures these are ('garmin', 'apple_health' or both,
    'garmin+apple_health')."""
    g = dict(garmin) if garmin else {}
    a = apple or {}
    used = set()

    def pick(garmin_key, apple_key, cast):
        if g.get(garmin_key):
            used.add('garmin')
            return g[garmin_key]
        if a.get(apple_key):
            used.add(SOURCE)
            return cast(a[apple_key])
        return None

    rhr = pick('restingHR', 'resting_hr_apple', round)
    hrv = pick('hrv', 'hrv_sdnn_apple', round)
    kind = None if hrv is None else ('rmssd' if g.get('hrv') else 'sdnn')
    sleep = pick('sleepHours', 'sleep_apple', lambda v: round(v, 2))
    stages = _stages(g, a)
    steps = (g.get('steps') if steps_source == 'garmin' else int(a.get('steps_health') or 0)) or None
    if any(g.get(k) for k in ('sleepScore', 'bodyBattery', 'stressScore')):
        used.add('garmin')
    return {'date': day, 'restingHR': rhr, 'hrv': hrv, 'hrv_kind': kind, 'hrvBalanced': g.get('hrvBalanced') if kind == 'rmssd' else None,
            'sleepHours': sleep, **stages, 'sleepScore': g.get('sleepScore'), 'bodyBattery': g.get('bodyBattery'), 'steps': steps,
            'stressScore': g.get('stressScore'), 'source': '+'.join(sorted(used)) or None}


def _stages(g, a):
    """The night's stages in hours (sleepDeep, sleepRem, sleepLight: Apple's Core), minutes awake, time in bed and sleep efficiency (asleep ÷ in bed,
    as a percentage), from whichever source gave its hours. Garmin's time in bed is its stages plus awake; Apple's is sent."""
    if g.get('sleepHours'):
        deep, rem, light, awake = (g.get(k) for k in ('sleepDeep', 'sleepRem', 'sleepLight', 'sleepAwake'))
        staged = (deep or 0) + (rem or 0) + (light or 0)
        in_bed = staged + (awake or 0) if staged else None
    elif a.get('sleep_apple'):
        deep, rem, light, awake, in_bed = (a.get(k) for k in ('sleep_deep_apple', 'sleep_rem_apple', 'sleep_core_apple', 'sleep_awake_apple',
                                                              'sleep_in_bed_apple'))
        staged = (deep or 0) + (rem or 0) + (light or 0)
    else:
        deep = rem = light = awake = in_bed = None
        staged = 0
    if staged:
        deep, rem, light = deep or 0, rem or 0, light or 0       # a stage with no minutes that night
    else:
        deep = rem = light = None
    r2 = lambda v: round(v, 2) if v is not None else None
    return {'sleepDeep': r2(deep), 'sleepRem': r2(rem), 'sleepLight': r2(light),
            'sleepAwakeMin': round(awake * 60) if awake is not None and staged else None, 'sleepInBed': r2(in_bed) if staged else None,
            'sleepEfficiency': min(100, round(100 * staged / in_bed)) if staged and in_bed else None}


def latest_recovery(rid):
    """The latest day with recovery data from Garmin or Apple Health, merged (see _merge), or None. The shape of GarminDaily's row as the phone API
    always sent it, plus hrv_kind and source."""
    g = query_db(f'SELECT {_GARMIN} FROM GarminDaily ORDER BY date DESC LIMIT 1', one=True)
    a = query_db("SELECT MAX(logDate) d FROM BodyMetric WHERE riderId=? AND source=? AND metric IN (?,?,?)",
                 [rid, SOURCE, 'resting_hr_apple', 'hrv_sdnn_apple', 'sleep_apple'], one=True)
    a_day = a['d'] if a else None
    if not g and not a_day:
        return None
    day = max(d for d in (g['date'] if g else None, a_day) if d)
    if g and g['date'] != day:
        g = query_db(f'SELECT {_GARMIN} FROM GarminDaily WHERE date=?', [day], one=True)
    from services import steps
    return _merge(day, g, _apple(rid, day, day).get(day), steps.effective_source())


def recovery_days(rid, until, days=3):
    """Merged recovery for each day with any, from `days` days before `until` to `until`, newest first."""
    since = (date.fromisoformat(until) - timedelta(days=days)).isoformat()
    garmin = {r['date']: r for r in query_db(f'SELECT {_GARMIN} FROM GarminDaily WHERE date<=? AND date>=?', [until, since])}
    apple = _apple(rid, since, until)
    from services import steps
    src = steps.effective_source()
    return [_merge(d, garmin.get(d), apple.get(d), src) for d in sorted(set(garmin) | set(apple), reverse=True)]


def device_burn(rid, day):
    """The day's total calories from a device, or None: Garmin's totalCalories, else Apple Health's active plus resting (both needed: active alone
    is far short of the day), with the rider's calorie adjustment applied as it is to Garmin's (services/calorie_adjust). Returns (kcal, label)."""
    g = query_db('SELECT totalCalories FROM GarminDaily WHERE date=?', [day], one=True)
    if g and g['totalCalories']:
        return g['totalCalories'], 'Garmin total'
    rows = {r['metric']: r['value'] for r in query_db('SELECT metric, value FROM BodyMetric WHERE riderId=? AND logDate=? AND source=? AND metric IN (?,?)',
                                                      [rid, day, SOURCE, 'active_kcal_apple', 'basal_kcal_apple'])}
    if not (rows.get('active_kcal_apple') and rows.get('basal_kcal_apple')):
        return None
    from services.calorie_adjust import apply
    return int(round(apply(rows['active_kcal_apple'] + rows['basal_kcal_apple']))), 'Apple Health total'


def summary(rid):
    """What the app's Settings shows: for each metric, the last day Apple Health sent one, and how many days there are."""
    out = {}
    for name, (metric, *_rest) in METRICS.items():
        r = query_db('SELECT MAX(logDate) last, COUNT(*) n FROM BodyMetric WHERE riderId=? AND metric=? AND source=?', [rid, metric, SOURCE], one=True)
        out[name] = {'last': r['last'], 'days': r['n']} if r and r['n'] else None
    r = query_db('SELECT MAX(logDate) last, COUNT(*) n FROM WeightLog WHERE riderId=? AND source=?', [rid, SOURCE], one=True)
    out[WEIGHT[0]] = {'last': r['last'], 'days': r['n']} if r and r['n'] else None
    return out


def delete_all(db, rid):
    """Forget everything Apple Health sent (the app's "Stop sending and remove"). Returns the number of rows removed. Doesn't commit."""
    n = db.execute('DELETE FROM BodyMetric WHERE riderId=? AND source=?', [rid, SOURCE]).rowcount
    return n + db.execute('DELETE FROM WeightLog WHERE riderId=? AND source=?', [rid, SOURCE]).rowcount
