const dropZone  = document.getElementById('dropZone');
const fileInput = document.getElementById('fileInput');
const selectedFile = document.getElementById('selectedFile');
const uploadBtn = document.getElementById('uploadBtn');
let chosenFile = null;

dropZone.addEventListener('click', () => fileInput.click());
dropZone.addEventListener('dragover', e => { e.preventDefault(); dropZone.classList.add('drag-over'); });
dropZone.addEventListener('dragleave', () => dropZone.classList.remove('drag-over'));
dropZone.addEventListener('drop', e => {
  e.preventDefault();
  dropZone.classList.remove('drag-over');
  const f = e.dataTransfer.files[0];
  if (f) setFile(f);
});
fileInput.addEventListener('change', () => { if (fileInput.files[0]) setFile(fileInput.files[0]); });

function setFile(f) {
  chosenFile = f;
  const mb = (f.size / 1024 / 1024).toFixed(1);
  selectedFile.textContent = `${f.name}  (${mb} MB)`;
  selectedFile.style.display = 'block';
  uploadBtn.style.display = 'inline-flex';
}

async function startUpload() {
  if (!chosenFile) return;
  uploadBtn.disabled = true;
  uploadBtn.textContent = 'Uploading…';

  const fd = new FormData();
  fd.append('zipfile', chosenFile);
  const riderSel = document.getElementById('riderSelect');
  if (riderSel) fd.append('riderId', riderSel.value);
  fd.append('importPhotos', document.getElementById('optPhotos').checked ? '1' : '0');
  fd.append('importSegments', document.getElementById('optSegments').checked ? '1' : '0');
  fd.append('importRoutes', document.getElementById('optRoutes').checked ? '1' : '0');
  fd.append('keepExport', document.getElementById('optKeep').checked ? '1' : '0');

  document.getElementById('progressCard').style.display = 'block';
  document.getElementById('doneCard').style.display = 'none';

  await follow(await fetch('/import/upload', { method: 'POST', body: fd }));
}

// Import again: the export kept on the server, read with the options ticked above. Nothing to upload.
async function importAgain(riderId, btn) {
  btn.disabled = true;
  uploadBtn.disabled = true;
  const fd = new FormData();
  fd.append('importPhotos', document.getElementById('optPhotos').checked ? '1' : '0');
  fd.append('importSegments', document.getElementById('optSegments').checked ? '1' : '0');
  fd.append('importRoutes', document.getElementById('optRoutes').checked ? '1' : '0');
  document.getElementById('progressCard').style.display = 'block';
  document.getElementById('doneCard').style.display = 'none';
  document.getElementById('progressCard').scrollIntoView({ behavior: 'smooth' });
  await follow(await fetch(`/import/strava-export/${riderId}/again`, { method: 'POST', body: fd }));
}

// The import runs in the background worker, on the server, whether or not this page stays open; coming back re-attaches to it (or shows
// how one that finished meanwhile turned out, once).
(async () => {
  const d = await (await fetch('/import/status')).json();
  if (!d.job) return;
  uploadBtn.disabled = true;
  document.getElementById('progressCard').style.display = 'block';
  watch(d.job);
})();

// {job} from the server: follow it to the end. {error}: say so.
async function follow(resp) {
  let d;
  try { d = await resp.json(); } catch { d = { error: 'Could not start the import (' + resp.status + ')' }; }
  if (d.job) watch(d.job);
  else handleEvent(d);
}

function watch(id) {
  let said = false;
  followJob(id, d => { said = said || !!d.error; handleEvent(d); }, (state, error) => {
    if (state === 'lost') return handleEvent({ error: 'Lost touch with Headwind: the import goes on there. Reload to see how it\'s getting on.' });
    if (state === 'failed' && !said) handleEvent({ error: error || 'The import stopped' });
    fetch('/import/progress/dismiss', { method: 'POST' }).catch(() => {});      // seen here: not again, nor in the indicator
  });
}

