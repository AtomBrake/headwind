"""Goals: distance, climbing, time or a count of activities, for the sports picked or for all of them.

A goal is the rider's own target for every week, month or year ("100 mi of riding a week", "50,000 ft of climbing this year", "3 rides or runs a
week"), measured from their activities as they are now, so a deleted or re-typed activity moves it straight away. Nothing is stored but the target
and the sports it counts: Goal.sports, a set of keys as favourites have them (services/favourites.parse_set: 'group:ride' for every kind of ride,
'sport:Run' for runs alone), NULL for every sport (stored_keys). Goal.sport, the one group it was before (database._step_17), is still written, as near as one
group gets, for an older Headwind opening the database. A rider has only the goals they set: none to start with.

The challenges with friends are services/challenges.py; their totals, values and titles are the ones here.
"""
from datetime import date

from services import sports, units

METRICS = ('distance', 'climb', 'time', 'count')
METRIC_LABELS = {'distance': 'Distance', 'climb': 'Climbing', 'time': 'Time', 'count': 'Activities'}
PERIODS = ('week', 'month', 'year')
PERIOD_LABELS = {'week': 'a week', 'month': 'a month', 'year': 'a year'}
ROLLING_PERIOD_LABELS = {'month': 'every 28 days'}    # services/periods.ROLLING
GROUPS = ('ride', 'foot', 'swim', 'all')        # services/sports.stat_group, plus every sport together
GROUP_LABELS = {'ride': 'Rides', 'foot': 'On foot', 'swim': 'Swims', 'all': 'Every sport'}
GROUP_ICONS = {'ride': '🚴', 'foot': '🏃', 'swim': '🏊', 'all': '🏅'}
HISTORY = {'week': 8, 'month': 6, 'year': 4}    # past periods shown under a goal


def ensure_schema(db):
    db.execute('''CREATE TABLE IF NOT EXISTS Goal (
        id        INTEGER PRIMARY KEY AUTOINCREMENT,
        riderId   INTEGER NOT NULL REFERENCES Rider(id),
        metric    TEXT NOT NULL,                  -- METRICS
        period    TEXT NOT NULL,                  -- PERIODS
        sport     TEXT NOT NULL DEFAULT 'all',    -- GROUPS: what an older Headwind counts (_old_group); sports is what counts
        target    REAL NOT NULL,                  -- metres, seconds or a count
        createdAt TEXT DEFAULT (datetime('now')),
        sports    TEXT                            -- services/favourites.parse_set keys, as JSON; NULL: sport's group, 'all' every sport (stored_keys)
    )''')


# ── Values: stored in metres, seconds and counts; typed and shown in the rider's units ──

def to_stored(metric, text):
    """A target typed in the rider's units (miles or km, feet or metres, hours, activities) -> what's stored. Raises ValueError on rubbish or
    on a target that isn't above zero."""
    v = float(str(text).replace(',', '').strip())
    if not v > 0 or v > 1e9:
        raise ValueError(text)
    if metric == 'distance':
        return units.to_metres(v)
    if metric == 'climb':
        return v / units.spec()['elevPerM']
    if metric == 'time':
        return v * 3600
    return round(v)


def to_typed(metric, value):
    """The other way, for a form: a stored target as the number the rider would type."""
    if metric == 'distance':
        return round(units.dist(value), 1)
    if metric == 'climb':
        return round(units.elev(value))
    if metric == 'time':
        return round(value / 3600, 1)
    return int(value)


