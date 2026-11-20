var PAGE = JSON.parse(document.getElementById('plannerData').textContent);
// ── Map setup ─────────────────────────────────────────────────────
var map = L.map('plannerMap', { zoomControl: false })
           .setView([PAGE.lat, PAGE.lng], 11);

L.control.zoom({ position: 'topright' }).addTo(map);

HWMap.attach(map, { page: 'routes', base: 'scheme' });      // starts on the grey that matches the page

// ── State ─────────────────────────────────────────────────────────
var waypoints  = [];   // [{lat, lng}, ...]
var markers    = [];   // L.Marker[]
var polyline   = null;
var savedRoutes = [];
var clickTimer  = null;
var shown       = null;   // a saved route that follows a line, while it's on the map: {id, name, track, ...}
var trackLine   = null;
var elevChart   = null;
var elevDot     = null;
var copyName    = '';     // the name the save form offers for an edited copy

// ── Icons ─────────────────────────────────────────────────────────
function makeIcon(type) {
  var cls = 'wp-dot' + (type === 'start' ? ' start' : type === 'end' ? ' end' : '');
  return L.divIcon({
    className: 'wp-icon',
    html: '<div class="' + cls + '"></div>',
    iconSize:   [14, 14],
    iconAnchor: [7, 7],
  });
}

function refreshIcons() {
  markers.forEach(function(m, i) {
    var type = i === 0 ? 'start' : (i === markers.length - 1 ? 'end' : '');
    m.setIcon(makeIcon(type));
  });
}

// ── Click to add waypoint (dblclick guard) ────────────────────────
map.on('click', function(e) {
  if (shown) return;                                  // a line, not waypoints: Edit as a copy first
  clickTimer = setTimeout(function() { addWaypoint(e.latlng); }, 200);
});
map.on('dblclick', function() { clearTimeout(clickTimer); });

function addWaypoint(latlng) {
  var wp  = { lat: latlng.lat, lng: latlng.lng };
  var idx = waypoints.length;
  waypoints.push(wp);

  var m = L.marker(latlng, { draggable: true, icon: makeIcon('') }).addTo(map);
  m._wpIdx = idx;
  m.on('drag', function(e) {
    waypoints[m._wpIdx] = { lat: e.latlng.lat, lng: e.latlng.lng };
    refreshPolyline();
    refreshStats();
  });
  markers.push(m);

  refreshIcons();
  refreshPolyline();
  refreshStats();
}

// ── Undo / Clear ──────────────────────────────────────────────────
function undo() {
  if (!waypoints.length) return;
  waypoints.pop();
  map.removeLayer(markers.pop());
  refreshIcons();
  refreshPolyline();
  refreshStats();
}

function clearAll() {
  if (waypoints.length && !confirm('Clear all waypoints?')) return;
  waypoints = [];
  markers.forEach(function(m) { map.removeLayer(m); });
  markers = [];
  refreshPolyline();
  refreshStats();
}

// ── Polyline ──────────────────────────────────────────────────────
function refreshPolyline() {
  if (polyline) { map.removeLayer(polyline); polyline = null; }
  if (waypoints.length >= 2) {
    polyline = L.polyline(
      waypoints.map(function(w) { return [w.lat, w.lng]; }),
      { color: cssVar('--accent'), weight: 3, opacity: 0.9 }
    ).addTo(map);
  }
}

// ── Distance (Haversine, miles) ───────────────────────────────────
function haversineMi(lat1, lng1, lat2, lng2) {
  var R    = 3958.8;
  var rad  = Math.PI / 180;
  var phi1 = lat1 * rad, phi2 = lat2 * rad;
  var dphi = (lat2 - lat1) * rad, dlam = (lng2 - lng1) * rad;
  var a = Math.sin(dphi / 2) * Math.sin(dphi / 2) +
          Math.cos(phi1) * Math.cos(phi2) * Math.sin(dlam / 2) * Math.sin(dlam / 2);
  return R * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
}

function totalMiles() {
  var d = 0;
  for (var i = 1; i < waypoints.length; i++) {
    d += haversineMi(
      waypoints[i-1].lat, waypoints[i-1].lng,
      waypoints[i].lat,   waypoints[i].lng
    );
  }
  return d;
}

