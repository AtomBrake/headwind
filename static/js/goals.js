// The target's unit follows what's counted: miles or km, feet or metres, hours, activities
function goalUnit(sel) {
  var u = JSON.parse(sel.dataset.units)[sel.value];
  document.querySelectorAll('[data-unit-for="' + sel.id + '"]').forEach(function (el) { el.textContent = u; });
}