def fmt(metric, value):
    value = value or 0
    if metric == 'distance':
        return units.fmt_dist(value, places=0 if units.dist(value) >= 100 else 1)
    if metric == 'climb':
        return units.fmt_elev(value)
    if metric == 'time':
        h, m = divmod(int(value) // 60, 60)
        return f'{h:,}h {m:02d}m' if h else f'{m}m'
    n = int(value)
    return f"{n:,} activit{'y' if n == 1 else 'ies'}"


def unit_label(metric):
    return {'distance': units.spec()['dist'], 'climb': units.spec()['elev'], 'time': 'hours', 'count': 'activities'}[metric]


def keys_of(sport):
    """What a goal counts, from a set of keys (a list; anything that isn't one dropped), a challenge's group ('ride', 'all') or None (every
    sport): None for every sport, else the list of keys. An empty list stays empty, for check() to refuse."""
    from services import favourites
    if sport is None or sport == 'all':
        return None
    if isinstance(sport, str):
        return [f'group:{sport}'] if sport in GROUPS else []
    return favourites.parse_set(favourites.dump_set(sport))


def stored_keys(row):
    """What a Goal row counts: its sports, or, where they're NULL, its one group, as a goal an older Headwind added has only that (NULL with
    sport 'all' is every sport)."""
    from services import favourites
    if row['sports'] is None:
        return keys_of(row['sport'] if row['sport'] in GROUPS else 'all')
    return favourites.parse_set(row['sports'])


def _old_group(keys):
    """Goal.sport for an older Headwind: the one group every key is in, else 'all'."""
    from services import favourites
    groups = {favourites.group_of(k) for k in keys or ()}
    return groups.pop() if keys and len(groups) == 1 and next(iter(groups)) in GROUPS else 'all'


def _on(sport):
    """' (rides or runs)' for a title, '' for every sport. sport: keys or a challenge's group."""
    from services import favourites
    keys = keys_of(sport)
    return '' if keys is None else f' ({favourites.nouns(keys)})'


def describe(metric, sport, target=None, period=None, mode=None):
    """'100 mi of distance (rides) a week', 'The most climbing', '3 activities (rides or runs) a week', ... sport: a set of keys (keys_of), a
    challenge's group, or None for every sport. mode 'rolling' (services/periods): a month goal is 'every 28 days'."""
    what = {'distance': 'distance', 'climb': 'climbing', 'time': 'time', 'count': 'activities'}[metric]
    on = _on(sport)
    if target is None:
        return f'The most {what}{on}'
    every = ROLLING_PERIOD_LABELS.get(period) if mode == 'rolling' else None    # a week is 7 days either way
    amount = fmt(metric, target) if metric == 'count' else f'{fmt(metric, target)} of {what}'      # '3 activities', not '3 activities of activities'
    return f"{amount}{on}" + (f' {every or PERIOD_LABELS[period]}' if period else '')


def check(metric, sport, period=None):
    """An error text for a combination that can't be measured, else None. sport: a set of keys, a challenge's group, or None for every sport.
    A distance needs sports whose distances add up, one stat group: a swim's metres never add to a ride's miles (services/sport_filter), nor a
    run's to a ride's. There's no climbing in the water."""
    from services import favourites
    if metric not in METRICS or (isinstance(sport, str) and sport not in GROUPS) or (period is not None and period not in PERIODS):
        return 'Pick what to count, the sport and how often.'
    keys = keys_of(sport)
    if keys == []:
        return 'Pick at least one sport, or every sport.'
    groups = {favourites.group_of(k) for k in keys or ()}
    if metric == 'distance' and (keys is None or len(groups) > 1):
        return ('A distance goal needs sports whose distances add up: rides, or runs and walks, not both. A swim’s or a run’s distance '
                'doesn’t add to a ride’s.')
    if metric == 'climb' and keys is not None:
        if groups == {'swim'}:
            return 'Swims have no climbing.'
        if not any(favourites.group_of(k) in ('ride', 'foot') or sports.has_climbing(k.partition(':')[2]) for k in keys):
            return 'None of those sports has climbing.'
    return None


# ── Totals ──

def _rows(db, rider_id, first, last):
    """(day, sportType, distance, movingTime, climb) of the rider's activities from first to last (dates, inclusive)."""
    return db.execute(f'''SELECT date(startDateLocal), sportType, distance, movingTime, {sports.climb_sql()}
                          FROM Activity WHERE riderId=? AND date(startDateLocal) BETWEEN ? AND ?''',
                      [rider_id, first.isoformat(), last.isoformat()]).fetchall()


def _value(metric, row):
    return {'distance': row[2], 'climb': row[4], 'time': row[3], 'count': 1}[metric] or 0


def _counts(keys, sport_type):
    """Whether an activity of this sport counts towards a goal or challenge of these keys (keys_of)."""
    from services import favourites
    return favourites.covers(keys, sport_type)


def total(db, rider_id, metric, sport, first, last):
    keys = keys_of(sport)
    return sum(_value(metric, r) for r in _rows(db, rider_id, first, last) if _counts(keys, r[1]))


# ── Goals ──

def add_goal(db, rider_id, metric, period, sport, target_text):
    """sport: the keys it counts (a list), a group ('ride') or None / 'all' for every sport. Returns an error text, or None once it's saved.
    Commits."""
    from services import favourites
    err = check(metric, sport, period)
    if err:
        return err
    try:
        target = to_stored(metric, target_text)
    except (TypeError, ValueError):
        return f'Type the target as a number of {unit_label(metric)}.'
    keys = keys_of(sport)
    db.execute('INSERT INTO Goal (riderId, metric, period, sport, sports, target) VALUES (?,?,?,?,?,?)',
               [rider_id, metric, period, _old_group(keys), favourites.dump_set(keys), target])
    db.commit()
    return None


def weekly_count(db, rider_id):
    """The rider's goal of a number of activities each week (the first, if they've set more than one): {id, target, keys, nouns ('rides or
    runs', 'activities' for every sport)}, or None when they have none. Home Assistant's weekly activity sensor and its "looking stagnant" status
    count its sports (services/mqtt, services/insights.activity_status)."""
    from services import favourites
    g = db.execute("SELECT id, target, sport, sports FROM Goal WHERE riderId=? AND metric='count' AND period='week' ORDER BY id LIMIT 1",
                   [rider_id]).fetchone() if rider_id is not None else None
    if not g:
        return None
    keys = stored_keys(g)
    return {'id': g['id'], 'target': int(g['target']), 'keys': keys, 'nouns': favourites.nouns(keys, every='activities')}


def delete_goal(db, rider_id, goal_id):
    db.execute('DELETE FROM Goal WHERE id=? AND riderId=?', [goal_id, rider_id])
    db.commit()


def goals(db, rider_id, today=None, p=None):
    """Each of the rider's goals with where it stands: {id, metric, period, sport, target, title, icon, done, pct, expected (where an even pace
    would be by the end of today), status ('done', 'ahead', 'behind'), to_go, per_day (needed each day left, including today), days_left,
    history [{label, value, pct, hit}] oldest first (the periods before this one), streak (periods hit in a row before this one), period_label}.
    A week and a month are the viewer's (services/periods, p: their Prefs): the past 7 and 28 days, whose only day left is today, or calendar
    ones; the history under a goal is the blocks before, of the same kind."""
    from services import periods, tz
    from services.dates import day_month
    today = today or tz.today()
    p = p or periods.resolve(rider_id)
    out = []
    from services import favourites
    for g in db.execute('SELECT * FROM Goal WHERE riderId=? ORDER BY period, sport, metric, id', [rider_id]).fetchall():
        keys = stored_keys(g)
        blocks = periods.blocks(g['period'], HISTORY[g['period']] + 1, p, today)
        now = blocks[-1]
        first, last = now.first, now.last
        rows = _rows(db, rider_id, blocks[0].first, last)
        sums = [0] * len(blocks)
        for r in rows:
            if _counts(keys, r[1]):
                i = periods.find(blocks, date.fromisoformat(r[0]))
                if i is not None:
                    sums[i] += _value(g['metric'], r)
        done, target = sums[-1], g['target']
        days, days_left = now.days, (last - today).days + 1
        expected = target * (days - days_left + 1) / days
        history = [{'label': b.dates, 'short': day_month(b.first) if p.mode == periods.ROLLING and b.kind != 'year' else b.dates, 'value': v, 'fmt': fmt(g['metric'], v),
                    'pct': min(100, round(100 * v / target)), 'hit': v >= target} for b, v in zip(blocks[:-1], sums[:-1])]
        streak = 0
        for h in reversed(history):
            if not h['hit']:
                break
            streak += 1
        out.append({
            'id': g['id'], 'metric': g['metric'], 'period': g['period'], 'sports': keys, 'target': target,
            'title': describe(g['metric'], keys, target, g['period'], p.mode), 'icon': favourites.icons(keys),
            'done': done, 'done_fmt': fmt(g['metric'], done), 'target_fmt': fmt(g['metric'], target),
            'pct': min(100, round(100 * done / target)), 'expected_pct': min(100, round(100 * expected / target)),
            'status': 'done' if done >= target else ('ahead' if done >= expected else 'behind'),
            'to_go_fmt': fmt(g['metric'], max(0, target - done)),
            'per_day_fmt': fmt(g['metric'], max(0, target - done) / days_left) if g['metric'] != 'count' else None,
            'days_left': days_left, 'history': history, 'streak': streak,
            'period_label': now.label, 'period_dates': now.dates, 'rolling': p.mode == periods.ROLLING and g['period'] != 'year',
        })
    return out


def forget_rider(db, rider_id):
    """A rider deleted: their goals go, and their challenges with them (services/challenges.forget_rider). Does not commit."""
    db.execute('DELETE FROM Goal WHERE riderId=?', [rider_id])
    from services import challenges
    challenges.forget_rider(db, rider_id)
