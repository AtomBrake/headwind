// times are stored in UTC: show them in this browser's time, as "today 14:05" or "3 Oct 14:05"
document.querySelectorAll('[data-when]').forEach(function (el) {
  var d = new Date(el.dataset.when);
  if (isNaN(d)) return;
  var t = d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  el.textContent = (d.toDateString() === new Date().toDateString() ? 'today ' : d.getDate() + ' ' + _MONTHS[d.getMonth()] + ' ') + t;
});

// The Logs card: filters live in the address (?log=…&level=…), so the page's own refresh and a link from the error page keep them.
var LOG_COLOURS = { ERROR: 'var(--danger)', CRITICAL: 'var(--danger)', WARNING: 'var(--warning)', DEBUG: 'var(--text-muted)' };
function loadLogs() {
  var list = document.getElementById('logList');
  if (!list) return;
  var q = document.getElementById('logQ').value.trim(), level = document.getElementById('logLevel').value;
  var url = new URL(location.href);
  q ? url.searchParams.set('log', q) : url.searchParams.delete('log');
  level !== 'INFO' ? url.searchParams.set('level', level) : url.searchParams.delete('level');
  history.replaceState(null, '', url);
  fetch('/tasks/logs?' + new URLSearchParams({ q: q, level: level, limit: 200 }))
    .then(function (r) { return r.json(); })
    .then(function (d) {
      list.textContent = '';
      d.records.forEach(function (r) {
        var row = document.createElement('div');
        row.style.cssText = 'padding:0.3rem 0; border-top:1px solid var(--border); overflow-wrap:anywhere;';
        var head = document.createElement('div');
        var when = document.createElement('span');
        when.style.color = 'var(--text-muted)';
        when.textContent = r.time.slice(0, 19) + ' ';
        var lvl = document.createElement('span');
        lvl.style.cssText = 'font-weight:600; color:' + (LOG_COLOURS[r.level] || 'inherit');
        lvl.textContent = r.level + ' ';
        head.append(when, lvl);
        if (r.id && r.id !== '-') {
          var id = document.createElement('a');
          id.href = '?log=' + encodeURIComponent(r.id) + '#logs';
          id.textContent = '[' + r.id + ']';
          id.title = 'Only this request’s lines';
          id.onclick = function () { return showLogId(r.id); };
          head.append(id, ' ');
        }
        var who = document.createElement('span');
        who.style.color = 'var(--text-muted)';
        who.textContent = r.logger + ': ';
        var msg = document.createElement('span');
        msg.style.whiteSpace = 'pre-wrap';
        logMessage(msg, r.message, d.links || {});
        head.append(who, msg);
        row.append(head);
        if (r.detail) {
          var det = document.createElement('details');
          var sum = document.createElement('summary');
          sum.textContent = r.detail.indexOf('Traceback') === 0 ? 'Traceback' : 'More';
          sum.style.cssText = 'cursor:pointer; color:var(--text-muted);';
          var pre = document.createElement('pre');
          pre.style.cssText = 'white-space:pre-wrap; margin:0.25rem 0 0; font-size:0.7rem;';
          pre.textContent = r.detail;
          det.append(sum, pre);
          row.append(det);
        }
        list.append(row);
      });
      document.getElementById('logFoot').textContent = d.records.length
        ? (d.more ? 'The newest ' + d.records.length + ' matching lines; narrow the search to see older ones.' : d.records.length + ' matching line' + (d.records.length === 1 ? '' : 's') + '.')
        : 'No matching lines' + (level === 'ERROR' ? ': no errors logged.' : '.');
    })
    .catch(function () { document.getElementById('logFoot').textContent = 'Could not load the log.'; });
}
// An activity id the server found (links: {id: {url, name}}) becomes a link to it, named in its tooltip; the rest stays text
function logMessage(el, text, links) {
  var rx = /\b(?:(?:garmin|wk|man|imp)_[0-9a-f]+|\d{7,})\b/g, last = 0, m;
  while ((m = rx.exec(text))) {
    var hit = links[m[0]];
    if (!hit) continue;
    el.append(text.slice(last, m.index));
    var a = document.createElement('a');
    a.href = hit.url;
    a.textContent = m[0];
    a.title = hit.name || 'Open this activity';
    el.append(a);
    last = m.index + m[0].length;
  }
  el.append(text.slice(last));
}
function showLogId(id) {
  document.getElementById('logQ').value = id;
  document.getElementById('logLevel').value = 'DEBUG';
  loadLogs();
  document.getElementById('logs').scrollIntoView({ behavior: 'smooth' });
  return false;
}
(function () {
  if (!document.getElementById('logList')) return;
  var p = new URLSearchParams(location.search);
  document.getElementById('logQ').value = p.get('log') || '';
  if (p.get('level')) document.getElementById('logLevel').value = p.get('level').toUpperCase();
  else if (p.get('log')) document.getElementById('logLevel').value = 'DEBUG';   // a request's own lines: all of them
  loadLogs();
  if (p.get('log') && location.hash === '#logs') document.getElementById('logs').scrollIntoView();
})();
// Refresh while something runs (data-refresh), but not under someone reading or typing in the Logs card
if (document.currentScript.hasAttribute('data-refresh')) setTimeout(function reload() {
  var busy = document.activeElement && document.activeElement.closest && document.activeElement.closest('#logs');
  if (busy || document.querySelector('#logs details[open]')) { setTimeout(reload, 20000); return; }
  location.reload();
}, 20000);

// The troubleshooting copy being made: the page reloads when it's ready
document.querySelectorAll('[data-poll]').forEach(function (el) {
  (function poll() {
    setTimeout(function () {
      fetch(el.dataset.poll).then(function (r) { return r.json(); })
        .then(function (s) { if (s.state === 'running') poll(); else location.reload(); })
        .catch(poll);
    }, 2000);
  })();
});
