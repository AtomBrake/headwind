"""Activity files a Strava export holds that the importer used to give up on, saving the activity from activities.csv alone with no track: a FIT
named .bin that ends without its CRC, a FIT saved as an escaped Ruby string, a recording from Strava's own app (.json), and a GPX with a UUID in
<number> and no <trkseg>. Also what the import says when it still can't read one. Full app, throwaway DB, files made here (no real athlete's)."""
import io
import json
import struct
import zipfile
from datetime import datetime, timedelta, timezone

import pytest
from fitparse.utils import FitParseError

import app as app_module
import config
import database
from routes import import_rides
from services import credentials, parser, reimport

FIT_EPOCH = 631065600              # 1989-12-31T00:00:00Z
START = datetime(2026, 7, 3, 9, 0, tzinfo=timezone.utc)


def _crc(data):
    t = (0x0000, 0xCC01, 0xD801, 0x1400, 0xF001, 0x3C00, 0x2800, 0xE401, 0xA001, 0x6C00, 0x7800, 0xB401, 0x5000, 0x9C01, 0x8801, 0x4400)
    crc = 0
    for b in data:
        for nib in (b & 0xF, b >> 4):
            tmp = t[crc & 0xF]
            crc = ((crc >> 4) & 0x0FFF) ^ tmp ^ t[nib]
    return crc


def track(n=61, step_s=10, lat0=54.5, alt=lambda i: 100 + i):
    """(seconds, lat, lng, altitude, distance) for n points, about 33 m apart."""
    return [(i * step_s, lat0 + i * 0.0003, -1.9, alt(i), i * 33.36) for i in range(n)]


def fit_file(points, start=START, session=True, crc=True, sport=2):
    """A minimal FIT activity: record messages (time, position, altitude, distance) and, optionally, a session. sport 2 is cycling."""
    body = bytearray()
    rec = ((253, 4, 0x86), (0, 4, 0x85), (1, 4, 0x85), (2, 2, 0x84), (5, 4, 0x86))
    body += struct.pack('<BBBHB', 0x40, 0, 0, 20, len(rec)) + b''.join(struct.pack('BBB', *f) for f in rec)
    ts0 = int(start.timestamp()) - FIT_EPOCH
    semi = lambda deg: 0x7FFFFFFF if deg is None else round(deg * 2 ** 31 / 180)      # FIT's "no value": a record with no fix
    for s, lat, lng, alt, d in points:
        body += struct.pack('<BIiiHI', 0, ts0 + s, semi(lat), semi(lng), round((alt + 500) * 5), round(d * 100))
    if session:
        ses = ((253, 4, 0x86), (2, 4, 0x86), (7, 4, 0x86), (8, 4, 0x86), (9, 4, 0x86), (5, 1, 0x00))
        body += struct.pack('<BBBHB', 0x41, 0, 0, 18, len(ses)) + b''.join(struct.pack('BBB', *f) for f in ses)
        last = points[-1]
        body += struct.pack('<BIIIIIB', 1, ts0 + last[0], ts0, last[0] * 1000, last[0] * 1000, round(last[4] * 100), sport)
    header = struct.pack('<BBHI4s', 14, 0x10, 2132, len(body), b'.FIT')
    out = header + struct.pack('<H', _crc(header)) + bytes(body)
    return out + struct.pack('<H', _crc(out)) if crc else out


def ruby_escaped(data):
    """A file as Strava's export keeps some FITs: ["<Ruby string literal>", true]."""
    esc = {0x1b: r'\e', 0x0c: r'\f', 0x0a: r'\n', 0x09: r'\t', 0x0d: r'\r', 0x0b: r'\v', 0x08: r'\b', 0x07: r'\a', 0x22: r'\"', 0x5c: '\\\\', 0x23: r'\#'}
    lit = ''.join(esc.get(c) or (chr(c) if 0x20 <= c < 0x7f else f'\\x{c:02X}') for c in data)
    return f'["{lit}", true]'.encode()


def strava_app_json(n=61, step_s=10, pauses=((200, 300),), timer=None, sport='run'):
    """A recording from Strava's own app as the export keeps it: [JSON string of {metadata, data}, false]."""
    t0 = START.timestamp()
    meta = {'activity_type': sport, 'activity_name': 'Park loop', 'start_date': START.isoformat(), 'elapsed_time': (n - 1) * step_s}
    if timer:
        meta['timer_time'] = timer
    pts = [[t0 + s, [lat, lng], 0 if i < 2 else alt, 5.0, 3.3, t0 + s, d] for i, (s, lat, lng, alt, d) in enumerate(track(n, step_s))]
    ps = [v for a, b in pauses for v in ([t0 + a, 2], [t0 + b, 3])]
    doc = {'metadata': meta, 'data': [{'fields': ['time', 'latlng', 'elevation', 'h_accuracy', 'speed', 'device_time', 'distance'], 'values': pts},
                                      {'fields': ['time', 'pause_type'], 'values': ps}]}
    return json.dumps([json.dumps(doc), False]).encode()


