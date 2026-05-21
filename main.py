"""ULG (PX4 ULog) File Viewer — Eel (HTML/CSS/JS) edition.

Python backend that exposes ULog parsing to a web-based frontend.
Favorites are persisted to settings.txt in the workspace.
"""

from __future__ import annotations

import os
import sys
import math
import tempfile
from typing import Dict, List, Tuple, Optional

import eel
import bottle
import numpy as np

# Allow large multipart uploads to spill to a temp file instead of RAM.
bottle.BaseRequest.MEMFILE_MAX = 8 * 1024 * 1024  # 8 MB in-memory threshold

try:
    from pyulog import ULog
except ImportError:
    print("Missing dependency: pyulog. Install it via:  pip install pyulog eel numpy")
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


# ====================== PX4 Flight Review "Default" panels ====================== #
def _get(topic: str, field: str) -> Optional[np.ndarray]:
    """Safe accessor: returns the field array or None if absent."""
    dset = state.datasets.get(topic)
    if dset is None:
        return None
    return dset.data.get(field)


def _t(topic: str) -> Optional[np.ndarray]:
    """Time in seconds (relative to topic start) or None."""
    dset = state.datasets.get(topic)
    if dset is None:
        return None
    ts = dset.data.get("timestamp")
    if ts is None or len(ts) == 0:
        return None
    return (ts - ts[0]) / 1e6


def _quat_to_euler_deg(topic: str):
    """Return (t, roll_deg, pitch_deg, yaw_deg) for a topic with q[0..3], or None."""
    q0 = _get(topic, "q[0]"); q1 = _get(topic, "q[1]")
    q2 = _get(topic, "q[2]"); q3 = _get(topic, "q[3]")
    t = _t(topic)
    if any(x is None for x in (q0, q1, q2, q3, t)):
        return None
    sinr = 2.0 * (q0 * q1 + q2 * q3)
    cosr = 1.0 - 2.0 * (q1 * q1 + q2 * q2)
    roll = np.degrees(np.arctan2(sinr, cosr))
    sinp = 2.0 * (q0 * q2 - q3 * q1)
    sinp = np.clip(sinp, -1.0, 1.0)
    pitch = np.degrees(np.arcsin(sinp))
    siny = 2.0 * (q0 * q3 + q1 * q2)
    cosy = 1.0 - 2.0 * (q2 * q2 + q3 * q3)
    yaw = np.degrees(np.arctan2(siny, cosy))
    return t, roll, pitch, yaw


def _quat_to_euler_deg_d(topic: str):
    """Same as _quat_to_euler_deg but for q_d (desired/setpoint quaternion)."""
    q0 = _get(topic, "q_d[0]"); q1 = _get(topic, "q_d[1]")
    q2 = _get(topic, "q_d[2]"); q3 = _get(topic, "q_d[3]")
    t = _t(topic)
    if any(x is None for x in (q0, q1, q2, q3, t)):
        return None
    sinr = 2.0 * (q0 * q1 + q2 * q3)
    cosr = 1.0 - 2.0 * (q1 * q1 + q2 * q2)
    roll = np.degrees(np.arctan2(sinr, cosr))
    sinp = 2.0 * (q0 * q2 - q3 * q1)
    sinp = np.clip(sinp, -1.0, 1.0)
    pitch = np.degrees(np.arcsin(sinp))
    siny = 2.0 * (q0 * q3 + q1 * q2)
    cosy = 1.0 - 2.0 * (q2 * q2 + q3 * q3)
    yaw = np.degrees(np.arctan2(siny, cosy))
    return t, roll, pitch, yaw


_MAX_POINTS_PER_SERIES = 6000  # downsample threshold for the default review page


def _downsample(t, y, max_points: int = _MAX_POINTS_PER_SERIES):
    """Uniform-stride downsample two parallel arrays to <= max_points."""
    n = len(t)
    if n <= max_points:
        return t, y
    step = int(math.ceil(n / max_points))
    return t[::step], y[::step]


def _series(name: str, t, y, color: Optional[str] = None,
            downsample: bool = True) -> Optional[dict]:
    if t is None or y is None:
        return None
    if len(t) == 0 or len(y) == 0:
        return None
    if len(t) != len(y):
        n = min(len(t), len(y))
        t = t[:n]; y = y[:n]
    t = np.asarray(t); y = np.asarray(y)
    if downsample:
        t, y = _downsample(t, y)
    out = {"name": name, "t": _clean_array(t), "y": _clean_array(y)}
    if color:
        out["color"] = color
    return out


