// Flight Review (Default plots) page logic

const els = {
  fileName:   document.getElementById("fileName"),
  fileStats:  document.getElementById("fileStats"),
  statusText: document.getElementById("statusText"),
  grid:       document.getElementById("panelGrid"),
  loading:    document.getElementById("loadingOverlay"),
  error:      document.getElementById("errorOverlay"),
  printBtn:   document.getElementById("printBtn"),
};

els.printBtn.addEventListener("click", () => window.print());

const PLOTLY_CONFIG = {
  responsive: true,
  displaylogo: false,
  modeBarButtonsToRemove: ["lasso2d", "select2d"],
  toImageButtonOptions: { format: "png", scale: 2 },
};

function baseLayout(extra = {}) {
  return Object.assign({
    paper_bgcolor: "rgba(0,0,0,0)",
    plot_bgcolor: "rgba(0,0,0,0)",
    font: { family: "Inter, sans-serif", size: 11, color: "#e7ecff" },
    margin: { l: 60, r: 24, t: 10, b: 40 },
    xaxis: {
      gridcolor: "rgba(255,255,255,0.06)",
      zerolinecolor: "rgba(255,255,255,0.12)",
      linecolor: "rgba(255,255,255,0.15)",
      tickcolor: "rgba(255,255,255,0.3)",
      title: { text: "time [s]", font: { color: "#9aa3c7", size: 10 } },
    },
    yaxis: {
      gridcolor: "rgba(255,255,255,0.06)",
      zerolinecolor: "rgba(255,255,255,0.12)",
      linecolor: "rgba(255,255,255,0.15)",
      tickcolor: "rgba(255,255,255,0.3)",
    },
    legend: {
      bgcolor: "rgba(22,26,43,0.55)",
      bordercolor: "rgba(255,255,255,0.1)",
      borderwidth: 1,
      font: { size: 10 },
      orientation: "v",
      x: 1.005, y: 1, xanchor: "left",
    },
    hovermode: "x unified",
    hoverlabel: { bgcolor: "#161a2b", bordercolor: "rgba(167, 139, 250, 0.6)", font: { color: "#e7ecff" } },
  }, extra);
}

function renderTimePanel(target, panel) {
  const traces = panel.series.map(s => ({
    x: s.t,
    y: s.y,
    name: s.name,
    type: "scattergl",
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
  const traces = panel.series.map(s => ({
    x: s.x, y: s.y,
    name: s.name,
    type: "scattergl",
    mode: "lines+markers",
    line: { color: s.color || "#a78bfa", width: 1.5 },
    marker: { size: 3, color: s.color || "#a78bfa" },
  }));
  const layout = baseLayout({
    xaxis: Object.assign({}, baseLayout().xaxis, {
      title: { text: panel.xlabel || "", font: { color: "#9aa3c7", size: 10 } },
      scaleanchor: "y", scaleratio: 1,
    }),
    yaxis: Object.assign({}, baseLayout().yaxis, {
      title: { text: panel.ylabel || "", font: { color: "#9aa3c7", size: 10 } }
    }),
    showlegend: false,
  });
  Plotly.newPlot(target, traces, layout, PLOTLY_CONFIG);
}

function buildPanel(idx, panel) {
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
  plotDiv.className = "review-plot" + (panel.type === "scatter_xy" ? " tall" : "");
  body.appendChild(plotDiv);
  section.appendChild(body);

  return { section, plotDiv };
}

async function init() {
  els.statusText.textContent = "Requesting plot data…";
  let res;
  try {
    res = await eel.get_default_plot_data()();
  } catch (e) {
    showError("Could not communicate with the backend.");
    return;
  }

  if (!res || !res.ok) {
    showError(res && res.error ? res.error : "No file loaded.");
    return;
  }

  els.fileName.textContent = res.file_name || "(no name)";
  els.fileStats.textContent = `${res.n_panels} panels`;
  els.statusText.textContent = `Rendering ${res.n_panels} panels…`;

  els.loading.hidden = true;
  els.grid.hidden = false;

  // Render panels sequentially with a tiny delay so each shows up progressively
  for (let i = 0; i < res.panels.length; i++) {
    const p = res.panels[i];
    const { section, plotDiv } = buildPanel(i, p);
    els.grid.appendChild(section);
    // Use requestAnimationFrame to let the DOM paint between panels
    await new Promise(resolve => requestAnimationFrame(resolve));
    try {
      if (p.type === "scatter_xy") {
        renderScatterXY(plotDiv, p);
      } else {
        renderTimePanel(plotDiv, p);
      }
    } catch (e) {
      plotDiv.innerHTML = `<div class="empty-panel-text">Could not render: ${e.message}</div>`;
    }
  }
  els.statusText.textContent = `Done · ${res.n_panels} panels rendered`;
}

function showError(msg) {
  els.loading.hidden = true;
  els.error.hidden = false;
  els.error.querySelector("p").innerHTML =
    msg + "<br>Open the main window, load a ULG file, then click <strong>Default</strong> again.";
  els.statusText.textContent = "Error";
}

window.addEventListener("DOMContentLoaded", init);
