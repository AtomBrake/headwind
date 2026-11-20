var PAGE = JSON.parse(document.getElementById('rideData').textContent);

// ── Commute and sport ────────────────────────────────────────────
function saveCommute(box) {
  fetch('/rides/' + PAGE.id + '/commute', {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: 'commute=' + (box.checked ? '1' : '0')
  }).then(function(r) {
    if (r.status !== 204) { box.checked = !box.checked; return; }
    var s = document.getElementById('commuteSaved');
    s.style.display = 'inline';
    setTimeout(function() { s.style.display = 'none'; }, 1500);
  }).catch(function() { box.checked = !box.checked; });
}
function typeChanged(sel) {
  var f = sel.form, cur = f.getAttribute('data-current');
  if (!sel.value || sel.value === cur) { sel.value = cur; return; }
  var label = sel.options[sel.selectedIndex].text.toLowerCase();
  var isRide = function (s) { return !s || /ride|cycl/i.test(s); };     // as services/sports.RIDE_SQL
  var moves = isRide(sel.value) !== isRide(cur);
  if (confirm('Change this to ' + (/^[aeiou]/.test(label) ? 'an ' : 'a ') + label + '?' + (moves ? (isRide(cur) ? ' It loses its bike and its ride best efforts and segment times, and its calories are worked out again for the new sport.' : ' It gets your default bike, and its calories are worked out again as a ride.') : ''))) f.submit();
  else sel.value = cur;
}

// ── Photos ───────────────────────────────────────────────────────
function openPhoto(a) {
  var d = document.getElementById('photoDialog');
  if (!d.showModal) return true;                        // no <dialog>: just open the picture
  document.getElementById('photoDialogImg').src = a.href;
  document.getElementById('photoDialogImg').alt = a.getAttribute('data-caption') || 'Photo from this activity';
  document.getElementById('photoDialogCaption').textContent = a.getAttribute('data-caption') || '';
  d.showModal();
  return false;
}
function addPhotos(input) {
  if (!input.files.length) return;
  input.closest('label').firstChild.textContent = 'Adding…';
  input.form.submit();
}
function captionKey(e, input) {                         // Enter saves (by leaving the field), rather than submitting anything
  if (e.key === 'Enter') { e.preventDefault(); input.blur(); }
}
function savePhotoCaption(input) {
  var fig = input.closest('figure');
  fetch('/rides/' + PAGE.id + '/photos/' + fig.getAttribute('data-pid') + '/caption', {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: 'caption=' + encodeURIComponent(input.value)
  }).then(function(r) {
    if (r.status !== 204) { input.classList.add('is-error'); return; }
    var text = input.value.trim();
    input.value = text;
    input.classList.remove('is-error');
    fig.querySelector('a').setAttribute('data-caption', text);
    fig.querySelector('img').alt = text || 'Photo from this activity';
  }).catch(function() { input.classList.add('is-error'); });
}
function photoOrder(grid) {
  return Array.prototype.map.call(grid.querySelectorAll('figure[data-pid]'), function(f) { return f.getAttribute('data-pid'); });
}
function savePhotoOrder(grid) {
  var body = new URLSearchParams();
  photoOrder(grid).forEach(function(id) { body.append('id', id); });
  fetch('/rides/' + PAGE.id + '/photos/order', { method: 'POST', body: body })
    .then(function(r) { if (r.status !== 204) location.reload(); })       // added or deleted in another tab: show what's there now
    .catch(function() { location.reload(); });
}
function movePhoto(btn, step) {
  var fig = btn.closest('figure'), grid = fig.parentNode;
  var other = step < 0 ? fig.previousElementSibling : fig.nextElementSibling;
  if (!other) return;
  grid.insertBefore(fig, step < 0 ? other : other.nextSibling);
  btn.focus();
  savePhotoOrder(grid);
}
(function() {
  var grid = document.getElementById('photoGrid'), dragged = null, before = '';
  if (!PAGE.canEdit || !grid || grid.children.length < 2) return;
  grid.addEventListener('dragstart', function(e) {         // the thumbnail is the handle (a link and an image drag anyway), not the caption field
    if (!e.target.closest || !e.target.closest('a')) return;
    dragged = e.target.closest('figure');
    before = photoOrder(grid).join();
    e.dataTransfer.effectAllowed = 'move';
    dragged.style.opacity = '0.4';
  });
  grid.addEventListener('dragover', function(e) {
    if (!dragged) return;
    e.preventDefault();
    var over = e.target.closest && e.target.closest('figure');
    if (!over || over === dragged) return;
    var box = over.getBoundingClientRect();
    grid.insertBefore(dragged, e.clientX > box.left + box.width / 2 ? over.nextSibling : over);
  });
  grid.addEventListener('drop', function(e) { if (dragged) e.preventDefault(); });
  grid.addEventListener('dragend', function() {
    if (!dragged) return;
    dragged.style.opacity = '';
    dragged = null;
    if (photoOrder(grid).join() !== before) savePhotoOrder(grid);
  });
})();

