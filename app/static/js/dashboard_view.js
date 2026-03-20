/**
 * Dashboard view — Phase 14, Milestones 3 & 4.
 *
 * On page load:
 * 1. Position widget cards on the CSS grid according to gs-* attributes.
 * 2. Fetch data for each widget from /api/dashboards/{id}/widgets/{wid}/data.
 * 3. Render widget content: value cards for card types, Plotly charts for chart types,
 *    HTML tables/lists for structured data types.
 * 4. Handle dock toggle for narrow viewports.
 */

document.addEventListener('DOMContentLoaded', function () {

  // ── Position widgets on the CSS grid ────────────────────────────────────
  var gridEl = document.querySelector('.widget-grid');
  if (gridEl) {
    var cols = parseInt(gridEl.getAttribute('data-columns'), 10) || 12;
    gridEl.style.setProperty('--grid-cols', cols);

    var items = gridEl.querySelectorAll('.grid-stack-item');
    items.forEach(function (item) {
      var x = parseInt(item.getAttribute('gs-x'), 10) || 0;
      var y = parseInt(item.getAttribute('gs-y'), 10) || 0;
      var w = parseInt(item.getAttribute('gs-w'), 10) || 4;
      var h = parseInt(item.getAttribute('gs-h'), 10) || 3;

      // CSS Grid columns are 1-indexed
      item.style.gridColumn = (x + 1) + ' / span ' + w;
      item.style.gridRow = (y + 1) + ' / span ' + h;
    });
  }

  // ── Fetch and render each widget ─────────────────────────────────────────
  var widgets = document.querySelectorAll('.grid-stack-item[data-widget-id]');
  widgets.forEach(function (el) {
    var dashboardId = el.getAttribute('data-dashboard-id');
    var widgetId    = el.getAttribute('data-widget-id');
    var bodyEl      = document.getElementById('widget-body-' + widgetId);
    var spinnerEl   = document.getElementById('spinner-' + widgetId);
    var titleEl     = el.querySelector('.widget-header__title');

    if (!dashboardId || !widgetId || !bodyEl) return;

    fetch('/api/dashboards/' + dashboardId + '/widgets/' + widgetId + '/data')
      .then(function (resp) {
        if (!resp.ok) throw new Error('HTTP ' + resp.status);
        return resp.json();
      })
      .then(function (data) {
        // Update widget title if the server returned one
        if (titleEl && data.title) {
          titleEl.textContent = data.title;
        }
        renderWidget(bodyEl, data, widgetId);
      })
      .catch(function () {
        bodyEl.innerHTML =
          '<div class="widget-body__error">Failed to load widget data.</div>';
      })
      .finally(function () {
        if (spinnerEl) spinnerEl.classList.add('spinner--hidden');
      });
  });

  // ── Dock toggle ────────────────────────────────────────────────────────
  var toggleBtn = document.getElementById('dock-toggle');
  var dock = document.getElementById('dash-dock');
  if (toggleBtn && dock) {
    toggleBtn.addEventListener('click', function () {
      dock.classList.toggle('dash-dock--open');
    });

    document.addEventListener('click', function (e) {
      if (window.innerWidth > 768) return;
      if (!dock.contains(e.target) && !toggleBtn.contains(e.target)) {
        dock.classList.remove('dash-dock--open');
      }
    });
  }

});


// ── Widget rendering dispatch ──────────────────────────────────────────────

/**
 * Route data to the appropriate renderer based on widget_type.
 */
function renderWidget(bodyEl, data, widgetId) {
  if (data.error) {
    bodyEl.innerHTML =
      '<div class="widget-body__error">' + escapeHtml(data.error) + '</div>';
    return;
  }

  var type = data.widget_type;

  // Card widgets (milliunit values)
  if (type === 'income_card' || type === 'spending_card' ||
      type === 'net_savings_card' || type === 'net_worth_card') {
    renderCardWidget(bodyEl, data);
    return;
  }

  // Savings rate card (percentage, not milliunits)
  if (type === 'savings_rate_card') {
    renderSavingsRateCard(bodyEl, data);
    return;
  }

  // Plotly chart widgets
  if (type === 'income_spending_trend' || type === 'savings_rate_trend' ||
      type === 'payee_breakdown' || type === 'month_over_month') {
    renderPlotlyWidget(bodyEl, data, widgetId);
    return;
  }

  if (type === 'net_worth_trend') {
    if (data.empty || !data.plotly) {
      bodyEl.innerHTML =
        '<div class="widget-body__placeholder">' +
        'No net worth history yet. Data will accumulate with each sync.' +
        '</div>';
    } else {
      renderPlotlyWidget(bodyEl, data, widgetId);
    }
    return;
  }

  if (type === 'category_breakdown') {
    if (data.empty || !data.plotly) {
      bodyEl.innerHTML =
        '<div class="widget-body__placeholder">No spending data for this period.</div>';
    } else {
      renderPlotlyWidget(bodyEl, data, widgetId);
    }
    return;
  }

  if (type === 'group_rollup') {
    if (data.empty || !data.plotly) {
      bodyEl.innerHTML =
        '<div class="widget-body__placeholder">No spending data for this period.</div>';
    } else {
      renderPlotlyWidget(bodyEl, data, widgetId);
    }
    return;
  }

  // Structured data widgets (HTML tables/lists)
  if (type === 'category_stats_table') {
    renderCategoryStatsTable(bodyEl, data);
    return;
  }

  if (type === 'account_balances_list') {
    renderAccountBalancesList(bodyEl, data);
    return;
  }

  if (type === 'recent_transactions') {
    renderRecentTransactions(bodyEl, data);
    return;
  }

  if (type === 'savings_projection') {
    if (data.empty || !data.plotly) {
      bodyEl.innerHTML =
        '<div class="widget-body__placeholder">Not enough transaction data to generate a projection. Sync more months of data.</div>';
    } else {
      renderPlotlyWidget(bodyEl, data, widgetId);
    }
    return;
  }

  if (type === 'investment_tracker') {
    if (data.empty || !data.plotly) {
      bodyEl.innerHTML =
        '<div class="widget-body__placeholder">No external investment accounts found. Upload statements via Import to add accounts.</div>';
    } else {
      renderPlotlyWidget(bodyEl, data, widgetId);
    }
    return;
  }

  // Fallback for unimplemented types
  bodyEl.innerHTML =
    '<div class="widget-body__placeholder">' +
    escapeHtml((type || 'Widget').replace(/_/g, ' ')) +
    '</div>';
}