def _build_default_panels() -> List[dict]:
    """Build the standard PX4 Flight Review panel list from the currently loaded file.

    Skips panels whose source topics are missing. Each panel: {title, ylabel, series, [layout]}
    Series: [{name, t, y, color?}]
    """
    panels: List[dict] = []

    C_EST = "#ff8a4c"      # orange (estimated)
    C_SP  = "#3ecf8e"      # green (setpoint)
    C_GT  = "#bbbbbb"      # gray (groundtruth)
    C_AUX = "#5dade2"      # blue (integral / fused)
    C_X   = "#ff8a4c"
    C_Y   = "#3ecf8e"
    C_Z   = "#5dade2"

    # ---------- 0. GPS Trajectory on satellite map ----------
    lat = _get("vehicle_gps_position", "latitude_deg")
    lon = _get("vehicle_gps_position", "longitude_deg")
    if lat is None or lon is None:
        # Fallback to legacy field names
        lat = _get("sensor_gps", "latitude_deg")
        lon = _get("sensor_gps", "longitude_deg")
    if lat is not None and lon is not None:
        lat_arr = np.asarray(lat)
        lon_arr = np.asarray(lon)
        # PX4 SITL frequently logs 0,0 before GPS fix; drop those samples.
        valid = (np.abs(lat_arr) > 1e-6) & (np.abs(lon_arr) > 1e-6) & \
                np.isfinite(lat_arr) & np.isfinite(lon_arr)
        lat_arr = lat_arr[valid]
        lon_arr = lon_arr[valid]
        if lat_arr.size > 1:
            lat_ds, lon_ds = _downsample(lat_arr, lon_arr)
            panels.append({
                "title": "GPS Trajectory (Satellite)",
                "type": "map",
                "ylabel": "",
                "series": [{
                    "name": "Trajectory",
                    "lat": _clean_array(lat_ds),
                    "lon": _clean_array(lon_ds),
                    "color": "#a78bfa",
                }],
            })

    # ---------- 1. Position (X/Y) — multi-series like PX4 Flight Review ----------
    lp_x = _get("vehicle_local_position", "x")
    lp_y = _get("vehicle_local_position", "y")

    # Local frame origin (used to project lat/lon to north/east meters)
    ref_lat_arr = _get("vehicle_local_position", "ref_lat")
    ref_lon_arr = _get("vehicle_local_position", "ref_lon")
    ref_lat = float(ref_lat_arr[-1]) if ref_lat_arr is not None and len(ref_lat_arr) > 0 else None
    ref_lon = float(ref_lon_arr[-1]) if ref_lon_arr is not None and len(ref_lon_arr) > 0 else None

    def _project_to_ne(lat_a, lon_a):
        """Equirectangular projection of lat/lon -> (north_m, east_m) about (ref_lat, ref_lon)."""
        if ref_lat is None or ref_lon is None:
            return None, None
        EARTH_R = 6371000.0
        ref_lat_rad = math.radians(ref_lat)
        dlat = np.radians(np.asarray(lat_a) - ref_lat)
        dlon = np.radians(np.asarray(lon_a) - ref_lon)
        return dlat * EARTH_R, dlon * EARTH_R * math.cos(ref_lat_rad)

    def _xy_series(name, north, east, color, mode="lines"):
        """Convert a (north, east) pair into a chart-space (x=east, y=north) trace."""
        if north is None or east is None or len(north) == 0:
            return None
        valid = np.isfinite(np.asarray(north)) & np.isfinite(np.asarray(east))
        n = np.asarray(north)[valid]
        e = np.asarray(east)[valid]
        if n.size == 0:
            return None
        e_ds, n_ds = _downsample(e, n)
        return {
            "name": name,
            "x": _clean_array(e_ds),
            "y": _clean_array(n_ds),
            "color": color,
            "mode": mode,
        }

    xy_series = []

    # Estimated — vehicle_local_position
    if lp_x is not None and lp_y is not None:
        s = _xy_series("Estimated", np.asarray(lp_x), np.asarray(lp_y), C_EST, "lines")
        if s: xy_series.append(s)

    # Setpoint — vehicle_local_position_setpoint
    sp_x = _get("vehicle_local_position_setpoint", "x")
    sp_y = _get("vehicle_local_position_setpoint", "y")
    if sp_x is not None and sp_y is not None:
        s = _xy_series("Setpoint", np.asarray(sp_x), np.asarray(sp_y), C_SP, "lines")
        if s: xy_series.append(s)

    # Groundtruth — vehicle_local_position_groundtruth (SITL only)
    gt_x = _get("vehicle_local_position_groundtruth", "x")
    gt_y = _get("vehicle_local_position_groundtruth", "y")
    if gt_x is not None and gt_y is not None:
        s = _xy_series("Groundtruth", np.asarray(gt_x), np.asarray(gt_y), C_GT, "lines")
        if s: xy_series.append(s)

    # GPS (projected) — vehicle_gps_position lat/lon projected to local NE
    gps_lat = _get("vehicle_gps_position", "latitude_deg")
    gps_lon = _get("vehicle_gps_position", "longitude_deg")
    if gps_lat is not None and gps_lon is not None and ref_lat is not None:
        lat_a = np.asarray(gps_lat); lon_a = np.asarray(gps_lon)
        valid = (np.abs(lat_a) > 1e-6) & (np.abs(lon_a) > 1e-6) & \
                np.isfinite(lat_a) & np.isfinite(lon_a)
        if valid.any():
            n, e = _project_to_ne(lat_a[valid], lon_a[valid])
            s = _xy_series("GPS (projected)", n, e, "#5dade2", "lines")
            if s: xy_series.append(s)

    # Position Setpoints — position_setpoint_triplet.current.lat/lon (markers)
    psp_lat = _get("position_setpoint_triplet", "current.lat")
    psp_lon = _get("position_setpoint_triplet", "current.lon")
    psp_valid = _get("position_setpoint_triplet", "current.valid")
    if psp_lat is not None and psp_lon is not None and ref_lat is not None:
        lat_a = np.asarray(psp_lat); lon_a = np.asarray(psp_lon)
        valid = (np.abs(lat_a) > 1e-6) & (np.abs(lon_a) > 1e-6) & \
                np.isfinite(lat_a) & np.isfinite(lon_a)
        if psp_valid is not None:
            valid = valid & (np.asarray(psp_valid) > 0)
        if valid.any():
            lat_ok = lat_a[valid]; lon_ok = lon_a[valid]
            # Keep only distinct consecutive waypoints
            if lat_ok.size > 1:
                changed = (np.diff(lat_ok) != 0) | (np.diff(lon_ok) != 0)
                keep = np.concatenate(([True], changed))
                lat_ok = lat_ok[keep]; lon_ok = lon_ok[keep]
            n, e = _project_to_ne(lat_ok, lon_ok)
            s = _xy_series("Position Setpoints", n, e, "#e879c5", "markers")
            if s: xy_series.append(s)

    if xy_series:
        panels.append({
            "title": "Position (X/Y)",
            "type": "scatter_xy",
            "xlabel": "[m] East",
            "ylabel": "[m] North",
            "series": xy_series,
        })

    # ---------- 2. Altitude Estimate ----------
    alt_series = []
    s = _series("GPS Altitude (MSL)", _t("sensor_gps"), _get("sensor_gps", "altitude_msl_m"), "#ff8a4c")
    if s: alt_series.append(s)
    s = _series("Barometer Altitude", _t("vehicle_air_data"), _get("vehicle_air_data", "baro_alt_meter"), "#3ecf8e")
    if s: alt_series.append(s)
    fused_z = _get("vehicle_local_position", "z")
    if fused_z is not None:
        s = _series("Fused Altitude Estimation", _t("vehicle_local_position"), -np.asarray(fused_z), "#5dade2")
        if s: alt_series.append(s)
    sp_z = _get("vehicle_local_position_setpoint", "z")
    if sp_z is not None:
        s = _series("Altitude Setpoint", _t("vehicle_local_position_setpoint"), -np.asarray(sp_z), "#e879c5")
        if s: alt_series.append(s)
    if alt_series:
        panels.append({"title": "Altitude Estimate", "ylabel": "[m]", "series": alt_series})

    # ---------- 3-8. Attitude (Roll / Pitch / Yaw) Angles & Rates ----------
    att = _quat_to_euler_deg("vehicle_attitude")
    att_sp = _quat_to_euler_deg_d("vehicle_attitude_setpoint")
    att_gt = _quat_to_euler_deg("vehicle_attitude_groundtruth")
    rate_est_t = _t("vehicle_angular_velocity")
    rate_x = _get("vehicle_angular_velocity", "xyz[0]")
    rate_y = _get("vehicle_angular_velocity", "xyz[1]")
    rate_z = _get("vehicle_angular_velocity", "xyz[2]")
    rsp_t = _t("vehicle_rates_setpoint")
    rsp_r = _get("vehicle_rates_setpoint", "roll")
    rsp_p = _get("vehicle_rates_setpoint", "pitch")
    rsp_y = _get("vehicle_rates_setpoint", "yaw")
    integ_t = _t("rate_ctrl_status")
    integ_r = _get("rate_ctrl_status", "rollspeed_integ")
    integ_p = _get("rate_ctrl_status", "pitchspeed_integ")
    integ_y = _get("rate_ctrl_status", "yawspeed_integ")

    def _angle_panel(title, est_idx, sp_idx, gt_idx, include_yaw_ff=False):
        ss = []
        if att:
            s = _series(f"{title.split()[0]} Estimated", att[0], att[est_idx], C_EST)
            if s: ss.append(s)
        if att_sp:
            s = _series(f"{title.split()[0]} Setpoint", att_sp[0], att_sp[sp_idx], C_SP)
            if s: ss.append(s)
        if att_gt:
            s = _series(f"{title.split()[0]} Groundtruth", att_gt[0], att_gt[gt_idx], C_GT)
            if s: ss.append(s)
        if ss:
            panels.append({"title": title, "ylabel": "[deg]", "series": ss})

    def _rate_panel(title, rate_arr, sp_arr, integ_arr):
        ss = []
        if rate_arr is not None:
            s = _series(f"{title.split()[0]} Rate Estimated", rate_est_t, np.degrees(np.asarray(rate_arr)), C_EST)
            if s: ss.append(s)
        if sp_arr is not None:
            s = _series(f"{title.split()[0]} Rate Setpoint", rsp_t, np.degrees(np.asarray(sp_arr)), C_SP)
            if s: ss.append(s)
        if integ_arr is not None:
            s = _series(f"{title.split()[0]} Rate Integral [-30, 30]", integ_t, np.asarray(integ_arr), C_AUX)
            if s: ss.append(s)
        if ss:
            panels.append({"title": title, "ylabel": "[deg/s]", "series": ss})

    _angle_panel("Roll Angle",  1, 1, 1)
    _rate_panel("Roll Angular Rate",  rate_x, rsp_r, integ_r)
    _angle_panel("Pitch Angle", 2, 2, 2)
    _rate_panel("Pitch Angular Rate", rate_y, rsp_p, integ_p)
    _angle_panel("Yaw Angle",   3, 3, 3)
    _rate_panel("Yaw Angular Rate",   rate_z, rsp_y, integ_y)

    # ---------- 9-11. Local Position X / Y / Z ----------
    for axis, label, sp_field in [("x", "Local Position X", "x"),
                                  ("y", "Local Position Y", "y"),
                                  ("z", "Local Position Z", "z")]:
        ss = []
        s = _series(f"{axis.upper()} Estimated", _t("vehicle_local_position"),
                    _get("vehicle_local_position", axis), C_EST)
        if s: ss.append(s)
        s = _series(f"{axis.upper()} Setpoint", _t("vehicle_local_position_setpoint"),
                    _get("vehicle_local_position_setpoint", sp_field), C_SP)
        if s: ss.append(s)
        if ss:
            panels.append({"title": label, "ylabel": "[m]", "series": ss})

    # ---------- 12. Velocity ----------
    ss = []
    for axis, c in [("vx", C_X), ("vy", C_Y), ("vz", C_Z)]:
        s = _series(axis.upper(), _t("vehicle_local_position"),
                    _get("vehicle_local_position", axis), c)
        if s: ss.append(s)
    for axis, name, c in [("vx", "X Setpoint", "#ffb38a"), ("vy", "Y Setpoint", "#8be0b8"), ("vz", "Z Setpoint", "#a0d2eb")]:
        s = _series(name, _t("vehicle_local_position_setpoint"),
                    _get("vehicle_local_position_setpoint", axis), c)
        if s: ss.append(s)
    if ss:
        panels.append({"title": "Velocity", "ylabel": "[m/s]", "series": ss})

    # ---------- 13. Manual Control Inputs ----------
    ss = []
    for f, name, c in [("roll", "Y / Roll", "#ff8a4c"),
                        ("pitch", "X / Pitch", "#3ecf8e"),
                        ("yaw", "Yaw", "#5dade2"),
                        ("throttle", "Throttle [-1, 1]", "#222831"),
                        ("aux1", "Aux1", "#fbbf24"),
                        ("aux2", "Aux2", "#60a5fa")]:
        s = _series(name, _t("manual_control_setpoint"),
                    _get("manual_control_setpoint", f), c)
        if s: ss.append(s)
    if ss:
        panels.append({"title": "Manual Control Inputs (Radio or Joystick)", "ylabel": "", "series": ss})

    # ---------- 14. Actuator Controls (torque + thrust setpoints) ----------
    ss = []
    for i, name, c in [(0, "Roll", "#ff8a4c"), (1, "Pitch", "#3ecf8e"), (2, "Yaw", "#5dade2")]:
        s = _series(name, _t("vehicle_torque_setpoint"),
                    _get("vehicle_torque_setpoint", f"xyz[{i}]"), c)
        if s: ss.append(s)
    s = _series("Thrust (up)", _t("vehicle_thrust_setpoint"),
                _get("vehicle_thrust_setpoint", "xyz[2]"), "#222831")
    if s: ss.append(s)
    s = _series("Thrust (forward)", _t("vehicle_thrust_setpoint"),
                _get("vehicle_thrust_setpoint", "xyz[0]"), "#fbbf24")
    if s: ss.append(s)
    if ss:
        panels.append({"title": "Actuator Controls", "ylabel": "", "series": ss})

    # ---------- 15. Motor Outputs ----------
    ss = []
    motor_colors = ["#ff8a4c", "#3ecf8e", "#5dade2", "#222831", "#fbbf24", "#a78bfa", "#f472b6", "#67e8f9"]
    for i in range(8):
        s = _series(f"Motor {i+1}", _t("actuator_motors"),
                    _get("actuator_motors", f"control[{i}]"), motor_colors[i % len(motor_colors)])
        if s and not all(v is None or v == 0 for v in s["y"][:50]):
            ss.append(s)
        elif s and i < 4:
            # Always show first 4 motors even if zero
            ss.append(s)
    if ss:
        panels.append({"title": "Motor Outputs", "ylabel": "", "series": ss})

    # ---------- 16. Raw Acceleration ----------
    ss = []
    for i, name, c in [(0, "X", C_X), (1, "Y", C_Y), (2, "Z", C_Z)]:
        s = _series(name, _t("sensor_combined"),
                    _get("sensor_combined", f"accelerometer_m_s2[{i}]"), c)
        if s: ss.append(s)
    if ss:
        panels.append({"title": "Raw Acceleration", "ylabel": "[m/s²]", "series": ss})

    # ---------- 17. Raw Angular Speed (Gyroscope) ----------
    ss = []
    for i, name, c in [(0, "X", C_X), (1, "Y", C_Y), (2, "Z", C_Z)]:
        gy = _get("sensor_combined", f"gyro_rad[{i}]")
        if gy is not None:
            s = _series(name, _t("sensor_combined"), np.degrees(np.asarray(gy)), c)
            if s: ss.append(s)
    if ss:
        panels.append({"title": "Raw Angular Speed (Gyroscope)", "ylabel": "[deg/s]", "series": ss})

    # ---------- 18. Raw Magnetic Field Strength ----------
    ss = []
    for i, name, c in [(0, "X", C_X), (1, "Y", C_Y), (2, "Z", C_Z)]:
        s = _series(name, _t("vehicle_magnetometer"),
                    _get("vehicle_magnetometer", f"magnetometer_ga[{i}]"), c)
        if s: ss.append(s)
    if ss:
        panels.append({"title": "Raw Magnetic Field Strength", "ylabel": "[gauss]", "series": ss})

    # ---------- 19. Distance Sensor ----------
    ss = []
    s = _series("Estimated Distance Bottom [m]", _t("vehicle_local_position"),
                _get("vehicle_local_position", "dist_bottom"), C_EST)
    if s: ss.append(s)
    s = _series("Dist Bottom Valid", _t("vehicle_local_position"),
                _get("vehicle_local_position", "dist_bottom_valid"), C_GT)
    if s: ss.append(s)
    if ss:
        panels.append({"title": "Distance Sensor", "ylabel": "[m]", "series": ss})

    # ---------- 20. GPS Uncertainty ----------
    ss = []
    for f, name, c in [("eph", "Horizontal position accuracy [m]", "#ff8a4c"),
                        ("epv", "Vertical position accuracy [m]", "#3ecf8e"),
                        ("hdop", "Horizontal dilution of precision [m]", "#5dade2"),
                        ("vdop", "Vertical dilution of precision [m]", "#222831"),
                        ("s_variance_m_s", "Speed accuracy [m/s]", "#fbbf24"),
                        ("satellites_used", "Num Satellites used", "#60a5fa"),
                        ("fix_type", "GPS Fix", "#e879c5")]:
        s = _series(name, _t("sensor_gps"), _get("sensor_gps", f), c)
        if s: ss.append(s)
    if ss:
        panels.append({"title": "GPS Uncertainty", "ylabel": "", "series": ss})

    # ---------- 21. GPS Noise & Jamming ----------
    ss = []
    s = _series("Noise per ms", _t("sensor_gps"), _get("sensor_gps", "noise_per_ms"), "#ff8a4c")
    if s: ss.append(s)
    s = _series("Jamming Indicator", _t("sensor_gps"), _get("sensor_gps", "jamming_indicator"), "#3ecf8e")
    if s: ss.append(s)
    if ss:
        panels.append({"title": "GPS Noise & Jamming", "ylabel": "", "series": ss})

    # ---------- 22. Power (Battery) ----------
    ss = []
    s = _series("Battery Voltage [V]", _t("battery_status"),
                _get("battery_status", "voltage_v"), "#ff8a4c")
    if s: ss.append(s)
    s = _series("Battery Current [A]", _t("battery_status"),
                _get("battery_status", "current_a"), "#3ecf8e")
    if s: ss.append(s)
    dmah = _get("battery_status", "discharged_mah")
    if dmah is not None:
        s = _series("Discharged Amount [mAh / 100]", _t("battery_status"),
                    np.asarray(dmah) / 100.0, "#5dade2")
        if s: ss.append(s)
    rem = _get("battery_status", "remaining")
    if rem is not None:
        s = _series("Battery remaining [0=empty, 10=full]", _t("battery_status"),
                    np.asarray(rem) * 10.0, "#222831")
        if s: ss.append(s)
    s = _series("OCV Estimate [V]", _t("battery_status"),
                _get("battery_status", "ocv_estimate"), "#fbbf24")
    if s: ss.append(s)
    s = _series("Internal Resistance Estimate [mOhm]", _t("battery_status"),
                _get("battery_status", "internal_resistance_estimate"), "#60a5fa")
    if s: ss.append(s)
    v5 = _get("system_power", "voltage5v_v")
    if v5 is not None:
        s = _series("5 V", _t("system_power"), v5, "#e879c5")
        if s: ss.append(s)
    if ss:
        panels.append({"title": "Power", "ylabel": "[V] / [A] / [%]", "series": ss})

    # ---------- 23. Temperature ----------
    ss = []
    s = _series("Baro temperature", _t("sensor_baro"),
                _get("sensor_baro", "temperature"), "#ff8a4c")
    if s: ss.append(s)
    s = _series("Accel temperature", _t("sensor_accel"),
                _get("sensor_accel", "temperature"), "#5dade2")
    if s: ss.append(s)
    s = _series("Battery temperature", _t("battery_status"),
                _get("battery_status", "temperature"), "#e879c5")
    if s: ss.append(s)
    if ss:
        panels.append({"title": "Temperature", "ylabel": "[°C]", "series": ss})

    # ---------- 24. Failsafe Flags ----------
    ss = []
    flag_fields = [("failsafe", "In Failsafe", "#ff8a4c"),
                   ("failsafe_and_user_took_over", "User Took Over", "#3ecf8e"),
                   ("manual_control_signal_lost", "manual control signal lost", "#5dade2"),
                   ("gcs_connection_lost", "gcs connection lost", "#222831"),
                   ("open_drone_id_system_healthy", "remote id unhealthy", "#fbbf24")]
    for f, name, c in flag_fields:
        s = _series(name, _t("vehicle_status"), _get("vehicle_status", f), c)
        if s: ss.append(s)
    if ss:
        panels.append({"title": "Failsafe Flags", "ylabel": "", "series": ss})

    # ---------- 25. CPU & RAM ----------
    ss = []
    s = _series("RAM Usage", _t("cpuload"), _get("cpuload", "ram_usage"), "#3ecf8e")
    if s: ss.append(s)
    s = _series("CPU Load", _t("cpuload"), _get("cpuload", "load"), "#5dade2")
    if s: ss.append(s)
    if ss:
        panels.append({"title": "CPU & RAM", "ylabel": "", "series": ss})

    return panels


