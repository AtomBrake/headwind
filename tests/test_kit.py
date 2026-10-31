"""Kit: shoes and the other gear that isn't a bike. Defaults per sport, distance from the activities, replace-at alerts once per level, retiring,
the activity page and bulk bar, and shoes from a Strava export. Throwaway DB, no network."""
import io
import json
import zipfile

import pytest
from flask import Flask

import database
from routes import import_rides
from services import bulk, gear, kit, strava_gear


@pytest.fixture
def db(tmp_path):
    app = Flask(__name__)
    app.config['DATABASE'] = str(tmp_path / 't.db')
    with app.app_context():
        database.migrate_db()
        d = database.get_db()
        d.execute("INSERT OR IGNORE INTO Settings (id) VALUES (1)")
        d.execute("INSERT INTO Rider (id, name, isDefault) VALUES (1, 'Tom', 1)")
        d.execute("INSERT INTO Rider (id, name, isDefault) VALUES (2, 'Sam', 0)")
        d.commit()
        yield d


def act(db, aid, sport='Run', km=10.0, day='2026-10-01', rider=1, kit_id=None):
    db.execute("INSERT INTO Activity (id, name, type, sportType, riderId, startDate, startDateLocal, distance, movingTime, elapsedTime, kitId) "
               "VALUES (?,?,?,?,?,?,?,?,3000,3000,?)", [aid, aid, sport, sport, rider, day + 'T08:00:00', day + 'T08:00:00', km * 1000, kit_id])
    db.commit()


def kit_of(db, aid):
    return db.execute('SELECT kitId FROM Activity WHERE id=?', [aid]).fetchone()[0]


def test_new_activities_get_the_default_for_their_sport_and_rides_never_do(db):
    road = kit.create(db, 1, 'Road shoes', sports_=['Run', 'Trail Run'])
    boots = kit.create(db, 1, 'Boots', sports_=['Hike'])
    for aid, sport in (('r', 'Run'), ('t', 'Trail Run'), ('h', 'Hike'), ('w', 'Walk'), ('b', 'Ride')):
        act(db, aid, sport)
        gear.on_ride_added(db, aid)
    assert (kit_of(db, 'r'), kit_of(db, 't'), kit_of(db, 'h'), kit_of(db, 'w'), kit_of(db, 'b')) == (road, road, boots, None, None)
    with pytest.raises(ValueError):
        kit.set_activity_kit(db, 'b', road)                     # a ride has a bike, not shoes
    act(db, 's', 'Run', rider=2)
    with pytest.raises(ValueError):
        kit.set_activity_kit(db, 's', road)                     # someone else's shoes


def test_a_sport_has_one_default_and_retiring_gives_it_up(db):
    a = kit.create(db, 1, 'Old pair', sports_=['Run'])
    b = kit.create(db, 1, 'New pair', sports_=['Run'])          # takes runs over
    assert kit.defaults(db, 1) == {'Run': b} and kit.defaults_of(db, a) == []
    kit.retire(db, b)
    assert kit.default_for(db, 1, 'Run') is None and [k['id'] for k in kit.list_kit(db, 1)] == [a]
    with pytest.raises(ValueError):
        kit.set_defaults(db, b, ['Run'])                        # retired: not a default


def test_distance_adds_up_and_alerts_fire_once_per_level(db, monkeypatch):
    sent = []
    monkeypatch.setattr(gear, '_notify', lambda alerts: sent.append([a['text'] for a in alerts]))
    k = kit.create(db, 1, 'Racers', replace_m=100_000, start_meters=50_000)      # 100 km, 50 km before Headwind
    act(db, 'a', km=30, kit_id=k)
    assert kit.status(db, kit.get(db, k))['meters'] == 80_000 and kit.status(db, kit.get(db, k))['level'] == 'ok'
    act(db, 'b', km=12)
    kit.set_activity_kit(db, 'b', k)                            # 92 km: nearly due
    act(db, 'c', km=2)
    kit.set_activity_kit(db, 'c', k)                            # 94 km: still "soon", no second alert
    assert len(sent) == 1 and 'Racers is nearly due for replacement' in sent[0][0]
    act(db, 'd', km=40)
    kit.set_activity_kit(db, 'd', k)                            # 134 km: straight to overdue, one alert
    assert len(sent) == 2 and 'overdue' in sent[1][0]
    assert [d['kit']['id'] for d in kit.due_items(db, 1)] == [k]
    kit.retire(db, k)
    assert kit.due_items(db, 1) == [] and kit.status(db, kit.get(db, k))['level'] == 'ok'
    assert kit.stats(db, k)['n'] == 4                           # retired, it keeps its history


