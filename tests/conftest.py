import pytest

from services import tz


@pytest.fixture(autouse=True)
def _home_zone(monkeypatch):
    """The tests were written for Europe/London (BST cases and all): make that the server's zone, whatever the machine running them uses."""
    monkeypatch.setenv('TZ', 'Europe/London')
    tz.forget()
    yield
    tz.forget()


@pytest.fixture
def backup_zip(monkeypatch):
    """backup_zip(client, secrets=False) -> the download's response: Make backup on Settings, with the background job run there and then
    (services/downloads.py)."""
    from services import downloads
    monkeypatch.setattr(downloads, '_spawn', lambda fn: fn())
    monkeypatch.setattr(downloads, '_expire_later', lambda kind, path: None)
    monkeypatch.setattr(downloads, '_jobs', {})

    def make(client, secrets=False):
        assert client.post('/settings/backup/export', data={'secrets': '1'} if secrets else {}).status_code == 302
        status = client.get('/settings/backup/status').get_json()
        assert status['state'] == 'ready', status
        return client.get(status['url'])
    return make


@pytest.fixture(autouse=True)
def _no_friend_sync_left_running():
    """A test that starts a friend sync with threads stubbed out (Sync, Add) leaves the friend marked as syncing: free it for the next test."""
    yield
    import sys
    friends = sys.modules.get('routes.friends')
    if friends:
        friends._syncing.clear()
        friends._last.clear()
