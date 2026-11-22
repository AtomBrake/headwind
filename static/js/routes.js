// The Routes page (templates/routes.html, routes/saved_routes.py): one route on the map with its profile, renaming, the sport, deleting,
// and bringing routes in from GPX files, a Strava export and Garmin Connect. A route's points, its GPX and its deletion are the planner's
// endpoints under /planner/routes (routes/route_builder.py).
var PAGE = JSON.parse(document.getElementById('routesData').textContent);
var FLASH_KEY = 'routesFlash';
var FROM = { gpx: 'from a GPX file', activity: 'from an activity', strava: 'from Strava', garmin: 'from Garmin Connect',
             planner: 'drawn in the planner' };

var map = null, line = null, profile = null, dot = null, shownId = null;

// ── Messages: what an import did, kept across the reload that shows its routes ──
function say(html, kind) {
  var el = document.getElementById('importResult');
  el.className = 'flash flash-' + (kind || 'success');
  el.innerHTML = html;
  el.hidden = false;
}

function reloadWith(html, kind, routeId) {
  try { sessionStorage.setItem(FLASH_KEY, JSON.stringify({ html: html, kind: kind })); } catch (e) {}
  location.href = '/routes/' + (routeId ? '?route=' + routeId : '');
}

function esc(s) {
  return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
    return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
  });
}

function plural(n, word) { return n + ' ' + word + (n === 1 ? '' : 's'); }

function postJSON(url, body) {
  return fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
    .then(function (r) { return r.json().then(function (d) { if (!r.ok) throw new Error(d.error || r.status); return d; }); });
}

function row(id) { return document.querySelector('tr[data-route="' + id + '"]'); }

// ── The map ──
function initMap() {
  if (!document.getElementById('routesMap')) return;
  map = L.map('routesMap').setView([PAGE.lat, PAGE.lng], 10);
  HWMap.attach(map, { page: 'routes', base: 'scheme' });
  document.getElementById('profileChart').addEventListener('mouseleave', function () {
    if (dot) { map.removeLayer(dot); dot = null; }
  });
}

function showRoute(id) {
  if (!map) return false;
  fetch('/planner/routes/' + id)
    .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
    .then(function (route) {
      shownId = route.id;
      document.querySelectorAll('#routesTable tr.shown').forEach(function (tr) { tr.classList.remove('shown'); });
      var tr = row(route.id);
      if (tr) tr.classList.add('shown');
      history.replaceState(null, '', '/routes/?route=' + route.id);
      var pts = route.track || route.waypoints.map(function (w) { return [w.lat, w.lng]; });
      if (line) map.removeLayer(line);
      line = L.polyline(pts.map(function (p) { return [p[0], p[1]]; }), { color: cssVar('--accent'), weight: 4, opacity: 0.9 }).addTo(map);
      if (pts.length) map.fitBounds(line.getBounds(), { padding: [30, 30] });
      describe(route);
      drawProfile(route.track);
    })
    .catch(function () { say('That route could not be loaded.', 'error'); });
  return false;                                          // the link's own address is for opening it in a new tab
}

// The heading over the map: the name, then its sport, distance, climb and where it came from
function describe(route) {
  document.getElementById('shownName').textContent = route.name;
  var facts = [];
  var sel = row(route.id) && row(route.id).querySelector('select');
  if (sel && sel.value) facts.push(sel.options[sel.selectedIndex].text);
  facts.push(UNITS.toDist(route.distM).toFixed(1) + ' ' + UNITS.dist);
  if (route.gainM != null) facts.push(Math.round(UNITS.toElev(route.gainM)).toLocaleString() + ' ' + UNITS.elev + ' climb');
  facts.push(FROM[route.source] || route.source);
  document.getElementById('shownFacts').textContent = facts.join(' · ');
}

function metresBetween(a, b) {
  var R = 6371008.8, rad = Math.PI / 180;
  var dLat = (b[0] - a[0]) * rad, dLng = (b[1] - a[1]) * rad;
  var h = Math.pow(Math.sin(dLat / 2), 2) + Math.cos(a[0] * rad) * Math.cos(b[0] * rad) * Math.pow(Math.sin(dLng / 2), 2);
  return 2 * R * Math.asin(Math.sqrt(Math.min(1, h)));
}

