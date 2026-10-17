"""Garmin incremental sync: same-day rides, retry-after-failure, and time-aware duplicate detection.
Runs against a throwaway SQLite file with a fake Garmin client — no network, no real data."""
import io
import zipfile

import pytest
from flask import Flask

import database
from services import garmin


def _zip():
    b = io.BytesIO()
    with zipfile.ZipFile(b, 'w') as z:
        z.writestr('x_ACTIVITY.fit', b'fit')
    return b.getvalue()


class FakeAPI:
    class ActivityDownloadFormat:
        ORIGINAL = 'orig'

    def __init__(self, acts, fail=()):
        self.acts, self.fail = acts, set(fail)

    def get_activities(self, start=0, limit=100):
        return self.acts[start:start + limit]

    def download_activity(self, aid, dl_fmt=None):
        if str(aid) in self.fail:
            raise RuntimeError('boom')
        return _zip()


def _act(aid, local, dist=10000):
    return {'activityId': aid, 'activityType': {'typeKey': 'cycling'}, 'startTimeLocal': local,
            'startTimeGMT': local, 'distance': dist, 'activityName': f'ride {aid}'}


@pytest.fixture
def env(tmp_path, monkeypatch):
    app = Flask(__name__)
    app.config['DATABASE'] = str(tmp_path / 't.db')
    with app.app_context():
        database.migrate_db()
        db = database.get_db()
        db.execute("INSERT INTO Rider(name) VALUES ('r')")
        db.commit()
        monkeypatch.setattr('services.parser.parse_fit', lambda b: {
            'distance': 10000, 'movingTime': 1800, 'elapsedTime': 1800, 'streams': None})
        monkeypatch.setattr('services.weather.fetch_weather', lambda *a, **k: None)

        def run(acts, fail=()):
            monkeypatch.setattr(garmin, '_client', lambda e, p: FakeAPI(acts, fail))
            return list(garmin.sync_garmin_activities('e', 'p', 1))
        yield db, run


def _ids(db):
    return sorted(r[0] for r in db.execute('SELECT id FROM Activity'))


def test_second_commute_same_day_is_imported_later(env):
    db, run = env
    run([_act(1, '2026-10-01 08:00:00')])
    # evening ride, identical distance, same day, uploaded after the first sync
    run([_act(2, '2026-10-01 17:30:00'), _act(1, '2026-10-01 08:00:00')])
    assert _ids(db) == ['garmin_1', 'garmin_2']


def test_failed_download_is_retried_not_skipped_forever(env):
    db, run = env
    run([_act(2, '2026-10-02 09:00:00'), _act(1, '2026-10-01 08:00:00')], fail={'2'})
    assert _ids(db) == ['garmin_1']
    run([_act(2, '2026-10-02 09:00:00'), _act(1, '2026-10-01 08:00:00')])
    assert _ids(db) == ['garmin_1', 'garmin_2']


def test_same_ride_from_another_source_keeps_the_garmin_recording(env):
    """A phone/file copy of the ride already exists: the Garmin one (device + sensors) replaces it, the old copy is parked, not lost."""
    db, run = env
    db.execute("INSERT INTO Activity (id,name,type,sportType,startDate,startDateLocal,distance,movingTime,elapsedTime,"
               "totalElevationGain,averageSpeed,maxSpeed,riderId,createdAt,updatedAt) VALUES "
               "('fit_x','a','Ride','Ride','2026-10-01T08:01:00','2026-10-01T08:01:00',10050,1700,1750,0,0,0,1,'n','n')")
    db.commit()
    run([_act(1, '2026-10-01 08:00:00')])
    assert _ids(db) == ['garmin_1']
    parked = db.execute("SELECT id, primaryId, status FROM ActivityDuplicate").fetchall()
    assert [tuple(r) for r in parked] == [('fit_x', 'garmin_1', 'parked')]
    run([_act(1, '2026-10-01 08:00:00')])               # a later sync must not bring the parked copy back or duplicate anything
    assert _ids(db) == ['garmin_1']


# ── Weigh-ins → WeightLog ────────────────────────────────────────────────

class FakeWeighAPI:
    """Daily-metric calls all fail (sync_garmin tolerates that); only weigh-ins answer."""
    def __init__(self, summaries, fail=False):
        self.summaries, self.fail = summaries, fail

    def get_weigh_ins(self, start, end):
        if self.fail:
            raise RuntimeError('boom')
        return {'dailyWeightSummaries': self.summaries}

    def __getattr__(self, name):
        def _missing(*a, **k):
            raise RuntimeError(name)
        return _missing


def _day(d, *grams_at):
    """A dailyWeightSummaries entry; grams_at = (grams, timestampGMT) pairs, deliberately not in time order."""
    ms = [{'calendarDate': d, 'weight': g, 'timestampGMT': t} for g, t in grams_at]
    return {'summaryDate': d, 'allWeightMetrics': ms, 'latestWeight': ms[0] if ms else None}


