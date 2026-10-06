/* Facetcast dashboard. Vanilla JS, no build step, CSP-safe (no inline handlers: every
   click goes through one delegated listener reading data-act / data-arg). */
"use strict";
const $ = s => document.querySelector(s);
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));
const S = {meta: null, runs: [], cur: null, d: null, engines: null, memory: null, view: "new", sel: null,
           g1n: null, g1p: null, tab: null, ig: 0, timer: null, drawer: false, models: {}, ver: Date.now(),
           prompt: null, fold: {}, saved: null, busyAct: false};
const PF = {linkedin: ["in", "LinkedIn"], x: ["𝕏", "X"], instagram: ["IG", "Instagram"], tiktok: ["♪", "TikTok / Reels"], github: ["GH", "GitHub & Portfolio"]};
const STL = {pending: "idle", running: "working", success: "done", done: "done", waiting: "needs answer", gate: "your turn",
             failed: "failed", skipped: "skipped", cancelled: "—"};
const pf = (p, label = true) => `<span class="pf pf-${p}"><i>${PF[p] ? PF[p][0] : "?"}</i>${label ? esc(PF[p] ? PF[p][1] : p) : ""}</span>`;
const pct = x => Math.round((x || 0) * 100);

/* ---------------- api ---------------- */
async function api(path, opt = {}) {
  const r = await fetch(path, opt);
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(j.error || r.statusText);
  return j;
}
const post = (p, body) => api(p, {method: "POST", headers: {"Content-Type": "application/json", "X-Facetcast": "1"}, body: JSON.stringify(body || {})});
function toast(msg, ok) { const t = $("#toast"); t.textContent = msg; t.className = "toast show" + (ok ? " ok" : ""); clearTimeout(t._h); t._h = setTimeout(() => t.className = "toast", ok ? 2600 : 8000); }
const kitUrl = rel => `/api/runs/${encodeURIComponent(S.cur)}/kit/${rel.split("/").map(encodeURIComponent).join("/")}?v=${S.ver}`;
const clock = iso => { const t = Date.parse(iso); return t ? new Date(t).toLocaleTimeString([], {hour: "numeric", minute: "2-digit", second: "2-digit", hour12: true}) : ""; };
const since = iso => { const t = Date.parse(iso); if (!t) return ""; const s = Math.max(0, Math.round((Date.now() - t) / 1000)); return s < 60 ? s + "s" : Math.floor(s / 60) + "m " + (s % 60) + "s"; };
async function copy(text, what) {
  try { await navigator.clipboard.writeText(text); }
  catch (e) { const a = document.createElement("textarea"); a.value = text; document.body.appendChild(a); a.select(); document.execCommand("copy"); a.remove(); }
  toast(`${what || "Text"} copied.`, true);
}

function go(id, view) {
  S.cur = id; S.d = null; S.sel = null; S.g1n = null; S.g1p = null; S.tab = null; S.ig = 0; S.prompt = null;
  S.view = view || (id ? "run" : "new");
  history.replaceState(null, "", id ? "#" + id : "#");
  render(); refresh();
}

async function refresh() {
  clearTimeout(S.timer);
  try {
    [S.runs, S.engines] = await Promise.all([api("/api/runs"), api("/api/engines")]);
    if (S.view === "memory") S.memory = await api("/api/memory");
    if (S.cur) { try { S.d = await api("/api/runs/" + encodeURIComponent(S.cur)); } catch (e) { S.d = {starting: true}; } }
  } catch (e) { toast("Dashboard server not reachable: " + e.message); }
  render();
  const active = (S.d && (S.d.busy || S.d.starting)) || S.runs.some(r => r.busy);
  S.timer = setTimeout(refresh, active ? 900 : 4000);
}

/* ---------------- top bar ---------------- */
function renderTop() {
  const sel = $("#runSel");
  const opts = [`<option value="">Runs (${S.runs.length})</option>`].concat(S.runs.map(r => {
    const lab = r.busy ? "working" : r.gate ? (r.gate === "G1" ? "pick angle" : "review") : r.status;
    return `<option value="${esc(r.run_id)}" ${r.run_id === S.cur ? "selected" : ""}>${esc(r.project || r.run_id)} · ${esc(lab)} · ${esc(r.run_id.slice(0, 11))}</option>`;
  })).join("");
  if (sel.innerHTML !== opts && document.activeElement !== sel) sel.innerHTML = opts;
  const e = S.engines;
  if (e) {
    const a = e.engines.find(x => x.active) || {};
    $("#enginePill").innerHTML = `<span class="led ${a.ready ? "ok" : "warn"}"></span>${esc(a.label || e.active)}`;
  }
}

/* ---------------- new run ---------------- */
function engineBanner() {
  const e = S.engines; if (!e) return "";
  const a = e.engines.find(x => x.active) || {};
  if (a.ready && a.name !== "claude") return "";
  const msg = a.name === "claude"
    ? "Engine: <b>Manual copy-paste</b>. Works with no setup, but you paste each step into Claude yourself. For a hands-free run, use Claude Code or paste an API key."
    : `Engine <b>${esc(a.label)}</b> is not ready (${esc(a.why)}).`;
  return `<div class="banner"><span class="led warn"></span><div class="grow">${msg}</div><button class="btn sm" data-act="engines">Set up an engine</button></div>`;
}
function renderNew() {
  return `<div class="hero">
    <h1>One project in.<br><em>Every platform out.</em></h1>
    <p class="lead">Drop a GitHub repo, a zip or a project folder. Facetcast reads the README, learns how you write, finds the angles worth posting, and builds a ready-to-post kit for every platform. Every claim is checked against your own files.</p>
    <div class="platrow">${["linkedin", "x", "instagram", "tiktok", "github"].map(p => pf(p)).join("")}</div>
    ${engineBanner()}
    <div class="drop" id="drop" data-act="pick-file">
      <div class="icons">⬇</div>
      <div class="big">Drop a project folder or a .zip</div>
      <div class="sub">or <a href="#" data-act="pick-folder">choose a folder</a> · <a href="#" data-act="pick-file">choose a .zip</a> · any project with a README: code, a thesis, a design portfolio, research</div>
      <input type="file" id="fileIn" accept=".zip" hidden>
      <input type="file" id="folderIn" webkitdirectory multiple hidden>
    </div>
    <div class="or">OR PASTE A LINK OR A PATH</div>
    <div class="srcrow"><input id="src" placeholder="https://github.com/you/project   ·   C:\\Users\\you\\Projects\\my-thesis   ·   ~/work/app.zip">
      <button class="btn" data-act="start-url">Start</button></div>
    <div class="row" style="justify-content:center;margin-top:14px"><span class="muted">New here?</span><button class="btn ghost sm" data-act="demo">Try the demo (no engine, no key)</button></div>
    <div class="how">
      <div class="card"><span class="n">01</span><b>Read</b><span class="muted">Your README and files. Works for GitHub, GitLab, zips and local folders.</span></div>
      <div class="card"><span class="n">02</span><b>Learn your voice</b><span class="muted">Tone, rhythm and phrases come from how your README is written. No templates.</span></div>
      <div class="card"><span class="n">03</span><b>Pick the angle</b><span class="muted">5-8 angles, each scored per platform. You choose the angle and the platforms.</span></div>
      <div class="card"><span class="n">04</span><b>Post the kit</b><span class="muted">Post, thread, carousel, video script, GitHub + portfolio kit, graphics and a PDF.</span></div>
    </div></div>`;
}

