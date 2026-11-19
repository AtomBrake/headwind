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
            from services import page_facts
            row = page_facts.get() or query_db('SELECT units FROM Settings WHERE id=1', one=True)
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


def round_metric(v):
    """A metric figure as a limit would be set in it: 40 km rather than 40.2, 150 m rather than 152, 1,600 km rather than 1,609."""
    for below, step in ((10, 1), (50, 5), (200, 10), (2000, 100), (20000, 1000)):
        if v < below:
            return max(step, round(v / step) * step)
    return round(v / 10000) * 10000


# Badges are written in miles, mph and feet. A metric rider's are the round figures the wording shows (localise), and they count against those:
# "40 km in one ride" is earned at 40 km, not at the 40.2 km that 25 miles is.
def limit_dist(mi, system=None):
    """A distance limit given in miles -> metres: that many miles, or the round number of km for a metric rider."""
    return mi * MI if spec(system)['system'] == 'imperial' else round_metric(mi * MI / 1000) * 1000


def limit_elev(ft, system=None):
    """A climb given in feet -> metres: that many feet, or the round number of metres."""
    return ft / FT_PER_M if spec(system)['system'] == 'imperial' else round_metric(ft / FT_PER_M)


def limit_speed(mph, system=None):
    """A speed given in mph -> m/s: that many mph, or the whole km/h nearest it."""
    return mph / MPH_PER_MPS if spec(system)['system'] == 'imperial' else round(mph * MI / 1000) / KMH_PER_MPS


_IMPERIAL_TEXT = None


def localise(text, system=None):
    """Re-word imperial amounts in a fixed sentence ('25 miles in one ride', '8 mph avg', '500ft+') in the rider's units. Used for text whose limits are
    defined in miles (badges, which count against the same figures: limit_dist and the rest), rounded: '25 miles' -> '40 km', '500ft+' -> '150m+'."""
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
            return f'{round_metric(v / FT_PER_M):,}{gap}m'
        return f'{round_metric(v * MI / 1000):,}{gap}km'
    return _IMPERIAL_TEXT.sub(sub, text)


# ---------- weather: stored in °C and km/h (Open-Meteo's), shown with the wind in the rider's speed unit and the temperature in its own choice ----------
TEMP_UNITS = ('C', 'F')          # Settings.tempUnit, apart from units: a UK rider rides in miles and mph and still says 9°C


def temp_unit():
    """'C' or 'F', cached for the request; 'C' outside one."""
    try:
        from flask import g, has_app_context
        if not has_app_context():
            return 'C'
        if not hasattr(g, 'temp_unit'):
            from database import query_db
            from services import page_facts
            row = page_facts.get() or query_db('SELECT tempUnit FROM Settings WHERE id=1', one=True)
            g.temp_unit = row['tempUnit'] if row and row['tempUnit'] in TEMP_UNITS else 'C'
        return g.temp_unit
    except Exception:
        return 'C'


def temp(c, unit=None):
    """°C -> the rider's temperature unit (a number), None for None."""
    if c is None:
        return None
    return float(c) * 9 / 5 + 32 if (unit or temp_unit()) == 'F' else float(c)


def fmt_temp(c, unit=None):
    """'9°C' or '48°F'; '—' for no reading."""
    return '—' if c is None else f"{round(temp(c, unit))}°{unit or temp_unit()}"


def wind(kph, system=None):
    """A wind speed stored in km/h -> mph or km/h (a number)."""
    return speed(float(kph or 0) / KMH_PER_MPS, system)


def fmt_wind(kph, system=None):
    return f"{round(wind(kph, system))} {spec(system)['speed']}"


_WEATHER_TEXT = None


def weather_text(text, system=None, unit=None):
    """A stored weather summary ('Light rain, 9°C, wind 12kph (gusts 30kph)') or a badge's wording ('Ride when temp ≤ −5°C') in the rider's
    units: the figures stay °C and km/h underneath."""
    global _WEATHER_TEXT
    if not text:
        return text
    import re
    if _WEATHER_TEXT is None:                           # '9°C', '−5°C' (a badge's minus sign), '12kph', '30+ kph'
        _WEATHER_TEXT = (re.compile(r'([-−]?\d+(?:\.\d+)?)°C'), re.compile(r'(\d+(?:\.\d+)?)(\+?)\s?kph'))

    def temp_sub(m):
        out = fmt_temp(float(m.group(1).replace('−', '-')), unit)
        return out.replace('-', '−') if '−' in m.group(1) else out
    text = _WEATHER_TEXT[0].sub(temp_sub, text)
    return _WEATHER_TEXT[1].sub(lambda m: f"{round(wind(float(m.group(1)), system))}{m.group(2)} {spec(system)['speed']}", text)