// ── Same route (routes/matched.py): the other times this way, fetched after the page; nothing when there are none
(function () {
  var slot = document.getElementById('matchedCard');
  if (!slot) return;
  fetch(PAGE.matchedUrl).then(function (r) { return r.ok ? r.text() : ''; }).then(function (html) {
    if (!html.trim()) { slot.remove(); return; }
    slot.outerHTML = html;
    var el = document.getElementById('matchedChart');
    if (!el || !window.Chart) return;
    var s = JSON.parse(el.dataset.series);
    new Chart(el, { type: 'line',
      data: { labels: s.map(function (p) { return p.d; }),
              datasets: [{ data: s.map(function (p) { return p.secs; }), borderColor: cssVar('--border-strong'), borderWidth: 1, tension: 0,
                           pointRadius: s.map(function (p) { return p.current ? 6 : 3; }),
                           pointBackgroundColor: s.map(function (p) { return p.current ? cssVar('--accent') : cssVar('--text-muted'); }),
                           pointBorderWidth: 0 }] },
      options: { animation: false, maintainAspectRatio: false,
        onClick: function (e, items) { if (items.length && !s[items[0].index].current) location.href = '/rides/' + s[items[0].index].id; },
        plugins: { legend: { display: false }, tooltip: { callbacks: {
          title: function (c) { return s[c[0].dataIndex].name || c[0].label; },
          label: function (c) { return c.label + ': ' + UNITS.fmtMinSec(c.parsed.y); } } } },
        scales: { x: { ticks: { maxTicksLimit: 6, font: { size: 10 } }, grid: { display: false } },
                  y: { ticks: { font: { size: 10 }, callback: function (v) { return UNITS.fmtMinSec(v); } },
                       title: { display: true, text: 'moving time (lower is quicker)', font: { size: 10 } } } } } });
  });
})();

