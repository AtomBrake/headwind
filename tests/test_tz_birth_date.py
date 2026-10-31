"""The home time zone (a setting, else the server's) and the date of birth that replaced the age. Throwaway DB."""
import json
from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest
from flask import Flask

import database
from services import goal_model, tz

FAR_EAST, FAR_WEST = 'Pacific/Kiritimati', 'Pacific/Pago_Pago'      # UTC+14 and UTC-11: never on the same date


def _app(tmp_path):
    app = Flask(__name__)
    app.config['DATABASE'] = str(tmp_path / 't.db')
    app.secret_key = 'test'
    app.teardown_appcontext(database.close_db)
    from routes.nutrition import bp as nutrition_bp
    from routes.settings import bp as settings_bp
    app.register_blueprint(nutrition_bp)
    app.register_blueprint(settings_bp, url_prefix='/settings')
    with app.app_context():
        database.migrate_db()
        d = database.get_db()
        d.execute("INSERT INTO Rider (id, name, isDefault) VALUES (1, 'Rob', 1)")
        d.execute("INSERT OR IGNORE INTO Settings (id) VALUES (1)")
        d.commit()
    return app


@pytest.fixture
def app(tmp_path):
    return _app(tmp_path)


def _set_zone(app, name):
    with app.app_context():
        database.get_db().execute('UPDATE Settings SET timeZone=? WHERE id=1', [name]); database.get_db().commit()
    tz.forget()


# ---------- time zone ----------
def test_a_new_install_uses_the_servers_zone(app, monkeypatch):
    monkeypatch.setenv('TZ', 'America/New_York')
    with app.app_context():
        assert database.get_db().execute('SELECT timeZone FROM Settings').fetchone()[0] is None
        assert tz.name() == 'America/New_York'


def test_the_setting_decides_today(app):
    for z in (FAR_EAST, FAR_WEST):
        _set_zone(app, z)
        with app.app_context():
            assert tz.today() == datetime.now(ZoneInfo(z)).date()
            assert goal_model._today() == tz.today()


def test_an_install_from_before_the_setting_keeps_london(tmp_path):
    app = _app(tmp_path)
    with app.app_context():
        d = database.get_db()
        for col in ('timeZone', 'birthDate', 'birthDateGuessed'):
            d.execute(f'ALTER TABLE Settings DROP COLUMN {col}')
        d.execute('UPDATE Settings SET birthYear=1985 WHERE id=1'); d.commit()
        database.migrate_db()
        row = d.execute('SELECT timeZone, birthDate, birthDateGuessed FROM Settings WHERE id=1').fetchone()
        assert tuple(row) == ('Europe/London', '1985-01-01', 1)


def test_settings_saves_a_zone_and_ignores_a_made_up_one(app):
    c = app.test_client()
    c.post('/settings/', data={'units': 'metric', 'timeZone': 'Asia/Tokyo'})
    with app.app_context():
        assert tz.name() == 'Asia/Tokyo'
    c.post('/settings/', data={'units': 'metric', 'timeZone': '../../etc/passwd'})
    with app.app_context():
        assert database.get_db().execute('SELECT timeZone FROM Settings').fetchone()[0] is None
    c.post('/settings/', data={'units': 'metric', 'timeZone': 'Asia/Tokyo'})
    c.post('/settings/', data={'aiProvider': 'ollama'})                     # another card's form leaves the zone alone
    with app.app_context():
        assert tz.name() == 'Asia/Tokyo'


def test_mqtt_water_lands_on_the_home_zones_day(app):
    from services.mqtt_commands import _apply_water
    for i, z in enumerate((FAR_EAST, FAR_WEST)):
        _set_zone(app, z)
        _apply_water(app, json.dumps({'ml': 250, 'id': f'press-{i}'}))
        with app.app_context():
            day = database.get_db().execute('SELECT logDate FROM HydrationLog ORDER BY id DESC LIMIT 1').fetchone()[0]
        assert day == datetime.now(ZoneInfo(z)).date().isoformat()


# ---------- date of birth ----------
@pytest.mark.parametrize('born, on, age', [
    (date(1985, 6, 15), date(2026, 6, 14), 40),
    (date(1985, 6, 15), date(2026, 6, 15), 41),         # goes up on the birthday itself
    (date(1985, 6, 15), date(2026, 12, 31), 41),
    (date(2000, 2, 29), date(2026, 2, 28), 25),
    (date(2000, 2, 29), date(2026, 3, 1), 26),
])
def test_age_on(born, on, age):
    assert goal_model.age_on(born, on) == age


def _profile(c, **body):
    r = c.post('/nutrition/api/goal-profile', json=body)
    return r.status_code, r.get_json()


def test_a_date_of_birth_sets_the_age(app):
    c = app.test_client()
    today = datetime.now(tz.zone()).date()
    born = date(today.year - 40, today.month, today.day).isoformat() if (today.month, today.day) != (2, 29) else f'{today.year - 40}-03-01'
    code, d = _profile(c, birth_date=born)
    assert code == 200 and d['profile']['birth_date'] == born and not d['profile']['birth_date_guessed']
    assert d['profile']['age'] == (40 if (today.month, today.day) != (2, 29) else 39)
    with app.app_context():
        assert database.get_db().execute('SELECT birthYear FROM Settings').fetchone()[0] == today.year - 40     # kept for older readers


def test_a_bad_date_of_birth_is_refused(app):
    c = app.test_client()
    for bad in ('1985-02-30', 'yesterday', f'{date.today().year - 5}-01-01', '1900-01-01'):
        code, d = _profile(c, birth_date=bad)
        assert code == 400 and 'date of birth' in d['error']


def test_an_age_alone_is_a_guess_until_the_date_is_given(app):
    c = app.test_client()
    code, d = _profile(c, age='40')                                            # an older client
    assert code == 200 and d['profile']['age'] == 40 and d['profile']['birth_date_guessed']
    code, d = _profile(c, sex='male')                                          # the form saved again with the date left blank
    assert d['profile']['birth_date_guessed'] and d['profile']['age'] == 40
    code, d = _profile(c, birth_date='1985-06-15')
    assert not d['profile']['birth_date_guessed'] and d['profile']['birth_date'] == '1985-06-15'
