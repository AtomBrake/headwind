"""Email, through the mail server set in Settings → Email (SMTP): how Headwind reaches people who don't use it. For now that's the live
tracking link sent to the rider's contacts (services/contacts.py); later the safety alert. A text message would need a paid gateway, so
there's none.

One send opens one connection for all its messages, with a timeout, so a mail server that has gone away fails them all in TIMEOUT_S
instead of holding up the job. Each message's outcome is its own: a server that refuses one address still sends the rest.

The password is kept sealed (services/vault.py), as the other saved passwords are."""
import logging
import re
import smtplib
import socket
import ssl
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid

log = logging.getLogger(__name__)

SECURITY = ('starttls', 'ssl', 'none')     # STARTTLS on the submission port, TLS from the start, or neither (a relay on the home network)
PORTS = {'starttls': 587, 'ssl': 465, 'none': 25}
TIMEOUT_S = 20
SETTINGS_PATH = '/settings#email'
COLUMNS = ('smtpHost', 'smtpPort', 'smtpSecurity', 'smtpUser', 'smtpPassword', 'smtpFrom')

# Good enough to catch a typing slip; the mail server is the judge of the rest.
_ADDRESS = re.compile(r'^[^@\s<>",;]+@[^@\s<>",;]+\.[^@\s<>",;.]+$')


def clean_address(value):
    """An email address as kept (trimmed), or None when it can't be one."""
    value = (value or '').strip()
    return value if len(value) <= 254 and _ADDRESS.match(value) else None


def config(db, row=None):
    """The saved settings, as a dict: {host, port, security, user, password, sender}. Host and sender are '' when not set. `row`: the
    Settings row, when the caller has read it already."""
    if row is None:
        row = db.execute(f"SELECT {', '.join(COLUMNS)} FROM Settings WHERE id=1").fetchone()       # the columns: database step 12
    get = (lambda c: row[c] if row is not None else None)
    security = get('smtpSecurity') if get('smtpSecurity') in SECURITY else 'starttls'
    return {'host': (get('smtpHost') or '').strip(), 'port': get('smtpPort') or PORTS[security], 'security': security,
            'user': (get('smtpUser') or '').strip(), 'password': get('smtpPassword') or '', 'sender': (get('smtpFrom') or '').strip()}


def problem(cfg):
    """Why email can't be sent with these settings, fit to show, or None when it can."""
    if not cfg['host']:
        return 'Email isn\'t set up: give Headwind a mail server in Settings → Email.'
    if not clean_address(cfg['sender']):
        return 'Email has no address to send from: set one in Settings → Email.'
    return None


def ready(db):
    """(True, None) when email can be sent, else (False, why)."""
    why = problem(config(db))
    return why is None, why


def message(cfg, to, subject, text, sender_name=None):
    m = EmailMessage()
    m['From'] = formataddr((sender_name or 'Headwind', cfg['sender']))
    m['To'] = to
    m['Subject'] = subject
    m['Date'] = formatdate(localtime=True)
    m['Message-ID'] = make_msgid(domain=cfg['sender'].rsplit('@', 1)[-1])
    m['Auto-Submitted'] = 'auto-generated'          # so an away message isn't sent back to an address nobody reads
    m.set_content(text)
    return m


def _connect(cfg):
    context = ssl.create_default_context()
    if cfg['security'] == 'ssl':
        server = smtplib.SMTP_SSL(cfg['host'], int(cfg['port']), timeout=TIMEOUT_S, context=context)
    else:
        server = smtplib.SMTP(cfg['host'], int(cfg['port']), timeout=TIMEOUT_S)
        if cfg['security'] == 'starttls':
            server.starttls(context=context)
    if cfg['user']:
        server.login(cfg['user'], cfg['password'])
    return server


def _why(e, cfg):
    """A connection's failure, in words to show."""
    if isinstance(e, smtplib.SMTPAuthenticationError):
        return 'The mail server refused the user name or password (Settings → Email).'
    if isinstance(e, ssl.SSLCertVerificationError):
        return f"The mail server's certificate could not be verified ({e.verify_message})."
    if isinstance(e, ssl.SSLError):
        return 'The secure connection to the mail server failed: is the security setting right for that port (Settings → Email)?'
    if isinstance(e, smtplib.SMTPNotSupportedError):
        return "The mail server doesn't offer STARTTLS or a login on that port (Settings → Email)."
    if isinstance(e, (socket.timeout, TimeoutError)):
        return f"The mail server ({cfg['host']}) didn't answer within {TIMEOUT_S} s."
    if isinstance(e, (socket.gaierror, ConnectionError, OSError)) and not isinstance(e, smtplib.SMTPException):
        return f"Couldn't reach the mail server ({cfg['host']}:{cfg['port']}): {getattr(e, 'strerror', None) or e}."
    return f'The mail server said: {e}'[:300]


def send(cfg, messages):
    """Send each of these EmailMessages through the server in cfg, over one connection. Returns one entry per message: None when the server
    took it, else why not, in words to show."""
    if not messages:
        return []
    why = problem(cfg)
    if why:
        return [why] * len(messages)
    try:
        server = _connect(cfg)
    except Exception as e:                  # anything at all: each message then says why, and the job ends normally
        log.warning('Could not connect to the mail server %s:%s', cfg['host'], cfg['port'], exc_info=True)
        return [_why(e, cfg)] * len(messages)
    out = []
    try:
        for m in messages:
            try:
                server.send_message(m)
                out.append(None)
            except smtplib.SMTPRecipientsRefused:
                out.append('The mail server would not send to this address.')
            except smtplib.SMTPServerDisconnected as e:      # gone mid-way: the rest can't go either
                out.append(_why(e, cfg))
                out += [_why(e, cfg)] * (len(messages) - len(out))
                log.warning('The mail server %s closed the connection', cfg['host'], exc_info=True)
                return out
            except (smtplib.SMTPException, OSError) as e:
                log.warning('The mail server %s refused a message', cfg['host'], exc_info=True)
                out.append(_why(e, cfg))
    finally:
        try:
            server.quit()
        except Exception:
            pass
    return out
