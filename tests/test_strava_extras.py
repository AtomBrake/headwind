"""What a Strava export holds besides the rides themselves: the commute tick, the photos on each activity and the segments the athlete made
(segments.csv). Imported with the rides, or added to rides already here by importing the export again. Throwaway DB."""
import io
import json
import os
import zipfile

import pytest
from flask import Flask
from PIL import Image

import database
from routes import import_rides
from services import duplicates, photos, segments

# 60 points heading north, 10 s and ~33 m apart (12 km/h): fast enough for a ride segment to match
GPX = ('<?xml version="1.0"?><gpx version="1.1" creator="t" xmlns="http://www.topografix.com/GPX/1/1"><trk><name>Tour</name><trkseg>'
       + ''.join(f'<trkpt lat="{50.4 + i * 0.0003:.5f}" lon="-4.7"><ele>{50 + i}</ele><time>2026-07-04T09:{i * 10 // 60:02d}:{i * 10 % 60:02d}Z</time></trkpt>'
                 for i in range(60))
       + '</trkseg></trk></gpx>')
CSV_HEAD = 'Activity ID,Activity Date,Activity Name,Activity Type,Elapsed Time,Distance,Commute,Filename,Moving Time,Distance,Commute,Media\n'
SEG_HEAD = 'Segment Name,Activity ID,Starting Latitude,Starting Longitude,Ending Latitude,Ending Longitude\n'


def jpeg(w=400, h=200, orientation=None):
    img = Image.new('RGB', (w, h), (200, 30, 30))
    exif = img.getexif()
    exif[0x010F] = 'PhoneMaker'                        # Make: anything in the EXIF must be gone afterwards
    if orientation:
        exif[0x0112] = orientation
    buf = io.BytesIO()
    img.save(buf, 'JPEG', exif=exif)
    return buf.getvalue()


@pytest.fixture
def db(tmp_path):
    app = Flask(__name__)
    app.config['DATABASE'] = str(tmp_path / 't.db')
    with app.app_context():
        database.migrate_db()
        d = database.get_db()
        d.execute("INSERT OR IGNORE INTO Settings (id) VALUES (1)")
        d.execute("INSERT INTO Rider (id, name, isDefault) VALUES (1, 'Tom', 1)")
        d.commit()
        yield d


def row(act_id='101', commute='false', media='', filename='activities/1.gpx', day=4):
    return f'{act_id},"Jul {day}, 2026, 9:00:00 AM",Tour,Ride,590,1.77,{commute},{filename},590,1770.0,{"1.0" if commute == "true" else "0.0"},{media}\n'


def strava_zip(rows, files=(), segs=None, media_csv=None):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as z:
        z.writestr('activities.csv', CSV_HEAD + ''.join(rows))
        z.writestr('activities/1.gpx', GPX)
        for name, data in files:
            z.writestr(name, data)
        if segs is not None:
            z.writestr('segments.csv', SEG_HEAD + ''.join(segs))
        if media_csv is not None:
            z.writestr('media.csv', 'Media Filename,Media Caption\n' + ''.join(media_csv))
    buf.seek(0)
    return zipfile.ZipFile(buf)


def run_import(db, z, **opts):
    events = [json.loads(e[len('data: '):]) for e in import_rides._process_strava_export(z, z.namelist(), 1, **opts)]
    db.commit()
    return events[-1]


def photo_files(db):
    return sorted(os.listdir(photos.photo_dir(database.current_app.config['DATABASE'])))


# ---------- commute ----------

def test_a_commute_in_the_export_is_ticked(db):
    done = run_import(db, strava_zip([row(commute='true')]))
    assert done['imported'] == 1 and done['commutes'] == 1
    assert db.execute("SELECT commute FROM Activity WHERE id='101'").fetchone()[0] == 1


def test_not_a_commute_is_left_unset(db):
    run_import(db, strava_zip([row(commute='false')]))
    assert db.execute("SELECT commute FROM Activity WHERE id='101'").fetchone()[0] is None


