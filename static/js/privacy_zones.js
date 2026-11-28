// Settings → Sharing → Privacy zones (services/privacy_zones.py): a map of the zones, each drawn as the circle that's hidden (moved off its
// point, and larger, at random), and the place for a new one, picked with a click, pasted as "lat, lng", or one of the start places offered.
(function () {
  var el = document.getElementById('privacyMap');
  if (!el) return;
  var DATA = JSON.parse(document.getElementById('privacyData').textContent);
  function cssVar(name) { return getComputedStyle(document.documentElement).getPropertyValue(name).trim(); }
  var map = L.map(el, { scrollWheelZoom: false });
  HWMap.attach(map, { page: 'settings', base: 'scheme' });

  var circles = {};
  var all = [];
  DATA.zones.forEach(function (z) {
    L.circle([z.hidden.lat, z.hidden.lng], { radius: z.hidden.radius, color: cssVar('--danger'), weight: 2,
                                                       fillOpacity: 0.2 }).addTo(map).bindTooltip(z.name);
    L.circleMarker([z.lat, z.lng], { radius: 4, color: cssVar('--danger'), weight: 2, fillOpacity: 1 }).addTo(map);
    circles[z.id] = L.latLng(z.hidden.lat, z.hidden.lng).toBounds(2 * z.hidden.radius);     // (a circle has no bounds before the map has a view)
    all.push(circles[z.id]);
  });
  DATA.suggest.forEach(function (p, i) {
    L.circleMarker([p.lat, p.lng], { radius: 5, color: cssVar('--accent'), weight: 2, fillOpacity: 0.6 })
      .addTo(map).bindTooltip('Start place ' + (i + 1) + ': ' + p.count.toLocaleString() + ' activities');
    all.push(L.latLngBounds([[p.lat, p.lng], [p.lat, p.lng]]));
  });
  if (all.length) {
    var b = L.latLngBounds(all[0].getSouthWest(), all[0].getNorthEast());
    all.forEach(function (x) { b.extend(x); });
    map.fitBounds(b.pad(0.3), { maxZoom: 15 });
  } else {
    map.setView([30, 0], 2);
  }

  var place = document.getElementById('zonePlace');
  var size = document.getElementById('zoneRadius');
  var picked = null;                 // the new zone's point and its radius (before the random move, which the server makes)

  function show(lat, lng, pan) {
    if (!size) return;
    var r = parseInt(size.value, 10);
    if (picked) { picked.setLatLng([lat, lng]); picked.setRadius(r); }
    else picked = L.circle([lat, lng], { radius: r, color: cssVar('--accent'), weight: 2, dashArray: '4 4', fillOpacity: 0.1 }).addTo(map);
    if (pan) map.fitBounds(L.latLng(lat, lng).toBounds(2 * r).pad(1.5), { maxZoom: 16 });
  }

  function parse(text) {
    var m = String(text || '').match(/^\s*(-?\d+(?:\.\d+)?)\s*[,; ]\s*(-?\d+(?:\.\d+)?)\s*$/);
    if (!m) return null;
    var lat = parseFloat(m[1]), lng = parseFloat(m[2]);
    return Math.abs(lat) <= 85 && Math.abs(lng) <= 180 ? [lat, lng] : null;
  }

  map.on('click', function (e) {
    if (!place) return;
    var lat = Math.round(e.latlng.lat * 1e5) / 1e5, lng = Math.round(L.Util.wrapNum(e.latlng.lng, [-180, 180], true) * 1e5) / 1e5;
    place.value = lat + ', ' + lng;
    show(lat, lng, false);
  });

  window.pickZonePlace = function (lat, lng) {
    if (!place) return;
    place.value = lat + ', ' + lng;
    show(lat, lng, true);
  };
  window.placeTyped = function (text) {
    var p = parse(text);
    if (p) show(p[0], p[1], true);
  };
  window.radiusChanged = function () {
    if (picked) show(picked.getLatLng().lat, picked.getLatLng().lng, false);
  };
  window.showZone = function (id) {
    if (circles[id]) map.fitBounds(circles[id].pad(0.5));
    el.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  };
})();
