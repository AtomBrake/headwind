/* Date-range picker on a bike's or kit's page (gear_item.html): put every ride in a range on this bike, or every activity of the ticked sports
   on these shoes, with a live count first. The full calendar for bikes is /gear/assign. */
(function () {
  'use strict';
  const G = window.GEAR_ASSIGN, $ = (id) => document.getElementById(id);
  if (!G || !$('bApply')) return;
  const pad = (n) => String(n).padStart(2, '0'), iso = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;   // local date, never toISOString (UTC shift)
  const isBike = G.what === 'bike', url = (isBike ? '/gear/api/assign' : '/gear/api/kit-assign') + '?rider=' + G.rider;
  const [one, many] = G.noun, n_ = (n) => `${n.toLocaleString()} ${n === 1 ? one : many}`, esc = (s) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;');
  const sportBoxes = () => [...document.querySelectorAll('input[name=aSport]')];
  let timer = null, seq = 0;
  const range = () => ({ from: $('bFrom').value || null, to: $('bPresent').checked ? G.today : ($('bTo').value || null) });
  const payload = (dry) => {
    const r = range(), p = { from: r.from, to: r.to, only_unassigned: $('bOnlyUn').checked, dry_run: dry };
    return isBike ? Object.assign(p, { bike: G.id, dates: [] }) : Object.assign(p, { kit: G.id, sports: sportBoxes().filter((c) => c.checked).map((c) => c.value) });
  };
  function schedule() {
    clearTimeout(timer); $('bApply').disabled = true; $('bResult').textContent = '';
    const r = range();
    if (!r.from && !r.to) { $('bPreview').textContent = `Choose a start date to see how many ${many} will move onto ${G.name}.`; return; }
    if (!isBike && !payload(true).sports.length) { $('bPreview').textContent = 'Tick at least one sport.'; return; }
    timer = setTimeout(preview, 250);
  }
  async function preview() {
    const my = ++seq, res = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload(true)) }), j = await res.json();
    if (my !== seq) return;
    if (!res.ok) { $('bPreview').textContent = j.error || 'Could not work that out.'; return; }
    const left = j.matched - j.changed;
    $('bPreview').innerHTML = j.matched === 0 ? `No ${many} in that range.` : j.changed === 0 ? `All ${n_(j.matched)} ${j.matched === 1 ? 'is' : 'are'} already on it or left alone.`
      : `<strong>${n_(j.changed)}</strong> will be put on <strong>${esc(G.name)}</strong>.` + (left > 0 ? `<div class="hint">${left.toLocaleString()} left as they are.</div>` : '');
    $('bApply').disabled = j.changed === 0; $('bApply').dataset.n = j.changed;
  }
  ['bFrom', 'bTo', 'bPresent', 'bOnlyUn'].forEach((id) => { $(id).onchange = () => { if (id === 'bPresent') $('bTo').disabled = $('bPresent').checked; schedule(); }; });
  sportBoxes().forEach((c) => { c.onchange = schedule; });
  document.querySelectorAll('[data-q]').forEach((b) => { b.onclick = () => {
    const t = new Date(), q = b.dataset.q;
    if (q === 'year') { $('bFrom').value = `${t.getFullYear()}-01-01`; $('bTo').value = iso(t); $('bPresent').checked = false; }
    if (q === '30') { const f = new Date(t); f.setDate(f.getDate() - 30); $('bFrom').value = iso(f); $('bPresent').checked = true; }
    if (q === 'all') { $('bFrom').value = '2000-01-01'; $('bPresent').checked = true; $('bOnlyUn').checked = true; }
    $('bTo').disabled = $('bPresent').checked; schedule();
  }; });
  $('bApply').onclick = async () => {
    const n = +$('bApply').dataset.n || 0;
    if (n > 50 && !confirm(`Put ${n_(n)} on ${G.name}?`)) return;
    $('bApply').disabled = true;
    const res = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload(false)) }), j = await res.json();
    if (!res.ok) { $('bResult').textContent = j.error || 'Something went wrong.'; return; }
    $('bResult').textContent = `Done: ${n_(j.changed)} updated. Refreshing...`;
    setTimeout(() => location.reload(), 700);
  };
})();
