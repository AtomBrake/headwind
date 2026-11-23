const PAGE = JSON.parse(document.getElementById('analyticsData').textContent);
// A cell that shows `text` and sorts on `value` (static/js/app.js, sortable tables)
function sortCell(td, text, value) {
  td.textContent = text;
  td.dataset.sort = value == null ? '' : value;
}

// ── Best times (one table per sport: rides, runs, swims) ──────────
(function() {
  const data = PAGE.achievements;
  data.forEach(ach => {
    const card = document.querySelector(`[data-records="${ach.key}"]`);
    const recYear = card && card.querySelector('.rec-year'), recMonth = card && card.querySelector('.rec-month');
    if (!recYear || !card.querySelector('.rec-table')) return;   // no efforts yet: nothing to fill in
    function populateMonths() {
      recMonth.innerHTML = '<option value="all">All months</option>';
      Object.keys(ach.by_month).filter(ym => ym.startsWith(recYear.value)).sort().reverse()
        .forEach(ym => recMonth.add(new Option(fmtMonth(ym), ym)));
    }
    function render() {
      const src = recMonth.value === 'all' ? (ach.by_year[recYear.value] || {}) : (ach.by_month[recMonth.value] || {});
      let anyData = false;
      card.querySelectorAll('tr[data-dist]').forEach(row => {
        const rec = src[row.dataset.dist];
        row.style.display = rec ? '' : 'none';
        if (!rec) return;
        anyData = true;
        sortCell(row.querySelector('.rec-time'), rec.time, rec.secs);
        sortCell(row.querySelector('.rec-speed'), rec.rate, rec.mps ? (ach.style === 'speed' ? rec.mps : 1 / rec.mps) : '');
        const a = document.createElement('a');
        a.href = '/activities/' + encodeURIComponent(rec.activityId);
        a.textContent = rec.name;
        row.querySelector('.rec-ride').replaceChildren(a);
        sortCell(row.querySelector('.rec-date'), fmtDate(rec.date), rec.date);
      });
      sortTable(card.querySelector('.rec-table'));
      card.querySelector('.rec-empty').style.display = anyData ? 'none' : '';
      card.querySelector('.rec-table').style.display = anyData ? '' : 'none';
    }
    recYear.addEventListener('change', () => { populateMonths(); render(); });
    recMonth.addEventListener('change', render);
    populateMonths();
    render();
  });
})();

// ── Records by sport ──────────────────────────────────────────────
(function() {
  const byPeriod = PAGE.sportRecords;
  const sel = document.getElementById('srPeriod'), body = document.getElementById('srBody');
  if (!sel || !body) return;
  function cell(rec) {
    const td = document.createElement('td');
    td.style.verticalAlign = 'top';
    if (!rec) { td.textContent = '—'; td.style.color = 'var(--text-muted)'; return td; }
    td.dataset.sort = rec.n;
    const v = document.createElement('div');
    v.style.cssText = 'font-weight:600; color:var(--accent); font-variant-numeric:tabular-nums; white-space:nowrap;';
    v.textContent = rec.v;
    const a = document.createElement('a');
    a.href = '/activities/' + encodeURIComponent(rec.id);
    a.style.cssText = 'display:block; color:var(--text-muted); font-size:0.75rem; margin-top:0.15rem;';
    a.textContent = rec.name + ' · ' + fmtDate(rec.date);
    td.append(v, a);
    return td;
  }
  function render() {
    body.replaceChildren(...(byPeriod[sel.value] || []).map(r => {
      const tr = document.createElement('tr');
      const name = document.createElement('td');
      name.style.cssText = 'font-weight:600; white-space:nowrap; vertical-align:top;';
      name.textContent = r.icon + ' ' + r.sport;
      name.dataset.sort = r.sport;
      tr.append(name, cell(r.dist), cell(r.time), cell(r.climb), cell(r.fast));
      return tr;
    }));
    sortTable(body.closest('table'));
  }
  sel.addEventListener('change', render);
  render();
})();

