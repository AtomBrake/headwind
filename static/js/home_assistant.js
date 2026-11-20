const PAGE = JSON.parse(document.getElementById('haData').textContent);
const TARGETS = PAGE.targets;
let maps = PAGE.mappings;
let weatherEntity = PAGE.weatherEntity;
let entities = [];
const $ = id => document.getElementById(id);
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

function creds() {
  const fd = new FormData();
  fd.append('url', $('haUrl').value.trim());
  fd.append('token', $('haToken').value.trim());
  return fd;
}
function say(id, msg, ok) { const e = $(id); e.textContent = msg; e.style.color = ok === true ? 'var(--success)' : ok === false ? 'var(--danger)' : 'var(--text-muted)'; }

function openOverlay(id) { $(id).classList.add('open'); document.body.style.overflow = 'hidden'; }
function closeOverlay(id) { $(id).classList.remove('open'); document.body.style.overflow = ''; }
$('haPickerClose').onclick = () => closeOverlay('haPicker');
$('haWeatherPickerClose').onclick = () => closeOverlay('haWeatherPicker');

let saveTimer = null;
function autoSave() {           // any change to the entity list or interval is stored straight away
  clearTimeout(saveTimer);
  saveTimer = setTimeout(async () => {
    const {ok, d} = await save();
    say('haSyncStatus', ok ? '✓ Saved' : '✗ Could not save: ' + d.error, ok);
  }, 400);
}

function renderMaps() {
  $('haMaps').innerHTML = maps.map((m, i) => `
    <div class="ha-map">
      <div class="ha-map-name"><b>${esc(m.name || m.entity_id)}</b><small>${esc(m.entity_id)}</small></div>
      <select data-change="setMapTarget(${i}, this.value)">
        ${Object.entries(TARGETS).map(([k, v]) => `<option value="${k}" ${m.target === k ? 'selected' : ''}>${esc(v[0])}</option>`).join('')}
      </select>
      <button class="ha-x" data-click="removeMap(${i})" aria-label="Remove">&times;</button>
    </div>`).join('') || '<p class="ha-status">Nothing selected yet.</p>';
}
renderMaps();
function setMapTarget(i, target) { maps[i].target = target; autoSave(); }
function removeMap(i) { maps.splice(i, 1); renderMaps(); autoSave(); }

function renderWeatherChosen() {
  $('haWeatherChosen').innerHTML = weatherEntity
    ? `<div class="ha-map"><div class="ha-map-name"><b>${esc(weatherEntity)}</b></div><button class="ha-x" data-click="clearWeather()" aria-label="Remove">&times;</button></div>`
    : '';
  $('haWeatherPick').textContent = weatherEntity ? 'Change weather entity' : '+ Choose a weather entity';
}
renderWeatherChosen();
function clearWeather() { weatherEntity = ''; renderWeatherChosen(); autoSave(); }

async function post(path, body) {
  const r = await fetch('/settings/home-assistant' + path, {method:'POST', body});
  const d = await r.json().catch(() => ({error:'Bad response'}));
  return {ok: r.ok, d};
}

$('haTest').onclick = async () => {
  say('haConnStatus', 'Testing…');
  const {ok, d} = await post('/test', creds());
  if (!ok) { say('haConnStatus', '✗ ' + d.error, false); return; }
  const s = await save();   // a working connection is saved straight away
  say('haConnStatus', s.ok ? `✓ Connected to ${d.name || 'Home Assistant'} (version ${d.version}) and saved` : '✗ Connected, but saving failed: ' + s.d.error, s.ok);
};

async function save() {
  const r = await fetch('/settings/home-assistant/save', {method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({url:$('haUrl').value.trim(), token:$('haToken').value.trim(), minutes:$('haMinutes').value, mappings:maps, weather_entity:weatherEntity})});
  const d = await r.json();
  if (r.ok) $('haToken').value = '';
  return {ok: r.ok, d};
}
$('haSave').onclick = async () => {
  const {ok, d} = await save();
  say('haConnStatus', ok ? '✓ Saved' : '✗ ' + d.error, ok);
};