def test_shoes_get_700_km_and_other_kit_nothing_unless_asked(db):
    assert kit.get(db, kit.create(db, 1, 'Pair'))['replaceAtM'] == 700_000
    assert kit.get(db, kit.create(db, 1, 'Wetsuit', kind='wetsuit'))['replaceAtM'] is None
    assert kit.get(db, kit.create(db, 1, 'Forever', replace_m=0))['replaceAtM'] is None


def test_deleting_kit_clears_its_activities(db):
    k = kit.create(db, 1, 'Pair', sports_=['Run'])
    act(db, 'a', kit_id=k)
    kit.delete(db, k)
    assert kit_of(db, 'a') is None and kit.defaults(db, 1) == {}


def test_bulk_sets_kit_on_workouts_and_skips_rides(db):
    k = kit.create(db, 1, 'Pair')
    act(db, 'a'); act(db, 'b', 'Walk'); act(db, 'c', 'Ride')
    res = bulk.apply(db, 'kit', ['a', 'b', 'c'], kit_id=k)
    assert (res['done'], res['skipped']) == (2, 1) and (kit_of(db, 'a'), kit_of(db, 'b'), kit_of(db, 'c')) == (k, k, None)
    bulk.apply(db, 'rider', ['a'], rider_id=2)
    assert kit_of(db, 'a') is None                              # moved to another rider: not their shoes


def test_a_ride_changed_to_a_run_takes_the_run_shoes_and_back_again_drops_them(db):
    from services import convert
    k = kit.create(db, 1, 'Pair', sports_=['Run'])
    act(db, 'x', 'Ride')
    convert.change_sport(db, None, 'x', 'Run')
    assert kit_of(db, 'x') == k
    convert.change_sport(db, None, 'x', 'Ride')
    assert kit_of(db, 'x') is None


CSV_HEAD = 'Activity ID,Activity Date,Activity Name,Activity Type,Activity Gear,Elapsed Time,Moving Time,Distance\n'
SHOES = ('Shoe Name,Shoe Brand,Shoe Model,Shoe Default Sport Types\n'
         ',Mizuno,Inspire,Run|Walk|Virtual Run|Trail Run\n'
         'Altra,Altra,timp 3,""\n'
         ',No name,Other,""\n'
         'Hanwag Boots,Hanwag,Tatra II,Hike\n')


def strava_zip(rows):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as z:
        z.writestr('activities.csv', CSV_HEAD + ''.join(rows))
        z.writestr('shoes.csv', SHOES)
        z.writestr('bikes.csv', 'Bike Name,Bike Brand,Bike Model,Bike Default Sport Types\n')
    buf.seek(0)
    return zipfile.ZipFile(buf)


def row(aid, day, sport, gear_name, km=8):
    return f'{aid},"{day}, 9:00:00 AM",{sport} {aid},{sport},{gear_name},3600,3500,{km}\n'


