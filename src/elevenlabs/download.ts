import fs from "node:fs/promises";
import path from "node:path";
import type { Page } from "puppeteer-core";
import { ensureDir, listFiles } from "../util/fsUtils.js";
import { sleep } from "../util/sleep.js";

/** Включает скачивание файлов браузером в указанную директорию через CDP. */
export async function enableDownloads(page: Page, downloadDir: string): Promise<void> {
  await ensureDir(downloadDir);
  const client = await page.target().createCDPSession();
  await client.send("Browser.setDownloadBehavior", {
    behavior: "allow",
    downloadPath: downloadDir,
    eventsEnabled: true,
  } as any).catch(async () => {
    // Fallback на устаревший Page.setDownloadBehavior
    await client.send("Page.setDownloadBehavior", {
      behavior: "allow",
      downloadPath: downloadDir,
    } as any);
  });
}

/**
 * Ждёт появления нового полностью скачанного файла в директории (по сравнению
 * со снимком `before`) и возвращает его путь. Учитывает временные файлы
 * .crdownload/.tmp и стабилизацию размера.
 */
export async function waitForNewDownload(
  downloadDir: string,
  before: Set<string>,
  timeoutMs = 120_000,
): Promise<string> {
  const start = Date.now();
  let candidate: string | null = null;
  while (Date.now() - start < timeoutMs) {
    const current = await listFiles(downloadDir).catch(() => []);
    const fresh = current.filter(
      (f) => !before.has(f) && !f.endsWith(".crdownload") && !f.endsWith(".tmp"),
    );
    if (fresh.length > 0) {
      candidate = fresh[fresh.length - 1];
      if (await isStable(candidate)) return candidate;
    }
    await sleep(500);
  }
  if (candidate) return candidate;
  throw new Error("Скачанный аудиофайл не появился вовремя");
}

/** Проверяет, что размер файла не меняется (загрузка завершена). */
async function isStable(file: string): Promise<boolean> {
  try {
    const s1 = (await fs.stat(file)).size;
    await sleep(600);
    const s2 = (await fs.stat(file)).size;
    return s1 === s2 && s1 > 0;
  } catch {
    return false;
  }
}

/** Снимок текущего набора файлов в директории. */
export async function snapshotDir(dir: string): Promise<Set<string>> {
  await ensureDir(dir);
  const files = await listFiles(dir).catch(() => []);
  return new Set(files);
}

/** Перемещает/переименовывает скачанный файл в целевой путь. */
export async function moveDownload(from: string, to: string): Promise<void> {
  await ensureDir(path.dirname(to));
  await fs.rename(from, to).catch(async () => {
    await fs.copyFile(from, to);
    await fs.unlink(from).catch(() => undefined);
  });
}
