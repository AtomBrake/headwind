"""The people a rider has chosen to hear from Headwind while they're out, by email (services/mail.py): today each live tracking link as it
starts (services/live_share.py), later a safety alert when they've stopped moving for a while away from home. Chosen beforehand, in Settings
on the web or in the app (/api/v1/contacts), so a link goes out from the server with nobody tapping anything: with the Watch alone, say.

Each contact has a tick for each thing it can be sent (PURPOSES, a column apiece), so the safety alert can go to fewer people than the links.
Contacts are a rider's own (riderId), as everything will be once there are logins (docs/MULTI-USER-PLAN.md).

What's sent goes through an outbox, ContactSend: a row per contact for each thing sent, named by `about` ('live:12' for share 12). The rows
are made once (UNIQUE about, contactId), so asking again, from another process or a retry, sends nobody anything twice. They say what became
of each: sending, sent, or failed and why, which the phone shows ("Sent to Sam and Alex"). The message itself is put together when it's sent,
by whatever queued it (deliver): the live link's token is kept sealed on its share, and never here."""
import time

from services import mail

PURPOSES = {'live': 'liveLinks'}        # purpose -> the Contact column that ticks it; the safety alert will add its own
MAX_CONTACTS = 20
MAX_NAME = 60
SENDING, SENT, FAILED = 'sending', 'sent', 'failed'


def ensure_schema(db):
    """Does not commit."""
    db.execute('''
        CREATE TABLE IF NOT EXISTS Contact (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            riderId     INTEGER NOT NULL,
            name        TEXT NOT NULL,
            email       TEXT NOT NULL,
            liveLinks   INTEGER NOT NULL DEFAULT 1,     -- sent each live tracking link as it starts
            createdAt   REAL NOT NULL
        )''')
    db.execute('CREATE INDEX IF NOT EXISTS idx_contact_rider ON Contact(riderId)')
    db.execute('''
        CREATE TABLE IF NOT EXISTS ContactSend (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            about       TEXT NOT NULL,                  -- what was sent: 'live:<LiveShare.id>'
            riderId     INTEGER NOT NULL,
            contactId   INTEGER NOT NULL,
            name        TEXT NOT NULL,                  -- the contact's name and address when it was queued: a contact changed or
            email       TEXT NOT NULL,                  -- removed since still says who it went to
            state       TEXT NOT NULL,                  -- sending | sent | failed
            error       TEXT,
            at          REAL NOT NULL,
            UNIQUE (about, contactId)
        )''')


def _public(row):
    return {'id': row['id'], 'name': row['name'], 'email': row['email'], 'live_links': bool(row['liveLinks'])}


def listing(db, rider_id):
    """The rider's contacts, by name: [{id, name, email, live_links}]."""
    rows = db.execute('SELECT * FROM Contact WHERE riderId=? ORDER BY name COLLATE NOCASE, id', [rider_id]).fetchall()
    return [_public(r) for r in rows]


def get(db, rider_id, contact_id):
    r = db.execute('SELECT * FROM Contact WHERE id=? AND riderId=?', [contact_id, rider_id]).fetchone()
    return _public(r) if r else None


def _checked(db, rider_id, name, email, contact_id=None):
    """(name, email) as kept, or raise ValueError with why not, fit to show."""
    name = ' '.join(str(name or '').split())[:MAX_NAME]
    if not name:
        raise ValueError('Give the contact a name: it says who the link went to.')
    address = mail.clean_address(str(email or ''))
    if not address:
        raise ValueError(f'"{str(email or "").strip()[:80]}" is not an email address.')
    same = db.execute('SELECT id FROM Contact WHERE riderId=? AND lower(email)=lower(?) AND id IS NOT ?',
                      [rider_id, address, contact_id]).fetchone()
    if same:
        raise ValueError(f'{address} is already a contact.')
    return name, address


def add(db, rider_id, name, email, live_links=True, now=None):
    """Add a contact. Returns it as listing() gives it. Raises ValueError with why not, fit to show. Commits."""
    name, email = _checked(db, rider_id, name, email)
    if db.execute('SELECT COUNT(*) FROM Contact WHERE riderId=?', [rider_id]).fetchone()[0] >= MAX_CONTACTS:
        raise ValueError(f'You have {MAX_CONTACTS} contacts already: remove one first.')
    cid = db.execute('INSERT INTO Contact (riderId, name, email, liveLinks, createdAt) VALUES (?,?,?,?,?)',
                     [rider_id, name, email, 1 if live_links else 0, time.time() if now is None else now]).lastrowid
    db.commit()
    return get(db, rider_id, cid)


