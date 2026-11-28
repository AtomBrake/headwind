"""The live tracking link (services/live_share.py, routes/live_share.py, POST /api/v1/live/share): the page shows the track and the figures,
stops working once stopped or expired, looks the same for a token that never existed, shows nothing of another rider or another recording,
keeps each rider's track apart, and survives a restart mid-ride."""
import json
import time

import pytest

import database
from services import live, live_share


class _NoThread:
    def __init__(self, *a, **kw): pass
    def start(self): pass


def _make_app(tmp_path, monkeypatch, address='https://h.example'):
    import app as app_module
    import config
    monkeypatch.setattr(config.Config, 'DATABASE', str(tmp_path / 'app.db'))
    monkeypatch.setattr(config.Config, 'APP_URL', address)
    monkeypatch.setattr(app_module.threading, 'Thread', _NoThread)
    monkeypatch.delenv('HEADWIND_DEMO', raising=False)
    monkeypatch.setattr(live, '_connection', lambda: None)        # no MQTT broker
    return app_module.create_app()


@pytest.fixture
def phone(tmp_path, monkeypatch):
    from services import credentials
    app = _make_app(tmp_path, monkeypatch)
    with app.app_context():
        d = database.get_db()
        d.execute("INSERT OR IGNORE INTO Settings (id) VALUES (1)")
        d.execute("INSERT INTO Rider (id, name, isDefault) VALUES (1, 'Tom Baker', 1)")
        d.execute("INSERT INTO Rider (id, name, isDefault) VALUES (2, 'Sam Smith', 0)")
        d.commit()
        av = credentials.auth_version()
    web = app.test_client()
    with web.session_transaction() as s:
        s['logged_in'] = True
        s['av'] = av
    token = web.post('/phones/create', json={'name': 'iPhone', 'server_url': 'https://h.example'}).get_json()['token']
    c = app.test_client()
    c.app_, c.H = app, {'Authorization': 'Bearer ' + token}
    return c


HOME = (51.5, -0.1)


def reading(i, recording='rec-1', state='riding', **kw):
    """The i-th reading of a ride heading north from HOME, about 111 m apart."""
    d = {'state': state, 'recording': recording, 'lat': HOME[0] + i * 0.001, 'lng': HOME[1], 'speed_mps': 6.0, 'distance_m': i * 111.0,
         'elapsed_s': i * 20, 'sport': 'Ride', 'battery_pct': 80}
    d.update(kw)
    return d


def start(phone, recording='rec-1', **body):
    return phone.post('/api/v1/live/share', json={'recording': recording, 'sport': 'Ride', **body}, headers=phone.H)


def token_of(url):
    return url.rsplit('/', 1)[1]


def post(phone, r):
    assert phone.post('/api/v1/live', json=r, headers=phone.H).status_code == 200


def test_a_link_shows_the_track_and_figures_to_anyone(phone):
    post(phone, reading(0))
    r = start(phone)
    assert r.status_code == 201
    share = r.get_json()
    assert share['url'].startswith('https://h.example/live/hwl_') and share['created'] is True
    for i in range(1, 8):
        post(phone, reading(i))
    anyone = phone.app_.test_client()                # nobody signed in
    page = anyone.get('/live/' + token_of(share['url']))
    assert page.status_code == 200 and page.headers['Cache-Control'] == 'no-store' and 'noindex' in page.headers['X-Robots-Tag']
    html = page.get_data(as_text=True)
    assert 'Anyone with this link can see this page' in html and 'Tom' in html and 'Baker' not in html
    d = anyone.get('/live/' + token_of(share['url']) + '/data').get_json()
    assert d['status'] == 'live' and d['name'] == 'Tom' and d['sport'] == 'Ride'
    assert d['distance'] == '0.5 mi' and d['time'] == '2:20' and d['battery'] == 80
    assert d['position'] == [round(HOME[0] + 0.007, 6), HOME[1]]
    # the points within HIDE_START_M of where it began (0, 111 and 222 m) are never sent
    assert [p[0] for p in d['points']] == [pytest.approx(HOME[0] + i * 0.001) for i in range(3, 8)]
    again = anyone.get('/live/' + token_of(share['url']) + '/data?since=' + str(d['last'])).get_json()
    assert again['points'] == []


def test_the_position_is_hidden_near_the_start(phone):
    share = start(phone).get_json()
    post(phone, reading(0))
    post(phone, reading(1))
    d = phone.app_.test_client().get('/live/' + token_of(share['url']) + '/data').get_json()
    assert d['position'] is None and d['hidden'] is True and d['points'] == []


def test_asking_again_gives_the_running_share(phone):
    first = start(phone).get_json()
    second = start(phone)
    assert second.status_code == 200 and second.get_json()['url'] == first['url'] and second.get_json()['created'] is False
    assert start(phone, 'rec-2').get_json()['url'] != first['url']       # another recording, another link


