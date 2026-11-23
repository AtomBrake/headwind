"""This week and this month (services/periods.py): the past 7 and 28 days, or calendar weeks from the rider's chosen day and calendar months,
the same on the dashboard, in /api/v1, the run stats and the Home Assistant sensors. Throwaway databases."""
import sqlite3
from datetime import date

import pytest

import database
from services import periods, tz
from services.periods import CALENDAR, ROLLING, Prefs

MON = date(2026, 11, 16)          # a Monday
FIRST = date(2026, 11, 1)         # a Sunday, and the 1st


# ── The helper on its own ──────────────────────────────────────

def test_rolling_on_a_monday_the_week_is_last_tuesday_to_today():
    w = periods.current('week', Prefs(ROLLING, 0), MON)
    assert (w.first, w.last, w.days, w.label, w.dates) == (date(2026, 11, 10), MON, 7, 'Past 7 days', '10–16 Nov')


def test_rolling_on_the_1st_the_month_takes_in_last_months_days():
    m = periods.current('month', Prefs(ROLLING, 0), FIRST)
    assert (m.first, m.last, m.days, m.label) == (date(2026, 10, 5), FIRST, 28, 'Past 28 days')
    assert periods.current('year', Prefs(ROLLING, 0), FIRST).first == date(2026, 1, 1)          # the year stays the calendar year


def test_calendar_weeks_and_months():
    w = periods.current('week', Prefs(CALENDAR, 0), MON)
    assert (w.first, w.last, w.label) == (MON, date(2026, 11, 22), 'This week')
    m = periods.current('month', Prefs(CALENDAR, 0), FIRST)
    assert (m.first, m.last, m.label) == (FIRST, date(2026, 11, 30), 'November')
    assert periods.current('month', Prefs(CALENDAR, 0), date(2026, 12, 31)).last == date(2026, 12, 31)


def test_calendar_with_a_sunday_start_gives_sunday_to_saturday_blocks():
    p = Prefs(CALENDAR, 6)
    blocks = periods.blocks('week', 4, p, MON)                              # Monday the 16th is in the week from Sunday the 15th
    assert [(b.first, b.last) for b in blocks] == [(date(2026, 10, 25), date(2026, 10, 31)), (date(2026, 11, 1), date(2026, 11, 7)),
                                                   (date(2026, 11, 8), date(2026, 11, 14)), (date(2026, 11, 15), date(2026, 11, 21))]
    assert [b.label for b in blocks] == ['25 Oct', '1 Nov', '8 Nov', 'This week']
    assert periods.find(blocks, date(2026, 11, 7)) == 1 and periods.find(blocks, date(2026, 10, 24)) is None
    assert periods.week_first(date(2026, 11, 15), 6) == date(2026, 11, 15) and periods.week_first(date(2026, 11, 14), 6) == date(2026, 11, 8)


def test_rolling_blocks_are_back_to_back_and_end_today():
    blocks = periods.blocks('week', 12, Prefs(ROLLING, 3), MON)               # the start day plays no part in rolling weeks
    assert blocks[-1].last == MON and blocks[0].first == date(2026, 8, 25)
    assert all((b.first - a.last).days == 1 and b.days == 7 for a, b in zip(blocks, blocks[1:]))
    months = periods.blocks('month', 3, Prefs(ROLLING, 0), MON)
    assert [(b.first, b.last) for b in months][0] == (date(2026, 8, 25), date(2026, 9, 21)) and months[-1].dates == '20 Oct–16 Nov'


def test_day_ranges_across_months_and_years():
    assert periods.day_range(date(2026, 10, 28), date(2026, 11, 3)) == '28 Oct–3 Nov'
    assert periods.day_range(date(2025, 12, 29), date(2026, 1, 4)) == '29 Dec 2025–4 Jan 2026'


# ── The setting ────────────────────────────────────────────────

@pytest.fixture
def db(tmp_path):
    from flask import Flask
    app = Flask(__name__)
    app.config['DATABASE'] = str(tmp_path / 'p.db')
    app.teardown_appcontext(database.close_db)
    with app.app_context():
        database.migrate_db()
        yield database.get_db()


def test_a_new_install_counts_the_past_7_and_28_days(db):
    assert periods.prefs(1, db) == Prefs(ROLLING, 0)


