"use strict";

// The interface calls the existing API; recipient data stays in memory until submitted.
const $ = (id) => document.getElementById(id);
const EDITOR_PAGE_SIZE = 8;
const RESULTS_PAGE_SIZE = 20;
const MAX_RECIPIENTS = 10000;
const HISTORY_KEY = "certificate-generator.recent.v1";
const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const STATUS_LABELS = {
  PENDING: "Queued", PROCESSING: "Generating", COMPLETED: "Completed",
  COMPLETED_WITH_ERRORS: "Completed with errors", FAILED: "Failed",
};
const state = {
  recipients: [{ name: "", email: "" }], editorPage: 1, resultsPage: 1,
  activeJob: null, requestVersion: 0, pollTimer: null, submitting: false, importing: false,
  recent: [], toastTimer: null, downloads: new Set(),
  signatureImage: null, signatureMode: "draw", hasDrawn: false, uploadedSignature: null,
};

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function icon(name) {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("class", "icon");
  svg.setAttribute("aria-hidden", "true");
  const use = document.createElementNS(svg.namespaceURI, "use");
  use.setAttribute("href", `#i-${name}`);
  svg.append(use);
  return svg;
}

function notify(message) {
  clearTimeout(state.toastTimer);
  $("toast").textContent = message;
  $("toast").hidden = false;
  state.toastTimer = setTimeout(() => { $("toast").hidden = true; }, 4500);
}

function showNotice(id, message) {
  $(id).textContent = message;
  $(id).hidden = !message;
}

function today() {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
}

function formatCertificateDate(value) {
  if (!value) return "Certificate date";
  const date = new Date(`${value}T12:00:00`);
  return Number.isNaN(date.getTime()) ? "Certificate date" : new Intl.DateTimeFormat("en-GB", {
    day: "2-digit", month: "long", year: "numeric",
  }).format(date);
}

function updatePreview() {
  $("preview-name").textContent = state.recipients.find((person) => person.name.trim())?.name.trim() || "Recipient name";
  $("preview-title").textContent = $("certificate-title").value.trim() || "Your certificate title";
  $("preview-date").textContent = formatCertificateDate($("certificate-date").value);

  const sigImg = $("preview-signature-img");
  const clearBtn = $("clear-signature");
  if (state.signatureImage) {
    sigImg.src = state.signatureImage;
    sigImg.hidden = false;
    if (clearBtn) clearBtn.hidden = false;
  } else {
    sigImg.removeAttribute("src");
    sigImg.hidden = true;
    if (clearBtn) clearBtn.hidden = true;
  }
}

function renderRecipients() {
  const pageCount = Math.max(1, Math.ceil(state.recipients.length / EDITOR_PAGE_SIZE));
  state.editorPage = Math.max(1, Math.min(state.editorPage, pageCount));
  const start = (state.editorPage - 1) * EDITOR_PAGE_SIZE;
  const fragment = document.createDocumentFragment();
  state.recipients.slice(start, start + EDITOR_PAGE_SIZE).forEach((recipient, offset) => {
    const index = start + offset;
    const row = element("div", "recipient-row");
    row.append(element("span", "", String(index + 1).padStart(2, "0")));
    for (const field of ["name", "email"]) {
      const input = element("input");
      input.type = field === "email" ? "email" : "text";
      input.id = `recipient-${index}-${field}`;
      input.dataset.index = String(index);
      input.dataset.field = field;
      input.value = recipient[field];
      input.maxLength = field === "name" ? 120 : 320;
      input.placeholder = field === "name" ? "Full name" : "name@example.com";
      input.setAttribute("aria-label", `Recipient ${index + 1} ${field === "name" ? "full name" : "email address"}`);
      input.autocomplete = "off";
      input.required = true;
      row.append(input);
    }
    const remove = element("button", "icon-button");
    remove.type = "button";
    remove.dataset.remove = String(index);
    remove.setAttribute("aria-label", `Remove recipient ${index + 1}`);
    remove.append(icon("close"));
    row.append(remove);
    fragment.append(row);
  });
  $("recipient-rows").replaceChildren(fragment);
  $("recipient-count").textContent = `${state.recipients.length.toLocaleString()} recipient${state.recipients.length === 1 ? "" : "s"}`;
  $("editor-pagination").hidden = pageCount === 1;
  $("editor-page").textContent = `${state.editorPage} of ${pageCount}`;
  $("editor-prev").disabled = state.editorPage === 1;
  $("editor-next").disabled = state.editorPage === pageCount;
  $("add-recipient").disabled = state.recipients.length >= MAX_RECIPIENTS;
  updatePreview();
}