def test_a_stopped_link_ends_at_once_and_looks_like_one_that_never_was(phone):
    share = start(phone).get_json()
    for i in range(6):
        post(phone, reading(i))
    url = '/live/' + token_of(share['url'])
    anyone = phone.app_.test_client()
    assert anyone.get(url).status_code == 200
    assert phone.delete('/api/v1/live/share', json={'recording': 'rec-1'}, headers=phone.H).get_json() == {'stopped': 1}
    stopped, never = anyone.get(url), anyone.get('/live/hwl_' + 'x' * 32)
    assert stopped.status_code == never.status_code == 404
    assert stopped.get_data() == never.get_data() and b'This link has ended' in never.get_data()
    assert anyone.get(url + '/data').status_code == 404
    with phone.app_.app_context():
        assert database.get_db().execute('SELECT COUNT(*) FROM LivePoint').fetchone()[0] == 0


def test_a_finished_recording_keeps_its_link_for_an_hour_then_it_expires(phone):
    share = start(phone).get_json()
    for i in range(6):
        post(phone, reading(i))
    post(phone, reading(6, state='idle'))
    url = '/live/' + token_of(share['url'])
    anyone = phone.app_.test_client()
    d = anyone.get(url + '/data').get_json()
    assert d['status'] == 'finished' and d['endedAt']
    with phone.app_.app_context():
        db = database.get_db()
        row = db.execute('SELECT * FROM LiveShare').fetchone()
        assert row['expiresAt'] == pytest.approx(row['endedAt'] + live_share.AFTER_END_S)
        later = row['expiresAt'] + 1
        assert live_share.lookup(db, token_of(share['url']), now=later) is None
        assert live_share.sweep(db, now=later) > 0
        assert db.execute('SELECT COUNT(*) FROM LivePoint').fetchone()[0] == 0
        assert db.execute('SELECT reading, sealedToken FROM LiveShare').fetchone()[:] == (None, None)
    post(phone, reading(7, recording='rec-2'))           # the next recording doesn't bring an ended share back
    with phone.app_.app_context():
        db = database.get_db()
        db.execute('UPDATE LiveShare SET expiresAt=?', [time.time() - 1])
        db.commit()
    assert anyone.get(url).status_code == 404


def test_a_share_shows_only_its_own_recording(phone):
    """A later recording, with no share, never shows on the earlier one's page; nor a reading sent before the share began."""
    post(phone, reading(5, recording='rec-0', lat=40.0, lng=-3.0))      # an earlier activity, somewhere else
    share = start(phone).get_json()
    for i in range(5):
        post(phone, reading(i))
    post(phone, reading(4, state='idle'))
    post(phone, reading(9, recording='rec-2', lat=48.0, lng=2.0, sport='Run'))
    d = phone.app_.test_client().get('/live/' + token_of(share['url']) + '/data').get_json()
    lats = [p[0] for p in d['points']] + ([d['position'][0]] if d['position'] else [])
    assert all(51.4 < lat < 51.6 for lat in lats) and d['sport'] == 'Ride' and d['status'] == 'finished'


def test_two_riders_recording_at_once_keep_their_own_tracks(phone):
    with phone.app_.app_context():
        db = database.get_db()
        a, ta, _ = live_share.start(db, 1, 'rec-a')
        b, tb, _ = live_share.start(db, 2, 'rec-a')          # the same recording id from two phones
        for i in range(6):
            live.update(reading(i, recording='rec-a'), rider_id=1)
            live.update(reading(i, recording='rec-a', lat=-33.9 - i * 0.001, lng=151.2), rider_id=2)
        va = live_share.view(db, live_share.lookup(db, ta))
        vb = live_share.view(db, live_share.lookup(db, tb))
    assert va['name'] == 'Tom' and vb['name'] == 'Sam'
    assert all(p[0] > 0 for p in va['points']) and all(p[0] < 0 for p in vb['points'])
    assert va['points'] and vb['points']


def test_the_track_survives_a_restart(phone, tmp_path, monkeypatch):
    share = start(phone).get_json()
    for i in range(6):
        post(phone, reading(i))
    before = phone.app_.test_client().get('/live/' + token_of(share['url']) + '/data').get_json()
    again = _make_app(tmp_path, monkeypatch)              # the same database, a new process
    after = again.test_client().get('/live/' + token_of(share['url']) + '/data').get_json()
    assert after['points'] == before['points'] and len(after['points']) == 3 and after['distance'] == before['distance']


def test_a_share_started_mid_recording_takes_the_track_so_far(phone):
    t0 = time.time() - 600
    track = [[HOME[0] + i * 0.0005, HOME[1], t0 + i * 15] for i in range(20)]
    share = start(phone, track=track).get_json()
    d = phone.app_.test_client().get('/live/' + token_of(share['url']) + '/data').get_json()
    assert len(d['points']) == 20 - 6             # within 300 m of the start: hidden (0 to 277 m)


@pytest.mark.parametrize('address, says', [
    ('', 'no outside address'),
    ('http://localhost:5000', 'only works at home'),
    ('https://192.168.1.20', 'only works at home'),
    ('https://headwind.local', 'only works at home'),
    ('http://h.example', 'not https'),
])
def test_no_link_without_an_address_others_can_open(tmp_path, monkeypatch, address, says):
    app = _make_app(tmp_path, monkeypatch, address)
    with app.test_request_context():
        base, why = live_share.link_base()
    assert base is None and says in why and 'Settings → Outside address' in why


