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
