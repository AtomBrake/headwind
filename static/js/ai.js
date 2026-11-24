// ── Memory dot timeline ──────────────────────────────────────────
(function() {
  var svg = document.getElementById('memTimeline');
  if (!svg) return;
  var dots = JSON.parse(document.getElementById('aiDots').textContent);
  if (!dots.length) return;

  var W = svg.clientWidth || svg.parentElement.clientWidth || 600;
  var H = 90;
  var PAD = 12;
  var innerW = W - PAD * 2;

  // Tooltip
  var tip = document.createElement('div');
  tip.style.cssText = 'position:fixed;background:var(--inset-bg);border:1px solid var(--border-strong);border-radius:6px;padding:0.4rem 0.65rem;font-size:0.75rem;color:var(--text);pointer-events:none;display:none;z-index:999;max-width:200px;line-height:1.4;';
  document.body.appendChild(tip);


  // Baseline
  var base = H - 14;

  // Draw month tick lines (derived from dot positions at month boundaries)
  // Just draw subtle horizontal baseline
  var line = document.createElementNS('http://www.w3.org/2000/svg', 'line');
  line.setAttribute('x1', PAD); line.setAttribute('x2', W - PAD);
  line.setAttribute('y1', base); line.setAttribute('y2', base);
  line.style.stroke = 'var(--border-strong)'; line.setAttribute('stroke-width', '1');
  svg.appendChild(line);

  dots.forEach(function(d) {
    var cx = PAD + (d.x / 100) * innerW;
    // Jitter y slightly using hash of date string for visual texture
    var hash = d.date.split('').reduce(function(a,c){ return a + c.charCodeAt(0); }, 0);
    var jitter = ((hash % 13) - 6) * 1.5;
    var cy = base - d.size - 2 + jitter;
    cy = Math.max(d.size + 2, Math.min(base - d.size - 1, cy));

    var circle = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
    circle.setAttribute('cx', cx);
    circle.setAttribute('cy', cy);
    circle.setAttribute('r', d.size);
    circle.style.fill = 'var(' + d.color + ')';        // the sport's colour, as the sport filter's
    circle.setAttribute('opacity', '0.85');
    circle.style.cursor = 'pointer';

    circle.addEventListener('mouseenter', function(e) {
      const strong = document.createElement('strong');
      strong.textContent = d.name;
      tip.replaceChildren(strong, document.createElement('br'),
        document.createTextNode(d.sport + ' · ' + d.date), document.createElement('br'),
        document.createTextNode(d.figs));
      tip.style.display = 'block';
    });
    circle.addEventListener('mousemove', function(e) {
      tip.style.left = (e.clientX + 12) + 'px';
      tip.style.top  = (e.clientY - 8)  + 'px';
    });
    circle.addEventListener('mouseleave', function() { tip.style.display = 'none'; });
    svg.appendChild(circle);
  });

  // Date labels at start and end
  function addLabel(text, x, anchor) {
    var t = document.createElementNS('http://www.w3.org/2000/svg', 'text');
    t.setAttribute('x', x); t.setAttribute('y', H - 2);
    t.setAttribute('text-anchor', anchor);
    t.setAttribute('font-size', '9'); t.style.fill = 'var(--text-muted)';
    t.textContent = text;
    svg.appendChild(t);
  }
  addLabel(dots[0].date, PAD, 'start');
  addLabel(dots[dots.length-1].date, W - PAD, 'end');
})();

