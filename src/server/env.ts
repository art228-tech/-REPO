import fs from "node:fs";
import os from "node:os";
import path from "node:path";

const APP_DIR_NAME = "elevenlabs-auto-voiceover";

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

/**
 * Постоянная пользовательская директория для настроек/логов (не зависит от
 * того, где лежит .exe и какая версия):
 *  - Windows: %APPDATA%\elevenlabs-auto-voiceover
 *  - macOS:   ~/Library/Application Support/elevenlabs-auto-voiceover
 *  - Linux:   $XDG_CONFIG_HOME|~/.config/elevenlabs-auto-voiceover
 */
export function userDataDir(): string {
  const home = os.homedir();
  if (process.platform === "win32") {
    const appData = process.env.APPDATA || path.join(home, "AppData", "Roaming");
    return path.join(appData, APP_DIR_NAME);
  }
  if (process.platform === "darwin") {
    return path.join(home, "Library", "Application Support", APP_DIR_NAME);
  }
  const xdg = process.env.XDG_CONFIG_HOME || path.join(home, ".config");
  return path.join(xdg, APP_DIR_NAME);
}

export interface AppPaths {
  root: string;
  publicDir: string;
  dataDir: string;
  logDir: string;
  /** Устаревшее расположение данных рядом с .exe (для миграции). */
  legacyDataDir: string;
}

export function resolvePaths(projectRoot: string): AppPaths {
  const root = baseDir(projectRoot);
  const publicDir = path.join(root, "public");
  const legacyDataDir = path.join(root, "data");

  let dataDir: string;
  if (process.env.DATA_DIR) {
    dataDir = path.resolve(root, process.env.DATA_DIR);
  } else if (isPackaged()) {
    // В бинарнике — стабильная пользовательская папка, чтобы настройки
    // сохранялись между обновлениями и не зависели от папки с .exe.
    dataDir = userDataDir();
  } else {
    dataDir = legacyDataDir;
  }

  const logDir = path.join(dataDir, "logs");
  fs.mkdirSync(logDir, { recursive: true });

  // Миграция настроек из старого места (рядом с .exe), если они там есть,
  // а в новом ещё нет.
  try {
    const newCfg = path.join(dataDir, "config.json");
    const oldCfg = path.join(legacyDataDir, "config.json");
    if (dataDir !== legacyDataDir && !fs.existsSync(newCfg) && fs.existsSync(oldCfg)) {
      fs.copyFileSync(oldCfg, newCfg);
    }
  } catch {
    // не критично
  }

  return { root, publicDir, dataDir, logDir, legacyDataDir };
}