def test_shoes_from_a_strava_export_become_kit_with_their_activities(db):
    from datetime import date, timedelta
    recent = lambda n: (date.today() - timedelta(days=n)).strftime('%b %d, %Y')          # this month: these shoes are still worn
    rows = [row('1', recent(1), 'Run', 'Altra timp 3 Altra'), row('2', recent(2), 'Walk', 'No name'), row('3', 'Jun 1, 2015', 'Run', 'Mizuno Inspire'),
            row('4', recent(3), 'Hike', 'Hanwag Tatra II Hanwag Boots'), row('5', recent(4), 'Run', ''), row('6', recent(5), 'Ride', 'Altra timp 3 Altra')]
    z = strava_zip(rows)
    events = [json.loads(e[len('data: '):]) for e in import_rides._process_strava_export(z, z.namelist(), 1)]
    db.commit()
    done = events[-1]
    assert done['kit_added'] == 4 and done['kit_filled'] == 4
    items = {k['name']: k for k in kit.list_kit(db, 1, include_retired=True)}
    assert set(items) == {'Altra', 'No name', 'Mizuno Inspire', 'Hanwag Boots'}
    assert items['Mizuno Inspire']['retiredOn'] and not items['Altra']['retiredOn']       # last worn in 2015: comes in retired
    assert kit_of(db, '1') == items['Altra']['id'] and kit_of(db, '3') == items['Mizuno Inspire']['id'] and kit_of(db, '6') is None
    assert kit.defaults(db, 1) == {'Hike': items['Hanwag Boots']['id']}                    # Mizuno's defaults went with its retirement
    assert strava_gear.strava_kit_name(db, items['Altra']['id']) == 'Altra timp 3 Altra'
    # importing again changes nothing, and a deleted item stays deleted
    kit.delete(db, items['No name']['id']); db.commit()
    z = strava_zip(rows)
    done = [json.loads(e[len('data: '):]) for e in import_rides._process_strava_export(z, z.namelist(), 1)][-1]
    db.commit()
    assert done['kit_added'] == 0 and done['kit_filled'] == 0 and len(kit.list_kit(db, 1, include_retired=True)) == 3


def test_gear_pages_and_the_activity_picker(tmp_path, monkeypatch):
    import app as app_module
    import config
    from services import credentials

    class _NoThread:
        def __init__(self, *a, **kw): pass
        def start(self): pass
    monkeypatch.setattr(config.Config, 'DATABASE', str(tmp_path / 'web.db'))
    monkeypatch.setattr(app_module.threading, 'Thread', _NoThread)
    app = app_module.create_app()
    with app.app_context():
        d = database.get_db()
        d.execute("INSERT OR IGNORE INTO Settings (id) VALUES (1)")
        d.execute("UPDATE Settings SET units='metric' WHERE id=1")
        d.execute("INSERT INTO Rider (id, name, isDefault) VALUES (1, 'Tom', 1)")
        d.commit()
        act(d, 'run1')
        act(d, 'ride1', 'Ride')
        av = credentials.auth_version()
    c = app.test_client()
    with c.session_transaction() as s:
        s['logged_in'] = True
        s['av'] = av
    assert 'Add shoes or other gear' in c.get('/rides/run1').get_data(as_text=True)
    assert 'id="kitCard"' not in c.get('/rides/ride1').get_data(as_text=True)
    r = c.post('/gear/kit/save', data={'rider': '1', 'name': 'Trail shoes', 'kind': 'shoes', 'replace': '600', 'sport': ['Run']})
    assert r.status_code == 302
    kid = int(r.headers['Location'].rstrip('/').split('/')[-1])
    with app.app_context():
        k = kit.get(database.get_db(), kid)
        assert k['replaceAtM'] == 600_000 and kit.defaults(database.get_db(), 1) == {'Run': kid}
    assert c.post('/gear/activity/run1/kit', data={'kit': str(kid)}).status_code == 302
    page = c.get(f'/gear/kit/{kid}').get_data(as_text=True)
    assert 'Trail shoes' in page and '10.0 km' in page and 'Default for</span><span class="chip default">Run</span>' in page
    gear_page = c.get('/gear/').get_data(as_text=True)
    assert 'Shoes and other gear' in gear_page and 'Trail shoes' in gear_page
    assert 'selected>Trail shoes' in c.get('/rides/run1').get_data(as_text=True)
    assert c.post('/gear/activity/ride1/kit', data={'kit': str(kid)}).status_code == 302          # refused, with the reason on the page
    with app.app_context():
        assert kit_of(database.get_db(), 'ride1') is None
    opts = c.get('/rides/bulk/options').get_json()
    assert opts['riders'][0]['kit'] == [{'id': kid, 'name': 'Trail shoes'}]
