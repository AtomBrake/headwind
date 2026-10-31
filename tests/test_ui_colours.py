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


# ---------- light and dark ----------
CSS = (ROOT / 'static/css/style.css').read_text()
NOT_COLOURS = {'--sidebar-w', '--font'}
SAME_IN_BOTH = {'--strava', '--coffee'}                                      # brands: dark only, the light block leaves them be


def _block(selector):
    body = re.search(re.escape(selector) + r'\s*\{(.*?)\n\}', CSS, re.S).group(1)
    return dict(re.findall(r'^\s*(--[\w-]+)\s*:\s*([^;]+);', body, re.M))


def _schemes():
    dark = _block(':root')
    light = {**dark, **_block(':root[data-scheme="light"]')}
    def resolve(s, v):
        while (m := re.fullmatch(r'var\((--[\w-]+)\)', v.strip())):
            v = s[m.group(1)]
        return v.strip().lower()
    names = [n for n in dark if n not in NOT_COLOURS and not dark[n].startswith('color-mix')]   # color-mix ones follow their base colour
    return {n: resolve(dark, dark[n]) for n in names}, {n: resolve(light, light[n]) for n in names}


def test_every_colour_has_a_light_value():
    dark, light = _block(':root'), _block(':root[data-scheme="light"]')
    assert set(light) == set(dark) - NOT_COLOURS - SAME_IN_BOTH


def test_colours_that_share_a_value_in_one_scheme_share_it_in_the_other():
    """base.html recolours charts and map lines on a scheme change by swapping each string cssVar() gave for the new scheme's.
    Two variables with the same string in one scheme and different ones in the other can't be told apart, and a page using
    both reloads instead. Only what goes through cssVar() matters: markup uses var(--x), which needs no swapping."""
    dark, light = _schemes()
    through_js = {n for f in FILES for n in re.findall(r"cssVar\('(--[\w-]+)'", _code(f))}
    through_js = sorted((through_js | {n for n in dark if n.startswith('--c-')}) & set(dark))     # the data hues also come by name from the server
    clashes = [(a, b, dark[a], dark[b], light[a], light[b]) for a in through_js for b in through_js
               if a < b and (dark[a] == dark[b]) != (light[a] == light[b])]
    assert not clashes
