"""Activities deleted or changed in Garmin Connect after they came in (services/garmin_changes): each is flagged once and nothing changes until it's
reviewed; a failed or short listing flags nothing; the rider's own edits win; a parked Garmin copy is left alone. Throwaway DB, Garmin faked."""
import io
import json
import zipfile

import pytest
from flask import Flask

import database
from services import duplicates, garmin, garmin_changes as gc, jobs, reimport
from services import streams as _streams


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
    return {c['activityId']: (c['kind'], c['diffs']) for c in gc.pending(db)}


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


def test_a_sport_changed_in_garmin_to_the_one_here_is_taken_as_garmins_from_then_on(db):
    """Walking in Garmin, a Hike here; then made hiking in Garmin too. Nothing to offer, but the start-up sport check must stop going by walking."""
    from services import sport_fix
    imported(db, act(1, '2026-09-01', name='Teignbridge Walking', key='walking'))
    db.execute("UPDATE Activity SET sportType='Hike', type='Hike' WHERE id='garmin_1'")
    sport_fix.from_seen(db)
    assert [p['newSport'] for p in sport_fix.pending(db, 1)] == ['Walk']
    gc.check(db, FakeAPI([act(1, '2026-09-01', name='Teignbridge Walking', key='hiking')]), 1, '2026-08-01', '2026-10-01')
    assert gc.pending(db) == [] and sport_fix.pending(db, 1) == []
    assert json.loads(db.execute("SELECT summary FROM GarminSeen WHERE garminId='1'").fetchone()[0])['typeKey'] == 'hiking'
    assert sport_fix.from_seen(db) == {}                                    # nor again at the next start


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
    assert c['activityId'] == 'garmin_1' and c['source'] == 'Garmin' and {d['label'] for d in c['diffs']} >= {'Distance'}
    assert db.execute("SELECT distance FROM Activity WHERE id='garmin_1'").fetchone()[0] == 20000      # untouched until chosen
    db.execute('DELETE FROM ImportChange')                                                   # "keep saved"
    db.commit()
    assert gc.check(db, api, 1, '2026-08-01', '2026-10-01')['recordings'] == 0 and reimport.pending(db) == []


def walk_then_drive(b):
    """A watch left running after a walk: 1.6 km on foot in 3,200 s, then 25 km in a car. Garmin's original upload keeps all of it."""
    t = list(range(0, 4900, 10))
    d = [x * 0.5 if x <= 3200 else 1600 + (x - 3200) * 15 for x in t]
    streams = {'time': {'data': t}, 'distance': {'data': d}, 'latlng': {'data': [[50.5 + m / 111_000, -3.5] for m in d]},
               'heartrate': {'data': [100 if x <= 3200 else 70 for x in t]}}
    return {'distance': d[-1], 'movingTime': 4890, 'elapsedTime': 4890, 'startDateLocal': '2026-09-01T08:00:00', 'calories': 900,
            'streams': json.dumps(streams), 'sportType': 'Walk'}


def counted(api):
    api.downloads = 0
    download = api.download_activity

    def count(aid, dl_fmt=None):
        api.downloads += 1
        return download(aid, dl_fmt)
    api.download_activity = count
    return api


def test_a_crop_made_in_garmin_before_the_import_comes_in_cropped(db, monkeypatch):
    monkeypatch.setattr('services.parser.parse_fit', walk_then_drive)
    walk = {**act(1, '2026-09-01', key='walking', dist=1600, dur=3200), 'movingDuration': 3100, 'calories': 250, 'elevationGain': 12}
    imported(db, walk)
    r = db.execute(f"SELECT *, {_streams.sql()} FROM Activity WHERE id='garmin_1'").fetchone()
    assert (r['distance'], r['movingTime'], r['elapsedTime'], r['totalElevationGain'], r['caloriesRaw']) == (1600, 3100, 3200, 12, 250)
    assert json.loads(r['streams'])['time']['data'][-1] == 3200 and r['averageHeartrate'] == 100     # the drive's left out
    api = counted(FakeAPI([walk]))
    assert gc.check(db, api, 1, '2026-08-01', '2026-10-01')['recordings'] == 0 and api.downloads == 0
    assert reimport.pending(db) == []


