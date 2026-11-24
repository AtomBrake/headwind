"""The Routes page (routes/saved_routes.py, templates/routes.html): every saved route listed, renamed and given a sport, and routes brought in
from a Strava export (kept or uploaded) and Garmin Connect's courses (services/planned_routes.import_garmin). Throwaway DB, no network: Garmin
is a stand-in."""
import io
import zipfile

import pytest

from services import jobs, planned_routes, strava_export
from tests.page_data import page_data
from tests.test_planned_routes import app, client, db, strava_zip, trk     # noqa: F401  (fixtures)


def add_gpx(client, *files):
    return client.post('/planner/routes/import', data={'files': [(io.BytesIO(d), n) for n, d in files]},
                       content_type='multipart/form-data').get_json()


def zip_bytes(z):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as out:
        for n in z.namelist():
            out.writestr(n, z.read(n))
    return buf.getvalue()


# ---------- the page ----------

def test_the_page_is_in_the_sidebar_and_says_how_to_get_routes_when_there_are_none(client):
    page = client.get('/routes/').get_data(as_text=True)
    assert 'No routes yet' in page and 'Save as route' in page and 'href="/routes/"' in page
    assert 'From Garmin' not in page and 'Connect Garmin in Settings' in page      # not connected here
    assert page_data(page, 'routesData')['show'] is None


def test_the_page_lists_every_route_and_shows_the_newest_or_the_one_asked_for(client):
    a = add_gpx(client, ('a.gpx', trk()))[0]['id']
    b = add_gpx(client, ('b.gpx', trk(30, 'Canal', 'running')))[0]['id']
    page = client.get('/routes/').get_data(as_text=True)
    assert 'Bodmin loop' in page and 'Canal' in page and 'No routes yet' not in page
    assert page_data(page, 'routesData')['show'] == b
    assert page_data(client.get(f'/routes/?route={a}').get_data(as_text=True), 'routesData')['show'] == a
    assert page_data(client.get('/routes/?route=999').get_data(as_text=True), 'routesData')['show'] == b     # gone: the newest
    assert '<option value="Run" selected>' in page and '<option value="MountainBikeRide" selected>' in page


def test_a_route_from_an_activity_links_back_to_it(client):
    loc = client.post('/planner/routes/from-activity/run1').headers['Location']
    page = client.get(loc).get_data(as_text=True)
    assert 'href="/activities/run1"' in page


# ---------- renaming and the sport ----------

def test_rename_trims_and_a_blank_name_or_a_missing_route_is_refused(client):
    rid = add_gpx(client, ('a.gpx', trk()))[0]['id']
    assert client.post(f'/routes/{rid}', json={'name': '  Moor loop  '}).get_json() == {'name': 'Moor loop', 'sportType': 'MountainBikeRide'}
    assert client.post(f'/routes/{rid}', json={'name': '   '}).status_code == 400
    assert client.post('/routes/999', json={'name': 'X'}).status_code == 404
    assert client.get(f'/planner/routes/{rid}').get_json()['name'] == 'Moor loop'
    assert add_gpx(client, ('a.gpx', trk()))[0]['status'] == 'exists'          # renamed, the same file brings no copy


def test_the_sport_is_one_headwind_knows_or_none(client):
    rid = add_gpx(client, ('a.gpx', trk()))[0]['id']
    assert client.post(f'/routes/{rid}', json={'sportType': 'Hike'}).get_json()['sportType'] == 'Hike'
    assert client.post(f'/routes/{rid}', json={'sportType': 'Gravel Ride'}).get_json()['sportType'] == 'GravelRide'   # Strava's spelling
    assert client.post(f'/routes/{rid}', json={'sportType': 'Pogo'}).status_code == 400
    assert client.get(f'/planner/routes/{rid}').get_json()['sportType'] == 'GravelRide'
    assert client.post(f'/routes/{rid}', json={'sportType': ''}).get_json()['sportType'] is None


# ---------- Strava ----------

ROUTES_CSV = 'Bodmin,routes/1.gpx\nCanal,routes/2.gpx\n'
ROUTE_FILES = [('routes/1.gpx', trk()), ('routes/2.gpx', trk(30, 'Canal', 'running'))]


def test_the_routes_come_from_an_uploaded_strava_export_once(client):
    data = zip_bytes(strava_zip(ROUTES_CSV, ROUTE_FILES))
    post = lambda: client.post('/routes/import/strava', data={'zipfile': (io.BytesIO(data), 'export.zip')},
                               content_type='multipart/form-data').get_json()
    assert post() == {'routes_created': 2, 'routes_existing': 0, 'routes_unread': 0}
    assert post() == {'routes_created': 0, 'routes_existing': 2, 'routes_unread': 0}
    assert sorted(r['source'] for r in client.get('/planner/routes').get_json()) == ['strava', 'strava']


