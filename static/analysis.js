// analysis.js — client-side port of the PX4 ULog analysis that used to live in
// main.py. Every function takes a parsed `model` (from ULogParser.parse) and
// returns the same JSON shapes the old Flask endpoints returned, so the page
// controllers render exactly as before.
(function (global) {
  "use strict";

  const MAX_POINTS = 6000;     // downsample threshold (matches the old backend)
  const DEG = 180 / Math.PI;

  // ---------- small array helpers (stand-ins for the old numpy ops) ----------
  const isFiniteNum = (v) => typeof v === "number" && isFinite(v);

  function cleanArray(arr) {
    const out = new Array(arr.length);
    for (let i = 0; i < arr.length; i++) {
      const v = arr[i];
      out[i] = (typeof v === "number" && !isFinite(v)) ? null : v;
    }
    return out;
  }

  function downsample(t, y, maxPoints) {
    const n = t.length;
    const max = maxPoints || MAX_POINTS;
    if (n <= max) return [t, y];
    const step = Math.ceil(n / max);
    const tt = [], yy = [];
    for (let i = 0; i < n; i += step) { tt.push(t[i]); yy.push(y[i]); }
    return [tt, yy];
  }

  const mapArr = (a, fn) => { const o = new Array(a.length); for (let i = 0; i < a.length; i++) o[i] = fn(a[i]); return o; };
  const deg = (a) => mapArr(a, (v) => v * DEG);
  const neg = (a) => mapArr(a, (v) => -v);
  const scale = (a, k) => mapArr(a, (v) => v * k);

  // ---------- model accessors (mirror _get / _t) ----------
  function get(model, topic, field) {
    const d = model.datasets[topic];
    if (!d) return null;
    return d.data[field] || null;
  }
  function relTime(model, topic) {
    const d = model.datasets[topic];
    if (!d) return null;
    const ts = d.data.timestamp;
    if (!ts || ts.length === 0) return null;
    const t0 = ts[0];
    return mapArr(ts, (v) => (v - t0) / 1e6);
  }

  function topicKeys(model) { return Object.keys(model.datasets).sort(); }

  function topicSummary(model, key) {
    const d = model.datasets[key];
    const fields = Object.keys(d.data).filter((f) => f !== "timestamp").sort();
    const ts = d.data.timestamp;
    const n = ts ? ts.length : 0;
    const duration = (ts && ts.length > 1) ? (ts[ts.length - 1] - ts[0]) / 1e6 : 0;
    return { name: key, fields, n_samples: n, duration_s: duration };
  }

  function topicsSummary(model) {
    const keys = topicKeys(model);
    const topics = keys.map((k) => topicSummary(model, k));
    const n_fields = topics.reduce((a, t) => a + t.fields.length, 0);
    return {
      ok: true, loaded: true,
      file_name: model.fileName, file_path: model.fileName,
      topics, n_topics: topics.length, n_fields,
    };
  }

  // ---------- get_series ----------
  function getSeries(model, selections) {
    if (!model) return { ok: false, error: "No file loaded." };
    const byTopic = {};
    for (const sel of selections || []) {
      const topic = sel.topic, field = sel.field;
      if (!topic || !model.datasets[topic]) continue;
      const data = model.datasets[topic].data;
      if (field == null || field === "" || field === "*") {
        for (const f of Object.keys(data)) if (f !== "timestamp") (byTopic[topic] = byTopic[topic] || new Set()).add(f);
      } else if (field in data) {
        (byTopic[topic] = byTopic[topic] || new Set()).add(field);
      }
    }
    const groups = [];
    for (const topic of Object.keys(byTopic).sort()) {
      const t = relTime(model, topic);
      if (!t || t.length === 0) continue;
      const tClean = cleanArray(t);
      const series = [];
      for (const f of Array.from(byTopic[topic]).sort()) {
        const y = model.datasets[topic].data[f];
        if (!y) continue;
        series.push({ field: f, t: tClean, y: cleanArray(y) });
      }
      if (series.length) groups.push({ topic, series });
    }
    return { ok: true, groups };
  }

  // ---------- get_all_topics_data ----------
  function getAllTopics(model) {
    if (!model) return { ok: false, error: "No file loaded." };
    const groups = [];
    for (const topic of topicKeys(model)) {
      const t = relTime(model, topic);
      if (!t || t.length === 0) continue;
      const tClean = cleanArray(t);
      const data = model.datasets[topic].data;
      const series = [];
      for (const f of Object.keys(data).sort()) {
        if (f === "timestamp") continue;
        series.push({ field: f, t: tClean, y: cleanArray(data[f]) });
      }
      if (series.length) groups.push({ topic, series });
    }
    return { ok: true, groups };
  }

  // ---------- quaternion -> euler (degrees) ----------
  function quatEuler(q0, q1, q2, q3) {
    const n = q0.length, roll = new Array(n), pitch = new Array(n), yaw = new Array(n);
    for (let i = 0; i < n; i++) {
      const a = q0[i], b = q1[i], c = q2[i], d = q3[i];
      roll[i] = Math.atan2(2 * (a * b + c * d), 1 - 2 * (b * b + c * c)) * DEG;
      let sp = 2 * (a * c - d * b); sp = Math.max(-1, Math.min(1, sp));
      pitch[i] = Math.asin(sp) * DEG;
      yaw[i] = Math.atan2(2 * (a * d + b * c), 1 - 2 * (c * c + d * d)) * DEG;
    }
    return [roll, pitch, yaw];
  }
  function attEuler(model, topic) {
    const q0 = get(model, topic, "q[0]"), q1 = get(model, topic, "q[1]"),
          q2 = get(model, topic, "q[2]"), q3 = get(model, topic, "q[3]"), t = relTime(model, topic);
    if (!q0 || !q1 || !q2 || !q3 || !t) return null;
    const [r, p, y] = quatEuler(q0, q1, q2, q3);
    return [t, r, p, y];
  }
  function attEulerD(model, topic) {
    const q0 = get(model, topic, "q_d[0]"), q1 = get(model, topic, "q_d[1]"),
          q2 = get(model, topic, "q_d[2]"), q3 = get(model, topic, "q_d[3]"), t = relTime(model, topic);
    if (!q0 || !q1 || !q2 || !q3 || !t) return null;
    const [r, p, y] = quatEuler(q0, q1, q2, q3);
    return [t, r, p, y];
  }

  // series builder (mirror _series): align lengths, downsample, clean.
  function series(name, t, y, color, doDown) {
    if (!t || !y || t.length === 0 || y.length === 0) return null;
    if (t.length !== y.length) { const n = Math.min(t.length, y.length); t = t.slice(0, n); y = y.slice(0, n); }
    if (doDown !== false) { const r = downsample(t, y); t = r[0]; y = r[1]; }
    const out = { name, t: cleanArray(t), y: cleanArray(y) };
    if (color) out.color = color;
    return out;
  }

  // ---------- build_default_panels ----------
  function buildDefaultPanels(model) {
    const panels = [];
    const G = (tp, fl) => get(model, tp, fl);
    const T = (tp) => relTime(model, tp);

    const C_EST = "#ff8a4c", C_SP = "#3ecf8e", C_GT = "#bbbbbb", C_AUX = "#5dade2";
    const C_X = "#ff8a4c", C_Y = "#3ecf8e", C_Z = "#5dade2";

    // ---------- 0. GPS Trajectory on satellite map ----------
    let lat = G("vehicle_gps_position", "latitude_deg");
    let lon = G("vehicle_gps_position", "longitude_deg");
    if (!lat || !lon) { lat = G("sensor_gps", "latitude_deg"); lon = G("sensor_gps", "longitude_deg"); }
    if (lat && lon) {
      const la = [], lo = [];
      for (let i = 0; i < lat.length; i++) {
        const a = lat[i], b = lon[i];
        if (Math.abs(a) > 1e-6 && Math.abs(b) > 1e-6 && isFiniteNum(a) && isFiniteNum(b)) { la.push(a); lo.push(b); }
      }
      if (la.length > 1) {
        const [laD, loD] = downsample(la, lo);
        panels.push({
          title: "GPS Trajectory (Satellite)", type: "map", ylabel: "",
          series: [{ name: "Trajectory", lat: cleanArray(laD), lon: cleanArray(loD), color: "#a78bfa" }],
        });
      }
    }

    // ---------- 1. Position (X/Y) ----------
    const lpX = G("vehicle_local_position", "x"), lpY = G("vehicle_local_position", "y");
    const refLatArr = G("vehicle_local_position", "ref_lat"), refLonArr = G("vehicle_local_position", "ref_lon");
    const refLat = (refLatArr && refLatArr.length) ? refLatArr[refLatArr.length - 1] : null;
    const refLon = (refLonArr && refLonArr.length) ? refLonArr[refLonArr.length - 1] : null;
    const EARTH_R = 6371000.0;

    function projectNE(latA, lonA) {
      if (refLat == null || refLon == null) return [null, null];
      const cosRef = Math.cos(refLat * Math.PI / 180);
      const north = mapArr(latA, (v) => (v - refLat) * Math.PI / 180 * EARTH_R);
      const east = mapArr(lonA, (v) => (v - refLon) * Math.PI / 180 * EARTH_R * cosRef);
      return [north, east];
    }
    function xySeries(name, north, east, color, mode) {
      if (!north || !east || north.length === 0) return null;
      const n = [], e = [];
      for (let i = 0; i < north.length; i++) {
        if (isFiniteNum(north[i]) && isFiniteNum(east[i])) { n.push(north[i]); e.push(east[i]); }
      }
      if (n.length === 0) return null;
      const [eD, nD] = downsample(e, n);
      return { name, x: cleanArray(eD), y: cleanArray(nD), color, mode: mode || "lines" };
    }

    const xy = [];
    if (lpX && lpY) { const s = xySeries("Estimated", lpX, lpY, C_EST, "lines"); if (s) xy.push(s); }
    const spX = G("vehicle_local_position_setpoint", "x"), spY = G("vehicle_local_position_setpoint", "y");
    if (spX && spY) { const s = xySeries("Setpoint", spX, spY, C_SP, "lines"); if (s) xy.push(s); }
    const gtX = G("vehicle_local_position_groundtruth", "x"), gtY = G("vehicle_local_position_groundtruth", "y");
    if (gtX && gtY) { const s = xySeries("Groundtruth", gtX, gtY, C_GT, "lines"); if (s) xy.push(s); }

    const gpsLat = G("vehicle_gps_position", "latitude_deg"), gpsLon = G("vehicle_gps_position", "longitude_deg");
    if (gpsLat && gpsLon && refLat != null) {
      const la = [], lo = [];
      for (let i = 0; i < gpsLat.length; i++) {
        const a = gpsLat[i], b = gpsLon[i];
        if (Math.abs(a) > 1e-6 && Math.abs(b) > 1e-6 && isFiniteNum(a) && isFiniteNum(b)) { la.push(a); lo.push(b); }
      }
      if (la.length) { const [n, e] = projectNE(la, lo); const s = xySeries("GPS (projected)", n, e, "#5dade2", "lines"); if (s) xy.push(s); }
    }

    const pspLat = G("position_setpoint_triplet", "current.lat"), pspLon = G("position_setpoint_triplet", "current.lon");
    const pspValid = G("position_setpoint_triplet", "current.valid");
    if (pspLat && pspLon && refLat != null) {
      let la = [], lo = [];
      for (let i = 0; i < pspLat.length; i++) {
        const a = pspLat[i], b = pspLon[i];
        const ok = Math.abs(a) > 1e-6 && Math.abs(b) > 1e-6 && isFiniteNum(a) && isFiniteNum(b) &&
                   (!pspValid || pspValid[i] > 0);
        if (ok) { la.push(a); lo.push(b); }
      }
      // keep distinct consecutive waypoints
      if (la.length > 1) {
        const la2 = [la[0]], lo2 = [lo[0]];
        for (let i = 1; i < la.length; i++) if (la[i] !== la[i - 1] || lo[i] !== lo[i - 1]) { la2.push(la[i]); lo2.push(lo[i]); }
        la = la2; lo = lo2;
      }
      if (la.length) { const [n, e] = projectNE(la, lo); const s = xySeries("Position Setpoints", n, e, "#e879c5", "markers"); if (s) xy.push(s); }
    }
    if (xy.length) panels.push({ title: "Position (X/Y)", type: "scatter_xy", xlabel: "[m] East", ylabel: "[m] North", series: xy });

    // ---------- 2. Altitude Estimate ----------
    let ss = [];
    let s = series("GPS Altitude (MSL)", T("sensor_gps"), G("sensor_gps", "altitude_msl_m"), "#ff8a4c"); if (s) ss.push(s);
    s = series("Barometer Altitude", T("vehicle_air_data"), G("vehicle_air_data", "baro_alt_meter"), "#3ecf8e"); if (s) ss.push(s);
    const fusedZ = G("vehicle_local_position", "z");
    if (fusedZ) { s = series("Fused Altitude Estimation", T("vehicle_local_position"), neg(fusedZ), "#5dade2"); if (s) ss.push(s); }
    const spZ = G("vehicle_local_position_setpoint", "z");
    if (spZ) { s = series("Altitude Setpoint", T("vehicle_local_position_setpoint"), neg(spZ), "#e879c5"); if (s) ss.push(s); }
    if (ss.length) panels.push({ title: "Altitude Estimate", ylabel: "[m]", series: ss });

    // ---------- 3-8. Attitude angles & rates ----------
    const att = attEuler(model, "vehicle_attitude");
    const attSp = attEulerD(model, "vehicle_attitude_setpoint");
    const attGt = attEuler(model, "vehicle_attitude_groundtruth");
    const rateT = T("vehicle_angular_velocity");
    const rateX = G("vehicle_angular_velocity", "xyz[0]"), rateY = G("vehicle_angular_velocity", "xyz[1]"), rateZ = G("vehicle_angular_velocity", "xyz[2]");
    const rspT = T("vehicle_rates_setpoint");
    const rspR = G("vehicle_rates_setpoint", "roll"), rspP = G("vehicle_rates_setpoint", "pitch"), rspY = G("vehicle_rates_setpoint", "yaw");
    const integT = T("rate_ctrl_status");
    const integR = G("rate_ctrl_status", "rollspeed_integ"), integP = G("rate_ctrl_status", "pitchspeed_integ"), integY = G("rate_ctrl_status", "yawspeed_integ");

    function anglePanel(title, idx) {
      const word = title.split(" ")[0];
      const a = [];
      if (att) { const x = series(`${word} Estimated`, att[0], att[idx], C_EST); if (x) a.push(x); }
      if (attSp) { const x = series(`${word} Setpoint`, attSp[0], attSp[idx], C_SP); if (x) a.push(x); }
      if (attGt) { const x = series(`${word} Groundtruth`, attGt[0], attGt[idx], C_GT); if (x) a.push(x); }
      if (a.length) panels.push({ title, ylabel: "[deg]", series: a });
    }
    function ratePanel(title, rateArr, spArr, integArr) {
      const word = title.split(" ")[0];
      const a = [];
      if (rateArr) { const x = series(`${word} Rate Estimated`, rateT, deg(rateArr), C_EST); if (x) a.push(x); }
      if (spArr) { const x = series(`${word} Rate Setpoint`, rspT, deg(spArr), C_SP); if (x) a.push(x); }
      if (integArr) { const x = series(`${word} Rate Integral [-30, 30]`, integT, integArr, C_AUX); if (x) a.push(x); }
      if (a.length) panels.push({ title, ylabel: "[deg/s]", series: a });
    }
    anglePanel("Roll Angle", 1);  ratePanel("Roll Angular Rate", rateX, rspR, integR);
    anglePanel("Pitch Angle", 2); ratePanel("Pitch Angular Rate", rateY, rspP, integP);
    anglePanel("Yaw Angle", 3);   ratePanel("Yaw Angular Rate", rateZ, rspY, integY);

    // ---------- 9-11. Local Position X / Y / Z ----------
    for (const [axis, label] of [["x", "Local Position X"], ["y", "Local Position Y"], ["z", "Local Position Z"]]) {
      const a = [];
      let x = series(`${axis.toUpperCase()} Estimated`, T("vehicle_local_position"), G("vehicle_local_position", axis), C_EST); if (x) a.push(x);
      x = series(`${axis.toUpperCase()} Setpoint`, T("vehicle_local_position_setpoint"), G("vehicle_local_position_setpoint", axis), C_SP); if (x) a.push(x);
      if (a.length) panels.push({ title: label, ylabel: "[m]", series: a });
    }

    // ---------- 12. Velocity ----------
    ss = [];
    for (const [axis, c] of [["vx", C_X], ["vy", C_Y], ["vz", C_Z]]) {
      s = series(axis.toUpperCase(), T("vehicle_local_position"), G("vehicle_local_position", axis), c); if (s) ss.push(s);
    }
    for (const [axis, name, c] of [["vx", "X Setpoint", "#ffb38a"], ["vy", "Y Setpoint", "#8be0b8"], ["vz", "Z Setpoint", "#a0d2eb"]]) {
      s = series(name, T("vehicle_local_position_setpoint"), G("vehicle_local_position_setpoint", axis), c); if (s) ss.push(s);
    }
    if (ss.length) panels.push({ title: "Velocity", ylabel: "[m/s]", series: ss });

    // ---------- 13. Manual Control Inputs ----------
    ss = [];
    for (const [f, name, c] of [["roll", "Y / Roll", "#ff8a4c"], ["pitch", "X / Pitch", "#3ecf8e"], ["yaw", "Yaw", "#5dade2"],
                                ["throttle", "Throttle [-1, 1]", "#222831"], ["aux1", "Aux1", "#fbbf24"], ["aux2", "Aux2", "#60a5fa"]]) {
      s = series(name, T("manual_control_setpoint"), G("manual_control_setpoint", f), c); if (s) ss.push(s);
    }
    if (ss.length) panels.push({ title: "Manual Control Inputs (Radio or Joystick)", ylabel: "", series: ss });

    // ---------- 14. Actuator Controls ----------
    ss = [];
    for (const [i, name, c] of [[0, "Roll", "#ff8a4c"], [1, "Pitch", "#3ecf8e"], [2, "Yaw", "#5dade2"]]) {
      s = series(name, T("vehicle_torque_setpoint"), G("vehicle_torque_setpoint", `xyz[${i}]`), c); if (s) ss.push(s);
    }
    s = series("Thrust (up)", T("vehicle_thrust_setpoint"), G("vehicle_thrust_setpoint", "xyz[2]"), "#222831"); if (s) ss.push(s);
    s = series("Thrust (forward)", T("vehicle_thrust_setpoint"), G("vehicle_thrust_setpoint", "xyz[0]"), "#fbbf24"); if (s) ss.push(s);
    if (ss.length) panels.push({ title: "Actuator Controls", ylabel: "", series: ss });

    // ---------- 15. Motor Outputs ----------
    ss = [];
    const motorColors = ["#ff8a4c", "#3ecf8e", "#5dade2", "#222831", "#fbbf24", "#a78bfa", "#f472b6", "#67e8f9"];
    for (let i = 0; i < 8; i++) {
      s = series(`Motor ${i + 1}`, T("actuator_motors"), G("actuator_motors", `control[${i}]`), motorColors[i % motorColors.length]);
      if (s && !s.y.slice(0, 50).every((v) => v == null || v === 0)) ss.push(s);
      else if (s && i < 4) ss.push(s);
    }
    if (ss.length) panels.push({ title: "Motor Outputs", ylabel: "", series: ss });

    // ---------- 16. Raw Acceleration ----------
    ss = [];
    for (const [i, name, c] of [[0, "X", C_X], [1, "Y", C_Y], [2, "Z", C_Z]]) {
      s = series(name, T("sensor_combined"), G("sensor_combined", `accelerometer_m_s2[${i}]`), c); if (s) ss.push(s);
    }
    if (ss.length) panels.push({ title: "Raw Acceleration", ylabel: "[m/s²]", series: ss });

    // ---------- 17. Raw Angular Speed (Gyroscope) ----------
    ss = [];
    for (const [i, name, c] of [[0, "X", C_X], [1, "Y", C_Y], [2, "Z", C_Z]]) {
      const gy = G("sensor_combined", `gyro_rad[${i}]`);
      if (gy) { s = series(name, T("sensor_combined"), deg(gy), c); if (s) ss.push(s); }
    }
    if (ss.length) panels.push({ title: "Raw Angular Speed (Gyroscope)", ylabel: "[deg/s]", series: ss });

    // ---------- 18. Raw Magnetic Field Strength ----------
    ss = [];
    for (const [i, name, c] of [[0, "X", C_X], [1, "Y", C_Y], [2, "Z", C_Z]]) {
      s = series(name, T("vehicle_magnetometer"), G("vehicle_magnetometer", `magnetometer_ga[${i}]`), c); if (s) ss.push(s);
    }
    if (ss.length) panels.push({ title: "Raw Magnetic Field Strength", ylabel: "[gauss]", series: ss });

    // ---------- 19. Distance Sensor ----------
    ss = [];
    s = series("Estimated Distance Bottom [m]", T("vehicle_local_position"), G("vehicle_local_position", "dist_bottom"), C_EST); if (s) ss.push(s);
    s = series("Dist Bottom Valid", T("vehicle_local_position"), G("vehicle_local_position", "dist_bottom_valid"), C_GT); if (s) ss.push(s);
    if (ss.length) panels.push({ title: "Distance Sensor", ylabel: "[m]", series: ss });

    // ---------- 20. GPS Uncertainty ----------
    ss = [];
    for (const [f, name, c] of [["eph", "Horizontal position accuracy [m]", "#ff8a4c"], ["epv", "Vertical position accuracy [m]", "#3ecf8e"],
                                ["hdop", "Horizontal dilution of precision [m]", "#5dade2"], ["vdop", "Vertical dilution of precision [m]", "#222831"],
                                ["s_variance_m_s", "Speed accuracy [m/s]", "#fbbf24"], ["satellites_used", "Num Satellites used", "#60a5fa"],
                                ["fix_type", "GPS Fix", "#e879c5"]]) {
      s = series(name, T("sensor_gps"), G("sensor_gps", f), c); if (s) ss.push(s);
    }
    if (ss.length) panels.push({ title: "GPS Uncertainty", ylabel: "", series: ss });

    // ---------- 21. GPS Noise & Jamming ----------
    ss = [];
    s = series("Noise per ms", T("sensor_gps"), G("sensor_gps", "noise_per_ms"), "#ff8a4c"); if (s) ss.push(s);
    s = series("Jamming Indicator", T("sensor_gps"), G("sensor_gps", "jamming_indicator"), "#3ecf8e"); if (s) ss.push(s);
    if (ss.length) panels.push({ title: "GPS Noise & Jamming", ylabel: "", series: ss });

    // ---------- 22. Power (Battery) ----------
    ss = [];
    s = series("Battery Voltage [V]", T("battery_status"), G("battery_status", "voltage_v"), "#ff8a4c"); if (s) ss.push(s);
    s = series("Battery Current [A]", T("battery_status"), G("battery_status", "current_a"), "#3ecf8e"); if (s) ss.push(s);
    const dmah = G("battery_status", "discharged_mah");
    if (dmah) { s = series("Discharged Amount [mAh / 100]", T("battery_status"), scale(dmah, 0.01), "#5dade2"); if (s) ss.push(s); }
    const rem = G("battery_status", "remaining");
    if (rem) { s = series("Battery remaining [0=empty, 10=full]", T("battery_status"), scale(rem, 10), "#222831"); if (s) ss.push(s); }
    s = series("OCV Estimate [V]", T("battery_status"), G("battery_status", "ocv_estimate"), "#fbbf24"); if (s) ss.push(s);
    s = series("Internal Resistance Estimate [mOhm]", T("battery_status"), G("battery_status", "internal_resistance_estimate"), "#60a5fa"); if (s) ss.push(s);
    const v5 = G("system_power", "voltage5v_v");
    if (v5) { s = series("5 V", T("system_power"), v5, "#e879c5"); if (s) ss.push(s); }
    if (ss.length) panels.push({ title: "Power", ylabel: "[V] / [A] / [%]", series: ss });

    // ---------- 23. Temperature ----------
    ss = [];
    s = series("Baro temperature", T("sensor_baro"), G("sensor_baro", "temperature"), "#ff8a4c"); if (s) ss.push(s);
    s = series("Accel temperature", T("sensor_accel"), G("sensor_accel", "temperature"), "#5dade2"); if (s) ss.push(s);
    s = series("Battery temperature", T("battery_status"), G("battery_status", "temperature"), "#e879c5"); if (s) ss.push(s);
    if (ss.length) panels.push({ title: "Temperature", ylabel: "[°C]", series: ss });

    // ---------- 24. Failsafe Flags ----------
    ss = [];
    for (const [f, name, c] of [["failsafe", "In Failsafe", "#ff8a4c"], ["failsafe_and_user_took_over", "User Took Over", "#3ecf8e"],
                                ["manual_control_signal_lost", "manual control signal lost", "#5dade2"], ["gcs_connection_lost", "gcs connection lost", "#222831"],
                                ["open_drone_id_system_healthy", "remote id unhealthy", "#fbbf24"]]) {
      s = series(name, T("vehicle_status"), G("vehicle_status", f), c); if (s) ss.push(s);
    }
    if (ss.length) panels.push({ title: "Failsafe Flags", ylabel: "", series: ss });

    // ---------- 25. CPU & RAM ----------
    ss = [];
    s = series("RAM Usage", T("cpuload"), G("cpuload", "ram_usage"), "#3ecf8e"); if (s) ss.push(s);
    s = series("CPU Load", T("cpuload"), G("cpuload", "load"), "#5dade2"); if (s) ss.push(s);
    if (ss.length) panels.push({ title: "CPU & RAM", ylabel: "", series: ss });

    return panels;
  }

  function getDefaultPlotData(model) {
    if (!model) return { ok: false, error: "No file loaded." };
    const panels = buildDefaultPanels(model);
    return { ok: true, file_name: model.fileName, file_path: model.fileName, n_panels: panels.length, panels };
  }

  // ---------- file info / flight stats ----------
  const AIRFRAME_NAMES = {
    4001: ["Generic Quadcopter", "Quadrotor x"], 4002: ["Generic 250 Racer", "Quadrotor x"],
    4010: ["Generic Quadplane VTOL", "Standard VTOL"], 4011: ["Tiltrotor VTOL", "Tiltrotor VTOL"],
    4012: ["Standard VTOL", "Standard VTOL"], 4013: ["Tailsitter VTOL", "Tailsitter VTOL"],
    4015: ["3DR Iris", "Quadrotor x"], 4017: ["HippoCampus AUV", "AUV"], 4019: ["Holybro X500", "Quadrotor x"],
    6001: ["Generic Hexarotor", "Hexarotor x"], 8001: ["Generic Octacopter", "Octorotor x"],
  };

  function decodeVersion(v) {
    if (typeof v !== "number" || v <= 0) return "";
    const major = (v >> 24) & 0xff, minor = (v >> 16) & 0xff, patch = (v >> 8) & 0xff, tb = v & 0xff;
    const suffix = { 0: "dev", 64: "alpha", 128: "beta", 192: "rc", 255: "" }[tb] || "";
    const base = `v${major}.${minor}.${patch}`;
    return suffix ? `${base} (${suffix})` : base;
  }
  function decodeOsVersion(v) {
    if (typeof v !== "number" || v <= 0) return "";
    return `v${(v >> 24) & 0xff}.${(v >> 16) & 0xff}.${(v >> 8) & 0xff}`;
  }

  function nanmax(arr) { let m = -Infinity; for (const v of arr) if (isFiniteNum(v) && v > m) m = v; return m === -Infinity ? 0 : m; }
  function nanmin(arr) { let m = Infinity; for (const v of arr) if (isFiniteNum(v) && v < m) m = v; return m === Infinity ? 0 : m; }

  function getFileInfo(model) {
    if (!model) return { ok: false, error: "No file loaded." };
    const info = model.msgInfo || {}, params = model.params || {};

    const airframeId = parseInt(params.SYS_AUTOSTART || 0, 10) || 0;
    const [afGroup, afName] = AIRFRAME_NAMES[airframeId] || ["", ""];

    const swFull = info.ver_sw || "";
    const swShort = typeof swFull === "string" ? swFull.slice(0, 8) : "";
    const swDecoded = decodeVersion(info.ver_sw_release);
    const osDecoded = decodeOsVersion(info.sys_os_ver_release);
    const ekf2 = params.EKF2_EN != null ? params.EKF2_EN : 1;
    const estimator = ekf2 ? "EKF2" : "—";

    const durationS = (model.lastTimestamp - model.startTimestamp) / 1e6;

    // Flight time = sum of intervals where the vehicle was NOT landed.
    let flightTimeS = 0;
    const vld = model.datasets.vehicle_land_detected;
    if (vld && vld.data.landed && vld.data.timestamp) {
      const ts = vld.data.timestamp, landed = vld.data.landed;
      if (ts.length > 1) {
        for (let i = 0; i < ts.length - 1; i++) if (!landed[i]) flightTimeS += (ts[i + 1] - ts[i]);
        flightTimeS /= 1e6;
      }
    }
    if (flightTimeS === 0) {
      const aa = model.datasets.actuator_armed;
      if (aa && aa.data.armed && aa.data.timestamp) {
        const ts = aa.data.timestamp, armed = aa.data.armed;
        if (ts.length > 1) {
          for (let i = 0; i < ts.length - 1; i++) if (armed[i]) flightTimeS += (ts[i + 1] - ts[i]);
          flightTimeS /= 1e6;
        }
      }
    }

    // Lifetime flight time — LND_FLIGHT_T_HI/LO form a uint64 microsecond counter.
    let lifetimeS = 0;
    const hi = params.LND_FLIGHT_T_HI || 0, lo = params.LND_FLIGHT_T_LO || 0;
    if (hi || lo) lifetimeS = (hi * Math.pow(2, 32) + lo) / 1e6;

    let distanceM = 0, maxAltDiff = 0, maxV = 0, maxVh = 0, maxVzUp = 0, maxVzDn = 0;
    const lp = model.datasets.vehicle_local_position;
    if (lp) {
      const x = lp.data.x, y = lp.data.y, z = lp.data.z, vx = lp.data.vx, vy = lp.data.vy, vz = lp.data.vz;
      if (x && y && x.length > 1) {
        for (let i = 1; i < x.length; i++) {
          const dx = x[i] - x[i - 1], dy = y[i] - y[i - 1];
          const d = Math.sqrt(dx * dx + dy * dy);
          if (isFiniteNum(d)) distanceM += d;
        }
      }
      if (z && z.length) { const zf = z.filter(isFiniteNum); if (zf.length) maxAltDiff = Math.max(...[nanmax(zf) - nanmin(zf)]); }
      if (vx && vy && vz && vx.length) {
        const speed = [], speedH = [], up = [], dn = [];
        for (let i = 0; i < vx.length; i++) {
          speed.push(Math.sqrt(vx[i] * vx[i] + vy[i] * vy[i] + vz[i] * vz[i]));
          speedH.push(Math.sqrt(vx[i] * vx[i] + vy[i] * vy[i]));
          up.push(-vz[i]); dn.push(vz[i]);
        }
        maxV = nanmax(speed); maxVh = nanmax(speedH); maxVzUp = nanmax(up); maxVzDn = nanmax(dn);
      }
    }

    let maxTilt = 0;
    const att = model.datasets.vehicle_attitude;
    if (att && att.data["q[1]"] && att.data["q[2]"]) {
      const q1 = att.data["q[1]"], q2 = att.data["q[2]"];
      const tilt = [];
      for (let i = 0; i < q1.length; i++) {
        let ct = 1 - 2 * (q1[i] * q1[i] + q2[i] * q2[i]); ct = Math.max(-1, Math.min(1, ct));
        tilt.push(Math.acos(ct) * DEG);
      }
      maxTilt = nanmax(tilt);
    }

    const avgSpeed = (flightTimeS > 0 && distanceM > 0) ? distanceM / flightTimeS : 0;

    return {
      ok: true,
      airframe_group: afGroup, airframe_name: afName, airframe_id: airframeId,
      hardware: info.ver_hw || "—",
      sw_version: swDecoded || "—", sw_hash: swShort,
      branch: info.ver_sw_branch || "—",
      os_label: ((info.sys_os_name || "") + (osDecoded ? `, ${osDecoded}` : "")).replace(/^,\s*|,\s*$/g, "") || "—",
      estimator,
      logging_duration_s: durationS, flight_time_s: flightTimeS, lifetime_s: lifetimeS,
      distance_m: distanceM, max_altitude_diff_m: maxAltDiff,
      avg_speed_kmh: avgSpeed * 3.6, max_speed_kmh: maxV * 3.6,
      max_speed_horizontal_kmh: maxVh * 3.6, max_speed_up_kmh: maxVzUp * 3.6, max_speed_down_kmh: maxVzDn * 3.6,
      max_tilt_deg: maxTilt,
    };
  }

  global.PawaAnalysis = {
    topicsSummary, getSeries, getAllTopics, getDefaultPlotData, buildDefaultPanels, getFileInfo,
  };
})(typeof window !== "undefined" ? window : globalThis);
