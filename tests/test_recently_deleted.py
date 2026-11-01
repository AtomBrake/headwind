"""Recently deleted (services/recently_deleted.py): a deleted activity is kept whole for 30 days and can be restored as it was, a sync never brings
it back while it's there or once it has been cut down to its tombstone, and a backup carries it. Throwaway DB."""
import io
import json
import os
import zipfile

import pytest
from flask import Flask, current_app
from PIL import Image

import database
from routes import import_rides
from services import duplicates, gear, garmin, kit, photos, recently_deleted, workouts


def line(secs, speed_mps, lat0=51.5, lng0=-0.12):
    """A straight northbound GPS track at a steady speed, one fix per second."""
    d_lat = speed_mps / 111_320.0
    return json.dumps({'latlng': {'data': [[lat0 + i * d_lat, lng0] for i in range(secs + 1)]}, 'time': {'data': list(range(secs + 1))}})


def jpeg():
    b = io.BytesIO()
    Image.new('RGB', (40, 20), (200, 30, 30)).save(b, 'JPEG')
    return b.getvalue()


@pytest.fixture
def db(tmp_path):
    app = Flask(__name__)
    app.config['DATABASE'] = str(tmp_path / 't.db')
    with app.app_context():
        database.migrate_db()
        d = database.get_db()
        d.execute("INSERT OR IGNORE INTO Settings (id) VALUES (1)")
        d.execute("INSERT INTO Rider (id, name, isDefault) VALUES (1, 'Tom', 1)")
        photos.ensure_schema(d)
        d.commit()
        yield d


def add(db, aid, sport='Ride', speed=6.0, secs=1200, day='2026-10-07', **cols):
    cols = dict(dict(id=aid, name=f'{aid} name'), type=sport, sportType=sport, startDate=f'{day}T09:00:00Z', startDateLocal=f'{day}T10:00:00',
                distance=secs * speed, movingTime=secs, elapsedTime=secs, rawData='{}', riderId=1, streams=line(secs, speed)) | cols
    db.execute(f"INSERT INTO Activity ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})", list(cols.values()))
    duplicates.rebuild_derived(db, aid)                         # segment efforts, best efforts, as an import makes them
    db.commit()


def add_seg(db, family):
    d = 1 / 111_320.0
    db.execute("INSERT INTO Segment (name,startLat,startLng,endLat,endLng,distanceM,sport) VALUES (?,?,?,?,?,900,?)",
               [family, 51.5 + 100 * d, -0.12, 51.5 + 1000 * d, -0.12, family])
    db.commit()


def row(db, aid):
    r = db.execute('SELECT * FROM Activity WHERE id=?', [aid]).fetchone()
    return dict(r) if r else None


def efforts(db, aid):
    """Its segment efforts, best efforts and best times by distance."""
    return (sorted(tuple(r) for r in db.execute('SELECT segmentId, elapsedSecs, isPR FROM SegmentEffort WHERE activityId=?', [aid])),
            sorted(tuple(r)[1:] for r in db.execute('SELECT * FROM BestEffort WHERE activityId=?', [aid])),
            sorted(tuple(r)[1:] for r in db.execute('SELECT * FROM SportEffort WHERE activityId=?', [aid])))


def files(db):
    return sorted(os.listdir(photos.photo_dir(current_app.config['DATABASE'])))


def binned(db):
    return [b['id'] for b in recently_deleted.listing(db)]


