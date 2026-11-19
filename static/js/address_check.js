// The "Check" button beside the outside address (Settings and the setup wizard). It loads the address from this browser, because the server
// often can't reach its own public address (no hairpin NAT). The answer is opaque (no-cors), so this only says something answered there.
function checkAddress(inputId, outId) {
  var out = document.getElementById(outId);
  var url = (document.getElementById(inputId).value || '').trim().replace(/\/+$/, '');
  function say(kind, text) { out.style.color = kind === 'ok' ? 'var(--success)' : 'var(--danger)'; out.textContent = text; }
  if (!/^https?:\/\/[^\s\/?#]+/.test(url)) { say('bad', 'Type the whole address first, starting https://'); return; }
  if (location.protocol === 'https:' && url.indexOf('http:') === 0) {
    say('bad', "This page is on https, so the browser won't load a plain http address to check it."); return;
  }
  out.style.color = 'var(--text-muted)'; out.textContent = 'Checking…';
  var ctl = window.AbortController ? new AbortController() : null;
  var timer = setTimeout(function () { if (ctl) ctl.abort(); }, 8000);
  fetch(url + '/api/v1/ping', {mode: 'no-cors', cache: 'no-store', credentials: 'omit', signal: ctl ? ctl.signal : undefined})
    .then(function () { say('ok', 'It answered from this browser. Try it from your phone on mobile data too, to be sure it works from outside.'); })
    .catch(function () { say('bad', "Nothing answered there from this browser. Check the address, and that your tunnel or reverse proxy is running."); })
    .finally(function () { clearTimeout(timer); });
}
