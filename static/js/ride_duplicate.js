const PAGE = JSON.parse(document.getElementById('duplicateData').textContent);
(function() {
  var recs = PAGE.labels.map(function(label, i) { return { label: label }; });
  var coords = PAGE.coords;
  var coordT = PAGE.coordT;
  var series = PAGE.series;
  var colours = PAGE.colours.map(function (c) { return cssVar(c); });
  var U = window.UNITS || {};
  var meta = PAGE.meta;
  var units = { velocity_smooth: U.speed, altitude: U.elev };

  var mapEl = document.getElementById('dupMap'), map = null;
  if (mapEl) {
    map = L.map(mapEl);
    var bounds = null;
    var zw = PAGE.zwiftWorld;
    if (zw) {
      // A virtual ride: drawn over its Zwift world's map alone, as the ride page does
      L.imageOverlay(zw.url, zw.bounds, { attribution: zw.credit, interactive: false }).addTo(map);
      map.setMaxBounds(zw.bounds);
      map.options.maxBoundsViscosity = 1;
      map.setMinZoom(map.getBoundsZoom(zw.bounds));
      map.setMaxZoom(18);
      mapEl.style.background = cssVar('--card-bg');
    } else {
      HWMap.attach(map, { page: 'duplicate', base: 'sat' });
    }
    coords.forEach(function(c, i) {
      if (!c.length) return;
      var line = L.polyline(c, { color: colours[i], weight: 3, opacity: 0.9 }).addTo(map).bindTooltip(recs[i].label);
      bounds = bounds ? bounds.extend(line.getBounds()) : line.getBounds();
    });
    if (bounds) map.fitBounds(bounds, { padding: [20, 20] });
  }

  // Hovering a chart puts a dot on the map where each recording was at that minute, and the cursor on a track shows that minute on every chart.
  var dots = [], charts = [];
  function nearest(n, at, t) {          // the index of 0..n-1 whose at(i) is closest to t; at() rises with i
    var lo = 0, hi = n - 1;
    while (lo < hi) { var mid = (lo + hi) >> 1; if (at(mid) < t) lo = mid + 1; else hi = mid; }
    return lo > 0 && t - at(lo - 1) < at(lo) - t ? lo - 1 : lo;
  }
  function showOnMap(t) {               // a minute, or null to take the dots away
    if (!map) return;
    coords.forEach(function (c, i) {
      var ts = coordT[i];
      if (t == null || !c.length || t < ts[0] || t > ts[ts.length - 1]) {
        if (dots[i]) { map.removeLayer(dots[i]); dots[i] = null; }
        return;
      }
      var ll = c[nearest(ts.length, function (j) { return ts[j]; }, t)];
      if (dots[i]) dots[i].setLatLng(ll);
      else dots[i] = L.circleMarker(ll, { radius: 7, weight: 2, color: cssVar('--card-bg'), fillColor: colours[i], fillOpacity: 1, interactive: false }).addTo(map);
    });
  }
  function linkChart(chart) {
    if (!map) return;
    charts.push(chart);
    chart.options.onHover = function (e) {
      var a = chart.chartArea;
      showOnMap(e.x >= a.left && e.x <= a.right ? chart.scales.x.getValueForPixel(e.x) : null);
    };
    chart.update('none');
    chart.canvas.addEventListener('mouseleave', function () { showOnMap(null); });
  }

  if (map) (function () {
    var shown = false, pending = null, proj = null;
    function clearCharts() {
      if (!shown) return;
      shown = false;
      showOnMap(null);
      charts.forEach(function (ch) { ch.setActiveElements([]); ch.tooltip.setActiveElements([], { x: 0, y: 0 }); ch.update('none'); });
    }
    // The minute of the track point under the cursor (within 15 px of either line), or null
    function under(latlng) {
      var z = map.getZoom();
      if (!proj || proj.zoom !== z) proj = { zoom: z, pts: coords.map(function (c) { return c.map(function (p) { return map.project(p, z); }); }) };
      var m = map.project(latlng, z), best = null, gap = 15 * 15;
      proj.pts.forEach(function (p, r) {
        for (var i = 0; i < p.length; i++) {
          var ax = p[i].x, ay = p[i].y, dx = i + 1 < p.length ? p[i + 1].x - ax : 0, dy = i + 1 < p.length ? p[i + 1].y - ay : 0, l2 = dx * dx + dy * dy;
          var f = l2 ? Math.max(0, Math.min(1, ((m.x - ax) * dx + (m.y - ay) * dy) / l2)) : 0;
          var ex = ax + f * dx - m.x, ey = ay + f * dy - m.y, d = ex * ex + ey * ey;
          if (d < gap) { gap = d; best = coordT[r][f < 0.5 ? i : i + 1]; }
        }
      });
      return best;
    }
    function at(latlng) {
      var t = charts.length ? under(latlng) : null;
      if (t == null) return clearCharts();
      shown = true;
      showOnMap(t);
      charts.forEach(function (ch) {
        var active = [];
        ch.data.datasets.forEach(function (d, k) {
          var pts = d.data;
          if (pts.length && t >= pts[0].x && t <= pts[pts.length - 1].x) active.push({ datasetIndex: k, index: nearest(pts.length, function (j) { return pts[j].x; }, t) });
        });
        var pt = active.length && ch.getDatasetMeta(active[0].datasetIndex).data[active[0].index];
        ch.setActiveElements(active);
        ch.tooltip.setActiveElements(active, { x: pt ? pt.x : 0, y: pt && isFinite(pt.y) ? pt.y : ch.chartArea.top });
        ch.update('none');
      });
    }
    map.on('mousemove', function (e) {            // once a frame at most
      if (pending === null) requestAnimationFrame(function () { var ll = pending; pending = null; at(ll); });
      pending = e.latlng;
    });
    map.on('mouseout', clearCharts);
  })();

  var wrap = document.getElementById('dupCharts'), any = false;
  meta.forEach(function(m) {
    var key = m[0], datasets = [];
    series.forEach(function(s, i) {
      if (s[key]) datasets.push({ label: recs[i].label, data: s[key], borderColor: colours[i], borderWidth: 1.4, pointRadius: 0, fill: false, tension: 0.2 });
    });
    if (!datasets.length) return;
    any = true;
    var box = document.createElement('div'); box.className = 'dup-chart';
    var canvas = document.createElement('canvas'); box.appendChild(canvas); wrap.appendChild(box);
    var unit = m[2] || units[key] || '';
    linkChart(new Chart(canvas, { type: 'line', data: { datasets: datasets },
      options: { animation: false, maintainAspectRatio: false, spanGaps: true, parsing: true,
        plugins: { legend: { display: datasets.length > 1, labels: { color: cssVar('--text-soft'), boxWidth: 10 } },
                   title: { display: true, text: m[1] + (unit ? ' (' + unit + ')' : ''), color: cssVar('--text-soft'), font: { size: 11 } },
                   tooltip: { mode: 'nearest', intersect: false, callbacks: { title: function(c) { return c[0].parsed.x.toFixed(1) + ' min'; } } } },
        scales: { x: { type: 'linear', ticks: { color: cssVar('--text-muted'), font: { size: 10 }, maxTicksLimit: 8, callback: function(v) { return Math.round(v) + 'm'; } }, grid: { display: false } },
                  y: { ticks: { color: cssVar('--text-muted'), font: { size: 10 } }, grid: { color: cssVar('--border') } } } } }));
  });
  if (!any) document.getElementById('dupNoCharts').style.display = '';
})();
