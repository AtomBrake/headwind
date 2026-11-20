var FRIENDS = document.currentScript.dataset;      // createUrl

function copyToken(text, btn) {
  if (navigator.clipboard) {
    navigator.clipboard.writeText(text).then(function() {
      btn.textContent = 'Copied!';
      setTimeout(function() { btn.textContent = 'Copy'; }, 1500);
    });
  } else {
    var ta = document.createElement('textarea');
    ta.value = text;
    ta.style.position = 'fixed';
    ta.style.opacity = '0';
    document.body.appendChild(ta);
    ta.select();
    document.execCommand('copy');
    document.body.removeChild(ta);
    btn.textContent = 'Copied!';
    setTimeout(function() { btn.textContent = 'Copy'; }, 1500);
  }
}

// Quick ranges, on the new-token form and each Edit form: fill "Activities from", leave "to" open so new activities keep flowing.
document.querySelectorAll('.fr-quick [data-range]').forEach(function(btn) {
  btn.addEventListener('click', function() {
    var form = btn.closest('form');
    var r = btn.dataset.range, d = new Date(), since = '';
    if (r !== 'all') {
      if (r !== 'today') d.setMonth(d.getMonth() - parseInt(r, 10));
      since = d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0');
    }
    form.sinceDate.value = since;
    form.untilDate.value = '';
    [form.sinceDate, form.untilDate].forEach(function(el) { el.dispatchEvent(new Event('input', { bubbles: true })); });
  });
});

function toggleEdit(btn, id) {
  var row = document.getElementById(id);
  row.hidden = !row.hidden;
  btn.setAttribute('aria-expanded', String(!row.hidden));
  btn.textContent = row.hidden ? 'Edit' : 'Close';
}

