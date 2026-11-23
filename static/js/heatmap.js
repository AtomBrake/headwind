var PAGE = JSON.parse(document.getElementById('heatmapData').textContent);
var map = L.map('heatMap', { zoomControl: true });

var layerGroup = L.layerGroup();
// Zwift worlds' maps sit above the base map and below the tracks
map.createPane('zwift').style.zIndex = 350;
var worldGroup = L.layerGroup().addTo(map);
var ZWIFT_WORLDS = PAGE.zwiftWorlds;
var ZWIFT_CREDIT = PAGE.zwiftCredit;
var shownWorlds = [];                  // the worlds drawn now, for the HD export
// Starts on the grey map that matches the page, and follows the page when it flips between light and dark (unless on another type)
var mapTypes = HWMap.attach(map, { page: 'heatmap', base: 'scheme', position: 'topleft' });
layerGroup.addTo(map);
var fitNext = true;                    // zoom to the tracks on the next load: the first, and after switching whose rides are shown
var currentFrom = '', currentTo = '';
var currentCount = 0;

// Each person keeps one colour in every view: the owner the accent, everyone else the next data colour along
var PEOPLE = PAGE.people;
var PERSON_COLOURS = ['--c-blue', '--c-green', '--c-pink', '--c-yellow', '--c-violet', '--c-teal', '--c-sky', '--c-lime', '--c-purple', '--c-red'];
var colourVar = {};
PEOPLE.filter(function (p) { return !p.isDefault; }).forEach(function (p, i) { colourVar[p.id] = PERSON_COLOURS[i % PERSON_COLOURS.length]; });
function personVar(id) { return colourVar[id] || '--accent'; }

function whoValue() { var w = document.getElementById('whoFilter'); return w ? w.value : ''; }

// The filters on the map now, as /heatmap/data's query string
function filterParams() {
  var params = new URLSearchParams();
  if (currentFrom) params.set('from', currentFrom);
  if (currentTo)   params.set('to', currentTo);
  var sport = document.getElementById('sportFilter').value;
  if (sport) params.set('sport', sport);
  if (whoValue()) params.set('who', whoValue());
  params.set('virtual', virtualValue());
  return params;
}

function virtualValue() { var v = document.getElementById('virtualFilter'); return v ? v.value : 'out'; }

// Draw each Zwift world that has a track, under the tracks. With real rides on the map too, only the made-up worlds: Zwift's London
// would cover the real London the other rides are on. Then a button per world (busiest first) to go to it.
function showWorlds(d) {
  worldGroup.clearLayers();
  var counts = {};
  (d.worlds || []).forEach(function (w) { if (w) counts[w] = (counts[w] || 0) + 1; });
  var slugs = Object.keys(counts).sort(function (a, b) { return counts[b] - counts[a]; });
  var realToo = virtualValue() !== 'only';
  shownWorlds = slugs.map(function (s) { return ZWIFT_WORLDS[s]; }).filter(function (w) { return w && (w.madeUp || !realToo); });
  shownWorlds.forEach(function (w) {
    L.imageOverlay(w.url, w.bounds, { pane: 'zwift', attribution: ZWIFT_CREDIT, interactive: false }).addTo(worldGroup);
  });
  var row = document.getElementById('zwiftWorlds');
  if (!row) return slugs;
  row.innerHTML = '';
  slugs.forEach(function (s) {
    var w = ZWIFT_WORLDS[s], b = document.createElement('button');
    b.className = 'preset-btn';
    b.textContent = w.name + ' ' + counts[s];
    b.onclick = function () { map.fitBounds(w.bounds, { padding: [20, 20] }); };
    row.appendChild(b);
  });
  row.style.display = slugs.length ? '' : 'none';
  return slugs;
}

// Everyone together: a key of who's who, with each person's count
function showKey(d) {
  var key = document.getElementById('whoKey');
  if (!key) return;
  var counts = {};
  d.riders.forEach(function (r) { counts[r] = (counts[r] || 0) + 1; });
  var shown = whoValue() === 'all' ? PEOPLE.filter(function (p) { return counts[p.id]; }) : [];
  key.innerHTML = '';
  shown.forEach(function (p) {
    var item = document.createElement('span'), dot = document.createElement('i');
    dot.style.background = 'var(' + personVar(p.id) + ')';
    item.append(dot, p.name + ' ' + counts[p.id]);
    key.appendChild(item);
  });
  key.style.display = shown.length > 1 ? '' : 'none';
}