def test_the_api_refuses_without_an_address(tmp_path, monkeypatch):
    app = _make_app(tmp_path, monkeypatch, 'http://192.168.1.20:5000')
    from services import device_auth
    with app.app_context():
        d = database.get_db()
        d.execute("INSERT OR IGNORE INTO Settings (id) VALUES (1)")
        d.execute("INSERT INTO Rider (id, name, isDefault) VALUES (1, 'Tom', 1)")
        d.commit()
        token = device_auth.create('iPhone')[0]
    r = app.test_client().post('/api/v1/live/share', json={'recording': 'r'}, headers={'Authorization': 'Bearer ' + token})
    assert r.status_code == 409 and r.get_json()['settings_url'] == '/settings#address'
    with app.app_context():
        assert database.get_db().execute('SELECT COUNT(*) FROM LiveShare').fetchone()[0] == 0


def test_home_assistant_still_gets_its_readings(phone):
    """The reading kept for Home Assistant is the same as before, with the figures for the link beside it."""
    post(phone, reading(3))
    with phone.app_.app_context():
        c = json.loads(database.get_db().execute('SELECT reading FROM LiveReading WHERE riderId=1').fetchone()[0])
    assert c['distance_mi'] == pytest.approx(0.21, abs=0.01) and c['speed_mph'] == pytest.approx(13.4, abs=0.1)
    assert c['recording'] == 'rec-1' and c['distance_m'] == 333.0
    assert live.states_for(c)['live_ride_status'] == 'riding'


def test_the_page_says_when_the_signal_went(phone):
    share = start(phone).get_json()
    with phone.app_.app_context():
        db = database.get_db()
        row = live_share.lookup(db, token_of(share['url']))
        assert live_share.view(db, row)['status'] == 'waiting'
    for i in range(5):
        post(phone, reading(i))
    with phone.app_.app_context():
        db = database.get_db()
        row = live_share.lookup(db, token_of(share['url']))
        assert live_share.view(db, row)['status'] == 'live'
        quiet = live_share.view(db, row, now=row['readingAt'] + live_share.NO_SIGNAL_S + 1)
        assert quiet['status'] == 'nosignal' and quiet['rateNow'] is None and quiet['rateAvg']


def test_one_address_asking_too_often_is_slowed(phone, monkeypatch):
    from routes import live_share as page
    from services.demo import RateLimiter
    monkeypatch.setattr(page, '_limiter', RateLimiter(limit=3, window=60))
    anyone = phone.app_.test_client()
    codes = [anyone.get('/live/hwl_unknown/data').status_code for _ in range(4)]
    assert codes == [404, 404, 404, 429]
    assert anyone.get('/live/hwl_unknown').status_code == 429


# Sending the link to contacts chosen beforehand (services/contacts.py, services/mail.py)

class _MailServer:
    """Stands in for the SMTP connection (services/mail._connect): keeps what it's given, refusing the addresses in `refuse`."""
    def __init__(self, refuse=()):
        self.sent, self.refuse, self.quit_called = [], set(refuse), False

    def send_message(self, m):
        import smtplib
        if m['To'] in self.refuse:
            raise smtplib.SMTPRecipientsRefused({m['To']: (550, b'No such user')})
        self.sent.append(m)

    def quit(self):
        self.quit_called = True


def _email_on(phone, monkeypatch, server=None, fail=None):
    """Settings → Email filled in, and the connection to it faked: `fail`, an exception the connection raises instead."""
    from services import mail
    with phone.app_.app_context():
        d = database.get_db()
        d.execute("UPDATE Settings SET smtpHost='smtp.example.com', smtpSecurity='starttls', smtpFrom='headwind@example.com' WHERE id=1")
        d.commit()
    server = server or _MailServer()

    def connect(cfg):
        if fail:
            raise fail
        return server
    monkeypatch.setattr(mail, '_connect', connect)
    return server


def _contact(phone, name, email, live_links=True):
    r = phone.post('/api/v1/contacts', json={'name': name, 'email': email, 'live_links': live_links}, headers=phone.H)
    assert r.status_code == 201, r.get_json()
    return r.get_json()


def _run_jobs(phone):
    from services import jobs
    return jobs.run_queued(phone.app_)


def _status(phone, recording='rec-1'):
    return phone.get(f'/api/v1/live/share?recording={recording}', headers=phone.H)


