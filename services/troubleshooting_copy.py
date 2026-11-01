"""The "Download a copy for troubleshooting" zip on the Tasks page: the database, for someone helping with a problem the diagnostics zip
(services/diagnostics.py: no data) can't show, with what isn't needed taken out. Only the copy is changed, never the live database.

Always taken out: every saved key, password and token (even encrypted), the Garmin email, addresses (Home Assistant, Ollama, ntfy, the
MQTT broker and user, friends' servers), the install id, friends' names, their riders with everything of theirs (activities, photos, best
times, weigh-ins, food), their segments and foods, the names of feed tokens and paired phones, and the Garmin account's name in Garmin's
listings. No photo or avatar file goes in the zip. On request: GPS (tracks, start points, segments, planned routes, and the coordinates in
the other copies of an activity), or the streams altogether (heart rate, power and the rest, and GPS with them).

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

from services import diagnostics, vault

KIND = 'troubleshooting'        # its job in services/downloads.py

# Settings columns emptied besides the secrets (vault.COLUMNS): addresses, user names, the install's id, a path on the server (mqttCaFile).
ADDRESSES = ('garminEmail', 'haUrl', 'ollamaUrl', 'ntfyUrl', 'mqttHost', 'mqttUser', 'mqttCaFile', 'installId', 'webhookSubId')
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
         'RideSensor': ('data', 'summary')}

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
        for c in ('activityId', 'rideId'):
            if c in cols:
                db.execute(f'DELETE FROM "{t}" WHERE "{c}" IN (SELECT id FROM _gone)')
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
    # reading each into Python would (15 s against 40 s for 1.5 GB). A parked duplicate's row holds its streams as a string.
    db.execute("UPDATE Activity SET streams=json_remove(streams, '$.latlng') WHERE json_valid(streams) AND json_type(streams, '$.latlng') IS NOT NULL")
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


def _without_streams(db, tables):
    _blank(db, 'Activity', ('streams',))
    if 'ActivityDuplicate' in tables:
        for rowid, raw in db.execute("SELECT rowid, rowJson FROM ActivityDuplicate WHERE rowJson LIKE '%\"streams\"%'").fetchall():
            try:
                row = json.loads(raw)
            except (TypeError, ValueError):
                continue
            if isinstance(row, dict) and row.get('streams') is not None:
                row['streams'] = None
                db.execute('UPDATE ActivityDuplicate SET rowJson=? WHERE rowid=?', [json.dumps(row), rowid])
    if 'RideSensor' in tables:
        _blank(db, 'RideSensor', ('data',))


def strip(db, no_gps=False, no_streams=False):
    """Take out of `db` (the copy) what the module docstring says, and GPS or the streams when asked. Doesn't commit."""
    tables = _tables(db)
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
    _without_friends(db, tables)
    for t, cols in _LISTINGS.items():
        if t in tables:
            for c in cols:
                _scrub_json(db, t, c, _OWNER)
    if no_streams:
        _without_streams(db, tables)
    if no_gps or no_streams:                        # a track's line and start point would still show the route
        _without_gps(db, tables)


def readme(no_gps, no_streams):
    out = [f'A copy of a Headwind database for troubleshooting, made {datetime.now():%Y-%m-%d %H:%M}.', '',
           'Taken out: every saved key, password and token, the Garmin email, the addresses of Home Assistant, Ollama, ntfy, the MQTT '
           'broker and friends\' servers, friends\' names, riders, activities, segments and foods, and every photo and avatar.']
    if no_gps or no_streams:
        out.append('Also taken out: GPS (tracks, start points, segments and planned routes).')
    if no_streams:
        out.append('Also taken out: the activities\' streams (GPS, heart rate, power and the rest, point by point).')
    out += ['', f'Left in it: {LEFT}' + ('.' if no_gps or no_streams else ', and the GPS tracks.'), '',
            'It is a Headwind backup with no photos: Settings -> Backup & Restore -> Restore loads it into a test server.']
    return '\n'.join(out) + '\n'


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