// The elevation profile under the map, from the route's own heights; hovering it marks the place on the map. None for waypoints.
function drawProfile(track) {
  var box = document.getElementById('routeProfile');
  if (profile) { profile.destroy(); profile = null; }
  if (dot) { map.removeLayer(dot); dot = null; }
  if (!window.Chart || !track || !track.some(function (p) { return p[2] != null; })) { box.hidden = true; return; }
  var along = [0];
  for (var i = 1; i < track.length; i++) along.push(along[i - 1] + metresBetween(track[i - 1], track[i]));
  var step = Math.max(1, Math.floor(track.length / 600)), idx = [];
  for (var j = 0; j < track.length; j += step) idx.push(j);
  if (idx[idx.length - 1] !== track.length - 1) idx.push(track.length - 1);
  box.hidden = false;
  profile = new Chart(document.getElementById('profileChart'), {
    type: 'line',
    data: {
      labels: idx.map(function (k) { return UNITS.toDist(along[k]).toFixed(1); }),
      datasets: [{ data: idx.map(function (k) { return track[k][2] != null ? UNITS.toElev(track[k][2]) : null; }),
                   borderColor: cssVar('--accent'), backgroundColor: cssVar('--accent', 0.18), fill: true,
                   borderWidth: 1.5, pointRadius: 0, tension: 0.2, spanGaps: true }],
    },
    options: {
      animation: false, maintainAspectRatio: false, interaction: { mode: 'index', intersect: false },
      onHover: function (e, items) {
        if (!items.length) return;
        var p = track[idx[items[0].index]];
        if (!dot) dot = L.circleMarker([p[0], p[1]], { radius: 7, color: cssVar('--card-bg'), weight: 2,
                                                       fillColor: cssVar('--c-yellow'), fillOpacity: 1, interactive: false }).addTo(map);
        else dot.setLatLng([p[0], p[1]]);
      },
      plugins: { legend: { display: false }, tooltip: { displayColors: false, callbacks: {
        title: function (c) { return c[0].label + ' ' + UNITS.dist; },
        label: function (c) { return Math.round(c.parsed.y) + ' ' + UNITS.elev; } } } },
      scales: { x: { ticks: { maxTicksLimit: 8, font: { size: 10 } }, grid: { display: false } },
                y: { ticks: { maxTicksLimit: 4, font: { size: 10 } } } },
    },
  });
}

// ── Rename, in the row ──
function startRename(id) {
  var tr = row(id), cell = tr.cells[0], link = cell.querySelector('a[data-name]');
  if (cell.querySelector('input')) return;
  var box = document.createElement('div');
  box.className = 'route-name-edit';
  var input = document.createElement('input');
  input.type = 'text'; input.maxLength = 100; input.value = link.textContent; input.setAttribute('aria-label', 'Route name');
  var save = document.createElement('button');
  save.className = 'btn btn-primary btn-sm'; save.textContent = 'Save';
  var cancel = document.createElement('button');
  cancel.className = 'btn btn-secondary btn-sm'; cancel.textContent = 'Cancel';
  box.append(input, save, cancel);
  link.hidden = true;
  cell.appendChild(box);
  input.focus(); input.select();

  function close() { box.remove(); link.hidden = false; }
  function commit() {
    var name = input.value.trim();
    if (!name) { input.focus(); return; }
    if (name === link.textContent) { close(); return; }
    save.disabled = true;
    postJSON('/routes/' + id, { name: name })
      .then(function (d) {
        link.textContent = d.name;
        cell.setAttribute('data-sort', d.name);
        tr.querySelector('select').setAttribute('aria-label', 'Sport of ' + d.name);
        if (shownId === id) document.getElementById('shownName').textContent = d.name;
        close();
      })
      .catch(function (e) { save.disabled = false; say(esc(e.message), 'error'); });
  }
  save.addEventListener('click', commit);
  cancel.addEventListener('click', close);
  input.addEventListener('keydown', function (e) {
    if (e.key === 'Enter') { e.preventDefault(); commit(); }
    if (e.key === 'Escape') close();
  });
}

// ── Sport ──
function setSport(id, sel) {
  var before = sel.getAttribute('data-was');
  if (before === null) before = sel.querySelector('option[selected]') ? sel.querySelector('option[selected]').value : '';
  sel.disabled = true;
  postJSON('/routes/' + id, { sportType: sel.value })
    .then(function () {
      sel.setAttribute('data-was', sel.value);
      sel.closest('td').setAttribute('data-sort', sel.value ? sel.options[sel.selectedIndex].text : '');
      if (shownId === id) fetch('/planner/routes/' + id).then(function (r) { return r.json(); }).then(describe);
    })
    .catch(function (e) { sel.value = before; say(esc(e.message), 'error'); })
    .finally(function () { sel.disabled = false; });
}

// ── Delete ──
function deleteRoute(id) {
  var name = row(id).querySelector('a[data-name]').textContent;
  if (!confirm('Delete the route ' + name + '? This cannot be undone.')) return;
  fetch('/planner/routes/' + id, { method: 'DELETE' })
    .then(function (r) { if (!r.ok) throw new Error(r.status); reloadWith(esc(name) + ' deleted.'); })
    .catch(function () { say('The route could not be deleted.', 'error'); });
}

// ── Import GPX files ──
function chooseGpxFiles() { document.getElementById('gpxFiles').click(); }

