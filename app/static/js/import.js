/**
 * Import page — file upload + review rendering (Milestone 3).
 * No chat (M4) or confirm/cancel logic (M5) beyond UI placeholders.
 */
(function () {
  "use strict";

  var MAX_FILE_SIZE = 10 * 1024 * 1024; // 10 MB
  var ALLOWED_EXTENSIONS = ["pdf", "csv", "txt"];

  // -- DOM refs --
  var uploadState = document.getElementById("upload-state");
  var reviewState = document.getElementById("review-state");
  var dropZone = document.getElementById("drop-zone");
  var fileInput = document.getElementById("file-input");
  var chooseBtn = document.getElementById("choose-file-btn");
  var fileNameDisplay = document.getElementById("file-name-display");
  var uploadBtn = document.getElementById("upload-btn");
  var uploadSpinner = document.getElementById("upload-spinner");
  var uploadError = document.getElementById("upload-error");
  var profileSelect = document.getElementById("institution-profile-select");

  // Review refs
  var duplicateWarning = document.getElementById("duplicate-warning");
  var visionNotice = document.getElementById("vision-notice");
  var summaryCard = document.getElementById("summary-card");
  var rowsThead = document.getElementById("rows-thead");
  var rowsTbody = document.getElementById("rows-tbody");
  var cancelBtn = document.getElementById("cancel-btn");
  var startOverBtn = document.getElementById("start-over-btn");

  var selectedFile = null;

  // -- Helpers --

  function getExtension(name) {
    var parts = name.split(".");
    return parts.length > 1 ? parts[parts.length - 1].toLowerCase() : "";
  }

  function showError(msg) {
    uploadError.textContent = msg;
    uploadError.style.display = "block";
  }

  function hideError() {
    uploadError.style.display = "none";
    uploadError.textContent = "";
  }

  function validateFile(file) {
    var ext = getExtension(file.name);
    if (ALLOWED_EXTENSIONS.indexOf(ext) === -1) {
      showError("Unsupported file type. Accepted: .pdf, .csv, .txt");
      return false;
    }
    if (file.size > MAX_FILE_SIZE) {
      showError("File exceeds the 10 MB size limit.");
      return false;
    }
    return true;
  }

  function setFile(file) {
    if (!validateFile(file)) {
      selectedFile = null;
      fileNameDisplay.textContent = "";
      uploadBtn.disabled = true;
      return;
    }
    hideError();
    selectedFile = file;
    fileNameDisplay.textContent = file.name;
    uploadBtn.disabled = false;
  }

  function formatCurrency(milliunits) {
    var dollars = milliunits / 1000;
    return dollars.toLocaleString("en-US", { style: "currency", currency: "USD" });
  }

  function resetPage() {
    selectedFile = null;
    fileInput.value = "";
    fileNameDisplay.textContent = "";
    uploadBtn.disabled = true;
    uploadBtn.textContent = "Upload and Analyze";
    uploadSpinner.classList.remove("spinner--visible");
    hideError();
    profileSelect.selectedIndex = 0;

    reviewState.style.display = "none";
    uploadState.style.display = "block";
  }

  // -- File selection --

  chooseBtn.addEventListener("click", function (e) {
    e.stopPropagation();
    fileInput.click();
  });

  dropZone.addEventListener("click", function () {
    fileInput.click();
  });

  fileInput.addEventListener("change", function () {
    if (fileInput.files && fileInput.files.length > 0) {
      setFile(fileInput.files[0]);
    }
  });

  // -- Drag & drop --

  dropZone.addEventListener("dragover", function (e) {
    e.preventDefault();
    dropZone.classList.add("drop-zone--over");
  });

  dropZone.addEventListener("dragleave", function () {
    dropZone.classList.remove("drop-zone--over");
  });

  dropZone.addEventListener("drop", function (e) {
    e.preventDefault();
    dropZone.classList.remove("drop-zone--over");
    if (e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      setFile(e.dataTransfer.files[0]);
      // Sync file input so form data picks it up
      var dt = new DataTransfer();
      dt.items.add(e.dataTransfer.files[0]);
      fileInput.files = dt.files;
    }
  });

  // -- Upload --

  uploadBtn.addEventListener("click", async function () {
    if (!selectedFile) return;

    hideError();
    uploadBtn.disabled = true;
    uploadBtn.textContent = "Uploading\u2026";
    uploadSpinner.classList.add("spinner--visible");

    var formData = new FormData();
    formData.append("file", selectedFile);
    formData.append("institution_profile_id", profileSelect.value);

    try {
      var resp = await fetch("/api/import/upload", {
        method: "POST",
        body: formData,
      });
      var data = await resp.json();

      if (!resp.ok || data.status !== "success") {
        throw new Error(data.message || data.detail || "Upload failed.");
      }

      renderReview(data);
      uploadState.style.display = "none";
      reviewState.style.display = "block";
    } catch (err) {
      showError(err.message || "Upload failed.");
      uploadBtn.disabled = false;
      uploadBtn.textContent = "Upload and Analyze";
      uploadSpinner.classList.remove("spinner--visible");
    }
  });

  // -- Review rendering --

  function renderReview(data) {
    var norm = data.normalization || {};

    // Summary card
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

    // Populate text content safely (no XSS)
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

    // Duplicate file warning
    if (data.duplicate_file_warning) {
      var confirmedDate = data.duplicate_file_warning.confirmed_at || "unknown date";
      duplicateWarning.textContent =
        "This file appears to have been imported before (on " + confirmedDate.substring(0, 10) + ").";
      duplicateWarning.style.display = "block";
    } else {
      duplicateWarning.style.display = "none";
    }

    // Vision notice
    visionNotice.style.display = data.vision_needed ? "block" : "none";

    // Rows table
    renderRowsTable(rows, dataType);
  }

  function renderRowsTable(rows, dataType) {
    // Clear
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

    // Determine columns based on data type
    var hasTransactions = false;
    var hasBalances = false;
    rows.forEach(function (r) {
      if (r.type === "transaction") hasTransactions = true;
      if (r.type === "balance") hasBalances = true;
    });

    var columns = [];
    columns.push({ key: "date", label: "Date", align: "left" });

    if (hasTransactions) {
      columns.push({ key: "description", label: "Description", align: "left" });
    }

    columns.push({ key: "amount_milliunits", label: "Amount", align: "right" });

    if (hasTransactions) {
      columns.push({ key: "category", label: "Category", align: "left" });
    }

    if (hasBalances) {
      columns.push({ key: "notes", label: "Notes", align: "left" });
      columns.push({ key: "contribution_milliunits", label: "Contribution", align: "right" });
      columns.push({ key: "return_bps", label: "Return", align: "right" });
    }

    columns.push({ key: "duplicate", label: "Duplicate?", align: "left" });

    // Header
    var headerRow = document.createElement("tr");
    columns.forEach(function (col) {
      var th = document.createElement("th");
      th.textContent = col.label;
      if (col.align === "right") th.classList.add("right");
      headerRow.appendChild(th);
    });
    rowsThead.appendChild(headerRow);

    // Body
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
            var span = document.createElement("span");
            span.className = "dup-exact";
            span.textContent = "\u26A0 Exact duplicate (will skip)";
            td.appendChild(span);
          } else if (row.duplicate === "near") {
            var nearSpan = document.createElement("span");
            nearSpan.className = "dup-near";
            nearSpan.textContent = "\u26A0 Near duplicate";
            if (row.existing_description) {
              nearSpan.title = "Existing: " + row.existing_description;
            }
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

  // -- Start over / cancel --

  cancelBtn.addEventListener("click", function () {
    resetPage();
  });

  startOverBtn.addEventListener("click", function (e) {
    e.preventDefault();
    resetPage();
  });
})();
