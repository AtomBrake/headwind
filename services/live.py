"""Live ride: the phone streams position, speed and motion-sensor readings while it records, and this turns them into Home Assistant entities.

The phone never talks to MQTT itself when it is paired with a server (only one publisher per broker, or sensors overwrite each other), so it
POSTs /api/v1/live every few seconds and this module publishes: a handful of sensors (status, speed, distance, elapsed, elevation, roughness,
lean, pressure, phone battery) plus a device_tracker whose attributes carry the position, so the HA map card can follow the ride.
A final {"state": "idle"} ends it; if the stream just stops (phone died, no signal) the worker marks the ride idle after IDLE_AFTER_S (go_idle).

The last reading is kept per rider in LiveReading, not in this process's memory: with more than one web process, the phone's POSTs land on
any of them, and the worker that checks for silence is a process of its own.
"""
import json
import logging
import time

log = logging.getLogger(__name__)

IDLE_AFTER_S = 90
IDLE_CHECK_S = 15         # how often the worker looks for a ride gone quiet
MIN_PUBLISH_GAP_S = 2.0

SENSORS = [   # (uid, name, icon, unit)
    ('live_ride_status',        'Live Ride Status',        'mdi:bike-fast',        None),
    ('live_ride_sport',         'Live Ride Sport',         'mdi:run',              None),
    ('live_ride_speed_mph',     'Live Ride Speed',         'mdi:speedometer',      'mph'),
    ('live_ride_distance_mi',   'Live Ride Distance',      'mdi:map-marker-distance', 'mi'),
    ('live_ride_elapsed',       'Live Ride Elapsed',       'mdi:timer-outline',    None),
    ('live_ride_elevation_ft',  'Live Ride Elevation',     'mdi:elevation-rise',   'ft'),
    ('live_ride_roughness',     'Live Ride Roughness',     'mdi:road-variant',     'm/s²'),
    ('live_ride_lean_deg',      'Live Ride Lean',          'mdi:angle-acute',      '°'),
    ('live_ride_pressure_hpa',  'Live Ride Pressure',      'mdi:gauge',            'hPa'),
    ('live_ride_phone_battery', 'Live Ride Phone Battery', 'mdi:cellphone',        '%'),
]
TRACKER = ('live_ride_position', 'Live Ride Position', 'mdi:bike')

_sent = {'discovery': False}    # per process: discovery is retained by the broker, so each process sending it once is harmless