def test_a_ride_comes_back_as_it_was(db):
    add_seg(db, 'ride')
    bike = gear.create_bike(db, 1, 'Road bike')
    add(db, 'garmin_1', secs=1800, bikeId=bike, notes='Windy on the tops', commute=1, aiKudos='Strong ride.')     # 10.8 km: a 5-mile best effort
    photos.save(db, 'garmin_1', jpeg(), current_app.config['DATABASE'], caption='Top of the hill')
    db.commit()
    before, eff = row(db, 'garmin_1'), efforts(db, 'garmin_1')
    assert eff[0] and eff[1]
    assert duplicates.delete_activity(db, 'garmin_1')
    db.commit()
    assert row(db, 'garmin_1') is None and efforts(db, 'garmin_1') == ([], [], []) and duplicates.is_deleted(db, 'garmin_1')
    assert len(files(db)) == 2                                  # still on disk, full size and thumbnail
    [b] = recently_deleted.listing(db)
    assert (b['id'], b['name'], b['sportType'], round(b['distance']), b['startDateLocal']) == ('garmin_1', 'garmin_1 name', 'Ride', 10800, '2026-10-07T10:00:00')

    assert recently_deleted.restore(db, 'garmin_1') == 'garmin_1'
    assert row(db, 'garmin_1') == before                        # every column: notes, bike, commute, the AI's analysis
    assert efforts(db, 'garmin_1') == eff
    assert [p['caption'] for p in photos.for_activity(db, 'garmin_1')] == ['Top of the hill'] and len(files(db)) == 2
    assert db.execute("SELECT aiSummary FROM RideMemory WHERE rideId='garmin_1'").fetchone()[0] == 'Strong ride.'
    assert binned(db) == [] and not duplicates.is_deleted(db, 'garmin_1')
    assert not db.execute("SELECT 1 FROM ActivityDuplicate WHERE id='garmin_1'").fetchone()


def test_a_run_comes_back_with_its_shoes_and_foot_segment(db):
    add_seg(db, 'foot')
    shoes = kit.create(db, 1, 'Trail shoes')
    add(db, 'wk_run', sport='Run', speed=3.0, kitId=shoes, notes='Easy')
    eff = efforts(db, 'wk_run')
    before = row(db, 'wk_run')
    assert eff[0] and eff[2]
    assert workouts.delete(db, 'wk_run', 1)
    db.commit()
    assert binned(db) == ['wk_run'] and efforts(db, 'wk_run') == ([], [], [])
    assert recently_deleted.restore(db, 'wk_run') == 'wk_run'
    assert row(db, 'wk_run') == before and efforts(db, 'wk_run') == eff


def test_gear_deleted_meanwhile_is_replaced_by_the_default(db):
    old, new = gear.create_bike(db, 1, 'Old'), gear.create_bike(db, 1, 'New')
    gear.set_default(db, 1, new)
    add(db, 'r1', bikeId=old)
    duplicates.delete_activity(db, 'r1')
    gear.delete_bike(db, old)
    db.commit()
    recently_deleted.restore(db, 'r1')
    assert row(db, 'r1')['bikeId'] == new


def test_copies_set_aside_behind_it_go_and_come_back_with_it(db):
    add(db, 'garmin_1')
    add(db, '111', name='Phone copy')
    duplicates.park(db, '111', 'garmin_1', 'test')
    db.commit()
    duplicates.delete_activity(db, 'garmin_1')
    db.commit()
    assert tuple(db.execute("SELECT primaryId, status FROM ActivityDuplicate WHERE id='111'").fetchone()) == ('garmin_1', 'parked')
    recently_deleted.restore(db, 'garmin_1')
    assert [d['id'] for d in duplicates.parked_for(db, 'garmin_1')] == ['111']


def test_one_kept_apart_from_another_recording_is_still_kept_apart(db):
    add(db, 'garmin_1')
    add(db, 'garmin_2')                                         # the same session, kept as its own on purpose
    db.execute("INSERT INTO ActivityDuplicate (id, primaryId, riderId, status, rowJson) VALUES ('garmin_2', 'garmin_1', 1, 'kept_both', '{}')")
    db.commit()
    duplicates.delete_activity(db, 'garmin_2')
    db.commit()
    assert recently_deleted.restore(db, 'garmin_2') == 'garmin_2'
    assert row(db, 'garmin_1') and row(db, 'garmin_2')
    assert tuple(db.execute("SELECT primaryId, status FROM ActivityDuplicate WHERE id='garmin_2'").fetchone()) == ('garmin_1', 'kept_both')


