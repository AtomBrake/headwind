"""services/whose.py: the one place that decides whose data a request is about (docs/MULTI-USER-PLAN.md, release A1). rider_id() is the owner
for now and raises outside a request; viewable(want) gives today's answers for ?rider=N, a form's rider and the dashboard's ?rider=friends.
And a guard: no owner lookup of its own creeps back into routes/ or services/. Full app, throwaway DB."""
import io
import os
import re
import tokenize

import pytest

import app as app_module
import config
import database
from services import whose

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class _NoThread:
    def __init__(self, *a, **kw): pass
    def start(self): pass


@pytest.fixture
def app(tmp_path, monkeypatch):
    """Tom (1) is the owner, Sam (2) a friend synced here, Lee (3) another rider who lives here: two local riders, so multi-rider mode."""
    monkeypatch.delenv('HEADWIND_MULTI_RIDER', raising=False)
    monkeypatch.setattr(config.Config, 'DATABASE', str(tmp_path / 't.db'))
    monkeypatch.setattr(app_module.threading, 'Thread', _NoThread)
    a = app_module.create_app()
    with a.app_context():
        db = database.get_db()
        db.execute('INSERT OR IGNORE INTO Settings (id) VALUES (1)')
        db.execute("INSERT INTO Rider (id, name, isDefault) VALUES (1, 'Tom', 1), (2, 'Sam', 0), (3, 'Lee', 0)")
        db.execute("INSERT INTO Friend (id, name, url, token, riderId) VALUES (1, 'Sam', 'https://sam.example', 't', 2)")
        db.commit()
    return a


@pytest.fixture
def single(monkeypatch):
    """Single-rider mode whatever the riders say (services/rider_mode.multi_rider, and gear's copy of it)."""
    import routes.gear  # noqa: F401  (so it can be patched)
    monkeypatch.setattr('services.rider_mode.multi_rider', lambda: False)
    monkeypatch.setattr('routes.gear.multi_rider', lambda: False)


def _view(app, want, friends=False):
    with app.test_request_context():
        return whose.viewable(want, friends=friends)


def test_in_a_request_it_is_the_owner(app):
    with app.test_request_context():
        assert whose.rider_id() == 1
        assert whose.rider()['name'] == 'Tom'


def test_outside_a_request_it_raises(app):
    """A background caller that was missed fails loudly, instead of quietly working on the owner's data."""
    with app.app_context():
        with pytest.raises(whose.OutsideRequest):
            whose.rider_id()
        with pytest.raises(whose.OutsideRequest):
            whose.rider()
        with pytest.raises(whose.OutsideRequest):
            whose.viewable('1')


def test_no_rider_asked_for_is_your_own(app):
    for want in (None, '', '  '):
        assert _view(app, want) == (1, whose.OWN, (1,))
    assert _view(app, '1') == (1, whose.OWN, (1,))
    assert _view(app, 1) == (1, whose.OWN, (1,))


def test_another_local_rider_in_multi_rider_mode(app):
    assert _view(app, '3') == (3, whose.LOCAL, (3,))


def test_another_local_rider_in_single_rider_mode_is_not_shown(app, single):
    assert _view(app, '3') is None
    assert _view(app, '1') == (1, whose.OWN, (1,))


def test_a_friends_rider_is_read_only_in_either_mode(app, monkeypatch):
    assert _view(app, '2') == (2, whose.FRIEND, (2,))
    monkeypatch.setattr('services.rider_mode.multi_rider', lambda: False)
    assert _view(app, '2') == (2, whose.FRIEND, (2,))


def test_no_such_rider_or_not_a_number(app):
    for want in ('99', 'abc', '1.5', 'friends'):
        assert _view(app, want) is None, want


def test_rider_friends_is_every_friend_together(app):
    assert _view(app, 'friends', friends=True) == ('friends', whose.FRIENDS, (2,))
    with app.app_context():
        database.get_db().execute('DELETE FROM Friend')
        database.get_db().commit()
    assert _view(app, 'friends', friends=True) is None          # none synced: the page shows your own instead
    assert _view(app, '2', friends=True) == (2, whose.LOCAL, (2,))   # no Friend row: Sam is just another rider here now