def test_importing_again_ticks_a_saved_ride_but_never_one_the_rider_unticked(db):
    run_import(db, strava_zip([row('101'), row('102', filename='', day=5)]))      # an export imported before commutes were read
    db.execute("UPDATE Activity SET commute=0 WHERE id='102'")              # the rider said 102 isn't one
    db.commit()
    done = run_import(db, strava_zip([row('101', commute='true'), row('102', commute='true', filename='', day=5)]))
    assert done['commutes'] == 1
    assert dict(db.execute("SELECT id, commute FROM Activity").fetchall()) == {'101': 1, '102': 0}


def test_a_commute_tick_follows_the_ride_that_is_kept(db):
    db.execute("INSERT INTO Activity (id, name, type, sportType, riderId, startDateLocal, distance, movingTime, elapsedTime, streams, commute) "
               "VALUES ('a', 'a', 'Ride', 'Ride', 1, '2026-07-04T10:00:00', 1000, 600, 600, '{}', 1)")
    db.execute("INSERT INTO Activity (id, name, type, sportType, riderId, startDateLocal, distance, movingTime, elapsedTime, streams) "
               "VALUES ('b', 'b', 'Ride', 'Ride', 1, '2026-07-04T10:00:00', 1000, 600, 600, '{}')")
    duplicates.park(db, 'a', 'b', 'test')
    assert db.execute("SELECT commute FROM Activity WHERE id='b'").fetchone()[0] == 1


# ---------- photos ----------

def test_photos_are_imported_without_their_exif_and_videos_are_left_out(db):
    media = 'media/p1.jpg|media/v1.mp4|media/p2.jpg'
    z = strava_zip([row(media=media)], files=[('media/p1.jpg', jpeg()), ('media/p2.jpg', jpeg()), ('media/v1.mp4', b'\0' * 100)],
                   media_csv=['media/p1.jpg,Top of the climb\n'])
    done = run_import(db, z)
    assert done['photos'] == 2
    rows = photos.for_activity(db, '101')
    assert [r['caption'] for r in rows] == ['Top of the climb', None]
    d = photos.photo_dir(database.current_app.config['DATABASE'])
    for r in rows:
        for name in (r['filename'], photos.thumb_name(r['filename'])):
            with Image.open(os.path.join(d, name)) as img:
                assert not img.getexif()                 # no location, no phone make
    assert len(photo_files(db)) == 4                     # each with its thumbnail


def test_a_sideways_phone_photo_is_turned_upright(db):
    z = strava_zip([row(media='media/p.jpg')], files=[('media/p.jpg', jpeg(400, 200, orientation=6))])
    run_import(db, z)
    name = photos.for_activity(db, '101')[0]['filename']
    with Image.open(os.path.join(photos.photo_dir(database.current_app.config['DATABASE']), name)) as img:
        assert img.size == (200, 400)


def test_importing_again_adds_no_photo_twice_and_adds_new_ones_to_the_saved_ride(db):
    run_import(db, strava_zip([row(media='media/p1.jpg')], files=[('media/p1.jpg', jpeg())]))
    done = run_import(db, strava_zip([row(media='media/p1.jpg|media/p2.jpg')], files=[('media/p1.jpg', jpeg()), ('media/p2.jpg', jpeg())]))
    assert done['photos'] == 1 and done['skipped'] == 1
    assert len(photos.for_activity(db, '101')) == 2


def test_photos_can_be_turned_off(db):
    done = run_import(db, strava_zip([row(media='media/p1.jpg')], files=[('media/p1.jpg', jpeg())]), photos=False)
    assert done['photos'] == 0 and not photos.for_activity(db, '101')


def test_a_broken_picture_does_not_stop_the_ride(db):
    done = run_import(db, strava_zip([row(media='media/p1.jpg')], files=[('media/p1.jpg', b'not a jpeg')]))
    assert done['imported'] == 1 and done['photos'] == 0 and done['errors'] == 0


def test_photos_move_to_the_kept_ride_and_go_when_it_is_deleted(db):
    run_import(db, strava_zip([row(media='media/p1.jpg')], files=[('media/p1.jpg', jpeg())]))
    db.execute("INSERT INTO Activity (id, name, type, sportType, riderId, startDateLocal, distance, movingTime, elapsedTime, streams) "
               "VALUES ('garmin_1', 'g', 'Ride', 'Ride', 1, '2026-07-04T10:00:00', 1770, 590, 590, '{}')")
    duplicates.park(db, '101', 'garmin_1', 'test')
    assert len(photos.for_activity(db, 'garmin_1')) == 1
    duplicates.delete_activity(db, 'garmin_1')
    db.commit()
    assert not db.execute('SELECT 1 FROM ActivityPhoto').fetchone() and photo_files(db) == []


