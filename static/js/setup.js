const PAGE = JSON.parse(document.getElementById('setupData').textContent);
var extraCount = 0;
function addRider() {
  extraCount++;
  var div = document.createElement('div');
  div.className = 'rider-row';
  div.id = 'extra-' + extraCount;
  div.innerHTML =
    '<input type="text" name="riders[]" placeholder="Rider name" autocomplete="off">' +
    '<button type="button" class="btn-remove" data-click="removeRider(' + extraCount + ')" title="Remove">×</button>';
  document.getElementById('extraRiders').appendChild(div);
  div.querySelector('input').focus();
}
function removeRider(id) {
  var el = document.getElementById('extra-' + id);
  if (el) el.remove();
}
function pickUnits(v) {
  // Only present on step 2 — this used to run unconditionally on every step and threw on
  // the others (null.classList), which silently killed the rest of this script block on
  // every step but 2 (nothing downstream happened to depend on that continuing, until the
  // Home Assistant step's JS wiring below did).
  var ci = document.getElementById('cardImperial'), cm = document.getElementById('cardMetric');
  if (ci) ci.classList.toggle('selected', v === 'imperial');
  if (cm) cm.classList.toggle('selected', v === 'metric');
}
pickUnits('imperial');

var garminMfaToken = null;

function garminStatusEl() { return document.getElementById('garminStatus'); }
function showGarminStatus(kind, text) {
  var el = garminStatusEl();
  el.className = 'garmin-status show ' + kind;
  el.textContent = text;
}

function garminConnect() {
  var email = document.getElementById('garminEmail').value.trim();
  var password = document.getElementById('garminPassword').value;
  if (!email || !password) {
    showGarminStatus('error', 'Enter your Garmin email and password first.');
    return;
  }
  var btn = document.getElementById('garminConnectBtn');
  btn.disabled = true;
  showGarminStatus('pending', 'Connecting to Garmin…');
  fetch('/garmin/connect', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({email: email, password: password}),
  })
  .then(function(r) { return r.json(); })
  .then(function(data) {
    btn.disabled = false;
    if (data.error) {
      showGarminStatus('error', data.error);
      return;
    }
    if (data.needs_mfa) {
      garminMfaToken = data.token;
      document.getElementById('mfaBox').classList.add('show');
      showGarminStatus('pending', 'Garmin needs a verification code — check your phone or email.');
      document.getElementById('garminMfaCode').focus();
      return;
    }
    if (data.ok) {
      document.getElementById('mfaBox').classList.remove('show');
      garminConnected();
    }
  })
  .catch(function() {
    btn.disabled = false;
    showGarminStatus('error', 'Could not reach the server — check your connection and try again.');
  });
}

// First run: once Garmin is connected, ask how much history to pull (default: all of it)
function garminConnected() {
  showGarminStatus('ok', 'Garmin connected.');
  document.getElementById('historyBox').classList.add('show');
  document.getElementById('garminSkip').style.display = 'none';
}

function garminHistory() {
  var btn = document.getElementById('garminHistoryBtn');
  btn.disabled = true;
  fetch('/garmin/history', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({range: document.getElementById('garminHistoryRange').value}),
  })
  .then(function(r) { return r.json(); })
  .then(function(data) {
    if (data.error) {
      btn.disabled = false;
      showGarminStatus('error', data.error);
      return;
    }
    window.location.href = '/setup?step=5';
  })
  .catch(function() {
    btn.disabled = false;
    showGarminStatus('error', 'Could not reach the server — check your connection and try again.');
  });
}

function garminVerify() {
  var code = document.getElementById('garminMfaCode').value.trim();
  if (!code || !garminMfaToken) return;
  var btn = document.getElementById('garminVerifyBtn');
  btn.disabled = true;
  showGarminStatus('pending', 'Verifying…');
  fetch('/garmin/connect/mfa', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({token: garminMfaToken, code: code}),
  })
  .then(function(r) { return r.json(); })
  .then(function(data) {
    btn.disabled = false;
    if (data.error) {
      showGarminStatus('error', data.error + ' — check the code and try again.');
      return;
    }
    if (data.ok) {
      document.getElementById('mfaBox').classList.remove('show');
      garminConnected();
    }
  })
  .catch(function() {
    btn.disabled = false;
    showGarminStatus('error', 'Could not reach the server — check your connection and try again.');
  });
}

