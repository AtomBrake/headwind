"""MQTT over TLS (Settings → MQTT): services/mqtt.connection reads the settings, and the publisher, the live-ride sender, the command
listener and the Settings page's connection test all use them. A small TLS broker on 127.0.0.1, with a certificate from a throwaway CA, stands in
for a real one: enough MQTT for CONNECT, PUBLISH (QoS 0 and 1), SUBSCRIBE, PINGREQ and DISCONNECT."""
import datetime
import ipaddress
import socket
import ssl
import time
from threading import Thread          # before the app fixture swaps threading.Thread out

import pytest
from flask import Flask

import app as app_module
import config
import database
from services import credentials, logs, mqtt, mqtt_commands


# ── A throwaway CA and a broker certificate for 127.0.0.1 ─────────────────────────────

def _certs(tmp):
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID
    now = datetime.datetime.now(datetime.timezone.utc)

    def cert(subject, key, issuer, issuer_key, ca, san=None):
        b = (x509.CertificateBuilder().subject_name(subject).issuer_name(issuer).public_key(key.public_key())
             .serial_number(x509.random_serial_number()).not_valid_before(now - datetime.timedelta(minutes=5))
             .not_valid_after(now + datetime.timedelta(days=1))
             .add_extension(x509.BasicConstraints(ca=ca, path_length=None), critical=True))
        if ca:
            b = b.add_extension(x509.KeyUsage(digital_signature=True, key_cert_sign=True, crl_sign=True, content_commitment=False,
                                              key_encipherment=False, data_encipherment=False, key_agreement=False,
                                              encipher_only=False, decipher_only=False), critical=True)
            b = b.add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
        else:
            b = b.add_extension(x509.SubjectAlternativeName(san), critical=False)
            b = b.add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(issuer_key.public_key()), critical=False)
            b = b.add_extension(x509.ExtendedKeyUsage([x509.oid.ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
        return b.sign(issuer_key, hashes.SHA256())

    ca_key, srv_key = ec.generate_private_key(ec.SECP256R1()), ec.generate_private_key(ec.SECP256R1())
    ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'Headwind test CA')])
    ca = cert(ca_name, ca_key, ca_name, ca_key, True)
    srv = cert(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, '127.0.0.1')]), srv_key, ca_name, ca_key, False,
               [x509.IPAddress(ipaddress.ip_address('127.0.0.1'))])
    pem = serialization.Encoding.PEM
    (tmp / 'ca.crt').write_bytes(ca.public_bytes(pem))
    (tmp / 'broker.crt').write_bytes(srv.public_bytes(pem))
    (tmp / 'broker.key').write_bytes(srv_key.private_bytes(pem, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    return str(tmp / 'ca.crt')


# ── The broker ──────────────────────────────────────────────────────────────────────

def _read(conn, n):
    out = b''
    while len(out) < n:
        got = conn.recv(n - len(out))
        if not got:
            raise ConnectionError
        out += got
    return out


def _str(body, i):
    n = int.from_bytes(body[i:i + 2], 'big')
    return body[i + 2:i + 2 + n].decode(), i + 2 + n


class Broker:
    def __init__(self, tmp):
        self.ca = _certs(tmp)
        self.ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        self.ctx.load_cert_chain(str(tmp / 'broker.crt'), str(tmp / 'broker.key'))
        self.sock = socket.socket()
        self.sock.bind(('127.0.0.1', 0))
        self.sock.listen()
        self.port = self.sock.getsockname()[1]
        self.logins, self.published, self.subscribed, self.handshakes = [], [], [], 0
        Thread(target=self._accept, daemon=True).start()

    def _accept(self):
        while True:
            try:
                raw, _ = self.sock.accept()
            except OSError:
                return
            Thread(target=self._serve, args=(raw,), daemon=True).start()

    def _serve(self, raw):
        try:
            conn = self.ctx.wrap_socket(raw, server_side=True)
        except (ssl.SSLError, OSError):
            raw.close()                                 # the client turned the certificate down, or spoke plain MQTT
            return
        self.handshakes += 1
        try:
            while True:
                head = _read(conn, 1)[0]
                length, mult = 0, 1
                while True:
                    b = _read(conn, 1)[0]
                    length += (b & 127) * mult
                    mult *= 128
                    if not b & 128:
                        break
                body = _read(conn, length)
                kind = head >> 4
                if kind == 1:                           # CONNECT: protocol name, level, flags, keep-alive, then client id, user, password
                    _, i = _str(body, 0)
                    flags, i = body[i + 1], i + 4
                    _, i = _str(body, i)
                    user = pw = None
                    if flags & 0x80:
                        user, i = _str(body, i)
                    if flags & 0x40:
                        pw, i = _str(body, i)
                    self.logins.append((user, pw))
                    conn.sendall(b'\x20\x02\x00\x00')
                elif kind == 3:                         # PUBLISH
                    topic, i = _str(body, 0)
                    self.published.append(topic)
                    if (head >> 1) & 3:
                        conn.sendall(b'\x40\x02' + body[i:i + 2])
                elif kind == 8:                         # SUBSCRIBE
                    topic, _ = _str(body, 2)
                    self.subscribed.append(topic)
                    conn.sendall(b'\x90\x03' + body[:2] + b'\x01')
                elif kind == 12:                        # PINGREQ
                    conn.sendall(b'\xd0\x00')
                elif kind == 14:                        # DISCONNECT
                    return
        except (ConnectionError, OSError, ssl.SSLError):
            pass
        finally:
            conn.close()

    def wait(self, what, n):
        """The broker's thread records what arrives a moment after the client has moved on."""
        for _ in range(50):
            if len(getattr(self, what)) >= n:
                break
            time.sleep(0.05)
        return getattr(self, what)

    def close(self):
        self.sock.close()


@pytest.fixture
def broker(tmp_path):
    b = Broker(tmp_path)
    yield b
    b.close()


def _settings(broker, tls=True, ca=True, port=None):
    return {'mqttHost': '127.0.0.1', 'mqttPort': broker.port if port is None else port, 'mqttUser': 'ha', 'mqttPassword': 's3cret',
            'mqttTls': 1 if tls else 0, 'mqttCaFile': broker.ca if ca else ''}


# ── The settings ───────────────────────────────────────────────────────────────────

def test_connection_from_settings():
    plain = {'mqttHost': ' ha.local ', 'mqttPort': None, 'mqttUser': '', 'mqttPassword': None, 'mqttTls': 0, 'mqttCaFile': None}
    assert mqtt.connection(plain) == ('ha.local', 1883, None, None)
    assert mqtt.connection({**plain, 'mqttTls': 1}) == ('ha.local', 8883, None, {'ca_certs': None})
    assert mqtt.connection({**plain, 'mqttTls': 1, 'mqttPort': 9000, 'mqttCaFile': ' /data/ca.crt ', 'mqttUser': 'u', 'mqttPassword': 'p'}) == \
        ('ha.local', 9000, {'username': 'u', 'password': 'p'}, {'ca_certs': '/data/ca.crt'})
    assert mqtt.connection({**plain, 'mqttHost': ''}) is None and mqtt.connection(None) is None


# ── Publishing, the live-ride sender and the command listener ─────────────────────────────

def test_publishes_over_tls_with_the_ca_file(broker):
    host, port, auth, tls = mqtt.connection(_settings(broker))
    mqtt._broker_send([{'topic': 'headwind/a', 'payload': '1', 'qos': 1}, {'topic': 'headwind/b', 'payload': '2'}], host, port, auth, tls)
    assert broker.wait('published', 2) == ['headwind/a', 'headwind/b'] and broker.logins == [('ha', 's3cret')]
    assert tls == {'ca_certs': broker.ca}                          # paho pops from the dict it's given: ours is left as it was


def test_an_unknown_certificate_is_refused(broker):
    with pytest.raises(ssl.SSLCertVerificationError):
        mqtt._broker_send([{'topic': 'headwind/a', 'payload': '1'}], *mqtt.connection(_settings(broker, ca=False)))
    assert broker.published == [] and broker.logins == []          # the password never went out


def test_command_listener_subscribes_over_tls(broker):
    client = mqtt_commands._make_client(object(), *mqtt.connection(_settings(broker)))
    try:
        broker.wait('subscribed', 1)
    finally:
        client.loop_stop()
        client.disconnect()
    assert broker.subscribed == [mqtt_commands.WATER_TOPIC] and broker.logins == [('ha', 's3cret')]


# ── Settings → MQTT ────────────────────────────────────────────────────────────────

class _NoThread:
    def __init__(self, *a, **kw): pass
    def start(self): pass


@pytest.fixture
def client(tmp_path, monkeypatch):
    path = str(tmp_path / 't.db')
    pre = Flask('pre')
    pre.config['DATABASE'] = path
    with pre.app_context():
        database.migrate_db()
        db = database.get_db()
        db.execute('INSERT OR IGNORE INTO Settings (id) VALUES (1)')
        db.execute("INSERT INTO Rider (id, name, isDefault) VALUES (1, 'Rider', 1)")      # set up: no redirect to the wizard
        db.commit()
    monkeypatch.delenv('LOG_DIR', raising=False)
    monkeypatch.setattr(config.Config, 'DATABASE', path)
    monkeypatch.setattr(app_module.threading, 'Thread', _NoThread)
    app = app_module.create_app()
    monkeypatch.setattr(app_module.threading, 'Thread', Thread)     # the start-up threads stay off; paho's loop needs a real one
    with app.app_context():
        av = credentials.auth_version()
    c = app.test_client()
    with c.session_transaction() as s:
        s['logged_in'] = True
        s['av'] = av
    c.app_ = app
    yield c
    logs.setup()


def _saved(client):
    with client.app_.app_context():
        return dict(database.get_db().execute('SELECT mqttHost, mqttPort, mqttTls, mqttCaFile FROM Settings WHERE id=1').fetchone())


def test_settings_card_saves_tls(client, tmp_path):
    ca = tmp_path / 'ca.crt'
    ca.write_text('x')
    card = {'mqttHost': 'ha.local', 'mqttPort': '', 'mqttUser': '', 'mqttPassword': '', 'mqttTls': '1', 'mqttCaFile': str(ca)}
    client.post('/settings/', data=card)
    assert _saved(client) == {'mqttHost': 'ha.local', 'mqttPort': 8883, 'mqttTls': 1, 'mqttCaFile': str(ca)}
    client.post('/settings/', data={'units': 'metric', 'mqttHost': 'ha.local', 'mqttPort': '8883'})     # another card: TLS stays as it was
    assert _saved(client)['mqttTls'] == 1
    page = client.get('/settings/').get_data(as_text=True)
    assert 'id="mqttTls" checked' in page and f'value="{ca}"' in page
    client.post('/settings/', data={**card, 'mqttTls': None, 'mqttPort': ''})                       # unticked: a box that posts nothing
    assert _saved(client)['mqttTls'] == 0 and _saved(client)['mqttPort'] == 1883
    r = client.post('/settings/', data={**card, 'mqttCaFile': '/no/such/ca.crt'}, follow_redirects=True)
    assert 'There is no CA file at /no/such/ca.crt on this server' in r.get_data(as_text=True)


def test_settings_connection_test(client, broker):
    form = {'mqttHost': '127.0.0.1', 'mqttPort': str(broker.port), 'mqttUser': 'ha', 'mqttPassword': 's3cret', 'mqttTls': '1', 'mqttCaFile': broker.ca}
    assert client.post('/settings/test-mqtt', data=form).get_json() == {'ok': True}
    r = client.post('/settings/test-mqtt', data={**form, 'mqttCaFile': ''})
    assert r.status_code == 400 and "certificate could not be verified" in r.get_json()['error']
    r = client.post('/settings/test-mqtt', data={**form, 'mqttCaFile': '/no/such/ca.crt'})
    assert r.get_json()['error'] == 'There is no CA file at /no/such/ca.crt on this server'
    assert client.post('/settings/test-mqtt', data={**form, 'mqttTls': ''}).status_code == 400      # plain MQTT to a TLS port
    assert broker.logins == [('ha', 's3cret')]                      # only the connection that checked the certificate logged in


def test_publishers_read_tls_from_settings(client, broker):
    with client.app_.app_context():
        db = database.get_db()
        db.execute('UPDATE Settings SET mqttHost=?, mqttPort=?, mqttUser=?, mqttTls=1, mqttCaFile=? WHERE id=1',
                   ['127.0.0.1', broker.port, 'ha', broker.ca])
        db.commit()
        assert mqtt.broker() == ('127.0.0.1', broker.port, {'username': 'ha', 'password': ''}, {'ca_certs': broker.ca})
        from services import live
        assert live._connection() == mqtt.broker()
        mqtt.push_gear_alert([{'riderId': None, 'text': 'Chain worn'}])
    assert broker.wait('published', 1) == [f'{mqtt._prefix()}/new_ride']