(function() {
  var coords = PAGE.coords || [];
  if (!coords.length) return;
  window._rideCoords = coords;
  window._rideAlt    = PAGE.alt;
  window._rideTime   = PAGE.time;
  var map = L.map('map');
  window._rideMap = map;
  var zw = PAGE.zwiftWorld;
  if (zw) {
    // A virtual ride: drawn over its Zwift world's map alone, with no real place around or under it, and the view kept to that world
    L.imageOverlay(zw.url, zw.bounds, { attribution: zw.credit, interactive: false }).addTo(map);
    map.setMaxBounds(zw.bounds);
    map.options.maxBoundsViscosity = 1;
    map.setMinZoom(map.getBoundsZoom(zw.bounds));
    map.setMaxZoom(18);                                   // no tiles to take it from
    map.getContainer().style.background = cssVar('--card-bg');
  }
  var line = L.polyline(coords, { color: cssVar('--accent'), weight: 3 }).addTo(map);
  map.fitBounds(line.getBounds(), { padding: [20, 20] });
  L.circleMarker(coords[0], {
    color: cssVar('--success'), fillColor: cssVar('--success'), fillOpacity: 1, radius: 7, weight: 2
  }).addTo(map).bindPopup('Start');
  L.marker(coords[coords.length - 1], {
    icon: L.divIcon({ html: '<div style="font-size:20px;line-height:1;">🏁</div>', className: '', iconAnchor: [10, 20] })
  }).addTo(map).bindPopup('Finish');

  // Distance along the track at each point, in metres: the distance stream where it matches the points, otherwise worked out from them,
  // and for a summary polyline (which cuts corners) stretched to the activity's own distance
  var dist = PAGE.dist;
  if (!dist) {
    dist = [0];
    for (var i = 1; i < coords.length; i++) dist.push(dist[i - 1] + L.latLng(coords[i - 1]).distanceTo(coords[i]));
    var total = PAGE.distance, last = dist[dist.length - 1];
    if (!PAGE.coordsFromStream && total > 0 && last > 0) dist = dist.map(function (d) { return d * total / last; });
  }
  for (var k = 1; k < dist.length; k++) if (dist[k] == null || dist[k] < dist[k - 1]) dist[k] = dist[k - 1];   // gaps, and GPS going back
  window._rideDist = dist;

  // The track in pixels at the current zoom (map.project: the same wherever the map is panned), worked out again on each zoom. The
  // direction arrows and distance markers are spaced on it, and the map's cursor is matched to it.
  var proj = null;
  window._rideProj = function () {
    var z = map.getZoom();
    if (!proj || proj.zoom !== z) {
      var pts = coords.map(function (c) { return map.project(c, z); }), len = 0;
      for (var i = 1; i < pts.length; i++) len += pts[i].distanceTo(pts[i - 1]);
      proj = { zoom: z, pts: pts, len: len };
    }
    return proj;
  };
  function view() { return map.getPixelBounds().pad(0.25); }

  // Direction arrows: a chevron every ARROW_PX of track on screen, pointing the way it went, so they stay evenly spread at any zoom.
  // Counted from the start, so they don't move when the map is dragged; only the ones in view are drawn.
  var ARROW_PX = 90, arrowLayer = L.layerGroup();
  var chevron = '<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 14 14" fill="none" stroke-linecap="round" stroke-linejoin="round">'
              + '<path d="M4 2.5 L10 7 L4 11.5" style="stroke:var(--accent)" stroke-width="5"/>'           // the track's colour round a light centre,
              + '<path d="M4 2.5 L10 7 L4 11.5" style="stroke:var(--on-accent)" stroke-width="2"/></svg>';  // to show on any map type
  function drawArrows() {
    arrowLayer.clearLayers();
    if (!map.hasLayer(arrowLayer)) return;
    var pr = window._rideProj(), p = pr.pts, box = view(), next = ARROW_PX / 2, run = 0, n = 0;
    for (var i = 1; i < p.length && n < 400; i++) {
      var seg = p[i].distanceTo(p[i - 1]);
      while (seg > 0 && run + seg >= next) {
        var f = (next - run) / seg, at = L.point(p[i - 1].x + (p[i].x - p[i - 1].x) * f, p[i - 1].y + (p[i].y - p[i - 1].y) * f);
        if (box.contains(at)) {
          var deg = Math.atan2(p[i].y - p[i - 1].y, p[i].x - p[i - 1].x) * 180 / Math.PI;
          L.marker(map.unproject(at, pr.zoom), { interactive: false, keyboard: false, icon: L.divIcon({ className: '', iconSize: [14, 14], iconAnchor: [7, 7],
            html: '<div class="map-chevron" style="transform:rotate(' + deg.toFixed(0) + 'deg)">' + chevron + '</div>' }) }).addTo(arrowLayer);
          n++;
        }
        next += ARROW_PX;
      }
      run += seg;
    }
  }

  // Distance markers: every mile or km in the rider's unit, or every 2, 5, 10, ... when they'd be closer than DIST_PX on screen
  var DIST_PX = 70, distLayer = L.layerGroup();
  function drawDistances() {
    distLayer.clearLayers();
    var total = dist[dist.length - 1];
    if (!map.hasLayer(distLayer) || !(total > 0)) return;
    var pr = window._rideProj(), unitPx = pr.len / total * UNITS.distM;
    var every = [1, 2, 5, 10, 20, 50, 100, 200].filter(function (n) { return n * unitPx >= DIST_PX; })[0] || 500;
    var box = view(), i = 1;
    for (var n = every; n * UNITS.distM < total; n += every) {
      var m = n * UNITS.distM;
      while (i < dist.length - 1 && dist[i] < m) i++;
      var span = dist[i] - dist[i - 1], f = span > 0 ? (m - dist[i - 1]) / span : 0;
      var at = L.point(pr.pts[i - 1].x + (pr.pts[i].x - pr.pts[i - 1].x) * f, pr.pts[i - 1].y + (pr.pts[i].y - pr.pts[i - 1].y) * f);
      if (!box.contains(at)) continue;
      L.marker(map.unproject(at, pr.zoom), { interactive: false, keyboard: false, zIndexOffset: 500,
        icon: L.divIcon({ className: '', iconSize: [0, 0], html: '<div class="map-dist">' + n + '</div>' }) }).addTo(distLayer);
    }
  }
  arrowLayer.on('add', drawArrows);
  distLayer.on('add', drawDistances);
  map.on('moveend', function () { drawArrows(); drawDistances(); });          // after a zoom too

  var windLayer = null;
  if (PAGE.windDir != null && PAGE.windKph) {
    // Wind arrows: ten along the track, all pointing the way the wind blew
    windLayer = L.layerGroup();
    var windDir = PAGE.windDir;
    var windKph = PAGE.windKph;
    var arrowDeg = (windDir + 180) % 360;
    var color = windKph < 15 ? 'var(--c-blue)' : windKph < 30 ? 'var(--c-amber)' : 'var(--danger)';
    var sw = windKph < 15 ? 16 : windKph < 30 ? 18 : 20;
    var sh = Math.round(sw * 1.4);
    var svg = '<svg xmlns="http://www.w3.org/2000/svg" width="' + sw + '" height="' + sh + '" viewBox="0 0 10 14">'
            + '<polygon points="5,0 10,14 5,10 0,14" style="fill:' + color + ';stroke:var(--card-bg)" stroke-width="1" stroke-linejoin="round"/></svg>';
    var step = Math.max(1, Math.floor(coords.length / 10));
    for (var w = step; w < coords.length - 1; w += step) {
      L.marker(coords[w], {
        icon: L.divIcon({
          html: '<div style="transform:rotate(' + arrowDeg + 'deg);transform-origin:center;opacity:1;line-height:0;pointer-events:none;filter:drop-shadow(0 0 2px var(--shadow));">' + svg + '</div>',
          className: '',
          iconSize: [sw, sh],
          iconAnchor: [sw / 2, sh / 2]
        }),
        interactive: false, zIndexOffset: 1000
      }).addTo(windLayer);
    }
  }

  // The picker: map types (none for a Zwift ride, whose world's map is all there is) and what's drawn on the track, remembered per viewer
  HWMap.attach(map, { page: 'activity', base: 'satlabel', types: !zw, extras: (windLayer ? [
    { id: 'wind', name: 'Wind arrows', layer: windLayer, on: true },
  ] : []).concat([
    { id: 'direction', name: 'Direction arrows', layer: arrowLayer, on: true },
    { id: 'distance', name: 'Distance markers', layer: distLayer, on: false },
  ]) });
})();

