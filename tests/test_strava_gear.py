"""Bikes from a Strava export: the import records which Strava bike rode each ride, the rider matches the Strava bikes to theirs (or new ones),
and the rides follow the matches without overwriting a bike the rider set. Throwaway DB, no network."""
import io
import json
import zipfile

import pytest
from flask import Flask

import database
from routes import import_rides
from services import gear, strava_gear

CSV_HEAD = 'Activity ID,Activity Date,Activity Name,Activity Type,Activity Gear,Elapsed Time,Moving Time,Distance\n'
BIKES = ('Bike Name,Bike Brand,Bike Model,Bike Default Sport Types\n'
         'Stumpy Evo,Specialized,Stumpjumper Evo,Mountain Bike Ride\n'
         'Co Bikes,,,""\n'
         'Orange Crush,Orange,Crush,""\n')
SHOES = 'Shoe Name,Shoe Brand,Shoe Model,Shoe Default Sport Types\nAltra,Altra,timp 3,""\n,Mizuno,Inspire,Run\n'


def row(act_id, day, sport='Ride', bike='', km=20):
    return f'{act_id},"{day}, 9:00:00 AM",Ride {act_id},{sport},{bike},3600,3500,{km}\n'


ROWS = [row('r1', 'Jul 4, 2026', bike='Stumpy Evo'), row('r2', 'Jul 5, 2026', 'E-Bike Ride', 'Co Bikes'),
        row('r3', 'Jul 6, 2026', 'Run', 'Altra', 8), row('r4', 'Jul 7, 2026')]


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


def strava_zip(rows, bikes=BIKES, shoes=SHOES):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as z:
        z.writestr('activities.csv', CSV_HEAD + ''.join(rows))
        if bikes:
            z.writestr('bikes.csv', bikes)
        if shoes:
            z.writestr('shoes.csv', shoes)
    buf.seek(0)
    return zipfile.ZipFile(buf)


def run_import(db, rows, **kw):
    z = strava_zip(rows, **kw)
    events = [json.loads(e[len('data: '):]) for e in import_rides._process_strava_export(z, z.namelist(), 1)]
    db.commit()
    return events[-1]


def bike_of(db, act_id):
    return db.execute('SELECT bikeId FROM Activity WHERE id=?', [act_id]).fetchone()[0]


def by_name(rows):
    return {r['name']: r for r in rows}


def test_rides_that_name_a_strava_bike_wait_for_it_instead_of_taking_the_default(db):
    road = gear.create_bike(db, 1, 'Road bike'); db.commit()               # the default bike
    done = run_import(db, ROWS)
    assert done['imported'] == 4 and done['bikes_to_match'] == 3 and done['bikes_filled'] == 0
    assert bike_of(db, 'r1') is None and bike_of(db, 'r2') is None          # not stamped with the default
    assert bike_of(db, 'r4') == road                                        # no Strava bike: the default, as before
    assert bike_of(db, 'r3') is None                                        # a run in shoes is left alone
    assert dict(db.execute('SELECT activityId, gear FROM StravaGear').fetchall()) == {'r1': 'Stumpy Evo', 'r2': 'Co Bikes'}

    rows = by_name(strava_gear.overview(db, 1))
    assert set(rows) == {'Stumpy Evo', 'Co Bikes', 'Orange Crush'}
    assert rows['Stumpy Evo']['kind'] == 'mtb' and rows['Co Bikes']['kind'] == 'ebike'          # from the default sport, from what it rode
    assert rows['Stumpy Evo']['choice'] == 'new' and rows['Orange Crush']['choice'] == 'ignore'  # no rides: nothing to add
    assert rows['Stumpy Evo']['brand'] == 'Specialized' and rows['Stumpy Evo']['rides'] == 1


