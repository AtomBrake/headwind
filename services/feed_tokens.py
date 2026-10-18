"""Feed tokens for friends' instances: one per friend, revocable on its own, each sharing a chosen subset.

A token is shown once when it's made and stored only as a SHA-256 hash (as phone tokens are, services/device_auth.py). Each one
says what it may read: rides, segments, foods, and an optional date window (inclusive, on the ride's local start date).
The single shared token from before (Settings.feedToken) becomes one row that shares everything, so friends already linked keep
syncing until it's revoked.
"""
import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from database import get_db, query_db

PREFIX = 'hwf_'
LEGACY_NAME = 'Shared token (everyone, from before per-friend tokens)'


def _hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def ensure_schema(db):
    db.execute('''
        CREATE TABLE IF NOT EXISTS FeedToken (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            name          TEXT NOT NULL,
            tokenHash     TEXT NOT NULL UNIQUE,
            shareRides    INTEGER DEFAULT 1,
            shareSegments INTEGER DEFAULT 1,
            shareFoods    INTEGER DEFAULT 1,
            sinceDate     TEXT,
            untilDate     TEXT,
            createdAt     TEXT DEFAULT (datetime('now')),
            lastUsedAt    TEXT,
            revokedAt     TEXT
        )
    ''')
    row = db.execute('SELECT feedToken FROM Settings WHERE id=1').fetchone()
    if row and row[0]:
        db.execute('INSERT OR IGNORE INTO FeedToken (name, tokenHash) VALUES (?, ?)', [LEGACY_NAME, _hash(str(row[0]))])
        db.execute('UPDATE Settings SET feedToken=NULL WHERE id=1')


def _date(value):
    """'YYYY-MM-DD' or None; anything else is dropped."""
    value = (value or '').strip()
    try:
        return datetime.strptime(value, '%Y-%m-%d').strftime('%Y-%m-%d') if value else None
    except ValueError:
        return None


def _scope(form):
    since, until = _date(form.get('sinceDate')), _date(form.get('untilDate'))
    if since and until and since > until:
        since, until = until, since
    return [1 if form.get(k) else 0 for k in ('shareRides', 'shareSegments', 'shareFoods')] + [since, until]


def create(name, form):
    token = PREFIX + secrets.token_urlsafe(32)
    db = get_db()
    cur = db.execute('INSERT INTO FeedToken (name, tokenHash, shareRides, shareSegments, shareFoods, sinceDate, untilDate) '
                     'VALUES (?,?,?,?,?,?,?)', [(name or 'Friend').strip()[:60] or 'Friend', _hash(token)] + _scope(form))
    db.commit()
    return token, cur.lastrowid


def update(token_id, form):
    db = get_db()
    db.execute('UPDATE FeedToken SET shareRides=?, shareSegments=?, shareFoods=?, sinceDate=?, untilDate=? WHERE id=?',
               _scope(form) + [token_id])
    db.commit()


def revoke(token_id):
    db = get_db()
    db.execute("UPDATE FeedToken SET revokedAt=datetime('now') WHERE id=? AND revokedAt IS NULL", [token_id])
    db.commit()


def tokens():
    return [dict(r) for r in query_db('SELECT id, name, shareRides, shareSegments, shareFoods, sinceDate, untilDate, '
                                      'createdAt, lastUsedAt, revokedAt FROM FeedToken ORDER BY revokedAt IS NOT NULL, id DESC')]


def lookup(token):
    """The un-revoked FeedToken row for this token, or None. Records last use (at most every five minutes)."""
    if not token:
        return None
    row = query_db('SELECT * FROM FeedToken WHERE tokenHash=? AND revokedAt IS NULL', [_hash(token)], one=True)
    if not row:
        return None
    last = row['lastUsedAt']
    if not last or datetime.now(timezone.utc).replace(tzinfo=None) - datetime.strptime(last, '%Y-%m-%d %H:%M:%S') > timedelta(minutes=5):
        db = get_db()
        db.execute("UPDATE FeedToken SET lastUsedAt=datetime('now') WHERE id=?", [row['id']])
        db.commit()
    return row