def test_another_recording_that_arrived_meanwhile_is_settled_on_restore(db):
    add(db, '111', name='Phone copy')
    duplicates.delete_activity(db, '111')
    add(db, 'garmin_1')                                         # Garmin's recording of it, synced while it was in the bin
    db.commit()
    assert recently_deleted.restore(db, '111') == 'garmin_1'      # the better recording kept, the restored one set aside behind it
    assert row(db, '111') is None and [d['id'] for d in duplicates.parked_for(db, 'garmin_1')] == ['111']


def test_after_thirty_days_only_the_tombstone_is_left(db):
    add(db, 'garmin_1')
    add(db, 'garmin_2', day='2026-10-08')
    photos.save(db, 'garmin_1', jpeg(), current_app.config['DATABASE'])
    photos.save(db, 'garmin_2', jpeg(), current_app.config['DATABASE'])
    duplicates.delete_activity(db, 'garmin_1')
    duplicates.delete_activity(db, 'garmin_2')
    db.execute("UPDATE ActivityDuplicate SET parkedAt=datetime('now', '-31 days') WHERE id='garmin_1'")
    db.commit()
    assert recently_deleted.purge(db, current_app.config['DATABASE']) == 1
    assert binned(db) == ['garmin_2'] and len(files(db)) == 2   # the other one's photo files went
    assert tuple(db.execute("SELECT status, rowJson FROM ActivityDuplicate WHERE id='garmin_1'").fetchone()) == ('deleted', '{}')
    assert duplicates.is_deleted(db, 'garmin_1') and recently_deleted.restore(db, 'garmin_1') is None
    assert recently_deleted.purge(db, current_app.config['DATABASE']) == 0


def test_delete_now_leaves_the_tombstone_and_takes_the_photos(db):
    add(db, 'garmin_1')
    photos.save(db, 'garmin_1', jpeg(), current_app.config['DATABASE'])
    duplicates.delete_activity(db, 'garmin_1')
    assert recently_deleted.empty(db, ['garmin_1'], current_app.config['DATABASE']) == 1
    assert binned(db) == [] and files(db) == [] and duplicates.is_deleted(db, 'garmin_1')


# ---------- syncs ----------
class FakeGarmin:
    class ActivityDownloadFormat:
        ORIGINAL = 'orig'

    def __init__(self, acts):
        self.acts = acts

    def get_activities(self, start=0, limit=100):
        return self.acts[start:start + limit]

    def download_activity(self, aid, dl_fmt=None):
        b = io.BytesIO()
        with zipfile.ZipFile(b, 'w') as z:
            z.writestr('x_ACTIVITY.fit', b'fit')
        return b.getvalue()


def test_a_garmin_sync_skips_a_binned_id_and_a_purged_one(db, monkeypatch):
    monkeypatch.setattr('services.parser.parse_fit', lambda b: {'distance': 10000, 'movingTime': 1800, 'elapsedTime': 1800, 'streams': None})
    monkeypatch.setattr('services.weather.fetch_weather', lambda *a, **k: None)
    acts = [{'activityId': i, 'activityType': {'typeKey': 'cycling'}, 'startTimeLocal': f'2026-10-0{i} 08:00:00',
             'startTimeGMT': f'2026-10-0{i} 07:00:00', 'distance': 10000, 'activityName': f'ride {i}'} for i in (2, 1)]
    monkeypatch.setattr(garmin, '_client', lambda: FakeGarmin(acts))
    list(garmin.sync_garmin_activities(1))
    assert sorted(r[0] for r in db.execute('SELECT id FROM Activity')) == ['garmin_1', 'garmin_2']
    duplicates.delete_activity(db, 'garmin_1')
    duplicates.delete_activity(db, 'garmin_2')
    recently_deleted.empty(db, ['garmin_2'], current_app.config['DATABASE'])
    db.execute("UPDATE Settings SET garminActivitySyncDate=NULL")
    db.commit()
    list(garmin.sync_garmin_activities(1))
    assert db.execute('SELECT COUNT(*) FROM Activity').fetchone()[0] == 0
    assert binned(db) == ['garmin_1']


