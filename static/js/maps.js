// The map types every Leaflet map offers (activity, segment, roughness, heatmap, route builder, duplicate check) and the picker that
// switches them: one list, so a new type reaches every map. services/map_tiles.py is the server's half, for the heatmap's HD export, and
// has each provider's terms. Thunderforest and OS need a key from Settings → Maps (window.MAP_KEYS, templates/_maps.html); a type whose
// key isn't saved isn't offered. Each kind of page remembers its viewer's choice in localStorage.
var HWMap = (function () {
  var KEYS = window.MAP_KEYS || {};
  var OSM = '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors';
  var ESRI_IMAGERY = 'Tiles &copy; Esri &mdash; Source: Esri, Maxar, Earthstar Geographics';
  var ESRI_CANVAS = '&copy; Esri, HERE, Garmin, FAO, NOAA, USGS';
  var TF = 'Maps &copy; <a href="https://www.thunderforest.com">Thunderforest</a>, Data ' + OSM;
  var WMT = 'Routes &copy; <a href="https://waymarkedtrails.org">Waymarked Trails</a> (CC-BY-SA)';
  function esri(path) { return 'https://server.arcgisonline.com/ArcGIS/rest/services/' + path + '/MapServer/tile/{z}/{y}/{x}'; }
  function tf(style) { return 'https://tile.thunderforest.com/' + style + '/{z}/{x}/{y}.png?apikey=' + encodeURIComponent(KEYS.thunderforest || ''); }

  // key -> name, layers ([url, Leaflet options], bottom first), exp (what the HD export draws: a services/map_tiles.py layer name, or a
  // tile URL the browser loads itself), needs (the key it needs). maxNativeZoom: the provider's last zoom, enlarged beyond it.
  var TYPES = {
    satlabel:    { name: 'Satellite + labels', exp: ['satellite', 'labels'],
                   layers: [[esri('World_Imagery'), { attribution: ESRI_IMAGERY, maxZoom: 19 }],
                            [esri('Reference/World_Boundaries_and_Places'), { maxZoom: 19 }]] },
    sat:         { name: 'Satellite', exp: ['satellite'], layers: [[esri('World_Imagery'), { attribution: ESRI_IMAGERY, maxZoom: 19 }]] },
    // CARTO's free basemaps need an API key from 2026, so dark/light are Esri's keyless gray canvases (base + place-name overlay)
    dark:        { name: 'Dark', exp: ['dark', 'dark_ref'],
                   layers: [[esri('Canvas/World_Dark_Gray_Base'), { attribution: ESRI_CANVAS, maxNativeZoom: 16, maxZoom: 19 }],
                            [esri('Canvas/World_Dark_Gray_Reference'), { maxNativeZoom: 16, maxZoom: 19 }]] },
    light:       { name: 'Light', exp: ['light', 'light_ref'],
                   layers: [[esri('Canvas/World_Light_Gray_Base'), { attribution: ESRI_CANVAS, maxNativeZoom: 16, maxZoom: 19 }],
                            [esri('Canvas/World_Light_Gray_Reference'), { maxNativeZoom: 16, maxZoom: 19 }]] },
    topo:        { name: 'Esri Topo', exp: ['topo'],
                   layers: [[esri('World_Topo_Map'), { attribution: 'Tiles &copy; Esri &mdash; Esri, HERE, Garmin, FAO, NOAA, USGS, ' + OSM, maxZoom: 19 }]] },
    opentopo:    { name: 'OpenTopoMap', exp: ['opentopo'],
                   layers: [['https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png', { subdomains: 'abc', maxNativeZoom: 17, maxZoom: 19,
                     attribution: 'Map data: ' + OSM + ', SRTM &middot; Style: &copy; <a href="https://opentopomap.org">OpenTopoMap</a> (CC-BY-SA)' }]] },
    cyclosm:     { name: 'CyclOSM', exp: ['cyclosm'],
                   layers: [['https://{s}.tile-cyclosm.openstreetmap.fr/cyclosm/{z}/{x}/{y}.png', { subdomains: 'abc', maxNativeZoom: 20, maxZoom: 20,
                     attribution: '<a href="https://www.cyclosm.org">CyclOSM</a> &middot; Map data: ' + OSM }]] },
    // Thunderforest's terms forbid proxies: the export loads these straight from the browser too
    tf_cycle:    { name: 'OpenCycleMap', needs: 'thunderforest', exp: [tf('cycle')], layers: [[tf('cycle'), { attribution: TF, maxZoom: 19 }]] },
    tf_outdoors: { name: 'Thunderforest Outdoors', needs: 'thunderforest', exp: [tf('outdoors')], layers: [[tf('outdoors'), { attribution: TF, maxZoom: 19 }]] },
    // Zooms 7-16 only: free on the OpenData plan (17 and closer are Premium, charged past an allowance). Great Britain only.
    os:          { name: 'OS Outdoor (GB)', needs: 'os', exp: ['os'],
                   layers: [['https://api.os.uk/maps/raster/v1/zxy/Outdoor_3857/{z}/{x}/{y}.png?key=' + encodeURIComponent(KEYS.os || ''),
                             { minZoom: 7, maxNativeZoom: 16, maxZoom: 19,
                               attribution: 'Contains OS data &copy; Crown copyright and database rights ' + new Date().getFullYear() }]] },
  };
  // Overlays that sit on any type: transparent tiles, above the base map
  var TRAILS = {
    wmt_mtb:     { name: 'MTB routes', exp: ['wmt_mtb'],
                   layers: [['https://tile.waymarkedtrails.org/mtb/{z}/{x}/{y}.png', { maxNativeZoom: 18, maxZoom: 19, zIndex: 10, attribution: WMT }]] },
    wmt_cycling: { name: 'Cycle routes', exp: ['wmt_cycling'],
                   layers: [['https://tile.waymarkedtrails.org/cycling/{z}/{x}/{y}.png', { maxNativeZoom: 18, maxZoom: 19, zIndex: 10, attribution: WMT }]] },
  };

  function group(def) { return L.layerGroup(def.layers.map(function (l) { return L.tileLayer(l[0], l[1]); })); }
  function schemeKey() { return document.documentElement.dataset.scheme === 'light' ? 'light' : 'dark'; }
  // Storage can be missing or refuse (a private window, blocked site data): the map then just starts on its defaults
  function load(page) { try { return JSON.parse(localStorage.getItem('headwind.map.' + page)) || {}; } catch (e) { return {}; } }
  function save(page, st) { try { localStorage.setItem('headwind.map.' + page, JSON.stringify(st)); } catch (e) {} }

  // Put map types and overlays on `map`, with a layers control. opts:
  //   page      the name its viewer's choices are kept under ('activity', 'heatmap', ...)
  //   base      the type to start on: a TYPES key, or 'scheme' for the grey that matches the page (and follows it between light and dark)
  //   types     false for no map types or trail overlays (a Zwift ride: its world's map is all there is)
  //   extras    the page's own overlays, [{ id, name, layer, on }]: on is whether it shows before the viewer has chosen
  //   position  the control's corner (Leaflet's: 'topright' unless given)
  // Returns { type(): the type shown, exportTiles(): (z, x, y) -> tile URL for each layer the HD export draws, bottom first }.
  function attach(map, opts) {
    var page = opts.page, st = load(page), on = st.on || {};
    var keys = opts.types === false ? [] : Object.keys(TYPES).filter(function (k) { return !TYPES[k].needs || KEYS[TYPES[k].needs]; });
    var bases = {}, baseNames = {}, overlayNames = {}, trails = {};
    keys.forEach(function (k) { bases[k] = group(TYPES[k]); bases[k]._hwKey = k; baseNames[TYPES[k].name] = bases[k]; });
    if (opts.types !== false) {
      Object.keys(TRAILS).forEach(function (k) {
        trails[k] = group(TRAILS[k]); trails[k]._hwId = k; overlayNames[TRAILS[k].name] = trails[k];
        if (on[k]) trails[k].addTo(map);
      });
    }
    (opts.extras || []).forEach(function (x) {
      x.layer._hwId = x.id; overlayNames[x.name] = x.layer;
      if (x.id in on ? on[x.id] : x.on) x.layer.addTo(map);
    });
    var follow = opts.base === 'scheme', start = follow ? schemeKey() : opts.base;
    var current = bases[st.type] ? st.type : bases[start] ? start : keys[0];
    if (current) bases[current].addTo(map);

    function remember() { save(page, { type: current, on: on }); }
    function setType(k) {
      if (!bases[k] || k === current) return;
      map.removeLayer(bases[current]); bases[k].addTo(map); current = k;
    }
    if (keys.length > 1 || Object.keys(overlayNames).length) {
      L.control.layers(keys.length > 1 ? baseNames : {}, overlayNames, { position: opts.position || 'topright' }).addTo(map);
    }
    map.on('baselayerchange', function (e) { if (e.layer._hwKey) { current = e.layer._hwKey; remember(); } });
    map.on('overlayadd overlayremove', function (e) { if (e.layer._hwId) { on[e.layer._hwId] = e.type === 'overlayadd'; remember(); } });
    if (follow) addEventListener('schemechange', function () { if (current === 'dark' || current === 'light') setType(schemeKey()); });

    return {
      type: function () { return current; },
      exportTiles: function () {
        var defs = current ? [TYPES[current]] : [];
        Object.keys(trails).forEach(function (k) { if (map.hasLayer(trails[k])) defs.push(TRAILS[k]); });
        var out = [];
        defs.forEach(function (d) {
          d.exp.forEach(function (e) {
            out.push(e.indexOf('/') < 0 ? function (z, x, y) { return '/heatmap/tile/' + z + '/' + x + '/' + y + '?layer=' + e; }
                                        : function (z, x, y) { return L.Util.template(e, { z: z, x: x, y: y }); });
          });
        });
        return out;
      },
    };
  }

  return { attach: attach, TYPES: TYPES, TRAILS: TRAILS };
})();