def test_saving_the_matches_creates_bikes_and_moves_the_rides(db):
    road = gear.create_bike(db, 1, 'Road bike'); db.commit()
    run_import(db, ROWS)
    res = strava_gear.save(db, 1, {'Stumpy Evo': {'match': 'new', 'kind': 'mtb'}, 'Co Bikes': {'match': 'ignore'}, 'Orange Crush': {'match': 'ignore'}})
    db.commit()
    stumpy = db.execute("SELECT * FROM Bike WHERE name='Stumpy Evo'").fetchone()
    assert res == {'created': ['Stumpy Evo'], 'moved': 1}
    assert (stumpy['kind'], stumpy['brand'], stumpy['model']) == ('mtb', 'Specialized', 'Stumpjumper Evo')
    assert bike_of(db, 'r1') == stumpy['id'] and bike_of(db, 'r2') is None and bike_of(db, 'r4') == road
    assert strava_gear.pending(db, 1) == 0
    assert db.execute('SELECT defaultBikeId FROM Rider WHERE id=1').fetchone()[0] == road          # a default already set is kept
    assert strava_gear.strava_name(db, stumpy['id']) == 'Stumpy Evo'

    done = run_import(db, ROWS + [row('r5', 'Aug 1, 2026', bike='Stumpy Evo')])                   # the next export follows the matches
    assert done['imported'] == 1 and done['bikes_filled'] == 1 and done['bikes_to_match'] == 0
    assert bike_of(db, 'r5') == stumpy['id']


def test_a_strava_bike_named_like_one_of_yours_is_matched_straight_away(db):
    mine = gear.create_bike(db, 1, 'stumpy  EVO'); db.commit()
    done = run_import(db, ROWS)
    assert bike_of(db, 'r1') == mine and done['bikes_filled'] == 1
    assert by_name(strava_gear.overview(db, 1))['Stumpy Evo']['status'] == 'matched'


def test_rides_already_saved_get_their_bike_but_one_you_set_is_kept_unless_asked(db):
    road = gear.create_bike(db, 1, 'Road bike'); spare = gear.create_bike(db, 1, 'Spare'); db.commit()
    run_import(db, ROWS, bikes=None)                                       # an export without bikes.csv: the ride names are enough
    gear.set_ride_bike(db, 'r2', spare); db.commit()                        # set by hand
    run_import(db, ROWS)                                                    # imported again: recorded for the saved rides too
    assert strava_gear.pending(db, 1) == 3
    assert by_name(strava_gear.overview(db, 1))['Co Bikes']['elsewhere'] == 1

    strava_gear.save(db, 1, {'Stumpy Evo': {'match': str(road)}, 'Co Bikes': {'match': 'new', 'kind': 'ebike'}})
    db.commit()
    co = db.execute("SELECT id FROM Bike WHERE name='Co Bikes'").fetchone()[0]
    assert bike_of(db, 'r1') == road and bike_of(db, 'r2') == spare         # the hand-set bike stays

    strava_gear.save(db, 1, {'Co Bikes': {'match': str(co)}}, replace=True)
    db.commit()
    assert bike_of(db, 'r2') == co


def test_changing_a_match_moves_the_rides_the_old_match_placed(db):
    road = gear.create_bike(db, 1, 'Road bike'); db.commit()
    run_import(db, ROWS)
    strava_gear.save(db, 1, {'Stumpy Evo': {'match': str(road)}}); db.commit()
    assert bike_of(db, 'r1') == road
    strava_gear.save(db, 1, {'Stumpy Evo': {'match': 'new', 'kind': 'mtb'}}); db.commit()
    stumpy = db.execute("SELECT id FROM Bike WHERE name='Stumpy Evo'").fetchone()[0]
    assert bike_of(db, 'r1') == stumpy
    strava_gear.save(db, 1, {'Stumpy Evo': {'match': 'ignore'}}); db.commit()
    assert bike_of(db, 'r1') is None and bike_of(db, 'r4') == road         # a ride Strava has no bike for is not touched


def test_the_most_recent_bike_becomes_the_default_and_retired_ones_are_archived(db):
    run_import(db, [row('a', 'Jan 2, 2015', bike='Stumpy Evo'), row('b', 'Jul 5, 2026', 'E-Bike Ride', 'Co Bikes')])
    rows = by_name(strava_gear.overview(db, 1))
    assert rows['Stumpy Evo']['retire'] and not rows['Co Bikes']['retire']                         # last ridden over a year ago
    strava_gear.save(db, 1, {'Stumpy Evo': {'match': 'new', 'kind': 'mtb', 'retired': True}, 'Co Bikes': {'match': 'new', 'kind': 'ebike'}})
    db.commit()
    co, stumpy = (db.execute('SELECT id FROM Bike WHERE name=?', [n]).fetchone()[0] for n in ('Co Bikes', 'Stumpy Evo'))
    assert db.execute('SELECT defaultBikeId FROM Rider WHERE id=1').fetchone()[0] == co
    assert gear.get_bike(db, stumpy)['archived'] == 1 and bike_of(db, 'a') == stumpy                # retired, its ride kept


