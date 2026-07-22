import fs from "node:fs";
import path from "node:path";

/** Читает .env (простой парсер) в process.env, не перезаписывая заданные значения. */
export function loadDotEnv(root: string): void {
  const file = path.join(root, ".env");
  if (!fs.existsSync(file)) return;
  const content = fs.readFileSync(file, "utf8");
  for (const line of content.split(/\r?\n/)) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith("#")) continue;
    const eq = trimmed.indexOf("=");
    if (eq === -1) continue;
    const key = trimmed.slice(0, eq).trim();
    let value = trimmed.slice(eq + 1).trim();
    if ((value.startsWith('"') && value.endsWith('"')) || (value.startsWith("'") && value.endsWith("'"))) {
      value = value.slice(1, -1);
    }
    if (!(key in process.env)) process.env[key] = value;
  }
}

/** true, если приложение запущено как собранный бинарник (pkg). */
export function isPackaged(): boolean {
  return Boolean((process as unknown as { pkg?: unknown }).pkg);
}

/**
 * Базовая директория приложения.
 * - В обычном режиме (Node): корень проекта.
 * - В собранном бинарнике: папка рядом с исполняемым файлом (туда пишутся
 *   data/логи и оттуда читается public).
 */
export function baseDir(projectRoot: string): string {
  return isPackaged() ? path.dirname(process.execPath) : projectRoot;
}

export interface AppPaths {
  root: string;
  publicDir: string;
  dataDir: string;
  logDir: string;
}

export function resolvePaths(projectRoot: string): AppPaths {
  const root = baseDir(projectRoot);
  const publicDir = path.join(root, "public");
  const dataDir = process.env.DATA_DIR
    ? path.resolve(root, process.env.DATA_DIR)
    : path.join(root, "data");
  const logDir = path.join(dataDir, "logs");
  fs.mkdirSync(logDir, { recursive: true });
  return { root, publicDir, dataDir, logDir };
}