function useElapsedTime() {
  fetch('/rides/' + PAGE.id + '/moving/elapsed', { method: 'POST' }).then(function(r) { if (r.ok) location.reload(); });
}

function setStart(e) {
  e.preventDefault();
  var m = document.getElementById('startMsg');
  fetch('/rides/' + PAGE.id + '/start', { method: 'POST', body: new URLSearchParams(new FormData(e.target)) })
    .then(function(r) { return r.json(); })
    .then(function(d) { if (d.error) { m.textContent = d.error; return; } location.href = '/rides/' + encodeURIComponent(d.id); })
    .catch(function() { m.textContent = 'Could not save it.'; });
  return false;
}

function dismissFlag() {
  fetch('/rides/' + PAGE.id + '/flag/dismiss', { method: 'POST' }).then(function(r) { if (r.ok) { var b = document.getElementById('flagBanner'); if (b) b.remove(); } });
}

function setWeather(v) {
  var m = document.getElementById('wxMsg');
  var body = new URLSearchParams({ condition: v });
  fetch('/rides/' + PAGE.id + '/weather', { method: 'POST', body: body })
    .then(function(r) { return r.json(); })
    .then(function(d) {
      if (d.error) { m.textContent = 'Could not save: ' + d.error; return; }
      m.textContent = d.manual ? 'Saved. Set by you; a backfill will not change it.' : 'Back to automatic' + (d.condition ? ': ' + d.condition : '') + '.';
    })
    .catch(function() { m.textContent = 'Could not reach the server.'; });
}

// ── Segment creation ─────────────────────────────────────────────
var _segState = { active: false, startIdx: 0, endIdx: null,
                  startMarker: null, endMarker: null, segLine: null, segLineGroup: null,
                  dragging: null };                 // 'start' or 'end' while that marker is held

function enterSegmentMode() {
  var coords = window._rideCoords || [];
  if (!coords.length) return;
  _segState.active = true;
  _segState.startIdx = 0;
  _segState.endIdx = coords.length - 1;
  _segState.segLineGroup = L.featureGroup();

  document.getElementById('segPanel').style.display = 'block';
  document.getElementById('segSliders').style.display = 'block';
  document.getElementById('segForm').style.display = 'none';

  var maxIdx = coords.length - 1;
  document.getElementById('segStartSlider').max = maxIdx;
  document.getElementById('segStartSlider').value = 0;
  document.getElementById('segEndSlider').max = maxIdx;
  document.getElementById('segEndSlider').value = maxIdx;

  updateSegmentFromSliders();
  window._rideMap.addLayer(_segState.segLineGroup);
  window._rideMap.getContainer().style.cursor = 'default';
  document.getElementById('map').scrollIntoView({ behavior: 'smooth', block: 'center' });
}

function adjustSegStart(delta) {
  var slider = document.getElementById('segStartSlider');
  var newVal = parseInt(slider.value) + delta;
  newVal = Math.max(0, Math.min(newVal, parseInt(slider.max)));
  slider.value = newVal;
  updateSegmentFromSliders('start');
}

function adjustSegEnd(delta) {
  var slider = document.getElementById('segEndSlider');
  var newVal = parseInt(slider.value) + delta;
  newVal = Math.max(0, Math.min(newVal, parseInt(slider.max)));
  slider.value = newVal;
  updateSegmentFromSliders('end');
}

function showSegmentForm() {
  document.getElementById('segSliders').style.display = 'none';
  document.getElementById('segForm').style.display = 'block';
  var nameInput = document.querySelector('#segForm input[name="name"]');
  if (nameInput) nameInput.focus();
}

function cancelSegment() {
  resetSegmentMode();
  document.getElementById('segPanel').style.display = 'none';
}

function resetSegmentMode() {
  var map = window._rideMap;
  if (_segState.segLineGroup && map) map.removeLayer(_segState.segLineGroup);
  _segState = { active: false, startIdx: 0, endIdx: null,
                startMarker: null, endMarker: null, segLine: null, segLineGroup: null,
                dragging: null };
  document.getElementById('segSliders').style.display = 'none';
  document.getElementById('segForm').style.display = 'none';
  if (map) map.getContainer().style.cursor = '';
}

