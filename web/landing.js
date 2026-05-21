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

function formatBytes(n) {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  if (n < 1024 * 1024 * 1024) return `${(n / 1024 / 1024).toFixed(1)} MB`;
  return `${(n / 1024 / 1024 / 1024).toFixed(2)} GB`;
}

// Upload a dropped File via a single binary multipart POST (no base64, no
// chunking). The browser streams the raw bytes; the server writes them straight
// to a temp file and parses it. This is the fast path for files outside data/.
function uploadFile(file) {
  return new Promise((resolve) => {
    setStatus(`Uploading ${file.name}…`);
    setProgress(0);

    const form = new FormData();
    form.append("file", file, file.name);

    const xhr = new XMLHttpRequest();
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable) {
        const pct = (e.loaded / e.total) * 100;
        setProgress(pct);
        setStatus(`Uploading ${file.name} — ${formatBytes(e.loaded)} / ${formatBytes(e.total)}`);
      }
    };
    xhr.upload.onload = () => {
      // Upload finished; server is now parsing the log.
      setProgress(100);
      setStatus("Parsing ULG…");
    };
    xhr.onload = () => {
      setProgress(null);
      if (xhr.status >= 200 && xhr.status < 300) {
        try { resolve(JSON.parse(xhr.responseText)); }
        catch (_) { resolve({ ok: false, error: "Bad server response." }); }
      } else {
        resolve({ ok: false, error: `Upload failed (HTTP ${xhr.status}).` });
      }
    };
    xhr.onerror = () => {
      setProgress(null);
      resolve({ ok: false, error: "Network error during upload." });
    };
    xhr.open("POST", "/upload_ulg");
    xhr.send(form);
  });
}

async function goToReviewAfterLoad(loadResultPromise) {
  setStatus("Loading…");
  const res = await loadResultPromise;
  if (!res || !res.ok) {
    setStatus(res && res.error ? res.error : "Failed to load file.", "error");
    return;
  }
  setStatus(`Loaded ${res.file_name}`, "success");
  window.location.href = "default.html";
}

// ----- Browse (native dialog) -----
async function browse() {
  setStatus("Opening file dialog…");
  const path = await eel.browse_file()();
  if (!path) { setStatus(""); return; }
  await goToReviewAfterLoad(eel.load_file(path)());
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
  const file = files[0];
  if (!file.name.toLowerCase().endsWith(".ulg")) {
    setStatus("Only .ulg files are supported.", "error");
    return;
  }

  // Fast path: if the file already exists in the data/ folder, load it directly.
  setStatus(`Locating ${file.name}…`);
  const resolved = await eel.resolve_dropped_file(file.name)();
  if (resolved.ok) {
    await goToReviewAfterLoad(eel.load_file(resolved.path)());
    return;
  }

  // Otherwise upload the file's bytes (works for files anywhere on the PC).
  const fin = await uploadFile(file);
  if (!fin) return;
  if (!fin.ok) {
    setStatus(fin.error || "Failed to load file.", "error");
    return;
  }
  setStatus(`Loaded ${fin.file_name}`, "success");
  window.location.href = "default.html";
});
