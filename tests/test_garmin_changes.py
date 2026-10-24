"""Activities deleted or changed in Garmin Connect after they came in (services/garmin_changes): each is flagged once and nothing changes until it's
reviewed; a failed or short listing flags nothing; the rider's own edits win; a parked Garmin copy is left alone. Throwaway DB, Garmin faked."""
import io
import json
import zipfile

import pytest
from flask import Flask

import database
from services import duplicates, garmin, garmin_changes as gc, reimport


class FakeAPI:
    """get_activities_by_date filters on the local start day and lists newest first, like Garmin's."""
    class ActivityDownloadFormat:
        ORIGINAL = 'orig'

    def __init__(self, acts, fail=False):
        self.acts, self.fail, self.calls = acts, fail, []

    def get_activities_by_date(self, start, end=None):
        self.calls.append((start, end))
        if self.fail:
            raise RuntimeError('Garmin is down')
        hit = [a for a in self.acts if start <= a['startTimeLocal'][:10] <= (end or '9999')]
        return sorted(hit, key=lambda a: a['startTimeLocal'], reverse=True)

    def get_activities(self, start=0, limit=100):
        return sorted(self.acts, key=lambda a: a['startTimeLocal'], reverse=True)[start:start + limit]

    def download_activity(self, aid, dl_fmt=None):
        b = io.BytesIO()
        with zipfile.ZipFile(b, 'w') as z:
            z.writestr(f'{aid}_ACTIVITY.fit', b'fit')
        return b.getvalue()


def act(aid, day, name=None, key='cycling', dist=20000, dur=3600):
    return {'activityId': aid, 'activityName': name or f'ride {aid}', 'activityType': {'typeKey': key}, 'startTimeLocal': f'{day} 09:00:00',
            'startTimeGMT': f'{day} 08:00:00', 'distance': dist, 'elapsedDuration': dur, 'duration': dur}


@pytest.fixture
def db(tmp_path, monkeypatch):
    app = Flask(__name__)
    app.config['DATABASE'] = str(tmp_path / 't.db')
    app.config['TESTING'] = True
    with app.app_context():
        database.migrate_db()
        d = database.get_db()
        d.execute("INSERT INTO Rider(name,isDefault) VALUES ('r',1)")
        d.commit()
        monkeypatch.setattr('services.parser.parse_fit', lambda b: {'distance': 15000, 'movingTime': 2700, 'elapsedTime': 2700, 'streams': None})
        monkeypatch.setattr('services.weather.fetch_weather', lambda *a, **k: None)
        yield d


def imported(db, *acts):
    """Activities brought in by the real sync, so Garmin's summary is kept the way it is in use."""
    api = FakeAPI(list(acts))
    for _ in garmin.sync_garmin_activities(1, api=api):
        pass
    return api


def flags(db):
    return {c['rideId']: (c['kind'], c['diffs']) for c in gc.pending(db)}


def test_sync_keeps_garmin_summary(db):
    imported(db, act(1, '2026-09-01', name='Morning ride'))
    seen = json.loads(db.execute("SELECT summary FROM GarminSeen WHERE garminId='1'").fetchone()[0])
    assert seen == {'name': 'Morning ride', 'typeKey': 'cycling', 'distance': 20000, 'duration': 3600, 'start': '2026-09-01 08:00:00'}


def test_deletion_is_flagged_once_and_nothing_is_deleted(db):
    imported(db, act(1, '2026-09-01'), act(2, '2026-09-05'), act(3, '2026-09-10'))
    api = FakeAPI([act(1, '2026-09-01'), act(3, '2026-09-10')])                    # 2 deleted in Garmin
    res = gc.check(db, api, 1, '2026-08-01', '2026-10-01')
    assert res['deleted'] == 1 and flags(db) == {'garmin_2': ('deleted', [])}
    assert db.execute("SELECT 1 FROM Activity WHERE id='garmin_2'").fetchone()        # still here
    assert gc.check(db, api, 1, '2026-08-01', '2026-10-01')['deleted'] == 0            # not flagged twice
    assert len(gc.pending(db)) == 1


