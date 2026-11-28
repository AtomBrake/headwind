"""The "Download a copy for troubleshooting" zip on the Tasks page: the database, for someone helping with a problem the diagnostics zip
(services/diagnostics.py: no data) can't show, with what isn't needed taken out. Only the copy is changed, never the live database.

Always taken out: every saved key, password and token (even encrypted), the Garmin email, addresses (Home Assistant, Ollama, ntfy, the
MQTT broker and user, the mail server, friends' servers, failed sign-ins), a live ride's last reading, the contacts its link goes to and
whom it was sent to, the privacy zones (services/privacy_zones.py: where home is), the install id, friends' names, their riders with
everything of theirs (activities, photos, best times, weigh-ins, food), their segments and foods, the names of feed tokens and paired
phones, and the Garmin account's name in Garmin's listings. No photo or avatar file goes in the zip. On request: GPS (tracks, start points, segments, planned routes, and the coordinates in
the other copies of an activity), or the streams altogether (heart rate, power and the rest, and GPS with them).

With GPS left in, the privacy zones (services/privacy_zones.py) are cut out of everything it keeps (_without_zones), every rider's zones
from every track, as a friend's feed is cut: each stream's samples at the positions inside (and the track summaries made from them, which
are made again from what's left when the copy is restored), start points, the positions in laps and rawData (a start_latlng, a
startLatitude and startLongitude, a FIT file's semicircles, an encoded polyline), the summary polyline, planned routes, segments that
start, end or pass inside, and the same in the other copies of an activity (ActivityDuplicate, ImportChange) and Garmin's listings. The
zones are read before strip deletes them; the activities' updatedAt is left as it was.

Everything else is left: the person's own activities with their names, dates, notes and figures, riders' names, gear, weight, food,
Garmin's health days, the body details in Settings, goals and the task log. The page says so, so they can decide.

The copy is made with SQLite's backup API (as the backup is), changed, then written out again with VACUUM INTO, so nothing taken out is
left in its free pages. It's a zip with headwind.db in it, like a backup, so it can be restored on a test server. Made in the background (services/downloads.py)."""
import json
import os
import re
import sqlite3
import zipfile
from datetime import datetime

from services import diagnostics, downloads, privacy_zones, streams, vault

KIND = 'troubleshooting'        # its job in services/downloads.py

# Settings columns emptied besides the secrets (vault.COLUMNS): addresses, user names, a path on the server (mqttCaFile).
ADDRESSES = ('garminEmail', 'haUrl', 'ollamaUrl', 'ntfyUrl', 'mqttHost', 'mqttUser', 'mqttCaFile', 'webhookSubId', 'smtpHost', 'smtpUser',
             'smtpFrom')
# Free text from a sync or a run, which can quote an address or a server's reply: through the same redaction as the diagnostics zip, and
# with the address in a URL taken out.
_URL = re.compile(r'(?i)\b([a-z][a-z0-9+.-]*://)[^\s/"\'<>]+')
STATUS = {'Settings': ('garminLastError', 'haLastResult', 'garminHistoryStatus', 'garminWeightsStatus'), 'TaskLog': ('result', 'error')}
# A key in JSON that holds a place: Strava's latlng and map, Garmin's startLatitude and locationName, a FIT file's position_lat, ...
_GPS = re.compile(r'(?i)latlng|lat_lng|latitude|longitude|polyline|location|waypoint|^map$|^(lat|lng|lon)$|^(start|end|position|min|max)_?(lat|lng|lon)')
# ... and one that names the Garmin account, in Garmin's listing of an activity: ownerFullName, ownerDisplayName, ownerProfileImageUrlSmall.
_OWNER = re.compile(r'(?i)^owner|displayname|fullname|userprofile')
_LISTINGS = {'GarminMissing': ('activity',), 'GarminChange': ('garmin',)}
# JSON columns that copy an activity, or Garmin's listing of one (ActivityDuplicate.rowJson is done apart: it's big).
_JSON = {'GarminMissing': ('activity',), 'GarminChange': ('garmin', 'diffs'), 'GarminSeen': ('summary',), 'ImportChange': ('act', 'diffs'),
         'ActivitySensor': ('data', 'summary')}

