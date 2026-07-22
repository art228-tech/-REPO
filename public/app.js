const LEVEL_ORDER = { debug: 10, info: 20, success: 25, warn: 30, error: 40 };
let logEntries = [];
let logFilter = "info";
let picker = { target: null, current: "" };

/* ---------- helpers ---------- */
function $(sel) { return document.querySelector(sel); }
function $all(sel) { return Array.from(document.querySelectorAll(sel)); }

function fieldElements() {
  return $all(".config [id]").filter((el) =>
    ["INPUT", "SELECT", "TEXTAREA"].includes(el.tagName),
  );
}

function setNested(obj, pathStr, value) {
  const parts = pathStr.split(".");
  let cur = obj;
  for (let i = 0; i < parts.length - 1; i++) {
    cur[parts[i]] = cur[parts[i]] || {};
    cur = cur[parts[i]];
  }
  cur[parts[parts.length - 1]] = value;
}

function getNested(obj, pathStr) {
  return pathStr.split(".").reduce((acc, k) => (acc == null ? undefined : acc[k]), obj);
}

function collectConfig() {
  const cfg = {};
  for (const el of fieldElements()) {
    let value;
    if (el.type === "checkbox") value = el.checked;
    else value = el.value;
    setNested(cfg, el.id, value);
  }
  return cfg;
}

function applyConfig(cfg) {
  for (const el of fieldElements()) {
    const value = getNested(cfg, el.id);
    if (value === undefined || value === null) continue;
    if (el.type === "checkbox") el.checked = Boolean(value);
    else el.value = value;
  }
  $all("[data-out]").forEach((out) => {
    const src = $("#" + out.getAttribute("data-out"));
    if (src) out.textContent = src.value;
  });
}

function toast(msg, kind = "") {
  const t = $("#toast");
  t.textContent = msg;
  t.className = "toast " + kind;
  setTimeout(() => (t.className = "toast hidden"), 3200);
}

/* ---------- config load/save ---------- */
async function loadConfig() {
  const res = await fetch("/api/config");
  const data = await res.json();
  applyConfig({ ...data.defaults, ...data.config });
}

async function saveConfig() {
  const res = await fetch("/api/config", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(collectConfig()),
  });
  const data = await res.json();
  if (data.ok) toast("Конфигурация сохранена", "ok");
  else showErrors(data.errors);
  return data.ok;
}

function showErrors(errors) {
  const text = (errors || []).map((e) => `${e.path}: ${e.message}`).join("\n");
  toast("Ошибки: " + (text || "неизвестно"), "err");
}

/* ---------- run control ---------- */
async function startRun() {
  const res = await fetch("/api/run", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(collectConfig()),
  });
  const data = await res.json();
  if (!data.ok) {
    if (data.errors) showErrors(data.errors);
    else toast(data.error || "Не удалось запустить", "err");
  } else {
    toast("Сценарий запущен", "ok");
  }
}

async function stopRun() {
  await fetch("/api/stop", { method: "POST" });
  toast("Запрошена остановка");
}

/* ---------- status ---------- */
function renderStatus(s) {
  $("#st-state").textContent = s.state;
  $("#st-state").className = "v badge " + s.state;
  $("#st-step").textContent = s.step || "—";
  $("#st-profile").textContent = s.profileId || "—";
  $("#st-voices").textContent = `${s.voicesCreated}/${s.voicesTarget}`;
  $("#st-files").textContent = s.filesDone;
  $("#st-failed").textContent = s.filesFailed;
  $("#st-texts").textContent = s.textsRemaining;
  $("#st-credits").textContent = s.creditsRemaining == null ? "—" : s.creditsRemaining;
  $("#st-error").textContent = s.error || "";

  const running = s.state === "running" || s.state === "stopping";
  $("#btn-start").disabled = running;
  $("#btn-stop").disabled = !running;
}

/* ---------- logs ---------- */
function renderLog() {
  const min = LEVEL_ORDER[logFilter];
  const box = $("#log");
  const atBottom = box.scrollHeight - box.scrollTop - box.clientHeight < 40;
  box.innerHTML = logEntries
    .filter((e) => LEVEL_ORDER[e.level] >= min)
    .slice(-1500)
    .map(logLine)
    .join("");
  if (atBottom) box.scrollTop = box.scrollHeight;
}

function logLine(e) {
  const time = new Date(e.ts).toLocaleTimeString();
  const meta = e.meta && Object.keys(e.meta).length ? " " + escapeHtml(JSON.stringify(e.meta)) : "";
  return `<div class="line log-${e.level}"><span class="t">${time}</span> <span class="s">(${escapeHtml(e.scope)})</span> ${escapeHtml(e.message)}${meta}</div>`;
}

function escapeHtml(str) {
  return String(str).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
}

function pushLog(entry) {
  logEntries.push(entry);
  if (logEntries.length > 5000) logEntries = logEntries.slice(-5000);
  renderLog();
}

/* ---------- websocket ---------- */
function connectWs() {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(`${proto}://${location.host}/ws`);
  ws.onmessage = (msg) => {
    const { type, payload } = JSON.parse(msg.data);
    if (type === "init") {
      logEntries = payload.logs || [];
      renderLog();
      renderStatus(payload.status);
    } else if (type === "log") {
      pushLog(payload);
    } else if (type === "status") {
      renderStatus(payload);
    }
  };
  ws.onclose = () => setTimeout(connectWs, 2000);
}

/* ---------- folder picker ---------- */
async function openPicker(target) {
  picker.target = target;
  const start = $("#" + target).value || "";
  await loadPickerDir(start);
  $("#picker").classList.remove("hidden");
}

async function loadPickerDir(dir) {
  const res = await fetch("/api/fs/list?dir=" + encodeURIComponent(dir || ""));
  const data = await res.json();
  if (data.error) { toast(data.error, "err"); return; }
  picker.current = data.path;
  picker.parent = data.parent;
  picker.home = data.home;
  $("#picker-current").textContent = data.path;
  $("#picker-list").innerHTML = data.dirs
    .map((d) => `<div class="picker-item" data-path="${escapeHtml(d.path)}">📁 ${escapeHtml(d.name)}</div>`)
    .join("") || '<div class="picker-item">— нет вложенных папок —</div>';
  $all("#picker-list .picker-item[data-path]").forEach((item) => {
    item.onclick = () => loadPickerDir(item.getAttribute("data-path"));
  });
}

/* ---------- wire up ---------- */
document.addEventListener("DOMContentLoaded", () => {
  loadConfig();
  connectWs();

  $("#btn-save").onclick = saveConfig;
  $("#btn-start").onclick = startRun;
  $("#btn-stop").onclick = stopRun;
  $("#btn-download-logs").onclick = () => (window.location.href = "/api/logs/download");
  $("#btn-clear-logs").onclick = () => { logEntries = []; renderLog(); };

  $("#log-filter").onchange = (e) => { logFilter = e.target.value; renderLog(); };

  $all("[data-out]").forEach((out) => {
    const src = $("#" + out.getAttribute("data-out"));
    if (src) src.addEventListener("input", () => (out.textContent = src.value));
  });

  $all(".pick").forEach((btn) => (btn.onclick = () => openPicker(btn.getAttribute("data-target"))));
  $("#picker-close").onclick = () => $("#picker").classList.add("hidden");
  $("#picker-up").onclick = () => loadPickerDir(picker.parent);
  $("#picker-home").onclick = () => loadPickerDir(picker.home);
  $("#picker-select").onclick = () => {
    $("#" + picker.target).value = picker.current;
    $("#picker").classList.add("hidden");
    toast("Папка выбрана");
  };
});
