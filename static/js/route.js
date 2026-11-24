// One route's page (templates/route.html, routes/saved_routes.route): the route on a map with its elevation profile, renaming, its sport,
// deleting, the segments along it (_route_segments.html, drawn on the map too) and the "Done before" card (_route_activities.html), both
// fetched after the page. The route's points, GPX and deletion are the
// planner's endpoints under /planner/routes (routes/route_builder.py).
var PAGE = JSON.parse(document.getElementById('routeData').textContent);
var FLASH_KEY = 'routesFlash';                          // the Routes page shows it after a delete

var map = null, profile = null, dot = null;

function say(html, kind) {
  var el = document.getElementById('routeResult');
  el.className = 'flash flash-' + (kind || 'success');
  el.innerHTML = html;
  el.hidden = false;
}

function esc(s) {
  return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
    return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
  });
}

function postJSON(url, body) {
  return fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
    .then(function (r) { return r.json().then(function (d) { if (!r.ok) throw new Error(d.error || r.status); return d; }); });
}

// ── The map and the profile ──
function drawRoute(route) {
  var pts = (route.track || route.waypoints.map(function (w) { return [w.lat, w.lng]; })).map(function (p) { return [p[0], p[1]]; });
  if (!pts.length) return;
  var line = L.polyline(pts, { color: cssVar('--accent'), weight: 4, opacity: 0.9 }).addTo(map);
  map.fitBounds(line.getBounds(), { padding: [30, 30] });
  L.circleMarker(pts[0], { color: cssVar('--success'), fillColor: cssVar('--success'), fillOpacity: 1, radius: 7, weight: 2 })
    .addTo(map).bindTooltip('Start');
  L.marker(pts[pts.length - 1], {
    icon: L.divIcon({ html: '<div style="font-size:20px;line-height:1;">🏁</div>', className: '', iconAnchor: [4, 20] })
  }).addTo(map).bindTooltip('Finish');
  drawProfile(route.track);
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

(function () {
  map = L.map('routeMap').setView([PAGE.lat, PAGE.lng], 10);
  HWMap.attach(map, { page: 'routes', base: 'scheme' });
  document.getElementById('profileChart').addEventListener('mouseleave', function () {
    if (dot) { map.removeLayer(dot); dot = null; }
  });
  fetch('/planner/routes/' + PAGE.id)
    .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
    .then(drawRoute)
    .catch(function () { say('The route could not be loaded.', 'error'); });
})();

// ── Rename ──
function startRename() {
  var form = document.getElementById('renameForm'), input = document.getElementById('nameInput');
  form.hidden = false;
  input.focus(); input.select();
}

function stopRename() {
  document.getElementById('renameForm').hidden = true;
  document.getElementById('nameInput').value = PAGE.name;
}

function nameKey(e) { if (e.key === 'Escape') stopRename(); }

function saveName(e) {
  e.preventDefault();
  var input = document.getElementById('nameInput'), name = input.value.trim();
  if (!name) { input.focus(); return false; }
  if (name === PAGE.name) { stopRename(); return false; }
  postJSON('/routes/' + PAGE.id, { name: name })
    .then(function (d) {
      PAGE.name = d.name;
      document.getElementById('routeName').textContent = d.name;
      document.title = d.name + ' · Routes — Headwind';
      stopRename();
    })
    .catch(function (err) { say(esc(err.message), 'error'); });
  return false;
}

// ── Sport ──
function setSport(sel) {
  var before = sel.getAttribute('data-was') || '';
  sel.disabled = true;
  postJSON('/routes/' + PAGE.id, { sportType: sel.value })
    .then(function () { sel.setAttribute('data-was', sel.value); loadActivities(); })   // which activities count depends on the sport
    .catch(function (e) { sel.value = before; say(esc(e.message), 'error'); })
    .finally(function () { sel.disabled = false; });
}

// ── Delete ──
function deleteRoute() {
  if (!confirm('Delete the route ' + PAGE.name + '? This cannot be undone.')) return;
  fetch('/planner/routes/' + PAGE.id, { method: 'DELETE' })
    .then(function (r) {
      if (!r.ok) throw new Error(r.status);
      try { sessionStorage.setItem(FLASH_KEY, JSON.stringify({ html: esc(PAGE.name) + ' deleted.', kind: 'success' })); } catch (e) {}
      location.href = '/routes/';
    })
    .catch(function () { say('The route could not be deleted.', 'error'); });
}

// ── Done before: the activities that followed this route, and their moving times ──
function loadActivities() {
  fetch('/routes/' + PAGE.id + '/activities')
    .then(function (r) { return r.ok ? r.text() : ''; })
    .then(function (html) {
      if (!html.trim()) return;
      document.getElementById('routeActivities').outerHTML = html;
      drawTimes();
    });
}

function drawTimes() {
  var el = document.getElementById('routeChart');
  if (!el || !window.Chart) return;
  var s = JSON.parse(el.dataset.series);
  new Chart(el, { type: 'line',
    data: { labels: s.map(function (p) { return p.d; }),
            datasets: [{ data: s.map(function (p) { return p.secs; }), borderColor: cssVar('--border-strong'), borderWidth: 1, tension: 0,
                         pointRadius: 4, pointBackgroundColor: cssVar('--accent'), pointBorderWidth: 0 }] },
    options: { animation: false, maintainAspectRatio: false,
      onClick: function (e, items) { if (items.length) location.href = '/activities/' + s[items[0].index].id; },
      plugins: { legend: { display: false }, tooltip: { callbacks: {
        title: function (c) { return s[c[0].dataIndex].name || c[0].label; },
        label: function (c) { return c.label + ': ' + UNITS.fmtMinSec(c.parsed.y) + (s[c.dataIndex].reversed ? ' (the other way round)' : ''); } } } },
      scales: { x: { ticks: { maxTicksLimit: 6, font: { size: 10 } }, grid: { display: false } },
                y: { ticks: { font: { size: 10 }, callback: function (v) { return UNITS.fmtMinSec(v); } },
                     title: { display: true, text: 'moving time (lower is quicker)', font: { size: 10 } } } } } });
}

// ── Segments on this route: listed under the map and drawn on it; pointing at one lights it ──
var segLayers = [];
function loadSegments() {
  fetch('/routes/' + PAGE.id + '/segments')
    .then(function (r) { return r.ok ? r.text() : ''; })
    .then(function (html) {
      if (!html.trim()) return;
      document.getElementById('routeSegments').outerHTML = html;
      var card = document.getElementById('routeSegments'), shapes = JSON.parse(card.dataset.shapes);
      segLayers = shapes.map(function (shape) {
        return L.polyline(shape, { color: cssVar('--c-blue'), weight: 5, opacity: 0.85 }).addTo(map);
      });
      segLayers.forEach(function (layer, i) {
        var tr = card.querySelector('tr[data-segment="' + i + '"]');
        layer.bindTooltip(tr.cells[0].textContent.trim(), { sticky: true });
        layer.on('mouseover', function () { litSegment(i, true); });
        layer.on('mouseout', function () { litSegment(i, false); });
        layer.on('click', function () { location.href = tr.querySelector('a').href; });
        tr.addEventListener('mouseenter', function () { litSegment(i, true); });
        tr.addEventListener('mouseleave', function () { litSegment(i, false); });
      });
    });
}

function litSegment(i, on) {
  var tr = document.querySelector('#routeSegments tr[data-segment="' + i + '"]');
  if (tr) tr.classList.toggle('lit', on);
  segLayers[i].setStyle({ weight: on ? 8 : 5, opacity: on ? 1 : 0.85 });
  if (on) segLayers[i].bringToFront();
}

loadSegments();
loadActivities();
