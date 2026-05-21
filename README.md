# Pawa ULG Viewer — Static (client-side) build

This folder is a **fully static** version of the Pawa ULG Viewer. There is no
Python, no Flask, no server — every `.ulg` file is parsed and plotted entirely
in the browser. It is self-contained and independent of `main.py` and `web/`.

## Files

| File | Role |
|------|------|
| `index.html` | Landing page (drag-drop / browse a `.ulg`) — **entry point** |
| `review.html` | PX4 Flight Review (the standard plot set + map + info card) |
| `inspector.html` | Custom inspector (pick topics/fields, favorites) |
| `ulog-parser.js` | Pure-JS parser for the binary ULog format (replaces `pyulog`) |
| `analysis.js` | All analysis/plot-building logic (ported from `main.py`) |
| `store.js` | IndexedDB persistence + shared UI helpers (theme, drag-drop) |
| `landing.js` / `review.js` / `inspector.js` | Per-page controllers |
| `style.css` / `review.css` | Styling |

External libraries (Plotly, Leaflet, Google Fonts) load from public CDNs.

## How the data flows (no server)

1. You pick or drop a `.ulg`. The browser reads its bytes (`File.arrayBuffer()`).
2. `ulog-parser.js` parses it into topics/fields in memory.
3. The raw bytes are cached in **IndexedDB** so the file survives navigation
   between the three pages. Nothing is ever uploaded anywhere.
4. Each page re-parses from IndexedDB on load and renders with Plotly/Leaflet.

Favorites and the day/night theme are stored per-user in `localStorage`.

## Run locally

Browsers restrict IndexedDB on `file://`, so serve the folder over HTTP:

```bash
cd static
python -m http.server 8080
# open http://localhost:8080/
```

## Deploy to GitHub Pages

1. Commit this `static/` folder (or its contents) to your repo.
2. In **Settings → Pages**, choose the branch and set the folder to `/static`
   (or move these files to the repo root / a `docs/` folder and point Pages there).
3. GitHub serves `index.html` as the entry page. Done — it's live.

Because everything runs client-side, GitHub Pages (which only serves static
files) is enough; no backend hosting is required.

### What works on a static deployment
- Parsing any PX4 `.ulg` in the browser (verified against `pyulog`).
- The full Flight Review: 26 standard panels, GPS satellite map, info card.
- The custom inspector: topic/field tree, search, plot selected / plot all.
- Favorites and theme persisted per-user; file persisted across pages.

### Limitations vs. the Flask build
- Very large logs are parsed on the client, so they use the visitor's RAM/CPU
  (a few-MB log parses in well under a second; hundreds of MB will be slower).
- The satellite map and chart libraries are loaded from CDNs, so the map tiles
  and plots need an internet connection (the parser itself works offline).
