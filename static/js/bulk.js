// Select mode for activity lists (templates/_bulk_bar.html). In select mode a click on a row picks it instead of opening it; shift-click picks
// everything between the last pick and this one. The bar at the bottom of the screen acts on the picked activities through POST /rides/bulk.
(function () {
  var bar = document.getElementById('bulkBar');
  if (!bar) return;
  var picked = new Set(), last = null, on = false, optionsLoaded = false;
  var rows = function () { return Array.prototype.slice.call(document.querySelectorAll('[data-pick-list] [data-pick]')); };
  var visible = function () { return rows().filter(function (r) { return r.offsetParent !== null; }); };

  function render() {
    rows().forEach(function (r) {
      var sel = picked.has(r.dataset.pick);
      r.classList.toggle('picked', sel);
      r.setAttribute('aria-pressed', on ? String(sel) : null);
      if (!on) r.removeAttribute('aria-pressed');
    });
    var n = picked.size;
    bar.querySelector('.bulk-count').textContent = n + ' picked';
    bar.querySelectorAll('select, .btn').forEach(function (el) { el.disabled = n === 0; });
  }

  function setMode(v) {
    on = v;
    document.body.classList.toggle('bulk-mode', on);
    bar.hidden = !on;
    if (!on) { picked.clear(); last = null; }
    document.querySelectorAll('[data-pick-toggle]').forEach(function (b) { b.textContent = on ? 'Done' : 'Select'; });
    if (on && !optionsLoaded) loadOptions();
    render();
  }

  function loadOptions() {
    optionsLoaded = true;
    fetch('/rides/bulk/options').then(function (r) { return r.json(); }).then(function (d) {
      var sport = bar.querySelector('[name=sport]'), bike = bar.querySelector('[name=bike]'), rider = bar.querySelector('[name=rider]'), kit = bar.querySelector('[name=kit]');
      d.sports.forEach(function (s) { sport.add(new Option(s.label, s.value)); });
      d.riders.forEach(function (r) {
        rider.add(new Option(r.name, r.id));
        [[bike, r.bikes], [kit, r.kit || []]].forEach(function (p) {        // one group of bikes (and of shoes and other kit) per rider
          if (!p[1].length) return;
          var g = document.createElement('optgroup');
          g.label = r.name;
          p[1].forEach(function (b) { g.appendChild(new Option(b.name, b.id)); });
          p[0].appendChild(g);
          p[0].hidden = false;
        });
      });
      if (d.riders.length < 2) rider.hidden = true;
    }).catch(function () {});
  }

  function toggle(row, shift) {
    var id = row.dataset.pick, list = visible();
    if (shift && last !== null) {
      var a = list.findIndex(function (r) { return r.dataset.pick === last; }), b = list.indexOf(row);
      if (a >= 0 && b >= 0) {
        list.slice(Math.min(a, b), Math.max(a, b) + 1).forEach(function (r) { picked.add(r.dataset.pick); });
        last = id;
        return render();
      }
    }
    picked.has(id) ? picked.delete(id) : picked.add(id);
    last = id;
    render();
  }

  // in select mode a row click picks it (captured before the row's own link or onclick)
  document.addEventListener('click', function (e) {
    if (!on) return;
    var row = e.target.closest('[data-pick-list] [data-pick]');
    if (!row || e.target.closest('#bulkBar')) return;
    e.preventDefault();
    e.stopPropagation();
    toggle(row, e.shiftKey);
  }, true);
  document.addEventListener('keydown', function (e) {
    if (on && e.key === 'Escape') setMode(false);
  });
  document.addEventListener('pick-list-changed', function () { render(); });   // rows added later (the dashboard's months, loaded when opened)
  document.querySelectorAll('[data-pick-toggle]').forEach(function (b) {
    b.addEventListener('click', function (e) { e.preventDefault(); setMode(!on); });
  });

  function submit(action, extra) {
    var ids = bar.querySelector('.bulk-ids');
    ids.replaceChildren();
    picked.forEach(function (id) {
      var i = document.createElement('input');
      i.type = 'hidden'; i.name = 'id'; i.value = id;
      ids.appendChild(i);
    });
    bar.querySelector('[name=action]').value = action;
    bar.action = action === 'download' ? '/rides/bulk/download' : '/rides/bulk';
    if (extra) extra();
    bar.submit();
  }

  var plural = function (n) { return n + ' activit' + (n === 1 ? 'y' : 'ies'); };
  bar.addEventListener('click', function (e) {
    var b = e.target.closest('[data-bulk]');
    if (!b) return;
    var act = b.dataset.bulk, n = picked.size;
    if (act === 'all') { visible().forEach(function (r) { picked.add(r.dataset.pick); }); return render(); }
    if (act === 'none') { picked.clear(); return render(); }
    if (act === 'done') return setMode(false);
    if (!n) return;
    if (act === 'delete' && !confirm('Delete ' + plural(n) + '? Their photos, notes and segment times go with them. This cannot be undone.')) return;
    if (act === 'dismiss' && !confirm('Mark ' + plural(n) + ' as right? Flagged ones count in the speed and weather analytics again.')) return;
    if (act === 'rename') {
      var name = prompt('New name for ' + plural(n) + ':');
      if (!name || !name.trim()) return;
      return submit('rename', function () { bar.querySelector('[name=name]').value = name.trim(); });
    }
    submit(act);
  });
  bar.addEventListener('change', function (e) {
    var sel = e.target, n = picked.size;
    if (!sel.value || !n) return;
    var label = sel.options[sel.selectedIndex].text;
    var q = { sport: 'Change ' + plural(n) + ' to ' + label + '? Rides that become walks, runs or other sports move to Workouts.',
              bike: 'Set the bike on ' + plural(n) + ' to ' + label + '? Only rides of that bike’s rider change.',
              kit: 'Set the gear on ' + plural(n) + ' to ' + label + '? Rides keep their bike; only that rider’s other activities change.',
              rider: 'Move ' + plural(n) + ' to ' + label + '? Their bikes are cleared.',
              commute: (sel.value === '1' ? 'Mark ' + plural(n) + ' as a commute?' : 'Mark ' + plural(n) + ' as not a commute?') }[sel.name];
    if (!q || !confirm(q)) { sel.value = ''; return; }
    bar.querySelectorAll('select').forEach(function (o) { if (o !== sel) o.value = ''; });
    submit(sel.name);
  });
})();
