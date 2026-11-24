var SETTINGS = document.currentScript.dataset;     // garminHistoryRunning, serverZone

// Appearance: shown as soon as it's picked (static/js/scheme.js), before it's saved
function previewAppearance(theme) { document.documentElement.dataset.theme = theme; applyScheme(); }

function checkForUpdate() {
  var btn      = document.getElementById('update-btn');
  var badge    = document.getElementById('update-badge');
  btn.textContent = 'Checking…';
  btn.disabled = true;
  badge.style.display = 'none';

  fetch('/settings/version-check')
    .then(function(r) { return r.json(); })
    .then(function(data) {
      btn.textContent = 'Check for update';
      btn.disabled = false;
      if (!data.latest) {
        badge.textContent = data.error || 'Could not check';
        badge.style.background = 'var(--raised-bg)';
        badge.style.color = 'var(--text-muted)';
      } else if (data.newer) {
        badge.textContent = 'Update available: v' + data.latest;
        badge.style.background = 'var(--due-soft)';
        badge.style.color = 'var(--due)';
      } else {
        badge.textContent = 'Up to date';
        badge.style.background = 'var(--success-soft)';
        badge.style.color = 'var(--success-text)';
      }
      badge.style.display = 'inline-block';
    })
    .catch(function() {
      btn.textContent = 'Check for update';
      btn.disabled = false;
      badge.textContent = 'Check failed';
      badge.style.background = 'var(--raised-bg)';
      badge.style.color = 'var(--text-muted)';
      badge.style.display = 'inline-block';
    });
}

function updateProvider() {
  var p = document.getElementById('providerSelect').value;
  document.getElementById('openaiFields').style.display = p === 'openai' ? 'contents' : 'none';
  document.getElementById('claudeFields').style.display = p === 'claude' ? 'contents' : 'none';
  document.getElementById('ollamaFields').style.display = p === 'ollama' ? 'block' : 'none';
}
updateProvider();

// Tests whatever is typed in the form this button sits in — no need to save first
function mqttTlsPort(box) {     // the usual port for each, unless one of their own was typed
  var port = document.getElementById('mqttPort');
  if (port.value === (box.checked ? '1883' : '8883') || !port.value) port.value = box.checked ? '8883' : '1883';
}

function testSetting(kind, btn) {
  var status = document.getElementById(kind + (kind === 'ai' ? 'TestStatus' : 'Status'));
  btn.disabled = true;
  status.style.color = 'var(--text-muted)';
  status.textContent = 'Testing…';
  fetch('/settings/test-' + kind, { method: 'POST', body: new FormData(btn.closest('form')) })
    .then(r => r.json())
    .then(d => {
      if (d.error) {
        status.textContent = '✗ ' + d.error;
        status.style.color = 'var(--danger)';
      } else {
        status.textContent = kind === 'ai' ? '✓ ' + d.model + ' responded in ' + d.ms + ' ms — now press Save to keep it'
          : '✓ ' + (d.message || 'Connected to broker — press Save to keep it');
        status.style.color = 'var(--success)';
      }
    })
    .catch(() => { status.textContent = '✗ Request failed'; status.style.color = 'var(--danger)'; })
    .finally(() => { btn.disabled = false; });
}

function mqttPublish() {
  var btn = document.getElementById('mqttBtn');
  var status = document.getElementById('mqttStatus');
  btn.disabled = true;
  status.textContent = 'Publishing…';
  status.style.color = 'var(--text-muted)';
  fetch('/mqtt/publish', { method: 'POST' })
    .then(r => r.json())
    .then(d => {
      if (d.error) {
        status.textContent = 'Error: ' + d.error;
        status.style.color = 'var(--danger)';
      } else {
        status.textContent = '✓ ' + d.sensors + ' sensors published';
        status.style.color = 'var(--success)';
      }
      btn.disabled = false;
    })
    .catch(() => {
      status.textContent = 'Request failed';
      status.style.color = 'var(--danger)';
      btn.disabled = false;
    });
}