const SKIP = new Set([".git", "node_modules", "__pycache__", ".venv", "venv", "env", "dist", "build", ".next", ".idea", ".vscode", "target", ".cache", ".DS_Store", "__MACOSX"]);
const TEXT = /\.(md|markdown|txt|rst|tex|org|adoc|html?|py|js|jsx|ts|tsx|go|rs|java|kt|swift|c|cc|cpp|h|cs|rb|php|sh|ps1|r|jl|scala|dart|lua|sql|vue|svelte|ino|sol|ya?ml|toml|json|csv|ipynb|css|scss|cfg|ini|lock|gradle|xml)$/i;
const IMG = /\.(png|jpe?g|gif|webp|svg)$/i;
async function walkEntry(entry, path, out) {
  if (SKIP.has(entry.name)) return;
  if (entry.isFile) { const f = await new Promise((res, rej) => entry.file(res, rej)); out.push({f, p: path + entry.name}); return; }
  const reader = entry.createReader();
  for (;;) {
    const batch = await new Promise((res, rej) => reader.readEntries(res, rej));
    if (!batch.length) break;
    for (const e of batch) await walkEntry(e, path + entry.name + "/", out);
  }
}
async function uploadFolder(files, name) {
  files = files.filter(x => !x.p.split("/").some(seg => SKIP.has(seg)));
  if (!files.length) return toast("That folder looks empty.");
  if (files.length > 20000) return toast("Too many files (20,000 max).");
  const enc = new TextEncoder(), parts = [];
  let total = 0, sent = 0;
  for (const {f, p} of files) {
    const full = (TEXT.test(p) && f.size < 3e6) || (IMG.test(p) && f.size < 8e6);
    const data = full ? new Uint8Array(await f.arrayBuffer()) : new Uint8Array(0);
    const head = enc.encode(JSON.stringify({p, n: data.length}));
    const len = new Uint8Array(4); new DataView(len.buffer).setUint32(0, head.length);
    parts.push(len, head, data); total += data.length; sent += full ? 1 : 0;
  }
  toast(`Uploading ${files.length} files (${(total / 1048576).toFixed(1)} MB)…`, true);
  try {
    const r = await api(`/api/upload-folder?name=${encodeURIComponent(name || "project")}`, {method: "POST", headers: {"X-Facetcast": "1"}, body: new Blob(parts)});
    go(r.run_id);
  } catch (e) { toast(e.message); }
}
async function uploadZip(f) {
  if (!f.name.toLowerCase().endsWith(".zip")) return toast("Drop a .zip or a folder.");
  toast(`Uploading ${f.name} (${(f.size / 1048576).toFixed(1)} MB)…`, true);
  try { const r = await api("/api/upload?name=" + encodeURIComponent(f.name), {method: "POST", headers: {"X-Facetcast": "1"}, body: f}); go(r.run_id); }
  catch (e) { toast(e.message); }
}
function wireNew() {
  const d = $("#drop"); if (!d || d._w) return; d._w = true;
  ["dragenter", "dragover"].forEach(e => d.addEventListener(e, ev => { ev.preventDefault(); d.classList.add("over"); }));
  ["dragleave", "drop"].forEach(e => d.addEventListener(e, ev => { ev.preventDefault(); d.classList.remove("over"); }));
  d.addEventListener("drop", async ev => {
    const items = [...(ev.dataTransfer.items || [])];
    const entry = items[0] && items[0].webkitGetAsEntry && items[0].webkitGetAsEntry();
    if (entry && entry.isDirectory) { const out = []; await walkEntry(entry, "", out); return uploadFolder(out, entry.name); }
    const f = ev.dataTransfer.files[0]; if (f) uploadZip(f);
  });
  $("#fileIn").addEventListener("change", e => e.target.files[0] && uploadZip(e.target.files[0]));
  $("#folderIn").addEventListener("change", e => {
    const fs = [...e.target.files]; if (!fs.length) return;
    uploadFolder(fs.map(f => ({f, p: f.webkitRelativePath || f.name})), (fs[0].webkitRelativePath || "project").split("/")[0]);
  });
  $("#src").addEventListener("keydown", e => { if (e.key === "Enter") act("start-url"); });
}

/* ---------------- pipeline + feed ---------------- */
function renderPipe(d) {
  const st = d.stages, done = st.filter(x => ["success", "done", "skipped"].includes(x.status)).length;
  return `<div class="pipe"><div class="stages">${st.map((s, i) => {
    const t = s.status === "running" && d.live ? since(d.live.since) : (s.ms != null && s.status !== "waiting" ? (s.ms < 1000 ? s.ms + "ms" : (s.ms / 1000).toFixed(1) + "s") : "");
    return `<div class="stg ${s.status} ${S.sel === s.tag ? "sel" : ""} ${i === st.length - 1 ? "last" : ""}" data-act="sel" data-arg="${s.tag}" title="${esc(s.error || s.title)}">
      <div class="t"><span>${s.tag}</span><span class="who who-${s.who}">${s.who === "ai" ? "AI" : s.who}</span></div>
      <div class="n">${esc(s.title)}</div><div class="s">${STL[s.status] || s.status}${t ? " · " + t : ""}</div></div>`;
  }).join("")}</div><div class="progress"><i style="width:${Math.round(done / st.length * 100)}%"></i></div></div>`;
}
function renderFeed(d) {
  const lv = d.live, s = d.summary;
  let head, body;
  if (lv && d.busy) {
    head = `<span style="color:var(--blue)">${esc(lv.tag)} ${esc(lv.name)}</span><span style="color:#636b80">· writing · ${since(lv.since)} · ${lv.chars.toLocaleString()} chars</span>`;
    body = lv.text ? esc(lv.text) + '<span class="cur"></span>' : `<span style="color:#636b80">thinking…</span> <span class="cur"></span>`;
  } else if (d.busy) {
    const cur = d.stages.find(x => x.status === "running");
    head = `<span style="color:var(--blue)">${esc(cur ? cur.tag + " " + cur.title : "working")}</span>`;
    body = `<span style="color:#636b80">working…</span> <span class="cur"></span>`;
  } else if (s.status === "waiting") {
    head = `<span style="color:var(--amber)">${esc((d.pending || [])[0])} waiting for an answer</span>`;
    body = `<span style="color:var(--amber)">Manual engine: paste the prompt into Claude (panel below), or switch to an automatic engine and resume.</span>`;
  } else if (s.gate) {
    head = `<span style="color:var(--brand)">${s.gate} · your turn</span>`;
    body = `<span style="color:#c9c2ff">${s.gate === "G1" ? "The angles are ready. Pick one and choose the platforms below." : "The kit is ready. Review every platform, edit if you like, then approve."}</span>`;
  } else {
    head = `<span>${esc(s.status)}</span>`;
    body = `<span style="color:#636b80">${s.status === "done" ? "Done. The kit is below." : "Idle."}</span>`;
  }
  const log = (d.events || []).map(e => {
    const t = clock(e.at);
    if (e.kind === "llm") {
      const cls = e.ok ? "ok" : e.waiting ? "wait" : "bad";
      const what = e.waiting ? "prompt ready, waiting" : e.ok ? `answer ok${e.repaired ? " (1 repair)" : ""}` : `error: ${esc(e.error || "")}`;
      return `<div><span class="t">${t}</span> <b>${esc(e.tag)}</b> <span class="${cls}">${esc(e.backend)}${e.model ? "/" + esc(e.model) : ""} · ${what}</span></div>`;
    }
    const cls = e.status === "success" ? "ok" : e.status === "failed" ? "bad" : "wait";
    return `<div><span class="t">${t}</span> <b>${esc(e.tag)}</b> <span class="${cls}">${esc(e.status)}</span> <span class="t">${e.ms != null ? (e.ms / 1000).toFixed(1) + "s" : ""}</span>${e.error && e.status === "failed" ? ` <span class="bad">${esc(e.error)}</span>` : ""}</div>`;
  }).join("") || `<div class="t">no activity yet</div>`;
  return `<div class="feed"><div class="fh"><span class="dots"><i></i><i></i><i></i></span>${head}</div>
    <div class="stream" id="stream">${body}</div><div class="log" id="log">${log}</div></div>`;
}