def test_delete_here_too_tombstones_so_a_sync_never_brings_it_back(db):
    imported(db, act(1, '2026-09-01'), act(2, '2026-09-05'))
    gc.check(db, FakeAPI([act(1, '2026-09-01')]), 1, '2026-08-01', '2026-10-01')
    assert flags(db) == {'garmin_2': ('deleted', [])}
    assert gc.resolve(db, 'garmin_2', 'delete') == 'deleted'
    db.commit()
    assert not db.execute("SELECT 1 FROM Activity WHERE id='garmin_2'").fetchone()
    assert duplicates.is_deleted(db, 'garmin_2') and gc.pending(db) == []


def test_kept_deletion_is_not_flagged_again(db):
    imported(db, act(1, '2026-09-01'), act(2, '2026-09-05'))
    api = FakeAPI([act(1, '2026-09-01')])
    gc.check(db, api, 1, '2026-08-01', '2026-10-01')
    gc.resolve(db, 'garmin_2', 'keep')
    db.commit()
    assert gc.check(db, api, 1, '2026-08-01', '2026-10-01')['deleted'] == 0 and gc.pending(db) == []
    assert db.execute("SELECT 1 FROM Activity WHERE id='garmin_2'").fetchone()


def test_back_in_garmin_takes_the_flag_off(db):
    imported(db, act(1, '2026-09-01'), act(2, '2026-09-05'))
    gc.check(db, FakeAPI([act(1, '2026-09-01')]), 1, '2026-08-01', '2026-10-01')
    res = gc.check(db, FakeAPI([act(1, '2026-09-01'), act(2, '2026-09-05')]), 1, '2026-08-01', '2026-10-01')
    assert res['back'] == 1 and gc.pending(db) == []


def test_an_api_error_or_an_empty_listing_flags_nothing(db):
    imported(db, act(1, '2026-09-01'), act(2, '2026-09-05'))
    with pytest.raises(RuntimeError):
        gc.check(db, FakeAPI([], fail=True), 1, '2026-08-01', '2026-10-01')
    assert gc.check(db, FakeAPI([]), 1, '2026-08-01', '2026-10-01')['deleted'] == 0
    assert gc.pending(db) == []


def test_activities_older_than_the_listing_reaches_are_not_judged(db):
    """A listing cut short gives the newest part: what's older than its oldest entry isn't taken as deleted."""
    imported(db, act(1, '2026-08-02'), act(2, '2026-08-20'), act(3, '2026-09-10'))
    gc.check(db, FakeAPI([act(2, '2026-08-20'), act(3, '2026-09-10')]), 1, '2026-08-01', '2026-10-01')
    assert gc.pending(db) == []


def test_most_of_them_missing_at_once_is_not_taken_as_deletions(db):
    acts = [act(i, f'2026-09-{i:02d}') for i in range(1, 15)]
    imported(db, *acts)
    res = gc.check(db, FakeAPI([acts[0], acts[-1]]), 1, '2026-08-01', '2026-10-01')        # 12 of 14 gone: another account, or a broken list
    assert res['suspect'] and gc.pending(db) == []


def test_rename_and_new_sport_are_offered_and_taken(db):
    imported(db, act(1, '2026-09-01', name='Morning ride'))
    api = FakeAPI([act(1, '2026-09-01', name='Lunch run', key='running')])
    res = gc.check(db, api, 1, '2026-08-01', '2026-10-01')
    assert res['edited'] == 1
    assert flags(db) == {'garmin_1': ('edited', [{'field': 'name', 'old': 'Morning ride', 'new': 'Lunch run'},
                                                 {'field': 'sport', 'old': 'Ride', 'new': 'Run'}])}
    assert db.execute("SELECT name, sportType FROM Activity WHERE id='garmin_1'").fetchone()[:] == ('Morning ride', 'Ride')    # untouched until chosen
    assert gc.check(db, api, 1, '2026-08-01', '2026-10-01')['edited'] == 0                  # not flagged twice
    assert gc.resolve(db, 'garmin_1', 'garmin') == 'changed'
    db.commit()
    assert db.execute("SELECT name, sportType FROM Activity WHERE id='garmin_1'").fetchone()[:] == ('Lunch run', 'Run')
    assert gc.check(db, api, 1, '2026-08-01', '2026-10-01')['edited'] == 0 and gc.pending(db) == []