def test_a_new_link_is_emailed_to_the_chosen_contacts_in_the_background_and_once(phone, monkeypatch):
    server = _email_on(phone, monkeypatch)
    _contact(phone, 'Sam', 'sam@example.com')
    _contact(phone, 'Alex', 'alex@example.com')
    _contact(phone, 'Pat', 'pat@example.com', live_links=False)          # not ticked: not sent
    r = start(phone)
    share = r.get_json()
    assert r.status_code == 201
    # The phone's answer doesn't wait for the mail server: it says who it's going to
    assert share['contacts'] == [{'name': 'Alex', 'state': 'sending', 'error': None}, {'name': 'Sam', 'state': 'sending', 'error': None}]
    assert server.sent == []
    assert _run_jobs(phone) == 1
    assert sorted(m['To'] for m in server.sent) == ['alex@example.com', 'sam@example.com'] and server.quit_called
    m = server.sent[0]
    assert m['Subject'] == "Follow Tom's ride live" and m['From'] == 'Tom via Headwind <headwind@example.com>'
    body = m.get_content()
    assert share['url'] in body and 'an hour after the ride ends' in body and 'Baker' not in body
    assert [c['state'] for c in _status(phone).get_json()['contacts']] == ['sent', 'sent']
    # The running link given again is not sent again
    again = start(phone)
    assert again.status_code == 200 and again.get_json()['created'] is False
    assert [c['state'] for c in again.get_json()['contacts']] == ['sent', 'sent']
    assert _run_jobs(phone) == 0 and len(server.sent) == 2


def test_each_contact_says_whether_it_reached_them(phone, monkeypatch):
    server = _email_on(phone, monkeypatch, _MailServer(refuse={'nobody@example.com'}))
    _contact(phone, 'Sam', 'sam@example.com')
    _contact(phone, 'Nobody', 'nobody@example.com')
    start(phone)
    _run_jobs(phone)
    got = {c['name']: c for c in _status(phone).get_json()['contacts']}
    assert got['Sam']['state'] == 'sent' and got['Sam']['error'] is None
    assert got['Nobody']['state'] == 'failed' and 'would not send to this address' in got['Nobody']['error']
    assert [m['To'] for m in server.sent] == ['sam@example.com']


def test_a_mail_server_that_doesnt_answer_fails_each_contact_saying_why(phone, monkeypatch):
    import socket
    _email_on(phone, monkeypatch, fail=socket.timeout('timed out'))
    _contact(phone, 'Sam', 'sam@example.com')
    start(phone)
    _run_jobs(phone)                    # the job itself ends normally
    (c,) = _status(phone).get_json()['contacts']
    assert c['state'] == 'failed' and "didn't answer" in c['error'] and 'smtp.example.com' in c['error']


def test_without_email_set_up_the_contacts_are_told_failed_at_once(phone):
    _contact(phone, 'Sam', 'sam@example.com')
    share = start(phone).get_json()
    (c,) = share['contacts']
    assert c['state'] == 'failed' and 'Settings → Email' in c['error']
    assert _run_jobs(phone) == 0                                # nothing queued for the worker
    assert start(phone, 'rec-2').status_code == 201             # and sharing goes on regardless


def test_no_contacts_no_email(phone, monkeypatch):
    server = _email_on(phone, monkeypatch)
    share = start(phone).get_json()
    assert share['contacts'] == [] and _run_jobs(phone) == 0 and server.sent == []


def test_a_link_stopped_before_it_was_sent_is_not_sent(phone, monkeypatch):
    server = _email_on(phone, monkeypatch)
    _contact(phone, 'Sam', 'sam@example.com')
    share = start(phone).get_json()
    phone.delete('/api/v1/live/share', json={'recording': 'rec-1'}, headers=phone.H)
    _run_jobs(phone)
    assert server.sent == []
    with phone.app_.app_context():
        (c,) = live_share.recipients(database.get_db(), share['id'])
    assert c['state'] == 'failed' and 'stopped' in c['error']


def test_the_sport_and_name_in_the_email(phone, monkeypatch):
    server = _email_on(phone, monkeypatch)
    _contact(phone, 'Sam', 'sam@example.com')
    start(phone, sport='TrailRun')
    _run_jobs(phone)
    m = server.sent[0]
    assert m['Subject'] == "Follow Tom's trail run live"
    assert 'Tom has started a trail run' in m.get_content() and 'distance, time and pace' in m.get_content()


def test_asking_for_a_link_that_isnt_running(phone):
    assert _status(phone, 'rec-none').status_code == 404


def test_who_it_was_sent_to_goes_with_the_share(phone, monkeypatch):
    _email_on(phone, monkeypatch)
    _contact(phone, 'Sam', 'sam@example.com')
    share = start(phone).get_json()
    _run_jobs(phone)
    with phone.app_.app_context():
        db = database.get_db()
        live_share.sweep(db, now=time.time() + live_share.SILENT_S + 86400 + 10)
        assert db.execute('SELECT COUNT(*) FROM LiveShare').fetchone()[0] == 0
        assert live_share.recipients(db, share['id']) == []


