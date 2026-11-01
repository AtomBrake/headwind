"""Device tokens for the phone app: one per paired phone, revocable, stored only as a SHA-256 hash (shown once at pairing).

A phone can make one more for its Apple Watch (create_child), so the Watch can upload a ride itself when the phone isn't with it. The Watch's token
names the phone's (parentId): it's listed under the phone on the Phones page, can be revoked on its own, and stops working when the phone's is revoked,
so a phone's token can't be used to leave a working one behind.

A token works until it's revoked. One not used for STALE_DAYS is flagged on the Phones page, which offers to revoke them all; none is revoked
by itself."""
import hashlib
import secrets
from datetime import datetime, timedelta

from flask import g

from database import get_db, query_db

PREFIX = 'hw_'
STALE_DAYS = 90


def _hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def create(name):
    token = PREFIX + secrets.token_urlsafe(32)
    db = get_db()
    cur = db.execute('INSERT INTO DeviceToken (name, tokenHash) VALUES (?, ?)', [(name or 'Phone').strip()[:60], _hash(token)])
    db.commit()
    return token, cur.lastrowid


def create_child(parent_id, name):
    """A token for the Apple Watch paired with the phone whose token is parent_id. Any earlier one for that phone is revoked: a phone has one Watch.
    Returns (token, id), or None if the parent is itself a child or is revoked."""
    db = get_db()
    parent = db.execute('SELECT parentId FROM DeviceToken WHERE id=? AND revokedAt IS NULL', [parent_id]).fetchone()
    if not parent or parent['parentId'] is not None:
        return None
    token = PREFIX + secrets.token_urlsafe(32)
    db.execute("UPDATE DeviceToken SET revokedAt=datetime('now') WHERE parentId=? AND revokedAt IS NULL", [parent_id])
    cur = db.execute('INSERT INTO DeviceToken (name, tokenHash, parentId) VALUES (?, ?, ?)',
                     [(name or 'Apple Watch').strip()[:60], _hash(token), parent_id])
    db.commit()
    return token, cur.lastrowid


def verify(token):
    """True for a known, un-revoked token (and, for a Watch's, an un-revoked phone). Records last use (at most once a minute, so a chatty app doesn't
    write on every call)."""
    if not token or not token.startswith(PREFIX):
        return False
    row = query_db('SELECT t.id, t.name, t.lastUsedAt FROM DeviceToken t LEFT JOIN DeviceToken p ON p.id = t.parentId '
                   'WHERE t.tokenHash=? AND t.revokedAt IS NULL AND (t.parentId IS NULL OR (p.id IS NOT NULL AND p.revokedAt IS NULL))',
                   [_hash(token)], one=True)
    if not row:
        return False
    g.device_name = row['name']                 # for the request's log line (services/logs.py)
    g.device_id = row['id']
    now = datetime.utcnow()
    last = row['lastUsedAt']
    if not last or now - datetime.strptime(last, '%Y-%m-%d %H:%M:%S') > timedelta(minutes=1):
        db = get_db()
        db.execute("UPDATE DeviceToken SET lastUsedAt=datetime('now') WHERE id=?", [row['id']])
        db.commit()
    return True


def stale_ids():
    """The un-revoked tokens last used (or, never used, made) more than STALE_DAYS ago. A phone counts as used when its Watch was, since revoking
    the phone's token ends the Watch's too."""
    rows = query_db('SELECT id, parentId, COALESCE(lastUsedAt, createdAt) AS seen FROM DeviceToken WHERE revokedAt IS NULL')
    seen = {r['id']: r['seen'] or '' for r in rows}
    for r in rows:
        if r['parentId'] in seen:
            seen[r['parentId']] = max(seen[r['parentId']], r['seen'] or '')
    cutoff = (datetime.utcnow() - timedelta(days=STALE_DAYS)).strftime('%Y-%m-%d %H:%M:%S')
    return {i for i, s in seen.items() if s < cutoff}


def devices():
    stale = stale_ids()
    return [dict(r, stale=r['id'] in stale)
            for r in query_db('SELECT id, name, createdAt, lastUsedAt, revokedAt, parentId FROM DeviceToken ORDER BY id DESC')]


def revoke(device_id):
    """Revoke a token, and the Watch's made from it."""
    db = get_db()
    db.execute("UPDATE DeviceToken SET revokedAt=datetime('now') WHERE (id=? OR parentId=?) AND revokedAt IS NULL", [device_id, device_id])
    db.commit()


def revoke_stale():
    """Revoke every token stale_ids() flags, each with its Watch's. Returns how many were flagged."""
    ids = stale_ids()
    for i in ids:
        revoke(i)
    return len(ids)