def update(db, rider_id, contact_id, name=None, email=None, live_links=None):
    """Change what's given of a contact (None keeps it). Returns it, or None when the rider has no such contact. Raises ValueError with why
    not, fit to show. Commits."""
    cur = db.execute('SELECT * FROM Contact WHERE id=? AND riderId=?', [contact_id, rider_id]).fetchone()
    if not cur:
        return None
    name, email = _checked(db, rider_id, cur['name'] if name is None else name, cur['email'] if email is None else email, contact_id)
    ticked = cur['liveLinks'] if live_links is None else (1 if live_links else 0)
    db.execute('UPDATE Contact SET name=?, email=?, liveLinks=? WHERE id=?', [name, email, ticked, contact_id])
    db.commit()
    return get(db, rider_id, contact_id)


def remove(db, rider_id, contact_id):
    """Returns whether there was one. Commits."""
    n = db.execute('DELETE FROM Contact WHERE id=? AND riderId=?', [contact_id, rider_id]).rowcount
    db.commit()
    return n > 0


def queue(db, rider_id, about, purpose, now=None):
    """Put whatever `about` names in the outbox for each of the rider's contacts ticked for `purpose` (a key of PURPOSES), once: a contact
    already queued for it isn't again. When email isn't set up they're failed at once, saying why. Returns how many are now waiting to be
    sent (deliver). Commits."""
    now = time.time() if now is None else now
    col = PURPOSES[purpose]
    ok, why = mail.ready(db)
    rows = db.execute(f'SELECT id, name, email FROM Contact WHERE riderId=? AND {col}=1 ORDER BY name COLLATE NOCASE, id', [rider_id]).fetchall()
    waiting = 0
    for c in rows:
        n = db.execute('INSERT OR IGNORE INTO ContactSend (about, riderId, contactId, name, email, state, error, at) VALUES (?,?,?,?,?,?,?,?)',
                       [about, rider_id, c['id'], c['name'], c['email'], SENDING if ok else FAILED, None if ok else why, now]).rowcount
        waiting += n if ok else 0
    db.commit()
    return waiting


def deliver(db, about, subject, text, sender_name=None, now=None):
    """Email what's waiting in the outbox for `about`, the same message to each, and record how each went. Returns how many were sent.
    Commits before talking to the mail server, so a slow one holds no lock on the database."""
    rows = db.execute('SELECT id, email FROM ContactSend WHERE about=? AND state=? ORDER BY id', [about, SENDING]).fetchall()
    db.commit()
    if not rows:
        return 0
    cfg = mail.config(db)
    why = mail.problem(cfg)                 # set up when queued, but changed since
    errors = [why] * len(rows) if why else mail.send(cfg, [mail.message(cfg, r['email'], subject, text, sender_name) for r in rows])
    now = time.time() if now is None else now
    for r, err in zip(rows, errors):
        db.execute('UPDATE ContactSend SET state=?, error=?, at=? WHERE id=?', [FAILED if err else SENT, err, now, r['id']])
    db.commit()
    return sum(1 for e in errors if not e)


def fail(db, about, why, now=None):
    """What's still waiting for `about` won't be sent (what it was about has ended, say). Commits."""
    db.execute('UPDATE ContactSend SET state=?, error=?, at=? WHERE about=? AND state=?',
               [FAILED, why, time.time() if now is None else now, about, SENDING])
    db.commit()


def report(db, about):
    """Who `about` went to, and how it went, in the order they were queued: [{name, state, error}]. The phone shows it."""
    rows = db.execute('SELECT name, state, error FROM ContactSend WHERE about=? ORDER BY id', [about]).fetchall()
    return [{'name': r['name'], 'state': r['state'], 'error': r['error']} for r in rows]


def forget(db, abouts):
    """The outbox rows for these, gone (what they were about has been deleted). Does not commit."""
    for about in abouts:
        db.execute('DELETE FROM ContactSend WHERE about=?', [about])
