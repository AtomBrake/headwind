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

    def __init__(self, acts, fail=False, count=None):
        self.acts, self.fail, self.calls, self.count = acts, fail, [], count

    def get_activities_by_date(self, start, end=None):
        self.calls.append((start, end))
        if self.fail:
            raise RuntimeError('Garmin is down')
        hit = [a for a in self.acts if start <= a['startTimeLocal'][:10] <= (end or '9999')]
        return sorted(hit, key=lambda a: a['startTimeLocal'], reverse=True)

    def count_activities(self):
        return len(self.acts) if self.count is None else self.count

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


def test_full_resync_judges_the_oldest_and_many_deleted_at_once(db):
    """Settings' Full re-sync: Garmin's count says the listing is all of it, so the oldest activities are judged and most of them gone is
    someone tidying Garmin, not a broken list."""
    acts = [act(i, f'2016-03-{i:02d}') for i in range(1, 13)] + [act(20, '2026-09-01'), act(21, '2026-09-10')]
    imported(db, *acts)
    res = gc.full(db, FakeAPI(acts[-2:]), 1)                    # the 12 old ones deleted in Garmin
    assert res['whole'] and not res['suspect'] and res['deleted'] == 12
    assert set(flags(db)) == {f'garmin_{i}' for i in range(1, 13)}
    assert db.execute("SELECT COUNT(*) FROM Activity").fetchone()[0] == 14              # flagged, not deleted
    assert gc.describe(res).startswith('Checked all 2 activities in Garmin. Flagged for review: 12 deleted in Garmin')


def test_full_resync_without_a_matching_count_keeps_the_usual_guards(db):
    acts = [act(i, f'2016-03-{i:02d}') for i in range(1, 13)] + [act(20, '2026-09-01'), act(21, '2026-09-10')]
    imported(db, *acts)
    res = gc.full(db, FakeAPI(acts[-2:], count=50), 1)         # Garmin counts more than it listed: maybe cut short
    assert not res['whole'] and gc.pending(db) == []
    assert "didn't match its list" in gc.describe(res)


def test_full_resync_with_none_of_them_listed_flags_nothing(db):
    imported(db, act(1, '2026-09-01'), act(2, '2026-09-05'))
    res = gc.full(db, FakeAPI([act(7, '2026-09-02')]), 1)       # another Garmin account
    assert res['whole'] and res['suspect'] and gc.pending(db) == []
    assert 'another account' in gc.describe(res)


def missing_ids(db):
    return [m['garminId'] for m in gc.not_here(db)]


def deleted_ids(db):
    return [m['garminId'] for m in gc.not_here(db, deleted=True)]


def test_full_resync_brings_in_skipped_gym_activities_and_lists_the_rest(db):
    """An older sync left out strength and yoga (garmin.ONCE_SKIPPED): never here, so never deleted, and brought in. A ride missing below the
    cursor may be one deleted before Headwind remembered deletions: listed, not brought back. Newer than the cursor is the sync's to fetch."""
    here = [act(1, '2026-09-01'), act(9, '2026-09-20')]
    imported(db, *here)                                          # cursor: 2026-09-20
    left = [act(2, '2026-09-03', key='strength_training'), act(3, '2026-09-04', key='yoga'), act(4, '2026-09-05', name='Gone ride'),
            act(5, '1999-01-01', key='yoga'), act(6, '2026-09-25', key='yoga')]
    res = gc.full(db, FakeAPI(here + left), 1)
    assert res['imported'] == 2 and res['missing'] == 1 and not res['failed']
    ids = {r[0] for r in db.execute('SELECT id FROM Activity')}
    assert ids == {'garmin_1', 'garmin_9', 'garmin_2', 'garmin_3'}
    assert db.execute("SELECT type FROM Activity WHERE id='garmin_2'").fetchone()[0] not in ('Ride', 'VirtualRide', 'EBikeRide')
    assert missing_ids(db) == ['4']
    line = gc.describe(res)
    assert 'Brought in 2 strength, yoga or other gym activities' in line and "1 other activity in Garmin isn't here" in line
    res = gc.full(db, FakeAPI(here + left), 1)                   # again: nothing new, the same one listed
    assert res['imported'] == 0 and missing_ids(db) == ['4']


