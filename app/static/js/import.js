/**
 * Import page — Phase 15 Queue Overhaul.
 * QueueManager handles multi-file upload, SSE processing, queue restore, and history.
 */
(function () {
  "use strict";

  // ---- DOM refs ----
  var uploadState      = document.getElementById("upload-state");
  var reviewState      = document.getElementById("review-state");
  var dropZone         = document.getElementById("drop-zone");
  var fileInput        = document.getElementById("file-input");
  var chooseBtn        = document.getElementById("choose-file-btn");
  var fileNameDisplay  = document.getElementById("file-name-display");
  var uploadBtn        = document.getElementById("upload-btn");
  var stopBtn          = document.getElementById("stop-btn");
  var uploadError      = document.getElementById("upload-error");
  var profileSelect    = document.getElementById("institution-profile-select");
  var queueSection     = document.getElementById("queue-section");
  var queueTbody       = document.getElementById("queue-tbody");
  var backToQueueBtn   = document.getElementById("back-to-queue-btn");
  var historyToggleBtn = document.getElementById("history-toggle-btn");
  var historyContent   = document.getElementById("history-content");
  var historyToggleIcon= document.getElementById("history-toggle-icon");
  var historyLoading   = document.getElementById("history-loading");
  var historySessions  = document.getElementById("history-sessions");
  var historyAccounts  = document.getElementById("history-accounts");

  // Review refs
  var duplicateWarning = document.getElementById("duplicate-warning");
  var visionNotice     = document.getElementById("vision-notice");
  var summaryCard      = document.getElementById("summary-card");
  var rowsThead        = document.getElementById("rows-thead");
  var rowsTbody        = document.getElementById("rows-tbody");
  var confirmBtn       = document.getElementById("confirm-btn");
  var confirmPanel     = document.getElementById("confirm-panel");
  var confirmAccountName = document.getElementById("confirm-account-name");
  var confirmAccountType = document.getElementById("confirm-account-type");
  var confirmSaveProfile = document.getElementById("confirm-save-profile");
  var confirmSaveBtn   = document.getElementById("confirm-save-btn");
  var confirmBackBtn   = document.getElementById("confirm-back-btn");
  var confirmError     = document.getElementById("confirm-error");
  var chatMessages     = document.getElementById("chat-messages");
  var chatInput        = document.getElementById("chat-input");
  var chatSendBtn      = document.getElementById("chat-send-btn");
  var profilesToggleBtn = document.getElementById("profiles-toggle-btn");
  var profilesList     = document.getElementById("profiles-list");

  var MAX_FILE_SIZE = 10 * 1024 * 1024;
  var ALLOWED_EXTENSIONS = ["pdf", "csv", "txt"];

  var isChatStreaming = false;
  var currentReviewSessionId = null; // session being reviewed

  // ---- Helpers ----

  function getExtension(name) {
    var parts = name.split(".");
    return parts.length > 1 ? parts[parts.length - 1].toLowerCase() : "";
  }

  function escHtml(str) {
    var d = document.createElement("div");
    d.textContent = String(str == null ? "" : str);
    return d.innerHTML;
  }

  function formatCurrency(milliunits) {
    return (milliunits / 1000).toLocaleString("en-US", { style: "currency", currency: "USD" });
  }

  function showUploadError(msg) {
    uploadError.textContent = msg;
    uploadError.style.display = "block";
  }

  function hideUploadError() {
    uploadError.style.display = "none";
    uploadError.textContent = "";
  }

  // ---- QueueManager ----

  var QueueManager = {
    sessions: [],          // {session_id, file_name, institution_name, status, stage, elapsed, normalization}
    processingId: null,
    sseReader: null,
    uploadAbort: null,
    elapsedTimer: null,
    stopUploadRequested: false,

    findSession: function (id) {
      return this.sessions.find(function (s) { return s.session_id === id; }) || null;
    },

    uploadFiles: async function (files) {
      var profileId = profileSelect ? profileSelect.value : "";
      for (var i = 0; i < files.length; i++) {
        if (this.stopUploadRequested) { this.stopUploadRequested = false; break; }
        var file = files[i];
        var ext = getExtension(file.name);
        if (ALLOWED_EXTENSIONS.indexOf(ext) === -1) {
          showUploadError("Unsupported file type: " + file.name + ". Accepted: .pdf, .csv, .txt");
          continue;
        }
        if (file.size > MAX_FILE_SIZE) {
          showUploadError(file.name + " exceeds the 10 MB size limit.");
          continue;
        }

        var formData = new FormData();
        formData.append("file", file);
        formData.append("institution_profile_id", profileId);

        this.uploadAbort = new AbortController();
        stopBtn.style.display = "inline-block";
        uploadBtn.disabled = true;

        try {
          var resp = await fetch("/api/import/upload", {
            method: "POST",
            body: formData,
            signal: this.uploadAbort.signal,
          });
          var data = await resp.json();
          if (!resp.ok || data.status !== "success") {
            showUploadError(data.message || data.detail || "Upload failed for " + file.name);
            continue;
          }

          var session = {
            session_id: data.session_id,
            file_name: data.file_name || file.name,
            institution_name: null,
            status: "pending",
            stage: null,
            elapsed: 0,
            normalization: null,
            duplicate_file_warning: data.duplicate_file_warning || null,
          };
          this.sessions.push(session);
          this.renderQueue();
          this.showQueueSection();
          hideUploadError();
        } catch (err) {
          if (err.name === "AbortError") {
            // Upload aborted by user
          } else {
            showUploadError("Upload failed for " + file.name + ": " + err.message);
          }
        }
      }

      this.uploadAbort = null;
      stopBtn.style.display = "none";
      uploadBtn.disabled = false;
      fileInput.value = "";
      fileNameDisplay.textContent = "";

      this.processNext();
    },

    processNext: async function () {
      if (this.processingId !== null) return; // already processing
      var pending = this.sessions.find(function (s) { return s.status === "pending"; });
      if (!pending) return;

      this.processingId = pending.session_id;
      pending.status = "processing";
      pending.stage = "extracting";
      pending.elapsed = 0;
      this.renderQueue();

      // Start elapsed timer
      var self = this;
      this.elapsedTimer = setInterval(function () {
        var s = self.findSession(self.processingId);
        if (s) {
          s.elapsed++;
          self.renderQueueRow(s);
        }
      }, 1000);

      try {
        var resp = await fetch("/api/import/process/" + pending.session_id);
        if (!resp.ok) {
          pending.status = "failed";
          pending.stage = null;
          this.finishProcessing();
          return;
        }

        var reader = resp.body.getReader();
        this.sseReader = reader;
        var decoder = new TextDecoder();
        var buffer = "";
        var done = false;

        while (!done) {
          var chunk = await reader.read();
          if (chunk.done) { done = true; break; }
          buffer += decoder.decode(chunk.value, { stream: true });

          var lines = buffer.split("\n\n");
          buffer = lines.pop();

          for (var li = 0; li < lines.length; li++) {
            var line = lines[li].trim();
            if (!line.startsWith("data: ")) continue;
            var payload = line.slice(6);
            try {
              var event = JSON.parse(payload);
              if (event.stage === "extracting" || event.stage === "normalizing") {
                pending.stage = event.stage;
                this.renderQueueRow(pending);
              } else if (event.stage === "vision") {
                pending.stage = "vision " + event.page + "/" + event.total;
                this.renderQueueRow(pending);
              } else if (event.stage === "done") {
                pending.status = "reviewing";
                pending.stage = null;
                pending.normalization = event.normalization;
                pending.institution_name = (event.normalization || {}).institution_name || null;
                done = true;
              } else if (event.stage === "error") {
                pending.status = "failed";
                pending.stage = event.message || "Failed";
                done = true;
              } else if (event.stage === "cancelled") {
                // Session was cancelled by another tab; remove from local queue
                QueueManager.sessions = QueueManager.sessions.filter(function (s) { return s.session_id !== pending.session_id; });
                done = true;
              }
            } catch (e) { /* ignore parse error */ }
          }
        }
      } catch (err) {
        if (err.name !== "AbortError") {
          pending.status = "failed";
        }
      }

      this.finishProcessing();
    },

    finishProcessing: function () {
      clearInterval(this.elapsedTimer);
      this.elapsedTimer = null;
      this.sseReader = null;
      this.processingId = null;
      this.renderQueue();
      this.processNext(); // start next pending item
    },

    openReview: async function (sessionId) {
      var session = this.findSession(sessionId);
      if (!session || session.status !== "reviewing") return;

      // Fetch normalization data if not loaded yet (e.g., after page restore)
      if (!session.normalization) {
        try {
          var resp = await fetch("/api/import/session/" + sessionId);
          if (resp.ok) {
            var data = await resp.json();
            if (data.normalization) {
              session.normalization = data.normalization;
              session.institution_name = (data.normalization || {}).institution_name || session.institution_name;
            }
          }
        } catch (e) { /* continue with empty normalization */ }
      }

      currentReviewSessionId = sessionId;
      isChatStreaming = false;

      // Reset chat
      if (chatMessages) {
        chatMessages.innerHTML = "";
        var initBubble = document.createElement("div");
        initBubble.className = "import-bubble import-bubble--assistant";
        initBubble.textContent = "I've analyzed your document. Do you see anything that needs correction?";
        chatMessages.appendChild(initBubble);
      }
      if (chatInput) { chatInput.value = ""; chatInput.disabled = false; chatInput.style.height = ""; }
      if (chatSendBtn) { chatSendBtn.disabled = false; }
      if (confirmPanel) { confirmPanel.classList.remove("open"); }
      if (confirmError) { confirmError.style.display = "none"; }
      if (confirmSaveBtn) { confirmSaveBtn.disabled = false; confirmSaveBtn.textContent = "Save Import"; }
      if (confirmBtn) { confirmBtn.disabled = false; }
      if (confirmAccountName) { confirmAccountName.value = ""; }
      if (confirmSaveProfile) { confirmSaveProfile.checked = false; }

      renderReview({
        normalization: session.normalization || {},
        duplicate_file_warning: session.duplicate_file_warning,
        vision_needed: false,
      });

      uploadState.style.display = "none";
      reviewState.style.display = "block";
    },

    cancel: async function (sessionId) {
      var session = this.findSession(sessionId);
      if (!session) return;

      // If this is the currently processing session, stop SSE first
      if (this.processingId === sessionId && this.sseReader) {
        try { await this.sseReader.cancel(); } catch (e) { /* ignore */ }
        clearInterval(this.elapsedTimer);
        this.elapsedTimer = null;
        this.sseReader = null;
        this.processingId = null;
      }

      try {
        await fetch("/api/import/cancel/" + sessionId, { method: "POST" });
      } catch (e) { /* fire-and-forget */ }

      this.sessions = this.sessions.filter(function (s) { return s.session_id !== sessionId; });
      this.renderQueue();
      if (this.sessions.length === 0) queueSection.style.display = "none";
      this.processNext();
    },

    stopActive: function () {
      if (this.uploadAbort) {
        this.stopUploadRequested = true;
        this.uploadAbort.abort();
        this.uploadAbort = null;
        stopBtn.style.display = "none";
        uploadBtn.disabled = false;
      } else if (this.processingId !== null) {
        var id = this.processingId;
        if (this.sseReader) {
          try { this.sseReader.cancel(); } catch (e) { /* ignore */ }
          this.sseReader = null;
        }
        clearInterval(this.elapsedTimer);
        this.elapsedTimer = null;
        this.processingId = null;
        var session = this.findSession(id);
        if (session) { session.status = "cancelled"; }
        // Call cancel endpoint (fire-and-forget)
        fetch("/api/import/cancel/" + id, { method: "POST" }).catch(function () {});
        // Remove cancelled session from list
        this.sessions = this.sessions.filter(function (s) { return s.session_id !== id; });
        this.renderQueue();
        if (this.sessions.length === 0) queueSection.style.display = "none";
        this.processNext();
      }
    },

    restore: async function () {
      try {
        var resp = await fetch("/api/import/sessions/active");
        if (!resp.ok) return;
        var data = await resp.json();
        var remoteSessions = data.sessions || [];
        if (remoteSessions.length === 0) return;

        this.sessions = remoteSessions.map(function (s) {
          return {
            session_id: s.id,
            file_name: s.file_name,
            institution_name: s.institution_name,
            status: s.status,
            stage: null,
            elapsed: 0,
            normalization: null,
            duplicate_file_warning: null,
          };
        });
        this.renderQueue();
        this.showQueueSection();
        // Resume processing if any pending sessions
        this.processNext();
      } catch (e) { /* ignore restore errors */ }
    },

    showQueueSection: function () {
      if (this.sessions.length > 0) queueSection.style.display = "block";
    },

    renderQueue: function () {
      queueTbody.innerHTML = "";
      var self = this;
      this.sessions.forEach(function (s) {
        self.renderQueueRow(s);
      });
    },

    renderQueueRow: function (session) {
      var existingRow = document.getElementById("queue-row-" + session.session_id);
      var tr = document.createElement("tr");
      tr.id = "queue-row-" + session.session_id;

      // File name cell
      var tdFile = document.createElement("td");
      tdFile.textContent = session.file_name;
      tr.appendChild(tdFile);

      // Institution cell
      var tdInst = document.createElement("td");
      tdInst.textContent = session.institution_name || "\u2014";
      tr.appendChild(tdInst);

      // Status cell
      var tdStatus = document.createElement("td");
      var statusText = "";
      var statusClass = "";
      if (session.status === "processing") {
        var stageLabel = session.stage || "processing";
        statusText = "\u27F3 " + stageLabel + " (" + session.elapsed + "s)";
        statusClass = "queue-status--processing";
      } else if (session.status === "reviewing") {
        statusText = "\u2713 Ready to Review";
        statusClass = "queue-status--reviewing";
      } else if (session.status === "pending") {
        statusText = "\u23F8 Waiting";
        statusClass = "queue-status--waiting";
      } else if (session.status === "failed") {
        statusText = "\u2715 Failed";
        statusClass = "queue-status--failed";
      } else if (session.status === "confirmed") {
        statusText = "\u2713 Confirmed";
        statusClass = "queue-status--confirmed";
      }
      var span = document.createElement("span");
      span.className = statusClass;
      span.textContent = statusText;
      tdStatus.appendChild(span);
      tr.appendChild(tdStatus);

      // Actions cell
      var tdActions = document.createElement("td");
      tdActions.style.display = "flex";
      tdActions.style.gap = "0.4rem";
      tdActions.style.alignItems = "center";

      if (session.status === "reviewing") {
        var reviewBtn = document.createElement("button");
        reviewBtn.type = "button";
        reviewBtn.className = "btn btn--primary btn--review";
        reviewBtn.textContent = "Review";
        var sid = session.session_id;
        reviewBtn.addEventListener("click", function () { QueueManager.openReview(sid); });
        tdActions.appendChild(reviewBtn);
      }

      if (session.status === "pending" || session.status === "reviewing" || session.status === "failed") {
        var cancelBtn = document.createElement("button");
        cancelBtn.type = "button";
        cancelBtn.className = "btn--cancel-row";
        cancelBtn.title = "Remove";
        cancelBtn.textContent = "\u2715";
        var sid2 = session.session_id;
        cancelBtn.addEventListener("click", function () { QueueManager.cancel(sid2); });
        tdActions.appendChild(cancelBtn);
      }

      tr.appendChild(tdActions);

      if (existingRow) {
        existingRow.parentNode.replaceChild(tr, existingRow);
      } else {
        queueTbody.appendChild(tr);
      }
    },

    loadHistory: async function () {
      if (!historyContent || historyContent.style.display === "none") return;
      if (historyLoading) historyLoading.style.display = "block";
      try {
        var resp = await fetch("/api/import/history");
        if (!resp.ok) { if (historyLoading) historyLoading.style.display = "none"; return; }
        var data = await resp.json();
        renderHistorySessions(data.sessions || []);
        renderHistoryAccounts(data.accounts || []);
      } catch (e) {
        // ignore
      } finally {
        if (historyLoading) historyLoading.style.display = "none";
      }
    },
  };

  // ---- History rendering ----

  function renderHistorySessions(sessions) {
    if (!historySessions) return;
    if (sessions.length === 0) {
      historySessions.innerHTML = '<p style="color:var(--muted);font-size:0.9rem;">No confirmed imports yet.</p>';
      return;
    }

    var html = '<div class="rows-table-wrap" style="max-height:300px;"><table class="rows-table"><thead><tr><th>Date</th><th>File</th><th>Institution</th><th class="right">Transactions</th><th class="right">Balances</th><th>Actions</th></tr></thead><tbody>';
    sessions.forEach(function (s) {
      var date = s.confirmed_at ? s.confirmed_at.substring(0, 10) : "\u2014";
      var hasRows = (s.transaction_count > 0 || s.balance_count > 0);
      html += '<tr id="hist-session-' + s.id + '">';
      html += '<td>' + escHtml(date) + '</td>';
      html += '<td>' + escHtml(s.file_name) + '</td>';
      html += '<td>' + escHtml(s.institution_name || "\u2014") + '</td>';
      html += '<td class="right" id="hist-txn-count-' + s.id + '">' + s.transaction_count + '</td>';
      html += '<td class="right" id="hist-bal-count-' + s.id + '">' + s.balance_count + '</td>';
      html += '<td>';
      if (hasRows) {
        html += '<button type="button" class="btn btn--danger" id="hist-del-btn-' + s.id + '" onclick="deleteSessionRows(' + s.id + ')">Delete Rows</button>';
      } else {
        html += '<span style="color:var(--muted);font-size:0.8rem;">Rows deleted</span>';
      }
      html += '</td></tr>';
    });
    html += '</tbody></table></div>';
    historySessions.innerHTML = html;
  }

  function renderHistoryAccounts(accounts) {
    if (!historyAccounts) return;
    if (accounts.length === 0) {
      historyAccounts.innerHTML = '<p style="color:var(--muted);font-size:0.9rem;">No external accounts.</p>';
      return;
    }
    var html = '<div class="rows-table-wrap" style="max-height:250px;"><table class="rows-table"><thead><tr><th>Account</th><th>Type</th><th>Institution</th><th>Status</th><th>Actions</th></tr></thead><tbody>';
    accounts.forEach(function (a) {
      html += '<tr id="hist-acct-' + a.id + '">';
      html += '<td>' + escHtml(a.name) + '</td>';
      html += '<td>' + escHtml(a.account_type || "\u2014") + '</td>';
      html += '<td>' + escHtml(a.institution || "\u2014") + '</td>';
      html += '<td id="hist-acct-status-' + a.id + '">' + (a.is_active ? '<span style="color:var(--success)">Active</span>' : '<span style="color:var(--muted)">Inactive</span>') + '</td>';
      html += '<td>';
      if (a.is_active) {
        html += '<button type="button" class="btn btn--neutral" style="font-size:0.8rem;padding:0.3rem 0.6rem;" onclick="toggleAccount(' + a.id + ', false)">Deactivate</button>';
      } else {
        html += '<button type="button" class="btn btn--primary" style="font-size:0.8rem;padding:0.3rem 0.6rem;" onclick="toggleAccount(' + a.id + ', true)">Reactivate</button>';
      }
      html += '</td></tr>';
    });
    html += '</tbody></table></div>';
    historyAccounts.innerHTML = html;
  }

  window.deleteSessionRows = async function (sessionId) {
    if (!confirm("Delete all imported rows for this session? This removes the data from dashboard widgets and reports. The import record itself is kept.")) return;
    var btn = document.getElementById("hist-del-btn-" + sessionId);
    if (btn) { btn.disabled = true; btn.textContent = "Deleting\u2026"; }
    try {
      var resp = await fetch("/api/import/session/" + sessionId + "/rows", { method: "DELETE" });
      var data = await resp.json();
      if (resp.ok && data.status === "success") {
        var txnCell = document.getElementById("hist-txn-count-" + sessionId);
        var balCell = document.getElementById("hist-bal-count-" + sessionId);
        if (txnCell) txnCell.textContent = "0";
        if (balCell) balCell.textContent = "0";
        if (btn) {
          btn.outerHTML = '<span style="color:var(--muted);font-size:0.8rem;">Rows deleted</span>';
        }
      } else {
        if (btn) { btn.disabled = false; btn.textContent = "Delete Rows"; }
        alert("Failed to delete rows.");
      }
    } catch (e) {
      if (btn) { btn.disabled = false; btn.textContent = "Delete Rows"; }
      alert("Failed to delete rows.");
    }
  };

  window.toggleAccount = async function (accountId, isActive) {
    try {
      var resp = await fetch("/api/import/account/" + accountId, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ is_active: isActive }),
      });
      var data = await resp.json();
      if (resp.ok && data.status === "success") {
        var statusCell = document.getElementById("hist-acct-status-" + accountId);
        if (statusCell) {
          statusCell.innerHTML = isActive
            ? '<span style="color:var(--success)">Active</span>'
            : '<span style="color:var(--muted)">Inactive</span>';
        }
        var row = document.getElementById("hist-acct-" + accountId);
        if (row) {
          var actionCell = row.cells[4];
          if (actionCell) {
            if (isActive) {
              actionCell.innerHTML = '<button type="button" class="btn btn--neutral" style="font-size:0.8rem;padding:0.3rem 0.6rem;" onclick="toggleAccount(' + accountId + ', false)">Deactivate</button>';
            } else {
              actionCell.innerHTML = '<button type="button" class="btn btn--primary" style="font-size:0.8rem;padding:0.3rem 0.6rem;" onclick="toggleAccount(' + accountId + ', true)">Reactivate</button>';
            }
          }
        }
      }
    } catch (e) {
      alert("Failed to update account.");
    }
  };

  // ---- Review rendering (preserved from original) ----

  function renderReview(data) {
    var norm = data.normalization || {};
    var institution = norm.institution_name || "Unknown institution";
    var accountName = norm.account_name || "\u2014";
    var dataType = norm.data_type || "unknown";
    var rows = norm.rows || [];
    var summary = norm.summary || "";
    var questions = norm.questions || [];

    var html = '<div class="summary-card__title"></div>';
    html += '<div class="summary-card__row"><span class="summary-card__label">Institution:</span><span class="summary-card__value" id="sc-institution"></span></div>';
    html += '<div class="summary-card__row"><span class="summary-card__label">Account:</span><span class="summary-card__value" id="sc-account"></span></div>';
    html += '<div class="summary-card__row"><span class="summary-card__label">Data type:</span><span class="summary-card__value" id="sc-datatype"></span></div>';
    html += '<div class="summary-card__row"><span class="summary-card__label">Rows found:</span><span class="summary-card__value" id="sc-rowcount"></span></div>';
    html += '<div class="summary-card__row"><span class="summary-card__label">Summary:</span><span class="summary-card__value" id="sc-summary"></span></div>';
    if (questions.length > 0) {
      html += '<div class="summary-card__questions"><div class="summary-card__questions-title">AI has questions:</div><ul id="sc-questions"></ul></div>';
    }
    summaryCard.innerHTML = html;
    document.getElementById("sc-institution").textContent = institution;
    document.getElementById("sc-account").textContent = accountName;
    document.getElementById("sc-datatype").textContent = dataType;
    document.getElementById("sc-rowcount").textContent = String(rows.length);
    document.getElementById("sc-summary").textContent = summary;
    if (questions.length > 0) {
      var qList = document.getElementById("sc-questions");
      questions.forEach(function (q) {
        var li = document.createElement("li");
        li.textContent = q;
        qList.appendChild(li);
      });
    }
    if (data.duplicate_file_warning) {
      var confirmedDate = data.duplicate_file_warning.confirmed_at || "unknown date";
      duplicateWarning.textContent = "This file appears to have been imported before (on " + confirmedDate.substring(0, 10) + ").";
      duplicateWarning.style.display = "block";
    } else {
      duplicateWarning.style.display = "none";
    }
    visionNotice.style.display = data.vision_needed ? "block" : "none";
    renderRowsTable(rows, dataType);
  }

  function renderRowsTable(rows, dataType) {
    rowsThead.innerHTML = "";
    rowsTbody.innerHTML = "";
    if (rows.length === 0) {
      var emptyRow = document.createElement("tr");
      var emptyCell = document.createElement("td");
      emptyCell.setAttribute("colspan", "6");
      emptyCell.textContent = "No rows extracted.";
      emptyCell.style.textAlign = "center";
      emptyCell.style.color = "var(--muted)";
      emptyCell.style.padding = "1.5rem";
      emptyRow.appendChild(emptyCell);
      rowsTbody.appendChild(emptyRow);
      return;
    }
    var hasTransactions = false;
    var hasBalances = false;
    rows.forEach(function (r) {
      if (r.type === "transaction") hasTransactions = true;
      if (r.type === "balance") hasBalances = true;
    });
    var columns = [{ key: "date", label: "Date", align: "left" }];
    if (hasTransactions) columns.push({ key: "description", label: "Description", align: "left" });
    columns.push({ key: "amount_milliunits", label: "Amount", align: "right" });
    if (hasTransactions) columns.push({ key: "category", label: "Category", align: "left" });
    if (hasBalances) {
      columns.push({ key: "notes", label: "Notes", align: "left" });
      columns.push({ key: "contribution_milliunits", label: "Contribution", align: "right" });
      columns.push({ key: "return_bps", label: "Return", align: "right" });
    }
    columns.push({ key: "duplicate", label: "Duplicate?", align: "left" });
    var headerRow = document.createElement("tr");
    columns.forEach(function (col) {
      var th = document.createElement("th");
      th.textContent = col.label;
      if (col.align === "right") th.classList.add("right");
      headerRow.appendChild(th);
    });
    rowsThead.appendChild(headerRow);
    rows.forEach(function (row) {
      var tr = document.createElement("tr");
      columns.forEach(function (col) {
        var td = document.createElement("td");
        if (col.align === "right") td.classList.add("right");
        if (col.key === "amount_milliunits") {
          var amt = row.amount_milliunits;
          td.textContent = amt != null ? formatCurrency(amt) : "\u2014";
        } else if (col.key === "contribution_milliunits") {
          var contrib = row.contribution_milliunits;
          td.textContent = contrib != null ? formatCurrency(contrib) : "\u2014";
        } else if (col.key === "return_bps") {
          var bps = row.return_bps;
          td.textContent = bps != null ? (bps / 100).toFixed(2) + "%" : "\u2014";
        } else if (col.key === "duplicate") {
          if (row.duplicate === "exact") {
            var dupSpan = document.createElement("span");
            dupSpan.className = "dup-exact";
            dupSpan.textContent = "\u26A0 Exact duplicate (will skip)";
            td.appendChild(dupSpan);
          } else if (row.duplicate === "near") {
            var nearSpan = document.createElement("span");
            nearSpan.className = "dup-near";
            nearSpan.textContent = "\u26A0 Near duplicate";
            if (row.existing_description) nearSpan.title = "Existing: " + row.existing_description;
            td.appendChild(nearSpan);
          }
        } else {
          var val = row[col.key];
          td.textContent = val != null ? String(val) : "\u2014";
        }
        tr.appendChild(td);
      });
      rowsTbody.appendChild(tr);
    });
  }

  // ---- Event wiring ----

  // File selection
  chooseBtn.addEventListener("click", function (e) { e.stopPropagation(); fileInput.click(); });
  dropZone.addEventListener("click", function () { fileInput.click(); });
  fileInput.addEventListener("change", function () {
    if (fileInput.files && fileInput.files.length > 0) {
      var names = [];
      for (var i = 0; i < fileInput.files.length; i++) names.push(fileInput.files[i].name);
      fileNameDisplay.textContent = names.join(", ");
      uploadBtn.disabled = false;
      hideUploadError();
    }
  });

  dropZone.addEventListener("dragover", function (e) { e.preventDefault(); dropZone.classList.add("drop-zone--over"); });
  dropZone.addEventListener("dragleave", function () { dropZone.classList.remove("drop-zone--over"); });
  dropZone.addEventListener("drop", function (e) {
    e.preventDefault();
    dropZone.classList.remove("drop-zone--over");
    if (e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      var names = [];
      for (var i = 0; i < e.dataTransfer.files.length; i++) names.push(e.dataTransfer.files[i].name);
      fileNameDisplay.textContent = names.join(", ");
      uploadBtn.disabled = false;
      hideUploadError();
      var dt = new DataTransfer();
      for (var j = 0; j < e.dataTransfer.files.length; j++) dt.items.add(e.dataTransfer.files[j]);
      fileInput.files = dt.files;
    }
  });

  uploadBtn.addEventListener("click", async function () {
    if (!fileInput.files || fileInput.files.length === 0) return;
    hideUploadError();
    await QueueManager.uploadFiles(fileInput.files);
  });

  stopBtn.addEventListener("click", function () { QueueManager.stopActive(); });

  // Back to queue from review
  if (backToQueueBtn) {
    backToQueueBtn.addEventListener("click", function () {
      reviewState.style.display = "none";
      uploadState.style.display = "block";
      currentReviewSessionId = null;
    });
  }

  // Confirm button
  if (confirmBtn) {
    confirmBtn.addEventListener("click", function () {
      var instEl = document.getElementById("sc-institution");
      if (instEl && instEl.textContent && instEl.textContent !== "Unknown institution") {
        confirmAccountName.value = instEl.textContent;
      }
      confirmPanel.classList.add("open");
      confirmBtn.disabled = true;
      confirmAccountName.focus();
    });
  }
  if (confirmBackBtn) {
    confirmBackBtn.addEventListener("click", function () {
      confirmPanel.classList.remove("open");
      if (confirmError) confirmError.style.display = "none";
      if (confirmBtn) confirmBtn.disabled = false;
    });
  }
  if (confirmSaveBtn) {
    confirmSaveBtn.addEventListener("click", async function () {
      var accountName = confirmAccountName.value.trim();
      if (!accountName) {
        if (confirmError) { confirmError.textContent = "Account name is required."; confirmError.style.display = "block"; }
        return;
      }
      if (confirmError) confirmError.style.display = "none";
      confirmSaveBtn.disabled = true;
      confirmSaveBtn.textContent = "Saving\u2026";
      try {
        var resp = await fetch("/api/import/confirm/" + currentReviewSessionId, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            account_name: accountName,
            account_type: confirmAccountType.value,
            save_institution_profile: confirmSaveProfile ? confirmSaveProfile.checked : false,
          }),
        });
        var data = await resp.json();
        if (!resp.ok || data.status !== "success") throw new Error(data.message || data.detail || "Confirm failed.");

        // Remove from queue, return to queue view
        QueueManager.sessions = QueueManager.sessions.filter(function (s) { return s.session_id !== currentReviewSessionId; });
        QueueManager.renderQueue();
        if (QueueManager.sessions.length === 0) queueSection.style.display = "none";

        reviewState.style.display = "none";
        uploadState.style.display = "block";
        currentReviewSessionId = null;

        // Refresh history
        QueueManager.loadHistory();
      } catch (err) {
        if (confirmError) { confirmError.textContent = err.message || "Failed to save import."; confirmError.style.display = "block"; }
        confirmSaveBtn.disabled = false;
        confirmSaveBtn.textContent = "Save Import";
      }
    });
  }

  // Chat
  function appendChatBubble(role, text) {
    var div = document.createElement("div");
    div.className = "import-bubble import-bubble--" + role;
    div.textContent = text;
    if (chatMessages) {
      chatMessages.appendChild(div);
      chatMessages.scrollTop = chatMessages.scrollHeight;
    }
    return div;
  }

  function appendDataUpdateNotice() {
    var div = document.createElement("div");
    div.className = "data-update-notice";
    div.textContent = "\u2713 Extracted data updated";
    if (chatMessages) {
      chatMessages.appendChild(div);
      chatMessages.scrollTop = chatMessages.scrollHeight;
    }
  }

  async function sendChatMessage() {
    if (isChatStreaming || !currentReviewSessionId) return;
    var text = chatInput.value.trim();
    if (!text) return;
    chatInput.value = "";
    chatInput.style.height = "";
    isChatStreaming = true;
    chatSendBtn.disabled = true;
    chatInput.disabled = true;
    appendChatBubble("user", text);
    var assistantBubble = appendChatBubble("assistant", "");
    var accumulatedText = "";
    try {
      var resp = await fetch("/api/import/chat/" + currentReviewSessionId, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ content: text }),
      });
      if (!resp.ok) { assistantBubble.textContent = "Error: could not reach the server."; return; }
      var reader = resp.body.getReader();
      var decoder = new TextDecoder();
      var buffer = "";
      while (true) {
        var result = await reader.read();
        if (result.done) break;
        buffer += decoder.decode(result.value, { stream: true });
        var lines = buffer.split("\n\n");
        buffer = lines.pop();
        for (var i = 0; i < lines.length; i++) {
          var line = lines[i];
          if (!line.startsWith("data: ")) continue;
          var payload = line.slice(6);
          if (payload === "[DONE]") { break; }
          else if (payload.startsWith("[ERROR]")) { assistantBubble.textContent = "Error: " + payload.slice(7).trim(); }
          else if (payload.startsWith("[DATA_UPDATE]")) {
            try {
              var updatedNorm = JSON.parse(payload.slice("[DATA_UPDATE]".length));
              renderRowsTable(updatedNorm.rows || [], updatedNorm.data_type || "unknown");
              // Update the session normalization in memory
              var s = QueueManager.findSession(currentReviewSessionId);
              if (s) s.normalization = updatedNorm;
              appendDataUpdateNotice();
            } catch (e) { /* ignore parse error */ }
          } else {
            var chunk = payload.replace(/\\n/g, "\n");
            accumulatedText += chunk;
            assistantBubble.textContent = accumulatedText;
            if (chatMessages) chatMessages.scrollTop = chatMessages.scrollHeight;
          }
        }
      }
    } catch (err) {
      assistantBubble.textContent = "Error: " + err.message;
    } finally {
      isChatStreaming = false;
      chatSendBtn.disabled = false;
      chatInput.disabled = false;
      chatInput.focus();
    }
  }

  if (chatSendBtn) chatSendBtn.addEventListener("click", sendChatMessage);
  if (chatInput) {
    chatInput.addEventListener("keydown", function (e) {
      if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendChatMessage(); }
    });
    chatInput.addEventListener("input", function () {
      this.style.height = "";
      this.style.height = Math.min(this.scrollHeight, 96) + "px";
    });
  }

  // History toggle
  if (historyToggleBtn && historyContent) {
    historyToggleBtn.addEventListener("click", function () {
      var isOpen = historyContent.style.display !== "none";
      historyContent.style.display = isOpen ? "none" : "block";
      historyToggleIcon.textContent = isOpen ? "\u25BC" : "\u25B2";
      if (!isOpen) QueueManager.loadHistory();
    });
  }

  // Institution profiles toggle (preserved)
  if (profilesToggleBtn && profilesList) {
    profilesToggleBtn.addEventListener("click", function () {
      var isOpen = profilesList.classList.toggle("open");
      document.getElementById("profiles-toggle-icon").textContent = isOpen ? "\u25B2" : "\u25BC";
    });
  }

  window.deleteInstitutionProfile = async function (profileId, btn) {
    if (!confirm("Delete this institution profile? This cannot be undone.")) return;
    btn.disabled = true;
    try {
      var resp = await fetch("/api/import/institution/" + profileId, { method: "DELETE" });
      if (resp.ok) {
        var row = document.getElementById("profile-row-" + profileId);
        if (row) row.remove();
      } else { btn.disabled = false; alert("Failed to delete profile."); }
    } catch (e) { btn.disabled = false; alert("Failed to delete profile."); }
  };

  // ---- Init ----
  document.addEventListener("DOMContentLoaded", function () {
    QueueManager.restore();
  });
  // Also call restore immediately in case DOMContentLoaded already fired
  if (document.readyState !== "loading") {
    QueueManager.restore();
  }

})();