$('haLoad').onclick = async () => {
  openOverlay('haPicker');
  say('haPickStatus', 'Loading entities…');
  const {ok, d} = await post('/entities', creds());
  if (!ok) { say('haPickStatus', '✗ ' + d.error, false); return; }
  entities = d;
  say('haPickStatus', `${d.length} entities — likely health ones first`);
  renderEnts();
  $('haSearch').focus();
};
$('haSearch').oninput = renderEnts;

function renderEnts() {
  const q = $('haSearch').value.toLowerCase().trim();
  const taken = new Set(maps.map(m => m.entity_id));
  $('haEnts').innerHTML = entities.filter(e => !taken.has(e.entity_id) && (!q || (e.name + ' ' + e.entity_id).toLowerCase().includes(q)))
    .slice(0, 60).map(e => `
    <button class="ha-ent" data-id="${esc(e.entity_id)}">
      ${esc(e.name)} <b style="float:right">${esc(e.state)} ${esc(e.unit)}</b>
      <small>${esc(e.entity_id)}</small>
    </button>`).join('') || '<div class="ha-status">No matches.</div>';
}
$('haEnts').onclick = ev => {
  const b = ev.target.closest('.ha-ent'); if (!b) return;
  const e = entities.find(x => x.entity_id === b.dataset.id);
  const blob = (e.name + e.entity_id).toLowerCase();
  const guess = blob.includes('fat') ? 'body_fat' : blob.includes('muscle') ? 'muscle_mass' : blob.includes('water') ? 'body_water'
              : blob.includes('bmi') ? 'bmi' : blob.includes('bone') ? 'bone_mass' : blob.includes('visceral') ? 'visceral_fat'
              : blob.includes('heart') ? 'resting_hr' : blob.includes('step') ? (blob.includes('phone') ? 'steps_phone' : 'steps_watch') : 'weight';
  maps.push({entity_id: e.entity_id, name: e.name, target: guess});
  renderMaps(); renderEnts(); autoSave();
};

$('haWeatherPick').onclick = async () => {
  openOverlay('haWeatherPicker');
  say('haWeatherPickStatus', 'Loading entities…');
  if (!entities.length) {
    const {ok, d} = await post('/entities', creds());
    if (!ok) { say('haWeatherPickStatus', '✗ ' + d.error, false); return; }
    entities = d;
  }
  say('haWeatherPickStatus', `${entities.filter(e => e.domain === 'weather').length} weather entities`);
  renderWeatherEnts();
  $('haWeatherSearch').focus();
};
$('haWeatherSearch').oninput = renderWeatherEnts;

function renderWeatherEnts() {
  const q = $('haWeatherSearch').value.toLowerCase().trim();
  const list = entities.filter(e => e.domain === 'weather' && (!q || (e.name + ' ' + e.entity_id).toLowerCase().includes(q)));
  $('haWeatherEnts').innerHTML = list.map(e => `
    <button class="ha-ent" data-id="${esc(e.entity_id)}">
      ${esc(e.name)} <b style="float:right">${esc(e.state)}</b>
      <small>${esc(e.entity_id)}</small>
    </button>`).join('') || '<div class="ha-status">No weather entities found — add the Met Office, OpenWeatherMap or a similar integration in Home Assistant first.</div>';
}
$('haWeatherEnts').onclick = ev => {
  const b = ev.target.closest('.ha-ent'); if (!b) return;
  weatherEntity = b.dataset.id;
  closeOverlay('haWeatherPicker');
  renderWeatherChosen();
  autoSave();
};

async function runSync(days) {
  say('haSyncStatus', 'Saving and syncing…');
  const s = await save();
  if (!s.ok) { say('haSyncStatus', '✗ ' + s.d.error, false); return; }
  const fd = new FormData(); if (days) fd.append('days', days);
  const {ok, d} = await post('/sync', fd);
  say('haSyncStatus', ok ? `✓ ${d.weights} weigh-in(s), ${d.metrics} other reading(s)` + (d.replaced_manual ? `, ${d.replaced_manual} hand-typed weigh-in(s) replaced by the scale` : '') + (d.errors.length ? ' — ' + d.errors.join('; ') : '')
                         : '✗ ' + d.error, ok && !d.errors.length);
  if (ok) setTimeout(() => location.reload(), 1500);
}
$('haSync').onclick = () => runSync();
$('haSync10').onclick = () => runSync(10);
