/* Delta OS dashboard. Plain JS, no libraries, no network except this app's own /api. All text is inserted with textContent. */
(function () {
"use strict";
const $ = (s, r) => (r || document).querySelector(s);
const $$ = (s, r) => Array.from((r || document).querySelectorAll(s));
const reduceMotion = window.matchMedia && matchMedia("(prefers-reduced-motion: reduce)").matches;

/* ------------------------------------------------------------------ tiny helpers */
function h(tag, props, ...kids) {
  const e = document.createElement(tag);
  if (props) for (const k in props) {
    const v = props[k];
    if (v == null || v === false) continue;
    if (k === "class") e.className = v;
    else if (k === "text") e.textContent = v;
    else if (k.startsWith("on")) e.addEventListener(k.slice(2), v);
    else if (k === "data") for (const d in v) e.dataset[d] = v[d];
    else e.setAttribute(k, v === true ? "" : v);
  }
  for (const c of kids.flat()) if (c != null && c !== false) e.append(c.nodeType ? c : document.createTextNode(String(c)));
  return e;
}
const ICONS = { // 24x24 stroke icons, static strings (never built from data)
  home: '<path d="M4 11l8-7 8 7v9a1 1 0 0 1-1 1h-4v-6H9v6H5a1 1 0 0 1-1-1z"/>',
  memory: '<path d="M9 4a3 3 0 0 0-3 3 3 3 0 0 0-2 5 3 3 0 0 0 2 5 3 3 0 0 0 6 1V5a2 2 0 0 0-3-1zM15 4a3 3 0 0 1 3 3 3 3 0 0 1 2 5 3 3 0 0 1-2 5 3 3 0 0 1-6 1"/>',
  tasks: '<rect x="4" y="4" width="16" height="16" rx="3"/><path d="M8 12l3 3 5-6"/>',
  routines: '<circle cx="12" cy="12" r="8"/><path d="M12 7v5l3 2"/>',
  activity: '<path d="M3 12h4l3-8 4 16 3-8h4"/>',
  modules: '<rect x="6" y="6" width="12" height="12" rx="2"/><path d="M9 3v3M15 3v3M9 18v3M15 18v3M3 9h3M3 15h3M18 9h3M18 15h3"/>',
  files: '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
  controls: '<path d="M5 6h9M18 6h1M5 12h3M12 12h7M5 18h11M20 18h-1"/><circle cx="16" cy="6" r="2"/><circle cx="10" cy="12" r="2"/><circle cx="18" cy="18" r="2"/>',
  bell: '<path d="M6 16V11a6 6 0 0 1 12 0v5l2 2H4zM10 20a2 2 0 0 0 4 0"/>',
  chat: '<path d="M4 5h16v11H9l-5 4z"/>',
  sun: '<circle cx="12" cy="12" r="4"/><path d="M12 3v2M12 19v2M3 12h2M19 12h2M5.6 5.6 7 7M17 17l1.4 1.4M5.6 18.4 7 17M17 7l1.4-1.4"/>',
  power: '<path d="M12 3v9M6.3 7.5a8 8 0 1 0 11.4 0"/>',
  mic: '<rect x="9" y="3" width="6" height="12" rx="3"/><path d="M5 11a7 7 0 0 0 14 0M12 18v3"/>',
  send: '<path d="M5 12h14M13 6l6 6-6 6"/>',
  code: '<path d="M8 8l-4 4 4 4M16 8l4 4-4 4M14 5l-4 14"/>',
  globe: '<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3c3 3 3 15 0 18M12 3c-3 3-3 15 0 18"/>',
  terminal: '<rect x="3" y="5" width="18" height="14" rx="2"/><path d="M7 10l3 2-3 2M12 15h5"/>',
  search: '<circle cx="11" cy="11" r="6"/><path d="M20 20l-4-4"/>',
  note: '<path d="M6 3h9l4 4v14H6z"/><path d="M14 3v5h5M9 13h7M9 17h5"/>',
  camera: '<path d="M4 8h3l2-3h6l2 3h3v11H4z"/><circle cx="12" cy="13" r="3.5"/>',
  lock: '<rect x="5" y="11" width="14" height="9" rx="2"/><path d="M8 11V8a4 4 0 0 1 8 0v3"/>',
  volume: '<path d="M4 10v4h4l5 4V6l-5 4zM16 9a4 4 0 0 1 0 6M18.5 6.5a8 8 0 0 1 0 11"/>',
  mute: '<path d="M4 10v4h4l5 4V6l-5 4zM17 9l4 6M21 9l-4 6"/>',
  play: '<path d="M7 5l12 7-12 7zM3 5v14"/>',
  shield: '<path d="M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  check: '<path d="M5 12l4 4 10-10"/>',
  x: '<path d="M6 6l12 12M18 6 6 18"/>',
  file: '<path d="M6 3h9l4 4v14H6z"/><path d="M14 3v5h5"/>',
  image: '<rect x="3" y="4" width="18" height="16" rx="2"/><circle cx="9" cy="10" r="2"/><path d="M21 17l-5-5-9 8"/>',
  chev: '<path d="M9 6l6 6-6 6"/>',
  bolt: '<path d="M13 3 5 14h6l-1 7 8-11h-6z"/>',
  clock: '<circle cx="12" cy="12" r="8"/><path d="M12 8v4l3 2"/>',
  battery: '<rect x="3" y="8" width="16" height="9" rx="2"/><path d="M21 11v3"/>',
  list: '<path d="M8 6h12M8 12h12M8 18h12M4 6h.01M4 12h.01M4 18h.01"/>',
  spark: '<path d="M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8zM18.5 15l.8 2.2 2.2.8-2.2.8-.8 2.2-.8-2.2-2.2-.8 2.2-.8z"/>',
  undo: '<path d="M9 14 4 9l5-5M4 9h10a6 6 0 0 1 0 12h-4"/>',
  stop: '<rect x="6" y="6" width="12" height="12" rx="2"/>',
  refresh: '<path d="M20 11a8 8 0 1 0-2.3 5.7M20 5v6h-6"/>',
  branch: '<circle cx="6" cy="6" r="2"/><circle cx="6" cy="18" r="2"/><circle cx="18" cy="9" r="2"/><path d="M6 8v8M18 11c0 4-6 3-12 5"/>',
  link: '<path d="M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1M14 10a4 4 0 0 0-5.7 0l-3 3A4 4 0 0 0 11 18.7l1-1"/>',
  eye: '<path d="M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>',
};
function ic(name, cls) {
  const s = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  s.setAttribute("viewBox", "0 0 24 24"); s.setAttribute("fill", "none"); s.setAttribute("stroke", "currentColor");
  s.setAttribute("stroke-width", "1.7"); s.setAttribute("stroke-linecap", "round"); s.setAttribute("stroke-linejoin", "round");
  s.setAttribute("aria-hidden", "true"); s.setAttribute("class", "ic" + (cls ? " " + cls : ""));
  s.innerHTML = ICONS[name] || ""; // constant strings only
  return s;
}
const fmtBytes = (n) => { const u = ["B", "KB", "MB", "GB", "TB"]; let i = 0; n = +n || 0; while (n >= 1024 && i < 4) { n /= 1024; i++; } return (i ? n.toFixed(n < 10 ? 1 : 0) : n.toFixed(0)) + " " + u[i]; };
const fmtPair = (used, total) => { const u = ["B", "KB", "MB", "GB", "TB"]; let i = 0, t = +total || 0; while (t >= 1024 && i < 4) { t /= 1024; i++; } const d = (+used || 0) / Math.pow(1024, i); return (d < 10 ? d.toFixed(1) : d.toFixed(0)) + "/" + (t < 10 ? t.toFixed(1) : t.toFixed(0)) + " " + u[i]; };
const fmtRate = (bps) => fmtBytes(bps) + "/s";
const clampPct = (v) => Math.max(0, Math.min(100, +v || 0));
function ago(ts) { const s = Math.max(0, Date.now() / 1000 - ts); if (s < 60) return "just now"; if (s < 3600) return Math.floor(s / 60) + "m ago"; if (s < 86400) return Math.floor(s / 3600) + "h ago"; return Math.floor(s / 86400) + "d ago"; }

/* ------------------------------------------------------------------ api */
async function api(path, opts) {
  const o = Object.assign({ credentials: "same-origin", headers: { "Content-Type": "application/json" } }, opts || {});
  const r = await fetch(path, o);
  if (r.status === 401) { document.body.replaceChildren(h("p", { style: "padding:40px;font:16px system-ui;color:#ccc", text: "Session expired. Open the full link printed in the Delta window." })); throw new Error("auth"); }
  if (!r.ok) { let d = ""; try { d = (await r.json()).detail; } catch (e) { /* ignore */ } throw new Error(typeof d === "string" && d ? d : "request failed (" + r.status + ")"); }
  return r.json();
}
const post = (p, body) => api(p, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) });
const del = (p) => api(p, { method: "DELETE" });

