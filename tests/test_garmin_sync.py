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
    """An activity as Garmin's list gives it: startTimeGMT is the UTC time of the UK local start (equal to it in winter only)."""
    from datetime import datetime, timezone
    from zoneinfo import ZoneInfo
    gmt = datetime.fromisoformat(local).replace(tzinfo=ZoneInfo('Europe/London')).astimezone(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
    return {'activityId': aid, 'activityType': {'typeKey': 'cycling'}, 'startTimeLocal': local,
            'startTimeGMT': gmt, 'distance': dist, 'activityName': f'ride {aid}'}


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
            monkeypatch.setattr(garmin, '_client', lambda: FakeAPI(acts, fail))
            return list(garmin.sync_garmin_activities(1))
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
    assert _ids(db) == ['garmin_1']                 # not before its next try (services/garmin_failures)
    db.execute("UPDATE GarminFailure SET nextAt='2000-01-01T00:00:00+00:00'")      # 25 minutes later
    db.commit()
    run([_act(2, '2026-10-02 09:00:00'), _act(1, '2026-10-01 08:00:00')])
    assert _ids(db) == ['garmin_1', 'garmin_2']
    assert db.execute('SELECT COUNT(*) FROM GarminFailure').fetchone()[0] == 0


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


def test_ride_abroad_lands_on_its_strava_copy(env):
    """Garmin's local time is where the ride was (Vancouver), the Strava copy's is the home zone's (London): matched on the UTC instant."""
    db, run = env
    db.execute("INSERT INTO Activity (id,name,type,sportType,startDate,startDateLocal,distance,movingTime,elapsedTime,"
               "totalElevationGain,averageSpeed,maxSpeed,riderId,createdAt,updatedAt) VALUES "
               "('555','a','Ride','Ride','2026-07-26T22:00:00','2026-07-26T23:00:00',10050,1700,1750,0,0,0,1,'n','n')")
    db.commit()
    run([dict(_act(1, '2026-07-26 15:00:00'), startTimeGMT='2026-07-26 22:00:00')])
    assert _ids(db) == ['garmin_1']
    assert tuple(db.execute("SELECT primaryId, status FROM ActivityDuplicate WHERE id='555'").fetchone()) == ('garmin_1', 'parked')


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
        monkeypatch.setattr(garmin, '_client', lambda: FakeWeighAPI(summaries, fail))
        garmin.sync_garmin(days=3)
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


def test_weigh_in_keeps_garmins_source_type_and_refreshes_it_on_an_unchanged_weight(wenv):
    db, run = wenv
    typed = _day('2026-10-15', (81000, 1))
    typed['allWeightMetrics'][0]['sourceType'] = 'MANUAL'
    run([typed, _day('2026-10-16', (80500, 1))])
    detail = lambda: dict(db.execute('SELECT logDate, sourceDetail FROM WeightLog').fetchall())
    assert detail() == {'2026-10-15': 'MANUAL', '2026-10-16': None}
    scale = _day('2026-10-16', (80500, 1))
    scale['allWeightMetrics'][0]['sourceType'] = 'INDEX_SCALE'
    run([scale])                                     # same weight, so only the source tells it apart
    assert detail()['2026-10-16'] == 'INDEX_SCALE'


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
        monkeypatch.setattr(garmin, '_client', lambda: api)
        return garmin.backfill_history(today=TODAY, pause=0)

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


class WeighInsFailOnce(FakeHistoryAPI):
    """Answers steps, but the first weigh-in request fails (not a rate limit)."""
    def __init__(self, **kw):
        super().__init__(**kw)
        self.failed = False

    def get_weigh_ins(self, start, end):
        if not self.failed:
            self.failed = True
            raise ValueError('weight service hiccup')
        return super().get_weigh_ins(start, end)


def test_history_does_not_move_past_a_stretch_whose_weigh_ins_failed(henv):
    db, run, state, days = henv
    api = WeighInsFailOnce(active={'2026-09-20'}, weights={'2026-09-25': 81000})
    msg = run(api, garmin.history_from('91', today=TODAY))
    assert 'weigh-ins' in msg and state()['done'] == 0 and state()['c'] is None       # still at the start: this stretch is asked again
    db.execute('UPDATE Settings SET garminHistoryRetryAt=NULL'); db.commit()
    run(api)
    assert db.execute("SELECT weightKg FROM WeightLog WHERE logDate='2026-09-25'").fetchone()[0] == 81.0 and state()['done'] == 1


class YearlyWeighAPI:
    def __init__(self, weights, down=False):
        self.weights, self.down, self.calls = weights, down, []

    def get_weigh_ins(self, start, end):
        if self.down:
            raise ConnectionError('no route to host')
        self.calls.append((start, end))
        return {'dailyWeightSummaries': [_day(d, (g, 1)) for d, g in self.weights.items() if start <= d <= end]}


@pytest.fixture
def wbenv(henv, monkeypatch):
    db, _, _, _ = henv

    def run(api, frm):
        db.execute('UPDATE Settings SET garminHistoryFrom=?, garminWeightsDone=0, garminWeightsRetryAt=NULL WHERE id=1', [frm]); db.commit()
        monkeypatch.setattr(garmin, '_client', lambda: api)
        return garmin.backfill_weigh_ins(today=TODAY)

    def weights():
        return dict(db.execute('SELECT logDate, weightKg FROM WeightLog ORDER BY logDate').fetchall())
    yield db, run, weights


def test_weight_history_comes_a_year_at_a_time_back_to_the_last_weigh_in(wbenv):
    db, run, weights = wbenv
    api = YearlyWeighAPI({'2026-10-01': 80000, '2024-05-01': 84000, '2019-02-01': 90000})
    msg = run(api, 'all')
    # 2019 is behind three empty years (2021-2023), so 'all' has stopped by then
    assert weights() == {'2024-05-01': 84.0, '2026-10-01': 80.0}
    assert len(api.calls) == 6 and all((date.fromisoformat(e) - date.fromisoformat(s)).days == 364 for s, e in api.calls)
    assert '2 days with a weigh-in' in msg
    assert db.execute('SELECT garminWeightsDone FROM Settings').fetchone()[0] == 1
    assert run(api, 'all') is not None and garmin.backfill_weigh_ins(today=TODAY) is None   # done: nothing more to do


def test_weight_history_keeps_to_the_chosen_range_and_manual_entries(wbenv):
    db, run, weights = wbenv
    db.execute("INSERT INTO WeightLog (riderId, logDate, weightKg, source) VALUES (1, '2026-10-01', 79.5, 'manual')"); db.commit()
    run(YearlyWeighAPI({'2026-10-01': 80000, '2026-03-01': 82000, '2025-01-01': 85000}), garmin.history_from('365', today=TODAY))
    assert weights() == {'2026-03-01': 82.0, '2026-10-01': 79.5}          # 2025-01-01 is outside the year; the typed-in weight stays


def test_weight_history_retries_after_an_outage(wbenv):
    db, run, weights = wbenv
    msg = run(YearlyWeighAPI({}, down=True), 'all')
    s = db.execute('SELECT garminWeightsDone, garminWeightsRetryAt, garminWeightsStatus FROM Settings').fetchone()
    assert 'could not reach Garmin' in msg and s[0] == 0 and s[1] and s[2] == msg


# ── Late uploads, and how many days the regular sync reads ───────

def test_a_ride_that_reaches_garmin_late_still_comes_in(env):
    """The bike computer uploaded Saturday's ride and moved the cursor on; the watch's Friday run arrives on Monday."""
    db, run = env
    run([_act(2, '2026-10-17 09:00:00'), _act(1, '2026-10-10 08:00:00')])
    run([_act(2, '2026-10-17 09:00:00'), _act(3, '2026-10-16 18:00:00'), _act(1, '2026-10-10 08:00:00')])
    assert _ids(db) == ['garmin_1', 'garmin_2', 'garmin_3']


def test_a_first_page_that_reaches_past_the_cursor_is_the_last(env, monkeypatch):
    db, run = env
    run([_act(2, '2026-10-17 09:00:00')])
    pages = []
    acts = [_act(100 + i, f'2026-10-{17 - i // 10:02d} 09:00:00') for i in range(150)]     # 150 activities over two pages
    api = FakeAPI(acts)
    real = api.get_activities
    api.get_activities = lambda start=0, limit=100: pages.append(start) or real(start, limit)
    monkeypatch.setattr(garmin, '_client', lambda: api)
    list(garmin.sync_garmin_activities(1))
    assert pages == [0]


NOW = '2026-10-19T12:00:00+00:00'


def _days(prev, new, sweep='2026-10-19T06:00:00+00:00'):
    from datetime import datetime
    return garmin.health_days(prev, new, sweep, now=datetime.fromisoformat(NOW))


def test_no_upload_since_the_last_sync_reads_no_day():
    assert _days('2026-10-19T11:00:00+00:00', '2026-10-19T11:00:00+00:00') == (0, False)


def test_an_upload_reads_the_days_since_the_one_before():
    assert _days('2026-10-19T09:00:00+00:00', '2026-10-19T11:30:00+00:00') == (2, False)       # today and yesterday at least
    assert _days('2026-10-14T20:00:00+00:00', '2026-10-19T11:30:00+00:00') == (7, False)       # the watch was off for five days
    assert _days('2026-08-01T20:00:00+00:00', '2026-10-19T11:30:00+00:00') == (garmin.HISTORY_RECENT, False)


def test_unknown_uploads_read_a_little_or_everything():
    assert _days('2026-10-19T09:00:00+00:00', None) == (2, False)
    assert _days(None, '2026-10-19T11:30:00+00:00') == (garmin.HISTORY_RECENT, False)


def test_once_a_day_every_recent_day_is_read():
    assert _days('2026-10-19T11:00:00+00:00', '2026-10-19T11:00:00+00:00', sweep='2026-10-18T11:00:00+00:00') == (garmin.HISTORY_RECENT, True)
    assert _days('2026-10-19T11:00:00+00:00', '2026-10-19T11:00:00+00:00', sweep=None) == (garmin.HISTORY_RECENT, True)


def test_strict_sync_calls_an_outage_an_outage(wenv):
    """The regular sync records the watch's upload as read: a sync where no daily-metric call answered must fail, or those days are lost."""
    api = FakeWeighAPI({})                                  # every daily-metric call fails
    with pytest.raises(RuntimeError):
        garmin.sync_garmin(days=2, api=api, strict=True)
    assert garmin.sync_garmin(days=0, api=api, strict=True) == 0     # nothing to read is not an outage


# ── Activities that keep failing (services/garmin_failures) ─────

class CountingAPI(FakeAPI):
    """FakeAPI that counts downloads and can hand back a zip of any files."""
    def __init__(self, acts, fail=(), files=None):
        super().__init__(acts, fail)
        self.downloads, self.files = [], files

    def download_activity(self, aid, dl_fmt=None):
        self.downloads.append(str(aid))
        if self.files is None:
            return super().download_activity(aid, dl_fmt)
        b = io.BytesIO()
        with zipfile.ZipFile(b, 'w') as z:
            for name, data in self.files.items():
                z.writestr(name, data)
        return b.getvalue()


@pytest.fixture
def fenv(env, monkeypatch):
    db, _ = env

    def run(api):
        monkeypatch.setattr(garmin, '_client', lambda: api)
        return list(garmin.sync_garmin_activities(1))

    def later():
        db.execute("UPDATE GarminFailure SET nextAt='2000-01-01T00:00:00+00:00' WHERE gaveUp=0")     # its next try is due
        db.commit()
    yield db, run, later


def _cursor(db):
    return db.execute('SELECT garminActivitySyncDate FROM Settings WHERE id=1').fetchone()[0]


def test_an_unreadable_file_is_given_up_on_and_stops_holding_the_cursor(fenv, monkeypatch):
    db, run, later = fenv
    monkeypatch.setattr('services.parser.parse_fit', lambda b: None)
    acts = [_act(2, '2026-10-10 09:00:00')]
    api = CountingAPI(acts)
    run(api)
    assert _cursor(db) == '2026-10-09'               # still being tried: the cursor waits for it
    later()
    run(api)
    assert api.downloads == ['2', '2']
    assert _cursor(db) == '2026-10-10'               # given up on: the cursor moves on
    later()
    run(api)
    assert api.downloads == ['2', '2']               # and it is never downloaded again
    from services import garmin_failures
    assert [r['activityId'] for r in garmin_failures.given_up(db)] == ['2']


def test_a_download_that_keeps_failing_is_tried_five_times(fenv):
    db, run, later = fenv
    api = CountingAPI([_act(2, '2026-10-10 09:00:00')], fail={'2'})
    for _ in range(7):
        run(api)
        later()
    assert len(api.downloads) == 5
    assert _cursor(db) == '2026-10-10'


def test_a_newer_headwind_tries_a_given_up_activity_once_more(fenv, monkeypatch):
    from services import garmin_failures
    db, run, later = fenv
    monkeypatch.setattr('services.parser.parse_fit', lambda b: None)
    api = CountingAPI([_act(2, '2026-10-10 09:00:00')])
    run(api); later(); run(api)
    assert len(api.downloads) == 2
    monkeypatch.setattr(garmin_failures, '_version', lambda: '9.9.9')
    monkeypatch.setattr('services.parser.parse_fit', lambda b: {'distance': 10000, 'movingTime': 1800, 'elapsedTime': 1800, 'streams': None})
    run(api)
    assert _ids(db) == ['garmin_2']
    assert garmin_failures.given_up(db) == []


def test_a_given_up_activity_past_the_first_page_is_reached_again_after_an_update(fenv, monkeypatch):
    from services import garmin_failures
    db, run, later = fenv
    db.execute('INSERT OR IGNORE INTO Settings (id) VALUES (1)')
    db.execute("UPDATE Settings SET garminActivitySyncDate='2026-10-15'")
    db.execute("INSERT INTO GarminFailure (activityId, startDate, kind, tries, gaveUp, version) VALUES ('7', '2026-09-01', 'parse', 2, 1, 'old')")
    db.commit()
    assert garmin_failures.rewind(db, '2026-10-15') == '2026-08-31'


def test_try_again_forgets_them_and_moves_the_cursor_back(fenv, monkeypatch):
    from services import garmin_failures
    db, run, later = fenv
    monkeypatch.setattr('services.parser.parse_fit', lambda b: None)
    api = CountingAPI([_act(3, '2026-10-12 09:00:00'), _act(2, '2026-10-10 09:00:00')])
    run(api); later(); run(api)
    assert len(garmin_failures.given_up(db)) == 2
    assert garmin_failures.retry_all(db) == 2
    db.commit()
    assert _cursor(db) == '2026-10-09' and garmin_failures.given_up(db) == []


def test_a_manual_activity_comes_in_from_the_list_without_a_download(fenv):
    db, run, later = fenv
    a = {**_act(4, '2026-10-11 07:00:00'), 'manualActivity': True, 'duration': 3600, 'movingDuration': 3500, 'calories': 600}
    api = CountingAPI([a])
    run(api)
    assert api.downloads == []
    row = db.execute("SELECT distance, movingTime, elapsedTime, streams FROM Activity WHERE id='garmin_4'").fetchone()
    assert (row['distance'], row['movingTime'], row['elapsedTime'], row['streams']) == (10000, 3500, 3600, None)


def test_a_zip_with_no_file_comes_in_from_the_list(fenv):
    db, run, later = fenv
    api = CountingAPI([{**_act(5, '2026-10-11 07:00:00'), 'duration': 1800}], files={'readme.txt': b'x'})
    run(api)
    assert _ids(db) == ['garmin_5']
    assert db.execute('SELECT COUNT(*) FROM GarminFailure').fetchone()[0] == 0


def test_an_uploaded_gpx_is_read_with_its_track(fenv, monkeypatch):
    db, run, later = fenv
    seen = []
    monkeypatch.setattr('services.parser.parse_activity_file',
                        lambda name, data: seen.append(name) or {'distance': 5000, 'movingTime': 900, 'elapsedTime': 900, 'streams': '{"latlng": {"data": []}}'})
    api = CountingAPI([_act(6, '2026-10-11 07:00:00')], files={'6.gpx': b'<gpx/>'})
    run(api)
    assert seen == ['6.gpx'] and _ids(db) == ['garmin_6']


def test_the_tasks_page_lists_what_was_given_up_on(fenv):
    from services import garmin_failures, tasks
    db, run, later = fenv
    db.execute('INSERT OR IGNORE INTO Settings (id) VALUES (1)')
    db.execute("UPDATE Settings SET garminEmail='e', garminPassword='p'")
    garmin_failures.record(db, '8', 'parse', 'bad', '2026-10-03', 'Morning swim')
    garmin_failures.record(db, '8', 'parse', 'bad', '2026-10-03', 'Morning swim')
    db.commit()
    card = next(j for j in tasks.overview(db)['jobs'] if j['name'] == 'Garmin activities not imported')
    assert 'Morning swim (2026-10-03)' in card['detail'] and card['action']['url'] == '/tasks/run/garmin-retry'
