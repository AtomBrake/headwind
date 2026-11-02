"""A day's step count comes from ONE source: Garmin, or the phone (Apple Health, the Android app's Health Connect, a watch that feeds Home Assistant).
Never the highest of several: a phone counts pedalling as steps (a 40-mile ride can add 15,000), so it won every ride day. Idea from upstream 0.9.0.

* `Settings.stepsSource`: 'garmin', 'phone', or NULL for automatic: Garmin when it has given steps on AUTO_MIN of the last AUTO_DAYS days, otherwise
  the phone. A bike computer gives no steps, so riding with one leaves the phone counting.
* A number typed on the Steps page (`steps_manual`) is a correction and wins for its day.
* When the chosen source has nothing for a day the count is 0, never a number borrowed from the other source.
"""
from database import query_db

SOURCES = ('auto', 'garmin', 'phone')
PHONE_METRICS = (('steps_health', 'Apple Health'), ('steps_phone', 'Phone'), ('steps_watch', 'Watch'))   # the first with a value
AUTO_DAYS = 14
AUTO_MIN = 5


def configured():
    """'auto', 'garmin' or 'phone', as chosen on the Steps page."""
    r = query_db('SELECT stepsSource FROM Settings WHERE id=1', one=True)
    v = ((r['stepsSource'] if r else None) or 'auto').lower()
    return v if v in SOURCES else 'auto'


def effective_source():
    """'garmin' or 'phone': the chosen source, with automatic worked out."""
    c = configured()
    if c != 'auto':
        return c
    n = query_db("SELECT COUNT(*) n FROM GarminDaily WHERE steps > 0 AND date >= date('now', ?)", [f'-{AUTO_DAYS} days'], one=True)['n']
    return 'garmin' if n >= AUTO_MIN else 'phone'


def _metric(rid, day_iso, metric):
    m = query_db('SELECT value FROM BodyMetric WHERE riderId=? AND logDate=? AND metric=?', [rid, day_iso, metric], one=True)
    return int(m['value']) if m and m['value'] else None


def steps_for(rid, day_iso, garmin_steps=None, source=None):
    """(steps, label) for a day: label is 'Manual', 'Garmin', 'Apple Health', 'Phone' or 'Watch', or None when there's nothing (steps 0).
    garmin_steps saves a query when the caller has GarminDaily's figure already; source saves working out automatic again for every day of a list."""
    manual = _metric(rid, day_iso, 'steps_manual')
    if manual:
        return manual, 'Manual'
    if (source or effective_source()) == 'garmin':
        if garmin_steps is None:
            g = query_db('SELECT steps FROM GarminDaily WHERE date=?', [day_iso], one=True)
            garmin_steps = g['steps'] if g else None
        return (int(garmin_steps), 'Garmin') if garmin_steps else (0, None)
    for metric, label in PHONE_METRICS:
        v = _metric(rid, day_iso, metric)
        if v:
            return v, label
    return 0, None