/* ------------------------------------------------------------------ state */
const S = { state: null, status: null, brief: null, vitals: null, procs: null, tasks: null, files: null, mods: null, routines: null, activity: null, safety: null, controls: null, notes: null, view: null, coreState: "idle", clockOffset: 0 };
const NAV = [["overview", "Overview", "home"], ["tasks", "Tasks", "tasks"], ["memory", "Memory", "memory"], ["routines", "Routines", "routines"], ["vibe", "Vibe Coding", "spark"], ["activity", "Activity", "activity"], ["modules", "Modules", "modules"], ["files", "Files", "files"], ["controls", "Controls", "controls"]];

/* ------------------------------------------------------------------ toasts */
function toast(title, text, kind) {
  const t = h("div", { class: "toast " + (kind || ""), role: "status" }, h("b", { text: title }), document.createTextNode(text));
  $("#toasts").append(t); setTimeout(() => t.remove(), 5200);
}
function reportResult(out, okTitle) {
  const r = out.result || out;
  if (out.state) applyState(out.state);
  if (r.status === "pending") { toast("Needs your approval", r.text, "warn"); pulseTray(); }
  else if (r.status === "ok") toast(okTitle || "Done", r.text);
  else if (r.status === "dry_run") toast("Dry-run", r.text);
  else toast(r.status === "blocked" || r.status === "killed" ? "Blocked" : "Couldn't do that", r.text, "err");
  return r;
}
function pulseTray() { refreshState(); }

/* ------------------------------------------------------------------ core / status */
const CORE_LABEL = { idle: "DELTA IS IDLE", listening: "DELTA IS LISTENING", thinking: "DELTA IS THINKING", speaking: "DELTA IS RESPONDING", paused: "DELTA IS PAUSED" };
let coreHold = null, waveEnergy = 0;
function setCore(st, holdMs) {
  if (S.state && S.state.killed) st = "paused";
  S.coreState = st;
  const c = $("#core"); c.dataset.state = st;
  let label = CORE_LABEL[st];
  if (st === "speaking" && S.status && S.status.voice.speaks) label = "DELTA IS SPEAKING";
  $("#core-label").textContent = label;
  c.setAttribute("aria-label", "Delta status: " + label.toLowerCase().replace("delta is ", ""));
  clearTimeout(coreHold);
  if (holdMs) coreHold = setTimeout(() => setCore(document.activeElement === $("#inp") ? "listening" : "idle"), holdMs);
}
function buildCoreTicks() {
  const svg = $(".core-ticks"); const ns = "http://www.w3.org/2000/svg"; let out = "";
  for (let i = 0; i < 120; i++) {
    const a = (i / 120) * Math.PI * 2, major = i % 10 === 0, r1 = 196, r2 = major ? 186 : 191;
    const x1 = 200 + Math.cos(a) * r1, y1 = 200 + Math.sin(a) * r1, x2 = 200 + Math.cos(a) * r2, y2 = 200 + Math.sin(a) * r2;
    out += `<line x1="${x1.toFixed(1)}" y1="${y1.toFixed(1)}" x2="${x2.toFixed(1)}" y2="${y2.toFixed(1)}" stroke="${major ? "#bdeaf5" : "#7fb2c2"}" stroke-opacity="${major ? .8 : .45}" stroke-width="${major ? 1.6 : .9}"/>`;
  }
  for (let k = 0; k < 4; k++) { const a0 = k * 90 + 14, a1 = a0 + 62, p = (a, r) => `${(200 + Math.cos(a * Math.PI / 180) * r).toFixed(1)} ${(200 + Math.sin(a * Math.PI / 180) * r).toFixed(1)}`;
    out += `<path d="M ${p(a0, 172)} A 172 172 0 0 1 ${p(a1, 172)}" fill="none" stroke="#8fd8ea" stroke-opacity=".28" stroke-width="2"/>`; }
  svg.innerHTML = out; // numeric constants only
}

/* ------------------------------------------------------------------ waveform */
function startWave() {
  const cv = $("#wave"), cx = cv.getContext("2d"), W = cv.width, H = cv.height, N = 56, bars = new Float32Array(N);
  let t = 0, last = 0;
  function frame(ts) {
    if (ts - last < 33) { requestAnimationFrame(frame); return; }
    last = ts; t += 0.07;
    const st = S.coreState, base = { idle: .1, listening: .3, thinking: .22, speaking: .55, paused: .04 }[st] || .1;
    cx.clearRect(0, 0, W, H);
    const g = cx.createLinearGradient(0, 0, W, 0);
    g.addColorStop(0, "rgba(85,217,244,.15)"); g.addColorStop(.5, "rgba(190,246,255,1)"); g.addColorStop(1, "rgba(85,217,244,.15)");
    cx.fillStyle = g;
    waveEnergy *= .93;
    for (let i = 0; i < N; i++) {
      const x = i / (N - 1), env = Math.pow(Math.sin(Math.PI * x), 1.4);
      let a;
      if (st === "thinking") a = base + .55 * Math.max(0, Math.sin(t * 2.2 - i * .28)) ** 3;
      else a = base + (st === "idle" ? .12 : .4) * Math.abs(Math.sin(t * (1 + (i % 5) * .35) + i * 1.7)) * (.5 + .5 * Math.sin(t * .9 + i * .35)) + waveEnergy * .6 * Math.abs(Math.sin(i * 2.1 + t * 3));
      const target = Math.min(1, a) * env; bars[i] += (target - bars[i]) * .35;
      const bw = W / N * .52, bh = Math.max(2, bars[i] * H * .94), bx = x * (W - bw) + 0;
      cx.fillRect(bx, (H - bh) / 2, bw, bh);
    }
    requestAnimationFrame(frame);
  }
  if (reduceMotion) { // one calm static frame
    const g = cx.createLinearGradient(0, 0, W, 0); g.addColorStop(0, "rgba(85,217,244,.15)"); g.addColorStop(.5, "rgba(190,246,255,1)"); g.addColorStop(1, "rgba(85,217,244,.15)");
    cx.fillStyle = g; for (let i = 0; i < N; i++) { const x = i / (N - 1), env = Math.pow(Math.sin(Math.PI * x), 1.4), bh = Math.max(2, (.1 + .25 * Math.abs(Math.sin(i * 1.3))) * env * H); cx.fillRect(x * (W - 4), (H - bh) / 2, W / N * .52, bh); }
    return;
  }
  requestAnimationFrame(frame);
}

/* ------------------------------------------------------------------ charts */
function smoothPath(vals, w, hgt, max, pad) {
  if (!vals.length) return ["", ""];
  const n = Math.max(vals.length, 2), step = w / (60 - 1);
  const pts = vals.map((v, i) => [w - (vals.length - 1 - i) * step, hgt - pad - (Math.min(v, max) / max) * (hgt - pad * 2)]);
  if (pts.length === 1) pts.unshift([pts[0][0] - step, pts[0][1]]);
  let d = "M" + pts[0][0].toFixed(1) + " " + pts[0][1].toFixed(1);
  for (let i = 1; i < pts.length; i++) { const mx = (pts[i - 1][0] + pts[i][0]) / 2, my = (pts[i - 1][1] + pts[i][1]) / 2; d += " Q" + pts[i - 1][0].toFixed(1) + " " + pts[i - 1][1].toFixed(1) + " " + mx.toFixed(1) + " " + my.toFixed(1); }
  const l = pts[pts.length - 1]; d += " L" + l[0].toFixed(1) + " " + l[1].toFixed(1);
  const area = d + " L" + l[0].toFixed(1) + " " + hgt + " L" + pts[0][0].toFixed(1) + " " + hgt + " Z";
  return [d, area];
}
const SVGNS = "http://www.w3.org/2000/svg";
function sv(tag, attrs) { const e = document.createElementNS(SVGNS, tag); for (const k in attrs || {}) e.setAttribute(k, attrs[k]); return e; }