LEFT = ('your activities (names, dates and times, notes, distances, heart rate, power and the other figures), riders\' names, bikes and '
        'kit, weigh-ins, the food log, Garmin and Apple Health days (sleep, HRV, resting heart rate, steps), the body details in Settings '
        '(height, sex, birth date), goals and the task log')


def _cols(db, table):
    return [r[1] for r in db.execute(f'PRAGMA table_info("{table}")').fetchall()]


def _tables(db):
    return [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchall()]


def _scrub(value, drop):
    """(value with every dict key `drop` matches taken out, all the way down, whether anything was). A string that is itself JSON
    (rowJson's streams) too. A list of numbers (a stream) is passed over whole."""
    if isinstance(value, dict):
        out, changed = {}, False
        for k, v in value.items():
            if drop.search(k):
                changed = True
                continue
            out[k], c = _scrub(v, drop)
            changed |= c
        return (out, True) if changed else (value, False)
    if isinstance(value, list):
        if not value or isinstance(value[0], (int, float)):
            return value, False
        pairs = [_scrub(v, drop) for v in value]
        return ([v for v, _ in pairs], True) if any(c for _, c in pairs) else (value, False)
    if isinstance(value, str) and value[:1] in '{[':
        try:
            inner = json.loads(value)
        except ValueError:
            return value, False
        clean, changed = _scrub(inner, drop)
        return (json.dumps(clean), True) if changed else (value, False)
    return value, False


def _scrub_json(db, table, col, drop):
    if col not in _cols(db, table):
        return
    for rowid, raw in db.execute(f'SELECT rowid, "{col}" FROM "{table}" WHERE "{col}" IS NOT NULL').fetchall():
        try:
            value = json.loads(raw)
        except (TypeError, ValueError):
            continue
        clean, changed = _scrub(value, drop)
        if changed:
            db.execute(f'UPDATE "{table}" SET "{col}"=? WHERE rowid=?', [json.dumps(clean), rowid])


def _blank(db, table, cols):
    have = [c for c in cols if c in _cols(db, table)]
    if have:
        db.execute(f'UPDATE "{table}" SET {", ".join(f"{c}=NULL" for c in have)}')


def _without_friends(db, tables):
    """Friends' riders and everything that hangs off them, their segments and foods; what's left of a friend is a numbered row."""
    if 'Friend' not in tables:
        return
    db.execute('CREATE TEMP TABLE _theirs AS SELECT riderId AS id FROM Friend WHERE riderId IS NOT NULL')
    db.execute('CREATE TEMP TABLE _gone AS SELECT id FROM Activity WHERE riderId IN (SELECT id FROM _theirs)')
    for t in tables:
        cols = _cols(db, t)
        if 'riderId' in cols and t != 'Friend':
            db.execute(f'DELETE FROM "{t}" WHERE riderId IN (SELECT id FROM _theirs)')
        if 'activityId' in cols:
            db.execute(f'DELETE FROM "{t}" WHERE activityId IN (SELECT id FROM _gone)')
    db.execute('DELETE FROM Rider WHERE id IN (SELECT id FROM _theirs)')
    if 'Bike' in tables:        # their bikes went with their riderId: and the parts on them
        for t, c in (('Part', 'bikeId'), ('ServiceLog', 'bikeId')):
            if t in tables:
                db.execute(f'DELETE FROM {t} WHERE {c} NOT IN (SELECT id FROM Bike)')
    if 'PartAlert' in tables and 'Part' in tables:
        db.execute('DELETE FROM PartAlert WHERE partId NOT IN (SELECT id FROM Part)')
    if 'KitAlert' in tables and 'Kit' in tables:
        db.execute('DELETE FROM KitAlert WHERE kitId NOT IN (SELECT id FROM Kit)')
    if 'friendId' in _cols(db, 'Segment'):
        db.execute('DELETE FROM SegmentEffort WHERE segmentId IN (SELECT id FROM Segment WHERE friendId IS NOT NULL)')
        db.execute('DELETE FROM Segment WHERE friendId IS NOT NULL')
    if 'SharedFood' in tables:
        db.execute('DELETE FROM SharedFood WHERE friendId IS NOT NULL')
    if 'Challenge' in tables:
        db.execute("UPDATE Challenge SET creatorName='Friend ' || viaFriendId WHERE viaFriendId IS NOT NULL")
    db.execute("UPDATE Friend SET name='Friend ' || id, url='', token=NULL" + (", riderName='Friend ' || id" if 'riderName' in _cols(db, 'Friend') else ''))
    db.execute('DROP TABLE _theirs')
    db.execute('DROP TABLE _gone')


