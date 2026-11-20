var map = L.map('roughMap', { zoomControl: true });
HWMap.attach(map, { page: 'roughness', base: 'satlabel' });
var layer = L.layerGroup().addTo(map), fitted = false, since = '';
var BANDS = ['--c-green', '--c-lime', '--c-amber', '--c-orange', '--danger'], COLOURS = BANDS.map(function(v) { return cssVar(v); }), NAMES = ['smooth', 'good', 'ok', 'rough', 'roughest'];

function setSince(btn) {
  document.querySelectorAll('.rg-chip').forEach(function(b) { b.classList.remove('active'); });
  btn.classList.add('active');
  var d = btn.getAttribute('data-since');
  since = d ? new Date(Date.now() - d * 864e5).toISOString().slice(0, 10) : '';
  load();
}

function zoomTo(lat, lng) { map.setView([lat, lng], 18); }
function dotRadius() { var z = map.getZoom(); return z >= 17 ? 12 : z >= 15 ? 7 : z >= 13 ? 4.5 : 3; }
map.on('zoomend', function() { layer.eachLayer(function(l) { l.setRadius(dotRadius()); }); });

function colour(r, b) { for (var i = 0; i < b.length; i++) { if (r < b[i]) return COLOURS[i]; } return COLOURS[COLOURS.length - 1]; }

function load() {
  var q = [];
  if (since) q.push('since=' + since);
  if (document.getElementById('pocket').checked) q.push('pocket=1');
  fetch('/roughness/data?' + q.join('&')).then(function(r) { return r.json(); }).then(function(d) {
    layer.clearLayers();
    var cells = d.cells || [], s = d.summary || {};
    document.getElementById('rgEmpty').style.display = cells.length ? 'none' : 'block';
    document.getElementById('rgMain').style.display = cells.length ? 'block' : 'none';
    if (cells.length) map.invalidateSize();           // the map was hidden (zero size) while there was nothing to show, so its tiles must be re-measured
    document.getElementById('rgCount').textContent = cells.length ? s.km + ' km of road · ' + cells.length + ' cells' : '';
    if (!cells.length) { fitted = false; return; }
    var b = s.breaks, bounds = [];
    cells.forEach(function(c) {
      var col = colour(c.r, b);
      L.circleMarker([c.lat, c.lng], { radius: dotRadius(), stroke: false, fillColor: col, fillOpacity: Math.min(0.9, 0.45 + c.n / 20) })
        .bindTooltip('Roughness ' + c.r + ' · ' + c.n + ' s over ' + c.rides + ' ride' + (c.rides === 1 ? '' : 's')).addTo(layer);
      bounds.push([c.lat, c.lng]);
    });
    if (!fitted) { map.fitBounds(bounds, { padding: [30, 30] }); fitted = true; }
    else map.invalidateSize();
    setTimeout(function() { map.invalidateSize(); }, 150);
    document.getElementById('rgLegend').innerHTML = COLOURS.map(function(c, i) {
      var lo = i === 0 ? 0 : b[i - 1], hi = i < b.length ? b[i] : s.max;
      return '<span><i style="background:var(' + BANDS[i] + ')"></i>' + NAMES[i] + ' ' + lo + '–' + hi + '</span>';
    }).join('');
    document.getElementById('rgWorst').innerHTML = (s.worst || []).map(function(c, i) {
      return '<div style="padding:0.3rem 0; border-top:1px solid var(--border);"><a href="#" data-click="zoomTo(' + c.lat + ', ' + c.lng + '); event.preventDefault()">' +
        (i + 1) + '. ' + c.lat.toFixed(5) + ', ' + c.lng.toFixed(5) + '</a> <span style="color:var(--text-muted);">· roughness ' + c.r + ' · ' + c.n + ' s · ' + c.rides + ' ride' + (c.rides === 1 ? '' : 's') + '</span></div>';
    }).join('');
  });
}
load();