@pytest.fixture
def wenv(env, monkeypatch):
    db, _ = env
    db.execute('UPDATE Rider SET isDefault=1')
    db.commit()

    def run(summaries, fail=False):
        monkeypatch.setattr(garmin, '_client', lambda e, p: FakeWeighAPI(summaries, fail))
        garmin.sync_garmin('e', 'p', days=3)
        return {r['logDate']: (r['weightKg'], r['source']) for r in db.execute('SELECT logDate, weightKg, source FROM WeightLog')}
    yield db, run


def test_weigh_ins_land_in_weightlog_in_kg_last_of_the_day(wenv):
    db, run = wenv
    rows = run([_day('2026-10-15', (81200, 1000), (80950, 2000)), _day('2026-10-16', (80700.0, 5))])
    assert rows == {'2026-10-15': (80.95, 'garmin'), '2026-10-16': (80.7, 'garmin')}


def test_weigh_in_never_overwrites_a_manual_or_other_scale_entry(wenv):
    db, run = wenv
    db.execute("INSERT INTO WeightLog (riderId, logDate, weightKg, source) VALUES (1, '2026-10-15', 82.0, 'manual')")
    db.execute("INSERT INTO WeightLog (riderId, logDate, weightKg, source) VALUES (1, '2026-10-16', 81.5, 'homeassistant')")
    db.commit()
    rows = run([_day('2026-10-15', (80000, 1)), _day('2026-10-16', (80000, 1))])
    assert rows == {'2026-10-15': (82.0, 'manual'), '2026-10-16': (81.5, 'homeassistant')}


def test_later_garmin_weigh_in_updates_its_own_row(wenv):
    db, run = wenv
    run([_day('2026-10-15', (81000, 1))])
    rows = run([_day('2026-10-15', (81000, 1), (80500, 9))])   # a second weigh-in later the same day
    assert rows == {'2026-10-15': (80.5, 'garmin')}
    assert db.execute('SELECT COUNT(*) FROM WeightLog').fetchone()[0] == 1


def test_bad_or_failed_weigh_ins_are_ignored(wenv):
    db, run = wenv
    assert run([_day('2026-10-15', (5000, 1)), _day('2026-10-16'), {'summaryDate': '2026-10-17'}]) == {}   # 5 kg, empty day, no data
    assert run([], fail=True) == {}   # the daily sync still completes
    assert garmin._parse_weigh_ins(None) == {}


# ── First-run health history backfill ────────────────────────────────────

from datetime import date, timedelta   # noqa: E402

TODAY = date(2026, 10, 17)


class GarminConnectTooManyRequestsError(Exception):
    pass


class FakeHistoryAPI:
    """Steps on `active` days (a resting HR too), weigh-ins on `weights` days. Counts per-day detail calls."""
    def __init__(self, active=(), weights=None, steps_unreadable=False, down=False, limit_before=None):
        self.active, self.weights = set(active), weights or {}
        self.steps_unreadable, self.down, self.limit_before = steps_unreadable, down, limit_before
        self.stats_calls = []

    def _check(self):
        if self.down:
            raise ConnectionError('no route to host')

    def get_daily_steps(self, start, end):
        self._check()
        if self.limit_before and start < self.limit_before:
            self.limit_before = None   # once
            raise GarminConnectTooManyRequestsError('429 Too Many Requests')
        if self.steps_unreadable:
            return {'unexpected': True}
        d, out = date.fromisoformat(start), []
        while d <= date.fromisoformat(end):
            out.append({'calendarDate': d.isoformat(), 'totalSteps': 5000 if d.isoformat() in self.active else None})
            d += timedelta(days=1)
        return out

    def get_weigh_ins(self, start, end):
        self._check()
        return {'dailyWeightSummaries': [_day(d, (g, 1)) for d, g in self.weights.items() if start <= d <= end]}

    def get_stats(self, d):
        self._check()
        self.stats_calls.append(d)
        return {'restingHeartRate': 50} if d in self.active else {}

    def __getattr__(self, name):
        def _none(*a, **k):
            self._check()
            return None
        return _none


@pytest.fixture
def henv(env, monkeypatch):
    db, _ = env
    db.execute('UPDATE Rider SET isDefault=1')
    db.execute('INSERT OR IGNORE INTO Settings (id) VALUES (1)')
    db.commit()

    def run(api, frm=None):
        if frm:
            db.execute('UPDATE Settings SET garminHistoryFrom=? WHERE id=1', [frm])
            db.commit()
        monkeypatch.setattr(garmin, '_client', lambda e, p: api)
        return garmin.backfill_history('e', 'p', today=TODAY, pause=0)

    def state():
        return dict(db.execute('SELECT garminHistoryFrom f, garminHistoryCursor c, garminHistoryDone done, garminHistoryRetryAt r FROM Settings').fetchone())

    def days():
        return sorted(r[0] for r in db.execute('SELECT date FROM GarminDaily'))
    yield db, run, state, days