def _without_gps(db, tables):
    # The streams are most of the file, and their only place is `latlng`: SQLite's JSON functions take it out several times as quickly as
    # reading each into Python would (15 s against 40 s for 1.5 GB). An activity's are compressed in ActivityStream (services/streams.py), and a
    # parked duplicate's and an import's waiting on the Import page in their own streams column (streams.apart); a parked duplicate's row kept
    # from before database step 5 holds them as a string.
    streams.register(db)
    for t, col in (('ActivityStream', 'data'), ('ActivityDuplicate', 'streams'), ('ImportChange', 'streams')):
        if t in tables and col in _cols(db, t):
            db.execute(f"UPDATE {t} SET {col}=streams_pack(json_remove(streams_json({col}), '$.latlng')) "
                       f"WHERE json_type(streams_json({col}), '$.latlng') IS NOT NULL")
    _blank(db, 'Activity', ('summaryPolyline', 'startLat', 'startLng'))
    for col in ('rawData', 'laps'):
        _scrub_json(db, 'Activity', col, _GPS)
    if 'ActivityDuplicate' in tables:
        # `|| ''` keeps the streams a string: another JSON function's result would go in as an object
        db.execute("""UPDATE ActivityDuplicate SET rowJson=CASE
                        WHEN json_type(rowJson, '$.streams') = 'text' AND json_valid(rowJson ->> '$.streams')
                        THEN json_set(json_remove(rowJson, '$.summaryPolyline', '$.startLat', '$.startLng'),
                                      '$.streams', json_remove(rowJson ->> '$.streams', '$.latlng') || '')
                        ELSE json_remove(rowJson, '$.summaryPolyline', '$.startLat', '$.startLng') END
                      WHERE json_valid(rowJson)""")
        for col in ('rawData', 'laps'):
            for rowid, raw in db.execute(f"SELECT rowid, rowJson ->> '$.{col}' FROM ActivityDuplicate WHERE json_valid(rowJson) "
                                         f"AND json_type(rowJson, '$.{col}') = 'text'").fetchall():
                clean, changed = _scrub(raw, _GPS)
                if changed:
                    db.execute(f"UPDATE ActivityDuplicate SET rowJson=json_set(rowJson, '$.{col}', ?) WHERE rowid=?", [clean, rowid])
    for t, cols in _JSON.items():
        if t in tables and t != 'ActivityDuplicate':
            for c in cols:
                _scrub_json(db, t, c, _GPS)
    for t in ('ActivityTrack', 'PlannedRoute', 'SegmentEffort', 'Segment'):     # a segment is a line on the map
        if t in tables:
            db.execute(f'DELETE FROM {t}')


# Zones (_without_zones)
_LAT = re.compile(r'(?i)^(.*?)(latitude|lat)(.*)$')
_LNG_FOR = ('lng', 'lon', 'long', 'longitude')
_POLY = re.compile(r'(?i)polyline')
_SEMI = 180 / 2 ** 31                       # a FIT file's semicircles in degrees


def _zones(db, tables):
    """Every rider's privacy zones, as one Hider: a zone says where a rider lives, and the people in one database mostly share a home."""
    if 'PrivacyZone' not in tables:
        return privacy_zones.Hider([])
    rows = db.execute('SELECT lat, lng, radiusM, bearing, shift FROM PrivacyZone').fetchall()
    return privacy_zones.Hider([dict(zip(('lat', 'lng', 'radiusM', 'bearing', 'shift'), r)) for r in rows])