document.getElementById('token-form').addEventListener('submit', function(e) {
  e.preventDefault();
  var form = this;
  fetch(FRIENDS.createUrl, { method: 'POST', body: new FormData(form) })
    .then(function(r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
    .then(function(d) {
      document.getElementById('new-token-name').textContent = form.elements.name.value;
      document.getElementById('new-token-shares').textContent = sharesText(form);
      document.getElementById('new-token-qr').src = d.qr;
      document.getElementById('new-token-code').textContent = d.code;
      document.getElementById('new-token-url').textContent = d.url;
      document.getElementById('new-token-addr').textContent = d.url;
      document.getElementById('new-token-value').textContent = d.token;
      document.getElementById('new-token-warn').hidden = !homeOnly(d.url);
      document.getElementById('new-token').style.display = 'flex';
      form.reset();
    })
    .catch(function(err) { alert('Could not create the token: ' + err.message); });
});

// What a token form shares, in words: "Rob's activities, segments and foods", or "nothing"
function sharesText(form) {
  var parts = [], el = form.elements;
  if (el.shareActivities.checked) {
    var whose = Array.prototype.filter.call(form.querySelectorAll('input[name=rider]'), function(c) { return c.checked; })
      .map(function(c) { return c.parentNode.textContent.trim() + "'s"; });
    parts.push(whose.length ? whose.join(', ') + ' activities' : 'no one\'s activities');
  }
  if (el.shareSegments.checked) parts.push('segments');
  if (el.shareFoods.checked) parts.push('foods');
  return parts.length ? parts.slice(0, -1).join(', ') + (parts.length > 1 ? ' and ' : '') + parts[parts.length - 1] : 'nothing';
}

// An address a friend's instance can't reach from outside: plain http, or a local name or private IP.
function homeOnly(url) {
  var host;
  try { host = new URL(url).hostname; } catch (e) { return true; }
  return !url.startsWith('https://') || host === 'localhost' || host.endsWith('.local')
      || /^(127\.|10\.|192\.168\.|172\.(1[6-9]|2\d|3[01])\.)/.test(host);
}

function probeInstance(via) {
  var body  = via === 'code'
    ? {code: document.getElementById('probe-code').value.trim()}
    : {url: document.getElementById('probe-url').value.trim().replace(/\/+$/, ''), token: document.getElementById('probe-token').value.trim()};
  var btns  = document.querySelectorAll('.probe-btn');
  var btn   = btns[via === 'code' ? 0 : 1];
  var errEl = document.getElementById('probe-error');
  if (!(body.code || body.url)) {
    errEl.textContent = via === 'code' ? 'Paste their code first' : 'Enter a URL first';
    errEl.style.display = 'block';
    return;
  }

  btn.textContent = 'Connecting…';
  btns.forEach(function(b) { b.disabled = true; });
  errEl.style.display = 'none';
  document.getElementById('add-form').style.display = 'none';

  fetch('/friends/probe', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(body)
  })
  .then(r => r.json())
  .then(data => {
    btn.textContent = 'Connect';
    btns.forEach(function(b) { b.disabled = false; });
    if (data.error) {
      errEl.textContent = data.error;
      errEl.style.display = 'block';
      return;
    }
    var riders = data.riders || [];
    var sel = document.getElementById('rider-select');
    sel.innerHTML = '';
    riders.forEach(function(r) {
      var opt = document.createElement('option');
      opt.value = (r.name === 'Default rider') ? '' : r.name;
      opt.textContent = r.name + (r.isDefault ? ' (default)' : '');
      sel.appendChild(opt);
    });

    // Auto-fill display name from first rider
    var firstName = (riders[0] && riders[0].name !== 'Default rider') ? riders[0].name : '';
    document.getElementById('form-name').value = firstName;

    // Update display name when rider selection changes
    sel.onchange = function() {
      var picked = riders.find(function(r) { return (r.name === 'Default rider' ? '' : r.name) === sel.value; });
      if (picked && picked.name !== 'Default rider') {
        document.getElementById('form-name').value = picked.name;
      }
    };

    document.getElementById('form-url').value = data.url;
    document.getElementById('form-token').value = data.token;
    document.getElementById('add-form').style.display = 'block';
  })
  .catch(function(e) {
    btn.textContent = 'Connect';
    btns.forEach(function(b) { b.disabled = false; });
    errEl.textContent = 'Connection failed: ' + e.message;
    errEl.style.display = 'block';
  });
}

function syncFriend(fid, btn) {
  btn.textContent = 'Syncing…';
  btn.disabled = true;
  fetch('/friends/' + fid + '/sync', { method: 'POST' })
    .then(r => r.json())
    .then(d => d.running ? waitForSync(fid, btn) : syncDone(btn, d))
    .catch(e => { btn.textContent = 'Failed'; btn.disabled = false; });
}

// The sync runs in the background (a first one can take minutes): ask how it's going every 2 seconds
function waitForSync(fid, btn) {
  btn.textContent = 'Syncing…';
  btn.disabled = true;
  fetch('/friends/' + fid + '/sync/status')
    .then(r => r.json())
    .then(d => d.running ? setTimeout(() => waitForSync(fid, btn), 2000) : syncDone(btn, d))
    .catch(e => setTimeout(() => waitForSync(fid, btn), 5000));
}

function syncDone(btn, d) {
  btn.textContent = d.ok ? (d.synced ? '✓ ' + d.synced + ' new or changed' : '✓ Nothing new') : ('Error: ' + d.error);
  setTimeout(() => { btn.textContent = 'Sync'; btn.disabled = false; }, 3000);
  if (d.ok) setTimeout(() => location.reload(), 1200);
}

// A sync that was already running when the page loaded
document.querySelectorAll('button[data-syncing]').forEach(b => waitForSync(b.dataset.syncing, b));
function copyFrom(id, btn) { copyToken(document.getElementById(id).textContent, btn); }
// A friend's new feed token, asked for when the form is sent: it isn't sent without one
function askToken(form) {
  var t = prompt(form.dataset.prompt);
  if (!t) return false;
  form.token.value = t;
}