def test_one_imported_whole_before_is_read_again_once_and_offered(db, monkeypatch):
    monkeypatch.setattr('services.parser.parse_fit', walk_then_drive)
    walk = act(1, '2026-09-01', key='walking', dist=1600, dur=3200)
    imported(db, {**walk, 'distance': 26000, 'elapsedDuration': 4890})          # what an older Headwind saved: the whole file
    db.execute('UPDATE GarminSeen SET summary=?, cropChecked=0', [json.dumps(gc.summary(walk))])   # and Garmin's summary as it kept it
    db.commit()
    api = counted(FakeAPI([walk]))
    assert gc.check(db, api, 1, '2026-08-01', '2026-10-01')['recordings'] == 1
    [c] = reimport.pending(db)
    assert {d['label'] for d in c['diffs']} >= {'Distance', 'Elapsed time', 'Track'}
    assert db.execute("SELECT distance FROM Activity WHERE id='garmin_1'").fetchone()[0] > 25000       # untouched until chosen
    assert reimport.resolve(db, 'garmin_1', 'replace')
    assert db.execute("SELECT distance, elapsedTime FROM Activity WHERE id='garmin_1'").fetchone()[:] == (1600, 3200)
    assert gc.check(db, api, 1, '2026-08-01', '2026-10-01')['recordings'] == 0 and api.downloads == 1  # once only


def test_only_one_longer_in_distance_and_time_is_read_again(db):
    imported(db, act(1, '2026-09-01'), act(2, '2026-09-02'))                     # saved 15 km in 2,700 s (the faked file)
    listing = [act(1, '2026-09-01', dist=15000, dur=1800),                      # an old upload: Garmin's time is the timer's
               act(2, '2026-09-02', dist=12000, dur=3600)]                      # Garmin's distance recalculated
    for a in listing:
        db.execute('UPDATE GarminSeen SET summary=?, cropChecked=0 WHERE garminId=?', [json.dumps(gc.summary(a)), str(a['activityId'])])
    db.commit()
    api = counted(FakeAPI(listing))
    gc.check(db, api, 1, '2026-08-01', '2026-10-01')
    assert api.downloads == 0 and reimport.pending(db) == []
    assert db.execute('SELECT COUNT(*) FROM GarminSeen WHERE cropChecked=1').fetchone()[0] == 2


def _typed_in_earlier(db, gid=1, dist=0.0, secs=0, key='swimming', name='Swimming'):
    """A Garmin activity typed into Garmin Connect as a sync before 0.7.41 saved it: no mark, no streams, and whatever figures it was given then.
    Garmin's list now says 500 m in 40 minutes."""
    a = {**act(gid, '2016-11-01', name=name, key=key, dist=500.0, dur=2400.0), 'manualActivity': True, 'calories': 180}
    db.execute("INSERT INTO Activity (id, name, type, sportType, riderId, startDate, startDateLocal, distance, movingTime, elapsedTime, rawData) "
               "VALUES (?, ?, 'Swim', 'Swim', 1, '2016-11-01T08:00:00', '2016-11-01T09:00:00', ?, ?, ?, '{}')", [f'garmin_{gid}', name, dist, secs, secs])
    _streams.save(db, f'garmin_{gid}', '{}')
    from services import sanity
    sanity.flag(db, f'garmin_{gid}')
    gc.remember(db, a, read=False)
    db.commit()
    return a


def test_one_typed_in_and_saved_empty_takes_garmins_figures(db):
    """garmin_1430559984, 1 Nov 2016: saved as 0 m in 0 s; Garmin says 500 m in 40 minutes."""
    a = _typed_in_earlier(db)
    assert 'nothing was recorded' in db.execute("SELECT flagReason FROM Activity WHERE id='garmin_1'").fetchone()[0]
    res = gc.check(db, FakeAPI([a]), 1, '2016-10-01', '2016-12-01')
    r = db.execute(f"SELECT *, {_streams.sql()} FROM Activity WHERE id='garmin_1'").fetchone()
    assert (r['distance'], r['movingTime'], r['elapsedTime'], r['source'], r['flagReason']) == (500, 2400, 2400, 'manual', None)
    assert r['averageSpeed'] == pytest.approx(500 / 2400) and r['caloriesRaw'] == 180
    assert res['filled'] == 1 and res['recordings'] == 0 and reimport.pending(db) == []
    assert "given Garmin's" in gc.describe(res)
    assert gc.check(db, FakeAPI([a]), 1, '2016-10-01', '2016-12-01')['filled'] == 0