function refreshStats() {
  var mi  = totalMiles();
  var has = waypoints.length >= 2;
  document.getElementById('statDist').textContent = has ? UNITS.toDist(mi * 1609.344).toFixed(1) + ' ' + UNITS.dist : '—';   // measured in miles, shown in the rider's unit
  document.getElementById('statWpts').textContent = waypoints.length;
  document.getElementById('btnUndo').disabled   = waypoints.length === 0;
  document.getElementById('btnClear').disabled  = waypoints.length === 0;
  document.getElementById('btnSave').disabled   = !has;
  document.getElementById('btnExport').disabled = !has;
}

// ── Save flow ─────────────────────────────────────────────────────
function showSaveForm() {
  document.getElementById('saveActions').style.display = 'none';
  document.getElementById('saveForm').style.display    = 'flex';
  document.getElementById('saveInput').value = copyName;
  document.getElementById('saveInput').focus();
}

function hideSaveForm() {
  document.getElementById('saveForm').style.display    = 'none';
  document.getElementById('saveActions').style.display = 'flex';
}

document.getElementById('saveInput').addEventListener('keydown', function(e) {
  if (e.key === 'Enter')  confirmSave();
  if (e.key === 'Escape') hideSaveForm();
});

function confirmSave() {
  var name = document.getElementById('saveInput').value.trim() || 'My Route';
  fetch('/planner/routes', {
    method:  'POST',
    headers: { 'Content-Type': 'application/json' },
    body:    JSON.stringify({ name: name, waypoints: waypoints }),
  })
  .then(function(r) { return r.json(); })
  .then(function() {
    hideSaveForm();
    copyName = '';
    loadSavedRoutes();
  });
}

// ── Export GPX ────────────────────────────────────────────────────
function exportGPX() {
  var name = document.getElementById('saveInput') && document.getElementById('saveInput').value.trim();
  name = name || prompt('Name for this GPX file:', 'My Route') || 'My Route';

  var btn     = document.getElementById('btnExport');
  var spinner = document.getElementById('exportSpinner');
  btn.disabled     = true;
  spinner.style.display = 'block';

  fetch('/planner/export', {
    method:  'POST',
    headers: { 'Content-Type': 'application/json' },
    body:    JSON.stringify({ name: name, waypoints: waypoints }),
  })
  .then(function(r) {
    if (!r.ok) throw new Error('Export failed');
    return r.blob();
  })
  .then(function(blob) {
    var url = URL.createObjectURL(blob);
    var a   = document.createElement('a');
    a.href  = url;
    a.download = name.replace(/ /g, '_') + '.gpx';
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    setTimeout(function() { URL.revokeObjectURL(url); }, 2000);
  })
  .catch(function() { alert('Export failed — check the console.'); })
  .finally(function() {
    spinner.style.display = 'none';
    refreshStats();
  });
}

// ── Saved routes ──────────────────────────────────────────────────
function escapeHtml(s) {
  return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
    return {'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c];
  });
}

function loadSavedRoutes() {
  fetch('/planner/routes')
    .then(function(r) { return r.json(); })
    .then(function(routes) {
      savedRoutes = routes;
      renderSavedRoutes();
    });
}

function renderSavedRoutes() {
  var el = document.getElementById('routeList');
  if (!savedRoutes.length) {
    el.innerHTML = '<div class="empty-hint">No saved routes yet.</div>';
    return;
  }
  el.innerHTML = savedRoutes.map(function(r) {
    var meta = [UNITS.toDist(r.distM).toFixed(1) + ' ' + UNITS.dist];
    if (r.gainM != null) meta.push(Math.round(UNITS.toElev(r.gainM)) + ' ' + UNITS.elev + ' climb');
    meta.push(r.hasTrack ? SOURCES[r.source] || r.source : r.count + ' wpts');
    if (r.rider) meta.push(escapeHtml(r.rider));
    return '<div class="route-row" data-id="' + r.id + '">' +
      '<div class="route-info" data-click="loadSaved(' + r.id + ')" title="Load onto map">' +
        '<div class="route-name">' + escapeHtml(r.name) + '</div>' +
        '<div class="route-meta">' + meta.join(' &middot; ') + '</div>' +
      '</div>' +
      '<div class="route-actions">' +
        '<a href="/planner/routes/' + r.id + '/export.gpx" class="icon-btn" title="Download GPX">&#x2193;</a>' +
        '<button class="icon-btn danger" data-click="deleteRoute(' + r.id + ')" title="Delete">&#x2715;</button>' +
      '</div>' +
    '</div>';
  }).join('');
}

