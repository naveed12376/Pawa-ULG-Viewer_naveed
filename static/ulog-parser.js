// ulog-parser.js — pure-JavaScript parser for PX4 ULog (.ulg) files.
//
// Replaces the Python `pyulog` dependency so the whole app can run as a static
// site (no server). Parses the binary ULog format entirely in the browser and
// returns a model with the same shape the rest of the app expects:
//
//   {
//     fileName, startTimestamp, lastTimestamp,
//     datasets: { topicKey: { name, multiId, data: { field: [numbers] } } },
//     msgInfo:  { key: value },     // ULog 'I' messages
//     params:   { key: value },     // ULog 'P'/'Q' messages
//   }
//
// The ULog spec adds explicit `_padding*` fields to keep every field aligned,
// so we read fields strictly in order with NO implicit padding, and simply skip
// storing the padding ones (matching pyulog's behaviour).
(function (global) {
  "use strict";

  const TYPE_SIZES = {
    int8_t: 1, uint8_t: 1, int16_t: 2, uint16_t: 2,
    int32_t: 4, uint32_t: 4, int64_t: 8, uint64_t: 8,
    float: 4, double: 8, bool: 1, char: 1,
  };

  const isPrimitive = (t) => Object.prototype.hasOwnProperty.call(TYPE_SIZES, t);

  // Split a "type[N]" token into base type + array length.
  function parseTypeToken(token, name) {
    let type = token, arraySize = 1;
    const br = token.indexOf("[");
    if (br >= 0) {
      type = token.slice(0, br);
      arraySize = parseInt(token.slice(br + 1, token.indexOf("]")), 10) || 1;
    }
    return { type, name, arraySize };
  }

  // Parse a format string: "msg_name:type field;type field;...".
  function parseFormat(str) {
    const colon = str.indexOf(":");
    if (colon < 0) return null;
    const name = str.slice(0, colon);
    const fields = [];
    for (const part of str.slice(colon + 1).split(";")) {
      if (!part) continue;
      const sp = part.indexOf(" ");
      if (sp < 0) continue;
      fields.push(parseTypeToken(part.slice(0, sp), part.slice(sp + 1)));
    }
    return { name, fields };
  }

  // Recursively flatten a message format into ordered read-instructions.
  // Each instruction: { name, type, size, store, isBlob }
  //   - primitive arrays expand to name[0], name[1], ...
  //   - nested message types expand to dotted paths (current.lat, ...)
  //   - char[N] in data is read as one opaque blob (not stored as a series)
  //   - `_padding*` fields are read for offset accuracy but not stored
  function flatten(formatName, formats, prefix, out, depth) {
    if (depth > 20) return;
    const fmt = formats[formatName];
    if (!fmt) return;
    for (const field of fmt.fields) {
      const isPad = field.name.indexOf("_padding") === 0;
      const base = prefix ? prefix + "." + field.name : field.name;

      if (isPrimitive(field.type)) {
        if (field.type === "char" && field.arraySize > 1) {
          out.push({ name: base, type: "char", size: field.arraySize, store: false, isBlob: true });
        } else if (field.arraySize > 1) {
          for (let i = 0; i < field.arraySize; i++) {
            out.push({ name: `${base}[${i}]`, type: field.type, size: TYPE_SIZES[field.type], store: !isPad });
          }
        } else {
          out.push({ name: base, type: field.type, size: TYPE_SIZES[field.type], store: !isPad });
        }
      } else {
        // nested message type
        if (field.arraySize > 1) {
          for (let i = 0; i < field.arraySize; i++) {
            flatten(field.type, formats, `${base}[${i}]`, out, depth + 1);
          }
        } else {
          flatten(field.type, formats, base, out, depth + 1);
        }
      }
    }
  }

  function makeReader(dv) {
    return function readValue(off, type) {
      switch (type) {
        case "int8_t":   return dv.getInt8(off);
        case "uint8_t":  return dv.getUint8(off);
        case "bool":     return dv.getUint8(off);
        case "char":     return dv.getUint8(off);
        case "int16_t":  return dv.getInt16(off, true);
        case "uint16_t": return dv.getUint16(off, true);
        case "int32_t":  return dv.getInt32(off, true);
        case "uint32_t": return dv.getUint32(off, true);
        case "float":    return dv.getFloat32(off, true);
        case "double":   return dv.getFloat64(off, true);
        case "int64_t":  return Number(dv.getBigInt64(off, true));
        case "uint64_t": return Number(dv.getBigUint64(off, true));
        default:         return null;
      }
    };
  }

  function parse(arrayBuffer, fileName) {
    const dv = new DataView(arrayBuffer);
    const u8 = new Uint8Array(arrayBuffer);
    const len = arrayBuffer.byteLength;
    const readValue = makeReader(dv);
    const decoder = new TextDecoder("ascii");
    const str = (o, n) => decoder.decode(u8.subarray(o, o + n));

    if (len < 16) throw new Error("File too small to be a ULog.");
    // Magic: 'U','L','o','g' then 0x01 0x12 0x35 then a version byte.
    if (!(u8[0] === 0x55 && u8[1] === 0x4c && u8[2] === 0x6f && u8[3] === 0x67)) {
      throw new Error("Not a ULog file (bad magic bytes).");
    }
    const startTimestamp = Number(dv.getBigUint64(8, true));

    const formats = {};      // name -> {name, fields}
    const subsById = {};     // msg_id -> subscription
    const msgInfo = {};
    const params = {};

    // Read an INFO/PARAM key/value pair starting at `p`, spanning `size` bytes.
    function readKeyValue(p, size, target) {
      const keyLen = dv.getUint8(p);
      const keyStr = str(p + 1, keyLen);            // "type name"
      const valOff = p + 1 + keyLen;
      const valLen = size - 1 - keyLen;
      const sp = keyStr.indexOf(" ");
      if (sp < 0) return;
      const field = parseTypeToken(keyStr.slice(0, sp), keyStr.slice(sp + 1));
      let value;
      if (field.type === "char") {
        value = str(valOff, valLen).replace(/\0+$/, "");
      } else if (field.arraySize > 1) {
        const sz = TYPE_SIZES[field.type] || 1;
        value = [];
        for (let i = 0; i < field.arraySize; i++) value.push(readValue(valOff + i * sz, field.type));
      } else {
        value = readValue(valOff, field.type);
      }
      target[field.name] = value;
    }

    let off = 16;
    while (off + 3 <= len) {
      const msgSize = dv.getUint16(off, true);
      const msgType = dv.getUint8(off + 2);
      off += 3;
      if (off + msgSize > len) break;               // truncated tail — stop cleanly
      const p = off;
      const ch = String.fromCharCode(msgType);

      try {
        if (ch === "F") {                            // format definition
          const f = parseFormat(str(p, msgSize));
          if (f) formats[f.name] = f;
        } else if (ch === "A") {                     // add subscription
          const multiId = dv.getUint8(p);
          const msgId = dv.getUint16(p + 1, true);
          const name = str(p + 3, msgSize - 3);
          const flat = [];
          flatten(name, formats, "", flat, 0);
          const data = {};
          for (const ins of flat) if (ins.store) data[ins.name] = [];
          subsById[msgId] = { name, multiId, flat, data };
        } else if (ch === "D") {                      // logged data
          const sub = subsById[dv.getUint16(p, true)];
          if (sub) {
            let o = p + 2;
            for (const ins of sub.flat) {
              if (ins.store) sub.data[ins.name].push(readValue(o, ins.type));
              o += ins.size;
            }
          }
        } else if (ch === "I") {
          readKeyValue(p, msgSize, msgInfo);
        } else if (ch === "M") {                      // multi-info: skip is_continued byte
          readKeyValue(p + 1, msgSize - 1, msgInfo);
        } else if (ch === "P") {
          readKeyValue(p, msgSize, params);
        } else if (ch === "Q") {                      // default param: skip type byte
          readKeyValue(p + 1, msgSize - 1, params);
        }
        // 'B' (flags), 'L'/'C' (text), 'S' (sync), 'O' (dropout), 'R' (remove) — ignored.
      } catch (_) { /* tolerate one bad message, keep going */ }

      off += msgSize;
    }

    // Key datasets by topic + multi-id (matches pyulog's naming). Subscriptions
    // that never received a data message are dropped, just like pyulog.
    const datasets = {};
    let lastTimestamp = startTimestamp;
    for (const id in subsById) {
      const sub = subsById[id];
      const ts = sub.data.timestamp;
      const n = ts ? ts.length : 0;
      if (n === 0) continue;
      const key = sub.name + (sub.multiId ? "_" + sub.multiId : "");
      datasets[key] = { name: sub.name, multiId: sub.multiId, data: sub.data };
      lastTimestamp = Math.max(lastTimestamp, ts[ts.length - 1]);
    }

    return { fileName: fileName || "", startTimestamp, lastTimestamp, datasets, msgInfo, params };
  }

  global.ULogParser = { parse };
})(typeof window !== "undefined" ? window : globalThis);