def _deg(v):
    """A latitude or longitude as degrees (a FIT file keeps semicircles), or None when it isn't a number."""
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    return v * _SEMI if abs(v) > 180 else float(v)


def _pair(v):
    """[lat, lng] (a start_latlng) as degrees, or None."""
    if isinstance(v, (list, tuple)) and len(v) == 2:
        a, b = _deg(v[0]), _deg(v[1])
        if a is not None and b is not None:
            return a, b
    return None


def _entered(line, pieces):
    """Whether Hider.pieces took anything out of the line (it also adds points near a zone, so the lengths can't say)."""
    return len(pieces) != 1 or pieces[0][0] != list(line[0]) or pieces[0][-1] != list(line[-1])


def _cut_polyline(text, zones):
    """An encoded polyline (Strava's summary_polyline) with what's inside the zones taken out: the pieces left, joined. (text, changed)."""
    import polyline
    try:
        pts = polyline.decode(text)
    except Exception:
        return text, False
    if not pts:
        return text, False
    line = [list(p) for p in pts]
    pieces = zones.pieces(line)
    if not _entered(line, pieces):
        return text, False
    return polyline.encode([tuple(p) for piece in pieces for p in piece]), True


def _cut(value, zones):
    """(value with every position inside the zones taken out, all the way down, whether any was): streams cut as a friend's feed is
    (Hider.streams), a lat and lng pair under any keys that say so (startLat/startLng, start_latitude/start_longitude, position_lat/
    position_long) taken out together, a [lat, lng] (start_latlng) or a list of them, and an encoded polyline cut. A string that is itself
    JSON (a parked copy's rawData) too."""
    if isinstance(value, dict):
        cut = zones.streams(value)
        if cut is not None:
            return cut, True
        out, changed, gone = {}, False, set()
        for k in value:                                     # pairs of keys: both go when the place is inside
            m = _LAT.match(k) if isinstance(k, str) else None
            if not m:
                continue
            partner = next((m.group(1) + w + m.group(3) for w in (*_LNG_FOR, *(x.capitalize() for x in _LNG_FOR),
                                                                   *(x.upper() for x in _LNG_FOR))
                            if m.group(1) + w + m.group(3) in value), None)
            if partner:
                lat, lng = _deg(value[k]), _deg(value[partner])
                if lat is not None and lng is not None and zones.inside(lat, lng):
                    gone |= {k, partner}
        for k, v in value.items():
            if k in gone:
                changed = True
                continue
            if isinstance(k, str) and _POLY.search(k) and isinstance(v, str) and v and v[:1] not in '{[':
                out[k], c = _cut_polyline(v, zones)
            elif isinstance(k, str) and _GPS.search(k) and _pair(v) is not None:
                out[k], c = ([], True) if zones.inside(*_pair(v)) else (v, False)
            else:
                out[k], c = _cut(v, zones)
            changed |= c
        return (out, True) if changed else (value, False)
    if isinstance(value, list):
        if not value or isinstance(value[0], (int, float, type(None))):
            return value, False
        if _pair(value[0]) is not None:                     # a list of positions
            kept = [p for p in value if _pair(p) is None or not zones.inside(*_pair(p))]
            return (kept, True) if len(kept) != len(value) else (value, False)
        pairs = [_cut(v, zones) for v in value]
        return ([v for v, _ in pairs], True) if any(c for _, c in pairs) else (value, False)
    if isinstance(value, str) and value[:1] in '{[':
        try:
            inner = json.loads(value)
        except ValueError:
            return value, False
        clean, changed = _cut(inner, zones)
        return (json.dumps(clean), True) if changed else (value, False)
    return value, False


