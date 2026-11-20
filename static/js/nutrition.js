// ── Config ────────────────────────────────────────────────────────────
const MEALS = [
  { key:'breakfast', label:'Breakfast' },
  { key:'lunch',     label:'Lunch' },
  { key:'dinner',    label:'Tea / Dinner' },
  { key:'snacks',    label:'Snacks' },
  { key:'ride_fuel', label:'Ride Fuel' },
  { key:'recovery',  label:'Recovery' },
];

function mealTypeOptions(selected) {
  return MEALS.map(m =>
    `<option value="${m.key}"${m.key===selected?' selected':''}>${m.label}</option>`
  ).join('') + `<option value="uncategorised"${'uncategorised'===selected?' selected':''}>Uncategorised</option>`;
}

function guessMealType() {
  const h = new Date().getHours();
  if (h < 10) return 'breakfast';
  if (h < 14) return 'lunch';
  if (h < 17) return 'snacks';
  if (h < 21) return 'dinner';
  return 'snacks';
}

// ── State ─────────────────────────────────────────────────────────────
let currentDate = new Date(); currentDate.setHours(12,0,0,0);
let currentMealType = guessMealType();
let scanner = null;
let lastWaterId = null;
let goals = {};
let savedMeals = [];
let recentFoods = [];
let favourites = [];
let myFoods = [];
let smPendingItems = null;
let pollTimer = null;
let buildMealItems = [];
let weightUnit = 'stlb';
let ffTab = 'recent';
let ffOffset = 0;
let ffHasMore = false;
let ffPickMode = null;          // null | 'buildmeal'
let fdBaseG = null;             // grams the entry's current macros describe, when the entry itself didn't record a weight
let fdContext = null;           // {mode:'per100'|'absolute', item, target:'log'|'editlog'|'buildmeal', entryId, sourceKind}
let manualImageUrl = null;
let mfImageUrl = null;
let editingMyFoodId = null;

// the local calendar date — NOT toISOString(), which is UTC and flips the day for evening/after-midnight users
function localIso(d) { return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0'); }
function isoDate(d) { return localIso(d); }
function yesterday() { const d=new Date(currentDate); d.setDate(d.getDate()-1); return d; }
function fmtDateLabel(d) {
  const today = isoDate(new Date());
  const ds    = isoDate(d);
  if (ds === today) return 'Today';
  const yd = new Date(); yd.setDate(yd.getDate()-1);
  if (ds === isoDate(yd)) return 'Yesterday';
  return d.toLocaleDateString('en-GB', {day:'numeric',month:'short'});
}
// Escapes quotes too: it is used inside attribute values (title="…") as well as text
function escHtml(s) { return String(s||'').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'})[c]); }

// ── Date nav ──────────────────────────────────────────────────────────
document.getElementById('prevDay').addEventListener('click', () => { currentDate.setDate(currentDate.getDate()-1); loadDay(); });
document.getElementById('nextDay').addEventListener('click', () => {
  const tom=new Date(); tom.setDate(tom.getDate()+1); tom.setHours(12,0,0,0);
  if (currentDate < tom) { currentDate.setDate(currentDate.getDate()+1); loadDay(); }
});

// ── Load day ──────────────────────────────────────────────────────────
async function loadDay() {
  clearTimeout(pollTimer);
  document.getElementById('dateLabel').textContent = fmtDateLabel(currentDate);
  const r    = await fetch(`/nutrition/api/day/${isoDate(currentDate)}`);
  const data = await r.json();
  goals = data.goals || {};
  lastWaterId = data.last_water_id || null;
  renderAll(data);
  pollTimer = setTimeout(loadDay, 5*60*1000);
}

// ── Render ────────────────────────────────────────────────────────────
function renderAll(data) {
  lastData = data;
  const entries = data.entries || [];
  const waterMl = data.water_ml || 0;
  const eaten   = entries.reduce((s,e) => s+(e.calories||0), 0);
  const protein = entries.reduce((s,e) => s+(e.protein||0), 0);
  const carbs   = entries.reduce((s,e) => s+(e.carbs||0), 0);
  const fat     = entries.reduce((s,e) => s+(e.fat||0), 0);
  const burned = data.burned || 0;

  renderWeightCard(data.weight);

  // Calories
  document.getElementById('calEaten').textContent = Math.round(eaten).toLocaleString();
  if (goals.cal) {
    document.getElementById('calGoalSub').textContent = `of ${goals.cal.toLocaleString()} kcal goal`;
    const rem = Math.max(0, goals.cal - eaten);
    document.getElementById('calRemaining').textContent = Math.round(rem).toLocaleString();
    document.getElementById('calRemainingCell').style.display = '';
    renderProg('calProgWrap','calProgFill','calProgPct','calProgRem', eaten, goals.cal, '{v} kcal eaten', '{r} kcal left');
  } else {
    document.getElementById('calGoalSub').textContent = '';
    document.getElementById('calRemainingCell').style.display = 'none';
    document.getElementById('calProgWrap').style.display = 'none';
  }
  if (burned) {
    document.getElementById('calBurned').textContent = '≈ ' + Math.round(burned).toLocaleString();
    document.getElementById('calBurnedLbl').textContent = data.burn_source || 'burned';
    document.getElementById('calBurnedCell').style.display = '';
  } else {
    document.getElementById('calBurnedCell').style.display = 'none';
  }
  const netEl = document.getElementById('netBadge');
  if (burned) {
    const net = eaten - burned;
    netEl.style.display = '';
    netEl.className = 'nu-net ' + (net<0?'deficit':net>0?'surplus':'neutral');
    netEl.textContent = '≈ ' + (net>=0?'+':'') + Math.round(net).toLocaleString() + ' kcal ' + (net<0?'deficit':'surplus') + ' (rough)';
  } else {
    netEl.style.display = 'none';
  }

  // Macros: filling rings (a ring is full when the goal is reached; sugar is a limit, so it turns red when you pass it)
  const fibreTot = entries.reduce((x,e) => x+(e.fibre||0), 0);
  const sugarTot = entries.reduce((x,e) => x+(e.sugar||0), 0);
  renderRing('protein', protein, goals.protein, 'var(--c-yellow)');
  renderRing('carbs',   carbs,   goals.carbs,   'var(--c-sky)');
  renderRing('fat',     fat,     goals.fat,     'var(--c-red)');
  renderRing('fibre',   fibreTot, goals.fibre || 30, 'var(--c-orange)');
  renderRing('sugar',   sugarTot, goals.sugar,  'var(--c-pink)', false);         // total sugar: a reference, never a red limit
  const sugEl = document.getElementById('ringVal_sugar');
  if (sugEl && goals.sugar && sugarTot > goals.sugar) sugEl.innerHTML += '<small class="hint">above reference</small>';
  const al = data.alcohol || {today: 0, week: 0, goal: goals.alcohol_week || 14};
  renderRing('alcohol', al.week, al.goal, 'var(--c-violet)', true, ' u');
  const alEl = document.getElementById('ringVal_alcohol');
  if (alEl && al.today) alEl.innerHTML += `<small style="color:var(--c-violet);">${al.today} today</small>`;

  // Hydration
  document.getElementById('waterTotal').textContent = waterMl.toLocaleString();
  if (goals.water) {
    document.getElementById('waterGoalLbl').textContent = `goal: ${goals.water.toLocaleString()} ml`;
    renderProg('waterProgWrap','waterProgFill','waterProgPct','waterProgRem',waterMl,goals.water,'{v} ml','{r} ml to go');
    document.getElementById('waterProgFill').style.background='var(--c-blue)';
  } else {
    document.getElementById('waterGoalLbl').textContent = '';
    document.getElementById('waterProgWrap').style.display='none';
  }

  // Meal sections
  renderMealSections(entries);
  renderNutriSheet();
}

function renderProg(wrapId, fillId, pctId, remId, val, goal, pctFmt, remFmt) {
  const wrap = document.getElementById(wrapId);
  const fill = document.getElementById(fillId);
  wrap.style.display = '';
  const pct = Math.min(100, (val/goal)*100);
  fill.style.width = pct+'%';
  fill.className = 'nu-prog-fill'+(pct>=100?' over':pct>=85?' nearly':'');
  if (pctId && pctFmt) document.getElementById(pctId).textContent = pctFmt.replace('{v}',Math.round(val).toLocaleString());
  if (remId && remFmt) document.getElementById(remId).textContent = remFmt.replace('{r}',Math.round(Math.max(0,goal-val)).toLocaleString()).replace('{g}',goal.toLocaleString());
}

const RING_C = 2 * Math.PI * 32;
function renderRing(key, val, goal, colour, isLimit, unit) {
  unit = unit || 'g';
  const bar = document.getElementById('ringBar_' + key), txt = document.getElementById('ringVal_' + key);
  if (!bar || !txt) return;
  const frac = goal ? Math.min(1, val / goal) : 0;
  bar.style.strokeDasharray = RING_C;
  bar.style.strokeDashoffset = RING_C * (1 - frac);
  bar.style.stroke = (isLimit && goal && val > goal) ? 'var(--danger)' : colour;
  const n = v => (unit === 'g' ? Math.round(v) : Math.round(v * 10) / 10);
  txt.innerHTML = goal ? `${n(val)}<small>of ${n(goal)}${unit}</small>` : `${n(val)}<small>${unit}</small>`;
}

function renderMacroGoal(goalId, wrapId, fillId, val, goal) {
  const goalEl = document.getElementById(goalId);
  const wrap   = document.getElementById(wrapId);
  if (goal) {
    goalEl.textContent = ` / ${Math.round(goal)}g`;
    wrap.style.display = '';
    const fill = document.getElementById(fillId);
    const pct = Math.min(100, (val/goal)*100);
    fill.style.width = pct+'%';
    fill.className = 'nu-prog-fill'+(pct>=100?' over':pct>=85?' nearly':'');
  } else {
    goalEl.textContent = 'g';
    wrap.style.display = 'none';
  }
}

// ── Meal sections ─────────────────────────────────────────────────────
function renderMealSections(entries) {
  const wrap = document.getElementById('mealSections');
  wrap.innerHTML = '';
  MEALS.forEach(meal => {
    const sEntries = entries.filter(e => (e.mealType||'uncategorised') === meal.key);
    wrap.appendChild(buildMealSection(meal, sEntries));
  });
  // uncategorised catch-all
  const uncat = entries.filter(e => !e.mealType || e.mealType === 'uncategorised');
  if (uncat.length) {
    wrap.appendChild(buildMealSection({key:'uncategorised',label:'Uncategorised'}, uncat));
  }
}

function buildMealSection(meal, entries) {
  const totalKcal = entries.reduce((s,e) => s+(e.calories||0), 0);
  const div = document.createElement('div');
  div.className = 'meal-section';
  div.dataset.meal = meal.key;

  // Nothing logged: one slim row with the add button right there
  if (!entries.length) {
    div.classList.add('empty-meal');
    div.innerHTML = `<div class="meal-header">
      <span class="meal-title" style="color:var(--text-muted); font-weight:500;">${escHtml(meal.label)}</span>
      <button class="btn btn-secondary meal-add" data-click="openFindFood('${meal.key}')">+ Add</button>
    </div>`;
    return div;
  }

  // the meal's macros at a glance, next to its calories
  const mt = k => entries.reduce((x, e) => x + (e[k] || 0), 0);
  const chip = (lbl, v, col) => `<span class="meal-mac" style="color:${col};" title="${lbl === 'S' ? 'Total sugar' : ''}"><b>${Math.round(v)}</b><small>${lbl}</small></span>`;
  const macros = `<div class="meal-macs">${chip('P', mt('protein'), 'var(--c-yellow)')}${chip('C', mt('carbs'), 'var(--c-sky)')}${chip('F', mt('fat'), 'var(--c-red)')}${chip('Fi', mt('fibre'), 'var(--c-orange)')}${chip('S', mt('sugar'), 'var(--c-pink)')}${mt('alcoholUnits') > 0 ? `<span class="meal-mac" style="color:var(--c-violet);"><b>${Math.round(mt('alcoholUnits') * 10) / 10}</b><small>U</small></span>` : ''}</div>`;
  const header = `
    <div class="meal-header">
      <button class="meal-title-btn" data-click="openMealSheet('${meal.key}')">${escHtml(meal.label)}<span class="chev">&rsaquo;</span></button>
      ${macros}
      <div class="meal-total"><b>${Math.round(totalKcal)}</b><small>Total kcal</small></div>
    </div>`;

  const entryRows = entries.map(e => {
    const kcalStr = e.calories ? Math.round(e.calories)+' kcal' : '—';
    const meta = [
      e.servingG   ? Math.round(e.servingG)+'g'      : null,
      e.quantity && e.quantity!==1 ? '×'+e.quantity  : null,
      e.protein    ? 'P'+Math.round(e.protein)+'g'   : null,
      e.carbs      ? 'C'+Math.round(e.carbs)+'g'     : null,
      e.fat        ? 'F'+Math.round(e.fat)+'g'       : null,
      e.sugar      ? 'S'+Math.round(e.sugar)+'g'     : null,
      e.alcoholUnits ? (Math.round(e.alcoholUnits*10)/10)+' units' : null,
      e.source === 'photo_ai' ? '≈ AI estimate' : null,
    ].filter(Boolean).join(' · ');
    return `<div class="meal-entry" data-id="${e.id}">
      ${thumbHtml(e.imageUrl, e.verified, 'entry')}
      <div class="meal-entry-name">
        <div>${escHtml(e.foodName)}</div>
        ${meta?`<div class="meal-entry-meta">${meta}</div>`:''}
      </div>
      <div class="meal-entry-kcal">${kcalStr}</div>
      <button class="btn-del" data-id="${e.id}" aria-label="Delete">&#x2715;</button>
    </div>`;
  }).join('');

  const footerBtns = `
    <button class="btn btn-secondary" data-click="openFindFood('${meal.key}')">+ Add</button>
    <button class="btn btn-secondary" data-click="openSaveAsMeal('${meal.key}')">Save as meal</button>
    <button class="btn btn-secondary" data-click="copyMeal('${meal.key}')" title="Copy from yesterday" style="color:var(--text-muted);">Copy yd</button>`;

  div.innerHTML = header + `
    <div class="meal-body">
      <div class="meal-entries">${entryRows}</div>
      <div class="meal-footer">${footerBtns}</div>
    </div>`;

  // Delete straight away, with an Undo — a mis-tap next to the calories shouldn't cost an entry
  div.querySelectorAll('.btn-del').forEach(btn =>
    btn.addEventListener('click', async (ev) => {
      ev.stopPropagation();
      const e = entries.find(x => x.id === parseInt(btn.dataset.id));
      await fetch(`/nutrition/api/log/${btn.dataset.id}`, {method:'DELETE'});
      loadDay();
      if (e) showUndo(`Deleted ${e.foodName}`, async () => {
        await fetch('/nutrition/api/log', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({
          date: isoDate(currentDate), name: e.foodName, barcode: e.barcode || null, calories: e.calories, protein: e.protein,
          carbs: e.carbs, fat: e.fat, fibre: e.fibre, sugar: e.sugar, alcohol_units: e.alcoholUnits, serving_g: e.servingG, quantity: e.quantity || 1,
          meal_type: e.mealType || 'uncategorised', source: e.source || 'manual', brand: e.brand || null,
          image_url: e.imageUrl || null, nutri_score_grade: e.nutriScoreGrade || null })});
        loadDay();
      });
    })
  );

  // Tap a row to edit it
  div.querySelectorAll('.meal-entry').forEach(row => {
    row.addEventListener('click', (ev) => {
      if (ev.target.closest('.btn-del')) return;
      const entry = entries.find(e => e.id === parseInt(row.dataset.id));
      if (entry) openEntryDetail(entry);
    });
  });

  return div;
}

let snackTimer = null, snackAction = null;
function showUndo(msg, action) {
  snackAction = action;
  document.getElementById('nuSnackMsg').textContent = msg;
  document.getElementById('nuSnack').classList.add('show');
  clearTimeout(snackTimer);
  snackTimer = setTimeout(() => document.getElementById('nuSnack').classList.remove('show'), 6000);
}
document.getElementById('nuSnackUndo').addEventListener('click', async () => {
  document.getElementById('nuSnack').classList.remove('show');
  if (snackAction) { const fn = snackAction; snackAction = null; await fn(); }
});

function toggleSection(header) {
  header.closest('.meal-section').classList.toggle('collapsed');
}


// ── Meal / day nutrition sheet ────────────────────────────────────────
let lastData = null;       // most recent /api/day payload
let nutriView = null;      // {kind:'meal', key} | {kind:'day'} while the sheet is open
const NN_COLORS = { protein:'var(--c-yellow)', fibre:'var(--c-orange)', carbs:'var(--c-sky)', fat:'var(--c-red)', sugar:'var(--c-pink)' };

function sumEntries(list) {
  const s = { calories:0, protein:0, fibre:0, carbs:0, fat:0, sugar:0 };
  list.forEach(e => { for (const k in s) s[k] += (e[k] || 0); });
  return s;
}
function nnTiles(t, goalsMap) {
  const fmt = (v, u) => v ? (Math.round(v * 10) / 10) + u : '0' + u;
  const tile = (cls, lbl, val, goal) => `<div class="fd-macro-tile"><div class="fd-macro-lbl ${cls}">${lbl}</div>
      <div class="fd-macro-val">${val}</div>${goal ? `<div style="font-size:0.65rem;color:var(--text-muted);margin-top:0.15rem;">of ${goal}</div>` : ''}</div>`;
  const g = goalsMap || {};
  return `<div class="fd-macro-grid nn-tiles">
    ${tile('cal', 'Calories', Math.round(t.calories), g.cal ? Math.round(g.cal) : '')}
    ${tile('protein', 'Protein', fmt(t.protein, 'g'), g.protein ? g.protein + 'g' : '')}
    ${tile('fibre', 'Fibre', fmt(t.fibre, 'g'), '')}
    ${tile('carbs', 'Carbs', fmt(t.carbs, 'g'), g.carbs ? g.carbs + 'g' : '')}
    ${tile('sugar', 'Total sugar', fmt(t.sugar, 'g'), g.sugar ? g.sugar + 'g' : '')}
    ${tile('fat', 'Fats', fmt(t.fat, 'g'), g.fat ? g.fat + 'g' : '')}
  </div>`;
}
function nnCompare(t) {
  const parts = [['protein','Protein'], ['fibre','Fibre'], ['carbs','Carbs'], ['fat','Fat']];
  const total = parts.reduce((a, [k]) => a + t[k], 0);
  if (!total) return '<div class="nn-sub">Add foods with macros to see the split.</div>';
  return `<div class="nn-bar">${parts.map(([k]) => `<div style="width:${t[k] / total * 100}%;background:${NN_COLORS[k]}"></div>`).join('')}</div>` +
    parts.map(([k, lbl]) => `<div class="nn-leg"><i style="background:${NN_COLORS[k]}"></i>${lbl}<b>${Math.round(t[k] * 10) / 10}g</b><small>${Math.round(t[k] / total * 100)}%</small></div>`).join('');
}
function nnItem(e, i) {
  return `<button class="nn-item" data-i="${i}">
    ${thumbHtml(e.imageUrl, e.verified, 'entry')}
    <div class="nn-name">${escHtml(e.foodName)}
      <div class="nn-chips">${e.servingG ? `<span class="nn-chip">${Math.round(e.servingG)}g</span>` : ''}<span class="nn-chip">${Math.round(e.calories || 0)} kcal</span></div>
    </div><span style="color:var(--text-muted);font-size:1.3rem;">&rsaquo;</span></button>`;
}

function renderNutriSheet() {
  if (!nutriView || !lastData) return;
  const entries = lastData.entries || [];
  const body = document.getElementById('nnBody');
  if (nutriView.kind === 'meal') {
    const meal = MEALS.find(m => m.key === nutriView.key) || { key: nutriView.key, label: 'Uncategorised' };
    const list = entries.filter(e => (e.mealType || 'uncategorised') === meal.key);
    document.getElementById('nnTitle').textContent = meal.label;
    body.innerHTML = `<div class="nn-h3">Total Nutrition</div><div class="nn-sub">Based on the items in this meal</div>
      ${nnTiles(sumEntries(list))}
      ${list.map(nnItem).join('') || '<div class="nn-sub">Nothing logged in this meal yet.</div>'}
      ${list.length ? `<div class="nn-h3" style="margin-top:1rem;">Smaller or bigger portion?</div>
        <div class="nn-sub">Scales the weight and macros of every item in this meal. Tap an item above to adjust just one.</div>
        <div class="scale-btns" id="nnPortion">${[[0.5,'½'],[0.75,'¾'],[1.25,'1¼'],[1.5,'1½'],[2,'2×']].map(([f,l]) => `<button class="scale-btn" data-f="${f}">${l}</button>`).join('')}</div>` : ''}
      <button class="btn btn-primary nn-cta" id="nnAdd">Add More ${escHtml(meal.label)}</button>
      <div class="nn-h3" style="margin-top:1.2rem;">Compare Your Nutrients</div>${nnCompare(sumEntries(list))}`;
    body.querySelectorAll('.nn-item').forEach(b => b.addEventListener('click', () => openEntryDetail(list[+b.dataset.i])));
    body.querySelectorAll('#nnPortion .scale-btn').forEach(b => b.addEventListener('click', () => scaleMealPortion(list, parseFloat(b.dataset.f), meal.label)));
    document.getElementById('nnAdd').addEventListener('click', () => { closeNutriSheet(); openFindFood(meal.key); });
  } else {
    document.getElementById('nnTitle').textContent = fmtDateLabel(currentDate);
    const perMeal = MEALS.map(m => [m.label, sumEntries(entries.filter(e => (e.mealType || 'uncategorised') === m.key)).calories]).filter(r => r[1] > 0);
    const t = sumEntries(entries);
    body.innerHTML = `<div class="nn-h3">Total Nutrition</div><div class="nn-sub">Everything logged, against your goals</div>
      ${nnTiles(t, goals)}
      <div class="nn-h3" style="margin-top:1rem;">By meal</div>
      ${perMeal.map(([l, k]) => `<div class="nn-mealrow"><span>${escHtml(l)}</span><b>${Math.round(k)} kcal</b></div>`).join('') || '<div class="nn-sub">Nothing logged yet.</div>'}
      <div class="nn-h3" style="margin-top:1.2rem;">Compare Your Nutrients</div>${nnCompare(t)}`;
  }
}
function openMealSheet(key) { openNutriSheet({ kind: 'meal', key: key }); }
function openNutriSheet(view) {
  nutriView = view;
  renderNutriSheet();
  document.getElementById('mealNutriModal').classList.add('open');
  document.getElementById('nnBody').scrollTop = 0;
}
function closeNutriSheet() { nutriView = null; document.getElementById('mealNutriModal').classList.remove('open'); }
document.getElementById('nnBack').addEventListener('click', closeNutriSheet);
document.getElementById('btnViewNutri').addEventListener('click', () => openNutriSheet({ kind: 'day' }));

// ── Saved meals ───────────────────────────────────────────────────────
async function loadSavedMeals() {
  const r = await fetch('/nutrition/api/saved-meals');
  savedMeals = await r.json();
}

function setScale(mealId, scale) {
  document.querySelectorAll(`#scale-wrap-${mealId} .scale-btn`).forEach(b => {
    b.classList.toggle('active', parseFloat(b.dataset.scale)===scale);
  });
}

// ── Save section as meal ──────────────────────────────────────────────
function openSaveAsMeal(mealKey) {
  // Get current entries for this section from DOM data — easier to re-fetch
  const section = document.querySelector(`.meal-section[data-meal="${mealKey}"]`);
  const entries = [];
  section.querySelectorAll('.meal-entry').forEach(row => {
    const id = row.querySelector('.btn-del')?.dataset.id;
    if (id) entries.push({id:parseInt(id)});
  });
  if (!entries.length) return;
  smPendingItems = {mealKey, entryIds: entries.map(e=>e.id)};
  document.getElementById('smNameInput').value = '';
  document.getElementById('savedMealsModal').classList.add('open');
  setTimeout(() => document.getElementById('smNameInput').focus(), 120);
}

document.getElementById('smSaveCancel').addEventListener('click', () => {
  document.getElementById('savedMealsModal').classList.remove('open');
  smPendingItems = null;
});

// ── Build meal from ingredients ───────────────────────────────────────
function openBuildMeal() {
  buildMealItems = [];
  document.getElementById('bmName').value = '';
  document.getElementById('bmIngredients').innerHTML = '';
  document.getElementById('bmTotalKcal').textContent = '0 kcal';
  document.getElementById('findFoodModal').classList.remove('open');
  document.getElementById('buildMealModal').classList.add('open');
  document.getElementById('bmName').focus();
}

function closeBuildMeal() {
  document.getElementById('buildMealModal').classList.remove('open');
  buildMealItems = [];
  document.getElementById('findFoodModal').classList.add('open');
  switchFfTab('recipes');
}

function openBuildMealSearch() {
  document.getElementById('buildMealModal').classList.remove('open');
  openFindFoodForBuildMeal();
}

function renderBuildMealIngredients() {
  const el = document.getElementById('bmIngredients');
  if (!buildMealItems.length) {
    el.innerHTML = '<div style="text-align:center; color:var(--text-muted); font-size:0.85rem; padding:1rem;">No ingredients yet</div>';
    document.getElementById('bmTotalKcal').textContent = '0 kcal';
    return;
  }
  el.innerHTML = buildMealItems.map((item, idx) => `
    <div style="display:flex; justify-content:space-between; align-items:center; padding:0.5rem; border-bottom:1px solid var(--border); font-size:0.85rem;">
      <div>
        <div style="font-weight:600;">${escHtml(item.foodName)}</div>
        <div style="color:var(--text-muted); font-size:0.75rem;">${item.servingG}g × ${item.quantity}</div>
      </div>
      <div style="display:flex; flex-direction:column; align-items:flex-end; gap:0.25rem;">
        <div style="font-weight:600; color:var(--accent);">${item.calories.toFixed(0)} kcal</div>
        <button class="btn-del" data-click="removeBuildMealItem(${idx})" style="font-size:0.9rem;">×</button>
      </div>
    </div>
  `).join('');
  const totalKcal = buildMealItems.reduce((sum, item) => sum + (item.calories || 0), 0);
  document.getElementById('bmTotalKcal').textContent = totalKcal.toFixed(0) + ' kcal';
}

function removeBuildMealItem(idx) {
  buildMealItems.splice(idx, 1);
  renderBuildMealIngredients();
}

function addComputedToBuildMeal(item, t) {
  buildMealItems.push({
    foodName: item.name || item.foodName,
    barcode:  item.barcode || null,
    servingG: t.g,
    quantity: t.qty,
    calories: t.kcal  || 0,
    protein:  t.prot  || 0,
    carbs:    t.carbs || 0,
    fat:      t.fat   || 0,
    fibre:    t.fibre || 0,
    sugar:    t.sugar || 0,
  });
  renderBuildMealIngredients();
}

async function saveBuildMeal() {
  const name = (document.getElementById('bmName').value || 'Saved Meal').trim();
  if (!name) {
    alert('Please enter a meal name');
    return;
  }
  if (!buildMealItems.length) {
    alert('Please add at least one ingredient');
    return;
  }
  const payload = {
    name: name,
    items: buildMealItems.map(item => ({
      foodName: item.foodName,
      barcode: item.barcode,
      calories: item.calories,
      protein: item.protein,
      carbs: item.carbs,
      fat: item.fat,
      fibre: item.fibre,
      sugar: item.sugar,
      servingG: item.servingG * item.quantity
    }))
  };
  const r = await fetch('/nutrition/api/saved-meals', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(payload)
  });
  if (r.ok) {
    buildMealItems = [];
    await loadSavedMeals();
    document.getElementById('buildMealModal').classList.remove('open');
    document.getElementById('findFoodModal').classList.add('open');
    switchFfTab('recipes');
  } else {
    alert('Failed to save meal');
  }
}