function focusRecipient(index, field) {
  state.editorPage = Math.floor(index / EDITOR_PAGE_SIZE) + 1;
  renderRecipients();
  const input = $(`recipient-${index}-${field}`);
  input.setAttribute("aria-invalid", "true");
  input.focus();
}

function validatedPayload() {
  const title = $("certificate-title").value.trim();
  if (!title || title.length > 200) {
    $("certificate-title").setAttribute("aria-invalid", "true");
    $("certificate-title").focus();
    throw new Error("Enter a certificate title between 1 and 200 characters.");
  }
  const dateInput = $("certificate-date");
  if (!dateInput.value || !dateInput.checkValidity()) {
    dateInput.setAttribute("aria-invalid", "true");
    dateInput.focus();
    throw new Error("Choose a valid certificate date.");
  }
  const recipients = state.recipients.map((person) => ({ name: person.name.trim(), email: person.email.trim() }));
  const emailProbe = document.createElement("input");
  emailProbe.type = "email";
  emailProbe.required = true;
  for (const [index, recipient] of recipients.entries()) {
    if (!recipient.name || recipient.name.length > 120) {
      focusRecipient(index, "name");
      throw new Error(`Recipient ${index + 1}: enter a name between 1 and 120 characters.`);
    }
    emailProbe.value = recipient.email;
    const hasValidDomain = /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(recipient.email);
    if (!emailProbe.checkValidity() || !hasValidDomain || recipient.email.length > 320) {
      focusRecipient(index, "email");
      throw new Error(`Recipient ${index + 1}: enter a valid email address.`);
    }
  }
  return {
    certificate_title: title,
    certificate_date: dateInput.value,
    recipients,
    signature_image: state.signatureImage || null,
  };
}

function errorDetail(detail) {
  if (typeof detail === "string") return detail;
  if (!Array.isArray(detail)) return "Something went wrong. Please try again.";
  return detail.slice(0, 5).map((error) => {
    const parts = (error.loc || []).filter((part) => part !== "body");
    const label = parts[0] === "recipients" && Number.isInteger(parts[1])
      ? `Recipient ${parts[1] + 1} ${parts[2] || ""}` : parts.join(" ").replaceAll("_", " ");
    return `${label}: ${error.msg || "Invalid value"}`;
  }).join("\n");
}

async function api(path, options = {}) {
  let response;
  try { response = await fetch(path, { cache: "no-store", ...options }); }
  catch { throw new Error("Unable to connect. Check that the application is running and try again."); }
  if (!response.ok) {
    let body;
    try { body = await response.json(); } catch { body = {}; }
    const error = new Error(response.status >= 500 ? "The server could not complete this request. Please try again." : errorDetail(body.detail));
    error.status = response.status;
    throw error;
  }
  return response;
}

async function submitJob(event) {
  event.preventDefault();
  if (state.submitting) return;
  if (state.importing) { showNotice("form-error", "Wait for the CSV import to finish before generating."); return; }
  showNotice("form-error", "");
  showNotice("import-notice", "");
  let payload;
  try { payload = validatedPayload(); }
  catch (error) { showNotice("form-error", error.message); return; }
  state.submitting = true;
  $("form-fields").disabled = true;
  $("generate-button").querySelector("span").textContent = "Creating your batch…";
  try {
    const response = await api("/api/v1/certificate-jobs", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload),
    });
    const job = await response.json();
    rememberJob({ id: job.job_id, title: payload.certificate_title, total: job.total_count, status: job.status, createdAt: new Date().toISOString() });
    openJob(job.job_id, payload.certificate_title);
  } catch (error) {
    showNotice("form-error", error.message);
  } finally {
    state.submitting = false;
    $("form-fields").disabled = false;
    $("generate-button").querySelector("span").textContent = "Generate certificates";
  }
}

