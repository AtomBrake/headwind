"""A day's steps come from one chosen source (services/steps.py), never the highest of several: a phone counts pedalling as steps. Throwaway DB."""
from datetime import date, timedelta

import pytest
from flask import Flask

import database
from routes import nutrition
from services import steps


@pytest.fixture
def db(tmp_path):
    app = Flask(__name__)
    app.config['DATABASE'] = str(tmp_path / 't.db')
    app.config['TESTING'] = True
    app.register_blueprint(nutrition.bp)
    with app.app_context():
        database.migrate_db()
        d = database.get_db()
        d.execute("INSERT OR IGNORE INTO Settings (id) VALUES (1)")
        d.execute("INSERT INTO Rider (id, name, isDefault) VALUES (1, 'Tom', 1)")
        d.commit()
        yield d


@pytest.fixture
def client(db):
    from flask import current_app
    return current_app.test_client()


DAY = '2026-10-20'


def phone(db, metric, n, day=DAY):
    db.execute("INSERT INTO BodyMetric (riderId, logDate, metric, value, unit, source) VALUES (1,?,?,?,'steps','t')", [day, metric, n])


def garmin_days(db, n, steps_=6000):
    for i in range(n):
        db.execute('INSERT INTO GarminDaily (date, steps) VALUES (?,?)', [(date.today() - timedelta(days=i)).isoformat(), steps_])


def test_garmin_is_counted_alone_once_it_gives_steps(db):
    """A ride day: the phone counted 21,000 (pedalling), Garmin 6,000. Before, the phone won."""
    garmin_days(db, 5)
    db.execute('INSERT OR REPLACE INTO GarminDaily (date, steps) VALUES (?,?)', [DAY, 6000])
    phone(db, 'steps_health', 21000)
    assert steps.effective_source() == 'garmin'
    assert steps.steps_for(1, DAY) == (6000, 'Garmin')


def test_without_garmin_steps_the_phone_counts(db):
    garmin_days(db, 4)                                  # under 5 of the last 14 days: a bike computer's odd figure, not a watch
    phone(db, 'steps_phone', 9000)
    phone(db, 'steps_watch', 12000)
    assert steps.effective_source() == 'phone'
    assert steps.steps_for(1, DAY) == (9000, 'Phone')                    # the first phone source with a value, not the highest
    assert steps.steps_for(1, '2026-10-21') == (0, None)                 # nothing from the phone that day: never Garmin's instead


def test_a_typed_number_wins_and_a_chosen_source_is_kept(db):
    garmin_days(db, 14)
    db.execute('INSERT OR REPLACE INTO GarminDaily (date, steps) VALUES (?,?)', [DAY, 6000])
    phone(db, 'steps_health', 8000)
    db.execute("UPDATE Settings SET stepsSource='phone'")
    assert steps.steps_for(1, DAY) == (8000, 'Apple Health')
    phone(db, 'steps_manual', 7000)
    assert steps.steps_for(1, DAY) == (7000, 'Manual')


def test_the_steps_page_sets_and_reports_the_source(db, client):
    c = client
    assert c.post('/nutrition/api/steps/source', json={'source': 'nonsense'}).status_code == 400
    r = c.post('/nutrition/api/steps/source', json={'source': 'garmin'}).get_json()
    assert r['source'] == 'garmin' and r['effective'] == 'garmin'
    d = c.get('/nutrition/api/steps').get_json()
    assert d['source'] == 'garmin' and d['days'][0]['used'] is None
    c.post('/nutrition/api/steps/source', json={'source': 'auto'})
    assert db.execute('SELECT stepsSource FROM Settings').fetchone()[0] is None