document.getElementById('smSaveConfirm').addEventListener('click', async () => {
  if (!smPendingItems) return;
  const name = document.getElementById('smNameInput').value.trim();
  if (!name) { document.getElementById('smNameInput').focus(); return; }
  // Re-fetch the day to get full entry data
  const r = await fetch(`/nutrition/api/day/${isoDate(currentDate)}`);
  const data = await r.json();
  const items = data.entries
    .filter(e => smPendingItems.entryIds.includes(e.id))
    .map(e => ({
      foodName: e.foodName, calories: e.calories, protein: e.protein,
      carbs: e.carbs, fat: e.fat, fibre: e.fibre, sugar: e.sugar, servingG: e.servingG, barcode: e.barcode,
    }));
  await fetch('/nutrition/api/saved-meals', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({name, items}),
  });
  document.getElementById('savedMealsModal').classList.remove('open');
  smPendingItems = null;
  await loadSavedMeals();
});

document.getElementById('closeSavedMeals').addEventListener('click', () => {
  document.getElementById('savedMealsModal').classList.remove('open');
});

// ── Copy yesterday ────────────────────────────────────────────────────
document.getElementById('btnCopyYd').addEventListener('click', () => {
  document.getElementById('copyModal').classList.add('open');
});
document.getElementById('closeCopy').addEventListener('click', () => {
  document.getElementById('copyModal').classList.remove('open');
});

async function copyMeal(mealKey) {
  const label = mealKey ? (MEALS.find(m=>m.key===mealKey)?.label || mealKey) : 'whole day';
  const yd = fmtDateLabel(yesterday());
  if (!confirm(`Copy ${label} from ${yd}?`)) return;
  const r = await fetch('/nutrition/api/copy-day', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({from_date:isoDate(yesterday()), to_date:isoDate(currentDate), meal_type:mealKey||null}),
  });
  const d = await r.json();
  if (!d.count) { alert(`Nothing logged for ${label} on ${yd}.`); return; }
  loadDay();
}

