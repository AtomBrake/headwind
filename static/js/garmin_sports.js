// stored in UTC: show in this browser's time, as on the Tasks page
document.querySelectorAll('[data-when]').forEach(function (el) {
  var d = new Date(el.dataset.when);
  if (isNaN(d)) return;
  var t = d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  el.textContent = (d.toDateString() === new Date().toDateString() ? 'today ' : d.getDate() + ' ' + _MONTHS[d.getMonth()] + ' ') + t;
});
if (document.currentScript.hasAttribute('data-running')) setTimeout(function () { location.reload(); }, 5000);

function confirmSportFixes(form) {
  var n = form.querySelectorAll('input[name=ride]:checked').length;
  return confirm('Change ' + n + ' activit' + (n == 1 ? 'y' : 'ies') + ' to the sport Garmin recorded? Rides that become runs, swims and so on lose their bike and ride segment times. The ones you untick are left as they are and not suggested again.'
                 + (form.querySelectorAll('input[name=ride][data-parked]:checked').length ? ' Other recordings set aside under the ticked ones are removed with them.' : ''));
}
function tickAllRides(box) { document.querySelectorAll('input[name=ride]').forEach(c => c.checked = box.checked); }
