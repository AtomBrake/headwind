// The dashboard's flagged activities: fix one from what was found, or say it's right.
function fixFlagged(id, fix) {
  fetch('/rides/' + id + '/' + fix, { method: 'POST' }).then(function(r) { return r.ok ? r.json() : null; }).then(function(d) {
    if (!d) return;
    if (!d.flagged) { var e = document.getElementById('flag_' + id); if (e) e.remove(); if (!document.querySelector('[id^=flag_]')) { var c = document.getElementById('flaggedCard'); if (c) c.remove(); } }
    else location.reload();
  });
}
function dismissFlagged(id) {
  fetch('/rides/' + id + '/flag/dismiss', { method: 'POST' }).then(function(r) {
    if (r.ok) { var e = document.getElementById('flag_' + id); if (e) e.remove(); if (!document.querySelector('[id^=flag_]')) { var c = document.getElementById('flaggedCard'); if (c) c.remove(); } }
  });
}