def test_full_resync_leaves_deleted_parked_and_unsynced_alone(db):
    here = [act(1, '2026-09-01'), act(9, '2026-09-20')]
    imported(db, *here)
    duplicates.tombstone(db, 'garmin_2', 1)                      # deleted by you
    db.commit()
    acts = here + [act(2, '2026-09-03', key='yoga'), act(3, '2026-09-04')]
    assert gc.full(db, FakeAPI(acts), 1)['imported'] == 0
    assert not db.execute("SELECT 1 FROM Activity WHERE id='garmin_2'").fetchone() and missing_ids(db) == ['3']
    assert deleted_ids(db) == ['2']                              # listed apart, to bring back; never brought in by itself
    db.execute('UPDATE Settings SET garminActivitySyncDate=NULL WHERE id=1')     # never synced: the sync fetches the whole history itself
    db.commit()
    assert gc.full(db, FakeAPI(acts), 1)['missing'] == 0 and missing_ids(db) == [] and deleted_ids(db) == ['2']


def test_full_resync_on_another_account_brings_in_nothing(db):
    imported(db, act(1, '2026-09-01'), act(2, '2026-09-20'))
    res = gc.full(db, FakeAPI([act(7, '2026-09-02', key='yoga'), act(8, '2026-09-03')]), 1)
    assert res['suspect'] and res['imported'] == 0 and missing_ids(db) == []


def test_listed_ones_are_brought_in_or_left_out_for_good(db, monkeypatch):
    here = [act(1, '2026-09-01'), act(9, '2026-09-20')]
    imported(db, *here)
    acts = here + [act(3, '2026-09-04'), act(4, '2026-09-05'), act(5, '2026-09-06')]
    gc.full(db, FakeAPI(acts), 1)
    assert missing_ids(db) == ['5', '4', '3']
    assert gc.leave_out(db, ['4']) == 1
    db.commit()
    assert deleted_ids(db) == ['4']                              # straight to the deleted ones: Leave out can be undone
    assert gc.bring_in(db, FakeAPI(acts), ['3']) == (1, 0)
    assert db.execute("SELECT 1 FROM Activity WHERE id='garmin_3'").fetchone() and missing_ids(db) == ['5']
    downloads = FakeAPI.download_activity
    monkeypatch.setattr(FakeAPI, 'download_activity', lambda self, aid, dl_fmt=None: (_ for _ in ()).throw(RuntimeError('boom')))
    assert gc.bring_in(db, FakeAPI(acts), ['5']) == (0, 1)
    assert missing_ids(db) == ['5']                              # still listed, to try again
    gc.full(db, FakeAPI(acts), 1)
    assert missing_ids(db) == []                                 # left out: never offered again; failed: not before its next try
    for _ in garmin.sync_garmin_activities(1, api=FakeAPI(acts)):
        pass
    assert not db.execute("SELECT 1 FROM Activity WHERE id='garmin_4'").fetchone()
    monkeypatch.setattr(FakeAPI, 'download_activity', downloads)  # Garmin downloads again
    assert gc.bring_in(db, FakeAPI(acts), ['4']) == (1, 0)       # changed your mind
    assert db.execute("SELECT 1 FROM Activity WHERE id='garmin_4'").fetchone() and not duplicates.is_deleted(db, 'garmin_4')


def test_one_deleted_here_is_listed_with_garmins_details_and_brought_back(db):
    """Headwind keeps only a deleted activity's id; Garmin's list gives back its name and date, whatever its date, and it can be brought back."""
    acts = [act(1, '2026-09-01', name='Commute'), act(2, '2026-09-10', name='Hill reps'), act(9, '2026-09-20')]
    imported(db, *acts)
    duplicates.delete_activity(db, 'garmin_2')
    duplicates.delete_activity(db, 'garmin_9')                   # on the cursor's own day: the sync won't fetch it either
    db.commit()
    res = gc.full(db, FakeAPI(acts), 1)
    assert res['deleted_here'] == 2 and res['missing'] == 0 and not res['deleted']
    assert [(m['garminId'], m['name'], m['startDateLocal']) for m in gc.not_here(db, deleted=True)] == \
        [('9', 'ride 9', '2026-09-20T09:00:00'), ('2', 'Hill reps', '2026-09-10T09:00:00')]
    assert '2 you deleted here are still in Garmin' in gc.describe(res)
    assert gc.bring_in(db, FakeAPI(acts), ['2']) == (1, 0)
    assert db.execute("SELECT name FROM Activity WHERE id='garmin_2'").fetchone()[0] == 'Hill reps'
    assert deleted_ids(db) == ['9']
    gc.full(db, FakeAPI(acts), 1)
    assert deleted_ids(db) == ['9'] and missing_ids(db) == []


