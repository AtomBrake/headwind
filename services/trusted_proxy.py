"""Honour X-Forwarded-* only from a reverse proxy we trust. A client reaching the port directly could otherwise claim a new
address on every sign-in attempt and never hit the login lockout.

TRUSTED_PROXIES (env) is a comma-separated list of addresses / networks the proxy connects from, or "none". Unset, any
loopback or private address is trusted: a proxy on the same machine, LAN, Docker network or a local tunnel (cloudflared,
Tailscale Serve). Set it if your proxy reaches Headwind from a public address."""
import ipaddress
import logging
import os

from werkzeug.middleware.proxy_fix import ProxyFix

log = logging.getLogger(__name__)

PRIVATE = ['127.0.0.0/8', '::1/128', '10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16', '100.64.0.0/10',
           'fc00::/7', 'fe80::/10', '169.254.0.0/16']


def parse(value):
    """TRUSTED_PROXIES -> list of networks. None/'' means the private default; 'none' means trust nobody."""
    value = (value or '').strip()
    if not value:
        return [ipaddress.ip_network(n) for n in PRIVATE]
    if value.lower() == 'none':
        return []
    nets = []
    for part in value.split(','):
        part = part.strip()
        if not part:
            continue
        try:
            nets.append(ipaddress.ip_network(part, strict=False))
        except ValueError:
            log.warning('TRUSTED_PROXIES: ignoring %r (not an address or network)', part)
    return nets


def _peer(addr):
    try:
        ip = ipaddress.ip_address((addr or '').split('%')[0])
    except ValueError:
        return None
    if ip.version == 6 and ip.ipv4_mapped:
        return ip.ipv4_mapped
    return ip


class TrustedProxyFix:
    """ProxyFix (one hop) for requests whose socket peer is a trusted proxy; everything else passes through untouched."""

    def __init__(self, app, networks):
        self.app = app
        self.networks = networks
        self.fixed = ProxyFix(app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

    def __call__(self, environ, start_response):
        ip = _peer(environ.get('REMOTE_ADDR'))
        if ip is not None and any(ip.version == n.version and ip in n for n in self.networks):
            return self.fixed(environ, start_response)
        return self.app(environ, start_response)


def wrap(app):
    return TrustedProxyFix(app, parse(os.environ.get('TRUSTED_PROXIES')))
