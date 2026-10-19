"""Friend sync, end to end against a real feed on a second throwaway instance: only what is new is fetched and matched. Every sync sends every
shared segment, but an unchanged one isn't matched against the owner's whole history again; a new or moved one is, from scratch. Rides: a
manifest of every shared ride, then only the missing or changed ones by id, so a late upload, an edit and a deletion all arrive, and a sync
that stops part way only counts as done when it is. A friend on a version before 0.7.6 gets the old ?since= request."""
import io
import json

import pytest
from flask import Flask

import database
from routes import friends
from services import feed_tokens, segments

D_LAT = 6.0 / 111_320.0          # a ride at 6 m/s, one fix a second
TOKEN = 'tok'
REQUESTS = []                    # the paths Alex's instance asked Tom's for, this sync


def line(secs=1200, lat0=51.5, lng0=-0.12, speed=6.0):
    ll = [[lat0 + i * speed / 111_320.0, lng0] for i in range(secs + 1)]
    return json.dumps({'latlng': {'data': ll}, 'time': {'data': list(range(secs + 1))}, 'distance': {'data': [i * speed for i in range(secs + 1)]}})


def add_ride(db, aid, rider=1, day='2026-10-01', speed=6.0):
    db.execute("INSERT INTO Activity (id,name,type,sportType,startDate,startDateLocal,distance,movingTime,elapsedTime,rawData,riderId,streams) "
               "VALUES (?,'R','Ride','Ride',?,?,7200,1200,1200,'{}',?,?)", [aid, f'{day}T10:00:00', f'{day}T10:00:00', rider, line(speed=speed)])
    db.commit()


def add_seg(db, start_s=100, end_s=700, lng=-0.12, name='Hill'):
    db.execute("INSERT INTO Segment (name,startLat,startLng,endLat,endLng,distanceM,sport) VALUES (?,?,?,?,?,?,'ride')",
               [name, 51.5 + start_s * D_LAT, lng, 51.5 + end_s * D_LAT, lng, (end_s - start_s) * 6.0])
    db.commit()
    return db.execute('SELECT last_insert_rowid()').fetchone()[0]


def make_app(path):
    app = Flask(__name__)
    app.config['DATABASE'] = str(path)
    app.teardown_appcontext(database.close_db)
    app.register_blueprint(friends.bp)
    with app.app_context():
        database.migrate_db()
        d = database.get_db()
        d.execute("INSERT OR IGNORE INTO Settings (id) VALUES (1)")
        d.commit()
    return app


@pytest.fixture
def tom(tmp_path):
    """The friend's instance: rider Tom shares his rides and segments."""
    app = make_app(tmp_path / 'tom.db')
    with app.app_context():
        d = database.get_db()
        d.execute("INSERT INTO Rider (id, name, isDefault) VALUES (1, 'Tom', 1)")
        d.execute("INSERT INTO FeedToken (name, tokenHash) VALUES ('Alex', ?)", [feed_tokens._hash(TOKEN)])
        d.commit()
    return app


@pytest.fixture
def db(tmp_path, tom, monkeypatch):
    """Alex's instance, the one syncing, with Tom as a friend and one ride of his own along Tom's segment."""
    app = make_app(tmp_path / 'alex.db')
    client = tom.test_client()

    def fake_peer(url, headers, timeout):
        path = url.split('tom.example', 1)[1]
        REQUESTS.append(path)
        resp = client.get(path, headers=headers)
        assert resp.status_code == 200, resp.status_code
        return io.BytesIO(resp.data)
    monkeypatch.setattr(friends, 'open_peer', fake_peer)
    with app.app_context():
        d = database.get_db()
        d.execute("INSERT INTO Rider (id, name, isDefault) VALUES (1, 'Alex', 1)")
        d.execute("INSERT INTO Friend (id, name, url, token) VALUES (1, 'Tom', 'https://tom.example', ?)", [TOKEN])
        d.commit()
        add_ride(d, 'own1')
        yield d


def on_tom(tom, fn):
    with tom.app_context():
        d = database.get_db()
        out = fn(d)
        d.commit()
        return out


def sync(db):
    REQUESTS.clear()
    return friends._do_ride_sync(1)