function calAdjSave(history) {
  var st = document.getElementById('calAdjStatus');
  var pct = document.getElementById('calAdjPct').value;
  st.style.color = 'var(--text-muted)';
  st.textContent = 'Saving…';
  fetch('/settings/calorie-adjust', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({pct: pct}) })
    .then(function(r) { return r.json().then(function(d) { return {ok: r.ok, d: d}; }); })
    .then(function(x) {
      if (!x.ok) { st.textContent = x.d.error || 'Could not save'; st.style.color = 'var(--danger)'; return; }
      if (!history) { st.textContent = '✓ Saved — ' + x.d.pct + '% off new data'; st.style.color = 'var(--success)'; return; }
      st.textContent = 'Applying to history…';
      return fetch('/settings/calorie-adjust/apply-history', { method: 'POST' }).then(function(r) { return r.json(); }).then(function(d) {
        var t = d.touched || {};
        st.textContent = '✓ Saved and applied — ' + (t.Activity || 0) + ' activities, ' + (t.GarminDaily || 0) + ' daily totals';
        st.style.color = 'var(--success)';
      });
    })
    .catch(function() { st.textContent = 'Could not reach the server'; st.style.color = 'var(--danger)'; });
}

function garminSync() {
  var btn = document.getElementById('garminBtn');
  var status = document.getElementById('garminStatus');
  btn.disabled = true;
  status.textContent = 'Syncing…';
  status.style.color = 'var(--text-muted)';
  fetch('/garmin/sync', { method: 'POST' })
    .then(r => r.json())
    .then(d => {
      if (d.error) {
        status.textContent = 'Error: ' + d.error;
        status.style.color = 'var(--danger)';
      } else {
        status.textContent = '✓ Synced ' + d.synced + ' days';
        status.style.color = 'var(--success)';
      }
      btn.disabled = false;
    })
    .catch(() => {
      status.textContent = 'Request failed';
      status.style.color = 'var(--danger)';
      btn.disabled = false;
    });
}

var garminMfaToken = null;

function garminConnectStatusEl() { return document.getElementById('garminConnectStatus'); }
function showGarminConnectStatus(kind, text) {
  var el = garminConnectStatusEl();
  var colors = {ok: 'var(--success)', error: 'var(--danger)', pending: 'var(--warning)'};
  var bg = {ok: 'var(--success-soft)', error: 'var(--danger-soft)', pending: 'var(--warning-soft)'};
  el.style.display = 'block';
  el.style.color = colors[kind];
  el.style.background = bg[kind];
  el.style.border = '1px solid ' + colors[kind];
  el.textContent = text;
}

function garminConnect() {
  var form = document.getElementById('garminConnectBtn').closest('form');
  var email = form.querySelector('input[name="garminEmail"]').value.trim();
  var password = form.querySelector('input[name="garminPassword"]').value;
  if (!email || !password) {
    showGarminConnectStatus('error', 'Enter your Garmin email and password first.');
    return;
  }
  var btn = document.getElementById('garminConnectBtn');
  btn.disabled = true;
  showGarminConnectStatus('pending', 'Connecting to Garmin…');
  fetch('/garmin/connect', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({email: email, password: password}),
  })
  .then(r => r.json())
  .then(data => {
    btn.disabled = false;
    if (data.error) {
      showGarminConnectStatus('error', data.error);
      return;
    }
    if (data.needs_mfa) {
      garminMfaToken = data.token;
      var box = document.getElementById('garminMfaBox');
      box.style.display = 'flex';
      box.style.alignItems = 'center';
      showGarminConnectStatus('pending', 'Garmin needs a verification code — check your phone or email.');
      document.getElementById('garminMfaCode').focus();
      return;
    }
    if (data.ok) {
      showGarminConnectStatus('ok', 'Garmin connected — reloading…');
      setTimeout(() => location.reload(), 800);
    }
  })
  .catch(() => {
    btn.disabled = false;
    showGarminConnectStatus('error', 'Could not reach the server — check your connection and try again.');
  });
}

function garminSave(form) {
  // Save keeps the sync settings only; a password typed here is for Connect / Sign in again, and /settings never stores it
  if (!form.querySelector('input[name="garminPassword"]').value) return true;
  showGarminConnectStatus('error', 'To sign in with that password, press ' + document.getElementById('garminConnectBtn').textContent.trim() + '. Save keeps the sync settings only.');
  return false;
}

function garminSignOut(btn) {
  btn.disabled = true;
  fetch('/garmin/disconnect', { method: 'POST' })
    .then(r => r.json())
    .then(() => location.reload())
    .catch(() => {
      btn.disabled = false;
      showGarminConnectStatus('error', 'Could not reach the server — check your connection and try again.');
    });
}

