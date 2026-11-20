function sportSkips(form, changed) {        // the unticked sports become skip=… on the form, for the tick boxes and the form's own button alike
  form.querySelectorAll('input[name="skip"]').forEach(i => i.remove());
  const keep = Array.from(form.elements).filter(b => b.matches('input[data-keep]'));
  if (changed) keep.forEach(b => b.remove());           // a box changed: the list is what's ticked now, not the group= or only= it was opened with
  else if (keep.length) return;
  Array.from(form.elements).filter(b => b.matches('input[data-sport]') && !b.checked).forEach(b => {
    const h = document.createElement('input'); h.type = 'hidden'; h.name = 'skip'; h.value = b.value; form.appendChild(h);
  });
}

function sportFilterAll(form) {             // "Every sport": tick them all
  Array.from(form.elements).forEach(b => { if (b.matches('input[data-sport]')) b.checked = true; });
  sportSkips(form, true);
  form.submit();
}