function localIso(d) { return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0'); }
function today() {
  return localIso(new Date());
}
function daysAgo(n) {
  var d = new Date(); d.setDate(d.getDate() - n);
  return localIso(d);
}

function setPreset(days) {
  if (days === 0) {
    document.getElementById('bulkFrom').value = '';
    document.getElementById('bulkTo').value   = '';
  } else {
    document.getElementById('bulkFrom').value = daysAgo(days);
    document.getElementById('bulkTo').value   = today();
  }
  updateCount();
}

function bulkSport() {
  var el = document.getElementById('bulkSport');
  return el ? el.value : '';
}

function updateCount() {
  var from  = document.getElementById('bulkFrom').value;
  var to    = document.getElementById('bulkTo').value;
  var force = document.getElementById('bulkForce').checked ? '1' : '0';
  var url   = '/ai/count?force=' + force + (from ? '&from='+from : '') + (to ? '&to='+to : '') + '&sport=' + encodeURIComponent(bulkSport());
  fetch(url).then(r => r.json()).then(d => {
    var label = document.getElementById('bulkCountLabel');
    label.textContent = d.count + ' ' + (d.count === 1 ? 'activity' : 'activities') + ' to analyse';
    label.style.color = d.count > 0 ? 'var(--text)' : 'var(--text-muted)';
  });
}

document.getElementById('bulkFrom').addEventListener('change', updateCount);
document.getElementById('bulkTo').addEventListener('change',   updateCount);
document.getElementById('bulkForce').addEventListener('change', updateCount);
if (document.getElementById('bulkSport')) document.getElementById('bulkSport').addEventListener('change', updateCount);
updateCount();

// Analyse New Activities: ticking Every sport greys out the single sports, which it takes in
(function () {
  var every = document.getElementById('autoEvery');
  if (!every) return;
  function sync() {
    document.querySelectorAll('input[name="sport"]').forEach(function (cb) { cb.disabled = every.checked; });
  }
  every.addEventListener('change', sync);
  sync();
})();

function startBulk() {
  var from  = document.getElementById('bulkFrom').value;
  var to    = document.getElementById('bulkTo').value;
  var force = document.getElementById('bulkForce').checked ? '1' : '0';

  document.getElementById('bulkProgress').style.display = 'block';
  document.getElementById('bulkDone').style.display     = 'none';
  document.getElementById('bulkStartBtn').disabled      = true;
  document.getElementById('bulkLog').innerHTML          = '';
  document.getElementById('bulkBar').style.width        = '0%';

  function lost(text) {
    document.getElementById('bulkStartBtn').disabled = false;
    document.getElementById('bulkStatusText').textContent = text;
  }
  // The batch runs in the background (services/jobs.py): leaving the page doesn't stop it
  var body = new FormData();
  body.append('force', force);
  body.append('from', from);
  body.append('to', to);
  body.append('sport', bulkSport());
  fetch('/ai/bulk-analyse', { method: 'POST', body: body }).then(function (r) { return r.json(); }).then(function (r) {
    if (!r.job) return lost('Could not start the analysis.');
    var finished = false;
    followJob(r.job, function (d) {
      if (d.type === 'start') {
        document.getElementById('bulkCounter').textContent = '0 / ' + d.total;
      } else if (d.type === 'progress') {
        var pct = Math.round((d.i / d.total) * 100);
        document.getElementById('bulkBar').style.width = pct + '%';
        document.getElementById('bulkCounter').textContent = d.i + ' / ' + d.total;
        document.getElementById('bulkStatusText').textContent = d.date + ' — ' + d.name;
        var log = document.getElementById('bulkLog');
        var row = document.createElement('div');
        row.textContent = '✓ ' + d.date + ' · ' + d.name;
        row.style.color = 'var(--text-muted)';
        log.appendChild(row);
        log.scrollTop = log.scrollHeight;
      } else if (d.type === 'error') {
        var log = document.getElementById('bulkLog');
        var row = document.createElement('div');
        row.textContent = '✗ ' + d.name + (d.detail ? ' — ' + d.detail : '');
        row.style.color = 'var(--danger)';
        log.appendChild(row);
        log.scrollTop = log.scrollHeight;
      } else if (d.type === 'done') {
        finished = true;
        document.getElementById('bulkBar').style.width = '100%';
        document.getElementById('bulkStartBtn').disabled = false;
        document.getElementById('bulkStatusText').textContent = 'Done';
        var doneEl = document.getElementById('bulkDone');
        doneEl.style.display = 'block';
        doneEl.textContent   = '✓ ' + d.analysed + ' ' + (d.analysed === 1 ? 'activity' : 'activities') + ' analysed'
          + (d.skipped > 0 ? ', ' + d.skipped + ' failed' : '') + '.';
        updateCount();
      }
    }, function (state, error) {
      if (!finished) lost(state === 'lost' ? 'Connection lost.' : 'Stopped: ' + (error || 'see the Tasks page') + '.');
    });
  }).catch(function () { lost('Connection lost.'); });
}
