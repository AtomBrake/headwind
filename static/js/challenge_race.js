// A segment race's map (templates/challenge_race.html): each segment's line, numbered as on its board, with its start and finish
(function () {
  var segs = JSON.parse(document.getElementById('raceData').textContent);
  var el = document.getElementById('raceMap');
  if (!segs.length || !el) { if (el) el.style.display = 'none'; return; }
  var map = L.map('raceMap');
  HWMap.attach(map, { page: 'race', base: 'satlabel' });
  var bounds = L.latLngBounds([]);
  var straight = 0;
  segs.forEach(function (s) {
    var line = s.shape || [s.start, s.end];
    if (!s.shape) straight++;
    var opts = { color: cssVar('--accent'), weight: 4 };
    if (!s.shape) opts.dashArray = '6 6';                    // no shape known: the two ends, not a route
    L.polyline(line, opts).addTo(map).bindTooltip(s.n + '. ' + s.name);
    L.circleMarker(s.start, { color: cssVar('--success'), fillColor: cssVar('--success'), fillOpacity: 1, radius: 6 }).addTo(map);
    L.marker(s.start, { icon: L.divIcon({ html: '<span class="race-num">' + s.n + '</span>', className: '', iconAnchor: [-6, 22] }) }).addTo(map);
    L.marker(s.end, { icon: L.divIcon({ html: '<div style="font-size:18px;line-height:1;">🏁</div>', className: '', iconAnchor: [9, 18] }) }).addTo(map);
    line.forEach(function (p) { bounds.extend(p); });
  });
  map.fitBounds(bounds, { padding: [30, 30], maxZoom: 16 });
  if (straight) {
    var note = document.getElementById('raceMapNote');
    note.textContent = 'Dashed: a segment whose shape isn’t known here, shown from its start to its finish.';
    note.style.display = 'block';
  }
})();
