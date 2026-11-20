// The parts form on a gear page (templates/_gear_parts.html): the catalogue fills in the intervals for the kind of part.
const CATALOG = JSON.parse(document.getElementById('partCatalog').textContent);
const UNITS_LABEL = UNITS.dist;
const kindSel = document.getElementById('partKind');
function fillFromKind() {
  const c = CATALOG.find(x => x.kind === kindSel.value); if (!c) return;
  document.getElementById('pReplace').value = c.replace; document.getElementById('pCheck').value = c.check;
  document.getElementById('pReplaceDays').value = c.replace_days || ''; document.getElementById('pCheckDays').value = c.check_days || '';
  document.getElementById('partNote').textContent = c.note || '';
  const nm = document.getElementById('partName'); if (kindSel.value !== 'custom') nm.placeholder = c.label + ' (name or model, optional)';
}
if (kindSel) { kindSel.onchange = fillFromKind; fillFromKind(); }
const act = document.getElementById('logAction');
function syncLog() { const show = act.value === 'replaced' && document.getElementById('logPart').value; const b = document.getElementById('replaceBox'); b.hidden = !show; b.style.display = show ? '' : 'none'; }
act.onchange = syncLog; document.getElementById('logPart').onchange = syncLog;
function fitNewChanged(box) { document.getElementById('fitNewVal').value = box.checked ? '1' : '0'; }
function logFor(id) { document.getElementById('logPart').value = id; document.getElementById('logForm').scrollIntoView({behavior: 'smooth'}); syncLog(); }
