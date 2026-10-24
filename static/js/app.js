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
