document.addEventListener('DOMContentLoaded', function () {
  document.querySelectorAll('.flash').forEach(function (el) {
    setTimeout(function () {
      el.style.transition = 'opacity 0.4s';
      el.style.opacity = '0';
      setTimeout(function () { el.remove(); }, 400);
    }, 4000);
  });
});

// A ⋯ menu (.more-menu) closes on a click outside it or on Esc.
document.addEventListener('click', function (ev) {
  document.querySelectorAll('details.more-menu[open]').forEach(function (d) {
    if (!d.contains(ev.target)) d.removeAttribute('open');
  });
});
document.addEventListener('keydown', function (ev) {
  if (ev.key !== 'Escape') return;
  document.querySelectorAll('details.more-menu[open]').forEach(function (d) {
    d.removeAttribute('open');
    d.querySelector('summary').focus();
  });
});

function doSync() {
  var btn = document.getElementById('syncBtn');
  if (!btn) return;
  btn.disabled = true;
  btn.textContent = 'Syncing...';
  fetch('/sync', { method: 'POST' })
    .then(function (r) { return r.json(); })
    .then(function (data) {
      btn.textContent = data.synced !== undefined
        ? 'Synced ' + data.synced + ' rides'
        : (data.error || 'Error');
      setTimeout(function () {
        btn.disabled = false;
        btn.textContent = 'Sync Rides';
        if (data.synced) location.reload();
      }, 2000);
    })
    .catch(function () {
      btn.textContent = 'Error';
      setTimeout(function () { btn.disabled = false; btn.textContent = 'Sync Rides'; }, 2000);
    });
}

function getKudos(rid) {
  var spinner     = document.getElementById('kudosSpinner');
  var card        = document.getElementById('kudosCard');
  var personality = (document.getElementById('personalitySelect') || {}).value || 'default';
  if (spinner) spinner.style.display = '';
  fetch('/rides/' + rid + '/kudos', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({personality: personality})
  })
    .then(function (r) { return r.json(); })
    .then(function (data) {
      if (spinner) spinner.style.display = 'none';
      if (data.kudos) {
        var el = document.getElementById('kudosText');
        if (el) {
          el.textContent = data.kudos;
        } else {
          var newEl = document.createElement('div');
          newEl.id = 'kudosText';
          newEl.style.cssText = 'line-height:1.9; white-space:pre-wrap;';
          newEl.textContent = data.kudos;
          card.insertBefore(newEl, spinner);
        }
      } else if (data.error) {
        alert('Error: ' + data.error);
      }
    })
    .catch(function () {
      if (spinner) spinner.style.display = 'none';
      alert('Request failed');
    });
}

// A new ride being analysed in the background (services/auto_analyse.py): look every few seconds, and show the page again once it's done.
(function () {
  var el = document.getElementById('kudosPending');
  if (!el) return;
  var rid = el.getAttribute('data-rid');
  var timer = setInterval(function () {
    fetch('/rides/' + rid + '/kudos/status')
      .then(function (r) { return r.json(); })
      .then(function (data) {
        if (!data.pending) { clearInterval(timer); location.reload(); }
      })
      .catch(function () {});
  }, 5000);
})();

// Safari draws an empty date field with today's date in it, which reads as a value. Mark empty ones so the CSS can dim them.
(function () {
  function mark(el) { el.classList.toggle('is-empty', !el.value); }
  document.addEventListener('DOMContentLoaded', function () {
    document.querySelectorAll('input[type="date"]').forEach(mark);
  });
  ['input', 'change'].forEach(function (ev) {
    document.addEventListener(ev, function (e) {
      if (e.target.matches && e.target.matches('input[type="date"]')) mark(e.target);
    });
  });
})();

