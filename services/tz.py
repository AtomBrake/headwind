"""The app's home time zone: what "today" means for nutrition, goals, MQTT and run stats, and how a naive local time (what Garmin gives us) is
read. It is Settings.timeZone, or the server's own zone when that is blank. Installs from before the setting existed were set to Europe/London
when it was added (database.migrate_db), which is what every one of them had been using."""
import os
import time
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError, available_timezones

_CACHE_SECONDS = 30
_cache = {}                 # DB path -> (read at, ZoneInfo)
_pinned = None              # set by a script working on a database outside the app (pin_from)


def server_zone_name():
    """The server's IANA zone name: $TZ, then where /etc/localtime points, then /etc/timezone. UTC when none of them says (a bare Docker
    container: set TZ there, or pick the zone in Settings)."""
    cands = [os.environ.get('TZ', '').lstrip(':')]
    try:
        real = os.path.realpath('/etc/localtime')
        if 'zoneinfo/' in real:
            cands.append(real.split('zoneinfo/', 1)[1])
    except OSError:
        pass
    try:
        with open('/etc/timezone') as f:
            cands.append(f.read().strip())
    except OSError:
        pass
    for name in cands:
        if valid(name):
            return name
    return 'UTC'


def valid(name):
    if not name or name.startswith('/') or '..' in name:
        return False
    try:
        ZoneInfo(name)
        return True
    except (ZoneInfoNotFoundError, ValueError):
        return False


def names():
    """Every zone to offer in Settings, sorted."""
    return sorted(n for n in available_timezones() if '/' in n and not n.startswith(('Etc/', 'SystemV/', 'US/', 'posix/', 'right/'))) + ['UTC']


def _setting():
    from flask import current_app, has_app_context
    if not has_app_context():
        return None, None
    key = current_app.config.get('DATABASE')
    hit = _cache.get(key)
    if hit and time.monotonic() - hit[0] < _CACHE_SECONDS:
        return key, hit[1]
    from database import get_db
    try:
        row = get_db().execute('SELECT timeZone FROM Settings WHERE id=1').fetchone()
        name = row[0] if row else None
    except Exception:                                   # before the column exists (mid-migration)
        name = None
    z = ZoneInfo(name) if valid(name) else None
    _cache[key] = (time.monotonic(), z)
    return key, z


def zone():
    """The home zone as a ZoneInfo."""
    return _pinned or _setting()[1] or ZoneInfo(server_zone_name())


def pin_from(db):
    """For a script with its own sqlite connection (no Flask app): use that database's setting."""
    global _pinned
    try:
        row = db.execute('SELECT timeZone FROM Settings WHERE id=1').fetchone()
    except Exception:
        row = None
    _pinned = ZoneInfo(row[0]) if row and valid(row[0]) else None


def name():
    return zone().key


def now():
    return datetime.now(zone())


def today():
    return now().date()


def forget():
    """Call after saving Settings.timeZone, so the next read sees it."""
    _cache.clear()