def test_the_contacts_api(phone):
    r = phone.get('/api/v1/contacts', headers=phone.H).get_json()
    assert r['contacts'] == [] and r['email']['ready'] is False and r['email']['settings_url'] == '/settings#email'
    sam = _contact(phone, '  Sam   Smith ', 'sam@example.com')
    assert sam['name'] == 'Sam Smith' and sam['live_links'] is True
    bad = phone.post('/api/v1/contacts', json={'name': 'X', 'email': 'not an address'}, headers=phone.H)
    assert bad.status_code == 400 and 'not an email address' in bad.get_json()['error']
    twice = phone.post('/api/v1/contacts', json={'name': 'Sam again', 'email': 'SAM@example.com'}, headers=phone.H)
    assert twice.status_code == 400 and 'already a contact' in twice.get_json()['error']
    nameless = phone.post('/api/v1/contacts', json={'name': ' ', 'email': 'x@example.com'}, headers=phone.H)
    assert nameless.status_code == 400
    off = phone.patch(f"/api/v1/contacts/{sam['id']}", json={'live_links': False}, headers=phone.H).get_json()
    assert off['live_links'] is False and off['email'] == 'sam@example.com'
    assert phone.patch('/api/v1/contacts/999', json={'name': 'X'}, headers=phone.H).status_code == 404
    assert phone.delete(f"/api/v1/contacts/{sam['id']}", headers=phone.H).get_json() == {'deleted': True}
    assert phone.get('/api/v1/contacts', headers=phone.H).get_json()['contacts'] == []


def test_another_riders_contacts_are_not_sent_a_link(phone, monkeypatch):
    from services import contacts
    server = _email_on(phone, monkeypatch)
    with phone.app_.app_context():
        contacts.add(database.get_db(), 2, 'Mum', 'mum@example.com')
    assert start(phone).get_json()['contacts'] == []
    _run_jobs(phone)
    assert server.sent == []


def _web(phone):
    from services import credentials
    with phone.app_.app_context():
        av = credentials.auth_version()
    web = phone.app_.test_client()
    with web.session_transaction() as s:
        s['logged_in'] = True
        s['av'] = av
    return web


def test_contacts_and_email_on_the_web_settings_page(phone):
    from services import contacts, mail, vault
    web = _web(phone)
    page = web.get('/settings/').get_data(as_text=True)
    assert 'Contacts for live links' in page and 'Email isn&#39;t set up' in page
    assert web.post('/settings/email', data={'smtpHost': 'smtp.example.com', 'smtpSecurity': 'ssl', 'smtpPort': '',
                                             'smtpUser': 'tom', 'smtpPassword': 'hunter22', 'smtpFrom': 'headwind@example.com'}).status_code == 302
    with phone.app_.app_context():
        db = database.get_db()
        assert db.execute('SELECT smtpPassword AS v FROM Settings').fetchone()['v'].startswith(vault.PREFIX)     # sealed
        cfg = mail.config(db)
        assert (cfg['host'], cfg['port'], cfg['security'], cfg['password']) == ('smtp.example.com', 465, 'ssl', 'hunter22')
    web.post('/settings/email', data={'smtpHost': 'smtp.example.com', 'smtpSecurity': 'ssl', 'smtpFrom': 'headwind@example.com',
                                      'smtpPassword': ''})                                  # blank keeps the password
    with phone.app_.app_context():
        assert mail.config(database.get_db())['password'] == 'hunter22'
    web.post('/settings/email', data={'smtpHost': 'smtp.example.com', 'smtpFrom': 'not an address'})       # refused: nothing changes
    with phone.app_.app_context():
        assert mail.config(database.get_db())['sender'] == 'headwind@example.com'
    assert web.post('/settings/contacts', data={'name': 'Sam', 'email': 'sam@example.com', 'liveLinks': '1'}).status_code == 302
    page = web.get('/settings/').get_data(as_text=True)
    assert 'value="sam@example.com"' in page and 'Email isn&#39;t set up' not in page
    with phone.app_.app_context():
        (sam,) = contacts.listing(database.get_db(), 1)
    web.post(f"/settings/contacts/{sam['id']}", data={'name': 'Sam S', 'email': 'sam@example.com'})        # unticked: posts nothing
    got = phone.get('/api/v1/contacts', headers=phone.H).get_json()
    assert got['contacts'][0]['name'] == 'Sam S' and got['contacts'][0]['live_links'] is False and got['email']['ready'] is True
    web.post(f"/settings/contacts/{sam['id']}/delete")
    assert phone.get('/api/v1/contacts', headers=phone.H).get_json()['contacts'] == []


def test_the_test_email_uses_what_is_typed(phone, monkeypatch):
    from services import mail
    server = _MailServer()
    seen = {}

    def connect(cfg):
        seen.update(cfg)
        return server
    monkeypatch.setattr(mail, '_connect', connect)
    web = _web(phone)
    r = web.post('/settings/test-email', data={'smtpHost': 'smtp.example.com', 'smtpSecurity': 'starttls', 'smtpFrom': 'headwind@example.com',
                                               'smtpTestTo': 'tom@example.com'})
    assert r.status_code == 200 and 'tom@example.com' in r.get_json()['message']
    assert seen['port'] == 587 and [m['To'] for m in server.sent] == ['tom@example.com']
    none = web.post('/settings/test-email', data={'smtpHost': ''})
    assert none.status_code == 400 and 'Settings → Email' in none.get_json()['error']


