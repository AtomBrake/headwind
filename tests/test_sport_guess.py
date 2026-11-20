"""An upload whose file can't be trusted about its sport (Strava's TCX says Biking for a run, a GPX names none) but that moved like a run or a
walk: saved as the file says, and the rider asked (services/sport_guess.py). No network; the app on a throwaway database."""
import io
import json
import zipfile
from datetime import datetime, timedelta, timezone

import pytest

import database
from services import sport_guess
from services.parser import on_foot, parse_activity_file

START = datetime(2026, 11, 1, 9, 0, tzinfo=timezone.utc)
M_PER_DEG = 111_195.0


def _streams(kmh, minutes=20, step=5, watts=False):
    """time and distance every `step` s at `kmh` (a function of the minute, or a number)."""
    speed = kmh if callable(kmh) else (lambda m: kmh)
    t, d, acc = [], [], 0.0
    for s in range(0, minutes * 60, step):
        t.append(s)
        d.append(acc)
        acc += speed(s // 60) / 3.6 * step
    out = {'time': {'data': t}, 'distance': {'data': d}}
    if watts:
        out['watts'] = {'data': [180] * len(t)}
    return out


def test_steady_paces_are_told_apart():
    assert on_foot(_streams(10)) == 'Run'
    assert on_foot(_streams(5)) == 'Walk'
    assert on_foot(_streams(14)) == 'Run'
    assert on_foot(_streams(lambda m: 40 if m % 5 == 0 else 15)) is None   # a slow ride, but its descents go fast
    assert on_foot(_streams(22)) is None


def test_no_guess_with_a_power_meter_or_too_little_track():
    assert on_foot(_streams(10, watts=True)) is None
    assert on_foot(_streams(10, minutes=2)) is None
    assert on_foot({}) is None


def _points(kmh, minutes, step=5):
    for i, s in enumerate(range(0, minutes * 60, step)):
        yield START + timedelta(seconds=s), 50.7 + i * kmh / 3.6 * step / M_PER_DEG, i * kmh / 3.6 * step


def tcx(kmh, sport='Biking', minutes=20):
    pts = ''.join(f'<Trackpoint><Time>{t:%Y-%m-%dT%H:%M:%SZ}</Time><Position><LatitudeDegrees>{lat:.7f}</LatitudeDegrees>'
                  f'<LongitudeDegrees>-3.5</LongitudeDegrees></Position><DistanceMeters>{dist:.1f}</DistanceMeters></Trackpoint>'
                  for t, lat, dist in _points(kmh, minutes))
    sport_attr = f' Sport="{sport}"' if sport else ''
    return (f'<?xml version="1.0" encoding="UTF-8"?><TrainingCenterDatabase xmlns="http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2">'
            f'<Activities><Activity{sport_attr}><Id>{START:%Y-%m-%dT%H:%M:%SZ}</Id><Lap StartTime="{START:%Y-%m-%dT%H:%M:%SZ}">'
            f'<TotalTimeSeconds>{minutes * 60}</TotalTimeSeconds><DistanceMeters>{kmh / 3.6 * minutes * 60:.1f}</DistanceMeters>'
            f'<Track>{pts}</Track></Lap></Activity></Activities></TrainingCenterDatabase>').encode()


def gpx(kmh, kind=None, minutes=20, start=START):
    pts = ''.join(f'<trkpt lat="{lat:.7f}" lon="-3.5000000"><time>{(t - START + start):%Y-%m-%dT%H:%M:%SZ}</time></trkpt>'
                  for t, lat, _ in _points(kmh, minutes))
    return (f'<?xml version="1.0" encoding="UTF-8"?><gpx version="1.1" creator="RunKeeper" xmlns="http://www.topografix.com/GPX/1/1">'
            f'<trk><name>Morning</name>{f"<type>{kind}</type>" if kind else ""}<trkseg>{pts}</trkseg></trk></gpx>').encode()


def test_a_strava_tcx_run_saying_biking_is_a_ride_with_a_guess():
    act = parse_activity_file('a.tcx', tcx(10))
    assert act['sportType'] == 'Ride' and act['sportGuess'] == 'Run' and act['fileSport'] == 'Biking'
    assert 'sportGuess' not in parse_activity_file('a.tcx', tcx(10, sport='Running'))       # the file says, and is believed
    assert 'sportGuess' not in parse_activity_file('a.tcx', tcx(25))                        # a ride's pace: nothing to ask
    assert parse_activity_file('a.tcx', tcx(5, sport=None))['sportGuess'] == 'Walk'


def test_a_gpx_naming_no_sport_is_guessed_but_one_that_names_it_is_not():
    act = parse_activity_file('a.gpx', gpx(10))
    assert act['sportType'] == 'Ride' and act['sportGuess'] == 'Run' and act['fileSport'] is None
    assert 'sportGuess' not in parse_activity_file('a.gpx', gpx(10, kind='cycling'))


class _NoThread:
    def __init__(self, *a, **kw): pass
    def start(self): pass


@pytest.fixture
def app(tmp_path, monkeypatch):
    import app as app_module
    import config
    monkeypatch.setattr(config.Config, 'DATABASE', str(tmp_path / 'app.db'))
    monkeypatch.setattr(app_module.threading, 'Thread', _NoThread)
    monkeypatch.setattr('services.weather.fetch_weather', lambda *a, **k: None)
    a = app_module.create_app()
    with a.app_context():
        d = database.get_db()
        d.execute('INSERT OR IGNORE INTO Settings (id) VALUES (1)')
        d.execute("INSERT INTO Rider (id, name, isDefault) VALUES (1, 'Tom', 1)")
        d.commit()
    return a


def _client(app):
    from services import credentials
    with app.app_context():
        av = credentials.auth_version()
    c = app.test_client()
    with c.session_transaction() as s:
        s['logged_in'] = True
        s['av'] = av
    return c


def _upload(app, tmp_path, data, name):
    from routes.import_rides import _process_single_file
    path = tmp_path / name
    path.write_bytes(data)
    with app.app_context():
        events = [json.loads(e[len('data: '):]) for e in _process_single_file(str(path), name, 1) if e.startswith('data: ')]
    return next(e for e in events if e.get('complete'))


def _sport(app, act_id):
    with app.app_context():
        return database.get_db().execute('SELECT sportType FROM Activity WHERE id=?', [act_id]).fetchone()[0]


def test_an_uploaded_run_is_asked_about_and_changed_on_yes(app, tmp_path):
    done = _upload(app, tmp_path, tcx(10), 'run.tcx')
    rid = done['activity']['id']
    assert done['sport_guess'] == {'id': rid, 'guess': 'Run', 'saved': 'Ride', 'file': 'Biking'}
    assert _sport(app, rid) == 'Ride'                                               # nothing changes until the rider says
    c = _client(app)
    page = c.get(f'/activities/{rid}').get_data(as_text=True)
    assert 'Was this a run?' in page and 'Strava writes whatever the sport' in page
    assert '1 upload looks like a run or a walk' in c.get('/import').get_data(as_text=True)
    assert 'Sports to check' in c.get('/dashboard').get_data(as_text=True)
    r = c.post(f'/import/sport-guess/{rid}/use', data={'back': f'/activities/{rid}'})
    assert r.status_code == 302 and r.headers['Location'].endswith(f'/activities/{rid}')
    assert _sport(app, rid) == 'Run'
    assert 'Was this a run?' not in c.get(f'/activities/{rid}').get_data(as_text=True)
    assert 'id="sport-guess"' not in c.get('/import').get_data(as_text=True)


def test_a_slow_ride_kept_as_a_ride_is_not_asked_again(app, tmp_path):
    rid = _upload(app, tmp_path, gpx(12), 'ride.gpx')['activity']['id']
    c = _client(app)
    c.post(f'/import/sport-guess/{rid}/keep', data={'back': f'/activities/{rid}'})
    assert _sport(app, rid) == 'Ride'
    with app.app_context():
        assert sport_guess.for_activity(database.get_db(), rid) is None
    assert 'Was this a run?' not in c.get(f'/activities/{rid}').get_data(as_text=True)


def test_changing_the_sport_by_hand_answers_it(app, tmp_path):
    rid = _upload(app, tmp_path, gpx(5), 'walk.gpx')['activity']['id']
    c = _client(app)
    c.post(f'/activities/{rid}/sport', data={'sport': 'Hike'})
    with app.app_context():
        assert sport_guess.pending(database.get_db()) == []


def test_a_zip_of_files_counts_the_ones_it_asks_about_and_all_can_be_changed_at_once(app):
    from routes.import_rides import _process_generic_zip
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as zf:
        zf.writestr('a.gpx', gpx(10))
        zf.writestr('b.gpx', gpx(5, start=START + timedelta(days=1)))
        zf.writestr('c.gpx', gpx(25, start=START + timedelta(days=2)))
        zf.writestr('d.gpx', gpx(10, kind='cycling', start=START + timedelta(days=3)))
    with app.app_context(), zipfile.ZipFile(buf) as zf:
        events = [json.loads(e[len('data: '):]) for e in _process_generic_zip(zf, zf.namelist(), 1) if e.startswith('data: ')]
    assert next(e for e in events if e.get('complete'))['sport_guessed'] == 2
    _client(app).post('/import/sport-guess/all/use')
    with app.app_context():
        sports = sorted(r[0] for r in database.get_db().execute('SELECT sportType FROM Activity'))
    assert sports == ['Ride', 'Ride', 'Run', 'Walk']