function garminVerifyMfa() {
  var code = document.getElementById('garminMfaCode').value.trim();
  if (!code || !garminMfaToken) return;
  showGarminConnectStatus('pending', 'Verifying…');
  fetch('/garmin/connect/mfa', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({token: garminMfaToken, code: code}),
  })
  .then(r => r.json())
  .then(data => {
    if (data.error) {
      showGarminConnectStatus('error', data.error + ' — check the code and try again.');
      return;
    }
    if (data.ok) {
      document.getElementById('garminMfaBox').style.display = 'none';
      showGarminConnectStatus('ok', 'Garmin connected — reloading…');
      setTimeout(() => location.reload(), 800);
    }
  })
  .catch(() => {
    showGarminConnectStatus('error', 'Could not reach the server — check your connection and try again.');
  });
}

function garminHistory() {
  var btn = document.getElementById('garminHistoryBtn');
  btn.disabled = true;
  fetch('/garmin/history', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({range: document.getElementById('garminHistoryRange').value}),
  })
  .then(r => r.json())
  .then(d => {
    btn.disabled = false;
    if (d.error) { showGarminConnectStatus('error', d.error); return; }
    document.getElementById('garminHistoryAsk').style.display = 'none';
    showGarminHistory(d);
    pollGarminHistory();
  })
  .catch(() => {
    btn.disabled = false;
    showGarminConnectStatus('error', 'Could not reach the server — check your connection and try again.');
  });
}

function showGarminHistory(d) {
  var el = document.getElementById('garminHistoryStatus');
  if (!el || !d.from) return;
  el.style.display = 'block';
  el.firstChild.textContent = (d.status || '') + ' ';
}

var garminHistoryTimer = null;
function pollGarminHistory() {
  clearTimeout(garminHistoryTimer);
  fetch('/garmin/history').then(r => r.json()).then(d => {
    showGarminHistory(d);
    if (d.from && !d.done) garminHistoryTimer = setTimeout(pollGarminHistory, 15000);
  }).catch(() => {});
}
if (SETTINGS.garminHistoryRunning) pollGarminHistory();

function updateGarminMode(mode) {
  var actBtn = document.getElementById('garminActivityBtn');
  if (actBtn) actBtn.style.display = mode === 'full' ? 'inline-flex' : 'none';
}


function garminActivitySync() {
  var btn    = document.getElementById('garminActivityBtn');
  var status = document.getElementById('garminActivityStatus');
  btn.disabled = true;
  status.style.display = 'block';
  status.style.color   = 'var(--text-muted)';
  status.textContent   = 'Connecting to Garmin…';

  function failed(msg) {
    status.textContent = 'Error: ' + msg;
    status.style.color = 'var(--danger)';
    btn.disabled = false;
  }
  // The sync runs in the background (services/jobs.py): leaving the page doesn't stop it, and the Tasks page shows how it went
  fetch('/garmin/sync-activities', { method: 'POST' }).then(function (r) { return r.json(); }).then(function (r) {
    if (!r.job) return failed(r.error || 'could not start the sync');
    var shown = false;
    followJob(r.job, function (d) {
      if (d.error) {
        shown = true;
        failed(d.error);
      } else if (d.done) {
        shown = true;
        status.textContent = '✓ Imported ' + d.imported + ' activit' + (d.imported === 1 ? 'y' : 'ies') + (d.skipped ? ', ' + d.skipped + ' skipped' : '');
        status.style.color = 'var(--success)';
        btn.disabled = false;
      } else if (d.msg) {
        status.textContent = d.msg;
      } else if (d.imported !== undefined) {
        status.textContent = 'Importing… ' + d.imported + ' done, ' + d.skipped + ' skipped';
      }
    }, function (state, error) {
      if (!shown) failed(error || 'the sync stopped');
    });
  }).catch(function () { failed('Connection lost'); });
}