# --------------- Drag-drop path resolution (no upload) --------------- #
@eel.expose
def resolve_dropped_file(name: str) -> dict:
    """Resolve a dropped file by NAME only (browser strips the absolute path).

    Searches the workspace data/ folder and SCRIPT_DIR for a matching file.
    Returns {ok, path} on success, or {ok: False, error} otherwise.
    """
    if not name:
        return {"ok": False, "error": "Empty filename."}
    base = os.path.basename(name)
    # Search candidate directories in priority order.
    search_dirs = [DATA_DIR, SCRIPT_DIR]
    for d in search_dirs:
        if not os.path.isdir(d):
            continue
        candidate = os.path.join(d, base)
        if os.path.isfile(candidate):
            return {"ok": True, "path": candidate}
    return {"ok": False, "error": (
        f"Could not locate '{base}' in the data/ folder."
    )}


# --------- Fast binary upload via HTTP POST (drag-drop from anywhere) --------- #
# A single multipart/form-data POST streams the raw file straight to disk — no
# base64, no per-chunk websocket round-trips. This is the fast path used by the
# landing page's drag-drop / browse fallback.
@bottle.post("/upload_ulg")
def _http_upload_ulg():
    upload = bottle.request.files.get("file")
    if upload is None:
        bottle.response.status = 400
        return {"ok": False, "error": "No file in request."}
    safe_name = os.path.basename(upload.raw_filename or "dropped.ulg")
    fd, path = tempfile.mkstemp(suffix=f"_{safe_name}", prefix="ulg_upload_")
    os.close(fd)
    try:
        upload.save(path, overwrite=True)
    except Exception as e:
        bottle.response.status = 500
        return {"ok": False, "error": f"Could not save upload: {e}"}
    result = load_file(path)
    bottle.response.content_type = "application/json"
    return result


