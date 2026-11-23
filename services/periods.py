"""What "this week" and "this month" mean, for one rider: the one place that works out a week or a month, so the pages, /api/v1, the goals and
the Home Assistant sensors give the same numbers.

Two ways to count, a per-rider choice in Settings → Display (RiderSettings.periodMode, defaulting to the Settings column of the same name):
  rolling   the past 7 and 28 days: today and the 6 or 27 days before it. Your body doesn't reset on a Monday or the 1st.
  calendar  calendar weeks, starting on the rider's chosen day (weekStart, 0 Monday to 6 Sunday), and calendar months from the 1st.
The year is the calendar year either way. Pages that are calendar by nature (the Nutrition week diary, the badge for the most sport groups in
one week) use calendar weeks in both modes, from the same chosen day: week_first().

"Today" is the home time zone's (services/tz). A request reads its rider's choice with for_request(), through whose; background work (MQTT,
the jobs) is handed its rider and calls prefs(rider_id), and never asks whose."""
from collections import namedtuple
from datetime import date, timedelta

from services.dates import day_month

ROLLING, CALENDAR = 'rolling', 'calendar'
MODES = (ROLLING, CALENDAR)
DAY_NAMES = ('Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday')
KINDS = ('week', 'month', 'year')
ROLLING_DAYS = {'week': 7, 'month': 28}

Prefs = namedtuple('Prefs', 'mode week_start')
DEFAULT = Prefs(ROLLING, 0)          # a new install; one from before the setting keeps calendar weeks from Monday (database step 13)


class Period(namedtuple('Period', 'kind mode first last label dates')):
    """One block of days, first to last inclusive. label is what a person reads for it as the current one ("Past 7 days", "This week",
    "November", "2026"); dates is its days as text ("17–23 Nov", or a calendar week's first day, "17 Nov"), for history and chart bars."""

    @property
    def days(self):
        return (self.last - self.first).days + 1

    def has(self, day):
        return self.first <= day <= self.last

    def sql_range(self):
        """[first, last] as ISO text, for `date(startDateLocal) BETWEEN ? AND ?`."""
        return [self.first.isoformat(), self.last.isoformat()]

    @property
    def short(self):
        """A word or two for a tight space, such as the phone's period picker: "7 days", "Week", "28 days", "Month", "Year"."""
        if self.kind == 'year':
            return 'Year'
        if self.mode == ROLLING:
            return f'{ROLLING_DAYS[self.kind]} days'
        return self.kind.capitalize()

    def as_json(self):
        return {'label': self.label, 'short': self.short, 'dates': self.dates, 'from': self.first.isoformat(), 'to': self.last.isoformat(), 'days': self.days,
                'mode': self.mode}


# ── The rider's choice ──

def _clean(mode, week_start):
    mode = mode if mode in MODES else None
    try:
        week_start = int(week_start) if week_start is not None and 0 <= int(week_start) <= 6 else None
    except (TypeError, ValueError):
        week_start = None
    return mode, week_start


def prefs(rider_id, db=None):
    """The rider's Prefs: their RiderSettings row, then the Settings column of the same name, then DEFAULT. rider_id None: the instance's.
    One statement."""
    if db is None:
        from database import get_db
        db = get_db()
    try:
        row = db.execute('SELECT r.periodMode, r.weekStart, s.periodMode, s.weekStart FROM Settings s '
                         'LEFT JOIN RiderSettings r ON r.riderId=? WHERE s.id=1', [rider_id]).fetchone()
    except Exception:                                   # before step 13 (mid-migration, a script on an old database)
        row = None
    if not row:
        return DEFAULT
    mode, week_start = _clean(row[0], row[1])
    inst_mode, inst_start = _clean(row[2], row[3])
    mode = mode or inst_mode or DEFAULT.mode
    week_start = week_start if week_start is not None else inst_start if inst_start is not None else DEFAULT.week_start
    return Prefs(mode, week_start)


def for_request():
    """The Prefs of the rider the request is about (whose.rider_id), read once a request. Inside a request only."""
    from flask import g
    from services import whose
    rid = whose.rider_id()
    hit = g.get('_period_prefs')
    if hit is None or hit[0] != rid:
        hit = g._period_prefs = (rid, prefs(rid))
    return hit[1]