// Sortable tables (docs/UI.md, Tables): click a heading of a <table class="sortable"> to sort on it, click again to turn it round.
// A cell's data-sort is the value to sort on (metres, seconds, an ISO date), else its text. Empty cells go last either way.
// A heading sorts ascending first, or descending with data-first="desc"; aria-sort in the markup marks the order the rows come in.
// A tr.grp heads a group, and its rows sort among themselves; a tr[data-follows] (an edit row) stays under the row before it.
// The choice goes in the URL (?sort=col, ?sort=-col for descending; the parameter is data-sort-name when a page has more than one).
(function () {
  function key(th) {
    return th.dataset.col || th.textContent.trim().toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
  }
  function value(tr, i) {
    var td = tr.cells[i];
    if (!td) return '';
    var v = td.hasAttribute('data-sort') ? td.dataset.sort : td.textContent.trim();
    return v === '—' ? '' : v;
  }
  function compare(a, b) {
    var x = Number(a), y = Number(b);
    if (!isNaN(x) && !isNaN(y)) return x - y;
    return a.localeCompare(b, undefined, {numeric: true, sensitivity: 'base'});
  }
  function apply(table) {
    var st = table._sort;
    if (!st) return;
    var i = st.th.cellIndex, sign = st.dir === 'ascending' ? 1 : -1;
    table.querySelectorAll('thead th').forEach(function (th) {
      if (th === st.th) th.setAttribute('aria-sort', st.dir); else th.removeAttribute('aria-sort');
    });
    Array.prototype.forEach.call(table.tBodies, function (tbody) {
      var groups = [{head: null, blocks: []}];                  // blocks: a row and the rows that follow it
      Array.prototype.slice.call(tbody.rows).forEach(function (tr) {
        var g = groups[groups.length - 1];
        if (tr.classList.contains('grp')) groups.push({head: tr, blocks: []});
        else if (tr.hasAttribute('data-follows') && g.blocks.length) g.blocks[g.blocks.length - 1].push(tr);
        else g.blocks.push([tr]);
      });
      groups.forEach(function (g) {
        g.blocks.sort(function (p, q) {
          var a = value(p[0], i), b = value(q[0], i);
          if (a === '' || b === '') return (a === '') - (b === '');
          return sign * compare(a, b);
        });
        if (g.head) tbody.appendChild(g.head);
        g.blocks.forEach(function (b) { b.forEach(function (tr) { tbody.appendChild(tr); }); });
      });
    });
  }
  function remember(table) {
    var st = table._sort, name = table.dataset.sortName || 'sort';
    try {
      var url = new URL(location.href);
      url.searchParams.set(name, (st.dir === 'descending' ? '-' : '') + key(st.th));
      history.replaceState(history.state, '', url);
    } catch (e) {}
  }
  function setup(table) {
    var wanted = new URLSearchParams(location.search).get(table.dataset.sortName || 'sort') || '';
    var want = wanted.replace(/^-/, ''), wantDir = wanted.charAt(0) === '-' ? 'descending' : 'ascending', fromUrl = null;
    table.querySelectorAll('thead th').forEach(function (th) {
      if (th.hasAttribute('data-nosort') || !th.textContent.trim()) return;
      var btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'th-sort';
      while (th.firstChild) btn.appendChild(th.firstChild);
      th.appendChild(btn);
      if (th.hasAttribute('aria-sort')) table._sort = {th: th, dir: th.getAttribute('aria-sort')};
      if (want && key(th) === want) fromUrl = {th: th, dir: wantDir};
      btn.addEventListener('click', function () {
        var st = table._sort, first = th.dataset.first === 'desc' ? 'descending' : 'ascending';
        var dir = st && st.th === th ? (st.dir === 'ascending' ? 'descending' : 'ascending') : first;
        table._sort = {th: th, dir: dir};
        apply(table);
        remember(table);
      });
    });
    if (fromUrl) { table._sort = fromUrl; apply(table); }
  }
  // A page that fills or refills a table itself calls this afterwards to put the rows back in the chosen order.
  window.sortTable = function (table) { if (table) apply(table); };
  document.addEventListener('DOMContentLoaded', function () {
    document.querySelectorAll('table.sortable').forEach(setup);
  });
})();