// ── Profile & goals ──
var PF = { auto: 0, rides: null, rideGoal: null, ws: null };
var KG_PER_LB = 0.45359237;
function pfNum(id) { var v = parseFloat(document.getElementById(id).value); return isNaN(v) ? null : v; }
function pfShowUnit(unit) {
  var kg = unit === 'kg';
  ['pfWtStlb', 'pfGoalStlb'].forEach(function(i) { document.getElementById(i).style.display = kg ? 'none' : 'flex'; });
  ['pfKg', 'pfGKg'].forEach(function(i) { document.getElementById(i).style.display = kg ? '' : 'none'; });
}
function pfFill(id1, id2, idKg, kg) {
  if (!kg) { document.getElementById(id1).value = ''; document.getElementById(id2).value = ''; document.getElementById(idKg).value = ''; return; }
  var lbs = kg / KG_PER_LB;
  document.getElementById(id1).value = Math.floor(lbs / 14); document.getElementById(id2).value = Math.round((lbs % 14) * 10) / 10;
  document.getElementById(idKg).value = Math.round(kg * 10) / 10;
}
function pfKgFrom(unit, idSt, idLb, idKg) {
  if (unit === 'kg') return pfNum(idKg);
  var st = pfNum(idSt), lb = pfNum(idLb);
  if (st === null && lb === null) return null;
  return ((st || 0) * 14 + (lb || 0)) * KG_PER_LB;
}
async function pfLoad() {
  var d = await (await fetch('/nutrition/api/profile')).json();
  var p = d.profile || {};
  PF.auto = p.auto ? 1 : 0; PF.rides = p.ride_kcal_week; PF.ws = d.weight_settings;
  document.getElementById('pfSex').value = p.sex || '';
  document.getElementById('pfBorn').value = (!p.birth_date_guessed && p.birth_date) || '';
  document.getElementById('pfBornHint').textContent = p.birth_date_guessed ? 'Only the year (' + p.birth_date.slice(0, 4) + ') is known: enter the full date.' : (p.age ? 'Age ' + p.age : '');
  if (p.height_cm) { document.getElementById('pfCm').value = Math.round(p.height_cm); pfHeightFrom('cm'); }
  document.getElementById('pfUnit').value = d.weight_unit; pfShowUnit(d.weight_unit);
  pfFill('pfSt', 'pfLb', 'pfKg', d.weight_kg); pfFill('pfGSt', 'pfGLb', 'pfGKg', d.goal_weight_kg);
  pfLossShow(p.loss_lb_week, d.weight_unit); document.getElementById('pfSteps').value = p.step_goal;
  pfRender(d);
}
function pfHeightFrom(which) {                  // the cm field and the ft / in fields say the same height, whichever was typed in
  if (which === 'cm') {
    var cm = pfNum('pfCm'), inch = cm === null ? null : cm / 2.54;
    document.getElementById('pfFt').value = inch === null ? '' : Math.floor(inch / 12);
    document.getElementById('pfIn').value = inch === null ? '' : Math.round((inch % 12) * 2) / 2;
  } else {
    var ft = pfNum('pfFt'), i = pfNum('pfIn');
    document.getElementById('pfCm').value = ft === null && i === null ? '' : Math.round(((ft || 0) * 12 + (i || 0)) * 2.54);
  }
}
// The loss target is kept in lb a week; it's shown and typed in the unit weights are shown in (0.5-2.5 lb is about 0.25-1.1 kg)
function pfLossShow(lb, unit) {
  var kg = unit === 'kg', box = document.getElementById('pfLoss');
  document.getElementById('pfLossLabel').textContent = 'Loss target (' + (kg ? 'kg' : 'lb') + ' / week)';
  box.max = kg ? 1.1 : 2.5; box.step = kg ? 0.05 : 0.25; box.dataset.unit = kg ? 'kg' : 'lb';
  box.value = lb === null || lb === undefined || lb === '' ? '' : (kg ? Math.round(lb * KG_PER_LB * 20) / 20 : lb);
  box.dataset.lb = box.value === '' ? '' : lb; box.dataset.shown = box.value;      // the exact lb, while the figure shown is left alone
}
function pfLossLb() {
  var box = document.getElementById('pfLoss'), v = pfNum('pfLoss');
  if (box.value === box.dataset.shown && box.dataset.lb !== '') return parseFloat(box.dataset.lb);
  return v === null ? '' : (box.dataset.unit === 'kg' ? Math.round(v / KG_PER_LB * 1000) / 1000 : v);
}
function pfLossText(lb, unit) {
  return unit === 'kg' ? (Math.round(lb * KG_PER_LB * 20) / 20) + ' kg' : lb + ' lb';
}
function pfRender(d) {
  var st = document.getElementById('pfStatus'), box = document.getElementById('pfPlan'), apply = document.getElementById('pfApply');
  var miss = [];
  var p = d.profile || {};
  if (!p.sex) miss.push('sex'); if (!p.age) miss.push('date of birth'); if (!p.height_cm) miss.push('height'); if (!d.weight_kg) miss.push('your weight'); if (!d.goal_weight_kg) miss.push('a goal weight');
  st.innerHTML = miss.length ? '<span style="color:var(--warning-text);">Still to fill in: ' + miss.join(', ') + '.</span>' : '<span style="color:var(--success-text);">Profile complete.</span>';
  apply.disabled = !!d.plan_error;
  if (d.plan_error) { box.textContent = d.plan_error + ' — fill those in above and save.'; return; }
  var pl = d.plan, f = function(n) { return Number(n).toLocaleString('en-GB'); };
  box.innerHTML = '<b>' + f(pl.goal) + ' kcal</b> a day &nbsp;·&nbsp; protein ' + pl.protein + ' g · carbs ' + pl.carbs + ' g · fat ' + pl.fat + ' g<br><span style="color:var(--text-muted)">From a resting burn of ' + f(pl.bmr) + ' kcal, your step goal and a typical week's exercise, minus the deficit for losing ' + pfLossText(p.loss_lb_week, d.weight_unit) + ' a week.</span>';
}
async function pfSave() {
  var msg = document.getElementById('pfMsg'); msg.textContent = 'Saving…';
  var unit = document.getElementById('pfUnit').value;
  var height = pfNum('pfCm');                    // kept in step with ft / in as either is typed (pfHeightFrom)
  var post = function(url, body) { return fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }); };
  var r = await post('/nutrition/api/goal-profile', { sex: document.getElementById('pfSex').value, birth_date: document.getElementById('pfBorn').value, height_cm: height,
    loss_lb_week: pfLossLb(), step_goal: document.getElementById('pfSteps').value, ride_kcal_week: PF.rides, auto: !!PF.auto });
  if (!r.ok) { msg.textContent = (await r.json()).error || 'Could not save.'; return; }
  var kg = pfKgFrom(unit, 'pfSt', 'pfLb', 'pfKg');
  if (kg) {
    var today = new Date(); var iso = today.getFullYear() + '-' + String(today.getMonth() + 1).padStart(2, '0') + '-' + String(today.getDate()).padStart(2, '0');
    var w = await (await post('/nutrition/api/weight', { date: iso, unit: 'kg', kg: Math.round(kg * 100) / 100, force: true, source: 'settings' })).json();
    if (w.error) { msg.textContent = w.error; return; }
  }
  var gkg = pfKgFrom(unit, 'pfGSt', 'pfGLb', 'pfGKg'); var ws = PF.ws || {};
  var gr = await post('/nutrition/api/weight/settings', { unit: unit, emaAlpha: ws.emaAlpha || 0.1, dietStartDate: ws.dietStartDate || null, goalWeightKg: gkg ? Math.round(gkg * 10) / 10 : null });
  if (!gr.ok) { msg.textContent = (await gr.json()).error || 'Could not save the goal weight.'; return; }
  msg.textContent = 'Saved.'; pfLoad();
}
async function pfApply() {
  var r = await fetch('/nutrition/api/goal-plan/apply', { method: 'POST' });
  document.getElementById('pfMsg').textContent = r.ok ? 'Your calorie and macro goals are updated.' : ((await r.json()).error || 'Could not apply.');
}
if (document.getElementById('profileCard')) {     // with Nutrition off there's no profile card
  document.getElementById('pfUnit').addEventListener('change', function() { var lb = pfLossLb(); pfShowUnit(this.value); pfLossShow(lb, this.value); });
  pfLoad();
}

