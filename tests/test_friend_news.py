"""A friend's new activities are easy to find: the Friends page shows each friend's latest activity, and after a sync that brought new ones it
says so ("Tom: 1 new ride, Evening Ride, 20 Oct") until dismissed. A first sync brings the friend's whole history, so it says nothing; what
several syncs bring adds up; an edit isn't new. End to end against a real feed on a second throwaway instance, and the page on the full app."""
import io

import pytest
from flask import Flask

import app as app_module
import config
import database
from routes import friends
from services import credentials, feed_tokens
from services import streams as _streams

TOKEN = 'tok'


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


def add_ride(tom, aid, name='Ride', day='2026-10-01', sport='Ride'):
    with tom.app_context():
        d = database.get_db()
        d.execute("INSERT INTO Activity (id,name,type,sportType,startDate,startDateLocal,distance,movingTime,elapsedTime,rawData,riderId) "
                  "VALUES (?,?,?,?,?,?,7200,1200,1200,'{}',1)", [aid, name, sport, sport, f'{day}T10:00:00', f'{day}T10:00:00'])
        _streams.save(d, aid, None)
        d.commit()


@pytest.fixture
def tom(tmp_path):
    """The friend's instance: rider Tom shares his activities."""
    app = make_app(tmp_path / 'tom.db')
    with app.app_context():
        d = database.get_db()
        d.execute("INSERT INTO Rider (id, name, isDefault) VALUES (1, 'Tom', 1)")
        d.execute("INSERT INTO FeedToken (name, tokenHash) VALUES ('Alex', ?)", [feed_tokens._hash(TOKEN)])
        d.execute('INSERT INTO FeedTokenRider (tokenId, riderId) VALUES (1, 1)')
        d.commit()
    return app


@pytest.fixture
def alex(tmp_path, tom, monkeypatch):
    """The instance syncing, with Tom as a friend."""
    app = make_app(tmp_path / 'alex.db')
    client = tom.test_client()
    monkeypatch.setattr(friends, 'open_peer', lambda url, headers, timeout: io.BytesIO(
        client.get(url.split('tom.example', 1)[1], headers=headers).data))
    with app.app_context():
        d = database.get_db()
        d.execute("INSERT INTO Rider (id, name, isDefault) VALUES (1, 'Alex', 1)")
        d.execute("INSERT INTO Friend (id, name, url, token) VALUES (1, 'Tom', 'https://tom.example', ?)", [TOKEN])
        d.commit()
        yield app


def news(alex):
    """What the Friends page says about Tom: (the "new" note or None, his latest activity's name)."""
    f = friends._with_activities(dict(database.query_db('SELECT * FROM Friend WHERE id=1', one=True)))
    return (f['new'] and (f['new']['text'], f['new']['newest']['name'])), f['latest'] and f['latest']['name']


def sync():
    assert friends._do_ride_sync(1)[1] is None


def test_the_first_sync_brings_history_and_no_note(alex, tom):
    add_ride(tom, 'a', 'Old ride', '2026-09-01')
    add_ride(tom, 'b', 'Last ride', '2026-10-01')
    sync()
    assert news(alex) == (None, 'Last ride')


def test_a_later_sync_says_what_came_in(alex, tom):
    add_ride(tom, 'a', 'Old ride', '2026-09-01')
    sync()
    add_ride(tom, 'b', 'Evening Ride', '2026-10-20')
    sync()
    assert news(alex) == (('1 new ride', 'Evening Ride'), 'Evening Ride')


def test_new_ones_from_several_syncs_add_up(alex, tom):
    add_ride(tom, 'a', 'Old run', '2026-09-01', 'Run')
    sync()
    add_ride(tom, 'b', 'Tuesday run', '2026-10-20', 'Run')
    sync()
    add_ride(tom, 'c', 'Thursday run', '2026-10-22', 'Run')
    sync()
    assert news(alex) == (('2 new runs', 'Thursday run'), 'Thursday run')


def test_an_edited_activity_is_not_new(alex, tom):
    add_ride(tom, 'a', 'Ride', '2026-09-01')
    sync()
    with tom.app_context():
        d = database.get_db()
        d.execute("UPDATE Activity SET name='Renamed', updatedAt=datetime('now', '+1 minute') WHERE id='a'")
        d.commit()
    sync()
    assert news(alex) == (None, 'Renamed')


