"""The one place distances, climbs, speeds and paces are turned into the rider's units (Settings.units: 'imperial' or 'metric'). Everything is stored in
metres, metres per second and seconds; pages, charts and messages convert on the way out through here (templates through the filters in app.py,
page scripts through window.UNITS from base.html), and form inputs in the rider's units come back in through to_metres()."""
MI = 1609.344
FT_PER_M = 3.28084
MPH_PER_MPS = 2.23694
KMH_PER_MPS = 3.6

_SPEC = {
    'imperial': {'system': 'imperial', 'dist': 'mi', 'distWord': 'miles', 'distM': MI, 'elev': 'ft', 'elevPerM': FT_PER_M, 'speed': 'mph', 'speedPerMps': MPH_PER_MPS, 'pace': '/mi'},
    'metric':   {'system': 'metric',   'dist': 'km', 'distWord': 'kilometres', 'distM': 1000.0, 'elev': 'm', 'elevPerM': 1.0, 'speed': 'km/h', 'speedPerMps': KMH_PER_MPS, 'pace': '/km'},
}


def current():
    """The rider's choice, cached for the request. Outside a request (background jobs, tests without Settings) it falls back to imperial."""
    try:
        from flask import g, has_app_context
        if not has_app_context():
            return 'imperial'
        if not hasattr(g, 'units'):
            from database import query_db
            row = query_db('SELECT units FROM Settings WHERE id=1', one=True)
            g.units = row['units'] if row and row['units'] in _SPEC else 'imperial'
        return g.units
    except Exception:
        return 'imperial'


def spec(system=None):
    return _SPEC.get(system or current(), _SPEC['imperial'])


def dist(m, system=None):
    """Metres -> miles or km (a number)."""
    return float(m or 0) / spec(system)['distM']


def elev(m, system=None):
    return float(m or 0) * spec(system)['elevPerM']


def speed(mps, system=None):
    return float(mps or 0) * spec(system)['speedPerMps']


def to_metres(value, system=None):
    """A distance typed in the rider's unit (a search filter, a form) -> metres. Raises ValueError on rubbish."""
    return float(value) * spec(system)['distM']


def fmt_dist(m, system=None, places=1):
    return f"{dist(m, system):,.{places}f} {spec(system)['dist']}"


def fmt_elev(m, system=None):
    return f"{round(elev(m, system)):,} {spec(system)['elev']}"


def fmt_speed(mps, system=None, places=1):
    return f"{speed(mps, system):,.{places}f} {spec(system)['speed']}"


def fmt_pace(mps, system=None):
    """Metres per second -> pace, e.g. 3.1 -> '8:39 /mi' or '5:23 /km'."""
    if not mps or mps <= 0:
        return '—'
    secs = round(spec(system)['distM'] / mps)
    return f"{secs // 60}:{secs % 60:02d} {spec(system)['pace']}"


def fmt_swim_pace(mps):
    """Metres per second -> time per 100 m, e.g. 0.9 -> '1:51 /100 m'. Pools are measured in metres, so this is the same in both systems."""
    if not mps or mps <= 0:
        return '—'
    secs = round(100 / mps)
    return f"{secs // 60}:{secs % 60:02d} /100 m"


def fmt_rate(mps, style, system=None):
    """Speed, pace or swim pace (services/sports.rate_style)."""
    if style == 'pace':
        return fmt_pace(mps, system)
    if style == 'swim':
        return fmt_swim_pace(mps)
    return fmt_speed(mps, system) if mps else '—'


_IMPERIAL_TEXT = None


def localise(text, system=None):
    """Re-word imperial amounts in a fixed sentence ('25 miles in one ride', '8 mph avg', '500ft+') in the rider's units. Used for text whose limits are
    defined in miles (badges); the limits stay as they are, only the wording changes (rounded: '25 miles' -> '40 km')."""
    global _IMPERIAL_TEXT
    if not text or spec(system)['system'] == 'imperial':
        return text
    import re
    if _IMPERIAL_TEXT is None:
        _IMPERIAL_TEXT = re.compile(r'(\d[\d,]*(?:\.\d+)?)(\+?\s?)(mph|miles?|mi|ft)\b')      # '25 miles', '25+ miles', '500ft+', '8mph'

    def sub(m):
        v, gap, unit = float(m.group(1).replace(',', '')), m.group(2), m.group(3)
        if unit == 'mph':
            return f'{round(v * MI / 1000):,}{gap}km/h'
        if unit == 'ft':
            return f'{round(v / FT_PER_M):,}{gap}m'
        return f'{round(v * MI / 1000):,}{gap}km'
    return _IMPERIAL_TEXT.sub(sub, text)