const gauges = {};
function buildGauges() {
  const wrap = $("#gauges"); wrap.replaceChildren();
  [["cpu", "CPU"], ["ram", "RAM"], ["disk", "DISK"], ["batt", "BATT"]].forEach(([k, label]) => {
    const R = 26, C = 2 * Math.PI * R;
    const svg = sv("svg", { viewBox: "0 0 64 64", role: "img", "aria-label": label });
    svg.append(sv("circle", { cx: 32, cy: 32, r: R, fill: "none", "stroke-width": 4.5, class: "trk" }));
    const val = sv("circle", { cx: 32, cy: 32, r: R, fill: "none", "stroke-width": 4.5, class: "val", transform: "rotate(-90 32 32)", "stroke-dasharray": C, "stroke-dashoffset": C });
    svg.append(val);
    const ticks = sv("g", { stroke: "rgba(150,220,240,.25)", "stroke-width": .8 });
    for (let i = 0; i < 24; i++) { const a = i / 24 * Math.PI * 2; ticks.append(sv("line", { x1: 32 + Math.cos(a) * 21, y1: 32 + Math.sin(a) * 21, x2: 32 + Math.cos(a) * 19.4, y2: 32 + Math.sin(a) * 19.4 })); }
    svg.append(ticks);
    const txt = sv("text", { x: 32, y: 32 }); txt.textContent = "–"; svg.append(txt);
    const sub = h("small", { text: " " }), box = h("div", { class: "gauge", data: { k } }, h("h3", { text: label }), svg, sub);
    wrap.append(box); gauges[k] = { box, val, txt, sub, C };
  });
}
function setGauge(k, pct, text, sub) {
  const g = gauges[k]; if (!g) return;
  if (pct == null) { g.val.setAttribute("stroke-dashoffset", g.C); g.txt.textContent = "n/a"; g.sub.textContent = sub || ""; g.box.className = "gauge"; return; }
  const p = clampPct(pct);
  g.val.setAttribute("stroke-dashoffset", (g.C * (1 - p / 100)).toFixed(2));
  g.txt.textContent = text != null ? text : Math.round(p) + "%";
  g.sub.textContent = sub || "";
  g.box.className = "gauge" + (k !== "batt" ? (p >= 92 ? " bad" : p >= 80 ? " warn" : "") : (p <= 15 ? " bad" : p <= 25 ? " warn" : ""));
}

function renderVitals() {
  const v = S.vitals; if (!v) return;
  setGauge("cpu", v.cpu.percent, null, "last 60 s");
  setGauge("ram", v.memory.percent, null, fmtPair(v.memory.used, v.memory.total));
  v.disk ? setGauge("disk", v.disk.percent, null, fmtPair(v.disk.used, v.disk.total)) : setGauge("disk", null, null, "no disk");
  v.battery ? setGauge("batt", v.battery.percent, v.battery.percent + "%", v.battery.plugged ? "charging" : "on battery") : setGauge("batt", null, null, "no battery");
  const live = $("#mon-live"); live.textContent = v.demo ? "demo · simulated" : "live"; live.className = v.demo ? "demo" : "";
  // 60 s sparkline: CPU + RAM
  const sp = $("#spark"); sp.replaceChildren();
  const W = 288, H = 56, [cd, ca] = smoothPath(v.cpu.history, W, H, 100, 4), [md] = smoothPath(v.memory.history, W, H, 100, 4);
  const svg = sv("svg", { viewBox: `0 0 ${W} ${H}`, preserveAspectRatio: "none", role: "img", "aria-label": "CPU and memory, last 60 seconds" });
  const defs = sv("defs"); const lg = sv("linearGradient", { id: "sp-fill", x1: 0, y1: 0, x2: 0, y2: 1 });
  lg.append(sv("stop", { offset: 0, "stop-color": "#55d9f4", "stop-opacity": ".32" }), sv("stop", { offset: 1, "stop-color": "#55d9f4", "stop-opacity": "0" })); defs.append(lg); svg.append(defs);
  [25, 50, 75].forEach((y) => svg.append(sv("line", { x1: 0, x2: W, y1: H - 4 - (y / 100) * (H - 8), y2: H - 4 - (y / 100) * (H - 8), class: "grid", "vector-effect": "non-scaling-stroke" })));
  if (ca) svg.append(sv("path", { d: ca, fill: "url(#sp-fill)" }));
  if (md) svg.append(sv("path", { d: md, fill: "none", stroke: "#dcc48f", "stroke-width": 1.3, "stroke-opacity": .85, "vector-effect": "non-scaling-stroke" }));
  if (cd) svg.append(sv("path", { d: cd, fill: "none", stroke: "#8cecff", "stroke-width": 1.8, "vector-effect": "non-scaling-stroke", filter: "url(#glow-s)" }));
  sp.append(h("div", { class: "spark-legend" }, h("span", {}, h("i", { style: "background:#8cecff" }), "CPU"), h("span", {}, h("i", { style: "background:#dcc48f" }), "RAM"), h("span", { text: "60 s" })), svg);
  // network
  const net = $("#net"); net.replaceChildren();
  const N = v.network, mx = Math.max(1, ...N.down_history, ...N.up_history);
  const [dd] = smoothPath(N.down_history, 120, 24, mx * 1.1, 2), [ud] = smoothPath(N.up_history, 120, 24, mx * 1.1, 2);
  const ns = sv("svg", { viewBox: "0 0 120 24", preserveAspectRatio: "none", "aria-hidden": "true" });
  if (dd) ns.append(sv("path", { d: dd, fill: "none", stroke: "#8cecff", "stroke-width": 1.4, "vector-effect": "non-scaling-stroke" }));
  if (ud) ns.append(sv("path", { d: ud, fill: "none", stroke: "#dcc48f", "stroke-width": 1.2, "vector-effect": "non-scaling-stroke" }));
  net.append(h("div", { class: "net-r" }, h("em", { text: "↓" }), h("b", { text: fmtRate(N.down_bps) })), h("div", { class: "net-r up" }, h("em", { text: "↑" }), h("b", { text: fmtRate(N.up_bps) })), ns);
  net.setAttribute("aria-label", "Network download " + fmtRate(N.down_bps) + ", upload " + fmtRate(N.up_bps));
}
function renderProcs() {
  const ul = $("#procs"); ul.replaceChildren();
  const p = S.procs; if (!p) return;
  if (!p.processes.length) { ul.append(h("li", { text: "No data" })); return; }
  p.processes.slice(0, 3).forEach((r) => ul.append(h("li", {}, h("span", { text: r.name.replace(/\.exe$/i, "") }), h("span", { text: r.cpu.toFixed(1) + "%" }))));
}

