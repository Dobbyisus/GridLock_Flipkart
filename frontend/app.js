const CORRECTION_HISTORY_KEY = "gridlock-weekly-corrections-v1";
const CORRECTION_SESSION_KEY = "gridlock-weekly-corrections-session-v1";
const MIN_CORRECTION_PANEL_MS = 1200;
const PANEL_WIDTH_KEY = "gridlock-operations-panel-width-v1";
const PANEL_WIDTH_DEFAULT = 340;
const PANEL_WIDTH_MIN = 320;
const PANEL_WIDTH_MAX = 520;
const LIVE_STATUS_POLL_MS = 60000;

function delay(ms) {
  return new Promise((resolve) => {
    setTimeout(resolve, ms);
  });
}

function roundValue(value, digits = 2) {
  const factor = 10 ** digits;
  return Math.round(Number(value) * factor) / factor;
}

function loadCorrectionHistory() {
  try {
    const raw = localStorage.getItem(CORRECTION_HISTORY_KEY);
    const parsed = raw ? JSON.parse(raw) : [];
    return Array.isArray(parsed) ? parsed : [];
  } catch (error) {
    return [];
  }
}

function loadStoredCorrectionSessionId() {
  return localStorage.getItem(CORRECTION_SESSION_KEY) || null;
}

function persistCorrectionSessionId(sessionId) {
  if (sessionId) {
    localStorage.setItem(CORRECTION_SESSION_KEY, sessionId);
  }
}

function clearCorrectionHistoryStore() {
  state.correctionHistory = [];
  state.activeCorrectionKey = null;
  localStorage.removeItem(CORRECTION_HISTORY_KEY);
}

function isLiveMode() {
  return state.mode === "live";
}

function dashboardBasePath() {
  return isLiveMode() ? "/dashboard/live" : "/dashboard";
}

function selectedOperationalDate() {
  if (!state.selectedDate) {
    return null;
  }
  return isLiveMode() ? String(state.selectedDate).slice(0, 10) : state.selectedDate;
}

const state = {
  mode: "historical",
  engineCatalog: null,
  windowIndex: 0,
  totalWindows: 0,
  selectedDate: null,
  selectedEvent: null,
  viewedDates: new Set(),
  calendarDates: [],
  calendarWindows: [],
  currentWindow: null,
  dayData: null,
  reviewUnlocked: false,
  routeData: null,
  correctionHistory: loadCorrectionHistory(),
  correctionRunning: false,
  activeCorrectionKey: null,
  selectedRouteId: null,
  activeRouteAnimation: null,
  sessionId: null,
  sessionStartedAt: null,
  liveStatus: null,
  liveRefreshSeenAt: null,
  livePollingHandle: null,
};

const map = L.map("map", {
  zoomControl: false,
  preferCanvas: true,
}).setView([12.9716, 77.5946], 11);

L.control.zoom({ position: "bottomright" }).addTo(map);
L.tileLayer("https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png", {
  attribution: "&copy; OpenStreetMap &copy; CARTO",
  maxZoom: 19,
}).addTo(map);

const hotspotLayer = L.layerGroup().addTo(map);
const policeLayer = L.layerGroup().addTo(map);
const routeLayer = L.layerGroup().addTo(map);
const routeEndpointLayer = L.layerGroup().addTo(map);

const elements = {
  appShell: document.querySelector(".app-shell"),
  dashboardLayout: document.querySelector(".dashboard-layout"),
  intelPanel: document.querySelector(".intel-panel"),
  goLiveButton: document.getElementById("goLiveButton"),
  liveStatusPill: document.getElementById("liveStatusPill"),
  bannerTitle: document.getElementById("bannerTitle"),
  bannerText: document.getElementById("bannerText"),
  selectedDateLabel: document.getElementById("selectedDateLabel"),
  summaryEventCount: document.getElementById("summaryEventCount"),
  summaryCriticalCount: document.getElementById("summaryCriticalCount"),
  summaryAverageImpact: document.getElementById("summaryAverageImpact"),
  priorityHotspotTitle: document.getElementById("priorityHotspotTitle"),
  priorityHotspotMeta: document.getElementById("priorityHotspotMeta"),
  priorityImpactValue: document.getElementById("priorityImpactValue"),
  priorityRiskValue: document.getElementById("priorityRiskValue"),
  priorityOfficerValue: document.getElementById("priorityOfficerValue"),
  priorityBarricadeValue: document.getElementById("priorityBarricadeValue"),
  eventFeed: document.getElementById("eventFeed"),
  routeResults: document.getElementById("routeResults"),
  routeOriginStation: document.getElementById("routeOriginStation"),
  routeDestinationEvent: document.getElementById("routeDestinationEvent"),
  routeModeLabel: document.getElementById("routeModeLabel"),
  routeSubmitButton: document.getElementById("routeSubmitButton"),
  addEventButton: document.getElementById("addEventButton"),
  timelineBar: document.getElementById("timelineBar"),
  windowLabel: document.getElementById("windowLabel"),
  reviewFeed: document.getElementById("reviewFeed"),
  reviewGateText: document.getElementById("reviewGateText"),
  reviewTabButton: document.getElementById("reviewTabButton"),
  weekSelect: document.getElementById("weekSelect"),
  dockTitle: document.getElementById("dockTitle"),
  dockMeta: document.getElementById("dockMeta"),
  dockStation: document.getElementById("dockStation"),
  dockCorridor: document.getElementById("dockCorridor"),
  dockMarshals: document.getElementById("dockMarshals"),
  dockDiversion: document.getElementById("dockDiversion"),
  dockDiversions: document.getElementById("dockDiversions"),
  toast: document.getElementById("toast"),
  manualEventOverlay: document.getElementById("manualEventOverlay"),
  manualEventForm: document.getElementById("manualEventForm"),
  manualEventCloseButton: document.getElementById("manualEventCloseButton"),
  manualEventCancelButton: document.getElementById("manualEventCancelButton"),
  manualEventSubmitButton: document.getElementById("manualEventSubmitButton"),
  manualEventPickHint: document.getElementById("manualEventPickHint"),
  manualEventDateLabel: document.getElementById("manualEventDateLabel"),
  manualEventTime: document.getElementById("manualEventTime"),
  manualEventTitle: document.getElementById("manualEventTitle"),
  manualEventAddress: document.getElementById("manualEventAddress"),
  manualEventLocationHints: document.getElementById("manualEventLocationHints"),
  manualEventCause: document.getElementById("manualEventCause"),
  manualEventPriority: document.getElementById("manualEventPriority"),
  manualEventAttendance: document.getElementById("manualEventAttendance"),
  manualEventClosure: document.getElementById("manualEventClosure"),
  forceRetrainButton: document.getElementById("forceRetrainButton"),
  correctionArchive: document.getElementById("correctionArchive"),
  correctionOverlay: document.getElementById("correctionOverlay"),
  correctionPanelTitle: document.getElementById("correctionPanelTitle"),
  correctionPanelText: document.getElementById("correctionPanelText"),
  correctionProgress: document.getElementById("correctionProgress"),
  correctionPanelBody: document.getElementById("correctionPanelBody"),
  correctionCollapseButton: document.getElementById("correctionCollapseButton"),
  correctionCollapseAction: document.getElementById("correctionCollapseAction"),
  panelResizerShell: document.querySelector(".panel-resizer-shell"),
  panelResizerHandle: document.getElementById("panelResizerHandle"),
  panelResizerToggle: document.getElementById("panelResizerToggle"),
};

function clampPanelWidth(width) {
  return Math.min(PANEL_WIDTH_MAX, Math.max(PANEL_WIDTH_MIN, width));
}