function updateSegmentFromSliders(moved) {
  if (!_segState.active) return;
  var coords = window._rideCoords || [];
  var timeData = window._rideTime || [];
  var altData = window._rideAlt || [];

  var si = parseInt(document.getElementById('segStartSlider').value);
  var ei = parseInt(document.getElementById('segEndSlider').value);

  if (si > ei) {                        // crossed: the one being moved stops at the other, the other stays put
    if (moved === 'end') { ei = si; document.getElementById('segEndSlider').value = ei; }
    else                 { si = ei; document.getElementById('segStartSlider').value = si; }
  }
  _segState.startIdx = si;
  _segState.endIdx = ei;

  var segCoords = coords.slice(si, ei + 1);
  if (!segCoords.length) return;

  // Update markers and segment line
  if (_segState.segLineGroup) _segState.segLineGroup.clearLayers();

  // Segment line, under the markers and not clickable, so pressing a marker grabs the marker
  _segState.segLine = L.polyline(segCoords, { color: cssVar('--info'), weight: 5, opacity: 0.85, interactive: false })
    .addTo(_segState.segLineGroup);

  // Start marker
  _segState.startMarker = L.circleMarker(coords[si], {
    color: cssVar('--success'), fillColor: cssVar('--success'), fillOpacity: 1, radius: 10, weight: 2
  }).addTo(_segState.segLineGroup);
  _segState.startMarker.on('mousedown', function(e) { startSegDrag('start', e); });

  // End marker
  _segState.endMarker = L.circleMarker(coords[ei], {
    color: cssVar('--danger'), fillColor: cssVar('--danger'), fillOpacity: 1, radius: 10, weight: 2
  }).addTo(_segState.segLineGroup);
  _segState.endMarker.on('mousedown', function(e) { startSegDrag('end', e); });

  // Calculate distance
  var dist = 0;
  for (var i = si; i < ei; i++) {
    var R = 6371000;
    var lat1 = coords[i][0]*Math.PI/180, lat2 = coords[i+1][0]*Math.PI/180;
    var dlat = (coords[i+1][0]-coords[i][0])*Math.PI/180;
    var dlng = (coords[i+1][1]-coords[i][1])*Math.PI/180;
    var a = Math.sin(dlat/2)*Math.sin(dlat/2) + Math.cos(lat1)*Math.cos(lat2)*Math.sin(dlng/2)*Math.sin(dlng/2);
    dist += 2*R*Math.atan2(Math.sqrt(a), Math.sqrt(1-a));
  }
  var distMi = UNITS.toDist(dist);              // in the rider's unit, despite the name

  // Calculate elevation gain
  var elevGain = 0;
  if (altData.length === coords.length) {
    for (var k = si; k < ei; k++) {
      var dElev = altData[k + 1] - altData[k];
      if (dElev > 0) elevGain += dElev;
    }
  }

  // Update display
  var startDistMi = 0;
  for (var i = 0; i < si; i++) {
    var R = 6371000;
    var lat1 = coords[i][0]*Math.PI/180, lat2 = coords[i+1][0]*Math.PI/180;
    var dlat = (coords[i+1][0]-coords[i][0])*Math.PI/180;
    var dlng = (coords[i+1][1]-coords[i][1])*Math.PI/180;
    var a = Math.sin(dlat/2)*Math.sin(dlat/2) + Math.cos(lat1)*Math.cos(lat2)*Math.sin(dlng/2)*Math.sin(dlng/2);
    startDistMi += UNITS.toDist(2*R*Math.atan2(Math.sqrt(a), Math.sqrt(1-a)));
  }
  var endDistMi = startDistMi + distMi;

  document.getElementById('segStartDist').textContent = startDistMi.toFixed(1);
  document.getElementById('segEndDist').textContent = endDistMi.toFixed(1);
  document.getElementById('segLength').textContent = distMi.toFixed(2);
  document.getElementById('segElevation').textContent = Math.round(UNITS.toElev(elevGain));

  if (timeData[si] !== undefined) {
    document.getElementById('segStartTime').textContent = Math.round(timeData[si]/60) + 'm in';
  }
  if (timeData[ei] !== undefined) {
    document.getElementById('segEndTime').textContent = Math.round(timeData[ei]/60) + 'm in';
  }

  // Update hidden form values
  document.getElementById('segStartLat').value = coords[si][0];
  document.getElementById('segStartLng').value = coords[si][1];
  document.getElementById('segEndLat').value = coords[ei][0];
  document.getElementById('segEndLng').value = coords[ei][1];
  document.getElementById('segDistM').value = Math.round(dist);
  document.getElementById('segElevGainM').value = Math.round(elevGain);
  document.getElementById('segPolyline').value = JSON.stringify(segCoords);
}

// Holding a marker drags it, not the map, until the button comes up anywhere on the page.
function startSegDrag(which, e) {
  _segState.dragging = which;
  window._rideMap.dragging.disable();
  L.DomEvent.preventDefault(e.originalEvent);
}

// The route point under the cursor for the marker being dragged. Only the part of the route that keeps the start before the end is
// searched, and where a loop or an out-and-back passes under the cursor more than once, the pass nearest the marker's current place
// along the route wins, so the marker stays on the pass it is on.
function segSnapIdx(latlng, which) {
  var map = window._rideMap, coords = window._rideCoords || [];
  var lo = which === 'end' ? _segState.startIdx : 0;
  var hi = which === 'start' ? _segState.endIdx : coords.length - 1;
  var cur = which === 'start' ? _segState.startIdx : _segState.endIdx;
  var p = map.latLngToContainerPoint(latlng), d = [], nearest = Infinity;
  for (var i = lo; i <= hi; i++) {
    d[i - lo] = p.distanceTo(map.latLngToContainerPoint(coords[i]));
    if (d[i - lo] < nearest) nearest = d[i - lo];
  }
  var tol = nearest + 15, pick = cur, pickGap = Infinity, runBest = -1;     // pixels
  for (var j = lo; j <= hi + 1; j++) {
    if (j <= hi && d[j - lo] <= tol) {
      if (runBest < 0 || d[j - lo] < d[runBest - lo]) runBest = j;
    } else if (runBest >= 0) {                                               // one pass under the cursor ends here
      if (Math.abs(runBest - cur) < pickGap) { pickGap = Math.abs(runBest - cur); pick = runBest; }
      runBest = -1;
    }
  }
  return pick;
}

