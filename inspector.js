// Custom inspector page — pick topics/fields and plot them. All data comes from
// a ULog parsed in-browser (no server). Favorites + theme persist per-user in
// this browser's localStorage.

PawaStore.initTheme();

// ========== State ==========
const state = {
  topics: [],            // [{name, fields[], n_samples, duration_s}]
  favorites: [],         // [{topic, field, present?}]
  selectedTopics: new Set(),
  selectedFields: new Set(),
  selectedFavs: new Set(),
  openTopics: new Set(),
  fileLoaded: false,
  filterText: "",
};
let model = null;        // parsed ULog model

const PLOT_COLORS = [
  "#a78bfa", "#67e8f9", "#fbbf24", "#4ade80",
  "#f472b6", "#60a5fa", "#fb923c", "#34d399",
  "#c084fc", "#22d3ee", "#facc15", "#f87171",
];

function cssVar(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

function buildPlotTemplate() {
  return {
    layout: {
      paper_bgcolor: "rgba(0,0,0,0)",
      plot_bgcolor: "rgba(0,0,0,0)",
      font: { family: "Inter, sans-serif", size: 12, color: cssVar("--plot-text") },
      margin: { l: 60, r: 30, t: 40, b: 50 },
      xaxis: {
        gridcolor: cssVar("--plot-grid"), zerolinecolor: cssVar("--plot-zero"),
        linecolor: cssVar("--plot-axis"), tickcolor: cssVar("--plot-tick"),
        title: { text: "time [s]", font: { color: cssVar("--plot-text-dim"), size: 11 } },
      },
      yaxis: {
        gridcolor: cssVar("--plot-grid"), zerolinecolor: cssVar("--plot-zero"),
        linecolor: cssVar("--plot-axis"), tickcolor: cssVar("--plot-tick"),
      },
      legend: {
        bgcolor: cssVar("--plot-legend-bg"), bordercolor: cssVar("--plot-legend-border"),
        borderwidth: 1, font: { size: 11 }, orientation: "v",
        x: 1.005, xanchor: "left", y: 0.88, yanchor: "top",
      },
      hovermode: "x unified",
      hoverlabel: { bgcolor: cssVar("--plot-hover-bg"), bordercolor: cssVar("--plot-hover-border"),
                    font: { color: cssVar("--plot-text") } },
    },
    config: {
      responsive: true,
      displaylogo: false,
      modeBarButtonsToRemove: ["lasso2d", "select2d"],
      toImageButtonOptions: { format: "png", scale: 2, filename: "ulg_plot" },
    },
  };
}

// ========== DOM helpers ==========
const $ = (sel) => document.querySelector(sel);
const els = {
  browseBtn:    $("#browseBtn"),
  defaultBtn:   $("#defaultBtn"),
  plotBtn:      $("#plotBtn"),
  plotAllBtn:   $("#plotAllBtn"),
  clearBtn:     $("#clearBtn"),
  searchInput:  $("#searchInput"),
  topicList:    $("#topicList"),
  topicCount:   $("#topicCount"),
  favList:      $("#favList"),
  favCount:     $("#favCount"),
  favRemoveBtn: $("#favRemoveBtn"),
  fileName:     $("#fileName"),
  fileChip:     $("#fileChip"),
  fileStats:    $("#fileStats"),
  statusText:   $("#statusText"),
  plot:         $("#plot"),
  contextMenu:  $("#contextMenu"),
  toast:        $("#toast"),
  dropOverlay:  $("#dropOverlay"),
};

function setStatus(msg) { els.statusText.textContent = msg; }

let toastTimer = null;
function toast(msg, kind = "") {
  els.toast.textContent = msg;
  els.toast.className = "toast " + (kind || "");
  els.toast.hidden = false;
  if (toastTimer) clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { els.toast.hidden = true; }, 2200);
}

function key(topic, field) { return `${topic}||${field}`; }

// ========== File loading ==========
els.browseBtn.addEventListener("click", async () => {
  const file = await PawaStore.pickUlgFile();
  if (!file) return;
  await loadFile(file);
});
els.defaultBtn.addEventListener("click", () => { window.location.href = "review.html"; });

PawaStore.setupDragAndDrop({
  dropOverlay: els.dropOverlay,
  onFile: async (file) => { await loadFile(file); },
});

