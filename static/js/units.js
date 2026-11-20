// The rider's units (services/units.py): page scripts get stored metres / m/s through these, never their own 1609.344 or 2.23694.
window.UNITS = JSON.parse(document.getElementById('unitsData').textContent);
// Labels: UNITS.dist ('mi'|'km'), UNITS.elev ('ft'|'m'), UNITS.speed ('mph'|'km/h'), UNITS.pace ('/mi'|'/km'). Numbers from stored values:
UNITS.toDist  = function (m)   { return (m || 0) / UNITS.distM; };
UNITS.toElev  = function (m)   { return (m || 0) * UNITS.elevPerM; };
UNITS.toSpeed = function (mps) { return (mps || 0) * UNITS.speedPerMps; };
// Pace (services/sports.rate_style): seconds per mile / km for 'pace', per 100 m for 'swim'.
UNITS.toPace    = function (mps, style) { return mps > 0 ? (style === 'swim' ? 100 : UNITS.distM) / mps : null; };
UNITS.paceLabel = function (style) { return style === 'swim' ? '/100 m' : UNITS.pace; };
UNITS.fmtMinSec = function (s) { s = Math.round(s || 0); return Math.floor(s / 60) + ':' + String(s % 60).padStart(2, '0'); };
(function () {
  // A colour from the variables in style.css, for what can't read var(--x) itself: Chart.js, Leaflet, canvas. Markup and inline
  // styles (SVG included, through .style) use var(--x), which follows the scheme by itself.
  // cssVar('--danger') is '#ef4444'; cssVar('--danger', 0.15) is 'rgba(239,68,68,0.15)'.
  function colourOf(name, alpha) {
    var v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
    if (alpha === undefined) return v;
    var m = /^#([0-9a-f]{3}|[0-9a-f]{6})$/i.exec(v);
    if (m) {
      var h = m[1].length === 3 ? m[1].replace(/./g, '$&$&') : m[1], n = parseInt(h, 16);
      return 'rgba(' + (n >> 16) + ',' + ((n >> 8) & 255) + ',' + (n & 255) + ',' + alpha + ')';
    }
    m = /^rgba?\(([^,]+),([^,]+),([^,)]+)/.exec(v);
    return m ? 'rgba(' + m[1] + ',' + m[2] + ',' + m[3] + ',' + alpha + ')' : v;
  }
  var handedOut = {};                     // 'name alpha' -> [name, alpha, the colour cssVar() gave for it]
  window.cssVar = function (name, alpha) {
    var v = colourOf(name, alpha);
    handedOut[name + ' ' + alpha] = [name, alpha, v];
    return v;
  };
  // When the scheme flips with the page open, every colour cssVar() handed out maps to the same variable's new one. A colour
  // two variables shared that now differ can't be mapped: null, and the page reloads instead.
  var stale = {};                         // a colour from an earlier scheme -> the current one
  window.cssVar.restale = function () {
    var step = {};
    for (var k in handedOut) {
      var h = handedOut[k], now = colourOf(h[0], h[1]);
      if (h[2] in step && step[h[2]] !== now) return null;
      step[h[2]] = now; h[2] = now;
    }
    for (var old in stale) { if (stale[old] in step) stale[old] = step[stale[old]]; }
    for (var o in step) stale[o] = step[o];
    for (var x in stale) { if (stale[x] === x) delete stale[x]; }
    return stale;
  };
})();
