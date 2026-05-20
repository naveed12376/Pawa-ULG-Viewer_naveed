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
import numpy as np

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


def _series(name: str, t, y, color: Optional[str] = None) -> Optional[dict]:
    if t is None or y is None:
        return None
    if len(t) == 0 or len(y) == 0:
        return None
    if len(t) != len(y):
        n = min(len(t), len(y))
        t = t[:n]; y = y[:n]
    out = {"name": name, "t": _clean_array(np.asarray(t)), "y": _clean_array(np.asarray(y))}
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

    # ---------- 1. GPS Trajectory (local X/Y or lat/lon scatter) ----------
    lp_x = _get("vehicle_local_position", "x")
    lp_y = _get("vehicle_local_position", "y")
    if lp_x is not None and lp_y is not None:
        panels.append({
            "title": "Position (X/Y)",
            "type": "scatter_xy",
            "xlabel": "Y [m] (East)",
            "ylabel": "X [m] (North)",
            "series": [{
                "name": "Trajectory",
                "x": _clean_array(np.asarray(lp_y)),
                "y": _clean_array(np.asarray(lp_x)),
                "color": "#a78bfa",
            }],
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
