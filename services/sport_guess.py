"""A file that can't be trusted about its sport: Strava writes Sport="Biking" into every TCX it exports, a run's too, and a GPX from Strava,
RunKeeper or Trailforks may name no sport at all, which has always made it a ride. Uploaded on their own, with no activities.csv beside them to
say, those runs and walks came in as rides. The track tells them apart well enough to ask, not well enough to decide: the fastest 30 seconds of a
run stay under services/parser.ON_FOOT_KMH where almost every ride's go over, but a slow ride beside a child, a towpath dawdle or a route drawn on
a map at a steady 16 km/h does not. So the activity is saved as its file says, and the rider is asked (the activity page, the Import page, the
dashboard), with the guess to accept in one click. Nothing changes until they answer. Cadence doesn't help: a run's is counted per foot, so 85
looks like pedalling, and the runs Strava exported as Biking carry none.

The guess is made as the file is read (services/parser.on_foot), and asked here once the activity is saved."""
import logging

log = logging.getLogger(__name__)

def ensure_schema(db):
    db.execute('''CREATE TABLE IF NOT EXISTS SportGuess (
        activityId TEXT PRIMARY KEY,
        fileSport  TEXT,                                    -- what the file said ('Biking'), or NULL when it said nothing
        savedSport TEXT NOT NULL,                           -- what it was saved as: the question stands only while it still is
        guess      TEXT NOT NULL,                           -- Run or Walk
        status     TEXT NOT NULL DEFAULT 'pending'          -- pending | kept (the rider said the file was right)
    )''')
    db.execute('DELETE FROM SportGuess WHERE activityId NOT IN (SELECT id FROM Activity)')


def note(db, act_id, act):
    """After an upload is saved: ask about it when the parser guessed (act['sportGuess']) and it is still saved with the file's sport. Does not
    commit. True when it asks."""
    guess = act.get('sportGuess')
    if not guess:
        return False
    row = db.execute('SELECT sportType FROM Activity WHERE id=?', [act_id]).fetchone()
    if not row or row['sportType'] == guess or row['sportType'] != act.get('sportType'):   # another recording's sport was kept, or it was changed
        return False
    db.execute('INSERT OR IGNORE INTO SportGuess (activityId, fileSport, savedSport, guess) VALUES (?,?,?,?)',
               [act_id, act.get('fileSport'), row['sportType'], guess])
    log.info('Upload %s saved as %s, looks like a %s: asking', act_id, row['sportType'], guess)
    return True


_OPEN = '''SELECT g.*, a.name, a.startDateLocal, a.distance, a.riderId FROM SportGuess g JOIN Activity a ON a.id = g.activityId
           WHERE g.status='pending' AND a.sportType = g.savedSport'''


def for_activity(db, act_id):
    """The question still open for this activity, or None."""
    try:
        row = db.execute(_OPEN + ' AND g.activityId=?', [act_id]).fetchone()
    except Exception:                                   # no SportGuess table yet (a bare database)
        return None
    return dict(row) if row else None


def pending(db, rider_id=None):
    """The questions still open, newest first: the rider's, or everyone's."""
    try:
        return [dict(r) for r in db.execute(_OPEN + (' AND a.riderId=?' if rider_id is not None else '') + ' ORDER BY a.startDateLocal DESC',
                                            [rider_id] if rider_id is not None else [])]
    except Exception:
        return []


def answer(db, act_ids, use):
    """`use`: change each to its guess (convert.change_sport: a run loses its bike and ride segment times, with its derived data put right; a recording set aside
    under it is the same session from another device and goes with it, as in sport_fix.apply). Else the file was right: not asked again.
    Does not commit. Returns (how many were answered, [(id, why it couldn't be changed)])."""
    from services import convert
    done, failed = 0, []
    for g in (q for q in (for_activity(db, i) for i in act_ids) if q):
        if not use:
            db.execute("UPDATE SportGuess SET status='kept' WHERE activityId=?", [g['activityId']])
            done += 1
            continue
        try:
            convert.change_sport(db, None, g['activityId'], g['guess'], discard_parked=True)
            db.execute('DELETE FROM SportGuess WHERE activityId=?', [g['activityId']])
            done += 1
        except ValueError as e:
            failed.append((g['activityId'], str(e)))
    return done, failed
