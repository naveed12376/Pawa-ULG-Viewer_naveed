// Flight Review (Default) page — entry view

const els = {
  fileName:    document.getElementById("fileName"),
  fileChip:    document.getElementById("fileChip"),
  fileStats:   document.getElementById("fileStats"),
  statusText:  document.getElementById("statusText"),
  grid:        document.getElementById("panelGrid"),
  loading:     document.getElementById("loadingOverlay"),
  welcome:     document.getElementById("welcomeOverlay"),
  browseBtn:   document.getElementById("browseBtn"),
  customBtn:   document.getElementById("customBtn"),
  toast:       document.getElementById("toast"),
  dropOverlay: document.getElementById("dropOverlay"),
};

let toastTimer = null;
function toast(msg, kind = "") {
  els.toast.textContent = msg;
  els.toast.className = "toast " + (kind || "");
  els.toast.hidden = false;
  if (toastTimer) clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { els.toast.hidden = true; }, 2200);
}

function setStatus(msg) { els.statusText.textContent = msg; }

const PLOTLY_CONFIG = {
  responsive: true,
  displaylogo: false,
  modeBarButtonsToRemove: ["lasso2d", "select2d"],
  toImageButtonOptions: { format: "png", scale: 2 },
};

function cssVar(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

function plotTheme() {
  return {
    text:        cssVar("--plot-text"),
    textDim:     cssVar("--plot-text-dim"),
    grid:        cssVar("--plot-grid"),
    zero:        cssVar("--plot-zero"),
    axis:        cssVar("--plot-axis"),
    tick:        cssVar("--plot-tick"),
    legendBg:    cssVar("--plot-legend-bg"),
    legendBord:  cssVar("--plot-legend-border"),
    hoverBg:     cssVar("--plot-hover-bg"),
    hoverBord:   cssVar("--plot-hover-border"),
  };
}

function baseLayout(extra = {}) {
  const t = plotTheme();
  return Object.assign({
    paper_bgcolor: "rgba(0,0,0,0)",
    plot_bgcolor: "rgba(0,0,0,0)",
    font: { family: "Inter, sans-serif", size: 11, color: t.text },
    margin: { l: 60, r: 24, t: 10, b: 40 },
    xaxis: {
      gridcolor: t.grid,
      zerolinecolor: t.zero,
      linecolor: t.axis,
      tickcolor: t.tick,
      title: { text: "time [s]", font: { color: t.textDim, size: 10 } },
    },
    yaxis: {
      gridcolor: t.grid,
      zerolinecolor: t.zero,
      linecolor: t.axis,
      tickcolor: t.tick,
    },
    legend: {
      bgcolor: t.legendBg,
      bordercolor: t.legendBord,
      borderwidth: 1,
      font: { size: 10 },
      orientation: "v",
      x: 1.005, xanchor: "left",
      y: 0.88, yanchor: "top",
    },
    hovermode: "x unified",
    hoverlabel: { bgcolor: t.hoverBg, bordercolor: t.hoverBord, font: { color: t.text } },
  }, extra);
}

function renderTimePanel(target, panel) {
  const traces = panel.series.map(s => ({
    x: s.t,
    y: s.y,
    name: s.name,
    type: "scatter",
    mode: "lines",
    line: { color: s.color || undefined, width: 1.3 },
    hovertemplate: `<b>${s.name}</b><br>t=%{x:.2f}s<br>val=%{y}<extra></extra>`,
  }));
  const layout = baseLayout({
    yaxis: Object.assign({}, baseLayout().yaxis, {
      title: { text: panel.ylabel || "", font: { color: "#9aa3c7", size: 10 } }
    }),
  });
  Plotly.newPlot(target, traces, layout, PLOTLY_CONFIG);
}

function renderScatterXY(target, panel) {
  const traces = panel.series.map(s => {
    const mode = s.mode || "lines";
    const color = s.color || "#a78bfa";
    const trace = {
      x: s.x, y: s.y,
      name: s.name,
      type: "scatter",
      mode,
      line: { color, width: 1.5 },
      hovertemplate: `<b>${s.name}</b><br>E=%{x:.2f} m<br>N=%{y:.2f} m<extra></extra>`,
    };
    if (mode === "markers") {
      trace.marker = {
        size: 9,
        color: "rgba(0,0,0,0)",
        symbol: "circle",
        line: { color, width: 1.6 },
      };
    } else {
      trace.marker = { size: 3, color };
    }
    return trace;
  });
  const layout = baseLayout({
    xaxis: Object.assign({}, baseLayout().xaxis, {
      title: { text: panel.xlabel || "", font: { color: "#9aa3c7", size: 10 } },
      scaleanchor: "y", scaleratio: 1,
    }),
    yaxis: Object.assign({}, baseLayout().yaxis, {
      title: { text: panel.ylabel || "", font: { color: "#9aa3c7", size: 10 } }
    }),
    showlegend: true,
  });
  Plotly.newPlot(target, traces, layout, PLOTLY_CONFIG);
}

function buildPanelDOM(idx, panel) {
  const section = document.createElement("section");
  section.className = "review-panel";

  const header = document.createElement("div");
  header.className = "review-panel-header";
  header.innerHTML = `
    <span class="panel-num">${String(idx + 1).padStart(2, "0")}</span>
    <h3>${panel.title}</h3>
    <span class="panel-ylabel">${panel.ylabel || ""}</span>
  `;
  section.appendChild(header);

  const body = document.createElement("div");
  body.className = "review-panel-body";
  const plotDiv = document.createElement("div");
  if (panel.type === "map") {
    plotDiv.className = "review-map";
  } else {
    plotDiv.className = "review-plot" + (panel.type === "scatter_xy" ? " tall" : "");
  }
  body.appendChild(plotDiv);
  section.appendChild(body);

  return { section, plotDiv };
}

function formatDuration(seconds) {
  if (!seconds || seconds <= 0) return "0 seconds";
  const s = Math.floor(seconds);
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  if (h > 0) return `${h}:${String(m).padStart(2, "0")}:${String(sec).padStart(2, "0")}`;
  if (m > 0) return `${m}:${String(sec).padStart(2, "0")}`;
  return `${sec} seconds`;
}

function formatHuman(seconds) {
  if (!seconds || seconds <= 0) return "0 seconds";
  const s = Math.floor(seconds);
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  const parts = [];
  if (h) parts.push(`${h} hour${h !== 1 ? "s" : ""}`);
  if (m) parts.push(`${m} minute${m !== 1 ? "s" : ""}`);
  if (sec || parts.length === 0) parts.push(`${sec} second${sec !== 1 ? "s" : ""}`);
  return parts.join(" ");
}

function buildInfoCard(info) {
  const wrap = document.createElement("section");
  wrap.className = "info-card";

  // Title — e.g. "PX4 Quadrotor"
  const title = document.createElement("h2");
  title.className = "info-card-title";
  const titleText = info.airframe_group
    ? `PX4 ${info.airframe_group.replace(/^Generic /, "")}`
    : "PX4 Flight Log";
  title.innerHTML = `<span>${titleText}</span>` +
    (info.airframe_id ? `<span class="id-chip">${info.airframe_id}</span>` : "");
  wrap.appendChild(title);

  const grid = document.createElement("div");
  grid.className = "info-grid";

  const f = (n, unit) => (n != null && isFinite(n) ? `${n.toFixed(1)} ${unit}` : "—");

  // All entries in one list, then split evenly across two columns.
  const rows = [
    ["Logging Duration", formatDuration(info.logging_duration_s)],
    ["Vehicle Life Flight Time",
        info.lifetime_s > 0 ? formatHuman(info.lifetime_s) : formatHuman(info.flight_time_s)],
    ["Distance",                f(info.distance_m, "m")],
    ["Max Altitude Difference", f(info.max_altitude_diff_m, "m")],
    ["Average Speed",           f(info.avg_speed_kmh, "km/h")],
    ["Max Speed",               f(info.max_speed_kmh, "km/h")],
    ["Max Speed Horizontal",    f(info.max_speed_horizontal_kmh, "km/h")],
    ["Max Speed Up",            f(info.max_speed_up_kmh, "km/h")],
    ["Max Speed Down",          f(info.max_speed_down_kmh, "km/h")],
    ["Max Tilt Angle",          f(info.max_tilt_deg, "deg")],
  ];

  const half = Math.ceil(rows.length / 2);
  const columns = [rows.slice(0, half), rows.slice(half)];
  for (const colRows of columns) {
    const col = document.createElement("div");
    col.className = "info-col";
    for (const [label, value] of colRows) {
      const l = document.createElement("div"); l.className = "info-label"; l.textContent = label + ":";
      const v = document.createElement("div"); v.className = "info-value"; v.innerHTML = value;
      col.appendChild(l); col.appendChild(v);
    }
    grid.appendChild(col);
  }

  wrap.appendChild(grid);
  return wrap;
}

function renderMap(target, panel) {
  if (typeof L === "undefined") {
    target.innerHTML = `<div class="empty-panel-text">Leaflet failed to load (offline?).</div>`;
    return;
  }
  const s = panel.series && panel.series[0];
  if (!s || !s.lat || s.lat.length < 2) {
    target.innerHTML = `<div class="empty-panel-text">No valid GPS data.</div>`;
    return;
  }
  const coords = s.lat.map((la, i) => [la, s.lon[i]]).filter(c => c[0] !== null && c[1] !== null);
  if (coords.length < 2) {
    target.innerHTML = `<div class="empty-panel-text">No valid GPS data.</div>`;
    return;
  }

  const map = L.map(target, { zoomControl: true, attributionControl: true });

  // Esri World Imagery (free, no API key, satellite tiles)
  L.tileLayer(
    "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
    {
      maxZoom: 19,
      attribution:
        "Tiles © Esri — Source: Esri, Maxar, Earthstar Geographics, and the GIS User Community",
    }
  ).addTo(map);

  const line = L.polyline(coords, {
    color: s.color || "#a78bfa",
    weight: 3,
    opacity: 0.95,
  }).addTo(map);

  // Start marker (green) + end marker (red)
  const start = coords[0];
  const end = coords[coords.length - 1];
  const dot = (color) => L.divIcon({
    className: "",
    iconSize: [14, 14],
    iconAnchor: [7, 7],
    html: `<div style="width:12px;height:12px;border-radius:50%;background:${color};border:2px solid #fff;box-shadow:0 0 8px ${color};"></div>`,
  });
  L.marker(start, { icon: dot("#4ade80"), title: "Start" }).addTo(map).bindPopup("Start");
  L.marker(end,   { icon: dot("#f87171"), title: "End"   }).addTo(map).bindPopup("End");

  const fitToData = () => map.fitBounds(line.getBounds(), { padding: [24, 24] });
  fitToData();

  // "Center on data" button, bottom-right.
  const RecenterControl = L.Control.extend({
    options: { position: "bottomright" },
    onAdd: function () {
      const btn = L.DomUtil.create("button", "map-recenter-btn");
      btn.type = "button";
      btn.title = "Center on flight data";
      btn.innerHTML =
        `<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" ` +
        `stroke-width="2" stroke-linecap="round" stroke-linejoin="round">` +
        `<circle cx="12" cy="12" r="3"/>` +
        `<path d="M12 2v3M12 19v3M2 12h3M19 12h3"/></svg>`;
      L.DomEvent.disableClickPropagation(btn);
      L.DomEvent.on(btn, "click", (e) => { L.DomEvent.stop(e); fitToData(); });
      return btn;
    },
  });
  map.addControl(new RecenterControl());

  // Leaflet requires invalidateSize() once its container becomes visible/sized.
  requestAnimationFrame(() => map.invalidateSize());
}

let _lastPanelsData = null;

async function renderPanels() {
  els.grid.innerHTML = "";
  els.welcome.hidden = true;
  els.loading.hidden = false;
  setStatus("Requesting plot data…");

  let res;
  try {
    res = await eel.get_default_plot_data()();
  } catch (e) {
    els.loading.hidden = true;
    els.welcome.hidden = false;
    toast("Backend error: " + e.message, "error");
    return;
  }

  if (!res || !res.ok) {
    els.loading.hidden = true;
    els.welcome.hidden = false;
    setStatus(res && res.error ? res.error : "No file loaded.");
    return;
  }

  _lastPanelsData = res;
  await renderPanelsFromData(res);
}

async function renderPanelsFromData(res) {
  els.grid.innerHTML = "";
  els.welcome.hidden = true;
  els.fileStats.textContent = `${res.n_panels} panels`;
  setStatus(`Rendering ${res.n_panels} panels…`);
  els.loading.hidden = true;
  els.grid.hidden = false;

  // File-info header card (shown above panel 01).
  try {
    const info = await eel.get_file_info()();
    if (info && info.ok) {
      els.grid.appendChild(buildInfoCard(info));
    }
  } catch (_) { /* non-fatal */ }

  for (let i = 0; i < res.panels.length; i++) {
    const p = res.panels[i];
    const { section, plotDiv } = buildPanelDOM(i, p);
    els.grid.appendChild(section);
    await new Promise(resolve => requestAnimationFrame(resolve));
    try {
      if (p.type === "map") {
        renderMap(plotDiv, p);
      } else if (p.type === "scatter_xy") {
        renderScatterXY(plotDiv, p);
      } else {
        renderTimePanel(plotDiv, p);
      }
    } catch (e) {
      plotDiv.innerHTML = `<div class="empty-panel-text">Could not render: ${e.message}</div>`;
    }
  }
  setStatus(`Done · ${res.n_panels} panels rendered`);
}

function showWelcome(msg) {
  els.grid.hidden = true;
  els.grid.innerHTML = "";
  els.loading.hidden = true;
  els.welcome.hidden = false;
  if (msg) setStatus(msg);
}

// ----- File loading (upload) -----
async function uploadAndLoad(file) {
  if (!file.name.toLowerCase().endsWith(".ulg")) {
    toast("Only .ulg files are supported.", "error");
    return;
  }
  setStatus(`Uploading ${file.name}…`);
  const res = await uploadUlgFile(file, (pct, loaded, total) => {
    if (loaded != null && total != null) {
      setStatus(`Uploading ${file.name} — ${formatBytes(loaded)} / ${formatBytes(total)}`);
    } else {
      setStatus("Parsing ULG…");
    }
  });
  if (!res || !res.ok) {
    toast(res && res.error ? res.error : "Failed to load file.", "error");
    setStatus("Load failed.");
    return;
  }
  els.fileName.textContent = res.file_name;
  els.fileChip.classList.remove("empty");
  toast(`Loaded ${res.file_name}`, "success");
  await renderPanels();
}

els.browseBtn.addEventListener("click", async () => {
  const file = await pickUlgFile();
  if (!file) return;
  await uploadAndLoad(file);
});

els.customBtn.addEventListener("click", () => {
  window.location.href = "index.html";
});

// ----- Drag & drop (uploads the dropped file) -----
setupDragAndDrop({
  dropOverlay: els.dropOverlay,
  onFile: async (file) => { await uploadAndLoad(file); },
});

function setupDragAndDrop({ dropOverlay, onFile }) {
  let dragDepth = 0;
  const isFileDrag = (e) =>
    e.dataTransfer && Array.from(e.dataTransfer.types || []).includes("Files");

  window.addEventListener("dragenter", (e) => {
    if (!isFileDrag(e)) return;
    e.preventDefault();
    dragDepth++;
    if (dragDepth === 1) {
      dropOverlay.hidden = false;
      document.body.classList.add("drag-active");
    }
  });
  window.addEventListener("dragover", (e) => {
    if (!isFileDrag(e)) return;
    e.preventDefault();
    e.dataTransfer.dropEffect = "copy";
  });
  window.addEventListener("dragleave", (e) => {
    if (!isFileDrag(e)) return;
    dragDepth = Math.max(0, dragDepth - 1);
    if (dragDepth === 0) {
      dropOverlay.hidden = true;
      document.body.classList.remove("drag-active");
    }
  });
  window.addEventListener("drop", (e) => {
    if (!isFileDrag(e)) return;
    e.preventDefault();
    dragDepth = 0;
    dropOverlay.hidden = true;
    document.body.classList.remove("drag-active");
    const files = e.dataTransfer.files;
    if (files && files.length > 0) {
      onFile(files[0]);
    }
  });
}

// ----- Theme toggle -----
function applyTheme(theme) {
  document.documentElement.setAttribute("data-theme", theme);
  localStorage.setItem("pawa-ulg-theme", theme);
}
function currentTheme() {
  return document.documentElement.getAttribute("data-theme") || "dark";
}
applyTheme(localStorage.getItem("pawa-ulg-theme") || "dark");

function applyThemeToPlots() {
  const t = plotTheme();
  document.querySelectorAll(".review-plot").forEach(div => {
    if (!div._fullLayout) return;
    const update = {
      "paper_bgcolor":          "rgba(0,0,0,0)",
      "plot_bgcolor":           "rgba(0,0,0,0)",
      "font.color":             t.text,
      "legend.bgcolor":         t.legendBg,
      "legend.bordercolor":     t.legendBord,
      "hoverlabel.bgcolor":     t.hoverBg,
      "hoverlabel.bordercolor": t.hoverBord,
      "hoverlabel.font.color":  t.text,
    };
    Object.keys(div._fullLayout).forEach(k => {
      if (/^[xy]axis\d*$/.test(k)) {
        update[`${k}.gridcolor`]     = t.grid;
        update[`${k}.zerolinecolor`] = t.zero;
        update[`${k}.linecolor`]     = t.axis;
        update[`${k}.tickcolor`]     = t.tick;
        update[`${k}.tickfont.color`]= t.text;
        const ax = div._fullLayout[k];
        if (ax && ax.title && (ax.title.text || (ax.title._templateindex == null && ax.title.font))) {
          update[`${k}.title.font.color`] = t.textDim;
        }
      }
    });
    try { Plotly.relayout(div, update); } catch (_) {}
  });
}

document.getElementById("themeToggle").addEventListener("click", () => {
  const next = currentTheme() === "dark" ? "light" : "dark";
  applyTheme(next);
  // Update existing plots in place (no DOM teardown, no scroll jump).
  applyThemeToPlots();
});

// ----- Init -----
(async function init() {
  const state = await eel.get_current_state()();
  if (state && state.loaded) {
    els.fileName.textContent = state.file_name;
    els.fileChip.classList.remove("empty");
    await renderPanels();
  } else {
    showWelcome("Ready. Click 'Browse ULG File' to begin.");
  }
})();
