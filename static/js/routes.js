// The Routes page (templates/routes.html, routes/saved_routes.py): every route drawn together on one map (/routes/lines), a click on a line
// opening its page (route.js); the table of them, sorted (static/js/app.js) and filtered here, the map showing only the routes the filters
// leave; the sport, deleting, and bringing routes in from GPX files, a Strava export and Garmin Connect. A route's GPX and its deletion are
// the planner's endpoints under /planner/routes (routes/route_builder.py).
var PAGE = JSON.parse(document.getElementById('routesData').textContent);
var FLASH_KEY = 'routesFlash';

var map = null, lines = {}, layers = {}, shown = [], lit = null, litLayer = null, pixels = {}, pixelZoom = null;
var PICK_PX = 8;                                        // how near a click must be to a line to pick it

// ── Messages: what an import did, kept across the reload that shows its routes ──
function say(html, kind) {
  var el = document.getElementById('importResult');
  el.className = 'flash flash-' + (kind || 'success');
  el.innerHTML = html;
  el.hidden = false;
}

function reloadWith(html, kind, routeId) {
  try { sessionStorage.setItem(FLASH_KEY, JSON.stringify({ html: html, kind: kind })); } catch (e) {}
  location.href = '/routes/' + (routeId || '');
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
function nameOf(id) { var tr = row(id); return tr ? tr.querySelector('a[data-name]').textContent : ''; }

// ── The map: every route shown in the table, light lines that add up where they overlap ──
function initMap() {
  if (!document.getElementById('routesMap')) return;
  map = L.map('routesMap', { preferCanvas: true }).setView([PAGE.lat, PAGE.lng], 9);
  HWMap.attach(map, { page: 'routes', base: 'scheme' });
  map.on('click', pickAt);
  map.on('mousemove', hoverAt);
  map.on('mouseout', function () { light(null); });
  map.on('moveend', function () { if (document.getElementById('fView').checked) applyFilters(); });
  map.on('popupclose', function () { light(null); });
  fetch('/routes/lines')
    .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
    .then(function (d) {
      lines = d.lines;
      Object.keys(lines).forEach(function (id) {
        if (lines[id].length < 2) return;
        layers[id] = L.polyline(lines[id], { color: cssVar('--accent'), weight: 3, opacity: 0.4, interactive: false });
      });
      applyFilters(true);
    })
    .catch(function () { say('The routes could not be drawn on the map.', 'error'); });
}

function drawShown(fit) {
  Object.keys(layers).forEach(function (id) {
    var on = shown.indexOf(id) >= 0;
    if (on && !map.hasLayer(layers[id])) layers[id].addTo(map);
    if (!on && map.hasLayer(layers[id])) map.removeLayer(layers[id]);
  });
  if (fit) fitShown();
}

// The map fitted to the routes shown: by itself to where most of them are (within CLUSTER_KM of their middle), so one far away (a holiday)
// doesn't zoom it out to the whole world; to every one of them with the link under the map (all)
var CLUSTER_KM = 150;
function fitShown(all) {
  var ids = shown.filter(function (id) { return layers[id]; });
  if (!all && ids.length > 2) {
    var mid = function (xs) { xs = xs.slice().sort(function (a, b) { return a - b; }); return xs[Math.floor(xs.length / 2)]; };
    var centres = ids.map(function (id) { return layers[id].getBounds().getCenter(); });
    var middle = L.latLng(mid(centres.map(function (c) { return c.lat; })), mid(centres.map(function (c) { return c.lng; })));
    var near = ids.filter(function (id, i) { return centres[i].distanceTo(middle) <= CLUSTER_KM * 1000; });
    if (near.length) ids = near;
  }
  var b = null;
  ids.forEach(function (id) { b = b ? b.extend(layers[id].getBounds()) : L.latLngBounds(layers[id].getBounds()); });
  if (b && b.isValid()) map.fitBounds(b, { padding: [20, 20], maxZoom: 14 });
  return false;
}

// One route drawn over the others: the one under the mouse, or the row being pointed at
function light(id) {
  id = id == null ? null : String(id);
  if (lit === id) return;
  if (litLayer) { map.removeLayer(litLayer); litLayer = null; }
  if (lit && row(lit)) row(lit).classList.remove('lit');
  lit = id;
  if (id && lines[id]) {
    litLayer = L.polyline(lines[id], { color: cssVar('--c-yellow'), weight: 5, opacity: 1, interactive: false }).addTo(map);
    if (row(id)) row(id).classList.add('lit');
  }
}

// The routes within PICK_PX of a point on the map, nearest first, from their lines in pixels at this zoom
function routesNear(latlng) {
  var z = map.getZoom();
  if (pixelZoom !== z) { pixels = {}; pixelZoom = z; }
  var p = map.project(latlng, z), tol2 = PICK_PX * PICK_PX, hits = [];
  shown.forEach(function (id) {
    var line = lines[id];
    if (!line || line.length < 2) return;
    var px = pixels[id] || (pixels[id] = line.map(function (q) { return map.project(q, z); }));
    var best = Infinity;
    for (var i = 1; i < px.length; i++) {
      var a = px[i - 1], b = px[i], dx = b.x - a.x, dy = b.y - a.y, ll = dx * dx + dy * dy;
      var t = ll ? Math.max(0, Math.min(1, ((p.x - a.x) * dx + (p.y - a.y) * dy) / ll)) : 0;
      var ex = a.x + t * dx - p.x, ey = a.y + t * dy - p.y, d2 = ex * ex + ey * ey;
      if (d2 < best) best = d2;
    }
    if (best <= tol2) hits.push({ id: id, d: best });
  });
  return hits.sort(function (a, b) { return a.d - b.d; }).map(function (h) { return h.id; });
}

var hoverTimer = null;
function hoverAt(e) {
  if (hoverTimer) return;
  hoverTimer = setTimeout(function () {
    hoverTimer = null;
    if (map._popup && map.hasLayer(map._popup)) return;      // a list of routes is open: it lights them itself
    var hits = routesNear(e.latlng);
    map.getContainer().classList.toggle('route-hover', hits.length > 0);
    light(hits[0]);
  }, 30);
}

// A click on one route opens it; on several where they overlap, a list to choose from
function pickAt(e) {
  var hits = routesNear(e.latlng);
  if (!hits.length) return;
  if (hits.length === 1) { location.href = '/routes/' + hits[0]; return; }
  var ul = document.createElement('ul');
  ul.className = 'route-pick';
  hits.forEach(function (id) {
    var tr = row(id), li = document.createElement('li'), a = document.createElement('a');
    a.href = '/routes/' + id;
    a.textContent = nameOf(id);
    a.addEventListener('mouseenter', function () { light(id); });
    li.appendChild(a);
    if (tr) {
      var facts = document.createElement('span');
      facts.className = 'hint';
      facts.textContent = tr.cells[2].textContent.trim();
      li.appendChild(facts);
    }
    ul.appendChild(li);
  });
  var head = document.createElement('div');
  head.className = 'hint';
  head.textContent = hits.length + ' routes here';
  var box = document.createElement('div');
  box.append(head, ul);
  L.popup({ maxWidth: 320 }).setLatLng(e.latlng).setContent(box).openOn(map);
}

// ── The table's filters: the name, sport, where from, distance and the map's view; kept in the URL ──
var FILTERS = { q: 'fName', sport: 'fSport', from: 'fSource', min: 'fMin', max: 'fMax' };

function filterValue(key) { var el = document.getElementById(FILTERS[key]); return el ? el.value.trim() : ''; }

function inView(id, bounds) { return !!(layers[id] && bounds.intersects(layers[id].getBounds())); }

function applyFilters(first) {
  var table = document.getElementById('routesTable');
  if (!table) return;
  var q = filterValue('q').toLowerCase(), sport = filterValue('sport'), from = filterValue('from');
  var min = parseFloat(filterValue('min')), max = parseFloat(filterValue('max'));
  var view = document.getElementById('fView').checked && map ? map.getBounds() : null;
  var rows = table.tBodies[0].rows, total = rows.length;
  shown = [];
  Array.prototype.forEach.call(rows, function (tr) {
    var id = tr.getAttribute('data-route'), dist = UNITS.toDist(Number(tr.getAttribute('data-dist')));
    var ok = (!q || tr.getAttribute('data-find').indexOf(q) >= 0) &&
             (!sport || tr.getAttribute('data-sport') === sport) &&
             (!from || tr.getAttribute('data-source') === from) &&
             (isNaN(min) || dist >= min) && (isNaN(max) || dist <= max) &&
             (!view || inView(id, view));
    tr.hidden = !ok;
    if (ok) shown.push(id);
  });
  var filtered = !!(q || sport || from || !isNaN(min) || !isNaN(max) || view);
  document.getElementById('fCount').textContent = filtered ? shown.length + ' of ' + plural(total, 'route') : plural(total, 'route');
  document.getElementById('fClear').hidden = !filtered;
  document.getElementById('fNone').hidden = shown.length > 0;
  table.hidden = !shown.length;
  if (map) {
    if (lit && shown.indexOf(lit) < 0) light(null);
    drawShown(first === true || (!view && first !== false));
  }
  if (first !== true) remember();
}

function clearFilters() {
  Object.keys(FILTERS).forEach(function (k) { var el = document.getElementById(FILTERS[k]); if (el) el.value = ''; });
  document.getElementById('fView').checked = false;
  applyFilters();
  return false;
}

function remember() {
  try {
    var url = new URL(location.href);
    Object.keys(FILTERS).forEach(function (k) { var v = filterValue(k); if (v) url.searchParams.set(k, v); else url.searchParams.delete(k); });
    if (document.getElementById('fView').checked) url.searchParams.set('view', '1'); else url.searchParams.delete('view');
    history.replaceState(history.state, '', url);
  } catch (e) {}
}

function restoreFilters() {
  var qs = new URLSearchParams(location.search);
  Object.keys(FILTERS).forEach(function (k) { var el = document.getElementById(FILTERS[k]); if (el && qs.get(k)) el.value = qs.get(k); });
}

// Pointing at a row lights its route on the map
function initRows() {
  var table = document.getElementById('routesTable');
  if (!table) return;
  table.tBodies[0].addEventListener('mouseover', function (e) {
    var tr = e.target.closest('tr[data-route]');
    if (tr && map) light(tr.getAttribute('data-route'));
  });
  table.tBodies[0].addEventListener('mouseleave', function () { if (map) light(null); });
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
      sel.closest('tr').setAttribute('data-sport', sel.value || '-');
    })
    .catch(function (e) { sel.value = before; say(esc(e.message), 'error'); })
    .finally(function () { sel.disabled = false; });
}