var SOURCES = { gpx: 'from a GPX file', activity: 'from an activity', strava: 'from Strava', planner: 'drawn here' };

function loadSaved(id) {
  return fetch('/planner/routes/' + id)
    .then(function(r) { if (!r.ok) throw new Error(r.status); return r.json(); })
    .then(function(route) {
      if (waypoints.length && !confirm('Replace current route with "' + route.name + '"?')) return;
      closeTrack();
      if (route.track) { showTrack(route); return; }
      copyName = '';
      placeWaypoints(route.waypoints);
    });
}

function clearWaypoints() {
  waypoints = [];
  markers.forEach(function(m) { map.removeLayer(m); });
  markers = [];
  if (polyline) { map.removeLayer(polyline); polyline = null; }
}

function placeWaypoints(wps) {
      clearWaypoints();
      wps.forEach(function(wp) {
        var idx = waypoints.length;
        waypoints.push(wp);
        var m = L.marker(L.latLng(wp.lat, wp.lng), { draggable: true, icon: makeIcon('') }).addTo(map);
        m._wpIdx = idx;
        m.on('drag', function(e) {
          waypoints[m._wpIdx] = { lat: e.latlng.lat, lng: e.latlng.lng };
          refreshPolyline();
          refreshStats();
        });
        markers.push(m);
      });

      refreshIcons();
      refreshPolyline();
      refreshStats();

      if (wps.length) {
        map.fitBounds(
          L.latLngBounds(wps.map(function(w) { return [w.lat, w.lng]; })),
          { padding: [40, 40] }
        );
      }
}

// ── A route that follows a line ───────────────────────────────────
// Drawn as one line with its elevation profile; hovering the profile marks the place on the map.
function showTrack(route) {
  clearWaypoints();
  refreshStats();
  shown = route;
  var pts = route.track.map(function(p) { return [p[0], p[1]]; });
  trackLine = L.polyline(pts, { color: cssVar('--accent'), weight: 4, opacity: 0.9 }).addTo(map);
  map.fitBounds(trackLine.getBounds(), { padding: [40, 40] });

  document.getElementById('drawPanel').style.display  = 'none';
  document.getElementById('trackPanel').style.display = 'flex';
  document.getElementById('trackName').textContent = route.name;
  var src = document.getElementById('trackSource');
  src.innerHTML = (route.sportType ? escapeHtml(route.sportType.replace(/([a-z])([A-Z])/g, '$1 $2')) + ', ' : '') +
    (route.source === 'activity' && route.sourceId
      ? '<a href="/activities/' + encodeURIComponent(route.sourceId) + '" style="color:var(--accent)">' + SOURCES.activity + '</a>'
      : escapeHtml(SOURCES[route.source] || route.source)) + ' &middot; ' + route.track.length + ' points';
  document.getElementById('trackDist').textContent = UNITS.toDist(route.distM).toFixed(1) + ' ' + UNITS.dist;
  document.getElementById('trackGain').textContent = route.gainM != null ? Math.round(UNITS.toElev(route.gainM)) + ' ' + UNITS.elev : '—';
  document.getElementById('trackExport').href = '/planner/routes/' + route.id + '/export.gpx';
  drawProfile(route.track);
}

function closeTrack() {
  if (trackLine) { map.removeLayer(trackLine); trackLine = null; }
  if (elevDot)   { map.removeLayer(elevDot); elevDot = null; }
  if (elevChart) { elevChart.destroy(); elevChart = null; }
  document.getElementById('elevBox').style.display    = 'none';
  document.getElementById('trackPanel').style.display = 'none';
  document.getElementById('drawPanel').style.display  = 'flex';
  shown = null;
}

// Waypoints a few metres off the line at most (services/planned_routes.as_waypoints), to drag and save as a new route
function editTrack() {
  if (!shown) return;
  var name = shown.name;
  fetch('/planner/routes/' + shown.id + '/waypoints')
    .then(function(r) { return r.json(); })
    .then(function(d) {
      closeTrack();
      copyName = (name + ' (edited)').slice(0, 100);
      placeWaypoints(d.waypoints);
    });
}