def test_the_troubleshooting_copy_leaves_out_the_contacts(phone, monkeypatch):
    import sqlite3
    from services import troubleshooting_copy
    _email_on(phone, monkeypatch)
    _contact(phone, 'Sam', 'sam@example.com')
    start(phone)
    copy = sqlite3.connect(':memory:')
    src = sqlite3.connect(phone.app_.config['DATABASE'])
    src.backup(copy)
    src.close()
    troubleshooting_copy.strip(copy)
    assert copy.execute('SELECT COUNT(*) FROM Contact').fetchone()[0] == 0
    assert copy.execute('SELECT COUNT(*) FROM ContactSend').fetchone()[0] == 0
    assert copy.execute('SELECT smtpHost, smtpFrom, smtpPassword FROM Settings').fetchone() == (None, None, None)


# The route being followed (live_share.route_copy, _follow, _route_view)

M_LAT = 111_320.0                                   # metres in a degree of latitude, near enough for these


def _route(phone, points, rider=1, name='Route'):
    """A saved route for the rider through these [lat, lng] points: its id."""
    from services import planned_routes
    with phone.app_.app_context():
        db = database.get_db()
        rid, _ = planned_routes.save(db, rider, name, track=planned_routes.clean(points), source='gpx')
        db.commit()
    return rid