// Robust RFC 4180 CSV parser supporting commas, CRLF/LF, escaped quotes, leading/trailing spaces outside quotes, and multiline values.
function parseCSV(text) {
  const rows = [];
  let row = [];
  let value = "";
  let quoted = false;
  let inCell = false;
  const source = text.replace(/^\uFEFF/, "");
  let i = 0;
  const len = source.length;

  const finishCell = () => {
    row.push(quoted ? value : value.trim());
    value = "";
    quoted = false;
    inCell = false;
  };

  const finishRow = () => {
    finishCell();
    if (row.some((cell) => cell.length > 0)) {
      rows.push(row);
    }
    row = [];
  };

  while (i < len) {
    const char = source[i];

    if (quoted) {
      if (char === '"') {
        if (i + 1 < len && source[i + 1] === '"') {
          value += '"';
          i++;
        } else {
          quoted = false;
        }
      } else {
        value += char;
      }
    } else {
      if (char === '"' && !inCell) {
        quoted = true;
        inCell = true;
      } else if (char === ",") {
        finishCell();
      } else if (char === "\r") {
        if (i + 1 < len && source[i + 1] === "\n") {
          i++;
        }
        finishRow();
      } else if (char === "\n") {
        finishRow();
      } else {
        if (!inCell && /\s/.test(char)) {
          // Ignore leading whitespace outside quotes
        } else {
          inCell = true;
          value += char;
        }
      }
    }
    i++;
  }
  if (quoted) {
    throw new Error("The CSV contains an unclosed quoted field. Please check the file and try again.");
  }
  finishRow();
  return rows;
}

async function importCSV(file) {
  if (!file || state.submitting || state.importing) return;
  state.importing = true;
  $("import-button").disabled = true;
  $("generate-button").disabled = true;
  showNotice("form-error", "");
  showNotice("import-notice", "");
  try {
    if (!/\.csv$/i.test(file.name)) throw new Error("Choose a CSV file with name and email columns.");
    if (file.size > 2 * 1024 * 1024) throw new Error("Choose a CSV file smaller than 2 MB.");
    const rows = parseCSV(await file.text());
    const headers = rows.shift()?.map((cell) => cell.trim().toLowerCase()) || [];
    const NAME_ALIASES = ["name", "full name", "fullname", "recipient name", "recipient_name", "student name", "student_name"];
    const EMAIL_ALIASES = ["email", "email address", "email_address", "recipient email", "recipient_email", "mail"];
    const nameColumn = headers.findIndex((h) => NAME_ALIASES.includes(h));
    const emailColumn = headers.findIndex((h) => EMAIL_ALIASES.includes(h));
    if (nameColumn < 0 || emailColumn < 0) throw new Error("The first CSV row must include name and email column headers. Download the sample to see the format.");
    if (!rows.length) throw new Error("This CSV has no recipients. Add at least one name and email.");
    const imported = rows.map((row, index) => {
      const name = row[nameColumn]?.trim() || "", email = row[emailColumn]?.trim() || "";
      if (!name || !email) throw new Error(`CSV row ${index + 2}: both name and email are required.`);
      if (name.length > 120 || email.length > 320) throw new Error(`CSV row ${index + 2}: a name or email is too long.`);
      return { name, email };
    });
    const existing = state.recipients.filter((person) => person.name.trim() || person.email.trim());
    if (existing.length + imported.length > MAX_RECIPIENTS) throw new Error("A batch can include up to 10,000 recipients. Split this list into smaller files.");
    state.recipients = [...existing, ...imported];
    state.editorPage = Math.floor(existing.length / EDITOR_PAGE_SIZE) + 1;
    renderRecipients();
    showNotice("import-notice", `Added ${imported.length.toLocaleString()} recipient${imported.length === 1 ? "" : "s"} from ${file.name}. Review the list before generating.`);
  } catch (error) { showNotice("form-error", error.message); }
  finally {
    state.importing = false;
    $("csv-file").value = "";
    $("import-button").disabled = false;
    $("generate-button").disabled = false;
  }
}

function saveBlob(blob, filename) {
  const url = URL.createObjectURL(blob);
  const link = element("a");
  link.href = url;
  link.download = filename;
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 60000);
}