function opacityFor(count) {
  if (count < 30)  return 0.55;
  if (count < 100) return 0.32;
  if (count < 300) return 0.20;
  if (count < 600) return 0.13;
  return 0.09;
}

function loadRange(from, to) {
  document.getElementById('loadingMsg').style.display = 'inline';
  document.getElementById('rideCount').textContent = '';
  document.getElementById('exportBtn').disabled = true;
  currentFrom = from; currentTo = to;

  fetch('/heatmap/data?' + filterParams().toString())
    .then(r => r.json())
    .then(function(d) {
      map.closePopup();
      layerGroup.clearLayers();
      loaded = d;
      d.boxes = d.tracks.map(boxOf);
      var opacity = opacityFor(d.count);
      var bounds  = [];                // where to zoom: the real rides, so Zwift's worlds don't pull the view out to sea

      d.tracks.forEach(function(pts, i) {
        if (!pts || pts.length < 2) return;
        L.polyline(pts, { color: cssVar(personVar(d.riders[i])), weight: 2, opacity: opacity, interactive: false })
         .addTo(layerGroup);
        if (!d.worlds[i]) pts.forEach(function(p) { bounds.push(p); });
      });
      var worlds = showWorlds(d);

      if (fitNext && (bounds.length || worlds.length)) {
        if (bounds.length) map.fitBounds(L.latLngBounds(bounds), { padding: [20, 20] });
        else map.fitBounds(ZWIFT_WORLDS[worlds[0]].bounds, { padding: [20, 20] });      // Zwift only: the busiest world
        fitNext = false;
      }
      showKey(d);

      currentCount = d.count;
      document.getElementById('loadingMsg').style.display = 'none';
      document.getElementById('rideCount').textContent =
        d.count + ' ride' + (d.count !== 1 ? 's' : '');
      document.getElementById('exportBtn').disabled = d.count === 0;
    })
    .catch(function() {
      document.getElementById('loadingMsg').style.display = 'none';
    });
}

// ── Picking a track ─────────────────────────────────────────────
// A click or tap lists the activities whose tracks pass within a few pixels of it, each linking to its page. The thousands of lines stay
// non-interactive (a clickable line, with a wider hit line for a finger, would double them): the click is checked against the lines
// already loaded, skipping each track whose bounding box is nowhere near.
var loaded = null;                     // the last /heatmap/data, with each track's box [minLat, maxLat, minLng, maxLng]
var pickGroup = L.layerGroup().addTo(map);      // the picked tracks, over the others while the popup is open
var picked = [];                       // [{i, halo, line}] for each of them

function boxOf(pts) {
  if (!pts || pts.length < 2) return null;
  var b = [pts[0][0], pts[0][0], pts[0][1], pts[0][1]];
  for (var j = 1; j < pts.length; j++) {
    var p = pts[j];
    if (p[0] < b[0]) b[0] = p[0]; else if (p[0] > b[1]) b[1] = p[0];
    if (p[1] < b[2]) b[2] = p[1]; else if (p[1] > b[3]) b[3] = p[1];
  }
  return b;
}

// The tracks within tol pixels of a point on the map (layer pixels), newest first
function tracksNear(c, tol) {
  var sw = map.layerPointToLatLng(L.point(c.x - tol, c.y + tol)), ne = map.layerPointToLatLng(L.point(c.x + tol, c.y - tol));
  var hits = [];
  loaded.tracks.forEach(function (pts, i) {
    var b = loaded.boxes[i];
    if (!b || b[0] > ne.lat || b[1] < sw.lat || b[2] > ne.lng || b[3] < sw.lng) return;
    var prev = map.latLngToLayerPoint(pts[0]);
    for (var j = 1; j < pts.length; j++) {
      var p = map.latLngToLayerPoint(pts[j]);
      if (L.LineUtil.pointToSegmentDistance(c, prev, p) <= tol) { hits.push(i); return; }
      prev = p;
    }
  });
  return hits.sort(function (a, b) { return (loaded.dates[b] || '').localeCompare(loaded.dates[a] || ''); });
}

