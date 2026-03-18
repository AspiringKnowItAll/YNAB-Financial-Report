# Phase 14 — Dashboard Redesign: Full Specification

> **Status:** In Progress — Milestones 1–3 complete; Milestone 4 next
> **Author:** Spec finalized 2026-03-17
> **Prerequisites:** Phases 12, 12.5, 13, and 13.5 must be complete (all are).

---

## Overview

Phase 14 replaces the current single static dashboard page (`/` via `app/routers/dashboard.py`) with a full multi-dashboard builder system. Users create named dashboards, populate them with configurable widgets via a WYSIWYG drag-and-drop editor, and switch between dashboards via a persistent left dock sidebar.

The existing dashboard has four hardcoded widgets (income/spending trend, category breakdown, net worth card, summary cards). Phase 14 promotes these to user-configurable widgets in a library of 17 widget types and adds the ability to create unlimited dashboards with custom layouts.

---

## Confirmed Design Decisions

1. **Multiple named dashboards** — user creates/names/deletes dashboards.
2. **Default dashboard** — user marks one as default; `/` redirects to it.
3. **Left dock** — persistent left sidebar showing all dashboard names for quick switching.
4. **WYSIWYG builder** — edit mode with gridstack.js for drag/resize/snap.
5. **Configurable column count per dashboard** — user sets the grid width (e.g., 6, 8, 12, 16, 24 columns).
6. **Dashboard-level default time period** — convenience default for new widgets; each widget still overrides freely.
7. **All filters are per-widget** — time period, included accounts (YNAB + external), excluded categories — all configured per widget, not restricted at dashboard level.
8. **All widget types user-selectable** — no forced defaults; user adds any combination.
9. **Per-dashboard custom CSS** — stored in `Dashboard.custom_css` (TEXT, nullable); injected in a `<style>` block on that dashboard's page only.
10. **Global custom CSS** — stored in `AppSettings.custom_css_enc` (LargeBinary, Fernet-encrypted like all secrets); injected in `base.html` for app-wide styling.
11. **gridstack.js** for the grid layout engine (MIT license).
12. **Reports integration** — deferred to a later milestone (M7); dashboards will eventually feed into reports.

---

## Widget Catalog

### Card Widgets

| Type key | Description |
|---|---|
| `income_card` | Total income for the configured time period |
| `spending_card` | Total spending for the configured time period |
| `net_savings_card` | Net (income - spending) for the period |
| `savings_rate_card` | Savings rate % for the period |
| `net_worth_card` | Total balance across all included accounts |

### Trend Chart Widgets

| Type key | Description |
|---|---|
| `income_spending_trend` | Income vs. spending bar/line over time |
| `net_worth_trend` | Net worth over time (line); YNAB data built from snapshots taken at each sync |
| `savings_rate_trend` | Savings rate % trend over time (line) |

### Breakdown Chart Widgets

| Type key | Description |
|---|---|
| `category_breakdown` | Spending by category (horizontal bar); shows this-period amount vs IQR-adjusted avg |
| `group_rollup` | Spending by category group (bar or donut) |
| `payee_breakdown` | Top spending payees (bar) |
| `month_over_month` | Month-by-month comparison for a selected set of categories or totals |

### Stats/Table Widgets

| Type key | Description |
|---|---|
| `category_stats_table` | Per-category table: avg / min / max / peak month |
| `account_balances_list` | List of included accounts with current balance |
| `recent_transactions` | Scrollable list of recent transactions from included accounts |

### Projection Widgets

| Type key | Description |
|---|---|
| `savings_projection` | Future savings balance at current avg savings rate (compound interest curve) |
| `investment_tracker` | Balance history + projected growth for investment/retirement accounts |

---

## DB Schema

### New table: `dashboard`

```
id              INTEGER PRIMARY KEY
name            TEXT NOT NULL
description     TEXT
is_default      BOOLEAN NOT NULL DEFAULT FALSE
grid_columns    INTEGER NOT NULL DEFAULT 12
default_time_period  TEXT  -- e.g. "last_12_months", nullable
custom_css      TEXT  -- per-dashboard CSS, nullable, NOT encrypted (single-user app)
created_at      DATETIME
updated_at      DATETIME
```

### New table: `dashboard_widget`