async function loadFile(file) {
  if (!file.name.toLowerCase().endsWith(".ulg")) {
    toast("Only .ulg files are supported.", "error");
    return;
  }
  setStatus(`Reading ${file.name}…`);
  await new Promise((r) => setTimeout(r, 20));
  const res = await PawaStore.saveFile(file);
  if (!res || !res.ok) {
    toast(res && res.error ? res.error : "Failed to load file.", "error");
    setStatus("Load failed.");
    return;
  }
  model = await PawaStore.loadModel();
  applyLoadedFile(res);
}

function applyLoadedFile(res) {
  state.fileLoaded = true;
  state.topics = res.topics;
  state.selectedTopics.clear();
  state.selectedFields.clear();
  state.selectedFavs.clear();

  els.fileName.textContent = res.file_name;
  els.fileChip.classList.remove("empty");
  els.fileStats.textContent = `${res.n_topics} topics · ${res.n_fields} fields`;
  setStatus(`Loaded ${res.file_name} — ${res.n_topics} topics, ${res.n_fields} numeric fields.`);

  renderTopics();
  refreshFavorites();
  resetPlotEmpty("Pick fields from Favorites or Topics, then click Plot Selected.");
  toast(`Loaded ${res.file_name}`, "success");
}

// ========== Topic rendering ==========
function renderTopics() {
  const q = state.filterText.trim().toLowerCase();
  const container = els.topicList;
  const prevScroll = container.scrollTop;
  container.innerHTML = "";

  if (!state.topics.length) {
    container.innerHTML = `<div class="empty-state">Load a ULG file to see topics.</div>`;
    els.topicCount.textContent = "0";
    return;
  }

  let shownTopicCount = 0;
  for (const t of state.topics) {
    const topicMatches = !q || t.name.toLowerCase().includes(q);
    const matchedFields = topicMatches ? t.fields : t.fields.filter(f => f.toLowerCase().includes(q));
    if (!topicMatches && matchedFields.length === 0) continue;
    shownTopicCount++;

    const isOpen = state.openTopics.has(t.name) || !!q;
    const topicEl = document.createElement("div");
    topicEl.className = "tree-topic" + (isOpen ? " open" : "");

    const header = document.createElement("div");
    header.className = "tree-topic-header";
    if (state.selectedTopics.has(t.name)) header.classList.add("selected");
    header.dataset.topic = t.name;
    header.innerHTML = `
      <span class="tree-caret">▶</span>
      <span class="tree-topic-name">${t.name}</span>
      <span class="tree-topic-meta">${t.n_samples} pts · ${t.duration_s.toFixed(1)}s</span>
    `;
    header.addEventListener("click", (e) => {
      if (e.ctrlKey || e.metaKey || e.shiftKey) {
        toggleTopicSelection(t.name);
      } else {
        if (state.openTopics.has(t.name)) state.openTopics.delete(t.name);
        else state.openTopics.add(t.name);
        topicEl.classList.toggle("open");
      }
    });
    header.addEventListener("dblclick", (e) => {
      e.stopPropagation();
      state.selectedTopics.clear(); state.selectedFields.clear(); state.selectedFavs.clear();
      state.selectedTopics.add(t.name);
      renderTopics();
      doPlot();
    });
    header.addEventListener("contextmenu", (e) => {
      e.preventDefault();
      openContextMenu(e.clientX, e.clientY, [
        { label: "★  Add all fields to Favorites", action: () => addFavorite(t.name, null) },
        { divider: true },
        { label: "▶  Plot all fields", action: () => {
            state.selectedTopics.clear(); state.selectedFields.clear(); state.selectedFavs.clear();
            state.selectedTopics.add(t.name); renderTopics(); doPlot();
        }},
      ]);
    });
    topicEl.appendChild(header);

    const fieldsWrap = document.createElement("div");
    fieldsWrap.className = "tree-fields";
    matchedFields.forEach(f => {
      const fEl = document.createElement("div");
      fEl.className = "tree-field";
      if (state.selectedFields.has(key(t.name, f))) fEl.classList.add("selected");
      fEl.textContent = f;
      fEl.dataset.topic = t.name;
      fEl.dataset.field = f;
      fEl.addEventListener("click", (e) => {
        e.stopPropagation();
        const k = key(t.name, f);
        if (e.ctrlKey || e.metaKey) {
          if (state.selectedFields.has(k)) state.selectedFields.delete(k);
          else state.selectedFields.add(k);
        } else {
          state.selectedFields.clear(); state.selectedTopics.clear(); state.selectedFavs.clear();
          state.selectedFields.add(k);
        }
        renderTopics();
        renderFavorites();
      });
      fEl.addEventListener("dblclick", (e) => {
        e.stopPropagation();
        state.selectedFields.clear(); state.selectedTopics.clear(); state.selectedFavs.clear();
        state.selectedFields.add(key(t.name, f));
        renderTopics(); renderFavorites();
        doPlot();
      });
      fEl.addEventListener("contextmenu", (e) => {
        e.preventDefault();
        const isFav = state.favorites.some(fv => fv.topic === t.name && fv.field === f);
        openContextMenu(e.clientX, e.clientY, [
          isFav
            ? { label: "✕  Remove from Favorites", action: () => removeFavorite(t.name, f), danger: true }
            : { label: "★  Add to Favorites", action: () => addFavorite(t.name, f) },
          { divider: true },
          { label: "▶  Plot", action: () => {
              state.selectedFields.clear(); state.selectedTopics.clear(); state.selectedFavs.clear();
              state.selectedFields.add(key(t.name, f));
              renderTopics(); renderFavorites();
              doPlot();
          }},
        ]);
      });
      fieldsWrap.appendChild(fEl);
    });
    topicEl.appendChild(fieldsWrap);
    container.appendChild(topicEl);
  }
  els.topicCount.textContent = String(shownTopicCount);
  container.scrollTop = prevScroll;
}

