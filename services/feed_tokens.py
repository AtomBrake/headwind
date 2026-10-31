"""Feed tokens for friends' instances: one per friend, revocable on its own, each sharing a chosen subset.

A token is shown once when it's made and stored only as a SHA-256 hash (as phone tokens are, services/device_auth.py). Each one
says what it may read: rides, segments, foods, and an optional date window (inclusive, on the ride's local start date).
The single shared token from before (Settings.feedToken) becomes one row that shares everything, so friends already linked keep
syncing until it's revoked.

A new token is also given as a share code: our address and the token in one string, for the friend to paste, or as a
headwind://friend link in a QR code for their phone app to open. The code is as secret as the token in it.
"""
import base64
import hashlib
import json
import secrets
import urllib.parse
from datetime import datetime, timedelta, timezone

from database import get_db, query_db

PREFIX = 'hwf_'
CODE_PREFIX = 'hwfc_'
LINK_PREFIX = 'headwind://friend?c='
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


def share_code(url, token):
    """`hwfc_` and the base64url of {"u": address, "t": token}, unpadded: one string to paste, short enough for a QR code."""
    raw = json.dumps({'u': url.rstrip('/'), 't': token}, separators=(',', ':')).encode()
    return CODE_PREFIX + base64.urlsafe_b64encode(raw).decode().rstrip('=')


def share_link(code):
    return LINK_PREFIX + code


def parse_share_code(text):
    """(address, token) from a share code or its headwind://friend link, or None if it isn't one."""
    text = (text or '').strip()
    if len(text) > 4000:
        return None
    if text.lower().startswith('headwind://'):
        link = urllib.parse.urlparse(text)
        if link.netloc.lower() != 'friend':
            return None
        text = (urllib.parse.parse_qs(link.query).get('c') or [''])[0].strip()
    if not text.startswith(CODE_PREFIX):
        return None
    body = text[len(CODE_PREFIX):]
    try:
        data = json.loads(base64.urlsafe_b64decode(body + '=' * (-len(body) % 4)))
    except ValueError:                  # bad base64 (binascii.Error), bytes that aren't UTF-8, or not JSON
        return None
    url, token = (data.get('u'), data.get('t')) if isinstance(data, dict) else (None, None)
    if not isinstance(url, str) or not isinstance(token, str) or not token.startswith(PREFIX):
        return None
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ('http', 'https') or not parsed.hostname:
        return None
    return url.rstrip('/'), token
