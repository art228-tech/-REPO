import { spawn } from "node:child_process";
import express from "express";
import fs from "node:fs/promises";
import http from "node:http";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { WebSocketServer } from "ws";
import { ConfigStore } from "../config/store.js";
import { defaultConfig, validateConfig } from "../config/schema.js";
import { Orchestrator } from "../core/orchestrator.js";
import { Logger } from "../logging/logger.js";
import { isDirectory } from "../util/fsUtils.js";
import { preferIPv4 } from "../util/net.js";
import { baseDir, isPackaged, loadDotEnv, resolvePaths } from "./env.js";

preferIPv4();

/** Корень проекта, устойчиво к запуску из ESM (tsx) и из CJS-бандла (pkg). */
function computeProjectRoot(): string {
  try {
    const modulePath = fileURLToPath(import.meta.url);
    return path.resolve(path.dirname(modulePath), "..", "..");
  } catch {
    return process.cwd();
  }
}

const projectRoot = computeProjectRoot();
loadDotEnv(baseDir(projectRoot));
const paths = resolvePaths(projectRoot);

const logger = new Logger({ logDir: paths.logDir, minLevel: "debug", console: true });
const configStore = new ConfigStore(paths.dataDir);
const orchestrator = new Orchestrator(logger);

const app = express();
app.use(express.json({ limit: "2mb" }));
app.use(express.static(paths.publicDir));

// ---- Config ----
app.get("/api/config", async (_req, res) => {
  const config = await configStore.load();
  res.json({ config, defaults: defaultConfig });
});

app.post("/api/config", async (req, res) => {
  const result = validateConfig(req.body);
  if (!result.ok) {
    return res.status(400).json({ ok: false, errors: result.errors });
  }
  await configStore.save(result.config!);
  res.json({ ok: true });
});

// ---- Run control ----
app.post("/api/run", async (req, res) => {
  if (orchestrator.isRunning()) {
    return res.status(409).json({ ok: false, error: "Сценарий уже выполняется" });
  }
  const input = req.body && Object.keys(req.body).length > 0 ? req.body : await configStore.load();
  const result = validateConfig(input);
  if (!result.ok) {
    return res.status(400).json({ ok: false, errors: result.errors });
  }
  await configStore.save(result.config!);
  // Запускаем в фоне; статус приходит по WebSocket.
  orchestrator.run(result.config!).catch((e) => logger.error("server", "Ошибка run()", { error: String(e) }));
  res.json({ ok: true, status: orchestrator.getStatus() });
});

app.post("/api/stop", (_req, res) => {
  orchestrator.requestStop();
  res.json({ ok: true, status: orchestrator.getStatus() });
});

app.get("/api/status", (_req, res) => {
  res.json({ status: orchestrator.getStatus() });
});

// ---- Logs ----
app.get("/api/logs/recent", (req, res) => {
  const limit = Number(req.query.limit ?? 500);
  res.json({ entries: logger.recent(Number.isFinite(limit) ? limit : 500) });
});

app.get("/api/logs/download", (_req, res) => {
  const stamp = new Date().toISOString().replace(/[:.]/g, "-");
  res.setHeader("Content-Type", "text/plain; charset=utf-8");
  res.setHeader("Content-Disposition", `attachment; filename="elevenlabs-auto-logs-${stamp}.log"`);
  res.send(logger.dumpText());
});

// ---- Filesystem helpers (folder picker) ----
app.get("/api/fs/list", async (req, res) => {
  const dir = typeof req.query.dir === "string" && req.query.dir ? req.query.dir : os.homedir();
  try {
    const abs = path.resolve(dir);
    const entries = await fs.readdir(abs, { withFileTypes: true });
    const dirs = entries
      .filter((e) => e.isDirectory() && !e.name.startsWith("."))
      .map((e) => ({ name: e.name, path: path.join(abs, e.name) }))
      .sort((a, b) => a.name.localeCompare(b.name));
    res.json({ path: abs, parent: path.dirname(abs), home: os.homedir(), dirs });
  } catch (error) {
    res.status(400).json({ error: String(error) });
  }
});

app.post("/api/fs/validate", async (req, res) => {
  const dirs: Record<string, string> = req.body?.dirs ?? {};
  const results: Record<string, boolean> = {};
  for (const [key, value] of Object.entries(dirs)) {
    results[key] = typeof value === "string" && value.length > 0 && (await isDirectory(value));
  }
  res.json({ results });
});

// ---- HTTP + WebSocket ----
const server = http.createServer(app);
const wss = new WebSocketServer({ server, path: "/ws" });

function broadcast(type: string, payload: unknown): void {
  const data = JSON.stringify({ type, payload });
  for (const client of wss.clients) {
    if (client.readyState === client.OPEN) client.send(data);
  }
}

logger.on("entry", (entry) => broadcast("log", entry));
orchestrator.on("status", (status) => broadcast("status", status));

wss.on("connection", (socket) => {
  socket.send(JSON.stringify({ type: "init", payload: { logs: logger.recent(300), status: orchestrator.getStatus() } }));
});

const port = Number(process.env.PORT ?? 4599);
server.listen(port, () => {
  const url = `http://localhost:${port}`;
  logger.info("server", `UI доступен на ${url}`);
  logger.info("server", `Данные и логи: ${paths.dataDir}`);
  // В собранном бинарнике автоматически открываем панель в браузере.
  if (isPackaged() && process.env.NO_OPEN !== "1") {
    openBrowser(url);
  }
});

/** Открывает URL в браузере по умолчанию (кроссплатформенно). */
function openBrowser(url: string): void {
  try {
    const cmd =
      process.platform === "win32" ? "cmd" : process.platform === "darwin" ? "open" : "xdg-open";
    const args = process.platform === "win32" ? ["/c", "start", "", url] : [url];
    spawn(cmd, args, { detached: true, stdio: "ignore" }).unref();
  } catch {
    // не критично — пользователь откроет ссылку вручную
  }
}