def test_an_install_from_before_keeps_calendar_weeks_from_monday(db):
    db.execute("INSERT INTO Rider (id, name, isDefault) VALUES (1, 'Tom', 1)")
    db.execute('UPDATE Settings SET periodMode=NULL, weekStart=NULL WHERE id=1')
    db.execute('PRAGMA user_version = 12')                                  # as an install that hasn't had step 13
    db.commit()
    database.migrate_db()
    assert periods.prefs(1, db) == Prefs(CALENDAR, 0) and periods.prefs(2, db) == Prefs(CALENDAR, 0)    # a rider added later too


def test_a_riders_own_choice_wins_over_the_instances(db):
    db.execute("INSERT INTO Rider (id, name, isDefault) VALUES (1, 'Tom', 1)")
    db.execute("INSERT INTO Rider (id, name, isDefault) VALUES (2, 'Sam', 0)")
    db.execute("UPDATE Settings SET periodMode='calendar', weekStart=0 WHERE id=1")
    periods.save(db, 2, ROLLING, 6)
    db.commit()
    assert periods.prefs(1, db) == Prefs(CALENDAR, 0) and periods.prefs(2, db) == Prefs(ROLLING, 6)
    periods.save(db, 2, 'nonsense', 9)                                      # anything else: the defaults
    assert periods.prefs(2, db) == Prefs(ROLLING, 0)


def test_prefs_before_step_13_are_the_defaults(tmp_path):
    old = sqlite3.connect(tmp_path / 'old.db')
    old.execute('CREATE TABLE Settings (id INTEGER PRIMARY KEY)')
    assert periods.prefs(1, old) == periods.DEFAULT


# ── The pages, the API and the sensors agree ───────────────────

class _NoThread:
    def __init__(self, *a, **kw): pass
    def start(self): pass


@pytest.fixture
def phone(tmp_path, monkeypatch):
    import app as app_module
    import config
    from services import credentials
    monkeypatch.setattr(config.Config, 'DATABASE', str(tmp_path / 'app.db'))
    monkeypatch.setattr(config.Config, 'APP_URL', 'https://h.example')
    monkeypatch.setattr(app_module.threading, 'Thread', _NoThread)
    monkeypatch.setattr('services.weather.fetch_weather', lambda *a, **k: None)
    monkeypatch.setattr(tz, 'today', lambda: MON)
    app = app_module.create_app()
    with app.app_context():
        d = database.get_db()
        d.execute("INSERT OR IGNORE INTO Settings (id) VALUES (1)")
        d.execute("INSERT INTO Rider (id, name, isDefault) VALUES (1, 'Tom', 1)")
        for aid, sport, day, dist in (('r-old', 'Ride', '2026-11-09', 50000),     # last Monday: 7 days back
                                      ('r-tue', 'Ride', '2026-11-10', 20000),     # last Tuesday: 6 days back
                                      ('r-sun', 'Ride', '2026-11-15', 30000),     # yesterday, a Sunday
                                      ('r-mon', 'Ride', '2026-11-16', 10000),     # today
                                      ('r-oct', 'Ride', '2026-10-20', 40000),     # 27 days back: in the past 28, not in November
                                      ('run-sat', 'Run', '2026-11-14', 8000),
                                      ('run-mon', 'Run', '2026-11-16', 5000)):
            d.execute("INSERT INTO Activity (id, riderId, type, sportType, name, startDate, startDateLocal, distance, movingTime, elapsedTime, "
                      "totalElevationGain, calories, rawData) VALUES (?,1,?,?,?,?,?,?,1800,1800,10,100,'{}')",
                      [aid, sport, sport, aid, f'{day}T08:00:00Z', f'{day}T08:00:00', dist])
        d.commit()
        av = credentials.auth_version()
    web = app.test_client()
    with web.session_transaction() as s:
        s['logged_in'] = True
        s['av'] = av
    token = web.post('/phones/create', json={'name': 'iPhone', 'server_url': 'https://h.example'}).get_json()['token']
    c = app.test_client()
    c.app_, c.web, c.H = app, web, {'Authorization': 'Bearer ' + token}
    return c


def _choose(phone, mode, week_start):
    r = phone.web.post('/settings/', data={'periodsShown': '1', 'periodMode': mode, 'weekStart': str(week_start)})
    assert r.status_code == 302


def _everything(phone):
    """(dashboard's last weekly bar, API overview, the sensors' week figures, the run stats) for rider 1."""
    from tests.page_data import page_data
    html = phone.web.get('/dashboard').get_data(as_text=True)
    bar = page_data(html, 'dashboardData')['weekly'][-1]
    o = phone.get('/api/v1/overview', headers=phone.H).get_json()
    with phone.app_.app_context():
        from services import mqtt, run_stats
        sensors = mqtt._state_values(mqtt._gather_stats(1))
        runs = run_stats.payloads(1)['nutrition_run_stats']
    return bar, o, sensors, runs