// ── Step 4: Home Assistant (health entities + weather) ──────────────
// Mirrors templates/home_assistant.html's flow exactly, against the same endpoints, so whatever
// gets configured here shows up identically on the Settings page afterwards.
const HA_TARGETS = PAGE.haTargets;
let haMaps = PAGE.haMappings;
let haWeatherEntity = PAGE.haWeatherEntity;
let haEntities = [];
const haEsc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

function haOpenOverlay(id) {
  document.getElementById(id).classList.add('open');
  document.body.style.overflow = 'hidden';  // one scrollable surface at a time while the overlay's open
}
function haCloseOverlay(id) {
  document.getElementById(id).classList.remove('open');
  document.body.style.overflow = '';
}
function haSay(id, msg, ok) {
  const e = document.getElementById(id); if (!e) return;
  e.textContent = msg;
  e.style.color = ok === true ? 'var(--success)' : ok === false ? 'var(--danger)' : 'var(--text-muted)';
}
function haCreds() {
  const fd = new FormData();
  fd.append('url', document.getElementById('haUrl').value.trim());
  fd.append('token', document.getElementById('haToken').value.trim());
  return fd;
}
async function haPost(path, body) {
  const r = await fetch('/settings/home-assistant' + path, {method: 'POST', body});
  const d = await r.json().catch(() => ({error: 'Bad response'}));
  return {ok: r.ok, d};
}
let haSaveTimer = null;
function haAutoSave() {
  clearTimeout(haSaveTimer);
  haSaveTimer = setTimeout(haSave, 400);
}
async function haSave() {
  const r = await fetch('/settings/home-assistant/save', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({
      url: document.getElementById('haUrl').value.trim(),
      token: document.getElementById('haToken').value.trim(),
      minutes: 15, mappings: haMaps, weather_entity: haWeatherEntity,
    }),
  });
  const d = await r.json().catch(() => ({}));
  if (r.ok) document.getElementById('haToken').value = '';
  return {ok: r.ok, d};
}
function haRenderMaps() {
  const el = document.getElementById('haMaps'); if (!el) return;
  el.innerHTML = haMaps.map((m, i) => `
    <div class="ha-map">
      <div class="ha-map-name"><b>${haEsc(m.name || m.entity_id)}</b></div>
      <select data-change="haSetMapTarget(${i}, this.value)">
        ${Object.entries(HA_TARGETS).map(([k, v]) => `<option value="${k}" ${m.target === k ? 'selected' : ''}>${haEsc(v[0])}</option>`).join('')}
      </select>
      <button type="button" class="ha-x" data-click="haRemoveMap(${i})" aria-label="Remove">&times;</button>
    </div>`).join('');
}
function haSetMapTarget(i, target) { haMaps[i].target = target; haAutoSave(); }
function haRemoveMap(i) { haMaps.splice(i, 1); haRenderMaps(); haAutoSave(); }
function haClearWeather() { haWeatherEntity = ''; haRenderWeatherChosen(); haAutoSave(); }
function haRenderWeatherChosen() {
  const el = document.getElementById('haWeatherChosen'); if (!el) return;
  el.innerHTML = haWeatherEntity
    ? `<div class="ha-map"><div class="ha-map-name"><b>${haEsc(haWeatherEntity)}</b></div><button type="button" class="ha-x" data-click="haClearWeather()" aria-label="Remove">&times;</button></div>`
    : '';
  const btn = document.getElementById('haWeatherPickBtn');
  if (btn) btn.textContent = haWeatherEntity ? 'Change weather entity' : '+ Choose a weather entity';
}
function haRenderEnts() {
  const q = document.getElementById('haSearch').value.toLowerCase().trim();
  const taken = new Set(haMaps.map(m => m.entity_id));
  document.getElementById('haEnts').innerHTML = haEntities
    .filter(e => e.domain !== 'weather' && !taken.has(e.entity_id) && (!q || (e.name + ' ' + e.entity_id).toLowerCase().includes(q)))
    .slice(0, 60).map(e => `
    <button type="button" class="ha-ent" data-id="${haEsc(e.entity_id)}">
      ${haEsc(e.name)} <b style="float:right">${haEsc(e.state)} ${haEsc(e.unit)}</b>
      <small>${haEsc(e.entity_id)}</small>
    </button>`).join('') || '<div class="ha-status">No matches.</div>';
}
function haRenderWeatherEnts() {
  const q = document.getElementById('haWeatherSearch').value.toLowerCase().trim();
  const list = haEntities.filter(e => e.domain === 'weather' && (!q || (e.name + ' ' + e.entity_id).toLowerCase().includes(q)));
  document.getElementById('haWeatherEnts').innerHTML = list.map(e => `
    <button type="button" class="ha-ent" data-id="${haEsc(e.entity_id)}">
      ${haEsc(e.name)} <b style="float:right">${haEsc(e.state)}</b>
      <small>${haEsc(e.entity_id)}</small>
    </button>`).join('') || '<div class="ha-status">No weather entities found in Home Assistant.</div>';
}
document.addEventListener('click', function (ev) {
  const b = ev.target.closest('#haEnts .ha-ent');
  if (b) {
    const e = haEntities.find(x => x.entity_id === b.dataset.id);
    const blob = (e.name + e.entity_id).toLowerCase();
    const guess = blob.includes('fat') ? 'body_fat' : blob.includes('muscle') ? 'muscle_mass' : blob.includes('water') ? 'body_water'
                : blob.includes('bmi') ? 'bmi' : blob.includes('bone') ? 'bone_mass' : blob.includes('visceral') ? 'visceral_fat'
                : blob.includes('heart') ? 'resting_hr' : blob.includes('step') ? (blob.includes('phone') ? 'steps_phone' : 'steps_watch') : 'weight';
    haMaps.push({entity_id: e.entity_id, name: e.name, target: guess});
    haRenderMaps(); haRenderEnts(); haAutoSave();
    return;
  }
  const wb = ev.target.closest('#haWeatherEnts .ha-ent');
  if (wb) {
    haWeatherEntity = wb.dataset.id;
    haCloseOverlay('haWeatherPicker');
    haRenderWeatherChosen();
    haAutoSave();
  }
});