document.getElementById('copyOptions').querySelectorAll('[data-meal]').forEach(btn => {
  btn.addEventListener('click', () => {
    document.getElementById('copyModal').classList.remove('open');
    copyMeal(btn.dataset.meal);
  });
});

// ── Hydration ─────────────────────────────────────────────────────────
document.querySelectorAll('[data-ml]').forEach(btn =>
  btn.addEventListener('click', async () => {
    const r = await fetch('/nutrition/api/water', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({date:isoDate(currentDate), ml:parseInt(btn.dataset.ml)}),
    });
    const d = await r.json();
    lastWaterId = d.id;
    loadDay();
  })
);
document.getElementById('undoWater').addEventListener('click', async () => {
  if (!lastWaterId) return;
  await fetch(`/nutrition/api/water/${lastWaterId}`, {method:'DELETE'});
  lastWaterId = null;
  loadDay();
});

// ── Photo of a meal → AI estimate ─────────────────────────────────────
let pmFile = null, pmData = null, pmScale = 1, pmBase = null, pmAbort = null, pmTimer = null;
const PM_SCALES = [0.5, 0.75, 1, 1.25, 1.5];

function pmShow(step) {
  for (const s of ['Pick', 'Ready', 'Busy', 'Review']) {
    document.getElementById('pmStep' + s).style.display = s === step ? '' : 'none';
    document.getElementById('pmFoot' + s).style.display = s === step ? '' : 'none';
  }
  document.getElementById('pmTitle').textContent = step === 'Review' ? 'Check the estimate' : 'Photo of your meal';
}
function openPhotoMeal() {
  pmFile = null; pmData = null; pmScale = 1;
  ['pmError', 'pmError2'].forEach(id => document.getElementById(id).textContent = '');
  document.getElementById('pmHint').value = '';
  pmShow('Pick');
  document.getElementById('photoMealModal').classList.add('open');
}
function pmClose() { if (pmAbort) pmAbort.abort(); clearInterval(pmTimer); document.getElementById('photoMealModal').classList.remove('open'); }
function pmPicked(f) {
  if (!f) return;
  pmFile = f;
  document.getElementById('pmPreview').src = URL.createObjectURL(f);
  document.getElementById('pmError2').textContent = '';
  pmShow('Ready');
}
document.getElementById('pmCam').addEventListener('change', e => { pmPicked(e.target.files[0]); e.target.value = ''; });
document.getElementById('pmGal').addEventListener('change', e => { pmPicked(e.target.files[0]); e.target.value = ''; });

async function pmEstimate() {
  if (!pmFile) return;
  const fd = new FormData();
  fd.append('photo', pmFile); fd.append('hint', document.getElementById('pmHint').value.trim());
  pmShow('Busy');
  let w = 15; const bar = document.getElementById('pmBar'); bar.style.width = '15%';
  clearInterval(pmTimer); pmTimer = setInterval(() => { w = Math.min(92, w + 4); bar.style.width = w + '%'; }, 700);
  pmAbort = new AbortController();
  try {
    const r = await fetch('/nutrition/api/estimate-meal', { method: 'POST', body: fd, signal: pmAbort.signal });
    const d = await r.json();
    if (!r.ok) throw new Error(d.error || 'Estimate failed');
    pmData = d; pmBase = { ...d.totals }; pmScale = 1;
    pmRenderReview();
    pmShow('Review');
  } catch (e) {
    if (e.name === 'AbortError') return;
    document.getElementById('pmError2').textContent = e.message;
    pmShow('Ready');
  } finally { clearInterval(pmTimer); pmAbort = null; }
}

function pmRenderReview() {
  const d = pmData;
  document.getElementById('pmThumb').src = d.image_url ? `/nutrition/api/image?url=${encodeURIComponent(d.image_url)}` : document.getElementById('pmPreview').src;
  document.getElementById('pmName').value = d.name;
  document.getElementById('pmMeta').textContent = `AI estimate · ${d.confidence} confidence`;
  document.getElementById('pmAssume').textContent = d.assumptions || '';
  document.getElementById('pmMeal').innerHTML = mealTypeOptions(currentMealType);
  document.getElementById('pmScales').innerHTML = PM_SCALES.map(s =>
    `<button class="btn btn-secondary${s === pmScale ? ' active' : ''}" data-s="${s}" style="min-height:44px; padding:0; justify-content:center;">${s === 1 ? '1×' : s + '×'}</button>`).join('');
  document.getElementById('pmItems').innerHTML = d.items.map(i =>
    `<div>${escHtml(i.name)}${i.portion ? ' <span style="color:var(--text-muted)">(' + escHtml(i.portion) + ')</span>' : ''} — <b>${Math.round(i.calories * pmScale)}</b> kcal</div>`).join('');
  pmFill();
}
function pmFill() {
  const f = (v, dp) => Math.round(v * pmScale * 10 ** dp) / 10 ** dp;
  document.getElementById('pmKcal').value = f(pmBase.calories, 0);
  document.getElementById('pmP').value = f(pmBase.protein, 1); document.getElementById('pmC').value = f(pmBase.carbs, 1);
  document.getElementById('pmF').value = f(pmBase.fat, 1);     document.getElementById('pmFi').value = f(pmBase.fibre, 1); document.getElementById('pmS').value = f(pmBase.sugar || 0, 1);
  const lo = Math.round(pmData.calories_low * pmScale), hi = Math.round(pmData.calories_high * pmScale);
  document.getElementById('pmRange').textContent = `Plausible range ${lo}–${hi} kcal — restaurant portions and hidden oil make these guesses rough.`;
  document.getElementById('pmLog').textContent = `Log · ${Math.round(pmBase.calories * pmScale)} kcal`;
}
// typing in a box updates the base, so the portion buttons scale YOUR numbers
[['pmKcal', 'calories'], ['pmP', 'protein'], ['pmC', 'carbs'], ['pmF', 'fat'], ['pmFi', 'fibre'], ['pmS', 'sugar']].forEach(([id, k]) => {
  document.getElementById(id).addEventListener('input', e => {
    const v = parseFloat(e.target.value); pmBase[k] = isNaN(v) ? 0 : v / pmScale;
    document.getElementById('pmLog').textContent = `Log · ${Math.round(pmBase.calories * pmScale)} kcal`;
  });
});
document.getElementById('pmScales').addEventListener('click', e => {
  const b = e.target.closest('button'); if (!b) return;
  pmScale = parseFloat(b.dataset.s);
  document.querySelectorAll('#pmScales button').forEach(x => x.className = 'btn btn-secondary' + (parseFloat(x.dataset.s) === pmScale ? ' active' : ''));
  document.getElementById('pmItems').querySelectorAll('div').forEach((row, i) => { row.querySelector('b').textContent = Math.round(pmData.items[i].calories * pmScale); });
  pmFill();
});
document.getElementById('pmLog').addEventListener('click', async () => {
  const name = document.getElementById('pmName').value.trim();
  const kcal = parseFloat(document.getElementById('pmKcal').value);
  if (!name || isNaN(kcal)) { alert('Give it a name and calories.'); return; }
  const num = id => { const v = parseFloat(document.getElementById(id).value); return isNaN(v) ? null : v; };
  await postLog({ name, calories: kcal, protein: num('pmP'), carbs: num('pmC'), fat: num('pmF'), fibre: num('pmFi'), sugar: num('pmS'),
                  serving_g: null, quantity: 1, meal_type: document.getElementById('pmMeal').value, source: 'photo_ai', image_url: pmData.image_url });
  pmClose();
  document.getElementById('findFoodModal').classList.remove('open');
});
document.getElementById('pmRedo').addEventListener('click', () => { document.getElementById('pmHint').focus(); pmShow('Ready'); });
document.getElementById('pmGo').addEventListener('click', pmEstimate);
document.getElementById('pmBackReady').addEventListener('click', () => pmShow('Pick'));
document.getElementById('pmBackReview').addEventListener('click', () => pmShow('Ready'));
document.getElementById('pmAbort').addEventListener('click', () => { if (pmAbort) pmAbort.abort(); pmShow('Ready'); });
document.getElementById('pmCancel').addEventListener('click', pmClose);
document.getElementById('pmClose').addEventListener('click', pmClose);
document.getElementById('ffPhotoBtn').addEventListener('click', openPhotoMeal);

// A nudge when the profile the smart goals need is incomplete (it lives under Settings -> Profile & goals)
(async function() {
  try {
    const d = await (await fetch('/nutrition/api/profile')).json();
    if (d.plan_error) {
      document.getElementById('profileNudgeText').textContent = d.plan_error + '. Add your details once and Headwind works out your calorie and macro goals, and your road to goal weight.';
      document.getElementById('profileNudge').style.display = '';
    }
  } catch (e) {}
})();

// ── Smart goals ───────────────────────────────────────────────────────
async function sgLoad() {
  const d = await (await fetch('/nutrition/api/goal-plan')).json();
  const p = d.profile;
  document.getElementById('sgSex').value = p.sex || '';
  sgBornShow(p);
  document.getElementById('sgHeight').value = p.height_cm || '';
  document.getElementById('sgRides').value = p.ride_kcal_week;
  document.getElementById('sgRideGoal').value = p.ride_goal_week;
  sgLossShow(p.loss_lb_week, d.weight_unit);
  document.getElementById('sgSteps').value = p.step_goal;
  document.getElementById('sgAuto').checked = !!p.auto;
  sgRender(d.plan, d.current);
}
// The loss rate is kept in lb a week, and shown and typed in kg a week when weights are shown in kg (0.25-1.1 kg for 0.5-2.5 lb)
const SG_KG_PER_LB = 0.45359237;
function sgLossShow(lb, unit) {
  const kg = unit === 'kg', box = document.getElementById('sgLoss');
  document.getElementById('sgLossLabel').textContent = kg ? 'Loss rate (kg/week)' : 'Loss rate (lb/week)';
  box.max = kg ? 1.1 : 2.5; box.step = kg ? 0.05 : 0.25; box.dataset.unit = kg ? 'kg' : 'lb';
  box.value = lb == null || lb === '' ? '' : (kg ? Math.round(lb * SG_KG_PER_LB * 20) / 20 : lb);
  box.dataset.lb = box.value === '' ? '' : lb; box.dataset.shown = box.value;       // the exact lb, while the figure shown is left alone
}
function sgLossLb() {
  const box = document.getElementById('sgLoss'), v = parseFloat(box.value);
  if (box.value === box.dataset.shown && box.dataset.lb !== '') return parseFloat(box.dataset.lb);
  return isNaN(v) ? '' : (box.dataset.unit === 'kg' ? Math.round(v / SG_KG_PER_LB * 1000) / 1000 : v);
}
function sgBornShow(p) {
  document.getElementById('sgBorn').value = (!p.birth_date_guessed && p.birth_date) || '';
  document.getElementById('sgBornHint').textContent = p.birth_date_guessed ? `Only the year (${p.birth_date.slice(0, 4)}) is known: enter the full date.` : (p.age ? `Age ${p.age}` : '');
}
function sgRender(pl, cur) {
  const box = document.getElementById('sgPlan');
  document.getElementById('sgApply').disabled = !!pl.error;
  if (pl.error) { box.textContent = pl.error + ' — fill those in above.'; return; }
  const f = n => Number(n).toLocaleString('en-GB');
  const diff = cur && cur.cal ? pl.goal - cur.cal : null;
  box.innerHTML =
    `<b>${f(pl.goal)} kcal</b> a day &nbsp;·&nbsp; P ${pl.protein}g · C ${pl.carbs}g · F ${pl.fat}g<br>` +
    `<span style="color:var(--text-muted)">Weight ${pl.weight_kg} kg → BMR ${f(pl.bmr)} × ${pl.profile.activity} = ${f(pl.neat)}, + ride allowance ${f(pl.rides_per_day)}/day ` +
    `(${f(pl.rides_week)}/week) = ~${f(pl.tdee)} − ${f(pl.deficit)} deficit${pl.floored ? ' (held at the ' + f(pl.floor) + ' floor)' : ''}.</span>` +
    (diff != null ? `<br>You have <b>${f(cur.cal)}</b> saved${diff ? ` — this is ${diff > 0 ? '+' : '−'}${Math.abs(diff)} kcal` : ' — the same'}.` : '');
}
async function sgSave() {
  const r = await fetch('/nutrition/api/goal-profile', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({
    sex: document.getElementById('sgSex').value, birth_date: document.getElementById('sgBorn').value, height_cm: document.getElementById('sgHeight').value,
    ride_kcal_week: document.getElementById('sgRides').value, ride_goal_week: document.getElementById('sgRideGoal').value, loss_lb_week: sgLossLb(),
    step_goal: document.getElementById('sgSteps').value, auto: document.getElementById('sgAuto').checked }) });
  const d = await r.json();
  if (!r.ok) { document.getElementById('sgPlan').textContent = d.error; return; }
  sgBornShow(d.profile);
  const cur = await (await fetch('/nutrition/api/goals')).json();
  sgRender(d.plan, cur);
}
['sgSex','sgBorn','sgHeight','sgRides','sgRideGoal','sgLoss','sgSteps','sgAuto'].forEach(id => document.getElementById(id).addEventListener('change', sgSave));
document.getElementById('sgApply').addEventListener('click', async () => {
  const r = await fetch('/nutrition/api/goal-plan/apply', { method: 'POST' });
  if (!r.ok) return;
  const g = await (await fetch('/nutrition/api/goals')).json();
  document.getElementById('gCal').value = g.cal || ''; document.getElementById('gProtein').value = g.protein || '';
  document.getElementById('gCarbs').value = g.carbs || ''; document.getElementById('gFat').value = g.fat || '';
  sgLoad(); loadDay();
});

// ── Goal weight helpers ──────────────────────────────────────────────
function gGoalUnitToggle() {
  const kg = document.getElementById('gWeightUnit').value === 'kg';
  document.getElementById('gGoalStlbRow').style.display = kg ? 'none' : '';
  document.getElementById('gGoalKg').style.display = kg ? '' : 'none';
}
document.getElementById('gWeightUnit').addEventListener('change', gGoalUnitToggle);
function gGoalKg() {
  if (document.getElementById('gWeightUnit').value === 'kg') return parseFloat(document.getElementById('gGoalKg').value) || null;
  const st = parseFloat(document.getElementById('gGoalSt').value) || 0, lb = parseFloat(document.getElementById('gGoalLb').value) || 0;
  return (st || lb) ? (st * 14 + lb) / 2.2046226218 : null;
}

