// Light or dark, before anything draws: sets <html data-scheme> from the Appearance setting (templates/_scheme.html says more).
(function () {
  var root = document.documentElement, device = matchMedia('(prefers-color-scheme: light)');
  window.applyScheme = function () {
    var t = root.dataset.theme, s = (t === 'light' || t === 'dark') ? t : (device.matches ? 'light' : 'dark');
    if (root.dataset.scheme === s) return;
    var was = root.dataset.scheme;
    root.dataset.scheme = s;
    if (was) dispatchEvent(new CustomEvent('schemechange', { detail: s }));
  };
  applyScheme();
  device.addEventListener('change', applyScheme);
})();
