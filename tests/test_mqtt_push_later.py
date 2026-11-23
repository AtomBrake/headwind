"""services/mqtt.push_later: a page's Home Assistant update is queued for the worker, not run while the page waits (a Settings save took 3-4 s
working out every sensor). Queued only with MQTT set up, once while one is waiting, and the job runs the push. Full app, throwaway DB."""
import pytest

import app as app_module
import config
import database
from services import credentials, jobs, mqtt


class _NoThread:
    def __init__(self, *a, **kw): pass
    def start(self): pass


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setattr(config.Config, 'DATABASE', str(tmp_path / 't.db'))
    monkeypatch.setattr(app_module.threading, 'Thread', _NoThread)
    app = app_module.create_app()
    with app.app_context():
        db = database.get_db()
        db.execute("INSERT OR IGNORE INTO Settings (id) VALUES (1)")
        db.execute("INSERT INTO Rider (id, name, isDefault) VALUES (1, 'Tom', 1)")
        db.commit()
    return app


@pytest.fixture
def pushes(monkeypatch):
    done = []
    monkeypatch.setattr(mqtt, 'broker', lambda: ('broker', 1883, None, None))
    monkeypatch.setattr(mqtt, 'push_update', lambda *a, **k: done.append('all'))
    monkeypatch.setattr(mqtt, 'push_update_nutrition', lambda *a, **k: done.append('nutrition'))
    return done


def queued(app):
    with app.app_context():
        return [r[0] for r in database.get_db().execute("SELECT kind FROM Job WHERE state='queued' ORDER BY id")]


def test_nothing_is_queued_without_a_broker(app, monkeypatch):
    monkeypatch.setattr(mqtt, 'broker', lambda: None)
    with app.app_context():
        mqtt.push_later()
    assert queued(app) == []


def test_queued_once_and_the_worker_runs_it(app, pushes):
    with app.app_context():
        mqtt.push_later()
        mqtt.push_later()                               # one waiting will see this change too
        mqtt.push_later(nutrition_only=True)            # and the full one covers the nutrition sensors
    assert queued(app) == [mqtt.PUSH_JOB]
    assert pushes == []                                 # not while the page waits
    assert jobs.run_queued(app) == 1
    assert pushes == ['all']


def test_a_nutrition_push_alone_runs_only_the_nutrition_sensors(app, pushes):
    with app.app_context():
        mqtt.push_later(nutrition_only=True)
        mqtt.push_later(nutrition_only=True)
    assert queued(app) == [mqtt.PUSH_NUTRITION_JOB]
    jobs.run_queued(app)
    assert pushes == ['nutrition']


def test_one_already_running_does_not_stop_another_being_queued(app, pushes):
    with app.app_context():
        mqtt.push_later()
        db = database.get_db()
        db.execute("UPDATE Job SET state='running'")    # it may have worked out its values before this change
        db.commit()
        mqtt.push_later()
    assert queued(app) == [mqtt.PUSH_JOB]


def test_saving_settings_does_not_wait_for_the_push(app, pushes):
    with app.app_context():
        av = credentials.auth_version()
    c = app.test_client()
    with c.session_transaction() as s:
        s['logged_in'] = True
        s['av'] = av
    r = c.post('/settings/features', data={'on': []})
    assert r.status_code == 302
    assert pushes == [] and queued(app) == [mqtt.PUSH_JOB]