function applyPanelWidth(width, persist = true) {
  const nextWidth = clampPanelWidth(width);
  document.documentElement.style.setProperty("--intel-panel-width", `${nextWidth}px`);
  if (persist) {
    localStorage.setItem(PANEL_WIDTH_KEY, String(nextWidth));
  }
  if (elements.panelResizerToggle) {
    const expanded = nextWidth >= 420;
    elements.panelResizerToggle.textContent = expanded ? "⇤" : "⇥";
    elements.panelResizerToggle.title = expanded
      ? "Shrink operations panel"
      : "Expand operations panel";
    elements.panelResizerToggle.setAttribute(
      "aria-label",
      expanded ? "Shrink operations panel" : "Expand operations panel",
    );
  }
}

function loadPanelWidthPreference() {
  const raw = Number(localStorage.getItem(PANEL_WIDTH_KEY));
  if (Number.isFinite(raw) && raw > 0) {
    applyPanelWidth(raw, false);
    return;
  }
  applyPanelWidth(PANEL_WIDTH_DEFAULT, false);
}

function setupPanelResize() {
  loadPanelWidthPreference();
  if (!elements.panelResizerHandle || !elements.panelResizerShell || !elements.panelResizerToggle) {
    return;
  }

  let dragStartX = 0;
  let dragStartWidth = PANEL_WIDTH_DEFAULT;

  const stopDragging = () => {
    elements.panelResizerShell.classList.remove("is-dragging");
    window.removeEventListener("pointermove", handlePointerMove);
    window.removeEventListener("pointerup", stopDragging);
  };

  const handlePointerMove = (pointerEvent) => {
    const delta = pointerEvent.clientX - dragStartX;
    applyPanelWidth(dragStartWidth + delta);
  };

  elements.panelResizerHandle.addEventListener("pointerdown", (pointerEvent) => {
    if (window.innerWidth <= 1180) {
      return;
    }
    dragStartX = pointerEvent.clientX;
    dragStartWidth = elements.intelPanel.getBoundingClientRect().width;
    elements.panelResizerShell.classList.add("is-dragging");
    window.addEventListener("pointermove", handlePointerMove);
    window.addEventListener("pointerup", stopDragging);
  });

  elements.panelResizerToggle.addEventListener("click", () => {
    const currentWidth = elements.intelPanel.getBoundingClientRect().width;
    applyPanelWidth(currentWidth >= 420 ? PANEL_WIDTH_DEFAULT : 440);
  });

  window.addEventListener("resize", () => {
    if (window.innerWidth <= 1180) {
      stopDragging();
    }
  });
}

function showToast(message) {
  elements.toast.textContent = message;
  elements.toast.classList.add("visible");
  clearTimeout(showToast.timer);
  showToast.timer = setTimeout(() => {
    elements.toast.classList.remove("visible");
  }, 2200);
}

function formatDate(dateText) {
  const normalized = String(dateText || "");
  const source = normalized.includes("T") ? normalized : `${normalized}T00:00:00`;
  return new Date(source).toLocaleDateString("en-IN", {
    weekday: "short",
    day: "numeric",
    month: "short",
  });
}

function formatShortDate(dateText) {
  return new Date(`${dateText}T00:00:00`).toLocaleDateString("en-IN", {
    day: "numeric",
    month: "short",
  });
}

function formatDateTime(dateText) {
  if (!dateText) {
    return "--";
  }
  const date = new Date(dateText);
  if (Number.isNaN(date.getTime())) {
    return "--";
  }
  return date.toLocaleString("en-IN", {
    day: "numeric",
    month: "short",
    hour: "numeric",
    minute: "2-digit",
  });
}

function timelineParts(dateText) {
  const source = String(dateText || "");
  const date = new Date(source.includes("T") ? source : `${source}T00:00:00`);
  return {
    month: date.toLocaleDateString("en-IN", { month: "short" }).toUpperCase(),
    day: date.toLocaleDateString("en-IN", { day: "2-digit" }),
  };
}

function formatWeekRange(startDateText, endDateText) {
  const startDate = new Date(`${startDateText}T00:00:00`);
  const endDate = new Date(`${endDateText}T00:00:00`);
  const sameMonth = startDate.getMonth() === endDate.getMonth()
    && startDate.getFullYear() === endDate.getFullYear();
  if (sameMonth) {
    return `${startDate.toLocaleDateString("en-IN", { month: "long" })} ${startDate.getDate()}-${endDate.getDate()}, ${startDate.getFullYear()}`;
  }
  return `${startDate.toLocaleDateString("en-IN", { day: "numeric", month: "short" })} - ${endDate.toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" })}`;
}

function weekKey(windowInfo) {
  if (!windowInfo) {
    return "";
  }
  return `${windowInfo.startDate}__${windowInfo.endDate}`;
}