def uuid_gpx(points=None, start=START, ele=None):
    """Strava's Android app's GPX (2014-16): a UUID in <number> and the points straight in <trk>."""
    points = points or track()
    pts = ''.join(f'<trkpt lat="{lat:.6f}" lon="{lng}"><ele>{(ele(i) if ele else alt):.1f}</ele>'
                  f'<time>{(start + timedelta(seconds=s)).strftime("%Y-%m-%dT%H:%M:%S.000Z")}</time></trkpt>\n'
                  for i, (s, lat, lng, alt, _) in enumerate(points))
    return (f'<?xml version="1.0" encoding="UTF-8"?><gpx version="1.1" creator="Strava Android Application" '
            f'xmlns="http://www.topografix.com/GPX/1/1"><trk><name>Morning Ride</name><number>801f3bce-4ddd-4974-9d79-52b8e8c35bc3</number>\n'
            f'{pts}</trk></gpx>').encode()


# ---------- the readers ----------

def test_a_fit_named_bin_that_ends_without_its_crc_is_read_whole():
    data = fit_file(track(), session=False, crc=False)
    act = parser.parse_activity_file('activities/1169465759.bin', data, strava_export=True)
    st = json.loads(act['streams'])
    assert len(st['time']['data']) == 61 and len(st['latlng']['data']) == 61
    assert act['elapsedTime'] == 600 and act['distance'] == pytest.approx(2001.6, abs=1) and act['totalElevationGain'] > 0
    assert act['startDateLocal'] == START.isoformat()


def test_a_bin_file_is_only_sniffed_inside_a_strava_export():
    assert parser.parse_activity_file('upload.bin', fit_file(track())) is None


def test_a_fit_that_is_junk_from_the_first_byte_still_fails():
    junk = b'\x0e\x10' + b'\xff' * 400
    with pytest.raises(FitParseError):
        parser.parse_activity_file('a.fit', junk)
    assert parser.parse_activity_file('activities/1.bin', b'PK\x03\x04 not an activity', strava_export=True) is None


def test_a_fit_saved_as_an_escaped_ruby_string_is_read():
    raw = fit_file(track(alt=lambda i: 27 + i % 9))          # bytes that need \e, \t, \n, \" and the rest
    escaped = ruby_escaped(raw)
    assert parser.unescape_ruby_fit(escaped) == raw
    act = parser.parse_activity_file('activities/7583442007.fit', escaped, strava_export=True)
    assert act['sportType'] == 'Ride' and act['distance'] == pytest.approx(2001.6, abs=1)
    assert len(json.loads(act['streams'])['latlng']['data']) == 61


def test_an_unknown_escape_is_refused():
    with pytest.raises(ValueError):
        parser.unescape_ruby_fit(b'["\\q", true]')


def test_a_recording_from_stravas_own_app():
    act = parser.parse_activity_file('activities/2973339872.json', strava_app_json(), strava_export=True)
    st = json.loads(act['streams'])
    assert act['sportType'] == 'Run' and act['name'] == 'Park loop' and act['startDateLocal'] == START.isoformat()
    assert act['movingTime'] == 500 and act['elapsedTime'] == 600                 # the 100 s paused left out
    assert act['totalElevationGain'] is None                                        # a phone's height: the export's figure is taken instead
    assert st['altitude']['data'][0] == st['altitude']['data'][2]                  # the 0 before the phone had a height isn't a 100 m drop
    assert len(st['latlng']['data']) == 61 and act['distance'] == pytest.approx(2001.6, abs=1)
    assert parser.parse_activity_file('activities/2973339872.json', strava_app_json(timer=480), strava_export=True)['movingTime'] == 480
    assert parser.parse_activity_file('upload.json', strava_app_json()) is None    # only inside a Strava export


def test_a_gpx_with_a_uuid_number_and_no_trkseg():
    act = parser.parse_gpx(uuid_gpx())
    assert act and len(json.loads(act['streams'])['latlng']['data']) == 61
    numbered = uuid_gpx().replace(b'801f3bce-4ddd-4974-9d79-52b8e8c35bc3', b'3')
    assert parser.parse_gpx(numbered)['distance'] == act['distance']                # an integer <number> is left alone


