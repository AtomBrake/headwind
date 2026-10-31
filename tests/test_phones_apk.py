"""The sideloaded APK lives beside the database unless HEADWIND_APK says otherwise."""
import pytest
from flask import Flask


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.delenv('HEADWIND_APK', raising=False)
    app = Flask(__name__)
    app.config['DATABASE'] = str(tmp_path / 'bike.db')
    from routes.phones import bp
    app.register_blueprint(bp)
    return app.test_client()


def test_no_apk_is_a_404(client):
    assert client.get('/phones/app.apk').status_code == 404


def test_apk_beside_the_database_is_served(client, tmp_path):
    (tmp_path / 'headwind.apk').write_bytes(b'PK apk')
    r = client.get('/phones/app.apk')
    assert r.status_code == 200 and r.data == b'PK apk'


def test_env_override(client, tmp_path, monkeypatch):
    other = tmp_path / 'elsewhere.apk'
    other.write_bytes(b'other')
    monkeypatch.setenv('HEADWIND_APK', str(other))
    assert client.get('/phones/app.apk').data == b'other'