def _cut_json(db, table, col, zones):
    if col not in _cols(db, table):
        return 0
    n = 0
    for rowid, raw in db.execute(f'SELECT rowid, "{col}" FROM "{table}" WHERE "{col}" IS NOT NULL').fetchall():
        try:
            value = json.loads(raw)
        except (TypeError, ValueError):
            continue
        clean, changed = _cut(value, zones)
        if changed:
            db.execute(f'UPDATE "{table}" SET "{col}"=? WHERE rowid=?', [json.dumps(clean), rowid])
            n += 1
    return n


def _cut_packed(db, table, col, key, zones, ids=None):
    """Streams stored compressed (services/streams.pack) cut: {key value: the cut latlng} of the rows that changed. ids: only these rows."""
    out = {}
    if table not in _tables(db) or col not in _cols(db, table):
        return out
    keys = [r[0] for r in db.execute(f'SELECT "{key}" FROM "{table}" WHERE "{col}" IS NOT NULL').fetchall()]
    for k in keys if ids is None else [k for k in keys if k in ids]:
        raw = db.execute(f'SELECT "{col}" FROM "{table}" WHERE "{key}"=?', [k]).fetchone()[0]
        try:
            whole = json.loads(streams.unpack(raw) or 'null')
        except (TypeError, ValueError, Exception):
            continue
        cut = zones.streams(whole)
        if cut is None:
            continue
        db.execute(f'UPDATE "{table}" SET "{col}"=? WHERE "{key}"=?', [streams.pack(cut), k])
        ll = cut.get('latlng')
        out[k] = ll.get('data') if isinstance(ll, dict) else ll
    return out


def _cut_route(row, zones):
    """(track JSON, waypoints JSON) of a planned route with what's inside the zones taken out, or None for unchanged. A track's points are
    close together, so those inside go; waypoints can be far apart, so their line is cut at the zones' edges (Hider.pieces), joined."""
    try:
        track = json.loads(row['track']) if row['track'] else None
        wps = json.loads(row['waypoints'] or '[]')
    except (TypeError, ValueError):
        return None
    changed = False
    if track:
        kept = [p for p in track if not zones.inside(p[0], p[1])]
        if len(kept) != len(track):
            track, changed = kept, True
    if wps and all(isinstance(w, dict) and 'lat' in w and 'lng' in w for w in wps):
        line = [[w['lat'], w['lng']] for w in wps]
        pieces = zones.pieces(line)
        if _entered(line, pieces):
            wps, changed = [{'lat': p[0], 'lng': p[1]} for piece in pieces for p in piece], True
    if not changed:
        return None
    return (json.dumps(track, separators=(',', ':')) if track else None), json.dumps(wps)