function loadRecent() {
  try {
    const saved = JSON.parse(localStorage.getItem(HISTORY_KEY) || "[]");
    state.recent = Array.isArray(saved) ? saved.filter((job) => job && UUID_PATTERN.test(job.id)
      && typeof job.title === "string" && typeof job.createdAt === "string"
      && Number.isInteger(job.total) && job.total >= 0 && job.total <= MAX_RECIPIENTS
      && Object.hasOwn(STATUS_LABELS, job.status)).slice(0, 12) : [];
  } catch { state.recent = []; }
}

function rememberJob(job) {
  state.recent = [job, ...state.recent.filter((entry) => entry.id !== job.id)].slice(0, 12);
  try { localStorage.setItem(HISTORY_KEY, JSON.stringify(state.recent)); } catch { /* History is optional. */ }
  renderRecent();
}

function badge(status) {
  return element("span", `status-badge ${Object.hasOwn(STATUS_LABELS, status) ? status.toLowerCase() : "pending"}`, STATUS_LABELS[status] || "Queued");
}

function renderRecent() {
  const list = $("recent-jobs");
  list.replaceChildren();
  if (!state.recent.length) {
    const empty = element("div", "recent-empty"), copy = element("p", "", "Your next milestone starts here.");
    copy.append(element("small", "", "Batches you create in this browser will appear here."));
    empty.append(icon("file"), copy);
    list.append(empty);
    return;
  }
  for (const job of state.recent) {
    const button = element("button", "recent-job");
    button.type = "button";
    const picture = element("span", "recent-file");
    picture.append(icon("file"));
    const text = element("div");
    text.append(element("div", "recent-title", job.title));
    const date = new Date(job.createdAt);
    const dateLabel = Number.isNaN(date.getTime()) ? "" : date.toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
    text.append(element("div", "recent-meta", `${job.total.toLocaleString()} recipients · ${dateLabel}`));
    button.append(picture, text, badge(job.status));
    button.addEventListener("click", () => openJob(job.id, job.title));
    list.append(button);
  }
}

function openJob(id, title = "") {
  if (!UUID_PATTERN.test(id)) return;
  clearTimeout(state.pollTimer);
  state.activeJob = id;
  state.resultsPage = 1;
  $("builder-view").hidden = true;
  $("results-view").hidden = false;
  $("download-zip").hidden = true;
  $("results-title").textContent = title;
  $("results-heading").textContent = "Preparing your certificates.";
  $("job-id").textContent = id;
  $("job-status").textContent = "Loading";
  $("job-status").className = "status-badge";
  $("job-message").textContent = "Loading your batch…";
  for (const stat of ["total", "completed", "successful", "failed"]) $(`stat-${stat}`).textContent = "—";
  $("progress-fill").style.width = "0%";
  $("progress-track").setAttribute("aria-valuenow", "0");
  $("progress-percentage").textContent = "0%";
  $("progress-label").textContent = "Waiting for progress";
  $("certificate-results").replaceChildren();
  $("results-count").textContent = "";
  $("result-range").textContent = "Loading…";
  $("results-prev").disabled = true;
  $("results-next").disabled = true;
  showNotice("tracking-error", "");
  window.scrollTo({ top: 0 });
  $("results-heading").focus({ preventScroll: true });
  refreshJob();
}

function renderProgress(job) {
  const terminal = ["COMPLETED", "COMPLETED_WITH_ERRORS", "FAILED"].includes(job.status);
  $("job-status").textContent = STATUS_LABELS[job.status] || job.status;
  $("job-status").className = `status-badge ${job.status.toLowerCase()}`;
  $("results-heading").textContent = job.status === "COMPLETED" ? "Ready for their moment." : job.status === "COMPLETED_WITH_ERRORS" ? "Your batch is complete." : job.status === "FAILED" ? "This batch needs attention." : "Creating something worth keeping.";
  const messages = {
    PENDING: "Your batch is queued. Certificate generation will begin shortly.",
    PROCESSING: "Your certificates are being created. You can download each one as soon as it’s ready.",
    COMPLETED: "All certificates have been generated. Download the PDFs below and share the achievement.",
    COMPLETED_WITH_ERRORS: "Processing is finished. Successful certificates are ready below; check the failed rows for details.",
    FAILED: "Processing stopped before the batch could finish. Any completed PDFs are still available below.",
  };
  $("job-message").textContent = messages[job.status] || "Loading your batch…";
  for (const stat of ["total", "completed", "successful", "failed"]) $(`stat-${stat}`).textContent = job[`${stat}_count`].toLocaleString();
  const percent = Math.max(0, Math.min(100, job.progress_percentage));
  $("progress-fill").style.width = `${percent}%`;
  $("progress-track").setAttribute("aria-valuenow", String(percent));
  $("progress-percentage").textContent = `${percent}%`;
  $("progress-label").textContent = `${job.completed_count.toLocaleString()} of ${job.total_count.toLocaleString()} recipients processed${terminal ? "" : " · Updates automatically"}`;
  $("download-zip").hidden = job.successful_count === 0;
}

