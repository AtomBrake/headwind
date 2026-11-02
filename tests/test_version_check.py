"""Check for update: the newest release tag on this fork's repository against the version running, not upstream's Docker Hub image."""
import pytest
from flask import Flask

from routes import settings


def test_version_order():
    k = settings.version_key
    assert k('v0.7.37-beta') > k('0.7.36-beta') > k('0.7.9-beta')        # numbers, not text
    assert k('0.8.0') > k('0.8.0-beta')                                    # a release after its beta
    assert k('latest') is None and k('') is None


class Reply:
    def __init__(self, body):
        self.body = body

    def raise_for_status(self):
        pass

    def json(self):
        return self.body


@pytest.fixture
def check(monkeypatch):
    app = Flask(__name__)

    def run(tags, version='0.7.36-beta'):
        monkeypatch.setattr('version.__version__', version)
        monkeypatch.setattr('requests.get', lambda url, **kw: Reply([{'name': t} for t in tags]))
        with app.test_request_context():
            r = settings.version_check()
            return r[0].get_json() if isinstance(r, tuple) else r.get_json()
    return run


def test_a_newer_tag_is_an_update(check):
    d = check(['v0.7.35-beta', 'v0.7.37-beta', 'v0.7.36-beta', 'not-a-version'])
    assert d == {'latest': '0.7.37-beta', 'current': '0.7.36-beta', 'newer': True}


def test_the_newest_tag_is_up_to_date(check):
    assert check(['v0.7.36-beta', 'v0.7.10-beta'])['newer'] is False


def test_no_tags_is_an_error(check):
    assert 'error' in check([])
