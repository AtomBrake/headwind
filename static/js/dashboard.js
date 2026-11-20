// Time-of-day greeting (client-side, avoids a server round trip for something this trivial)
(function () {
  var h = new Date().getHours();
  var word = h < 12 ? 'Good morning' : (h < 18 ? 'Good afternoon' : 'Good evening');
  var el = document.getElementById('greetingText');
  if (el) el.textContent = word + ', ' + el.dataset.name;
})();

const DASH          = JSON.parse(document.getElementById('dashboardData').textContent);
const weeklyData    = DASH.weekly;
const yearSpeedData = DASH.yearSpeed;
const riderQuery    = DASH.riderQuery;
const chartGroups   = DASH.chartGroups;   // one stack per stat group (rides, on foot, swims, ...), services/sport_filter.chart_groups
const rateStyle     = DASH.rateStyle;     // 'speed', 'pace' or 'swim' when the sports left in share a distance, else null

// A bar opens that week's activities (the search below already filters by date); a point on the speed line opens that activity.
const weekLinks = weeklyData.map(w => '/dashboard?' + (riderQuery ? riderQuery + '&' : '') + 'from=' + w.from + '&to=' + w.to + '#ride-history');

const TICK_COLOR = cssVar('--text-muted');
const GRID_COLOR = cssVar('--border');

function baseScales(yUnit, opts) {
  opts = opts || {};
  return {
    x: { stacked: !!opts.stacked, ticks: { color: TICK_COLOR, font: { size: 11 } }, grid: { display: false } },
    y: { stacked: !!opts.stacked, reverse: !!opts.reverse, beginAtZero: !opts.reverse, grid: { color: GRID_COLOR },
         ticks: { color: TICK_COLOR, font: { size: 11 }, callback: opts.tick || (v => v + (yUnit ? (' ' + yUnit) : '')) } }
  };
}

// Weekly bars, one stack per group: a week of runs and a ride shows both, each in its own colour. With one group it is a plain bar.
function weekly(label, value, fmt) {
  return { type: 'bar', label, sub: 'Last 12 weeks', labels: weeklyData.map(w => w.label), links: weekLinks, hint: 'Click to see this week\'s activities', stacked: true, fmt,
           datasets: chartGroups.map(g => ({ label: g.label, color: g.color, data: weeklyData.map(w => value(w.by[g.key] || {})) })) };
}
const onePlace = v => +(v || 0).toFixed(1);
const hm = h => { const mins = Math.round(h * 60); return Math.floor(mins / 60) + 'h ' + String(mins % 60).padStart(2, '0') + 'm'; };
const METRICS = {
  distance:  weekly(UNITS.dist, t => onePlace(UNITS.toDist(t.dist_m)), v => v.toFixed(1) + ' ' + UNITS.dist),
  elevation: weekly(UNITS.elev, t => Math.round(UNITS.toElev(t.elev_m)), v => Math.round(v).toLocaleString() + ' ' + UNITS.elev),
  calories:  weekly('kcal', t => t.cals || 0, v => Math.round(v).toLocaleString() + ' kcal'),
  time:      weekly('h', t => +((t.secs || 0) / 3600).toFixed(2), hm),
};
if (rateStyle) {
  const pace = rateStyle !== 'speed', unit = pace ? UNITS.paceLabel(rateStyle) : UNITS.speed;
  METRICS.speed = { type: 'line', label: unit, sub: 'This year, per activity' + (pace ? ' (faster is higher)' : ''), labels: yearSpeedData.map(r => fmtDate(r.d)),
                    names: yearSpeedData.map(r => r.name), links: yearSpeedData.map(r => '/activities/' + encodeURIComponent(r.id)), hint: 'Click to open this activity',
                    reverse: pace, fmt: v => (pace ? UNITS.fmtMinSec(v) : v.toFixed(1)) + ' ' + unit, tick: pace ? (v => UNITS.fmtMinSec(v)) : null,
                    datasets: [{ label: unit, color: chartGroups[0] ? chartGroups[0].color : '--accent',
                                 data: yearSpeedData.map(r => pace ? Math.round(UNITS.toPace(r.mps, rateStyle)) : onePlace(UNITS.toSpeed(r.mps))) }] };
}

let mainChart = null;
function renderMainChart(metric) {
  const m = METRICS[metric];
  document.getElementById('chartSubtitle').textContent = m.sub;
  if (mainChart) mainChart.destroy();
  const isBar = m.type === 'bar';
  const several = m.datasets.length > 1;
  mainChart = new Chart(document.getElementById('mainChart'), {
    type: m.type,
    data: {
      labels: m.labels,
      datasets: m.datasets.map(d => ({
        label: d.label,
        data: d.data,
        backgroundColor: isBar ? cssVar(d.color, 0.75) : 'transparent',
        borderColor: cssVar(d.color),
        borderWidth: isBar ? 1 : 2,
        borderRadius: isBar ? 3 : 0,
        pointRadius: isBar ? 0 : 3,
        pointHoverRadius: isBar ? 0 : 5,
        pointBackgroundColor: cssVar(d.color),
        fill: false,
        tension: 0.3,
      }))
    },
    options: {
      animation: false,
      maintainAspectRatio: false,
      interaction: isBar ? { mode: 'index', intersect: false } : { mode: 'nearest', intersect: true },
      onClick: (evt, els) => { if (els.length) location.href = m.links[els[0].index]; },
      onHover: (evt, els) => { evt.native.target.style.cursor = els.length ? 'pointer' : 'default'; },
      plugins: {
        legend: { display: several, labels: { color: TICK_COLOR, boxWidth: 12 } },
        tooltip: {
          filter: ctx => !several || ctx.parsed.y > 0,
          callbacks: {
            title: ctx => (m.names ? m.names[ctx[0].dataIndex] : ctx[0].label),
            label: ctx => (several ? ctx.dataset.label + ': ' : '') + m.fmt(ctx.parsed.y),
            footer: ctx => (several && ctx.length > 1 ? 'Total ' + m.fmt(ctx.reduce((t, c) => t + c.parsed.y, 0)) + '\n' : '') + m.hint,
          }
        }
      },
      scales: baseScales(m.label, { stacked: m.stacked, reverse: m.reverse, tick: m.tick }),
    }
  });
}

renderMainChart(document.querySelector('#chartTabs .seg-btn.active').dataset.metric);
document.getElementById('chartTabs').addEventListener('click', function (e) {
  const btn = e.target.closest('.seg-btn');
  if (!btn) return;
  this.querySelectorAll('.seg-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  renderMainChart(btn.dataset.metric);
});
