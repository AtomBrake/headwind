"""The pages' scripts under the CSP (app.py), which runs only Headwind's own script files: nothing inline in the templates or in the
markup the scripts build, and every data-click= and the rest (static/js/actions.js) calls a function a handler can reach."""
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
TEMPLATES = sorted((ROOT / 'templates').rglob('*.html'))
SCRIPTS = sorted((ROOT / 'static' / 'js').glob('*.js'))


def _text(f):
    return f.read_text(encoding='utf-8', errors='replace')


def test_nothing_inline():
    for f in TEMPLATES + SCRIPTS:
        text = _text(f)
        if f.suffix == '.html':
            for tag in re.findall(r'<script\b[^>]*>', text):
                assert 'src=' in tag or 'type="application/json"' in tag, f'{f.name}: inline {tag}'
        assert not re.findall(r'\son[a-z]+\s*=\s*["\']', text), f'{f.name}: an on…= handler'
        assert 'javascript:' not in text, f'{f.name}: a javascript: link'


def test_handlers_call_functions_they_can_reach():
    """A handler looks its function up on window: a `function` or `var` at the top of a script, or window.x = ..., not a let or const."""
    reachable = {'this', 'event', 'location', 'history', 'document', 'window', 'confirm'}
    for f in SCRIPTS:
        text = _text(f)
        reachable |= set(re.findall(r'^\s*(?:async\s+)?function\s+([\w$]+)', text, re.M))
        reachable |= set(re.findall(r'^var\s+([\w$]+)', text, re.M))
        reachable |= set(re.findall(r'window\.([\w$]+)\s*=', text))
    calls = 0
    for f in TEMPLATES + SCRIPTS:
        text = _text(f)
        for m in re.finditer(r'data-(?:click|change|input|submit|keydown|error)="([^"]*)"', text):
            body = re.sub(r"\{\{.*?\}\}|\$\{[^}]*\}|'(?:[^'\\]|\\.)*'", '0', m.group(1))       # Jinja, ${...} and strings are values
            for callee in re.findall(r'([A-Za-z_$][\w$.]*)\s*\(', body):
                calls += 1
                line = text.count('\n', 0, m.start()) + 1
                assert callee.split('.')[0] in reachable, f'{f.name}:{line}: {callee}() is not a function a handler can reach'
    assert calls > 100
