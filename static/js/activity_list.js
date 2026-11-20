// The history tree carries only the open month's activities; any other month's are fetched the first time it is opened (routes/dashboard.history).
(function () {
var data = document.currentScript.dataset;   // riderQuery, listPath
document.addEventListener('toggle', function (e) {
  var det = e.target;
  if (!det.open || !det.classList || !det.classList.contains('tree-month')) return;
  var slot = det.querySelector(':scope > .tree-days-pending');
  if (!slot || slot.dataset.loading) return;
  slot.dataset.loading = '1';
  slot.textContent = 'Loading…';
  var rq = data.riderQuery, q = (rq ? rq + '&' : '') + 'from=' + slot.dataset.historyFrom + '&to=' + slot.dataset.historyTo;
  fetch('/dashboard/history?' + q + '&list=' + encodeURIComponent(data.listPath)).then(function (r) {
    if (!r.ok) throw new Error(r.status);
    return r.text();
  }).then(function (html) {
    slot.insertAdjacentHTML('beforebegin', html);
    slot.remove();
    document.dispatchEvent(new Event('pick-list-changed'));   // static/js/bulk.js marks rows already picked
  }).catch(function () {
    delete slot.dataset.loading;
    slot.textContent = 'Could not load this month. Close it and open it again to retry, or use List.';
  });
}, true);
})();

function filterSubmitted(form) { if (window.sportSkips) sportSkips(form); }      // static/js/sport_filter.js, when the list has the sport filter
function confirmBulkSport(form, n) {
  return confirm('Change the type of these ' + n + ' activities to ' + form.sport.options[form.sport.selectedIndex].text + '?');
}
