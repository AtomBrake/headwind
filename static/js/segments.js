function scanAll() {
  const btn = document.getElementById('scanBtn');
  const status = document.getElementById('scanStatus');
  const again = () => { btn.disabled = false; btn.textContent = 'Rescan all activities'; };
  btn.disabled = true;
  btn.textContent = 'Scanning…';
  status.style.display = 'block';
  status.textContent = 'Scanning every activity against the segments of its kind, in the background: you can leave this page, and Tasks shows how far it has got.';
  fetch('/segments/scan', { method: 'POST' })
    .then(r => r.json())
    .then(d => {
      if (!d.job) { status.textContent = '✓ Scanned — reload to see updated results'; again(); return; }
      followJob(d.job, () => {}, (state, error) => {
        status.textContent = state === 'done' ? '✓ Scanned every activity — reload to see updated results'
                           : state === 'lost' ? 'Lost touch with Headwind: the scan carries on, and Tasks shows how it went.'
                           : `Scan failed: ${error}`;
        again();
      });
    })
    .catch(() => { status.textContent = 'Scan failed'; again(); });
}