def test_only_photo_file_names_are_served():
    assert photos.valid_name('act_0123456789ab.jpg') and photos.valid_name('act_0123456789ab_t.jpg')
    for bad in ('../bike.db', 'act_0123456789ab.png', 'act_xyz.jpg', 'bike_1_abcdef12.jpg', ''):
        assert not photos.valid_name(bad)


# ---------- segments ----------

def lat(i):
    return f'{50.4 + i * 0.0003:.6f}'


def test_a_strava_segment_is_made_from_the_ride_it_was_drawn_on_and_matched(db):
    done = run_import(db, strava_zip([row()], segs=[f'Hill,101,{lat(10)},-4.7,{lat(50)},-4.7\n']), segments=True)
    assert done['segments_created'] == 1
    seg = db.execute('SELECT * FROM Segment').fetchone()
    assert seg['name'] == 'Hill' and seg['sourceActivityId'] == '101' and seg['sport'] == 'ride'
    assert 1300 < seg['distanceM'] < 1360                # 40 gaps of ~33 m
    assert seg['elevationGainM'] == 40
    assert len(json.loads(seg['polyline'])) == 41
    assert db.execute('SELECT activityId FROM SegmentEffort WHERE segmentId=?', [seg['id']]).fetchone()[0] == '101'


def test_segments_are_only_imported_when_asked(db):
    done = run_import(db, strava_zip([row()], segs=[f'Hill,101,{lat(10)},-4.7,{lat(50)},-4.7\n']))
    assert 'segments_created' not in done and not db.execute('SELECT 1 FROM Segment').fetchone()


def test_segment_rows_that_cant_be_made_are_counted_not_failed(db):
    segs = ['Name only\n',                                                  # rows like this are in real exports
            f'Hill,101,{lat(10)},-4.7,{lat(50)},-4.7\n',
            f'Hill again,101,{lat(10)},-4.7,{lat(50)},-4.7\n',               # same ends: already here
            f'Backwards,101,{lat(50)},-4.7,{lat(10)},-4.7\n',                # the ride went the other way
            f'Elsewhere,999,51.5,-0.1,51.51,-0.1\n']                         # nobody here rode it
    done = run_import(db, strava_zip([row()], segs=segs), segments=True)
    assert (done['segments_created'], done['segments_existing'], done['segments_unridden']) == (1, 1, 2)


def test_a_segment_whose_activity_is_missing_takes_its_shape_from_another_ride(db):
    done = run_import(db, strava_zip([row()], segs=[f'Hill,,{lat(5)},-4.7,{lat(20)},-4.7\n', f'Climb,424242,{lat(30)},-4.7,{lat(40)},-4.7\n']),
                      segments=True)
    assert done['segments_created'] == 2
    assert {r[0] for r in db.execute('SELECT sourceActivityId FROM Segment')} == {'101'}


def test_shape_from_a_loop_takes_the_shortest_way_from_start_to_end():
    out = [[50.4 + i * 0.0003, -4.7] for i in range(40)]
    track = out + out[::-1] + out                       # out, back past the start, out again
    shape = segments.shape_from_streams(json.dumps({'latlng': {'data': track}}), [50.4 + 10 * 0.0003, -4.7], [50.4 + 20 * 0.0003, -4.7])
    assert shape and 300 < shape[1] < 360               # 10 gaps, not the whole loop


# ---------- the activity page ----------

class _NoThread:
    def __init__(self, *a, **kw): pass
    def start(self): pass