// ── Climbing Records ──────────────────────────────────────────────
(function() {
  const byYear  = PAGE.climbingByYear;
  const byMonth = PAGE.climbingByMonth;
  const climbYear  = document.getElementById('climbYear');
  const climbMonth = document.getElementById('climbMonth');
  if (!climbYear) return;

  function populateClimbMonths() {
    const yr = climbYear.value;
    climbMonth.innerHTML = '<option value="all">All months</option>';
    Object.keys(byMonth).filter(ym => ym.startsWith(yr)).sort().reverse().forEach(ym => {
      climbMonth.add(new Option(fmtMonth(ym), ym));
    });
  }

  window.renderClimbing = function() {
    const yr  = climbYear.value;
    const mth = climbMonth.value;
    const src = mth === 'all' ? (byYear[yr] || {}) : (byMonth[mth] || {});
    const rows = document.querySelectorAll('#climbBody tr[data-bracket]');
    let anyData = false;
    rows.forEach(row => {
      const b   = row.dataset.bracket;
      const rec = src[b];
      if (rec) {
        anyData = true;
        sortCell(row.querySelector('.climb-ft'), rec.ft.toLocaleString() + ' ' + UNITS.elev, rec.ft);      // rec.ft is in the rider's unit
        {
          const a = document.createElement('a');
          a.href = '/activities/' + encodeURIComponent(rec.activityId);
          a.textContent = rec.name;
          row.querySelector('.climb-ride').replaceChildren(a);
        }
        sortCell(row.querySelector('.climb-date'), fmtDate(rec.date), rec.date);
        row.style.display = '';
      } else {
        row.style.display = 'none';
      }
    });
    document.getElementById('climbEmpty').style.display = anyData ? 'none' : '';
    document.getElementById('climbTable') && (document.getElementById('climbTable').style.display = anyData ? '' : 'none');
    sortTable(document.getElementById('climbTable'));
  };

  climbYear.addEventListener('change', function() { populateClimbMonths(); renderClimbing(); });
  populateClimbMonths();
  renderClimbing();
})();

function computeEfforts() {
  const btn = document.getElementById('effortsBtn');
  const st  = document.getElementById('effortsStatus');
  if (btn) btn.disabled = true;
  st.style.display = 'block';
  st.textContent = 'Scanning rides in the background: you can leave this page, and Tasks shows how far it has got.';
  fetch('/data/scan-efforts', { method: 'POST' })
    .then(r => r.json())
    .then(d => followJob(d.job, () => {}, (state, error) => {
      st.textContent = state === 'done' ? '✓ Scanned every ride — reload to see records.'
                     : state === 'lost' ? 'Lost touch with Headwind: the scan carries on, and Tasks shows how it went.'
                     : `Scan failed: ${error}`;
      if (btn) btn.disabled = false;
    }))
    .catch(() => { st.textContent = 'Scan failed.'; if (btn) btn.disabled = false; });
}

// ── Global defaults ──────────────────────────────────────────────
Chart.defaults.color          = cssVar('--text-muted');
Chart.defaults.borderColor    = cssVar('--border');
Chart.defaults.font.family    = 'inherit';
Chart.defaults.maintainAspectRatio = false;      // each chart fills a fixed-height box (.cbox) instead of growing taller as the screen gets wider

const GRID_COLOR  = cssVar('--border');
const TICK_COLOR  = cssVar('--text-muted');
const ORANGE      = cssVar('--accent');
const BLUE        = cssVar('--c-sky');
const GREEN       = cssVar('--success');
const PURPLE      = cssVar('--c-purple');
const YELLOW      = cssVar('--warning');
const RED         = cssVar('--danger');
const TEAL        = cssVar('--c-cyan');

function scalesXY(yLabel) {
  return {
    x: { ticks: { color: TICK_COLOR, font: { size: 10 }, maxTicksLimit: 12 }, grid: { color: GRID_COLOR } },
    y: { ticks: { color: TICK_COLOR, font: { size: 10 } }, grid: { color: GRID_COLOR },
         title: { display: !!yLabel, text: yLabel || '', color: TICK_COLOR, font: { size: 10 } } }
  };
}

function noLegend() { return { legend: { display: false } }; }