if (document.getElementById('haUrl')) {
  haRenderMaps();
  haRenderWeatherChosen();

  document.getElementById('haTestBtn').onclick = async function () {
    haSay('haConnStatus', 'Testing…');
    const {ok, d} = await haPost('/test', haCreds());
    if (!ok) { haSay('haConnStatus', '✗ ' + d.error, false); return; }
    const s = await haSave();
    haSay('haConnStatus', s.ok ? `✓ Connected to ${d.name || 'Home Assistant'} and saved` : '✗ Connected, but saving failed: ' + s.d.error, s.ok);
  };

  document.getElementById('haLoadBtn').onclick = async function () {
    haOpenOverlay('haPicker');
    haSay('haPickStatus', 'Loading entities…');
    const {ok, d} = await haPost('/entities', haCreds());
    if (!ok) { haSay('haPickStatus', '✗ ' + d.error, false); return; }
    haEntities = d;
    haSay('haPickStatus', `${d.filter(e => e.domain !== 'weather').length} entities — likely health ones first`);
    haRenderEnts();
    document.getElementById('haSearch').focus();
  };
  document.getElementById('haSearch').oninput = haRenderEnts;
  document.getElementById('haPickerClose').onclick = () => haCloseOverlay('haPicker');

  document.getElementById('haWeatherPickBtn').onclick = async function () {
    haOpenOverlay('haWeatherPicker');
    haSay('haWeatherPickStatus', 'Loading entities…');
    if (!haEntities.length) {
      const {ok, d} = await haPost('/entities', haCreds());
      if (!ok) { haSay('haWeatherPickStatus', '✗ ' + d.error, false); return; }
      haEntities = d;
    }
    haSay('haWeatherPickStatus', `${haEntities.filter(e => e.domain === 'weather').length} weather entities`);
    haRenderWeatherEnts();
    document.getElementById('haWeatherSearch').focus();
  };
  document.getElementById('haWeatherSearch').oninput = haRenderWeatherEnts;
  document.getElementById('haWeatherPickerClose').onclick = () => haCloseOverlay('haWeatherPicker');
}
