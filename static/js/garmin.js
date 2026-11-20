const PAGE = JSON.parse(document.getElementById('recoveryData').textContent);
// ── Intraday charts ───────────────────────────────────────────
const hrIntraday = PAGE.hrIntraday;
const bbIntraday = PAGE.bbIntraday;

function tsToTime(ms) {
  const d = new Date(ms);
  return d.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' });
}

// Thin the labels so the X axis isn't solid text — show one every N points
function sparseLabels(data, every) {
  return data.map((_, i) => i % every === 0 ? tsToTime(data[i][0]) : '');
}

const intradayOpts = (yMin, yMax, yCallback) => ({
  maintainAspectRatio: false,
  animation: false,
  plugins: {
    legend: { display: false },
    tooltip: {
      callbacks: {
        label: ctx => yCallback(ctx.raw),
        title: ctx => tsToTime(ctx[0].dataset.data[ctx[0].dataIndex][0]),
      },
      mode: 'index',
      intersect: false,
    },
  },
  scales: {
    x: {
      ticks: { color: cssVar('--text-muted'), font: { size: 10 }, maxRotation: 0, autoSkip: false },
      grid: { display: false },
    },
    y: {
      min: yMin, max: yMax,
      ticks: { color: cssVar('--text-muted'), font: { size: 11 }, callback: v => yCallback(v) },
      grid: { color: cssVar('--border') },
    },
  },
});

if (hrIntraday.length > 0) {
  const every = Math.max(1, Math.round(hrIntraday.length / 12));
  new Chart(document.getElementById('hrIntradayChart'), {
    type: 'line',
    data: {
      labels: sparseLabels(hrIntraday, every),
      datasets: [{
        data: hrIntraday.map(p => p[1]),
        borderColor: cssVar('--danger'),
        backgroundColor: cssVar('--danger', 0.12),
        borderWidth: 1.5,
        pointRadius: 0,
        fill: true,
        tension: 0.3,
      }],
    },
    options: intradayOpts(30, 200, v => v + ' bpm'),
  });
}

if (bbIntraday.length > 0) {
  const every = Math.max(1, Math.round(bbIntraday.length / 12));
  const bbValues = bbIntraday.map(p => p[1]);
  new Chart(document.getElementById('bbIntradayChart'), {
    type: 'line',
    data: {
      labels: sparseLabels(bbIntraday, every),
      datasets: [{
        data: bbValues,
        borderColor: cssVar('--success'),
        backgroundColor: bbValues.map(v =>
          v < 25 ? cssVar('--danger', 0.15) :
          v < 50 ? cssVar('--warning', 0.15) :
          cssVar('--success', 0.15)
        ),
        borderWidth: 1.5,
        pointRadius: 0,
        fill: true,
        tension: 0.3,
      }],
    },
    options: intradayOpts(0, 100, v => v + '%'),
  });
}

// ── Multi-day trend charts ─────────────────────────────────────
const labels     = PAGE.labels;
const rhrData    = PAGE.rhr;
const batData    = PAGE.battery;
const sleepData  = PAGE.sleep;
const stageData  = PAGE.stages;
const stepsData  = PAGE.steps;
const stressData = PAGE.stress;
const rideData   = PAGE.hasRide;

const shortLabels = labels.map(d => {
  const dt = new Date(d + 'T00:00:00');
  return dt.toLocaleDateString('en-GB', { day: 'numeric', month: 'short' });
});

const baseOpts = (yLabel, yCallback) => ({
  maintainAspectRatio: false,
  plugins: {
    legend: { display: false },
    tooltip: { callbacks: { label: ctx => ctx.raw !== null ? yCallback(ctx.raw) : 'no data' } },
  },
  scales: {
    x: {
      ticks: { color: cssVar('--text-muted'), font: { size: 10 }, maxTicksLimit: 10 },
      grid: { display: false },
    },
    y: {
      ticks: { color: cssVar('--text-muted'), font: { size: 11 }, callback: v => yCallback(v) },
      grid: { color: cssVar('--border') },
    },
    yRide: {
      display: false,
      min: 0, max: 2,
    },
  },
});

