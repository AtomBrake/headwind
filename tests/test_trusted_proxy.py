"""X-Forwarded-* is believed only from a trusted proxy, so a direct client can't dodge the sign-in lockout."""
from services.trusted_proxy import TrustedProxyFix, parse


def _seen(networks, remote_addr, headers=None):
    got = {}

    def app(environ, start_response):
        got.update(environ)
        start_response('200 OK', [])
        return [b'']

    environ = {'REMOTE_ADDR': remote_addr, 'HTTP_HOST': 'internal:5001', 'wsgi.url_scheme': 'http',
               'REQUEST_METHOD': 'GET', 'PATH_INFO': '/', 'SERVER_NAME': 'x', 'SERVER_PORT': '5001'}
    for k, v in (headers or {}).items():
        environ['HTTP_' + k.upper().replace('-', '_')] = v
    TrustedProxyFix(app, networks)(environ, lambda *a: None)
    return got


FWD = {'X-Forwarded-For': '198.51.100.9', 'X-Forwarded-Proto': 'https', 'X-Forwarded-Host': 'headwind.example.com'}


def test_default_trusts_a_local_proxy():
    for proxy in ('127.0.0.1', '::1', '172.18.0.2', '192.168.1.10', '100.101.102.103', '::ffff:10.0.0.5'):
        env = _seen(parse(None), proxy, FWD)
        assert env['REMOTE_ADDR'] == '198.51.100.9', proxy
        assert env['wsgi.url_scheme'] == 'https'
        assert env['HTTP_HOST'] == 'headwind.example.com'


def test_default_ignores_forwarded_headers_from_a_public_client():
    env = _seen(parse(None), '203.0.113.50', FWD)
    assert env['REMOTE_ADDR'] == '203.0.113.50'
    assert env['wsgi.url_scheme'] == 'http'
    assert env['HTTP_HOST'] == 'internal:5001'


def test_explicit_list_replaces_the_default():
    nets = parse('203.0.113.7, 10.8.0.0/24')
    assert _seen(nets, '203.0.113.7', FWD)['REMOTE_ADDR'] == '198.51.100.9'
    assert _seen(nets, '10.8.0.20', FWD)['REMOTE_ADDR'] == '198.51.100.9'
    assert _seen(nets, '192.168.1.10', FWD)['REMOTE_ADDR'] == '192.168.1.10'


def test_none_trusts_nobody_and_bad_entries_are_skipped():
    assert _seen(parse('none'), '127.0.0.1', FWD)['REMOTE_ADDR'] == '127.0.0.1'
    assert len(parse('not-an-ip, 10.0.0.1')) == 1


def test_unparseable_peer_passes_through():
    assert _seen(parse(None), '', FWD)['REMOTE_ADDR'] == ''


def test_default_believes_a_direct_client_that_arrives_from_a_private_address():
    """The trade-off the instance-wide sign-in limit (routes/login.py, tests/test_login_lockout.py) covers: under Docker
    Desktop or the userland proxy, a client reaching the port directly can arrive from the bridge address, so it can claim
    a new address on every attempt."""
    for docker_peer in ('172.17.0.1', '192.168.65.1', '::ffff:172.17.0.1'):
        claimed = [_seen(parse(None), docker_peer, {'X-Forwarded-For': f'198.51.100.{i}'})['REMOTE_ADDR'] for i in range(3)]
        assert claimed == ['198.51.100.0', '198.51.100.1', '198.51.100.2'], docker_peer


def test_loopback_only_ignores_a_docker_bridge_peer():
    """TRUSTED_PROXIES=127.0.0.1,::1: a proxy on the same machine still works; the bridge address no longer can claim one."""
    nets = parse('127.0.0.1, ::1')
    assert _seen(nets, '127.0.0.1', FWD)['REMOTE_ADDR'] == '198.51.100.9'
    assert _seen(nets, '::1', FWD)['REMOTE_ADDR'] == '198.51.100.9'
    assert _seen(nets, '172.17.0.1', FWD)['REMOTE_ADDR'] == '172.17.0.1'
    assert _seen(nets, '::ffff:127.0.0.1', FWD)['REMOTE_ADDR'] == '198.51.100.9'      # IPv4-mapped loopback counts as loopback


def test_a_trusted_proxy_hands_on_only_the_last_hop():
    """One hop (x_for=1): a client can't pick its address by sending its own X-Forwarded-For through the proxy."""
    env = _seen(parse(None), '127.0.0.1', {'X-Forwarded-For': '203.0.113.66, 198.51.100.9'})
    assert env['REMOTE_ADDR'] == '198.51.100.9'
