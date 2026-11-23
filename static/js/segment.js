const PAGE = JSON.parse(document.getElementById('segmentData').textContent);
// Being matched in the background (the notice routes/segments.detail shows while a job is): reload once it's done, to show the efforts
(function () {
  var note = document.getElementById('segmentMatching');
  if (note) followJob(note.dataset.job, function () {}, function (state) { if (state !== 'lost') location.reload(); });
})();

function rankLabel(n) { return ['🥇','🥈','🥉'][n-1] || String(n); }

function filterEfforts() {
  var yr     = document.getElementById('yearFilter').value;
  var riderEl = document.getElementById('riderFilter');
  var rider  = riderEl ? riderEl.value : 'all';
  var rows   = Array.from(document.querySelectorAll('tr[data-year]'))
    .sort(function(a, b) { return a.dataset.i - b.dataset.i; });   // ranked by time, whichever column the table is sorted on
  var rank   = 1;
  rows.forEach(function(row) {
    var yearOk  = yr === 'all' || row.dataset.year === yr;
    var riderOk = rider === 'all' || row.dataset.riderId === rider;
    var show    = yearOk && riderOk;
    row.style.display = show ? '' : 'none';
    if (show) {
      var cell = row.querySelector('.effort-rank');
      if (cell) cell.textContent = rankLabel(rank++);
    }
  });
}

// ── Mini map ─────────────────────────────────────────────────────
(function() {
  // Server-validated data (see routes/segments.py): numbers only, injected as JSON — never raw stored text.
  const mapData = PAGE.mapData;
  const note = document.getElementById('segMapNote');
  if (!mapData.start || !mapData.end) {
    document.getElementById('segMap').style.display = 'none';
    if (note) { note.textContent = 'Map unavailable — this segment has no valid start/finish position.'; note.style.display = 'block'; }
    return;
  }

  const map = L.map('segMap');
  HWMap.attach(map, { page: 'segment', base: 'satlabel' });

  L.circleMarker(mapData.start, { color:cssVar('--success'), fillColor:cssVar('--success'), fillOpacity:1, radius:7 })
   .addTo(map).bindPopup('Start');
  L.marker(mapData.end, {
    icon: L.divIcon({ html: '<div style="font-size:20px;line-height:1;">🏁</div>', className: '', iconAnchor: [10, 20] })
  }).addTo(map).bindPopup('Finish');

  let bounds;
  if (mapData.shape) {
    bounds = L.polyline(mapData.shape, { color: cssVar('--accent'), weight: 3 }).addTo(map).getBounds();
  } else {
    // No verified route shape: show just the two ends and say so, rather than a straight line that looks like the route.
    bounds = L.latLngBounds([mapData.start, mapData.end]);
    if (note) { note.textContent = 'Route shape unavailable — showing start and finish only.'; note.style.display = 'block'; }
  }
  map.fitBounds(bounds, { padding: [30, 30], maxZoom: 17 });
})();

// ── Trend chart ───────────────────────────────────────────────────
(function() {
  if (PAGE.trendDates.length < 2) return;
  const allDates = PAGE.trendDates;
  const allSecs  = PAGE.trendSecs;

  function rollingAvg(arr) {
    return arr.map((_, i) => {
      const w = arr.slice(Math.max(0, i - 2), i + 1);
      return Math.round(w.reduce((a, b) => a + b, 0) / w.length);
    });
  }

  const chartDatasets = [
    { borderColor:cssVar('--accent'), borderWidth:2, pointBackgroundColor:cssVar('--accent'), pointRadius:4, fill:false, tension:0.2, label:'Effort' },
    { borderColor:cssVar('--text-muted'), borderWidth:2, borderDash:[5,4], pointRadius:0, fill:false, tension:0.3, label:'3-effort avg' },
  ];

  const trendChart = new Chart(document.getElementById('trendChart'), {
    type: 'line',
    data: { labels: [], datasets: chartDatasets.map(d => ({...d, data:[]})) },
    options: {
      maintainAspectRatio: false,
      animation: false,
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            label: ctx => {
              const s = ctx.parsed.y;
              const h = Math.floor(s/3600), m = Math.floor((s%3600)/60), sec = s%60;
              return h ? `${h}:${String(m).padStart(2,'0')}:${String(sec).padStart(2,'0')}`
                       : `${m}:${String(sec).padStart(2,'0')}`;
            }
          }
        }
      },
      scales: {
        x: { ticks: { color:cssVar('--text-muted'), font:{size:10}, maxTicksLimit:10 }, grid:{color:cssVar('--border')} },
        y: {
          ticks: {
            color: cssVar('--text-muted'), font:{size:10},
            callback: v => { const m=Math.floor(v/60), s=v%60; return `${m}:${String(s).padStart(2,'0')}`; }
          },
          grid: { color:cssVar('--border') },
          reverse: false,
        }
      }
    }
  });

  window.filterTrend = function() {
    var yr = document.getElementById('trendYear').value;
    var filtered = allDates.map((d, i) => ({ d, s: allSecs[i] }))
                           .filter(r => yr === 'all' || r.d.startsWith(yr));
    var labels  = filtered.map(r => fmtDate(r.d));
    var secs    = filtered.map(r => r.s);
    var rolling = rollingAvg(secs);
    trendChart.data.labels        = labels;
    trendChart.data.datasets[0].data = secs;
    trendChart.data.datasets[1].data = rolling;
    trendChart.update();
  }

  filterTrend(); // initial render
})();