// ── Card renderers ─────────────────────────────────────────────────────────

/**
 * Render a card widget: large value + period label.
 */
function renderCardWidget(bodyEl, data) {
  var value   = typeof data.value === 'number' ? data.value : 0;
  var period  = data.period || '';

  var isNegative = value < 0;
  var colorClass = '';
  if (data.widget_type === 'net_savings_card') {
    colorClass = isNegative ? 'widget-value--negative' : 'widget-value--positive';
  } else if (data.widget_type === 'income_card') {
    colorClass = 'widget-value--income';
  } else if (data.widget_type === 'spending_card') {
    colorClass = 'widget-value--spending';
  }

  bodyEl.classList.add('widget-body--card');
  bodyEl.innerHTML =
    '<div class="widget-card-content">' +
      '<div class="widget-card-value ' + colorClass + '">' +
        escapeHtml(formatMilliunits(value)) +
      '</div>' +
      '<div class="widget-card-period">' + escapeHtml(period) + '</div>' +
    '</div>';
}


/**
 * Render the savings rate card: percentage value with colour coding.
 */
function renderSavingsRateCard(bodyEl, data) {
  var value  = typeof data.value === 'number' ? data.value : 0;
  var period = data.period || '';

  var colorClass = '';
  if (value > 0) {
    colorClass = 'widget-value--positive';
  } else if (value < 0) {
    colorClass = 'widget-value--negative';
  }

  var formatted = value.toFixed(1) + '%';

  bodyEl.classList.add('widget-body--card');
  bodyEl.innerHTML =
    '<div class="widget-card-content">' +
      '<div class="widget-card-value ' + colorClass + '">' +
        escapeHtml(formatted) +
      '</div>' +
      '<div class="widget-card-period">' + escapeHtml(period) + '</div>' +
    '</div>';
}


// ── Plotly chart renderer ──────────────────────────────────────────────────

/**
 * Render a Plotly chart widget.  Plotly must be loaded on the page.
 */
function renderPlotlyWidget(bodyEl, data, widgetId) {
  if (typeof Plotly === 'undefined') {
    bodyEl.innerHTML =
      '<div class="widget-body__error">Chart library not loaded.</div>';
    return;
  }

  bodyEl.classList.add('widget-body--chart');

  var plotDiv = document.createElement('div');
  plotDiv.id = 'plot-' + widgetId;
  plotDiv.className = 'widget-plot';
  bodyEl.innerHTML = '';
  bodyEl.appendChild(plotDiv);

  if (!data.plotly || typeof data.plotly !== 'object') {
    bodyEl.innerHTML =
      '<div class="widget-body__error">Chart data unavailable.</div>';
    return;
  }

  var figure = data.plotly;
  var layout = figure.layout && typeof figure.layout === 'object'
    ? figure.layout
    : {};

  Plotly.newPlot(plotDiv, figure.data || [], layout, {
    responsive: true,
    displayModeBar: false,
    scrollZoom: false,
  });
}


// ── Structured data renderers ──────────────────────────────────────────────

/**
 * Render the category stats table widget.
 */
