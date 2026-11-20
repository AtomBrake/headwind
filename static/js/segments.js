function scanAll() {
  const btn = document.getElementById('scanBtn');
  const status = document.getElementById('scanStatus');
  btn.disabled = true;
  btn.textContent = 'Scanning…';
  status.style.display = 'block';
  status.textContent = 'Scanning every activity against the segments of its kind…';
  fetch('/segments/scan', { method: 'POST' })
    .then(r => r.json())
    .then(d => {
      status.textContent = `✓ Scanned ${d.scanned} activities — reload to see updated results`;
      btn.disabled = false;
      btn.textContent = 'Rescan all activities';
    })
    .catch(() => {
      status.textContent = 'Scan failed';
      btn.disabled = false;
      btn.textContent = 'Rescan all activities';
    });
}