def test_one_typed_in_and_saved_empty_is_then_matched_with_its_strava_copy(db):
    a = _typed_in_earlier(db)
    db.execute("INSERT INTO Activity (id, name, type, sportType, riderId, startDate, startDateLocal, distance, movingTime, elapsedTime, source) "
               "VALUES ('776859134', 'Swim', 'Swim', 'Swim', 1, '2016-11-01T08:00:00', '2016-11-01T09:00:00', 500, 2400, 2400, 'manual')")
    db.commit()
    gc.check(db, FakeAPI([a]), 1, '2016-10-01', '2016-12-01')
    assert db.execute('SELECT COUNT(*) FROM Activity').fetchone()[0] == 1          # one swim, the other set aside behind it


def test_one_typed_in_that_differs_from_garmin_is_offered_once_either_way(db):
    a = _typed_in_earlier(db, dist=300.0, secs=1200)                               # shorter here: a crop check alone never looked
    res = gc.check(db, FakeAPI([a]), 1, '2016-10-01', '2016-12-01')
    assert res['recordings'] == 1 and res['filled'] == 0
    [c] = reimport.pending(db)
    assert {d['label'] for d in c['diffs']} >= {'Distance', 'Moving time', 'Elapsed time'}
    assert db.execute("SELECT distance FROM Activity WHERE id='garmin_1'").fetchone()[0] == 300     # nothing changed until it's reviewed
    db.execute('DELETE FROM ImportChange')
    assert gc.check(db, FakeAPI([a]), 1, '2016-10-01', '2016-12-01')['recordings'] == 0


def test_one_typed_in_that_matches_garmin_is_only_marked(db):
    a = _typed_in_earlier(db, dist=500.0, secs=2400)
    res = gc.check(db, FakeAPI([a]), 1, '2016-10-01', '2016-12-01')
    assert (res['recordings'], res['filled']) == (0, 0)
    r = db.execute(f"SELECT source, {_streams.sql()} FROM Activity WHERE id='garmin_1'").fetchone()
    assert r['source'] == 'manual' and r['streams'] is None                     # empty streams are stored as none
    assert duplicates.is_manual(db.execute(f"SELECT *, {_streams.sql()} FROM Activity WHERE id='garmin_1'").fetchone())


def test_a_recording_is_never_marked_typed_in(db):
    imported(db, act(1, '2026-09-01'))
    gc.check(db, FakeAPI([act(1, '2026-09-01')]), 1, '2026-08-01', '2026-10-01')
    assert db.execute("SELECT source FROM Activity WHERE id='garmin_1'").fetchone()[0] is None


def test_garmin_seen_from_before_gets_the_crop_check_column(db):
    db.execute('DROP TABLE IF EXISTS GarminSeen')
    db.execute("CREATE TABLE GarminSeen (garminId TEXT PRIMARY KEY, summary TEXT NOT NULL, seenAt TEXT DEFAULT (datetime('now')))")
    db.execute("INSERT INTO GarminSeen (garminId, summary) VALUES ('1', '{}')")
    gc.ensure_schema(db)
    assert db.execute("SELECT cropChecked FROM GarminSeen WHERE garminId='1'").fetchone()[0] == 0


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
    ride = c.get('/activities/garmin_2').get_data(as_text=True)
    assert 'This activity was changed in Garmin Connect' in ride and 'New name' in ride
    r = c.post('/garmin/changes/garmin_2/garmin', data={'back': 'ride'})
    assert r.status_code == 302 and r.headers['Location'].endswith('/activities/garmin_2')
    assert 'changed in Garmin Connect' not in c.get('/activities/garmin_2').get_data(as_text=True)
    assert 'This activity was deleted in Garmin Connect' in c.get('/activities/garmin_1').get_data(as_text=True)
    c.post('/garmin/changes/deleted/delete')
    with app.app_context():
        d = database.get_db()
        assert d.execute("SELECT name FROM Activity WHERE id='garmin_2'").fetchone()[0] == 'New name'
        assert not d.execute("SELECT 1 FROM Activity WHERE id='garmin_1'").fetchone() and gc.pending(d) == []