function renderCertificates(result) {
  const fragment = document.createDocumentFragment();
  for (const certificate of result.certificates) {
    const row = element("tr"), recipient = element("td"), number = element("td"), status = element("td"), action = element("td");
    recipient.append(element("span", "recipient-name", certificate.recipient_name), element("span", "recipient-email", certificate.recipient_email));
    number.append(element("span", "certificate-number", certificate.certificate_number));
    status.append(badge(certificate.status));
    if (certificate.error_message) status.append(element("p", "row-error", certificate.error_message));
    if (certificate.status === "COMPLETED") {
      const download = element("button", "button button-secondary download-button");
      download.type = "button";
      download.dataset.certificateId = certificate.certificate_id;
      download.disabled = state.downloads.has(certificate.certificate_id);
      download.append(icon("download"), document.createTextNode("PDF"));
      download.setAttribute("aria-label", `Download certificate for ${certificate.recipient_name}`);
      download.addEventListener("click", () => downloadCertificate(certificate, download));
      action.append(download);
    } else action.append(element("span", "field-hint", certificate.status === "FAILED" ? "Unavailable" : "Not ready yet"));
    row.append(recipient, number, status, action);
    fragment.append(row);
  }
  if (!result.certificates.length) {
    const row = element("tr"), cell = element("td", "empty-results", "No certificates on this page.");
    cell.colSpan = 4;
    row.append(cell);
    fragment.append(row);
  }
  $("certificate-results").replaceChildren(fragment);
  $("results-count").textContent = `${result.total_count.toLocaleString()} certificates`;
  const start = (result.page - 1) * result.page_size + 1;
  $("result-range").textContent = result.total_count ? `${start.toLocaleString()}–${Math.min(start + result.certificates.length - 1, result.total_count).toLocaleString()} of ${result.total_count.toLocaleString()}` : "No results";
  $("results-prev").disabled = result.page <= 1;
  $("results-next").disabled = result.page * result.page_size >= result.total_count;
}

async function refreshJob() {
  if (!state.activeJob) return;
  clearTimeout(state.pollTimer);
  const id = state.activeJob, version = ++state.requestVersion, page = state.resultsPage;
  $("results-prev").disabled = true;
  $("results-next").disabled = true;
  try {
    const [jobResponse, listResponse] = await Promise.all([
      api(`/api/v1/certificate-jobs/${id}`),
      api(`/api/v1/certificate-jobs/${id}/certificates?page=${page}&page_size=${RESULTS_PAGE_SIZE}`),
    ]);
    const [job, result] = await Promise.all([jobResponse.json(), listResponse.json()]);
    if (version !== state.requestVersion || state.activeJob !== id) return;
    showNotice("tracking-error", "");
    renderProgress(job);
    renderCertificates(result);
    const title = result.certificates[0]?.certificate_title || $("results-title").textContent || "Certificate batch";
    $("results-title").textContent = title;
    rememberJob({ id, title, total: job.total_count, status: job.status, createdAt: job.created_at });
    if (["PENDING", "PROCESSING"].includes(job.status)) state.pollTimer = setTimeout(refreshJob, 1500);
  } catch (error) {
    if (version !== state.requestVersion || state.activeJob !== id) return;
    const missing = error.status === 404;
    showNotice("tracking-error", missing ? "This job could not be found. Check the job ID or create a new batch." : `${error.message} Retrying in 5 seconds.`);
    if (missing) {
      $("results-heading").textContent = "Batch not found.";
      $("job-message").textContent = "The job ID does not match a saved batch on this server.";
      $("job-status").textContent = "Not found";
      $("result-range").textContent = "No results";
      $("download-zip").hidden = true;
    } else state.pollTimer = setTimeout(refreshJob, 5000);
  }
}