(function() {
  var map = window._rideMap;
  if (!map) return;

  map.on('mousemove', function(e) {
    if (!_segState.active || !_segState.dragging) return;
    var which = _segState.dragging;
    document.getElementById(which === 'start' ? 'segStartSlider' : 'segEndSlider').value = segSnapIdx(e.latlng, which);
    updateSegmentFromSliders(which);
  });

  document.addEventListener('mouseup', function() {
    if (!_segState.dragging) return;
    _segState.dragging = null;
    map.dragging.enable();
    if (_segState.active) {
      document.getElementById('segForm').style.display = 'block';
    }
  });
})();

// ── Charts and the map ───────────────────────────────────────────
// Hovering a chart puts a dot on the map where that point is, and the map's cursor on the track shows on every chart. A chart point's idx is
// its place in the streams, the same as the map's points when they're the latlng stream; on a track drawn from the summary polyline the
// spot is matched by how far along it is instead. A chart against minutes (the phone sensors: data.mins) is matched by the time at each point,
// and isn't linked when there are no times; a minute outside the chart, or the track, has no spot.
var _linkedCharts = [], _hoverDot = null, COORDS_FROM_STREAM = PAGE.coordsFromStream;

function chartToCoord(data, j) {
  var coords = window._rideCoords, dist = window._rideDist, time = window._rideTime;
  if (data.mins) {
    var s = data.mins[j] * 60, lo = 0, hi = time.length - 1;
    if (s < time[0] || s > time[hi]) return null;
    while (lo < hi) { var mid = (lo + hi) >> 1; if (time[mid] < s) lo = mid + 1; else hi = mid; }
    return lo;
  }
  if (COORDS_FROM_STREAM && data.idx) return Math.min(data.idx[j], coords.length - 1);
  var last = data.labels[data.labels.length - 1], m = last > 0 ? data.labels[j] / last * dist[dist.length - 1] : 0, lo = 0, hi = dist.length - 1;
  while (lo < hi) { var mid = (lo + hi) >> 1; if (dist[mid] < m) lo = mid + 1; else hi = mid; }
  return lo;
}

function coordToChart(data, ci) {
  if (data.mins) {
    var mins = data.mins, at = window._rideTime[ci] / 60, best = -1, gap = Infinity;
    if (at < mins[0] || at > mins[mins.length - 1]) return -1;
    for (var k = 0; k < mins.length; k++) if (Math.abs(mins[k] - at) < gap) { gap = Math.abs(mins[k] - at); best = k; }
    return best;
  }
  var dist = window._rideDist, last = data.labels[data.labels.length - 1], best = 0, gap = Infinity;
  var byIdx = COORDS_FROM_STREAM && data.idx, at = byIdx ? ci : dist[ci] / (dist[dist.length - 1] || 1) * last;
  for (var j = 0; j < data.labels.length; j++) {
    var g = Math.abs((byIdx ? data.idx[j] : data.labels[j]) - at);
    if (g < gap) { gap = g; best = j; }
  }
  return best;
}

function showOnMap(ci) {                  // a point of the track, or null to take the dot away
  var map = window._rideMap;
  if (!map) return;
  if (ci == null) { if (_hoverDot) { map.removeLayer(_hoverDot); _hoverDot = null; } return; }
  var c = window._rideCoords[ci];
  if (_hoverDot) _hoverDot.setLatLng(c);
  else _hoverDot = L.circleMarker(c, { radius: 7, weight: 2, color: cssVar('--card-bg'), fillColor: cssVar('--c-yellow'), fillOpacity: 1, interactive: false }).addTo(map);
}

function linkChart(chart, data) {
  if (!window._rideMap || !window._rideCoords || !window._rideCoords.length || (data.mins && !window._rideTime)) return;
  _linkedCharts.push({ chart: chart, data: data });
  chart.options.interaction = { mode: 'index', intersect: false };
  chart.options.onHover = function (e, active) { showOnMap(active.length ? chartToCoord(data, active[0].index) : null); };
  chart.update('none');
  chart.canvas.addEventListener('mouseleave', function () { showOnMap(null); });
}