const rideDataset = {
  data: rideData,
  type: 'scatter',
  yAxisID: 'yRide',
  pointRadius: 5,
  pointHoverRadius: 6,
  pointStyle: 'triangle',
  backgroundColor: cssVar('--accent', 0.7),
  borderColor: cssVar('--accent', 0.9),
  label: 'Rode',
};

// Resting HR
const rhrEl = document.getElementById('rhrChart');
if (rhrEl && rhrData.some(v => v !== null)) {
  new Chart(rhrEl, {
    type: 'line',
    data: {
      labels: shortLabels,
      datasets: [
        {
          data: rhrData,
          borderColor: cssVar('--accent'),
          backgroundColor: cssVar('--accent', 0.08),
          borderWidth: 2,
          pointRadius: rhrData.map(v => v !== null ? 4 : 0),
          pointHoverRadius: 6,
          pointBackgroundColor: cssVar('--accent'),
          fill: true,
          tension: 0.3,
          spanGaps: false,
        },
        { ...rideDataset },
      ],
    },
    options: {
      ...baseOpts('bpm', v => v + ' bpm'),
      scales: {
        ...baseOpts('bpm', v => v + ' bpm').scales,
        y: { ...baseOpts('bpm', v => v + ' bpm').scales.y, suggestedMin: 40, suggestedMax: 80 },
      },
    },
  });
}

// Body Battery
const batEl = document.getElementById('batteryChart');
if (batEl && batData.some(v => v !== null)) {
  new Chart(batEl, {
    type: 'line',
    data: {
      labels: shortLabels,
      datasets: [
        {
          data: batData,
          borderColor: cssVar('--success'),
          backgroundColor: cssVar('--success', 0.08),
          borderWidth: 2,
          pointRadius: batData.map(v => v !== null ? 4 : 0),
          pointHoverRadius: 6,
          pointBackgroundColor: cssVar('--success'),
          fill: true,
          tension: 0.3,
          spanGaps: false,
        },
        { ...rideDataset },
      ],
    },
    options: {
      ...baseOpts('%', v => v + '%'),
      scales: {
        ...baseOpts('%', v => v + '%').scales,
        y: { ...baseOpts('%', v => v + '%').scales.y, min: 0, max: 100 },
      },
    },
  });
}

// Sleep: stacked by stage on nights that have them (deep, light, REM, then time awake on top), one bar of the hours on nights that don't
const sleepEl = document.getElementById('sleepChart');
if (sleepEl && sleepData.some(v => v !== null)) {
  const sleepColour = (v, alpha) => v === null ? 'transparent' :
    v < 6 ? cssVar('--danger', alpha) : v < 7 ? cssVar('--warning', alpha) : cssVar('--c-purple', alpha);
  const unstaged = stageData ? sleepData.map((v, i) => stageData.deep[i] === null ? v : null) : sleepData;
  const stage = (label, key, colour, alpha = 0.7) => ({
    label, data: stageData[key], backgroundColor: cssVar(colour, alpha), borderColor: cssVar(colour), borderWidth: 1, stack: 'night',
  });
  const datasets = [{
    label: 'Asleep', data: unstaged, stack: 'night',
    backgroundColor: unstaged.map(v => sleepColour(v, 0.6)), borderColor: unstaged.map(v => sleepColour(v)), borderWidth: 1, borderRadius: 3,
  }];
  if (stageData) {
    datasets.push(stage('Deep', 'deep', '--c-indigo'), stage('Light', 'light', '--c-blue'), stage('REM', 'rem', '--c-sky'),
                  stage('Awake', 'awake', '--c-orange', 0.35));
  }
  const fmtH = h => { const m = Math.round(h * 60); return m < 60 ? m + ' min' : Math.floor(m / 60) + 'h ' + String(m % 60).padStart(2, '0'); };
  new Chart(sleepEl, {
    type: 'bar',
    data: { labels: shortLabels, datasets },
    options: {
      maintainAspectRatio: false,
      interaction: stageData ? { mode: 'index', intersect: false } : undefined,     // the whole night in one tooltip
      plugins: {
        legend: stageData ? { display: true, position: 'bottom', labels: { color: cssVar('--text-muted'), boxWidth: 10, font: { size: 10 },
                                                                          filter: item => item.text !== 'Asleep' } }
                          : { display: false },
        tooltip: {
          filter: ctx => ctx.raw !== null,
          callbacks: {
            label: ctx => stageData ? ctx.dataset.label + ': ' + fmtH(ctx.raw) : ctx.raw + 'h',
            footer: items => stageData && items.length && stageData.deep[items[0].dataIndex] !== null
              ? 'Asleep ' + fmtH(sleepData[items[0].dataIndex]) : '',
          },
        },
      },
      scales: {
        x: { stacked: true, ticks: { color: cssVar('--text-muted'), font: { size: 10 }, maxTicksLimit: 10 }, grid: { display: false } },
        y: {
          stacked: true,
          ticks: { color: cssVar('--text-muted'), font: { size: 11 }, callback: v => v + 'h' },
          grid: { color: cssVar('--border') },
          beginAtZero: true,
          suggestedMax: 10,
        },
      },
    },
  });
}