# ---------- the import ----------

CSV_HEAD = ('Activity ID,Activity Date,Activity Name,Activity Type,Elapsed Time,Distance,Filename,Moving Time,Distance,Elevation Gain,Media\n')


def csv_row(act_id, filename, start=START, name='Tour', sport='Ride', elapsed=600, km=2.0, moving=None, climb=60, media=''):
    when = start.strftime('%b %-d, %Y, %-I:%M:%S %p')
    return f'{act_id},"{when}",{name},{sport},{elapsed},{km},{filename},{moving or elapsed},{km * 1000},{climb},{media}\n'


def export(rows, files):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as z:
        z.writestr('activities.csv', CSV_HEAD + ''.join(rows))
        for name, data in files.items():
            z.writestr(name, data)
    buf.seek(0)
    return zipfile.ZipFile(buf)


class _NoThread:
    def __init__(self, *a, **kw): pass
    def start(self): pass


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setattr(config.Config, 'DATABASE', str(tmp_path / 't.db'))
    monkeypatch.setattr(app_module.threading, 'Thread', _NoThread)
    monkeypatch.setattr('services.weather.fetch_weather', lambda *a, **kw: None)
    a = app_module.create_app()
    with a.app_context():
        db = database.get_db()
        db.execute("INSERT OR IGNORE INTO Settings (id) VALUES (1)")
        db.execute("INSERT INTO Rider (id, name, isDefault) VALUES (1, 'Tom', 1)")
        db.commit()
    return a


@pytest.fixture
def client(app):
    with app.app_context():
        av = credentials.auth_version()
    c = app.test_client()
    with c.session_transaction() as s:
        s['logged_in'] = True
        s['av'] = av
    return c


def run(z):
    events = [json.loads(e[len('data: '):]) for e in import_rides._process_strava_export(z, z.namelist(), 1)]
    database.get_db().commit()
    return events[-1]


def _streams(act_id):
    row = database.get_db().execute('SELECT streams FROM Activity WHERE id=?', [act_id]).fetchone()
    return json.loads(row['streams'] or '{}') if row else None


def test_an_export_with_each_kind_saves_tracks_not_csv_only_rows(app):
    day = lambda d: START + timedelta(days=d)
    rows = [csv_row('1', 'activities/1.bin.gz', day(0)), csv_row('2', 'activities/2.fit', day(1)),
            csv_row('3', 'activities/3.json', day(2), sport='Run', climb=12), csv_row('4', 'activities/4.gpx.gz', day(3))]
    import gzip
    files = {'activities/1.bin.gz': gzip.compress(fit_file(track(), day(0), session=False, crc=False)),
             'activities/2.fit': ruby_escaped(fit_file(track(), day(1))),
             'activities/3.json': strava_app_json(),
             'activities/4.gpx.gz': gzip.compress(uuid_gpx(start=day(3)))}
    files['activities/3.json'] = files['activities/3.json'].replace(START.isoformat().encode(), day(2).isoformat().encode())
    with app.app_context():
        done = run(export(rows, files))
        assert done['imported'] == 4 and done['unread'] == [] and done['parked'] == []
        for i in '1234':
            assert len(_streams(i)['latlng']['data']) == 61, i
        assert database.get_db().execute("SELECT totalElevationGain FROM Activity WHERE id='3'").fetchone()[0] == 12     # Strava's, for the phone's
        assert reimport.problems(database.get_db()) == []


def test_a_file_still_unreadable_is_listed_and_kept_on_the_import_page(app, client):
    rows = [csv_row('9', 'activities/9.fit'), csv_row('8', 'activities/8.gpx', START + timedelta(days=1))]
    files = {'activities/9.fit': b'\x0e\x10' + b'\xff' * 400, 'activities/8.gpx': uuid_gpx(start=START + timedelta(days=1))}
    with app.app_context():
        done = run(export(rows, files))
        assert done['imported'] == 2 and done['unread'] == [{'id': '9', 'name': 'Tour', 'file': 'activities/9.fit'}]
        assert done['noun'] == 'rides'
    page = client.get('/import').get_data(as_text=True)
    assert "1 file couldn't be read" in page and 'activities/9.fit' in page and '/rides/9' in page
    files['activities/9.fit'] = fit_file(track())                    # a later Headwind reads it, or a better export: off the list
    with app.app_context():
        run(export(rows, files))
        assert reimport.problems(database.get_db()) == []
    assert "couldn't be read" not in client.get('/import').get_data(as_text=True)
    with app.app_context():
        run(export(rows, {**files, 'activities/9.fit': b'junk'}))
    assert client.post('/import/problems/clear').status_code == 302
    assert "couldn't be read" not in client.get('/import').get_data(as_text=True)