async function downloadCertificate(certificate, button) {
  if (state.downloads.has(certificate.certificate_id)) return;
  state.downloads.add(certificate.certificate_id);
  if (button) button.disabled = true;
  try {
    const response = await api(`/api/v1/certificates/${certificate.certificate_id}`);
    saveBlob(await response.blob(), `${certificate.certificate_number}.pdf`);
    notify(`Downloaded certificate for ${certificate.recipient_name}.`);
  } catch (error) { notify(error.message); }
  finally {
    state.downloads.delete(certificate.certificate_id);
    const activeBtn = document.querySelector(`button[data-certificate-id="${certificate.certificate_id}"]`);
    if (activeBtn) activeBtn.disabled = false;
    else if (button) button.disabled = false;
  }
}

async function downloadBatchZip() {
  if (!state.activeJob || state.downloadingZip) return;
  state.downloadingZip = true;
  const btn = $("download-zip");
  btn.disabled = true;
  const originalHtml = btn.innerHTML;
  btn.textContent = "Packaging ZIP…";
  try {
    const response = await api(`/api/v1/certificate-jobs/${state.activeJob}/zip`);
    saveBlob(await response.blob(), `certificates-${state.activeJob.slice(0, 8)}.zip`);
    notify("Downloaded all certificates as ZIP archive.");
  } catch (error) {
    notify(error.message);
  } finally {
    state.downloadingZip = false;
    btn.disabled = false;
    btn.innerHTML = originalHtml;
  }
}

function newBatch() {
  clearTimeout(state.pollTimer);
  state.requestVersion++;
  state.activeJob = null;
  state.recipients = [{ name: "", email: "" }];
  state.editorPage = 1;
  $("certificate-form").reset();
  $("certificate-date").value = today();
  for (const input of document.querySelectorAll('[aria-invalid="true"]')) input.removeAttribute("aria-invalid");
  showNotice("form-error", "");
  showNotice("import-notice", "");
  $("download-zip").hidden = true;
  $("results-view").hidden = true;
  $("builder-view").hidden = false;
  removeAnySignature();
  renderRecipients();
  window.scrollTo({ top: 0 });
  $("certificate-title").focus({ preventScroll: true });
}

$("certificate-date").value = today();
$("certificate-form").addEventListener("submit", submitJob);
$("certificate-form").addEventListener("input", (event) => {
  event.target.removeAttribute("aria-invalid");
  const { index, field } = event.target.dataset;
  if (index !== undefined && ["name", "email"].includes(field)) state.recipients[Number(index)][field] = event.target.value;
  updatePreview();
});
$("recipient-rows").addEventListener("click", (event) => {
  const button = event.target.closest("button[data-remove]");
  if (!button) return;
  state.recipients.splice(Number(button.dataset.remove), 1);
  if (!state.recipients.length) state.recipients.push({ name: "", email: "" });
  renderRecipients();
});
$("add-recipient").addEventListener("click", () => {
  if (state.recipients.length >= MAX_RECIPIENTS) return;
  state.recipients.push({ name: "", email: "" });
  state.editorPage = Math.ceil(state.recipients.length / EDITOR_PAGE_SIZE);
  renderRecipients();
  $(`recipient-${state.recipients.length - 1}-name`).focus();
});
$("editor-prev").addEventListener("click", () => { state.editorPage--; renderRecipients(); });
$("editor-next").addEventListener("click", () => { state.editorPage++; renderRecipients(); });
$("import-button").addEventListener("click", () => $("csv-file").click());
$("csv-file").addEventListener("change", (event) => importCSV(event.target.files[0]));
$("sample-csv").addEventListener("click", () => saveBlob(new Blob(["name,email\r\nRahul Sharma,rahul@example.com\r\nPriya Kumar,priya@example.com\r\n"], { type: "text/csv;charset=utf-8" }), "recipients-sample.csv"));
$("drop-zone").addEventListener("dragover", (event) => { event.preventDefault(); if (!state.submitting) $("drop-zone").classList.add("dragging"); });
$("drop-zone").addEventListener("dragleave", () => $("drop-zone").classList.remove("dragging"));
$("drop-zone").addEventListener("drop", (event) => {
  event.preventDefault();
  $("drop-zone").classList.remove("dragging");
  if (event.dataTransfer.files.length !== 1) showNotice("form-error", "Import one CSV file at a time.");
  else importCSV(event.dataTransfer.files[0]);
});
$("lookup-form").addEventListener("submit", (event) => {
  event.preventDefault();
  const id = $("lookup-id").value.trim();
  showNotice("lookup-error", UUID_PATTERN.test(id) ? "" : "Enter the full job ID, including its hyphens.");
  if (UUID_PATTERN.test(id)) openJob(id);
});
$("new-batch").addEventListener("click", newBatch);
$("download-zip").addEventListener("click", downloadBatchZip);
$("refresh-job").addEventListener("click", refreshJob);
$("results-prev").addEventListener("click", () => { state.resultsPage = Math.max(1, state.resultsPage - 1); refreshJob(); });
$("results-next").addEventListener("click", () => { state.resultsPage++; refreshJob(); });
$("copy-job").addEventListener("click", async () => {
  try { await navigator.clipboard.writeText(state.activeJob); notify("Job ID copied."); }
  catch { notify("Copy the job ID shown in the progress card."); }
});
loadRecent();
renderRecipients();
renderRecent();