/* ------------------------------------------------------------------ left panels */
function emptyBox(icon, title, hint) { return h("li", { class: "empty" }, ic(icon), h("b", { text: title }), hint ? h("small", { text: hint }) : null); }
function renderNav() {
  const ul = $("#nav"); ul.replaceChildren();
  NAV.forEach(([id, label, icon]) => {
    const cur = (id === "overview" && !S.view) || id === S.view;
    const b = h("button", { type: "button", "aria-current": cur ? "page" : null, onclick: () => openView(id) }, ic(icon), h("span", { text: label }), ic("chev", "chev"));
    b.querySelector(".chev").style.cssText = "width:11px;height:11px;margin-left:auto";
    ul.append(h("li", {}, b));
  });
}
function renderGreeting() {
  const b = S.brief; if (!b) return;
  const part = b.greeting.split(",")[0].toUpperCase();
  $("#g-part").textContent = part + ",";
  $("#g-name").textContent = b.name || "there";
  $("#g-av").textContent = (b.name || "D").slice(0, 1).toUpperCase();
  const ul = $("#brief"); ul.replaceChildren();
  const n = b.reminders_today.length;
  ul.append(h("li", {}, ic("clock", "ic"), h("span", {}, h("b", { text: String(n) }), " reminder" + (n === 1 ? "" : "s") + " today" + (n ? " · next " + b.reminders_today[0].at : ""))));
  ul.append(h("li", {}, ic("tasks", "ic"), h("span", {}, h("b", { text: String(b.todos_open) }), " open task" + (b.todos_open === 1 ? "" : "s"))));
  if (b.next_routine) { const d = new Date(b.next_routine.at); ul.append(h("li", {}, ic("routines", "ic"), h("span", {}, "Next routine ", h("b", { text: b.next_routine.name }), " · " + d.toLocaleString([], { weekday: "short", hour: "numeric", minute: "2-digit" })))); }
}
function fileIcon(ext) { return ["png", "jpg", "jpeg", "gif", "webp", "svg"].includes(ext) ? "image" : ["py", "js", "ts", "html", "css", "json", "yaml", "yml", "c", "cpp", "java", "go", "rs"].includes(ext) ? "code" : "file"; }
function renderRecent() {
  const ul = $("#recent"); ul.replaceChildren();
  const f = S.files; if (!f) return;
  if (!f.files.length) { ul.append(emptyBox("files", "No recent files", "Files in your allowed folders show up here.")); return; }
  f.files.slice(0, 4).forEach((x) => ul.append(h("li", {}, h("button", { class: "row", type: "button", title: "Open " + x.name, onclick: () => openFile(x.path) }, ic(fileIcon(x.ext)), h("span", { class: "t" }, h("b", { text: x.name }), h("small", { text: x.folder + " · " + ago(x.mtime) }))))));
}
function renderLinks() {
  const ul = $("#links"); ul.replaceChildren();
  const f = S.files; if (!f) return;
  if (!f.folders.length) { ul.append(emptyBox("files", "No folders allowed", "Set safety.allowed_folders in config.yaml.")); return; }
  f.folders.slice(0, 3).forEach((x) => ul.append(h("li", {}, h("button", { class: "row", type: "button", title: x.path, onclick: () => ask("list files in " + x.name.toLowerCase()) }, ic("files"), h("span", { class: "t" }, h("b", { text: x.name }), h("small", { text: x.exists ? "list files" : "folder missing" }))))));
}
function taskRow(t, full) {
  if (t.type === "todo") {
    const c = h("button", { class: "circ", type: "button", "aria-label": "Mark done: " + t.text, onclick: (e) => { e.stopPropagation(); completeTodo(t.id); } }, ic("check"));
    return h("li", {}, h("div", { class: "row hov" }, c, h("span", { class: "t" }, h("b", { text: t.text }), full ? h("small", { text: "to-do #" + t.id }) : null)));
  }
  return h("li", {}, h("div", { class: "row hov" }, ic(t.kind === "timer" ? "clock" : "bell"), h("span", { class: "t" }, h("b", { text: t.text }), h("small", { text: t.kind + " · " + t.due }))));
}
function renderTasks() {
  const ul = $("#tasks"); ul.replaceChildren();
  const t = S.tasks; if (!t) return;
  const items = [...t.reminders.slice(0, 2).map((r) => ({ type: "rem", ...r })), ...t.todos.map((x) => ({ type: "todo", ...x }))].slice(0, 3);
  if (!items.length) { ul.append(emptyBox("tasks", "Nothing on your plate", "Add a task below or say “add todo …”.")); return; }
  items.forEach((i) => ul.append(taskRow(i)));
}
function renderSys() {
  const ul = $("#sys"); ul.replaceChildren();
  const s = S.status, st = S.state; if (!s || !st) return;
  const row = (cls, label, val) => h("li", {}, h("i", { class: "dot " + cls }), h("span", {}, label + " ", h("b", { text: val })));
  ul.append(s.demo ? h("li", {}, h("i", { class: "dot warn" }), h("span", {}, h("b", { text: "DEMO MODE" }), " · simulated PC")) : row("ok", "Adapter", "Windows · live"));
  ul.append(row(st.killed ? "bad" : st.dry_run ? "warn" : "ok", "Gate", st.killed ? "paused" : st.dry_run ? "dry-run" : "live"));
  ul.append(row(s.llm.available ? "ok" : "", "Brain", s.llm.available ? s.llm.model : "rules only"));
  ul.append(row(s.voice.available ? "ok" : "", "Voice", s.voice.available ? "ready" : "off"));
}

/* ------------------------------------------------------------------ right panels */
function renderMods() {
  const ul = $("#mods"); ul.replaceChildren();
  const m = S.mods; if (!m) return;
  const rows = m.modules.slice(0, 6);
  rows.forEach((x) => ul.append(h("li", {}, h("div", { class: "row" }, ic(x.kind === "core" ? (x.id === "gate" ? "shield" : x.id === "voice" ? "mic" : x.id === "scheduler" ? "clock" : "bolt") : "modules"), h("span", { class: "t" }, h("b", { text: x.name }), h("small", { text: x.detail })), h("span", { class: "pill " + x.status, text: x.status === "active" ? "Active" : x.status === "standby" ? "Standby" : x.status === "paused" ? "Paused" : "Error" })))));
}
function renderGate() {
  const st = S.state; if (!st) return;
  const big = $("#gate-big"); big.textContent = st.killed ? "PAUSED" : st.dry_run ? "DRY-RUN" : "GATE ONLINE"; big.className = "gate-big" + (st.killed ? " paused" : "");
  $("#gate-sub").textContent = st.killed ? "Kill switch is on. Nothing runs until you resume." : st.dry_run ? "Describing actions only. Nothing is executed." : "Every action is checked, asked or blocked, then logged.";
  $("#dry").setAttribute("aria-checked", String(!!st.dry_run));
  const k = $("#b-kill"); k.setAttribute("aria-pressed", String(!!st.killed)); k.setAttribute("aria-label", st.killed ? "Resume Delta" : "Kill switch: pause Delta");
  k.title = st.killed ? "Resume Delta" : "Kill switch (pause everything)";
}
function renderTray() {
  const tray = $("#tray"), want = (S.state && S.state.pending) || [];
  const have = new Map($$("[data-pid]", tray).map((n) => [n.dataset.pid, n]));
  have.forEach((n, id) => { if (!want.find((p) => p.id === id)) n.remove(); });
  want.forEach((p) => {
    let c = have.get(p.id);
    if (!c) { c = card({ status: "pending", tool: p.tool, text: "Needs your approval: " + p.description + ".", pending_id: p.id, tainted: p.tainted }, tray, true); c.setAttribute("role", "alertdialog"); c.setAttribute("aria-label", "Approval needed: " + p.description); }
    const e = $(".exp", c); if (e) e.textContent = "expires in " + p.expires_in + "s";
  });
  const n = want.length, chat = $("#b-chat"); let bd = $(".badge", chat); if (bd) bd.remove();
  if (n) chat.append(h("span", { class: "badge", text: String(n), "aria-hidden": "true" }));
  chat.setAttribute("aria-label", "Open conversation" + (n ? " (" + n + " waiting for approval)" : ""));
}

/* ------------------------------------------------------------------ clock */
function tickClock() {
  const d = new Date(Date.now() + S.clockOffset);
  $("#clock").textContent = d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }).toLowerCase();
  $("#date").textContent = d.toLocaleDateString([], { weekday: "long", day: "numeric", month: "long", year: "numeric" });
}

/* ------------------------------------------------------------------ chat dock (transcript) */
const col = $("#col"), feed = $("#feed");
function scrollFeed() { feed.scrollTop = feed.scrollHeight; }
function addUser(t) { const m = h("div", { class: "msg user" }, h("div", { class: "bubble", text: t })); col.append(m); scrollFeed(); }
function addBot(text) { const m = h("div", { class: "msg bot" }, h("div", { class: "who", text: "Delta" })); if (text) m.append(h("div", { class: "text", text })); col.append(m); scrollFeed(); return m; }
const TAGS = { ok: "done", error: "failed", blocked: "blocked", pending: "needs approval", denied: "cancelled", killed: "paused", dry_run: "dry-run", expired: "expired" };
function card(res, host, inTray) {
  const cls = { error: "err", blocked: "blocked", pending: "pending", dry_run: "dry", denied: "err", killed: "blocked", expired: "err" }[res.status] || "";
  const c = h("div", { class: "card " + cls }, h("div", { class: "hd" }, h("span", { class: "dot" }), h("span", { class: "tool", text: res.tool }), h("span", { class: "tag", text: TAGS[res.status] || res.status })), h("div", { class: "bd", text: res.text }));
  if (res.status === "pending") {
    if (res.tainted) c.append(h("div", { class: "warnline", text: "⚠ Requested after reading untrusted web/file text. Check it is what you want." }));
    const yes = h("button", { class: "btn go sm", type: "button", text: "Approve" }), no = h("button", { class: "btn no sm", type: "button", text: "Deny" });
    yes.onclick = () => decide(res.pending_id, true, c); no.onclick = () => decide(res.pending_id, false, c);
    c.append(h("div", { class: "actions" }, yes, no, h("span", { class: "exp" })));
    c.dataset.pid = res.pending_id;
  }
  host.append(c); if (!inTray) scrollFeed(); return c;
}
async function decide(id, approve, cardEl) {
  $$("button", cardEl).forEach((b) => (b.disabled = true));
  try {
    const r = await post("/api/confirm", { id, approve });
    $$('[data-pid="' + id + '"]').forEach((n) => { if (n.closest("#tray")) n.remove(); else { $(".actions", n)?.remove(); n.classList.remove("pending"); $(".tag", n).textContent = approve ? "approved" : "denied"; } });
    const out = r.result; toast(approve ? (out.status === "ok" ? "Approved" : "Approved, but") : "Denied", out.text, out.status === "ok" || out.status === "denied" ? "" : "err");
    if (S.view || !$("#dock").hidden) { const host = $("#col"); const m = addBot(""); card(out, m); }
    applyState(r.state); refreshAll();
  } catch (e) { toast("Error", e.message, "err"); $$("button", cardEl).forEach((b) => (b.disabled = false)); }
}
function renderReply(reply) {
  const host = addBot(reply.source === "llm" ? reply.text : "");
  if (reply.results && reply.results.length) reply.results.forEach((r) => card(r, host));
  else if (reply.source !== "llm") host.append(h("div", { class: "text", text: reply.text }));
  if (reply.source === "llm" && !reply.text && !(reply.results || []).length) host.append(h("div", { class: "text", text: "Done." }));
  scrollFeed();
}
let busy = false;
async function ask(text, opts) {
  text = (text || "").trim(); if (!text || busy) return;
  busy = true; $("#send").disabled = true; $("#inp").value = "";
  openDock(true); addUser(text);
  const typing = h("div", { class: "msg bot" }, h("div", { class: "typing" }, h("i"), h("i"), h("i"))); col.append(typing); scrollFeed();
  setCore("thinking");
  try {
    const r = await post("/api/chat", { message: text });
    typing.remove(); renderReply(r); applyState(r.state);
    setCore("speaking", Math.min(5200, 1400 + (r.text || "").length * 22));
  } catch (e) { typing.remove(); addBot("Could not reach Delta. Is it still running?"); setCore("idle"); }
  busy = false; $("#send").disabled = false; refreshAll();
}
function openDock(keepFocus) { $("#dock").hidden = false; if (!keepFocus) $("#dock-title").focus(); }
function closeDock() { $("#dock").hidden = true; $("#b-chat").focus(); }

