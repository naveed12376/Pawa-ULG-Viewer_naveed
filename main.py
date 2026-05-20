"""ULG (PX4 ULog) File Viewer — Eel (HTML/CSS/JS) edition.

Python backend that exposes ULog parsing to a web-based frontend.
Favorites are persisted to settings.txt in the workspace.
"""

from __future__ import annotations

import os
import sys
import math
import threading
from typing import Dict, List, Tuple, Optional

import eel

try:
    from pyulog import ULog
except ImportError:
    print("Missing dependency: pyulog. Install it via:  pip install pyulog eel")
    sys.exit(1)


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SETTINGS_FILE = os.path.join(SCRIPT_DIR, "settings.txt")
DATA_DIR = os.path.join(SCRIPT_DIR, "data")
WEB_DIR = os.path.join(SCRIPT_DIR, "web")


# ----------------------------- State ----------------------------- #
class AppState:
    def __init__(self):
        self.ulog: Optional[ULog] = None
        self.current_file: Optional[str] = None
        self.datasets: Dict[str, object] = {}

    def reset(self):
        self.ulog = None
        self.current_file = None
        self.datasets = {}


state = AppState()


# --------------------- Favorites persistence --------------------- #
def _load_favorites() -> List[Tuple[str, str]]:
    favs: List[Tuple[str, str]] = []
    if not os.path.isfile(SETTINGS_FILE):
        return favs
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "|" not in line:
                    continue
                topic, field = line.split("|", 1)
                topic, field = topic.strip(), field.strip()
                if topic and field and (topic, field) not in favs:
                    favs.append((topic, field))
    except Exception as e:
        print(f"Warning: could not read {SETTINGS_FILE}: {e}")
    return favs


def _save_favorites(favs: List[Tuple[str, str]]):
    try:
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            f.write("# ULG Viewer favorites - one per line as: topic|field\n")
            for topic, field in favs:
                f.write(f"{topic}|{field}\n")
    except Exception as e:
        print(f"Failed to save favorites: {e}")


# --------------------- Helpers --------------------- #
def _topic_key(d) -> str:
    return d.name + (f"_{d.multi_id}" if d.multi_id else "")


def _clean_array(arr) -> list:
    """Convert numpy array to JSON-safe list, replacing inf/nan with None."""
    out = []
    for v in arr.tolist():
        if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
            out.append(None)
        else:
            out.append(v)
    return out


def _topic_summary(d) -> dict:
    fields = [f for f in sorted(d.data.keys()) if f != "timestamp"]
    ts = d.data.get("timestamp")
    n_samples = int(len(ts)) if ts is not None else 0
    duration = float((ts[-1] - ts[0]) / 1e6) if ts is not None and len(ts) > 1 else 0.0
    return {
        "name": _topic_key(d),
        "fields": fields,
        "n_samples": n_samples,
        "duration_s": duration,
    }


# --------------------- Eel-exposed API --------------------- #
@eel.expose
def list_data_dir() -> list:
    """List ULG files in the workspace data/ directory."""
    if not os.path.isdir(DATA_DIR):
        return []
    files = []
    for name in sorted(os.listdir(DATA_DIR)):
        if name.lower().endswith(".ulg"):
            full = os.path.join(DATA_DIR, name)
            files.append({
                "name": name,
                "path": full,
                "size_kb": round(os.path.getsize(full) / 1024, 1),
            })
    return files


@eel.expose
def browse_file() -> Optional[str]:
    """Open a native file dialog and return the chosen path (or None)."""
    try:
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        initial = DATA_DIR if os.path.isdir(DATA_DIR) else SCRIPT_DIR
        path = filedialog.askopenfilename(
            title="Select a ULG File",
            initialdir=initial,
            filetypes=[("ULog files", "*.ulg"), ("All files", "*.*")],
        )
        root.destroy()
        return path or None
    except Exception as e:
        print(f"File dialog failed: {e}")
        return None


@eel.expose
def load_file(path: str) -> dict:
    """Parse a ULG file and return its topic summary."""
    if not path or not os.path.isfile(path):
        return {"ok": False, "error": f"File not found: {path}"}
    try:
        ulog = ULog(path)
    except Exception as e:
        return {"ok": False, "error": f"Could not parse ULG: {e}"}

    state.ulog = ulog
    state.current_file = path
    state.datasets = {_topic_key(d): d for d in ulog.data_list}

    topics = [_topic_summary(state.datasets[k]) for k in sorted(state.datasets.keys())]
    total_fields = sum(len(t["fields"]) for t in topics)
    return {
        "ok": True,
        "file_name": os.path.basename(path),
        "file_path": path,
        "topics": topics,
        "n_topics": len(topics),
        "n_fields": total_fields,
    }