def test_keep_as_here_is_not_flagged_again(db):
    imported(db, act(1, '2026-09-01', name='Morning ride'))
    api = FakeAPI([act(1, '2026-09-01', name='Renamed')])
    gc.check(db, api, 1, '2026-08-01', '2026-10-01')
    assert gc.resolve(db, 'garmin_1', 'keep') is None
    db.commit()
    assert db.execute("SELECT name FROM Activity WHERE id='garmin_1'").fetchone()[0] == 'Morning ride'
    assert gc.check(db, api, 1, '2026-08-01', '2026-10-01')['edited'] == 0 and gc.pending(db) == []


def test_the_riders_own_rename_wins(db):
    imported(db, act(1, '2026-09-01', name='Morning ride'))
    db.execute("UPDATE Activity SET name='Into the hills' WHERE id='garmin_1'")
    db.commit()
    gc.check(db, FakeAPI([act(1, '2026-09-01', name='Renamed in Garmin')]), 1, '2026-08-01', '2026-10-01')
    assert gc.pending(db) == []
    assert db.execute("SELECT name FROM Activity WHERE id='garmin_1'").fetchone()[0] == 'Into the hills'


def test_first_check_of_older_imports_sets_a_baseline_and_flags_nothing(db):
    imported(db, act(1, '2026-09-01', name='Morning ride'))
    db.execute('DELETE FROM GarminSeen')                                                     # imported before Garmin's summary was kept
    db.commit()
    api = FakeAPI([act(1, '2026-09-01', name='Renamed', dist=12000)])
    res = gc.check(db, api, 1, '2026-08-01', '2026-10-01')
    assert res['baseline'] == 1 and res['edited'] == res['recordings'] == 0 and gc.pending(db) == []
    assert reimport.pending(db) == []
    assert gc.check(db, api, 1, '2026-08-01', '2026-10-01')['edited'] == 0                   # Garmin's name now is the baseline


def test_crop_reads_the_file_again_and_offers_it_once(db):
    imported(db, act(1, '2026-09-01'))
    db.execute("UPDATE Activity SET distance=20000, movingTime=3600, elapsedTime=3600 WHERE id='garmin_1'")
    db.commit()
    api = FakeAPI([act(1, '2026-09-01', dist=15000, dur=2700)])                              # cropped in Garmin
    assert gc.check(db, api, 1, '2026-08-01', '2026-10-01')['recordings'] == 1
    [c] = reimport.pending(db)
    assert c['rideId'] == 'garmin_1' and c['source'] == 'Garmin' and {d['label'] for d in c['diffs']} >= {'Distance'}
    assert db.execute("SELECT distance FROM Activity WHERE id='garmin_1'").fetchone()[0] == 20000      # untouched until chosen
    db.execute('DELETE FROM ImportChange')                                                   # "keep saved"
    db.commit()
    assert gc.check(db, api, 1, '2026-08-01', '2026-10-01')['recordings'] == 0 and reimport.pending(db) == []


def test_a_parked_garmin_copy_and_the_one_kept_are_left_alone(db):
    db.execute("INSERT INTO Activity (id,name,type,sportType,startDate,startDateLocal,distance,movingTime,elapsedTime,totalElevationGain,"
               "averageSpeed,maxSpeed,riderId,createdAt,updatedAt) VALUES ('phone_1','Phone','Ride','Ride','2026-09-01T08:00:30','2026-09-01T09:00:30',"
               "15000,2700,2700,0,0,0,1,'n','n')")                                                # the same ride as the file the fake Garmin gives
    db.commit()
    imported(db, act(1, '2026-09-01', dist=15000, dur=2700), act(9, '2026-09-20'))
    assert duplicates.swap(db, 'phone_1') == 'phone_1'                                      # the phone's recording kept, Garmin's set aside
    db.commit()
    assert db.execute("SELECT status FROM ActivityDuplicate WHERE id='garmin_1'").fetchone()[0] == 'parked'
    gc.check(db, FakeAPI([act(9, '2026-09-20')]), 1, '2026-08-01', '2026-10-01')            # garmin_1 deleted in Garmin
    gc.check(db, FakeAPI([act(1, '2026-09-01', name='Renamed', dist=15000, dur=2700), act(9, '2026-09-20')]), 1, '2026-08-01', '2026-10-01')
    assert gc.pending(db) == [] and reimport.pending(db) == []
    assert db.execute("SELECT name FROM Activity WHERE id='phone_1'").fetchone()[0] == 'Phone'