function prettifyLabel(text) {
  return String(text || "")
    .replace(/_/g, " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function formatSigned(value, digits = 2) {
  const amount = roundValue(value || 0, digits).toFixed(digits);
  if (Number(amount) > 0) {
    return `+${amount}`;
  }
  return amount;
}

function persistCorrectionHistory() {
  try {
    localStorage.setItem(CORRECTION_HISTORY_KEY, JSON.stringify(state.correctionHistory));
    if (state.sessionId) {
      persistCorrectionSessionId(state.sessionId);
    }
  } catch (error) {
    showToast("Correction summary could not be stored locally.");
  }
}

function getCurrentWindowInfo() {
  return state.currentWindow;
}

function getStoredCorrection(windowInfo = getCurrentWindowInfo()) {
  const key = weekKey(windowInfo);
  return state.correctionHistory.find((record) => record.weekKey === key) || null;
}

function summarizeWeightChanges(beforeState, afterState) {
  const previousWeights = beforeState?.weights || {};
  const nextWeights = afterState?.weights || {};
  return Object.keys(nextWeights)
    .map((key) => {
      const beforeValue = Number(previousWeights[key] || 0);
      const afterValue = Number(nextWeights[key] || 0);
      return {
        label: prettifyLabel(key),
        delta: roundValue(afterValue - beforeValue, 4),
      };
    })
    .filter((item) => Math.abs(item.delta) >= 0.0001)
    .sort((left, right) => Math.abs(right.delta) - Math.abs(left.delta))
    .slice(0, 3);
}

function summarizeCauseChanges(beforeState, afterState) {
  const previousAdjustments = beforeState?.cause_adjustments || {};
  const nextAdjustments = afterState?.cause_adjustments || {};
  return Object.keys(nextAdjustments)
    .map((key) => {
      const beforeValue = Number(previousAdjustments[key] || 0);
      const afterValue = Number(nextAdjustments[key] || 0);
      return {
        label: prettifyLabel(key),
        delta: roundValue(afterValue - beforeValue, 3),
      };
    })
    .filter((item) => Math.abs(item.delta) >= 0.01)
    .sort((left, right) => Math.abs(right.delta) - Math.abs(left.delta))
    .slice(0, 3);
}

function buildCorrectionRecord(windowInfo, beforeState, result) {
  const nextState = result?.state || beforeState || {};
  const trainingSummary = nextState.last_training_summary || {};
  const samplesUsed = Number(trainingSummary.samples_used || 0);
  const feedbackRecords = Number(nextState.feedback_records ?? beforeState?.feedback_records ?? 0);
  const retrained = Boolean(result?.retrained);
  const headline = retrained
    ? `${samplesUsed || feedbackRecords} reviewed events tuned the model for ${windowInfo.label}.`
    : (result?.message || "Weekly correction was reviewed without any model updates.");

  return {
    weekKey: weekKey(windowInfo),
    windowIndex: windowInfo.windowIndex,
    windowLabel: windowInfo.label,
    startDate: windowInfo.startDate,
    endDate: windowInfo.endDate,
    ranAt: new Date().toISOString(),
    retrained,
    headline,
    message: result?.message || "",
    nextDueAt: result?.next_due_at || null,
    feedbackRecords,
    samplesUsed,
    meanError: retrained ? Number(trainingSummary.mean_error || 0) : null,
    meanAbsoluteError: retrained ? Number(trainingSummary.mean_absolute_error || 0) : null,
    biasShift: retrained ? Number(trainingSummary.bias_shift || 0) : null,
    biasAfter: Number(nextState.bias ?? beforeState?.bias ?? 0),
    lastRetrainedAt: nextState.last_retrained_at || beforeState?.last_retrained_at || null,
    weightChanges: retrained && beforeState ? summarizeWeightChanges(beforeState, nextState) : [],
    causeChanges: retrained && beforeState ? summarizeCauseChanges(beforeState, nextState) : [],
  };
}

function upsertCorrectionRecord(record) {
  const nextHistory = state.correctionHistory.filter((item) => item.weekKey !== record.weekKey);
  nextHistory.unshift(record);
  nextHistory.sort((left, right) => {
    if (left.windowIndex === right.windowIndex) {
      return new Date(right.ranAt).getTime() - new Date(left.ranAt).getTime();
    }
    return left.windowIndex - right.windowIndex;
  });
  state.correctionHistory = nextHistory;
  persistCorrectionHistory();
  renderCorrectionArchive();
}

function renderCorrectionArchive() {
  if (!state.correctionHistory.length) {
    elements.correctionArchive.innerHTML = "<div class=\"correction-archive-empty\">Weekly correction summaries will stay here once you run them. Each week gets its own info icon for quick recall.</div>";
    return;
  }

  elements.correctionArchive.innerHTML = state.correctionHistory
    .map((record) => {
      const isActive = record.weekKey === state.activeCorrectionKey;
      const statusLabel = record.retrained ? "Corrected" : "Checked";
      return `
        <button
          class="correction-history-item ${isActive ? "active" : ""}"
          data-week-key="${record.weekKey}"
          type="button"
          aria-label="Open ${record.windowLabel} correction summary"
          title="${record.windowLabel} - ${statusLabel}"
        >
          <span class="correction-history-icon">i</span>
          <span class="correction-history-label">${record.windowLabel}</span>
        </button>
      `;
    })
    .join("");

  elements.correctionArchive.querySelectorAll(".correction-history-item").forEach((button) => {
    button.addEventListener("click", () => {
      const record = state.correctionHistory.find((item) => item.weekKey === button.dataset.weekKey);
      if (!record) {
        return;
      }
      state.activeCorrectionKey = record.weekKey;
      renderCorrectionArchive();
      renderCorrectionSummary(record);
      openCorrectionPanel();
    });
  });
}

function openCorrectionPanel() {
  elements.correctionOverlay.hidden = false;
}

function closeCorrectionPanel() {
  elements.correctionOverlay.hidden = true;
}

function setCorrectionCollapseEnabled(enabled) {
  elements.correctionCollapseButton.disabled = !enabled;
  elements.correctionCollapseAction.disabled = !enabled;
}

function renderCorrectionLoading(windowInfo) {
  state.activeCorrectionKey = weekKey(windowInfo);
  renderCorrectionArchive();
  elements.correctionPanelTitle.textContent = `Running correction for ${windowInfo.label}`;
  elements.correctionPanelText.textContent = "Reviewing the logged outcomes, keeping the progress rail live, and preparing the weekly correction summary.";
  elements.correctionProgress.hidden = false;
  elements.correctionPanelBody.innerHTML = `
    <div class="correction-loading-stack" aria-hidden="true">
      <div class="correction-loading-line"></div>
      <div class="correction-loading-line"></div>
      <div class="correction-loading-line"></div>
    </div>
  `;
  setCorrectionCollapseEnabled(false);
  openCorrectionPanel();
}

function createCorrectionMetric(label, value) {
  return `
    <div class="correction-metric">
      <span>${label}</span>
      <strong>${value}</strong>
    </div>
  `;
}

function createCorrectionRows(rows, emptyText) {
  if (!rows.length) {
    return `<div class="correction-summary-row"><span>${emptyText}</span><strong>Stable</strong></div>`;
  }
  return rows
    .map((row) => {
      const deltaClass = row.delta >= 0 ? "correction-delta-positive" : "correction-delta-negative";
      return `
        <div class="correction-summary-row">
          <span>${row.label}</span>
          <strong class="${deltaClass}">${formatSigned(row.delta, Math.abs(row.delta) >= 1 ? 2 : 3)}</strong>
        </div>
      `;
    })
    .join("");
}

function renderCorrectionSummary(record) {
  const ranAtLabel = formatDateTime(record.ranAt);
  const metrics = record.retrained
    ? [
        createCorrectionMetric("Samples Used", String(record.samplesUsed)),
        createCorrectionMetric("Mean Error", formatSigned(record.meanError || 0)),
        createCorrectionMetric("Mean Abs Error", roundValue(record.meanAbsoluteError || 0).toFixed(2)),
        createCorrectionMetric("Bias Shift", formatSigned(record.biasShift || 0, 3)),
      ].join("")
    : [
        createCorrectionMetric("Week", `${formatShortDate(record.startDate)} - ${formatShortDate(record.endDate)}`),
        createCorrectionMetric("Feedback Logs", String(record.feedbackRecords)),
        createCorrectionMetric("Last Sync", record.lastRetrainedAt ? formatDateTime(record.lastRetrainedAt) : "--"),
        createCorrectionMetric("Status", record.message || "No correction update"),
      ].join("");

  const summaryClass = record.retrained ? "correction-summary-banner" : "correction-summary-banner is-warning";
  const nextDue = record.nextDueAt
    ? `<p class="correction-summary-caption">Next correction window opens around ${formatDateTime(record.nextDueAt)}.</p>`
    : "";

  elements.correctionPanelTitle.textContent = record.windowLabel;
  elements.correctionPanelText.textContent = `Saved on ${ranAtLabel}. Collapse this panel any time and reopen it from the info icon archive.`;
  elements.correctionProgress.hidden = true;
  elements.correctionPanelBody.innerHTML = `
    <div class="correction-summary-shell">
      <div class="${summaryClass}">
        <p class="correction-summary-title">${record.headline}</p>
        <p class="correction-summary-caption">${record.retrained ? "The model has been rebalanced using the latest reviewed events for this week." : (record.message || "No model values changed for this week.")}</p>
        ${nextDue}
      </div>
      <div class="correction-summary-grid">
        ${metrics}
      </div>
      <div class="correction-summary-card">
        <div class="correction-summary-topline">
          <span class="correction-summary-list-label">Top Weight Shifts</span>
          <span class="review-meta">${record.retrained ? "Largest model weight changes" : "Awaiting reviewed deltas"}</span>
        </div>
        <div class="correction-summary-list">
          ${createCorrectionRows(record.weightChanges, "No weight changes were large enough to highlight.")}
        </div>
      </div>
      <div class="correction-summary-card">
        <div class="correction-summary-topline">
          <span class="correction-summary-list-label">Cause Adjustments</span>
          <span class="review-meta">${record.retrained ? "Strongest cause-specific tuning" : "No cause adjustments recorded"}</span>
        </div>
        <div class="correction-summary-list">
          ${createCorrectionRows(record.causeChanges, "No cause-level adjustments were recorded for this correction.")}
        </div>
      </div>
    </div>
  `;
  setCorrectionCollapseEnabled(true);
  openCorrectionPanel();
}

function renderCorrectionFailure(windowInfo, error) {
  const message = error?.message || "Weekly correction could not be completed.";
  elements.correctionPanelTitle.textContent = `Correction unavailable for ${windowInfo.label}`;
  elements.correctionPanelText.textContent = "The progress panel stayed active, but the summary could not be built this time.";
  elements.correctionProgress.hidden = true;
  elements.correctionPanelBody.innerHTML = `
    <div class="correction-summary-shell">
      <div class="correction-summary-banner is-warning">
        <p class="correction-summary-title">${message}</p>
        <p class="correction-summary-caption">Retry the correction once the backend is reachable again. Existing saved week summaries remain available through their info icons.</p>
      </div>
    </div>
  `;
  setCorrectionCollapseEnabled(true);
  openCorrectionPanel();
}

function riskBadge(score, riskLevel) {
  const background = score >= 82
    ? "#f4d7d2"
    : score >= 64
      ? "#f0ddd0"
      : score >= 42
        ? "#f5e6b8"
        : "#d8ecdf";
  const color = score >= 82
    ? "#bb4d43"
    : score >= 64
      ? "#d16d3f"
      : score >= 42
        ? "#9a7416"
        : "#3f8a5d";
  return `<span class="risk-badge" style="background:${background};color:${color}">${riskLevel}</span>`;
}

function impactBadge(score, color) {
  return `<span class="impact-badge" style="background:#f2ece2;color:${color};border:1px solid #ddd1bf">${score}</span>`;
}

function routeSourceLabel(routeSource) {
  if (routeSource === "google_gridlock_reranked") {
    return "Live reranked";
  }
  return "GridLock fallback";
}

function renderRouteEmptyState(title, message) {
  elements.routeResults.innerHTML = `
    <div class="route-empty-state">
      <strong>${title}</strong>
      <p class="route-meta">${message}</p>
    </div>
  `;
}

function createHotspotIcon(color) {
  return L.divIcon({
    className: "",
    html: `<div class="marker-hotspot" style="background:${color};color:${color}"></div>`,
    iconSize: [18, 18],
    iconAnchor: [9, 9],
  });
}

function createStationIcon() {
  return L.divIcon({
    className: "",
    html: "<div class=\"marker-station\"></div>",
    iconSize: [16, 16],
    iconAnchor: [8, 8],
  });
}

async function fetchJson(url, options) {
  const response = await fetch(url, options);
  if (!response.ok) {
    let message = `Request failed: ${response.status}`;
    try {
      const payload = await response.json();
      if (payload?.detail) {
        message = String(payload.detail);
      }
    } catch (error) {
      // ignore non-json error bodies
    }
    throw new Error(message);
  }
  return response.json();
}

async function loadEngineCatalog() {
  try {
    state.engineCatalog = await fetchJson("/engine/catalog");
  } catch (error) {
    state.engineCatalog = {
      known_event_causes: ["public_event", "procession", "protest", "vip_movement", "others"],
    };
  }
}

async function loadLearningState() {
  try {
    const learningState = await fetchJson("/learning/state");
    state.sessionId = learningState.session_id || null;
    state.sessionStartedAt = learningState.session_started_at || null;
    const storedSessionId = loadStoredCorrectionSessionId();
    if (storedSessionId && state.sessionId && storedSessionId !== state.sessionId) {
      clearCorrectionHistoryStore();
    }
    if (state.sessionId) {
      persistCorrectionSessionId(state.sessionId);
    }
  } catch (error) {
    state.sessionId = null;
    state.sessionStartedAt = null;
  }
}

async function loadLiveStatus() {
  const data = await fetchJson("/dashboard/live/status");
  state.liveStatus = data;
  if (data.session_id) {
    state.sessionId = data.session_id;
  }
  if (data.session_started_at) {
    state.sessionStartedAt = data.session_started_at;
  }
  return data;
}

function applyModeUi() {
  const isLive = isLiveMode();
  elements.goLiveButton.textContent = isLive ? "Back To History" : "Go Live";
  elements.goLiveButton.classList.toggle("is-live", isLive);
  elements.liveStatusPill.textContent = isLive
    ? (state.liveStatus?.stale ? "Live Mode (Stale Cache)" : "Live Mode")
    : "Historical Mode";
  elements.reviewTabButton.classList.toggle("locked", !isLive && !state.reviewUnlocked);
  elements.forceRetrainButton.disabled = isLive || state.correctionRunning;
  elements.forceRetrainButton.textContent = isLive ? "Historical Mode Only" : "Run Weekly Correction";
  elements.weekSelect.disabled = isLive;
  document.getElementById("previousWindowButton").disabled = isLive || state.windowIndex === 0;
  document.getElementById("nextWindowButton").disabled = isLive || state.windowIndex >= state.totalWindows - 1;
}

async function toggleDashboardMode() {
  state.mode = isLiveMode() ? "historical" : "live";
  state.viewedDates = new Set();
  state.reviewUnlocked = false;
  state.selectedEvent = null;
  state.selectedRouteId = null;
  clearRouteVisualization();
  document.querySelectorAll(".tab-button").forEach((item) => {
    item.classList.toggle("active", item.dataset.tab === "operations");
  });
  document.querySelectorAll(".tab-panel").forEach((panel) => {
    panel.classList.toggle("active", panel.dataset.panel === "operations");
  });
  try {
    if (isLiveMode()) {
      await loadLiveStatus();
    }
    await loadCalendarWindowsList();
    await loadCalendarWindow(0);
    applyModeUi();
    manageLivePolling();
  } catch (error) {
    elements.bannerTitle.textContent = "Dashboard mode could not load.";
    elements.bannerText.textContent = error.message || "Check the backend service and refresh the page.";
  }
}

function manageLivePolling() {
  if (state.livePollingHandle) {
    clearInterval(state.livePollingHandle);
    state.livePollingHandle = null;
  }
  if (!isLiveMode()) {
    return;
  }
  state.livePollingHandle = setInterval(async () => {
    try {
      const liveStatus = await loadLiveStatus();
      applyModeUi();
      const refreshAt = liveStatus.last_refresh_at || "";
      if (refreshAt && refreshAt !== state.liveRefreshSeenAt) {
        state.liveRefreshSeenAt = refreshAt;
        await loadCalendarWindow(0);
      }
    } catch (error) {
      // Keep the current live snapshot rendered until polling recovers.
    }
  }, LIVE_STATUS_POLL_MS);
}

function formatCauseLabel(value) {
  return String(value || "others")
    .split("_")
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

function populateManualEventCauseOptions() {
  const causes = state.engineCatalog?.known_event_causes?.length
    ? state.engineCatalog.known_event_causes
    : ["public_event", "procession", "protest", "vip_movement", "others"];
  elements.manualEventCause.innerHTML = causes
    .map((cause) => `<option value="${cause}">${formatCauseLabel(cause)}</option>`)
    .join("");
}

function populateManualEventLocationHints() {
  const locations = state.engineCatalog?.known_locations || [];
  elements.manualEventLocationHints.innerHTML = locations
    .map((location) => `<option value="${location}"></option>`)
    .join("");
}

function closeManualEventModal() {
  elements.manualEventOverlay.hidden = true;
}

function openManualEventModal() {
  const selectedDate = selectedOperationalDate();
  if (!selectedDate) {
    showToast("Select a dashboard date before adding an event.");
    return;
  }
  clearManualEventForm();
  populateManualEventCauseOptions();
  populateManualEventLocationHints();
  elements.manualEventDateLabel.value = formatDate(selectedDate);
  elements.manualEventTime.value = "18:00";
  elements.manualEventOverlay.hidden = false;
}

function clearManualEventForm() {
  elements.manualEventForm.reset();
  elements.manualEventDateLabel.value = "";
  elements.manualEventPickHint.textContent = "Use a Bengaluru road, junction, metro stop, area, or police station name.";
}

async function submitManualEvent(formEvent) {
  formEvent.preventDefault();
  const selectedDate = selectedOperationalDate();
  if (!selectedDate) {
    showToast("Select a dashboard date before saving an event.");
    return;
  }
  const formData = new FormData(elements.manualEventForm);
  const payload = {
    date: selectedDate,
    time: formData.get("time"),
    title: formData.get("title"),
    address: formData.get("address"),
    event_cause: formData.get("event_cause"),
    priority: formData.get("priority"),
    requires_road_closure: elements.manualEventClosure.checked,
    event_type: "planned",
    expected_attendance: formData.get("expected_attendance")
      ? Number(formData.get("expected_attendance"))
      : null,
  };
  elements.manualEventSubmitButton.disabled = true;
  elements.manualEventSubmitButton.textContent = "Saving...";
  try {
    const data = await fetchJson("/dashboard/events/manual", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    closeManualEventModal();
    clearManualEventForm();
    await loadDay(state.selectedDate, data.event.event_id);
    await loadReviewWindow();
    showToast(isLiveMode() ? "Manual event added to today’s live watch." : "Manual event added to the selected date.");
  } catch (error) {
    showToast(error.message || "Unable to save the manual event.");
  } finally {
    elements.manualEventSubmitButton.disabled = false;
    elements.manualEventSubmitButton.textContent = "Save Event";
  }
}

function clearRecommendationCard() {
  elements.priorityHotspotTitle.textContent = "Select a hotspot";
  elements.priorityHotspotMeta.textContent = "Impact details and field plan will appear here.";
  elements.priorityImpactValue.textContent = "--";
  elements.priorityRiskValue.textContent = "--";
  elements.priorityOfficerValue.textContent = "--";
  elements.priorityBarricadeValue.textContent = "--";
}

function updateRoutePlannerContext() {
  if (!state.selectedEvent) {
    elements.routeOriginStation.textContent = "Select a hotspot";
    elements.routeDestinationEvent.textContent = "Select a hotspot";
    elements.routeModeLabel.textContent = "Google Routes + GridLock reranking";
    elements.routeSubmitButton.disabled = true;
    return;
  }
  elements.routeOriginStation.textContent = state.selectedEvent.police_station.station_name;
  elements.routeDestinationEvent.textContent = state.selectedEvent.zone || "Zone unavailable";
  elements.routeModeLabel.textContent = "Assigned station to congestion source";
  elements.routeSubmitButton.disabled = false;
}

function clearRouteVisualization() {
  routeLayer.clearLayers();
  routeEndpointLayer.clearLayers();
  if (state.activeRouteAnimation) {
    cancelAnimationFrame(state.activeRouteAnimation);
    state.activeRouteAnimation = null;
  }
}

function decodePathPoints(route) {
  const pathPoints = route.path_points || route.waypoints || [];
  return pathPoints
    .map((point) => [Number(point.latitude), Number(point.longitude)])
    .filter((point) => Number.isFinite(point[0]) && Number.isFinite(point[1]));
}

function animateRouteSelection(route) {
  const path = decodePathPoints(route);
  if (path.length < 2) {
    return;
  }
  clearRouteVisualization();
  const basePolyline = L.polyline([], {
    color: "#1e4faf",
    weight: 5,
    opacity: 0.92,
    lineCap: "round",
    lineJoin: "round",
  }).addTo(routeLayer);
  const haloPolyline = L.polyline([], {
    color: "#8fb5ff",
    weight: 10,
    opacity: 0.28,
    lineCap: "round",
    lineJoin: "round",
  }).addTo(routeLayer);
  L.circleMarker(path[0], {
    radius: 9,
    color: "#ffffff",
    weight: 2,
    fillColor: "#0a2a73",
    fillOpacity: 1,
  }).addTo(routeEndpointLayer);
  L.circleMarker(path[path.length - 1], {
    radius: 9,
    color: "#ffffff",
    weight: 2,
    fillColor: route.recommended ? "#22c1a7" : "#f18d38",
    fillOpacity: 1,
  }).addTo(routeEndpointLayer);
  map.fitBounds(L.latLngBounds(path), { padding: [54, 54] });

  let index = 1;
  const increment = Math.max(1, Math.ceil(path.length / 26));
  const step = () => {
    const visiblePath = path.slice(0, index + 1);
    basePolyline.setLatLngs(visiblePath);
    haloPolyline.setLatLngs(visiblePath);
    if (index < path.length - 1) {
      index = Math.min(path.length - 1, index + increment);
      state.activeRouteAnimation = requestAnimationFrame(step);
      return;
    }
    state.activeRouteAnimation = null;
  };
  state.activeRouteAnimation = requestAnimationFrame(step);
}

async function loadCalendarWindow(windowIndex = 0) {
  const data = await fetchJson(`${dashboardBasePath()}/calendar?window=${windowIndex}`);
  state.windowIndex = data.window_index;
  state.totalWindows = data.total_windows;
  state.calendarDates = data.dates;
  state.currentWindow = {
    windowIndex: data.window_index,
    startDate: data.start_date,
    endDate: data.end_date,
    label: data.label || formatWeekRange(data.start_date, data.end_date),
  };
  if (isLiveMode()) {
    state.liveRefreshSeenAt = state.liveStatus?.last_refresh_at || state.liveRefreshSeenAt;
  }
  elements.weekSelect.dataset.label = state.currentWindow.label;
  elements.windowLabel.textContent = isLiveMode()
    ? "Today live feed"
    : `Window ${data.window_index + 1} / ${data.total_windows}`;
  renderWeekSelect();
  renderTimeline();
  renderCorrectionArchive();
  const latestDate = data.dates.length ? data.dates[data.dates.length - 1].date : null;
  const defaultDate = state.selectedDate && data.dates.some((item) => item.date === state.selectedDate)
    ? state.selectedDate
    : (isLiveMode() ? latestDate : (data.dates[0] ? data.dates[0].date : null));
  if (defaultDate) {
    await loadDay(defaultDate);
  } else {
    renderSummary({
      date: data.start_date,
      event_count: 0,
      critical_count: 0,
      average_impact_score: 0,
      high_or_above: 0,
      mode: state.mode,
    });
  }
  await loadReviewWindow();
  applyModeUi();
}

function renderWeekSelect() {
  const options = state.calendarWindows.map((window) => {
    const selected = window.window_index === state.windowIndex ? "selected" : "";
    const label = window.label || formatWeekRange(window.start_date, window.end_date);
    return `<option value="${window.window_index}" ${selected}>${label}</option>`;
  }).join("");
  elements.weekSelect.innerHTML = options;
}

async function loadCalendarWindowsList() {
  const data = await fetchJson(`${dashboardBasePath()}/calendar/windows`);
  state.calendarWindows = data.windows;
}

async function loadDay(dateKey, preferredEventId = null) {
  const data = await fetchJson(`${dashboardBasePath()}/day/${encodeURIComponent(dateKey)}`);
  state.selectedDate = dateKey;
  state.dayData = data;
  state.viewedDates.add(dateKey);
  state.reviewUnlocked = isLiveMode()
    ? true
    : state.calendarDates.length > 0 && state.calendarDates.every((item) => state.viewedDates.has(item.date));
  updateReviewGate();
  renderTimeline();
  renderSummary(data.summary);
  renderEventFeed(data.events);
  renderMap(data.events, data.police_markers);
  updateRoutePlannerContext();
  state.selectedRouteId = null;
  renderRouteEmptyState("Select a hotspot", "Pick a hotspot from the feed or map to generate a route from the assigned police station.");
  clearRouteVisualization();
  const defaultEvent = preferredEventId
    ? data.events.find((item) => item.event_id === preferredEventId) || data.events[0] || null
    : data.events[0] || null;
  if (defaultEvent) {
    setSelectedEvent(defaultEvent.event_id);
  } else {
    state.selectedEvent = null;
    clearRecommendationCard();
    fillDetailDock(null);
    updateRoutePlannerContext();
    renderRouteEmptyState(
      isLiveMode() ? "No hotspots in this snapshot" : "No hotspots on this date",
      isLiveMode()
        ? "Wait for the next live refresh or switch to historical mode."
        : "Move the timeline to another date with active congestion events to enable route suggestions.",
    );
  }
}

async function loadReviewWindow() {
  const data = await fetchJson(`${dashboardBasePath()}/review?window=${state.windowIndex}`);
  renderReviewFeed(data.events || [], data);
}

function renderTimeline() {
  elements.timelineBar.innerHTML = state.calendarDates
    .map((item) => {
      const parts = isLiveMode()
        ? {
          month: "LIVE",
          day: item.slot_hour || item.slot_label || "--",
        }
        : timelineParts(item.date);
      return `
        <button class="timeline-chip ${item.date === state.selectedDate ? "active" : ""} ${state.viewedDates.has(item.date) ? "viewed" : ""}" data-date="${item.date}" type="button">
          <div class="chip-day">${parts.month}</div>
          <div class="chip-score">${parts.day}</div>
          <div class="chip-events">${isLiveMode() ? (item.slot_label || "") : "&nbsp;"}</div>
        </button>
      `;
    })
    .join("");
  elements.timelineBar.querySelectorAll(".timeline-chip").forEach((button) => {
    button.addEventListener("click", () => loadDay(button.dataset.date));
  });
}

function renderSummary(summary) {
  const isLiveSummary = summary.mode === "live" || isLiveMode();
  elements.selectedDateLabel.textContent = isLiveSummary
    ? `Today ${summary.slot_label || (summary.date ? formatDateTime(summary.date).split(",").slice(-1)[0].trim() : "")}`
    : (summary.date ? formatDate(summary.date) : "--");
  elements.summaryEventCount.textContent = summary.event_count;
  elements.summaryCriticalCount.textContent = summary.critical_count;
  elements.summaryAverageImpact.textContent = summary.average_impact_score;
  if (isLiveSummary) {
    const staleLabel = state.liveStatus?.stale ? " Cached live probe remains active." : "";
    elements.bannerTitle.textContent = summary.critical_count > 0
      ? `${summary.critical_count} live critical zones require immediate watch`
      : `${summary.event_count} live hotspots monitored across Bengaluru today`;
    elements.bannerText.textContent = summary.event_count > 0
      ? `${summary.high_or_above} hotspots are currently operating at high or critical impact levels.${staleLabel}`
      : `No live hotspots are currently active.${staleLabel}`;
  } else {
    elements.bannerTitle.textContent = summary.critical_count > 0
      ? `${summary.critical_count} critical zones require immediate watch`
      : `${summary.event_count} hotspots mapped for ${summary.date ? formatDate(summary.date) : "the selected window"}`;
    elements.bannerText.textContent = summary.event_count > 0
      ? `${summary.high_or_above} hotspots are operating at high or critical congestion levels.`
      : "No events available for the selected date window.";
  }
}

function renderEventFeed(events) {
  if (!events.length) {
    elements.eventFeed.innerHTML = isLiveMode()
      ? "<div class=\"event-item\"><strong>No live hotspots in the current snapshot.</strong><p class=\"event-meta\">Wait for the next refresh or switch back to the historical dashboard.</p></div>"
      : "<div class=\"event-item\"><strong>No hotspots for this date.</strong><p class=\"event-meta\">Move the timeline to another day.</p></div>";
    return;
  }
  elements.eventFeed.innerHTML = events.map((event) => `
    <button class="event-item ${state.selectedEvent && state.selectedEvent.event_id === event.event_id ? "active" : ""}" data-event-id="${event.event_id}" type="button">
      <div class="event-item-top">
        <div>
          <strong>${event.title}</strong>${event.event_source === "manual" ? '<span class="event-source-pill">Manual</span>' : ""}
          <p class="event-meta">${event.event_source === "live" ? `${event.corridor} - ${event.zone}` : event.address}</p>
        </div>
        ${impactBadge(event.impact_score, event.impact_color)}
      </div>
      <div class="event-item-top">
        <div class="event-meta">${event.time} - ${event.corridor} - ${event.police_station.station_name}</div>
        ${riskBadge(event.impact_score, event.risk_level)}
      </div>
    </button>
  `).join("");
  elements.eventFeed.querySelectorAll(".event-item").forEach((button) => {
    button.addEventListener("click", () => setSelectedEvent(button.dataset.eventId));
  });
}

function renderMap(events, policeMarkers) {
  hotspotLayer.clearLayers();
  policeLayer.clearLayers();
  const bounds = [];

  events.forEach((event) => {
    const marker = L.marker([event.latitude, event.longitude], {
      icon: createHotspotIcon(event.impact_color),
    });
    marker.eventId = event.event_id;
    marker.bindPopup(`
      <strong>${event.title}</strong><br />
      ${event.event_source === "manual" ? '<span class="popup-meta">Operator event</span><br />' : ""}
      <span class="popup-meta">${event.event_source === "live" ? `${event.corridor} - ${event.zone}` : event.address}</span><br />
      <span class="popup-meta">Impact ${event.impact_score} - ${event.risk_level}</span><br />
      <span class="popup-meta">${event.police_station.station_name}</span>
    `);
    marker.on("click", () => setSelectedEvent(event.event_id));
    hotspotLayer.addLayer(marker);
    bounds.push([event.latitude, event.longitude]);
  });

  policeMarkers.forEach((station) => {
    const marker = L.marker([station.latitude, station.longitude], {
      icon: createStationIcon(),
    });
    marker.bindPopup(`
      <strong>${station.station_name}</strong><br />
      <span class="popup-meta">${station.historical_event_count} historical linked events</span>
    `);
    policeLayer.addLayer(marker);
    bounds.push([station.latitude, station.longitude]);
  });

  if (bounds.length) {
    map.fitBounds(bounds, { padding: [40, 40] });
  }
}

function setSelectedEvent(eventId) {
  if (!state.dayData) return;
  const event = state.dayData.events.find((item) => item.event_id === eventId);
  if (!event) return;
  state.selectedEvent = event;
  renderEventFeed(state.dayData.events);
  fillRecommendationCard(event);
  fillDetailDock(event);
  updateRoutePlannerContext();
  state.selectedRouteId = null;
  renderRouteEmptyState("Ready to route", "Click “Suggest Optimal Route” to compare the assigned station path to this congestion source.");
  clearRouteVisualization();
  hotspotLayer.eachLayer((layer) => {
    if (layer.eventId === eventId) {
      map.flyTo([event.latitude, event.longitude], Math.max(map.getZoom(), 13), { duration: 0.8 });
      layer.openPopup();
    }
  });
}

function fillRecommendationCard(event) {
  elements.priorityHotspotTitle.textContent = event.title;
  elements.priorityHotspotMeta.textContent = event.event_source === "live"
    ? `${event.corridor} - ${event.zone} - ${event.police_station.station_name}`
    : `${event.address} - ${event.corridor} - ${event.police_station.station_name}`;
  elements.priorityImpactValue.textContent = event.impact_score;
  elements.priorityRiskValue.textContent = event.risk_level;
  elements.priorityOfficerValue.textContent = event.resource_plan.traffic_officers_required;
  elements.priorityBarricadeValue.textContent = event.resource_plan.barricades_required;
}

function fillDetailDock(event) {
  if (!event) {
    elements.dockTitle.textContent = "Select a hotspot marker";
    elements.dockMeta.textContent = "Exact impact, station, diversion, and field deployment details will appear here.";
    elements.dockStation.textContent = "--";
    elements.dockCorridor.textContent = "--";
    elements.dockMarshals.textContent = "--";
    elements.dockDiversion.textContent = "--";
    elements.dockDiversions.innerHTML = "";
    return;
  }
  elements.dockTitle.textContent = event.title;
  elements.dockMeta.textContent = event.event_source === "live"
    ? `${event.zone} - ${event.corridor}`
    : `${event.zone} - ${event.address}`;
  elements.dockStation.textContent = event.police_station.station_name;
  elements.dockCorridor.textContent = event.corridor;
  elements.dockMarshals.textContent = event.resource_plan.traffic_marshals_required;
  elements.dockDiversion.textContent = event.diversion_required ? "Recommended" : "Not Required";
  elements.dockDiversions.innerHTML = event.diversion_suggestions.length
    ? event.diversion_suggestions.map((item) => `<span class="diversion-pill">${item.corridor} via ${item.via_junction}</span>`).join("")
    : "<span class=\"diversion-pill\">Direct corridor management preferred</span>";
}

function updateReviewGate() {
  if (isLiveMode()) {
    elements.reviewTabButton.classList.remove("locked");
    elements.reviewGateText.textContent = "Weekly review stays as a placeholder in live mode. Switch back to historical mode to log reviewed outcomes and run correction.";
    return;
  }
  const unlocked = state.reviewUnlocked;
  elements.reviewTabButton.classList.toggle("locked", !unlocked);
  elements.reviewGateText.textContent = unlocked
    ? "Weekly review unlocked. Operators can now log observed impact and field outcomes."
    : `Open all 7 dates in the current window to unlock review. Progress: ${state.viewedDates.size}/${state.calendarDates.length}.`;
}

function renderReviewFeed(events, payload = {}) {
  if (isLiveMode() || payload.placeholder) {
    elements.reviewFeed.innerHTML = `<div class="review-item"><strong>Weekly review placeholder</strong><p class="review-meta">${payload.message || "Historical mode keeps the full weekly correction workflow."}</p></div>`;
    return;
  }
  if (!events.length) {
    elements.reviewFeed.innerHTML = "<div class=\"review-item\"><strong>No events in this review window.</strong></div>";
    return;
  }
  elements.reviewFeed.innerHTML = events.map((event) => `
    <form class="review-item" data-event-id="${event.event_id}">
      <div class="review-item-top">
        <div>
          <strong>${event.title}</strong>
          <p class="review-meta">${formatDate(event.date)} - ${event.time} - ${event.corridor}</p>
        </div>
        ${impactBadge(event.predicted_impact_score, event.impact_color)}
      </div>
      <div class="review-form-grid">
        <label>
          Actual Impact Score
          <select name="actual_impact_score">
            ${event.dropdown_options.actual_impact_scores.map((score) => `<option value="${score}" ${score === Math.round(event.predicted_impact_score / 5) * 5 ? "selected" : ""}>${score}</option>`).join("")}
          </select>
        </label>
        <label>
          Observed Severity
          <select name="observed_severity">
            ${event.dropdown_options.observed_severity.map((item) => `<option value="${item}">${item}</option>`).join("")}
          </select>
        </label>
        <label>
          Observed Crowd Level
          <select name="observed_crowd_level">
            ${event.dropdown_options.crowd_levels.map((item) => `<option value="${item}">${item}</option>`).join("")}
          </select>
        </label>
        <label>
          Clearance Minutes
          <input type="number" name="actual_clearance_minutes" min="0" value="45" />
        </label>
        <label>
          Field Officers
          <input type="number" name="field_officers_deployed" min="0" value="${event.resource_plan.traffic_officers_required}" />
        </label>
        <label>
          Field Barricades
          <input type="number" name="field_barricades_used" min="0" value="${event.resource_plan.barricades_required}" />
        </label>
      </div>
      <label>
        Operator Notes
        <textarea name="notes" placeholder="Observed dispersal pattern, bottleneck, or unexpected field issue"></textarea>
      </label>
      <button class="review-submit" type="submit">Log Weekly Review</button>
    </form>
  `).join("");

  elements.reviewFeed.querySelectorAll("form").forEach((form) => {
    form.addEventListener("submit", async (submitEvent) => {
      submitEvent.preventDefault();
      if (!state.reviewUnlocked) {
        showToast("Open all 7 dates in this window before submitting weekly review.");
        return;
      }
      const eventId = form.dataset.eventId;
      const reviewSource = events.find((item) => item.event_id === eventId);
      const payload = buildFeedbackPayload(reviewSource, new FormData(form));
      try {
        await fetchJson("/feedback/log", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });
        showToast("Weekly review logged.");
      } catch (error) {
        showToast("Unable to log weekly review.");
      }
    });
  });
}

function buildFeedbackPayload(reviewEvent, formData) {
  return {
    event_reference_id: reviewEvent.event_id,
    event_cause: reviewEvent.event_cause,
    priority: reviewEvent.priority,
    requires_road_closure: Boolean(reviewEvent.requires_road_closure),
    latitude: reviewEvent.latitude,
    longitude: reviewEvent.longitude,
    event_type: reviewEvent.event_type,
    start_datetime: reviewEvent.date ? `${reviewEvent.date}T${reviewEvent.time || "00:00"}:00+05:30` : null,
    end_latitude: reviewEvent.end_latitude ?? null,
    end_longitude: reviewEvent.end_longitude ?? null,
    actual_impact_score: Number(formData.get("actual_impact_score")),
    observed_severity: formData.get("observed_severity"),
    observed_crowd_level: formData.get("observed_crowd_level"),
    actual_clearance_minutes: Number(formData.get("actual_clearance_minutes")),
    field_officers_deployed: Number(formData.get("field_officers_deployed")),
    field_barricades_used: Number(formData.get("field_barricades_used")),
    diversion_effectiveness: "Operator Reviewed",
    notes: formData.get("notes"),
    source: "manual_dashboard",
  };
}

async function submitRoute(event) {
  event.preventDefault();
  if (!state.selectedEvent) {
    renderRouteEmptyState("Select a hotspot", "Pick a hotspot from the feed or map before requesting an optimal route.");
    showToast("Select a hotspot first to route around it.");
    return;
  }

  try {
    elements.routeSubmitButton.disabled = true;
    elements.routeSubmitButton.textContent = "Finding Route...";
    const payload = {
      event_id: state.selectedEvent.event_id,
      alternatives: 3,
    };
    const data = await fetchJson("/routes/recommend", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    state.routeData = data;
    if (!data.routes.length) {
      renderRouteEmptyState("No routes available", "Try another hotspot or retry once live routing is available.");
      clearRouteVisualization();
      return;
    }

    state.selectedRouteId = null;
    elements.routeModeLabel.textContent = data.route_source === "google_gridlock_reranked"
      ? "Google Routes + GridLock reranking"
      : "GridLock fallback routing";
    elements.routeResults.innerHTML = data.routes.map((route) => `
      <button class="route-card" data-route-id="${route.route_label}" type="button">
        <div class="route-card-top">
          <div>
            <strong>${route.route_label}${route.recommended ? " - Recommended" : ""}</strong>
            <p class="route-meta">${route.origin_station?.station_name || state.selectedEvent.police_station.station_name} Police Station &rarr; ${route.destination_event?.zone || state.selectedEvent.zone || "Zone unavailable"}</p>
          </div>
          <div class="route-metric-badge" title="Normalized GridLock exposure score">Exposure ${route.gridlock_exposure_score}/100</div>
        </div>
        <div class="route-metric-grid">
          <div class="route-metric-cell">
            <span>ETA</span>
            <strong>${route.google_duration_minutes ? `${route.google_duration_minutes} min` : "--"}</strong>
          </div>
          <div class="route-metric-cell">
            <span>Distance</span>
            <strong>${route.google_distance_km ?? route.estimated_distance_km} km</strong>
          </div>
          <div class="route-metric-cell">
            <span>Exposure</span>
            <strong>${route.gridlock_exposure_score}/100</strong>
          </div>
        </div>
        <p class="route-meta"><strong>Why this rank:</strong> ${route.rerank_reason}</p>
        <div class="route-card-top">
          <span class="route-source-badge">${routeSourceLabel(route.route_source)}</span>
          <span class="route-meta">${route.recommended ? "Best operational route" : "Alternative path"}</span>
        </div>
      </button>
    `).join("");

    elements.routeResults.querySelectorAll(".route-card").forEach((button) => {
      button.addEventListener("click", () => {
        const route = data.routes.find((item) => item.route_label === button.dataset.routeId);
        if (!route) {
          return;
        }
        state.selectedRouteId = route.route_label;
        elements.routeResults.querySelectorAll(".route-card").forEach((card) => {
          card.classList.toggle("active", card === button);
        });
        animateRouteSelection(route);
      });
    });

    const recommendedRoute = data.routes.find((route) => route.recommended) || data.routes[0];
    if (recommendedRoute) {
      state.selectedRouteId = recommendedRoute.route_label;
      const recommendedButton = elements.routeResults.querySelector(`[data-route-id="${recommendedRoute.route_label}"]`);
      if (recommendedButton) {
        recommendedButton.classList.add("active");
      }
      animateRouteSelection(recommendedRoute);
    }
  } catch (error) {
    state.routeData = null;
    state.selectedRouteId = null;
    clearRouteVisualization();
    elements.routeModeLabel.textContent = "Google Routes + GridLock reranking";
    renderRouteEmptyState("Route suggestion unavailable", "Check the backend service or Google Routes configuration, then try again.");
    showToast("Unable to fetch route suggestions.");
  } finally {
    elements.routeSubmitButton.disabled = !state.selectedEvent;
    elements.routeSubmitButton.textContent = "Suggest Optimal Route";
  }
}

function setupTabs() {
  document.querySelectorAll(".tab-button").forEach((button) => {
    button.addEventListener("click", () => {
      const tab = button.dataset.tab;
      if (!isLiveMode() && tab === "review" && !state.reviewUnlocked) {
        showToast("Open all 7 dates in the current window to unlock weekly review.");
        return;
      }
      document.querySelectorAll(".tab-button").forEach((item) => {
        item.classList.toggle("active", item === button);
      });
      document.querySelectorAll(".tab-panel").forEach((panel) => {
        panel.classList.toggle("active", panel.dataset.panel === tab);
      });
    });
  });
}

async function runWeeklyCorrection() {
  if (isLiveMode()) {
    showToast("Weekly correction is available in historical mode only.");
    return;
  }
  if (!state.reviewUnlocked) {
    showToast("Open all 7 dates in the current window to unlock weekly review.");
    return;
  }
  if (!state.currentWindow || state.correctionRunning) {
    return;
  }

  state.correctionRunning = true;
  elements.forceRetrainButton.disabled = true;
  elements.forceRetrainButton.textContent = "Running Correction...";
  renderCorrectionLoading(state.currentWindow);

  const learningStatePromise = fetchJson("/learning/state").catch(() => null);
  const correctionPromise = fetchJson("/learning/retrain", { method: "POST" })
    .then((result) => ({ ok: true, result }))
    .catch((error) => ({ ok: false, error }));

  const [, beforeState, correctionResponse] = await Promise.all([
    delay(MIN_CORRECTION_PANEL_MS),
    learningStatePromise,
    correctionPromise,
  ]);

  state.correctionRunning = false;
  elements.forceRetrainButton.disabled = false;
  elements.forceRetrainButton.textContent = "Run Weekly Correction";

  if (!correctionResponse.ok) {
    renderCorrectionFailure(state.currentWindow, correctionResponse.error);
    showToast("Unable to run weekly correction.");
    return;
  }

  const record = buildCorrectionRecord(state.currentWindow, beforeState, correctionResponse.result);
  upsertCorrectionRecord(record);
  renderCorrectionSummary(record);
  showToast(record.retrained ? "Weekly correction completed." : "Weekly correction checked.");
}

function setupControls() {
  setupTabs();
  elements.goLiveButton.addEventListener("click", toggleDashboardMode);
  elements.addEventButton.addEventListener("click", openManualEventModal);
  elements.manualEventCloseButton.addEventListener("click", () => {
    closeManualEventModal();
    clearManualEventForm();
  });
  elements.manualEventCancelButton.addEventListener("click", () => {
    closeManualEventModal();
    clearManualEventForm();
  });
  elements.manualEventForm.addEventListener("submit", submitManualEvent);
  elements.manualEventOverlay.addEventListener("click", (clickEvent) => {
    if (clickEvent.target === elements.manualEventOverlay) {
      closeManualEventModal();
      clearManualEventForm();
    }
  });
  document.getElementById("routeForm").addEventListener("submit", submitRoute);
  document.getElementById("fitCityButton").addEventListener("click", () => {
    map.setView([12.9716, 77.5946], 11);
  });
  document.getElementById("focusHotspotButton").addEventListener("click", () => {
    if (state.selectedEvent) {
      map.flyTo([state.selectedEvent.latitude, state.selectedEvent.longitude], 13, { duration: 0.8 });
    }
  });
  document.getElementById("stationAlertButton").addEventListener("click", () => {
    raiseStationAlert();
  });
  document.getElementById("previousWindowButton").addEventListener("click", async () => {
    if (isLiveMode()) return;
    if (state.windowIndex === 0) return;
    state.viewedDates = new Set();
    state.reviewUnlocked = false;
    await loadCalendarWindow(state.windowIndex - 1);
  });
  document.getElementById("nextWindowButton").addEventListener("click", async () => {
    if (isLiveMode()) return;
    if (state.windowIndex >= state.totalWindows - 1) return;
    state.viewedDates = new Set();
    state.reviewUnlocked = false;
    await loadCalendarWindow(state.windowIndex + 1);
  });
  elements.weekSelect.addEventListener("change", async (event) => {
    if (isLiveMode()) {
      return;
    }
    state.viewedDates = new Set();
    state.reviewUnlocked = false;
    await loadCalendarWindow(Number(event.target.value));
  });
  elements.forceRetrainButton.addEventListener("click", runWeeklyCorrection);
  elements.correctionCollapseButton.addEventListener("click", () => {
    if (!elements.correctionCollapseButton.disabled) {
      closeCorrectionPanel();
    }
  });
  elements.correctionCollapseAction.addEventListener("click", () => {
    if (!elements.correctionCollapseAction.disabled) {
      closeCorrectionPanel();
    }
  });
}

async function raiseStationAlert() {
    if (!state.selectedEvent) {
      showToast("Select a hotspot before raising a station alert.");
      return;
    }
  const stationAlertButton = document.getElementById("stationAlertButton");
  stationAlertButton.disabled = true;
  stationAlertButton.textContent = "Sending Alert...";
  try {
    const data = await fetchJson("/alerts/station-email", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ event_id: state.selectedEvent.event_id }),
    });
    showToast(`Station alert sent to ${data.recipient}.`);
  } catch (error) {
    showToast(error.message || "Unable to send station alert.");
  } finally {
    stationAlertButton.disabled = false;
    stationAlertButton.textContent = "Raise Station Alert";
  }
}

async function bootstrap() {
  await loadLearningState();
  await loadEngineCatalog();
  renderCorrectionArchive();
  setupPanelResize();
  setupControls();
  populateManualEventCauseOptions();
  populateManualEventLocationHints();
  try {
    await loadCalendarWindowsList();
    await loadCalendarWindow(0);
    applyModeUi();
  } catch (error) {
    elements.bannerTitle.textContent = "Dashboard could not load.";
    elements.bannerText.textContent = "Check the backend service and refresh the page.";
  }
}

bootstrap();