/* ---------------- actions by state ---------------- */
function renderAction(d) {
  const s = d.summary;
  if (d.error) return `<div class="card action failed"><h3 style="color:var(--red)">Last action failed</h3><p class="mono" style="white-space:pre-wrap">${esc(d.error)}</p><button class="btn ghost" data-act="resume">Retry</button></div>`;
  if (d.busy || d.starting) return "";
  if (s.status === "waiting") return renderWaiting(d);
  if (s.gate === "G1") return renderG1(d);
  if (s.gate === "G2") return renderKit(d, true);
  if (s.status === "failed") {
    const f = d.stages.find(x => x.status === "failed");
    return `<div class="card action failed"><h3 style="color:var(--red)">${esc(f && f.tag)} ${esc(f && f.title)} failed</h3>
      <p class="mono" style="white-space:pre-wrap">${esc(s.detail || (f && f.error) || "")}</p>
      <div class="row"><button class="btn ghost" data-act="resume">Retry this step</button><button class="btn ghost" data-act="engines">Change engine</button></div></div>`;
  }
  if (s.status === "done") {
    const m = s.memory_write || {};
    return `<div class="card action done" style="margin-bottom:16px"><div class="row"><h3 style="color:var(--green)">Approved and remembered</h3>
      <span class="chip">${Object.keys(m.post_ids || {}).length} platform(s) saved</span><span class="chip">${esc(m.angles_queued)} angles queued for next time</span>
      <span class="chip">${m.embedded ? "deduped next time" : "dedup off (optional)"}</span></div>
      <p class="muted" style="margin:8px 0 0">Future runs will not repeat this angle. Unused angles wait in Memory.</p></div>${renderKit(d, false)}`;
  }
  if (s.status === "rejected") return `<div class="card action"><h3>Rejected</h3><p class="muted">${esc(s.note)}. Nothing was saved.</p></div>`;
  return "";
}
function renderWaiting(d) {
  const [tag, name] = d.pending || ["", ""];
  const cc = S.engines && S.engines.engines.find(e => e.name === "claude_cli");
  const ready = S.engines && S.engines.engines.filter(e => e.ready && !["claude", "mock"].includes(e.name));
  return `<div class="card action waiting" style="margin-bottom:16px"><div class="row"><h3 style="color:var(--amber)">${esc(tag)} ${esc(name)} needs an answer</h3><span class="grow"></span>
    ${ready && ready.length ? `<button class="btn" data-act="auto-resume" data-arg="${esc(ready[0].name)}">Run it with ${esc(ready[0].label)}</button>` : `<button class="btn ghost" data-act="engines">Set up an automatic engine</button>`}</div>
    <p class="muted">You are on the manual engine. Three steps, about a minute:</p>
    <div class="steps">
      <div class="step"><div class="grow"><b>Copy the prompt</b><div class="row" style="margin-top:6px"><button class="btn sm" data-act="copy-prompt">Copy prompt</button><button class="btn ghost sm" data-act="view-prompt">${S.prompt ? "Hide" : "View"}</button></div>
        ${S.prompt ? `<pre class="prompt">${esc(S.prompt)}</pre>` : ""}</div></div>
      <div class="step"><div class="grow"><b>Paste it into any Claude chat</b><div class="muted">Claude replies with one JSON object. Copy all of it.</div></div></div>
      <div class="step"><div class="grow"><b>Paste the answer here</b><textarea class="resp" id="resp" placeholder='{"...": "..."}' style="margin-top:6px"></textarea>
        <div class="row" style="margin-top:8px"><button class="btn" data-act="send-resp">Submit and continue</button></div></div></div>
    </div>${cc && !cc.ready ? `<p class="dim" style="font-size:12.5px;margin-top:12px">Tip: install Claude Code once (<span class="mono">npm install -g @anthropic-ai/claude-code</span>, then run <span class="mono">claude</span> to log in) and every step runs by itself.</p>` : ""}</div>`;
}

/* ---------------- G1: angle + platforms ---------------- */
function gauge(p, c) { return `<div class="gauge" style="--p:${p};--c:${c}"><span>${p}%</span></div>`; }
function renderProfile(pr) {
  if (!pr) return "";
  const v = pr.voice || {};
  const fit = pr.platform_fit || {};
  return `<div class="voice">
    <div class="box"><h4>Your voice <span class="dim" style="font-weight:400">read from ${esc(pr.voice_source || "the README")}${pr.user_voice_used ? " + your posts" : ""}</span></h4>
      <div class="row">${(v.tone || []).map(t => `<span class="chip">${esc(t)}</span>`).join("")}<span class="chip">“${esc(v.person)}”</span><span class="chip">formality ${v.formality}/5</span><span class="chip">emoji ${esc(v.emoji)}</span></div>
      <p class="muted" style="margin:10px 0 0;font-size:13px">${esc(v.sentence_style)} ${esc(v.vocabulary)}</p>
      ${(v.signature_phrases || []).length ? `<p style="margin:8px 0 0;font-size:13px">Phrases kept: ${(v.signature_phrases).map(x => `<i>“${esc(x)}”</i>`).join(" · ")}</p>` : ""}
      <p style="margin:10px 0 0"><b>${esc(pr.positioning)}</b></p></div>
    <div class="box"><h4>Where this project lands <span class="dim" style="font-weight:400">README ${pr.readme ? pr.readme.score + "/100" : ""}</span></h4>
      ${Object.entries(fit).map(([p, f]) => `<div class="fitbar" title="${esc(f.why)}">${pf(p)}<div class="bar"><i style="width:${pct(f.score)}%"></i></div><span class="mono">${pct(f.score)}%</span></div>`).join("")}</div></div>`;
}
function renderG1(d) {
  const s = d.summary, rec = s.recommendation, angles = s.angles;
  if (S.g1n == null) { const r = angles.find(a => a.recommended) || angles[0]; S.g1n = r.n; S.g1p = new Set(r.default_platforms); }
  const cur = angles.find(a => a.n === S.g1n) || angles[0];
  const fitOf = p => p === "github" ? ((s.profile_fit || {}).github || {}).score : (cur.platform_fit || {})[p];
  return `<div class="card action gate" style="margin-bottom:16px"><div class="row"><h2>Pick the angle</h2><span class="grow"></span><span class="muted">Confidence = how sure the AI is it lands. Bars = fit per platform.</span></div>
    ${renderProfile(d.outputs.A04)}
    ${rec ? `<div class="rec"><span class="badge">RECOMMENDED</span><div class="grow"><b>${esc(rec.title)}</b><div class="muted" style="margin-top:3px">${esc(rec.reason || "")}</div></div></div>` : ""}
    <div class="angles">${angles.map(a => {
      const p = pct(a.score), col = p >= 80 ? "var(--green)" : p >= 65 ? "var(--brand)" : "var(--amber)";
      const fresh = a.max_similarity == null ? "dedup off" : a.max_similarity < 0.4 ? "fresh idea" : a.max_similarity < 0.7 ? "related to a past post" : "close to a past post";
      return `<div class="angle ${a.n === S.g1n ? "on" : ""}" data-act="g1-angle" data-arg="${a.n}">${a.recommended ? `<span class="ribbon badge">RECOMMENDED</span>` : ""}
        <div class="row">${gauge(p, col)}<div class="grow"><div class="row" style="gap:6px"><span class="chip">#${a.n}</span><span class="chip">${esc(a.post_type)}</span></div>
          <div class="dim" style="font-size:12px;margin-top:4px">${fresh}</div></div></div>
        <div class="ttl">${esc(a.title)}</div><div class="hook">${esc(a.hook)}</div>${a.why ? `<div class="why">${esc(a.why)}</div>` : ""}
        <div class="row" style="gap:6px">${(a.best_platforms || []).map(x => pf(x)).join("")}</div>
        <div class="minifit">${["linkedin", "x", "instagram", "tiktok"].map(x => `<div>${esc(PF[x][1].split(" ")[0])} ${pct((a.platform_fit || {})[x])}%<div class="bar ${(a.best_platforms || []).includes(x) ? "" : "amber"}"><i style="width:${pct((a.platform_fit || {})[x])}%"></i></div></div>`).join("")}</div></div>`;
    }).join("")}</div>
    <div class="pickbar"><b>Make a kit for:</b>${["linkedin", "x", "instagram", "tiktok", "github"].map(p => `<button class="toggle ${S.g1p.has(p) ? "on" : ""}" data-act="g1-plat" data-arg="${p}">${pf(p)}<span class="fit">${fitOf(p) != null ? pct(fitOf(p)) + "%" : ""}</span></button>`).join("")}
      <span class="grow"></span><span class="muted" style="font-size:12.5px">Angle #${cur.n}</span><button class="btn" data-act="g1-go" ${S.g1p.size ? "" : "disabled"}>Write the kit →</button></div></div>`;
}