def test_a_zip_that_isn_t_a_strava_export_or_isn_t_a_zip_is_refused(client):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as z:
        z.writestr('hello.txt', 'hi')
    r = client.post('/routes/import/strava', data={'zipfile': (io.BytesIO(buf.getvalue()), 'x.zip')}, content_type='multipart/form-data')
    assert r.status_code == 400 and 'routes.csv' in r.get_json()['error']
    r = client.post('/routes/import/strava', data={'zipfile': (io.BytesIO(b'nope'), 'x.zip')}, content_type='multipart/form-data')
    assert r.status_code == 400 and r.get_json()['error'] == 'Not a zip file'
    assert client.post('/routes/import/strava', data={}).status_code == 400


def test_the_routes_come_from_the_kept_export_without_uploading_it(app, client):
    with app.app_context():
        from database import get_db
        d = get_db()
        strava_export.ensure_schema(d)
        with open(strava_export.path_for(app.config['DATABASE'], 1), 'wb') as f:
            f.write(zip_bytes(strava_zip(ROUTES_CSV, ROUTE_FILES)))
        d.execute("INSERT INTO StravaExport (riderId, keptAt) VALUES (1, '2026-11-01 10:00:00')")
        d.commit()
    assert 'Read the routes in the export imported' in client.get('/routes/').get_data(as_text=True)
    assert client.post('/routes/import/strava', data={'rider': 1}).get_json()['routes_created'] == 2
    assert client.post('/routes/import/strava', data={'rider': 7}).status_code == 404


# ---------- Garmin Connect ----------

class FakeGarmin:
    def __init__(self, courses, files):
        self.courses, self.files, self.downloaded = courses, files, []

    def get_courses(self):
        return self.courses

    def download_course(self, cid, fmt='gpx'):
        assert fmt == 'gpx'
        self.downloaded.append(cid)
        if cid not in self.files:
            raise RuntimeError('404')
        return self.files[cid]


COURSES = [{'courseId': 11, 'courseName': 'Tamar trail', 'activityType': {'typeKey': 'gravel_cycling'}},
           {'courseId': 12, 'courseName': 'Parkrun', 'activityType': {'typeKey': 'running'}},
           {'courseId': 13, 'courseName': 'Gone'},
           {'courseName': 'No id'}]


def test_garmin_courses_come_in_with_their_names_and_sports_once(db):
    api = FakeGarmin(COURSES, {11: trk(), 12: trk(30, 'x', None)})
    seen = []
    res = planned_routes.import_garmin(db, api, 1, progress=lambda done, total: seen.append((done, total)))
    assert res == {'created': 2, 'existing': 0, 'unread': 2, 'total': 4} and seen[-1] == (4, 4)
    assert [tuple(r) for r in db.execute('SELECT name, sportType, source, sourceId FROM PlannedRoute ORDER BY id')] == \
        [('Tamar trail', 'GravelRide', 'garmin', '11'), ('Parkrun', 'Run', 'garmin', '12')]
    again = FakeGarmin(COURSES, {11: trk(), 12: trk(30, 'x', None)})
    assert planned_routes.import_garmin(db, again, 1)['existing'] == 2 and again.downloaded == [13]     # only the one it couldn't read


def test_a_garmin_course_with_the_same_points_as_a_route_here_is_kept_once(db):
    planned_routes.save(db, 1, 'From a file', track=planned_routes.from_gpx(trk())['track'], source='gpx')
    res = planned_routes.import_garmin(db, FakeGarmin(COURSES[:1], {11: trk()}), 1)
    assert (res['created'], res['existing']) == (0, 1)


def test_the_course_list_may_come_wrapped(db):
    res = planned_routes.import_garmin(db, FakeGarmin({'coursesForUser': COURSES[:1]}, {11: trk()}), 1)
    assert res['created'] == 1


def test_only_the_chosen_garmin_courses_come_in(db):
    api = FakeGarmin(COURSES, {11: trk(), 12: trk(30, 'x', None)})
    res = planned_routes.import_garmin(db, api, 1, ids=['12'])
    assert res == {'created': 1, 'existing': 0, 'unread': 0, 'total': 1} and api.downloaded == [12]
    assert [r[0] for r in db.execute('SELECT sourceId FROM PlannedRoute')] == ['12']


