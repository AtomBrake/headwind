"""Each activity's streams (time, latlng, distance, altitude, heart rate, power, ... in Strava's JSON shape) in ActivityStream, one row per
activity, zlib'd. They were three quarters of the database as JSON in Activity.streams, and every SELECT * on Activity carried a megabyte a row.
Moved by database step 2.

Reading: sql() is an expression that gives the streams as JSON text, for a SELECT list (`SELECT id, {streams.sql('a')} FROM Activity a`), so a
row's 'streams' is the same text it always was; load() gives one activity's parsed. streams_json(), the SQL function it uses, is registered on
every connection get_db() makes (register() for any other). has_sql() is the test for an activity with streams.

Writing: save(), which stores nothing for empty streams. An activity's row is written first, then its streams. Triggers (ensure_schema) take the
streams with an activity deleted or given a new id, drop its track summary (services/tracks.py) when its streams change, and move its updatedAt
on when they change, so a friend's feed sends it again (as database._views_and_triggers does for its other columns)."""
import json
import zlib

FORMAT = 1                      # zlib'd JSON text, UTF-8
EMPTY = (None, '', 'null', '{}', b'')


def ensure_schema(db):
    """Does not commit."""
    db.execute('''CREATE TABLE IF NOT EXISTS ActivityStream (
        activityId TEXT PRIMARY KEY,
        format     INTEGER NOT NULL DEFAULT 1,
        data       BLOB NOT NULL
    )''')
    db.execute('CREATE TRIGGER IF NOT EXISTS ActivityStream_gone AFTER DELETE ON Activity '
               'BEGIN DELETE FROM ActivityStream WHERE activityId = OLD.id; END')
    db.execute('CREATE TRIGGER IF NOT EXISTS ActivityStream_renamed AFTER UPDATE OF id ON Activity WHEN NEW.id IS NOT OLD.id '
               'BEGIN UPDATE ActivityStream SET activityId = NEW.id WHERE activityId = OLD.id; END')
    # Changed or removed streams move the activity's updatedAt on. Not the first ones it gets: they come with the activity's row (a new
    # activity, one put back from Recently deleted, a friend's), whose own write says when it changed.
    touch = "UPDATE Activity SET updatedAt = strftime('%Y-%m-%d %H:%M:%f', 'now') WHERE id = {}.activityId"
    db.execute(f'CREATE TRIGGER IF NOT EXISTS ActivityStream_touch_update AFTER UPDATE OF data ON ActivityStream WHEN NEW.data IS NOT OLD.data '
               f'BEGIN {touch.format("NEW")}; END')
    db.execute(f'CREATE TRIGGER IF NOT EXISTS ActivityStream_touch_delete AFTER DELETE ON ActivityStream BEGIN {touch.format("OLD")}; END')


def pack(streams):
    """Streams (a dict, or its JSON text) as stored, or None when there are none."""
    if isinstance(streams, (dict, list)):
        streams = json.dumps(streams) if streams else None
    if isinstance(streams, bytes):
        streams = streams.decode()
    if streams in EMPTY:
        return None
    return zlib.compress(streams.encode(), 6)


def unpack(data):
    """The stored bytes as JSON text, or None."""
    if data is None:
        return None
    return zlib.decompress(data).decode()


def register(conn):
    """streams_json(data) on this connection, what sql() needs, and streams_pack(text), its opposite."""
    conn.create_function('streams_json', 1, unpack, deterministic=True)
    conn.create_function('streams_pack', 1, pack, deterministic=True)


def sql(alias='Activity', name='streams'):
    """An expression for a SELECT list: the activity's streams as JSON text (NULL for none), named `name`. alias is the table or view the
    activity's id comes from (Activity, Ride, a)."""
    return f'(SELECT streams_json(s.data) FROM ActivityStream s WHERE s.activityId = {alias}.id) AS {name}'


def has_sql(alias='Activity', key=None):
    """True for an activity with streams (save() stores none for empty ones), or, with key, with that stream ('latlng': a GPS track)."""
    also = f""" AND instr(streams_json(s.data), '"{key}"') > 0""" if key else ''
    return f'EXISTS (SELECT 1 FROM ActivityStream s WHERE s.activityId = {alias}.id{also})'


def load_json(db, activity_id):
    row = db.execute('SELECT data FROM ActivityStream WHERE activityId=?', [activity_id]).fetchone()
    return unpack(row[0]) if row else None


def load(db, activity_id):
    """One activity's streams, parsed: {} when it has none."""
    text = load_json(db, activity_id)
    return json.loads(text) if text else {}


def save(db, activity_id, streams):
    """Store an activity's streams (a dict or its JSON text), replacing any it had; empty ones delete them. Does not commit."""
    data = pack(streams)
    if data is None:
        db.execute('DELETE FROM ActivityStream WHERE activityId=?', [activity_id])
    else:
        db.execute('INSERT INTO ActivityStream (activityId, format, data) VALUES (?, ?, ?) '
                   'ON CONFLICT(activityId) DO UPDATE SET format=excluded.format, data=excluded.data WHERE data IS NOT excluded.data',
                   [activity_id, FORMAT, data])


def split(row):
    """(a copy of an activity's row as a dict without its streams, the streams): for writing a whole row kept elsewhere (a parked copy, a
    friend's) back into Activity."""
    row = dict(row)
    return row, row.pop('streams', None)
