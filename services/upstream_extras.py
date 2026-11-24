"""What upstream's rewrite (lordmaa/headwind 0.8 onwards) keeps that this Headwind keeps differently, brought over once at start-up
(Settings.upstreamExtrasDone, after the steps). Everything else in such a database is in the same tables and columns as here, and the steps
and the other repairs bring it up to date as they do upstream's 0.5.

* Photos on an activity: upstream's RidePhoto rows and their files, rideimg/rp_<hex>.jpg and rp_<hex>_t.jpg, become ActivityPhoto rows with
  the files act_<hex>.jpg and act_<hex>_t.jpg (services/photos.py). Upstream already saved them as EXIF-free JPEGs and thumbnails, so the
  files are linked under the new name (copied where a link can't be made), not decoded again. The caption comes too; where on the map a
  photo was placed doesn't, as photos aren't placed here.
* Faults (RideFault: a puncture, a snapped chain), which have no list of their own here: each goes into its activity's notes as a line, much
  as upstream wrote it into the bike's service log (that entry, for a fault on an activity with a bike, comes across as it is; a fault on one
  without a bike had none, and would otherwise be lost from sight).
* A rider whose activities came from a Strava export is asked, on the Import page, to import it again (advise_reimport): the original read
  less of it (tracks it couldn't read, Strava's own figures, photos, bikes and shoes), and importing it again proposes those changes.

Such a database is told by what's in it, not by PRAGMA user_version (0, as upstream's 0.5.3 had): the RidePhoto and RideFault tables, which
this Headwind never had. Their rows and upstream's files are left as they were, as nothing here reads them, so the copy of the database kept
before the steps (<database>.pre-<version>) still has its photos."""
import logging
import os
import re
import shutil

from services import photos

log = logging.getLogger(__name__)

# Tables only upstream's 0.8 onwards has. RidePhoto and RideFault hold what a rider entered; the others are worked out again by upstream
# (WeighInVerdict, DiarySummary), the phone app's bookkeeping (WorkoutTombstone) or a convenience (FoodDefaultWeight), with nothing here
# that reads them.
UPSTREAM_TABLES = ('RidePhoto', 'RideFault', 'WeighInVerdict', 'DiarySummary', 'FoodDefaultWeight', 'WorkoutTombstone')
_RP_RE = re.compile(r'^rp_([a-f0-9]{12})\.jpg$')

# Upstream's own words (services/ride_extras.py, CATEGORIES and OUTCOMES), so a fault reads here as it did in its service log
_CATEGORIES = {'puncture': 'Puncture / flat', 'tyre': 'Tyre damage / blow-out', 'chain': 'Chain (snapped, dropped, skipping)',
               'gears': 'Gears / derailleur / shifter', 'brakes': 'Brakes', 'wheel': 'Wheel, spokes or hub', 'pedals': 'Pedals / cleats',
               'crank': 'Crank / bottom bracket', 'frame': 'Frame / fork', 'contact': 'Bars, stem, saddle or seatpost',
               'electrics': 'Electrics / e-bike / computer / lights', 'crash': 'Crash damage', 'other': 'Something else'}
_OUTCOMES = {'fixed': 'fixed it and carried on', 'limped': 'carried on, but limping',
             'ended': 'ride ended early (walked, rescued or got a lift)'}


def upstream_tables(db):
    """Which of upstream's 0.8-onwards tables this database has: empty for this Headwind's own and for upstream's 0.5."""
    have = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    return [t for t in UPSTREAM_TABLES if t in have]


def from_rewrite(db):
    """Whether this is a database from upstream's 0.8 onwards (step 16 sets the flag done where it isn't)."""
    return bool(upstream_tables(db))


def advise_reimport(db):
    """Ask each rider whose activities came from a Strava export, imported by the original, to import it again (services/strava_export.advice:
    the card on the Import page and its badge). Such an activity has Strava's id, all digits; the original's own imports are imp_..., its typed-in
    ones man_ or wk_, Garmin's garmin_.... Does not commit. Returns the riders asked."""
    from services import strava_export
    riders = [r[0] for r in db.execute("SELECT DISTINCT riderId FROM Activity WHERE riderId IS NOT NULL AND id <> '' AND id NOT GLOB '*[^0-9]*' "
                                       "AND riderId NOT IN (SELECT riderId FROM Friend WHERE riderId IS NOT NULL)").fetchall()]
    for rid in riders:
        db.execute('''INSERT INTO StravaExportRead (riderId, advised, dismissed) VALUES (?, ?, ?)
                      ON CONFLICT(riderId) DO UPDATE SET advised=excluded.advised, dismissed=excluded.dismissed''',
                   [rid, strava_export.FROM_ORIGINAL, strava_export.FROM_ORIGINAL])
    return riders


def _activity(db, act_id):
    """The activity a photo or fault belongs to now: itself, or the one it was set aside behind as a copy. None when it's gone."""
    if db.execute('SELECT 1 FROM Activity WHERE id=?', [act_id]).fetchone():
        return act_id
    r = db.execute('SELECT primaryId FROM ActivityDuplicate WHERE id=?', [act_id]).fetchone()
    if r and db.execute('SELECT 1 FROM Activity WHERE id=?', [r[0]]).fetchone():
        return r[0]
    return None