function personName(id) {
  for (var k = 0; k < PEOPLE.length; k++) if (PEOPLE[k].id === id) return PEOPLE[k].name;
  return '';
}

function pickList(hits) {
  var box = document.createElement('div');
  box.className = 'pick-list';
  if (hits.length > 1) {
    var head = document.createElement('div');
    head.className = 'pick-head';
    head.textContent = hits.length + ' activities here';
    box.appendChild(head);
  }
  var everyone = whoValue() === 'all';
  hits.forEach(function (i) {
    var a = document.createElement('a'), name = document.createElement('span'), sub = document.createElement('span');
    a.className = 'pick-item';
    a.href = '/activities/' + encodeURIComponent(loaded.ids[i]);
    name.className = 'pick-name';
    if (everyone) {                    // whose it is, in their colour on the map
      var dot = document.createElement('i');
      dot.style.background = 'var(' + personVar(loaded.riders[i]) + ')';
      dot.title = personName(loaded.riders[i]);
      name.appendChild(dot);
    }
    name.appendChild(document.createTextNode(loaded.names[i]));
    var bits = [];
    if (everyone && personName(loaded.riders[i])) bits.push(personName(loaded.riders[i]));
    if (loaded.dates[i]) bits.push(fmtDate(loaded.dates[i].slice(0, 10)));
    bits.push(loaded.sports[i]);
    if (loaded.distances[i] != null) bits.push(UNITS.toDist(loaded.distances[i]).toFixed(1) + ' ' + UNITS.dist);
    sub.className = 'pick-sub';
    sub.textContent = bits.join(' · ');
    a.append(name, sub);
    a.addEventListener('mouseenter', function () { emphasise(i); });
    a.addEventListener('mouseleave', function () { emphasise(null); });
    box.appendChild(a);
  });
  return box;
}

// Draw the picked tracks again on top, solid and edged in the text colour (dark on a light page, light on a dark one), so they stand out
// from the others in the same colour on any map type
function highlight(hits) {
  pickGroup.clearLayers();
  picked = hits.slice().reverse().map(function (i) {      // the newest drawn last, on top
    var pts = loaded.tracks[i];
    return { i: i,
             halo: L.polyline(pts, { color: cssVar('--text'), weight: 6, opacity: 0.7, interactive: false }).addTo(pickGroup),
             line: L.polyline(pts, { color: cssVar(personVar(loaded.riders[i])), weight: 3, opacity: 1, interactive: false }).addTo(pickGroup) };
  });
}

// Hovering one in the list brings it forward and fades the rest; null puts them all back
function emphasise(i) {
  picked.forEach(function (p) {
    var on = i === null || p.i === i;
    p.halo.setStyle({ opacity: on ? 0.7 : 0 });
    p.line.setStyle({ opacity: on ? 1 : 0.3 });
    if (p.i === i) { p.halo.bringToFront(); p.line.bringToFront(); }
  });
}

// The filter panel floats over the map (above its popups): pan a popup clear of it, below it on a phone, where it spans the map, and
// to its left on a wider screen
function clearOfPanel() {
  var o = document.getElementById('mapOverlay').getBoundingClientRect(), m = map.getContainer().getBoundingClientRect();
  if (o.width > m.width / 2) return { autoPanPaddingTopLeft: [20, o.bottom - m.top + 10], autoPanPaddingBottomRight: [20, 20] };
  return { autoPanPaddingTopLeft: [20, 20], autoPanPaddingBottomRight: [m.right - o.left + 10, 20] };
}