// --- Interactive Signature Manager ---
const sigCanvas = $("signature-canvas");
const sigWrapper = $("canvas-wrapper");
const sigCtx = sigCanvas ? sigCanvas.getContext("2d") : null;
let isDrawing = false;
let lastX = 0;
let lastY = 0;

function setupCanvas() {
  if (!sigCanvas || !sigCtx) return;
  const rect = sigCanvas.getBoundingClientRect();
  const dpr = window.devicePixelRatio || 1;
  const width = rect.width || 480;
  const height = 130;

  sigCanvas.width = width * dpr;
  sigCanvas.height = height * dpr;
  sigCtx.scale(dpr, dpr);
  sigCtx.lineCap = "round";
  sigCtx.lineJoin = "round";
  sigCtx.lineWidth = 2.4;
  sigCtx.strokeStyle = "#1c344b";
}

function clearDrawing() {
  if (!sigCanvas || !sigCtx) return;
  const dpr = window.devicePixelRatio || 1;
  sigCtx.clearRect(0, 0, sigCanvas.width / dpr, sigCanvas.height / dpr);
  sigWrapper.classList.remove("has-content");
  state.hasDrawn = false;
  if (state.signatureMode === "draw") {
    state.signatureImage = null;
    updatePreview();
  }
}

function getPointerPos(event) {
  const rect = sigCanvas.getBoundingClientRect();
  return {
    x: event.clientX - rect.left,
    y: event.clientY - rect.top,
  };
}

function startDrawing(event) {
  event.preventDefault();
  isDrawing = true;
  try { sigCanvas.setPointerCapture(event.pointerId); } catch (_) {}
  sigWrapper.classList.add("is-drawing", "has-content");
  const pos = getPointerPos(event);
  lastX = pos.x;
  lastY = pos.y;

  sigCtx.beginPath();
  sigCtx.arc(lastX, lastY, 1.2, 0, Math.PI * 2);
  sigCtx.fillStyle = "#1c344b";
  sigCtx.fill();
}

function drawMove(event) {
  if (!isDrawing) return;
  event.preventDefault();
  const pos = getPointerPos(event);

  sigCtx.beginPath();
  sigCtx.moveTo(lastX, lastY);
  sigCtx.lineTo(pos.x, pos.y);
  sigCtx.stroke();

  lastX = pos.x;
  lastY = pos.y;
  state.hasDrawn = true;
}

function stopDrawing(event) {
  if (!isDrawing) return;
  isDrawing = false;
  try { sigCanvas.releasePointerCapture(event.pointerId); } catch (_) {}
  sigWrapper.classList.remove("is-drawing");

  if (state.hasDrawn) {
    state.signatureMode = "draw";
    state.signatureImage = sigCanvas.toDataURL("image/png");
    updatePreview();
  }
}

