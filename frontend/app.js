const state = {
  windowIndex: 0,
  totalWindows: 0,
  selectedDate: null,
  selectedEvent: null,
  viewedDates: new Set(),
  calendarDates: [],
  calendarWindows: [],
  dayData: null,
  reviewUnlocked: false,
  routeData: null,
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

const elements = {
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
};

function showToast(message) {
  elements.toast.textContent = message;
  elements.toast.classList.add("visible");
  clearTimeout(showToast.timer);
  showToast.timer = setTimeout(() => {
    elements.toast.classList.remove("visible");
  }, 2200);
}

function formatDate(dateText) {
  return new Date(`${dateText}T00:00:00`).toLocaleDateString("en-IN", {
    weekday: "short",
    day: "numeric",
    month: "short",
  });
}

function timelineParts(dateText) {
  const date = new Date(`${dateText}T00:00:00`);
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
    throw new Error(`Request failed: ${response.status}`);
  }
  return response.json();
}

function clearRecommendationCard() {
  elements.priorityHotspotTitle.textContent = "Select a hotspot";
  elements.priorityHotspotMeta.textContent = "Impact details and field plan will appear here.";
  elements.priorityImpactValue.textContent = "--";
  elements.priorityRiskValue.textContent = "--";
  elements.priorityOfficerValue.textContent = "--";
  elements.priorityBarricadeValue.textContent = "--";
}

async function loadCalendarWindow(windowIndex = 0) {
  const data = await fetchJson(`/dashboard/calendar?window=${windowIndex}`);
  state.windowIndex = data.window_index;
  state.totalWindows = data.total_windows;
  state.calendarDates = data.dates;
  elements.weekSelect.dataset.label = data.label || formatWeekRange(data.start_date, data.end_date);
  elements.windowLabel.textContent = `Window ${data.window_index + 1} / ${data.total_windows}`;
  renderWeekSelect();
  renderTimeline();
  const defaultDate = state.selectedDate && data.dates.some((item) => item.date === state.selectedDate)
    ? state.selectedDate
    : (data.dates[0] ? data.dates[0].date : null);
  if (defaultDate) {
    await loadDay(defaultDate);
  } else {
    renderSummary({
      date: data.start_date,
      event_count: 0,
      critical_count: 0,
      average_impact_score: 0,
      high_or_above: 0,
    });
  }
  await loadReviewWindow();
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
  const data = await fetchJson("/dashboard/calendar/windows");
  state.calendarWindows = data.windows;
}

async function loadDay(dateKey) {
  const data = await fetchJson(`/dashboard/day/${dateKey}`);
  state.selectedDate = dateKey;
  state.dayData = data;
  state.viewedDates.add(dateKey);
  state.reviewUnlocked = state.calendarDates.length > 0
    && state.calendarDates.every((item) => state.viewedDates.has(item.date));
  updateReviewGate();
  renderTimeline();
  renderSummary(data.summary);
  renderEventFeed(data.events);
  renderMap(data.events, data.police_markers);
  const defaultEvent = data.events[0] || null;
  if (defaultEvent) {
    setSelectedEvent(defaultEvent.event_id);
  } else {
    state.selectedEvent = null;
    clearRecommendationCard();
    fillDetailDock(null);
  }
}

async function loadReviewWindow() {
  const data = await fetchJson(`/dashboard/review?window=${state.windowIndex}`);
  renderReviewFeed(data.events);
}

function renderTimeline() {
  elements.timelineBar.innerHTML = state.calendarDates
    .map((item) => {
      const parts = timelineParts(item.date);
      return `
        <button class="timeline-chip ${item.date === state.selectedDate ? "active" : ""} ${state.viewedDates.has(item.date) ? "viewed" : ""}" data-date="${item.date}" type="button">
          <div class="chip-day">${parts.month}</div>
          <div class="chip-score">${parts.day}</div>
          <div class="chip-events">&nbsp;</div>
        </button>
      `;
    })
    .join("");
  elements.timelineBar.querySelectorAll(".timeline-chip").forEach((button) => {
    button.addEventListener("click", () => loadDay(button.dataset.date));
  });
}

function renderSummary(summary) {
  elements.selectedDateLabel.textContent = summary.date ? formatDate(summary.date) : "--";
  elements.summaryEventCount.textContent = summary.event_count;
  elements.summaryCriticalCount.textContent = summary.critical_count;
  elements.summaryAverageImpact.textContent = summary.average_impact_score;
  elements.bannerTitle.textContent = summary.critical_count > 0
    ? `${summary.critical_count} critical zones require immediate watch`
    : `${summary.event_count} hotspots mapped for ${summary.date ? formatDate(summary.date) : "the selected window"}`;
  elements.bannerText.textContent = summary.event_count > 0
    ? `${summary.high_or_above} hotspots are operating at high or critical congestion levels.`
    : "No events available for the selected date window.";
}

