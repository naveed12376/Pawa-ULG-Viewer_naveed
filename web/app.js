// ========== State ==========
const state = {
  topics: [],            // [{name, fields[], n_samples, duration_s}]
  favorites: [],         // [{topic, field, present?}]
  selectedTopics: new Set(),   // topic names (topic-level selections, plot all fields)
  selectedFields: new Set(),   // "topic||field"
  selectedFavs: new Set(),     // "topic||field"
  fileLoaded: false,
  filterText: "",
};

const PLOT_COLORS = [
  "#a78bfa", "#67e8f9", "#fbbf24", "#4ade80",
  "#f472b6", "#60a5fa", "#fb923c", "#34d399",
  "#c084fc", "#22d3ee", "#facc15", "#f87171",
];

const PLOT_TEMPLATE = {
  layout: {
    paper_bgcolor: "rgba(0,0,0,0)",
    plot_bgcolor: "rgba(0,0,0,0)",
    font: { family: "Inter, sans-serif", size: 12, color: "#e7ecff" },
    margin: { l: 60, r: 30, t: 40, b: 50 },
    xaxis: {
      gridcolor: "rgba(255,255,255,0.06)",
      zerolinecolor: "rgba(255,255,255,0.12)",
      linecolor: "rgba(255,255,255,0.15)",
      tickcolor: "rgba(255,255,255,0.3)",
      title: { text: "time [s]", font: { color: "#9aa3c7", size: 11 } },
    },
    yaxis: {
      gridcolor: "rgba(255,255,255,0.06)",
      zerolinecolor: "rgba(255,255,255,0.12)",
      linecolor: "rgba(255,255,255,0.15)",
      tickcolor: "rgba(255,255,255,0.3)",
    },
    legend: {
      bgcolor: "rgba(22,26,43,0.6)",
      bordercolor: "rgba(255,255,255,0.1)",
      borderwidth: 1,
      font: { size: 11 },
    },
    hovermode: "x unified",
    hoverlabel: { bgcolor: "#161a2b", bordercolor: "rgba(167, 139, 250, 0.6)", font: { color: "#e7ecff" } },
  },
  config: {
    responsive: true,
    displaylogo: false,
    modeBarButtonsToRemove: ["lasso2d", "select2d"],
    toImageButtonOptions: { format: "png", scale: 2, filename: "ulg_plot" },
  },
};

// ========== DOM helpers ==========
const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));

const els = {
  browseBtn:    $("#browseBtn"),
  quickPickBtn: $("#quickPickBtn"),
  quickPickMenu:$("#quickPickMenu"),
  quickPickList:$("#quickPickList"),
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
  setStatus("Opening file dialog...");
  const path = await eel.browse_file()();
  if (!path) { setStatus("File selection cancelled."); return; }
  await loadFile(path);
});

els.quickPickBtn.addEventListener("click", async (e) => {
  e.stopPropagation();
  if (!els.quickPickMenu.hidden) {
    els.quickPickMenu.hidden = true;
    return;
  }
  const files = await eel.list_data_dir()();
  els.quickPickList.innerHTML = "";
  if (!files.length) {
    els.quickPickList.innerHTML = `<div class="empty-state">No .ulg files in data/.</div>`;
  } else {
    files.forEach(f => {
      const div = document.createElement("div");
      div.className = "popover-item";
      div.innerHTML = `<span>${f.name}</span><span class="popover-item-size">${f.size_kb} KB</span>`;
      div.addEventListener("click", () => {
        els.quickPickMenu.hidden = true;
        loadFile(f.path);
      });
      els.quickPickList.appendChild(div);
    });
  }
  els.quickPickMenu.hidden = false;
});

document.addEventListener("click", (e) => {
  if (!els.quickPickMenu.hidden &&
      !els.quickPickMenu.contains(e.target) &&
      e.target !== els.quickPickBtn) {
    els.quickPickMenu.hidden = true;
  }
});

async function loadFile(path) {
  setStatus(`Loading ${path}...`);
  const res = await eel.load_file(path)();
  if (!res.ok) {
    toast(res.error || "Failed to load file.", "error");
    setStatus("Load failed.");
    return;
  }
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
  await refreshFavorites();
  resetPlotEmpty("Pick fields from Favorites or Topics, then click Plot Selected.");
  toast(`Loaded ${res.file_name}`, "success");
}