function toggleTopicSelection(name) {
  if (state.selectedTopics.has(name)) state.selectedTopics.delete(name);
  else state.selectedTopics.add(name);
  renderTopics();
}

els.searchInput.addEventListener("input", (e) => {
  state.filterText = e.target.value;
  renderTopics();
});

// ========== Favorites (per-user, localStorage) ==========
const FAV_STORAGE_KEY = "pawa-ulg-favorites";

function loadStoredFavorites() {
  try {
    const raw = localStorage.getItem(FAV_STORAGE_KEY);
    if (!raw) return [];
    const arr = JSON.parse(raw);
    if (!Array.isArray(arr)) return [];
    const seen = new Set();
    const out = [];
    for (const e of arr) {
      if (!e || !e.topic || !e.field) continue;
      const k = e.topic + "||" + e.field;
      if (seen.has(k)) continue;
      seen.add(k);
      out.push({ topic: e.topic, field: e.field });
    }
    return out;
  } catch (_) { return []; }
}
function saveStoredFavorites(favs) {
  try {
    localStorage.setItem(FAV_STORAGE_KEY,
      JSON.stringify(favs.map(f => ({ topic: f.topic, field: f.field }))));
  } catch (_) {}
}
function favIsPresent(topic, field) {
  if (!state.fileLoaded) return false;
  const t = state.topics.find(x => x.name === topic);
  return !!(t && t.fields && t.fields.includes(field));
}
function refreshFavorites() {
  const stored = loadStoredFavorites();
  state.favorites = stored.map(f => ({
    topic: f.topic, field: f.field, present: favIsPresent(f.topic, f.field),
  }));
  renderFavorites();
}
function renderFavorites() {
  els.favCount.textContent = String(state.favorites.length);
  els.favList.innerHTML = "";
  if (!state.favorites.length) {
    els.favList.innerHTML = `<div class="empty-state">No favorites yet.<br><span class="dim">Right-click a field to add it.</span></div>`;
    return;
  }
  state.favorites.forEach(fv => {
    const div = document.createElement("div");
    div.className = "fav-item";
    if (!fv.present) div.classList.add("missing");
    if (state.selectedFavs.has(key(fv.topic, fv.field))) div.classList.add("selected");
    div.innerHTML = `
      <span class="fav-topic">${fv.topic}</span>
      <span class="fav-sep">·</span>
      <span class="fav-field">${fv.field}</span>
      ${fv.present ? "" : '<span class="fav-missing-tag">not in file</span>'}
    `;
    div.addEventListener("click", (e) => {
      const k = key(fv.topic, fv.field);
      if (e.ctrlKey || e.metaKey) {
        if (state.selectedFavs.has(k)) state.selectedFavs.delete(k);
        else state.selectedFavs.add(k);
      } else {
        state.selectedFavs.clear(); state.selectedFields.clear(); state.selectedTopics.clear();
        state.selectedFavs.add(k);
      }
      renderFavorites();
      renderTopics();
    });
    div.addEventListener("dblclick", () => {
      state.selectedFavs.clear(); state.selectedFields.clear(); state.selectedTopics.clear();
      state.selectedFavs.add(key(fv.topic, fv.field));
      renderFavorites(); renderTopics();
      doPlot();
    });
    div.addEventListener("contextmenu", (e) => {
      e.preventDefault();
      openContextMenu(e.clientX, e.clientY, [
        { label: "▶  Plot", action: () => {
            state.selectedFavs.clear(); state.selectedFields.clear(); state.selectedTopics.clear();
            state.selectedFavs.add(key(fv.topic, fv.field));
            renderFavorites(); renderTopics();
            doPlot();
        }},
        { divider: true },
        { label: "✕  Remove from Favorites", action: () => removeFavorite(fv.topic, fv.field), danger: true },
      ]);
    });
    els.favList.appendChild(div);
  });
}

