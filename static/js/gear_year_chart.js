// A gear item's distance per year (templates/gear_item.html)
(function () {
  const rows = JSON.parse(document.getElementById('yearRows').textContent), noun = JSON.parse(document.getElementById('gearAssign').textContent).noun;
  if (!window.Chart) return;
  new Chart(document.getElementById('yearChart'), { type: 'bar',
    data: { labels: rows.map(r => r.year), datasets: [{ data: rows.map(r => Math.round(UNITS.toDist(r.distance))), backgroundColor: cssVar('--accent'), borderRadius: 4, maxBarThickness: 64 }] },
    options: { maintainAspectRatio: false, plugins: { legend: { display: false }, tooltip: { callbacks: { label: c => c.parsed.y.toLocaleString() + ' ' + UNITS.dist + ' · ' + rows[c.dataIndex].n + ' ' + noun[rows[c.dataIndex].n === 1 ? 0 : 1] } } },
      scales: { x: { ticks: { color: cssVar('--text-soft') }, grid: { display: false } }, y: { ticks: { color: cssVar('--text-soft') }, grid: { color: cssVar('--border') } } } } });
})();
