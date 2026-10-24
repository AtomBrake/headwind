"""Secrets kept in the database (the AI keys, the Home Assistant token, the MQTT password, the feed tokens friends gave us, the Garmin
sign-in) are encrypted with a key kept beside it, in `.secrets_key`, and never in it: a copy of bike.db or a backup shared for
troubleshooting gives none of them away. Not Flask's SECRET_KEY, which can come from the environment and be changed: that would lose every
secret.

A value is stored as `enc:v1:<Fernet token>`. Reading needs nothing: get_db's row factory (row_factory) opens these columns, so code reads
them as before. Writing goes through seal(). A plain value from before is encrypted at the next start (seal_plain). A value this key can't
open (a database restored on another server, without its key) reads as None, as if it had never been entered; unreadable() lists them."""
import logging
import os
import sqlite3
import threading

from cryptography.fernet import Fernet, InvalidToken

log = logging.getLogger(__name__)

PREFIX = 'enc:v1:'
KEY_FILE = '.secrets_key'
COLUMNS = {
    'Settings': ('openaiKey', 'claudeKey', 'haToken', 'mqttPassword', 'garminEmail', 'garminPassword'),
    'Friend':   ('token',),
}
NAMES = frozenset(c for cols in COLUMNS.values() for c in cols)
# what to enter again, and where, when one can't be read
LABELS = {
    'openaiKey':      'the OpenAI API key (Settings → AI)',
    'claudeKey':      'the Claude API key (Settings → AI)',
    'haToken':        'the Home Assistant token (Home Assistant page)',
    'mqttPassword':   'the MQTT password (Settings → MQTT)',
    'garminEmail':    'the Garmin sign-in (Settings → Garmin Connect)',
    'garminPassword': 'the Garmin sign-in (Settings → Garmin Connect)',
}

_lock = threading.Lock()
_keys = {}              # key file path -> Fernet
_warned = set()
_described = {}         # id(cursor.description) -> (description, indexes of secret columns)
_memory_key = Fernet(Fernet.generate_key())   # an in-memory database's: it goes when the process does, and so does the database


def _key_path(db_path):
    return os.path.join(os.path.dirname(os.path.abspath(db_path)), KEY_FILE)


def _fernet(db_path, create=False):
    """The key beside db_path, or None when there is none (create=False) or it can't be read or made. Reading never makes one: a database
    opened somewhere else (a restore being checked, say) mustn't leave a key behind."""
    if not db_path or db_path == ':memory:':
        return _memory_key
    path = _key_path(db_path)
    f = _keys.get(path)
    if f:
        return f
    with _lock:
        if path in _keys:
            return _keys[path]
        try:
            try:
                with open(path, 'rb') as fh:
                    key = fh.read().strip()
            except FileNotFoundError:
                if not create:
                    return None
                key = Fernet.generate_key()
                fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, 'wb') as fh:
                    fh.write(key)
            _keys[path] = Fernet(key)
        except (OSError, ValueError) as e:      # unreadable, or not a key: leave it be, so a fixable fault doesn't lose the secrets
            if path not in _warned:
                _warned.add(path)
                log.error('Could not use the secrets key %s (%s): saved keys and passwords stay as they are', path, e)
            return None
        return _keys[path]


def _db_path():
    from flask import current_app
    return current_app.config['DATABASE']


def seal(value):
    """The value to store for a secret column. Blank stays blank. Without a usable key it's stored as it is, rather than lost."""
    if not value or value.startswith(PREFIX):
        return value
    f = _fernet(_db_path(), create=True)
    if f is None:
        return value
    return PREFIX + f.encrypt(value.encode()).decode()


def _open(value, db_path, column):
    f = _fernet(db_path)
    if f is not None:
        try:
            return f.decrypt(value[len(PREFIX):].encode()).decode()
        except InvalidToken:
            pass
    if column not in _warned:
        _warned.add(column)
        log.warning('The saved %s was encrypted with a key this server does not have (a backup from another server?): enter it again',
                    column)
    return None


def row_factory(db_path):
    """sqlite3.Row, with the secret columns opened. Goes by the name each column is read as: `SELECT haToken AS v` reads it as stored."""
    def factory(cur, row):
        d = cur.description
        seen = _described.get(id(d))
        if seen is None or seen[0] is not d:
            if len(_described) > 4000:
                _described.clear()
            seen = _described[id(d)] = (d, tuple(i for i, c in enumerate(d) if c[0] in NAMES))
        idx = seen[1]
        if idx and any(row[i].__class__ is str and row[i].startswith(PREFIX) for i in idx):
            row = list(row)
            for i in idx:
                if row[i].__class__ is str and row[i].startswith(PREFIX):
                    row[i] = _open(row[i], db_path, d[i][0])
            row = tuple(row)
        return sqlite3.Row(cur, row)
    return factory


def seal_plain(db):
    """Encrypt every secret still stored as it was typed (a database from before, or one written by hand). Returns how many. Commits."""
    if _fernet(_db_path(), create=True) is None:       # logged why
        return 0
    n = 0
    secure = db.execute('PRAGMA secure_delete').fetchone()[0]
    db.execute('PRAGMA secure_delete = ON')            # SQLite leaves a replaced value's bytes in the page unless told to zero them
    try:
        for table, cols in COLUMNS.items():
            for col in cols:
                rows = db.execute(f"SELECT rowid AS r, {col} AS v FROM {table} WHERE {col} <> '' AND {col} NOT LIKE '{PREFIX}%'").fetchall()
                for r in rows:
                    db.execute(f'UPDATE {table} SET {col}=? WHERE rowid=?', [seal(r['v']), r['r']])
                    n += 1
        if n:
            db.commit()
            db.execute('PRAGMA wal_checkpoint(TRUNCATE)')   # into the database file now, and out of the WAL
            log.info('Encrypted %d saved secret%s', n, '' if n == 1 else 's')
    finally:
        db.execute(f'PRAGMA secure_delete = {int(secure)}')
    return n


def unreadable(db):
    """What has to be entered again because this server's key can't open it, in LABELS' words (friends by name), each once."""
    f = _fernet(_db_path())
    out = []

    def bad(v):
        if f is None:
            return True
        try:
            f.decrypt(v[len(PREFIX):].encode())
            return False
        except InvalidToken:
            return True
    for col in COLUMNS['Settings']:
        for r in db.execute(f"SELECT {col} AS v FROM Settings WHERE {col} LIKE '{PREFIX}%'").fetchall():
            if bad(r['v']) and LABELS[col] not in out:
                out.append(LABELS[col])
    for r in db.execute(f"SELECT name, token AS v FROM Friend WHERE token LIKE '{PREFIX}%' ORDER BY name").fetchall():
        if bad(r['v']):
            out.append(f"{r['name']}'s feed token (Friends)")
    return out