// ========== Topic rendering ==========
function renderTopics() {
  const q = state.filterText.trim().toLowerCase();
  const container = els.topicList;
  container.innerHTML = "";

  if (!state.topics.length) {
    container.innerHTML = `<div class="empty-state">Load a ULG file to see topics.</div>`;
    els.topicCount.textContent = "0";
    return;
  }

  let shownTopicCount = 0;
  for (const t of state.topics) {
    const topicMatches = !q || t.name.toLowerCase().includes(q);
    const matchedFields = topicMatches
      ? t.fields
      : t.fields.filter(f => f.toLowerCase().includes(q));
    if (!topicMatches && matchedFields.length === 0) continue;

    shownTopicCount++;

    const topicEl = document.createElement("div");
    topicEl.className = "tree-topic" + (q ? " open" : "");

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
        // Treat as selection-toggle (topic-level == all fields)
        toggleTopicSelection(t.name);
      } else {
        topicEl.classList.toggle("open");
      }
    });
    header.addEventListener("dblclick", (e) => {
      e.stopPropagation();
      state.selectedTopics.clear();
      state.selectedFields.clear();
      state.selectedFavs.clear();
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
          state.selectedFields.clear();
          state.selectedTopics.clear();
          state.selectedFavs.clear();
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

// ========== Favorites ==========
async function refreshFavorites() {
  const favs = await eel.check_favorites_in_file()();
  state.favorites = favs;
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
        state.selectedFavs.clear();
        state.selectedFields.clear();
        state.selectedTopics.clear();
        state.selectedFavs.add(k);
      }
      renderFavorites();
      renderTopics();
    });
    div.addEventListener("dblclick", () => {
      state.selectedFavs.clear();
      state.selectedFields.clear();
      state.selectedTopics.clear();
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

async function addFavorite(topic, field) {
  // If field is null -> add all fields of topic
  if (field === null) {
    const entries = [{ topic, field: null }];
    await eel.add_favorites_bulk(entries)();
  } else {
    await eel.add_favorite(topic, field)();
  }
  await refreshFavorites();
  toast(field === null ? `Added all "${topic}" fields to favorites` : `Added ${topic} · ${field}`, "success");
}

async function removeFavorite(topic, field) {
  await eel.remove_favorite(topic, field)();
  state.selectedFavs.delete(key(topic, field));
  await refreshFavorites();
  toast("Removed from favorites");
}

els.favRemoveBtn.addEventListener("click", async () => {
  if (!state.selectedFavs.size) {
    toast("Select favorites to remove.", "error");
    return;
  }
  const entries = Array.from(state.selectedFavs).map(k => {
    const [t, f] = k.split("||");
    return { topic: t, field: f };
  });
  await eel.remove_favorites_bulk(entries)();
  state.selectedFavs.clear();
  await refreshFavorites();
  toast(`Removed ${entries.length} favorite(s)`);
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
    div.addEventListener("click", () => {
      els.contextMenu.hidden = true;
      it.action();
    });
    els.contextMenu.appendChild(div);
  });
  els.contextMenu.hidden = false;

  // Clamp to viewport
  const rect = els.contextMenu.getBoundingClientRect();
  const vw = window.innerWidth, vh = window.innerHeight;
  const cw = rect.width || 200, ch = rect.height || 100;
  const finalX = Math.min(x, vw - cw - 8);
  const finalY = Math.min(y, vh - ch - 8);
  els.contextMenu.style.left = `${finalX}px`;
  els.contextMenu.style.top  = `${finalY}px`;
}

document.addEventListener("click", () => { els.contextMenu.hidden = true; });
document.addEventListener("contextmenu", (e) => {
  if (!e.target.closest(".tree-topic-header") &&
      !e.target.closest(".tree-field") &&
      !e.target.closest(".fav-item")) {
    els.contextMenu.hidden = true;
  }
});

// Delete key removes selected favorites
document.addEventListener("keydown", (e) => {
  if (e.key === "Delete" && state.selectedFavs.size) {
    els.favRemoveBtn.click();
  }
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
  for (const k of state.selectedFields) {
    const [topic, field] = k.split("||");
    selections.push({ topic, field });
  }
  for (const k of state.selectedFavs) {
    const [topic, field] = k.split("||");
    selections.push({ topic, field });
  }
  return selections;
}

async function doPlot() {
  if (!state.fileLoaded) { toast("Load a ULG file first.", "error"); return; }
  const sel = gatherSelections();
  if (!sel.length) { toast("Nothing selected.", "error"); return; }

  setStatus("Plotting...");
  const res = await eel.get_series(sel)();
  if (!res.ok) { toast(res.error || "Failed to get data.", "error"); return; }
  if (!res.groups.length) { toast("No plottable data in selection.", "error"); return; }

  renderPlot(res.groups);
  setStatus(`Plotted ${res.groups.length} topic(s).`);
}

async function doPlotAll() {
  if (!state.fileLoaded) { toast("Load a ULG file first.", "error"); return; }
  if (!confirm(`Plot every topic? (${state.topics.length} subplots — may be slow.)`)) return;

  setStatus("Plotting all topics...");
  const res = await eel.get_all_topics_data()();
  if (!res.ok) { toast(res.error || "Failed.", "error"); return; }
  renderPlot(res.groups);
  setStatus(`Plotted overview of ${res.groups.length} topics.`);
}

function renderPlot(groups) {
  // Clear empty-state
  els.plot.innerHTML = "";

  const traces = [];
  const annotations = [];
  const n = groups.length;
  // One y-axis per group: yaxis, yaxis2, ..., share x-axis. Stack vertically.
  const subplotHeight = 220;
  const gap = 60;
  const totalHeight = Math.max(420, n * subplotHeight + (n - 1) * gap + 80);

  const yAxisLayout = {};
  let colorIdx = 0;
  const yDomainStep = 1 / n;
  for (let i = 0; i < n; i++) {
    const g = groups[i];
    const yAxisName = i === 0 ? "yaxis" : `yaxis${i + 1}`;
    const yRef = i === 0 ? "y" : `y${i + 1}`;
    // Compute vertical domain so most-recent groups are on top
    const domainTop = 1 - i * yDomainStep;
    const padding = 0.045;
    const domain = [
      Math.max(0, 1 - (i + 1) * yDomainStep + padding * (i === n - 1 ? 0 : 1)),
      Math.min(1, domainTop - (i === 0 ? 0 : padding))
    ];
    yAxisLayout[yAxisName] = {
      domain,
      gridcolor: "rgba(255,255,255,0.06)",
      zerolinecolor: "rgba(255,255,255,0.12)",
      linecolor: "rgba(255,255,255,0.15)",
      tickcolor: "rgba(255,255,255,0.3)",
      automargin: true,
    };
    annotations.push({
      text: `<b>${g.topic}</b>`,
      xref: "paper", yref: "paper",
      x: 0, y: domain[1],
      xanchor: "left", yanchor: "bottom",
      showarrow: false,
      font: { color: "#67e8f9", size: 12 },
    });
    for (const s of g.series) {
      traces.push({
        x: s.t,
        y: s.y,
        name: `${g.topic}.${s.field}`,
        legendgroup: g.topic,
        type: "scattergl",
        mode: "lines",
        line: { color: PLOT_COLORS[colorIdx % PLOT_COLORS.length], width: 1.4 },
        hovertemplate: `<b>${s.field}</b><br>t=%{x:.3f}s<br>val=%{y}<extra></extra>`,
        yaxis: i === 0 ? "y" : `y${i + 1}`,
      });
      colorIdx++;
    }
  }

  const layout = JSON.parse(JSON.stringify(PLOT_TEMPLATE.layout));
  Object.assign(layout, yAxisLayout);
  layout.height = totalHeight;
  layout.showlegend = true;
  layout.annotations = annotations;
  layout.xaxis.domain = [0, 1];
  // Use only the bottom axis label
  layout.xaxis.title = { text: "time [s]", font: { color: "#9aa3c7", size: 11 } };

  Plotly.newPlot(els.plot, traces, layout, PLOT_TEMPLATE.config);
}

function resetPlotEmpty(message) {
  // Tear down any plotly instance
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

// ========== Boot ==========
(async function init() {
  // Load favorites even before file is loaded
  const favs = await eel.get_favorites()();
  state.favorites = favs.map(f => ({ ...f, present: false }));
  renderFavorites();
  renderTopics();
  setStatus("Ready. Click 'Browse ULG File' to begin.");
})();