```
id              INTEGER PRIMARY KEY
dashboard_id    INTEGER NOT NULL REFERENCES dashboard(id) ON DELETE CASCADE
widget_type     TEXT NOT NULL  -- one of the type keys from the widget catalog
grid_x          INTEGER NOT NULL DEFAULT 0
grid_y          INTEGER NOT NULL DEFAULT 0
grid_w          INTEGER NOT NULL DEFAULT 4
grid_h          INTEGER NOT NULL DEFAULT 3
config_json     TEXT NOT NULL DEFAULT '{}'
-- config_json holds ALL per-widget options:
--   time_period, custom_start_date, custom_end_date,
--   included_account_ids (list), excluded_category_ids (list),
--   chart_type, title_override, show_legend, color_scheme, etc.
created_at      DATETIME
updated_at      DATETIME
```

### New table: `net_worth_snapshot`

```
id              INTEGER PRIMARY KEY
budget_id       TEXT NOT NULL
snapped_at      DATE NOT NULL  -- date of the sync
ynab_balance_milliunits   INTEGER NOT NULL  -- sum of on-budget YNAB accounts at time of sync
```

External account balances are already stored in `ExternalAccountBalance` from Phase 13. The `net_worth_trend` widget combines both sources.

### Modified: `app_settings`

Add columns via `apply_migrations()`:

```
custom_css_enc                    BLOB     -- global custom CSS, Fernet-encrypted, nullable
projection_expected_return_rate   REAL     -- annual expected return rate, default 0.07 (7%)
projection_retirement_target      INTEGER  -- target retirement balance in milliunits, nullable
```

All three columns added in the M1 migration. Settings UI for projection fields added in M5; global CSS UI added in M6.

---

## Routes

### HTML routes (new router: `app/routers/dashboards.py`)

| Method | Path | Description |
|---|---|---|
| `GET` | `/` | Redirect to default dashboard, or `/dashboards/new` if none exist |
| `GET` | `/dashboards` | List page (all dashboards with preview/edit/delete) |
| `GET` | `/dashboards/new` | Create new dashboard form |
| `GET` | `/dashboards/{id}` | View dashboard (live data rendering) |
| `GET` | `/dashboards/{id}/edit` | Builder/edit mode (gridstack active) |

### API routes (new router: `app/routers/api_dashboards.py` or extend `app/routers/api.py`)

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/dashboards` | Create dashboard |
| `PUT` | `/api/dashboards/{id}` | Update dashboard metadata (name, description, grid_columns, default_time_period, custom_css, is_default) |
| `DELETE` | `/api/dashboards/{id}` | Delete dashboard |
| `PUT` | `/api/dashboards/{id}/default` | Set as default (clears `is_default` on all others) |
| `PUT` | `/api/dashboards/{id}/layout` | Bulk-save all widget positions (called by gridstack on change) |
| `POST` | `/api/dashboards/{id}/widgets` | Add widget (type + initial config) |
| `PUT` | `/api/dashboards/{id}/widgets/{widget_id}` | Update widget config |
| `DELETE` | `/api/dashboards/{id}/widgets/{widget_id}` | Remove widget |
| `GET` | `/api/dashboards/{id}/widgets/{widget_id}/data` | Fetch live data for one widget (returns chart JSON or card values) |

---

## Frontend Architecture

### gridstack.js Integration

- Vendor the library into `app/static/js/vendor/gridstack/` (do not load from CDN in production).
- Preserve the MIT copyright notice in the vendored file header (see Attribution section below).
- Two modes on `/dashboards/{id}/edit`:
  - **View mode** (default): gridstack initialized as static (no drag/resize), widgets display live data.
  - **Edit mode**: toggled by "Edit Dashboard" button; gridstack becomes interactive; widgets show drag handles and resize grips; live data is replaced with widget type labels + config buttons.
- Layout changes are auto-saved to `/api/dashboards/{id}/layout` on gridstack's `change` event (debounced 500ms).

### Widget Rendering

Each widget on the dashboard page renders as a gridstack item. On page load, each widget fires a JS `fetch()` to `/api/dashboards/{id}/widgets/{widget_id}/data` and renders the result (Plotly chart or card values) into the widget container. This means:

- Each widget can have a different time period and independently fetches its data.
- A loading spinner shows until data arrives.
- Widgets can be individually refreshed without a full page reload.

### CSS Injection Order

```html
<!-- in base.html, just before </head> -->
{% if global_custom_css %}
<style id="global-custom-css">{{ global_custom_css | safe }}</style>
{% endif %}

