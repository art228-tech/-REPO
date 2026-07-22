import fs from "node:fs/promises";
import path from "node:path";
import { listFiles } from "../util/fsUtils.js";

export interface PromptItem {
  path: string;
  name: string;
  content: string;
}

const TEXT_EXTENSIONS = [".txt", ".md", ".text"];

/**
 * Очередь промптов для дизайна голосов. Читается циклически: когда список
 * заканчивается, чтение продолжается с начала (по требованию ТЗ).
 * Промпты НЕ удаляются.
 */
export class PromptQueue {
  private items: PromptItem[] = [];
  private cursor = 0;

  constructor(private readonly dir: string) {}

  /** Загружает и читает содержимое всех файлов-промптов из папки. */
  async load(): Promise<void> {
    const files = await listFiles(this.dir, TEXT_EXTENSIONS);
    const items: PromptItem[] = [];
    for (const file of files) {
      const content = (await fs.readFile(file, "utf8")).trim();
      if (content.length === 0) continue;
      items.push({ path: file, name: path.basename(file), content });
    }
    this.items = items;
    this.cursor = 0;
  }

  get size(): number {
    return this.items.length;
  }

  isEmpty(): boolean {
    return this.items.length === 0;
  }

  /** Возвращает следующий промпт по кругу. Бросает, если список пуст. */
  next(): PromptItem {
    if (this.items.length === 0) {
      throw new Error("Папка с промптами пуста — нет ни одного непустого файла-промпта");
    }
    const item = this.items[this.cursor % this.items.length];
    this.cursor += 1;
    return item;
  }

  /** Снимок всех промптов (без сдвига курсора). */
  all(): PromptItem[] {
    return [...this.items];
  }
}