def test_one_deleted_in_garmin_drops_off_the_list(db):
    here = [act(1, '2026-09-01'), act(9, '2026-09-20')]
    imported(db, *here)
    gc.full(db, FakeAPI(here + [act(3, '2026-09-04')]), 1)
    assert missing_ids(db) == ['3']
    gc.full(db, FakeAPI(here), 1)
    assert missing_ids(db) == []


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


def test_settings_full_resync_button_runs_the_whole_check(tmp_path, monkeypatch):
    """Settings shows Full re-sync once Garmin is signed in for rides, and it starts garmin_changes.full in the background. Full app."""
    import app as app_module
    import config
    from routes import garmin as garmin_routes
    from services import credentials
    monkeypatch.setattr(config.Config, 'DATABASE', str(tmp_path / 'p.db'))
    monkeypatch.setattr(app_module.threading, 'Thread', _NoThread)
    monkeypatch.setattr('services.garmin.signed_in', lambda: True)
    app = app_module.create_app()
    with app.app_context():
        d = database.get_db()
        d.execute("INSERT OR IGNORE INTO Settings (id) VALUES (1)")
        d.execute("UPDATE Settings SET garminSyncMode='full', garminEmail='a@b.c' WHERE id=1")
        d.execute("INSERT INTO Rider (id, name, isDefault) VALUES (1, 'Tom', 1)")
        d.commit()
        av = credentials.auth_version()
    started = []
    monkeypatch.setattr(garmin_routes.threading, 'Thread', lambda target, args, daemon: type('T', (), {'start': lambda s: started.append(args)})())
    c = app.test_client()
    with c.session_transaction() as s:
        s['logged_in'] = True
        s['av'] = av
    assert 'Full re-sync' in c.get('/settings/').get_data(as_text=True)
    r = c.post('/garmin/changes/check?whole=1')
    assert r.status_code == 302 and r.headers['Location'].endswith('/import#garmin-changes')
    assert started and started[0][1:] == (1, True)
    garmin_routes._changes_lock.release()


def test_import_page_lists_the_missing_and_its_buttons_work(tmp_path, monkeypatch):
    """In Garmin, not here: listed on the Import page; Leave out settles it there and then, Bring in starts a background fetch. Full app."""
    import app as app_module
    import config
    from routes import garmin as garmin_routes
    from services import credentials
    monkeypatch.setattr(config.Config, 'DATABASE', str(tmp_path / 'p.db'))
    monkeypatch.setattr(app_module.threading, 'Thread', _NoThread)
    monkeypatch.setattr('services.garmin.signed_in', lambda: True)
    app = app_module.create_app()
    with app.app_context():
        d = database.get_db()
        d.execute("INSERT OR IGNORE INTO Settings (id) VALUES (1)")
        d.execute("UPDATE Settings SET garminSyncMode='full', garminEmail='a@b.c', garminActivitySyncDate='2026-09-20' WHERE id=1")
        d.execute("INSERT INTO Rider (id, name, isDefault) VALUES (1, 'Tom', 1)")
        d.execute("INSERT INTO Activity (id, name, type, sportType, riderId, startDateLocal, distance, movingTime) VALUES ('garmin_1', 'r', 'Ride', 'Ride', 1, '2026-09-01T09:00:00', 20000, 3600)")
        d.commit()
        gc.full(d, FakeAPI([act(1, '2026-09-01'), act(3, '2026-09-04', name='Lost ride'), act(4, '2026-09-05', name='Other lost ride')]), 1)
        av = credentials.auth_version()
    started = []
    monkeypatch.setattr(garmin_routes.threading, 'Thread', lambda target, args, daemon: type('T', (), {'start': lambda s: started.append(args)})())
    c = app.test_client()
    with c.session_transaction() as s:
        s['logged_in'] = True
        s['av'] = av
    page = c.get('/import').get_data(as_text=True)
    assert 'In Garmin, not here (2)' in page and 'Lost ride' in page and 'Bring all in' in page
    r = c.post('/garmin/missing/4/leave')
    assert r.status_code == 302 and r.headers['Location'].endswith('/import#garmin-changes')
    with app.app_context():
        assert missing_ids(database.get_db()) == ['3'] and duplicates.is_deleted(database.get_db(), 'garmin_4')
    page = c.get('/import').get_data(as_text=True)
    assert 'Deleted here, still in Garmin (1)' in page and 'Other lost ride' in page
    c.post('/garmin/missing/all/import')
    assert started and started[0][1] == ['3']
    garmin_routes._changes_lock.release()
    c.post('/garmin/missing/all/restore')
    assert started[1][1] == ['4']
    garmin_routes._changes_lock.release()
