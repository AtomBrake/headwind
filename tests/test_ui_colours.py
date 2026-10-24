"""Every colour comes from the variables in static/css/style.css: none written into templates, page scripts or gear.css.
Markup uses var(--x); Chart.js, Leaflet and canvas take cssVar('--x') (templates/base.html)."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FILES = sorted([*ROOT.glob('templates/**/*.html'), *ROOT.glob('static/js/*.js'), ROOT / 'static/css/gear.css'])

HEX = re.compile(r'(?<![&\w])#(?:[0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{3,4})\b')   # not &#8592; entities
RGB = re.compile(r'\brgba?\(\s*\d')                                                      # rgb(1,2,3); not rgba(' + r + ...
ALLOWED = (
    re.compile(r'<meta name="theme-color" content="#[0-9a-f]{6}">'),      # read by the browser chrome, before any CSS
)


def _code(f):
    return re.sub(r'(?m)^\s*//.*$', '', f.read_text())                        # a JS comment line may name a colour or a variable


def _colours(text):
    for pattern in ALLOWED:
        text = pattern.sub('', text)
    return [m.group() for p in (HEX, RGB) for m in p.finditer(text)]


def test_no_colour_is_written_outside_style_css():
    found = {str(f.relative_to(ROOT)): c for f in FILES if (c := _colours(_code(f)))}
    assert not found, 'use a variable from static/css/style.css instead: %s' % found


def test_every_variable_used_is_defined():
    defined = set(re.findall(r'^\s*(--[\w-]+)\s*:', (ROOT / 'static/css/style.css').read_text(), re.M))
    used = set()
    for f in [*FILES, ROOT / 'static/css/style.css']:
        code = _code(f)
        used |= set(re.findall(r"var\((--[\w-]+)", code)) | set(re.findall(r"cssVar\('(--[\w-]+)'", code))
    set_inline = {'--pct', '--gauge-color'}                                   # set per element in a style attribute
    assert used - defined - set_inline == set()