/* ------------------------------------------------------------------ actions */
async function doAction(name, value, okTitle) {
  try { const out = await post("/api/actions/" + name, value == null ? undefined : { value }); const r = reportResult(out, okTitle); refreshAll(); return r; }
  catch (e) { toast("Error", e.message, "err"); }
}
async function completeTodo(id) { try { reportResult(await post("/api/todos/" + id + "/done"), "Task done"); } catch (e) { toast("Error", e.message, "err"); } refreshTasks(); refreshBrief(); }
async function addTodo(text) { text = text.trim(); if (!text) return; try { reportResult(await post("/api/todos", { text }), "Task added"); } catch (e) { toast("Error", e.message, "err"); } refreshTasks(); refreshBrief(); }
async function openFile(path) { try { reportResult(await post("/api/files/open", { text: path }), "Opening"); } catch (e) { toast("Error", e.message, "err"); } }
async function runRoutine(name) {
  try {
    const out = await post("/api/routines/" + encodeURIComponent(name) + "/run"); applyState(out.state);
    const bad = out.results.filter((r) => r.status !== "ok" && r.status !== "dry_run" && r.status !== "pending");
    const pend = out.results.filter((r) => r.status === "pending").length;
    toast("Routine · " + name, out.results.length + " step" + (out.results.length === 1 ? "" : "s") + " run" + (pend ? ", " + pend + " waiting for your approval" : "") + (bad.length ? ", " + bad.length + " failed" : "."), bad.length ? "err" : pend ? "warn" : "");
  } catch (e) { toast("Error", e.message, "err"); }
  refreshAll();
}
async function toggleKill() { try { applyState(await post(S.state && S.state.killed ? "/api/resume" : "/api/kill")); refreshAll(); } catch (e) { toast("Error", e.message, "err"); } }
async function toggleDry() { try { applyState(await post("/api/dryrun", { enabled: !(S.state && S.state.dry_run) })); refreshAll(); } catch (e) { toast("Error", e.message, "err"); } }

