/**
 * Dashboard view — Phase 14, Milestone 1.
 *
 * On page load:
 * 1. Position widget cards on the CSS grid according to gs-* attributes.
 * 2. Fetch data for each widget from /api/dashboards/{id}/widgets/{wid}/data.
 * 3. Show placeholder/error in widget body; hide spinner when complete.
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

  // ── Fetch widget data ──────────────────────────────────────────────────
  var widgets = document.querySelectorAll('.grid-stack-item[data-widget-id]');
  widgets.forEach(function (el) {
    var dashboardId = el.getAttribute('data-dashboard-id');
    var widgetId = el.getAttribute('data-widget-id');
    var bodyEl = document.getElementById('widget-body-' + widgetId);
    var spinnerEl = document.getElementById('spinner-' + widgetId);

    if (!dashboardId || !widgetId || !bodyEl) return;

    fetch('/api/dashboards/' + dashboardId + '/widgets/' + widgetId + '/data')
      .then(function (resp) {
        if (!resp.ok) throw new Error('HTTP ' + resp.status);
        return resp.json();
      })
      .then(function (data) {
        if (data.status === 'pending_implementation') {
          bodyEl.innerHTML =
            '<div class="widget-body__placeholder">' +
            '<div style="font-size: 1.5rem; margin-bottom: 0.5rem; opacity: 0.3;">&#9632;</div>' +
            '<div>' + (data.widget_type || 'Widget').replace(/_/g, ' ') + '</div>' +
            '<div style="font-size: 0.75rem; margin-top: 0.25rem;">Data available in Milestone 3</div>' +
            '</div>';
        } else {
          bodyEl.innerHTML =
            '<div class="widget-body__placeholder">' +
            '<pre style="font-size: 0.75rem; max-width: 100%; overflow: auto;">' +
            JSON.stringify(data, null, 2) +
            '</pre></div>';
        }
      })
      .catch(function (err) {
        bodyEl.innerHTML =
          '<div class="widget-body__error">Failed to load: ' +
          err.message + '</div>';
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

    // Close dock when clicking outside on mobile
    document.addEventListener('click', function (e) {
      if (window.innerWidth > 768) return;
      if (!dock.contains(e.target) && !toggleBtn.contains(e.target)) {
        dock.classList.remove('dash-dock--open');
      }
    });
  }
});