def _without_zones(db, tables, zones):
    """What the module docstring says, with GPS left in. Doesn't commit."""
    streams.register(db)
    touched = {}
    if 'Activity' in tables and 'updatedAt' in _cols(db, 'Activity'):
        touched = dict(db.execute('SELECT id, updatedAt FROM Activity').fetchall())
    # The streams, read only for activities whose track summary says they may go into a zone (or that have none yet)
    ids = None
    if 'ActivityTrack' in tables:
        ids = set()
        have = {}
        for aid, a, b, c, d, cells in db.execute('SELECT activityId, minLat, maxLat, minLng, maxLng, cells FROM ActivityTrack').fetchall():
            have[aid] = a is not None and zones.may_cross([a, b, c, d], cells)
        for (aid,) in db.execute('SELECT activityId FROM ActivityStream').fetchall() if 'ActivityStream' in tables else []:
            if have.get(aid, True):
                ids.add(aid)
    cut = _cut_packed(db, 'ActivityStream', 'data', 'activityId', zones, ids)    # its trigger drops the track summary
    # Start points: inside a zone, the first position of the cut track, or none
    if 'Activity' in tables:
        for aid, lat, lng in db.execute('SELECT id, startLat, startLng FROM Activity WHERE startLat IS NOT NULL').fetchall():
            if zones.inside(lat, lng):
                new = zones.start(lat, lng, cut.get(aid))
                db.execute('UPDATE Activity SET startLat=?, startLng=? WHERE id=?', [new[0], new[1], aid])
        for aid, text in db.execute("SELECT id, summaryPolyline FROM Activity WHERE summaryPolyline IS NOT NULL AND summaryPolyline != ''").fetchall():
            clean, changed = _cut_polyline(text, zones)
            if changed:
                db.execute('UPDATE Activity SET summaryPolyline=? WHERE id=?', [clean, aid])
        for col in ('rawData', 'laps', 'streams'):
            _cut_json(db, 'Activity', col, zones)
    # The other copies of an activity: their own streams column, and the row as JSON (a parked copy's start, polyline, rawData, laps, and its
    # streams when kept from before database step 5)
    _cut_packed(db, 'ActivityDuplicate', 'streams', 'rowid', zones)
    _cut_packed(db, 'ImportChange', 'streams', 'rowid', zones)
    if 'ActivityDuplicate' in tables:
        _cut_json(db, 'ActivityDuplicate', 'rowJson', zones)
    for t, cols in _JSON.items():
        if t in tables:
            for c in cols:
                _cut_json(db, t, c, zones)
    if 'PlannedRoute' in tables:
        for row in db.execute('SELECT id, track, waypoints FROM PlannedRoute').fetchall():
            got = _cut_route({'track': row[1], 'waypoints': row[2]}, zones)
            if got is None:
                continue
            track, wps = got
            if len(json.loads(track or '[]')) < 2 and len(json.loads(wps)) < 2:
                db.execute('DELETE FROM PlannedRoute WHERE id=?', [row[0]])         # nothing left of it outside
            else:
                db.execute('UPDATE PlannedRoute SET track=?, waypoints=? WHERE id=?', [track, wps, row[0]])
    if 'Segment' in tables:                                 # a segment is a line on the map: one that goes inside says where
        gone = []
        for sid, a, b, c, d, poly in db.execute('SELECT id, startLat, startLng, endLat, endLng, polyline FROM Segment').fetchall():
            try:
                pts = json.loads(poly) if poly else []
            except ValueError:
                pts = []
            line = [[a, b]] + [p[:2] for p in pts if isinstance(p, list) and len(p) >= 2] + [[c, d]]
            if a is None or c is None:
                continue
            if _entered(line, zones.pieces(line)):
                gone.append(sid)
        for sid in gone:
            if 'SegmentEffort' in tables:
                db.execute('DELETE FROM SegmentEffort WHERE segmentId=?', [sid])
            db.execute('DELETE FROM Segment WHERE id=?', [sid])
    if touched:                                             # the triggers moved updatedAt on: put it back
        for aid, was in db.execute('SELECT id, updatedAt FROM Activity').fetchall():
            if aid in touched and touched[aid] != was:
                db.execute('UPDATE Activity SET updatedAt=? WHERE id=?', [touched[aid], aid])


def _without_streams(db, tables):
    if 'ActivityStream' in tables:
        db.execute('DELETE FROM ActivityStream')
    for t in ('ActivityDuplicate', 'ImportChange'):
        if t in tables and 'streams' in _cols(db, t):
            db.execute(f'UPDATE {t} SET streams=NULL')
    if 'ActivityDuplicate' in tables:
        for rowid, raw in db.execute("SELECT rowid, rowJson FROM ActivityDuplicate WHERE rowJson LIKE '%\"streams\"%'").fetchall():
            try:
                row = json.loads(raw)
            except (TypeError, ValueError):
                continue
            if isinstance(row, dict) and row.get('streams') is not None:
                row['streams'] = None
                db.execute('UPDATE ActivityDuplicate SET rowJson=? WHERE rowid=?', [json.dumps(row), rowid])
    if 'ActivitySensor' in tables:
        _blank(db, 'ActivitySensor', ('data',))


