// The target's unit follows what's counted: miles or km, feet or metres, hours, activities
function goalUnit(sel) {
  var u = JSON.parse(sel.dataset.units)[sel.value];
  document.querySelectorAll('[data-unit-for="' + sel.id + '"]').forEach(function (el) { el.textContent = u; });
}

// A goal's sports: Every sport, or any of the rest; ticking one clears the other kind
function goalSportTick(box) {
  var all = box.closest('.checks').querySelectorAll('input[type=checkbox]');
  all.forEach(function (b) { if (b !== box && box.checked && (box.name === 'every') !== (b.name === 'every')) b.checked = false; });
}