def test_a_copy_set_aside_is_counted_apart_and_linked(app):
    rows = [csv_row('1', 'activities/1.gpx'), csv_row('2', 'activities/2.gpx', name='Tour (watch)')]
    files = {'activities/1.gpx': uuid_gpx(), 'activities/2.gpx': uuid_gpx()}
    with app.app_context():
        done = run(export(rows, files))
    assert done['imported'] == 1 and len(done['parked']) == 1
    p = done['parked'][0]
    assert {p['id'], p['kept']} == {'1', '2'}


def test_a_piece_saved_first_and_then_set_aside_is_not_counted_twice(app):
    whole = track(n=361)                                           # an hour; the piece is its first ten minutes, without GPS
    piece = [(s, None, None, a, d) for s, _, _, a, d in whole[:61]]
    rows = [csv_row('1', 'activities/1.fit', elapsed=600, km=2.0, name='Piece'), csv_row('2', 'activities/2.fit', elapsed=3600, km=12.0)]
    files = {'activities/1.fit': fit_file(piece), 'activities/2.fit': fit_file(whole)}
    with app.app_context():
        db = database.get_db()
        done = run(export(rows, files))
        assert done['imported'] == 1 and [p['id'] for p in done['parked']] == ['1']
        assert db.execute("SELECT status FROM ActivityDuplicate WHERE id='1'").fetchone()[0] == 'parked'


def test_activities_not_rides_are_worded_as_activities(app):
    rows = [csv_row('1', 'activities/1.gpx'), csv_row('2', 'activities/2.json', START + timedelta(days=1), sport='Run')]
    files = {'activities/1.gpx': uuid_gpx(), 'activities/2.json': strava_app_json().replace(START.isoformat().encode(), (START + timedelta(days=1)).isoformat().encode())}
    with app.app_context():
        assert run(export(rows, files))['noun'] == 'activities'


def test_photos_strava_left_out_of_the_zip_are_counted(app):
    rows = [csv_row('1', 'activities/1.gpx', media='media/a.jpg|media/b.jpg')]
    with app.app_context():
        done = run(export(rows, {'activities/1.gpx': uuid_gpx()}))
    assert done['photos_missing'] == 2


def test_one_file_two_activities_each_get_their_own_window(app):
    """A kayak and the bike shuttle back, both pointing at the one recording: each is cut to its own part, and neither is a copy of the other."""
    pts = track(n=361)
    rows = [csv_row('k', 'activities/1.gpx', START, name='Kayak', sport='Water Sport', elapsed=1800, km=6.0),
            csv_row('r', 'activities/1.gpx', START + timedelta(seconds=2400), name='Shuttle', elapsed=1200, km=4.0)]
    with app.app_context():
        done = run(export(rows, {'activities/1.gpx': uuid_gpx(pts)}))
        assert done['imported'] == 2 and done['parked'] == []
        k, r = _streams('k')['time']['data'], _streams('r')['time']['data']
        assert k[-1] == pytest.approx(1800, abs=10) and r[-1] == pytest.approx(1200, abs=10)


# ---------- manual entries in a Strava export ----------

def test_a_row_with_no_file_is_a_manual_entry_and_never_swallows_a_ride(app):
    """A 2.5 km top-up typed in on Strava, "lasting" 15 hours, used to park the 24 km ride recorded that evening behind itself."""
    ride = track(n=361)
    rows = [csv_row('2241486599', '', START - timedelta(hours=1), name='Evening Ride', elapsed=54000, km=2.5),
            csv_row('100', 'activities/100.gpx', START, name='Real ride', elapsed=3600, km=12.0)]
    with app.app_context():
        db = database.get_db()
        done = run(export(rows, {'activities/100.gpx': uuid_gpx(ride)}))
        assert done['imported'] == 2 and done['parked'] == []
        assert db.execute("SELECT source FROM Activity WHERE id='2241486599'").fetchone()[0] == 'manual'
        assert db.execute("SELECT source FROM Activity WHERE id='100'").fetchone()[0] is None