def test_a_turbo_is_not_made_the_default_while_there_is_another_bike(db):
    run_import(db, [row('a', 'Jul 5, 2026', bike='Stumpy Evo'), row('z', 'Oct 17, 2026', 'Virtual Ride', 'Turbo'),
                    row('x', 'Oct 16, 2026', 'Virtual Ride', 'Turbo'), row('y', 'Oct 1, 2026', bike='Turbo')])
    rows = by_name(strava_gear.overview(db, 1))
    assert rows['Turbo']['kind'] == 'turbo'                                                       # mostly indoor
    strava_gear.save(db, 1, {n: {'match': 'new', 'kind': r['kind']} for n, r in rows.items() if r['rides']}); db.commit()
    assert db.execute('SELECT b.name FROM Rider r JOIN Bike b ON b.id=r.defaultBikeId').fetchone()[0] == 'Stumpy Evo'


def test_a_rider_bike_from_someone_else_is_refused(db):
    db.execute("INSERT INTO Rider (id, name, isDefault) VALUES (2, 'Leanne', 0)")
    theirs = gear.create_bike(db, 2, 'Hers'); db.commit()
    run_import(db, ROWS)
    with pytest.raises(ValueError):
        strava_gear.save(db, 1, {'Stumpy Evo': {'match': str(theirs)}})


def test_deleting_a_matched_bike_puts_the_strava_bike_back_to_match(db):
    run_import(db, ROWS)
    strava_gear.save(db, 1, {'Stumpy Evo': {'match': 'new'}, 'Co Bikes': {'match': 'ignore'}, 'Orange Crush': {'match': 'ignore'}}); db.commit()
    gear.delete_bike(db, db.execute("SELECT id FROM Bike WHERE name='Stumpy Evo'").fetchone()[0]); db.commit()
    assert strava_gear.pending(db, 1) == 1 and by_name(strava_gear.overview(db, 1))['Stumpy Evo']['choice'] == 'new'


def test_guess_kind():
    from collections import Counter
    assert strava_gear.guess_kind('Handcycle|Gravel Ride|Virtual Ride|E-Mountain Bike Ride|Ride', Counter({'Ride': 300})) == 'other'
    assert strava_gear.guess_kind('', Counter({'Virtual Ride': 202, 'Ride': 9})) == 'turbo'
    assert strava_gear.guess_kind('', Counter({'E-Bike Ride': 8, 'Ride': 42})) == 'other'          # a loan bike, mostly pedalled
    assert strava_gear.guess_kind('Gravel Ride', Counter()) == 'gravel'


class _NoThread:
    def __init__(self, *a, **kw): pass
    def start(self): pass


def test_the_match_page_renders_and_saves(tmp_path, monkeypatch):
    import app as app_module
    import config
    from services import credentials
    monkeypatch.setattr(config.Config, 'DATABASE', str(tmp_path / 'web.db'))
    monkeypatch.setattr(app_module.threading, 'Thread', _NoThread)
    a = app_module.create_app()
    with a.app_context():
        d = database.get_db()
        d.execute("INSERT OR IGNORE INTO Settings (id) VALUES (1)")
        d.execute("INSERT INTO Rider (id, name, isDefault) VALUES (1, 'Tom', 1)")
        d.commit()
        run_import(d, ROWS)
        av = credentials.auth_version()
    c = a.test_client()
    with c.session_transaction() as s:
        s['logged_in'] = True
        s['av'] = av
    page = c.get('/gear/strava')
    assert page.status_code == 200 and b'Stumpy Evo' in page.data and b'Add as a new bike' in page.data
    assert b'Match Strava bikes' in c.get('/gear/').data and b'Match Strava bikes' in c.get('/import').data
    r = c.post('/gear/strava', data={'name': ['Co Bikes', 'Orange Crush', 'Stumpy Evo'], 'match_0': 'ignore', 'match_1': 'ignore', 'match_2': 'new', 'kind_2': 'mtb'})
    assert r.status_code == 302 and 'done=' in r.headers['Location']
    assert b'1 ride put on its Strava bike' in c.get(r.headers['Location']).data
    with a.app_context():
        d = database.get_db()
        assert strava_gear.pending(d, 1) == 0
        stumpy = d.execute("SELECT id FROM Bike WHERE name='Stumpy Evo'").fetchone()[0]
    assert b'Strava had on' in c.get(f'/gear/bike/{stumpy}').data