def _link(src, dst):
    if os.path.exists(dst):
        return
    try:
        os.link(src, dst)
    except OSError:
        shutil.copy2(src, dst)


def fault_line(f):
    """A fault as one line of notes, as upstream's _log_notes wrote it into the service log."""
    bits = [_CATEGORIES.get(f['category'] or 'other', 'Something else')]
    if f['description']:
        bits.append(f['description'])
    if f['outcome'] in _OUTCOMES:
        bits.append(_OUTCOMES[f['outcome']])
    if f['minutesLost']:
        bits.append(f"{f['minutesLost']} min lost")
    bits.append(f"repaired {f['repairedOn']}" if f['repairedOn'] else 'not repaired yet')
    return 'Fault on a ride: ' + ' - '.join(bits)


def _photos(db, db_path):
    moved, missing, gone = 0, 0, 0
    d = photos.photo_dir(db_path)
    for p in db.execute('SELECT id, rideId, file, caption FROM RidePhoto ORDER BY rideId, id').fetchall():
        m = _RP_RE.match(p['file'] or '')
        src = os.path.join(d, p['file']) if m else None
        if not src or not os.path.isfile(src):
            missing += 1
            continue
        act_id = _activity(db, p['rideId'])
        if not act_id:
            gone += 1
            continue
        key = f"upstream:rideimg/{p['file']}"
        if photos.have(db, key):
            continue
        name = f'act_{m.group(1)}.jpg'
        _link(src, os.path.join(d, name))
        thumb = os.path.join(d, f'rp_{m.group(1)}_t.jpg')
        if os.path.isfile(thumb):
            _link(thumb, os.path.join(d, photos.thumb_name(name)))
        db.execute('INSERT INTO ActivityPhoto (activityId, filename, caption, sourceKey, position) VALUES (?,?,?,?,?)',
                   [act_id, name, (p['caption'] or '').strip()[:photos.MAX_CAPTION] or None, key, photos.next_position(db, act_id)])
        moved += 1
    return moved, missing, gone


def _faults(db):
    noted, gone = 0, 0
    for f in db.execute('SELECT * FROM RideFault ORDER BY rideId, date, id').fetchall():
        act_id = _activity(db, f['rideId'])
        if not act_id:
            gone += 1
            continue
        line = fault_line(f)
        notes = db.execute('SELECT notes FROM Activity WHERE id=?', [act_id]).fetchone()[0] or ''
        if line in notes:
            continue
        db.execute("UPDATE Activity SET notes=?, updatedAt=datetime('now') WHERE id=?", [(notes.rstrip() + '\n\n' + line).strip(), act_id])
        noted += 1
    return noted, gone


def fix(db, db_path):
    """Run once (Settings.upstreamExtrasDone). Commits. Returns {'photos', 'faults', 'missing', 'gone', 'others'}, or None when it has run before.
    others: the upstream-only tables left as they are that have rows, for the Tasks page to name."""
    s = db.execute('SELECT upstreamExtrasDone FROM Settings WHERE id=1').fetchone()
    if not s or s['upstreamExtrasDone']:
        return None
    tables = upstream_tables(db)
    moved = missing = gone = noted = 0
    if 'RidePhoto' in tables and db_path:                   # a database in memory has no files beside it
        moved, missing, g = _photos(db, db_path)
        gone += g
    if 'RideFault' in tables:
        noted, g = _faults(db)
        gone += g
    others = [t for t in tables if t not in ('RidePhoto', 'RideFault') and db.execute(f'SELECT 1 FROM {t} LIMIT 1').fetchone()]
    if tables:
        advise_reimport(db)
    db.execute('UPDATE Settings SET upstreamExtrasDone=1 WHERE id=1')
    db.commit()
    if moved or noted or missing or gone:
        log.info('From the original Headwind: photos brought over %d, faults put in notes %d, photo files missing %d, on activities no longer '
                 'here %d', moved, noted, missing, gone)
    return {'photos': moved, 'faults': noted, 'missing': missing, 'gone': gone, 'others': others}


_OTHER_WORDS = {'WeighInVerdict': 'the verdicts on each weigh-in', 'DiarySummary': 'the food diary summaries',
                'FoodDefaultWeight': 'the usual portion of each food', 'WorkoutTombstone': "the Android app's record of deleted workouts"}


def summary(res):
    """The Tasks page's line for what fix() did."""
    p, f = res['photos'], res['faults']
    parts = []
    if p:
        parts.append(f"{p} photo{'' if p == 1 else 's'} on {'its activity' if p == 1 else 'their activities'} now show{'s' if p == 1 else ''} here")
    if f:
        parts.append(f"{f} fault{'' if f == 1 else 's'} (a puncture, a snapped chain) {'is' if f == 1 else 'are'} in "
                     f"{'its activity' + chr(39) + 's' if f == 1 else 'their activities' + chr(39)} notes, as there's no list of faults here")
    if res['missing']:
        parts.append(f"{res['missing']} photo file{' was' if res['missing'] == 1 else 's were'} missing from rideimg/")
    if res['gone']:
        parts.append(f"{res['gone']} belonged to activities no longer here")
    text = '; '.join(parts) + '.' if parts else 'Nothing to bring over.'
    if res['others']:
        text += (' Not used here, so left as they were: ' + ', '.join(_OTHER_WORDS[t] for t in res['others']) + '.')
    return text[0].upper() + text[1:]
