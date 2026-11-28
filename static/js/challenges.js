// The Challenges page's form (templates/challenges.html): a total shows its sport and target, a segment race its class and segments
function challengeKind(sel) {
  var race = sel.value === 'segments';
  document.getElementById('challengeForm').classList.toggle('race-form', race);
  if (!race) goalUnit(sel);
  raceClass(document.getElementById('chClass'));
}

// Only the segments of the class's family (rides for a bike or an e-bike, on foot for on foot); a ticked one of the other family is let go
function raceClass(sel) {
  var picks = document.getElementById('racePicks');
  if (!sel || !picks) return;
  var family = sel.options[sel.selectedIndex].dataset.family;
  picks.querySelectorAll('label[data-family]').forEach(function (l) {
    var fits = l.dataset.family === family;
    l.hidden = !fits;
    if (!fits) l.querySelector('input').checked = false;
  });
  racePick(null);
}

// No more than the most a race has: the rest can't be ticked until one is let go
function racePick() {
  var picks = document.getElementById('racePicks');
  if (!picks) return;
  var boxes = picks.querySelectorAll('input[type=checkbox]');
  var n = picks.querySelectorAll('input[type=checkbox]:checked').length;
  boxes.forEach(function (b) { b.disabled = !b.checked && n >= Number(picks.dataset.max); });
}

(function () {
  var sel = document.getElementById('chMetric');
  if (sel) challengeKind(sel);
})();