def count_scans(monkeypatch):
    calls = []
    real = segments.scan_activity_against_segments
    monkeypatch.setattr(segments, 'scan_activity_against_segments', lambda db, act, segs, **kw: calls.append(act['id']) or real(db, act, segs, **kw))
    monkeypatch.setattr(friends, 'scan_activity_against_segments', segments.scan_activity_against_segments)
    return calls


def efforts(db):
    return {r['activityId']: r['isPR'] for r in db.execute('SELECT activityId, isPR FROM SegmentEffort')}


def friend_rides(db):
    return {r['id']: r['name'] for r in db.execute("SELECT id, name FROM Activity WHERE id LIKE 'f1_%'")}


def fetched(db):
    return [p for p in REQUESTS if 'ids=' in p]


# ── Segments ─────────────────────────────────────────────────────

def test_a_new_segment_is_matched_against_the_owners_rides(db, tom):
    on_tom(tom, add_seg)
    assert sync(db) == (0, None)
    assert efforts(db) == {'own1': 1}


def test_an_unchanged_segment_reads_no_ride_again(db, tom, monkeypatch):
    on_tom(tom, add_seg)
    sync(db)
    calls = count_scans(monkeypatch)
    assert sync(db) == (0, None)
    assert calls == []
    assert efforts(db) == {'own1': 1}


def test_a_renamed_segment_reads_no_ride_again(db, tom, monkeypatch):
    sid = on_tom(tom, add_seg)
    sync(db)
    calls = count_scans(monkeypatch)
    on_tom(tom, lambda d: d.execute("UPDATE Segment SET name='The Hill' WHERE id=?", [sid]))
    sync(db)
    assert calls == []
    assert db.execute('SELECT name FROM Segment').fetchone()[0] == 'The Hill'


def test_a_moved_segment_is_matched_again_from_scratch(db, tom):
    sid = on_tom(tom, add_seg)
    sync(db)
    on_tom(tom, lambda d: d.execute('UPDATE Segment SET startLng=-0.5, endLng=-0.5 WHERE id=?', [sid]))   # somewhere Alex never rode
    sync(db)
    assert efforts(db) == {}
    on_tom(tom, lambda d: d.execute('UPDATE Segment SET startLng=-0.12, endLng=-0.12 WHERE id=?', [sid]))
    sync(db)
    assert efforts(db) == {'own1': 1}


def test_a_segment_stored_by_a_sync_that_stopped_is_still_matched(db, tom, monkeypatch):
    on_tom(tom, add_seg)
    real = friends.scan_all_activities
    monkeypatch.setattr(friends, 'scan_all_activities', lambda *a, **k: (_ for _ in ()).throw(RuntimeError('restart')))
    with pytest.raises(RuntimeError):
        sync(db)
    monkeypatch.setattr(friends, 'scan_all_activities', real)
    sync(db)
    assert efforts(db) == {'own1': 1}


# ── Rides ────────────────────────────────────────────────────────

def test_a_received_ride_is_matched_and_gets_its_riders_pr(db, tom, monkeypatch):
    on_tom(tom, add_seg)
    sync(db)
    on_tom(tom, lambda d: add_ride(d, 'r1'))
    calls = count_scans(monkeypatch)
    sync(db)
    assert calls == ['f1_r1']                       # only the new ride is read
    assert efforts(db) == {'own1': 1, 'f1_r1': 1}   # each rider has their own PR


def test_nothing_new_fetches_no_ride(db, tom):
    on_tom(tom, lambda d: add_ride(d, 'r1'))
    sync(db)
    assert sync(db) == (0, None)
    assert fetched(db) == []


def test_a_late_upload_of_an_old_ride_still_arrives(db, tom):
    on_tom(tom, lambda d: add_ride(d, 'r1', day='2026-10-18'))
    sync(db)
    on_tom(tom, lambda d: add_ride(d, 'r0', day='2026-09-01'))       # started well before the last sync
    assert sync(db) == (1, None)
    assert set(friend_rides(db)) == {'f1_r1', 'f1_r0'}