// What the charts count: distance in the rider's unit when the sports left in share one (services/sport_filter), else hours
const DIST_MODE = PAGE.distMode;
const AMOUNT_UNIT = DIST_MODE ? UNITS.dist : 'h';
const RATE_STYLE = PAGE.rateStyle;
const PACE = RATE_STYLE && RATE_STYLE !== 'speed';
const RATE_UNIT = PACE ? UNITS.paceLabel(RATE_STYLE) : UNITS.speed;

// ── Speed (or pace) scatter ──────────────────────────────────────
if (document.getElementById('speedChart')) new Chart(document.getElementById('speedChart'), {
  type: 'line',
  data: {
    labels: PAGE.speedLabels.map(fmtDate),
    datasets: [
      {
        label: PACE ? 'Pace' : 'Speed',
        data:  PAGE.speedValues,
        borderColor: 'transparent',
        pointBackgroundColor: cssVar('--c-sky', 0.45),
        pointBorderColor: 'transparent',
        pointRadius: 3,
        pointHoverRadius: 5,
        fill: false,
        tension: 0,
      },
      {
        label: '20-activity avg',
        data:  PAGE.speedRolling,
        borderColor: ORANGE,
        borderWidth: 2,
        pointRadius: 0,
        fill: false,
        tension: 0.4,
      }
    ]
  },
  options: {
    animation: false,
    plugins: {
      legend: { display: true, labels: { color: TICK_COLOR, boxWidth: 12 } },
      tooltip: { mode: 'index', intersect: false, callbacks: { label: ctx => ctx.dataset.label + ': ' + (PACE ? UNITS.fmtMinSec(ctx.parsed.y) : ctx.parsed.y) + ' ' + RATE_UNIT } }
    },
    scales: (function () {                       // pace: seconds per unit, drawn as m:ss with faster (fewer seconds) at the top
      const sc = scalesXY(RATE_UNIT);
      if (PACE) { sc.y.reverse = true; sc.y.ticks.callback = v => UNITS.fmtMinSec(v); }
      return sc;
    })()
  }
});

// ── Monthly distance ─────────────────────────────────────────────
new Chart(document.getElementById('monthlyChart'), {
  type: 'bar',
  data: {
    labels: PAGE.monthlyLabels.map(fmtMonth),
    datasets: [{
      data: PAGE.monthlyValues,
      backgroundColor: cssVar('--accent', 0.7),
      borderColor: ORANGE,
      borderWidth: 1,
      borderRadius: 3,
    }]
  },
  options: {
    animation: false,
    plugins: { ...noLegend(), tooltip: { callbacks: { label: ctx => `${ctx.parsed.y} ${AMOUNT_UNIT}` } } },
    scales: scalesXY(AMOUNT_UNIT)
  }
});

// ── Year on year ─────────────────────────────────────────────────
(function() {
  const yoyData   = PAGE.yearOnYear;
  const months    = PAGE.monthLabels;
  const years     = Object.keys(yoyData).sort();
  const palette   = ['--accent', '--c-sky', '--success', '--c-purple', '--warning', '--danger', '--c-cyan',
                     '--c-orange', '--info', '--c-teal', '--c-violet', '--c-pink', '--c-green', '--c-yellow', '--c-indigo'];

  const datasets = years.map((yr, i) => {
    const age    = years.length - 1 - i;
    const recent = age < 3;
    const color  = palette[i % palette.length];
    return {
      label: yr,
      data:  yoyData[yr],
      borderColor: cssVar(color, recent ? 1 : 0.28),
      backgroundColor: 'transparent',
      borderWidth: age === 0 ? 2.5 : (recent ? 1.8 : 1),
      pointRadius: age === 0 ? 3 : 0,
      tension: 0.3,
    };
  });

  new Chart(document.getElementById('yoyChart'), {
    type: 'line',
    data: { labels: months, datasets },
    options: {
      animation: false,
      plugins: {
        legend: { display: true, labels: { color: TICK_COLOR, boxWidth: 10, font: { size: 10 } } },
        tooltip: { mode: 'index', intersect: false, callbacks: { label: ctx => `${ctx.dataset.label}: ${ctx.parsed.y} ${AMOUNT_UNIT}` } }
      },
      scales: scalesXY(AMOUNT_UNIT)
    }
  });
})();