// ── Goals modal ───────────────────────────────────────────────────────
document.getElementById('btnGoals').addEventListener('click', async () => {
  const g  = await (await fetch('/nutrition/api/goals')).json();
  const ws = await (await fetch('/nutrition/api/weight/settings')).json();
  document.getElementById('gCal').value     = g.cal     || '';
  document.getElementById('gProtein').value = g.protein || '';
  document.getElementById('gCarbs').value   = g.carbs   || '';
  document.getElementById('gFat').value     = g.fat     || '';
  document.getElementById('gWater').value   = g.water   || '';
  document.getElementById('gSugar').value   = g.sugar   || '';
  document.getElementById('gAlcohol').value = g.alcohol_week || '';
  document.getElementById('gBmr').value     = g.bmr     || '';
  document.getElementById('gWeightUnit').value = ws.unit || 'stlb';
  document.getElementById('gDietStart').value  = ws.dietStartDate || '';
  gGoalUnitToggle();
  const gk = ws.goalWeightKg;
  if (gk) {
    const totalLb = Math.round(gk * 2.2046226218 * 10) / 10;   // round first so 223.9998 lb is 16 st 0, not 15 st 14
    document.getElementById('gGoalSt').value = Math.floor(totalLb / 14);
    document.getElementById('gGoalLb').value = Math.round((totalLb - Math.floor(totalLb / 14) * 14) * 10) / 10;
    document.getElementById('gGoalKg').value = Math.round(gk * 10) / 10;
  } else {
    ['gGoalSt', 'gGoalLb', 'gGoalKg'].forEach(id => document.getElementById(id).value = '');
  }

  document.getElementById('goalsModal').classList.add('open');
  sgLoad();
});
document.getElementById('closeGoals').addEventListener('click',  () => document.getElementById('goalsModal').classList.remove('open'));
document.getElementById('cancelGoals').addEventListener('click', () => document.getElementById('goalsModal').classList.remove('open'));
document.getElementById('saveGoals').addEventListener('click', async () => {
  await fetch('/nutrition/api/goals', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({
      cal:     parseInt(document.getElementById('gCal').value)     || null,
      protein: parseInt(document.getElementById('gProtein').value) || null,
      carbs:   parseInt(document.getElementById('gCarbs').value)   || null,
      fat:     parseInt(document.getElementById('gFat').value)     || null,
      water:   parseInt(document.getElementById('gWater').value)   || null,
      sugar:   parseInt(document.getElementById('gSugar').value)   || null,
      alcohol_week: parseFloat(document.getElementById('gAlcohol').value) || null,
      bmr:     parseInt(document.getElementById('gBmr').value)     || null,
    }),
  });
  await fetch('/nutrition/api/weight/settings', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({
      unit:          document.getElementById('gWeightUnit').value,
      dietStartDate: document.getElementById('gDietStart').value || null,
      goalWeightKg:  gGoalKg(),
    }),
  });
  const lossLb = sgLossLb();
  weightUnit = document.getElementById('gWeightUnit').value;
  sgLossShow(lossLb, weightUnit);
  document.getElementById('goalsModal').classList.remove('open');
  loadDay();
});

// ── Core log helper ───────────────────────────────────────────────────
async function postLog(fields) {
  await fetch('/nutrition/api/log', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({date:isoDate(currentDate), ...fields}),
  });
  loadDay();
}

// Scale every logged item in a meal by one factor (weight + all macros), e.g. a smaller portion of a saved meal.
async function scaleMealPortion(list, f, label) {
  if (!list.length || !(f > 0)) return;
  if (!confirm(`Scale everything in ${label} by ${f}×?`)) return;
  const sc = v => (v == null ? null : Math.round(v * f * 10) / 10);
  const date = isoDate(currentDate);
  for (const e of list) {
    await fetch('/nutrition/api/log', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({
      id: e.id, date, name: e.foodName, barcode: e.barcode || null,
      calories: sc(e.calories), protein: sc(e.protein), carbs: sc(e.carbs), fat: sc(e.fat), fibre: sc(e.fibre), sugar: sc(e.sugar), alcohol_units: sc(e.alcoholUnits),
      serving_g: e.servingG ? Math.round(e.servingG * f * 10) / 10 : null, quantity: e.quantity || 1,
      meal_type: e.mealType || 'uncategorised', source: e.source || 'manual', brand: e.brand || null,
      image_url: e.imageUrl || null, nutri_score_grade: e.nutriScoreGrade || null }) });
  }
  await loadDay();
  renderNutriSheet();
}

// ── Thumbnails / badges (shared by Find-a-Food rows, day view, detail) ──
function thumbHtml(url, verified, kind) {
  const cls      = kind === 'entry' ? 'meal-entry-thumb'       : 'ff-thumb';
  const iconCls  = kind === 'entry' ? 'meal-entry-thumb-icon'  : 'ff-thumb-icon';
  const badgeCls = kind === 'entry' ? 'meal-entry-thumb-badge' : 'ff-thumb-badge';
  const inner = url
    ? `<img src="/nutrition/api/image?url=${encodeURIComponent(url)}" loading="lazy" data-error="this.remove()">`
    : `<span class="${iconCls}">&#x1F37D;</span>`;
  const badge = verified ? `<span class="${badgeCls}">&#x2713;</span>` : '';
  return `<div class="${cls}">${inner}${badge}</div>`;
}

function qualityEmoji(label) {
  return {Excellent:'&#x1F60A;', Good:'&#x1F642;', OK:'&#x1F610;', Poor:'&#x1F61F;'}[label] || '';
}
function tagBadgeClass(color) {
  return {fibre:'tag-fibre', protein:'tag-protein', fat:'tag-fat', carbs:'tag-carbs'}[color] || 'tag-fibre';
}

// ── Find A Food (bottom sheet) ──────────────────────────────────────────
function openFindFood(mealKey) {
  currentMealType = mealKey;
  ffPickMode = null;
  document.getElementById('ffSearchBar').classList.remove('open');
  document.getElementById('ffSearchInput').value = '';
  document.getElementById('findFoodModal').classList.add('open');
  switchFfTab('recent');
}

function openFindFoodForBuildMeal() {
  ffPickMode = 'buildmeal';
  document.getElementById('ffSearchBar').classList.remove('open');
  document.getElementById('ffSearchInput').value = '';
  document.getElementById('findFoodModal').classList.add('open');
  switchFfTab('recent');
}

document.getElementById('ffClose').addEventListener('click', () => document.getElementById('findFoodModal').classList.remove('open'));

document.getElementById('ffSearchToggle').addEventListener('click', () => {
  const bar = document.getElementById('ffSearchBar');
  bar.classList.toggle('open');
  if (bar.classList.contains('open')) setTimeout(() => document.getElementById('ffSearchInput').focus(), 100);
});
document.getElementById('ffSearchGo').addEventListener('click', runFfSearch);
document.getElementById('ffSearchInput').addEventListener('keydown', e => { if (e.key === 'Enter') runFfSearch(); });

document.getElementById('ffScanBtn').addEventListener('click', () => {
  document.getElementById('findFoodModal').classList.remove('open');
  openScanner();
});

document.getElementById('ffTabs').querySelectorAll('.ff-tab').forEach(tab => {
  tab.addEventListener('click', () => switchFfTab(tab.dataset.tab));
});

function switchFfTab(tab) {
  ffTab = tab;
  ffOffset = 0;
  document.getElementById('ffTabs').querySelectorAll('.ff-tab').forEach(t => t.classList.toggle('active', t.dataset.tab === tab));
  loadFfTab();
}

async function loadFfTab() {
  const list = document.getElementById('ffList');
  list.innerHTML = '<div class="ff-empty">Loading…</div>';
  document.getElementById('ffLoadMore').style.display = 'none';
  if (ffTab === 'recent') {
    const mealLbl = (MEALS.find(m => m.key === currentMealType) || {label: ''}).label;
    document.getElementById('ffListLbl').textContent = mealLbl ? `Recent ${mealLbl}` : 'Recently logged food items';
    const r = await fetch(`/nutrition/api/recent?meal_type=${currentMealType}&offset=0&limit=20`);
    const data = await r.json();
    if (data.fallback && mealLbl) document.getElementById('ffListLbl').textContent = `Nothing logged for ${mealLbl} yet — showing your recent foods`;
    recentFoods = data.items || [];
    ffOffset = recentFoods.length;
    ffHasMore = data.hasMore;
    renderFfList(recentFoods, 'recent');
    document.getElementById('ffLoadMore').style.display = ffHasMore ? '' : 'none';
  } else if (ffTab === 'gotos') {
    document.getElementById('ffListLbl').textContent = 'Your Go-To foods';
    favourites = await (await fetch('/nutrition/api/favourites')).json();
    renderFfList(favourites, 'gotos');
  } else if (ffTab === 'recipes') {
    document.getElementById('ffListLbl').textContent = 'Saved meals';
    await loadSavedMeals();
    renderFfRecipes();
  } else if (ffTab === 'myfoods') {
    document.getElementById('ffListLbl').textContent = "Foods you've created";
    myFoods = await (await fetch('/nutrition/api/my-foods')).json();
    renderFfList(myFoods, 'myfoods');
    document.getElementById('ffList').insertAdjacentHTML('afterbegin',
      `<button class="btn btn-secondary btn-block" style="margin-bottom:0.75rem;" data-click="openMyFoodModal(null)">+ Create food</button>`);
  }
}

document.getElementById('ffLoadMore').addEventListener('click', async () => {
  const r = await fetch(`/nutrition/api/recent?meal_type=${currentMealType}&offset=${ffOffset}&limit=20`);
  const data = await r.json();
  recentFoods = recentFoods.concat(data.items || []);
  ffOffset += (data.items || []).length;
  ffHasMore = data.hasMore;
  renderFfList(recentFoods, 'recent');
  document.getElementById('ffLoadMore').style.display = ffHasMore ? '' : 'none';
});

async function runFfSearch() {
  const q = document.getElementById('ffSearchInput').value.trim();
  if (!q) return;
  document.getElementById('ffListLbl').textContent = `Results for "${q}"`;
  document.getElementById('ffLoadMore').style.display = 'none';
  const list = document.getElementById('ffList');
  list.innerHTML = '<div class="ff-empty">Searching…</div>';
  try {
    const products = await (await fetch(`/nutrition/api/search?q=${encodeURIComponent(q)}`)).json();
    if (!products.length) { list.innerHTML = '<div class="ff-empty">No results with calorie data. Try Manual entry.</div>'; return; }
    if (products[0] && products[0].cached) document.getElementById('ffListLbl').textContent =
      products[0].offline ? `Results for "${q}" — saved locally (search service unreachable)` : `Results for "${q}" — from your saved foods`;
    renderFfList(products, 'search');
  } catch {
    list.innerHTML = '<div class="ff-empty">Search failed — check connection.</div>';
  }
}

function ffRowMeta(item, kind) {
  if (kind === 'search' || kind === 'myfoods') {
    const g = item.serving_g || 100;
    const kcal = item.kcal_per_100g ? Math.round(item.kcal_per_100g / 100 * g) : null;
    return [Math.round(g) + 'g', kcal != null ? kcal + ' kcal' : null].filter(Boolean).join(' · ');
  }
  const g = item.servingG;
  return [g ? Math.round(g) + 'g' : null, item.calories != null ? Math.round(item.calories) + ' kcal' : null].filter(Boolean).join(' · ');
}