function addFavorite(topic, field) {
  const favs = loadStoredFavorites();
  const has = (t, f) => favs.some(x => x.topic === t && x.field === f);
  let added = 0;
  if (field === null) {
    const t = state.topics.find(x => x.name === topic);
    if (t && t.fields) for (const f of t.fields) if (!has(topic, f)) { favs.push({ topic, field: f }); added++; }
  } else {
    if (!has(topic, field)) { favs.push({ topic, field }); added++; }
  }
  if (added > 0) {
    saveStoredFavorites(favs);
    refreshFavorites();
    toast(field === null ? `Added all "${topic}" fields to favorites` : `Added ${topic} · ${field}`, "success");
  } else {
    toast("Already in favorites.");
  }
}
function removeFavorite(topic, field) {
  const favs = loadStoredFavorites().filter(x => !(x.topic === topic && x.field === field));
  saveStoredFavorites(favs);
  state.selectedFavs.delete(key(topic, field));
  refreshFavorites();
  toast("Removed from favorites");
}
els.favRemoveBtn.addEventListener("click", () => {
  if (!state.selectedFavs.size) { toast("Select favorites to remove.", "error"); return; }
  const drop = state.selectedFavs;
  const favs = loadStoredFavorites().filter(x => !drop.has(key(x.topic, x.field)));
  const removed = state.selectedFavs.size;
  saveStoredFavorites(favs);
  state.selectedFavs.clear();
  refreshFavorites();
  toast(`Removed ${removed} favorite(s)`);
});

// ========== Context menu ==========
function openContextMenu(x, y, items) {
  els.contextMenu.innerHTML = "";
  items.forEach(it => {
    if (it.divider) {
      const d = document.createElement("div");
      d.className = "context-menu-divider";
      els.contextMenu.appendChild(d);
      return;
    }
    const div = document.createElement("div");
    div.className = "context-menu-item" + (it.danger ? " danger" : "");
    div.textContent = it.label;
    div.addEventListener("click", () => { els.contextMenu.hidden = true; it.action(); });
    els.contextMenu.appendChild(div);
  });
  els.contextMenu.hidden = false;
  const rect = els.contextMenu.getBoundingClientRect();
  const vw = window.innerWidth, vh = window.innerHeight;
  const cw = rect.width || 200, ch = rect.height || 100;
  els.contextMenu.style.left = `${Math.min(x, vw - cw - 8)}px`;
  els.contextMenu.style.top  = `${Math.min(y, vh - ch - 8)}px`;
}
document.addEventListener("click", () => { els.contextMenu.hidden = true; });
document.addEventListener("contextmenu", (e) => {
  if (!e.target.closest(".tree-topic-header") &&
      !e.target.closest(".tree-field") &&
      !e.target.closest(".fav-item")) {
    els.contextMenu.hidden = true;
  }
});
document.addEventListener("keydown", (e) => {
  if (e.key === "Delete" && state.selectedFavs.size) els.favRemoveBtn.click();
});