def resolve(rider_id):
    """for_request() inside a request (the viewer's choice, whichever rider's figures are shown), else prefs(rider_id): for code that runs
    both ways, such as services/goals. Never whose outside a request."""
    from flask import has_request_context
    return for_request() if has_request_context() else prefs(rider_id)


def save(db, rider_id, mode, week_start):
    """Keep the rider's choice in their RiderSettings row (made if they have none). Leaves the other columns alone. Doesn't commit."""
    mode, week_start = _clean(mode, week_start)
    from flask import g, has_app_context
    if has_app_context():
        g.pop('_period_prefs', None)
    db.execute('INSERT INTO RiderSettings (riderId, periodMode, weekStart) VALUES (?,?,?) '
               'ON CONFLICT(riderId) DO UPDATE SET periodMode=excluded.periodMode, weekStart=excluded.weekStart',
               [rider_id, mode or DEFAULT.mode, DEFAULT.week_start if week_start is None else week_start])


# ── Working the days out ──

def _today(today):
    if today is not None:
        return today
    from services import tz
    return tz.today()


def week_first(day, week_start=0):
    """The first day of the calendar week `day` is in, weeks starting on week_start (0 Monday to 6 Sunday)."""
    return day - timedelta(days=(day.weekday() - week_start) % 7)


def _month_last(first):
    nxt = first.replace(year=first.year + 1, month=1) if first.month == 12 else first.replace(month=first.month + 1)
    return nxt - timedelta(days=1)


def day_range(first, last):
    """"17–23 Nov", "28 Oct–3 Nov", "29 Dec 2025–4 Jan 2026"."""
    if first == last:
        return day_month(first)
    if first.year != last.year:
        return f'{first.day} {first:%b %Y}–{last.day} {last:%b %Y}'
    if first.month != last.month:
        return f'{day_month(first)}–{day_month(last)}'
    return f'{first.day}–{day_month(last)}'


def _period(kind, p, first, last, current):
    if kind == 'year':
        return Period(kind, p.mode, first, last, str(first.year), str(first.year))
    if p.mode == ROLLING:
        n = ROLLING_DAYS[kind]
        return Period(kind, p.mode, first, last, f'Past {n} days' if current else day_range(first, last), day_range(first, last))
    if kind == 'week':
        return Period(kind, p.mode, first, last, 'This week' if current else day_month(first), day_month(first))
    return Period(kind, p.mode, first, last, f'{first:%B}' if current else f'{first:%b %Y}', f'{first:%b %Y}')


def _bounds(kind, p, day):
    """(first, last) of the period of `kind` that `day` is in: the calendar one, or for rolling, the block of 7 or 28 days ending on `day`."""
    if kind == 'year':
        return date(day.year, 1, 1), date(day.year, 12, 31)
    if p.mode == ROLLING:
        return day - timedelta(days=ROLLING_DAYS[kind] - 1), day
    if kind == 'week':
        first = week_first(day, p.week_start)
        return first, first + timedelta(days=6)
    first = day.replace(day=1)
    return first, _month_last(first)


def current(kind, p=None, today=None):
    """This week, month or year (kind) as a Period. p: the rider's Prefs (for_request() when None, so inside a request only)."""
    p = p or for_request()
    first, last = _bounds(kind, p, _today(today))
    return _period(kind, p, first, last, True)


def currents(p=None, today=None):
    """{'week': Period, 'month': Period, 'year': Period}."""
    p = p or for_request()
    today = _today(today)
    return {k: current(k, p, today) for k in KINDS}


def blocks(kind, n, p=None, today=None):
    """The last n periods of `kind`, oldest first, the current one last: for history and weekly bars. Rolling blocks are back to back,
    ending today (the last bar is the past 7 days); calendar ones are whole weeks, months or years."""
    p = p or for_request()
    today = _today(today)
    out = [current(kind, p, today)]
    while len(out) < n:
        first, last = _bounds(kind, p, out[0].first - timedelta(days=1))
        out.insert(0, _period(kind, p, first, last, False))
    return out


def find(blocks_, day):
    """The index of the block `day` falls in, or None."""
    for i, b in enumerate(blocks_):
        if b.has(day):
            return i
    return None


def describe(p):
    """The choice in words, for Settings and hints: "the past 7 and 28 days" / "calendar weeks from Monday and calendar months"."""
    return 'the past 7 and 28 days' if p.mode == ROLLING else f'calendar weeks from {DAY_NAMES[p.week_start]} and calendar months'