// Steps
const stepsEl = document.getElementById('stepsChart');
if (stepsEl && stepsData.some(v => v !== null)) {
  new Chart(stepsEl, {
    type: 'bar',
    data: {
      labels: shortLabels,
      datasets: [
        {
          data: stepsData,
          backgroundColor: cssVar('--c-indigo', 0.5),
          borderColor: cssVar('--c-indigo'),
          borderWidth: 1,
          borderRadius: 3,
        },
        { ...rideDataset },
      ],
    },
    options: {
      ...baseOpts('steps', v => v.toLocaleString()),
      scales: {
        ...baseOpts('steps', v => v.toLocaleString()).scales,
        y: { ...baseOpts('steps', v => v.toLocaleString()).scales.y, beginAtZero: true },
      },
    },
  });
}

// Stress
const stressEl = document.getElementById('stressChart');
if (stressEl && stressData.some(v => v !== null)) {
  new Chart(stressEl, {
    type: 'line',
    data: {
      labels: shortLabels,
      datasets: [
        {
          data: stressData,
          borderColor: cssVar('--warning'),
          backgroundColor: cssVar('--warning', 0.08),
          borderWidth: 2,
          pointRadius: stressData.map(v => v !== null ? 4 : 0),
          pointHoverRadius: 6,
          pointBackgroundColor: stressData.map(v =>
            v === null ? 'transparent' : v > 60 ? cssVar('--danger') : v > 35 ? cssVar('--warning') : cssVar('--success')
          ),
          fill: true,
          tension: 0.3,
          spanGaps: false,
        },
        { ...rideDataset },
      ],
    },
    options: {
      ...baseOpts('stress', v => String(v)),
      scales: {
        ...baseOpts('stress', v => String(v)).scales,
        y: { ...baseOpts('stress', v => String(v)).scales.y, min: 0, max: 100 },
      },
    },
  });
}

function doSync() {
  const btn = document.getElementById('syncBtn');
  const status = document.getElementById('syncStatus');
  btn.disabled = true;
  status.textContent = 'Syncing…';
  fetch('/garmin/sync', { method: 'POST' })
    .then(r => r.json())
    .then(d => {
      if (d.error) {
        status.textContent = 'Error: ' + d.error;
        status.style.color = 'var(--danger)';
        btn.disabled = false;
      } else {
        status.textContent = '✓ Done';
        status.style.color = 'var(--success)';
        setTimeout(() => location.reload(), 800);
      }
    })
    .catch(() => {
      status.textContent = 'Failed';
      status.style.color = 'var(--danger)';
      btn.disabled = false;
    });
}