/* ------------------------------------------------------------------ views */
const viewEl = $("#view"), viewBody = $("#view-body"); let viewUpdate = null, viewDestroy = null;
function field(label, node) { return h("div", {}, h("h3", { text: label }), node); }
const VIEWS = {
  vibe() { // Vibe Coding workspace lives in vibe.js (loaded after this file); it only gets these helpers
    if (!window.DeltaVibe) { viewBody.append(h("p", { class: "stat-row", text: "The Vibe Coding module did not load. Reload the page." })); return null; }
    return window.DeltaVibe.mount(viewBody, { h, ic, api, post, toast, reportResult, applyState, refreshState, $, $$, ago, close: () => closeView(), state: () => S.state });
  },
  tasks() {
    const todoList = h("ul", { class: "rows" }), remList = h("ul", { class: "rows" });
    const tIn = h("input", { type: "text", maxlength: 300, placeholder: "New task…", "aria-label": "New task" });
    const rText = h("input", { type: "text", maxlength: 300, placeholder: "Remind me to…", "aria-label": "Reminder text" }), rWhen = h("input", { type: "text", maxlength: 80, placeholder: "in 20 minutes / at 6pm", "aria-label": "When" });
    const timerBtn = (m) => h("button", { class: "chip", type: "button", text: m + " min timer", onclick: async () => { try { reportResult(await post("/api/timers", { duration: m + " minutes", label: m + " min timer" }), "Timer set"); } catch (e) { toast("Error", e.message, "err"); } refreshTasks(); } });
    viewBody.append(
      h("div", { class: "cols2" },
        field("To-do", h("div", {}, todoList, h("form", { class: "form-r", style: "margin-top:10px", onsubmit: (e) => { e.preventDefault(); addTodo(tIn.value); tIn.value = ""; } }, tIn, h("button", { class: "btn", type: "submit" }, ic("plus"), "Add")))),
        field("Reminders & timers", h("div", {}, remList, h("form", { class: "form-r", style: "margin-top:10px", onsubmit: async (e) => { e.preventDefault(); if (!rText.value.trim() || !rWhen.value.trim()) return; try { reportResult(await post("/api/reminders", { text: rText.value, when: rWhen.value }), "Reminder set"); rText.value = ""; rWhen.value = ""; } catch (er) { toast("Error", er.message, "err"); } refreshTasks(); } }, rText, rWhen, h("button", { class: "btn", type: "submit" }, ic("plus"), "Set")), h("div", { class: "chips", style: "margin-top:10px" }, timerBtn(5), timerBtn(10), timerBtn(25))))));
    return () => {
      const t = S.tasks; if (!t) return;
      todoList.replaceChildren(); remList.replaceChildren();
      if (!t.todos.length) todoList.append(emptyBox("tasks", "All clear", "No open tasks.")); t.todos.forEach((x) => todoList.append(taskRow({ type: "todo", ...x }, true)));
      if (!t.reminders.length) remList.append(emptyBox("bell", "No reminders or timers", "Set one with the form below.")); t.reminders.forEach((r) => { const li = taskRow({ type: "rem", ...r }, true); $(".row", li).append(h("button", { class: "linkbtn", type: "button", style: "margin:0", text: "Cancel", "aria-label": "Cancel " + r.text, onclick: async () => { try { reportResult(await del("/api/reminders/" + r.id), "Cancelled"); } catch (e) { toast("Error", e.message, "err"); } refreshTasks(); } })); remList.append(li); });
    };
  },
  memory() {
    const list = h("div", { class: "rows", style: "display:grid;gap:8px" }), facts = h("ul", { class: "rows" });
    const nIn = h("input", { type: "text", maxlength: 500, placeholder: "Write a note…", "aria-label": "New note" });
    viewBody.append(h("div", { class: "cols2" }, field("Notes", h("div", {}, h("form", { class: "form-r", style: "margin-bottom:10px", onsubmit: async (e) => { e.preventDefault(); if (!nIn.value.trim()) return; try { reportResult(await post("/api/notes", { text: nIn.value }), "Note saved"); nIn.value = ""; } catch (er) { toast("Error", er.message, "err"); } refreshNotes(); } }, nIn, h("button", { class: "btn", type: "submit" }, ic("plus"), "Save")), list)), field("What Delta remembers about you", facts)));
    return () => {
      const n = S.notes; if (!n) return; list.replaceChildren(); facts.replaceChildren();
      if (!n.notes.length) list.append(emptyBox("note", "No notes yet", "Say “note buy cables” or write one above.")); n.notes.forEach((x) => list.append(h("div", { class: "note-i" }, x.text, h("small", { text: new Date(x.ts * 1000).toLocaleString([], { day: "numeric", month: "short", hour: "numeric", minute: "2-digit" }) }))));
      if (!n.facts.length) facts.append(emptyBox("memory", "Nothing remembered", "Say “remember my name is …”. Passwords and keys are never stored.")); n.facts.forEach((x) => facts.append(h("li", {}, h("div", { class: "row" }, ic("memory"), h("span", { class: "t" }, h("b", { text: x.text }), h("small", { text: "fact #" + x.id }))))));
    };
  },
  routines() {
    const box = h("div", { style: "display:grid;gap:10px" });
    viewBody.append(box);
    return () => {
      const r = S.routines; if (!r) return; box.replaceChildren();
      if (!r.routines.length) { box.append(h("ul", { class: "rows" }, emptyBox("routines", "No routines yet", "Copy routines.example.yaml to routines.yaml to add macros like “work mode”."))); return; }
      r.routines.forEach((x) => box.append(h("div", { class: "rcard" },
        h("header", {}, h("b", { text: x.name }), x.schedule ? h("span", { class: "pill standby", text: x.schedule }) : null, h("button", { class: "btn sm", type: "button", "aria-label": "Run " + x.name, onclick: () => runRoutine(x.name) }, ic("play"), "Run")),
        x.description ? h("small", { text: x.description }) : null,
        h("div", {}, x.steps.map((s) => h("span", { class: "tstep", text: s }))),
        h("small", { text: (x.next_run ? "Next run " + new Date(x.next_run).toLocaleString([], { weekday: "short", hour: "numeric", minute: "2-digit" }) + (x.ran_today ? " · already ran today" : "") : "Manual only") + (x.triggers.length ? " · say: " + x.triggers.map((t) => "“" + t + "”").join(", ") : "") }))));
      box.append(h("p", { class: "stat-row" }, "Every step goes through the safety gate. Steps that need approval wait for you; scheduled runs never run risky steps unattended."));
    };
  },
  activity() {
    let filter = "all"; const list = h("ul", { class: "rows" }), chips = h("div", { class: "chips" }), meta = h("div", { class: "stat-row" });
    const mk = () => { chips.replaceChildren(); [["all", "All"], ["safe", "Safe"], ["confirm", "Asked first"], ["blocked", "Blocked"]].forEach(([k, l]) => chips.append(h("button", { class: "chip", type: "button", "aria-pressed": String(filter === k), text: l, onclick: () => { filter = k; mk(); upd(); } }))); };
    viewBody.append(h("div", { style: "display:flex;gap:12px;align-items:center;flex-wrap:wrap" }, chips, meta), list); mk();
    const upd = () => {
      const a = S.activity; if (!a) return; list.replaceChildren();
      meta.replaceChildren(h("span", {}, "Audit chain ", h("b", { text: a.chain_ok ? "intact" : "TAMPERED", style: a.chain_ok ? "" : "color:var(--bad)" })), h("span", {}, "safe ", h("b", { text: String(a.counts.safe || 0) })), h("span", {}, "asked ", h("b", { text: String(a.counts.confirm || 0) })), h("span", {}, "blocked ", h("b", { text: String(a.counts.blocked || 0) })));
      const items = a.items.filter((i) => filter === "all" || i.badge === filter);
      if (!items.length) { list.append(emptyBox("activity", filter === "all" ? "No activity yet" : "Nothing in this category", "Everything Delta does is written here.")); return; }
      items.forEach((i) => list.append(h("li", {}, h("div", { class: "row" }, h("span", { class: "meta", text: (i.ts || "").slice(11, 19) }), h("span", { class: "t" }, h("b", { text: i.title }), h("small", { text: (i.detail || "").split("\n")[0] || i.outcome })), h("span", { class: "meta", text: i.outcome }), h("span", { class: "badge-s " + i.badge, text: i.badge === "confirm" ? "asked" : i.badge })))));
    };
    return upd;
  },
  modules() {
    const box = h("ul", { class: "rows" }), head = h("div", { class: "stat-row" });
    viewBody.append(head, h("p", { class: "stat-row", text: "These are the real parts of Delta: its safety gate, scheduler, optional language model and voice, and one group per skill area. Nothing here is simulated, except values on a PC in demo mode." }), box);
    return () => {
      const m = S.mods; if (!m) return; box.replaceChildren(); head.replaceChildren(h("span", {}, "tools ", h("b", { text: String(m.tools_total) })), h("span", {}, "modules ", h("b", { text: String(m.modules.length) })));
      m.modules.forEach((x) => box.append(h("li", {}, h("div", { class: "row" }, ic(x.kind === "core" ? "shield" : "modules"), h("span", { class: "t" }, h("b", { text: x.name }), h("small", { text: x.detail })), h("span", { class: "pill " + x.status, text: x.status[0].toUpperCase() + x.status.slice(1) })))));
    };
  },
  files() {
    const list = h("ul", { class: "rows" }), folders = h("ul", { class: "rows" });
    viewBody.append(h("div", { class: "cols2" }, field("Recent files", list), field("Allowed folders", h("div", {}, folders, h("p", { class: "stat-row", style: "margin-top:10px", text: "Delta can only read, move or delete inside these folders. Opening a program or script always asks first." })))));
    return () => {
      const f = S.files; if (!f) return; list.replaceChildren(); folders.replaceChildren();
      if (!f.files.length) list.append(emptyBox("files", "No recent files", "Nothing found in your allowed folders yet.")); f.files.forEach((x) => list.append(h("li", {}, h("button", { class: "row", type: "button", onclick: () => openFile(x.path), title: x.path }, ic(fileIcon(x.ext)), h("span", { class: "t" }, h("b", { text: x.name }), h("small", { text: x.folder + " · " + fmtBytes(x.size) + " · " + ago(x.mtime) }))))));
      f.folders.forEach((x) => folders.append(h("li", {}, h("button", { class: "row", type: "button", onclick: () => ask("list files in " + x.name.toLowerCase()), title: x.path }, ic("files"), h("span", { class: "t" }, h("b", { text: x.name }), h("small", { text: x.path }))))));
    };
  },
  controls() {
    const vol = h("input", { type: "range", min: 0, max: 100, "aria-label": "Volume" }), volOut = h("output", { text: "–" }), bri = h("input", { type: "range", min: 0, max: 100, "aria-label": "Brightness" }), briOut = h("output", { text: "–" });
    const sl = (icn, input, out) => h("div", { class: "slider" }, ic(icn), input, out);
    const paint = (r) => r.style.setProperty("--p", r.value + "%");
    let tm = {}; const commit = (name, r, o) => { r.addEventListener("input", () => { o.textContent = r.value + "%"; paint(r); clearTimeout(tm[name]); tm[name] = setTimeout(() => doAction(name, +r.value), 220); }); };
    commit("volume", vol, volOut); commit("brightness", bri, briOut);
    const tile = (icn, title, sub, fn) => h("button", { class: "tile", type: "button", onclick: fn }, ic(icn), h("b", { text: title }), h("small", { text: sub }));
    const muteTile = tile("mute", "Mute / unmute", "toggle sound", () => doAction("mute")), rtiles = h("div", { class: "tile-grid" }), safety = h("dl", { class: "kv" }), status = h("dl", { class: "kv" });
    viewBody.append(
      field("Sound & display", h("div", { class: "cols2", style: "gap:10px" }, sl("volume", vol, volOut), sl("sun", bri, briOut))),
      field("Quick actions", h("div", { class: "tile-grid" }, muteTile, tile("lock", "Lock", "lock the screen", () => doAction("lock")), tile("camera", "Screenshot", "to Pictures/Delta", () => doAction("screenshot")), tile("play", "Play / pause", "media key", () => doAction("play_pause")), tile("power", "Shut down…", "always asks first", () => doAction("shutdown")), tile("tasks", "Briefing", "read it to me", () => ask("daily briefing")))),
      field("Routines", rtiles),
      h("div", { class: "cols2" }, field("Safety", safety), field("Brain, voice & adapter", status)));
    let primed = false;
    return () => {
      const c = S.controls;
      if (c && !primed) { primed = true; if (c.volume != null) { vol.value = c.volume; volOut.textContent = c.volume + "%"; paint(vol); } if (c.brightness != null) { bri.value = c.brightness; briOut.textContent = c.brightness + "%"; paint(bri); } else { bri.disabled = true; briOut.textContent = "n/a"; bri.setAttribute("aria-label", "Brightness (not supported on this display)"); bri.parentElement.setAttribute("aria-disabled", "true"); } }
      $("small", muteTile).textContent = c && c.muted ? "currently muted" : "toggle sound";
      const r = S.routines; rtiles.replaceChildren(); if (r) { if (!r.routines.length) rtiles.append(h("p", { class: "stat-row", text: "No routines configured." })); r.routines.slice(0, 6).forEach((x) => rtiles.append(tile("play", x.name, x.schedule || "run now", () => runRoutine(x.name)))); }
      const sf = S.safety; if (sf) { safety.replaceChildren(); [["Kill switch", sf.killed ? "ON (paused)" : "off · hotkey " + sf.kill_hotkey], ["Dry-run", sf.dry_run ? "on" : "off"], ["Approval timeout", sf.confirm_timeout_s + " s"], ["Secret redaction", sf.redact_secrets ? "on" : "off"], ["Audit chain", sf.audit.ok ? "intact" : "TAMPERED at line " + sf.audit.first_bad_line], ["Tools", sf.tools.total + " (" + sf.tools.always_ask + " ask first)"], ["Allowed folders", sf.allowed_folders.map((f) => f.path).join("\n")]].forEach(([k, v]) => safety.append(h("dt", { text: k }), h("dd", { text: v, style: "white-space:pre-line" }))); }
      const s = S.status; if (s) { status.replaceChildren(); [["Mode", s.demo ? "DEMO · mock adapter, simulated PC" : "Windows · live"], ["Brain", s.llm.available ? s.llm.model + (s.llm.local ? " (local)" : " (cloud)") : "rules only, offline"], ["Voice", s.voice.available ? "ready (" + (s.voice.hotkey || "hotkey") + ")" : "not enabled"], ["Scheduler", s.scheduler.running == null ? "not started" : s.scheduler.running ? "running" : "stopped"], ["Version", "Delta " + s.version]].forEach(([k, v]) => status.append(h("dt", { text: k }), h("dd", { text: v }))); }
    };
  },
};
function openView(id) {
  if (id === "overview") return closeView();
  const fn = VIEWS[id]; if (!fn) return;
  if (viewDestroy) { viewDestroy(); viewDestroy = null; }
  S.view = id; viewEl.classList.toggle("wide", id === "vibe"); viewBody.replaceChildren(); viewUpdate = fn(); viewDestroy = (viewUpdate && viewUpdate.destroy) || null;
  $("#view-title").textContent = NAV.find((n) => n[0] === id)[1];
  viewEl.hidden = false; renderNav(); refreshForView(); if (viewUpdate) viewUpdate();
  $("#view-title").focus();
}
function closeView() { if (viewDestroy) { viewDestroy(); viewDestroy = null; } S.view = null; viewEl.hidden = true; viewEl.classList.remove("wide"); viewUpdate = null; renderNav(); $("#inp").focus(); }
function refreshForView() {
  const v = S.view; if (!v) return;
  const jobs = { tasks: refreshTasks, memory: refreshNotes, routines: refreshRoutines, activity: refreshActivity, modules: refreshMods, files: refreshFiles, controls: async () => { await Promise.all([refreshControls(), refreshRoutines(), refreshSafety(), refreshStatus()]); } };
  return jobs[v] && jobs[v]();
}
function updView() { if (viewUpdate) viewUpdate(); }