<!-- in dashboard template, just before </head> -->
{% if dashboard.custom_css %}
<style id="dashboard-custom-css">{{ dashboard.custom_css | safe }}</style>
{% endif %}
```

Dashboard CSS is injected after global CSS so per-dashboard overrides win.

### Left Dock

- Fixed-width left sidebar (collapsed by default on small viewports, always visible on wide viewports).
- Lists all dashboard names; active dashboard highlighted.
- "New Dashboard" button at bottom.
- Rendered server-side from the full dashboard list passed to every dashboard template.

---

## Milestones

### Milestone 1 — Foundation & Navigation

**Goal:** Get the new routing, DB models, and navigation shell in place. No builder yet — just viewing.

**Files to create:**
- `app/models/dashboard.py` — `Dashboard`, `DashboardWidget`, `NetWorthSnapshot` SQLAlchemy models
- `app/routers/dashboards.py` — HTML routes
- `app/routers/api_dashboards.py` — API routes (dashboard/widget CRUD + widget data endpoint)
- `app/schemas/dashboard.py` — Pydantic schemas for API request/response
- `app/services/widget_service.py` — stub (returns placeholder; fully implemented in M3)
- `app/templates/dashboards/dashboard_list.html`
- `app/templates/dashboards/dashboard_view.html` — view mode (widgets load via JS)
- `app/templates/dashboards/dashboard_new.html`
- `app/static/css/dashboard.css` — left dock + widget grid styles
- `app/static/js/dashboard_view.js` — widget data fetching on page load

**Files to modify:**
- `app/database.py` — add `create_all()` for new models; add migrations for new columns
- `app/main.py` — register new routers; remove old dashboard router; update `/` redirect logic
- `app/models/settings.py` — add `custom_css_enc`, `projection_expected_return_rate`, `projection_retirement_target`
- `app/templates/base.html` — global CSS injection; pass `global_custom_css` context to all templates
- `AGENTS.md` — updated implementation status, new files listed
- `README.md` — feature table update

**Auto-migration on first run:** `apply_migrations()` detects absence of `dashboard` table and creates it. Also inserts one "Default Dashboard" row with the four existing widgets (trend chart, category breakdown, net worth card, summary cards) so the app shows something useful immediately after upgrade.

**NetWorthSnapshot on sync:** Modify `app/services/sync_service.py` to write one `NetWorthSnapshot` row per sync (current sum of on-budget YNAB account balances).

---

### Milestone 2 — Dashboard Builder (Edit Mode)

**Goal:** WYSIWYG edit mode. User can add/remove/reposition/resize widgets and configure dashboard settings.

**Files to create:**
- `app/templates/dashboards/dashboard_edit.html` — edit mode template
- `app/static/js/vendor/gridstack/` — vendored gridstack.js + CSS (MIT notice preserved)
- `app/static/js/dashboard_builder.js` — edit mode JS: gridstack init, widget picker, config modal, auto-save
- `app/templates/dashboards/partials/widget_picker.html` — widget catalog panel
- `app/templates/dashboards/partials/widget_config_modal.html` — per-widget config UI

**Files to modify:**
- `app/routers/dashboards.py` — add `GET /dashboards/{id}/edit` route
- `app/routers/api_dashboards.py` — bulk layout save, widget CRUD endpoints

**Dashboard settings panel** (in edit mode sidebar):
- Name, description fields
- Grid columns selector (6 / 8 / 12 / 16 / 24)
- Default time period dropdown
- Custom CSS textarea (with a "Preview" toggle)

**Widget config modal** (per widget):
- Title override field
- Time period selector: Last Month / Last 3 Months / Last 6 Months / YTD / Last 12 Months / Last 18 Months / Last 24 Months / All Time / Custom Date Range
- Included accounts: multi-select checklist (all YNAB accounts + all external accounts)
- Excluded categories: multi-select checklist
- Chart type (where applicable): Bar / Line / Donut
- Other widget-specific options

---

### Milestone 3 — Widget Library: Rebuild Existing Widgets

**Goal:** Port the four existing dashboard widgets into the new per-widget data endpoint framework.

Widget data endpoint (`GET /api/dashboards/{id}/widgets/{widget_id}/data`) returns JSON appropriate for the widget type:
- Card widgets: `{ "value": 123456, "label": "Income", "period": "Nov 2025" }`
- Chart widgets: same Plotly JSON structure the current dashboard uses, but scoped to the widget's config

Widget types to implement in M3:
- `income_card`, `spending_card`, `net_savings_card`, `net_worth_card`
- `income_spending_trend`
- `category_breakdown`

A new `app/services/widget_service.py` handles all widget data queries. It dispatches on `widget_type` and applies the widget's `config_json` (time period, account filters, category exclusions) to scope the DB queries. This service is the only place that reads widget config and translates it to data — no widget logic in the router.

**Files to modify:**
- `app/routers/api_dashboards.py` — wire `GET /api/dashboards/{id}/widgets/{widget_id}/data` to `widget_service`
- `app/static/js/dashboard_view.js` — add Plotly rendering for each widget type

---

### Milestone 4 — Widget Library: New Widgets

**Goal:** Implement all remaining widget types.

New widget types:
- `savings_rate_card` — savings rate % for the period
- `net_worth_trend` — net worth over time using `NetWorthSnapshot` (YNAB) + `ExternalAccountBalance` (external); note in UI if YNAB history is short (snapshots started at Phase 14 deployment)
- `savings_rate_trend` — savings rate % over time
- `group_rollup` — spending by category group
- `payee_breakdown` — top payees bar chart
- `month_over_month` — side-by-side month comparison
- `category_stats_table` — avg / min / max / peak per category (table widget, not a chart)
- `account_balances_list` — account name + current balance rows
- `recent_transactions` — paginated transaction list

All implemented in `widget_service.py`. Template partial added for each new widget type's JS rendering in `dashboard_view.js`.

---

### Milestone 5 — Projection Widgets (Advanced)

**Goal:** Forward-looking widgets that require some user-provided parameters.

**New AppSettings columns** (with migration):
- `projection_expected_return_rate` REAL (default 0.07 — 7% annual)
- `projection_retirement_target` INTEGER (milliunits, nullable)

**New widget types:**
- `savings_projection` — future savings balance line chart: takes avg monthly savings from last N months, projects forward N years using compound interest
- `investment_tracker` — balance history + projected growth for selected external investment/retirement accounts

**New Settings UI section:** "Financial Projections" with fields for expected annual return rate and optional retirement target amount.

**Files to modify:**
- `app/models/settings.py` — new projection fields
- `app/database.py` — migrations
- `app/templates/settings/settings.html` — new section
- `app/services/widget_service.py` — projection widget implementations
- `docs/configuration.md` — document new settings fields

---

### Milestone 6 — Global Custom CSS

**Goal:** App-wide CSS override via Settings.

**Files to modify:**
- `app/models/settings.py` — `custom_css_enc` (already added in M1 migration; M6 adds the UI)
- `app/routers/settings.py` — load/save global custom CSS (decrypt on load, encrypt on save)
- `app/templates/settings/settings.html` — new "Appearance" section with global CSS textarea
- `app/routers/dashboards.py` — decrypt and pass `global_custom_css` to all dashboard templates
- `app/templates/base.html` — inject global CSS (already scaffolded in M1)
- `docs/configuration.md` — document global CSS setting

---

### Milestone 7 — Reports Integration (TBD)

Scope to be defined. Dashboards will feed into reports in some form. Full spec deferred until M1-M6 are complete.

---

## Security Notes

### Custom CSS (Both Per-Dashboard and Global)

- **Single-user self-hosted app** — the CSS is authored by the same user who owns all the data. CSS-based data exfiltration attacks are a multi-tenant concern and do not apply here.
- Per-dashboard CSS is stored **unencrypted** (it is not a secret; it is display configuration).
- Global CSS is stored **encrypted** (`custom_css_enc`) consistent with how all `AppSettings` sensitive fields are stored, as a defense-in-depth measure.
- Both are injected with `| safe` in templates. This is intentional and must not be changed to auto-escape.
- This security posture **must be documented** in a comment in both the model and the template injection point.

### Widget Data Endpoint

- `GET /api/dashboards/{id}/widgets/{widget_id}/data` is behind the standard auth gate (master key required).
- Widget config is read from DB (server-side); no client-supplied filter parameters are accepted in the query string — prevents parameter tampering.

---

## Files Overview (Complete List of New/Modified Files)

### New files

| File | Purpose |
|---|---|
| `app/models/dashboard.py` | `Dashboard`, `DashboardWidget`, `NetWorthSnapshot` SQLAlchemy models |
| `app/routers/dashboards.py` | HTML routes for dashboard viewing, listing, creation, editing |
| `app/routers/api_dashboards.py` | API routes for dashboard/widget CRUD and widget data |
| `app/schemas/dashboard.py` | Pydantic schemas for API request/response validation |
| `app/services/widget_service.py` | Widget data query dispatcher (reads config, returns chart/card JSON) |
| `app/templates/dashboards/dashboard_list.html` | Dashboard list page |
| `app/templates/dashboards/dashboard_view.html` | Dashboard view mode (widgets load via JS) |
| `app/templates/dashboards/dashboard_edit.html` | Dashboard edit/builder mode |
| `app/templates/dashboards/dashboard_new.html` | New dashboard creation form |
| `app/templates/dashboards/partials/widget_picker.html` | Widget catalog panel for edit mode |
| `app/templates/dashboards/partials/widget_config_modal.html` | Per-widget configuration modal |
| `app/static/css/dashboard.css` | Left dock + widget grid + dashboard-specific styles |
| `app/static/js/dashboard_view.js` | Widget data fetching and Plotly rendering on page load |
| `app/static/js/dashboard_builder.js` | Edit mode JS: gridstack init, widget picker, config modal, auto-save |
| `app/static/js/vendor/gridstack/` | Vendored gridstack.js + gridstack.min.css (MIT notice preserved) |
| `docs/phase14_plan.md` | This document |

### Modified files

| File | Change |
|---|---|
| `app/models/settings.py` | Add `custom_css_enc` column; add projection fields (M5) |
| `app/database.py` | `create_all()` for new models; `apply_migrations()` for new columns |
| `app/main.py` | Register new routers; update `/` redirect; remove old dashboard router |
| `app/routers/dashboard.py` | **DELETED** (replaced by `dashboards.py`) |
| `app/services/sync_service.py` | Write `NetWorthSnapshot` on each sync |
| `app/templates/base.html` | Global CSS injection; pass `global_custom_css` context |
| `app/templates/settings/settings.html` | New "Appearance" section (M6) + "Financial Projections" section (M5) |
| `app/routers/settings.py` | Handle new settings fields (global CSS, projection params) |
| `AGENTS.md` | Phase 14 section added; implementation status updated; new files listed |
| `README.md` | Feature table updated |
| `docs/configuration.md` | New settings documented |

---

## gridstack.js Attribution (Required)

gridstack.js is used under the MIT License.

**Copyright (c) 2021-present Alain Dumesny, Dylan Weiss, Lyor Goldstein**

The MIT license requires preserving the copyright notice in the source distribution. The following copyright notice must be preserved in the vendored file `app/static/js/vendor/gridstack/gridstack.js` (in the file header comment). Do not strip it during minification:

```
Copyright (c) 2021-present Alain Dumesny, Dylan Weiss, Lyor Goldstein
MIT License — https://github.com/gridstack/gridstack.js/blob/master/LICENSE
```

No attribution is required in the application UI.

---

## Conventions (Must Follow Existing Project Rules)

These are not new rules — they are reminders of existing project conventions that apply to all Phase 14 code:

- All monetary amounts remain as milliunits in the DB; convert to dollars only in templates or widget data endpoint responses (where Plotly needs floats).
- `widget_service.py` must be pure with respect to HTTP — no external API calls, only DB access.
- Secrets (global CSS) decrypted in service layer, not in routers.
- Button labels Title Case throughout.
- No `print()` — logging module only.
- `apply_migrations()` column values must be hardcoded string literals only.
- The new `dashboards` router must import the shared `Jinja2Templates` instance from `app/templates_config.py`.
- YNAB entity deletes are soft — set `deleted = True`, never hard-delete rows.
- Singleton tables (`app_settings`) always use `id = 1`.