function renderFfList(items, kind) {
  const list = document.getElementById('ffList');
  if (!items.length) { list.innerHTML = '<div class="ff-empty">Nothing here yet.</div>'; return; }
  list.innerHTML = items.map((item, i) => {
    const name  = item.name || item.foodName;
    const brand = item.brand ? `<span class="ff-row-brand">${escHtml(item.brand)}</span><br>` : '';
    const img   = item.image_url || item.imageUrl;
    let extraBtns = '';
    if (kind === 'myfoods') extraBtns = `<button class="ff-icon-btn" data-edit="${i}">&#x270E;</button><button class="ff-icon-btn" data-del="${i}">&#x1F5D1;</button>`;
    else if (kind === 'gotos') extraBtns = `<button class="ff-icon-btn" data-del="${i}">&#x1F5D1;</button>`;
    return `<div class="ff-row" data-idx="${i}">
      ${thumbHtml(img, item.verified)}
      <div class="ff-row-body">
        ${brand}<div class="ff-row-name">${escHtml(name)}${item.shared_from ? ` <span style="font-size:0.7rem;color:var(--text-muted);font-weight:400">&#x1F91D; ${escHtml(item.shared_from)}</span>` : ''}</div>
        <div class="ff-row-meta">${ffRowMeta(item, kind)}</div>
      </div>
      <div class="ff-row-actions">
        ${extraBtns}
        <button class="ff-plus-btn" data-quick="${i}">+</button>
      </div>
    </div>`;
  }).join('');

  list.querySelectorAll('.ff-row').forEach(row => {
    const idx = parseInt(row.dataset.idx);
    row.addEventListener('click', (ev) => {
      if (ev.target.closest('[data-quick],[data-edit],[data-del]')) return;
      openDetailFromFf(items[idx], kind);
    });
  });
  list.querySelectorAll('[data-quick]').forEach(btn => {
    btn.addEventListener('click', (ev) => { ev.stopPropagation(); quickAddFf(items[parseInt(btn.dataset.quick)], kind); });
  });
  list.querySelectorAll('[data-edit]').forEach(btn => {
    btn.addEventListener('click', (ev) => { ev.stopPropagation(); openMyFoodModal(items[parseInt(btn.dataset.edit)]); });
  });
  list.querySelectorAll('[data-del]').forEach(btn => {
    btn.addEventListener('click', async (ev) => {
      ev.stopPropagation();
      const item = items[parseInt(btn.dataset.del)];
      if (!confirm(`Delete "${item.name || item.foodName}"?`)) return;
      if (kind === 'myfoods') await fetch(`/nutrition/api/my-foods/${item.id}`, {method:'DELETE'});
      else await fetch(`/nutrition/api/favourites/${item.id}`, {method:'DELETE'});
      loadFfTab();
    });
  });
}

function renderFfRecipes() {
  const list = document.getElementById('ffList');
  const createBtn = `<button class="btn btn-secondary btn-block" style="margin-bottom:0.75rem;" data-click="openBuildMeal()">+ Create meal</button>`;
  if (!savedMeals.length) { list.innerHTML = createBtn + '<div class="ff-empty">No saved meals yet.</div>'; return; }
  list.innerHTML = createBtn + savedMeals.map(m => {
    const opts = mealTypeOptions(currentMealType);
    const items = m.items.map(i => escHtml(i.foodName)).join(', ');
    return `<div class="saved-meal-row">
      <div class="saved-meal-name">${escHtml(m.name)}</div>
      <div class="saved-meal-meta">${m.totalCal} kcal · ${escHtml(items)}</div>
      <div class="scale-btns" id="scale-wrap-${m.id}">
        ${[0.5,1,1.5,2].map(s=>`<button class="scale-btn${s===1?' active':''}" data-scale="${s}" data-click="setScale(${m.id},${s})">${s}×</button>`).join('')}
      </div>
      <div style="display:flex; gap:0.4rem; align-items:center; margin-bottom:0.3rem;">
        <span style="font-size:0.78rem; color:var(--text-muted); flex-shrink:0;">Add to</span>
        <select id="smMeal-${m.id}" style="flex:1; font-size:0.78rem;">${opts}</select>
      </div>
      <div class="saved-meal-actions">
        <button class="btn btn-primary" data-click="logSavedMealFf(${m.id})">+ Log</button>
        <button class="btn btn-danger-quiet" data-click="deleteSavedMealFf(${m.id})">Delete</button>
      </div>
    </div>`;
  }).join('');
}

async function logSavedMealFf(mealId) {
  const activeScale = document.querySelector(`#scale-wrap-${mealId} .scale-btn.active`);
  const scale = activeScale ? parseFloat(activeScale.dataset.scale) : 1;
  const mealType = document.getElementById(`smMeal-${mealId}`).value;
  await fetch(`/nutrition/api/saved-meals/${mealId}/log`, {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({date:isoDate(currentDate), meal_type:mealType, scale}),
  });
  document.getElementById('findFoodModal').classList.remove('open');
  loadDay();
}

async function deleteSavedMealFf(mealId) {
  const meal = savedMeals.find(m=>m.id===mealId);
  if (!confirm(`Delete "${meal?.name||'this meal'}"?`)) return;
  await fetch(`/nutrition/api/saved-meals/${mealId}`, {method:'DELETE'});
  await loadSavedMeals();
  renderFfRecipes();
}

// ── Quick-add (the '+' button — logs at default/last-used serving) ──────
function quickAddFf(item, kind) {
  if (ffPickMode === 'buildmeal') {
    const g = (kind === 'search' || kind === 'myfoods') ? (item.serving_g || 100) : (item.servingG || 100);
    addFfItemToBuildMeal(item, kind, g, 1);
    return;
  }
  if (kind === 'search' || kind === 'myfoods') {
    logPer100Item(item, item.serving_g || 100, 1, currentMealType, kind === 'myfoods' ? 'custom_food' : 'barcode');
  } else {
    logAbsoluteItem(item, item.servingG, item.quantity || 1, currentMealType, kind === 'gotos' ? 'favourite' : 'recent');
  }
  document.getElementById('findFoodModal').classList.remove('open');
}

async function logPer100Item(item, g, qty, mealType, source) {
  let kcal=null, prot=null, carbs=null, fat=null;
  if (item.kcal_per_100g && g) {
    const f = (g/100)*qty;
    kcal  = item.kcal_per_100g * f;
    prot  = item.protein_per_100g != null ? item.protein_per_100g * f : null;
    carbs = item.carbs_per_100g   != null ? item.carbs_per_100g   * f : null;
    fat   = item.fat_per_100g     != null ? item.fat_per_100g     * f : null;
  }
  await postLog({
    name: item.name, barcode: item.barcode || null, calories: kcal, protein: prot, carbs, fat,
    serving_g: g ? g*qty : null, quantity: qty, meal_type: mealType, source,
    brand: item.brand || null, image_url: item.image_url || null, nutri_score_grade: item.nutri_score_grade || null,
  });
}

async function logAbsoluteItem(item, g, qty, mealType, source) {
  const name = item.name || item.foodName;
  let kcal=item.calories, prot=item.protein, carbs=item.carbs, fat=item.fat, servG=g;
  if (item.servingG && g && item.servingG !== g) {
    const ratio = g / item.servingG * qty;
    kcal  = item.calories != null ? item.calories * ratio : null;
    prot  = item.protein  != null ? item.protein  * ratio : null;
    carbs = item.carbs    != null ? item.carbs    * ratio : null;
    fat   = item.fat      != null ? item.fat      * ratio : null;
    servG = g * qty;
  } else {
    kcal  = item.calories != null ? item.calories * qty : null;
    prot  = item.protein  != null ? item.protein  * qty : null;
    carbs = item.carbs    != null ? item.carbs    * qty : null;
    fat   = item.fat      != null ? item.fat      * qty : null;
    servG = item.servingG ? item.servingG * qty : null;
  }
  await postLog({
    name, barcode: item.barcode || null, calories: kcal, protein: prot, carbs, fat,
    serving_g: servG, quantity: qty, meal_type: mealType, source,
    brand: item.brand || null, image_url: item.imageUrl || item.image_url || null, nutri_score_grade: item.nutriScoreGrade || null,
  });
}

function addFfItemToBuildMeal(item, kind, g, qty) {
  const mode = (kind === 'search' || kind === 'myfoods') ? 'per100' : 'absolute';
  fdContext = {mode, item, target:'buildmeal'};
  document.getElementById('fdServingG').value = g;
  document.getElementById('fdServingQty').value = qty;
  addComputedToBuildMeal(item, fdComputeTotals());
  document.getElementById('findFoodModal').classList.remove('open');
  document.getElementById('buildMealModal').classList.add('open');
}

// ── Food detail card ─────────────────────────────────────────────────
function openDetailFromFf(item, kind) {
  const mode = (kind === 'search' || kind === 'myfoods') ? 'per100' : 'absolute';
  openFoodDetail(item, {mode, target: ffPickMode === 'buildmeal' ? 'buildmeal' : 'log', sourceKind: kind});
}

function openEntryDetail(entry) {
  openFoodDetail(entry, {mode:'absolute', target:'editlog', entryId:entry.id, sourceKind:'log'});
}

// A food or recipe photo that won't load: the plate icon, or no cell at all in the photo picker
function foodPhotoMissing(img) { img.parentElement.innerHTML = '<span class="fd-photo-icon">&#x1F37D;</span>'; }
function photoCellMissing(img) { img.closest('.ph-cell').remove(); }

function openFoodDetail(item, ctx) {
  // A logged entry stores TOTALS (macros and grams already include the quantity). The card works per single serving and
  // multiplies by the quantity box, so convert once here — otherwise a quantity-2 entry opens (and re-saves) at double.
  if (ctx.mode === 'absolute' && (item.quantity || 1) > 1) {
    const q = item.quantity, per = v => (v == null ? v : v / q);
    item = { ...item, calories: per(item.calories), protein: per(item.protein), carbs: per(item.carbs), fat: per(item.fat),
             fibre: per(item.fibre), sugar: per(item.sugar), alcoholUnits: per(item.alcoholUnits), servingG: per(item.servingG) };
  }
  fdBaseG = null;
  fdContext = { ...ctx, item };
  const name  = item.name || item.foodName;
  const brand = item.brand || '';
  const img   = item.image_url || item.imageUrl;

  document.getElementById('fdPhoto').innerHTML = img
    ? `<img src="/nutrition/api/image?url=${encodeURIComponent(img)}" data-error="foodPhotoMissing(this)">`
    : `<span class="fd-photo-icon">&#x1F37D;</span>`;
  const brandEl = document.getElementById('fdBrand');
  if (brand) { brandEl.textContent = brand; brandEl.style.display=''; } else brandEl.style.display='none';
  document.getElementById('fdName').textContent = name;

  const badges = [];
  if (item.verified) badges.push(`<span class="fd-badge verified">&#x2713; Verified</span>`);
  if (item.shared_from) badges.push(`<span class="fd-badge quality">&#x1F91D; From ${escHtml(item.shared_from)}</span>`);
  if (item.nutri_score_label) badges.push(`<span class="fd-badge quality">${qualityEmoji(item.nutri_score_label)} ${item.nutri_score_label}</span>`);
  (item.tags || []).forEach(t => badges.push(`<span class="fd-badge ${tagBadgeClass(t.color)}">${escHtml(t.label)}</span>`));
  document.getElementById('fdBadges').innerHTML = badges.join('');

  document.getElementById('fdSectionLbl').textContent =
    ctx.target === 'editlog' ? 'Edit Your Food' : (ctx.target === 'buildmeal' ? 'Add Ingredient' : 'Add Your Food');
  document.getElementById('fdSaveBtn').textContent =
    ctx.target === 'editlog' ? 'Update' : (ctx.target === 'buildmeal' ? 'Add to meal' : 'Add');

  let defG, defQty;
  if (ctx.mode === 'per100') {
    defG = item.serving_g ? Math.round(item.serving_g) : 100;
    defQty = 1;
  } else {
    defG = item.servingG ? Math.round(item.servingG) : '';
    defQty = item.quantity || 1;
  }
  document.getElementById('fdServingG').value = defG;
  document.getElementById('fdServingQty').value = defQty;
  // a drink: show the strength field (known strength, else a typical one to confirm, else for an entry that already has units, the strength they imply)
  let abv = null, isDrink = !!(item.alcoholic || item.abv != null || item.alcoholUnits != null);
  if (item.abv != null) abv = item.abv;
  else if (ctx.mode === 'absolute' && item.alcoholUnits != null && item.servingG) abv = Math.round(item.alcoholUnits * 1000 / item.servingG * 10) / 10;
  else if (item.abv_guess != null) abv = item.abv_guess;
  document.getElementById('fdAbvRow').style.display = isDrink ? '' : 'none';
  document.getElementById('fdAbvHint').style.display = (isDrink && item.abv == null && item.alcoholUnits == null) ? '' : 'none';
  document.getElementById('fdAbv').value = isDrink && abv != null ? abv : '';
  fdUpdateWeightHint();
  document.getElementById('fdMealType').innerHTML = mealTypeOptions(item.mealType || currentMealType);
  document.getElementById('fdMealType').closest('.serving-row').style.display = ctx.target === 'buildmeal' ? 'none' : '';

  fdEditing = false;
  document.getElementById('fdEditNutri').textContent = '✎ Edit nutrition';
  document.getElementById('fdEditCancel').style.display = 'none';
  buildFdMoreMenu();
  updateFdMacros();
  document.getElementById('foodDetailModal').classList.add('open');
}

function fdComputeTotals() {
  const item = fdContext.item;
  const g   = parseFloat(document.getElementById('fdServingG').value) || 0;
  const qty = parseFloat(document.getElementById('fdServingQty').value) || 1;
  let kcal=null, prot=null, carbs=null, fat=null, fibre=null, sugar=null, alcohol=null, servG=null;
  if (fdContext.mode === 'per100') {
    if (item.kcal_per_100g && g) {
      const f = (g/100)*qty;
      kcal  = item.kcal_per_100g * f;
      prot  = item.protein_per_100g != null ? item.protein_per_100g * f : null;
      carbs = item.carbs_per_100g   != null ? item.carbs_per_100g   * f : null;
      fat   = item.fat_per_100g     != null ? item.fat_per_100g     * f : null;
      fibre = item.fibre_per_100g   != null ? item.fibre_per_100g   * f : null;
      sugar = item.sugars_per_100g  != null ? item.sugars_per_100g  * f : null;
      alcohol = item.abv            != null ? g * qty * item.abv / 1000 : null;
    }
    servG = g ? g*qty : null;
  } else {
    const baseG = item.servingG || fdBaseG;      // the weight the stored macros describe
    if (baseG && g && baseG !== g) {
      const ratio = g / baseG * qty;
      kcal  = item.calories != null ? item.calories * ratio : null;
      prot  = item.protein  != null ? item.protein  * ratio : null;
      carbs = item.carbs    != null ? item.carbs    * ratio : null;
      fat   = item.fat      != null ? item.fat      * ratio : null;
      fibre = item.fibre    != null ? item.fibre    * ratio : null;
      sugar = item.sugar    != null ? item.sugar    * ratio : null;
      alcohol = item.alcoholUnits != null ? item.alcoholUnits * ratio : null;
      servG = g * qty;
    } else {
      kcal  = item.calories != null ? item.calories * qty : null;
      prot  = item.protein  != null ? item.protein  * qty : null;
      carbs = item.carbs    != null ? item.carbs    * qty : null;
      fat   = item.fat      != null ? item.fat      * qty : null;
      fibre = item.fibre    != null ? item.fibre    * qty : null;
      sugar = item.sugar    != null ? item.sugar    * qty : null;
      alcohol = item.alcoholUnits != null ? item.alcoholUnits * qty : null;
      servG = g ? g * qty : (item.servingG ? item.servingG * qty : null);
    }
  }
  if (document.getElementById('fdAbvRow').style.display !== 'none') {       // a drink: units come from the strength shown on the card
    const abv = parseFloat(document.getElementById('fdAbv').value);
    alcohol = abv > 0 && servG ? Math.round(servG * abv / 1000 * 100) / 100 : null;
  }
  return { kcal, prot, carbs, fat, fibre, sugar, alcohol, servG, g, qty };
}

function updateFdMacros() {
  const t = fdComputeTotals();
  const au = document.getElementById('fdAbvUnits'); if (au) au.textContent = t.alcohol != null ? '= ' + (Math.round(t.alcohol * 10) / 10) + ' units' : '';
  const tiles = [
    ['cal',     'Calories', t.kcal  != null ? Math.round(t.kcal)        : '—'],
    ['protein', 'Protein',  t.prot  != null ? Math.round(t.prot)+'g'    : '—'],
    ['carbs',   'Carbs',    t.carbs != null ? Math.round(t.carbs)+'g'   : '—'],
    ['fat',     'Fats',     t.fat   != null ? Math.round(t.fat)+'g'     : '—'],
    ['fibre',   'Fibre',    t.fibre != null ? (Math.round(t.fibre*10)/10)+'g' : '—'],
    ['sugar',   'Total sugar', t.sugar != null ? (Math.round(t.sugar*10)/10)+'g' : '—'],
  ];
  if (fdEditing) {
    const ids = { cal:['fdEdKcal', t.kcal], protein:['fdEdProt', t.prot], fibre:['fdEdFibre', t.fibre], sugar:['fdEdSugar', t.sugar], carbs:['fdEdCarbs', t.carbs], fat:['fdEdFat', t.fat] };
    document.getElementById('fdMacroGrid').innerHTML = tiles.map(([cls,lbl]) => {
      const [id, v] = ids[cls];
      return `<div class="fd-macro-tile"><div class="fd-macro-lbl ${cls}">${lbl}</div>
              <input type="number" inputmode="decimal" step="0.1" id="${id}" value="${v != null ? Math.round(v*10)/10 : ''}"></div>`;
    }).join('');
    return;
  }
  document.getElementById('fdMacroGrid').innerHTML = tiles.map(([cls,lbl,val]) =>
    `<div class="fd-macro-tile"><div class="fd-macro-lbl ${cls}">${lbl}</div><div class="fd-macro-val">${val}</div></div>`
  ).join('');
}
function fdUpdateWeightHint() {
  const el = document.getElementById('fdWeightHint');
  if (!el || !fdContext) return;
  const hasBase = fdContext.mode === 'per100' || fdContext.item.servingG || fdBaseG;
  el.textContent = hasBase ? 'Change the weight and the calories and macros scale to match.'
                           : "No weight recorded for this entry. Enter the weight of this portion once, then change it any time and the macros scale.";
}
document.getElementById('fdServingG').addEventListener('input', updateFdMacros);
// First weight typed for an entry that never had one: it describes the macros as they are now, so it becomes the baseline
// (committed on blur/enter, not per keystroke — "2", "25", "250" must not each rescale).
document.getElementById('fdServingG').addEventListener('change', () => {
  if (fdContext && fdContext.mode === 'absolute' && !fdContext.item.servingG && !fdBaseG) {
    const g = parseFloat(document.getElementById('fdServingG').value);
    if (g > 0) fdBaseG = g;
  }
  fdUpdateWeightHint();
  updateFdMacros();
});
document.getElementById('fdServingQty').addEventListener('input', updateFdMacros);
document.getElementById('fdAbv').addEventListener('input', updateFdMacros);

document.getElementById('fdBack').addEventListener('click', () => {
  document.getElementById('foodDetailModal').classList.remove('open');
  if (fdContext && fdContext.target !== 'editlog') document.getElementById('findFoodModal').classList.add('open');
});

async function fdSaveEntry() {
  const item = fdContext.item;
  const t = fdComputeTotals();
  const mealType = document.getElementById('fdMealType').value;
  const sourceMap = {search:'barcode', myfoods:'custom_food', gotos:'favourite', log:'manual'};
  const payload = {
    name: item.name || item.foodName, barcode: item.barcode || null,
    calories: t.kcal, protein: t.prot, carbs: t.carbs, fat: t.fat, fibre: t.fibre, sugar: t.sugar, alcohol_units: t.alcohol,
    abv: (document.getElementById('fdAbvRow').style.display !== 'none' ? (parseFloat(document.getElementById('fdAbv').value) || null) : null),
    serving_g: t.servG, quantity: t.qty, meal_type: mealType,
    source: sourceMap[fdContext.sourceKind] || fdContext.sourceKind || 'manual',
    brand: item.brand || null,
    image_url: item.image_url || item.imageUrl || null,
    nutri_score_grade: item.nutri_score_grade || item.nutriScoreGrade || null,
  };
  if (fdContext.target === 'editlog') payload.id = fdContext.entryId;
  await postLog(payload);
}

document.getElementById('fdSaveBtn').addEventListener('click', async () => {
  if (fdEditing) { await fdSaveNutrition(); return; }   // "Add" while editing saves the corrected values first
  const item = fdContext.item;
  const t = fdComputeTotals();
  if (fdContext.target === 'buildmeal') {
    addComputedToBuildMeal(item, t);
    document.getElementById('foodDetailModal').classList.remove('open');
    document.getElementById('buildMealModal').classList.add('open');
    return;
  }
  await fdSaveEntry();
  document.getElementById('foodDetailModal').classList.remove('open');
  document.getElementById('findFoodModal').classList.remove('open');
});

function buildFdMoreMenu() {
  const item = fdContext.item;
  const menu = document.getElementById('fdMoreMenu');
  const btns = [];
  if (fdContext.target === 'editlog') btns.push(`<button id="fdMenuDelete" class="danger">Delete entry</button>`);
  if (fdContext.sourceKind !== 'gotos' && fdContext.target !== 'buildmeal') btns.push(`<button id="fdMenuFav">Add to Go-Tos</button>`);
  if (fdContext.mode === 'per100' && item.barcode && fdContext.target !== 'buildmeal') btns.push(`<button id="fdMenuOverride">Save corrections</button>`);
  menu.innerHTML = btns.join('') || '<button disabled style="opacity:0.5;">No actions</button>';

  const del = document.getElementById('fdMenuDelete');
  if (del) del.addEventListener('click', async () => {
    if (!confirm('Delete this entry?')) return;
    await fetch(`/nutrition/api/log/${fdContext.entryId}`, {method:'DELETE'});
    document.getElementById('foodDetailModal').classList.remove('open');
    menu.classList.remove('open');
    loadDay();
  });
  const fav = document.getElementById('fdMenuFav');
  if (fav) fav.addEventListener('click', async () => {
    const t = fdComputeTotals();
    await fetch('/nutrition/api/favourites', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({
        foodName: item.name || item.foodName, barcode: item.barcode || null, brand: item.brand || null,
        calories: t.kcal, protein: t.prot, carbs: t.carbs, fat: t.fat,
        servingG: t.g, imageUrl: item.image_url || item.imageUrl || null,
      }),
    });
    menu.classList.remove('open');
    fav.textContent = 'Added to Go-Tos ✓'; fav.disabled = true;
  });
  const ov = document.getElementById('fdMenuOverride');
  if (ov) ov.addEventListener('click', async () => {
    await fetch('/nutrition/api/override', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({
        barcode: item.barcode, name: item.name, brand: item.brand,
        kcal_per_100g: item.kcal_per_100g, protein_per_100g: item.protein_per_100g,
        carbs_per_100g: item.carbs_per_100g, fat_per_100g: item.fat_per_100g,
        serving_g: parseFloat(document.getElementById('fdServingG').value) || item.serving_g,
      }),
    });
    menu.classList.remove('open');
    ov.textContent = 'Saved ✓'; ov.disabled = true;
  });
}
document.getElementById('fdMoreBtn').addEventListener('click', (ev) => {
  ev.stopPropagation();
  document.getElementById('fdMoreMenu').classList.toggle('open');
});
document.addEventListener('click', (ev) => {
  const menu = document.getElementById('fdMoreMenu');
  if (menu.classList.contains('open') && !ev.target.closest('.fd-more-wrap')) menu.classList.remove('open');
});


