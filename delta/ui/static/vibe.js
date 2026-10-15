/* Delta OS: Vibe Coding workspace. Plain JS, no libraries, no network except this app's own /api (and the preview iframe on loopback).
   Every piece of text from a file, a model, a log or a diff is inserted with textContent, never innerHTML. */
(function () {
"use strict";

/* ------------------------------------------------------------------ syntax highlighter (own, tiny, regex based) */
const words = (s) => new Set(s.split(/\s+/));
const KW = {
  js: words("break case catch class const continue debugger default delete do else export extends finally for from function if import in instanceof let new of return static super switch this throw try typeof var void while with yield async await null undefined true false interface type enum implements public private readonly as"),
  python: words("and as assert async await break class continue def del elif else except finally for from global if import in is lambda None nonlocal not or pass raise return try while with yield True False self"),
  sh: words("if then else elif fi for do done while case esac function echo cd set export call exit goto"),
  yaml: words("true false null yes no on off"),
};
const RX = {
  js: [["c", /\/\/[^\n]*|\/\*[\s\S]*?(?:\*\/|$)/y], ["s", /"(?:[^"\\\n]|\\.)*"?|'(?:[^'\\\n]|\\.)*'?|`(?:[^`\\]|\\[\s\S])*`?/y], ["t", /<\/?[A-Za-z][\w.]*(?=[\s/>])|\/>/y],
       ["n", /\b(?:0x[\da-fA-F]+|\d+\.?\d*(?:e[+-]?\d+)?)\b/y], ["w", /[A-Za-z_$][\w$]*/y]],
  python: [["c", /#[^\n]*/y], ["s", /[rbfRBF]{0,2}(?:"""[\s\S]*?(?:"""|$)|'''[\s\S]*?(?:'''|$)|"(?:[^"\\\n]|\\.)*"?|'(?:[^'\\\n]|\\.)*'?)/y], ["v", /@[\w.]+/y],
           ["n", /\b(?:0x[\da-fA-F]+|\d+\.?\d*(?:e[+-]?\d+)?)\b/y], ["w", /[A-Za-z_][\w]*/y]],
  css: [["c", /\/\*[\s\S]*?(?:\*\/|$)/y], ["s", /"(?:[^"\\\n]|\\.)*"?|'(?:[^'\\\n]|\\.)*'?/y], ["k", /@[\w-]+/y], ["n", /#[\da-fA-F]{3,8}\b/y],
        ["n", /-?\d*\.?\d+(?:px|em|rem|%|vh|vw|vmin|vmax|s|ms|deg|fr|ch)?\b/y], ["v", /--[\w-]+/y], ["f", /[\w-]+(?=\()/y], ["p", /[\w-]+(?=\s*:(?!:))/y], ["t", /[.#][A-Za-z_][\w-]*/y]],
  json: [["p", /"(?:[^"\\\n]|\\.)*"(?=\s*:)/y], ["s", /"(?:[^"\\\n]|\\.)*"?/y], ["n", /-?\d+\.?\d*(?:[eE][+-]?\d+)?/y], ["k", /\b(?:true|false|null)\b/y]],
  sh: [["c", /(?:#|::|REM\b)[^\n]*/y], ["s", /"(?:[^"\\\n]|\\.)*"?|'[^'\n]*'?/y], ["v", /\$\{?[\w]+\}?|%[\w]+%/y], ["w", /[A-Za-z_][\w-]*/y]],
  yaml: [["c", /#[^\n]*/y], ["s", /"(?:[^"\\\n]|\\.)*"?|'[^'\n]*'?/y], ["p", /[\w.-]+(?=\s*[:=])/y], ["n", /-?\d+\.?\d*\b/y], ["w", /[A-Za-z_][\w]*/y]],
};
function tokenize(text, lang) {
  const out = []; let plain = "";
  const flush = () => { if (plain) { out.push(["", plain]); plain = ""; } };
  if (lang === "html") return tokenizeHtml(text);
  if (lang === "md") return tokenizeMd(text);
  const rules = RX[lang]; if (!rules) return [["", text]];
  const kws = KW[lang] || new Set(), n = text.length; let i = 0;
  while (i < n) {
    let hit = null;
    for (const [type, rx] of rules) { rx.lastIndex = i; const m = rx.exec(text); if (m && m[0]) { hit = [type, m[0]]; break; } }
    if (!hit) { plain += text[i++]; continue; }
    let [type, str] = hit;
    if (type === "w") {
      if (kws.has(str)) type = "k";
      else if (text[i + str.length] === "(") type = "f";
      else if (/^[A-Z][A-Za-z0-9]+$/.test(str) && lang !== "sh" && lang !== "yaml") type = "t";
      else type = "";
    }
    if (!type) plain += str; else { flush(); out.push([type, str]); }
    i += str.length;
  }
  flush(); return out;
}
function tokenizeHtml(text) {
  const out = [], n = text.length; let i = 0, inTag = false, plain = "";
  const flush = () => { if (plain) { out.push(["", plain]); plain = ""; } };
  const take = (rx) => { rx.lastIndex = i; const m = rx.exec(text); return m && m[0] ? m[0] : null; };
  while (i < n) {
    let m;
    if (!inTag) {
      if ((m = take(/<!--[\s\S]*?(?:-->|$)/y))) { flush(); out.push(["c", m]); i += m.length; continue; }
      if ((m = take(/<![^>]*>?/y))) { flush(); out.push(["k", m]); i += m.length; continue; }
      if ((m = take(/<\/?[A-Za-z][\w:-]*/y))) { flush(); out.push(["t", m]); i += m.length; inTag = true; continue; }
      if ((m = take(/&[#\w]+;/y))) { flush(); out.push(["n", m]); i += m.length; continue; }
      plain += text[i++];
    } else {
      if ((m = take(/\/?>/y))) { flush(); out.push(["t", m]); i += m.length; inTag = false; continue; }
      if ((m = take(/"[^"]*"?|'[^']*'?/y))) { flush(); out.push(["s", m]); i += m.length; continue; }
      if ((m = take(/[\w:@.-]+(?=\s*=)/y))) { flush(); out.push(["a", m]); i += m.length; continue; }
      plain += text[i++];
    }
  }
  flush(); return out;
}
function tokenizeMd(text) {
  const out = []; let fence = false;
  text.split("\n").forEach((line, idx, arr) => {
    const nl = idx < arr.length - 1 ? "\n" : "";
    if (/^\s*```/.test(line)) { fence = !fence; out.push(["c", line + nl]); }
    else if (fence) out.push(["s", line + nl]);
    else if (/^#{1,6}\s/.test(line)) out.push(["t", line + nl]);
    else if (/^\s*([-*+]|\d+\.)\s/.test(line)) { const m = /^(\s*(?:[-*+]|\d+\.)\s)(.*)$/.exec(line); out.push(["k", m[1]], ["", m[2] + nl]); }
    else out.push(["", line + nl]);
  });
  return out;
}
/* tokens -> an array of lines, each an array of [type, text] pieces */
function toLines(tokens) {
  const lines = [[]];
  for (const [t, s] of tokens) {
    const parts = s.split("\n");
    parts.forEach((p, i) => { if (i) lines.push([]); if (p) lines[lines.length - 1].push([t, p]); });
  }
  return lines;
}

/* ------------------------------------------------------------------ module */
const MAX_LINES = 4000;
const TAB_LABEL = { changes: "Changes", code: "Code", preview: "Preview", history: "History" };
const SUGGEST = {
  static: ["Turn this into a landing page for a small coffee shop", "Add a dark / light theme toggle", "Add a contact form with name, email and message"],
  "react-vite": ["Make a to-do app with add, tick and delete", "Add a counter button that remembers its value", "Style it with a clean dark theme"],
  fastapi: ["Add a /todos API with create, list and delete (in memory)", "Add a /health endpoint returning ok", "Add a simple HTML page that calls the API"],
  express: ["Add a /api/todos route with create, list and delete (in memory)", "Add a /health route returning ok", "Serve a small HTML page from /"],
  "python-script": ["Write a script that prints the first 20 Fibonacci numbers", "Read a CSV file and print basic statistics", "Make a simple number-guessing game"],
  blank: ["Create a README.md describing the project", "Create a small Python script that prints hello"],
};

function mount(body, D) {
  const { h, ic, api, post, toast, reportResult, $, ago } = D;
  const V = { status: null, projects: [], root: "", problem: "", name: null, info: null, tab: "changes", mtab: "chat", tree: [], file: null, fileKey: "", open: new Set(),
              changes: [], history: [], pv: null, pvSince: 0, pvLines: [], run: null, runData: null, steps: [], since: 0, dead: false, tick: 0, newName: "", newTpl: "static", busy: false,
              narrow: false, logsOpen: true, device: "desktop", frameKey: 0, drafts: "", lastChangeSig: "", lastAppr: "" };
  const root = h("div", { class: "vb" });
  body.append(root);
  const guard = (fn) => async (...a) => { try { return await fn(...a); } catch (e) { if (e.message !== "auth") toast("Vibe Coding", e.message, "err"); } };
  const quiet = (fn) => async (...a) => { try { return await fn(...a); } catch (e) { return null; } };

  /* -------------------------------------------------------------- picker screen */
  async function loadHome() {
    const [st, pr] = await Promise.all([api("/api/vibe/status"), api("/api/vibe/projects")]);
    V.status = st; V.projects = pr.projects; V.root = pr.root; V.problem = pr.problem;
  }
  function pill(text, kind) { return h("span", { class: "vb-pill " + (kind || ""), text }); }
  function envChips() {
    const s = V.status; if (!s) return h("div");
    const row = h("div", { class: "vb-env" });
    row.append(s.mode === "ai" ? pill("AI · " + (s.llm.model || "model"), "ok") : pill("Offline rules mode (no AI model)", "warn"));
    row.append(pill(s.git.found ? "git " + (s.git.version || "").replace(/^git version\s*/, "") : "git missing", s.git.found ? "ok" : "bad"));
    row.append(pill(s.node.found ? "Node.js ready" : "Node.js not found", s.node.found ? "ok" : "dim"));
    row.append(pill(s.python.found ? "Python ready" : "Python not found", s.python.found ? "ok" : "dim"));
    row.append(pill(s.vscode.found ? "VS Code found" : "VS Code not found", s.vscode.found ? "ok" : "dim"));
    return row;
  }
  function renderPicker() {
    V.name = null; stopRunTimers();
    const s = V.status;
    root.replaceChildren();
    root.className = "vb vb-home";
    const hd = h("div", { class: "vb-top" },
      h("div", { class: "vb-title" }, ic("spark"), h("div", {}, h("b", { text: "Vibe Coding" }), h("small", { text: "Describe it. Delta builds it. You review every change before it touches a file." }))),
      h("button", { class: "x", type: "button", "aria-label": "Close Vibe Coding", onclick: () => D.close() , text: "×" }));
    root.append(hd, envChips());
    if (s && !s.ready) root.append(h("div", { class: "vb-banner bad", role: "alert" }, h("b", { text: "Projects folder not ready. " }), s.problem || "Check vibe.projects_root in config.yaml."));
    else if (s && !s.git.found) root.append(h("div", { class: "vb-banner warn" }, h("b", { text: "git was not found. " }), "Delta needs git for the safety snapshot and Undo. Install Git for Windows, then restart Delta (or set vibe.require_git: false to run without Undo)."));
    if (s && s.mode === "rules") root.append(h("div", { class: "vb-banner info" }, h("b", { text: "Offline mode. " }), "No language model is connected, so only simple edits work (titles, colours, sections, routes). Connect Groq or Ollama (README) for free-form building."));
    const cols = h("div", { class: "vb-home-cols" });
    const list = h("section", { class: "vb-card-sec", "aria-labelledby": "vb-h-proj" }, h("h3", { id: "vb-h-proj", text: "Your projects" }));
    if (!V.projects.length) list.append(h("div", { class: "vb-empty" }, ic("files"), h("b", { text: "No projects yet" }), h("small", { text: "Pick a template on the right and give it a name." })));
    else {
      const g = h("div", { class: "vb-proj-grid" });
      V.projects.forEach((p) => g.append(h("button", { type: "button", class: "vb-proj", onclick: () => openProject(p.name) },
        h("span", { class: "vb-proj-ic" }, ic(p.kind === "static" ? "globe" : p.kind === "python-script" || p.kind === "fastapi" || p.kind === "flask" ? "terminal" : "code")),
        h("span", { class: "vb-proj-t" }, h("b", { text: p.name }), h("small", { text: (p.template || p.kind) + " · " + (p.modified ? ago(p.modified) : "new") + (p.runs ? " · " + p.runs + " run" + (p.runs === 1 ? "" : "s") : "") })),
        p.active ? pill("working", "ok") : p.pending ? pill(p.pending + " to review", "warn") : null)));
      list.append(g);
    }
    list.append(h("p", { class: "vb-note", text: "Folder: " + (V.root || "(not set)") }));
    const form = h("section", { class: "vb-card-sec", "aria-labelledby": "vb-h-new" }, h("h3", { id: "vb-h-new", text: "New project" }));
    const nameIn = h("input", { type: "text", maxlength: 64, placeholder: "my-project", "aria-label": "Project name", value: V.newName, autocomplete: "off", spellcheck: "false",
      oninput: (e) => { V.newName = e.target.value; } });
    const tpls = h("div", { class: "vb-tpls", role: "radiogroup", "aria-label": "Template" });
    const tplBtns = [];
    (s ? s.templates : []).filter((t) => t.key !== "blank").concat((s ? s.templates : []).filter((t) => t.key === "blank")).forEach((t) => {
      const b = h("button", { type: "button", role: "radio", class: "vb-tpl", "aria-checked": String(V.newTpl === t.key), data: { key: t.key },
        onclick: () => { V.newTpl = t.key; tplBtns.forEach((x) => x.setAttribute("aria-checked", String(x.dataset.key === t.key))); } },
        h("span", { class: "vb-tpl-ic" }, ic(t.key === "static" ? "globe" : t.key === "blank" ? "file" : t.key === "python-script" || t.key === "fastapi" ? "terminal" : "code")),
        h("span", {}, h("b", { text: t.title }), h("small", { text: t.blurb })));
      tplBtns.push(b); tpls.append(b);
    });
    const go = h("button", { class: "btn go", type: "submit" }, ic("plus"), "Create project");
    form.append(h("form", { class: "vb-new", onsubmit: guard(async (e) => {
      e.preventDefault(); const name = nameIn.value.trim(); if (!name) { nameIn.focus(); return; }
      go.disabled = true;
      try { const out = await post("/api/vibe/projects", { name, template: V.newTpl }); const r = reportResult(out, "Project created"); if (r.status === "ok") { V.newName = ""; await openProject(name); } }
      finally { go.disabled = false; }
    }) }, h("label", { text: "Name", for: "vb-name" }), (nameIn.id = "vb-name", nameIn), tpls, go,
      h("p", { class: "vb-note", text: "Letters, digits, dot, dash and underscore. The folder is created inside the projects folder shown on the left, with a git history." })));
    cols.append(list, form); root.append(cols);
  }

  /* -------------------------------------------------------------- workspace screen */
  const W = {};   // element refs of the workspace
  async function openProject(name) {
    V.name = name; V.info = null; V.tree = []; V.file = null; V.fileKey = ""; V.changes = []; V.history = []; V.pv = null; V.pvSince = 0; V.pvLines = [];
    W.barSig = W.stageSig = W.logSig = ""; V.run = null; V.runData = null; V.steps = []; V.since = 0; V.tab = "changes"; V.mtab = "chat"; V.open = new Set(); V.lastChangeSig = ""; V.lastAppr = "";
    buildWorkspace();
    await refreshProject(true);
    if (V.info && V.info.active_run) attachRun(V.info.active_run);
    if (!V.info || !V.info.active_run) { await refreshChanges(); if (!V.changes.length) V.tab = "preview"; selectTab(V.tab); }
    startLoop();
  }
  const refreshProject = quiet(async (first) => {
    if (!V.name) return;
    const info = await api("/api/vibe/projects/" + encodeURIComponent(V.name));
    V.info = info; renderHeader(); renderApprovals();
    if (first) { await Promise.all([refreshTree(), refreshHistory()]); }
  });
  const refreshTree = quiet(async () => { if (!V.name) return; V.tree = (await api("/api/vibe/projects/" + encodeURIComponent(V.name) + "/tree")).files; renderTree(); });
  const refreshHistory = quiet(async () => { if (!V.name) return; V.history = (await api("/api/vibe/projects/" + encodeURIComponent(V.name) + "/history")).runs; renderHistory(); });
  const refreshChanges = quiet(async () => {
    if (!V.name) return;
    const r = await api("/api/vibe/projects/" + encodeURIComponent(V.name) + "/changes");
    const sig = r.changes.map((c) => c.id + c.status + c.added + c.removed).join("|") + (r.auto_accept ? "A" : "");
    V.changes = r.changes; V.auto = r.auto_accept;
    if (sig !== V.lastChangeSig) { V.lastChangeSig = sig; renderChanges(); }
    renderTabs();
  });

  function buildWorkspace() {
    root.replaceChildren(); root.className = "vb vb-ws";
    W.title = h("div", { class: "vb-title" });
    W.actions = h("div", { class: "vb-actions" });
    W.mode = null;
    const top = h("div", { class: "vb-top" }, h("button", { class: "vb-back", type: "button", "aria-label": "Back to projects", onclick: guard(async () => { stopRunTimers(); await loadHome(); renderPicker(); }) }, ic("chev", "flip"), h("span", { text: "Projects" })), W.title, W.actions,
      h("button", { class: "x", type: "button", "aria-label": "Close Vibe Coding", onclick: () => D.close(), text: "×" }));
    // mobile tabs (chat | changes | code | preview | history)
    W.mtabs = h("div", { class: "vb-mtabs", role: "tablist", "aria-label": "Workspace sections" });
    // chat column
    W.phase = h("div", { class: "vb-phase", "aria-live": "polite" });
    W.feed = h("div", { class: "vb-feed", role: "log", "aria-label": "Conversation with the coding agent" });
    W.appr = h("div", { class: "vb-appr", "aria-live": "assertive" });
    W.live = h("pre", { class: "vb-live", hidden: true });
    W.input = h("textarea", { rows: 3, maxlength: 6000, placeholder: "Describe what to build or change…", "aria-label": "Message to the coding agent",
      onkeydown: (e) => { if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); W.form.requestSubmit(); } } });
    W.send = h("button", { class: "btn go", type: "submit" }, ic("send"), "Build");
    W.stop = h("button", { class: "btn no", type: "button", hidden: true, onclick: guard(cancelRun) }, ic("stop"), "Stop");
    W.chips = h("div", { class: "vb-chips" });
    W.form = h("form", { class: "vb-compose", onsubmit: guard(async (e) => { e.preventDefault(); await sendPrompt(W.input.value); }) },
      W.chips, W.input, h("div", { class: "vb-compose-row" }, h("small", { text: "Enter to send · Shift+Enter for a new line" }), h("span", { class: "vb-sp" }), W.stop, W.send));
    W.chat = h("section", { class: "vb-col vb-chat", "aria-label": "Chat" }, W.phase, W.feed, W.live, W.appr, W.form);
    // right column
    W.tabs = h("div", { class: "vb-tabs", role: "tablist", "aria-label": "Project panels" });
    W.pChanges = h("div", { class: "vb-pane", role: "tabpanel" }); W.pCode = h("div", { class: "vb-pane", role: "tabpanel" });
    W.pPreview = h("div", { class: "vb-pane", role: "tabpanel" }); W.pHistory = h("div", { class: "vb-pane", role: "tabpanel" });
    W.right = h("section", { class: "vb-col vb-right", "aria-label": "Project" }, W.tabs, W.pChanges, W.pCode, W.pPreview, W.pHistory);
    root.append(top, W.mtabs, h("div", { class: "vb-body" }, W.chat, W.right));
    buildTabs(); buildHeader(); buildCode(); buildPreview();
    renderChips(); renderHeader(); renderTabs(); renderChanges(); renderHistory(); renderPhase(); selectTab(V.tab);
  }

  function buildHeader() {
    W.mode = h("span", { class: "vb-pill" });
    W.btnVs = h("button", { class: "btn sm", type: "button", title: "Open this folder in VS Code", onclick: guard(openVsCode) }, ic("code"), h("span", { text: "VS Code" }));
    W.btnUndo = h("button", { class: "btn sm", type: "button", title: "Go back to how the files were before the last run (asks first)", onclick: guard(undoLast) }, ic("undo"), h("span", { text: "Undo" }), h("span", { class: "long", text: "last run" }));
    W.actions.append(W.mode, W.btnVs, W.btnUndo);
    W.tName = h("b"); W.tSub = h("small");
    W.title.append(ic("spark"), h("div", {}, W.tName, W.tSub));
  }
  function renderHeader() {
    if (!W.title || !W.mode) return;
    const i = V.info;
    W.tName.textContent = V.name || "";
    const sig = i ? (i.kind || "") + "|" + (i.branch || "") : "";
    if (W.tSub.dataset.sig !== sig) { W.tSub.dataset.sig = sig; W.tSub.replaceChildren(document.createTextNode(i ? (i.kind || "") : "")); if (i && i.branch) W.tSub.append(ic("branch", "vb-bi"), document.createTextNode(i.branch)); }
    const ai = V.status && V.status.mode === "ai";
    W.mode.className = "vb-pill " + (ai ? "ok" : "warn"); W.mode.textContent = ai ? "AI · " + (V.status.llm.model || "model") : "Offline rules";
    const running = V.runData && V.runData.active;
    W.btnUndo.disabled = !!running || !(V.history[0] && V.history[0].can_undo);
  }
  function renderChips() {
    if (!W.chips) return;
    W.chips.replaceChildren();
    if (V.steps.length) return;
    const kind = (V.info && (V.info.template || V.info.kind)) || "static";
    (SUGGEST[kind] || SUGGEST.blank).forEach((t) => W.chips.append(h("button", { type: "button", class: "chip", text: t, onclick: () => { W.input.value = t; W.input.focus(); } })));
  }

  /* tabs */
  function buildTabs() {
    [[W.tabs, false], [W.mtabs, true]].forEach(([box, mobile]) => {
      box.replaceChildren();
      (mobile ? ["chat", "changes", "code", "preview", "history"] : ["changes", "code", "preview", "history"]).forEach((k) => {
        box.append(h("button", { type: "button", role: "tab", class: "vb-tab", data: { k, m: mobile ? "1" : "" }, onclick: () => { if (mobile) { V.mtab = k; if (k !== "chat") V.tab = k; selectTab(V.tab); } else { V.tab = k; if (V.mtab === "chat") V.mtab = k; selectTab(k); } } },
          h("span", { text: k === "chat" ? "Chat" : TAB_LABEL[k] }), h("em", { class: "vb-badge", hidden: true }), h("i", { class: "vb-dot ok", hidden: true, "aria-hidden": "true" })));
      });
    });
  }
  function renderTabs() {
    if (!W.tabs) return;
    const n = V.changes.length, pvOn = V.pv && V.pv.status === "running";
    [W.tabs, W.mtabs].forEach((box) => Array.from(box.children).forEach((b) => {
      const k = b.dataset.k, mobile = b.dataset.m === "1", cur = mobile ? V.mtab === k : V.tab === k;
      b.classList.toggle("on", cur); b.setAttribute("aria-selected", String(cur));
      const bd = b.querySelector(".vb-badge"), dot = b.querySelector(".vb-dot");
      bd.hidden = !(k === "changes" && n); bd.textContent = String(n); if (!bd.hidden) bd.setAttribute("aria-label", n + " files to review");
      dot.hidden = !(k === "preview" && pvOn);
    }));
  }
  function selectTab(k) {
    V.tab = k;
    const panes = { changes: W.pChanges, code: W.pCode, preview: W.pPreview, history: W.pHistory };
    Object.entries(panes).forEach(([key, el]) => { el.hidden = key !== k; });
    root.dataset.mtab = V.mtab; root.classList.toggle("m-chat", V.mtab === "chat");
    renderTabs();
    if (k === "code") { renderTree(); if (!V.file && V.tree.length) { const first = V.tree.find((f) => f.type === "file" && /^(index\.html|main\.py|server\.js|src\/App\.jsx|App\.jsx|README\.md)$/.test(f.path)) || V.tree.find((f) => f.type === "file"); if (first) openFile(first.path); } }
    if (k === "preview") renderPreview();
    if (k === "history") refreshHistory();
    if (k === "changes") refreshChanges();
  }

  /* -------------------------------------------------------------- run handling */
  function stepNode(s) {
    const k = s.kind;
    if (k === "user") return h("div", { class: "vb-m user" }, h("div", { class: "vb-bub", text: s.text }));
    if (k === "done") return h("div", { class: "vb-m bot" }, h("div", { class: "vb-who", text: "Delta" }), h("div", { class: "vb-bub " + (s.status === "error" ? "err" : ""), text: s.text }));
    if (k === "think") return h("div", { class: "vb-step think", text: s.text });
    if (k === "tool") return h("div", { class: "vb-step tool" }, ic(/^run/.test(s.text) ? "terminal" : /^(write|delete|patch)/.test(s.text) ? "file" : "search"), h("span", { text: s.text }));
    if (k === "result") return h("div", { class: "vb-step result " + (s.status || ""), text: s.text.length > 220 ? s.text.slice(0, 220) + "…" : s.text });
    if (k === "change") { const b = h("button", { type: "button", class: "vb-step chg", onclick: () => { V.tab = "changes"; V.mtab = "changes"; selectTab("changes"); } }, ic("file"), h("span", { text: s.text.replace(/\s+·\s+waiting for review$/, "") }), h("em", { text: "review" })); return b; }
    if (k === "approval") return h("div", { class: "vb-step info warn", text: "Waiting for your approval (card below)." });
    if (k === "error") return h("div", { class: "vb-step error", text: s.text });
    return h("div", { class: "vb-step info " + (s.status === "warn" ? "warn" : ""), text: s.text });
  }
  function appendSteps(steps) {
    const stick = W.feed.scrollHeight - W.feed.scrollTop - W.feed.clientHeight < 60;
    steps.forEach((s) => { V.steps.push(s); W.feed.append(stepNode(s)); });
    if (steps.length) { renderChips(); if (stick) W.feed.scrollTop = W.feed.scrollHeight; }
  }
  function renderPhase() {
    if (!W.phase) return;
    const r = V.runData, active = r && r.active;
    W.phase.className = "vb-phase" + (active ? " on " + (r.status === "waiting_approval" || r.status === "waiting_review" ? "wait" : "") : "");
    W.phase.replaceChildren();
    if (active) {
      W.phase.append(h("i", { class: "vb-pulse", "aria-hidden": "true" }), h("span", { text: r.phase || "Working" }), h("small", { text: r.mode === "rules" ? "offline rules" : "AI" }));
      if (r.tainted) W.phase.append(pill("untrusted text seen: commands ask first", "warn"));
    } else if (r) {
      W.phase.append(h("span", { text: r.phase || "" })); if (r.snapshot) W.phase.append(h("small", { text: "snapshot " + r.snapshot }));
    } else W.phase.append(h("span", { text: V.status && V.status.mode === "ai" ? "Ready. Tell me what to build." : "Ready (offline rules mode: simple edits only)." }));
    W.send.disabled = !!active; W.input.disabled = !!active; W.stop.hidden = !active;
    W.input.placeholder = active ? "Working… you can stop it at any time." : "Describe what to build or change…";
    if (r && r.live) { W.live.hidden = false; W.live.textContent = "$ " + r.live.command + "\n" + r.live.lines.join("\n"); W.live.scrollTop = W.live.scrollHeight; } else W.live.hidden = true;
  }
  function attachRun(run) { V.run = run.id; V.since = 0; V.steps = []; W.feed.replaceChildren(); V.runData = run; applyRun(run); }
  function applyRun(r) {
    V.runData = r;
    if (r.steps.length) appendSteps(r.steps);
    V.since = Math.max(V.since, r.next || 0);
    renderPhase(); renderApprovals();
    if ((r.changes || []).length || r.rev !== V.rev) { V.rev = r.rev; refreshChanges(); }
  }
  async function sendPrompt(text) {
    text = (text || "").trim(); if (!text || (V.runData && V.runData.active)) return;
    W.input.value = "";
    const r = await post("/api/vibe/projects/" + encodeURIComponent(V.name) + "/runs", { prompt: text });
    V.run = r.id; V.since = 0; V.rev = -1; W.chips.replaceChildren();
    V.runData = r; applyRun(r); V.mtab = "chat"; renderTabs(); renderHeader();
  }
  async function cancelRun() { if (V.run) { await post("/api/vibe/runs/" + V.run + "/cancel"); toast("Stopping", "The run will stop at the next safe point."); } }
  async function pollRun() {
    if (!V.run) return;
    const r = await api("/api/vibe/runs/" + V.run + "?since=" + V.since);
    const was = V.runData && V.runData.active;
    applyRun(r);
    if (was && !r.active) { await Promise.all([refreshProject(), refreshChanges(), refreshTree(), refreshHistory()]); renderHeader(); if (V.changes.length) { V.tab = "changes"; selectTab("changes"); } if (V.file) openFile(V.file.path, true); }
  }

  /* approvals (command / undo / auto-accept cards); decisions go to the same /api/confirm the main tray uses */
  function renderApprovals() {
    if (!W.appr) return;
    const list = [];
    const seen = new Set();
    [(V.runData && V.runData.active ? V.runData.approvals : []), (V.info && V.info.approvals) || []].forEach((a) => (a || []).forEach((p) => { if (!seen.has(p.id)) { seen.add(p.id); list.push(p); } }));
    const sig = list.map((p) => p.id).join(",");
    if (sig === V.lastAppr) { list.forEach((p) => { const e = W.appr.querySelector('[data-pid="' + p.id + '"] .exp'); if (e) e.textContent = "expires in " + p.expires_in + "s"; }); return; }
    V.lastAppr = sig; W.appr.replaceChildren();
    list.forEach((p) => {
      const decide = (ok) => guard(async () => { await post("/api/confirm", { id: p.id, approve: ok }); D.refreshState(); V.lastAppr = ""; await Promise.all([refreshProject(), V.run ? pollRun() : null, refreshChanges()]); })();
      const cmd = p.tool === "vibe_run_command";
      W.appr.append(h("div", { class: "vb-ap", role: "alertdialog", "aria-label": "Approval needed: " + p.description, data: { pid: p.id } },
        h("div", { class: "vb-ap-hd" }, ic("shield"), h("b", { text: cmd ? "Run this command?" : "Approval needed" }), h("span", { class: "exp", text: "expires in " + p.expires_in + "s" })),
        h("div", { class: "vb-ap-bd", text: p.description }),
        p.tainted ? h("div", { class: "vb-ap-warn", text: "⚠ This run read text that looked like instructions to an AI, so everything asks first." }) : null,
        cmd ? h("div", { class: "vb-ap-hint", text: "It runs in this project's folder with your permissions. Read it before you approve." }) : null,
        h("div", { class: "vb-ap-btn" }, h("button", { class: "btn go sm", type: "button", onclick: () => decide(true) }, ic("check"), "Approve"), h("button", { class: "btn no sm", type: "button", onclick: () => decide(false) }, ic("x"), "Deny"))));
    });
  }

  /* -------------------------------------------------------------- changes (review before apply) */
  function diffView(text) {
    const box = h("div", { class: "vb-diff", role: "group", "aria-label": "Diff" });
    let o = 0, n = 0, rows = 0;
    const frag = document.createDocumentFragment();
    for (const line of (text || "").split("\n")) {
      if (line.startsWith("--- ") || line.startsWith("+++ ")) continue;
      if (rows > MAX_LINES) { frag.append(h("div", { class: "dl hunk", text: "… more lines not shown …" })); break; }
      const m = /^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@/.exec(line);
      let cls = "ctx", sign = " ", a = "", b = "", t = line.slice(1);
      if (m) { o = +m[1]; n = +m[2]; frag.append(h("div", { class: "dl hunk" }, h("span", { class: "g" }), h("span", { class: "g" }), h("span", { class: "sg" }), h("span", { class: "tx", text: line }))); continue; }
      if (line.startsWith("+")) { cls = "add"; sign = "+"; b = n++; }
      else if (line.startsWith("-")) { cls = "del"; sign = "−"; a = o++; }
      else if (line.startsWith("\\")) { cls = "meta"; sign = ""; t = line; }
      else if (line === "" ) continue;
      else { a = o++; b = n++; }
      rows++;
      frag.append(h("div", { class: "dl " + cls }, h("span", { class: "g", text: String(a) }), h("span", { class: "g", text: String(b) }), h("span", { class: "sg", text: sign }), h("span", { class: "tx", text: t })));
    }
    box.append(frag); return box;
  }
  function renderChanges() {
    if (!W.pChanges) return;
    const p = W.pChanges, list = V.changes;
    const keepOpen = new Set(Array.from(p.querySelectorAll(".vb-ch[data-open='1']")).map((x) => x.dataset.id));
    p.replaceChildren();
    const auto = h("label", { class: "vb-auto" }, h("button", { type: "button", class: "sw-b", role: "switch", "aria-checked": String(!!V.auto), "aria-label": "Auto-accept changes", onclick: guard(toggleAuto) }),
      h("span", {}, h("b", { text: "Auto-accept" }), h("small", { text: V.auto ? "On: new files are written without asking. Undo last run still works." : "Off: you review every file before it is written." })));
    const hd = h("div", { class: "vb-ch-hd" },
      h("div", {}, h("b", { text: list.length ? list.length + " file" + (list.length === 1 ? "" : "s") + " waiting for your review" : "Nothing waiting for review" }),
        h("small", { text: list.length ? "Nothing is written until you accept." : "When the agent edits files, the diffs show up here first." })),
      list.length ? h("div", { class: "vb-ch-all" }, h("button", { class: "btn go sm", type: "button", onclick: guard(() => decideAll("accept")) }, ic("check"), "Accept all"), h("button", { class: "btn no sm", type: "button", onclick: guard(() => decideAll("reject")) }, ic("x"), "Reject all")) : null);
    p.append(hd, auto);
    if (!list.length) p.append(h("div", { class: "vb-empty" }, ic("check"), h("b", { text: "All caught up" }), h("small", { text: "Ask the agent for a change on the left." })));
    list.forEach((c, idx) => {
      const open = keepOpen.size ? keepOpen.has(c.id) : idx < 3;
      const card = h("article", { class: "vb-ch " + c.op, data: { id: c.id, open: open ? "1" : "0" }, "aria-label": c.op + " " + c.path });
      const dv = diffView(c.diff); dv.hidden = !open;
      const toggle = h("button", { type: "button", class: "vb-ch-t", "aria-expanded": String(open), onclick: () => { const o = dv.hidden; dv.hidden = !o; card.dataset.open = o ? "1" : "0"; toggle.setAttribute("aria-expanded", String(o)); } },
        ic("chev", "vb-chev"), h("span", { class: "vb-op " + c.op, text: c.op === "create" ? "NEW" : c.op === "delete" ? "DELETE" : "EDIT" }), h("b", { class: "mono", text: c.path }),
        h("span", { class: "vb-pm" }, h("i", { class: "p", text: "+" + c.added }), h("i", { class: "m", text: "−" + c.removed })));
      card.append(h("header", {}, toggle, h("div", { class: "vb-ch-b" },
        h("button", { class: "btn go sm", type: "button", "aria-label": "Accept " + c.path, onclick: guard(() => decide(c.id, "accept")) }, ic("check"), "Accept"),
        h("button", { class: "btn no sm", type: "button", "aria-label": "Reject " + c.path, onclick: guard(() => decide(c.id, "reject")) }, ic("x"), "Reject"))), dv);
      p.append(card);
    });
  }
  async function decide(id, what) {
    const r = await post("/api/vibe/changes/" + id + "/" + what);
    if (r.result.status !== "ok") toast("Review", r.result.text, "err");
    await Promise.all([refreshChanges(), refreshTree(), refreshProject(), V.run ? pollRun() : null]); if (V.file) openFile(V.file.path, true);
  }
  async function decideAll(what) {
    const r = await post("/api/vibe/projects/" + encodeURIComponent(V.name) + "/changes/" + what + "_all");
    const bad = r.results.filter((x) => x.status !== "ok"); if (bad.length) toast("Review", bad[0].text, "err"); else toast(what === "accept" ? "Accepted" : "Rejected", r.results.length + " file" + (r.results.length === 1 ? "" : "s"));
    await Promise.all([refreshChanges(), refreshTree(), refreshProject()]); if (V.file) openFile(V.file.path, true);
  }
  async function toggleAuto() {
    const r = reportResult(await post("/api/vibe/projects/" + encodeURIComponent(V.name) + "/auto_accept", { enabled: !V.auto }));
    V.lastChangeSig = ""; await Promise.all([refreshChanges(), refreshProject()]);
  }

  /* -------------------------------------------------------------- code viewer */
  function buildCode() {
    W.tree = h("div", { class: "vb-tree", role: "tree", "aria-label": "Project files" });
    W.codeHd = h("div", { class: "vb-code-hd" });
    W.code = h("div", { class: "vb-code", tabindex: "0", role: "region", "aria-label": "File contents" });
    W.pCode.append(h("div", { class: "vb-codewrap" }, W.tree, h("div", { class: "vb-view" }, W.codeHd, W.code)));
    W.code.append(h("div", { class: "vb-empty" }, ic("file"), h("b", { text: "Pick a file" })));
  }
  function renderTree() {
    if (!W.tree) return;
    W.tree.replaceChildren();
    if (!V.tree.length) { W.tree.append(h("small", { class: "vb-note", text: "No files yet." })); return; }
    V.tree.forEach((f) => {
      const parts = f.path.split("/"), depth = parts.length - 1;
      let hidden = false;
      for (let i = 1; i <= depth; i++) if (!V.open.has(parts.slice(0, i).join("/"))) { hidden = true; break; }
      if (hidden) return;
      if (f.type === "dir") {
        const o = V.open.has(f.path);
        W.tree.append(h("button", { type: "button", role: "treeitem", class: "vb-ti dir", style: "--d:" + depth, "aria-expanded": String(o), onclick: () => { if (o) V.open.delete(f.path); else V.open.add(f.path); renderTree(); } },
          ic("chev", "vb-chev" + (o ? " o" : "")), h("span", { text: parts[depth] })));
      } else {
        const cur = V.file && V.file.path === f.path;
        W.tree.append(h("button", { type: "button", role: "treeitem", class: "vb-ti file" + (cur ? " on" : ""), style: "--d:" + depth, "aria-selected": String(!!cur), onclick: () => openFile(f.path) },
          ic("file"), h("span", { text: parts[depth] }), f.pending ? h("i", { class: "vb-dot warn", title: "has a change waiting for review" }) : null));
      }
    });
  }
  async function openFile(path, quietly) {
    const key = V.name + "/" + path;
    try {
      const f = await api("/api/vibe/projects/" + encodeURIComponent(V.name) + "/file?path=" + encodeURIComponent(path));
      V.file = f; V.fileKey = key;
      path.split("/").slice(0, -1).reduce((acc, p) => { const q = acc ? acc + "/" + p : p; V.open.add(q); return q; }, "");
      renderTree(); renderFile();
    } catch (e) { if (!quietly) toast("Code", e.message, "err"); }
  }
  function renderFile() {
    const f = V.file; if (!f) return;
    W.codeHd.replaceChildren(...[h("b", { class: "mono", text: f.path }), pill(f.lang), f.staged ? pill("staged, not written yet", "warn") : null, h("span", { class: "vb-sp" }),
      h("small", { text: fmtSize(f.size) + (f.truncated ? " · showing the first 400 KB" : "") }),
      h("button", { class: "btn sm", type: "button", onclick: guard(openVsCode), title: "Open the project folder in VS Code" }, ic("code"), h("span", { text: "Open in VS Code" }))].filter(Boolean));
    W.code.replaceChildren();
    if (f.binary) { W.code.append(h("div", { class: "vb-empty" }, ic("image"), h("b", { text: "Binary file" }), h("small", { text: "Not shown here." }))); return; }
    const lines = toLines(tokenize(f.text, f.lang));
    const shown = lines.slice(0, MAX_LINES), pad = String(shown.length).length;
    const frag = document.createDocumentFragment();
    shown.forEach((parts, i) => {
      const code = h("span", { class: "c" });
      parts.forEach(([t, s]) => code.append(t ? h("span", { class: "tk-" + t, text: s }) : document.createTextNode(s)));
      if (!parts.length) code.append(document.createTextNode(" "));
      frag.append(h("div", { class: "cl" }, h("span", { class: "ln", text: String(i + 1).padStart(pad, " "), "aria-hidden": "true" }), code));
    });
    if (lines.length > MAX_LINES) frag.append(h("div", { class: "cl" }, h("span", { class: "ln" }), h("span", { class: "c tk-c", text: "… " + (lines.length - MAX_LINES) + " more lines not shown …" })));
    W.code.append(frag); W.code.scrollTop = 0;
  }
  const fmtSize = (n) => n < 1024 ? n + " B" : n < 1048576 ? (n / 1024).toFixed(1) + " KB" : (n / 1048576).toFixed(1) + " MB";
  async function openVsCode() { reportResult(await post("/api/vibe/projects/" + encodeURIComponent(V.name) + "/open_in_vscode"), "Opening VS Code"); }

  /* -------------------------------------------------------------- live preview */
  function buildPreview() {
    W.pvBar = h("div", { class: "vb-pvbar" }); W.pvStage = h("div", { class: "vb-pvstage" }); W.pvLog = h("div", { class: "vb-pvlog" });
    W.pPreview.append(W.pvBar, W.pvStage, W.pvLog);
  }
  /* The preview runs AI-written code on its own loopback port. It is shown on the OTHER loopback host name (localhost vs 127.0.0.1) so the
     browser never sends the Delta session cookie to it. */
  function frameUrl(u) { try { const x = new URL(u); x.hostname = location.hostname === "localhost" ? "127.0.0.1" : "localhost"; return x.href; } catch (e) { return ""; } }
  const pvStart = () => post("/api/vibe/projects/" + encodeURIComponent(V.name) + "/preview/start").then((r) => { reportResult(r, "Preview"); pollPreview(); });
  const pvStop = () => post("/api/vibe/projects/" + encodeURIComponent(V.name) + "/preview/stop").then((r) => { reportResult(r, "Preview stopped"); pollPreview(); });
  async function pvFix() { const r = await post("/api/vibe/projects/" + encodeURIComponent(V.name) + "/preview/fix"); V.mtab = "chat"; V.run = r.id; V.since = 0; V.rev = -1; V.runData = r; applyRun(r); renderTabs(); toast("Fixing", "The agent is looking at the error. Review its changes in the Changes tab."); }
  async function pollPreview() {
    if (!V.name) return;
    const s = await api("/api/vibe/projects/" + encodeURIComponent(V.name) + "/preview?since=" + V.pvSince);
    const prev = V.pv; V.pv = s; V.pvSince = s.next || V.pvSince;
    if (s.lines.length) V.pvLines = V.pvLines.concat(s.lines).slice(-400);
    if (s.status === "stopped" && (!prev || prev.status !== "stopped")) V.pvLines = V.pvLines.slice(-400);
    renderPreview(); renderTabs();
  }
  function renderPreview() {
    if (!W.pvBar) return;
    const s = V.pv || { status: "stopped", url: "", message: "Not running.", errors: [], can_fix: false, kind: "", lines: [] };
    const running = s.status === "starting" || s.status === "running";
    const barSig = [s.status, s.url, V.device, s.message].join("|");
    if (W.barSig !== barSig) {
      W.barSig = barSig;
      W.pvBar.replaceChildren(...[
        running ? h("button", { class: "btn sm no", type: "button", onclick: guard(pvStop) }, ic("stop"), "Stop") : h("button", { class: "btn sm go", type: "button", onclick: guard(pvStart) }, ic("play"), s.status === "stopped" ? "Start preview" : "Restart"),
        h("button", { class: "btn sm", type: "button", disabled: s.status === "running" ? null : true, onclick: () => { V.frameKey++; renderPreview(); } }, ic("refresh"), "Refresh"),
        h("button", { class: "btn sm", type: "button", "aria-pressed": String(V.device === "phone"), onclick: () => { V.device = V.device === "phone" ? "desktop" : "phone"; renderPreview(); } }, ic("eye"), V.device === "phone" ? "Phone width" : "Full width"),
        s.status === "running" ? h("a", { class: "btn sm", href: frameUrl(s.url), target: "_blank", rel: "noopener noreferrer" }, ic("link"), "Open in tab") : null,
        h("span", { class: "vb-sp" }),
        h("span", { class: "vb-pv-st " + s.status }, h("i", { class: "vb-dot " + (s.status === "running" ? "ok" : s.status === "crashed" ? "bad" : s.status === "starting" ? "warn" : "") }), h("span", { text: s.status === "running" ? s.url.replace("http://", "") : s.message }))].filter(Boolean));
    }
    const stageSig = [s.status, s.url, V.device, V.frameKey, s.status === "crashed" || s.status === "starting" ? s.message : ""].join("|");
    if (W.stageSig !== stageSig) {
      W.stageSig = stageSig;
      W.pvStage.replaceChildren(); W.pvStage.className = "vb-pvstage " + V.device;
      if (s.status === "running" && s.url) {
        const fr = h("iframe", { class: "vb-frame", src: frameUrl(s.url) + (V.frameKey ? "?_r=" + V.frameKey : ""), title: "Live preview of " + V.name, referrerpolicy: "no-referrer",
          sandbox: "allow-scripts allow-same-origin allow-forms allow-modals allow-popups" });
        W.pvStage.append(fr, h("small", { class: "vb-pv-note", text: "Runs on its own port, in a sandboxed frame, separate from Delta." }));
      } else if (s.status === "done") W.pvStage.append(h("div", { class: "vb-empty" }, ic("check"), h("b", { text: "Script finished" }), h("small", { text: "Output is in the log below." })));
      else if (s.status === "crashed") W.pvStage.append(h("div", { class: "vb-empty bad" }, ic("x"), h("b", { text: "It didn't start" }), h("small", { text: s.message })));
      else if (s.status === "starting") W.pvStage.append(h("div", { class: "vb-empty" }, h("i", { class: "vb-pulse" }), h("b", { text: s.message || "Starting…" }), h("small", { text: "The first start may install packages." })));
      else W.pvStage.append(h("div", { class: "vb-empty" }, ic("eye"), h("b", { text: "Live preview" }), h("small", { text: "Press Start preview to run the project on a private local port. Static sites open instantly." })));
    }
    // log: header rebuilt only when counts change, lines appended in place
    const errs = s.errors || [];
    const logSig = [V.logsOpen, errs.length, !!s.can_fix].join("|");
    if (W.logSig !== logSig) {
      W.logSig = logSig;
      W.pvLog.replaceChildren(h("div", { class: "vb-pvlog-hd" }, ...[h("button", { type: "button", class: "vb-ch-t", "aria-expanded": String(V.logsOpen), onclick: () => { V.logsOpen = !V.logsOpen; W.logSig = ""; W.logN = -1; renderPreview(); } }, ic("chev", "vb-chev" + (V.logsOpen ? " o" : "")), h("b", { text: "Logs" }),
        ...(errs.length ? [pill(errs.length + " error" + (errs.length === 1 ? "" : "s"), "bad")] : [])), h("span", { class: "vb-sp" }),
        s.can_fix ? h("button", { class: "btn sm go", type: "button", onclick: guard(pvFix) }, ic("spark"), "Fix this error") : null].filter(Boolean)));
      W.pre = null;
      if (V.logsOpen) { W.pre = h("pre", { class: "vb-logs", tabindex: "0", "aria-label": "Preview log" }); W.pvLog.append(W.pre); W.logN = -1; }
    }
    if (W.pre && W.logN !== V.pvLines.length + ":" + (V.pvLines.length ? V.pvLines[V.pvLines.length - 1].i : 0)) {
      W.logN = V.pvLines.length + ":" + (V.pvLines.length ? V.pvLines[V.pvLines.length - 1].i : 0);
      const stick = W.pre.scrollHeight - W.pre.scrollTop - W.pre.clientHeight < 40;
      const errSet = new Set(errs.map((e) => e.i));
      W.pre.replaceChildren(...(V.pvLines.length ? V.pvLines : [{ i: 0, t: "(no output yet)" }]).slice(-120).map((l) => h("div", { class: "lg" + (errSet.has(l.i) || /^ERROR|\[browser\]|Traceback|Error\b/.test(l.t) ? " er" : ""), text: l.t })));
      if (stick) W.pre.scrollTop = W.pre.scrollHeight;
    }
  }

  /* -------------------------------------------------------------- history / undo */
  function renderHistory() {
    if (!W.pHistory) return;
    const p = W.pHistory; p.replaceChildren();
    p.append(h("div", { class: "vb-ch-hd" }, h("div", {}, h("b", { text: "Runs" }), h("small", { text: "Every run starts with a git snapshot, so the last one can always be undone." }))));
    if (!V.history.length) p.append(h("div", { class: "vb-empty" }, ic("clock"), h("b", { text: "No runs yet" })));
    V.history.forEach((r) => p.append(h("article", { class: "vb-run " + r.status + (r.undone ? " undone" : "") },
      h("div", { class: "vb-run-t" }, h("b", { text: r.prompt }), pill(r.undone ? "undone" : r.status === "done" ? "done" : r.status, r.undone ? "dim" : r.status === "done" ? "ok" : r.status === "error" ? "bad" : "warn")),
      h("small", { text: ago(r.ts) + " · " + (r.mode === "rules" ? "offline rules" : "AI") + (r.files && r.files.length ? " · " + r.files.join(", ") : " · no file changes") + (r.snapshot ? " · snapshot " + r.snapshot.slice(0, 7) : "") }),
      r.summary ? h("p", { text: r.summary }) : null,
      r.can_undo ? h("button", { class: "btn sm", type: "button", onclick: guard(undoLast) }, ic("undo"), "Undo this run") : null)));
    renderHeader();
  }
  async function undoLast() { reportResult(await post("/api/vibe/projects/" + encodeURIComponent(V.name) + "/undo"), "Undone"); D.refreshState(); await refreshProject(); }

  /* -------------------------------------------------------------- loop */
  let timer = null;
  function startLoop() {
    stopRunTimers();
    timer = setInterval(async () => {
      if (V.dead || document.hidden || !V.name) return;
      V.tick++;
      const active = V.runData && V.runData.active;
      try {
        if (active) await pollRun();
        if (V.tick % (active ? 3 : 4) === 0) { await refreshProject(); if (!active || V.tick % 6 === 0) await refreshChanges(); }
        const pvOn = V.pv && (V.pv.status === "starting" || V.pv.status === "running");
        if (pvOn || V.tab === "preview" || V.tick % 8 === 0) await pollPreview();
        if (V.tab === "code" && V.tick % 8 === 0) await refreshTree();
      } catch (e) { /* one failed poll must not stop the loop */ }
    }, 700);
  }
  function stopRunTimers() { if (timer) { clearInterval(timer); timer = null; } }

  /* -------------------------------------------------------------- start */
  root.append(h("p", { class: "vb-note", text: "Loading…" }));
  loadHome().then(() => { if (!V.dead) renderPicker(); }).catch((e) => { if (e.message !== "auth") root.replaceChildren(h("p", { class: "vb-note", text: "Could not load Vibe Coding: " + e.message })); });
  const upd = () => {};
  upd.destroy = () => { V.dead = true; stopRunTimers(); };
  upd.open = openProject;      // used by the demo / tests
  window.__vibe = { open: (n) => openProject(n), state: V };
  return upd;
}
window.DeltaVibe = { mount, tokenize, toLines };
})();
