import fs from "node:fs/promises";
import path from "node:path";

/** Создаёт директорию (рекурсивно), если её ещё нет. */
export async function ensureDir(dir: string): Promise<void> {
  await fs.mkdir(dir, { recursive: true });
}

/** Проверяет существование пути. */
export async function pathExists(p: string): Promise<boolean> {
  try {
    await fs.access(p);
    return true;
  } catch {
    return false;
  }
}

/** Проверяет, что путь существует и является директорией. */
export async function isDirectory(p: string): Promise<boolean> {
  try {
    const stat = await fs.stat(p);
    return stat.isDirectory();
  } catch {
    return false;
  }
}

/**
 * Возвращает отсортированный список файлов в директории (без вложенных папок),
 * опционально фильтруя по расширениям (в нижнем регистре, с точкой, напр. ['.txt']).
 */
export async function listFiles(dir: string, extensions?: string[]): Promise<string[]> {
  const entries = await fs.readdir(dir, { withFileTypes: true });
  const files = entries
    .filter((e) => e.isFile())
    .map((e) => e.name)
    .filter((name) => {
      if (!extensions || extensions.length === 0) return true;
      const ext = path.extname(name).toLowerCase();
      return extensions.includes(ext);
    })
    .sort((a, b) => a.localeCompare(b, undefined, { numeric: true, sensitivity: "base" }));
  return files.map((name) => path.join(dir, name));
}

/** Делает имя файла безопасным для файловой системы. */
export function sanitizeFilename(name: string): string {
  return name
    .replace(/[<>:"/\\|?*\u0000-\u001f]/g, "_")
    .replace(/\s+/g, " ")
    .trim()
    .slice(0, 180) || "untitled";
}

/** Возвращает уникальный путь в директории, добавляя суффикс при коллизии. */
export async function uniquePath(dir: string, baseName: string, ext: string): Promise<string> {
  let candidate = path.join(dir, `${baseName}${ext}`);
  let counter = 1;
  while (await pathExists(candidate)) {
    candidate = path.join(dir, `${baseName} (${counter})${ext}`);
    counter += 1;
  }
  return candidate;
}
