const fmt = n => (n == null ? '–' : Number(n).toLocaleString('en-GB'));
const $ = id => document.getElementById(id);
const SOURCES = [['manual','Manual'],['phone','Phone'],['watch','Watch'],['health','Apple Health'],['garmin','Garmin']];
const sourceParts = x => SOURCES.filter(([k]) => x[k] != null).map(([k, l]) => l + ' ' + fmt(x[k]));
function showSource(d) {
  document.querySelectorAll('#stSource .st-chip').forEach(x => x.classList.toggle('on', x.dataset.src === d.source));
  $('stSourceNote').textContent = d.source === 'auto'
    ? 'Garmin when it has given steps on 5 of the last 14 days, otherwise the phone (Apple Health, the Android app, or a watch through Home Assistant). Now counting ' + (d.effective === 'garmin' ? 'Garmin.' : 'the phone.')
    : '';
}
async function load() {
  const d = await (await fetch('/nutrition/api/steps')).json();
  showSource(d);
  $('stGoal').textContent = fmt(d.goal);
  if (!$('stDate').value) $('stDate').value = d.today;
  $('stDate').max = d.today;
  const t = d.days[0];
  $('stToday').textContent = fmt(t.best);
  $('stBar').style.width = Math.min(100, t.best / d.goal * 100) + '%';
  const srcs = sourceParts(t);
  $('stSrc').textContent = srcs.length ? (t.used ? 'Counting ' + (t.used === 'Manual' ? 'your entry' : t.used) + ' · ' : '') + srcs.join(' · ') : 'No steps logged today yet';
  $('stList').innerHTML = d.days.map(x => {
    const parts = sourceParts(x).join(' · ');
    const dt = new Date(x.date + 'T12:00:00').toLocaleDateString('en-GB', {weekday:'short', day:'numeric', month:'short'});
    return `<div class="st-row"><div>${dt}<small>${parts || 'nothing logged'}</small></div>
      <div style="display:flex;align-items:center;gap:0.4rem"><span class="st-num ${x.best >= d.goal ? 'st-hit' : ''}">${fmt(x.best || null)}${x.best >= d.goal ? ' ✓' : ''}</span>
      ${x.manual != null ? `<button class="st-del" title="Remove my manual entry" data-click="del('${x.date}')">&#x1F5D1;</button>` : ''}</div></div>`;
  }).join('');
}
async function save() {
  const steps = $('stSteps').value;
  if (steps === '') { $('stMsg').textContent = 'Enter a number of steps.'; return; }
  const r = await fetch('/nutrition/api/steps', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({date: $('stDate').value, steps})});
  const j = await r.json();
  $('stMsg').style.color = r.ok ? 'var(--success)' : 'var(--danger)';
  $('stMsg').textContent = r.ok ? 'Saved.' : (j.error || 'Could not save.');
  if (r.ok) { $('stSteps').value = ''; load(); }
}
async function del(day) { await fetch('/nutrition/api/steps/' + day, {method:'DELETE'}); load(); }
document.querySelectorAll('#stSource .st-chip').forEach(b => b.addEventListener('click', async () => {
  const r = await fetch('/nutrition/api/steps/source', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({source: b.dataset.src})});
  if (r.ok) load();
}));
document.querySelectorAll('.st-chip[data-off]').forEach(b => b.addEventListener('click', () => {
  const t = new Date($('stDate').max + 'T12:00:00'); t.setDate(t.getDate() - Number(b.dataset.off));
  $('stDate').value = t.getFullYear() + '-' + String(t.getMonth() + 1).padStart(2, '0') + '-' + String(t.getDate()).padStart(2, '0');
  document.querySelectorAll('.st-chip[data-off]').forEach(x => x.classList.toggle('on', x === b));
  $('stSteps').focus();
}));
$('stSave').addEventListener('click', save);
$('stSteps').addEventListener('keydown', e => { if (e.key === 'Enter') save(); });
load();