def test_gear_is_yours_or_a_local_riders_never_a_friends(app):
    """Riders only edit their own gear; another local rider's is the admin's case (multi-rider mode). A friend's rider has no gear here."""
    from routes import gear
    for want, rid in (('', 1), ('3', 3), ('2', 1), ('99', 1)):
        with app.test_request_context(f'/gear?rider={want}'):
            assert gear._rider_id() == rid, want
        with app.test_request_context('/gear/bike/save', method='POST', data={'rider': want}):
            assert gear._rider_id() == rid, want
    with app.test_request_context('/gear'):
        assert [r['id'] for r in gear._pickable()] == [1, 3]


def test_gear_in_single_rider_mode_is_always_yours(app, single):
    from routes import gear
    with app.test_request_context('/gear?rider=3'):
        assert gear._rider_id() == 1 and gear._pickable() == []


def test_the_dashboard_falls_back_to_your_own(app):
    from routes.dashboard import _riders
    for want, rid in (('3', 3), ('2', 2), ('99', 1), ('abc', 1), ('friends', 1)):
        with app.test_request_context(f'/dashboard?rider={want}'):
            _, active, got = _riders({'rider': want})
            assert got == rid and active['id'] == rid, want
    with app.test_request_context('/dashboard?rider=friends'):
        _, active, got = _riders({'rider': 'friends'}, friends=True)
        assert got is None and active['id'] == 'friends' and active['ids'] == [2]


# What may still say which rider is the owner: whose itself, and the two it asks
OWNER_LOOKUP_OK = {'services/whose.py', 'services/rider_mode.py', 'services/page_facts.py'}
OWNER_LOOKUP = re.compile(r'isDefault\s*=\s*1', re.IGNORECASE)
FIRST_BY_DEFAULT = re.compile(r'isDefault\s+DESC.*LIMIT\s+1', re.IGNORECASE | re.DOTALL)     # the first rider, owner first: within one string
# The routes that may ask for the instance's owner by name: a friend's Headwind reading the feed, where nobody here is signed in
OWNER_ID_OK = {'routes/friends.py'}


def _tokens(path):
    with open(path, encoding='utf-8') as f:
        return list(tokenize.generate_tokens(io.StringIO(f.read()).readline))


def _code(path):
    """The file's code without its comments (a comment may name the query it warns about), as one string."""
    return ' '.join(t.string for t in _tokens(path) if t.type != tokenize.COMMENT)


def _looks_up_owner(path):
    strings = [t.string for t in _tokens(path) if t.type == tokenize.STRING or tokenize.tok_name[t.type] == 'FSTRING_MIDDLE']
    return bool(OWNER_LOOKUP.search(_code(path))) or any(FIRST_BY_DEFAULT.search(s) for s in strings)


def _sources(*dirs):
    for d in dirs:
        for name in sorted(os.listdir(os.path.join(ROOT, d))):
            if name.endswith('.py'):
                yield f'{d}/{name}', os.path.join(ROOT, d, name)


def test_no_owner_lookup_outside_whose():
    """A route or service that picks the owner itself (isDefault=1, or the first rider by isDefault) would keep showing the owner's data once
    there are logins: it asks services/whose.py (a request) or is handed its rider (background work) instead."""
    found = [rel for rel, path in _sources('routes', 'services') if rel not in OWNER_LOOKUP_OK and _looks_up_owner(path)]
    assert found == [], f'Owner looked up outside services/whose.py: {found}'


def test_routes_ask_whose_not_for_the_owner():
    """In a route, "the owner" is whose.rider_id() (it becomes the signed-in user's). Only what really is the instance's own asks for it."""
    found = [rel for rel, path in _sources('routes') if rel not in OWNER_ID_OK and 'owner_rider_id' in _code(path)]
    assert found == [], f'Routes asking for the owner rather than whose: {found}'


def test_the_guard_sees_a_lookup():
    assert OWNER_LOOKUP.search("query_db('SELECT id FROM Rider WHERE isDefault = 1 LIMIT 1')")
    assert FIRST_BY_DEFAULT.search("SELECT id FROM Rider ORDER BY isDefault DESC, id LIMIT 1")
    assert not FIRST_BY_DEFAULT.search("SELECT id, name FROM Rider ORDER BY isDefault DESC, name")
    assert not _looks_up_owner(os.path.join(ROOT, 'routes', 'setup.py'))                # named in a comment only
    assert _looks_up_owner(os.path.join(ROOT, 'services', 'rider_mode.py'))             # and it does see the real thing
