"""Secrets kept in the database (the AI keys, the Home Assistant token, the MQTT password, the feed tokens friends gave us, the Garmin
sign-in) are encrypted with a key kept beside it, in `.secrets_key`, and never in it: a copy of bike.db or a backup shared for
troubleshooting gives none of them away. Not Flask's SECRET_KEY, which can come from the environment and be changed: that would lose every
secret.

A value is stored as `enc:v1:<Fernet token>`. Reading needs nothing: get_db's row factory (row_factory) opens these columns, so code reads
them as before. Writing goes through seal(). A plain value from before is encrypted at the next start (seal_plain). A value this key can't
open (a database restored on another server, without its key) reads as None, as if it had never been entered; unreadable() lists them.
A backup made with "include the secrets key" carries this key, and restoring it seals them again with the new server's (rekey)."""
import contextlib
import logging
import os
import sqlite3
import threading

from cryptography.fernet import Fernet, InvalidToken

log = logging.getLogger(__name__)

PREFIX = 'enc:v1:'
KEY_FILE = '.secrets_key'
COLUMNS = {
    # feedToken: the shared feed token from before per-friend tokens. services/feed_tokens.py moves it to a FeedToken row and the column is
    # dropped, so it's only ever found in an old copy of the database (seal_copies) or in a restore not yet migrated.
    'Settings': ('openaiKey', 'claudeKey', 'haToken', 'mqttPassword', 'garminEmail', 'garminPassword', 'feedToken', 'thunderforestKey',
                 'osMapsKey'),
    'Friend':   ('token',),
}
# Secrets nothing reads any more: emptied wherever they're found, and dropped from the live database (database._drop_dead_secrets).
# Upstream's Strava API tokens, from before Headwind imported Strava exports instead.
DEAD = {'Athlete': ('accessToken', 'refreshToken')}
NAMES = frozenset(c for cols in COLUMNS.values() for c in cols)
# what to enter again, and where, when one can't be read
LABELS = {
    'openaiKey':      'the OpenAI API key (Settings → AI)',
    'claudeKey':      'the Claude API key (Settings → AI)',
    'haToken':        'the Home Assistant token (Home Assistant page)',
    'mqttPassword':   'the MQTT password (Settings → MQTT)',
    'thunderforestKey': 'the Thunderforest API key (Settings → Maps)',
    'osMapsKey':      'the OS Maps API key (Settings → Maps)',
    'garminEmail':    'the Garmin sign-in (Settings → Garmin Connect)',
    'garminPassword': 'the Garmin sign-in (Settings → Garmin Connect)',
    'feedToken':      'the shared feed token from before per-friend tokens (Friends: give each friend a code of their own)',
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


def present(db, table, cols):
    """Those of cols that `table` has: an older database (a restore, a copy from before) may lack some, or the table."""
    have = {r[1] for r in db.execute(f'PRAGMA table_info({table})').fetchall()}
    return [c for c in cols if c in have]


@contextlib.contextmanager
def secure_delete(db):
    """SQLite leaves a replaced value's bytes in the page unless told to zero them."""
    was = db.execute('PRAGMA secure_delete').fetchone()[0]
    db.execute('PRAGMA secure_delete = ON')
    try:
        yield
    finally:
        db.execute(f'PRAGMA secure_delete = {int(was)}')


def seal_plain(db, where=None):
    """Encrypt every secret still stored as it was typed (a database from before, or one written by hand), and empty the DEAD ones. Returns
    how many. Commits. `where` names a database other than the live one, for the log."""
    if _fernet(_db_path(), create=True) is None:       # logged why
        return 0
    n = 0
    with secure_delete(db):
        for table, cols in COLUMNS.items():
            for col in present(db, table, cols):
                rows = db.execute(f"SELECT rowid AS r, {col} AS v FROM {table} WHERE {col} <> '' AND {col} NOT LIKE '{PREFIX}%'").fetchall()
                for r in rows:
                    db.execute(f'UPDATE {table} SET {col}=? WHERE rowid=?', [seal(r['v']), r['r']])
                    n += 1
        for table, cols in DEAD.items():
            for col in present(db, table, cols):
                n += db.execute(f"UPDATE {table} SET {col}=NULL WHERE {col} <> ''").rowcount
        if n:
            db.commit()
            db.execute('PRAGMA wal_checkpoint(TRUNCATE)')   # into the database file now, and out of the WAL
            log.info('Encrypted or emptied %d saved secret%s%s', n, '' if n == 1 else 's', f' in {where}' if where else '')
    return n


def seal_copies():
    """The same in the copies of the whole database kept beside it: <database>.pre-0.7.0 from before the one-table merge and .pre-restore
    from before a restore, made before their secrets were encrypted, which anyone copying the data folder takes too. Encrypted with this
    server's key, so restoring one here still has them; an older Headwind going back to one needs them entered again. Returns how many."""
    path = os.path.abspath(_db_path())
    folder, base = os.path.split(path)
    n = 0
    for name in sorted(os.listdir(folder)):
        if not name.startswith(base + '.pre-') or name.endswith(('-wal', '-shm', '-journal')):
            continue
        copy = os.path.join(folder, name)
        try:
            conn = sqlite3.connect(copy, timeout=5)
            try:
                conn.row_factory = sqlite3.Row
                if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='Settings'").fetchone():
                    n += seal_plain(conn, where=name)
            finally:
                conn.close()
        except sqlite3.Error as e:          # not a database, or locked: it stays as it is
            log.warning('Could not check %s for saved secrets: %s', name, e)
    return n


def rekey(db, key):
    """Restoring a backup made with its secrets key: open with that key the secrets this server's can't, and seal them again with this
    server's. Returns how many. Commits."""
    try:
        old = Fernet(key.strip())
    except (ValueError, TypeError, AttributeError):
        log.warning('The secrets key in the backup is not a key: its saved keys and passwords stay as they are')
        return 0
    live = _fernet(_db_path(), create=True)
    if live is None:
        return 0
    n = 0
    with secure_delete(db):
        for table, cols in COLUMNS.items():
            for col in present(db, table, cols):
                for r in db.execute(f"SELECT rowid AS r, {col} AS v FROM {table} WHERE {col} LIKE '{PREFIX}%'").fetchall():
                    token = r['v'][len(PREFIX):].encode()
                    try:
                        live.decrypt(token)
                        continue
                    except InvalidToken:
                        pass
                    try:
                        plain = old.decrypt(token)
                    except InvalidToken:
                        continue
                    db.execute(f'UPDATE {table} SET {col}=? WHERE rowid=?', [PREFIX + live.encrypt(plain).decode(), r['r']])
                    n += 1
    db.commit()
    return n


def unseal(value):
    """A value seal() made, opened with this server's key: for what's kept outside the database (the Garmin token file). A value that was
    never sealed comes back as it is; None when this key can't open it."""
    if not value or not value.startswith(PREFIX):
        return value
    return _open(value, _db_path(), 'Garmin token file')


def key_path():
    """This server's key file, for a backup that includes it. None when there's none yet (nothing secret has been saved)."""
    path = _key_path(_db_path())
    return path if os.path.isfile(path) else None


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
    for col in present(db, 'Settings', COLUMNS['Settings']):
        for r in db.execute(f"SELECT {col} AS v FROM Settings WHERE {col} LIKE '{PREFIX}%'").fetchall():
            if bad(r['v']) and LABELS[col] not in out:
                out.append(LABELS[col])
    for r in db.execute(f"SELECT name, token AS v FROM Friend WHERE token LIKE '{PREFIX}%' ORDER BY name").fetchall():
        if bad(r['v']):
            out.append(f"{r['name']}'s feed token (Friends)")
    return out