def test_settings_full_resync_button_runs_the_whole_check(tmp_path, monkeypatch):
    """Settings shows Full re-sync once Garmin is signed in for rides, and it starts garmin_changes.full in the background. Full app."""
    import app as app_module
    import config
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
    c = app.test_client()
    with c.session_transaction() as s:
        s['logged_in'] = True
        s['av'] = av
    assert 'Full re-sync' in c.get('/settings/').get_data(as_text=True)
    r = c.post('/garmin/changes/check?whole=1')
    assert r.status_code == 302 and r.headers['Location'].endswith('/import#garmin-changes')
    with app.app_context():
        job = jobs.active(database.get_db(), 'garmin_changes_check')
    assert job['args'] == {'rider': 1, 'whole': True}


def test_import_page_lists_the_missing_and_its_buttons_work(tmp_path, monkeypatch):
    """In Garmin, not here: listed on the Import page; Leave out settles it there and then, Bring in starts a background fetch. Full app."""
    import app as app_module
    import config
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
    assert 'href="https://connect.garmin.com/modern/activity/4"' in page and 'href="https://connect.garmin.com/modern/activity/3"' in page
    c.post('/garmin/missing/all/import')
    c.post('/garmin/missing/all/restore')                                   # one Garmin review job at a time: not while that one waits
    with app.app_context():
        db = database.get_db()
        assert [json.loads(r[0])['ids'] for r in db.execute("SELECT args FROM Job WHERE kind='garmin_bring_in'")] == [['3']]
        db.execute("UPDATE Job SET state='done'")
        db.commit()
    c.post('/garmin/missing/all/restore')
    with app.app_context():
        assert jobs.active(database.get_db(), 'garmin_bring_in')['args'] == {'ids': ['4']}


def in_step_ride(b):
    """A ride whose file reads with one time for each position, as the parser has read files since 0.7.7."""
    t = list(range(0, 600))
    streams = {'time': {'data': t}, 'latlng': {'data': [[50.5 + x * 5 / 111_000, -3.5] for x in t]}, 'distance': {'data': [x * 5.0 for x in t]}}
    return {'distance': 2995.0, 'movingTime': 599, 'elapsedTime': 599, 'startDateLocal': '2026-09-01T08:00:00', 'streams': json.dumps(streams)}


def test_one_stored_out_of_step_is_read_again_and_put_right_once(db, monkeypatch):
    monkeypatch.setattr('services.parser.parse_fit', in_step_ride)
    ride = act(1, '2026-09-01', dist=2995, dur=599)
    imported(db, ride)
    st = json.loads(_streams.load_json(db, 'garmin_1'))
    st['time']['data'] = list(range(630))                         # as an older Headwind kept it: a time for each record, 30 with no fix
    _streams.save(db, 'garmin_1', st)
    db.commit()
    api = counted(FakeAPI([ride]))
    res = gc.check(db, api, 1, '2026-08-01', '2026-10-01')
    assert res['in_step'] == 1 and api.downloads == 1 and 'out of step' in gc.describe(res)
    st = json.loads(_streams.load_json(db, 'garmin_1'))
    assert len(st['time']['data']) == len(st['latlng']['data']) == 600
    assert gc.check(db, api, 1, '2026-08-01', '2026-10-01')['in_step'] == 0 and api.downloads == 1   # once only