// ========== Plotting ==========
els.plotBtn.addEventListener("click", () => doPlot());
els.plotAllBtn.addEventListener("click", () => doPlotAll());
els.clearBtn.addEventListener("click", () => {
  resetPlotEmpty("Plot cleared.");
  setStatus("Plot cleared.");
});

function gatherSelections() {
  const selections = [];
  for (const t of state.selectedTopics) selections.push({ topic: t, field: null });
  for (const k of state.selectedFields) { const [topic, field] = k.split("||"); selections.push({ topic, field }); }
  for (const k of state.selectedFavs) { const [topic, field] = k.split("||"); selections.push({ topic, field }); }
  return selections;
}

function doPlot() {
  if (!state.fileLoaded) { toast("Load a ULG file first.", "error"); return; }
  const sel = gatherSelections();
  if (!sel.length) { toast("Nothing selected.", "error"); return; }

  setStatus("Plotting...");
  const res = PawaAnalysis.getSeries(model, sel);
  if (!res.ok) { toast(res.error || "Failed to get data.", "error"); return; }
  if (!res.groups.length) { toast("No plottable data in selection.", "error"); return; }

  renderPlot(res.groups);
  setStatus(`Plotted ${res.groups.length} topic(s).`);
}

function doPlotAll() {
  if (!state.fileLoaded) { toast("Load a ULG file first.", "error"); return; }
  if (!confirm(`Plot every topic? (${state.topics.length} subplots — may be slow.)`)) return;

  setStatus("Plotting all topics...");
  const res = PawaAnalysis.getAllTopics(model);
  if (!res.ok) { toast(res.error || "Failed.", "error"); return; }
  renderPlot(res.groups);
  setStatus(`Plotted overview of ${res.groups.length} topics.`);
}

let _lastPlotGroups = null;

function renderPlot(groups) {
  _lastPlotGroups = groups;
  els.plot.innerHTML = "";

  const traces = [];
  const annotations = [];
  const n = groups.length;
  const subplotHeight = 220;
  const gap = 60;
  const avail = (els.plot.clientHeight && els.plot.clientHeight > 200) ? els.plot.clientHeight - 6 : 600;
  const computed = n * subplotHeight + (n - 1) * gap + 80;
  const totalHeight = Math.max(avail, computed);

  const yAxisLayout = {};
  let colorIdx = 0;
  const yDomainStep = 1 / n;
  for (let i = 0; i < n; i++) {
    const g = groups[i];
    const yAxisName = i === 0 ? "yaxis" : `yaxis${i + 1}`;
    const domainTop = 1 - i * yDomainStep;
    const padding = 0.045;
    const domain = [
      Math.max(0, 1 - (i + 1) * yDomainStep + padding * (i === n - 1 ? 0 : 1)),
      Math.min(1, domainTop - (i === 0 ? 0 : padding))
    ];
    yAxisLayout[yAxisName] = {
      domain,
      gridcolor: cssVar("--plot-grid"), zerolinecolor: cssVar("--plot-zero"),
      linecolor: cssVar("--plot-axis"), tickcolor: cssVar("--plot-tick"),
      automargin: true,
    };
    annotations.push({
      text: `<b>${g.topic}</b>`,
      xref: "paper", yref: "paper",
      x: 0, y: domain[1], xanchor: "left", yanchor: "bottom",
      showarrow: false, font: { color: cssVar("--accent-2"), size: 12 },
    });
    for (const s of g.series) {
      traces.push({
        x: s.t, y: s.y,
        name: `${g.topic}.${s.field}`,
        legendgroup: g.topic,
        type: "scattergl", mode: "lines",
        line: { color: PLOT_COLORS[colorIdx % PLOT_COLORS.length], width: 1.4 },
        hovertemplate: `<b>${s.field}</b><br>t=%{x:.3f}s<br>val=%{y}<extra></extra>`,
        yaxis: i === 0 ? "y" : `y${i + 1}`,
      });
      colorIdx++;
    }
  }

  const tmpl = buildPlotTemplate();
  const layout = JSON.parse(JSON.stringify(tmpl.layout));
  Object.assign(layout, yAxisLayout);
  layout.height = totalHeight;
  layout.showlegend = true;
  layout.annotations = annotations;
  layout.xaxis.domain = [0, 1];
  layout.xaxis.title = { text: "time [s]", font: { color: cssVar("--plot-text-dim"), size: 11 } };

  Plotly.newPlot(els.plot, traces, layout, tmpl.config);
}