/* ---------------- G2 / done: the kit ---------------- */
function initials(b) { const s = (b.name || b.handle || b.project || "Me").replace("@", ""); return s.split(/[\s_-]+/).map(w => w[0]).join("").slice(0, 2).toUpperCase(); }
function fmtLi(t) { return esc(t).replace(/(^|\s)(#[A-Za-z0-9_]+)/g, '$1<span class="tag">$2</span>'); }
function renderKit(d, review) {
  const k = d.kit; if (!k) return "";
  const plats = k.platforms; if (!S.tab || !plats.includes(S.tab)) S.tab = plats[0];
  const p = S.tab, s = d.summary;
  const scores = (d.outputs.A09 || {}).scores || {};
  const prev = {linkedin: previewLinkedIn, x: previewX, instagram: previewIG, tiktok: previewTikTok, github: previewGitHub}[p](k, d);
  return `<div class="kitwrap" style="margin-bottom:16px"><div>
      <div class="tabs">${plats.map(x => `<button class="tab ${x === p ? "on" : ""}" data-act="tab" data-arg="${x}">${pf(x)}${k.edited.includes(x) ? '<span class="ed">edited</span>' : ""}</button>`).join("")}</div>
      ${prev}</div>
    <div class="side">
      ${review ? `<div class="card" style="padding:14px"><div class="row"><button class="btn good grow" data-act="approve">Approve the kit</button><button class="btn danger" data-act="reject">Reject</button></div>
        <p class="dim" style="font-size:12px;margin:8px 0 0">Approving saves it to memory so future runs never repeat this angle.</p></div>` : ""}
      <div class="card" style="padding:14px"><h4 style="margin-bottom:8px">Graphics theme</h4><div class="swatches">${(S.meta ? S.meta.themes : []).map(t => `<button class="sw sw-${t} ${t === k.theme ? "on" : ""}" title="${t}" data-act="theme" data-arg="${t}"></button>`).join("")}</div>
        <div class="row" style="margin-top:12px">${k.has_pdf ? `<a class="btn sm" href="${kitUrl("00_REPORT.pdf")}" target="_blank" rel="noopener">Open PDF report</a>` : ""}
        <a class="btn ghost sm" href="${kitUrl("index.html")}" target="_blank" rel="noopener">Copy-paste page</a><button class="btn ghost sm" data-act="open-folder">Open folder</button></div>
        <div class="dim mono" style="font-size:11px;margin-top:8px;word-break:break-all">${esc(k.folder)}</div></div>
      ${k.warnings.length ? `<div class="warn"><b>Heads up</b>${k.warnings.map(w => `<div>${esc(w)}</div>`).join("")}</div>` : ""}
      ${scores[p] ? `<div class="card" style="padding:14px"><h4 style="margin-bottom:6px">Critic, first draft ${(d.outputs.A10 && d.outputs.A10.revised || []).includes(p) ? '<span class="chip">then revised</span>' : ""}</h4>${Object.entries(scores[p]).map(([a, v]) => `<div class="score"><span class="muted">${a}</span><div class="bar"><i style="width:${v * 20}%"></i></div><span class="mono">${v}</span></div>`).join("")}</div>` : ""}
      <div class="card" style="padding:14px"><h4>Evidence · ${k.claims.length} claims, all checked</h4>${k.claims.map(c => `<div class="claim">${esc(c.claim)}<br><span class="chip ev">${esc(c.source_path)}</span></div>`).join("")}</div>
    </div></div>`;
}
function copyBtn(label, key) { return `<button class="btn ghost sm" data-act="copy" data-arg="${esc(key)}">${esc(label)}</button>`; }
function previewLinkedIn(k, d) {
  const kk = k.kits.linkedin, b = k.brand, text = kk.post, fold = 210, open = S.fold.li;
  const shown = open || text.length <= fold ? text : text.slice(0, fold);
  return `<div class="stage2"><div class="li"><div class="who"><div class="av">${esc(initials(b))}</div><div><div class="nm">${esc(b.name || b.handle || "You")}</div><div class="hl">${esc(b.headline || "Your headline")} · now</div></div></div>
      <div class="body">${fmtLi(shown)}${!open && text.length > fold ? `<span class="more" data-act="fold" data-arg="li">…see more</span>` : ""}</div>
      <img src="${kitUrl("linkedin/graphic.png")}" alt="">
      <div class="acts"><span>Like</span><span>Comment</span><span>Repost</span><span>Send</span></div></div>
    <div><div class="copyrow">${copyBtn("Copy post", "linkedin.post")}${copyBtn("Copy first comment", "linkedin.first_comment")}${copyBtn("Copy alt text", "linkedin.alt_text")}
      <a class="btn ghost sm" href="${kitUrl("linkedin/graphic.png")}" download>Download image</a>${editBtn("linkedin")}</div>
      <div class="box"><h4>First comment</h4><pre>${esc(kk.first_comment)}</pre></div>
      <div class="box" style="margin-top:10px"><h4>Numbers</h4><span class="muted">${text.length} / 3000 chars. LinkedIn shows about the first 210 characters before “see more”, so the preview cuts there too.</span></div>${steps("linkedin")}</div></div>`;
}
function previewX(k) {
  const kk = k.kits.x, b = k.brand;
  return `<div class="stage2"><div class="thread">${kk.tweets.map((t, i) => {
    const n = [...t.replace(/https?:\/\/\S+/g, "x".repeat(23))].length;
    return `<div class="tw"><div class="av">${esc(initials(b))}</div><div class="line"></div><div class="grow"><div><span class="nm">${esc(b.name || "You")}</span> <span class="hd">${esc(b.handle || "@you")} · ${i + 1}/${kk.tweets.length}</span></div>
      <div style="white-space:pre-wrap">${esc(t)}</div>${i === 0 ? `<img src="${kitUrl("x/card.png")}" alt="">` : ""}<div class="cnt ${n > 280 ? "over" : ""}">${n}/280 <a href="#" data-act="copy-tweet" data-arg="${i}">copy</a></div></div></div>`;
  }).join("")}</div>
    <div><div class="copyrow">${copyBtn("Copy whole thread", "x.thread")}<a class="btn ghost sm" href="${kitUrl("x/card.png")}" download>Download card</a>${editBtn("x")}</div>${steps("x")}</div></div>`;
}
function previewIG(k) {
  const kk = k.kits.instagram, n = kk.slides.length; S.ig = Math.min(S.ig, n - 1);
  const cap = kk.caption, open = S.fold.ig;
  return `<div class="stage2"><div><div class="phone ig"><div class="screen"><img src="${kitUrl(`instagram/slide-${String(S.ig + 1).padStart(2, "0")}.png`)}" alt="">
      ${S.ig > 0 ? `<button class="nav prev" data-act="ig" data-arg="-1">‹</button>` : ""}${S.ig < n - 1 ? `<button class="nav next" data-act="ig" data-arg="1">›</button>` : ""}</div>
      <div class="dots2">${kk.slides.map((_, i) => `<i class="${i === S.ig ? "on" : ""}"></i>`).join("")}</div>
      <div class="igcap">${esc(open || cap.length <= 125 ? cap : cap.slice(0, 125))}${!open && cap.length > 125 ? ` <span class="dim" data-act="fold" data-arg="ig" style="cursor:pointer">… more</span>` : ""}</div></div></div>
    <div><div class="copyrow">${copyBtn("Copy caption", "instagram.caption")}${copyBtn("Copy alt texts", "instagram.alt")}${editBtn("instagram")}</div>
      <div class="box"><h4>Slides (${n})</h4>${kk.slides.map((s, i) => `<div style="margin:6px 0;font-size:13px;cursor:pointer" data-act="ig-go" data-arg="${i}"><span class="mono dim">${String(i + 1).padStart(2, "0")}</span> <b>${esc(s.title)}</b> <span class="muted">${esc(s.body || "")}</span></div>`).join("")}
      <div class="row" style="margin-top:8px">${kk.slides.map((_, i) => `<a class="chip" href="${kitUrl(`instagram/slide-${String(i + 1).padStart(2, "0")}.png`)}" download>slide ${i + 1}</a>`).join("")}</div></div>${steps("instagram")}</div></div>`;
}
function previewTikTok(k) {
  const kk = k.kits.tiktok;
  return `<div class="stage2"><div><div class="phone"><div class="screen"><img src="${kitUrl("tiktok/cover.png")}" alt=""></div></div>
      <p class="dim" style="text-align:center;font-size:12px">Cover · ${kk.duration_s}s · fits TikTok, Reels and Shorts</p></div>
    <div><div class="copyrow">${copyBtn("Copy voiceover", "tiktok.voiceover")}${copyBtn("Copy caption", "tiktok.caption")}<a class="btn ghost sm" href="${kitUrl("tiktok/cover.png")}" download>Download cover</a>${editBtn("tiktok")}</div>
      <div class="box"><h4>Hook (first 2 seconds)</h4><b>${esc(kk.hook)}</b></div>
      <div class="scenes" style="margin-top:10px">${kk.scenes.map(s => `<div class="scene"><div class="tm">${s.seconds}s</div><div><div style="font-size:13px">${esc(s.visual)}</div>
        ${s.voiceover ? `<div class="muted" style="font-size:13px;margin-top:4px">🎙 ${esc(s.voiceover)}</div>` : ""}${s.on_screen ? `<span class="os">${esc(s.on_screen)}</span>` : ""}</div></div>`).join("")}</div>${steps("tiktok")}</div></div>`;
}
function previewGitHub(k, d) {
  const g = k.kits.github, sc = k.showcase || {}, repo = d.outputs.A01 || {};
  return `<div class="stage2"><div><div class="gh"><div class="repo">${esc(repo.owner && repo.owner !== "local" ? repo.owner + " / " : "")}<b>${esc(repo.repo || "")}</b></div>
      <p style="margin:10px 0 4px">${esc(g.description)}</p><div>${g.topics.map(t => `<span class="topic">${esc(t)}</span>`).join("")}</div>
      <img src="${kitUrl("github/social-preview.png")}" alt="" style="width:100%;border-radius:8px;margin-top:12px"></div>
      <div class="box" style="margin-top:12px"><h4>README checklist <span class="chip">${sc.readme_score != null ? sc.readme_score + "/100 now" : ""}</span></h4>
        ${g.checklist.map(c => `<div class="check"><b class="st-${c.status} mono" style="font-size:11px;text-transform:uppercase">${esc(c.status)}</b><div><b>${esc(c.item)}</b>${c.fix ? `<div class="muted">${esc(c.fix)}</div>` : ""}</div></div>`).join("")}</div></div>
    <div><div class="copyrow">${copyBtn("Copy description", "github.description")}${copyBtn("Copy topics", "github.topics")}${copyBtn("Copy README draft", "github.readme")}
      ${copyBtn("Copy case study", "github.case_study")}${copyBtn("Copy pitch", "github.pitch")}<a class="btn ghost sm" href="${kitUrl("github/social-preview.png")}" download>Social preview</a></div>
      <div class="box"><h4>Freelance pitch</h4><pre>${esc(g.pitch)}</pre></div>
      <div class="box" style="margin-top:10px"><h4>Portfolio case study</h4><pre>${esc(g.case_study)}</pre></div>
      <div class="box" style="margin-top:10px"><h4>Suggested README</h4><div class="readme">${esc(g.readme)}</div></div>
      ${(sc.notes || []).length ? `<div class="warn" style="margin-top:10px">${sc.notes.map(n => `<div>${esc(n)}</div>`).join("")}</div>` : ""}${steps("github")}</div></div>`;
}
const STEPS = {
  linkedin: ["Start a post, paste the post.", "Add the image, paste the alt text.", "Publish, then comment the first comment (it carries the link).", "Reply to every comment in the first hour."],
  x: ["Post tweet 1 with the card attached.", "Reply with each next tweet, in order.", "Pin it if it is your best work this week."],
  instagram: ["New post: select every slide in order (4:5).", "Paste the caption; add alt text per slide.", "Put the project link in your bio first."],
  tiktok: ["Record the voiceover (~2.5 words per second).", "Capture each scene's visual.", "Edit in CapCut / TikTok, add on-screen text, set the cover.", "Paste the caption. Same video works on Reels and Shorts."],
  github: ["Merge what fits from the README draft.", "About → paste description + topics.", "Settings → Social preview → upload the image.", "Pin the repo; reuse the case study on your portfolio."],
};
function steps(p) { return `<div class="box" style="margin-top:10px"><h4>Post it</h4><ol style="margin:0;padding-left:20px;font-size:13px">${STEPS[p].map(s => `<li>${esc(s)}</li>`).join("")}</ol></div>`; }
function editBtn(p) { return S.d && S.d.summary.gate === "G2" ? `<button class="btn ghost sm" data-act="edit" data-arg="${p}">Edit</button>` : ""; }
function copyKey(key) {
  const k = S.d.kit.kits, [p, f] = key.split(".");
  if (key === "instagram.alt") return k.instagram.alt_texts.join("\n");
  if (key === "github.topics") return k.github.topics.join(" ");
  return k[p][f];
}

/* ---------------- edit modal ---------------- */
function openEdit(p) {
  const d = S.d.kit.drafts[p]; let body = "";
  if (p === "linkedin") body = `<label class="sect">Post</label><textarea id="e1" rows="16">${esc(d.text)}</textarea><label class="sect">First comment</label><textarea id="e2" rows="3">${esc(d.first_comment || "")}</textarea>`;
  if (p === "x") body = `<label class="sect">Tweets (separate with a line containing only ---)</label><textarea id="e1" rows="18">${esc(d.tweets.join("\n---\n"))}</textarea>`;
  if (p === "instagram") body = `<label class="sect">Slides (first line = title, rest = body; separate slides with ---)</label><textarea id="e1" rows="14">${esc(d.slides.map(s => s.title + "\n" + (s.body || "")).join("\n---\n"))}</textarea><label class="sect">Caption</label><textarea id="e2" rows="8">${esc(d.caption)}</textarea>`;
  if (p === "tiktok") body = `<label class="sect">Hook (on screen, first 2 s)</label><input id="e1" value="${esc(d.hook)}"><label class="sect">Voiceover per scene (one block per scene, separated by ---)</label><textarea id="e3" rows="10">${esc(d.scenes.map(s => s.voiceover || "").join("\n---\n"))}</textarea><label class="sect">Caption</label><textarea id="e2" rows="4">${esc(d.caption)}</textarea>`;
  $("#modal").innerHTML = `<div class="panel"><div class="row"><h2>Edit ${esc(PF[p][1])}</h2><span class="grow"></span><button class="link" data-act="close-modal">✕</button></div>
    <p class="muted">Your edit replaces the AI's version. The kit (images, PDF, files) is rebuilt and the platform limits are re-checked.</p>${body}
    <div class="row" style="margin-top:14px"><span class="grow"></span><button class="btn ghost" data-act="close-modal">Cancel</button><button class="btn" data-act="save-edit" data-arg="${p}">Save and rebuild</button></div></div>`;
  $("#modal").hidden = false;
}
function collectEdit(p) {
  const d = JSON.parse(JSON.stringify(S.d.kit.drafts[p])), v = id => ($("#" + id) || {}).value;
  const split = t => t.split(/\n-{3,}\n/).map(x => x.trim()).filter(Boolean);
  if (p === "linkedin") { d.text = v("e1"); d.first_comment = v("e2") || null; }
  if (p === "x") d.tweets = split(v("e1"));
  if (p === "instagram") { d.slides = split(v("e1")).map(b => { const [t, ...r] = b.split("\n"); return {title: t.trim(), body: r.join("\n").trim()}; }); d.caption = v("e2"); }
  if (p === "tiktok") { d.hook = v("e1"); d.caption = v("e2"); const vo = split(v("e3")); d.scenes.forEach((s, i) => { if (vo[i] != null) s.voiceover = vo[i]; }); }
  return d;
}

/* ---------------- inspector ---------------- */
const ev = e => `<span class="chip ev">${esc(e.source_path)}</span>`;
const DETAIL = {
  A01: r => `<div class="tiles"><div class="tile"><div class="n">${esc(r.repo)}</div><div class="l">${esc(r.source_type)}${r.cache_hit ? " · cached" : ""}</div></div><div class="tile"><div class="n">${esc(r.file_count)}</div><div class="l">files</div></div>
      <div class="tile"><div class="n">${esc((r.head_sha || "").slice(0, 10))}</div><div class="l">${esc(r.source_ref_kind)}</div></div><div class="tile"><div class="n">${esc(r.kind_hint)}</div><div class="l">first guess</div></div></div>
    <div class="sect">README (${esc(r.readme_path || "none")})</div><pre class="json" style="white-space:pre-wrap;max-height:260px">${esc(r.readme || "(no README)")}</pre>
    <div class="sect">Files read (${r.key_files.length})</div><div class="row">${r.key_files.map(k => `<span class="chip ev">${esc(k.path)}</span>`).join("")}</div>`,
  A03: a => `<p><b>${esc(a.project_kind)} · ${esc(a.field)}.</b> ${esc(a.summary)}</p><p class="muted">${esc(a.purpose)}</p>` +
    ["highlights", "components", "decisions", "limitations"].map(k => (a[k] || []).length ? `<div class="sect">${k} (${a[k].length})</div><div class="finds">${a[k].map(f => `<div class="find"><b>${esc(f.title)}</b><p>${esc(f.detail)}</p><div class="row">${f.evidence.map(ev).join("")}</div></div>`).join("")}</div>` : "").join("") +
    ((a.dropped || []).length ? `<div class="sect">Dropped by the evidence check (${a.dropped.length})</div>${a.dropped.map(x => `<div class="dim" style="font-size:12.5px">✕ ${esc(x.finding)}: ${esc(x.reason)}</div>`).join("")}` : ""),
  A04: p => renderProfile(p),
  A06: s => `<p><b>Core message.</b> ${esc(s.core_message)}</p><p class="muted">${esc(s.rationale || "")}</p><div class="finds">${Object.entries(s.plans).map(([p, pl]) => `<div class="find">${pf(p)}<p style="margin-top:6px"><span class="chip">${esc(pl.format)}</span> <span class="chip">length ${pl.length}</span></p><b>${esc(pl.hook)}</b><p>${pl.beats.map(esc).join(" → ")}</p><p>${esc(pl.cta)}</p></div>`).join("")}</div>`,
  A09: c => `<div class="row"><b>Verdict</b><span class="chip">${esc(c.verdict)}</span></div><div style="display:grid;gap:8px;margin-top:10px">${c.flags.map(f => `<div class="find"><div class="row">${pf(f.platform, false)}<span class="chip">${esc(f.severity)}</span><span class="chip">${esc(f.source)}</span></div><p style="margin-top:6px"><span class="mono">“${esc(f.quote)}”</span></p><p>${esc(f.issue)} → ${esc(f.suggestion)}</p></div>`).join("") || '<div class="dim">clean</div>'}</div>`,
};
function renderInspect(d) {
  const tags = ["A01", "A02", "A03", "A04", "A05", "G1", "A06", "A07", "A08", "A09", "A10", "A11", "A12", "A13"];
  const avail = tags.filter(t => d.outputs[t]); if (!avail.length) return "";
  if (!S.sel || !d.outputs[S.sel]) return `<div class="card inspect"><div class="row"><h3>Under the hood</h3><span class="muted">Click any stage above to see exactly what it produced.</span></div></div>`;
  const sel = S.sel;
  let body = ""; try { body = DETAIL[sel] ? DETAIL[sel](d.outputs[sel]) : ""; } catch (e) { body = ""; }
  if (!body) body = `<pre class="json">${esc(JSON.stringify(d.outputs[sel], null, 2))}</pre>`;
  const st = d.stages.find(s => s.tag === sel) || {};
  return `<div class="card inspect" id="inspect"><div class="itabs">${tags.map(t => `<button class="itab ${t === sel ? "on" : ""}" ${d.outputs[t] ? "" : "disabled"} data-act="sel" data-arg="${t}">${t}</button>`).join("")}<span class="grow"></span><button class="itab" data-act="raw">raw JSON</button></div>
    <div class="row" style="margin-bottom:12px"><h3>${esc(sel)} · ${esc(st.title || "")}</h3></div><div id="detailBody">${body}</div></div>`;
}

/* ---------------- engines drawer ---------------- */
function renderEngines() {
  const e = S.engines; if (!e) return "";
  const local = e.engines.filter(x => ["claude_cli", "claude"].includes(x.name));
  const apis = e.engines.filter(x => !["claude_cli", "claude", "mock"].includes(x.name));
  const card = x => {
    const models = S.models[x.name] || [];
    const sel = (tier) => models.length ? `<select data-model="${x.name}:${tier}">${[x.models[tier], ...models.filter(m => m !== x.models[tier])].filter(Boolean).map(m => `<option ${m === x.models[tier] ? "selected" : ""}>${esc(m)}</option>`).join("")}</select>`
      : `<input data-model="${x.name}:${tier}" value="${esc(x.models[tier] || "")}" placeholder="model name">`;
    return `<div class="eng ${x.active ? "active" : ""}"><div class="hd"><span class="led ${x.ready ? "ok" : ""}"></span><b>${esc(x.label)}</b>${x.active ? '<span class="chip">active</span>' : ""}</div>
      <div class="k">${esc(x.blurb || x.why)}${x.key ? ` · key ${esc(x.key)}` : ""}</div>
      ${x.needs_key ? `<input type="password" data-key="${x.name}" placeholder="${x.key ? "replace key" : "paste key"}" autocomplete="off">` : ""}
      ${x.name === "custom" ? `<input data-base="custom" value="${esc(x.base_url)}" placeholder="https://api.example.com/v1">` : ""}
      ${x.kind !== "manual" ? `<div class="row" style="gap:6px"><span class="dim" style="font-size:11px;width:40px">heavy</span><div class="grow">${sel("heavy")}</div></div><div class="row" style="gap:6px"><span class="dim" style="font-size:11px;width:40px">mid</span><div class="grow">${sel("mid")}</div></div>` : ""}
      <div class="row" style="gap:6px"><button class="btn sm" data-act="eng-use" data-arg="${x.name}">${x.active ? "Save" : "Use this"}</button>
        ${x.kind !== "manual" ? `<button class="btn ghost sm" data-act="eng-test" data-arg="${x.name}">Test</button>` : ""}
        ${x.key ? `<button class="btn ghost sm" data-act="eng-forget" data-arg="${x.name}">Forget key</button>` : ""}
        ${x.docs ? `<a class="link" style="font-size:12.5px" href="${esc(x.docs)}" target="_blank" rel="noopener">${x.needs_key ? "Get a key ↗" : "Docs ↗"}</a>` : ""}</div></div>`;
  };
  return `<div class="panel"><div class="row"><h2>AI engine</h2><span class="grow"></span><button class="link" data-act="close-drawer">✕ Close</button></div>
    ${e.locked ? `<div class="warn" style="margin-top:10px">FACETCAST_ENGINE is set in your environment, so it wins over this panel.</div>` : ""}
    <div class="keydrop" id="keydrop"><b>Paste any API key and you're done.</b><div class="muted" style="font-size:13px;margin:4px 0 10px">Anthropic, OpenAI, OpenRouter, Groq or Gemini. Facetcast detects the provider, tests the key and switches to it. You can also drop a .env or text file here. Keys stay on this computer, in <span class="mono">.env</span>.</div>
      <textarea id="anykey" placeholder="sk-ant-…   sk-…   sk-or-…   gsk_…   AIza…"></textarea>
      <div class="row" style="margin-top:8px"><button class="btn" data-act="key-go">Connect</button>${S.saved ? `<span class="${S.saved.test && S.saved.test.ok ? "" : "muted"}">${esc(S.saved.engine)} · ${esc(S.saved.masked)} · ${esc(S.saved.test ? S.saved.test.message : "")}</span>` : ""}</div></div>
    <div class="sect">No key needed</div><div class="engs">${local.map(card).join("")}</div>
    <div class="sect">API engines</div><div class="engs">${apis.map(card).join("")}</div>
    <p class="dim" style="font-size:12px;margin-top:14px">"heavy" models do the analysis, angles, writing and revisions; "mid" models do the voice profile, planning, visuals and critique. Press Test to load the models your key can use.</p></div>`;
}
function wireEngines() {
  const kd = $("#keydrop"); if (!kd || kd._w) return; kd._w = true;
  ["dragenter", "dragover"].forEach(e => kd.addEventListener(e, ev => { ev.preventDefault(); kd.classList.add("over"); }));
  ["dragleave", "drop"].forEach(e => kd.addEventListener(e, ev => { ev.preventDefault(); kd.classList.remove("over"); }));
  kd.addEventListener("drop", async ev => {
    const f = ev.dataTransfer.files[0];
    const text = f ? (f.size < 200000 ? await f.text() : "") : ev.dataTransfer.getData("text");
    if (text) { $("#anykey").value = text; act("key-go"); }
  });
  $("#anykey").addEventListener("paste", () => setTimeout(() => act("key-go"), 50));
}

/* ---------------- memory ---------------- */
function renderMemory() {
  const m = S.memory || {posts: [], queued: [], counts: {}};
  return `<div class="card"><div class="row"><h2>Memory</h2><span class="grow"></span><span class="chip">${m.counts.posts || 0} posts</span><span class="chip">${m.counts.queued || 0} queued angles</span><span class="chip">${m.counts.projects || 0} projects</span></div>
    <p class="muted">Every approved kit is stored here so new runs never repeat an idea. Unused angles wait for your next run of the same project.</p>
    <div class="sect">Posts</div><div style="display:grid;gap:8px">${m.posts.map(p => `<div class="find"><div class="row">${pf(p.platform)}<span class="chip">${esc(p.project_id)}</span><span class="chip">${p.chars} chars</span><span class="chip">${p.embedded ? "deduped" : "no embedding"}</span></div><p style="margin-top:8px">${esc(p.preview)}…</p></div>`).join("") || '<div class="empty">Nothing yet. Approve a kit and it shows up here.</div>'}</div>
    <div class="sect">Queued angles</div>${m.queued.map(a => `<div style="font-size:13px;margin-bottom:4px"><span class="mono dim">${pct(a.score)}%</span> ${esc(a.title)} <span class="dim">· ${esc(a.project_id)}</span></div>`).join("") || '<div class="empty">none</div>'}</div>`;
}

/* ---------------- render ---------------- */
function renderRun() {
  const d = S.d;
  if (!d) return `<div class="empty"><span class="spin"></span> loading…</div>`;
  if (d.starting) return `<div class="card action"><div class="row"><span class="spin"></span><h3>Reading the project…</h3></div></div>`;
  const s = d.summary, k = d.busy ? "running" : s.gate ? "gate" : s.status;
  const label = d.busy ? "agents working" : s.gate ? "your turn · " + s.gate : s.status === "waiting" ? "needs an answer" : s.status;
  return `<div class="runhead"><div class="grow"><h1>${esc(d.project || s.run_id)}</h1><div class="src">${esc(d.source)}</div></div>
      ${(s.platforms || []).map(p => pf(p, false)).join("")}<span class="pill ${k}">${esc(label)}</span></div>
    <div class="grid2">${renderPipe(d)}${renderFeed(d)}</div>${renderAction(d)}${renderInspect(d)}`;
}
function render() {
  renderTop();
  const ae = document.activeElement;
  const typing = ae && (ae.tagName === "TEXTAREA" || (ae.tagName === "INPUT" && ae.type !== "file")) ;
  if (S.drawer) { if (!(typing && $("#drawer").contains(ae))) { $("#drawer").innerHTML = renderEngines(); wireEngines(); } $("#drawer").hidden = false; }
  else $("#drawer").hidden = true;
  if (typing && $("#view").contains(ae)) return;
  const stream = $("#stream"), atBottom = !stream || stream.scrollTop + stream.clientHeight >= stream.scrollHeight - 30;
  const logEl = $("#log"), logBottom = !logEl || logEl.scrollTop + logEl.clientHeight >= logEl.scrollHeight - 20;
  const resp = $("#resp") && $("#resp").value, y = window.scrollY;
  $("#view").innerHTML = S.view === "memory" ? renderMemory() : S.cur ? renderRun() : renderNew();
  window.scrollTo(0, y);
  if (resp && $("#resp")) $("#resp").value = resp;
  if (atBottom && $("#stream")) $("#stream").scrollTop = 1e9;
  if (logBottom && $("#log")) $("#log").scrollTop = 1e9;
  wireNew();
}

/* ---------------- actions ---------------- */
async function runAct(a, body) { try { await post(`/api/runs/${encodeURIComponent(S.cur)}/${a}`, body); refresh(); } catch (e) { toast(e.message); } }
async function act(a, arg, el) {
  switch (a) {
    case "home": return go(null);
    case "memory": S.view = "memory"; S.cur = null; S.memory = await api("/api/memory").catch(() => null); history.replaceState(null, "", "#"); return render();
    case "engines": S.drawer = true; return render();
    case "close-drawer": S.drawer = false; return render();
    case "close-modal": $("#modal").hidden = true; return;
    case "theme-toggle": { const l = document.documentElement.dataset.theme !== "light"; document.documentElement.dataset.theme = l ? "light" : "dark"; try { localStorage.setItem("fc-theme", l ? "light" : "dark"); } catch (e) {} return; }
    case "pick-file": if (el && el.tagName === "A") { } $("#fileIn").click(); return;
    case "pick-folder": $("#folderIn").click(); return;
    case "start-url": { const s = $("#src").value.trim(); if (!s) return toast("Paste a GitHub link, a zip link or a folder path first."); try { const r = await post("/api/runs", {source: s}); go(r.run_id); } catch (e) { toast(e.message); } return; }
    case "demo": try { const r = await post("/api/demo"); go(r.run_id); } catch (e) { toast(e.message); } return;
    case "sel": S.sel = S.sel === arg ? null : arg; render(); setTimeout(() => $("#inspect") && $("#inspect").scrollIntoView({behavior: "smooth", block: "start"}), 30); return;
    case "raw": $("#detailBody").innerHTML = `<pre class="json">${esc(JSON.stringify(S.d.outputs[S.sel], null, 2))}</pre>`; return;
    case "resume": return runAct("resume");
    case "auto-resume": try { await post("/api/engines/use", {engine: arg}); } catch (e) { return toast(e.message); } return runAct("resume");
    case "copy-prompt": try { const p = await api(`/api/runs/${encodeURIComponent(S.cur)}/prompt`); copy(p.text, `Prompt (${p.text.length.toLocaleString()} chars)`); } catch (e) { toast(e.message); } return;
    case "view-prompt": if (S.prompt) S.prompt = null; else { try { S.prompt = (await api(`/api/runs/${encodeURIComponent(S.cur)}/prompt`)).text; } catch (e) { toast(e.message); } } return render();
    case "send-resp": { const t = $("#resp").value.trim(); if (!t) return toast("Paste the JSON answer first."); try { await post(`/api/runs/${encodeURIComponent(S.cur)}/response`, {text: t}); $("#resp").value = ""; S.prompt = null; toast("Answer saved, continuing…", true); refresh(); } catch (e) { toast(e.message); } return; }
    case "g1-angle": { S.g1n = +arg; const a = S.d.summary.angles.find(x => x.n === +arg); S.g1p = new Set(a.default_platforms); return render(); }
    case "g1-plat": S.g1p.has(arg) ? S.g1p.delete(arg) : S.g1p.add(arg); return render();
    case "g1-go": return runAct("pick", {n: S.g1n, platforms: [...S.g1p]});
    case "tab": S.tab = arg; S.ig = 0; return render();
    case "fold": S.fold[arg] = true; return render();
    case "ig": S.ig += +arg; return render();
    case "ig-go": S.ig = +arg; return render();
    case "copy": return copy(copyKey(arg), arg.split(".")[1].replace("_", " "));
    case "copy-tweet": return copy(S.d.kit.kits.x.tweets[+arg], `Tweet ${+arg + 1}`);
    case "theme": S.ver = Date.now(); toast(`Redrawing every graphic in “${arg}”…`, true); await runAct("theme", {theme: arg}); setTimeout(() => { S.ver = Date.now(); refresh(); }, 2500); return;
    case "open-folder": try { await post(`/api/runs/${encodeURIComponent(S.cur)}/open`); toast("Opened the kit folder.", true); } catch (e) { toast(e.message); } return;
    case "approve": return runAct("approve");
    case "reject": { const r = window.prompt("Why reject it? (one line, optional)", ""); if (r !== null) runAct("reject", {reason: r}); return; }
    case "edit": return openEdit(arg);
    case "save-edit": { const data = collectEdit(arg); $("#modal").hidden = true; toast("Saving your edit and rebuilding the kit…", true); S.ver = Date.now(); return runAct("edit", {platform: arg, data}); }
    case "key-go": { const t = ($("#anykey") || {}).value || ""; if (!t.trim()) return toast("Paste a key first."); try { const r = await post("/api/engines/key", {key: t}); S.engines = r; S.saved = r.saved; $("#anykey").value = ""; toast(r.saved.test && r.saved.test.ok ? `Connected to ${r.saved.engine}. ${r.saved.test.message}` : `Saved, but the test failed: ${r.saved.test.message}`, r.saved.test && r.saved.test.ok); if (r.saved.test && r.saved.test.models) S.models[r.saved.engine] = r.saved.test.models; render(); } catch (e) { toast(e.message); } return; }
    case "eng-test": { const keyIn = document.querySelector(`[data-key="${arg}"]`); try { if (keyIn && keyIn.value.trim()) { await post("/api/engines/key", {key: keyIn.value.trim(), engine: arg, activate: false}); keyIn.value = ""; } const r = await post("/api/engines/test", {engine: arg}); S.engines = r; S.models[arg] = r.test.models || []; toast(r.test.message, r.test.ok); render(); } catch (e) { toast(e.message); } return; }
    case "eng-use": {
      const keyIn = document.querySelector(`[data-key="${arg}"]`), base = document.querySelector(`[data-base="${arg}"]`);
      const h = document.querySelector(`[data-model="${arg}:heavy"]`), m = document.querySelector(`[data-model="${arg}:mid"]`);
      try {
        if (keyIn && keyIn.value.trim()) await post("/api/engines/key", {key: keyIn.value.trim(), engine: arg, activate: false});
        S.engines = await post("/api/engines/use", {engine: arg, heavy: h ? h.value : null, mid: m ? m.value : null, base_url: base ? base.value : null});
        toast(`Engine: ${arg}`, true); render();
      } catch (e) { toast(e.message); } return;
    }
    case "eng-forget": try { S.engines = await post("/api/engines/forget", {engine: arg}); render(); } catch (e) { toast(e.message); } return;
  }
}
document.addEventListener("click", e => {
  const el = e.target.closest("[data-act]"); if (!el) return;
  if (el.tagName === "A" && el.getAttribute("href") === "#") e.preventDefault();
  if (el.id === "drop" && e.target.closest("a")) return;
  e.stopPropagation();
  act(el.dataset.act, el.dataset.arg, el);
});
document.addEventListener("keydown", e => { if (e.key === "Escape") { $("#modal").hidden = true; if (S.drawer) { S.drawer = false; render(); } } });
$("#drawer").addEventListener("click", e => { if (e.target.id === "drawer") { S.drawer = false; render(); } });
$("#runSel").addEventListener("change", e => go(e.target.value || null));
window.addEventListener("hashchange", () => { const h = decodeURIComponent(location.hash.slice(1)) || null; if (h !== S.cur) go(h); });
try { const t = localStorage.getItem("fc-theme"); if (t) document.documentElement.dataset.theme = t; } catch (e) {}
S.cur = decodeURIComponent(location.hash.slice(1)) || null; S.view = S.cur ? "run" : "new";
api("/api/meta").then(m => { S.meta = m; render(); }).catch(() => {});
render(); refresh();
