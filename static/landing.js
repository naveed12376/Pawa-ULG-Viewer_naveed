// Landing page — drag-drop or browse a .ulg file, parse it in-browser, then
// go to the Flight Review. No server: parsing happens here via ULogParser.

PawaStore.initTheme();

const dropZone = document.getElementById("dropZone");
const statusEl = document.getElementById("landingStatus");
const progressEl = document.getElementById("landingProgress");
const progressBar = document.getElementById("landingProgressBar");

function setStatus(msg, kind = "") {
  statusEl.textContent = msg || "";
  statusEl.className = "landing-status" + (kind ? " " + kind : "");
}
function setProgress(pct) {
  if (pct == null) { progressEl.hidden = true; progressBar.style.width = "0%"; }
  else { progressEl.hidden = false; progressBar.style.width = pct.toFixed(1) + "%"; }
}

// Parse + persist the file, then navigate to the Flight Review.
async function loadAndGo(file) {
  if (!file.name.toLowerCase().endsWith(".ulg")) {
    setStatus("Only .ulg files are supported.", "error");
    return;
  }
  setStatus(`Reading ${file.name} (${PawaStore.formatBytes(file.size)})…`);
  setProgress(10);
  // Yield so the UI paints the status before the (synchronous) parse runs.
  await new Promise((r) => setTimeout(r, 20));
  setStatus("Parsing ULG…");
  const res = await PawaStore.saveFile(file, (pct) => setProgress(pct));
  setProgress(null);
  if (!res || !res.ok) {
    setStatus(res && res.error ? res.error : "Failed to load file.", "error");
    return;
  }
  setStatus(`Loaded ${res.file_name} — ${res.n_topics} topics`, "success");
  window.location.href = "review.html";
}

async function browse() {
  const file = await PawaStore.pickUlgFile();
  if (!file) { setStatus(""); return; }
  await loadAndGo(file);
}
dropZone.addEventListener("click", browse);
dropZone.addEventListener("keydown", (e) => {
  if (e.key === "Enter" || e.key === " ") { e.preventDefault(); browse(); }
});

// ----- Drag & drop (highlights the drop zone) -----
let dragDepth = 0;
const isFileDrag = (e) => e.dataTransfer && Array.from(e.dataTransfer.types || []).includes("Files");
window.addEventListener("dragenter", (e) => {
  if (!isFileDrag(e)) return;
  e.preventDefault(); dragDepth++; dropZone.classList.add("drag-over");
});
window.addEventListener("dragover", (e) => {
  if (!isFileDrag(e)) return;
  e.preventDefault(); e.dataTransfer.dropEffect = "copy";
});
window.addEventListener("dragleave", (e) => {
  if (!isFileDrag(e)) return;
  dragDepth = Math.max(0, dragDepth - 1);
  if (dragDepth === 0) dropZone.classList.remove("drag-over");
});
window.addEventListener("drop", async (e) => {
  if (!isFileDrag(e)) return;
  e.preventDefault();
  dragDepth = 0;
  dropZone.classList.remove("drag-over");
  const files = e.dataTransfer.files;
  if (!files || files.length === 0) return;
  await loadAndGo(files[0]);
});