function importGPX(input) {
  if (!input.files.length) return;
  var fd = new FormData();
  Array.prototype.forEach.call(input.files, function (f) { fd.append('files', f); });
  say('Reading ' + plural(input.files.length, 'file') + '…', 'warning');
  fetch('/planner/routes/import', { method: 'POST', body: fd })
    .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
    .then(function (res) {
      var saved = res.filter(function (x) { return x.status === 'saved'; });
      var lines = [saved.length ? plural(saved.length, 'route') + ' added.' : 'No new routes.'];
      var bad = false;
      res.forEach(function (x) {
        if (x.status === 'exists') lines.push(esc(x.file) + ': already here.');
        if (x.status === 'empty') { bad = true; lines.push(esc(x.file) + ': no points in it.'); }
        if (x.status === 'unreadable') { bad = true; lines.push(esc(x.file) + ': not a GPX file Headwind can read.'); }
      });
      var first = saved[0] || res.find(function (x) { return x.id; });
      reloadWith(lines.join('<br>'), bad ? 'warning' : 'success', first && first.id);
    })
    .catch(function () { say('The import failed.', 'error'); })
    .finally(function () { input.value = ''; });
}

// ── Strava: the routes in a Strava export, kept from an earlier import or uploaded now ──
function stravaDone(d) {
  var msg = d.routes_created ? plural(d.routes_created, 'route') + ' added from Strava.' : 'No new routes from Strava.';
  if (d.routes_existing) msg += ' ' + d.routes_existing + ' already here.';
  if (d.routes_unread) msg += ' ' + d.routes_unread + ' could not be read.';
  reloadWith(msg, d.routes_unread ? 'warning' : 'success');
}

function stravaPost(fd, busy) {
  return fetch('/routes/import/strava', { method: 'POST', body: fd })
    .then(function (r) { return r.json().then(function (d) { if (!r.ok) throw new Error(d.error || r.status); return d; }); })
    .then(stravaDone)
    .catch(function (e) { say(esc(e.message), 'error'); })
    .finally(function () { if (busy) busy.disabled = false; });
}

function importStrava(rider, btn) {
  var fd = new FormData();
  fd.append('rider', rider);
  btn.disabled = true;
  say('Reading the routes in your Strava export…', 'warning');
  stravaPost(fd, btn);
}

function importStravaZip(input) {
  if (!input.files.length) return;
  var fd = new FormData();
  fd.append('zipfile', input.files[0]);
  input.disabled = true;
  say('Uploading your Strava export and reading its routes… A big export can take a few minutes to upload.', 'warning');
  stravaPost(fd, input).finally(function () { input.value = ''; });
}

// ── Garmin Connect courses: in the background, followed here ──
function importGarmin() {
  var btn = document.getElementById('garminBtn');
  btn.disabled = true;
  say('Asking Garmin for your courses…', 'warning');
  fetch('/routes/import/garmin', { method: 'POST' })
    .then(function (r) { return r.json().then(function (d) { if (!r.ok) throw new Error(d.error || r.status); return d; }); })
    .then(function (d) { followGarmin(d.job); })
    .catch(function (e) { btn.disabled = false; say(esc(e.message), 'error'); });
}

function followGarmin(job) {
  var btn = document.getElementById('garminBtn');
  if (btn) btn.disabled = true;
  fetch('/routes/import/garmin/' + job)
    .then(function (r) { return r.json(); })
    .then(function (d) {
      var p = d.progress || {};
      if (d.state === 'failed') {
        if (btn) btn.disabled = false;
        say(esc(d.error || 'Bringing in the Garmin courses failed.'), 'error');
        return;
      }
      if (d.state === 'done' && p.result) {
        var res = p.result;
        if (!res.total) { reloadWith('Garmin Connect has no courses of yours.', 'warning'); return; }
        var msg = res.created ? plural(res.created, 'course') + ' added from Garmin.' : 'No new courses from Garmin.';
        if (res.existing) msg += ' ' + res.existing + ' already here.';
        if (res.unread) msg += ' ' + res.unread + ' could not be read.';
        reloadWith(msg, res.unread ? 'warning' : 'success');
        return;
      }
      say(p.total ? 'Bringing in your Garmin courses: ' + p.done + ' of ' + p.total + '…' : 'Asking Garmin for your courses…', 'warning');
      setTimeout(function () { followGarmin(job); }, 1500);
    })
    .catch(function () { setTimeout(function () { followGarmin(job); }, 4000); });
}

// ── Start ──
(function () {
  var flash = null;
  try { flash = JSON.parse(sessionStorage.getItem(FLASH_KEY) || 'null'); sessionStorage.removeItem(FLASH_KEY); } catch (e) {}
  if (flash) say(flash.html, flash.kind);
  initMap();
  if (PAGE.show) showRoute(PAGE.show);
  if (PAGE.garminJob) followGarmin(PAGE.garminJob);
})();