@eel.expose
def get_series(selections: list) -> dict:
    """For each {topic, field} selection, return time + value arrays.

    Returns:
        {
          "ok": bool,
          "groups": [
              {"topic": "...", "series": [{"field": "...", "t": [...], "y": [...]}, ...]},
              ...
          ]
        }
    """
    if not state.ulog:
        return {"ok": False, "error": "No file loaded."}

    by_topic: Dict[str, set] = {}
    for sel in selections:
        topic = sel.get("topic")
        field = sel.get("field")
        if not topic or topic not in state.datasets:
            continue
        dset = state.datasets[topic]
        if field is None or field == "" or field == "*":
            for f in dset.data.keys():
                if f != "timestamp":
                    by_topic.setdefault(topic, set()).add(f)
        elif field in dset.data:
            by_topic.setdefault(topic, set()).add(field)

    groups = []
    for topic in sorted(by_topic.keys()):
        dset = state.datasets[topic]
        ts = dset.data.get("timestamp")
        if ts is None or len(ts) == 0:
            continue
        t = (ts - ts[0]) / 1e6
        t_list = _clean_array(t)
        series = []
        for f in sorted(by_topic[topic]):
            y = dset.data.get(f)
            if y is None:
                continue
            series.append({"field": f, "t": t_list, "y": _clean_array(y)})
        if series:
            groups.append({"topic": topic, "series": series})

    return {"ok": True, "groups": groups}


@eel.expose
def get_all_topics_data() -> dict:
    """Return data for every topic - used by 'Plot All Overview'."""
    if not state.ulog:
        return {"ok": False, "error": "No file loaded."}
    groups = []
    for topic in sorted(state.datasets.keys()):
        dset = state.datasets[topic]
        ts = dset.data.get("timestamp")
        if ts is None or len(ts) == 0:
            continue
        t = _clean_array((ts - ts[0]) / 1e6)
        series = []
        for f in sorted(dset.data.keys()):
            if f == "timestamp":
                continue
            series.append({"field": f, "t": t, "y": _clean_array(dset.data[f])})
        if series:
            groups.append({"topic": topic, "series": series})
    return {"ok": True, "groups": groups}


@eel.expose
def get_favorites() -> list:
    return [{"topic": t, "field": f} for (t, f) in _load_favorites()]


@eel.expose
def add_favorite(topic: str, field: str) -> list:
    favs = _load_favorites()
    if (topic, field) not in favs:
        favs.append((topic, field))
        _save_favorites(favs)
    return [{"topic": t, "field": f} for (t, f) in favs]


@eel.expose
def add_favorites_bulk(entries: list) -> list:
    """Add multiple favorites at once. Each entry: {topic, field|None}."""
    favs = _load_favorites()
    fav_set = set(favs)
    for e in entries:
        topic = e.get("topic")
        field = e.get("field")
        if not topic or topic not in state.datasets:
            continue
        dset = state.datasets[topic]
        if field is None or field == "":
            for f in dset.data.keys():
                if f != "timestamp" and (topic, f) not in fav_set:
                    favs.append((topic, f))
                    fav_set.add((topic, f))
        elif field in dset.data:
            if (topic, field) not in fav_set:
                favs.append((topic, field))
                fav_set.add((topic, field))
    _save_favorites(favs)
    return [{"topic": t, "field": f} for (t, f) in favs]


@eel.expose
def remove_favorite(topic: str, field: str) -> list:
    favs = [fv for fv in _load_favorites() if fv != (topic, field)]
    _save_favorites(favs)
    return [{"topic": t, "field": f} for (t, f) in favs]


@eel.expose
def remove_favorites_bulk(entries: list) -> list:
    drop = {(e.get("topic"), e.get("field")) for e in entries}
    favs = [fv for fv in _load_favorites() if fv not in drop]
    _save_favorites(favs)
    return [{"topic": t, "field": f} for (t, f) in favs]


@eel.expose
def check_favorites_in_file() -> list:
    """For each favorite, indicate whether it exists in the currently loaded file."""
    out = []
    for topic, field in _load_favorites():
        present = bool(state.ulog) and topic in state.datasets and field in state.datasets[topic].data
        out.append({"topic": topic, "field": field, "present": present})
    return out


# ------------------------------ Main ------------------------------ #
def main():
    eel.init(WEB_DIR)
    # Pick a reasonable default size; close_callback prevents the Python process from hanging.
    try:
        eel.start(
            "index.html",
            size=(1440, 900),
            mode="default",   # uses Chrome/Edge if available
            block=True,
        )
    except (SystemExit, KeyboardInterrupt):
        pass
    except Exception as e:
        print(f"eel.start failed ({e}); retrying with mode=None (will print URL).")
        eel.start("index.html", mode=None, host="localhost", port=8765, block=True)


if __name__ == "__main__":
    main()
