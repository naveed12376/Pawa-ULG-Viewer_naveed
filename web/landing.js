// Landing page — drag-drop or browse a ULG file, then go to Flight Review.

// Respect the saved theme (no toggle shown here).
document.documentElement.setAttribute(
  "data-theme", localStorage.getItem("pawa-ulg-theme") || "dark"
);

const dropZone = document.getElementById("dropZone");
const statusEl = document.getElementById("landingStatus");
const progressEl = document.getElementById("landingProgress");
const progressBar = document.getElementById("landingProgressBar");

function setStatus(msg, kind = "") {
  statusEl.textContent = msg || "";
  statusEl.className = "landing-status" + (kind ? " " + kind : "");
}

function setProgress(pct) {
  if (pct == null) {
    progressEl.hidden = true;
    progressBar.style.width = "0%";
  } else {
    progressEl.hidden = false;
    progressBar.style.width = pct.toFixed(1) + "%";
  }
}

// Upload a File to the server, then navigate to the Flight Review.
async function loadAndGo(file) {
  if (!file.name.toLowerCase().endsWith(".ulg")) {
    setStatus("Only .ulg files are supported.", "error");
    return;
  }
  setStatus(`Uploading ${file.name}…`);
  setProgress(0);
  const res = await uploadUlgFile(file, (pct, loaded, total) => {
    setProgress(pct);
    if (loaded != null && total != null) {
      setStatus(`Uploading ${file.name} — ${formatBytes(loaded)} / ${formatBytes(total)}`);
    } else {
      setStatus("Parsing ULG…");
    }
  });
  setProgress(null);
  if (!res || !res.ok) {
    setStatus(res && res.error ? res.error : "Failed to load file.", "error");
    return;
  }
  setStatus(`Loaded ${res.file_name}`, "success");
  window.location.href = "default.html";
}

// ----- Browse (file picker) -----
async function browse() {
  const file = await pickUlgFile();
  if (!file) { setStatus(""); return; }
  await loadAndGo(file);
}
dropZone.addEventListener("click", browse);
dropZone.addEventListener("keydown", (e) => {
  if (e.key === "Enter" || e.key === " ") { e.preventDefault(); browse(); }
});

// ----- Drag & drop -----
let dragDepth = 0;
const isFileDrag = (e) =>
  e.dataTransfer && Array.from(e.dataTransfer.types || []).includes("Files");

window.addEventListener("dragenter", (e) => {
  if (!isFileDrag(e)) return;
  e.preventDefault();
  dragDepth++;
  dropZone.classList.add("drag-over");
});
window.addEventListener("dragover", (e) => {
  if (!isFileDrag(e)) return;
  e.preventDefault();
  e.dataTransfer.dropEffect = "copy";
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