def _along(points, step_m=100):
    """Positions every step_m along a [lat, lng] line, as a rider going round it would send them."""
    out = []
    for a, b in zip(points, points[1:]):
        d = live_share._metres(a[0], a[1], b[0], b[1])
        n = max(1, int(d // step_m))
        out += [[a[0] + (b[0] - a[0]) * k / n, a[1] + (b[1] - a[1]) * k / n] for k in range(n)]
    return out + [points[-1]]


def _ride(db, share, positions, t0, every_s=15, gone=0.0, recording='rec-1'):
    """Readings at these positions, every_s apart from t0: (the time of the last, metres gone)."""
    t = t0
    for i, (lat, lng) in enumerate(positions):
        if i:
            gone += live_share._metres(positions[i - 1][0], positions[i - 1][1], lat, lng)
            t += every_s
        live_share.record(db, 1, {'state': 'riding', 'recording': recording, 'lat': lat, 'lng': lng, 'distance_m': gone,
                                  'elapsed_s': t - t0 + 1, 'speed_mps': 6.0, 'sport': 'Ride'}, now=t)
    db.commit()
    return t, gone


def _view(db, token, now):
    return live_share.view(db, live_share.lookup(db, token, now=now), now=now)


def test_progress_along_an_out_and_back_doesnt_jump_ahead_or_back(phone):
    tip = [HOME[0] + 0.03, HOME[1]]                       # 3.3 km north, then back the same road
    rid = _route(phone, [list(HOME), tip, list(HOME)])
    out = _along([list(HOME), tip])
    with phone.app_.app_context():
        db = database.get_db()
        t0 = time.time() - 3600
        _, token, _ = live_share.start(db, 1, 'rec-1', sport='Ride', route=rid, now=t0)
        t, _ = _ride(db, None, out[:16], t0)                                   # 1.5 km out
        v = _view(db, token, t)
        total = 2 * 0.03 * M_LAT
        assert v['hasRoute'] and v['route_done_m'] == pytest.approx(1500, abs=60)
        assert v['route_left_m'] == pytest.approx(total - 1500, abs=60) and not v['offRoute']
        t, gone = _ride(db, None, out[16:] + out[::-1][1:16], t + 15, gone=1500)   # to the tip and 1.5 km back
        v = _view(db, token, t)
        assert v['route_done_m'] == pytest.approx(total / 2 + 1500, abs=80)    # on the way back, not the way out
        assert v['route_left_m'] == pytest.approx(total / 2 - 1500, abs=80)


def test_progress_round_a_loop_that_crosses_itself(phone):
    # North 3.3 km, east, south half way, west across the way out (at 1.67 km along), south, then east home: a figure of eight
    lat0, lng0 = HOME
    loop = [[lat0, lng0], [lat0 + 0.03, lng0], [lat0 + 0.03, lng0 + 0.01], [lat0 + 0.015, lng0 + 0.01], [lat0 + 0.015, lng0 - 0.01],
            [lat0, lng0 - 0.01], [lat0, lng0]]
    rid = _route(phone, loop)
    path = _along(loop)
    crossing = min(range(len(path)), key=lambda i: abs(path[i][0] - (lat0 + 0.015)) + abs(path[i][1] - lng0))
    with phone.app_.app_context():
        db = database.get_db()
        t0 = time.time() - 3600
        _, token, _ = live_share.start(db, 1, 'rec-1', route=rid, now=t0)
        t, _ = _ride(db, None, path[:crossing + 1], t0)
        first = _view(db, token, t)['route_done_m']
        assert first == pytest.approx(0.015 * M_LAT, abs=80)                   # the first time over the crossing
        second = min(range(crossing + 20, len(path)), key=lambda i: live_share._metres(path[i][0], path[i][1], lat0 + 0.015, lng0))
        t, _ = _ride(db, None, path[crossing + 1:second + 1], t + 15)
        v = _view(db, token, t)
        assert v['route_done_m'] > first + 3000                                # the second time, further on
        t, _ = _ride(db, None, path[second + 1:], t + 15)
        v = _view(db, token, t)
        assert v['route_left_m'] < 60


def test_off_the_route_it_says_so_and_keeps_the_last_figures(phone):
    rid = _route(phone, [list(HOME), [HOME[0] + 0.03, HOME[1]]])
    with phone.app_.app_context():
        db = database.get_db()
        t0 = time.time() - 3600
        _, token, _ = live_share.start(db, 1, 'rec-1', route=rid, now=t0)
        t, _ = _ride(db, None, _along([list(HOME), [HOME[0] + 0.01, HOME[1]]]), t0)
        done = _view(db, token, t)['route_done_m']
        t, _ = _ride(db, None, [[HOME[0] + 0.01, HOME[1] + 0.003 * k] for k in range(1, 4)], t + 15)   # 200 m east and on
        v = _view(db, token, t)
        assert v['offRoute'] is True and v['route_done_m'] == done
        t, _ = _ride(db, None, [[HOME[0] + 0.012, HOME[1]]], t + 15)                                 # back on it
        v = _view(db, token, t)
        assert v['offRoute'] is False and v['route_done_m'] == pytest.approx(done + 222, abs=30)


def test_the_finish_time_is_at_the_recent_moving_speed(phone):
    rid = _route(phone, [list(HOME), [HOME[0] + 0.05, HOME[1]]])             # 5.6 km
    path = _along([list(HOME), [HOME[0] + 0.02, HOME[1]]], step_m=60)         # 60 m every 10 s: 6 m/s
    with phone.app_.app_context():
        db = database.get_db()
        t0 = time.time() - 3600
        _, token, _ = live_share.start(db, 1, 'rec-1', route=rid, now=t0)
        t, gone = _ride(db, None, path[:20], t0, every_s=10)
        t, gone = _ride(db, None, [path[19]] * 20, t + 15, every_s=15, gone=gone)     # five minutes at a café
        t, gone = _ride(db, None, path[19:30], t + 10, every_s=10, gone=gone)
        v = _view(db, token, t)
        assert v['eta'] == pytest.approx(t + v['route_left_m'] / 6.0, abs=60)
        live_share.record(db, 1, {'state': 'idle', 'recording': 'rec-1', 'lat': path[30][0], 'lng': path[30][1]}, now=t + 10)
        db.commit()
        assert _view(db, token, t + 20)['eta'] is None                         # finished


def _shown(v):
    return [p for piece in (v['route'] or []) for p in piece]


def test_the_route_is_cut_round_both_ends_and_the_privacy_zones(phone):
    import random
    from services import privacy_zones
    finish = [HOME[0] + 0.03, HOME[1] + 0.02]
    mid = [HOME[0] + 0.03, HOME[1] + 0.005]
    rid = _route(phone, [list(HOME), [HOME[0] + 0.03, HOME[1]], finish])
    with phone.app_.app_context():
        db = database.get_db()
        privacy_zones.add(db, 1, 'Work', mid[0], mid[1], 200, rng=random.Random(3))
        t0 = time.time() - 600
        _, token, _ = live_share.start(db, 1, 'rec-1', route=rid, show_route=True, now=t0)
        v = _view(db, token, t0)
        pts = _shown(v)
        assert v['routeShown'] and len(v['route']) == 2 and len(pts) > 20       # in two pieces either side of the zone
        for end in (HOME, finish):
            assert min(live_share._metres(end[0], end[1], p[0], p[1]) for p in pts) >= live_share.HIDE_START_M
        assert min(live_share._metres(mid[0], mid[1], p[0], p[1]) for p in pts) >= 200
        # and so is the rider: at the finish, which isn't where the recording began, the position isn't shown
        _ride(db, None, [list(HOME), [HOME[0] + 0.01, HOME[1]], finish], t0, every_s=200)
        v = _view(db, token, t0 + 400)
        assert v['position'] is None and v['hidden'] is True


def test_a_route_not_shown_still_gives_the_distance_to_go_and_finish(phone):
    rid = _route(phone, [list(HOME), [HOME[0] + 0.05, HOME[1]]])
    share = start(phone, route=rid).get_json()
    assert share['route'] == {'id': rid, 'shown': False}
    for i in range(6):
        post(phone, reading(i))
    anyone = phone.app_.test_client()
    html = anyone.get('/live/' + token_of(share['url'])).get_data(as_text=True)
    assert 'Done along the route' in html and 'the route they' not in html
    d = anyone.get('/live/' + token_of(share['url']) + '/data').get_json()
    assert d['hasRoute'] and d['route'] is None and d['routeShown'] is False
    assert d['routeDone'] and d['routeLeft'] and d['eta']
    # turned on later: the page draws it
    again = start(phone, route=rid, show_route=True).get_json()
    assert again['created'] is False and again['route'] == {'id': rid, 'shown': True}
    d = anyone.get('/live/' + token_of(share['url']) + '/data').get_json()
    assert d['routeShown'] and d['route']
    assert anyone.get('/live/' + token_of(share['url']) + '/data?since=' + str(d['last'])).get_json()['route'] is None    # sent once


def test_a_deleted_route_stays_on_the_running_link_and_goes_with_it(phone):
    rid = _route(phone, [list(HOME), [HOME[0] + 0.05, HOME[1]]])
    share = start(phone, route=rid, show_route=True).get_json()
    with phone.app_.app_context():
        db = database.get_db()
        db.execute('DELETE FROM PlannedRoute')
        db.commit()
    post(phone, reading(5))
    d = phone.app_.test_client().get('/live/' + token_of(share['url']) + '/data').get_json()
    assert d['hasRoute'] and d['route'] and d['route_done_m'] == pytest.approx(555, abs=30)
    phone.delete('/api/v1/live/share', json={'recording': 'rec-1'}, headers=phone.H)
    with phone.app_.app_context():
        db = database.get_db()
        assert db.execute('SELECT routeLine, routeHide FROM LiveShare').fetchone()[:] == (None, None)
        # one that expired instead: sweep takes it
        live_share.start(db, 1, 'rec-2', route=_route(phone, [list(HOME), [HOME[0] + 0.05, HOME[1]]]))
        live_share.sweep(db, now=time.time() + live_share.SILENT_S + 1)
        assert db.execute('SELECT COUNT(*) FROM LiveShare WHERE routeLine IS NOT NULL').fetchone()[0] == 0


def test_a_route_that_isnt_the_riders_or_is_gone_is_left_out(phone):
    theirs = _route(phone, [list(HOME), [HOME[0] + 0.05, HOME[1]]], rider=2)
    for route in (theirs, 99999, 'nonsense'):
        share = start(phone, recording=f'rec-{route}', route=route).get_json()
        assert share['created'] and share['route'] is None
        assert phone.app_.test_client().get('/live/' + token_of(share['url']) + '/data').get_json()['hasRoute'] is False


def test_a_share_started_mid_route_takes_up_where_the_track_is(phone):
    rid = _route(phone, [list(HOME), [HOME[0] + 0.05, HOME[1]]])
    t0 = time.time() - 600
    track = [[HOME[0] + i * 0.001, HOME[1], t0 + i * 15] for i in range(20)]
    share = start(phone, route=rid, track=track).get_json()
    d = phone.app_.test_client().get('/live/' + token_of(share['url']) + '/data').get_json()
    assert d['route_done_m'] == pytest.approx(19 * 0.001 * M_LAT, abs=30)


def test_a_long_route_is_simplified_for_the_link(phone):
    import math
    wiggly = [[HOME[0] + i * 0.0002, HOME[1] + 0.0003 * math.sin(i / 3)] for i in range(20_000)]      # 445 km of bends
    rid = _route(phone, wiggly)
    with phone.app_.app_context():
        line, hide = live_share.route_copy(database.get_db(), 1, rid)
    assert len(line) <= live_share.MAX_ROUTE_POINTS and line[-1][2] > 400_000 and len(hide) == 2


def _web(phone):
    from services import credentials
    with phone.app_.app_context():
        av = credentials.auth_version()
    web = phone.app_.test_client()
    with web.session_transaction() as s:
        s['logged_in'] = True
        s['av'] = av
    return web


def test_the_phones_page_lists_the_links_and_stops_one(phone):
    running = start(phone).get_json()
    done = start(phone, 'rec-2').get_json()
    post(phone, reading(3, recording='rec-2', state='idle'))
    web = _web(phone)
    html = web.get('/phones/').get_data(as_text=True)
    assert 'Live tracking links' in html and html.count('data-click="stopLive(') == 2       # both still work
    assert 'running' in html and 'finished' in html and running['url'] in html
    assert web.post(f"/phones/live/{running['id']}/stop").get_json() == {'ok': True, 'stopped': 1}
    assert phone.app_.test_client().get('/live/' + token_of(running['url'])).status_code == 404
    html = web.get('/phones/').get_data(as_text=True)
    assert html.count('data-click="stopLive(') == 1 and 'stopped' in html and running['url'] not in html
    assert web.post('/phones/live/999/stop').status_code == 404
    assert phone.app_.test_client().post(f"/phones/live/{done['id']}/stop").status_code in (302, 401)    # signed in only


def test_the_watch_stops_its_own_link_with_its_own_token(phone):
    """The Watch has a token of its own (POST /api/v1/devices/watch) and stops the link it started with it."""
    watch = phone.post('/api/v1/devices/watch', headers=phone.H).get_json()['token']
    W = {'Authorization': 'Bearer ' + watch}
    share = phone.post('/api/v1/live/share', json={'recording': 'watch-1', 'sport': 'Run'}, headers=W).get_json()
    assert phone.delete('/api/v1/live/share', json={'recording': 'watch-1'}, headers=W).get_json() == {'stopped': 1}
    assert phone.app_.test_client().get('/live/' + token_of(share['url'])).status_code == 404