(function () {
  var map = window._rideMap, shown = false, pending = null;
  if (!map) return;
  function clearCharts() {
    if (!shown) return;
    shown = false;
    showOnMap(null);
    _linkedCharts.forEach(function (l) { l.chart.setActiveElements([]); l.chart.tooltip.setActiveElements([], { x: 0, y: 0 }); l.chart.update('none'); });
  }
  // The point of the track under the cursor (within 15 px of the line), or -1. Not while a segment is being made: that has the map's cursor.
  function under(latlng) {
    var pr = window._rideProj(), p = pr.pts, m = map.project(latlng, pr.zoom), best = -1, gap = 15 * 15;
    if (p.length === 1) return m.distanceTo(p[0]) <= 15 ? 0 : -1;
    for (var i = 1; i < p.length; i++) {
      var ax = p[i - 1].x, ay = p[i - 1].y, dx = p[i].x - ax, dy = p[i].y - ay, l2 = dx * dx + dy * dy;
      var t = l2 ? Math.max(0, Math.min(1, ((m.x - ax) * dx + (m.y - ay) * dy) / l2)) : 0;
      var ex = ax + t * dx - m.x, ey = ay + t * dy - m.y, d = ex * ex + ey * ey;
      if (d < gap) { gap = d; best = t < 0.5 ? i - 1 : i; }
    }
    return best;
  }
  function at(latlng) {
    var ci = _segState.active || !_linkedCharts.length ? -1 : under(latlng);
    if (ci < 0) return clearCharts();
    shown = true;
    showOnMap(ci);
    _linkedCharts.forEach(function (l) {
      var j = coordToChart(l.data, ci), pt = l.chart.getDatasetMeta(0).data[j];
      if (j < 0) { l.chart.setActiveElements([]); l.chart.tooltip.setActiveElements([], { x: 0, y: 0 }); l.chart.update('none'); return; }
      var active = l.chart.data.datasets.map(function (d, k) { return { datasetIndex: k, index: j }; });
      l.chart.setActiveElements(active);
      l.chart.tooltip.setActiveElements(active, { x: pt ? pt.x : 0, y: pt && isFinite(pt.y) ? pt.y : l.chart.chartArea.top });
      l.chart.update('none');
    });
  }
  map.on('mousemove', function (e) {            // once a frame at most
    if (pending === null) requestAnimationFrame(function () { var ll = pending; pending = null; at(ll); });
    pending = e.latlng;
  });
  map.on('mouseout', clearCharts);
})();

function makeChart(id, data, colour) {     // colour: a variable from style.css, e.g. '--success'
  var color = cssVar(colour);
  linkChart(new Chart(document.getElementById(id), {
    type: 'line',
    data: {
      labels: data.labels,
      datasets: [{ data: data.values, borderColor: color, borderWidth: 1.5,
        pointRadius: 0, fill: true,
        backgroundColor: cssVar(colour, 0.08) }]
    },
    options: {
      animation: false,
      maintainAspectRatio: false,
      plugins: { legend: { display: false }, tooltip: {
        mode: 'index', intersect: false,
        callbacks: { title: ctx => ctx[0].label + ' ' + UNITS.dist }
      }},
      scales: {
        x: { ticks: { color: cssVar('--text-muted'), font: { size: 10 }, maxTicksLimit: 8 }, grid: { display: false } },
        y: { ticks: { color: cssVar('--text-muted'), font: { size: 10 } }, grid: { color: cssVar('--border') } }
      }
    }
  }), data);
}

// Pace in seconds per mile / km / 100 m: faster at the top, minutes and seconds on the axis. A gap is a stop.
function makePaceChart(id, data, colour) {
  var color = cssVar(colour);
  var mmss = function (v) { v = Math.round(v); return Math.floor(v / 60) + ':' + String(v % 60).padStart(2, '0'); };
  var vals = data.values.filter(function (v) { return v; }).sort(function (a, b) { return a - b; });
  var cap = vals.length ? vals[Math.floor(vals.length * 0.95)] * 1.15 : null;      // a slow shuffle at a junction shouldn't squash the rest
  linkChart(new Chart(document.getElementById(id), {
    type: 'line',
    data: { labels: data.labels, datasets: [{ data: data.values.map(function (v) { return v && cap && v > cap ? cap : v; }), borderColor: color,
            borderWidth: 1.5, pointRadius: 0, fill: false, spanGaps: false }] },
    options: {
      animation: false,
      maintainAspectRatio: false,
      plugins: { legend: { display: false }, tooltip: { mode: 'index', intersect: false,
        callbacks: { title: function (ctx) { return ctx[0].label + ' ' + UNITS.dist; }, label: function (ctx) { return mmss(ctx.parsed.y); } } } },
      scales: {
        x: { ticks: { color: cssVar('--text-muted'), font: { size: 10 }, maxTicksLimit: 8 }, grid: { display: false } },
        y: { reverse: true, ticks: { color: cssVar('--text-muted'), font: { size: 10 }, callback: mmss }, grid: { color: cssVar('--border') } }
      }
    }
  }), data);
}

function makeElevHrChart(id, elevData, hrData) {
  linkChart(new Chart(document.getElementById(id), {
    type: 'line',
    data: {
      labels: elevData.labels,
      datasets: [
        { label: 'Elev (' + UNITS.elev + ')', data: elevData.values, borderColor: cssVar('--success'), borderWidth: 1.5,
          pointRadius: 0, fill: true, backgroundColor: cssVar('--success', 0.08), yAxisID: 'yElev' },
        { label: 'HR (bpm)',  data: hrData.values,   borderColor: cssVar('--danger'),  borderWidth: 1.5,
          pointRadius: 0, fill: false, yAxisID: 'yHr' }
      ]
    },
    options: {
      animation: false,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: true, labels: { color: cssVar('--text-muted'), font: { size: 10 }, boxWidth: 10, padding: 12 } },
        tooltip: { mode: 'index', intersect: false,
          callbacks: { title: ctx => ctx[0].label + ' ' + UNITS.dist } }
      },
      scales: {
        x: { ticks: { color: cssVar('--text-muted'), font: { size: 10 }, maxTicksLimit: 8 }, grid: { display: false } },
        yElev: { position: 'left',  ticks: { color: cssVar('--success'), font: { size: 10 } }, grid: { color: cssVar('--border') } },
        yHr:   { position: 'right', ticks: { color: cssVar('--danger'),  font: { size: 10 } }, grid: { drawOnChartArea: false } }
      }
    }
  }), elevData);
}

