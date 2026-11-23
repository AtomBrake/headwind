let currentDate = new Date(); currentDate.setHours(12, 0, 0, 0);

function isoDate(d) {   // local calendar date (toISOString is UTC and flips the day near midnight)
  return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0');
}

function fmtDate(iso) {
  const [y, m, d] = iso.split('-').map(Number);
  const date = new Date(y, m - 1, d);
  return date.toLocaleDateString('en-GB', { month: 'short', day: 'numeric' });
}

async function loadWeek() {
  const dateStr = isoDate(currentDate);      // the server finds the week it's in, from the rider's chosen first day (services/periods)

  const r = await fetch(`/nutrition/api/week/${dateStr}`);
  if (!r.ok) {
    document.getElementById('weekLabel').textContent = 'Error loading data';
    return;
  }

  const data = await r.json();
  const days = data.days;
  const totals = data.totals;
  const goals = data.goals || {};

  // Week label
  const label = `w/c ${fmtDate(data.week_start)}`;
  document.getElementById('weekLabel').textContent = label;

  // Summary cards
  document.getElementById('summaryEaten').textContent = `${totals.eaten} kcal`;
  document.getElementById('summaryBurned').textContent = totals.burned ? `${totals.burned} kcal` : '—';
  if (totals.net !== null) {
    const netVal = Math.abs(totals.net);
    const isDeficit = totals.net < 0;
    document.getElementById('summaryNet').textContent = `${isDeficit ? '−' : '+'}${netVal} kcal`;
    document.getElementById('summaryNet').className = `summary-value ${isDeficit ? 'deficit' : 'surplus'}`;
  } else {
    document.getElementById('summaryNet').textContent = '—';
  }
  const totalProtein = totals.protein.toFixed(0);
  const totalCarbs = totals.carbs.toFixed(0);
  const totalFat = totals.fat.toFixed(0);

  document.getElementById('summaryProtein').textContent = `${totalProtein}g`;
  document.getElementById('summaryCarbsVal').textContent = `${totalCarbs}g`;
  document.getElementById('summaryFatVal').textContent = `${totalFat}g`;

  const proteinTarget = goals.protein ? (goals.protein * 7).toFixed(0) : null;
  const carbsTarget = goals.carbs ? (goals.carbs * 7).toFixed(0) : null;
  const fatTarget = goals.fat ? (goals.fat * 7).toFixed(0) : null;

  document.getElementById('proteinTarget').textContent = proteinTarget ? `target ${proteinTarget}g` : '';
  document.getElementById('carbsTarget').textContent = carbsTarget ? `target ${carbsTarget}g` : '';
  document.getElementById('fatTarget').textContent = fatTarget ? `target ${fatTarget}g` : '';

  // Table
  const tbody = document.getElementById('weekTableBody');
  tbody.innerHTML = days.map(d => {
    const netClass = d.net === null ? 'neutral' : (d.net < 0 ? 'deficit' : 'surplus');
    const netVal = d.net === null ? '—' : `${d.net < 0 ? '−' : '+'}${Math.abs(d.net)}`;
    const rowClass = d.has_data ? '' : 'no-data';
    const actIcon = d.has_activity ? ' 🚴' : '';
    return `
      <tr class="${rowClass}">
        <td data-sort="${d.date}">${d.dow} ${fmtDate(d.date)}${actIcon}</td>
        <td>${d.eaten}</td>
        <td>${d.burned || '—'}</td>
        <td data-sort="${d.net === null ? '' : d.net}"><span class="badge ${netClass}">${netVal}</span></td>
        <td data-sort="${d.protein}">${d.protein.toFixed(0)}g</td>
        <td data-sort="${d.carbs}">${d.carbs.toFixed(0)}g</td>
        <td data-sort="${d.fat}">${d.fat.toFixed(0)}g</td>
        <td data-sort="${d.water_ml}">${d.water_ml}ml</td>
      </tr>
    `;
  }).join('');

  if (window.sortTable) sortTable(document.getElementById('weekTable'));   // app.js loads after this page's script

  // Totals row, under the days however they're sorted
  const totalsNet = totals.net === null ? '—' : `${totals.net < 0 ? '−' : '+'}${Math.abs(totals.net)}`;
  const netClass = totals.net === null ? 'neutral' : (totals.net < 0 ? 'deficit' : 'surplus');
  document.getElementById('weekTableFoot').innerHTML = `
    <tr class="totals">
      <td>Total</td>
      <td>${totals.eaten}</td>
      <td>${totals.burned}</td>
      <td><span class="badge ${netClass}">${totalsNet}</span></td>
      <td>${totals.protein.toFixed(0)}g</td>
      <td>${totals.carbs.toFixed(0)}g</td>
      <td>${totals.fat.toFixed(0)}g</td>
      <td>${totals.water_ml}ml</td>
    </tr>
    <tr class="totals" style="opacity: 0.6; font-size: 0.85rem;">
      <td></td>
      <td></td>
      <td></td>
      <td></td>
      <td>${proteinTarget ? `target ${proteinTarget}g` : ''}</td>
      <td>${carbsTarget ? `target ${carbsTarget}g` : ''}</td>
      <td>${fatTarget ? `target ${fatTarget}g` : ''}</td>
      <td></td>
    </tr>
  `;
}

function prevWeek() {
  currentDate.setDate(currentDate.getDate() - 7);
  loadWeek();
}

function nextWeek() {
  currentDate.setDate(currentDate.getDate() + 7);
  loadWeek();
}

function thisWeek() {
  currentDate = new Date(); currentDate.setHours(12, 0, 0, 0);
  loadWeek();
}

document.addEventListener('DOMContentLoaded', loadWeek);