/* ------------------------------------------------------------------ data refreshers */
const safe = (fn) => async () => { try { await fn(); } catch (e) { if (e.message !== "auth") { /* a single failed poll must not break the page */ } } };
const refreshState = safe(async () => { applyState(await api("/api/state")); });
const refreshBrief = safe(async () => { const b = await api("/api/briefing"); S.clockOffset = new Date(b.now).getTime() - Date.now(); S.brief = b; renderGreeting(); tickClock(); });
const refreshStatus = safe(async () => { S.status = await api("/api/status"); renderSys(); updView(); if (S.status.voice.available) { $("#mic").removeAttribute("aria-disabled"); $("#mic").setAttribute("aria-label", "Push to talk"); } });
const refreshVitals = safe(async () => { S.vitals = await api("/api/vitals"); renderVitals(); });
const refreshProcs = safe(async () => { S.procs = await api("/api/processes?sort=cpu&limit=3"); renderProcs(); });
const refreshTasks = safe(async () => { S.tasks = await api("/api/tasks"); renderTasks(); updView(); });
const refreshFiles = safe(async () => { S.files = await api("/api/files/recent?limit=12"); renderRecent(); renderLinks(); updView(); });
const refreshMods = safe(async () => { S.mods = await api("/api/modules"); renderMods(); updView(); });
const refreshRoutines = safe(async () => { S.routines = await api("/api/routines"); updView(); });
const refreshActivity = safe(async () => { S.activity = await api("/api/activity?limit=40"); updView(); });
const refreshSafety = safe(async () => { S.safety = await api("/api/safety"); updView(); });
const refreshControls = safe(async () => { S.controls = await api("/api/controls"); updView(); });
const refreshNotes = safe(async () => { S.notes = await api("/api/notes"); updView(); });
function refreshAll() { return Promise.all([refreshState(), refreshBrief(), refreshTasks(), refreshMods(), refreshFiles(), refreshStatus(), refreshProcs(), refreshVitals(), S.view ? refreshForView() : null]); }

function applyState(s) {
  const was = S.state && S.state.killed; S.state = s;
  renderGate(); renderSys(); renderTray(); renderMods();
  if (!!was !== !!s.killed) setCore(s.killed ? "paused" : "idle");
  else if (s.killed && S.coreState !== "paused") setCore("paused");
  const banner = s.dry_run && !s.killed; document.title = (s.killed ? "⏻ Paused · " : banner ? "Dry-run · " : "") + "Delta OS";
  $("#ver").textContent = "PERSONAL AI SYSTEM · v" + s.version;
  $$(".card.pending", col).forEach((c) => { const p = (s.pending || []).find((x) => x.id === c.dataset.pid); const e = $(".exp", c); if (e) e.textContent = p ? "expires in " + p.expires_in + "s" : "expired"; });
}

/* ------------------------------------------------------------------ command palette */
const pal = $("#pal"), palQ = $("#pal-q"), palList = $("#pal-list"); let palItems = [], palSel = 0, palReturn = null;
function palCommands() {
  const L = [];
  NAV.forEach(([id, label, icn]) => L.push({ g: "Go to", icon: icn, label: label === "Overview" ? "Overview (close panel)" : label, hint: "view", run: () => openView(id) }));
  const A = (icn, label, hint, fn) => L.push({ g: "Actions", icon: icn, label, hint, run: fn });
  A("lock", "Lock the screen", "safe", () => doAction("lock")); A("mute", "Mute / unmute", "safe", () => doAction("mute")); A("camera", "Take a screenshot", "safe", () => doAction("screenshot"));
  A("play", "Play / pause media", "safe", () => doAction("play_pause")); A("code", "Open VS Code", "safe", () => doAction("open_vscode")); A("terminal", "Open terminal", "safe", () => doAction("open_terminal"));
  A("power", "Shut down…", "asks first", () => doAction("shutdown"));
  A("shield", (S.state && S.state.dry_run ? "Turn dry-run off" : "Turn dry-run on"), "safety", toggleDry);
  A("power", (S.state && S.state.killed ? "Resume Delta" : "Kill switch: pause Delta"), "safety", toggleKill);
  A("chat", "Open conversation", "chat", () => openDock());
  ((S.routines && S.routines.routines) || []).forEach((r) => L.push({ g: "Routines", icon: "routines", label: "Run routine: " + r.name, hint: r.schedule || "manual", run: () => runRoutine(r.name) }));
  return L;
}
function palRender() {
  const q = palQ.value.trim().toLowerCase(); palList.replaceChildren(); palItems = [];
  let items = palCommands().filter((c) => !q || (c.label + " " + c.g).toLowerCase().includes(q));
  if (q) items.push({ g: "Ask Delta", icon: "send", label: "Ask Delta: “" + palQ.value.trim() + "”", hint: "chat", run: () => ask(palQ.value) });
  let lastG = ""; let idx = 0;
  items.forEach((c) => { if (c.g !== lastG) { palList.append(h("li", { class: "grp", role: "presentation", text: c.g })); lastG = c.g; }
    const li = h("li", { role: "option", id: "pal-o" + idx, "aria-selected": "false", onclick: () => palRun(c), onmousemove: ((i) => () => palSelect(i))(idx) }, ic(c.icon), h("span", { text: c.label }), h("small", { text: c.hint })); palList.append(li); palItems.push({ c, li }); idx++; });
  if (!palItems.length) palList.append(h("li", { class: "grp", role: "presentation", text: "No matches" }));
  palSelect(0);
}
function palSelect(i) { if (!palItems.length) return; palSel = (i + palItems.length) % palItems.length; palItems.forEach((p, k) => p.li.setAttribute("aria-selected", String(k === palSel))); const li = palItems[palSel].li; palQ.setAttribute("aria-activedescendant", li.id); li.scrollIntoView({ block: "nearest" }); }
function palRun(c) { palClose(true); c.run(); }
function palOpen() { palReturn = document.activeElement; pal.hidden = false; palQ.value = ""; palRender(); palQ.focus(); }
function palClose(skipFocus) { pal.hidden = true; if (!skipFocus && palReturn && palReturn.focus) palReturn.focus(); }
palQ.addEventListener("input", palRender);
palQ.addEventListener("keydown", (e) => {
  if (e.key === "ArrowDown") { e.preventDefault(); palSelect(palSel + 1); } else if (e.key === "ArrowUp") { e.preventDefault(); palSelect(palSel - 1); }
  else if (e.key === "Enter") { e.preventDefault(); if (palItems[palSel]) palRun(palItems[palSel].c); } else if (e.key === "Tab") e.preventDefault(); // focus stays in the dialog
});
pal.addEventListener("mousedown", (e) => { if (e.target === pal) palClose(); });