function renderEventFeed(events) {
  if (!events.length) {
    elements.eventFeed.innerHTML = "<div class=\"event-item\"><strong>No hotspots for this date.</strong><p class=\"event-meta\">Move the timeline to another day.</p></div>";
    return;
  }
  elements.eventFeed.innerHTML = events.map((event) => `
    <button class="event-item ${state.selectedEvent && state.selectedEvent.event_id === event.event_id ? "active" : ""}" data-event-id="${event.event_id}" type="button">
      <div class="event-item-top">
        <div>
          <strong>${event.title}</strong>
          <p class="event-meta">${event.address}</p>
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
      <span class="popup-meta">${event.address}</span><br />
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
  hotspotLayer.eachLayer((layer) => {
    if (layer.eventId === eventId) {
      map.flyTo([event.latitude, event.longitude], Math.max(map.getZoom(), 13), { duration: 0.8 });
      layer.openPopup();
    }
  });
}

function fillRecommendationCard(event) {
  elements.priorityHotspotTitle.textContent = event.title;
  elements.priorityHotspotMeta.textContent = `${event.address} - ${event.corridor} - ${event.police_station.station_name}`;
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
  elements.dockMeta.textContent = `${event.zone} - ${event.address}`;
  elements.dockStation.textContent = event.police_station.station_name;
  elements.dockCorridor.textContent = event.corridor;
  elements.dockMarshals.textContent = event.resource_plan.traffic_marshals_required;
  elements.dockDiversion.textContent = event.diversion_required ? "Recommended" : "Not Required";
  elements.dockDiversions.innerHTML = event.diversion_suggestions.length
    ? event.diversion_suggestions.map((item) => `<span class="diversion-pill">${item.corridor} via ${item.via_junction}</span>`).join("")
    : "<span class=\"diversion-pill\">Direct corridor management preferred</span>";
}

function updateReviewGate() {
  const unlocked = state.reviewUnlocked;
  elements.reviewTabButton.classList.toggle("locked", !unlocked);
  elements.reviewGateText.textContent = unlocked
    ? "Weekly review unlocked. Operators can now log observed impact and field outcomes."
    : `Open all 7 dates in the current window to unlock review. Progress: ${state.viewedDates.size}/${state.calendarDates.length}.`;
}

function renderReviewFeed(events) {
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
    showToast("Select a hotspot first to route around it.");
    return;
  }
  const formData = new FormData(event.target);
  const payload = {
    origin_latitude: Number(formData.get("origin_latitude")),
    origin_longitude: Number(formData.get("origin_longitude")),
    destination_latitude: Number(formData.get("destination_latitude")),
    destination_longitude: Number(formData.get("destination_longitude")),
    alternatives: 3,
    event_context: {
      event_cause: state.selectedEvent.event_cause,
      priority: state.selectedEvent.priority,
      requires_road_closure: state.selectedEvent.requires_road_closure,
      latitude: state.selectedEvent.latitude,
      longitude: state.selectedEvent.longitude,
      event_type: state.selectedEvent.event_type,
    },
  };
  const data = await fetchJson("/routes/recommend", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  state.routeData = data;
  elements.routeResults.innerHTML = data.routes.map((route) => `
    <div class="route-card">
      <div class="route-card-top">
        <div>
          <strong>${route.route_label}${route.recommended ? " - Recommended" : ""}</strong>
          <p class="route-meta">${route.waypoints.slice(1, -1).map((point) => point.corridor).filter(Boolean).slice(0, 4).join(" -> ")}</p>
        </div>
        <div>${route.average_exposure_score}</div>
      </div>
      <p class="route-meta">${route.estimated_distance_km} km - Travel multiplier ${route.estimated_travel_multiplier}</p>
    </div>
  `).join("");
}

function setupTabs() {
  document.querySelectorAll(".tab-button").forEach((button) => {
    button.addEventListener("click", () => {
      const tab = button.dataset.tab;
      if (tab === "review" && !state.reviewUnlocked) {
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

function setupControls() {
  setupTabs();
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
    if (!state.selectedEvent) {
      showToast("Select a hotspot before raising a station alert.");
      return;
    }
    showToast(`Alert relay prepared for ${state.selectedEvent.police_station.station_name}.`);
  });
  document.getElementById("previousWindowButton").addEventListener("click", async () => {
    if (state.windowIndex === 0) return;
    state.viewedDates = new Set();
    state.reviewUnlocked = false;
    await loadCalendarWindow(state.windowIndex - 1);
  });
  document.getElementById("nextWindowButton").addEventListener("click", async () => {
    if (state.windowIndex >= state.totalWindows - 1) return;
    state.viewedDates = new Set();
    state.reviewUnlocked = false;
    await loadCalendarWindow(state.windowIndex + 1);
  });
  elements.weekSelect.addEventListener("change", async (event) => {
    state.viewedDates = new Set();
    state.reviewUnlocked = false;
    await loadCalendarWindow(Number(event.target.value));
  });
  document.getElementById("forceRetrainButton").addEventListener("click", async () => {
    try {
      const result = await fetchJson("/learning/retrain", { method: "POST" });
      showToast(result.retrained ? "Weekly correction completed." : "No review data available yet.");
    } catch (error) {
      showToast("Unable to run weekly correction.");
    }
  });
}

async function bootstrap() {
  setupControls();
  try {
    await loadCalendarWindowsList();
    await loadCalendarWindow(0);
  } catch (error) {
    elements.bannerTitle.textContent = "Dashboard could not load.";
    elements.bannerText.textContent = "Check the backend service and refresh the page.";
  }
}

bootstrap();