def test_dismissing_clears_it_until_the_next_new_one(alex, tom):
    add_ride(tom, 'a', 'Old ride', '2026-09-01')
    sync()
    add_ride(tom, 'b', 'Ride two', '2026-10-01')
    sync()
    alex.test_client().post('/friends/1/seen')
    assert news(alex)[0] is None
    sync()                                          # nothing new: still nothing to say
    assert news(alex)[0] is None
    add_ride(tom, 'c', 'Ride three', '2026-10-02')
    sync()
    assert news(alex)[0] == ('1 new ride', 'Ride three')


def test_a_new_activity_no_longer_shared_drops_out(alex, tom):
    add_ride(tom, 'a', 'Old ride', '2026-09-01')
    sync()
    add_ride(tom, 'b', 'Gone soon', '2026-10-01')
    sync()
    with tom.app_context():
        d = database.get_db()
        d.execute("DELETE FROM Activity WHERE id='b'")
        d.commit()
    sync()
    assert news(alex) == (None, 'Old ride')


@pytest.mark.parametrize('sports_, text', [
    (['Ride'], '1 new ride'),
    (['Ride', 'VirtualRide', 'EBikeRide'], '3 new rides'),
    (['Walk', 'Walk'], '2 new walks'),
    (['VirtualRun'], '1 new indoor run'),
    (['Run', 'Ride'], '2 new activities'),
    (['Yoga'], '1 new activity'),
    (['Strength', 'Strength'], '2 new activities'),
])
def test_how_many_reads(sports_, text):
    assert friends._count(len(sports_), sports_) == text


# ── The page ─────────────────────────────────────────────────────

class _NoThread:
    def __init__(self, *a, **kw): pass
    def start(self): pass


@pytest.fixture
def page(tmp_path, monkeypatch):
    monkeypatch.setattr(config.Config, 'DATABASE', str(tmp_path / 'page.db'))
    monkeypatch.setattr(app_module.threading, 'Thread', _NoThread)
    app = app_module.create_app()
    with app.app_context():
        db = database.get_db()
        db.execute("INSERT OR IGNORE INTO Settings (id) VALUES (1)")
        db.execute("INSERT INTO Rider (id, name, isDefault) VALUES (1, 'Alex', 1), (2, 'Sam', 0), (3, 'Jo', 0)")
        db.execute("INSERT INTO Friend (id, name, url, token, riderId, lastSynced, newFrom) "
                   "VALUES (1, 'Sam', 'https://sam.example', 't', 2, '2026-10-21 08:00:00', '2026-10-20 00:00:00'), "
                   "(2, 'Jo', 'https://jo.example', 't', 3, '2026-10-21 08:00:00', NULL)")
        for aid, rid, name, day, made in (('f1_1', 2, 'Old ride', '2026-09-01', '2026-09-02 00:00:00'),
                                          ('f1_2', 2, 'Hill reps', '2026-10-20', '2026-10-20 12:00:00.123'),
                                          ('f2_1', 3, 'Park run', '2026-10-19', '2026-10-19 12:00:00')):
            db.execute("INSERT INTO Activity (id, name, sportType, riderId, startDateLocal, distance, createdAt) VALUES (?,?,?,?,?,16093,?)",
                       [aid, name, 'Run' if aid == 'f2_1' else 'Ride', rid, f'{day}T08:00:00', made])
        db.commit()
        av = credentials.auth_version()
    c = app.test_client()
    with c.session_transaction() as s:
        s['logged_in'] = True
        s['av'] = av
    return c


def test_the_page_shows_latest_activities_and_whats_new(page):
    html = page.get('/friends').get_data(as_text=True)
    assert '<b>Sam</b>: 1 new ride, <a href="/rides/f1_2">Hill reps</a>, 20 Oct' in html
    assert 'Jo</b>' not in html                                   # nothing new from Jo
    assert '<a href="/rides/f2_1">Park run</a>' in html            # but Jo's latest is in the list
    assert 'href="/activities?rider=3"' in html                   # and Jo's name goes to their activities
    page.post('/friends/1/seen')
    assert '<b>Sam</b>' not in page.get('/friends').get_data(as_text=True)
