// api.js — HTTP API layer for the Flask backend (replaces eel).
//
// Provides an `eel`-compatible shim so existing call sites that use
// `await eel.fn(args)()` keep working, plus helpers for file picking and
// uploading (since browsers can't hand the server a local file path).

async function _apiGet(url) {
  const r = await fetch(url, { credentials: "same-origin" });
  return r.json();
}

async function _apiPost(url, body) {
  const r = await fetch(url, {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body || {}),
  });
  return r.json();
}

// eel shim: each call returns a thunk that, when invoked, returns a Promise —
// matching eel's `eel.fn(args)()` calling convention used throughout the app.
window.eel = {
  get_current_state:     ()           => () => _apiGet("/api/state"),
  get_series:            (selections) => () => _apiPost("/api/series", { selections }),
  get_all_topics_data:   ()           => () => _apiGet("/api/all_topics"),
  get_default_plot_data: ()           => () => _apiGet("/api/default_plots"),
  get_file_info:         ()           => () => _apiGet("/api/file_info"),
  close_file:            ()           => () => _apiPost("/api/close", {}),
};

// Open a native file picker and resolve with the chosen File (or null).
function pickUlgFile() {
  return new Promise((resolve) => {
    const input = document.createElement("input");
    input.type = "file";
    input.accept = ".ulg";
    input.style.position = "fixed";
    input.style.left = "-9999px";
    document.body.appendChild(input);

    let settled = false;
    const finish = (val) => {
      if (settled) return;
      settled = true;
      if (input.parentNode) input.parentNode.removeChild(input);
      resolve(val);
    };

    input.addEventListener("change", () => {
      finish(input.files && input.files[0] ? input.files[0] : null);
    });
    // Fallback if the dialog is cancelled (no change event fires).
    window.addEventListener("focus", function onFocus() {
      window.removeEventListener("focus", onFocus);
      setTimeout(() => finish(null), 400);
    });

    input.click();
  });
}

// Upload a File to the backend; resolves with the load summary
// {ok, file_name, topics, n_topics, n_fields} (same shape the old load_file gave).
// onProgress(pctNumber, loadedBytes, totalBytes) is optional.
function uploadUlgFile(file, onProgress) {
  return new Promise((resolve) => {
    const form = new FormData();
    form.append("file", file, file.name);

    const xhr = new XMLHttpRequest();
    if (onProgress) {
      xhr.upload.onprogress = (e) => {
        if (e.lengthComputable) onProgress((e.loaded / e.total) * 100, e.loaded, e.total);
      };
      xhr.upload.onload = () => onProgress(100);
    }
    xhr.onload = () => {
      try { resolve(JSON.parse(xhr.responseText)); }
      catch (_) { resolve({ ok: false, error: "Bad server response." }); }
    };
    xhr.onerror = () => resolve({ ok: false, error: "Network error during upload." });
    xhr.open("POST", "/api/upload");
    xhr.withCredentials = true;
    xhr.send(form);
  });
}

function formatBytes(n) {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  if (n < 1024 * 1024 * 1024) return `${(n / 1024 / 1024).toFixed(1)} MB`;
  return `${(n / 1024 / 1024 / 1024).toFixed(2)} GB`;
}
