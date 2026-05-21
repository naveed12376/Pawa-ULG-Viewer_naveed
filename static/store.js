// store.js — client-side state + persistence shared by all pages.
//
// In the old Flask app the parsed ULog lived in a per-session store on the
// server. Here everything is client-side: the raw .ulg bytes are kept in
// IndexedDB so they survive navigation between pages, and each page parses them
// with ULogParser. Nothing ever leaves the browser.
(function (global) {
  "use strict";

  const DB_NAME = "pawa-ulg-viewer";
  const STORE = "files";
  const KEY = "current";

  function openDB() {
    return new Promise((resolve, reject) => {
      const req = indexedDB.open(DB_NAME, 1);
      req.onupgradeneeded = () => req.result.createObjectStore(STORE);
      req.onsuccess = () => resolve(req.result);
      req.onerror = () => reject(req.error);
    });
  }
  async function idbPut(rec) {
    const db = await openDB();
    return new Promise((resolve, reject) => {
      const tx = db.transaction(STORE, "readwrite");
      tx.objectStore(STORE).put(rec, KEY);
      tx.oncomplete = () => resolve();
      tx.onerror = () => reject(tx.error);
    });
  }
  async function idbGet() {
    const db = await openDB();
    return new Promise((resolve, reject) => {
      const tx = db.transaction(STORE, "readonly");
      const rq = tx.objectStore(STORE).get(KEY);
      rq.onsuccess = () => resolve(rq.result || null);
      rq.onerror = () => reject(rq.error);
    });
  }
  async function idbDelete() {
    const db = await openDB();
    return new Promise((resolve, reject) => {
      const tx = db.transaction(STORE, "readwrite");
      tx.objectStore(STORE).delete(KEY);
      tx.oncomplete = () => resolve();
      tx.onerror = () => reject(tx.error);
    });
  }

  // In-page cache so we parse at most once per page load.
  let _cached = null;  // { name, model }

  // Read a File, validate by parsing, persist the bytes, return a load summary.
  async function saveFile(file, onProgress) {
    if (!file.name.toLowerCase().endsWith(".ulg")) {
      return { ok: false, error: "Only .ulg files are supported." };
    }
    if (onProgress) onProgress(40);
    let buffer;
    try {
      buffer = await file.arrayBuffer();
    } catch (e) {
      return { ok: false, error: "Could not read file: " + e.message };
    }
    if (onProgress) onProgress(70);
    let model;
    try {
      model = ULogParser.parse(buffer, file.name);
    } catch (e) {
      return { ok: false, error: "Could not parse ULG: " + e.message };
    }
    try {
      await idbPut({ name: file.name, buffer });
    } catch (e) {
      // Persisting failed (private mode / quota) — still usable on this page.
    }
    if (onProgress) onProgress(100);
    _cached = { name: file.name, model };
    return PawaAnalysis.topicsSummary(model);
  }

  // Return the parsed model for the stored file (or null if none).
  async function loadModel() {
    if (_cached) return _cached.model;
    let rec;
    try { rec = await idbGet(); } catch (_) { rec = null; }
    if (!rec) return null;
    try {
      const model = ULogParser.parse(rec.buffer, rec.name);
      _cached = { name: rec.name, model };
      return model;
    } catch (_) {
      return null;
    }
  }

  async function clear() {
    _cached = null;
    try { await idbDelete(); } catch (_) {}
  }

  // ---------------- shared UI helpers ----------------
  function formatBytes(n) {
    if (n < 1024) return `${n} B`;
    if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
    if (n < 1024 * 1024 * 1024) return `${(n / 1024 / 1024).toFixed(1)} MB`;
    return `${(n / 1024 / 1024 / 1024).toFixed(2)} GB`;
  }

  // Open a native file picker, resolve with the chosen File (or null).
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
      input.addEventListener("change", () => finish(input.files && input.files[0] ? input.files[0] : null));
      window.addEventListener("focus", function onFocus() {
        window.removeEventListener("focus", onFocus);
        setTimeout(() => finish(null), 400);
      });
      input.click();
    });
  }

  // Wire whole-window drag & drop. onFile(file) is called on drop.
  function setupDragAndDrop({ dropOverlay, onFile }) {
    let dragDepth = 0;
    const isFileDrag = (e) => e.dataTransfer && Array.from(e.dataTransfer.types || []).includes("Files");
    window.addEventListener("dragenter", (e) => {
      if (!isFileDrag(e)) return;
      e.preventDefault();
      dragDepth++;
      if (dragDepth === 1 && dropOverlay) { dropOverlay.hidden = false; document.body.classList.add("drag-active"); }
    });
    window.addEventListener("dragover", (e) => {
      if (!isFileDrag(e)) return;
      e.preventDefault();
      e.dataTransfer.dropEffect = "copy";
    });
    window.addEventListener("dragleave", (e) => {
      if (!isFileDrag(e)) return;
      dragDepth = Math.max(0, dragDepth - 1);
      if (dragDepth === 0 && dropOverlay) { dropOverlay.hidden = true; document.body.classList.remove("drag-active"); }
    });
    window.addEventListener("drop", (e) => {
      if (!isFileDrag(e)) return;
      e.preventDefault();
      dragDepth = 0;
      if (dropOverlay) { dropOverlay.hidden = true; document.body.classList.remove("drag-active"); }
      const files = e.dataTransfer.files;
      if (files && files.length > 0) onFile(files[0]);
    });
  }

  // ---------------- theme (per-user, localStorage) ----------------
  const THEME_KEY = "pawa-ulg-theme";
  function applyTheme(theme) {
    document.documentElement.setAttribute("data-theme", theme);
    try { localStorage.setItem(THEME_KEY, theme); } catch (_) {}
  }
  function currentTheme() {
    return document.documentElement.getAttribute("data-theme") || "dark";
  }
  function initTheme() {
    let saved = "dark";
    try { saved = localStorage.getItem(THEME_KEY) || "dark"; } catch (_) {}
    applyTheme(saved);
  }
  // Wire a #themeToggle button; afterToggle() runs after the theme flips.
  function wireThemeToggle(afterToggle) {
    const btn = document.getElementById("themeToggle");
    if (!btn) return;
    btn.addEventListener("click", () => {
      applyTheme(currentTheme() === "dark" ? "light" : "dark");
      if (afterToggle) afterToggle();
    });
  }

  global.PawaStore = {
    saveFile, loadModel, clear,
    formatBytes, pickUlgFile, setupDragAndDrop,
    applyTheme, currentTheme, initTheme, wireThemeToggle,
  };
})(typeof window !== "undefined" ? window : globalThis);