map.on('click', function (e) {
  if (!loaded) return;
  var pointer = e.originalEvent && e.originalEvent.pointerType;
  var tol = (pointer ? pointer !== 'mouse' : matchMedia('(pointer: coarse)').matches) ? 14 : 6;     // a finger is less exact than a mouse
  var hits = tracksNear(e.layerPoint, tol);
  if (!hits.length) return;
  L.popup(L.extend({ className: 'heat-pick', maxWidth: 320, minWidth: 220, maxHeight: 300 }, clearOfPanel()))
   .setLatLng(e.latlng).setContent(pickList(hits)).openOn(map);
  highlight(hits);                     // after openOn, which closes the last popup and with it the last highlight
});
map.on('popupclose', function () { pickGroup.clearLayers(); picked = []; });

function reload() { loadRange(currentFrom, currentTo); }
function reloadAndFit() { fitNext = true; reload(); }

function setActive(btn) {
  document.querySelectorAll('#datePresets .preset-btn').forEach(b => b.classList.remove('active'));
  if (btn) btn.classList.add('active');
}

function localIso(d) { return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0'); }
function applyPreset(btn, preset) {
  var today = new Date();
  var from  = '', to = '';
  if (preset === 'year') {
    from = today.getFullYear() + '-01-01';
    to   = localIso(today);
  } else if (preset === 'lastyear') {
    var y = today.getFullYear() - 1;
    from = y + '-01-01'; to = y + '-12-31';
  } else if (preset === '6m') {
    var d = new Date(today); d.setMonth(d.getMonth() - 6);
    from = localIso(d);
    to   = localIso(today);
  } else if (preset === '30d') {
    var d = new Date(today); d.setDate(d.getDate() - 30);
    from = localIso(d);
    to   = localIso(today);
  }
  document.getElementById('fromDate').value = from;
  document.getElementById('toDate').value   = to;
  setActive(btn);
  loadRange(from, to);
}

function applyCustom() {
  var from = document.getElementById('fromDate').value;
  var to   = document.getElementById('toDate').value;
  setActive(null);
  loadRange(from, to);
}

// ── HD Canvas Export ─────────────────────────────────────────────
function exportHD() {
  var btn = document.getElementById('exportBtn');
  btn.disabled = true;
  btn.textContent = '⏳ Fetching tiles…';

  var W = 3440, H = 1440;
  var mapSize = map.getSize();
  var scaleX  = W / mapSize.x;
  var scaleY  = H / mapSize.y;
  var zoom    = Math.round(map.getZoom());
  var TILE    = 256;  // logical tile size (the tiles are 256px)
  var maxT    = Math.pow(2, zoom) - 1;

  // Work out which tiles cover the current viewport (+1 tile bleed each side)
  var bounds  = map.getBounds();
  var centerP = map.project(map.getCenter(), zoom);

  function latLngToTileXY(latlng) {
    var p = map.project(latlng, zoom);
    return { tx: Math.floor(p.x / TILE), ty: Math.floor(p.y / TILE) };
  }
  var nwT = latLngToTileXY(bounds.getNorthWest());
  var seT = latLngToTileXY(bounds.getSouthEast());

  var tileList = [];
  for (var ty = Math.max(0, nwT.ty - 1); ty <= Math.min(maxT, seT.ty + 1); ty++) {
    for (var tx = Math.max(0, nwT.tx - 1); tx <= Math.min(maxT, seT.tx + 1); tx++) {
      tileList.push({ tx: tx, ty: ty });
    }
  }

  // Tile images, one set per layer of the map type shown and any trail overlays on it: through the server (services/map_tiles.py) so the
  // canvas can be saved, or for Thunderforest, whose terms forbid that, from the provider with CORS
  var tileLayerPromises = mapTypes.exportTiles().map(function(tileUrl) {
    return Promise.all(tileList.map(function(t) {
      return new Promise(function(resolve) {
        var img = new Image();
        img.crossOrigin = 'anonymous';
        img.onload  = function() { resolve({ img: img, tx: t.tx, ty: t.ty }); };
        img.onerror = function() { resolve(null); };
        img.src = tileUrl(zoom, t.tx, t.ty);
      });
    }));
  });

  // Fetch HD track data, under the same filters as the map
  var params = filterParams();
  params.set('hd', '1');
  var trackPromise = fetch('/heatmap/data?' + params.toString()).then(r => r.json());

  // Zwift worlds' maps, through the server (Zwift's CDN sends no CORS headers, so the canvas couldn't be saved)
  var worldPromise = Promise.all(shownWorlds.map(function(w) {
    return new Promise(function(resolve) {
      var img = new Image();
      img.onload  = function() { resolve({ img: img, bounds: w.bounds }); };
      img.onerror = function() { resolve(null); };
      img.src = w.url;
    });
  }));

  Promise.all([trackPromise, Promise.all(tileLayerPromises), worldPromise])
    .then(function(results) {
      var trackData      = results[0];
      var tileLayerSets  = results[1];
      var worldImages    = results[2];

      btn.textContent = '⏳ Rendering…';
      setTimeout(function() {
        var canvas = document.createElement('canvas');
        canvas.width = W; canvas.height = H;
        var ctx = canvas.getContext('2d');

        // Dark background (shows behind any missing tiles)
        ctx.fillStyle = cssVar('--sidebar-bg');
        ctx.fillRect(0, 0, W, H);

        // Draw map tile layers in order (base first, then overlays)
        ctx.globalAlpha = 1;
        tileLayerSets.forEach(function(tileImages) {
          tileImages.forEach(function(t) {
            if (!t) return;
            var cx = (t.tx * TILE - centerP.x + mapSize.x / 2) * scaleX;
            var cy = (t.ty * TILE - centerP.y + mapSize.y / 2) * scaleY;
            ctx.drawImage(t.img, cx, cy, TILE * scaleX, TILE * scaleY);
          });
        });

        function project(lat, lng) {
          var pt = map.latLngToContainerPoint(L.latLng(lat, lng));
          return [pt.x * scaleX, pt.y * scaleY];
        }

        // Zwift worlds over the tiles: [[south, west], [north, east]] -> the north-west and south-east corners
        worldImages.forEach(function(w) {
          if (!w) return;
          var nw = project(w.bounds[1][0], w.bounds[0][1]), se = project(w.bounds[0][0], w.bounds[1][1]);
          ctx.drawImage(w.img, nw[0], nw[1], se[0] - nw[0], se[1] - nw[1]);
        });

        // Draw routes on top — alpha accumulates so busy segments glow
        if (trackData.tracks.length) {

          var alpha = Math.max(0.12, 4.0 / Math.max(trackData.tracks.length, 1));
          ctx.lineWidth   = 1.8;
          ctx.lineCap     = 'round';
          ctx.lineJoin    = 'round';
          ctx.globalAlpha = alpha;

          trackData.tracks.forEach(function(pts, i) {
            if (pts.length < 2) return;
            ctx.strokeStyle = cssVar(personVar(trackData.riders[i]));
            ctx.beginPath();
            var p0 = project(pts[0][0], pts[0][1]);
            ctx.moveTo(p0[0], p0[1]);
            for (var i = 1; i < pts.length; i++) {
              var p = project(pts[i][0], pts[i][1]);
              ctx.lineTo(p[0], p[1]);
            }
            ctx.stroke();
          });
        }

        canvas.toBlob(function(blob) {
          var url   = URL.createObjectURL(blob);
          var a     = document.createElement('a');
          var label = (currentFrom && currentTo)
            ? currentFrom + '_' + currentTo
            : (currentFrom || currentTo || 'all-time');
          var whoSel = document.getElementById('whoFilter');
          var whose  = whoSel && whoSel.value ? whoSel.options[whoSel.selectedIndex].text.replace(/[^\w-]+/g, '-').toLowerCase() + '_' : '';
          a.href     = url;
          a.download = 'heatmap_' + whose + label + '.png';
          a.click();
          setTimeout(function() { URL.revokeObjectURL(url); }, 2000);
          btn.disabled = false;
          btn.textContent = '⬇ Export 3440×1440';
        }, 'image/png');

      }, 30);
    })
    .catch(function(e) {
      console.error('Export failed:', e);
      btn.disabled = false;
      btn.textContent = '⬇ Export 3440×1440';
    });
}

// Default: this year
applyPreset(document.querySelector('#datePresets .preset-btn:nth-child(2)'), 'year');
