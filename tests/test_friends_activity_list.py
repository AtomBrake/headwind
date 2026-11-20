"""The Friends choice in the dashboard's and the Activities page's rider buttons (?rider=friends, routes/dashboard.FRIENDS): every friend's
activities together, newest first, each row with its rider's avatar, and nothing on it to change them with. A rider who lives on this instance
but isn't a synced friend is never in it. Full app, throwaway DB."""
import pytest

import app as app_module
import config
import database
from services import credentials

#  id, rider, sport, start: Tom (1) is the owner, Sam (2) and Alex (3) are friends, Lee (4) lives here too but isn't one
ACTS = (('r1', 1, 'Ride', '2026-10-21T08:00:00'), ('s1', 2, 'Ride', '2026-10-19T08:00:00'), ('s2', 2, 'Run', '2026-10-20T08:00:00'),
        ('a1', 3, 'Ride', '2026-10-18T08:00:00'), ('l1', 4, 'Ride', '2026-10-17T08:00:00'))


class _NoThread:
    def __init__(self, *a, **kw): pass
    def start(self): pass


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config.Config, 'DATABASE', str(tmp_path / 't.db'))
    monkeypatch.setattr(app_module.threading, 'Thread', _NoThread)
    app = app_module.create_app()
    with app.app_context():
        db = database.get_db()
        db.execute("INSERT OR IGNORE INTO Settings (id) VALUES (1)")
        db.execute("INSERT INTO Rider (id, name, isDefault, avatarPath) VALUES (1, 'Tom', 1, NULL), (2, 'Sam', 0, 'sam.jpg'), (3, 'Alex', 0, NULL), "
                   "(4, 'Lee', 0, NULL)")
        db.execute("INSERT INTO Friend (id, name, url, token, riderId, lastSynced) VALUES (1, 'Sam', 'https://sam.example', 't', 2, '2026-10-21 08:00:00'), "
                   "(2, 'Alex', 'https://alex.example', 't', 3, '2026-10-21 08:00:00')")
        for aid, rider, sport, start in ACTS:
            db.execute("INSERT INTO Activity (id, name, type, sportType, riderId, startDate, startDateLocal, distance, movingTime, elapsedTime, rawData) "
                       "VALUES (?, ?, ?, ?, ?, ?, ?, 20000, 3600, 3600, '{}')", [aid, f'Act {aid}', sport, sport, rider, start, start])
        db.commit()
        av = credentials.auth_version()
    c = app.test_client()
    with c.session_transaction() as s:
        s['logged_in'] = True
        s['av'] = av
    return c


def listed(page):
    """The activities a page lists, in its order."""
    return sorted((a for a, *_ in ACTS if f'/activities/{a}"' in page), key=lambda a: page.index(f'/activities/{a}"'))


@pytest.mark.parametrize('path', ['/dashboard', '/activities'])
def test_friends_lists_every_friends_activities_newest_first(client, path):
    page = client.get(path + '?rider=friends').get_data(as_text=True)
    assert listed(page) == ['s2', 's1', 'a1']                   # not yours, and not Lee's: Lee lives here but isn't a friend
    assert 'avatars/sam.jpg' in page and 'title="Alex">A</span>' in page      # each row with its rider's avatar
    assert "Friends' activities" in page


@pytest.mark.parametrize('path', ['/dashboard', '/activities'])
def test_the_friends_button_comes_once_two_friends_have_synced(client, path):
    page = client.get(path).get_data(as_text=True)
    assert f'href="{path}?rider=friends"' in page
    with client.application.app_context():
        database.get_db().execute('DELETE FROM Friend WHERE id=2')
        database.get_db().commit()
    page = client.get(path).get_data(as_text=True)
    assert 'rider=friends' not in page                          # one friend: their own button is the same list


def test_nothing_on_the_friends_list_can_be_changed(client):
    for q in ('', '&q=Act'):                                     # the history tree, and a search's flat list
        page = client.get('/activities?rider=friends' + q).get_data(as_text=True)
        assert listed(page) == ['s2', 's1', 'a1']
        assert 'data-pick-toggle' not in page and 'id="bulkBar"' not in page
        assert '/activities/bulk-sport' not in page             # "change the type of all results"
        assert 'Add an activity by hand' not in page
    page = client.get('/activities?q=Act').get_data(as_text=True)           # your own list keeps them
    assert 'data-pick-toggle' in page and '/activities/bulk-sport' in page and 'Add an activity by hand' in page


def test_a_search_and_its_totals_cover_the_friends_together(client):
    page = client.get('/activities?rider=friends&q=Act').get_data(as_text=True)
    assert '3 results' in page and '3 activities' in page
    page = client.get('/activities?rider=friends&only=Run').get_data(as_text=True)
    assert listed(page) == ['s2']
    assert 'value="Run"' in page                                 # the sport filter offers what the friends have between them


def test_a_month_opened_later_is_the_friends_too(client):
    page = client.get('/dashboard/history?rider=friends&from=2026-10-01&to=2026-10-31&list=/activities').get_data(as_text=True)
    assert listed(page) == ['s2', 's1', 'a1']


def test_friends_with_none_synced_is_your_own_list(client):
    with client.application.app_context():
        database.get_db().execute('DELETE FROM Friend')
        database.get_db().commit()
    page = client.get('/activities?rider=friends').get_data(as_text=True)
    assert listed(page) == ['r1'] and "Tom&#39;s activities" in page