def test_run_walks_further_back_a_block_at_a_time(db):
    from datetime import date
    imported(db, act(1, '2026-01-10'), act(2, '2026-09-01'))
    api = FakeAPI([act(2, '2026-09-01')])
    today = date(2026, 10, 1)
    gc.run(db, api, 1, today)
    before = db.execute('SELECT garminChangesBefore FROM Settings WHERE id=1').fetchone()[0]
    assert api.calls[0] == ('2026-07-03', '2026-10-02') and before == '2026-05-04'
    for _ in range(5):
        gc.run(db, api, 1, today)
    assert db.execute('SELECT garminChangesBefore FROM Settings WHERE id=1').fetchone()[0] is None      # past the oldest: start again
    assert gc.pending(db) == []                                                              # the oldest one is never the only one listed


class _NoThread:
    def __init__(self, *a, **kw): pass
    def start(self): pass


def test_pages_show_the_flags_and_the_buttons_settle_them(tmp_path, monkeypatch):
    """The Import page lists both kinds, the activity's page shows its own, and the buttons there do what they say. Full app."""
    import app as app_module
    import config
    from services import credentials
    monkeypatch.setattr(config.Config, 'DATABASE', str(tmp_path / 'p.db'))
    monkeypatch.setattr(app_module.threading, 'Thread', _NoThread)
    app = app_module.create_app()
    with app.app_context():
        d = database.get_db()
        d.execute("INSERT OR IGNORE INTO Settings (id) VALUES (1)")
        d.execute("UPDATE Settings SET garminSyncMode='full' WHERE id=1")
        d.execute("INSERT INTO Rider (id, name, isDefault) VALUES (1, 'Tom', 1)")
        for aid, name in (('garmin_1', 'Gone ride'), ('garmin_2', 'Old name')):
            d.execute("INSERT INTO Activity (id, name, type, sportType, riderId, startDateLocal, distance, movingTime) VALUES (?, ?, 'Ride', 'Ride', 1, '2026-09-01T09:00:00', 20000, 3600)",
                      [aid, name])
        gc.remember(d, act(2, '2026-09-01', name='Old name'))
        d.commit()
        gc.check(d, FakeAPI([act(2, '2026-09-01', name='New name'), act(3, '2026-08-01')]), 1, '2026-07-01', '2026-10-01')
        assert set(flags(d)) == {'garmin_1', 'garmin_2'}
        av = credentials.auth_version()
    c = app.test_client()
    with c.session_transaction() as s:
        s['logged_in'] = True
        s['av'] = av
    page = c.get('/import').get_data(as_text=True)
    assert 'Deleted in Garmin (1)' in page and 'Gone ride' in page and 'New name' in page and 'Check now' in page
    ride = c.get('/rides/garmin_2').get_data(as_text=True)
    assert 'This activity was changed in Garmin Connect' in ride and 'New name' in ride
    r = c.post('/garmin/changes/garmin_2/garmin', data={'back': 'ride'})
    assert r.status_code == 302 and r.headers['Location'].endswith('/rides/garmin_2')
    assert 'changed in Garmin Connect' not in c.get('/rides/garmin_2').get_data(as_text=True)
    assert 'This activity was deleted in Garmin Connect' in c.get('/rides/garmin_1').get_data(as_text=True)
    c.post('/garmin/changes/deleted/delete')
    with app.app_context():
        d = database.get_db()
        assert d.execute("SELECT name FROM Activity WHERE id='garmin_2'").fetchone()[0] == 'New name'
        assert not d.execute("SELECT 1 FROM Activity WHERE id='garmin_1'").fetchone() and gc.pending(d) == []