def test_history_from_choices():
    assert garmin.history_from('all') == 'all'
    assert garmin.history_from('none') == 'none'
    assert garmin.history_from('365', today=TODAY) == '2025-10-17'
    assert garmin.history_from(7, today=TODAY) == 'none'   # inside what the regular sync covers anyway
    with pytest.raises(ValueError):
        garmin.history_from('lots')


def test_all_history_fetches_only_active_days_and_stops_after_a_quiet_year(henv):
    db, run, state, days = henv
    api = FakeHistoryAPI(active={'2026-09-20', '2026-01-10', '2024-03-01'}, weights={'2025-12-01': 82000})
    msg = run(api, 'all')
    # 2024-03-01 is behind ~22 empty months: 'all' has already stopped by then
    assert days() == ['2026-01-10', '2026-09-20']
    assert sorted(api.stats_calls) == ['2026-01-10', '2026-09-20']   # one steps request per window, details only for active days
    assert db.execute("SELECT logDate, weightKg, source FROM WeightLog").fetchall()[0][:] == ('2025-12-01', 82.0, 'garmin')
    st = state()
    assert st['done'] == 1 and st['c'] < '2025-02-01' and 'complete' in msg


def test_fixed_range_stops_at_its_start_date(henv):
    db, run, state, days = henv
    api = FakeHistoryAPI(active={'2026-09-20', '2026-06-01'})
    run(api, garmin.history_from('182', today=TODAY))   # 2026-04-18
    assert days() == ['2026-06-01', '2026-09-20']
    assert state()['done'] == 1 and state()['c'] == '2026-04-18'


def test_unreadable_step_list_falls_back_to_every_day(henv):
    db, run, state, days = henv
    api = FakeHistoryAPI(active={'2026-09-20'}, steps_unreadable=True)
    run(api, garmin.history_from('91', today=TODAY))
    assert days() == ['2026-09-20']                 # empty days are not stored
    assert len(api.stats_calls) == (date(2026, 10, 3) - date(2026, 7, 18)).days + 1


def test_rate_limit_keeps_its_place_and_resumes(henv):
    db, run, state, days = henv
    api = FakeHistoryAPI(active={'2026-09-20', '2026-06-01'}, limit_before='2026-07-01')
    msg = run(api, 'all')
    st = state()
    assert 'slow down' in msg and st['done'] == 0 and st['r'] and st['c'] > '2026-07-01'
    assert days() == ['2026-09-20']
    db.execute('UPDATE Settings SET garminHistoryRetryAt=NULL')
    run(api)
    assert days() == ['2026-06-01', '2026-09-20'] and state()['done'] == 1


def test_outage_is_not_mistaken_for_no_data(henv):
    db, run, state, days = henv
    msg = run(FakeHistoryAPI(down=True), 'all')
    st = state()
    assert 'did not answer' in msg and st['done'] == 0 and st['c'] is None and st['r']


def test_days_already_stored_are_not_fetched_again(henv):
    db, run, state, days = henv
    db.execute("INSERT INTO GarminDaily (date, steps) VALUES ('2026-09-20', 4000)")
    db.commit()
    api = FakeHistoryAPI(active={'2026-09-20'})
    run(api, garmin.history_from('91', today=TODAY))
    assert api.stats_calls == []


def test_none_just_marks_it_answered(henv):
    db, run, state, days = henv
    run(FakeHistoryAPI(down=True), 'none')
    assert state()['done'] == 1 and days() == []


def test_history_route_and_account_switch_reset(env, monkeypatch):
    from flask import current_app
    from routes.garmin import bp
    db, _ = env
    app = current_app._get_current_object()
    app.register_blueprint(bp)
    c = app.test_client()
    monkeypatch.setattr(garmin, 'start_login', lambda e, p: {'ok': True})
    garmin.HISTORY_WAKE.clear()
    assert c.post('/garmin/connect', json={'email': 'a@x', 'password': 'p'}).get_json() == {'ok': True}
    assert c.get('/garmin/history').get_json()['from'] is None            # not asked yet → the page asks
    r = c.post('/garmin/history', json={}).get_json()
    assert r['from'] == 'all' and not r['done'] and garmin.HISTORY_WAKE.is_set()   # default is all of it
    assert c.post('/garmin/history', json={'range': 'lots'}).status_code == 400
    c.post('/garmin/connect', json={'email': 'b@x', 'password': 'p'})
    assert c.get('/garmin/history').get_json()['from'] is None            # new account: ask again