// ── Edit nutrition (unlock the tiles, correct values, save them to the local database) ─────────
let fdEditing = false;

function fdBeginEdit() {
  fdEditing = true;
  updateFdMacros();
  document.getElementById('fdEditNutri').textContent = '💾 Save nutrition';
  document.getElementById('fdEditCancel').style.display = '';
}
function fdEndEdit() {
  fdEditing = false;
  document.getElementById('fdEditNutri').textContent = '✎ Edit nutrition';
  document.getElementById('fdEditCancel').style.display = 'none';
  updateFdMacros();
}

async function fdSaveNutrition() {
  const item = fdContext.item;
  const num = id => { const v = document.getElementById(id).value; return v === '' ? null : parseFloat(v); };
  const T = { kcal: num('fdEdKcal'), prot: num('fdEdProt'), fibre: num('fdEdFibre'), sugar: num('fdEdSugar'), carbs: num('fdEdCarbs'), fat: num('fdEdFat') };
  const t0 = fdComputeTotals();
  const grams = t0.servG;              // grams these totals describe (serving × quantity)
  if (T.kcal == null) { alert('Calories are required.'); return; }
  if (!grams) { alert('Set a serving size in grams first so the values can be saved per 100g.'); return; }
  const per100 = v => v == null ? null : Math.round(v / grams * 100 * 10) / 10;
  const res = await fetch('/nutrition/api/food-nutrition', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({
      name: item.name || item.foodName, brand: item.brand || null, barcode: item.barcode || null,
      kcal_per_100g: per100(T.kcal), protein_per_100g: per100(T.prot), carbs_per_100g: per100(T.carbs),
      fat_per_100g: per100(T.fat), fibre_per_100g: per100(T.fibre),
      serving_g: parseFloat(document.getElementById('fdServingG').value) || null,
      image_url: item.image_url || item.imageUrl || null,
    }),
  });
  if (!res.ok) { alert('Could not save — try again.'); return; }
  // Reflect the correction in the open card
  const qty = t0.qty || 1;
  if (fdContext.mode === 'per100') {
    Object.assign(item, { kcal_per_100g: per100(T.kcal), protein_per_100g: per100(T.prot), carbs_per_100g: per100(T.carbs),
                          fat_per_100g: per100(T.fat), fibre_per_100g: per100(T.fibre), sugars_per_100g: per100(T.sugar) });
  } else {
    Object.assign(item, { calories: T.kcal / qty, protein: T.prot == null ? null : T.prot / qty, carbs: T.carbs == null ? null : T.carbs / qty,
                          fat: T.fat == null ? null : T.fat / qty, fibre: T.fibre == null ? null : T.fibre / qty, sugar: T.sugar == null ? null : T.sugar / qty,
                          servingG: grams / qty });
  }
  fdEndEdit();
  if (fdContext.target === 'editlog') await fdSaveEntry();   // also correct the diary entry itself
  const b = document.getElementById('fdEditNutri');
  b.textContent = '✓ Saved to your database'; setTimeout(() => { if (!fdEditing) b.textContent = '✎ Edit nutrition'; }, 2500);
}
document.getElementById('fdEditNutri').addEventListener('click', () => fdEditing ? fdSaveNutrition() : fdBeginEdit());
document.getElementById('fdEditCancel').addEventListener('click', fdEndEdit);

// ── Update photo ──────────────────────────────────────────────────────
function fdFoodRef() {
  const it = fdContext.item;
  return { name: it.name || it.foodName, brand: it.brand || '', barcode: it.barcode || '' };
}
function openPhotoPicker() {
  const ref = fdFoodRef();
  const cleanName = ref.name.replace(/\(.*?\)/g, '').replace(/\b\d+(\.\d+)?\s*(x\s*\d+\s*)?(kg|g|ml|l)\b/gi, '').replace(/\s+/g, ' ').trim();
  // Lead with the brand / supermarket (the green line above the name) unless the name already has it
  document.getElementById('phTerms').value =
    (ref.brand && !cleanName.toLowerCase().includes(ref.brand.toLowerCase()) ? ref.brand + ' ' : '') + cleanName;
  document.getElementById('phGrid').innerHTML = '';
  document.getElementById('phStatus').textContent = '';
  document.getElementById('photoModal').classList.add('open');
  searchPhotos(true);
}
async function searchPhotos(auto) {
  const ref = fdFoodRef();
  const q = document.getElementById('phTerms').value.trim();
  const st = document.getElementById('phStatus');
  st.textContent = 'Searching…';
  document.getElementById('phGrid').innerHTML = '';
  const params = new URLSearchParams({ name: ref.name, brand: ref.brand });
  // First search uses every relevant term the server derives; an edited box searches just what was typed
  if (!auto) params.set('q', q);
  try {
    const list = await (await fetch('/nutrition/api/image-search?' + params)).json();
    st.textContent = list.length ? 'Tap the right one' : 'No photos found — try different words, or take your own.';
    document.getElementById('phGrid').innerHTML = list.map((c, i) => `
      <button class="ph-cell" data-i="${i}" title="${escHtml(c.title)}">
        <img src="/nutrition/api/image?url=${encodeURIComponent(c.url)}" loading="lazy" data-error="photoCellMissing(this)">
        <span>${escHtml(c.source)}</span>
      </button>`).join('');
    window._phList = list;
  } catch { st.textContent = 'Search failed — check connection.'; }
}
async function applyPhoto(url) {
  const st = document.getElementById('phStatus');
  st.textContent = 'Saving…';
  const r = await fetch('/nutrition/api/food-image', { method: 'POST', headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({ ...fdFoodRef(), url }) });
  finishPhoto(r, st);
}
async function uploadPhoto(file) {
  const st = document.getElementById('phStatus');
  st.textContent = 'Saving…';
  const fd = new FormData(); const ref = fdFoodRef();
  fd.append('photo', file); fd.append('name', ref.name); fd.append('brand', ref.brand); fd.append('barcode', ref.barcode);
  finishPhoto(await fetch('/nutrition/api/food-image/upload', { method: 'POST', body: fd }), st);
}
async function finishPhoto(r, st) {
  const d = await r.json().catch(() => ({}));
  if (!r.ok) { st.textContent = '✗ ' + (d.error || 'Could not save'); return; }
  const it = fdContext.item; it.image_url = it.imageUrl = d.image_url;
  document.getElementById('fdPhoto').innerHTML = `<img src="/nutrition/api/image?url=${encodeURIComponent(d.image_url)}">`;
  document.getElementById('photoModal').classList.remove('open');
  loadDay();
}
document.getElementById('fdPhotoBtn').addEventListener('click', openPhotoPicker);
document.getElementById('closePhoto').addEventListener('click', () => document.getElementById('photoModal').classList.remove('open'));
document.getElementById('phGo').addEventListener('click', () => searchPhotos(false));
document.getElementById('phTerms').addEventListener('keydown', e => { if (e.key === 'Enter') searchPhotos(false); });
document.getElementById('phGrid').addEventListener('click', e => {
  const cell = e.target.closest('.ph-cell'); if (cell) applyPhoto(window._phList[+cell.dataset.i].url);
});
document.getElementById('phFile').addEventListener('change', e => { if (e.target.files[0]) uploadPhoto(e.target.files[0]); });


// ── My Foods (create/edit) ───────────────────────────────────────────
function renderMfPhotoPreview() {
  const wrap = document.getElementById('mfPhotoPreview');
  const box  = document.getElementById('mfPhotoBox');
  if (mfImageUrl) {
    box.innerHTML = `<img src="/nutrition/api/image?url=${encodeURIComponent(mfImageUrl)}" style="width:100%; height:100%; object-fit:cover;">`;
    wrap.style.display = '';
  } else {
    wrap.style.display = 'none';
  }
}

function openMyFoodModal(existing) {
  editingMyFoodId = existing ? existing.id : null;
  document.getElementById('mfTitle').textContent = existing ? 'Edit food' : 'Create food';
  document.getElementById('mfName').value     = existing ? existing.name : '';
  document.getElementById('mfBrand').value    = existing ? (existing.brand || '') : '';
  document.getElementById('mfKcal').value     = existing && existing.kcal_per_100g    != null ? existing.kcal_per_100g    : '';
  document.getElementById('mfServingG').value = existing && existing.serving_g        != null ? existing.serving_g        : '';
  document.getElementById('mfProtein').value  = existing && existing.protein_per_100g != null ? existing.protein_per_100g : '';
  document.getElementById('mfCarbs').value    = existing && existing.carbs_per_100g   != null ? existing.carbs_per_100g   : '';
  document.getElementById('mfFat').value      = existing && existing.fat_per_100g     != null ? existing.fat_per_100g     : '';
  mfImageUrl = existing ? (existing.image_url || null) : null;
  renderMfPhotoPreview();
  document.getElementById('findFoodModal').classList.remove('open');
  document.getElementById('myFoodModal').classList.add('open');
  setTimeout(() => document.getElementById('mfName').focus(), 120);
}

document.getElementById('mfName').addEventListener('blur', async () => {
  if (mfImageUrl) return;
  const name = document.getElementById('mfName').value.trim();
  if (!name) return;
  try {
    const r = await fetch(`/nutrition/api/stock-image?name=${encodeURIComponent(name)}`);
    const d = await r.json();
    if (d.image_url) { mfImageUrl = d.image_url; renderMfPhotoPreview(); }
  } catch {}
});

document.getElementById('closeMyFood').addEventListener('click',  () => document.getElementById('myFoodModal').classList.remove('open'));
document.getElementById('cancelMyFood').addEventListener('click', () => document.getElementById('myFoodModal').classList.remove('open'));

document.getElementById('saveMyFood').addEventListener('click', async () => {
  const name = document.getElementById('mfName').value.trim();
  const kcal = parseFloat(document.getElementById('mfKcal').value);
  if (!name || isNaN(kcal)) { alert('Name and calories (per 100g) are required.'); return; }
  const payload = {
    name, brand: document.getElementById('mfBrand').value.trim() || null,
    kcal_per_100g: kcal,
    protein_per_100g: parseFloat(document.getElementById('mfProtein').value)  || null,
    carbs_per_100g:   parseFloat(document.getElementById('mfCarbs').value)    || null,
    fat_per_100g:     parseFloat(document.getElementById('mfFat').value)     || null,
    serving_g:        parseFloat(document.getElementById('mfServingG').value) || null,
    image_url: mfImageUrl,
  };
  if (editingMyFoodId) {
    await fetch(`/nutrition/api/my-foods/${editingMyFoodId}`, {method:'PUT', headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload)});
  } else {
    await fetch('/nutrition/api/my-foods', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload)});
  }
  document.getElementById('myFoodModal').classList.remove('open');
  document.getElementById('findFoodModal').classList.add('open');
  switchFfTab('myfoods');
});

