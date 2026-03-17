/**
 * Dashboard Builder — edit-mode JS (Phase 14 M2).
 *
 * Handles gridstack drag/resize, widget picker, config modal,
 * dashboard settings, and CSS preview.
 */

(function () {
  'use strict';

  // ---------------------------------------------------------------------------
  // Helpers
  // ---------------------------------------------------------------------------

  /** Parse JSON from a <script type="application/json"> tag by ID. */
  function readJsonScript(id) {
    var el = document.getElementById(id);
    if (!el || !el.textContent.trim()) return null;
    try {
      return JSON.parse(el.textContent);
    } catch (e) {
      return null;
    }
  }

  /** Show a brief status message (success or error). */
  function showStatus(message, isError) {
    var bar = document.getElementById('builder-status');
    if (!bar) return;
    bar.textContent = message;
    bar.style.display = 'block';
    bar.style.background = isError
      ? 'rgba(255,107,107,0.12)'
      : 'rgba(76,175,130,0.12)';
    bar.style.border = isError
      ? '1px solid rgba(255,107,107,0.4)'
      : '1px solid rgba(76,175,130,0.4)';
    bar.style.color = isError ? '#ff9e9e' : '#7de0b0';
    clearTimeout(bar._timer);
    bar._timer = setTimeout(function () {
      bar.style.display = 'none';
    }, 3000);
  }

  /** Debounce helper. */
  function debounce(fn, delay) {
    var timer;
    return function () {
      var ctx = this;
      var args = arguments;
      clearTimeout(timer);
      timer = setTimeout(function () {
        fn.apply(ctx, args);
      }, delay);
    };
  }

  // ---------------------------------------------------------------------------
  // State
  // ---------------------------------------------------------------------------

  var dashboardMeta = readJsonScript('dashboard-meta') || { id: 0, grid_columns: 12 };
  var ynabAccounts = readJsonScript('ynab-accounts-data') || [];
  var externalAccounts = readJsonScript('external-accounts-data') || [];
  var categories = readJsonScript('categories-data') || [];

  var grid = null;
  var cssPreviewOn = false;

  // ---------------------------------------------------------------------------
  // Gridstack init
  // ---------------------------------------------------------------------------

  function initGrid() {
    var gridEl = document.getElementById('widget-grid');
    if (!gridEl) return;

    grid = GridStack.init({
      column: dashboardMeta.grid_columns,
      cellHeight: 120,
      draggable: { handle: '.widget-drag-handle' },
      resizable: { handles: 'se,sw,ne,nw,e,w,s,n' },
      animate: true,
    }, gridEl);

    // Auto-save layout on change (debounced 500ms)
    grid.on('change', debounce(function () {
      saveLayout();
    }, 500));
  }

  // ---------------------------------------------------------------------------
  // Layout auto-save
  // ---------------------------------------------------------------------------

  function saveLayout() {
    var gridEl = document.getElementById('widget-grid');
    if (!gridEl) return;

    var items = [];
    var widgetEls = gridEl.querySelectorAll('.grid-stack-item[data-widget-id]');
    for (var i = 0; i < widgetEls.length; i++) {
      var el = widgetEls[i];
      items.push({
        widget_id: parseInt(el.getAttribute('data-widget-id'), 10),
        grid_x: parseInt(el.getAttribute('gs-x') || '0', 10),
        grid_y: parseInt(el.getAttribute('gs-y') || '0', 10),
        grid_w: parseInt(el.getAttribute('gs-w') || '4', 10),
        grid_h: parseInt(el.getAttribute('gs-h') || '3', 10),
      });
    }

    fetch('/api/dashboards/' + dashboardMeta.id + '/layout', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ items: items }),
    })
      .then(function (resp) {
        if (!resp.ok) throw new Error('Layout save failed');
        showStatus('Layout saved', false);
      })
      .catch(function (err) {
        showStatus('Error saving layout: ' + err.message, true);
      });
  }

  // ---------------------------------------------------------------------------
  // Widget picker — add new widget
  // ---------------------------------------------------------------------------

  function bindWidgetPicker() {
    var buttons = document.querySelectorAll('.widget-picker-item');
    for (var i = 0; i < buttons.length; i++) {
      buttons[i].addEventListener('click', function () {
        var widgetType = this.getAttribute('data-widget-type');
        addWidget(widgetType);
      });
    }
  }

  function addWidget(widgetType) {
    var payload = {
      widget_type: widgetType,
      grid_x: 0,
      grid_y: 99,
      grid_w: 4,
      grid_h: 3,
      config_json: '{}',
    };

    fetch('/api/dashboards/' + dashboardMeta.id + '/widgets', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })
      .then(function (resp) {
        if (!resp.ok) throw new Error('Failed to add widget');
        return resp.json();
      })
      .then(function (data) {
        var widgetId = data.id;
        var label = widgetType.replace(/_/g, ' ').replace(/\b\w/g, function (c) {
          return c.toUpperCase();
        });

        // Create DOM element
        var el = document.createElement('div');
        el.className = 'grid-stack-item widget-card widget-card--edit';
        el.setAttribute('data-widget-id', widgetId);
        el.setAttribute('data-widget-type', widgetType);
        el.setAttribute('data-config-json', '{}');
        el.setAttribute('gs-x', '0');
        el.setAttribute('gs-y', '99');
        el.setAttribute('gs-w', '4');
        el.setAttribute('gs-h', '3');
        el.innerHTML =
          '<div class="grid-stack-item-content">' +
            '<div class="widget-drag-handle"></div>' +
            '<div class="widget-header">' +
              '<span class="widget-header__title">' + escapeHtml(label) + '</span>' +
              '<div style="display:flex;gap:0.25rem;">' +
                '<button type="button" class="widget-config-btn" data-widget-id="' + widgetId + '" title="Configure Widget">&#9881;</button>' +
                '<button type="button" class="widget-remove-btn" data-widget-id="' + widgetId + '" title="Remove Widget">&times;</button>' +
              '</div>' +
            '</div>' +
            '<div class="widget-body widget-body__placeholder">' + escapeHtml(label) + '</div>' +
          '</div>';

        // Add to grid
        var gridEl = document.getElementById('widget-grid');
        gridEl.appendChild(el);
        if (grid) {
          grid.makeWidget(el);
        }

        // Bind events on new buttons
        bindWidgetCardEvents(el);

        // Hide empty message if present
        var emptyMsg = document.getElementById('empty-grid-message');
        if (emptyMsg) emptyMsg.style.display = 'none';

        showStatus('Widget added', false);
      })
      .catch(function (err) {
        showStatus('Error adding widget: ' + err.message, true);
      });
  }

  /** Escape HTML to prevent XSS when inserting user-derived text. */
  function escapeHtml(str) {
    var div = document.createElement('div');
    div.appendChild(document.createTextNode(str));
    return div.innerHTML;
  }

  // ---------------------------------------------------------------------------
  // Widget remove
  // ---------------------------------------------------------------------------

  function handleRemoveWidget(btn) {
    var widgetId = btn.getAttribute('data-widget-id');
    if (!confirm('Remove this widget?')) return;

    var el = btn.closest('.grid-stack-item');

    fetch('/api/dashboards/' + dashboardMeta.id + '/widgets/' + widgetId, {
      method: 'DELETE',
    })
      .then(function (resp) {
        if (!resp.ok) throw new Error('Failed to remove widget');
        if (grid && el) {
          grid.removeWidget(el, true);
        } else if (el && el.parentNode) {
          el.parentNode.removeChild(el);
        }
        showStatus('Widget removed', false);
      })
      .catch(function (err) {
        showStatus('Error removing widget: ' + err.message, true);
      });
  }

  // ---------------------------------------------------------------------------
  // Config modal
  // ---------------------------------------------------------------------------

  function openConfigModal(widgetId) {
    var el = document.querySelector('.grid-stack-item[data-widget-id="' + widgetId + '"]');
    if (!el) return;

    var configStr = el.getAttribute('data-config-json') || '{}';
    var config;
    try {
      config = JSON.parse(configStr);
    } catch (e) {
      config = {};
    }

    // Set hidden widget ID
    document.getElementById('config-widget-id').value = widgetId;

    // Populate fields
    document.getElementById('config-title-override').value = config.title_override || '';
    document.getElementById('config-time-period').value = config.time_period || '';
    document.getElementById('config-date-start').value = config.date_start || '';
    document.getElementById('config-date-end').value = config.date_end || '';
    document.getElementById('config-chart-type').value = config.chart_type || '';

    // Show/hide custom dates
    toggleCustomDates();

    // Populate multiselect lists with current selections
    buildCheckboxList(
      'config-ynab-accounts',
      ynabAccounts,
      'id',
      'name',
      config.included_ynab_accounts || []
    );
    buildCheckboxList(
      'config-external-accounts',
      externalAccounts,
      'id',
      'name',
      config.included_external_accounts || []
    );
    buildCheckboxList(
      'config-excluded-categories',
      categories,
      'id',
      'display_name',
      config.excluded_categories || []
    );

    // Show modal
    document.getElementById('config-modal-overlay').style.display = 'flex';
  }

  function closeConfigModal() {
    document.getElementById('config-modal-overlay').style.display = 'none';
  }

  function saveConfigModal() {
    var widgetId = document.getElementById('config-widget-id').value;
    if (!widgetId) return;

    var config = {};

    var titleOverride = document.getElementById('config-title-override').value.trim();
    if (titleOverride) config.title_override = titleOverride;

    var timePeriod = document.getElementById('config-time-period').value;
    if (timePeriod) config.time_period = timePeriod;

    if (timePeriod === 'custom') {
      var dateStart = document.getElementById('config-date-start').value;
      var dateEnd = document.getElementById('config-date-end').value;
      if (dateStart) config.date_start = dateStart;
      if (dateEnd) config.date_end = dateEnd;
    }

    var chartType = document.getElementById('config-chart-type').value;
    if (chartType) config.chart_type = chartType;

    // Always assign — even empty arrays — so clearing a selection is persisted.
    config.included_ynab_accounts = getCheckedValues('config-ynab-accounts');
    config.included_external_accounts = getCheckedValues('config-external-accounts');
    config.excluded_categories = getCheckedValues('config-excluded-categories');

    var configJson = JSON.stringify(config);

    fetch('/api/dashboards/' + dashboardMeta.id + '/widgets/' + widgetId, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ config_json: configJson }),
    })
      .then(function (resp) {
        if (!resp.ok) throw new Error('Failed to save widget config');
        // Update data attribute on the widget element
        var el = document.querySelector('.grid-stack-item[data-widget-id="' + widgetId + '"]');
        if (el) el.setAttribute('data-config-json', configJson);
        closeConfigModal();
        showStatus('Widget config saved', false);
      })
      .catch(function (err) {
        showStatus('Error saving config: ' + err.message, true);
      });
  }

  function toggleCustomDates() {
    var periodSelect = document.getElementById('config-time-period');
    var customDates = document.getElementById('config-custom-dates');
    if (periodSelect && customDates) {
      customDates.style.display = periodSelect.value === 'custom' ? 'block' : 'none';
    }
  }

  // ---------------------------------------------------------------------------
  // Multiselect list builder
  // ---------------------------------------------------------------------------

  /**
   * Build a list of checkboxes inside a container element.
   * @param {string} containerId - ID of the container element.
   * @param {Array} items - Array of objects with at least [valueKey] and [labelKey].
   * @param {string} valueKey - Key for the checkbox value (e.g., 'id').
   * @param {string} labelKey - Key for the display label (e.g., 'name').
   * @param {Array} checkedIds - Array of currently selected IDs.
   */
  function buildCheckboxList(containerId, items, valueKey, labelKey, checkedIds) {
    var container = document.getElementById(containerId);
    if (!container) return;
    container.innerHTML = '';

    if (!items || items.length === 0) {
      container.innerHTML = '<p style="font-size:0.8rem;color:var(--muted);">None available</p>';
      return;
    }

    // Normalize checkedIds to strings for comparison
    var checkedSet = {};
    for (var c = 0; c < checkedIds.length; c++) {
      checkedSet[String(checkedIds[c])] = true;
    }

    for (var i = 0; i < items.length; i++) {
      var item = items[i];
      var val = String(item[valueKey]);
      var label = item[labelKey] || val;
      var isChecked = checkedSet[val] ? 'checked' : '';

      var labelEl = document.createElement('label');
      labelEl.className = 'multiselect-item';
      labelEl.innerHTML =
        '<input type="checkbox" value="' + escapeHtml(val) + '" ' + isChecked + '> ' +
        escapeHtml(label);
      container.appendChild(labelEl);
    }
  }

  /** Get all checked values from a multiselect container. */
  function getCheckedValues(containerId) {
    var container = document.getElementById(containerId);
    if (!container) return [];
    var checkboxes = container.querySelectorAll('input[type="checkbox"]:checked');
    var values = [];
    for (var i = 0; i < checkboxes.length; i++) {
      values.push(checkboxes[i].value);
    }
    return values;
  }

  // ---------------------------------------------------------------------------
  // Dashboard settings save
  // ---------------------------------------------------------------------------

  function saveSettings() {
    var name = document.getElementById('settings-name').value.trim();
    if (!name) {
      showStatus('Dashboard name is required', true);
      return;
    }

    var payload = {
      name: name,
      description: document.getElementById('settings-description').value.trim() || null,
      grid_columns: parseInt(document.getElementById('settings-grid-columns').value, 10),
      default_time_period: document.getElementById('settings-time-period').value || null,
      custom_css: document.getElementById('settings-custom-css').value || null,
    };

    fetch('/api/dashboards/' + dashboardMeta.id, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })
      .then(function (resp) {
        if (!resp.ok) throw new Error('Failed to save settings');
        // Update grid columns if changed
        if (payload.grid_columns !== dashboardMeta.grid_columns) {
          dashboardMeta.grid_columns = payload.grid_columns;
          if (grid) {
            grid.column(payload.grid_columns);
          }
          var gridEl = document.getElementById('widget-grid');
          if (gridEl) {
            gridEl.setAttribute('data-columns', payload.grid_columns);
          }
        }
        // Update page title
        var titleEl = document.querySelector('.dash-main__title');
        if (titleEl) titleEl.textContent = 'Edit: ' + payload.name;

        showStatus('Settings saved', false);
      })
      .catch(function (err) {
        showStatus('Error saving settings: ' + err.message, true);
      });
  }

  // ---------------------------------------------------------------------------
  // CSS preview toggle
  // ---------------------------------------------------------------------------

  function toggleCssPreview() {
    var btn = document.getElementById('preview-css-btn');
    var textarea = document.getElementById('settings-custom-css');
    if (!btn || !textarea) return;

    cssPreviewOn = !cssPreviewOn;

    var previewStyle = document.getElementById('css-preview');
    if (cssPreviewOn) {
      if (!previewStyle) {
        previewStyle = document.createElement('style');
        previewStyle.id = 'css-preview';
        document.head.appendChild(previewStyle);
      }
      previewStyle.textContent = textarea.value;
      btn.textContent = 'Preview Off';
    } else {
      if (previewStyle) {
        previewStyle.textContent = '';
      }
      btn.textContent = 'Preview On';
    }
  }

  // ---------------------------------------------------------------------------
  // Event binding for individual widget card buttons
  // ---------------------------------------------------------------------------

  function bindWidgetCardEvents(parentEl) {
    var configBtns = parentEl.querySelectorAll('.widget-config-btn');
    for (var i = 0; i < configBtns.length; i++) {
      configBtns[i].addEventListener('click', function (e) {
        e.stopPropagation();
        openConfigModal(this.getAttribute('data-widget-id'));
      });
    }

    var removeBtns = parentEl.querySelectorAll('.widget-remove-btn');
    for (var j = 0; j < removeBtns.length; j++) {
      removeBtns[j].addEventListener('click', function (e) {
        e.stopPropagation();
        handleRemoveWidget(this);
      });
    }
  }

  // ---------------------------------------------------------------------------
  // Dock toggle (copied from dashboard_view pattern)
  // ---------------------------------------------------------------------------

  function bindDockToggle() {
    var toggle = document.getElementById('dock-toggle');
    var dock = document.getElementById('dash-dock');
    if (toggle && dock) {
      toggle.addEventListener('click', function () {
        dock.classList.toggle('dash-dock--open');
      });
    }
  }

  // ---------------------------------------------------------------------------
  // Init
  // ---------------------------------------------------------------------------

  document.addEventListener('DOMContentLoaded', function () {
    initGrid();
    bindWidgetPicker();
    bindDockToggle();

    // Bind events on existing widget cards
    var gridEl = document.getElementById('widget-grid');
    if (gridEl) {
      bindWidgetCardEvents(gridEl);
    }

    // Config modal events
    var modalClose = document.getElementById('config-modal-close');
    var modalCancel = document.getElementById('config-modal-cancel');
    var modalSave = document.getElementById('config-modal-save');
    var modalOverlay = document.getElementById('config-modal-overlay');

    if (modalClose) modalClose.addEventListener('click', closeConfigModal);
    if (modalCancel) modalCancel.addEventListener('click', closeConfigModal);
    if (modalSave) modalSave.addEventListener('click', saveConfigModal);

    // Close modal on overlay click (but not on modal body click)
    if (modalOverlay) {
      modalOverlay.addEventListener('click', function (e) {
        if (e.target === modalOverlay) closeConfigModal();
      });
    }

    // Custom date range visibility toggle
    var timePeriodSelect = document.getElementById('config-time-period');
    if (timePeriodSelect) {
      timePeriodSelect.addEventListener('change', toggleCustomDates);
    }

    // Dashboard settings save
    var saveBtn = document.getElementById('save-settings-btn');
    if (saveBtn) saveBtn.addEventListener('click', saveSettings);

    // CSS preview toggle
    var previewBtn = document.getElementById('preview-css-btn');
    if (previewBtn) previewBtn.addEventListener('click', toggleCssPreview);

    // Escape key closes modal
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') {
        var overlay = document.getElementById('config-modal-overlay');
        if (overlay && overlay.style.display !== 'none') {
          closeConfigModal();
        }
      }
    });
  });
})();
