import fs from "node:fs/promises";
import path from "node:path";
import { ensureDir, pathExists } from "../util/fsUtils.js";
import { AppConfig, defaultConfig } from "./schema.js";

/**
 * Хранилище конфигурации в JSON-файле. Пароли/токены хранятся локально,
 * так как софт запускается на машине пользователя рядом с Dolphin Anty.
 */
export class ConfigStore {
  private readonly file: string;

  constructor(dataDir: string) {
    this.file = path.join(dataDir, "config.json");
  }

  get filePath(): string {
    return this.file;
  }

  /** Загружает сохранённую конфигурацию (или дефолт, если файла нет). */
  async load(): Promise<Partial<AppConfig>> {
    if (!(await pathExists(this.file))) {
      return { ...defaultConfig };
    }
    try {
      const raw = await fs.readFile(this.file, "utf8");
      const parsed = JSON.parse(raw) as Partial<AppConfig>;
      return { ...defaultConfig, ...parsed };
    } catch {
      return { ...defaultConfig };
    }
  }

  /** Сохраняет конфигурацию на диск. */
  async save(config: Partial<AppConfig>): Promise<void> {
    await ensureDir(path.dirname(this.file));
    await fs.writeFile(this.file, JSON.stringify(config, null, 2), "utf8");
  }
}