def test_a_manual_entry_parked_before_is_brought_back_when_the_export_is_imported_again(app):
    from services import duplicates
    ride = track(n=361)
    rows = [csv_row('2241486599', '', START - timedelta(hours=1), name='Evening Ride', elapsed=54000, km=2.5),
            csv_row('100', 'activities/100.gpx', START, name='Real ride', elapsed=3600, km=12.0)]
    z = export(rows, {'activities/100.gpx': uuid_gpx(ride)})
    with app.app_context():
        db = database.get_db()
        run(z)
        db.execute("UPDATE Activity SET source=NULL WHERE id='2241486599'")        # as an import before this one saved it
        duplicates.park(db, '2241486599', '100', 'Kept the whole ride')            # and set it aside behind the ride, as it used to
        db.commit()
        reimport_version = reimport._reader_version
        reimport._reader_version = 'next'
        try:
            run(export(rows, {'activities/100.gpx': uuid_gpx(ride)}))
        finally:
            reimport._reader_version = reimport_version
        assert db.execute("SELECT source FROM Activity WHERE id='2241486599'").fetchone()[0] == 'manual'
        assert db.execute("SELECT status FROM ActivityDuplicate WHERE id='2241486599'").fetchone()[0] == 'kept_both'


# ---------- the climb ----------

def _broken(i):
    return -500 if i % 2 else 12600                                # a barometer swinging between the two, every 10 s


def test_an_impossible_climb_takes_stravas_and_drops_the_altitude(app, client):
    rows = [csv_row('5', 'activities/5.gpx', km=2.0, climb=195)]
    with app.app_context():
        run(export(rows, {'activities/5.gpx': uuid_gpx(ele=_broken)}))
        r = database.get_db().execute("SELECT totalElevationGain, rawData, flagReason FROM Activity WHERE id='5'").fetchone()
        assert r['totalElevationGain'] == 195 and r['flagReason'] is None
        raw = json.loads(r['rawData'])
        assert raw['stravaClimb'] == 195 and raw['fileClimb'] > 9000 and raw['altitudeDropped']
        assert 'altitude' not in _streams('5')
    page = client.get('/rides/5').get_data(as_text=True)
    assert "Strava's figure: the file said" in page


def test_a_real_big_day_keeps_the_files_climb(app):
    """7,000 m over 100 km, 14 m every 10 s: hard, real, and the file's figure stays."""
    pts = [(i * 10, 45.0 + i * 0.0009, 6.6, 0, i * 100.0) for i in range(1000)]
    ele = lambda i: 1000 + 14 * (i % 250 if (i // 250) % 2 == 0 else 250 - i % 250)
    rows = [csv_row('6', 'activities/6.gpx', elapsed=9990, km=100.0, climb=6900)]
    with app.app_context():
        run(export(rows, {'activities/6.gpx': uuid_gpx(pts, ele=ele)}))
        r = database.get_db().execute("SELECT totalElevationGain, rawData FROM Activity WHERE id='6'").fetchone()
        assert r['totalElevationGain'] > 6500 and r['totalElevationGain'] != 6900
        assert 'fileClimb' not in json.loads(r['rawData']) and 'altitude' in _streams('6')


def test_use_stravas_climb_on_a_flagged_ride(app, client):
    with app.app_context():
        db = database.get_db()
        streams = json.dumps({'time': {'data': list(range(0, 600, 10))}, 'altitude': {'data': [_broken(i) for i in range(60)]}})
        db.execute("""INSERT INTO Activity (id, riderId, name, sportType, startDateLocal, distance, movingTime, elapsedTime, totalElevationGain, streams, rawData)
                      VALUES ('w', 1, 'Wahoo', 'Ride', '2021-07-16T09:00:00', 57000, 9000, 9000, 41539, ?, ?)""", [streams, json.dumps({'stravaClimb': 2714})])
        from services import sanity
        sanity.flag(db, 'w')
        db.commit()
        assert sanity.flagged(db, 1)[0]['stravaClimb'] == 2714
    assert "Use Strava's climb (8,904 ft)" in client.get('/dashboard').get_data(as_text=True)
    assert client.post('/rides/w/climb/strava').get_json() == {'ok': True, 'flagged': False}
    with app.app_context():
        r = database.get_db().execute("SELECT totalElevationGain, streams, rawData FROM Activity WHERE id='w'").fetchone()
        assert r['totalElevationGain'] == 2714 and 'altitude' not in json.loads(r['streams']) and json.loads(r['rawData'])['fileClimb'] == 41539
    assert client.post('/rides/nope/climb/strava').status_code == 404