@pytest.mark.parametrize('mode, week_start, week, month, ride_week_m, run_week_m, ride_month_m', [
    (ROLLING, 0, ('2026-11-10', '2026-11-16'), ('2026-10-20', '2026-11-16'), 60000, 13000, 150000),
    (CALENDAR, 0, ('2026-11-16', '2026-11-22'), ('2026-11-01', '2026-11-30'), 10000, 5000, 110000),
    (CALENDAR, 6, ('2026-11-15', '2026-11-21'), ('2026-11-01', '2026-11-30'), 40000, 5000, 110000),
])
def test_the_dashboard_api_and_sensors_give_the_same_numbers(phone, mode, week_start, week, month, ride_week_m, run_week_m, ride_month_m):
    _choose(phone, mode, week_start)
    bar, o, sensors, runs = _everything(phone)
    assert (bar['from'], bar['to']) == week and bar['by']['ride']['dist_m'] == ride_week_m and bar['by']['foot']['dist_m'] == run_week_m
    assert (o['periods']['week']['from'], o['periods']['week']['to']) == week
    assert (o['periods']['month']['from'], o['periods']['month']['to']) == month
    assert o['week']['distance_m'] == ride_week_m and o['month']['distance_m'] == ride_month_m
    groups = {g['key']: g['totals'] for g in o['groups']}
    assert groups['ride']['week']['distance_m'] == ride_week_m and groups['foot']['week']['distance_m'] == run_week_m
    assert o['weekly'][-1]['distance_m'] == ride_week_m and (o['weekly'][-1]['from'], o['weekly'][-1]['to']) == week
    assert sensors['week_ride_distance_mi'] == str(round(ride_week_m / 1609.344, 1))
    assert sensors['week_foot_distance_mi'] == str(round(run_week_m / 1609.344, 1))
    assert runs['week']['m'] == run_week_m and (runs['periods']['week']['from'], runs['periods']['week']['to']) == week
    assert o['periods']['week']['label'] == ('Past 7 days' if mode == ROLLING else 'This week')
    assert o['periods']['month']['label'] == ('Past 28 days' if mode == ROLLING else 'November')
    assert o['periods']['year']['from'] == '2026-01-01'


def test_the_sensor_names_follow_the_setting_and_their_ids_dont(phone):
    from services import mqtt
    with phone.app_.app_context():
        names = {uid: name for uid, name, _, _ in mqtt._named(mqtt.SENSORS + mqtt.NUTRITION_SENSORS, 1)}
    assert names['week_activities'] == 'Activities Past 7 Days' and names['nutrition_alcohol_week'] == 'Nutrition Alcohol Past 7 Days'
    _choose(phone, CALENDAR, 0)
    with phone.app_.app_context():
        named = mqtt._named(mqtt.SENSORS, 1)
    assert dict((u, n) for u, n, _, _ in named)['week_activities'] == 'Activities This Week'
    assert [u for u, _, _, _ in named] == [u for u, _, _, _ in mqtt.SENSORS]


def test_settings_shows_and_saves_the_choice(phone):
    html = phone.web.get('/settings/').get_data(as_text=True)
    assert 'Count this week and this month as' in html and 'value="rolling" checked' in html
    _choose(phone, CALENDAR, 6)
    html = phone.web.get('/settings/').get_data(as_text=True)
    assert 'value="calendar" checked' in html and '<option value="6" selected>Sunday</option>' in html


def test_the_nutrition_week_follows_the_chosen_start_day(phone):
    j = phone.web.get('/nutrition/api/week/2026-11-18').get_json()             # a Wednesday
    assert j['week_start'] == '2026-11-16' and [d['date'] for d in j['days']][-1] == '2026-11-22'
    _choose(phone, ROLLING, 6)                                                 # a diary is calendar by nature: rolling still uses the start day
    j = phone.web.get('/nutrition/api/week/2026-11-18').get_json()
    assert j['week_start'] == '2026-11-15' and j['days'][0]['dow'] == 'Sun'
    j = phone.web.get('/nutrition/api/week/2026-11-15').get_json()             # a Sunday is the first day, not the last
    assert j['week_start'] == '2026-11-15'