def test_an_edit_arrives_and_only_that_ride_is_fetched(db, tom):
    on_tom(tom, lambda d: [add_ride(d, 'r1'), add_ride(d, 'r2', day='2026-10-02')])
    sync(db)
    on_tom(tom, lambda d: d.execute("UPDATE Activity SET name='Morning loop', sportType='EBikeRide' WHERE id='r1'"))
    assert sync(db) == (1, None)
    assert fetched(db) == ['/api/feed?ids=r1']
    assert friend_rides(db)['f1_r1'] == 'Morning loop'
    assert db.execute("SELECT sportType FROM Activity WHERE id='f1_r1'").fetchone()[0] == 'EBikeRide'
    assert sync(db) == (0, None)


def test_a_deleted_ride_goes_with_its_efforts(db, tom):
    on_tom(tom, add_seg)
    on_tom(tom, lambda d: [add_ride(d, 'r1'), add_ride(d, 'r2', day='2026-10-02', speed=7.0)])
    sync(db)
    assert efforts(db)['f1_r2'] == 1                # r2 is faster on the segment
    on_tom(tom, lambda d: d.execute("DELETE FROM Activity WHERE id='r2'"))
    sync(db)
    assert set(friend_rides(db)) == {'f1_r1'}
    assert efforts(db) == {'own1': 1, 'f1_r1': 1}   # r1 has Tom's PR again


def test_rides_no_longer_shared_go(db, tom):
    on_tom(tom, lambda d: add_ride(d, 'r1'))
    sync(db)
    on_tom(tom, lambda d: d.execute('UPDATE FeedToken SET shareRides=0'))
    sync(db)
    assert friend_rides(db) == {}


def test_a_rider_tom_no_longer_has_deletes_nothing(db, tom):
    on_tom(tom, lambda d: add_ride(d, 'r1'))
    sync(db)
    db.execute("UPDATE Friend SET riderName='Thomas'")         # no such rider there: no manifest
    db.commit()
    sync(db)
    assert set(friend_rides(db)) == {'f1_r1'}


def test_a_sync_that_stops_part_way_is_not_done_and_the_next_gets_the_rest(db, tom, monkeypatch):
    monkeypatch.setattr(friends, 'MAX_IDS', 2)
    on_tom(tom, lambda d: [add_ride(d, f'r{i}', day=f'2026-10-0{i}') for i in range(1, 6)])
    peer = friends.open_peer
    calls = []

    def flaky(url, headers, timeout):
        calls.append(url)
        if len(calls) == 3:                         # the manifest, one batch, then the network goes
            raise OSError('connection reset')
        return peer(url, headers, timeout)
    monkeypatch.setattr(friends, 'open_peer', flaky)
    n, err = sync(db)
    assert (n, err) == (2, 'connection reset')
    assert db.execute('SELECT lastSynced FROM Friend').fetchone()[0] is None
    monkeypatch.setattr(friends, 'open_peer', peer)
    assert sync(db) == (3, None)
    assert len(friend_rides(db)) == 5
    assert db.execute('SELECT lastSynced FROM Friend').fetchone()[0]


def test_a_ride_stored_but_never_matched_is_fetched_again(db, tom):
    on_tom(tom, lambda d: add_ride(d, 'r1'))
    sync(db)
    db.execute("UPDATE Activity SET srcUpdatedAt='' WHERE id='f1_r1'")     # what a sync that stopped before matching leaves
    db.commit()
    assert sync(db) == (1, None)


def test_rides_from_before_the_manifest_are_not_all_fetched_again(db, tom):
    on_tom(tom, lambda d: [add_ride(d, 'r1'), add_ride(d, 'r2', day='2026-10-02')])
    sync(db)
    on_tom(tom, lambda d: d.execute("UPDATE Activity SET updatedAt='2026-10-01 00:00:00'"))
    db.execute("UPDATE Activity SET srcUpdatedAt=NULL WHERE id LIKE 'f1_%'")             # as synced by 0.7.5
    db.execute("UPDATE Friend SET lastSynced='2026-10-10 00:00:00'")
    db.commit()
    on_tom(tom, lambda d: d.execute("UPDATE Activity SET name='Edited after the last sync' WHERE id='r2'"))
    assert sync(db) == (1, None)
    assert fetched(db) == ['/api/feed?ids=r2']
    assert sync(db) == (0, None)                    # r1 is settled now: nothing more


# ── A friend on a version before 0.7.6 ──────────────────────────