# ----------------------- ULog metadata + flight stats ----------------------- #
# Common PX4 SITL airframes — extend as needed.
AIRFRAME_NAMES: Dict[int, Tuple[str, str]] = {
    4001: ("Generic Quadcopter",            "Quadrotor x"),
    4002: ("Generic 250 Racer",             "Quadrotor x"),
    4010: ("Generic Quadplane VTOL",        "Standard VTOL"),
    4011: ("Tiltrotor VTOL",                "Tiltrotor VTOL"),
    4012: ("Standard VTOL",                 "Standard VTOL"),
    4013: ("Tailsitter VTOL",               "Tailsitter VTOL"),
    4015: ("3DR Iris",                      "Quadrotor x"),
    4017: ("HippoCampus AUV",               "AUV"),
    4019: ("Holybro X500",                  "Quadrotor x"),
    6001: ("Generic Hexarotor",             "Hexarotor x"),
    8001: ("Generic Octacopter",            "Octorotor x"),
}


def _decode_version(v) -> str:
    """Decode PX4's packed semver int into 'vMAJOR.MINOR.PATCH (type)' string."""
    if not isinstance(v, int) or v <= 0:
        return ""
    major = (v >> 24) & 0xff
    minor = (v >> 16) & 0xff
    patch = (v >> 8) & 0xff
    type_byte = v & 0xff
    suffix_map = {0: "dev", 64: "alpha", 128: "beta", 192: "rc", 255: ""}
    suffix = suffix_map.get(type_byte, "")
    base = f"v{major}.{minor}.{patch}"
    return f"{base} ({suffix})" if suffix else base