def test_the_garmin_course_list_says_what_each_is_and_which_are_here_without_downloading(db):
    courses = [dict(COURSES[0], distanceInMeters=42195.0, elevationGainInMeters=610.4, createdDate=1735732800000),   # 1 Jan 2025
               dict(COURSES[1], createdDate=1767268800000),                                                          # 1 Jan 2026
               COURSES[2], COURSES[3]]
    planned_routes.import_garmin(db, FakeGarmin(courses, {11: trk()}), 1, ids=[11])
    api = FakeGarmin(courses, {})
    got = planned_routes.garmin_course_list(db, api, 1)
    assert api.downloaded == []
    assert got == [{'id': '12', 'name': 'Parkrun', 'sport': 'Run', 'distM': None, 'gainM': None, 'created': '2026-01-01', 'here': False},
                   {'id': '11', 'name': 'Tamar trail', 'sport': 'GravelRide', 'distM': 42195.0, 'gainM': 610.4, 'created': '2025-01-01',
                    'here': True},
                   {'id': '13', 'name': 'Gone', 'sport': None, 'distM': None, 'gainM': None, 'created': None, 'here': False}]  # no id: left out


def test_from_garmin_lists_the_courses_then_brings_in_the_chosen_ones_in_the_background(app, client, monkeypatch):
    assert client.get('/routes/import/garmin/courses').status_code == 400       # not connected
    assert client.post('/routes/import/garmin', json={'ids': ['11']}).status_code == 400
    monkeypatch.setattr('routes.saved_routes._garmin_on', lambda: True)
    monkeypatch.setattr('services.garmin._client', lambda: FakeGarmin(COURSES[:2], {11: trk(), 12: trk(30, 'x', None)}))
    page = client.get('/routes/').get_data(as_text=True)
    assert 'From Garmin' in page and 'id="garminPanel"' in page
    listed = client.get('/routes/import/garmin/courses').get_json()['courses']
    assert [(c['id'], c['sportLabel'], c['here']) for c in listed] == [('11', 'Gravel ride', False), ('12', 'Run', False)]
    assert client.post('/routes/import/garmin', json={}).status_code == 400                  # nothing chosen
    assert client.post('/routes/import/garmin', json={'ids': []}).status_code == 400
    assert client.post('/routes/import/garmin', json={'ids': [True]}).status_code == 400
    job = client.post('/routes/import/garmin', json={'ids': ['11']}).get_json()['job']
    assert client.post('/routes/import/garmin', json={'ids': ['12']}).get_json()['job'] == job   # one at a time: the page follows it
    assert page_data(client.get('/routes/').get_data(as_text=True), 'routesData')['garminJob'] == job
    jobs.run_queued(app)
    st = client.get(f'/routes/import/garmin/{job}').get_json()
    assert st['state'] == 'done' and st['progress']['result'] == {'created': 1, 'existing': 0, 'unread': 0, 'total': 1}
    assert [c['here'] for c in client.get('/routes/import/garmin/courses').get_json()['courses']] == [True, False]
    assert client.get('/routes/import/garmin/999').status_code == 404


def test_a_garmin_course_list_that_fails_says_so(client, monkeypatch):
    from services.garmin import SIGN_IN_AGAIN, SignInNeeded

    def refuse():
        raise SignInNeeded(SIGN_IN_AGAIN)

    def down():
        raise ConnectionError('timed out')
    monkeypatch.setattr('routes.saved_routes._garmin_on', lambda: True)
    monkeypatch.setattr('services.garmin._client', refuse)
    r = client.get('/routes/import/garmin/courses')
    assert r.status_code == 400 and 'sign in again' in r.get_json()['error']
    monkeypatch.setattr('services.garmin._client', down)
    r = client.get('/routes/import/garmin/courses')
    assert r.status_code == 502 and 'Could not reach Garmin' in r.get_json()['error']


def test_a_garmin_sign_in_that_fails_says_so(app, client, monkeypatch):
    from services.garmin import SIGN_IN_AGAIN, SignInNeeded

    def refuse():
        raise SignInNeeded(SIGN_IN_AGAIN)
    monkeypatch.setattr('routes.saved_routes._garmin_on', lambda: True)
    monkeypatch.setattr('services.garmin._client', refuse)
    job = client.post('/routes/import/garmin', json={'ids': ['11']}).get_json()['job']
    jobs.run_queued(app)
    st = client.get(f'/routes/import/garmin/{job}').get_json()
    assert st['state'] == 'failed' and 'sign in again' in st['error']
