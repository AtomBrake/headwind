// The live tracking link's page (templates/live.html, routes/live_share.py): draws the track so far and where the rider is, then asks
// /live/<token>/data every few seconds for what's new (the points after the last one it has) and the latest figures. The server sends the
// figures already in the rider's units. When the link ends (turned off or expired) the page says so.
(function () {
  var PAGE = JSON.parse(document.getElementById('liveData').textContent);
  var v = PAGE.view;
  var pollMs = (PAGE.pollS || 10) * 1000;
  var dataUrl = location.pathname.replace(/\/$/, '') + '/data';
  var since = v.last;
  var clockSkew = Date.now() / 1000 - v.now;      // the viewer's clock minus the server's, so "2 min ago" doesn't depend on either being right
  var followed = true;                             // the map keeps the rider in view until the viewer drags it
  var framed = false;                              // the map has been fitted to the track once

  function cssVar(name) { return getComputedStyle(document.documentElement).getPropertyValue(name).trim(); }
  function el(id) { return document.getElementById(id); }

  var map = L.map('liveMap', { zoomControl: true });
  L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Topo_Map/MapServer/tile/{z}/{y}/{x}', {
    maxZoom: 19,
    attribution: 'Tiles &copy; Esri &mdash; Esri, HERE, Garmin, FAO, NOAA, USGS, &copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
  }).addTo(map);
  var line = L.polyline(v.points || [], { color: cssVar('--accent'), weight: 4, opacity: 0.9 }).addTo(map);
  var marker = null;
  map.on('dragstart', function () { followed = false; });

  function place(pos) {
    if (!pos) {
      if (marker) { map.removeLayer(marker); marker = null; }
      return;
    }
    if (!marker) {
      marker = L.circleMarker(pos, { radius: 8, color: cssVar('--card-bg'), weight: 3, fillColor: cssVar('--accent'), fillOpacity: 1 }).addTo(map);
    } else {
      marker.setLatLng(pos);
    }
  }

  function clockTime(epoch) {
    return new Date(epoch * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  }

  function ago(epoch) {
    var s = Math.max(0, Math.round(Date.now() / 1000 - clockSkew - epoch));
    if (s < 45) return 'just now';
    if (s < 90) return '1 min ago';
    if (s < 3600) return Math.round(s / 60) + ' min ago';
    return 'at ' + clockTime(epoch);
  }

  function headline() {
    var what = (v.sport || 'activity').toLowerCase();
    return v.name ? v.name + "'s " + what : what.charAt(0).toUpperCase() + what.slice(1);
  }

  function statusText() {
    if (v.status === 'finished') return 'Finished at ' + clockTime(v.endedAt);
    if (v.status === 'waiting' || !v.updatedAt) return 'Waiting for the first position…';
    if (v.status === 'nosignal') return 'No signal since ' + clockTime(v.updatedAt);
    return 'Live · updated ' + ago(v.updatedAt);
  }

  function draw() {
    el('liveHeadline').textContent = headline();
    el('liveIcon').textContent = v.icon || '';
    var st = el('liveStatus');
    st.textContent = statusText();
    st.className = 'live-status ' + v.status;
    el('liveDistance').textContent = v.distance || '—';
    el('liveTime').textContent = v.time || '—';
    el('liveRateLabel').textContent = v.rateNow ? v.rateLabel + ' now' : 'Average ' + v.rateLabel.toLowerCase();
    el('liveRateNow').textContent = v.rateNow || v.rateAvg || '—';
    el('liveRateAvg').textContent = v.rateNow && v.rateAvg ? 'Average ' + v.rateAvg : '';
    el('liveBattery').textContent = v.battery != null ? Math.round(v.battery) + '%' : '—';
    el('liveHidden').hidden = !v.hidden;
    place(v.position);
    var pts = line.getLatLngs();
    if (!framed) {
      if (pts.length > 1) map.fitBounds(line.getBounds(), { padding: [30, 30], maxZoom: 16 });
      else if (v.position || pts.length) map.setView(v.position || pts[0], 15);
      else { map.setView([20, 0], 2); return; }       // nothing to show yet
      framed = true;
    } else if (followed && v.position && !map.getBounds().pad(-0.2).contains(v.position)) {
      map.panTo(v.position);
    }
  }

  function ended() {
    location.reload();          // the server's "This link has ended" page
  }

  var timer = null, busy = false;
  function poll() {
    if (busy) return;
    busy = true;
    clearTimeout(timer);
    fetch(dataUrl + (since != null ? '?since=' + encodeURIComponent(since) : ''), { cache: 'no-store', credentials: 'omit' })
      .then(function (r) {
        if (r.status === 404) { ended(); return null; }
        return r.ok ? r.json() : null;
      })
      .then(function (d) {
        if (!d) return;
        (d.points || []).forEach(function (p) { line.addLatLng(p); });
        since = d.last != null ? d.last : since;
        clockSkew = Date.now() / 1000 - d.now;
        v = d;
        draw();
      })
      .catch(function () { /* offline for a moment: the next poll tries again */ })
      .then(function () {
        busy = false;
        timer = setTimeout(poll, document.hidden ? pollMs * 3 : pollMs);
      });
  }

  draw();
  setInterval(function () { el('liveStatus').textContent = statusText(); }, 15000);    // "updated 2 min ago" moves on between polls
  document.addEventListener('visibilitychange', function () {
    if (!document.hidden) poll();
  });
  timer = setTimeout(poll, pollMs);
})();