def _decode_os_version(v) -> str:
    if not isinstance(v, int) or v <= 0:
        return ""
    major = (v >> 24) & 0xff
    minor = (v >> 16) & 0xff
    patch = (v >> 8) & 0xff
    return f"v{major}.{minor}.{patch}"


@eel.expose
def get_file_info() -> dict:
    """Extract metadata + flight statistics from the currently loaded ULog."""
    if not state.ulog:
        return {"ok": False, "error": "No file loaded."}

    info_dict = state.ulog.msg_info_dict or {}
    params = state.ulog.initial_parameters or {}

    airframe_id = int(params.get("SYS_AUTOSTART", 0))
    af_group, af_name = AIRFRAME_NAMES.get(airframe_id, ("", ""))

    sw_full = info_dict.get("ver_sw", "")
    sw_short = sw_full[:8] if isinstance(sw_full, str) else ""
    sw_decoded = _decode_version(info_dict.get("ver_sw_release"))
    os_decoded = _decode_os_version(info_dict.get("sys_os_ver_release"))

    # Estimator: PX4 always uses EKF2 in recent versions; check EKF2_EN to confirm.
    ekf2_en = params.get("EKF2_EN", 1)
    estimator = "EKF2" if ekf2_en else "—"

    duration_s = (state.ulog.last_timestamp - state.ulog.start_timestamp) / 1e6

    # Flight time within this log = sum of intervals where the vehicle was NOT landed.
    flight_time_s = 0.0
    vld = state.datasets.get("vehicle_land_detected")
    if vld is not None and "landed" in vld.data and "timestamp" in vld.data:
        ts = np.asarray(vld.data["timestamp"], dtype=np.int64)
        landed = np.asarray(vld.data["landed"]).astype(bool)
        if ts.size > 1:
            dt_us = np.diff(ts).astype(np.float64)
            in_air = ~landed[:-1]
            flight_time_s = float(np.sum(dt_us[in_air])) / 1e6
    # Fallback: if no land-detector data, derive from actuator_armed transitions.
    if flight_time_s == 0.0:
        aa = state.datasets.get("actuator_armed")
        if aa is not None and "armed" in aa.data and "timestamp" in aa.data:
            ts = np.asarray(aa.data["timestamp"], dtype=np.int64)
            armed = np.asarray(aa.data["armed"]).astype(bool)
            if ts.size > 1:
                dt_us = np.diff(ts).astype(np.float64)
                flight_time_s = float(np.sum(dt_us[armed[:-1]])) / 1e6

    # Lifetime flight time — LND_FLIGHT_T_HI/LO together form a uint64 microsecond counter.
    # (LO wraps every 2**32 us ≈ 71.6 minutes; HI tracks the wraps.)
    lifetime_s = 0.0
    hi = params.get("LND_FLIGHT_T_HI", 0)
    lo = params.get("LND_FLIGHT_T_LO", 0)
    if isinstance(hi, (int, float)) and isinstance(lo, (int, float)) and (hi or lo):
        lifetime_us = int(hi) * (1 << 32) + int(lo)
        lifetime_s = lifetime_us / 1e6

    # Trajectory-derived stats (vehicle_local_position).
    distance_m = 0.0
    max_alt_diff_m = 0.0
    max_v = max_vh = max_vz_up = max_vz_dn = 0.0
    lp = state.datasets.get("vehicle_local_position")
    if lp is not None:
        x = np.asarray(lp.data.get("x")) if "x" in lp.data else None
        y = np.asarray(lp.data.get("y")) if "y" in lp.data else None
        z = np.asarray(lp.data.get("z")) if "z" in lp.data else None
        vx = np.asarray(lp.data.get("vx")) if "vx" in lp.data else None
        vy = np.asarray(lp.data.get("vy")) if "vy" in lp.data else None
        vz = np.asarray(lp.data.get("vz")) if "vz" in lp.data else None
        if x is not None and y is not None and x.size > 1:
            dx = np.diff(x); dy = np.diff(y)
            distance_m = float(np.nansum(np.sqrt(dx * dx + dy * dy)))
        if z is not None and z.size > 0:
            z_valid = z[np.isfinite(z)]
            if z_valid.size > 0:
                max_alt_diff_m = float(z_valid.max() - z_valid.min())
        if vx is not None and vy is not None and vz is not None and vx.size > 0:
            speed = np.sqrt(vx * vx + vy * vy + vz * vz)
            speed_h = np.sqrt(vx * vx + vy * vy)
            max_v = float(np.nanmax(speed)) if speed.size else 0.0
            max_vh = float(np.nanmax(speed_h)) if speed_h.size else 0.0
            max_vz_up = float(np.nanmax(-vz)) if vz.size else 0.0     # NED: -vz is up
            max_vz_dn = float(np.nanmax(vz)) if vz.size else 0.0      # NED: +vz is down

    # Max tilt angle from quaternion (angle between body-z and world-z).
    max_tilt_deg = 0.0
    att = state.datasets.get("vehicle_attitude")
    if att is not None:
        q1 = np.asarray(att.data.get("q[1]")) if "q[1]" in att.data else None
        q2 = np.asarray(att.data.get("q[2]")) if "q[2]" in att.data else None
        if q1 is not None and q2 is not None and q1.size > 0:
            cos_tilt = np.clip(1.0 - 2.0 * (q1 * q1 + q2 * q2), -1.0, 1.0)
            tilt = np.degrees(np.arccos(cos_tilt))
            max_tilt_deg = float(np.nanmax(tilt))

    avg_speed = 0.0
    if flight_time_s > 0 and distance_m > 0:
        avg_speed = distance_m / flight_time_s

    return {
        "ok": True,
        "airframe_group": af_group,
        "airframe_name": af_name,
        "airframe_id": airframe_id,
        "hardware": info_dict.get("ver_hw", "—"),
        "sw_version": sw_decoded or "—",
        "sw_hash": sw_short,
        "branch": info_dict.get("ver_sw_branch", "—"),
        "os_label": (info_dict.get("sys_os_name", "") + (
            f", {os_decoded}" if os_decoded else "")).strip(", ") or "—",
        "estimator": estimator,
        "logging_duration_s": duration_s,
        "flight_time_s": flight_time_s,
        "lifetime_s": lifetime_s,
        "distance_m": distance_m,
        "max_altitude_diff_m": max_alt_diff_m,
        "avg_speed_kmh": avg_speed * 3.6,
        "max_speed_kmh": max_v * 3.6,
        "max_speed_horizontal_kmh": max_vh * 3.6,
        "max_speed_up_kmh": max_vz_up * 3.6,
        "max_speed_down_kmh": max_vz_dn * 3.6,
        "max_tilt_deg": max_tilt_deg,
    }