(function () {
  var c = PAGE.charts;           // each a series or null (routes/rides.py)
  if (c.elevation && c.heartrate) makeElevHrChart('elevChart', c.elevation, c.heartrate);
  else if (c.elevation) makeChart('elevChart', c.elevation, '--success');
  if (c.speed) makeChart('speedChart', c.speed, '--c-sky');
  if (c.pace) makePaceChart('paceChart', c.pace, '--c-sky');
  if (c.heartrate && !c.elevation) makeChart('hrChart', c.heartrate, '--danger');
  if (c.power) makeChart('powerChart', c.power, '--accent');
  if (c.cadence) makeChart('cadenceChart', c.cadence, '--c-purple');
})();

(function() {
  if (!PAGE.sensors) return;
  var s = PAGE.sensors.series;
  function line(id, vals, color, label, unit) {
    var el = document.getElementById(id); if (!el) return;
    linkChart(new Chart(el, { type: 'line',
      data: { labels: s.min, datasets: [{ data: vals, borderColor: color, borderWidth: 1.3, pointRadius: 0, fill: false, tension: 0.25 }] },
      options: { animation: false, maintainAspectRatio: false, spanGaps: true,
        plugins: { legend: { display: false }, title: { display: true, text: label, color: cssVar('--text-soft'), font: { size: 11 } },
          tooltip: { mode: 'index', intersect: false, callbacks: { title: c => Math.round(c[0].label) + ' min', label: c => c.parsed.y + ' ' + unit } } },
        scales: { x: { ticks: { color: cssVar('--text-muted'), font: { size: 10 }, maxTicksLimit: 8, callback: function(v) { return Math.round(this.getLabelForValue(v)) + 'm'; } }, grid: { display: false } },
                  y: { ticks: { color: cssVar('--text-muted'), font: { size: 10 } }, grid: { color: cssVar('--border') } } } } }), { mins: s.min });
  }
  line('roughChart', s.rough, cssVar('--c-amber'), 'Roughness', 'm/s²');
  // the route itself, coloured by how rough it was (this ride's own smooth-to-rough scale)
  var tr = PAGE.sensors.track, m = window._rideMap;
  if (m && tr.length > 5 && !PAGE.sensors.pocket) {        // a pocket mostly measures the rider, so no road colouring
    var vals = tr.map(function(p) { return p[2]; }).sort(function(a, b) { return a - b; });
    var q = function(f) { return vals[Math.floor(f * (vals.length - 1))]; }, br = [q(0.25), q(0.5), q(0.8), q(0.95)];
    var cols = [cssVar('--c-green'), cssVar('--c-lime'), cssVar('--c-amber'), cssVar('--c-orange'), cssVar('--danger')];
    for (var i = 1; i < tr.length; i++) {
      var r = tr[i][2], c = cols[cols.length - 1];
      for (var k = 0; k < br.length; k++) { if (r < br[k]) { c = cols[k]; break; } }
      L.polyline([[tr[i - 1][0], tr[i - 1][1]], [tr[i][0], tr[i][1]]], { color: c, weight: 6, opacity: 0.9 }).addTo(m);
    }
  }
  if (document.getElementById('cadChart')) line('cadChart', s.cad, cssVar('--c-violet'), 'Cadence (estimated rpm)', 'rpm');
  line('baroChart', s.alt, cssVar('--c-sky'), 'Barometric altitude (m, relative)', 'm');
})();

(function() {
  var deg = PAGE.windDir;
  if (deg == null) return;
  var dirs = ['N','NE','E','SE','S','SW','W','NW'];
  var el = document.getElementById('wdCompass');
  if (el) el.textContent = dirs[Math.round(deg / 45) % 8];
})();

function scanSegments(rid) {
  var btn = document.getElementById('scanBtn');
  var res = document.getElementById('scanResult');
  btn.disabled = true;
  res.style.display = 'none';
  fetch('/rides/' + rid + '/scan', { method: 'POST' })
    .then(function(r) { return r.json(); })
    .then(function(d) {
      res.textContent = d.matched + ' effort' + (d.matched === 1 ? '' : 's') + ' found';
      res.style.display = 'inline';
      btn.disabled = false;
      if (d.matched > 0) setTimeout(function() { location.reload(); }, 800);
    });
}

function saveNotes(rid) {
  var text = document.getElementById('rideNotes').value;
  var saved = document.getElementById('notesSaved');
  fetch('/rides/' + rid + '/notes', {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: 'notes=' + encodeURIComponent(text)
  }).then(function(r) {
    if (r.status === 204) {
      saved.style.display = 'inline';
      setTimeout(function() { saved.style.display = 'none'; }, 2000);
    }
  });
}