def _fmt_elapsed(secs):
    secs = int(max(0, secs or 0))
    return '%d:%02d:%02d' % (secs // 3600, (secs % 3600) // 60, secs % 60)


def _f(v, nd=1):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return None if x != x else round(x, nd)


def clean(payload):
    """The fields we trust from the phone, converted to what Home Assistant shows (miles, mph, feet)."""
    p = payload if isinstance(payload, dict) else {}
    state = 'riding' if str(p.get('state') or 'riding') != 'idle' else 'idle'
    spd = _f(p.get('speed_mps'), 3)
    dist = _f(p.get('distance_m'), 1)
    alt = _f(p.get('alt_m'), 1)
    sens = p.get('sensors') if isinstance(p.get('sensors'), dict) else {}
    lat, lng = _f(p.get('lat'), 6), _f(p.get('lng'), 6)
    if lat is not None and lng is not None and not (-90 <= lat <= 90 and -180 <= lng <= 180):
        lat = lng = None
    return {
        'state': state, 'sport': str(p.get('sport') or '')[:20], 'ts': time.time(),
        'lat': lat, 'lng': lng, 'acc': _f(p.get('accuracy_m'), 0),
        'speed_mph': None if spd is None else round(spd * 2.23694, 1),
        'distance_mi': None if dist is None else round(dist / 1609.344, 2),
        'elapsed': _fmt_elapsed(p.get('elapsed_s')),
        'elevation_ft': None if alt is None else round(alt * 3.28084),
        'roughness': _f(sens.get('rough'), 2), 'lean': _f(sens.get('tilt'), 1), 'pressure': _f(sens.get('press'), 1),
        'battery': _f(p.get('battery_pct'), 0),
        # as the phone sent them, for the live tracking link (services/live_share.py), which shows them in the rider's units
        'recording': str(p.get('recording') or '').strip()[:64], 'speed_mps': spd, 'distance_m': dist,
        'elapsed_s': _f(p.get('elapsed_s'), 0), 'alt_m': alt,
    }


def states_for(c):
    """{uid: state string} for the sensors; missing readings are 'unknown'."""
    riding = c['state'] == 'riding'
    s = lambda v: 'unknown' if v is None else str(v)
    return {
        'live_ride_status': c['state'], 'live_ride_sport': c['sport'] or 'unknown',
        'live_ride_speed_mph': s(c['speed_mph'] if riding else 0), 'live_ride_distance_mi': s(c['distance_mi']),
        'live_ride_elapsed': c['elapsed'], 'live_ride_elevation_ft': s(c['elevation_ft']),
        'live_ride_roughness': s(c['roughness']), 'live_ride_lean_deg': s(c['lean']),
        'live_ride_pressure_hpa': s(c['pressure']), 'live_ride_phone_battery': s(c['battery']),
    }


def tracker_attrs(c):
    a = {'source_type': 'gps'}
    if c['lat'] is not None and c['lng'] is not None:
        a.update(latitude=c['lat'], longitude=c['lng'], gps_accuracy=c['acc'] or 10)
    return a


def build_messages(c, with_discovery):
    """The MQTT messages for one update (pure: no network)."""
    from services import mqtt
    msgs = []
    if with_discovery:
        for uid, name, icon, unit in SENSORS:
            config_topic, state_topic, config_json = mqtt._discovery(uid, name, icon, unit)
            msgs.append({'topic': config_topic, 'payload': config_json, 'retain': True, 'qos': 1})
        p = mqtt._prefix()
        uid, name, icon = TRACKER
        cfg = {'name': name, 'unique_id': f'{p}_{uid}', 'icon': icon, 'device': mqtt._device(),
               'state_topic': f'homeassistant/device_tracker/{p}_{uid}/state', 'json_attributes_topic': f'homeassistant/device_tracker/{p}_{uid}/attributes',
               'payload_home': 'home', 'payload_not_home': 'not_home', 'source_type': 'gps'}
        if p != mqtt._DEFAULT_PREFIX:
            cfg['default_entity_id'] = f'device_tracker.{p}_{uid}'
        msgs.append({'topic': f'homeassistant/device_tracker/{p}_{uid}/config', 'payload': json.dumps(cfg), 'retain': True, 'qos': 1})
    for uid, val in states_for(c).items():
        msgs.append({'topic': f'homeassistant/sensor/{mqtt._prefix()}_{uid}/state', 'payload': val, 'retain': True, 'qos': 1})
    p = mqtt._prefix()
    uid = TRACKER[0]
    msgs.append({'topic': f'homeassistant/device_tracker/{p}_{uid}/attributes', 'payload': json.dumps(tracker_attrs(c)), 'retain': True, 'qos': 1})
    msgs.append({'topic': f'homeassistant/device_tracker/{p}_{uid}/state', 'payload': 'not_home', 'retain': True, 'qos': 1})
    return msgs


def _connection():
    from services import mqtt
    return mqtt.broker()


def _publish(c, sender=None, conn=None):
    conn = conn if conn is not None else _connection()
    if not conn:
        return False
    from services import mqtt
    msgs = build_messages(c, with_discovery=not _sent['discovery'])
    try:
        (sender or mqtt._broker_send)(msgs, *conn)
        _sent['discovery'] = True
        return True
    except Exception as e:
        log.warning('live ride publish failed (non-fatal): %s', e)
        return False


def _rider_id(db):
    r = db.execute('SELECT id FROM Rider WHERE isDefault=1 ORDER BY id LIMIT 1').fetchone()
    return r[0] if r else 0


def _save(db, rider_id, c, published_at):
    db.execute('INSERT INTO LiveReading (riderId, reading, state, ts, publishedAt) VALUES (?, ?, ?, ?, ?) ON CONFLICT(riderId) DO UPDATE SET '
               'reading=excluded.reading, state=excluded.state, ts=excluded.ts, publishedAt=excluded.publishedAt',
               [rider_id, json.dumps(c), c['state'], c['ts'], published_at])
    db.commit()


def announce(sender=None, conn=None):
    """Publish the live-ride entities (retained discovery + an idle state) once, without a ride, so Home Assistant has them, and the Live dashboard tab can show,
    before the first ride is ever streamed. Safe to repeat. Returns True if published."""
    from database import get_db
    if get_db().execute('SELECT 1 FROM LiveReading LIMIT 1').fetchone():
        return False              # a real reading has already gone out
    return _publish(clean({'state': 'idle'}), sender, conn)


def update(payload, sender=None, conn=None, rider_id=None):
    """Handle one POST from the phone, for the default rider (as /api/v1 is) unless told whose. Returns the cleaned reading. Publishes at
    most every MIN_PUBLISH_GAP_S, but always publishes idle and a change of state. The rider's live tracking link of this recording, if
    there is one, takes it too (services/live_share.py)."""
    from database import get_db
    from services import live_share
    c = clean(payload)
    db = get_db()
    rider_id = _rider_id(db) if rider_id is None else rider_id
    prev = db.execute('SELECT state, publishedAt FROM LiveReading WHERE riderId=?', [rider_id]).fetchone()
    published_at = prev['publishedAt'] if prev else 0.0
    if c['state'] == 'idle' or prev is None or prev['state'] != c['state'] or time.time() - published_at >= MIN_PUBLISH_GAP_S:
        if _publish(c, sender, conn):         # before the write, so no write lock is held while the broker answers
            published_at = time.time()
    live_share.record(db, rider_id, c)
    _save(db, rider_id, c, published_at)          # commits both
    return c


def go_idle(db, sender=None, conn=None):
    """A ride with no reading for IDLE_AFTER_S: the phone went away. Mark it idle (keeping the last position) and publish that. The worker runs
    this every IDLE_CHECK_S. Returns how many went idle."""
    n = 0
    for r in db.execute("SELECT riderId, reading, ts FROM LiveReading WHERE state='riding' AND ts < ?", [time.time() - IDLE_AFTER_S]).fetchall():
        last = dict(json.loads(r['reading']), state='idle', ts=time.time())
        cur = db.execute("UPDATE LiveReading SET reading=?, state='idle', ts=? WHERE riderId=? AND state='riding' AND ts=?",
                         [json.dumps(last), last['ts'], r['riderId'], r['ts']])
        db.commit()
        if cur.rowcount:                  # not if a reading came in meanwhile
            _publish(last, sender, conn)
            n += 1
    return n


def snapshot():
    """The default rider's last reading, or None."""
    from database import get_db
    db = get_db()
    r = db.execute('SELECT reading FROM LiveReading WHERE riderId=?', [_rider_id(db)]).fetchone()
    return json.loads(r['reading']) if r else None
