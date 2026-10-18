import pytest

from services import tz


@pytest.fixture(autouse=True)
def _home_zone(monkeypatch):
    """The tests were written for Europe/London (BST cases and all): make that the server's zone, whatever the machine running them uses."""
    monkeypatch.setenv('TZ', 'Europe/London')
    tz.forget()
    yield
    tz.forget()