function renderCategoryStatsTable(bodyEl, data) {
  var rows = data.rows;
  if (!rows || !Array.isArray(rows) || rows.length === 0) {
    bodyEl.innerHTML =
      '<div class="widget-body__placeholder">No category data for this period.</div>';
    return;
  }

  bodyEl.classList.add('widget-body--table');

  var html = '<div class="widget-stats-table-wrap">' +
    '<table class="widget-stats-table">' +
    '<thead><tr>' +
      '<th>Category</th>' +
      '<th>Group</th>' +
      '<th>Avg/mo</th>' +
      '<th>Min</th>' +
      '<th>Max</th>' +
      '<th>Peak Month</th>' +
      '<th>Months</th>' +
    '</tr></thead>' +
    '<tbody>';

  for (var i = 0; i < rows.length; i++) {
    var r = rows[i];
    html += '<tr>' +
      '<td>' + escapeHtml(r.category_name || '') + '</td>' +
      '<td>' + escapeHtml(r.group_name || '') + '</td>' +
      '<td>' + escapeHtml(formatMilliunits(r.avg_amount || 0)) + '</td>' +
      '<td>' + escapeHtml(formatMilliunits(r.min_amount || 0)) + '</td>' +
      '<td>' + escapeHtml(formatMilliunits(r.max_amount || 0)) + '</td>' +
      '<td>' + escapeHtml(r.peak_month || '') + '</td>' +
      '<td>' + escapeHtml(String(r.months_with_data || 0)) + '</td>' +
    '</tr>';
  }

  html += '</tbody></table></div>';
  bodyEl.innerHTML = html;
}


/**
 * Render the account balances list widget.
 */
function renderAccountBalancesList(bodyEl, data) {
  var accounts = data.accounts;
  if (!accounts || !Array.isArray(accounts) || accounts.length === 0) {
    bodyEl.innerHTML =
      '<div class="widget-body__placeholder">No accounts found.</div>';
    return;
  }

  bodyEl.classList.add('widget-body--table');

  var html = '<div class="widget-accounts-list">';

  for (var i = 0; i < accounts.length; i++) {
    var acct = accounts[i];
    var sourceLabel = acct.source === 'external' ? ' (ext)' : '';
    var balClass = (acct.balance || 0) < 0 ? 'widget-value--negative' : '';

    html += '<div class="widget-accounts-list__row">' +
      '<span class="widget-accounts-list__name">' +
        escapeHtml(acct.name || '') +
        '<span class="widget-accounts-list__type">' + escapeHtml(acct.type || '') + escapeHtml(sourceLabel) + '</span>' +
      '</span>' +
      '<span class="widget-accounts-list__balance ' + balClass + '">' +
        escapeHtml(formatMilliunits(acct.balance || 0)) +
      '</span>' +
    '</div>';
  }

  // Total row
  var totalVal = typeof data.total === 'number' ? data.total : 0;
  var totalClass = totalVal < 0 ? 'widget-value--negative' : '';
  html += '<div class="widget-accounts-list__row widget-accounts-list__total">' +
    '<span class="widget-accounts-list__name">Total</span>' +
    '<span class="widget-accounts-list__balance ' + totalClass + '">' +
      escapeHtml(formatMilliunits(totalVal)) +
    '</span>' +
  '</div>';

  html += '</div>';
  bodyEl.innerHTML = html;
}


/**
 * Render the recent transactions list widget.
 */
function renderRecentTransactions(bodyEl, data) {
  var txns = data.transactions;
  if (!txns || !Array.isArray(txns) || txns.length === 0) {
    bodyEl.innerHTML =
      '<div class="widget-body__placeholder">No recent transactions.</div>';
    return;
  }

  bodyEl.classList.add('widget-body--table');

  var html = '<div class="widget-transactions-list-wrap">' +
    '<table class="widget-transactions-list">' +
    '<thead><tr>' +
      '<th>Date</th>' +
      '<th>Payee</th>' +
      '<th>Account</th>' +
      '<th class="txn-col-amount">Amount</th>' +
    '</tr></thead>' +
    '<tbody>';

  for (var i = 0; i < txns.length; i++) {
    var t = txns[i];
    var amt = typeof t.amount === 'number' ? t.amount : 0;
    var amtClass = amt >= 0 ? 'txn-amount--positive' : 'txn-amount--negative';

    html += '<tr>' +
      '<td>' + escapeHtml(t.date || '') + '</td>' +
      '<td>' + escapeHtml(t.payee_name || '') + '</td>' +
      '<td>' + escapeHtml(t.account_name || '') + '</td>' +
      '<td class="txn-col-amount ' + amtClass + '">' +
        escapeHtml(formatMilliunits(amt)) +
      '</td>' +
    '</tr>';
  }

  html += '</tbody></table></div>';
  bodyEl.innerHTML = html;
}


// ── Utility functions ──────────────────────────────────────────────────────

/**
 * Format a milliunit integer as a dollar string.
 * Examples: 12345678 -> "$12,345.68"; -500000 -> "-$500.00"
 */
function formatMilliunits(milliunits) {
  if (!Number.isFinite(milliunits)) return '$0.00';
  var negative = milliunits < 0;
  var absVal   = Math.abs(milliunits) / 1000;
  var formatted = absVal.toLocaleString('en-US', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
  return negative ? '-$' + formatted : '$' + formatted;
}


/**
 * Escape HTML special characters to prevent XSS in innerHTML assignments.
 */
function escapeHtml(str) {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}