@pytest.fixture
def client(tmp_path, monkeypatch):
    import app as app_module
    import config
    from services import credentials
    monkeypatch.setattr(config.Config, 'DATABASE', str(tmp_path / 'app.db'))
    monkeypatch.setattr(app_module.threading, 'Thread', _NoThread)
    app = app_module.create_app()
    with app.app_context():
        d = database.get_db()
        d.execute("INSERT OR IGNORE INTO Settings (id) VALUES (1)")
        d.execute("INSERT INTO Rider (id, name, isDefault) VALUES (1, 'Tom', 1)")
        for aid, sport in (('r1', 'Ride'), ('w1', 'Run')):
            d.execute("INSERT INTO Activity (id, name, type, sportType, riderId, startDateLocal, distance, movingTime, elapsedTime, streams) "
                      "VALUES (?, ?, ?, ?, 1, '2026-07-04T10:00:00', 1000, 600, 600, '{}')", [aid, aid, sport, sport])
        name = photos.save(d, 'r1', jpeg(), app.config['DATABASE'], caption='Café stop')
        pid = d.execute('SELECT id FROM ActivityPhoto').fetchone()[0]
        d.commit()
        av = credentials.auth_version()
    c = app.test_client()
    with c.session_transaction() as s:
        s['logged_in'] = True
        s['av'] = av
    c.app_, c.photo, c.pid = app, name, pid
    return c


def commute_of(client, aid):
    with client.app_.app_context():
        return database.get_db().execute('SELECT commute FROM Activity WHERE id=?', [aid]).fetchone()[0]


def test_the_commute_box_on_rides_and_runs(client):
    for aid in ('r1', 'w1'):
        page = client.get(f'/rides/{aid}').get_data(as_text=True)
        assert 'id="commuteBox"' in page and 'id="commuteBox" checked' not in page
        assert client.post(f'/rides/{aid}/commute', data={'commute': '1'}).status_code == 204 and commute_of(client, aid) == 1
        assert 'id="commuteBox" checked' in client.get(f'/rides/{aid}').get_data(as_text=True)
        assert client.post(f'/rides/{aid}/commute', data={'commute': '0'}).status_code == 204 and commute_of(client, aid) == 0
    assert client.post('/rides/nope/commute', data={'commute': '1'}).status_code == 404


def test_the_photos_card_serves_and_removes_a_photo(client):
    page = client.get('/rides/r1').get_data(as_text=True)
    assert 'id="photosCard"' in page and 'Café stop' in page and photos.thumb_name(client.photo) in page
    assert 'No photos yet' in client.get('/rides/w1').get_data(as_text=True)          # a card with only "Add photos"
    r = client.get(f'/rides/photo/{client.photo}')
    assert r.status_code == 200 and r.mimetype == 'image/jpeg'
    assert client.get('/rides/photo/..%2Fapp.db').status_code == 404
    assert client.post(f'/rides/w1/photos/{client.pid}/delete').status_code == 302      # not that activity's photo: nothing happens
    assert client.get(f'/rides/photo/{client.photo}').status_code == 200
    client.post(f'/rides/r1/photos/{client.pid}/delete')
    assert client.get(f'/rides/photo/{client.photo}').status_code == 404
    assert 'No photos yet' in client.get('/rides/r1').get_data(as_text=True)