@eel.expose
def get_current_state() -> dict:
    """Return whether a file is currently loaded + its summary (used on page load)."""
    if not state.ulog or not state.current_file:
        return {"ok": True, "loaded": False}
    topics = [_topic_summary(state.datasets[k]) for k in sorted(state.datasets.keys())]
    total_fields = sum(len(t["fields"]) for t in topics)
    return {
        "ok": True,
        "loaded": True,
        "file_name": os.path.basename(state.current_file),
        "file_path": state.current_file,
        "topics": topics,
        "n_topics": len(topics),
        "n_fields": total_fields,
    }


@eel.expose
def get_default_plot_data() -> dict:
    """Return PX4 Flight Review-style panels for the loaded file."""
    if not state.ulog:
        return {"ok": False, "error": "No file loaded."}
    panels = _build_default_panels()
    return {
        "ok": True,
        "file_name": os.path.basename(state.current_file) if state.current_file else "",
        "file_path": state.current_file or "",
        "n_panels": len(panels),
        "panels": panels,
    }


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
            "landing.html",
            size=(1440, 900),
            mode="default",   # uses Chrome/Edge if available
            block=True,
        )
    except (SystemExit, KeyboardInterrupt):
        pass
    except Exception as e:
        print(f"eel.start failed ({e}); retrying with mode=None (will print URL).")
        eel.start("landing.html", mode=None, host="localhost", port=8765, block=True)


if __name__ == "__main__":
    main()