def strava_zip(ids):
    b = io.BytesIO()
    with zipfile.ZipFile(b, 'w') as z:
        rows = '\n'.join(f'{i},"Oct {i}, 2026, 9:00:00 AM",Ride {i},Ride,,,,,' for i in ids)
        z.writestr('activities.csv', 'Activity ID,Activity Date,Activity Name,Activity Type,Activity Description,Elapsed Time,Distance,Filename,Media\n' + rows)
    return zipfile.ZipFile(io.BytesIO(b.getvalue()))


def test_a_strava_export_imported_again_skips_a_binned_id_and_a_purged_one(db):
    def run():
        zf = strava_zip(['101', '102'])
        return [json.loads(e[6:]) for e in import_rides._process_strava_export(zf, zf.namelist(), rider_id=1) if e.startswith('data: ')][-1]
    run()
    assert sorted(r[0] for r in db.execute('SELECT id FROM Activity')) == ['101', '102']
    duplicates.delete_activity(db, '101')
    duplicates.delete_activity(db, '102')
    recently_deleted.empty(db, ['102'], current_app.config['DATABASE'])
    db.commit()
    assert run()['imported'] == 0
    assert db.execute('SELECT COUNT(*) FROM Activity').fetchone()[0] == 0 and binned(db) == ['101']


# ---------- the Import page and a backup ----------
@pytest.fixture
def app_client(tmp_path, monkeypatch):
    import app as app_module
    import config
    from services import credentials

    class _NoThread:
        def __init__(self, *a, **kw): pass
        def start(self): pass

    monkeypatch.setattr(config.Config, 'DATABASE', str(tmp_path / 'live' / 't.db'))
    os.makedirs(tmp_path / 'live')
    monkeypatch.setattr(app_module.threading, 'Thread', _NoThread)
    for k in ('APP_USERNAME', 'APP_PASSWORD'):
        monkeypatch.delenv(k, raising=False)
    env = tmp_path / 'env'
    env.write_text('SECRET_KEY=x\n')
    monkeypatch.setenv('HEADWIND_ENV', str(env))
    a = app_module.create_app()
    c = a.test_client()
    with a.app_context():
        av = credentials.auth_version()
        d = database.get_db()
        d.execute("INSERT INTO Rider (id, name, isDefault) VALUES (1, 'Tom', 1)")
        d.commit()
    with c.session_transaction() as s:
        s['logged_in'], s['av'] = True, av
    return a, c


def test_the_import_page_lists_it_and_restores_it(app_client):
    a, c = app_client
    with a.app_context():
        add(database.get_db(), 'garmin_1')
    assert c.post('/rides/garmin_1/delete').status_code == 302
    page = c.get('/import').get_data(as_text=True)
    assert 'Recently deleted (1)' in page and 'garmin_1 name' in page
    assert c.post('/import/deleted/garmin_1/restore').status_code == 302
    with a.app_context():
        assert row(database.get_db(), 'garmin_1')
    assert 'Recently deleted' not in c.get('/import').get_data(as_text=True)


def test_a_backup_carries_the_bin_photos_and_all(app_client, tmp_path):
    a, c = app_client
    with a.app_context():
        db = database.get_db()
        add(db, 'garmin_1', notes='Kept')
        photos.save(db, 'garmin_1', jpeg(), a.config['DATABASE'])
        duplicates.delete_activity(db, 'garmin_1')
        db.commit()
    backup = c.get('/settings/backup/export').get_data()
    with a.app_context():                                       # gone from this server: restored from the backup alone
        recently_deleted.empty(database.get_db(), ['garmin_1'], a.config['DATABASE'])
        database.get_db().commit()
        assert files(database.get_db()) == []
    assert c.post('/settings/backup/import', data={'backup': (io.BytesIO(backup), 'headwind-backup.zip')}).status_code == 302
    with a.app_context():
        db = database.get_db()
        assert binned(db) == ['garmin_1'] and len(files(db)) == 2
        recently_deleted.restore(db, 'garmin_1')
        assert row(db, 'garmin_1')['notes'] == 'Kept' and len(photos.for_activity(db, 'garmin_1')) == 1
