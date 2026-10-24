# The web UI's shared pieces

Every page is built from the same few pieces in `static/css/style.css`. Use them rather than styling a page on its own, so the same thing looks and behaves the same everywhere, and light mode keeps working.

## Colours

- Every colour is a variable on `:root` in `style.css`. Write `var(--x)` in templates, inline styles and `<style>` blocks; never a hex or `rgb()` value. `tests/test_ui_colours.py` fails on a literal colour, or on a `var(--x)` that isn't defined.
- Chart.js, Leaflet, canvas and SVG attributes can't read `var(--x)`, so they take `cssVar('--x')` (or `cssVar('--x', 0.15)` for a see-through one) from `templates/base.html`. Anything that ends up in a `style` attribute keeps `var(--x)`.
- Pick by meaning, not by look:
  - **Surfaces:** `--main-bg`, `--card-bg`, `--inset-bg` (a well inside a card), `--raised-bg` (secondary buttons, badges), `--field-bg`, `--hover-tint`, `--overlay`.
  - **Lines:** `--border`, `--border-strong`, `--divider` (between the rows of a list).
  - **Text:** `--text`, `--text-strong`, `--text-soft`, `--text-muted`, and `--on-accent` on a solid fill.
  - **Status:** `--accent`, `--success`, `--warning`, `--due`, `--danger` and `--info`. Each has a `-soft` background, a `-line` border and, for the four main ones, a `-text` readable on the soft background.
  - **Data:** `--c-red` … `--c-grey` give one hue per series, sport or nutrient; `--heat-0` … `--heat-4` are the calendar heatmap.
- A colour that comes from Python (sport groups, segment difficulty) is a variable name, such as `'--accent'` or `'var(--info)'`, never a value.

## Buttons

| Class | Use |
|---|---|
| `btn btn-primary` | The one action the page, form or dialog exists for: Save, Add, Create, Import. One per form; on a page, the action in its head. |
| `btn btn-secondary` | Everything else. |
| `btn btn-secondary active` | The chosen one of a row of options (a sport, a period). Picked, not an action, so not orange. |
| `btn btn-danger` | A page's own Delete, in its head. |
| `btn btn-danger-quiet` | Delete, Remove or Revoke in a row, or beside a Save. |
| `btn-sm` | In a table row, a card header or a toolbar. |
| `btn-block` | Full width, for the one action of a narrow form or dialog. |

Words: **Add …** creates something, **Save** stores changes to it, **Delete** gets rid of it for good, **Remove** takes it off something without deleting it, and **Retire** / **Bring back** hide gear that's no longer used, keeping its history.

## Confirmations

Every `confirm()` names the thing, then says what goes with it and what stays, and ends with "This cannot be undone." when that's true:

> Delete Stumpjumper, its parts and its service log? Its rides stay, but will have no bike. This cannot be undone.

Inside an `onsubmit="…"` attribute the text is in single quotes, so write "cannot" and "will not", not "can't" and "won't".

## Page head

The topbar holds the title, the page's actions (`{% block topbar_actions %}`) and the way back. The way back is the page above this one, named before the title (Gear › Stumpjumper), set with:

```jinja
{% block parent %}<a href="{{ url_for('gear.index') }}">Gear</a>{% endblock %}
```

Don't add "← Back" buttons; a form's **Cancel** stays.

## Text

- `.hint` is helper text: what a field, card or list is for, or what happens next. It's the one class for it; `.text-muted` is the old name.
- `.card-title` is the small upper-case heading of a card.

## Empty states

A list or page with nothing in it yet gets an icon, one line saying what goes there, a hint on how to get some, and the action:

```html
<div class="card empty-state">
  <div class="empty-icon">🏁</div>
  <h3>No segments yet</h3>
  <p>Open any ride that has a map, then click <strong>Create Segment</strong>.</p>
  <a class="btn btn-primary" href="…">…</a>
</div>
```

Inside a card that already exists, drop `card`.

## Tables

```html
<div class="table-wrap">
  <table class="table">
    <thead><tr><th>Ride</th><th class="num">Distance</th></tr></thead>
    <tbody><tr><td>…</td><td class="num">{{ a.distance | fmt_dist }}</td></tr></tbody>
  </table>
</div>
```

- `.table-compact` is for a dense table. `.flush` is for a table that runs to the edges of a card with no padding.
- `.num` is for numbers: right-aligned, in figures of equal width.
- `<tr class="grp">` is a group heading inside the body.
- Don't put padding, borders or font sizes on cells.

## Lists of activities

Every list of activities (dashboard, Activities, Workouts, a bike's, kit's or rider's page) draws its rows with the one macro in `templates/_activity_row.html`: sport icon, name, then date, distance, time, speed or pace by sport, and the climb where the sport has one.

```jinja
{% from '_activity_row.html' import activity_row %}
<div data-pick-list>{% for a in rows %}{{ activity_row(a) }}{% endfor %}</div>
```

- The query needs `id`, `name`, `sportType` (or `sport`), `startDateLocal`, `distance`, `movingTime`, `averageSpeed` and `totalElevationGain`; `riderName` / `riderAvatar` add the rider at the end.
- `date=false` where a day heading already gives the date; `more=[…]` adds figures to the second line (kcal, steps).
- `{% call activity_row(a) %}…{% endcall %}` puts controls at the end of the row, above the link. They hide while the Select bar is on.
- `gear_row(a, pickers, back)` (same file) is a row with a bike or kit picker at the end, for the "no gear" list; `a.isRide` picks which.
- Don't put activities in a table.

## Forms

One layout: the label above the field, a `.hint` below it, and an error in a `.flash.flash-error` at the top of the page or form (the route passes `error`).

```html
<div class="form-group">
  <label for="bikeName">Name</label>
  <input id="bikeName" name="name">
  <p class="hint">Shown on the Gear page and on each ride.</p>
</div>
```

- `.form-grid` lays several fields side by side, as many as fit, and one to a row on a phone. Its fields are `.form-group`s, or a `<label>` wrapping its field (`<label>Brand<input name="brand"></label>`); `.wide` takes a whole row.
- `.check` is a checkbox or radio with its words beside it: `<label class="check"><input type="checkbox"> Commute</label>`. Several in a row go in `.checks`; a group with a heading is a `<fieldset>` with a `<legend>`.
- `.form-actions` is the row of buttons at the end: the one primary action first, then Cancel and a hint.
- `details.gcard` is a card that opens, for a form that's needed now and then ("+ Add a part").
- The toolbar above a list (`.toolbar`, `.form-group-sm`) is the one smaller layout, for search and filter fields.
- Don't set font sizes, colours or margins on labels and fields.

## Chips

`.chip` is a small label on a row or card: `.chip.ok`, `.soon`, `.due`, `.overdue` for wear and status, `.chip.default` for the default bike.

## Dates and numbers

Dates go through `fmt_date` (`15 May 2026`), moments Headwind recorded itself (`datetime('now')`, UTC) through `fmt_when` (`24 Oct 2026, 14:05`, at home time), and distances, climbs, speeds and paces through the `services/units.py` filters (`fmt_dist`, `fmt_elev`, `fmt_speed`, `fmt_rate`, `dist_val` …). Page scripts use `window.UNITS`. Never slice an ISO date (`[:10]`) or write your own 1609.344.