def test_adding_photos_on_the_activity_page(client):
    assert 'rides/w1/photos"' in client.get('/rides/w1').get_data(as_text=True)    # the "Add photos" form
    r = client.post('/rides/w1/photos', data={'photos': [(io.BytesIO(jpeg(3000, 1000, orientation=6)), 'a.jpg'),
                                                         (io.BytesIO(b'not a picture'), 'notes.txt'),
                                                         (io.BytesIO(b'heic bytes'), 'IMG_0001.HEIC'),
                                                         (io.BytesIO(jpeg()), 'b.jpg')]},
                    content_type='multipart/form-data')
    assert r.status_code == 302 and r.location.endswith('/rides/w1#photosCard')
    with client.session_transaction() as sess:
        flashes = dict(sess['_flashes'])
    assert flashes['success'] == 'Added 2 photos.'
    assert 'notes.txt: that does not look like a picture' in flashes['error'] and 'IMG_0001.HEIC: HEIC' in flashes['error']
    with client.app_.app_context():
        rows = photos.for_activity(database.get_db(), 'w1')
        pos = [r[0] for r in database.get_db().execute("SELECT position FROM ActivityPhoto WHERE activityId='w1' ORDER BY id")]
    assert len(rows) == 2 and pos == [0, 1]
    big = Image.open(io.BytesIO(client.get(f'/rides/photo/{rows[0]["filename"]}').data))
    assert big.size == (photos.FULL // 3, photos.FULL) and 0x010F not in big.getexif()     # upright, shrunk, no EXIF
    client.post('/rides/w1/photos', data={'photos': [(io.BytesIO(jpeg()), 'c.jpg')]}, content_type='multipart/form-data')
    with client.app_.app_context():
        assert database.get_db().execute("SELECT MAX(position) FROM ActivityPhoto WHERE activityId='w1'").fetchone()[0] == 2     # after the others
    assert client.post('/rides/nope/photos', data={'photos': [(io.BytesIO(jpeg()), 'd.jpg')]}, content_type='multipart/form-data').status_code == 404


def test_commute_in_the_phone_api(client):
    H = {'Authorization': 'Bearer ' + client.post('/phones/create', json={'name': 'Pixel', 'server_url': 'https://h.example'}).get_json()['token']}
    phone = client.app_.test_client()
    assert phone.get('/api/v1/rides/ride/r1', headers=H).get_json()['commute'] is False
    r = phone.post('/api/v1/rides/workout/w1/commute', json={'commute': True}, headers=H)
    assert r.status_code == 200 and r.get_json() == {'id': 'w1', 'commute': True} and commute_of(client, 'w1') == 1
    assert phone.get('/api/v1/rides/workout/w1', headers=H).get_json()['commute'] is True
    phone.post('/api/v1/rides/workout/w1/commute', json={'commute': False}, headers=H)
    assert commute_of(client, 'w1') == 0
    assert phone.post('/api/v1/rides/ride/r1/commute', json={'commute': 'yes'}, headers=H).status_code == 400
    assert phone.post('/api/v1/rides/ride/nope/commute', json={'commute': True}, headers=H).status_code == 404
    assert phone.post('/api/v1/rides/ride/r1/commute', json={'commute': True}).status_code == 401


def test_the_import_page_offers_photos_and_segments(client):
    page = client.get('/import').get_data(as_text=True)
    assert 'id="optPhotos" checked' in page and 'id="optSegments"' in page and 'id="optSegments" checked' not in page


def test_a_backup_carries_activity_photos_and_restore_stages_only_real_ones(db, tmp_path):
    import shutil
    import sqlite3
    from services import backup
    path = database.current_app.config['DATABASE']
    db.execute("INSERT INTO Activity (id, name, type, sportType, riderId, startDateLocal, streams) VALUES ('r1', 'r1', 'Ride', 'Ride', 1, '2026-07-04T10:00:00', '{}')")
    name = photos.save(db, 'r1', jpeg(), path)
    db.commit()
    snap = str(tmp_path / 'snap.db')
    sqlite3.connect(path).backup(sqlite3.connect(snap))
    z = str(tmp_path / 'b.zip')
    with zipfile.ZipFile(z, 'w') as zf:
        zf.write(snap, 'headwind.db')
        for n in (name, photos.thumb_name(name)):
            zf.write(os.path.join(photos.photo_dir(path), n), f'rideimg/{n}')
        zf.writestr('rideimg/../../evil.jpg', b'x')
        zf.writestr('rideimg/holiday.jpg', b'x')

    class FS:
        def save(self, dest): shutil.copy(z, dest)
    tmp, staged, assets = backup.stage_upload(FS())
    try:
        assert sorted(os.listdir(assets['rideimg'])) == sorted([name, photos.thumb_name(name)])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_shape_takes_the_pass_through_the_ends_not_a_shorter_one_that_skirts_them():
    # the real TQ3 case: the ride first cuts between the two ends ~25 m off them, then later rides the segment through both ends
    start, end = [50.4, -4.7], [50.4 + 20 * 0.0003, -4.7]
    skirt = [[50.4 + i * 0.0003, -4.7 + 0.00035] for i in range(21)]                   # ~25 m east of the line, straight
    real = [[50.4 + i * 0.0003, -4.7 + (0.002 if 5 <= i <= 15 else 0)] for i in range(21)]  # through both ends, with a dog-leg: longer
    away = [[50.39, -4.69]]
    shape = segments.shape_from_streams(json.dumps({'latlng': {'data': skirt + away + real}}), start, end)
    assert shape and shape[0][0] == start and shape[0][-1] == end and shape[1] > 700