def test_a_copy_kept_beside_one_out_of_step_is_set_aside_once_it_is_put_right(db, monkeypatch):
    """A ski app's copy of the watch's day (Alpe d'Huez, March 2025): the last two thirds of it, so its track must agree with the watch's, and
    the watch's was stored with a time for 200 records with no fix, so it couldn't be compared until Garmin's file was read again."""
    monkeypatch.setattr('services.parser.parse_fit', in_step_ride)
    ride = act(1, '2026-09-01', dist=2995, dur=599)
    imported(db, ride)
    st = json.loads(_streams.load_json(db, 'garmin_1'))
    st['time']['data'] = [x * 0.75 for x in range(800)]                # each position's moment known only to within 150 s
    db.execute("UPDATE Activity SET sportType='AlpineSki', type='AlpineSki' WHERE id='garmin_1'")
    _streams.save(db, 'garmin_1', st)
    t = list(range(400))
    piece = {'time': {'data': t}, 'latlng': {'data': [[50.5 + (x + 200) * 5 / 111_000, -3.5] for x in t]}}
    db.execute("INSERT INTO Activity (id, name, type, sportType, riderId, startDate, startDateLocal, distance, movingTime, elapsedTime) "
               "VALUES ('14000000001', 'Ski app', 'AlpineSki', 'AlpineSki', 1, '2026-09-01T08:03:20', '2026-09-01T09:03:20', 1200, 399, 399)",
               [])
    _streams.save(db, '14000000001', json.dumps(piece))
    db.commit()
    assert duplicates.resolve(db, '14000000001') is None                  # the watch's track is minutes out where it lost the fix
    res = gc.check(db, FakeAPI([ride]), 1, '2026-08-01', '2026-10-01')
    assert res['in_step'] == 1
    assert {r[0] for r in db.execute('SELECT id FROM Activity')} == {'garmin_1'}
    assert db.execute("SELECT primaryId FROM ActivityDuplicate WHERE id='14000000001'").fetchone()[0] == 'garmin_1'


def test_one_out_of_step_that_cant_be_downloaded_is_tried_again_next_time(db, monkeypatch):
    monkeypatch.setattr('services.parser.parse_fit', in_step_ride)
    ride = act(1, '2026-09-01', dist=2995, dur=599)
    imported(db, ride)
    db.execute("UPDATE ActivityStream SET data=streams_pack(json_set(streams_json(data), '$.time.data', json('[0,1,2]'))) WHERE activityId='garmin_1'")
    db.commit()
    api = FakeAPI([ride])
    api.download_activity = lambda aid, dl_fmt=None: (_ for _ in ()).throw(RuntimeError('Garmin is busy'))
    assert gc.check(db, api, 1, '2026-08-01', '2026-10-01')['in_step'] == 0
    assert gc._out_of_step(db, ['garmin_1']) == {'garmin_1'}


def test_no_write_is_held_open_across_a_download_or_the_weather(db, monkeypatch):
    """A full re-sync on a live server (19 Nov 2026) held its first write open across every download after it: a page, a duplicate swap and the
    Tasks page all waited their 60 s for the lock and failed with "database is locked". The sync and the check commit before each call out."""
    held = []

    def weather(*a, **k):
        held.append(('weather', db.in_transaction))
    monkeypatch.setattr('services.weather.fetch_weather', weather)
    monkeypatch.setattr('services.parser.parse_fit', lambda b: {'distance': 15000, 'movingTime': 2700, 'elapsedTime': 2700, 'streams': None,
                                                                'startLat': 50.5, 'startLng': -3.5})
    rides = [act(i, f'2026-09-0{i}') for i in (1, 2, 3)]
    api = FakeAPI(rides)
    download = api.download_activity

    def watched(aid, dl_fmt=None):
        held.append(('download', db.in_transaction))
        return download(aid, dl_fmt)
    api.download_activity = watched
    for _ in garmin.sync_garmin_activities(1, api=api):
        pass
    assert len(held) == 6 and not any(h for _, h in held)
    held.clear()
    api.acts = [act(i, f'2026-09-0{i}', dist=12000, dur=2000) for i in (1, 2, 3)]       # all three cropped in Garmin: each file read again
    assert gc.full(db, api, 1)['recordings'] == 3
    assert len(held) == 3 and not any(h for _, h in held)
