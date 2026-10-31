"""The "Download diagnostics" zip on the Tasks page: one file to attach to a GitHub issue. It holds the recent log files (services/logs.py), the
version and platform, the settings with anything secret or personal reduced to "set" / "blank", the table row counts and the recent TaskLog rows.

An issue is public, so nothing here may carry a key, password, token, e-mail address, home-network address or body measurement. The logs are
already redacted as they're written; the settings are filtered by column name (PRIVATE) and every text value goes through logs.redact as well."""
import io
import json
import logging
import os
import platform
import re
import sqlite3
import sys
import zipfile
from datetime import datetime, timezone

from services import logs

# Settings columns whose values stay out: credentials, addresses, the person's body and goals. Matched anywhere in the column name.
PRIVATE = re.compile(r'(?i)key|password|token|secret|email|user|url|host|webhook|installid|entity|height|sex|birth|weight|goal|holiday|'
                     r'bmr|kcal|cal(orie)?|protein|carb|fat|sugar|alcohol|water|diet|haWeather')
_EMAIL = re.compile(r'[\w.+-]+@[\w-]+\.[\w.-]+')
# Environment variables worth reporting with their value; any other Headwind-looking one is listed by name only.
_ENV_VALUES = ('LOG_LEVEL', 'LOG_FORMAT', 'LOG_CONSOLE_LEVEL', 'TZ', 'TELEMETRY', 'HEADWIND_MULTI_RIDER', 'HEADWIND_MQTT_NUTRITION',
               'HEADWIND_DEBUG', 'SESSION_COOKIE_SECURE', 'DEMO_MODE', 'PORT')
_ENV_NAMES = ('APP_', 'HEADWIND_', 'LOG_', 'DATABASE_URL', 'SECRET_KEY', 'RIDE_UPLOAD_TOKEN', 'TRUSTED_PROXIES', 'AVATAR_DIR', 'DEMO')


def _clean(v):
    if isinstance(v, str):
        return _EMAIL.sub('<email>', logs.redact(v))
    return v


def settings(db):
    row = db.execute('SELECT * FROM Settings WHERE id=1').fetchone()
    if not row:
        return {}
    return {k: (('set' if row[k] not in (None, '') else 'blank') if PRIVATE.search(k) else _clean(row[k])) for k in row.keys()}


def row_counts(db):
    out = {}
    for (name,) in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"):
        try:
            out[name] = db.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0]
        except sqlite3.Error as e:
            out[name] = f'error: {e}'
    return out


def task_log(db, limit=200):
    rows = db.execute('SELECT * FROM TaskLog ORDER BY id DESC LIMIT ?', [limit]).fetchall()
    return [{k: _clean(r[k]) for k in r.keys()} for r in rows]


def about(database):
    from version import __version__
    build = None
    for p in ('/app/build_time.txt', os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'build_time.txt')):
        try:
            with open(p) as f:
                build = f.read().strip()
            break
        except OSError:
            pass
    try:
        db_bytes = os.path.getsize(database)
    except OSError:
        db_bytes = None
    env = {k: (os.environ[k] if k in _ENV_VALUES else 'set')
           for k in sorted(os.environ) if k in _ENV_VALUES or k.startswith(_ENV_NAMES)}
    return {
        'version': __version__, 'build_time': build, 'generated': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'python': sys.version.split()[0], 'platform': platform.platform(), 'machine': platform.machine(),
        'sqlite': sqlite3.sqlite_version, 'database_bytes': db_bytes, 'docker': os.path.exists('/.dockerenv'),
        'log_level': logging.getLevelName(logs.level()), 'log_file': os.path.basename(logs.file_path()) if logs.file_path() else None,
        'environment': env,
    }


def build_zip(db, database):
    """The zip's bytes."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr('about.json', json.dumps(about(database), indent=2))
        for name, fn in (('settings.json', settings), ('row_counts.json', row_counts), ('task_log.json', task_log)):
            try:
                z.writestr(name, json.dumps(fn(db), indent=2, default=str))
            except Exception as e:                   # a broken table must not stop the rest being collected
                z.writestr(name, json.dumps({'error': str(e)}))
        for path in logs.files():
            z.write(path, f'logs/{os.path.basename(path)}')
        if not logs.files():
            z.writestr('logs/README.txt', 'No log file: LOG_DIR is off or the log folder could not be created. Copy `docker logs headwind` instead.')
    return buf.getvalue()
