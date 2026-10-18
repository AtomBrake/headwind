"""Where an activity came from, as a link to it on Garmin Connect or Strava (the ride page's button). The id says it: a Garmin sync saves
'garmin_<Garmin activity id>', a Strava export saves Strava's own activity id, a number. Every other source (files, the phone, friends, typed in) has an
id of its own. Changing a ride into a workout or back gives it a new id, so the one it came in with is kept in originId (services/convert.py)."""
import hashlib
import json
import re


def link(activity_id, origin_id=None):
    """{'name': 'Garmin' | 'Strava', 'url'} or None."""
    aid = str(origin_id or activity_id or '')
    if aid.startswith('conv_'):                         # a Garmin workout changed into a ride before originId existed
        aid = aid[5:]
    m = re.fullmatch(r'garmin_(\d+)', aid)
    if m:
        return {'name': 'Garmin', 'url': f'https://connect.garmin.com/modern/activity/{m[1]}'}
    if re.fullmatch(r'\d+', aid):
        return {'name': 'Strava', 'url': f'https://www.strava.com/activities/{aid}'}
    return None


def links(db, activity_id, origin_id=None):
    """Every place this activity can be opened: its own link, then those of recordings merged into it (services/duplicates.py) — the same ride
    imported from Garmin and from Strava gets a button for each. A discarded recording still counts: only its data is gone here, not on Garmin or
    Strava. One link per service, the main recording's first."""
    from services import duplicates
    duplicates.ensure_schema(db)
    found = [link(activity_id, origin_id)]
    for d in db.execute("SELECT id, rowJson FROM ActivityDuplicate WHERE primaryId=? AND status IN ('parked','discarded') ORDER BY parkedAt",
                        [str(activity_id)]):
        try:
            row = json.loads(d['rowJson'] or '{}')
        except ValueError:
            row = {}
        found.append(link(d['id'], row.get('originId')))
    out = []
    for l in found:
        if l and l['name'] not in {o['name'] for o in out}:
            out.append(l)
    return out


def backfill(db):
    """At start-up: workouts changed from rides before originId existed. Their id is a hash of the ride's id, and the ride's id was remembered when it
    was removed (ActivityDuplicate), so the pair can be matched up again. Does not commit."""
    todo = {r['id'] for r in db.execute("SELECT id FROM Workout WHERE source='converted' AND originId IS NULL")}
    if not todo:
        return 0
    n = 0
    for r in db.execute('SELECT id, riderId FROM ActivityDuplicate').fetchall():
        wid = 'wk_' + hashlib.sha1(f"{r['riderId']}|conv|{r['id']}".encode()).hexdigest()[:16]
        if wid in todo:
            db.execute('UPDATE Workout SET originId=? WHERE id=?', [r['id'], wid])
            n += 1
    return n