def strip(db, no_gps=False, no_streams=False):
    """Take out of `db` (the copy) what the module docstring says, and GPS or the streams when asked; with GPS left in, what's inside the
    privacy zones. Doesn't commit."""
    tables = _tables(db)
    zones = _zones(db, tables) if not (no_gps or no_streams) else None      # before the zones go, below
    for t, cols in (*vault.COLUMNS.items(), *vault.DEAD.items()):
        if t in tables:
            _blank(db, t, cols)
    _blank(db, 'Settings', ADDRESSES)
    for t, cols in STATUS.items():
        if t in tables:
            for c in [c for c in cols if c in _cols(db, t)]:
                for rowid, v in db.execute(f'SELECT rowid, "{c}" FROM "{t}" WHERE "{c}" IS NOT NULL').fetchall():
                    clean = _URL.sub(r'\1<address>', diagnostics._clean(v)) if isinstance(v, str) else v
                    if clean != v:
                        db.execute(f'UPDATE "{t}" SET "{c}"=? WHERE rowid=?', [clean, rowid])
    for t, label in (('FeedToken', 'Token'), ('DeviceToken', 'Phone')):      # hashes only, but a name says whose
        if t in tables:
            db.execute(f"UPDATE {t} SET name='{label} ' || id, tokenHash='removed-' || id")
    # the addresses of failed sign-ins, where a rider was a moment ago, the people their live links go to, and their privacy zones (home)
    for t in ('SignInFail', 'LiveReading', 'LivePoint', 'LiveShare', 'Contact', 'ContactSend', 'PrivacyZone'):
        if t in tables:
            db.execute(f'DELETE FROM {t}')
    _without_friends(db, tables)
    for t, cols in _LISTINGS.items():
        if t in tables:
            for c in cols:
                _scrub_json(db, t, c, _OWNER)
    if no_streams:
        _without_streams(db, tables)
    if no_gps or no_streams:                        # a track's line and start point would still show the route
        _without_gps(db, tables)
    elif zones:
        _without_zones(db, tables, zones)


def readme(no_gps, no_streams):
    out = [f'A copy of a Headwind database for troubleshooting, made {datetime.now():%Y-%m-%d %H:%M}.', '',
           'Taken out: every saved key, password and token, the Garmin email, the addresses of Home Assistant, Ollama, ntfy, the MQTT '
           'broker, the mail server and friends\' servers, the contacts live links go to, your privacy zones, friends\' names, riders, activities, segments '
           'and foods, and every photo and avatar.']
    if no_gps or no_streams:
        out.append('Also taken out: GPS (tracks, start points, segments and planned routes).')
    if no_streams:
        out.append('Also taken out: the activities\' streams (GPS, heart rate, power and the rest, point by point).')
    out += ['', f'Left in it: {LEFT}' + ('.' if no_gps or no_streams else ', and the GPS tracks, with the places inside your privacy zones '
                                         'cut out of them.'), '',
            'It is a Headwind backup with no photos: Settings -> Backup & Restore -> Restore loads it into a test server.']
    return '\n'.join(out) + '\n'


@downloads.maker(KIND)
def _make(args, work_dir, report):
    return build(args['database'], work_dir, no_gps=args['no_gps'], no_streams=args['no_streams'])


def build(database, tmp_dir, no_gps=False, no_streams=False):
    """Write the zip into tmp_dir and return its path."""
    snap = os.path.join(tmp_dir, 'snapshot.db')
    src = sqlite3.connect(database, timeout=60)
    dst = sqlite3.connect(snap)
    try:
        src.backup(dst)
    finally:
        src.close()
    try:
        dst.execute('PRAGMA journal_mode = DELETE')
        strip(dst, no_gps=no_gps, no_streams=no_streams)
        dst.commit()
        out = os.path.join(tmp_dir, 'headwind.db')
        dst.execute('VACUUM INTO ?', [out])          # a fresh file: nothing taken out is left in a free page
    finally:
        dst.close()
    os.remove(snap)
    zip_path = os.path.join(tmp_dir, 'headwind-troubleshooting.zip')
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED, compresslevel=1) as zf:     # 13% bigger than the default, 8x as quick
        zf.write(out, 'headwind.db')
        zf.writestr('README.txt', readme(no_gps, no_streams))
    os.remove(out)
    return zip_path