function handleEvent(d) {
  if (d.error) {
    document.getElementById('progressLabel').textContent = 'Error: ' + d.error;
    document.getElementById('progressLabel').style.color = 'var(--danger)';
    return;
  }

  if (d.stage) {
    document.getElementById('progressLabel').textContent = d.stage;
    return;
  }

  if (d.total !== undefined && d.done === undefined) {
    const src = d.source === 'strava' ? 'Strava export' : 'GPS files';
    document.getElementById('progressLabel').textContent = `Detected ${src} — ${d.total} activities`;
    return;
  }

  if (d.done !== undefined) {
    const pct = d.total ? Math.round(d.done / d.total * 100) : 0;
    document.getElementById('progressFill').style.width = pct + '%';
    document.getElementById('progressLabel').textContent =
      `${d.done} / ${d.total}  (${pct}%)`;
    document.getElementById('progressStats').innerHTML =
      `<span style="color:var(--success)">✓ ${d.imported} imported</span>` +
      `<span style="color:var(--text-muted)">— ${d.skipped} skipped</span>` +
      (d.errors ? `<span style="color:var(--danger)">✗ ${d.errors} errors</span>` : '');
  }

  if (d.complete) {
    const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
    const an = w => (/^[aeiou]/i.test(w) ? 'an ' : 'a ') + w.toLowerCase();
    const noun = d.noun || 'activities';
    const parked = d.parked || [], unread = d.unread || [];
    document.getElementById('progressCard').querySelector('.card-title').textContent = 'Complete';
    document.getElementById('doneCard').style.display = 'block';
    document.getElementById('doneStats').innerHTML =
      `<strong style="color:var(--success)">${d.imported}</strong> ${d.imported === 1 ? noun.replace(/ies$/, 'y').replace(/s$/, '') : noun} imported<br>` +
      (parked.length ? `<span>${parked.length} set aside as a second recording of one already here:</span>` +
        `<ul style="margin:0 0 0.25rem 1.25rem;padding:0;line-height:1.6;">` +
        parked.map(p => `<li><a href="/activities/${encodeURIComponent(p.kept)}/duplicate/${encodeURIComponent(p.id)}" style="color:var(--accent)">${esc(p.name || p.id)}</a></li>`).join('') +
        `</ul>` : '') +
      `<span style="color:var(--text-muted)">${d.skipped} already existed / skipped</span>` +
      (d.unchanged ? `<br><span style="color:var(--text-muted)">${d.unchanged} unchanged since the last import, so not read again</span>` : '') +
      (unread.length ? `<br><span style="color:var(--danger)">${unread.length} file${unread.length === 1 ? '' : 's'} could not be read</span>` +
        (unread.some(u => u.id) ? `<span style="color:var(--text-muted)">: saved from activities.csv only, with no track</span>` : '') +
        `<ul style="margin:0 0 0.25rem 1.25rem;padding:0;line-height:1.6;">` +
        unread.map(u => u.id ? `<li><a href="/activities/${encodeURIComponent(u.id)}" style="color:var(--accent)">${esc(u.name)}</a> <span style="color:var(--text-muted)">${esc(u.file)}</span></li>`
                             : `<li style="color:var(--text-muted)">${esc(u.file)}</li>`).join('') +
        `</ul>` : '') +
      (d.errors ? `<br><span style="color:var(--danger)">${d.errors} could not be saved</span>` : '') +
      (d.kept ? `<br><span style="color:var(--text-muted)">The export is kept here: <a href="/import#kept" data-click="location.reload()" style="color:var(--accent)">import it again</a> any time without uploading it</span>` : '') +
      (d.changed ? `<br><a href="/import#changes" data-click="location.reload()" style="color:var(--accent)">${d.changed} differ from what's saved: review them</a>` : '') +
      (d.sport_guess ? `<br><a href="/activities/${encodeURIComponent(d.sport_guess.id)}" style="color:var(--accent)">Saved as ${esc(an(d.sport_guess.saved))} because the file ` +
        (d.sport_guess.file ? `says "${esc(d.sport_guess.file)}"` : `doesn't say`) + `, but it looks like ${esc(an(d.sport_guess.guess))}: check it</a>` : '') +
      (d.sport_guessed ? `<br><a href="/import#sport-guess" data-click="location.reload()" style="color:var(--accent)">${d.sport_guessed} saved as rides look like runs or walks: check them</a>` : '') +
      (d.bikes_filled ? `<br><span style="color:var(--text-muted)">${d.bikes_filled} rides put on their Strava bike</span>` : '') +
      (d.bikes_to_match ? `<br><a href="${d.bikes_url}" style="color:var(--accent)">${d.bikes_to_match} bike${d.bikes_to_match === 1 ? '' : 's'} from Strava to match to yours</a>` : '') +
      (d.photos ? `<br><span style="color:var(--text-muted)">${d.photos} photo${d.photos === 1 ? '' : 's'} added</span>` : '') +
      (d.photos_missing ? `<br><span style="color:var(--text-muted)">${d.photos_missing} photo${d.photos_missing === 1 ? '' : 's'} named in activities.csv ${d.photos_missing === 1 ? 'is' : 'are'} not in the zip (Strava leaves some out), so ${d.photos_missing === 1 ? 'it wasn\'t' : 'they weren\'t'} added</span>` : '') +
      (d.commutes ? `<br><span style="color:var(--text-muted)">${d.commutes} activit${d.commutes === 1 ? 'y' : 'ies'} ticked as a commute</span>` : '') +
      (d.segments_created !== undefined ? `<br><a href="/segments" style="color:var(--accent)">${d.segments_created} segment${d.segments_created === 1 ? '' : 's'} created</a>` +
        (d.segments_existing ? `<span style="color:var(--text-muted)">, ${d.segments_existing} already here</span>` : '') +
        (d.segments_unridden ? `<span style="color:var(--text-muted)">, ${d.segments_unridden} skipped (no ride here goes along them)</span>` : '') : '') +
      (d.routes_created !== undefined ? `<br><a href="/planner" style="color:var(--accent)">${d.routes_created} route${d.routes_created === 1 ? '' : 's'} added to the planner</a>` +
        (d.routes_existing ? `<span style="color:var(--text-muted)">, ${d.routes_existing} already there</span>` : '') +
        (d.routes_unread ? `<span style="color:var(--danger)">, ${d.routes_unread} could not be read</span>` : '') : '');
  }
}

// the last Garmin changes check, stored in UTC: shown in this browser's time, as on the Tasks page
document.querySelectorAll('#garmin-changes [data-when]').forEach(function (el) {
  var d = new Date(el.dataset.when);
  if (isNaN(d)) return;
  var t = d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  el.textContent = '(' + (d.toDateString() === new Date().toDateString() ? 'today ' : d.getDate() + ' ' + _MONTHS[d.getMonth()] + ' ') + t + ')';
});
