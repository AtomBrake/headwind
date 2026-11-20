// Event handlers without inline JavaScript, which the Content-Security-Policy (CSP in app.py) doesn't run. An element says what to
// call in data-click, data-change, data-input, data-submit, data-keydown or data-error, as it would have in onclick= and the rest:
// one or more calls such as "importAgain(12, this)" or "setPreset(30); reload()". A call is a global function, a method of a global
// (location.reload) or of the element (this.form.submit); its arguments are numbers, 'strings', true, false, null, this, event,
// or a property of this or event (this.value). Nothing else is evaluated. A call that returns false cancels the event's default
// action, as "return f()" did. Elements added later (innerHTML) work too: the listeners are on the document. docs/UI.md has more.
//
// Three common cases need no function of their own:
//   <form data-confirm="Delete this?">   asks first, and doesn't submit on Cancel
//   <select data-autosubmit>             submits its form when changed
//   <form data-busy="Saving…">           disables its (first) button once submitted, with that text if one is given
(function () {
  var TOKEN = /\s*(?:(-?\d+(?:\.\d+)?)|'((?:[^'\\]|\\.)*)'|([A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)*)|([(),;]))/y;

  function lex(src) {
    var out = [], m;
    TOKEN.lastIndex = 0;
    while (TOKEN.lastIndex < src.length) {
      if (!/\S/.test(src.slice(TOKEN.lastIndex))) break;
      m = TOKEN.exec(src);
      if (!m) throw new Error('can\'t read ' + JSON.stringify(src));
      if (m[1] !== undefined) out.push({ value: Number(m[1]) });
      else if (m[2] !== undefined) out.push({ value: m[2].replace(/\\(.)/g, '$1') });
      else if (m[3] !== undefined) out.push({ name: m[3] });
      else out.push({ punct: m[4] });
    }
    return out;
  }

  var CONST = { 'true': true, 'false': false, 'null': null };

  function lookup(path, el, ev) {       // [the object the last name is on, its value]
    var parts = path.split('.'), o = window;
    if (parts[0] === 'this') { o = el; parts.shift(); }
    else if (parts[0] === 'event') { o = ev; parts.shift(); }
    var owner = window;
    parts.forEach(function (p) { owner = o; o = o == null ? undefined : o[p]; });
    return [owner, o];
  }

  function run(src, el, ev) {
    var t = lex(src), i = 0, result;
    function want(p) { if (!t[i] || t[i].punct !== p) throw new Error('expected ' + p + ' in ' + JSON.stringify(src)); i++; }
    while (i < t.length) {
      if (t[i].punct === ';') { i++; continue; }
      if (!t[i].name) throw new Error('expected a call in ' + JSON.stringify(src));
      var callee = lookup(t[i++].name, el, ev), args = [];
      want('(');
      while (t[i] && t[i].punct !== ')') {
        var a = t[i++];
        if ('value' in a) args.push(a.value);
        else if (a.name in CONST) args.push(CONST[a.name]);
        else if (a.name && /^(this|event)\b/.test(a.name)) args.push(a.name === 'this' ? el : a.name === 'event' ? ev : lookup(a.name, el, ev)[1]);
        else throw new Error('can\'t pass ' + (a.name || a.punct) + ' in ' + JSON.stringify(src));
        if (t[i] && t[i].punct === ',') i++;
      }
      want(')');
      if (typeof callee[1] !== 'function') throw new Error('no function for ' + JSON.stringify(src));
      result = callee[1].apply(callee[0], args);
      if (result === false) ev.preventDefault();
    }
  }

  function dispatch(attr) {
    return function (ev) {
      for (var el = ev.target; el && el !== document && !ev.cancelBubble; el = el.parentNode) {
        var src = el.getAttribute && el.getAttribute(attr);
        if (src == null) continue;
        try { run(src, el, ev); } catch (e) { console.error(attr + ':', e); }
      }
    };
  }
  ['click', 'change', 'input', 'submit', 'keydown'].forEach(function (type) {
    document.addEventListener(type, dispatch('data-' + type));
  });
  // error doesn't bubble (a broken <img>), so it's caught on its way down
  document.addEventListener('error', function (ev) {
    var el = ev.target, src = el.getAttribute && el.getAttribute('data-error');
    if (src != null) { try { run(src, el, ev); } catch (e) { console.error('data-error:', e); } }
  }, true);

  // Asked before anything else sees the submit, so Cancel stops it for every listener.
  document.addEventListener('submit', function (ev) {
    var f = ev.target;
    if (f.hasAttribute('data-confirm') && !confirm(f.getAttribute('data-confirm'))) {
      ev.preventDefault();
      ev.stopImmediatePropagation();
    }
  }, true);
  document.addEventListener('submit', function (ev) {
    var f = ev.target;
    var b = f.querySelector('button');
    if (ev.defaultPrevented || !f.hasAttribute('data-busy') || !b) return;
    b.disabled = true;
    if (f.getAttribute('data-busy')) b.textContent = f.getAttribute('data-busy');
  });
  document.addEventListener('change', function (ev) {
    if (ev.target.hasAttribute && ev.target.hasAttribute('data-autosubmit') && ev.target.form) ev.target.form.submit();
  });
})();