/* ------------------------------------------------------------------ controls popover (sun button) */
function toggleCtl() {
  const pop = $("#ctl-pop");
  if (!pop.hidden) { pop.hidden = true; return; }
  pop.replaceChildren();
  const c = S.controls || {};
  const mk = (icn, label, val, name, disabled) => { const r = h("input", { type: "range", min: 0, max: 100, value: val == null ? 0 : val, "aria-label": label, disabled: disabled ? "" : null }); const o = h("output", { text: val == null ? "n/a" : val + "%" }); r.style.setProperty("--p", (val || 0) + "%"); let t; r.addEventListener("input", () => { o.textContent = r.value + "%"; r.style.setProperty("--p", r.value + "%"); clearTimeout(t); t = setTimeout(() => doAction(name, +r.value), 220); }); return h("div", { class: "slider", "aria-disabled": disabled ? "true" : null }, ic(icn), r, o); };
  pop.append(h("h3", { class: "ph", text: "Controls" }), mk("volume", "Volume", c.volume, "volume"), mk("sun", c.brightness == null ? "Brightness (not supported here)" : "Brightness", c.brightness, "brightness", c.brightness == null),
    h("div", { class: "tile-grid", style: "grid-template-columns:1fr 1fr" }, h("button", { class: "btn", type: "button", onclick: () => doAction("mute") }, ic("mute"), "Mute"), h("button", { class: "btn", type: "button", onclick: () => doAction("lock") }, ic("lock"), "Lock")));
  const r = $("#b-ctl").getBoundingClientRect(); pop.style.top = r.bottom + 8 + "px"; pop.style.left = Math.max(8, Math.min(innerWidth - 328, r.right - 320)) + "px"; pop.hidden = false;
  $("input", pop).focus();
}

/* ------------------------------------------------------------------ wiring */
function build() {
  $("#b-chat").append(ic("chat")); $("#b-ctl").append(ic("sun")); $("#b-kill").append(ic("power"));
  $("#mic").append(ic("mic")); $("#send").append(ic("send")); $(".cmd-play").append(ic("play")); $(".pal-ico").append(ic("search"));
  $("#task-add .ico").append(ic("plus"));
  const QA = [["code", "Open VS Code", "Development", () => doAction("open_vscode", null, "Opening VS Code")], ["globe", "Web search", "Search the web", () => { $("#inp").value = "search for "; $("#inp").focus(); }],
    ["terminal", "Open terminal", "Command line", () => doAction("open_terminal", null, "Opening terminal")], ["search", "Search files", "File system", () => { $("#inp").value = "find file "; $("#inp").focus(); }],
    ["note", "Take note", "Quick notes", () => { $("#inp").value = "note "; $("#inp").focus(); }], ["camera", "Capture screen", "Screenshot", () => doAction("screenshot", null, "Screenshot saved")]];
  QA.forEach(([i, t, s, fn]) => $("#qa").append(h("button", { type: "button", onclick: fn }, ic(i), h("b", { text: t }), h("small", { text: s }))));
  $("#mic").setAttribute("aria-disabled", "true"); $("#mic").title = "Voice is not enabled (see README)";
  buildCoreTicks(); buildGauges(); renderNav();
  $$("[data-view]").forEach((b) => b.addEventListener("click", () => openView(b.dataset.view)));
  $("#view-x").onclick = closeView; $("#dock-x").onclick = closeDock; $("#b-chat").onclick = () => ($("#dock").hidden ? openDock() : closeDock());
  $("#dock-clear").onclick = async () => { try { await post("/api/clear"); col.replaceChildren(); addBot("Cleared."); } catch (e) { toast("Error", e.message, "err"); } };
  $("#b-kill").onclick = toggleKill; $("#dry").onclick = toggleDry; $("#b-ctl").onclick = toggleCtl;
  $("#cmd").addEventListener("submit", (e) => { e.preventDefault(); ask($("#inp").value); });
  $("#task-add").addEventListener("submit", (e) => { e.preventDefault(); const i = $("#task-in"); addTodo(i.value); i.value = ""; });
  $("#inp").addEventListener("blur", () => { if (S.coreState === "listening" && !busy) setCore("idle"); });
  $("#inp").addEventListener("input", () => { waveEnergy = Math.min(1, waveEnergy + .35); if (!busy && S.coreState === "idle" && $("#inp").value) setCore("listening"); else if (!busy && S.coreState === "listening" && !$("#inp").value) setCore("idle"); });
  $("#mic").onclick = async () => {
    if ($("#mic").getAttribute("aria-disabled") === "true") { toast("Voice is off", "Enable it with `delta serve --voice` (see README).", "warn"); return; }
    try { await post("/api/voice/listen"); $("#mic").classList.add("on"); setCore("listening", 7000); toast("Listening", "Speak now…"); setTimeout(() => $("#mic").classList.remove("on"), 7000); } catch (e) { toast("Voice", e.message, "err"); }
  };
  document.addEventListener("click", (e) => { const p = $("#ctl-pop"); if (!p.hidden && !p.contains(e.target) && !$("#b-ctl").contains(e.target)) p.hidden = true; });
  document.addEventListener("keydown", (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") { e.preventDefault(); pal.hidden ? palOpen() : palClose(); return; }
    if (e.key === "Escape") {
      if (!pal.hidden) palClose(); else if (!$("#ctl-pop").hidden) { $("#ctl-pop").hidden = true; $("#b-ctl").focus(); } else if (!$("#dock").hidden) closeDock(); else if (S.view) closeView();
    } else if (e.key === "/" && !/^(INPUT|TEXTAREA)$/.test(document.activeElement.tagName)) { e.preventDefault(); $("#inp").focus(); }
  });
  viewEl.addEventListener("keydown", () => {});
}

async function init() {
  build(); startWave(); tickClock(); setInterval(tickClock, 1000);
  try {
    const s = await api("/api/state"); applyState(s);
    const hist = await api("/api/history");
    if (hist.messages.length) hist.messages.slice(-8).forEach((m) => (m.role === "user" ? addUser(m.content) : addBot(m.content)));
    else addBot("Good to see you" + (s.user ? ", " + s.user : "") + ". Ask me to open apps, change volume, set reminders, find files… Risky actions always ask first.");
  } catch (e) { return; }
  await refreshAll(); refreshRoutines(); refreshControls(); refreshSafety();
  setCore("idle"); $("#inp").focus({ preventScroll: true });
  setInterval(() => { if (!document.hidden) { refreshVitals(); } }, 2000);
  setInterval(() => { if (!document.hidden) { refreshState(); refreshProcs(); pollEvents(); } }, 3000);
  setInterval(() => { if (!document.hidden) { refreshBrief(); refreshTasks(); refreshFiles(); refreshMods(); refreshStatus(); if (S.view) refreshForView(); } }, 8000);
  document.addEventListener("visibilitychange", () => { if (!document.hidden) refreshAll(); });
}
let lastEvent = 0;
async function pollEvents() { try { const ev = await api("/api/events?since=" + lastEvent); ev.events.forEach((e) => { lastEvent = Math.max(lastEvent, e.id); if (e.type === "reminder") { toast(e.title, e.text, "warn"); refreshTasks(); } }); } catch (e) { /* ignore */ } }
init();
})();