def old_feed(monkeypatch, *items, fail=False):
    body = ''.join(json.dumps(o) + '\n' for o in ({'type': 'meta', 'name': 'Tom'}, *items)).encode()

    class Resp(io.BytesIO):
        def readline(self, *a):
            got = super().readline(*a)
            if not got and fail:
                raise OSError('connection reset')
            return got
    monkeypatch.setattr(friends, 'open_peer', lambda url, headers, timeout: Resp(body))


def old_ride(rid):
    return {'type': 'ride', 'id': rid, 'name': 'Old feed ride', 'sportType': 'Ride', 'startDate': '2026-10-18T09:00:00Z',
            'startDateLocal': '2026-10-18T10:00:00', 'distance': 7200, 'movingTime': 1200, 'elapsedTime': 1200, 'streams': line()}


def test_an_old_friends_feed_still_syncs(db, monkeypatch):
    old_feed(monkeypatch, old_ride('r1'))
    assert sync(db) == (1, None)
    assert friend_rides(db) == {'f1_r1': 'Old feed ride'}
    assert db.execute('SELECT lastSynced FROM Friend').fetchone()[0]


def test_an_old_friends_feed_that_breaks_is_not_done(db, monkeypatch):
    old_feed(monkeypatch, old_ride('r1'), fail=True)
    assert sync(db) == (1, 'connection reset')
    assert db.execute('SELECT lastSynced FROM Friend').fetchone()[0] is None


def test_an_old_friend_asks_with_since_and_gets_no_manifest(db, tom):
    """A friend on 0.7.5 reading this instance's feed: the rides since that day, and an end line it ignores."""
    on_tom(tom, lambda d: [add_ride(d, 'r1', day='2026-10-01'), add_ride(d, 'r2', day='2026-10-18')])
    lines = [json.loads(x) for x in tom.test_client().get('/api/feed?since=2026-10-10', headers={'X-Feed-Token': TOKEN}).get_data(as_text=True).splitlines()]
    assert [o['type'] for o in lines] == ['meta', 'ride', 'end']
    assert lines[1]['id'] == 'r2'


def test_rewriting_a_ride_with_the_same_values_or_new_calories_fetches_nothing(db, tom):
    on_tom(tom, lambda d: add_ride(d, 'r1'))
    sync(db)
    on_tom(tom, lambda d: d.execute("UPDATE Activity SET name=name, streams=streams, calories=512 WHERE id='r1'"))
    assert sync(db) == (0, None)


# ── Every sport ──────────────────────────────────────────────────

def add_run(db, aid, day='2026-10-05', speed=3.0):
    db.execute("INSERT INTO Activity (id,name,type,sportType,startDate,startDateLocal,distance,movingTime,elapsedTime,rawData,riderId,streams,steps) "
               "VALUES (?,'Run','Run','Run',?,?,3600,1200,1200,'{}',1,?,4200)", [aid, f'{day}T07:00:00', f'{day}T07:00:00', line(speed=speed)])
    db.commit()


def test_a_friends_run_arrives_and_races_on_their_foot_segment(db, tom):
    def setup(d):
        add_run(d, 'run1')
        d.execute("INSERT INTO Segment (name,startLat,startLng,endLat,endLng,distanceM,sport) VALUES ('Park lap',?,-0.12,?,-0.12,1500,'foot')",
                  [51.5 + 100 * 3.0 / 111_320.0, 51.5 + 600 * 3.0 / 111_320.0])
    on_tom(tom, setup)
    assert sync(db) == (1, None)
    row = db.execute("SELECT sportType, steps FROM Activity WHERE id='f1_run1'").fetchone()
    assert (row['sportType'], row['steps']) == ('Run', 4200)
    assert efforts(db) == {'f1_run1': 1}            # Alex's ride never races on a foot segment


def test_a_friend_on_an_older_version_gets_runs_too(db, tom):
    on_tom(tom, lambda d: [add_run(d, 'run1', day='2026-10-18'), add_ride(d, 'r1', day='2026-10-18')])
    body = tom.test_client().get('/api/feed?since=2026-10-10', headers={'X-Feed-Token': TOKEN}).get_data(as_text=True)
    assert sorted(o['id'] for o in map(json.loads, body.splitlines()) if o['type'] == 'ride') == ['r1', 'run1']
