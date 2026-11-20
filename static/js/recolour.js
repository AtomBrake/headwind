// Chart.js draws ticks, labels and grid lines in these unless a chart says otherwise
if (window.Chart) { Chart.defaults.color = cssVar('--text-muted'); Chart.defaults.borderColor = cssVar('--border'); }

// Recolouring on a scheme change. Charts and map lines hold the strings cssVar() returned, so they are swapped for the new
// scheme's: in what is already drawn, and in charts and lines a page makes later from colours it kept in a variable.
(function () {
  var stale = {}, maps = [];
  function plain(o) { var p = Object.getPrototypeOf(o); return p === Object.prototype || p === null; }     // Chart.js merges scales into null-prototype objects
  function swap(o, depth) {             // options and datasets, not the data points
    for (var k in o) {
      var x = o[k];
      if (typeof x === 'string') { if (stale.hasOwnProperty(x)) o[k] = stale[x]; }
      else if (x && typeof x === 'object' && k !== 'data' && depth < 8 && (Array.isArray(x) || plain(x))) swap(x, depth + 1);
    }
  }
  function swapChart(c) { swap(c.config.data, 0); swap(c.config.options, 0); }
  function pathStyle(o) {
    var s = {};
    ['color', 'fillColor'].forEach(function (k) { if (stale.hasOwnProperty(o[k])) s[k] = stale[o[k]]; });
    return s;
  }
  if (window.Chart) Chart.register({ id: 'scheme', beforeInit: swapChart });
  if (window.L) {
    L.Map.addInitHook(function () { maps.push(this); });
    L.Path.addInitHook(function () { L.Util.extend(this.options, pathStyle(this.options)); });
  }
  function themeColour() { document.querySelectorAll('meta[name="theme-color"]').forEach(function (m) { m.content = cssVar('--main-bg'); }); }
  addEventListener('DOMContentLoaded', themeColour);
  addEventListener('schemechange', function () {
    var now = cssVar.restale();
    if (!now) { location.reload(); return; }
    stale = now;
    themeColour();
    if (window.Chart) {
      ['color', 'borderColor', 'backgroundColor'].forEach(function (k) { if (stale.hasOwnProperty(Chart.defaults[k])) Chart.defaults[k] = stale[Chart.defaults[k]]; });
      Object.values(Chart.instances).forEach(function (c) { swapChart(c); c.update('none'); });
    }
    maps.forEach(function (m) {
      m.eachLayer(function (l) { if (l.setStyle && l.options) { var s = pathStyle(l.options); if (Object.keys(s).length) l.setStyle(s); } });
    });
  });
})();