function drawProfile(track) {
  var box = document.getElementById('elevBox');
  if (!window.Chart || !track.some(function(p) { return p[2] != null; })) { box.style.display = 'none'; return; }
  var along = [0];
  for (var i = 1; i < track.length; i++) {
    along.push(along[i - 1] + haversineMi(track[i-1][0], track[i-1][1], track[i][0], track[i][1]) * 1609.344);
  }
  var step = Math.max(1, Math.floor(track.length / 600));
  var idx = [];
  for (var j = 0; j < track.length; j += step) idx.push(j);
  if (idx[idx.length - 1] !== track.length - 1) idx.push(track.length - 1);
  box.style.display = 'block';
  elevChart = new Chart(document.getElementById('elevChart'), {
    type: 'line',
    data: {
      labels: idx.map(function(k) { return UNITS.toDist(along[k]).toFixed(1); }),
      datasets: [{ data: idx.map(function(k) { return track[k][2] != null ? UNITS.toElev(track[k][2]) : null; }),
                   borderColor: cssVar('--accent'), backgroundColor: cssVar('--accent', 0.18), fill: true,
                   borderWidth: 1.5, pointRadius: 0, tension: 0.2, spanGaps: true }],
    },
    options: {
      animation: false, maintainAspectRatio: false, interaction: { mode: 'index', intersect: false },
      onHover: function(e, items) {
        if (!items.length) return;
        var p = track[idx[items[0].index]];
        if (!elevDot) elevDot = L.circleMarker([p[0], p[1]], { radius: 7, color: cssVar('--card-bg'), weight: 2,       // as the activity page's
                                                               fillColor: cssVar('--c-yellow'), fillOpacity: 1, interactive: false }).addTo(map);
        else elevDot.setLatLng([p[0], p[1]]);
      },
      plugins: { legend: { display: false }, tooltip: { displayColors: false, callbacks: {
        title: function(c) { return c[0].label + ' ' + UNITS.dist; },
        label: function(c) { return Math.round(c.parsed.y) + ' ' + UNITS.elev; } } } },
      scales: { x: { ticks: { maxTicksLimit: 8, font: { size: 10 } }, grid: { display: false } },
                y: { ticks: { maxTicksLimit: 4, font: { size: 10 } } } },
    },
  });
  document.getElementById('elevChart').addEventListener('mouseleave', function() {
    if (elevDot) { map.removeLayer(elevDot); elevDot = null; }
  });
}

// ── Import GPX ────────────────────────────────────────────────────
function importGPX(input) {
  if (!input.files.length) return;
  var fd = new FormData();
  Array.prototype.forEach.call(input.files, function(f) { fd.append('files', f); });
  var out = document.getElementById('importResult');
  out.textContent = 'Reading ' + input.files.length + ' file' + (input.files.length === 1 ? '' : 's') + '…';
  fetch('/planner/routes/import', { method: 'POST', body: fd })
    .then(function(r) { if (!r.ok) throw new Error(r.status); return r.json(); })
    .then(function(res) {
      var saved = res.filter(function(x) { return x.status === 'saved'; });
      var lines = [];
      if (saved.length) lines.push(saved.length + ' route' + (saved.length === 1 ? '' : 's') + ' saved');
      res.forEach(function(x) {
        if (x.status === 'exists') lines.push(escapeHtml(x.file) + ': already saved');
        if (x.status === 'empty') lines.push('<span class="bad">' + escapeHtml(x.file) + ': no points in it</span>');
        if (x.status === 'unreadable') lines.push('<span class="bad">' + escapeHtml(x.file) + ': not a GPX file Headwind can read</span>');
      });
      out.innerHTML = lines.join('<br>');
      loadSavedRoutes();
      var first = saved[0] || res.find(function(x) { return x.id; });
      if (first && !waypoints.length) loadSaved(first.id);
    })
    .catch(function() { out.innerHTML = '<span class="bad">The import failed.</span>'; })
    .finally(function() { input.value = ''; });
}

function deleteRoute(id) {
  var route = savedRoutes.find(function(r) { return r.id === id; });
  var name  = route ? route.name : 'this route';
  if (!confirm('Delete "' + name + '"? This cannot be undone.')) return;
  fetch('/planner/routes/' + id, { method: 'DELETE' })
    .then(function() {
      if (shown && shown.id === id) closeTrack();
      loadSavedRoutes();
    });
}

// ── Init ──────────────────────────────────────────────────────────
refreshStats();
loadSavedRoutes();
if (PAGE.openRoute) loadSaved(PAGE.openRoute).catch(function() {});

function chooseGpxFiles() { document.getElementById('gpxFiles').click(); }