// ── Calories ─────────────────────────────────────────────────────
new Chart(document.getElementById('calChart'), {
  type: 'line',
  data: {
    labels: PAGE.calLabels.map(fmtDate),
    datasets: [
      {
        label: 'Calories',
        data: PAGE.calValues,
        borderColor: 'transparent',
        pointBackgroundColor: cssVar('--danger', 0.4),
        pointBorderColor: 'transparent',
        pointRadius: 3,
        fill: false,
        tension: 0,
      },
      {
        label: '20-activity avg',
        data: PAGE.calRolling,
        borderColor: RED,
        borderWidth: 2,
        pointRadius: 0,
        fill: false,
        tension: 0.4,
      }
    ]
  },
  options: {
    animation: false,
    plugins: {
      legend: { display: true, labels: { color: TICK_COLOR, boxWidth: 12 } },
      tooltip: { mode: 'index', intersect: false }
    },
    scales: scalesXY('kcal')
  }
});

// ── Histogram ────────────────────────────────────────────────────
new Chart(document.getElementById('histChart'), {
  type: 'bar',
  data: {
    labels: PAGE.histLabels,
    datasets: [{
      data: PAGE.histValues,
      backgroundColor: cssVar('--c-sky', 0.7),
      borderColor: BLUE,
      borderWidth: 1,
      borderRadius: 3,
    }]
  },
  options: {
    animation: false,
    plugins: { ...noLegend(), tooltip: { callbacks: { label: ctx => `${ctx.parsed.y} activities` } } },
    scales: scalesXY('activities')
  }
});

// ── Day of week ──────────────────────────────────────────────────
new Chart(document.getElementById('dowChart'), {
  type: 'bar',
  data: {
    labels: PAGE.dowLabels,
    datasets: [{
      data: PAGE.dowValues,
      backgroundColor: cssVar('--c-purple', 0.7),
      borderColor: PURPLE,
      borderWidth: 1,
      borderRadius: 3,
    }]
  },
  options: {
    animation: false,
    plugins: { ...noLegend(), tooltip: { callbacks: { label: ctx => `${ctx.parsed.y} activities` } } },
    scales: scalesXY('activities')
  }
});