function setSignatureMode(mode) {
  state.signatureMode = mode;
  const isDraw = mode === "draw";
  $("tab-draw").classList.toggle("is-active", isDraw);
  $("tab-draw").setAttribute("aria-selected", isDraw ? "true" : "false");
  $("tab-upload").classList.toggle("is-active", !isDraw);
  $("tab-upload").setAttribute("aria-selected", isDraw ? "false" : "true");
  $("panel-draw").hidden = !isDraw;
  $("panel-upload").hidden = isDraw;

  if (isDraw && sigCanvas.width === 0) {
    setupCanvas();
  }

  if (isDraw && state.hasDrawn) {
    state.signatureImage = sigCanvas.toDataURL("image/png");
  } else if (!isDraw && state.uploadedSignature) {
    state.signatureImage = state.uploadedSignature;
  }
  updatePreview();
}

function handleSignatureUpload(file) {
  if (!file) return;
  if (!file.type.startsWith("image/")) {
    notify("Please choose an image file (PNG, JPG, SVG, WebP).");
    return;
  }
  if (file.size > 4 * 1024 * 1024) {
    notify("Image must be smaller than 4MB.");
    return;
  }
  const reader = new FileReader();
  reader.onload = () => {
    state.uploadedSignature = reader.result;
    state.signatureMode = "upload";
    state.signatureImage = reader.result;
    $("sig-upload-thumb").src = reader.result;
    $("sig-upload-name").textContent = file.name;
    $("sig-upload-preview").hidden = false;
    $("sig-drop-zone").hidden = true;
    updatePreview();
    notify("Signature image attached.");
  };
  reader.readAsDataURL(file);
}

function removeUploadedSignature() {
  state.uploadedSignature = null;
  $("sig-file").value = "";
  $("sig-upload-thumb").removeAttribute("src");
  $("sig-upload-preview").hidden = true;
  $("sig-drop-zone").hidden = false;
  if (state.signatureMode === "upload") {
    state.signatureImage = null;
    updatePreview();
  }
}

function removeAnySignature() {
  clearDrawing();
  removeUploadedSignature();
  state.signatureImage = null;
  updatePreview();
}

$("tab-draw").addEventListener("click", () => setSignatureMode("draw"));
$("tab-upload").addEventListener("click", () => setSignatureMode("upload"));
$("reset-canvas").addEventListener("click", clearDrawing);
$("clear-signature").addEventListener("click", () => {
  removeAnySignature();
  notify("Signature removed.");
});
$("sig-upload-btn").addEventListener("click", () => $("sig-file").click());
$("sig-file").addEventListener("change", (e) => handleSignatureUpload(e.target.files[0]));
$("sig-remove-upload").addEventListener("click", removeUploadedSignature);

if (sigCanvas) {
  sigCanvas.addEventListener("pointerdown", startDrawing);
  sigCanvas.addEventListener("pointermove", drawMove);
  sigCanvas.addEventListener("pointerup", stopDrawing);
  sigCanvas.addEventListener("pointercancel", stopDrawing);
  setupCanvas();
}

const sigDropZone = $("sig-drop-zone");
if (sigDropZone) {
  sigDropZone.addEventListener("dragover", (e) => {
    e.preventDefault();
    sigDropZone.classList.add("dragging");
  });
  sigDropZone.addEventListener("dragleave", () => sigDropZone.classList.remove("dragging"));
  sigDropZone.addEventListener("drop", (e) => {
    e.preventDefault();
    sigDropZone.classList.remove("dragging");
    if (e.dataTransfer.files.length) handleSignatureUpload(e.dataTransfer.files[0]);
  });
}

window.addEventListener("resize", () => {
  const temp = state.hasDrawn && sigCanvas ? sigCanvas.toDataURL("image/png") : null;
  setupCanvas();
  if (temp && sigCanvas && sigCtx) {
    const img = new Image();
    img.onload = () => {
      const dpr = window.devicePixelRatio || 1;
      sigCtx.drawImage(img, 0, 0, sigCanvas.width / dpr, sigCanvas.height / dpr);
    };
    img.src = temp;
  }
});
