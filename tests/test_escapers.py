"""Every hand-rolled HTML escaper in the templates and scripts escapes all five characters, so one used inside a quoted attribute
(either quote) can't be broken out of. Each escaper is cut out of its file and run in Node; a line that writes `&lt;` outside a
named escaper (an inline `.replace(/</g, '&lt;')`) fails, as it would escape less than the rest."""
import json
import pathlib
import re
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
DEFINITION = re.compile(r'(?:function\s+(\w+)\s*\(|(?:\bconst|\blet|\bvar|,)\s*(\w+)\s*=\s*(?:\(\s*\w*\s*\)|\w+)\s*=>)')
EXPECTED = '&lt;&gt;&amp;&quot;&#39;'

# Given the source from a definition's start, try each cut point (after `;`, `,`, `}` or a newline) until the text compiles to a function.
_RUNNER = r"""
const items = JSON.parse(require('fs').readFileSync(0, 'utf8')), out = [];
for (const { name, src, isFunction } of items) {
  let fn = null;
  for (let i = 0; i < src.length && !fn; i++) {
    if (!';,}\n'.includes(src[i])) continue;
    const head = src.slice(0, i + (src[i] === '}' ? 1 : 0));
    try {
      fn = isFunction ? new Function(head + '\nreturn ' + name + ';')() : new Function('return (' + head + ');')();
      if (typeof fn !== 'function') fn = null;
    } catch (e) { fn = null; }
  }
  out.push(fn ? fn('<>&"\'') : null);
}
process.stdout.write(JSON.stringify(out));
"""


def _sources():
    for p in sorted([*ROOT.glob('templates/**/*.html'), *ROOT.glob('static/js/**/*.js')]):
        if not p.name.endswith('.min.js'):
            yield p


def _escapers():
    """(file, line, name, source from the definition on, is it a `function`) for every escaper, plus the lines writing `&lt;` that no escaper covers."""
    found, stray = [], []
    for p in _sources():
        text = p.read_text(encoding='utf-8')
        defs = list(DEFINITION.finditer(text))
        for m in re.finditer(r'&lt;', text):
            line = text.count('\n', 0, m.start()) + 1
            before = [d for d in defs if d.start() < m.start() and text.count('\n', d.start(), m.start()) <= 3]
            if not before:
                stray.append(f'{p.relative_to(ROOT)}:{line}')
                continue
            d = before[-1]
            name = d.group(1) or d.group(2)
            key = (str(p.relative_to(ROOT)), name)
            if key in {(f, n) for f, _, n, _, _ in found}:
                continue
            start = d.start() if d.group(1) else d.start(2) + len(name)
            src = text[start:start + 2000]
            if not d.group(1):
                src = src.split('=', 1)[1]
            found.append((key[0], line, name, src, bool(d.group(1))))
    return found, stray


def test_no_inline_escaping():
    _, stray = _escapers()
    assert not stray, f'escape through a named escaper instead: {stray}'


def test_known_escapers_found():
    names = {(f, n) for f, _, n, _, _ in _escapers()[0]}
    for want in [('templates/nutrition.html', 'escHtml'), ('templates/home_assistant.html', 'esc'), ('templates/setup.html', 'haEsc'),
                 ('static/js/gear_assign.js', 'esc'), ('static/js/gear_assign_range.js', 'esc'), ('templates/route_builder.html', 'escapeHtml')]:
        assert want in names


@pytest.mark.skipif(not shutil.which('node'), reason='needs Node.js')
def test_every_escaper_escapes_all_five():
    found, _ = _escapers()
    items = [{'name': n, 'src': s, 'isFunction': f} for _, _, n, s, f in found]
    res = subprocess.run(['node', '-e', _RUNNER], input=json.dumps(items), capture_output=True, text=True, timeout=30, check=True)
    got = json.loads(res.stdout)
    bad = [f'{f}:{line} {n} -> {g!r}' for (f, line, n, _, _), g in zip(found, got) if g != EXPECTED]
    assert not bad, bad


@pytest.mark.skipif(not shutil.which('node'), reason='needs Node.js')
def test_runner_catches_a_weak_escaper():
    src = " (s) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;');"
    res = subprocess.run(['node', '-e', _RUNNER], input=json.dumps([{'name': 'esc', 'src': src, 'isFunction': False}]),
                         capture_output=True, text=True, timeout=30, check=True)
    assert json.loads(res.stdout) == ['&lt;>&amp;"\'']