// ── Calendar heatmap ─────────────────────────────────────────────
(function () {
  const heatmap  = PAGE.heatmap;
  const MONTHS   = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
  const WEEK_START = ((PAGE.weekStart || 0) + 1) % 7;                     // the rider's first day (services/periods: 0 Monday) as getDay() (0 Sunday)
  const DAY_NAMES = Array.from({length: 7}, (_, i) => { const d = (WEEK_START + i) % 7; return [1, 3, 5].includes(d) ? ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'][d] : ''; });   // Mon, Wed and Fri, wherever they fall
  const today    = new Date();
  today.setHours(0, 0, 0, 0);

  const STEPS = PAGE.heatSteps, HEAT_UNIT = PAGE.heatUnit;      // in the unit shown: distance for one group of sports, else minutes
  const HEAT = ['--heat-0', '--heat-1', '--heat-2', '--heat-3', '--heat-4'].map(v => 'var(' + v + ')');     // cell backgrounds: follow the scheme
  function heatColor(v) {
    if (v <= 0)        return HEAT[0];
    if (v < STEPS[0])  return HEAT[1];
    if (v < STEPS[1])  return HEAT[2];
    if (v < STEPS[2])  return HEAT[3];
    return HEAT[4];
  }

  // Derive year range from actual data
  const dataYears = [...new Set(Object.keys(heatmap).map(d => parseInt(d.slice(0, 4))))].sort();
  const minYear   = dataYears[0] || today.getFullYear();
  const maxYear   = today.getFullYear();

  // Populate dropdowns
  const fromSel = document.getElementById('heatFrom');
  const toSel   = document.getElementById('heatTo');
  for (let y = minYear; y <= maxYear; y++) {
    fromSel.add(new Option(y, y));
    toSel.add(new Option(y, y));
  }
  // Default: last 3 years
  fromSel.value = Math.max(minYear, maxYear - 2);
  toSel.value   = maxYear;

  // One continuous calendar (a column per week, a row per weekday), the same for any span. Cells keep a fixed size and never shrink, so a long span scrolls
  // sideways instead of being squashed; it opens scrolled to the most recent end.
  const CELL = 12, GAP = 3, STEP = CELL + GAP;
  const ymd = d => d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0');   // local date: toISOString() (UTC) shifts local-midnight cells a day in summer time

  window.renderHeatmap = function () {
    let fromYear = parseInt(fromSel.value), toYear = parseInt(toSel.value);
    if (fromYear > toYear) { const t = fromYear; fromYear = toYear; toYear = t; }
    const rangeEnd = new Date(Math.min(new Date(toYear, 11, 31), today));
    const jan1  = new Date(fromYear, 0, 1);
    const start = new Date(jan1);
    start.setDate(jan1.getDate() - (jan1.getDay() - WEEK_START + 7) % 7); // back to the first day of the week on or before 1 Jan
    const weeks = Math.ceil((rangeEnd - start) / (7 * 864e5)) + 1;

    const container = document.getElementById('heatmapContainer');
    container.innerHTML = '';

    const wrap = document.createElement('div');
    wrap.className = 'heatmap-wrap';
    wrap.style.cssText = 'overflow-x:auto; padding-bottom:0.5rem;';

    const inner = document.createElement('div');
    inner.style.cssText = 'display:flex; flex-direction:column; width:max-content;';

    // month labels (the year is shown on each January)
    const monthRow = document.createElement('div');
    monthRow.style.cssText = 'position:relative; height:16px; margin-left:28px; width:' + (weeks * STEP) + 'px;';
    let lastMonth = -1;
    for (let w = 0; w < weeks; w++) {
      const d = new Date(start); d.setDate(start.getDate() + w * 7);
      const mo = d.getMonth();
      if (mo !== lastMonth && d <= rangeEnd) {
        const lbl = document.createElement('div');
        lbl.style.cssText = 'position:absolute; top:0; font-size:10px; color:var(--text-muted); white-space:nowrap; left:' + (w * STEP) + 'px;';
        lbl.textContent = mo === 0 ? `${MONTHS[mo]} ${d.getFullYear()}` : MONTHS[mo];
        monthRow.appendChild(lbl);
        lastMonth = mo;
      }
    }

    const row = document.createElement('div');
    row.style.display = 'flex';
    const dayCol = document.createElement('div');
    dayCol.style.cssText = 'width:28px; flex-shrink:0; display:flex; flex-direction:column; gap:' + GAP + 'px; position:sticky; left:0; z-index:1; background:var(--card-bg);';
    DAY_NAMES.forEach(name => {
      const lbl = document.createElement('div');
      lbl.style.cssText = 'height:' + CELL + 'px; font-size:9px; color:var(--text-muted); line-height:' + CELL + 'px;';
      lbl.textContent = name;
      dayCol.appendChild(lbl);
    });
    row.appendChild(dayCol);

    const grid = document.createElement('div');
    grid.style.cssText = 'display:flex; gap:' + GAP + 'px; flex-shrink:0;';
    for (let w = 0; w < weeks; w++) {
      const col = document.createElement('div');
      col.style.cssText = 'display:flex; flex-direction:column; gap:' + GAP + 'px; flex-shrink:0;';
      for (let d = 0; d < 7; d++) {
        const cd = new Date(start); cd.setDate(start.getDate() + w * 7 + d);
        const c = document.createElement('div');
        c.style.cssText = 'width:' + CELL + 'px; height:' + CELL + 'px; border-radius:2px; flex-shrink:0;';
        if (cd > rangeEnd || cd > today || cd.getFullYear() < fromYear) {
          c.style.background = 'transparent';
        } else {
          const ds = ymd(cd), mi = heatmap[ds] || 0;
          c.style.background = heatColor(mi);
          c.title = mi > 0 ? `${fmtDate(ds)}: ${HEAT_UNIT === 'min' ? mi + ' min' : mi.toFixed(1) + ' ' + HEAT_UNIT}` : fmtDate(ds);
        }
        col.appendChild(c);
      }
      grid.appendChild(col);
    }
    row.appendChild(grid);
    inner.appendChild(monthRow);
    inner.appendChild(row);
    wrap.appendChild(inner);
    container.appendChild(wrap);
    wrap.scrollLeft = wrap.scrollWidth;                                    // open at the most recent end
    const legend = document.getElementById('heatLegendNote');
    if (legend) legend.textContent = 'Each square is a day (' + (HEAT_UNIT === 'min' ? 'minutes of activity' : UNITS.distWord) + '). Scroll sideways for earlier years.';
  };

  renderHeatmap();
})();

if (PAGE.wxTempX.length) {
  // ── Weather scatter: speed vs temperature ─────────────────────────
  (function() {
    const tempX    = PAGE.wxTempX;
    const tempY    = PAGE.wxTempY;
    const seasons  = PAGE.wxTempSeason;
    const tempIds  = PAGE.wxTempIds;

    const palette = {
      Winter: cssVar('--c-blue', 0.55),
      Spring: cssVar('--c-green', 0.55),
      Summer: cssVar('--c-amber', 0.55),
      Autumn: cssVar('--c-red', 0.55),
    };
    const datasets = {};
    for (let i = 0; i < tempX.length; i++) {
      const s = seasons[i];
      if (!datasets[s]) datasets[s] = { label: s, data: [], backgroundColor: palette[s], pointRadius: 3, pointHoverRadius: 5 };
      datasets[s].data.push({ x: tempX[i], y: tempY[i], id: tempIds[i] });
    }

    new Chart(document.getElementById('wxTempChart'), {
      type: 'scatter',
      data: { datasets: Object.values(datasets) },
      options: {
        animation: false,
        onClick(evt, elements) {
          if (elements.length) {
            const el = elements[0];
            const pt = this.data.datasets[el.datasetIndex].data[el.index];
            if (pt.id) window.location = '/activities/' + pt.id;
          }
        },
        plugins: { legend: { labels: { color: cssVar('--text-soft'), boxWidth: 10, font: { size: 11 } } } },
        scales: {
          x: { title: { display: true, text: 'Temperature (' + PAGE.temp + ')', color: cssVar('--text-muted') },
               ticks: { color: cssVar('--text-muted') }, grid: { color: cssVar('--border') } },
          y: { title: { display: true, text: 'Avg Speed (' + UNITS.speed + ')', color: cssVar('--text-muted') },
               ticks: { color: cssVar('--text-muted') }, grid: { color: cssVar('--border') } },
        }
      }
    });
    document.getElementById('wxTempChart').style.cursor = 'pointer';
  })();

  // ── Weather scatter: speed vs wind ────────────────────────────────
  (function() {
    const windX   = PAGE.wxWindX;
    const windY   = PAGE.wxWindY;
    const rels    = PAGE.wxWindRel;
    const windIds = PAGE.wxWindIds;

    const palette = {
      headwind:   cssVar('--danger', 0.6),
      tailwind:   cssVar('--c-green', 0.6),
      crosswind:  cssVar('--c-amber', 0.6),
      calm:       cssVar('--c-blue', 0.6),
      mixed:      cssVar('--c-grey', 0.6),
    };
    const labels = { headwind: 'Headwind', tailwind: 'Tailwind', crosswind: 'Crosswind', calm: 'Calm', mixed: 'Mixed (loop)' };
    const datasets = {};
    for (let i = 0; i < windX.length; i++) {
      const r = rels[i] || 'calm';
      if (!datasets[r]) datasets[r] = { label: labels[r] || r, data: [], backgroundColor: palette[r] || cssVar('--c-grey', 0.5), pointRadius: 3, pointHoverRadius: 5 };
      datasets[r].data.push({ x: windX[i], y: windY[i], id: windIds[i] });
    }

    new Chart(document.getElementById('wxWindChart'), {
      type: 'scatter',
      data: { datasets: Object.values(datasets) },
      options: {
        animation: false,
        onClick(evt, elements) {
          if (elements.length) {
            const el = elements[0];
            const pt = this.data.datasets[el.datasetIndex].data[el.index];
            if (pt.id) window.location = '/activities/' + pt.id;
          }
        },
        plugins: { legend: { labels: { color: cssVar('--text-soft'), boxWidth: 10, font: { size: 11 } } } },
        scales: {
          x: { title: { display: true, text: 'Wind Speed (' + UNITS.speed + ')', color: cssVar('--text-muted') },
               ticks: { color: cssVar('--text-muted') }, grid: { color: cssVar('--border') } },
          y: { title: { display: true, text: 'Avg Speed (' + UNITS.speed + ')', color: cssVar('--text-muted') },
               ticks: { color: cssVar('--text-muted') }, grid: { color: cssVar('--border') } },
        }
      }
    });
    document.getElementById('wxWindChart').style.cursor = 'pointer';
  })();

  // ── Weather bar: avg speed by condition ───────────────────────────
  (function() {
    const labels = PAGE.wxCondLabels;
    const avgs   = PAGE.wxCondAvgs;
    const counts = PAGE.wxCondCounts;

    const condColors = {
      Clear:  cssVar('--c-amber', 0.8),
      Cloudy: cssVar('--c-blue', 0.8),
      Fog:    cssVar('--c-grey', 0.8),
      Rain:   cssVar('--c-blue', 0.55),
      Snow:   cssVar('--text-soft', 0.8),
      Storm:  cssVar('--danger', 0.8),
    };

    new Chart(document.getElementById('wxCondChart'), {
      type: 'bar',
      data: {
        labels: labels.map((l, i) => l + ' (' + counts[i] + ')'),
        datasets: [{
          label: 'Avg Speed (' + UNITS.speed + ')',
          data: avgs,
          backgroundColor: labels.map(l => condColors[l] || cssVar('--c-blue', 0.7)),
          borderRadius: 4,
          yAxisID: 'y',
        }, {
          type: 'line',
          label: 'Rides',
          data: counts,
          yAxisID: 'y2',
          showLine: false,
          pointStyle: 'rectRot',
          pointRadius: 7,
          pointBackgroundColor: cssVar('--accent'),
          pointBorderColor: cssVar('--text-strong'),
        }]
      },
      options: {
        animation: false,
        plugins: {
          legend: { display: true, labels: { color: cssVar('--text-soft') } },
          tooltip: { callbacks: { afterLabel: (ctx) => ctx.datasetIndex === 0 ? `${counts[ctx.dataIndex]} rides` : '' } }
        },
        scales: {
          x: { ticks: { color: cssVar('--text-soft') }, grid: { color: cssVar('--border') } },
          y: { beginAtZero: true, title: { display: true, text: 'Avg Speed (' + UNITS.speed + ')', color: cssVar('--text-muted') },
               ticks: { color: cssVar('--text-muted') }, grid: { color: cssVar('--border') } },
          y2: { beginAtZero: true, position: 'right', title: { display: true, text: 'Rides', color: cssVar('--accent') },
                ticks: { color: cssVar('--accent') }, grid: { drawOnChartArea: false } },
        }
      }
    });
  })();
}
function stormPick(id, what) {
  fetch('/activities/' + id + '/weather', { method: 'POST', body: new URLSearchParams({ condition: what }) })
    .then(function(r) { return r.json(); })
    .then(function(d) {
      if (d.error) { alert('Could not save: ' + d.error); return; }
      var row = document.getElementById('storm_' + id);
      if (row) row.innerHTML = '<span style="color:var(--text-muted);">' + (what === 'Storm' ? 'Counted as a storm ride. Refresh to update the chart.' : 'Taken back to ' + (d.condition || 'its own condition') + '.') + '</span>';
    });
}

function fogPick(id, what) {
  fetch('/activities/' + id + '/weather', { method: 'POST', body: new URLSearchParams({ condition: what }) })
    .then(function(r) { return r.json(); })
    .then(function(d) {
      if (d.error) { alert('Could not save: ' + d.error); return; }
      var row = document.getElementById('fog_' + id);
      if (row) row.innerHTML = '<span style="color:var(--text-muted);">' + (what === 'Fog' ? 'Marked as fog. Refresh to update the chart.' : 'Kept as it was.') + '</span>';
    });
}