function resetPlotEmpty(message) {
  try { Plotly.purge(els.plot); } catch (_) {}
  els.plot.innerHTML = `
    <div class="plot-empty">
      <div class="plot-empty-icon">
        <svg viewBox="0 0 24 24" width="64" height="64" fill="none" stroke="currentColor" stroke-width="1.2" stroke-linecap="round" stroke-linejoin="round">
          <path d="M3 3v18h18"/>
          <path d="M7 16l3-6 4 4 6-10"/>
        </svg>
      </div>
      <h2>${message ? message.split(".")[0] : "No data yet"}</h2>
      <p>${message || "Load a ULG file, then pick fields from Favorites or Topics."}</p>
    </div>`;
}

// ========== Theme toggle ==========
function applyThemeToPlots() {
  const div = els.plot;
  if (!div || !div._fullLayout) return;
  const text = cssVar("--plot-text"), textDim = cssVar("--plot-text-dim");
  const update = {
    "paper_bgcolor": "rgba(0,0,0,0)", "plot_bgcolor": "rgba(0,0,0,0)",
    "font.color": text,
    "legend.bgcolor": cssVar("--plot-legend-bg"), "legend.bordercolor": cssVar("--plot-legend-border"),
    "hoverlabel.bgcolor": cssVar("--plot-hover-bg"), "hoverlabel.bordercolor": cssVar("--plot-hover-border"),
    "hoverlabel.font.color": text,
  };
  Object.keys(div._fullLayout).forEach(k => {
    if (/^[xy]axis\d*$/.test(k)) {
      update[`${k}.gridcolor`] = cssVar("--plot-grid");
      update[`${k}.zerolinecolor`] = cssVar("--plot-zero");
      update[`${k}.linecolor`] = cssVar("--plot-axis");
      update[`${k}.tickcolor`] = cssVar("--plot-tick");
      update[`${k}.tickfont.color`] = text;
      const ax = div._fullLayout[k];
      if (ax && ax.title && ax.title.text) update[`${k}.title.font.color`] = textDim;
    }
  });
  if (Array.isArray(div._fullLayout.annotations)) {
    div._fullLayout.annotations.forEach((_, i) => { update[`annotations[${i}].font.color`] = cssVar("--accent-2"); });
  }
  try { Plotly.relayout(div, update); } catch (_) {}
}
PawaStore.wireThemeToggle(applyThemeToPlots);

// Keep the plot filling the available height when the window is resized.
let _resizeTimer = null;
window.addEventListener("resize", () => {
  if (!_lastPlotGroups || !els.plot._fullLayout) return;
  clearTimeout(_resizeTimer);
  _resizeTimer = setTimeout(() => {
    const n = _lastPlotGroups.length;
    const avail = (els.plot.clientHeight && els.plot.clientHeight > 200) ? els.plot.clientHeight - 6 : 600;
    const computed = n * 220 + (n - 1) * 60 + 80;
    Plotly.relayout(els.plot, { height: Math.max(avail, computed) });
  }, 150);
});

// ========== Boot ==========
(async function init() {
  model = await PawaStore.loadModel();
  if (model) {
    const summary = PawaAnalysis.topicsSummary(model);
    state.fileLoaded = true;
    state.topics = summary.topics;
    els.fileName.textContent = summary.file_name;
    els.fileChip.classList.remove("empty");
    els.fileStats.textContent = `${summary.n_topics} topics · ${summary.n_fields} fields`;
    setStatus(`Loaded ${summary.file_name} — ${summary.n_topics} topics, ${summary.n_fields} numeric fields.`);
    renderTopics();
    refreshFavorites();
    resetPlotEmpty("Pick fields from Favorites or Topics, then click Plot Selected.");
  } else {
    refreshFavorites();
    renderTopics();
    setStatus("Ready. Click 'Browse ULG File' to begin.");
  }
})();
