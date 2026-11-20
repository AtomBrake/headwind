const STALE_DAYS = document.currentScript.dataset.staleDays;
document.getElementById('phGo').addEventListener('click', async () => {
  const r = await fetch('/phones/create', {method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({name: document.getElementById('phName').value})});
  const j = await r.json();
  if (!r.ok) { alert(j.error || 'Could not create token'); return; }
  document.getElementById('phQr').src = j.qr; document.getElementById('phLink').textContent = j.link;
  document.getElementById('phResult').style.display = 'block';
});
async function revoke(id) { if (!confirm('Revoke this phone? The app on it will stop working.')) return; await fetch('/phones/' + id + '/revoke', {method:'POST'}); location.reload(); }
async function revokeStale(n) {
  if (!confirm('Revoke ' + (n === 1 ? 'the token' : 'the ' + n + ' tokens') + ' not used for over ' + STALE_DAYS + ' days? The app on those phones, and their Apple Watches, will stop working until paired again.')) return;
  await fetch('/phones/revoke-stale', {method:'POST'}); location.reload();
}