// ── Scanner (full-screen; native BarcodeDetector with html5-qrcode fallback) ──
const scanModal   = document.getElementById('scanModal');
const scannerView = document.getElementById('scannerView');
let nativeStream = null;
let scanHandled  = false;

function openScanner() {
  document.getElementById('scanModalTitle').textContent = 'Scan a barcode';
  document.getElementById('scanHint').textContent = 'Point camera at barcode (EAN-13 / UPC)';
  document.getElementById('scanHint').style.display = '';
  scannerView.style.display = '';
  scanModal.classList.add('open', 'scanning');
  startScan();
}
function closeScanner() { stopScan(); scanModal.classList.remove('open', 'scanning'); }
document.getElementById('closeScan').addEventListener('click', closeScanner);

function startScan() {
  stopScan();
  scanHandled = false;
  if ('BarcodeDetector' in window) startNativeScan();
  else startQrcodeScan();
}

async function startNativeScan() {
  try {
    const supported = await BarcodeDetector.getSupportedFormats();
    const wanted = ['ean_13','ean_8','upc_a','upc_e','code_128'].filter(f => supported.includes(f));
    const detector = new BarcodeDetector({formats: wanted.length ? wanted : undefined});
    const video = document.createElement('video');
    video.setAttribute('playsinline', '');
    video.setAttribute('muted', '');
    video.style.cssText = 'width:100%; display:block;';
    scannerView.innerHTML = '';
    scannerView.appendChild(video);
    nativeStream = await navigator.mediaDevices.getUserMedia({video:{facingMode:'environment'}});
    video.srcObject = nativeStream;
    await video.play();
    const timer = setInterval(async () => {
      if (scanHandled) return;
      try {
        const codes = await detector.detect(video);
        if (codes.length) onScanSuccess(codes[0].rawValue);
      } catch {}
    }, 350);
    scanner = {native:true, timer};
  } catch (err) {
    startQrcodeScan();
  }
}

function startQrcodeScan() {
  scannerView.innerHTML = '';
  scanner = new Html5Qrcode('scannerView');
  scanner.start({facingMode:'environment'}, {
    fps:10, qrbox:{width:240,height:110},
    formatsToSupport:[
      Html5QrcodeSupportedFormats.EAN_13, Html5QrcodeSupportedFormats.EAN_8,
      Html5QrcodeSupportedFormats.UPC_A,  Html5QrcodeSupportedFormats.UPC_E,
      Html5QrcodeSupportedFormats.CODE_128,
    ]
  }, onScanSuccess).catch(err => {
    document.getElementById('scanHint').textContent = 'Camera error: '+err;
  });
}

function stopScan() {
  if (scanner && scanner.native) {
    clearInterval(scanner.timer);
    if (nativeStream) { nativeStream.getTracks().forEach(t=>t.stop()); nativeStream=null; }
  } else if (scanner) {
    scanner.stop().catch(()=>{});
  }
  scanner = null;
}

async function onScanSuccess(code) {
  if (scanHandled) return;
  scanHandled = true;
  stopScan();
  document.getElementById('scanHint').textContent = 'Looking up…';
  scannerView.style.display = 'none';
  try {
    const r = await fetch(`/nutrition/api/lookup/${encodeURIComponent(code)}`);
    const p = await r.json();
    if (!r.ok || p.error) throw new Error('not_found');
    p.barcode = code;
    scanModal.classList.remove('open', 'scanning');
    openFoodDetail(p, {mode:'per100', target: ffPickMode === 'buildmeal' ? 'buildmeal' : 'log', sourceKind:'search'});
  } catch {
    scanModal.classList.remove('open', 'scanning');
    openManual(`Barcode ${code} (not found)`);
  }
}

// ── Manual entry ──────────────────────────────────────────────────────
document.getElementById('btnManual').addEventListener('click', () => { currentMealType=guessMealType(); openManual(''); });
// ── Drinks: alcohol units ─────────────────────────────────────────────
const DRINKS = [
  ['Pint of lager', 568, 4.5], ['Pint of bitter / ale', 568, 4.2], ['Pint of cider', 568, 4.5], ['Half pint', 284, 4.5],
  ['Bottle of beer', 330, 5], ['Can of beer', 440, 4.5], ['Small wine (125 ml)', 125, 13], ['Medium wine (175 ml)', 175, 13],
  ['Large wine (250 ml)', 250, 13], ['Glass of prosecco', 125, 11], ['Single spirit (25 ml)', 25, 40], ['Double spirit (50 ml)', 50, 40],
];
const drUnits = () => { const q = parseFloat(document.getElementById('drQty').value) || 1, ml = parseFloat(document.getElementById('drMl').value) || 0, a = parseFloat(document.getElementById('drAbv').value) || 0; return ml * a / 1000 * q; };
function drRecalc(fromPreset) {
  const q = parseFloat(document.getElementById('drQty').value) || 1, ml = parseFloat(document.getElementById('drMl').value) || 0, a = parseFloat(document.getElementById('drAbv').value) || 0;
  const eachUnits = ml * a / 1000;
  if (fromPreset !== 'kcal') document.getElementById('drKcal').value = Math.round(eachUnits * 55.2) || '';
  const total = eachUnits * q;
  document.getElementById('drSummary').textContent = total ? `${Math.round(total * 10) / 10} units` + (q > 1 ? ` (${Math.round(eachUnits * 10) / 10} each)` : '') : '';
}
function openDrink() {
  const box = document.getElementById('drPresets');
  box.innerHTML = DRINKS.map((d, i) => `<button class="btn btn-secondary" data-i="${i}">${d[0]}<small>${d[1]} ml · ${d[2]}% · ${Math.round(d[1] * d[2]) / 1000} u</small></button>`).join('');
  box.querySelectorAll('button').forEach(b => b.addEventListener('click', () => {
    const d = DRINKS[+b.dataset.i];
    document.getElementById('drName').value = d[0].replace(/ \(.*\)/, ''); document.getElementById('drMl').value = d[1]; document.getElementById('drAbv').value = d[2]; document.getElementById('drQty').value = 1;
    drRecalc();
  }));
  ['drQty', 'drMl', 'drAbv'].forEach(id => { document.getElementById(id).value = id === 'drQty' ? 1 : ''; });
  document.getElementById('drName').value = ''; document.getElementById('drKcal').value = ''; document.getElementById('drSummary').textContent = '';
  document.getElementById('drMeal').innerHTML = mealTypeOptions(guessMealType());
  document.getElementById('drinkModal').classList.add('open');
}
document.getElementById('btnDrink').addEventListener('click', openDrink);
document.getElementById('closeDrink').addEventListener('click', () => document.getElementById('drinkModal').classList.remove('open'));
['drQty', 'drMl', 'drAbv'].forEach(id => document.getElementById(id).addEventListener('input', () => drRecalc()));
document.getElementById('drKcal').addEventListener('input', () => drRecalc('kcal'));
document.getElementById('drLog').addEventListener('click', async () => {
  const q = Math.max(1, parseFloat(document.getElementById('drQty').value) || 1), ml = parseFloat(document.getElementById('drMl').value), a = parseFloat(document.getElementById('drAbv').value);
  const name = document.getElementById('drName').value.trim() || 'Drink';
  if (!(ml > 0) || !(a > 0)) { alert('Pick a drink, or enter its size (ml) and strength (% ABV).'); return; }
  const kcal = parseFloat(document.getElementById('drKcal').value);
  await postLog({ name: q > 1 ? `${name} x${q}` : name, calories: isNaN(kcal) ? Math.round(ml * a / 1000 * 55.2 * q) : kcal * q, protein: 0, carbs: null, fat: 0,
                  serving_g: ml * q, quantity: 1, alcohol_units: Math.round(ml * a / 1000 * q * 100) / 100, meal_type: document.getElementById('drMeal').value, source: 'drink' });
  document.getElementById('drinkModal').classList.remove('open');
});

document.getElementById('closeManual').addEventListener('click',  () => document.getElementById('manualModal').classList.remove('open'));
document.getElementById('cancelManual').addEventListener('click', () => document.getElementById('manualModal').classList.remove('open'));
document.getElementById('btnAddFood').addEventListener('click', () => openFindFood(guessMealType()));

function openManual(nameHint) {
  ['mName','mKcal','mServingG','mProtein','mCarbs','mFat'].forEach(id => document.getElementById(id).value='');
  document.getElementById('mName').value = nameHint || '';
  document.getElementById('mMealType').innerHTML = mealTypeOptions(currentMealType);
  manualImageUrl = null;
  document.getElementById('manualModal').classList.add('open');
  setTimeout(() => document.getElementById('mName').focus(), 120);
}

document.getElementById('mName').addEventListener('blur', async () => {
  if (manualImageUrl) return;
  const name = document.getElementById('mName').value.trim();
  if (!name) return;
  try {
    const r = await fetch(`/nutrition/api/stock-image?name=${encodeURIComponent(name)}`);
    const d = await r.json();
    if (d.image_url) manualImageUrl = d.image_url;
  } catch {}
});

document.getElementById('saveManual').addEventListener('click', async () => {
  const name = document.getElementById('mName').value.trim();
  const kcal = parseFloat(document.getElementById('mKcal').value);
  if (!name || isNaN(kcal)) { alert('Name and calories are required.'); return; }
  await postLog({
    name, calories:kcal,
    serving_g: parseFloat(document.getElementById('mServingG').value) || null,
    protein:   parseFloat(document.getElementById('mProtein').value)  || null,
    carbs:     parseFloat(document.getElementById('mCarbs').value)    || null,
    fat:       parseFloat(document.getElementById('mFat').value)      || null,
    meal_type: document.getElementById('mMealType').value,
    source:    'manual',
    image_url: manualImageUrl,
  });
  document.getElementById('manualModal').classList.remove('open');
});


// ── Screenshot import ─────────────────────────────────────────────────
let impItems = [];
// The review's fields write straight into impItems (data-change, static/js/actions.js)
function impSet(i, key, value) { impItems[i][key] = value; }
function impNumber(i, key, value) { impItems[i][key] = value === '' ? null : parseFloat(value); }
let impShareToken = null;
let impTotals = {};
let impOverlap = 0;
let impAbort = null;
let impMode = 'diary';
let impRecipeCount = 0;

function impShow(step) {
  for (const s of ['Pick','Progress','Review']) {
    document.getElementById('impStep'+s).style.display = s === step ? '' : 'none';
    document.getElementById('impFoot'+s).style.display = s === step ? '' : 'none';
  }
  document.getElementById('impTitle').textContent =
    step === 'Review' ? 'Check before logging' : step === 'Progress' ? 'Reading…' : 'Import from screenshots';
}

function impSetMode(mode) {
  impMode = mode;
  document.querySelectorAll('.imp-mode').forEach(b => b.classList.toggle('active', b.dataset.mode === mode));
  document.getElementById('impDateWrap').style.display = mode === 'diary' ? '' : 'none';
  document.getElementById('impChooseHint').textContent =
    mode === 'diary' ? 'Pick them in order, top of the diary first' : 'Recipe pages or your recipe list — any order';
  document.getElementById('impModeHelp').textContent = mode === 'diary'
    ? 'Log a day from your other app. Recipes you have already imported get their macros filled in automatically.'
    : `Teach Headwind your recipes so diary imports can fill in their macros.${impRecipeCount ? ` ${impRecipeCount} saved so far.` : ''}`;
}
document.querySelectorAll('.imp-mode').forEach(b => b.addEventListener('click', () => impSetMode(b.dataset.mode)));

async function openImport(shareToken, mode) {
  impShareToken = shareToken || null;
  try { impRecipeCount = (await (await fetch('/nutrition/api/recipes')).json()).length; } catch { impRecipeCount = 0; }
  impSetMode(shareToken ? 'diary' : (mode || 'diary'));
  document.getElementById('impFiles').value = '';
  document.getElementById('impThumbs').innerHTML = '';
  document.getElementById('impDate').value = isoDate(currentDate);
  document.getElementById('impError').textContent = '';
  document.getElementById('impAnalyse').disabled = !impShareToken;
  impShow('Pick');
  document.getElementById('importModal').classList.add('open');
  if (impShareToken) analyseScreenshots();
}
function closeImport() {
  if (impAbort) impAbort.abort();
  document.getElementById('importModal').classList.remove('open');
}

document.getElementById('impFiles').addEventListener('change', e => {
  const files = [...e.target.files].sort((a, b) => a.name.localeCompare(b.name));
  const box = document.getElementById('impThumbs');
  box.innerHTML = '';
  files.forEach(f => {
    const img = document.createElement('img');
    img.src = URL.createObjectURL(f);
    img.onload = () => URL.revokeObjectURL(img.src);
    box.appendChild(img);
  });
  document.getElementById('impAnalyse').disabled = !files.length;
  document.getElementById('impAnalyse').textContent = files.length ? `Read ${files.length} screenshot${files.length>1?'s':''}` : 'Read screenshots';
});

function impProgress(ev) {
  // read = 0–50 %, lookup = 50–100 %
  const frac = ev.total ? ev.done / ev.total : 0;
  const pct = ev.stage === 'read' ? frac * 50 : ev.stage === 'lookup' ? 50 + frac * 40 : 95;
  document.getElementById('impBarFill').style.width = Math.round(pct) + '%';
  document.getElementById('impStage').textContent =
    ev.stage === 'read' ? (impMode === 'recipes' ? 'Reading your recipes' : 'Reading your screenshots') : ev.stage === 'lookup' ? 'Looking up macros' : 'Working out your recipes';
  document.getElementById('impStageSub').textContent = ev.total
    ? (ev.stage === 'read' ? `Screenshot ${Math.min(ev.done+1, ev.total)} of ${ev.total}` : ev.stage === 'lookup' ? `Food ${Math.min(ev.done+1, ev.total)} of ${ev.total}` : 'Using the app’s day totals')
    : '';
}

async function analyseScreenshots() {
  const files = document.getElementById('impFiles').files;
  const errEl = document.getElementById('impError');
  if (!files.length && !impShareToken) { errEl.textContent = 'Pick at least one screenshot.'; return; }
  const fd = new FormData();
  for (const f of files) fd.append('screenshots', f);
  if (impShareToken) fd.append('share_token', impShareToken);
  fd.append('mode', impMode);
  errEl.textContent = '';
  impProgress({stage:'read', done:0, total:files.length});
  impShow('Progress');
  impAbort = new AbortController();
  try {
    const r = await fetch('/nutrition/api/import-screenshot', {method:'POST', body:fd, signal:impAbort.signal});
    if (!r.ok) { const d = await r.json().catch(() => ({})); throw new Error(d.error || 'Import failed'); }
    const reader = r.body.getReader(), dec = new TextDecoder();
    let buf = '', result = null;
    while (true) {
      const {done, value} = await reader.read();
      if (done) break;
      buf += dec.decode(value, {stream:true});
      let nl;
      while ((nl = buf.indexOf('\n')) >= 0) {
        const line = buf.slice(0, nl).trim(); buf = buf.slice(nl + 1);
        if (!line) continue;
        const ev = JSON.parse(line);
        if (ev.type === 'progress') impProgress(ev);
        else if (ev.type === 'error') throw new Error(ev.error);
        else if (ev.type === 'result') result = ev;
      }
    }
    if (!result) throw new Error('The import stopped unexpectedly — try again.');
    impShareToken = null;
    document.getElementById('impBarFill').style.width = '100%';
    await showImportReview(result);
  } catch (e) {
    if (e.name === 'AbortError') return;
    errEl.textContent = e.message;
    impShow('Pick');
    document.getElementById('impAnalyse').disabled = !document.getElementById('impFiles').files.length;
  } finally {
    impAbort = null;
  }
}