// ── Delete ──
function deleteRoute(id) {
  var name = nameOf(id);
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

// ── Garmin Connect courses: listed to choose from, then brought in the background, followed here ──
var garminCourses = null;

function openGarmin() {
  var panel = document.getElementById('garminPanel');
  if (!panel.hidden) { closeGarmin(); return; }
  panel.hidden = false;
  if (garminCourses) return;
  var loading = document.getElementById('garminLoading');
  loading.textContent = 'Asking Garmin for your courses…';
  loading.hidden = false;
  document.getElementById('garminChoose').hidden = true;
  fetch('/routes/import/garmin/courses')
    .then(function (r) { return r.json().then(function (d) { if (!r.ok) throw new Error(d.error || r.status); return d; }); })
    .then(function (d) { listGarmin(d.courses); })
    .catch(function (e) { loading.textContent = e.message || 'Garmin could not be reached.'; });
}

function closeGarmin() { document.getElementById('garminPanel').hidden = true; }

function listGarmin(courses) {
  garminCourses = courses;
  var loading = document.getElementById('garminLoading');
  if (!courses.length) { loading.textContent = 'Garmin Connect has no courses of yours.'; return; }
  loading.hidden = true;
  var fresh = courses.filter(function (c) { return !c.here; }).length;
  document.querySelector('#garminChoose > .hint').textContent = plural(courses.length, 'course') + ' on Garmin Connect, ' +
    (fresh === courses.length ? 'none of them here yet' : fresh + ' not here yet') + '. Tick the ones to bring in as routes.';
  var tbody = document.querySelector('#garminCourses tbody');
  tbody.innerHTML = courses.map(function (c) {
    var dist = c.distM != null ? UNITS.toDist(c.distM).toFixed(1) + ' ' + UNITS.dist : '—';
    var gain = c.gainM != null ? Math.round(UNITS.toElev(c.gainM)).toLocaleString() + ' ' + UNITS.elev : '—';
    var made = c.created ? new Date(c.created + 'T12:00:00').toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' }) : '';
    return '<tr data-course="' + esc(c.id) + '" data-find="' + esc(c.name.toLowerCase()) + '"' + (c.here ? ' class="here"' : '') +
      ' data-click="toggleCourse(this, event)">' +
      '<td><input type="checkbox" value="' + esc(c.id) + '" aria-label="Bring in ' + esc(c.name) + '"' +
      (c.here ? ' disabled title="Already here"' : '') + ' data-change="countGarmin()"></td>' +
      '<td data-sort="' + esc(c.name) + '">' + esc(c.name) + (c.here ? ' <span class="hint">· already here</span>' : '') + '</td>' +
      '<td>' + esc(c.sportLabel || '') + '</td>' +
      '<td class="num" data-sort="' + (c.distM != null ? c.distM : '') + '">' + dist + '</td>' +
      '<td class="num" data-sort="' + (c.gainM != null ? c.gainM : '') + '">' + gain + '</td>' +
      '<td data-sort="' + esc(c.created || '') + '">' + made + '</td></tr>';
  }).join('');
  if (window.sortTable) sortTable(document.getElementById('garminCourses'));
  document.getElementById('garminChoose').hidden = false;
  countGarmin();
}

// A click anywhere in a row ticks it, except on the box itself, which ticks itself
function toggleCourse(tr, ev) {
  var box = tr.querySelector('input');
  if (ev.target === box || box.disabled) return;
  box.checked = !box.checked;
  countGarmin();
}

function garminBoxes(shownOnly) {
  return Array.prototype.filter.call(document.querySelectorAll('#garminCourses tbody input'), function (b) {
    return !b.disabled && (!shownOnly || !b.closest('tr').hidden);
  });
}

function filterGarmin() {
  var q = document.getElementById('garminFilter').value.trim().toLowerCase();
  document.querySelectorAll('#garminCourses tbody tr').forEach(function (tr) {
    tr.hidden = q !== '' && tr.getAttribute('data-find').indexOf(q) < 0;
  });
  countGarmin();
}

function pickGarmin(on) {
  garminBoxes(true).forEach(function (b) { b.checked = on; });
  countGarmin();
}

function countGarmin() {
  var chosen = garminBoxes(false).filter(function (b) { return b.checked; }).length;
  var shown = garminBoxes(true);
  var all = document.getElementById('garminAll');
  all.checked = shown.length > 0 && shown.every(function (b) { return b.checked; });
  all.indeterminate = !all.checked && shown.some(function (b) { return b.checked; });
  all.disabled = !shown.length;
  document.getElementById('garminCount').textContent = chosen ? plural(chosen, 'course') + ' chosen' : '';
  var go = document.getElementById('garminGo');
  go.disabled = !chosen;
  go.textContent = chosen ? 'Bring in ' + plural(chosen, 'course') : 'Bring in the chosen courses';
}

function importGarmin() {
  var ids = garminBoxes(false).filter(function (b) { return b.checked; }).map(function (b) { return b.value; });
  if (!ids.length) return;
  var btn = document.getElementById('garminBtn'), go = document.getElementById('garminGo');
  btn.disabled = go.disabled = true;
  say('Bringing in ' + plural(ids.length, 'course') + ' from Garmin…', 'warning');
  postJSON('/routes/import/garmin', { ids: ids })
    .then(function (d) { closeGarmin(); followGarmin(d.job); })
    .catch(function (e) { btn.disabled = false; countGarmin(); say(esc(e.message), 'error'); });
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
        if (!res.total) { reloadWith('Those courses are no longer on Garmin Connect.', 'warning'); return; }
        var msg = res.created ? plural(res.created, 'course') + ' added from Garmin.' : 'No new courses from Garmin.';
        if (res.existing) msg += ' ' + res.existing + ' already here.';
        if (res.unread) msg += ' ' + res.unread + ' could not be read.';
        reloadWith(msg, res.unread ? 'warning' : 'success');
        return;
      }
      say(p.total ? 'Bringing in your Garmin courses: ' + p.done + ' of ' + p.total + '…' : 'Bringing in your Garmin courses…', 'warning');
      setTimeout(function () { followGarmin(job); }, 1500);
    })
    .catch(function () { setTimeout(function () { followGarmin(job); }, 4000); });
}

// ── Start ──
(function () {
  var flash = null;
  try { flash = JSON.parse(sessionStorage.getItem(FLASH_KEY) || 'null'); sessionStorage.removeItem(FLASH_KEY); } catch (e) {}
  if (flash) say(flash.html, flash.kind);
  restoreFilters();
  if (new URLSearchParams(location.search).get('view') && document.getElementById('fView')) document.getElementById('fView').checked = true;
  initRows();
  initMap();
  applyFilters(false);
  if (PAGE.garminJob) followGarmin(PAGE.garminJob);
})();
