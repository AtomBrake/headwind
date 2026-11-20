let wbUnit = 'stlb';
let wbParsedRows = [];
let wbOverwrite = false;

// the local calendar date — NOT toISOString(), which is UTC and flips the day for evening/after-midnight users
function localIso(d) { return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0'); }
function isoDate(d) { return localIso(d); }

function addRow(dateVal, stVal, lbVal, kgVal) {
  const wrap = document.getElementById('wbRowsWrap');
  const row = document.createElement('div');
  row.className = 'wb-row';
  const weightHtml = wbUnit === 'kg'
    ? `<input type="number" class="wb-kg" step="0.1" min="20" max="300" placeholder="kg" value="${kgVal||''}">`
    : `<input type="number" class="wb-st" step="1" min="0" max="60" placeholder="st" value="${stVal||''}">
       <input type="number" class="wb-lb" step="0.1" min="0" max="13.9" placeholder="lb" value="${lbVal||''}">`;
  row.innerHTML = `
    <input type="date" class="wb-date" value="${dateVal||''}">
    ${weightHtml}
    <button class="wb-row-del" type="button">&#x2715;</button>
  `;
  row.querySelector('.wb-row-del').addEventListener('click', () => row.remove());
  wrap.appendChild(row);
  return row;
}

document.getElementById('wbAddRow').addEventListener('click', () => {
  const rows = document.querySelectorAll('.wb-row');
  const last = rows[rows.length - 1];
  let dateVal = '', stVal = '', lbVal = '', kgVal = '';
  if (last) {
    const lastDate = last.querySelector('.wb-date').value;
    if (lastDate) {
      const d = new Date(lastDate + 'T12:00:00');
      d.setDate(d.getDate() - 1);
      dateVal = isoDate(d);
    }
    if (wbUnit === 'kg') kgVal = last.querySelector('.wb-kg').value;
    else { stVal = last.querySelector('.wb-st').value; lbVal = last.querySelector('.wb-lb').value; }
  }
  addRow(dateVal, stVal, lbVal, kgVal);
});

document.getElementById('wbAdvancedToggle').addEventListener('click', () => {
  document.getElementById('wbAdvanced').classList.toggle('open');
});

async function initBackfill() {
  const settings = await (await fetch('/nutrition/api/weight/settings')).json();
  wbUnit = settings.unit || 'stlb';
  const today = new Date();
  for (let i = 0; i < 3; i++) {
    const d = new Date(today);
    d.setDate(d.getDate() - (i + 1));
    addRow(isoDate(d));
  }
}

function rowLines() {
  const lines = [];
  document.querySelectorAll('.wb-row').forEach(row => {
    const dateVal = row.querySelector('.wb-date').value;
    if (!dateVal) return;
    if (wbUnit === 'kg') {
      const kg = row.querySelector('.wb-kg').value.trim();
      if (!kg) return;
      lines.push(`${dateVal}, ${kg}kg`);
    } else {
      const st = row.querySelector('.wb-st').value.trim();
      const lb = row.querySelector('.wb-lb').value.trim();
      if (!st && !lb) return;
      lines.push(`${dateVal}, ${st || 0}st ${lb || 0}lb`);
    }
  });
  return lines;
}

document.getElementById('wbOverwriteToggle').addEventListener('click', () => {
  wbOverwrite = !wbOverwrite;
  document.getElementById('wbOverwriteToggle').textContent =
    wbOverwrite ? 'Overwriting duplicates ✓' : 'Also overwrite duplicates';
});

document.getElementById('wbPreviewBtn').addEventListener('click', async () => {
  const fileInput = document.getElementById('wbFile');
  let resp;
  if (fileInput.files.length) {
    const fd = new FormData();
    fd.append('file', fileInput.files[0]);
    resp = await fetch('/nutrition/api/weight/backfill/preview', { method: 'POST', body: fd });
  } else {
    const lines  = rowLines();
    const pasted = document.getElementById('wbText').value.trim();
    const text   = lines.join('\n') + (pasted ? '\n' + pasted : '');
    if (!text.trim()) { alert('Add at least one date and weight first.'); return; }
    resp = await fetch('/nutrition/api/weight/backfill/preview', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text }),
    });
  }
  const data = await resp.json();
  wbParsedRows = data.rows || [];
  renderPreview();
});

function renderPreview() {
  const card = document.getElementById('wbResultsCard');
  card.style.display = '';
  const ok     = wbParsedRows.filter(r => !r.error);
  const errors = wbParsedRows.filter(r => r.error);
  const dupes  = ok.filter(r => r.duplicate);
  document.getElementById('wbSummary').textContent =
    `${wbParsedRows.length} row(s) — ${ok.length} valid, ${errors.length} error(s), ${dupes.length} already logged.`;

  document.getElementById('wbRows').innerHTML = wbParsedRows.map(r => {
    const cls = r.error ? 'wb-error' : (r.duplicate ? 'wb-duplicate' : '');
    const status = r.error ? r.error : (r.duplicate ? 'Already logged — will replace if overwrite is on' : 'OK');
    return `<tr class="${cls}">
      <td>${r.date || r.raw}</td>
      <td>${r.weightKg != null ? r.weightKg.toFixed(1) + ' kg' : '—'}</td>
      <td>${status}</td>
    </tr>`;
  }).join('');
  card.scrollIntoView({behavior:'smooth', block:'start'});
}

document.getElementById('wbConfirmBtn').addEventListener('click', async () => {
  const rows = wbParsedRows
    .filter(r => !r.error)
    .map(r => ({ date: r.date, weightKg: r.weightKg, overwrite: wbOverwrite && r.duplicate }));
  if (!rows.length) return;
  const resp = await fetch('/nutrition/api/weight/backfill/confirm', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ rows }),
  });
  const data = await resp.json();
  alert(`Imported ${data.imported} weigh-in(s)${data.skipped ? `, skipped ${data.skipped} already-logged date(s)` : ''}.`);
  window.location.href = '/nutrition/weight';
});

initBackfill();