// ── Features ──
// An upper switch (Health, Gear) off: its parts are dimmed, but keep their ticks and are still sent, so they come back as they were
function featureGroup(box) {
  var parts = document.getElementById('featureParts-' + box.value);
  if (parts) parts.classList.toggle('is-dimmed', !box.checked);
}
(function () {
  try {
    var b = Intl.DateTimeFormat().resolvedOptions().timeZone, sel = document.getElementById('timeZone');
    var cur = sel.value || SETTINGS.serverZone;
    if (b && b !== cur && sel.querySelector('option[value="' + b + '"]'))
      document.getElementById('tzBrowser').textContent = ' This browser is in ' + b.replace(/_/g, ' ') + '.';
  } catch (e) {}
})();

// ── Backup ──
// A backup being made: the page reloads when it's ready
document.querySelectorAll('[data-poll]').forEach(function (el) {
  (function poll() {
    setTimeout(function () {
      fetch(el.dataset.poll).then(function (r) { return r.json(); })
        .then(function (s) {
          if (s.state !== 'running') { location.reload(); return; }
          if (s.progress) document.getElementById('backupProgress').textContent = s.progress;
          poll();
        })
        .catch(poll);
    }, 2000);
  })();
});

// stored in UTC: shown in this browser's time
document.querySelectorAll('[data-backup-when]').forEach(function (el) {
  var d = new Date(el.dataset.backupWhen);
  if (!isNaN(d)) el.textContent = 'on ' + d.getDate() + ' ' + _MONTHS[d.getMonth()] + ' at ' + d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
});