function renderRecipeReview() {
  document.getElementById('impChips').innerHTML = '';
  document.getElementById('impFill').style.display = 'none';
  const sel = impItems.filter(i => i.on).length;
  document.getElementById('impNote').textContent = `${sel} of ${impItems.length} recipes selected`;
  document.getElementById('impList').innerHTML = impItems.map((it, i) => `
    <div class="imp-card ${it.on ? '' : 'off'}">
      <div class="imp-row">
        <input type="checkbox" ${it.on ? 'checked' : ''} data-change="impSet(${i}, 'on', this.checked); renderRecipeReview()">
        <input type="text" value="${escHtml(it.name).replace(/"/g,'&quot;')}" data-change="impSet(${i}, 'name', this.value)">
      </div>
      <div class="imp-macros">
        ${[['calories','kcal'],['protein','P g'],['carbs','C g'],['fat','F g']].map(([k, lbl]) => `
          <div><label>${lbl}</label>
          <input type="number" inputmode="decimal" step="0.1" value="${it[k] ?? ''}"
                 data-change="impNumber(${i}, '${k}', this.value)"></div>`).join('')}
      </div>
      ${it.exists ? '<div class="imp-lookup">Already in your recipe book — saving updates it</div>' : ''}
      ${it.protein == null || it.carbs == null || it.fat == null ? '<div class="imp-lookup">Macros missing — fill them in or it won’t be used for lookups</div>' : ''}
    </div>`).join('') || '<p>No recipes found in those screenshots.</p>';
  const btn = document.getElementById('impSave');
  btn.disabled = !sel;
  btn.textContent = sel ? `Save ${sel} recipe${sel>1?'s':''}` : 'Nothing selected';
}

async function showImportReview(d) {
  if (impMode === 'recipes') {
    impItems = (d.recipes || []).map(r => ({...r, on: true}));
    renderRecipeReview();
    impShow('Review');
    return;
  }
  const date = document.getElementById('impDate').value || isoDate(currentDate);
  // Flag items that look already logged on that day so re-importing doesn't double up
  let existing = [];
  try { existing = (await (await fetch(`/nutrition/api/day/${date}`)).json()).entries || []; } catch {}
  impItems = d.items.map(it => ({
    ...it,
    dup: existing.some(e => (e.foodName||'').toLowerCase() === it.name.toLowerCase()
                         && Math.abs((e.calories||0) - it.calories) < 2),
  }));
  impItems.forEach(it => it.on = !it.dup);
  impTotals = d.day_totals || {};
  impOverlap = d.overlap_dropped || 0;
  renderImportReview();
  impShow('Review');
  document.getElementById('impStepReview').scrollTop = 0;
}

function impLookupNote(it) {
  if (it.dup) return '<div class="imp-lookup">Looks already logged — unticked</div>';
  if (it.filled) return '<div class="imp-lookup">Macros estimated from the day total</div>';
  const l = it.lookup;
  if (l && l.source === 'day-total') return `<div class="imp-lookup">${l.confidence === 'estimate' && l.match.startsWith('exact') ? '✓' : '≈'} Macros ${escHtml(l.match)} — edit if you know them</div>`;
  if (!l) return it.protein == null ? '<div class="imp-lookup">No macro match — enter them, or use the day-total fill</div>' : '';
  const how = l.source === 'history' ? 'from your earlier log' : l.source === 'recipe' ? 'from your recipe: ' + escHtml(l.match) : 'matched: ' + escHtml(l.match);
  return `<div class="imp-lookup">${l.confidence === 'high' ? '✓' : '≈'} Macros ${how}${l.confidence === 'medium' ? ' — check it’s the right product' : ''}</div>`;
}

function renderImportReview() {
  document.getElementById('impList').innerHTML = impItems.map((it, i) => `
    <div class="imp-card ${it.on ? '' : 'off'}">
      <div class="imp-row">
        <input type="checkbox" ${it.on ? 'checked' : ''} data-change="impSet(${i}, 'on', this.checked); renderImportReview()">
        <input type="text" value="${escHtml(it.name).replace(/"/g,'&quot;')}" data-change="impSet(${i}, 'name', this.value)">
      </div>
      <select data-change="impSet(${i}, 'meal_type', this.value)">${mealTypeOptions(it.meal_type === 'uncategorised' ? currentMealType : it.meal_type)}</select>
      <div class="imp-macros">
        ${[['calories','kcal'],['protein','P g'],['carbs','C g'],['fat','F g']].map(([k, lbl]) => `
          <div><label>${lbl}</label>
          <input type="number" inputmode="decimal" step="0.1" value="${it[k] ?? ''}"
                 data-change="impNumber(${i}, '${k}', this.value); impSet(${i}, 'userEdited', true); renderImportSummary()"></div>`).join('')}
      </div>
      ${impLookupNote(it)}
    </div>`).join('') || '<p>No food items found in those screenshots.</p>';
  renderImportSummary();
}

function fillFromDayTotals() {
  const keys = ['protein','carbs','fat'];
  const sel = impItems.filter(i => i.on);
  const unmatched = sel.filter(i => keys.every(k => i[k] == null));
  const kcalSum = unmatched.reduce((a,i) => a + (i.calories||0), 0);
  if (!unmatched.length || !kcalSum) return;
  for (const k of keys) {
    const known = sel.reduce((a,i) => a + (i[k]||0), 0);
    const residual = Math.max(0, (impTotals[k] ?? 0) - known);
    unmatched.forEach(i => { i[k] = Math.round(residual * (i.calories / kcalSum) * 10) / 10; });
  }
  unmatched.forEach(i => { i.filled = true; });
  renderImportReview();
}

function renderImportSummary() {
  const sel = impItems.filter(i => i.on);
  const keys = ['calories','protein','carbs','fat'];
  const sums = keys.map(k => Math.round(sel.reduce((a,i) => a + (i[k]||0), 0)));
  const chip = (label, sum, app, tol) => {
    const bad = app != null && Math.abs(app - sum) > tol;
    return `<span class="imp-chip ${bad ? 'warn' : ''}">${label} ${sum}${app != null ? ` / ${Math.round(app)}` : ''}</span>`;
  };
  document.getElementById('impChips').innerHTML =
    chip('kcal', sums[0], impTotals.calories, 5) + chip('P', sums[1], impTotals.protein, 8) +
    chip('C', sums[2], impTotals.carbs, 8) + chip('F', sums[3], impTotals.fat, 5);
  const hasTotals = keys.some(k => impTotals[k] != null);
  document.getElementById('impNote').textContent =
    `${sel.length} of ${impItems.length} selected` + (hasTotals ? ' · yours / the app’s day total' : '') +
    (impOverlap ? ` · ${impOverlap} overlapping item${impOverlap>1?'s':''} merged` : '');
  const canFill = ['protein','carbs','fat'].every(k => impTotals[k] != null) &&
                  sel.some(i => ['protein','carbs','fat'].every(k => i[k] == null));
  document.getElementById('impFill').style.display = canFill ? '' : 'none';
  const btn = document.getElementById('impSave');
  btn.disabled = !sel.length;
  btn.textContent = sel.length ? `Log ${sel.length} item${sel.length>1?'s':''} · ${sums[0]} kcal` : 'Nothing selected';
}

document.getElementById('btnImportShot').addEventListener('click', () => openImport());
document.getElementById('closeImport').addEventListener('click', closeImport);
document.getElementById('impCancel').addEventListener('click', closeImport);
document.getElementById('impAbort').addEventListener('click', () => { if (impAbort) impAbort.abort(); impShow('Pick'); });
document.getElementById('impBack').addEventListener('click', () => impShow('Pick'));
document.getElementById('impAnalyse').addEventListener('click', analyseScreenshots);
document.getElementById('impFill').addEventListener('click', fillFromDayTotals);
document.getElementById('impSave').addEventListener('click', async () => {
  if (impMode === 'recipes') {
    const recipes = impItems.filter(i => i.on && i.name && i.calories);
    const b = document.getElementById('impSave');
    b.disabled = true; b.textContent = 'Saving…';
    const r = await fetch('/nutrition/api/recipes', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({recipes})});
    if (!r.ok) { alert('Could not save — try again.'); renderRecipeReview(); return; }
    impRecipeCount += recipes.filter(x => !x.exists).length;
    impSetMode('recipes');
    impShow('Pick');
    document.getElementById('impFiles').value = ''; document.getElementById('impThumbs').innerHTML = '';
    document.getElementById('impAnalyse').disabled = true; document.getElementById('impAnalyse').textContent = 'Read screenshots';
    document.getElementById('impError').textContent = '';
    document.getElementById('impModeHelp').textContent = `✓ Saved ${recipes.length} recipe${recipes.length>1?'s':''} — ${impRecipeCount} in your book. Add more, or switch to Food diary.`;
    return;
  }
  const items = impItems.filter(i => i.on && i.name && i.calories != null);
  const date = document.getElementById('impDate').value || isoDate(currentDate);
  const btn = document.getElementById('impSave');
  btn.disabled = true; btn.textContent = 'Saving…';
  const r = await fetch('/nutrition/api/log-batch', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({date, items: items.map(i => ({...i, est: !i.userEdited && ((i.lookup && i.lookup.source === 'day-total' && !i.lookup.match.startsWith('exact')) || i.filled)}))}),
  });
  if (!r.ok) { alert('Could not save — try again.'); renderImportSummary(); return; }
  closeImport();
  currentDate = new Date(date + 'T12:00:00');
  loadDay();
});

// Opened via the Android share sheet: /nutrition/?import=<token>
(function() {
  const token = new URLSearchParams(location.search).get('import');
  if (token) { history.replaceState(null, '', location.pathname); openImport(token); }
})();

// ── Weight card + weigh-in modal ────────────────────────────────────────
const LB_PER_KG = 2.2046226218488;

function kgToStlb(kg) {
  const totalLb = kg * LB_PER_KG;
  const stone = Math.floor(totalLb / 14);
  return { stone, lb: totalLb - stone * 14 };
}

function formatWeightJs(kg, unit) {
  if (kg == null) return '—';
  if (unit === 'kg') return kg.toFixed(1) + ' kg';
  let { stone, lb } = kgToStlb(kg);
  let lbR = Math.round(lb * 10) / 10;
  if (lbR >= 14) { stone += 1; lbR = Math.round((lbR - 14) * 10) / 10; }
  return `${stone}st ${lbR.toFixed(1)}lb`;
}

function renderWeightCard(weight) {
  weight = weight || {};
  weightUnit = weight.unit || weightUnit;
  const hasData = weight.trend != null;
  document.getElementById('weightEmpty').style.display   = hasData ? 'none' : '';
  document.getElementById('weightHasData').style.display = hasData ? '' : 'none';
  if (hasData) {
    document.getElementById('weightTrendVal').textContent = formatWeightJs(weight.trend, weightUnit);
    const rawWrap = document.getElementById('weightRawWrap');
    if (weight.raw != null) {
      rawWrap.style.display = '';
      document.getElementById('weightRawVal').textContent = formatWeightJs(weight.raw, weightUnit);
      document.getElementById('weightSrc').textContent = weight.scale ? ' · ⚖ scale' : '';
    } else {
      rawWrap.style.display = 'none';
    }
    const fatEl = document.getElementById('weightFat');
    fatEl.style.display = weight.bodyFat != null ? '' : 'none';
    fatEl.textContent = weight.bodyFat != null ? `· ${weight.bodyFat}% body fat` : '';
  }
}

let saveWeighInArmed = false;

function openWeighInModal() {
  document.getElementById('wiDate').value = isoDate(currentDate);
  document.getElementById('wiStlbRow').style.display = weightUnit === 'kg' ? 'none' : '';
  document.getElementById('wiKgRow').style.display   = weightUnit === 'kg' ? '' : 'none';
  document.getElementById('wiStone').value = '';
  document.getElementById('wiLb').value = '';
  document.getElementById('wiKg').value = '';
  document.getElementById('wiExistingWarn').style.display = 'none';
  saveWeighInArmed = false;
  document.getElementById('weighInModal').classList.add('open');
}
document.getElementById('btnWeighIn').addEventListener('click', openWeighInModal);
document.getElementById('closeWeighIn').addEventListener('click',  () => document.getElementById('weighInModal').classList.remove('open'));
document.getElementById('cancelWeighIn').addEventListener('click', () => document.getElementById('weighInModal').classList.remove('open'));
document.getElementById('wiDate').addEventListener('change', () => {
  saveWeighInArmed = false;
  document.getElementById('wiExistingWarn').style.display = 'none';
});

async function submitWeighIn() {
  const payload = { date: document.getElementById('wiDate').value, force: saveWeighInArmed };
  if (weightUnit === 'kg') {
    payload.unit = 'kg';
    payload.kg = parseFloat(document.getElementById('wiKg').value);
  } else {
    payload.unit = 'stlb';
    payload.stone = parseFloat(document.getElementById('wiStone').value) || 0;
    payload.lb    = parseFloat(document.getElementById('wiLb').value) || 0;
  }
  if (!payload.date || (payload.unit === 'kg' ? !payload.kg : !(payload.stone || payload.lb))) return;

  const r = await fetch('/nutrition/api/weight', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  const data = await r.json();
  if (data.exists) {
    const warn = document.getElementById('wiExistingWarn');
    warn.style.display = '';
    warn.textContent = `Already logged ${formatWeightJs(data.existingKg, weightUnit)} on this date. Tap Save again to replace it.`;
    saveWeighInArmed = true;
    return;
  }
  document.getElementById('weighInModal').classList.remove('open');
  saveWeighInArmed = false;
  loadDay();
}
document.getElementById('saveWeighIn').addEventListener('click', submitWeighIn);

// ── Service worker ────────────────────────────────────────────────────
if ('serviceWorker' in navigator) {
  navigator.serviceWorker.register('/static/nutrition-sw.js').catch(()=>{});
}

// ── Init ──────────────────────────────────────────────────────────────
loadDay();

// Pull any new scale readings from Home Assistant whenever the app is opened or comes back to the foreground
async function refreshScale() {
  try {
    const d = await (await fetch('/nutrition/api/weight/refresh', {method:'POST'})).json();
    if (d.changed) loadDay();
  } catch {}
}
refreshScale();
document.addEventListener('visibilitychange', () => { if (document.visibilityState === 'visible') refreshScale(); });
