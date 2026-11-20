// The kind and retired boxes only mean something for a bike being added.
document.querySelectorAll('.sb-row').forEach(row => {
  const sel = row.querySelector('.sb-match');
  const sync = () => row.querySelectorAll('.sb-new').forEach(el => { el.style.visibility = sel.value === 'new' ? 'visible' : 'hidden'; });
  sel.addEventListener('change', sync);
  sync();
});
